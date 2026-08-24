// Checks every foreground/background pair the UI actually uses, in both
// palettes, against WCAG AA. Parses themes.css so the test cannot drift from
// the stylesheet.
const fs = require('fs');
const css = fs.readFileSync(__dirname + '/../web/themes.css', 'utf8');

function block(re) {
  const m = css.match(re);
  const vars = {};
  if (m) for (const [, k, v] of m[1].matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) vars[k] = v;
  return vars;
}
const light = block(/:root\s*\{([\s\S]*?)\n\}/);
const dark = block(/:root\[data-theme="dark"\]\s*\{([\s\S]*?)\n\}/);

const lum = hex => {
  const c = [1, 3, 5].map(i => parseInt(hex.substr(i, 2), 16) / 255)
    .map(v => v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

// [foreground, background, minimum, what it is]
const PAIRS = [
  ['ink', 'bg', 4.5, 'body text'],
  ['ink', 'bg-raised', 4.5, 'text on cards'],
  ['ink', 'bg-sunken', 4.5, 'text on sunken areas'],
  ['ink-muted', 'bg', 4.5, 'secondary text'],
  ['ink-faint', 'bg', 4.5, 'faint text'],
  ['ink-faint', 'bg-raised', 4.5, 'faint text on cards'],
  ['accent', 'bg', 4.5, 'links'],
  ['accent', 'bg-raised', 4.5, 'links on cards'],
  ['accent-ink', 'accent', 4.5, 'primary button label'],
  ['ok', 'bg', 4.5, 'pass text'],
  ['ok', 'ok-soft', 4.5, 'pass badge'],
  ['warn', 'bg', 4.5, 'warning text'],
  ['warn', 'warn-soft', 4.5, 'warning badge'],
  ['bad', 'bg', 4.5, 'failure text'],
  ['bad', 'bad-soft', 4.5, 'failure badge'],
  ['line-strong', 'bg', 3.0, 'control borders'],
  ['focus', 'bg', 3.0, 'focus ring'],
];

let bad = 0;
for (const [name, vars] of [['light', light], ['dark', dark]]) {
  console.log(`\n${name} palette`);
  for (const [fg, bg, min, label] of PAIRS) {
    if (!vars[fg] || !vars[bg]) { console.log(`  ?? missing ${fg} or ${bg}`); bad++; continue; }
    const r = ratio(vars[fg], vars[bg]);
    const ok = r >= min;
    if (!ok) bad++;
    console.log(`  ${ok ? 'ok  ' : 'FAIL'} ${r.toFixed(2).padStart(6)}:1  (min ${min})  ${fg} on ${bg} — ${label}`);
  }
}
console.log(bad ? `\n${bad} pair(s) below AA` : '\nall pairs meet AA in both palettes');
process.exit(bad ? 1 : 0);
