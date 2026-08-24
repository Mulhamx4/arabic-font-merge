#!/usr/bin/env python3
"""User-supplied currency artwork: it must work, and it must not damage a font.

Unicode has encoded symbols for very few currencies. For one that has none, the
Private Use Area is the right home, and the tool lets a user bring their own
official artwork. The dangerous part is the codepoint: `add_symbol_glyph`
writes straight into the cmap, so an already-mapped codepoint would silently
replace a real character -- choose U+0041 and every capital A becomes a
currency symbol. This checks the guard holds before checking the happy path.

    python3 tests/test_custom_currency.py
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "web", "py"))

from fontTools.ttLib import TTFont
import web_build as wb

import fixtures
FONT = fixtures.base_font()
MANIFEST = os.path.join(ROOT, "assets/currencies.json")
OUT = os.path.join(ROOT, "tests/out/custom")

# A deliberately simple mark: a filled box with a slash through it. Real artwork
# must come from the issuing authority -- this is a test fixture, not a symbol.
FIXTURE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 120">
  <path d="M10 10 H90 V110 H10 Z M20 20 V100 H80 V20 Z"/>
  <path d="M15 105 L85 15 L92 22 L22 112 Z"/>
</svg>"""
NO_VIEWBOX_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0 H10 V10 Z"/></svg>'


def write(name, text):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(text)
    return p


def build(custom, label):
    out = os.path.join(OUT, label)
    shutil.rmtree(out, ignore_errors=True)
    return wb.build([FONT], {
        "out_dir": out, "manifest": MANIFEST, "route": "merge",
        "version": "2.000", "custom_currencies": custom,
    })


def main():
    bad = 0
    good_svg = write("fixture.svg", FIXTURE_SVG)
    flat_svg = write("noviewbox.svg", NO_VIEWBOX_SVG)

    print("rejections")
    cases = [
        ("codepoint already used by a real glyph",
         {"id": "bad-a", "codepoint": 0x0041, "svg": good_svg}, "codepoint_taken"),
        ("codepoint out of range",
         {"id": "bad-range", "codepoint": 0x200000, "svg": good_svg}, "codepoint_invalid"),
        ("surrogate codepoint",
         {"id": "bad-surrogate", "codepoint": 0xD801, "svg": good_svg}, "codepoint_surrogate"),
        ("artwork with no viewBox",
         {"id": "bad-svg", "codepoint": 0xE001, "svg": flat_svg}, "svg_no_viewbox"),
        ("artwork missing",
         {"id": "bad-path", "codepoint": 0xE002, "svg": "/nope.svg"}, "svg_missing"),
    ]
    for label, entry, expect in cases:
        res = build([entry], "reject-" + entry["id"])
        kinds = [p["kind"] for item in res["custom_problems"] for p in item["problems"]]
        if expect not in kinds:
            print(f"  FAIL {label}: expected {expect}, got {kinds}")
            bad += 1
        elif res["custom_added"]:
            print(f"  FAIL {label}: was added anyway")
            bad += 1
        else:
            print(f"  ok   {label:42} -> {expect}")

    # And the guard has to be real: whatever U+0041 mapped to in the source must
    # still be what it maps to afterwards. Comparing against the source rather
    # than against the literal name "A" keeps this honest on any base font.
    source_a = TTFont(FONT).getBestCmap().get(0x0041)
    res = build([{"id": "bad-a", "codepoint": 0x0041, "svg": good_svg}], "reject-A-check")
    face = TTFont(os.path.join(OUT, "reject-A-check", res["faces"][0]["file"]))
    a_glyph = face.getBestCmap().get(0x0041)
    face.close()
    if a_glyph != source_a:
        print(f"  FAIL U+0041 mapped to {source_a!r} in the source and {a_glyph!r} "
              f"after -- a real glyph was overwritten")
        bad += 1
    else:
        print(f"  ok   U+0041 still maps to {source_a!r} after the rejected attempt")

    print("\nacceptance")
    res = build([{
        "id": "kuwaiti-dinar", "name": "Kuwaiti Dinar", "name_ar": "دينار كويتي",
        "codepoint": 0xE000, "svg": good_svg,
        "latin": ["KWD"], "arabic": ["د.ك"],
    }], "accept")
    face_info = res["faces"][0]
    face = TTFont(os.path.join(OUT, "accept", face_info["file"]))
    cmap = face.getBestCmap()
    order = set(face.getGlyphOrder())
    face.close()

    checks = [
        ("custom currency reported as added", res["custom_added"] == ["kuwaiti-dinar"]),
        ("no problems reported", res["custom_problems"] == []),
        ("U+E000 present in cmap", 0xE000 in cmap),
        ("glyph uniE000 present", "uniE000" in order),
        ("official three still present", all(c in cmap for c in (0x20C1, 0x20C3, 0x20C4))),
        ("four symbols added", face_info["symbols"] == 4),
        ("shortcut rules built", face_info["shortcuts"] > 0),
        ("no verification failures",
         not [f for f in face_info["verify"]["findings"] if f["level"] == "fail"]),
        ("U+0041 untouched", cmap.get(0x0041) == TTFont(FONT).getBestCmap().get(0x0041)),
    ]
    for label, ok in checks:
        bad += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {label}")

    print("\n" + ("FAILED" if bad else
                  "PASS: custom artwork works, and a bad codepoint cannot overwrite a glyph"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
