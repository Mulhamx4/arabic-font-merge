#!/usr/bin/env bash
# Fetch the test fixtures. They are OFL fonts, so the repository downloads them
# rather than redistributing them -- see NOTICE.md.
#
#   tests/fetch_fonts.sh
#
# Downloads four static weights of IBM Plex Sans Arabic, the variable Readex
# Pro, and the variable IBM Plex Sans Italic, then derives the rest locally:
#
#   plex-cff/       the same faces converted to CFF outlines
#   mixed-italic/   Arabic uprights + Latin italics = an italic with no Arabic
#   restricted/     fsType set to Restricted License Embedding
#   arabic-named/   an Arabic family name in the Windows records
#   reserved-name/  an OFL font that reserves the name it carries
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
B="https://raw.githubusercontent.com/google/fonts/main/ofl"
F=tests/fonts

mkdir -p "$F"/{plex-arabic,plex-cff,mixed-italic,variable,restricted,arabic-named,reserved-name}

get() {  # get <url> <dest>
  [ -s "$2" ] && { echo "  have $(basename "$2")"; return; }
  curl -sSfL --max-time 120 -o "$2" "$1" && echo "  got  $(basename "$2")"
}

echo "IBM Plex Sans Arabic (static, glyf, Arabic)"
for w in Light Regular SemiBold Bold; do
  get "$B/ibmplexsansarabic/IBMPlexSansArabic-$w.ttf" "$F/plex-arabic/IBMPlexSansArabic-$w.ttf"
done

echo "Readex Pro (variable)"
get "$B/readexpro/ReadexPro%5BHEXP%2Cwght%5D.ttf" "$F/variable/ReadexPro[HEXP,wght].ttf"

echo "IBM Plex Sans Italic (variable; static instances are cut from it)"
get "$B/ibmplexsans/IBMPlexSans-Italic%5Bwdth%2Cwght%5D.ttf" "$F/.plex-italic-vf.ttf"

echo "deriving the rest"
"$PY" - <<'PY'
import os, shutil, subprocess, sys
sys.path.insert(0, "web/py")
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

F = "tests/fonts"

# --- static italic instances, Latin only: an italic with no Arabic ---------
NAMES = {300: "Light", 400: "Regular", 600: "SemiBold", 700: "Bold"}
for wght, label in NAMES.items():
    out = f"{F}/mixed-italic/IBMPlexSans-{label}Italic.ttf"
    if os.path.exists(out):
        continue
    f = TTFont(f"{F}/.plex-italic-vf.ttf")
    instancer.instantiateVariableFont(f, {"wght": wght, "wdth": 100}, inplace=True)
    n = f["name"]
    for nid, val in ((1, "IBM Plex Sans" if label in ("Regular", "Bold") else f"IBM Plex Sans {label}"),
                     (2, "Italic" if label != "Bold" else "Bold Italic"),
                     (4, f"IBM Plex Sans {label} Italic"),
                     (6, f"IBMPlexSans-{label}Italic"),
                     (16, "IBM Plex Sans"),
                     (17, f"{label} Italic" if label != "Regular" else "Italic")):
        for pid, eid, lid in ((3, 1, 0x409), (1, 0, 0)):
            n.setName(val, nid, pid, eid, lid)
    f["OS/2"].usWeightClass = wght
    f.save(out)
    f.close()
for w in ("Light", "Regular", "SemiBold", "Bold"):
    shutil.copy(f"{F}/plex-arabic/IBMPlexSansArabic-{w}.ttf",
                f"{F}/mixed-italic/IBMPlexSansArabic-{w}.ttf")

# --- CFF versions of the Arabic faces --------------------------------------
if not os.listdir(f"{F}/plex-cff"):
    subprocess.run([sys.executable, "tools/ttf2cff.py",
                    *[f"{F}/plex-arabic/{n}" for n in sorted(os.listdir(f"{F}/plex-arabic"))],
                    f"{F}/plex-cff/"], check=True)

BASE = f"{F}/plex-arabic/IBMPlexSansArabic-Regular.ttf"

# --- fsType: Restricted License Embedding ----------------------------------
out = f"{F}/restricted/Restricted-Regular.ttf"
if not os.path.exists(out):
    f = TTFont(BASE)
    f["OS/2"].fsType = 0x0002
    f["name"].setName("All rights reserved. No modification permitted.", 13, 3, 1, 0x409)
    f.save(out); f.close()

# --- an Arabic family name, in the Windows records only --------------------
out = f"{F}/arabic-named/ArabicNamed-Regular.ttf"
if not os.path.exists(out):
    f = TTFont(BASE)
    for nid, val in ((1, "خط تجريبي"), (4, "خط تجريبي عادي"), (16, "خط تجريبي")):
        f["name"].setName(val, nid, 3, 1, 0x409)
    f.save(out); f.close()

# --- an OFL font that reserves the very name it carries --------------------
out = f"{F}/reserved-name/Qamar-Regular.ttf"
if not os.path.exists(out):
    f = TTFont(BASE); n = f["name"]
    n.setName("Copyright (c) 2024, Example Foundry (foundry@example.com), "
              "with Reserved Font Name Qamar.", 0, 3, 1, 0x409)
    n.setName("This Font Software is licensed under the SIL Open Font License, "
              "Version 1.1.", 13, 3, 1, 0x409)
    n.setName("https://openfontlicense.org", 14, 3, 1, 0x409)
    for nid, val in ((1, "Qamar"), (4, "Qamar Regular"), (16, "Qamar"), (6, "Qamar-Regular")):
        for pid, eid, lid in ((3, 1, 0x409), (1, 0, 0)):
            n.setName(val, nid, pid, eid, lid)
    f.save(out); f.close()

print("  fixtures ready")
PY

echo
echo "done. now: tests/run_all.sh"
