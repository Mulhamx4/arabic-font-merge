#!/usr/bin/env python3
"""Generate a tiny synthetic *variable* font, so the HVAR check can run in CI.

`tests/test_variable_advance.py` guards a bug that only exists in variable
fonts: `otTables.VarIdxMap.postRead` pads a short delta-set index map by
repeating its last entry, so a glyph appended to a variable font silently
inherits its neighbour's HVAR advance-width deltas. No font is committed to
this repository and CI downloads nothing (see NOTICE.md), so we build the
fixture the same way `make_test_font.py` builds the static pair.

Reproducing the bug takes three things, and this file exists to guarantee all
three:

  * `fvar`, so there is a design space to move through;
  * `gvar`, so the outlines -- and the phantom points that carry advances --
    really vary. Without it the font would be variable in name only, and the
    test's claim that fontTools' own instancer cannot see the damage (it
    rebuilds hmtx from those phantom points) would be untestable;
  * `HVAR` with a populated `VarStore` and an `AdvWidthMap` whose *trailing*
    entries all repeat one NON-ZERO delta-set index. `VarIdxMap.preWrite`
    trims trailing duplicates, so the map reaches disk shorter than the glyph
    count -- and a short map is precisely what makes `postRead` pad. Were the
    trailing rows zero the padding would be harmless and the test would prove
    nothing, so the digits carry a real width delta and sit last in the order.

That last point is checked against the saved bytes rather than hoped for; see
`_ondisk_map_count`.

    python tests/make_variable_test_font.py out-dir/
"""

import os
import struct
import sys

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables import otTables as ot
from fontTools.ttLib.tables.TupleVariation import TupleVariation
from fontTools.varLib import builder as varBuilder

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_test_font import CHARS, UPEM, box   # noqa: E402  the same design, moving

# One axis, and its low end is also its default: the regression test samples
# every axis from min to max, so a default that sits at the minimum keeps the
# base of that sweep on the font's default instance.
AXIS = ("wght", 400, 400, 700, "Weight")

BODY_H, BOLD_H = 640, 700          # the box grows taller with weight ...
BODY_W, WIDE_W = 600, 720          # ... and the digits also grow wider
ADV_DELTA = WIDE_W - BODY_W        # 120 units of advance at wght=700

# The glyphs that carry a width delta. They must be the *last* entries in the
# glyph order for their index-map rows to be the ones `preWrite` trims and
# `postRead` later repeats onto anything appended after them.
WIDE = "0123456789"
assert CHARS.endswith(WIDE), "the wide glyphs must sit last in the glyph order"

FILENAME = "SmokeTestVF[wght].ttf"


def _name(ch):
    return "uni%04X" % ord(ch)


def _outlines():
    """The default master: the same boxes `make_test_font.py` draws."""
    glyphs, metrics = {}, {}
    for ch in CHARS:
        pen = TTGlyphPen(None)
        if ch == " ":
            adv = 300                       # space: blank, and does not vary
        else:
            box(pen, BODY_W, BODY_H)
            adv = BODY_W
        glyphs[_name(ch)] = pen.glyph()
        metrics[_name(ch)] = (adv, 60)

    pen = TTGlyphPen(None)
    box(pen, BODY_W, BOLD_H)                # .notdef is constant across the axis
    glyphs[".notdef"] = pen.glyph()
    metrics[".notdef"] = (BODY_W, 60)
    return glyphs, metrics


def _variations():
    """gvar deltas taking every box to its wght=700 shape.

    A contour is four points -- (60,0), (w-60,0), (w-60,h), (60,h) -- followed
    by the four phantom points fontTools appends. Phantom point 1 carries the
    advance, so the digits widen there by exactly the delta HVAR also states:
    a real variable font agrees with itself, and it is that agreement which
    hides the HVAR damage from anything that reads advances out of gvar.
    """
    grow = BOLD_H - BODY_H
    narrow = [(0, 0), (0, 0), (0, grow), (0, grow)] + [(0, 0)] * 4
    wide = ([(0, 0), (ADV_DELTA, 0), (ADV_DELTA, grow), (0, grow)]
            + [(0, 0), (ADV_DELTA, 0), (0, 0), (0, 0)])
    peak = {AXIS[0]: (0.0, 1.0, 1.0)}
    return {_name(ch): [TupleVariation(peak, wide if ch in WIDE else narrow)]
            for ch in CHARS if ch != " "}


def _add_hvar(font):
    """HVAR: two delta-set rows, and a map that sends the digits to the live one."""
    order = font.getGlyphOrder()
    regions = varBuilder.buildVarRegionList([{AXIS[0]: (0.0, 1.0, 1.0)}], [AXIS[0]])
    # Row 0 is all zeros -- the row `neutralise_advance_variation` should find
    # and reuse. Row 1 is the width delta the digits actually want.
    data = varBuilder.buildVarData([0], [[0], [ADV_DELTA]], optimize=False)

    table = ot.HVAR()
    table.Version = 0x00010000
    table.VarStore = varBuilder.buildVarStore(regions, [data])
    table.AdvWidthMap = varBuilder.buildVarIdxMap(
        [1 if g in {_name(c) for c in WIDE} else 0 for g in order], order)
    table.LsbMap = table.RsbMap = None

    font["HVAR"] = newTable("HVAR")
    font["HVAR"].table = table


def _ondisk_map_count(path):
    """MappingCount of HVAR's AdvWidthMap as it was actually written.

    Read from the bytes rather than from a decompiled table, because a
    decompiled one has already been padded back to full length by the very
    `postRead` this fixture exists to provoke. HVAR is a version, then four
    offsets from the top of the table; a VarIdxMap is uint16 EntryFormat then
    uint16 MappingCount.
    """
    with TTFont(path) as f:
        raw = f.reader["HVAR"]
    adv_off = struct.unpack(">L", raw[8:12])[0]
    return struct.unpack(">H", raw[adv_off + 2:adv_off + 4])[0]


def build(path):
    glyphs, metrics = _outlines()
    order = [".notdef"] + [_name(c) for c in CHARS]

    fb = FontBuilder(UPEM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap({ord(c): _name(c) for c in CHARS})
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({
        "familyName": "SmokeTest VF",
        "styleName": "Regular",
        "fullName": "SmokeTest VF Regular",
        "psName": "SmokeTestVF-Regular",
        "version": "Version 1.000",
    })
    fb.setupOS2(version=4, sTypoAscender=800, sTypoDescender=-200,
                usWeightClass=AXIS[1], sCapHeight=700, fsSelection=0x40)
    fb.setupPost()
    fb.setupFvar([AXIS], [
        {"location": {AXIS[0]: 400}, "stylename": "Regular"},
        {"location": {AXIS[0]: 700}, "stylename": "Bold"},
    ])
    fb.setupGvar(_variations())
    _add_hvar(fb.font)
    fb.save(path)

    count = _ondisk_map_count(path)
    if count >= len(order):
        raise SystemExit(
            f"{path}: HVAR.AdvWidthMap kept all {count} entries, so nothing was "
            "trimmed and postRead has nothing to pad. The fixture would not "
            "reproduce the bug it exists for.")
    return path, count, len(order)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "tests/fonts/variable"
    os.makedirs(out, exist_ok=True)
    path, count, total = build(os.path.join(out, FILENAME))
    print(f"wrote {path}")
    print(f"  HVAR.AdvWidthMap: {count} entries on disk for {total} glyphs "
          f"-- {total - count} trailing duplicates trimmed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
