#!/usr/bin/env python3
"""Build a synthetic variable font that reproduces the HVAR inheritance bug.

`test_variable_advance.py` guards the subtlest defect in this repository, and
without a variable font it cannot run at all -- which in CI, where nothing is
downloaded, meant it never ran. This builds one.

The font only has to be a *faithful* reproduction of the conditions, not a
realistic typeface:

* an `fvar` wght axis, so a shaper can be asked for a location;
* an `HVAR` table whose `VarStore` holds a non-zero advance delta;
* an `AdvWidthMap` in which the LAST glyph of the order points at that delta.

That last point is the whole mechanism. `VarIdxMap.preWrite` trims trailing
duplicate entries, and `postRead` pads a short map by repeating its final
entry -- so a glyph appended after the map was written inherits whatever the
previous last glyph had. Give that final glyph a non-zero delta and the newly
added glyph silently starts varying in width.

    python tests/make_variable_font.py tests/fonts/variable
"""

import os
import sys

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import newTable
from fontTools.ttLib.tables import otTables as ot
from fontTools.varLib.builder import (buildVarData, buildVarIdxMap,
                                      buildVarRegionList, buildVarStore)

UPEM = 1000
CHARS = " .ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"

# The delta the last glyph carries, in font units at the wght extreme. Large
# enough that no rounding can hide it, small enough to stay plausible.
TRAP_DELTA = -40


def box(pen, width, height):
    pen.moveTo((60, 0))
    pen.lineTo((width - 60, 0))
    pen.lineTo((width - 60, height))
    pen.lineTo((60, height))
    pen.closePath()


def build(path):
    names = [".notdef"] + ["uni%04X" % ord(c) for c in CHARS]
    fb = FontBuilder(UPEM, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({ord(c): "uni%04X" % ord(c) for c in CHARS})

    glyphs, metrics = {}, {}
    for name in names:
        pen = TTGlyphPen(None)
        if name == "uni0020":
            adv = 300
        else:
            box(pen, 600, 700)
            adv = 600
        glyphs[name] = pen.glyph()
        metrics[name] = (adv, 60)

    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({
        "familyName": "SmokeTestVF",
        "styleName": "Regular",
        "fullName": "SmokeTestVF Regular",
        "psName": "SmokeTestVF-Regular",
        "version": "Version 1.000",
    })
    fb.setupOS2(version=4, sTypoAscender=800, sTypoDescender=-200,
                usWeightClass=400, sCapHeight=700, fsSelection=0x40)
    fb.setupPost()
    fb.setupFvar(axes=[("wght", 400, 400, 900, "Weight")], instances=[])
    # An empty gvar keeps the file a legitimate glyf variable font. Outlines do
    # not need to move for this test: the defect is in advance widths, and a
    # shaper reads those from HVAR in preference to gvar's phantom points.
    gvar = newTable("gvar")
    gvar.version, gvar.reserved = 1, 0
    gvar.variations = {}
    fb.font["gvar"] = gvar

    font = fb.font
    order = font.getGlyphOrder()

    # One region peaking at the wght maximum, and two delta rows: a zero row
    # every ordinary glyph points at, and the trap the final glyph points at.
    regions = buildVarRegionList([{"wght": (0.0, 1.0, 1.0)}], ["wght"])
    var_data = buildVarData([0], [[0], [TRAP_DELTA]], optimize=False)
    store = buildVarStore(regions, [var_data])

    # varIdx is (outer << 16) | inner; one VarData means outer is always 0.
    ZERO_ROW, TRAP_ROW = 0, 1
    var_idxes = [ZERO_ROW] * len(order)
    var_idxes[-1] = TRAP_ROW

    hvar = ot.HVAR()
    hvar.Version = 0x00010000
    hvar.VarStore = store
    hvar.AdvWidthMap = buildVarIdxMap(var_idxes, order)
    hvar.LsbMap = hvar.RsbMap = None
    font["HVAR"] = newTable("HVAR")
    font["HVAR"].table = hvar

    fb.save(path)
    return path, order[-1]


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "tests/fonts/variable"
    os.makedirs(out, exist_ok=True)
    path, trap_glyph = build(os.path.join(out, "SmokeTestVF.ttf"))
    print(f"wrote {path}")
    print(f"  the trap: {trap_glyph!r} is the last glyph and carries a "
          f"{TRAP_DELTA}-unit advance delta at the wght extreme")
    return 0


if __name__ == "__main__":
    sys.exit(main())
