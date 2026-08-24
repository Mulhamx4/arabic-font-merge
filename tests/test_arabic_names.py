#!/usr/bin/env python3
"""An Arabic-named font must build, and its PostScript name must stay ASCII.

Two real failures this guards against:

* `apply_naming` writes every name to the Mac platform records too, and those
  are mac_roman -- which has no Arabic. A font whose family name is Arabic
  (this tool's entire audience) failed to save at all, with a
  UnicodeEncodeError raised from deep inside the compile.

* Under the OFL the reserved name must change. A suffix with no ASCII in it
  cannot reach nameID 6, so the reserved PostScript name would survive intact
  and the rename would be cosmetic. The interface blocks that; this checks the
  engine's half of the contract.

    python3 tests/test_arabic_names.py
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# web_build.py imports fontkit, which lives with the skill in scripts/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "web", "py"))

from fontTools.ttLib import TTFont
import web_build as wb

FIXTURE_DIR = os.path.join(ROOT, "tests/fonts/arabic-named")
FIXTURE = os.path.join(FIXTURE_DIR, "ArabicNamed-Regular.ttf")
MANIFEST = os.path.join(ROOT, "assets/currencies.json")
import fixtures
BASE = fixtures.base_font()


def ensure_fixture():
    if os.path.exists(FIXTURE):
        return
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    f = TTFont(BASE)
    # How Arabic families actually ship: the Arabic name in the Windows UTF-16
    # records, the Mac records left Latin.
    for nid, val in ((1, "خط تجريبي"), (4, "خط تجريبي عادي"), (16, "خط تجريبي")):
        f["name"].setName(val, nid, 3, 1, 0x409)
    f.save(FIXTURE)
    f.close()


def build(label, **extra):
    out = os.path.join(ROOT, "tests/out/arabic-names", label)
    shutil.rmtree(out, ignore_errors=True)
    opts = {"out_dir": out, "manifest": MANIFEST, "route": "merge",
            "version": "2.000"}
    opts.update(extra)
    result = wb.build([FIXTURE], opts)
    face = result["faces"][0]
    font = TTFont(os.path.join(out, face["file"]))
    info = {
        "ps": font["name"].getDebugName(6),
        "family": str(font["name"].getName(1, 3, 1, 0x409)),
        "dropped": face["dropped_mac_names"],
        "fails": [f["kind"] for f in face["verify"]["findings"] if f["level"] == "fail"],
    }
    font.close()
    return info


def main():
    ensure_fixture()
    source_ps = TTFont(FIXTURE)["name"].getDebugName(6)
    bad = 0

    cases = [
        ("no rename", {}, None),
        ("ascii suffix", {"rename_suffix": "ZMKN"}, "ZMKN"),
        ("mixed suffix", {"rename_suffix": "زمكان ZMKN"}, "ZMKN"),
    ]
    for label, extra, expect_in_ps in cases:
        try:
            got = build(label.replace(" ", "-"), **extra)
        except Exception as exc:
            print(f"FAIL {label}: build raised {type(exc).__name__}: {exc}")
            bad += 1
            continue
        ok = True
        if not got["ps"].isascii():
            print(f"FAIL {label}: PostScript name is not ASCII: {got['ps']!r}")
            ok = False
        if expect_in_ps and expect_in_ps not in got["ps"]:
            print(f"FAIL {label}: renamed but PostScript name lacks {expect_in_ps!r}: {got['ps']!r}")
            ok = False
        if expect_in_ps and got["ps"] == source_ps:
            print(f"FAIL {label}: reserved PostScript name survived the rename")
            ok = False
        if got["fails"]:
            print(f"FAIL {label}: verification failures {got['fails']}")
            ok = False
        bad += 0 if ok else 1
        if ok:
            print(f"  ok {label:14} ps={got['ps']!r}  family={got['family']!r}  "
                  f"mac records dropped={got['dropped']}")

    # The engine cannot rename through a pure-Arabic suffix; the interface must
    # be the thing that refuses it. Assert the engine's behaviour is at least
    # predictable rather than silently half-done.
    pure = build("pure-arabic", rename_suffix="زمكان")
    if pure["ps"] != source_ps:
        print(f"FAIL pure-Arabic suffix unexpectedly changed the PostScript name "
              f"to {pure['ps']!r}; the interface guard assumes it cannot")
        bad += 1
    else:
        print(f"  ok pure arabic   PostScript name unchanged as expected "
              f"({pure['ps']!r}) -- the interface blocks this case")

    print("\n" + ("FAILED" if bad else "PASS: Arabic-named fonts build with ASCII "
                                       "PostScript names throughout"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
