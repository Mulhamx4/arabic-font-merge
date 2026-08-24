/* Stage and state management. No fontTools work happens here -- that all lives
   in worker.js. This file's job is to keep exactly one stage interactive at a
   time, and to never claim something it has not measured. */

import { PROJECT, projectLinks, SKILL_FILES } from './project.js';
import { makeZip } from './zip.js';

const MB = 1048576;

/* The ladder from plan section 2. Note the third rung uses AND, not OR: the
   plan's table reads "<=10MB per file OR <=20 files", but OR would wave a
   500MB file through on a file count, which is the opposite of what the rest
   of that section is for. */
const TIERS = [
  { id: 'full',   perFile: 2 * MB,  files: 8,  preview: 'all' },
  { id: 'medium', perFile: 5 * MB,  files: 16, preview: 'three' },
  { id: 'heavy',  perFile: 10 * MB, files: 20, preview: 'none' },
];

const BUILD_TIMEOUT_MS = 90_000;
// Saving a font costs roughly 5-8x its size while tables are decompiled and
// recompiled. 8 is the pessimistic end, which is the one worth planning for.
const MEMORY_FACTOR = 8;

const SHAPING_POSITIVE = ['SAR', 'AED', 'OMR', 'sar', 'aed', 'omr'];
const SHAPING_POSITIVE_AR = ['ر.س', 'د.إ', 'ر.ع'];
const SHAPING_GUARD = ['COMRADE', 'comrade', 'SARAH', 'sarcasm', 'sardine',
                       'aedile', 'PAEDIATRIC', 'tomorrow', 'HOMER', 'Caesar'];

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  lang: 'ar',
  strings: {},
  files: [],          // {name, size, buf}
  report: null,       // inspection report
  tier: null,
  caps: null,
  build: null,        // build result
  outputs: [],        // {name, kind, bytes, buf, url}
  previewFamily: null,
  faces: [],
  renamed: false,
  worker: null,
  timer: null,
  custom: [],         // user-supplied currencies: {id,name,codepoint,latin,arabic,svg}
};

/* Unicode has encoded symbols for very few currencies. For one it has not, the
   Private Use Area is the correct home -- it exists for characters that are not
   standardised. The Currency Symbols block is NOT: Unicode may assign one of
   those codepoints to a different currency later. */
const PUA = [0xE000, 0xF8FF];
const CURRENCY_BLOCK = [0x20A0, 0x20CF];

/* --------------------------------------------------------------- helpers */

const fmtBytes = n => n >= MB ? `${(n / MB).toFixed(1)} MB`
                              : `${Math.max(1, Math.round(n / 1024))} KB`;

function t(key, params) {
  let s = state.strings[key];
  if (s === undefined) return key;
  if (params) for (const [k, v] of Object.entries(params)) s = s.split(`{${k}}`).join(v);
  return s;
}

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined) continue;
    if (v === false && !k.startsWith('aria-')) continue;
    if (k === 'class') n.className = v;
    else if (k === 'html') n.innerHTML = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k.startsWith('aria-')) n.setAttribute(k, String(v));
    else n.setAttribute(k, v === true ? '' : v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    n.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return n;
}

const clear = node => { while (node.firstChild) node.firstChild.remove(); };

/* Wrap a mixed number+unit string so RTL bidi does not reverse it. */
const ltr = text => el('span', { class: 'ltr' }, text);

/* -------------------------------------------------------------- language */

async function setLang(lang) {
  const res = await fetch(`i18n/${lang}.json`);
  state.strings = await res.json();
  state.lang = lang;
  const meta = state.strings._meta;
  document.documentElement.lang = meta.lang;
  document.documentElement.dir = meta.dir;
  localStorage.setItem('lang', lang);
  $('#lang-toggle').textContent = meta.otherLabel;
  applyStrings();
  if (state.report) renderInspection();
  if (state.build) { renderReport(); renderDownloads(); renderInstall(); }
}

function applyStrings() {
  for (const node of $$('[data-i18n]')) {
    const v = state.strings[node.dataset.i18n];
    if (v !== undefined) node.textContent = v;
  }
  for (const node of $$('[data-i18n-html]')) {
    const v = state.strings[node.dataset.i18nHtml];
    if (v !== undefined) node.innerHTML = v;
  }
  document.title = t('intro.title');
  renderAbout();
}

function renderAbout() {
  const by = $('#about-by');
  if (by) by.innerHTML = t('about.by', { d: PROJECT.author });
  const host = $('#project-links');
  if (!host) return;
  clear(host);
  for (const l of projectLinks(state.lang)) {
    host.append(el('a', { href: l.href, target: '_blank', rel: 'noopener noreferrer' },
                   l.ltr ? ltr(l.label) : l.label));
  }
}

/* ----------------------------------------------------------------- theme */

function setTheme(mode) {
  const root = document.documentElement;
  if (mode === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', mode);
  localStorage.setItem('theme', mode);
  const dark = mode === 'dark' ||
    (mode === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
  // The label names the current mode; the accessible name says what a click
  // does, because "Dark" on a button is ambiguous on its own.
  $('#theme-toggle span').textContent = dark ? t('theme.dark') : t('theme.light');
  $('#theme-toggle').setAttribute('aria-label',
    t('theme.switchTo', { d: dark ? t('theme.light') : t('theme.dark') }));
}

function setEngineStatus(stateName, text) {
  const node = $('#engine-status');
  if (!node) return;
  node.dataset.state = stateName;
  node.textContent = text;
}

/* ---------------------------------------------------------------- stages */

function stage(n) { return $(`#stage-${n}`); }

function openStage(n) {
  for (let i = 1; i <= 5; i++) {
    const s = stage(i);
    if (i < n) { if (s.dataset.state !== 'locked') s.dataset.state = 'done'; }
    else if (i === n) s.dataset.state = 'active';
    else if (s.dataset.state !== 'done') s.dataset.state = 'locked';
  }
  const target = stage(n);
  if (target.getBoundingClientRect().top < 0) {
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function summarise(n, text) { $(`#s${n}-summary`).textContent = text; }

/* ------------------------------------------------------- stage 1: upload */

function pickTier(files) {
  const biggest = Math.max(...files.map(f => f.size));
  for (const tier of TIERS) {
    if (biggest <= tier.perFile && files.length <= tier.files) return tier;
  }
  return null;
}

function memoryVerdict(totalBytes) {
  const need = totalBytes * MEMORY_FACTOR;
  const limit = performance.memory && performance.memory.jsHeapSizeLimit;
  if (!limit) return { known: false, need };
  return { known: true, need, limit, tight: need > limit * 0.7 };
}

async function onFiles(fileList) {
  const files = [...fileList].filter(f => /\.(ttf|otf)$/i.test(f.name));
  if (!files.length) {
    renderNote('#s1-out', 'bad', t('err.noFiles'));
    return;
  }
  const tier = pickTier(files);
  const total = files.reduce((a, f) => a + f.size, 0);
  if (!tier) {
    renderRejection(files, total);
    return;
  }
  state.tier = tier;

  clear($('#s1-out'));
  $('#s1-next').hidden = true;
  state.custom = [];
  $('#s1-out').append(el('p', { class: 'num', style: 'color:var(--ink-faint)' },
                          t('s1.reading')));

  state.files = await Promise.all(files.map(async f => ({
    name: f.name, size: f.size, buf: await f.arrayBuffer(),
  })));

  await ensureWorker();
  send('inspect', { files: state.files.map(f => ({ name: f.name, buf: f.buf })) });
}

function renderRejection(files, total) {
  const out = $('#s1-out');
  clear(out);
  const biggest = fmtBytes(Math.max(...files.map(f => f.size)));
  out.append(
    el('div', { class: 'note bad' }, el('span', {}, el('p', {},
      t('s1.tierReject', { d: `${files.length} x ${biggest}` })))),
    el('p', {},
      el('a', { class: 'btn secondary', href: 'details.html#local' },
         t('s1.localTools')),
      el('small', { style: 'display:block;margin-block-start:.5rem;color:var(--ink-faint)' },
         t('s1.localToolsWhy'))));
}

function renderNote(sel, kind, html) {
  const host = $(sel);
  clear(host);
  host.append(el('div', { class: `note ${kind}` }, el('span', { html })));
}

function renderInspection() {
  const r = state.report;
  const out = $('#s1-out');
  clear(out);

  const head = ['s1.tableFile', 's1.tableStyle', 's1.tableWeight', 's1.tableItalic',
                's1.tableGlyphs', 's1.tableArabic', 's1.tableFormat', 's1.tableSize'];
  const table = el('table', { class: 'tbl' },
    el('thead', {}, el('tr', {}, head.map(k => el('th', {}, t(k))))),
    el('tbody', {}, r.faces.map(f => el('tr', {},
      el('td', { class: 'name' }, f.file),
      el('td', {}, f.style),
      el('td', { class: 'num' }, f.weight),
      el('td', {}, f.italic ? t('s1.yes') : t('s1.no')),
      el('td', { class: 'num' }, f.glyphs.toLocaleString('en')),
      el('td', { class: 'num' }, f.arabic_letters || t('s1.no')),
      el('td', {}, el('span', { class: 'pill' }, f.format),
                   f.variable ? el('span', { class: 'pill warn',
                                             style: 'margin-inline-start:.3rem' },
                                   t('s1.variable')) : null),
      el('td', { class: 'num' }, ltr(fmtBytes(f.bytes)))))));
  out.append(el('div', { class: 'scroll-x' }, table));

  if (r.unreadable && r.unreadable.length) {
    out.append(el('div', { class: 'note warn' },
      el('span', {}, t('s1.unreadable', { n: r.unreadable.length }))));
  }

  if (r.route === 'blocked') {
    // The journey ends here, so the reason has to be here too -- stage 2 is
    // where this text used to live, and stage 2 is now unreachable.
    out.append(
      el('div', { class: 'note bad' }, el('span', { html: t('s2.blocked') })),
      el('p', { style: 'color:var(--ink-faint);font-size:.85rem' },
         t('s2.blockedFiles', { d: r.blocked_files.join(', ') })),
      el('p', {}, el('a', { class: 'btn secondary', href: 'details.html#local' },
                     t('s1.localTools'))));
  } else {
    const routeKind = r.route === 'symbols-only' ? 'warn' : 'ok';
    const routeKey = r.route === 'symbols-only' ? 's1.routeSymbols' : 's1.routeMerge';
    out.append(el('div', { class: `note ${routeKind}` }, el('span', { html: t(routeKey) })));
  }

  for (const w of r.warnings) {
    const map = {
      mixed_upem: ['bad', 's1.warnMixedUpem'],
      italics_without_arabic: ['info', 's1.warnItalicsNoArabic'],
      cff2: ['bad', 's1.warnCff2'],
    }[w.kind];
    if (!map) continue;
    out.append(el('div', { class: `note ${map[0]}` },
      el('span', {}, t(map[1], { d: Array.isArray(w.detail) ? w.detail.join(', ') : w.detail }))));
  }
  if (r.name_problems.length && r.route !== 'blocked') {
    out.append(el('div', { class: 'note info' },
      el('span', {}, t('s1.warnNames', { n: r.name_problems.length }))));
  }

  // No point discussing build capacity for a file that will never be built.
  if (r.route !== 'blocked') {
    const tierKey = { full: 's1.tierFull', medium: 's1.tierMedium', heavy: 's1.tierHeavy' }[state.tier.id];
    const mem = memoryVerdict(r.total_bytes);
    out.append(el('div', { class: `note ${mem.tight ? 'warn' : 'info'}` },
      el('span', {}, t(tierKey), ' ',
         mem.known ? ltr(`(${fmtBytes(mem.need)} / ${fmtBytes(mem.limit)})`) : '')));
  }

  summarise(1, t('s1.summary', { n: r.faces.length, family: r.family_root }));

  // Deliberately NOT auto-advancing. The inspection table is stage 1's whole
  // output, and collapsing the stage the moment it arrives would mean nobody
  // ever reads it.
  const next = $('#s1-next');
  next.hidden = r.route === 'blocked';
  next.onclick = () => { renderConsent(); openStage(2); };
}

/* ------------------------------------------------------ stage 2: consent */

function renderConsent() {
  const r = state.report;

  // "the user agrees while looking at their font's name and its inspection
  // result, not a blind page before they start" -- plan section 3b.
  $('#s2-recap').textContent = t('s2.recap', {
    n: r.faces.length,
    family: r.family_root,
    route: t(r.route === 'symbols-only' ? 's2.routeSymbolsShort' : 's2.routeMergeShort'),
  });

  const host = $('#s2-license');
  clear(host);

  if (r.blocked_files.length) {
    host.append(
      el('div', { class: 'note bad' }, el('span', { html: t('s2.blocked') })),
      el('p', { style: 'color:var(--ink-faint);font-size:.85rem' },
         t('s2.blockedFiles', { d: r.blocked_files.join(', ') })),
      el('p', {}, el('a', { class: 'btn secondary', href: 'details.html#local' },
                     t('s1.localTools'))));
    $('#s2-consent').hidden = true;
    return;
  }
  $('#s2-consent').hidden = false;

  const lic = r.faces.find(f => f.license.present);
  if (lic) {
    host.append(
      el('p', { style: 'font-size:.85rem;color:var(--ink-faint);margin-block-end:.25rem' },
         t('s2.licenseFound')),
      el('blockquote', {
        style: 'margin:0 0 .75rem;padding:.7rem .9rem;background:var(--bg-sunken);' +
               'border-radius:8px;font-size:.85rem;color:var(--ink-muted)',
      }, lic.license.description || lic.license.url));
  } else {
    host.append(el('div', { class: 'note info' }, el('span', {}, t('s2.licenseNone'))));
  }
  if (r.ofl) {
    host.append(el('div', { class: `note ${r.rename_required ? 'warn' : 'info'}` },
      el('span', {
        html: r.rename_required
          ? t('s2.oflRfnNotice', { d: r.reserved_names.join('، ') })
          : t('s2.oflNotice'),
      })));
  }

  const pts = $('#s2-points');
  clear(pts);
  for (const k of ['s2.point1', 's2.point2', 's2.point3']) pts.append(el('li', {}, t(k)));

  $('#agree').checked = false;
  $('#s2-next').disabled = true;
}

/* ------------------------------------------------------ stage 3: options */

/* `ratio` is the artwork's viewBox aspect, so the masked span keeps the
   official proportions instead of being squashed into a square. */
const CURRENCIES = [
  { id: 'saudi-riyal', cp: 0x20C1, latin: 'SAR', ar: 'ر.س',
    name: 'Saudi Riyal', name_ar: 'ريال سعودي', svg: 'saudi-riyal.svg', ratio: 0.895 },
  { id: 'uae-dirham',  cp: 0x20C3, latin: 'AED', ar: 'د.إ',
    name: 'UAE Dirham',  name_ar: 'درهم إماراتي', svg: 'uae-dirham.svg', ratio: 1.149 },
  { id: 'omani-rial',  cp: 0x20C4, latin: 'OMR', ar: 'ر.ع',
    name: 'Omani Rial',  name_ar: 'ريال عماني', svg: 'omani-rial.svg', ratio: 1.874 },
];

/* The official mark, drawn from its own artwork rather than from a font. */
const symbolMark = (c, em = 1) => el('span', {
  class: 'sym',
  role: 'img',
  'aria-label': c.name,
  style: `--sym:url("assets/${c.svg}");block-size:${em}em;inline-size:${(em * c.ratio).toFixed(3)}em`,
});

/* Flow arrows must follow the reading direction, not the glyph we happen to
   have typed. */
const flowArrow = () => (state.strings._meta.dir === 'rtl' ? '←' : '→');

function renderOptions() {
  const r = state.report;

  const routeHost = $('#s3-route');
  clear(routeHost);
  if (r.route === 'symbols-only') {
    routeHost.append(el('div', { class: 'note warn' },
      el('span', { html: t('s1.routeSymbols') })));
  }

  const cards = $('#currency-cards');
  clear(cards);
  for (const c of CURRENCIES) {
    cards.append(el('label', { class: 'card' },
      el('span', { class: 'card-head' },
        el('input', { type: 'checkbox', 'data-currency': c.id, checked: true }),
        el('b', {}, state.lang === 'ar' ? c.name_ar : c.name)),
      el('span', { class: 'demo' },
        el('span', {}, `${c.latin} · ${c.ar}`),
        el('span', { class: 'arrow' }, flowArrow()),
        symbolMark(c, 1.3)),
      el('small', {}, `U+${c.cp.toString(16).toUpperCase()} · ${t('s3.symbolNote')}`)));
  }

  const feats = $('#feature-cards');
  clear(feats);
  feats.append(el('label', { class: 'card' },
    el('span', { class: 'card-head' },
      el('input', { type: 'checkbox', id: 'opt-shortcuts', checked: true }),
      el('b', {}, t('s3.shortcuts'))),
    el('span', { class: 'demo' },
      el('span', { class: 'ltr' }, 'OMR 5'),
      el('span', { class: 'arrow' }, flowArrow()),
      el('span', { class: 'ltr' }, symbolMark(CURRENCIES[2], 1.2), ' 5')),
    el('small', {}, t('s3.shortcutsSub'))));

  if (r.can_graft_arabic && r.route === 'merge') {
    feats.append(el('label', { class: 'card' },
      el('span', { class: 'card-head' },
        el('input', { type: 'checkbox', id: 'opt-graft', checked: true }),
        el('b', {}, t('s3.graft'))),
      el('small', {}, t('s3.graftSub'))));
  }

  const brotli = state.caps && state.caps.brotli;
  feats.append(el('label', { class: 'card' },
    el('span', { class: 'card-head' },
      el('input', { type: 'checkbox', id: 'opt-woff2', disabled: !brotli }),
      el('b', {}, t('s3.woff2'))),
    el('small', {}, brotli ? t('s3.woff2Sub') : t('s3.woff2Unavailable'))));

  /* Renaming has three states, and only one of them is a licence obligation:
       - OFL with a declared Reserved Font Name -> required (clause 3)
       - OFL with no reserved name              -> optional; nothing obliges it
       - any other licence                      -> optional
     The required case is still overridable, because clause 3 carves out its
     own exception for written permission from the copyright holder -- and
     because reserved-name detection reads prose and can be wrong. */
  const renameField = $('#rename-field');
  renameField.hidden = false;
  const input = $('#rename');
  const overrideRow = $('#rename-override-row');
  const override = $('#rename-override');
  overrideRow.hidden = !r.rename_required;
  if (!r.rename_required) override.checked = false;
  input.placeholder = r.rename_required ? 'ZMKN' : '';
  const hint = $('#rename-hint');
  const overrideNote = $('#rename-override-note');
  const updateHint = () => {
    const skipping = r.rename_required && override.checked;
    const suffix = input.value.trim();
    input.required = r.rename_required && !skipping;
    input.disabled = skipping;
    const base = r.family_root + (suffix ? ' ' + suffix : '');
    // Mirrors _renamed_ps_name in web_build.py: the PostScript name is built
    // from the OLD one, because the display family may be Arabic while
    // nameID 6 is ASCII by spec.
    const asciiSuffix = suffix.replace(/[^A-Za-z0-9\-_.]/g, '');
    const oldPs = (r.faces[0] && r.faces[0].ps_name) || '';
    const [fam, ...rest] = oldPs.split('-');
    const newPs = oldPs ? `${fam}${asciiSuffix}-${rest.join('-') || 'Regular'}` : '';
    // A suffix with no ASCII at all cannot reach the PostScript name, so the
    // reserved name would survive and an OFL rename would be rename in name only.
    const usable = !suffix || /[A-Za-z0-9]/.test(suffix);

    const lines = [
      r.rename_required ? t('s3.renameHintRfn', { d: r.reserved_names.join('، ') })
        : r.ofl ? t('s3.renameHintOflNoRfn')
        : t('s3.renameHintFree'),
    ];
    if (suffix && !skipping) {
      lines.push(t('s3.renameResult', { d: base }));
      if (usable && newPs) lines.push(t('s3.renamePs', { d: newPs }));
    }
    if (suffix && !usable && !skipping) lines.push(`<b>${t('s3.renameNeedsAscii')}</b>`);
    hint.innerHTML = lines.join('<br>');

    clear(overrideNote);
    if (skipping) {
      overrideNote.append(el('div', { class: 'note warn' },
        el('span', { html: t('s3.renameOverrideOn', { d: r.reserved_names.join('، ') }) })));
    }

    $('#build').disabled =
      (r.rename_required && !skipping && !suffix) ||
      (!!suffix && !usable && !skipping);
  };
  input.oninput = updateHint;
  override.onchange = updateHint;
  updateHint();

  const fmt = $('#format');
  clear(fmt);
  const opts = r.route === 'symbols-only'
    ? [['single', 's3.formatSingle']]
    : [['auto', 's3.formatAuto'], ['ttc', 's3.formatTtc'],
       ['otc', 's3.formatOtc'], ['single', 's3.formatSingle']];
  for (const [v, k] of opts) fmt.append(el('option', { value: v }, t(k)));
  const hintFor = { ttc: 's3.formatHintTtc', otc: 's3.formatHintOtc', single: 's3.formatHintSingle' };
  fmt.onchange = () => {
    const k = hintFor[fmt.value];
    $('#format-hint').textContent = k ? t(k) : '';
  };
  fmt.onchange();

  renderCustomList();

  const last = parseFloat(localStorage.getItem('lastVersion') || '2.000');
  $('#version').value = (last + 0.001).toFixed(3);
}

/* ------------------------------------------------ user-supplied currencies */

function nextFreeCodepoint() {
  const used = new Set([
    ...CURRENCIES.map(c => c.cp),
    ...state.custom.map(c => c.codepoint),
  ]);
  for (let cp = PUA[0]; cp <= PUA[1]; cp++) if (!used.has(cp)) return cp;
  return PUA[0];
}

function codepointHint(cp) {
  if (cp >= PUA[0] && cp <= PUA[1]) return ['info', t('s3.customCpHintPua')];
  if (cp >= CURRENCY_BLOCK[0] && cp <= CURRENCY_BLOCK[1])
    return ['warn', t('s3.customCpHintCurrency')];
  return ['warn', t('s3.customCpHintOther')];
}

function renderCustomList() {
  const host = $('#custom-currencies');
  clear(host);
  if (!state.custom.length) return;
  const list = el('div', { class: 'custom-list' });
  for (const c of state.custom) {
    list.append(el('div', { class: 'custom-item' },
      el('span', { class: 'preview' },
         el('img', { src: c.dataUrl, alt: '', width: 28, height: 28 })),
      el('span', {},
        el('b', {}, c.name),
        el('span', { class: 'meta', style: 'display:block' },
           ltr(`U+${c.codepoint.toString(16).toUpperCase()}`
               + (c.latin.length ? ` · ${c.latin.join(' ')}` : '')
               + (c.arabic.length ? ` · ${c.arabic.join(' ')}` : '')))),
      el('button', { type: 'button', onclick: () => {
        state.custom = state.custom.filter(x => x.id !== c.id);
        renderCustomList();
        if (state.build) renderWeightsPanelIfReady();
      } }, t('s3.customRemove'))));
  }
  host.append(list);
}

function openCustomForm() {
  const host = $('#custom-form-host');
  clear(host);

  let svgText = null, dataUrl = null, svgName = null;

  const drop = el('label', { class: 'svg-drop' },
    el('span', { class: 'preview' }, el('span', { id: 'svg-preview' }, '—')),
    el('span', { class: 'label' },
       el('span', { id: 'svg-label' }, t('s3.customSvgPick')),
       el('small', {}, t('s3.customSvgNeed'))),
    el('input', { type: 'file', accept: '.svg,image/svg+xml', class: 'sr-only',
                  id: 'svg-input' }));

  const nameInput = el('input', { type: 'text', id: 'cc-name',
                                  placeholder: t('s3.customNamePh') });
  const cpInput = el('input', { type: 'text', id: 'cc-cp', spellcheck: 'false',
                                value: nextFreeCodepoint().toString(16).toUpperCase() });
  const latinInput = el('input', { type: 'text', id: 'cc-latin', placeholder: 'KWD',
                                   spellcheck: 'false' });
  const arabicInput = el('input', { type: 'text', id: 'cc-arabic', placeholder: 'د.ك' });
  const cpHint = el('small', { id: 'cc-cp-hint' });
  const error = el('div', {});

  const refreshCpHint = () => {
    const cp = parseInt(cpInput.value.replace(/^(u\+|0x)/i, ''), 16);
    clear(cpHint);
    if (!Number.isFinite(cp)) return;
    const [level, text] = codepointHint(cp);
    cpHint.innerHTML = text;
    cpHint.style.color = level === 'warn' ? 'var(--warn)' : 'var(--ink-faint)';
  };
  cpInput.oninput = refreshCpHint;

  const form = el('div', { class: 'custom-form' },
    el('h4', {}, t('s3.addCurrency')),
    el('p', {}, t('s3.addCurrencySub')),
    el('div', { class: 'note warn' }, el('span', { html: t('s3.customLegal') })),
    el('div', { class: 'field' }, el('label', { for: 'cc-name' }, t('s3.customName')), nameInput),
    el('div', { class: 'field' },
       el('label', {}, t('s3.customSvg')), drop),
    el('div', { class: 'row' },
      el('div', { class: 'field' },
         el('label', { for: 'cc-cp' }, t('s3.customCp')),
         el('div', { style: 'display:flex;align-items:center;gap:.4rem' },
            el('span', { style: 'color:var(--ink-faint);font-size:.9rem' }, 'U+'), cpInput),
         cpHint),
      el('div', { class: 'field' },
         el('label', { for: 'cc-latin' }, t('s3.customLatin')), latinInput),
      el('div', { class: 'field' },
         el('label', { for: 'cc-arabic' }, t('s3.customArabic')), arabicInput)),
    error,
    el('div', { class: 'custom-actions' },
      el('button', { class: 'btn', type: 'button', id: 'cc-add' }, t('s3.customAdd')),
      el('button', { class: 'btn secondary', type: 'button',
                     onclick: () => clear(host) }, t('s3.customCancel'))));

  host.append(form);

  $('#svg-input').onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    svgText = await file.text();
    svgName = file.name;
    dataUrl = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgText)));
    const prev = $('#svg-preview');
    clear(prev);
    prev.append(el('img', { src: dataUrl, alt: '', width: 30, height: 30 }));
    $('#svg-label').textContent = file.name;
    drop.classList.add('has-file');
  };

  $('#cc-add').onclick = () => {
    clear(error);
    const fail = msg => error.append(el('div', { class: 'note bad' }, el('span', {}, msg)));
    if (!svgText) return fail(t('s3.customNeedSvg'));
    if (!/viewBox\s*=/.test(svgText)) return fail(t('s3.customSvgNeed'));
    const name = nameInput.value.trim();
    if (!name) return fail(t('s3.customNeedName'));
    const cp = parseInt(cpInput.value.replace(/^(u\+|0x)/i, ''), 16);
    if (!Number.isFinite(cp) || cp <= 0 || cp > 0x10FFFF) return fail(t('s3.customBadCp'));
    if (state.custom.some(c => c.codepoint === cp) || CURRENCIES.some(c => c.cp === cp))
      return fail(t('s3.customDupCp'));

    state.custom.push({
      id: 'custom-' + cp.toString(16),
      name, codepoint: cp,
      latin: latinInput.value.trim() ? [latinInput.value.trim()] : [],
      arabic: arabicInput.value.trim() ? [arabicInput.value.trim()] : [],
      svgText, svgName, dataUrl,
    });
    clear(host);
    renderCustomList();
  };

  refreshCpHint();
  nameInput.focus();
}

function renderWeightsPanelIfReady() {
  if (!state.faces.length) return;
  const weights = [...new Set(state.faces.map(f => f.weight))].sort((a, b) => a - b);
  renderWeightsPanel(weights);
}

function collectOptions() {
  const r = state.report;
  const chosen = $$('[data-currency]').filter(i => i.checked).map(i => i.dataset.currency);
  const skipping = $('#rename-override') && $('#rename-override').checked
    && !$('#rename-override-row').hidden;
  const suffix = skipping ? '' : $('#rename').value.trim();
  state.renamed = !!suffix;
  return {
    paths: state.files.map(f => `/work/${f.name}`),
    route: r.route,
    version: $('#version').value,
    rename_suffix: suffix,
    currencies: chosen,          // always a list; [] genuinely means none
    shortcuts: $('#opt-shortcuts').checked,
    arabic_graft: $('#opt-graft') ? $('#opt-graft').checked : false,
    format: $('#format').value,
    woff2: $('#opt-woff2') ? $('#opt-woff2').checked : false,
    custom_currencies: state.custom.map(c => ({
      id: c.id, name: c.name, codepoint: c.codepoint,
      latin: c.latin, arabic: c.arabic, svgText: c.svgText,
    })),
  };
}

/* --------------------------------------------------- stage 4: build flow */

function startBuild() {
  const opts = collectOptions();
  localStorage.setItem('lastVersion', opts.version);
  summarise(3, t('s3.summary', {
    n: opts.currencies.length + state.custom.length,
    fmt: opts.format + (opts.woff2 ? ' + woff2' : ''),
  }));

  openStage(4);
  $('#build-progress').hidden = false;
  $('#preview-area').hidden = true;
  $('#verify-area').hidden = true;
  setProgress(0, t('s3.building'));

  state.timer = setTimeout(() => {
    hardStopWorker();
    showBuildFailure(t('s4.timeout', { n: BUILD_TIMEOUT_MS / 1000 }));
  }, BUILD_TIMEOUT_MS);

  send('build', { opts });
}

function setProgress(pct, label) {
  $('#progress-fill').style.inlineSize = `${pct}%`;
  $('#progress-pct').textContent = `${Math.round(pct)}%`;
  $('#progress-label').textContent = label;
  $('#progress-sr').textContent = `${label} ${Math.round(pct)}%`;
}

const PROGRESS_LABELS = {
  face: 'building', graft: 'copying Arabic', symbols: 'adding symbols',
  shortcuts: 'adding shortcuts', outlines: 'converting outlines',
  collection: 'writing the collection', woff2: 'compressing for the web', done: 'done',
};

function showBuildFailure(msg) {
  $('#build-progress').hidden = true;
  $('#preview-area').hidden = true;
  $('#verify-area').hidden = false;
  const host = $('#report');
  clear(host);
  host.append(el('div', { class: 'report-row fail' },
    el('span', { class: 'who' }, msg)));
  $('#to-download').hidden = true;
}

async function onBuilt(result, files) {
  clearTimeout(state.timer);
  state.build = result;
  state.outputs = files.map(f => ({ ...f, url: URL.createObjectURL(new Blob([f.buf])) }));

  $('#build-progress').hidden = true;
  await setUpPreview();
  renderReport();
  $('#verify-area').hidden = false;
  $('#to-download').hidden = false;
  summarise(4, t('s4.summary', {
    n: result.faces.length,
    v: result.failures ? t('s4.fail') : t('s4.pass'),
  }));
  renderDownloads();
  renderInstall();
}

/* ------------------------------------------------------------ preview */

async function setUpPreview() {
  const previewable = state.tier.preview !== 'none';
  $('#preview-area').hidden = !previewable;
  if (!previewable) {
    renderNote('#s3-route', 'info', t('s4.noPreview'));
    state.faces = [];
    return;
  }

  // A random family name, never the font's real one. A same-named font already
  // installed on the machine would otherwise win the lookup and we would be
  // previewing the OLD font while every number on screen said PASS.
  state.previewFamily = 'PF_' + Math.random().toString(36).slice(2, 8);

  let faces = state.build.faces
    .map(f => ({ ...f, out: state.outputs.find(o => o.name === f.file) }))
    .filter(f => f.out)
    .sort((a, b) => a.weight - b.weight || a.italic - b.italic);

  if (state.tier.preview === 'three' && faces.length > 3) {
    faces = [faces[0], faces[Math.floor(faces.length / 2)], faces[faces.length - 1]];
  }

  for (const f of faces) {
    const face = new FontFace(state.previewFamily, `url(${f.out.url})`, {
      weight: String(f.weight),
      style: f.italic ? 'italic' : 'normal',
    });
    await face.load();
    document.fonts.add(face);
  }
  state.faces = faces;

  const text = $('#preview-text');
  text.setAttribute('dir', 'auto');
  text.style.fontFamily = `'${state.previewFamily}'`;
  if (!text.value) text.value = t('sample.all');

  const weights = [...new Set(faces.map(f => f.weight))].sort((a, b) => a - b);
  const slider = $('#weight-slider');
  slider.max = String(weights.length - 1);
  slider.value = String(Math.min(weights.indexOf(400) < 0 ? 0 : weights.indexOf(400),
                                 weights.length - 1));
  const applyWeight = () => {
    const w = weights[Number(slider.value)];
    text.style.fontWeight = String(w);
    $('#weight-label').textContent = String(w);
  };
  slider.oninput = applyWeight;
  applyWeight();

  const size = $('#size-slider');
  const applySize = () => { text.style.fontSize = `${size.value}px`; };
  size.oninput = applySize;
  applySize();

  const samples = $('#samples');
  clear(samples);
  for (const k of ['sample.all', 'sample.amount', 'sample.mixed',
                   'sample.tashkeel', 'sample.protected']) {
    samples.append(el('button', { type: 'button', onclick: () => { text.value = t(k); } },
                      t(k)));
  }

  renderWeightsPanel(weights);
}

function renderWeightsPanel(weights) {
  const grid = $('#weights-grid');
  clear(grid);
  const shown = weights.length > 1 ? [weights[0], weights[weights.length - 1]] : weights;
  const chosen = $$('[data-currency]').filter(i => i.checked).map(i => i.dataset.currency);
  const syms = [
    ...CURRENCIES.filter(c => chosen.includes(c.id)),
    ...state.custom.map(c => ({ ...c, cp: c.codepoint, latin: c.latin[0] || c.name,
                                name_ar: c.name })),
  ];
  for (const c of syms) {
    grid.append(el('div', { class: 'weight-pair' },
      shown.map(w => el('div', { class: 'weight-cell' },
        el('span', {
          class: 'glyph',
          style: `font-family:'${state.previewFamily}';font-weight:${w}`,
        }, String.fromCodePoint(c.cp)),
        el('span', { class: 'label num' }, ltr(String(w))))),
      el('span', { class: 'caption' }, state.lang === 'ar' ? c.name_ar : c.name)));
  }
}

/* ------------------------------------------------ browser-side shaping */

function measure(text, calt, family, weight = 400) {
  const s = el('span', {
    style: `position:absolute;visibility:hidden;white-space:pre;font-size:64px;` +
           `font-family:'${family}';font-weight:${weight};` +
           `font-feature-settings:"calt" ${calt ? 1 : 0}`,
  }, text);
  document.body.append(s);
  const w = s.getBoundingClientRect().width;
  s.remove();
  return w;
}

/* Does calt actually fire, in this browser, on this file? The width of a run
   with calt on and off differs only if a substitution happened -- which tests
   the real shaping engine rather than a library's opinion of it. */
function probeShaping() {
  if (!state.previewFamily || !state.faces.length) return null;
  const fam = state.previewFamily;
  const hasArabic = state.build.faces.some(f => f.verify.arabic_after > 0);
  const chosen = $$('[data-currency]').filter(i => i.checked).map(i => i.dataset.currency);
  const active = CURRENCIES.filter(c => !chosen.length || chosen.includes(c.id));
  const latin = SHAPING_POSITIVE.filter(s =>
    active.some(c => c.latin.toLowerCase() === s.toLowerCase()));
  const arabic = hasArabic
    ? SHAPING_POSITIVE_AR.filter(s => active.some(c => c.ar === s)) : [];
  // Whatever shortcuts the user defined get probed the same way.
  const customShortcuts = state.custom.flatMap(c =>
    [...c.latin, ...(hasArabic ? c.arabic : [])]);
  const positive = [...latin, ...arabic, ...customShortcuts];

  const differs = s => Math.abs(measure(s, true, fam) - measure(s, false, fam)) > 0.5;
  const fired = positive.filter(differs).length;
  const guarded = SHAPING_GUARD.filter(s => !differs(s)).length;
  return { fired, total: positive.length, guarded, guardTotal: SHAPING_GUARD.length };
}

/* -------------------------------------------------------------- report */

const FINDING_TEXT = {
  codepoints_lost: f => t('s4.findCodepointsLost', { n: f.count, d: f.sample.join(' ') }),
  symbol_missing: f => t('s4.findSymbolMissing', { d: f.sample.join(' ') }),
  arabic_lost: f => t('s4.findArabicLost', { n: f.count }),
  advance_mismatch_new: f => t('s4.findAdvanceNew', { n: f.count }),
  gsub_features_lost: f => t('s4.findFeaturesLost', { d: f.sample.join(' ') }),
  advance_mismatch_pre_existing: f => t('s4.findAdvancePre', { n: f.count }),
};

function renderReport() {
  const host = $('#report');
  clear(host);

  for (const face of state.build.faces) {
    const fails = face.verify.findings.filter(f => f.level === 'fail');
    const bits = [];
    if (face.symbols) bits.push(t('s4.symbolsAdded', { n: face.symbols }));
    if (face.shortcuts) bits.push(t('s4.shortcutsAdded', { n: face.shortcuts }));
    if (face.grafted) bits.push(t('s4.grafted'));
    if (face.variable_fix.applied) bits.push(t('s4.vfFixed'));
    bits.push(t('s4.glyphs', { a: face.verify.glyphs_before, b: face.verify.glyphs_after }));

    host.append(el('div', { class: `report-row ${fails.length ? 'fail' : 'pass'}` },
      el('span', { class: 'pill ' + (fails.length ? 'bad' : 'ok') },
         fails.length ? t('s4.fail') : t('s4.pass')),
      el('span', { class: 'who' }, face.face),
      el('span', { class: 'what' }, bits.join(' · '))));

    for (const f of face.verify.findings) {
      const text = FINDING_TEXT[f.kind];
      if (!text) continue;
      if (f.level === 'note' || f.level === 'warn') {
        host.append(el('div', { class: 'report-row note' },
          el('span', { class: 'pill' }, t('s4.noteLevel')),
          el('span', { class: 'what' }, text(f))));
      } else {
        host.append(el('div', { class: 'report-row fail' },
          el('span', { class: 'what' }, text(f))));
      }
    }
  }

  for (const item of (state.build.custom_problems || [])) {
    const detail = item.problems.map(p => ({
      codepoint_taken: () => t('err.cpTaken',
        { d: (p.codepoint || 0).toString(16).toUpperCase() }),
      codepoint_invalid: () => t('err.cpInvalid'),
      codepoint_surrogate: () => t('err.cpSurrogate'),
      codepoint_duplicate: () => t('s3.customDupCp'),
      svg_no_viewbox: () => t('err.svgNoViewbox'),
      svg_viewbox_empty: () => t('err.svgNoViewbox'),
      svg_missing: () => t('err.svgMissing'),
    }[p.kind] || (() => p.kind))()).join(' · ');
    host.append(el('div', { class: 'report-row fail' },
      el('span', { class: 'pill bad' }, t('s4.fail')),
      el('span', { class: 'who' }, item.id),
      el('span', { class: 'what' }, t('err.customRejected', { d: detail }))));
  }

  const shaping = probeShaping();
  if (shaping) {
    const ok = shaping.fired === shaping.total && shaping.guarded === shaping.guardTotal;
    host.append(el('div', { class: `report-row ${ok ? 'pass' : 'fail'}` },
      el('span', { class: 'pill ' + (ok ? 'ok' : 'bad') }, ok ? t('s4.pass') : t('s4.fail')),
      el('span', { class: 'who' },
         t('s4.shapingFired', { a: shaping.fired, b: shaping.total })),
      el('span', { class: 'what' },
         t('s4.shapingGuard', { a: shaping.guarded, b: shaping.guardTotal }))));
    host.append(el('div', { class: 'report-row note' },
      el('span', { class: 'what' }, t('s4.shapingHow'))));
  }
}

/* ------------------------------------------------------ stage 5: output */

const KIND_LABEL = { collection: 's5.collection', face: 's5.face', woff2: 's5.woff2', css: 's5.css' };

function download(name, url) {
  const a = el('a', { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
}

function renderDownloads() {
  const host = $('#downloads');
  clear(host);
  for (const o of state.outputs) {
    host.append(el('button', {
      class: 'dl', type: 'button', onclick: () => download(o.name, o.url),
    },
      el('span', {},
        el('span', { class: 'kind', style: 'display:block' }, t(KIND_LABEL[o.kind] || 's5.face')),
        el('span', { class: 'meta' }, o.name)),
      el('span', { class: 'size num' }, ltr(fmtBytes(o.bytes)))));
  }

  const warn = $('#conflict-warning');
  clear(warn);
  if (state.renamed) {
    warn.append(el('div', { class: 'note ok' }, el('span', {}, t('s5.conflictRenamed'))));
  } else {
    warn.append(el('div', { class: 'note warn' },
      el('span', { html: t('s5.conflict', { d: state.build.ps_names.slice(0, 3).join(', ') }) })));
  }
  warn.append(el('div', { class: 'note info' }, el('span', {}, t('s5.codepointNote'))));

  summarise(5, t('s5.summary', { n: state.outputs.length }));
}

function guessOS() {
  const ua = navigator.userAgent;
  if (/Windows/i.test(ua)) return 'windows';
  if (/Mac OS X|Macintosh/i.test(ua)) return 'mac';
  if (/Linux|X11/i.test(ua)) return 'linux';
  return 'mac';
}

function renderInstall() {
  const tabs = $('#os-tabs');
  clear(tabs);
  const current = tabs.dataset.current || guessOS();
  tabs.dataset.current = current;
  const list = [['windows', 's5.osWindows'], ['mac', 's5.osMac'],
                ['adobe', 's5.osAdobe'], ['linux', 's5.osLinux']];
  for (const [id, key] of list) {
    tabs.append(el('button', {
      type: 'button', role: 'tab', 'aria-selected': id === current,
      onclick: () => { tabs.dataset.current = id; renderInstall(); },
    }, t(key)));
  }
  const steps = $('#install-steps');
  clear(steps);
  const key = { windows: 's5.stepsWindows', mac: 's5.stepsMac',
                adobe: 's5.stepsAdobe', linux: 's5.stepsLinux' }[current];
  for (const line of t(key).split('|')) steps.append(el('li', { html: line }));

  const fmt = $('#format').value;
  const coll = state.outputs.find(o => o.kind === 'collection');
  if (current === 'windows' && coll && coll.name.endsWith('.otc')) {
    steps.before(el('div', { class: 'note bad' }, el('span', {}, t('s5.windowsOtcWarning'))));
  }
}

/* The self-test embeds the font rather than naming it, for the same reason the
   preview uses a random family: a same-named installed copy would win and the
   page would quietly test the wrong file. */
/* `String.fromCharCode(...bytes)` spreads one argument per byte, so a 230KB
   font overflows the call stack and the whole self-test silently fails to
   generate. Chunking keeps each call small. */
function toBase64(buf) {
  const bytes = new Uint8Array(buf);
  const CHUNK = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(binary);
}

function buildSelfTest() {
  const faces = state.outputs.filter(o => o.kind === 'face');
  // Prefer the face nearest Regular: it is the one a reader recognises.
  const byWeight = state.build.faces
    .map(f => ({ f, out: faces.find(o => o.name === f.file) }))
    .filter(x => x.out && !x.f.italic)
    .sort((a, b) => Math.abs(a.f.weight - 400) - Math.abs(b.f.weight - 400));
  const face = (byWeight[0] && byWeight[0].out) || faces[0] || state.outputs[0];
  const mime = face.name.endsWith('.otf') ? 'font/otf' : 'font/ttf';
  const b64 = toBase64(face.buf);
  const rows = CURRENCIES.map(c => `
    <tr><td>${c.name}</td>
        <td class="big">${String.fromCodePoint(c.cp)}</td>
        <td class="big">${c.latin} 10.50</td>
        <td class="big">${c.ar} ١٠</td></tr>`).join('');
  return `<!doctype html><meta charset="utf-8"><title>self-test — ${state.build.family}</title>
<style>
  @font-face{font-family:'ST';src:url(data:${mime};base64,${b64});}
  body{font:16px/1.6 system-ui;max-width:52rem;margin:2rem auto;padding:0 1rem}
  .big{font-family:'ST';font-size:2rem}
  table{border-collapse:collapse;width:100%}
  td,th{padding:.5rem;border-bottom:1px solid #ddd;text-align:start}
  .guard{font-family:'ST';font-size:1.5rem}
  h1{font-size:1.2rem}
  p.help{color:#555}
</style>
<h1>${state.build.family} — self-test</h1>
<p class="help">The font is embedded in this page, so nothing here depends on it
being installed. If the symbols show below, the file is fine and any problem you
are seeing is installation or the application.</p>
<table><thead><tr><th>currency</th><th>symbol</th><th>latin shortcut</th><th>arabic shortcut</th></tr></thead>
<tbody>${rows}</tbody></table>
<h2 style="font-size:1rem">These must stay unchanged</h2>
<p class="guard">${SHAPING_GUARD.join(' · ')}</p>
<p class="help">Built ${new Date().toISOString().slice(0, 10)} · version ${state.build.version} · embedded face: ${face.name}</p>`;
}

/* --------------------------------------------------------- the skill zip */

async function downloadSkill() {
  const status = $('#skill-status');
  const btn = $('#dl-skill');
  btn.disabled = true;
  status.textContent = t('skill.building');
  try {
    const files = [];
    for (const name of SKILL_FILES) {
      // The page lives in web/, the skill at the repository root.
      const res = await fetch('../' + name);
      if (!res.ok) throw new Error(`${name}: ${res.status}`);
      files.push({ name, bytes: new Uint8Array(await res.arrayBuffer()) });
    }
    const blob = makeZip(files);
    download('arabic-font-merge-skill.zip', URL.createObjectURL(blob));
    status.textContent = `${files.length} files · ${fmtBytes(blob.size)}`;
  } catch (err) {
    status.textContent = t('skill.failed', { d: err.message || String(err) });
  } finally {
    btn.disabled = false;
  }
}

/* ---------------------------------------------------------------- worker */

function send(type, payload) { state.worker.postMessage({ type, ...payload }); }

function hardStopWorker() {
  if (state.worker) { state.worker.terminate(); state.worker = null; }
  clearTimeout(state.timer);
}

let workerReady = null;

function ensureWorker() {
  if (workerReady) return workerReady;
  workerReady = new Promise((resolve, reject) => {
    state.worker = new Worker('worker.js', { type: 'module' });
    state.worker.onmessage = (e) => {
      const m = e.data;
      if (m.type === 'boot') {
        setProgress(m.pct, m.key);
        setEngineStatus('loading', `${t('engine.loading')} ${Math.round(m.pct)}%`);
      } else if (m.type === 'ready') {
        state.caps = m.capabilities;
        setEngineStatus('ready',
          t('engine.ready', { v: m.capabilities.fonttools }) + '  ' +
          (m.capabilities.networkSevered ? t('engine.severed') : t('engine.notSevered')));
        resolve(m.capabilities);
      }
      else if (m.type === 'inspected') { state.report = m.report; renderInspection(); }
      else if (m.type === 'progress') {
        setProgress(m.pct, `${PROGRESS_LABELS[m.key] || m.key}${m.detail ? ' — ' + m.detail : ''}`);
      } else if (m.type === 'built') onBuilt(m.result, m.files);
      else if (m.type === 'error') {
        clearTimeout(state.timer);
        if (m.stage === 'build') showBuildFailure(t('s4.error', { d: m.message }));
        else {
          setEngineStatus('failed', t('engine.failed', { d: m.message }));
          renderNote('#s1-out', 'bad', t('err.worker', { d: m.message }));
        }
        resolve(state.caps || {});
      }
    };
    state.worker.onerror = (e) => {
      setEngineStatus('failed', t('engine.failed', { d: e.message || 'worker failed' }));
      renderNote('#s1-out', 'bad', t('err.worker', { d: e.message || 'worker failed' }));
      reject(e);
    };
    send('init');
  });
  return workerReady;
}

/* ------------------------------------------------------------------ wire */

function wire() {
  $('#lang-toggle').onclick = () => setLang(state.strings._meta.other);
  $('#theme-toggle').onclick = () => {
    const now = document.documentElement.getAttribute('data-theme');
    const dark = now ? now === 'dark'
                     : matchMedia('(prefers-color-scheme: dark)').matches;
    setTheme(dark ? 'light' : 'dark');
  };

  const drop = $('#drop');
  const input = $('#file-input');
  $('#pick').onclick = () => input.click();
  input.onchange = () => onFiles(input.files);
  for (const ev of ['dragenter', 'dragover']) {
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); });
  }
  for (const ev of ['dragleave', 'drop']) {
    drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); });
  }
  drop.addEventListener('drop', e => onFiles(e.dataTransfer.files));

  $('#agree').onchange = e => { $('#s2-next').disabled = !e.target.checked; };
  $('#s2-next').onclick = () => { summarise(2, t('s2.summary')); renderOptions(); openStage(3); };
  $('#add-currency').onclick = openCustomForm;
  $('#build').onclick = startBuild;
  $('#cancel').onclick = () => {
    hardStopWorker();
    workerReady = null;
    showBuildFailure(t('s4.cancelled'));
  };
  $('#to-download').onclick = () => openStage(5);
  $('#dl-selftest').onclick = () => {
    const blob = new Blob([buildSelfTest()], { type: 'text/html' });
    download(`selftest-${state.build.family}.html`, URL.createObjectURL(blob));
  };
  $('#restart').onclick = () => location.reload();
  $('#dl-skill').onclick = downloadSkill;
  $('#skill-repo').href = PROJECT.repo;

  for (const head of $$('.stage-head')) {
    head.onclick = () => {
      const s = head.closest('.stage');
      if (s.dataset.state === 'done') openStage(Number(s.dataset.stage));
    };
  }
}

/* ------------------------------------------------------------------ init */

(async function init() {
  await setLang(localStorage.getItem('lang') || 'ar');
  setTheme(localStorage.getItem('theme') || 'system');
  wire();
  setEngineStatus('loading', t('engine.loading'));
  // Warm the engine while the visitor is still reading, so the first build does
  // not also pay for a 7MB download.
  ensureWorker().catch(() => {});
})();
