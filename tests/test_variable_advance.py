#!/usr/bin/env python3
"""Regression test for decision #1: a variable font must not inherit width deltas.

Appending a glyph to a variable font makes `VarIdxMap.postRead` pad its map by
repeating the last entry, so the new glyph picks up its neighbour's HVAR delta
set. The damage is invisible to fontTools' own instancer, which rebuilds hmtx
from gvar phantom points -- but every real shaper prefers HVAR, so it is
visible everywhere that matters. This test measures through HarfBuzz.

    python3 tests/test_variable_advance.py     # exits non-zero on regression
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# web_build.py imports fontkit, which lives with the skill in scripts/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "web", "py"))

from fontTools.ttLib import TTFont
import uharfbuzz as hb
import fontkit as fk
import web_build as wb
import fixtures

SRC = fixtures.variable_font()
SVG = os.path.join(ROOT, "assets/saudi-riyal.svg")
GLYPH, CP = "uni20C1", 0x20C1


def build(path, fix):
    f = TTFont(SRC)
    snap = wb.snapshot_advance_maps(f) if fix else {}
    f["OS/2"].sCapHeight = f["OS/2"].sCapHeight or 700
    fk.add_symbol_glyph(f, SVG, CP, GLYPH)
    if fix:
        wb.neutralise_advance_variation(f, [GLYPH], snap)
    f.save(path)
    f.close()


def advances(path):
    order = TTFont(path).getGlyphOrder()
    gid = order.index(GLYPH)
    face = hb.Face(hb.Blob.from_file_path(path))
    axes = {a.axisTag: (a.minValue, a.maxValue)
            for a in TTFont(path)["fvar"].axes}
    out = {}
    for tag, (lo, hi) in axes.items():
        for step in range(5):
            loc = {t: axes[t][0] for t in axes}
            loc[tag] = lo + (hi - lo) * step / 4
            font = hb.Font(face)
            font.set_variations(loc)
            out[tuple(sorted(loc.items()))] = font.get_glyph_h_advance(gid)
    return out


def main():
    print(f"fixture: {os.path.relpath(SRC, ROOT)}")
    build("/tmp/vf_naive.ttf", fix=False)
    build("/tmp/vf_fixed.ttf", fix=True)
    naive, fixed = advances("/tmp/vf_naive.ttf"), advances("/tmp/vf_fixed.ttf")

    n_vals, f_vals = sorted(set(naive.values())), sorted(set(fixed.values()))
    print(f"symbol advance across the design space, measured by HarfBuzz")
    print(f"  without the fix: {n_vals}")
    print(f"  with the fix:    {f_vals}")

    if len(n_vals) == 1:
        # A fixture that stopped reproducing would make this test pass for the
        # wrong reason, so it is a failure rather than a pass.
        print("\nINCONCLUSIVE: this fixture does not reproduce the inheritance "
              "bug, so the test proves nothing. Check that the last glyph of "
              "the order still carries a non-zero advance delta.")
        return 1
    if len(f_vals) != 1:
        print("\nFAIL: the symbol's advance still varies across the design space.")
        return 1
    print(f"\nPASS: unfixed drifts by {max(n_vals) - min(n_vals)} units; fixed is "
          f"constant at {f_vals[0]}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
