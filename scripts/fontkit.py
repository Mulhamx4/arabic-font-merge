"""Shared helpers for merging a font family into one file and adding glyphs.

Design notes worth knowing before you edit this:

* Advance widths live in TWO places in a CFF/OTF font: the `hmtx` table and the
  charstring itself. The charstring stores the width RELATIVE to
  Private.nominalWidthX. Write an absolute value there and the glyph silently
  gains `nominalWidthX` units of dead space -- in Adobe apps only, because
  browsers and HarfBuzz read hmtx. `add_symbol_glyph` handles this; `verify.py`
  asserts the two agree.

* Retail static fonts are almost never interpolation-compatible, so a true
  variable font is usually impossible without redrawing outlines. Collections
  (.otc/.ttc) are the honest way to get "one file" with zero glyph changes.
"""

import math
import os
import unicodedata

from fontTools.ttLib import TTFont, TTCollection
from fontTools.ttLib.tables import otTables as ot
from fontTools.otlLib import builder as otl
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.misc.transform import Transform

WIN = (3, 1, 0x409)
MAC = (1, 0, 0)

# Everything worth carrying when copying Arabic between faces -- includes the
# invisible joiners and marks, which shaping needs.
ARABIC_RANGES = [
    (0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF), (0xFE70, 0xFEFF), (0x200C, 0x200F), (0x061C, 0x061C),
]

# Actual letters only. Fonts with no Arabic at all still often map the joiners
# and the Arabic comma, so counting ARABIC_RANGES makes an Arabic-less italic
# look like it has coverage. Decisions about grafting must use this instead.
ARABIC_LETTER_RANGES = [
    (0x0620, 0x064A), (0x066E, 0x06D3), (0x06D5, 0x06D5),
    (0x06EE, 0x06EF), (0x06FA, 0x06FF), (0x0750, 0x077F),
]

# Fallback only. Style names are read from the fonts themselves first, because
# foundries disagree (600 is "Demi" for some, "SemiBold" for others) and
# silently renaming a customer's styles breaks their existing documents.
WEIGHT_NAMES = {
    100: "Thin", 200: "ExtraLight", 250: "UltraLight", 275: "UltraLight",
    300: "Light", 350: "SemiLight", 400: "Regular", 500: "Medium",
    600: "SemiBold", 700: "Bold", 800: "ExtraBold", 900: "Black", 950: "Heavy",
}

PANOSE_WEIGHT = {100: 2, 200: 2, 250: 3, 275: 3, 300: 3, 350: 4, 400: 5,
                 500: 6, 600: 7, 700: 8, 800: 9, 900: 10, 950: 11}


# ---------------------------------------------------------------- inspection

def is_italic(font):
    if bool(font["head"].macStyle & 2):
        return True
    if bool(font["OS/2"].fsSelection & 1):
        return True
    return font["post"].italicAngle != 0


def best_name(font, *nids):
    """First non-empty name record among nids, preferring the Windows record."""
    name = font["name"]
    for nid in nids:
        for pid, eid, lid in (WIN, MAC):
            rec = name.getName(nid, pid, eid, lid)
            if rec:
                val = str(rec).strip()
                if val:
                    return val
    return ""


def arabic_codepoints(font):
    cmap = font.getBestCmap()
    return [c for c in cmap if any(a <= c <= b for a, b in ARABIC_RANGES)]


def arabic_letters(font):
    cmap = font.getBestCmap()
    return [c for c in cmap if any(a <= c <= b for a, b in ARABIC_LETTER_RANGES)]


def gsub_scripts(font):
    if "GSUB" not in font:
        return set()
    sl = font["GSUB"].table.ScriptList
    return {r.ScriptTag for r in (sl.ScriptRecord or [])} if sl else set()


def gsub_features(font):
    if "GSUB" not in font:
        return set()
    fl = font["GSUB"].table.FeatureList
    return {r.FeatureTag for r in (fl.FeatureRecord or [])} if fl else set()


def outline_signature(font):
    """Per-glyph (operator, argcount) tuples -- used to test interpolability."""
    gs = font.getGlyphSet()
    sig = {}
    for gn in font.getGlyphOrder():
        pen = RecordingPen()
        gs[gn].draw(pen)
        sig[gn] = tuple((op, len(args)) for op, args in pen.value)
    return sig


def interpolation_report(fonts):
    """Can these masters become a variable font? Returns (ok, details).

    A wght axis needs every glyph to have identical point structure across
    masters. Retail families are drawn per weight, so this almost always fails
    -- run it anyway so you can tell the user *why* with a number instead of an
    assertion.
    """
    uprights = [f for f in fonts if not is_italic(f)]
    if len(uprights) < 2:
        return True, {"reason": "fewer than 2 upright masters", "incompatible": 0}
    orders = [tuple(f.getGlyphOrder()) for f in uprights]
    if len(set(orders)) != 1:
        return False, {"reason": "glyph orders differ between masters",
                       "incompatible": None}
    sigs = [outline_signature(f) for f in uprights]
    base = sigs[0]
    bad = [gn for gn in orders[0] if any(s[gn] != base[gn] for s in sigs[1:])]
    return (len(bad) == 0), {"reason": "outline structure differs",
                             "incompatible": len(bad),
                             "total": len(orders[0]),
                             "examples": bad[:10]}


# ------------------------------------------------------------------- naming

def family_root(fonts):
    """Longest word-wise common prefix of the legacy family names.

    Families are usually split RIBBI-style ("Foo", "Foo Light", "Foo Black"),
    so the shared prefix is the real typographic family name.
    """
    names = [best_name(f, 16, 1).split() for f in fonts]
    if not names:
        return "Font"
    root = []
    for i in range(min(len(n) for n in names)):
        token = names[0][i]
        if all(n[i] == token for n in names):
            root.append(token)
        else:
            break
    return " ".join(root) or " ".join(names[0][:1])


def style_name(font, root):
    """Typographic style ("Demi Italic", "Regular", ...) for one face.

    Prefer what the foundry called it. nameID 17 is authoritative when present;
    otherwise reconstruct from the split family name plus subfamily, which is
    how RIBBI-grouped families encode weight.
    """
    ital = is_italic(font)
    n17 = best_name(font, 17)
    if n17:
        style = n17
    else:
        fam = best_name(font, 1)
        suffix = fam[len(root):].strip() if fam.startswith(root) else ""
        sub = best_name(font, 2)
        # Mac subfamily is usually right even when the Windows one says
        # "Regular" for every face -- a very common bug in shipped fonts.
        parts = [p for p in (suffix, sub) if p and p.lower() != "regular"]
        style = " ".join(parts).strip()
        if not style:
            style = WEIGHT_NAMES.get(font["OS/2"].usWeightClass, "Regular")
    style = " ".join(style.split())
    if ital and "italic" not in style.lower():
        style = (style + " Italic").strip()
    if not ital:
        style = style.replace("Italic", "").strip() or "Regular"
    # "Regular Italic" is not a style name anyone uses -- the italic of the
    # regular weight is just "Italic".
    if style.lower() == "regular italic":
        style = "Italic"
    return style or "Regular"


def legacy_pair(root, style):
    """(family, subfamily) for the 4-styles-per-family limit older apps have.

    Keeping this correct is what makes the family collapse into ONE entry with a
    weight dropdown instead of six separate families in the font menu.
    """
    ital = style.lower().endswith("italic")
    stem = style[: -len("Italic")].strip() if ital else style
    if stem in ("", "Regular"):
        return root, ("Italic" if ital else "Regular")
    if stem == "Bold":
        return root, ("Bold Italic" if ital else "Bold")
    return f"{root} {stem}", ("Italic" if ital else "Regular")


def ps_name(root, style):
    base = "".join(root.split())
    stem = style.replace(" ", "")
    if stem == "Regular":
        stem = "Regular"
    stem = stem.replace("Italic", "It")
    if stem in ("", "It"):
        stem = "Italic" if stem == "It" else "Regular"
    return f"{base}-{stem}"[:63]


def set_name(font, nid, value):
    for pid, eid, lid in (WIN, MAC):
        font["name"].setName(value, nid, pid, eid, lid)


def apply_naming(font, root, style, version="2.000", single_family=False):
    """Unify names so all faces read as one family, and fix the usual breakage.

    Many shipped fonts have nameID 2 == "Regular" on the Windows platform for
    every single face (Bold Italic included). Apps that read the Windows records
    then show the family scattered across menus. Rewriting 1/2/4/6/16/17 from a
    single source of truth fixes that.
    """
    name = font["name"]
    name.names = [r for r in name.names if r.nameID not in (18, 20, 21, 22)]

    if single_family:
        # One legacy family for every face. Modern apps were already collapsing
        # the family via nameIDs 16/17, so this only changes what GDI-era apps
        # see -- and those have exactly four style slots per family, so most
        # faces end up sharing a slot. Measure before shipping it.
        legacy_fam, legacy_sub = root, style
    else:
        legacy_fam, legacy_sub = legacy_pair(root, style)
    # Prefer the foundry's own PostScript name. Existing documents reference it,
    # so inventing a new one silently breaks those files -- and SKILL.md promises
    # we keep it. Only synthesise when the source has none.
    ps = best_name(font, 6) or ps_name(root, style)
    full = f"{root} {style}".strip()

    set_name(font, 1, legacy_fam)
    set_name(font, 2, legacy_sub)
    set_name(font, 3, f"{version};{full}")
    set_name(font, 4, full)
    set_name(font, 5, f"Version {version}")
    set_name(font, 6, ps)
    set_name(font, 16, root)
    set_name(font, 17, style)

    os2, head, post = font["OS/2"], font["head"], font["post"]
    ital = style.lower().endswith("italic")
    bold = legacy_sub in ("Bold", "Bold Italic")

    fs = os2.fsSelection & ~(1 | (1 << 5) | (1 << 6))
    fs |= (1 << 8)                      # WWS: family+style names are regular
    if ital:
        fs |= 1
    if bold:
        fs |= (1 << 5)
    if not ital and not bold:
        fs |= (1 << 6)
    os2.fsSelection = fs

    head.macStyle = (head.macStyle & ~3) | (1 if bold else 0) | (2 if ital else 0)
    try:
        head.fontRevision = float(version)
    except ValueError:
        pass
    if hasattr(os2, "panose"):
        os2.panose.bWeight = PANOSE_WEIGHT.get(os2.usWeightClass, 5)
    if ital and post.italicAngle == 0:
        post.italicAngle = -10.0
    return ps


# -------------------------------------------------------- arabic into italics

def arabic_subset(src_path, out_path):
    """Write a copy of src containing only Arabic glyphs + their layout rules."""
    from fontTools import subset
    font = TTFont(src_path)
    cps = arabic_codepoints(font)
    if not cps:
        font.close()
        return 0
    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.name_legacy = True
    opts.notdef_outline = True
    opts.glyph_names = True
    opts.drop_tables = ["DYNA", "GDYN"]
    sub = subset.Subsetter(options=opts)
    sub.populate(unicodes=cps)
    sub.subset(font)
    font.save(out_path)
    font.close()
    return len(cps)


def graft_arabic(italic_path, upright_path, tmp_dir, out_path):
    """Give an italic face the Arabic of its matching upright weight.

    Type families routinely ship Arabic in the uprights only, so Arabic set in
    an italic run falls back to a system font. Arabic has no italic tradition --
    upright Arabic inside slanted Latin is the accepted convention -- so copying
    the upright glyphs across is a genuine fix, not a compromise.
    """
    from fontTools.merge import Merger
    ar = os.path.join(tmp_dir, "_arabic_subset.otf")
    if not arabic_subset(upright_path, ar):
        return None
    Merger().merge([italic_path, ar]).save(out_path)
    return out_path


# ------------------------------------------------------------- adding a glyph

def _svg_outline(svg_path, cap_height, side_bearing, vb_w, vb_h):
    """SVG path -> recorded pen in font units (y-up, bottom on the baseline)."""
    from fontTools.svgLib.path import SVGPath
    scale = cap_height / vb_h
    rec = RecordingPen()
    SVGPath(svg_path).draw(
        TransformPen(rec, Transform(scale, 0, 0, -scale, side_bearing, cap_height))
    )
    return rec, vb_w * scale


def svg_viewbox(svg_path):
    import re
    text = open(svg_path, encoding="utf-8").read()
    m = re.search(r'viewBox\s*=\s*"([^"]+)"', text)
    if not m:
        raise ValueError(f"no viewBox in {svg_path}")
    x, y, w, h = [float(v) for v in m.group(1).replace(",", " ").split()]
    return w, h


def add_symbol_glyph(font, svg_path, codepoint, glyph_name,
                     cap_ratio=1.0, side_bearing=60, slant=0.0):
    """Insert an SVG-drawn glyph and map it at `codepoint`. Returns advance."""
    order = list(font.getGlyphOrder())
    if glyph_name in order:
        return font["hmtx"][glyph_name][0]

    cap = font["OS/2"].sCapHeight * cap_ratio
    vb_w, vb_h = svg_viewbox(svg_path)
    rec, ink_w = _svg_outline(svg_path, cap, side_bearing, vb_w, vb_h)
    shear = math.tan(math.radians(slant))
    adv = int(round(ink_w + 2 * side_bearing + cap * shear))

    def draw(pen):
        target = TransformPen(pen, Transform(1, 0, shear, 1, 0, 0)) if shear else pen
        rec.replay(target)

    if "CFF " in font:
        cff = font["CFF "].cff
        top = cff[cff.fontNames[0]]
        nominal = getattr(top.Private, "nominalWidthX", 0)
        default = getattr(top.Private, "defaultWidthX", 0)
        # The charstring width operand is an offset from nominalWidthX. Passing
        # the absolute advance here is the bug that adds nominalWidthX units of
        # invisible space in Adobe apps while browsers look fine.
        cff_width = None if adv == default else adv - nominal
        pen = T2CharStringPen(cff_width, font.getGlyphSet())
        draw(pen)
        cs = pen.getCharString(private=top.Private, globalSubrs=top.GlobalSubrs)
        chs = top.CharStrings
        if getattr(chs, "charStringsAreIndexed", False):
            chs.charStringsIndex.append(cs)
            chs.charStrings[glyph_name] = len(chs.charStringsIndex) - 1
        else:
            chs.charStrings[glyph_name] = cs
        if glyph_name not in top.charset:
            top.charset.append(glyph_name)
    else:
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        from fontTools.pens.cu2quPen import Cu2QuPen
        pen = TTGlyphPen(font.getGlyphSet())
        draw(Cu2QuPen(pen, max_err=1.0))
        font["glyf"].glyphs[glyph_name] = pen.glyph()

    font.setGlyphOrder(order + [glyph_name])
    if hasattr(font, "_reverseGlyphOrderDict"):
        del font._reverseGlyphOrderDict
    font["hmtx"].metrics[glyph_name] = (adv, int(round(side_bearing)))
    font["maxp"].numGlyphs = len(order) + 1
    for table in font["cmap"].tables:
        if table.isUnicode():
            table.cmap[codepoint] = glyph_name
    if "GDEF" in font:
        gdef = font["GDEF"].table
        if gdef.GlyphClassDef is not None:
            gdef.GlyphClassDef.classDefs[glyph_name] = 1  # base glyph
    return adv


# ------------------------------------------------- typing shortcuts via calt

def letter_glyphs(font):
    out = set()
    for cp, gn in font.getBestCmap().items():
        try:
            if unicodedata.category(chr(cp)).startswith("L"):
                out.add(gn)
        except ValueError:
            pass
    return out


def text_to_glyphs(font, text):
    """Map a literal string to base glyph names via cmap, or None if any are absent."""
    cmap = font.getBestCmap()
    out = []
    for ch in text:
        gn = cmap.get(ord(ch))
        if gn is None:
            return None
        out.append(gn)
    return out


def add_shortcuts(font, mapping, feature_tag="calt"):
    """Make typed sequences turn into glyphs, but only as whole tokens.

    `mapping` is a list of (glyph_name_sequence, target_glyph). One call handles
    every currency at once so the font ends up with a single ligature lookup and
    a single chain-context lookup rather than a pile of near-duplicates.

    A plain ligature would rewrite "COMRADE" to "C<symbol>ADE" in any all-caps
    heading, and "SARAH" to "<symbol>AH". So each distinct starting context gets
    two blocking rules first (letter before / letter after). OpenType applies the
    first matching subtable in a lookup and stops, which is exactly what FEA's
    `ignore` statements compile to -- and because the blockers require a
    neighbouring glyph, a token at the start of a line still falls through to the
    real rule.
    """
    if not mapping:
        return 0
    gsub = _ensure_gsub(font)
    gmap = {g: i for i, g in enumerate(font.getGlyphOrder())}

    usable = [(seq, tgt) for seq, tgt in mapping
              if tgt in gmap and all(g in gmap for g in seq)]
    if not usable:
        return 0
    letters = letter_glyphs(font) & set(gmap)

    lig = otl.buildLigatureSubstSubtable({tuple(seq): tgt for seq, tgt in usable})
    lookups = gsub.LookupList.Lookup
    lig_idx = len(lookups)
    lookups.append(otl.buildLookup([lig], flags=0))

    def cov(glyphs):
        return otl.buildCoverage(set(glyphs), gmap)

    def chain(back, inp, ahead, substitute):
        st = ot.ChainContextSubst()
        st.Format = 3
        st.BacktrackGlyphCount = len(back)
        st.BacktrackCoverage = [cov(g) for g in back]
        st.InputGlyphCount = len(inp)
        st.InputCoverage = [cov(g) for g in inp]
        st.LookAheadGlyphCount = len(ahead)
        st.LookAheadCoverage = [cov(g) for g in ahead]
        if substitute:
            rec = ot.SubstLookupRecord()
            rec.SequenceIndex = 0
            rec.LookupListIndex = lig_idx
            st.SubstLookupRecord = [rec]
        else:
            st.SubstLookupRecord = []
        st.SubstCount = len(st.SubstLookupRecord)
        return st

    # One context per distinct first-three glyphs. The ligature lookup itself
    # picks the longest match from that point, so trailing variants ("ر.س." vs
    # "ر.س") need no extra context.
    contexts, seen = [], set()
    for seq, _ in sorted(usable, key=lambda x: len(x[0])):
        key = tuple(seq[:3])
        if key not in seen:
            seen.add(key)
            contexts.append([{g} for g in key])

    subtables = []
    for ctx in contexts:                      # blockers first
        subtables.append(chain([letters], ctx, [], False))
        subtables.append(chain([], ctx, [letters], False))
    for ctx in contexts:                      # then the real substitution
        subtables.append(chain([], ctx, [], True))

    ctx_idx = len(lookups)
    lookups.append(otl.buildLookup(subtables, flags=0))
    gsub.LookupList.LookupCount = len(lookups)

    patched, seen_feats = 0, set()
    for frec in gsub.FeatureList.FeatureRecord:
        if frec.FeatureTag != feature_tag or id(frec.Feature) in seen_feats:
            continue
        seen_feats.add(id(frec.Feature))
        frec.Feature.LookupListIndex.append(ctx_idx)
        frec.Feature.LookupCount = len(frec.Feature.LookupListIndex)
        patched += 1

    if patched == 0:
        patched = _register_new_feature(gsub, feature_tag, ctx_idx)
    return patched


def _ensure_gsub(font):
    """Return the font's GSUB table, creating an empty one if it has none.

    Nearly every retail font has a GSUB. A few simple Latin faces do not, and
    without this they would silently come out with no shortcuts at all while the
    build reported success.
    """
    if "GSUB" in font:
        return font["GSUB"].table

    from fontTools.ttLib import newTable

    langsys = ot.LangSys()
    langsys.LookupOrder = None
    langsys.ReqFeatureIndex = 0xFFFF
    langsys.FeatureIndex = []
    langsys.FeatureCount = 0

    script = ot.Script()
    script.DefaultLangSys = langsys
    script.LangSysRecord = []
    script.LangSysCount = 0

    srec = ot.ScriptRecord()
    srec.ScriptTag = "DFLT"
    srec.Script = script

    table = ot.GSUB()
    table.Version = 0x00010000
    table.ScriptList = ot.ScriptList()
    table.ScriptList.ScriptRecord = [srec]
    table.ScriptList.ScriptCount = 1
    table.FeatureList = ot.FeatureList()
    table.FeatureList.FeatureRecord = []
    table.FeatureList.FeatureCount = 0
    table.LookupList = ot.LookupList()
    table.LookupList.Lookup = []
    table.LookupList.LookupCount = 0

    font["GSUB"] = newTable("GSUB")
    font["GSUB"].table = table
    return table


def _register_new_feature(gsub, tag, lookup_idx):
    """Add `tag` to every script/langsys when the font has no such feature."""
    feat = ot.Feature()
    feat.FeatureParams = None
    feat.LookupListIndex = [lookup_idx]
    feat.LookupCount = 1
    frec = ot.FeatureRecord()
    frec.FeatureTag = tag
    frec.Feature = feat
    fl = gsub.FeatureList
    fl.FeatureRecord.append(frec)
    fl.FeatureCount = len(fl.FeatureRecord)
    idx = len(fl.FeatureRecord) - 1
    count = 0
    for srec in gsub.ScriptList.ScriptRecord:
        for ls in [srec.Script.DefaultLangSys] + list(srec.Script.LangSysRecord or []):
            langsys = ls if hasattr(ls, "FeatureIndex") else getattr(ls, "LangSys", None)
            if langsys is None:
                continue
            langsys.FeatureIndex.append(idx)
            langsys.FeatureCount = len(langsys.FeatureIndex)
            count += 1
    return count


# ------------------------------------------------------------------- writing

def recalc_os2(font, extra_codepage_bits=()):
    os2 = font["OS/2"]
    if hasattr(os2, "recalcUnicodeRanges"):
        os2.recalcUnicodeRanges(font)
    for bit in extra_codepage_bits:
        os2.ulCodePageRange1 |= (1 << bit)


def cff_to_glyf(font, max_err=1.0):
    """Convert CFF (cubic) outlines to TrueType (quadratic) in place.

    Why this exists: the Windows font installer does not register the .otc
    extension, so a CFF-based collection has no "Install" action in Explorer at
    all -- the user is stuck even though the file is spec-legal. Windows has
    shipped .ttc support since forever (its own system fonts are .ttc), so a
    TrueType collection is the format that actually installs everywhere.

    The cost is honest and worth stating: cubic curves are approximated by
    quadratics (max_err is in font units, ~0.1% of the em at the default) and
    CFF hinting is dropped. Shapes are visually identical at any normal size;
    only sub-pixel hinting at very small sizes differs. Prefer the CFF original
    when Windows is not a target.
    """
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.ttLib import newTable

    if "glyf" in font:
        return font
    order = font.getGlyphOrder()
    glyph_set = font.getGlyphSet()
    glyphs = {}
    for name in order:
        pen = TTGlyphPen(glyph_set)
        glyph_set[name].draw(Cu2QuPen(pen, max_err, reverse_direction=True))
        glyphs[name] = pen.glyph()

    glyf = newTable("glyf")
    glyf.glyphOrder = order
    glyf.glyphs = glyphs
    font["glyf"] = glyf
    font["loca"] = newTable("loca")

    maxp = font["maxp"]
    maxp.tableVersion = 0x00010000
    for attr, val in (("maxZones", 1), ("maxTwilightPoints", 0), ("maxStorage", 0),
                      ("maxFunctionDefs", 0), ("maxInstructionDefs", 0),
                      ("maxStackElements", 0), ("maxSizeOfInstructions", 0),
                      ("maxComponentElements", 0), ("maxComponentDepth", 0)):
        setattr(maxp, attr, val)

    post = font["post"]
    post.formatType = 2.0
    post.extraNames = []
    post.mapping = {}
    post.glyphOrder = order

    del font["CFF "]
    font.sfntVersion = "\x00\x01\x00\x00"
    font.recalcBBoxes = True
    return font


def save_collection(fonts, out_path):
    coll = TTCollection()
    coll.fonts = fonts
    coll.save(out_path, shareTables=True)
    return out_path


def glyph_bounds(font, glyph_name):
    gs = font.getGlyphSet()
    pen = BoundsPen(gs)
    gs[glyph_name].draw(pen)
    return pen.bounds


def cff_advance(font, glyph_name):
    """Advance as encoded in the charstring (what Adobe's engine reads)."""
    if "CFF " not in font:
        return font["hmtx"][glyph_name][0]
    from fontTools.misc.psCharStrings import T2WidthExtractor
    cff = font["CFF "].cff
    top = cff[cff.fontNames[0]]
    priv = top.Private
    ex = T2WidthExtractor([], top.GlobalSubrs,
                          priv.nominalWidthX, priv.defaultWidthX)
    ex.localSubrs = getattr(priv, "Subrs", [])
    ex.execute(top.CharStrings[glyph_name])
    return ex.width
