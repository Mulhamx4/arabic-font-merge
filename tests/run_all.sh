#!/usr/bin/env bash
# Every check, in the order that fails cheapest first.
#
#   tests/run_all.sh              # against whatever fontTools is installed
#   PY=./.venv-pyodide-parity/bin/python tests/run_all.sh
#                                 # against the version Pyodide actually ships
set -uo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
fails=0

step() {
  printf '\n\033[1m== %s\033[0m\n' "$1"; shift
  if "$@"; then printf '   \033[32mok\033[0m\n'; else printf '   \033[31mFAILED\033[0m\n'; fails=$((fails+1)); fi
}

printf 'fontTools: %s\n' "$($PY -c 'import fontTools;print(fontTools.version)')"

if [ ! -d tests/fonts/plex-arabic ]; then
  printf '\n\033[31mtest fixtures are missing -- run tests/fetch_fonts.sh first\033[0m\n'
  exit 1
fi

step "theme contrast (WCAG AA, both palettes)" node tests/test_contrast.js
step "i18n keys: both languages, none dead" $PY - <<'EOF'
import json, sys
a = json.load(open("web/i18n/ar.json", encoding="utf-8"))
e = json.load(open("web/i18n/en.json", encoding="utf-8"))
bad = 0
lopsided = sorted(set(a) ^ set(e))
if lopsided:
    print("keys present in only one language:", lopsided); bad = 1
# A key nothing references is a string that silently stopped being shown.
src = "".join(open(f, encoding="utf-8").read()
              for f in ("web/app.js", "web/index.html", "web/pages.js",
                        "web/project.js"))
unused = [k for k in a if k != "_meta" and k not in src]
if unused:
    print("keys nothing references:", unused); bad = 1
if not bad:
    print(f"{len(a)} keys, both languages, all referenced")
sys.exit(bad)
EOF
step "javascript parses" node tests/check_js.mjs
step "markdown links and anchors resolve" $PY tests/check_docs.py
step "variable-font advance regression (HVAR)" $PY tests/test_variable_advance.py
step "engine, all four corpora" bash -c "$PY tests/run_engine.py all 2>&1 | tail -3"
for corpus in plex-arabic plex-cff mixed-italic; do
  step "parity with the command-line build: $corpus" bash -c "$PY tests/test_parity.py tests/fonts/$corpus 2>&1 | tail -2"
done
step "licence rules: rename required only when the OFL says so" $PY tests/test_license_rules.py
step "Arabic-named fonts build; PostScript names stay ASCII" $PY tests/test_arabic_names.py
step "custom currency artwork: works, and cannot overwrite a glyph" $PY tests/test_custom_currency.py
step "restricted fsType is blocked" $PY - <<'EOF'
import glob, sys
sys.path.insert(0, "scripts")
sys.path.insert(0, "web/py")
import web_build as wb
r = wb.inspect_paths(sorted(glob.glob("tests/fonts/restricted/*.ttf")))
assert r["route"] == "blocked", r["route"]
assert r["blocked_files"], "nothing was blocked"
print("route =", r["route"], "|", r["blocked_files"])
EOF

printf '\n'
if [ "$fails" -eq 0 ]; then printf '\033[32mall checks passed\033[0m\n'; else printf '\033[31m%s check(s) failed\033[0m\n' "$fails"; fi
exit "$fails"
