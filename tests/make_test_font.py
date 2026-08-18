#!/usr/bin/env python3
"""Generate a tiny synthetic two-weight family so CI can run end to end.

No font is committed to this repository (see NOTICE.md), and downloading one in
CI makes the test depend on someone else's uptime. So we build one: two faces,
a handful of box glyphs, and exactly the characters the currency shortcuts need.

    python tests/make_test_font.py out-dir/
"""

import os
import sys

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

UPEM = 1000

# Everything the SAR / AED / OMR shortcuts and the negative corpus touch.
CHARS = " .ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def box(pen, width, height):
    pen.moveTo((60, 0))
    pen.lineTo((width - 60, 0))
    pen.lineTo((width - 60, height))
    pen.lineTo((60, height))
    pen.closePath()


def build(path, style, weight, bold):
    names = [".notdef"] + ["uni%04X" % ord(c) for c in CHARS]
    fb = FontBuilder(UPEM, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({ord(c): "uni%04X" % ord(c) for c in CHARS})

    glyphs, metrics = {}, {}
    for name in names:
        pen = TTGlyphPen(None)
        if name == "uni0020":                      # space: blank
            adv = 300
        elif name == ".notdef":
            box(pen, 600, 700)
            adv = 600
        else:
            box(pen, 600, 700 if bold else 640)
            adv = 600
        glyphs[name] = pen.glyph()
        metrics[name] = (adv, 60)

    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({
        "familyName": "SmokeTest",
        "styleName": style,
        "fullName": f"SmokeTest {style}",
        "psName": f"SmokeTest-{style.replace(' ', '')}",
        "version": "Version 1.000",
    })
    fb.setupOS2(version=4, sTypoAscender=800, sTypoDescender=-200,
                usWeightClass=weight, sCapHeight=700,
                fsSelection=(0x20 if bold else 0x40))
    fb.setupPost()
    fb.font["head"].macStyle = 1 if bold else 0
    fb.save(path)
    return path


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "tests/fonts"
    os.makedirs(out, exist_ok=True)
    for style, weight, bold in (("Regular", 400, False), ("Bold", 700, True)):
        p = build(os.path.join(out, f"SmokeTest-{style}.ttf"), style, weight, bold)
        print("wrote", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
