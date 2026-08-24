/* All fontTools work happens here, off the main thread, so the interface never
   freezes and a cancel can kill the whole thing by terminating the worker.

   The other reason this file exists: once Pyodide and its packages are loaded,
   the worker revokes its own network access. From that point the code holding
   your font physically cannot make a request, whatever it is asked to do. The
   page's CSP is the outer wall; this is the inner one. */

const PYODIDE_VERSION = '0.28.3';   // pinned on purpose -- see details.html
const PYODIDE_URL = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

/* The engine is the repository's own skill code, loaded from `scripts/` rather
   than from a copy inside `web/`. One source of truth: fix a bug in fontkit.py
   and the command line and the browser both get it. `web_build.py` is the only
   file that exists solely for the browser. */
const SKILL_MODULES = ['fontkit.py'];
const WEB_MODULES = ['web_build.py'];
const ASSETS = ['currencies.json', 'saudi-riyal.svg', 'uae-dirham.svg', 'omani-rial.svg'];

const WORK = '/work';
const OUT = '/work/out';

let py = null;
let ready = false;
let capabilities = { brotli: false, fonttools: null, pyodide: PYODIDE_VERSION };

const post = (type, payload = {}) => self.postMessage({ type, ...payload });

/* ------------------------------------------------------------- lockdown */

function severNetwork() {
  const dead = name => () => {
    throw new Error(
      `${name} is disabled: this worker gave up network access once your font was loaded.`);
  };
  // Assigning over the globals is enough -- nothing in the worker can reach the
  // originals afterwards, because the only references left are these stubs.
  try { self.fetch = dead('fetch'); } catch (e) {}
  try { self.XMLHttpRequest = dead('XMLHttpRequest'); } catch (e) {}
  try { self.WebSocket = dead('WebSocket'); } catch (e) {}
  try { self.EventSource = dead('EventSource'); } catch (e) {}
  try { self.importScripts = dead('importScripts'); } catch (e) {}
  try { if (self.navigator) self.navigator.sendBeacon = dead('sendBeacon'); } catch (e) {}
  try { self.Request = dead('Request'); } catch (e) {}
}

async function verifyLockdown() {
  // Claiming it is not the same as showing it, so prove the stub actually bites.
  // The target is a real same-origin file, relative to this worker: if the stub
  // somehow failed to take, the request succeeds and we report the truth rather
  // than a 404 that happens to look like a block.
  try {
    await self.fetch('py/web_build.py');
    return false;
  } catch (e) {
    return true;
  }
}

/* ----------------------------------------------------------------- boot */

async function boot() {
  post('boot', { pct: 5, key: 'pyodide' });
  const { loadPyodide } = await import(PYODIDE_URL + 'pyodide.mjs');
  py = await loadPyodide({ indexURL: PYODIDE_URL });

  post('boot', { pct: 45, key: 'packages' });
  // Both come from the Pyodide distribution itself, so there is no PyPI round
  // trip and one origin covers everything.
  await py.loadPackage(['fonttools', 'brotli']);

  post('boot', { pct: 75, key: 'scripts' });
  py.FS.mkdirTree(WORK);
  py.FS.mkdirTree(OUT);
  py.FS.mkdirTree('/py');
  py.FS.mkdirTree('/assets');

  for (const name of SKILL_MODULES) {
    const src = await (await fetch('../scripts/' + name)).text();
    py.FS.writeFile('/py/' + name, src);
  }
  for (const name of WEB_MODULES) {
    const src = await (await fetch('py/' + name)).text();
    py.FS.writeFile('/py/' + name, src);
  }
  for (const name of ASSETS) {
    const src = await (await fetch('../assets/' + name)).text();
    py.FS.writeFile('/assets/' + name, src);
  }

  post('boot', { pct: 88, key: 'checking:import' });
  const caps = py.runPython(`
import sys, json
sys.path.insert(0, '/py')
import fontTools
try:
    import brotli
    _brotli = True
except Exception:
    _brotli = False
import web_build
json.dumps({"fonttools": fontTools.version, "brotli": _brotli})
`);
  capabilities = { ...capabilities, ...JSON.parse(caps) };

  post('boot', { pct: 92, key: 'checking:sever' });
  severNetwork();
  post('boot', { pct: 96, key: 'checking:verify' });
  capabilities.networkSevered = await verifyLockdown();
  post('boot', { pct: 99, key: 'checking:done' });

  ready = true;
  post('ready', { capabilities });
}

/* ------------------------------------------------------------ handlers */

function writeInputs(files) {
  const paths = [];
  for (const f of files) {
    const p = `${WORK}/${f.name}`;
    py.FS.writeFile(p, new Uint8Array(f.buf));
    paths.push(p);
  }
  return paths;
}

function clearDir(dir) {
  let entries = [];
  try { entries = py.FS.readdir(dir); } catch (e) { return; }
  for (const name of entries) {
    if (name === '.' || name === '..') continue;
    const p = `${dir}/${name}`;
    const st = py.FS.stat(p);
    if (py.FS.isDir(st.mode)) { clearDir(p); try { py.FS.rmdir(p); } catch (e) {} }
    else { try { py.FS.unlink(p); } catch (e) {} }
  }
}

async function doInspect(files) {
  clearDir(WORK);
  py.FS.mkdirTree(OUT);
  const paths = writeInputs(files);
  py.globals.set('js_paths', paths);
  const out = py.runPython(`
import json, web_build
json.dumps(web_build.inspect_paths(list(js_paths)))
`);
  py.globals.delete('js_paths');
  post('inspected', { report: JSON.parse(out) });
}

async function doBuild(opts) {
  clearDir(OUT);
  py.FS.mkdirTree(OUT);

  // User-supplied artwork arrives as SVG source; fontkit reads it from a path,
  // so it lands in the worker's own filesystem and never anywhere else.
  const custom = (opts.custom_currencies || []).map((c, i) => {
    const path = `${WORK}/custom_${i}.svg`;
    py.FS.writeFile(path, c.svgText);
    return { id: c.id, name: c.name, codepoint: c.codepoint,
             latin: c.latin, arabic: c.arabic, svg: path };
  });

  const progress = (pct, key, detail) => post('progress', { pct, key, detail });
  const full = { ...opts, custom_currencies: custom,
                 out_dir: OUT, manifest: '/assets/currencies.json' };

  py.globals.set('js_opts', full);
  py.globals.set('js_progress', progress);
  const out = py.runPython(`
import json, web_build
_opts = js_opts.to_py()
_paths = _opts.pop('paths')
json.dumps(web_build.build(_paths, _opts, progress=js_progress))
`);
  py.globals.delete('js_opts');
  py.globals.delete('js_progress');

  const result = JSON.parse(out);
  const files = [];
  const transfer = [];
  for (const o of result.outputs) {
    const bytes = py.FS.readFile(o.path);
    // Copy out of the Pyodide heap, then hand ownership to the main thread so
    // nothing is duplicated across the boundary.
    const buf = bytes.slice().buffer;
    files.push({ name: o.name, kind: o.kind, bytes: o.bytes, buf });
    transfer.push(buf);
  }
  // Free the WASM-side copies now rather than at some later GC.
  clearDir(OUT);
  py.runPython('import gc; gc.collect()');

  self.postMessage({ type: 'built', result, files }, transfer);
}

/* ------------------------------------------------------------ dispatch */

self.onmessage = async (e) => {
  const msg = e.data;
  try {
    if (msg.type === 'init') {
      if (!ready) await boot();
      else post('ready', { capabilities });
      return;
    }
    if (!ready) throw new Error('worker is not ready yet');
    if (msg.type === 'inspect') return await doInspect(msg.files);
    if (msg.type === 'build') return await doBuild(msg.opts);
  } catch (err) {
    post('error', {
      stage: msg && msg.type,
      message: (err && err.message) || String(err),
      stack: (err && err.stack) || '',
    });
  }
};
