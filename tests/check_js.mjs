// app.js, worker.js and project.js are ES modules loaded with type="module",
// so `node --check` -- which assumes CommonJS for a .js file -- would reject
// their `import` statements while the browser accepts them. Parse each file
// with the same goal the browser uses.
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const MODULES = ['web/app.js', 'web/worker.js', 'web/project.js',
                 'web/pages.js', 'web/zip.js'];
const SCRIPTS = ['tests/test_contrast.js'];

let bad = 0;
const check = (file, type) => {
  try {
    execFileSync(process.execPath, [`--input-type=${type}`, '--check'],
                 { input: readFileSync(file), stdio: ['pipe', 'pipe', 'pipe'] });
    console.log(`  ok   ${file}  (${type})`);
  } catch (e) {
    console.log(`  FAIL ${file}  (${type})\n${(e.stderr || '').toString().split('\n').slice(0, 4).join('\n')}`);
    bad++;
  }
};
MODULES.forEach(f => check(f, 'module'));
SCRIPTS.forEach(f => check(f, 'commonjs'));
console.log(bad ? `${bad} file(s) failed to parse` : 'all javascript parses');
process.exit(bad ? 1 : 0);
