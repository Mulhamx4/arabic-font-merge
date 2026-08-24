#!/usr/bin/env python3
"""Turn a glyf font into a CFF one, so the test corpus covers both outline types.

Fixture builder only -- the site itself never converts in this direction.
Uses FontBuilder.setupCFF so the CFF is assembled by the supported API rather
than hand-built index objects.
"""
import os
import sys

from fontTools.ttLib import TTFont
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.qu2cuPen import Qu2CuPen


def convert(src, dst):
    f = TTFont(src)
    order = list(f.getGlyphOrder())
    gs = f.getGlyphSet()
    ps = f["name"].getDebugName(6) or os.path.splitext(os.path.basename(dst))[0]

    charstrings = {}
    for gn in order:
        pen = T2CharStringPen(f["hmtx"][gn][0], gs)
        gs[gn].draw(Qu2CuPen(pen, max_err=0.6, all_cubic=True))
        charstrings[gn] = pen.getCharString()

    for tag in ("glyf", "loca", "cvt ", "fpgm", "prep", "gasp"):
        if tag in f:
            del f[tag]

    fb = FontBuilder(font=f)
    fb.setupCFF(ps, {"FullName": f["name"].getDebugName(4) or ps}, charstrings, {})
    f.sfntVersion = "OTTO"
    f["maxp"].tableVersion = 0x00005000
    f["post"].formatType = 3.0
    f.save(dst)
    f.close()
    return len(order)


if __name__ == "__main__":
    for src in sys.argv[1:-1]:
        dst = os.path.join(sys.argv[-1],
                           os.path.splitext(os.path.basename(src))[0] + ".otf")
        print(f"{os.path.basename(dst)}: {convert(src, dst)} glyphs")
