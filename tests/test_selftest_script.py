"""Run the emitted self-test JavaScript against synthetic browser measurements.

No font libraries or browser required; Node.js exercises callback completion and
row attribution. These measurements do not validate real font shaping.
"""
import ast
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

SOURCE = Path(__file__).resolve().parents[1]/'scripts/make_proof.py'

def emitted_script():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'build_selftest_html')
    template = next(n.value for n in ast.walk(function) if isinstance(n, ast.Constant) and isinstance(n.value, str) and '<script>' in n.value)
    return re.search(r'<script>(.*?)</script>', template, re.S).group(1)

@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class SelftestScript(unittest.TestCase):
    def run_script(self, broken=''):
        harness = r'''
const vm = require('node:vm');
const elements = {};
const broken = BROKEN;
const symbols = {SAR:'\u20c1', AED:'\u20c3', OMR:'\u20c4', 'ر.س':'\u20c1', 'د.إ':'\u20c3', 'ر.ع':'\u20c4'};
function measure(text) {
  if (text.startsWith(broken + ' ') && broken) return 999;
  let normalized = text;
  for (const [token, symbol] of Object.entries(symbols)) {
    if (text === token || text.startsWith(token + ' ')) normalized = symbol + text.slice(token.length);
  }
  return Array.from(normalized).reduce((n, ch) => n + ch.codePointAt(0) % 19 + 8, 0);
}
const document = {
  getElementById(id) { return elements[id] ||= {style:{}, textContent:'', getBoundingClientRect() {return {width:measure(this.textContent)};}}; },
  fonts: {load: async () => [], ready: Promise.resolve()}
};
vm.runInNewContext(SCRIPT, {document});
setImmediate(() => console.log(JSON.stringify(elements)));
'''
        harness = harness.replace('BROKEN', json.dumps(broken)).replace('SCRIPT', json.dumps(emitted_script()))
        result = subprocess.run(['node', '-e', harness], capture_output=True, text=True, encoding='utf-8', check=True)
        return json.loads(result.stdout)

    def test_verdict_callback_completes(self):
        elements = self.run_script()
        self.assertTrue(elements['verdict']['textContent'])
        for row in range(1, 6):
            self.assertEqual(elements[f't{row}']['className'], 'tag ok')

    def test_latin_failures_mark_the_matching_row(self):
        for token, row in [('SAR', 1), ('AED', 2), ('OMR', 3)]:
            with self.subTest(token=token):
                elements = self.run_script(token)
                self.assertEqual(elements[f't{row}']['className'], 'tag no')
                for other in {1, 2, 3} - {row}:
                    self.assertEqual(elements[f't{other}']['className'], 'tag ok')

    def test_all_arabic_shortcuts_affect_the_arabic_row(self):
        for token in ['ر.س', 'د.إ', 'ر.ع']:
            with self.subTest(token=token):
                self.assertEqual(self.run_script(token)['t4']['className'], 'tag no')

if __name__ == '__main__':
    unittest.main()
