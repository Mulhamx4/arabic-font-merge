#!/usr/bin/env python3
"""Prove a built font actually works. Exits non-zero on any failure.

    python scripts/verify_font.py <font.otc|font.otf|dir> [--corpus extra.txt]

Two checks here exist because of real bugs that shipped:

* advance-width parity -- a CFF glyph carries its advance twice, in `hmtx` and
  inside the charstring. Browsers and HarfBuzz read hmtx; Adobe reads the
  charstring. Get them out of sync and the font looks perfect in every browser
  test while Adobe shows a wide band of dead space. Never sign off on a font
  from browser rendering alone.

* shortcut guards -- a bare ligature for "OMR" rewrites "COMRADE" in all-caps
  headings. The negative corpus is as important as the positive one.
"""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fontTools.ttLib import TTFont, TTCollection
import fontkit as fk

try:
    import uharfbuzz as hb
except ImportError:
    print("error: pip install uharfbuzz --break-system-packages", file=sys.stderr)
    raise

ARABIC_CORPUS = [
    "السلام عليكم ورحمة الله وبركاته",
    "مَرْحَبًا بِكَ يَا صَدِيقِي",
    "لا إله إلا الله",
    "الأرقام ٠١٢٣٤٥٦٧٨٩ مع 0123456789",
    "کیف حالت؟ اردو ہے ٹھیک",
    "جميع الحقوق محفوظة © 2026",
    "المبلغ ٢٥٠ ريال عماني فقط لا غير",
]
# One entry per currency: (glyph, sequences that must fire, literal char).
SYMBOLS = {
    "uni20C1": {"name": "Saudi Riyal",  "fire": ["SAR 10.50", "sar 5", "ر.س ١٠", "ر.س. ٥", "\u20C1 20"]},
    "uni20C3": {"name": "UAE Dirham",   "fire": ["AED 10.50", "aed 5", "د.إ ١٠", "د.إ. ٥", "\u20C3 20"]},
    "uni20C4": {"name": "Omani Rial",   "fire": ["OMR 10.500", "omr 5", "ر.ع ١٠", "ر.ع. ٥", "\u20C4 20"]},
}
# Near-misses that must survive untouched. A bare ligature would eat the middle
# of every one of these, which is the whole reason the guards exist.
SHOULD_NOT_FIRE = ["comrade", "COMRADE", "Omri", "OMRAN", "homer", "tomorrow",
                   "commercial", "HOMER", "SARAH", "Caesar", "sarcasm", "SARCASM",
                   "sardine", "aedile", "PAEDIATRIC"]


def faces_of(path):
    if path.lower().endswith((".otc", ".ttc")):
        coll = TTCollection(path)
        blob = hb.Blob(open(path, "rb").read())
        return [(f, hb.Font(hb.Face(blob, i))) for i, f in enumerate(coll.fonts)]
    font = TTFont(path)
    return [(font, hb.Font(hb.Face(hb.Blob.from_file_path(path))))]


def shaper(font, hbfont):
    order = font.getGlyphOrder()

    def shape(text):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(hbfont, buf)
        return [order[i.codepoint] for i in buf.glyph_infos]
    return shape


def check_face(font, hbfont, corpus, expect_symbol):
    shape = shaper(font, hbfont)
    name = fk.best_name(font, 4) or "?"
    fails = []

    cmap = font.getBestCmap()
    n_arabic = len(fk.arabic_letters(font))

    # A Latin-only font legitimately cannot shape Arabic. Failing it here would
    # teach everyone to ignore this report, so Arabic checks only apply to faces
    # that claim Arabic coverage. Whether the family SHOULD have Arabic is a
    # family-level question, checked once at the end.
    if n_arabic:
        for text in corpus:
            missing = shape(text).count(".notdef")
            if missing:
                fails.append(f"{missing} missing glyph(s) shaping {text!r}")

    order = set(font.getGlyphOrder())
    present = [g for g in SYMBOLS if g in order and int(g[3:], 16) in cmap]
    sym_ok = bool(present)
    fired = guarded = n_fire = None
    if expect_symbol:
        for g in (g for g in SYMBOLS if g not in present):
            fails.append(f"{SYMBOLS[g]['name']} U+{g[3:]} missing from cmap or glyph order")
        if present:
            # Arabic shortcuts only apply where the face actually covers Arabic,
            # so a Latin-only family is judged on its Latin shortcuts alone.
            expect = [(t, g) for g in present for t in SYMBOLS[g]["fire"]
                      if n_arabic or not any("\u0600" <= c <= "\u06ff" for c in t)]
            bad_fire = [(t, g) for t, g in expect if g not in shape(t)]
            fired, n_fire = len(expect) - len(bad_fire), len(expect)
            all_syms = set(present)
            bad_guard = [t for t in SHOULD_NOT_FIRE if all_syms & set(shape(t))]
            guarded = len(SHOULD_NOT_FIRE) - len(bad_guard)
            for t, g in bad_fire:
                fails.append(f"{SYMBOLS[g]['name']} shortcut did not fire: {t!r}")
            for t in bad_guard:
                fails.append(f"a shortcut wrongly fired inside {t!r}")

    # Advance parity: hmtx vs the charstring. This is the check that catches the
    # "looks fine in the browser, broken in Adobe" class of bug.
    mismatches = []
    if "CFF " in font:
        for gn in font.getGlyphOrder():
            try:
                cff_w = fk.cff_advance(font, gn)
            except Exception:
                continue
            hmtx_w = font["hmtx"][gn][0]
            if cff_w != hmtx_w:
                mismatches.append((gn, cff_w, hmtx_w))
    for gn, cw, hw in mismatches[:5]:
        fails.append(f"advance mismatch on {gn!r}: CFF={cw} hmtx={hw} "
                     f"({cw - hw:+d} units of dead space in Adobe apps)")
    if len(mismatches) > 5:
        fails.append(f"...and {len(mismatches) - 5} more advance mismatches")

    return {
        "name": name,
        "style": fk.best_name(font, 17),
        "typo_family": fk.best_name(font, 16),
        "legacy_family": fk.best_name(font, 1),
        "legacy_sub": font["name"].getName(2, *fk.WIN),
        "ps": fk.best_name(font, 6),
        "weight": font["OS/2"].usWeightClass,
        "italic": fk.is_italic(font),
        "glyphs": len(font.getGlyphOrder()),
        "arabic": n_arabic,
        "symbol": sym_ok,
        "fired": fired,
        "guarded": guarded,
        "advance_mismatches": len(mismatches),
        "symbols": len(present),
        "n_fire": n_fire,
        "fails": fails,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--corpus", help="file with extra test lines, one per line")
    ap.add_argument("--no-symbols", "--no-symbol", dest="no_symbol",
                    action="store_true",
                    help="font is not expected to contain the currency symbols")
    args = ap.parse_args()

    corpus = list(ARABIC_CORPUS)
    if args.corpus:
        with open(args.corpus, encoding="utf-8") as fh:
            corpus += [l.strip() for l in fh if l.strip()]

    targets = []
    if os.path.isdir(args.target):
        for ext in ("*.otc", "*.ttc", "*.otf", "*.ttf"):
            targets.extend(sorted(glob.glob(os.path.join(args.target, ext))))
    else:
        targets = [args.target]
    if not targets:
        print("no fonts found", file=sys.stderr)
        return 1

    results, total_fails = [], 0
    for path in targets:
        for font, hbfont in faces_of(path):
            r = check_face(font, hbfont, corpus, not args.no_symbol)
            r["file"] = os.path.basename(path)
            results.append(r)
            total_fails += len(r["fails"])

    header = (f"{'face':34} {'wght':>4} {'glyphs':>6} {'arab':>5} "
              f"{'sym':>4} {'fire':>5} {'guard':>6} {'adv':>4}  ")
    print(header)
    print("-" * (len(header) + 6))
    for r in results:
        mark = "PASS" if not r["fails"] else "FAIL"
        fire = "-" if r["fired"] is None else "{}/{}".format(r["fired"], r["n_fire"])
        sym = "no" if not r["symbol"] else str(r["symbols"])
        guard = "-" if r["guarded"] is None else "{}/{}".format(r["guarded"], len(SHOULD_NOT_FIRE))
        adv = "ok" if r["advance_mismatches"] == 0 else str(r["advance_mismatches"])
        print(f"{str(r['name'])[:34]:34} {r['weight']:>4} {r['glyphs']:>6} "
              f"{(r['arabic'] or 'n/a'):>5} {sym:>4} {fire:>5} {guard:>6} {adv:>4}  {mark}")

    # Family coherence -- what makes the styles collapse into one menu entry.
    print()
    ps_names = [str(r["ps"]) for r in results]
    dupes = {n for n in ps_names if ps_names.count(n) > 1}
    fams = {str(r["typo_family"]) for r in results}
    if dupes:
        print(f"FAIL duplicate PostScript names: {sorted(dupes)}")
        total_fails += len(dupes)
    else:
        print(f"PASS {len(ps_names)} unique PostScript names")
    if len(fams) == 1:
        print(f"PASS one typographic family: {fams.pop()!r}")
    else:
        print(f"FAIL faces claim {len(fams)} different typographic families: {sorted(fams)}")
        total_fails += 1

    with_ar = [r for r in results if r["arabic"]]
    without_ar = [r for r in results if not r["arabic"]]
    if with_ar and without_ar:
        print(f"FAIL {len(without_ar)} face(s) have no Arabic while "
              f"{len(with_ar)} do -- Arabic will fall back to a system font in "
              f"those styles: {', '.join(str(r['style']) for r in without_ar[:6])}")
        total_fails += 1
    elif with_ar:
        print(f"PASS all {len(with_ar)} face(s) cover Arabic ({with_ar[0]['arabic']} letters)")
    else:
        print("note  no face covers Arabic; Arabic shaping checks were skipped")

    if total_fails:
        print(f"\n{total_fails} failure(s) across {len(results)} face(s)")
        for r in results:
            if r["fails"]:
                print(f"\n{r['name']}:")
                for f in r["fails"]:
                    print(f"  - {f}")
        return 1

    print(f"\nall {len(results)} face(s) pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
