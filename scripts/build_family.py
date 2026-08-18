#!/usr/bin/env python3
"""Merge a font family into one collection file and add the Gulf currency symbols.

    python scripts/build_family.py <dir-or-files...> --out build/ [options]

What it does, in order:
  1. groups the input faces and works out one coherent family name
  2. gives each italic the Arabic of its matching upright weight (skippable)
  3. adds every symbol in assets/currencies.json plus its typed shortcuts
  4. rewrites the name tables so the whole family collapses to one menu entry
  5. writes <Family>.otc, individual OTF/TTFs, and optionally a WOFF2+CSS bundle

Always run verify_font.py on the result. The build reports what it intended;
verify checks what actually landed in the binary.
"""

import argparse
import glob
import json
import logging
import os
import shutil
import sys
import tempfile

logging.getLogger("fontTools").setLevel(logging.ERROR)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fontTools.ttLib import TTFont
import fontkit as fk

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(SKILL_DIR, "assets")
MANIFEST = os.path.join(ASSETS, "currencies.json")


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


def load_currencies(path, only=None):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for c in data["currencies"]:
        if only and c["id"] not in only:
            continue
        cp = int(c["codepoint"], 16)
        out.append({
            "id": c["id"], "name": c["name"], "codepoint": cp,
            "glyph": "uni%04X" % cp,
            "svg": os.path.join(ASSETS, c["svg"]),
            "latin": c.get("latin", []), "arabic": c.get("arabic", []),
        })
    return out


def shortcut_mapping(font, currencies):
    """Literal shortcut strings -> (glyph sequence, target glyph) pairs.

    Longest first so "ر.س." is tried before "ر.س"; the ligature builder relies on
    that ordering, and a sequence whose characters the font lacks is skipped
    rather than silently producing a broken rule.
    """
    mapping = []
    for cur in currencies:
        if cur["glyph"] not in set(font.getGlyphOrder()):
            continue
        for text in sorted(cur["latin"] + cur["arabic"], key=len, reverse=True):
            seq = fk.text_to_glyphs(font, text)
            if seq:
                mapping.append((seq, cur["glyph"]))
    return mapping


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--family", help="override family name")
    ap.add_argument("--version", default="2.000",
                    help="bump this on every rebuild; Adobe caches fonts by "
                         "PostScript name and serves stale data otherwise")
    ap.add_argument("--currencies", default=MANIFEST,
                    help="path to the currency manifest")
    ap.add_argument("--only", nargs="*",
                    help="build just these currency ids (default: all)")
    ap.add_argument("--no-symbols", action="store_true")
    ap.add_argument("--no-shortcuts", action="store_true")
    ap.add_argument("--no-arabic-graft", action="store_true")
    ap.add_argument("--side-bearing", type=float, default=60)
    ap.add_argument("--cap-ratio", type=float, default=1.0)
    ap.add_argument("--slant-symbols-in-italics", action="store_true",
                    help="oblique the symbols in italic faces (off by default: "
                         "they are official marks and Arabic has no italic)")
    ap.add_argument("--format", choices=["auto", "otc", "ttc"], default="auto",
                    help="auto keeps the source outline type; ttc converts CFF to "
                         "TrueType so the file installs on Windows (Explorer has "
                         "no Install action for .otc at all)")
    ap.add_argument("--single-family", action="store_true",
                    help="put every face under one legacy family name too. Gives a "
                         "single clean menu entry, but GDI-era apps only address "
                         "four styles per family -- run the report the skill "
                         "describes before choosing this")
    ap.add_argument("--woff2", action="store_true", help="also write a web bundle")
    args = ap.parse_args()

    paths = collect(args.paths)
    if not paths:
        print("no font files found", file=sys.stderr)
        return 1

    currencies = [] if args.no_symbols else load_currencies(args.currencies, args.only)
    missing = [c["svg"] for c in currencies if not os.path.exists(c["svg"])]
    if missing:
        print("error: missing artwork: " + ", ".join(missing), file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    otf_dir = os.path.join(args.out, "otf")
    os.makedirs(otf_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="fontbuild_")

    probes = [TTFont(p) for p in paths]
    root = args.family or fk.family_root(probes)
    upems = {f["head"].unitsPerEm for f in probes}
    if len(upems) > 1:
        print(f"error: mixed unitsPerEm {sorted(upems)}; cannot combine", file=sys.stderr)
        return 1

    # Map weight -> upright path so italics can borrow Arabic from their peer.
    upright_by_weight, plan = {}, []
    for path, font in zip(paths, probes):
        entry = {"path": path, "style": fk.style_name(font, root),
                 "weight": font["OS/2"].usWeightClass,
                 "italic": fk.is_italic(font),
                 "arabic": len(fk.arabic_letters(font))}
        plan.append(entry)
        if not entry["italic"]:
            upright_by_weight.setdefault(entry["weight"], entry)
    for f in probes:
        f.close()

    plan.sort(key=lambda e: (e["weight"], e["italic"]))
    if currencies:
        print("symbols: " + ", ".join(
            f"{c['name']} U+{c['codepoint']:04X}" for c in currencies))
    if args.format == "ttc":
        print("outlines: converting CFF -> TrueType so the collection installs on Windows")
    print(f"family: {root}   version {args.version}   {len(plan)} faces\n")

    faces, rows = [], []
    for entry in plan:
        src, grafted = entry["path"], False

        if not args.no_arabic_graft and entry["italic"] and entry["arabic"] == 0:
            peer = upright_by_weight.get(entry["weight"])
            if peer and peer["arabic"] > 0:
                dest = os.path.join(tmp, f"graft_{len(faces)}.otf")
                if fk.graft_arabic(src, peer["path"], tmp, dest):
                    src, grafted = dest, True

        font = TTFont(src)
        for tag in ("DYNA", "GDYN"):     # foundry-private, not needed downstream
            if tag in font:
                del font[tag]

        ps = fk.apply_naming(font, root, entry["style"], args.version,
                             single_family=args.single_family)

        added, shortcuts = 0, 0
        if currencies:
            if not getattr(font["OS/2"], "sCapHeight", 0):
                font["OS/2"].sCapHeight = int(font["head"].unitsPerEm * 0.71)
            slant = 10.0 if (args.slant_symbols_in_italics and entry["italic"]) else 0.0
            for cur in currencies:
                fk.add_symbol_glyph(font, cur["svg"], cur["codepoint"], cur["glyph"],
                                    cap_ratio=args.cap_ratio,
                                    side_bearing=args.side_bearing, slant=slant)
                added += 1
            if not args.no_shortcuts:
                shortcuts = fk.add_shortcuts(font, shortcut_mapping(font, currencies))

        fk.recalc_os2(font, extra_codepage_bits=(6,))   # 6 = Arabic (cp1256)

        if args.format == "ttc" and "CFF " in font:
            fk.cff_to_glyf(font)

        out_file = os.path.join(otf_dir, f"{ps}.otf" if "CFF " in font else f"{ps}.ttf")
        font.save(out_file)
        faces.append(font)
        rows.append((f"{root} {entry['style']}", len(font.getGlyphOrder()),
                     added, shortcuts, "yes" if grafted else "-"))

    header = f"{'face':34} {'glyphs':>6} {'syms':>5} {'calt':>5} {'ar graft':>8}"
    print(header)
    print("-" * len(header))
    for name, n, syms, sc, gr in rows:
        print(f"{name[:34]:34} {n:>6} {syms or '-':>5} {sc or '-':>5} {gr:>8}")

    ext = ".otc" if "CFF " in faces[0] else ".ttc"
    if args.format == "otc":
        ext = ".otc"
    coll_path = os.path.join(args.out, f"{root}{ext}")
    fk.save_collection(faces, coll_path)
    print(f"\nwrote {coll_path}  ({os.path.getsize(coll_path) // 1024} KB, {len(faces)} faces)")
    print(f"wrote {otf_dir}/  ({len(rows)} standalone files)")

    if args.woff2:
        web = os.path.join(args.out, "web")
        os.makedirs(web, exist_ok=True)
        css = []
        for fname in sorted(os.listdir(otf_dir)):
            font = TTFont(os.path.join(otf_dir, fname))
            weight = font["OS/2"].usWeightClass
            ital = fk.is_italic(font)
            font.flavor = "woff2"
            w2 = os.path.splitext(fname)[0] + ".woff2"
            font.save(os.path.join(web, w2))
            font.close()
            css.append("@font-face{\n"
                       f"  font-family: '{root}';\n"
                       f"  src: url('{w2}') format('woff2');\n"
                       f"  font-weight: {weight};\n"
                       f"  font-style: {'italic' if ital else 'normal'};\n"
                       "  font-display: swap;\n}\n")
        with open(os.path.join(web, "fonts.css"), "w", encoding="utf-8") as fh:
            fh.write("".join(css))
        print(f"wrote {web}/  (woff2 + fonts.css)")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nnext: python scripts/verify_font.py \"{coll_path}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
