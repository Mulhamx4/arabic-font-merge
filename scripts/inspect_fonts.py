#!/usr/bin/env python3
"""Survey a set of font files before touching them.

Run this first, always. It answers the questions that decide the whole job:
which weights exist, which faces have Arabic, whether a variable font is even
possible, and whether the name tables are broken.

    python scripts/inspect_fonts.py <dir-or-files...> [--json out.json]
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fontTools.ttLib import TTFont
import fontkit as fk


def collect(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for ext in ("*.ttf", "*.otf", "*.TTF", "*.OTF"):
                out.extend(sorted(glob.glob(os.path.join(p, ext))))
        else:
            out.append(p)
    seen, uniq = set(), []
    for p in out:
        rp = os.path.realpath(p)
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--json")
    args = ap.parse_args()

    paths = collect(args.paths)
    if not paths:
        print("no font files found")
        return 1

    fonts = [TTFont(p) for p in paths]
    root = fk.family_root(fonts)
    report = {"family_root": root, "count": len(paths), "faces": [],
              "name_table_problems": [], "warnings": []}

    print(f"family root: {root!r}   ({len(paths)} files)\n")
    header = f"{'file':38} {'style':17} {'wght':>4} {'ital':>4} {'glyphs':>6} {'arabic':>6} {'fmt':>4}"
    print(header)
    print("-" * len(header))

    for path, font in zip(paths, fonts):
        style = fk.style_name(font, root)
        ital = fk.is_italic(font)
        ar = len(fk.arabic_letters(font))
        fmt = "CFF" if "CFF " in font else "glyf"
        scripts = sorted(fk.gsub_scripts(font))
        face = {
            "file": os.path.basename(path), "path": path, "style": style,
            "weight": font["OS/2"].usWeightClass, "italic": ital,
            "glyphs": len(font.getGlyphOrder()), "arabic_letters": ar,
            "format": fmt, "gsub_scripts": scripts,
            "has_arabic_layout": "arab" in scripts,
            "cap_height": getattr(font["OS/2"], "sCapHeight", None),
            "upem": font["head"].unitsPerEm,
            "version": fk.best_name(font, 5),
        }
        report["faces"].append(face)
        print(f"{face['file'][:38]:38} {style:17} {face['weight']:>4} "
              f"{'yes' if ital else '-':>4} {face['glyphs']:>6} {ar:>6} {fmt:>4}")

        # The classic shipped-font bug: Windows subfamily says Regular for
        # every face, so apps scatter the family across the font menu.
        win_sub = font["name"].getName(2, *fk.WIN)
        if win_sub and str(win_sub).strip() == "Regular" and style != "Regular":
            report["name_table_problems"].append(
                f"{face['file']}: Windows nameID 2 says 'Regular' but face is {style!r}")

    # Arabic present in uprights but missing from italics?
    ups = [f for f in report["faces"] if not f["italic"]]
    its = [f for f in report["faces"] if f["italic"]]
    if ups and its:
        up_ar = max((f["arabic_letters"] for f in ups), default=0)
        it_ar = max((f["arabic_letters"] for f in its), default=0)
        if up_ar > 0 and it_ar == 0:
            report["warnings"].append(
                f"italics have no Arabic ({up_ar} Arabic letters in uprights) "
                "-- graft it across, or Arabic in italic runs falls back to a system font")

    upems = {f["upem"] for f in report["faces"]}
    if len(upems) > 1:
        report["warnings"].append(f"mixed unitsPerEm {sorted(upems)} -- cannot combine as-is")

    ok, detail = fk.interpolation_report(fonts)
    report["variable_font_possible"] = ok
    report["interpolation"] = detail
    print()
    if ok:
        print("variable font: masters look interpolation-compatible")
    else:
        n, tot = detail.get("incompatible"), detail.get("total")
        if n:
            print(f"variable font: NOT possible -- {n} of {tot} glyphs differ in "
                  f"outline structure between weights ({detail['reason']})")
            print(f"  e.g. {', '.join(detail['examples'][:6])}")
        else:
            print(f"variable font: NOT possible -- {detail['reason']}")
        print("  -> build a collection (.otc/.ttc) instead; it keeps outlines byte-identical")

    if report["name_table_problems"]:
        print(f"\nname table problems ({len(report['name_table_problems'])}):")
        for p in report["name_table_problems"][:6]:
            print(f"  - {p}")
        if len(report["name_table_problems"]) > 6:
            print(f"  ... and {len(report['name_table_problems']) - 6} more")

    for w in report["warnings"]:
        print(f"\nwarning: {w}")

    missing = [f["file"] for f in report["faces"] if f["cap_height"] in (None, 0)]
    if missing:
        print(f"\nwarning: no OS/2 sCapHeight in {len(missing)} face(s); "
              "symbol sizing will need an explicit --cap-height")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
