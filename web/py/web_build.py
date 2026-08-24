"""Browser-side entry points around fontkit. Runs inside Pyodide, in a worker.

Everything here is called from worker.js with plain JSON in and plain JSON out;
output fonts are left in the Pyodide filesystem for JS to read back as bytes.

Two things live here that the command-line tool never needed:

* `inspect_paths` decides the ROUTE (merge vs symbols-only) and reads the two
  legal signals the foundry put in the file itself -- OS/2.fsType and the
  license records. The user does not get to override the route; the file does.

* Variable fonts. Appending a glyph to a variable font corrupts its advance
  widths in two different ways depending on when fontTools decompiles HVAR --
  see `neutralise_advance_variation`. That is the single reason the merge path
  is hidden for variable input.
"""

import json
import os
import re
import string
import time

from fontTools.ttLib import TTFont, TTCollection
from fontTools.ttLib.tables import otTables as ot

import fontkit as fk

TOOL_STAMP = "modified with font-currency-tool (web)"

# fsType is a bitfield, and bit 1 alone means Restricted License Embedding:
# the foundry is saying "no". Bits 2/3 are preview-print / editable, which are
# permissive. Bit 8 (no subsetting) and 9 (bitmap only) do not block us.
FSTYPE_RESTRICTED = 0x0002

OFL_MARKERS = ("open font license", "openfontlicense", "scripts.sil.org/ofl")

# The OFL only forbids reusing a name that the font actually RESERVES. Clause 3
# reads "No Modified Version of the Font Software may use the Reserved Font
# Name(s) unless explicit written permission is granted" -- so a font under the
# OFL that declares no reserved name may keep its name after modification.
# The declaration lives in the copyright notice: "... with Reserved Font Name Foo."
_RFN_RE = re.compile(r"with\s+reserved\s+font\s+names?\s*[:\-]?\s*(.+?)(?:\.\s|\.$|$)",
                     re.IGNORECASE | re.DOTALL)
_QUOTED_RE = re.compile(r"[\"\u201c\u2018']([^\"\u201d\u2019']+)[\"\u201d\u2019']")


def _reserved_font_names(*texts):
    """Names this font reserves, or [] if it reserves none."""
    for text in texts:
        if not text:
            continue
        m = _RFN_RE.search(text)
        if not m:
            continue
        tail = m.group(1).strip()
        quoted = _QUOTED_RE.findall(tail)
        if quoted:
            return [q.strip() for q in quoted if q.strip()]
        # Unquoted form: "with Reserved Font Name Foo Bar" -- take the phrase up
        # to a conjunction or a sentence end.
        parts = re.split(r"\s+and\s+|,", tail)
        names = [p.strip(" .\"'") for p in parts]
        return [n for n in names if n]
    return []


# --------------------------------------------------------------- inspection

def _name(font, *nids):
    return fk.best_name(font, *nids)


def _uses_reserved_name(font, reserved):
    """Does this font's own name actually USE one of the reserved names?

    Clause 3 ends with "This restriction only applies to the primary font name
    as presented to the users." Readex Pro is the case that makes this matter:
    it reserves "RevReading Lexend", a name it does not itself carry, so a
    modified Readex Pro never touches the reserved name and needs no rename.
    """
    names = " ".join(_name(font, nid) for nid in (16, 1, 4)).lower()
    names = " ".join(names.split())
    return [r for r in reserved if " ".join(r.lower().split()) in names]


def _license_info(font):
    """What the file itself says about its licence. nameID 13 is the text, 14 the URL."""
    desc = _name(font, 13)
    url = _name(font, 14)
    copyright_ = _name(font, 0)
    hay = (desc + " " + url).lower()
    ofl = any(m in hay for m in OFL_MARKERS)
    reserved = _reserved_font_names(copyright_, desc) if ofl else []
    # Two separate questions: what the file reserves, and whether its own name
    # actually uses any of it. Only the second obliges a rename.
    conflicting = _uses_reserved_name(font, reserved)
    return {
        "description": desc[:400],
        "url": url,
        "copyright": copyright_[:300],
        "ofl": ofl,
        "reserved_names": reserved,
        "conflicting_names": conflicting,
        "rename_required": bool(conflicting),
        "present": bool(desc or url),
    }


def _fstype_info(font):
    bits = int(getattr(font["OS/2"], "fsType", 0) or 0)
    return {
        "value": bits,
        "restricted": bool(bits & FSTYPE_RESTRICTED),
    }


def _axes(font):
    if "fvar" not in font:
        return []
    return [{"tag": a.axisTag, "min": a.minValue,
             "default": a.defaultValue, "max": a.maxValue}
            for a in font["fvar"].axes]


def _outline_format(font):
    if "CFF2" in font:
        return "CFF2"
    if "CFF " in font:
        return "CFF"
    return "glyf"


def inspect_paths(paths):
    """Survey the uploaded files and decide the route. Returns a JSON-able dict."""
    faces, fonts = [], []
    for p in paths:
        try:
            fonts.append(TTFont(p, lazy=True))
        except Exception as exc:
            faces.append({"file": os.path.basename(p), "unreadable": repr(exc)})
    readable = [p for p in paths if os.path.basename(p) not in
                {f["file"] for f in faces if f.get("unreadable")}]

    if not fonts:
        return {"ok": False, "faces": faces, "error": "no readable font files"}

    root = fk.family_root(fonts)
    problems, warnings = [], []

    for path, font in zip(readable, fonts):
        fmt = _outline_format(font)
        variable = "fvar" in font
        lic = _license_info(font)
        fst = _fstype_info(font)
        style = fk.style_name(font, root)
        entry = {
            "file": os.path.basename(path),
            "path": path,
            "bytes": os.path.getsize(path),
            "style": style,
            "family": _name(font, 16, 1),
            "ps_name": _name(font, 6),
            "weight": font["OS/2"].usWeightClass,
            "italic": fk.is_italic(font),
            "glyphs": len(font.getGlyphOrder()),
            "arabic_letters": len(fk.arabic_letters(font)),
            "format": fmt,
            "variable": variable,
            "axes": _axes(font),
            "upem": font["head"].unitsPerEm,
            "cap_height": getattr(font["OS/2"], "sCapHeight", 0) or 0,
            "version": _name(font, 5),
            "has_arabic_layout": "arab" in fk.gsub_scripts(font),
            "license": lic,
            "fstype": fst,
        }
        faces.append(entry)

        win_sub = font["name"].getName(2, *fk.WIN)
        if win_sub and str(win_sub).strip() == "Regular" and style != "Regular":
            problems.append({"file": entry["file"], "kind": "win_subfamily",
                             "detail": style})

    real = [f for f in faces if not f.get("unreadable")]
    variable_files = [f["file"] for f in real if f["variable"]]
    blocked = [f["file"] for f in real if f["fstype"]["restricted"]]
    ofl = any(f["license"]["ofl"] for f in real)
    reserved_names = sorted({n for f in real for n in f["license"]["conflicting_names"]})
    declared_names = sorted({n for f in real for n in f["license"]["reserved_names"]})
    cff2 = [f["file"] for f in real if f["format"] == "CFF2"]

    # The route is decided by the files, never by the user (plan section 4.1).
    if blocked:
        route = "blocked"
    elif variable_files:
        route = "symbols-only"
    else:
        route = "merge"

    upems = sorted({f["upem"] for f in real})
    if len(upems) > 1:
        warnings.append({"kind": "mixed_upem", "detail": upems})

    ups = [f for f in real if not f["italic"]]
    its = [f for f in real if f["italic"]]
    up_ar = max((f["arabic_letters"] for f in ups), default=0)
    it_ar = max((f["arabic_letters"] for f in its), default=0)
    can_graft = bool(ups and its and up_ar > 0 and it_ar == 0)
    if can_graft:
        warnings.append({"kind": "italics_without_arabic", "detail": up_ar})

    if cff2:
        warnings.append({"kind": "cff2", "detail": cff2})

    ps_names = [f["ps_name"] for f in real if f["ps_name"]]
    dupes = sorted({n for n in ps_names if ps_names.count(n) > 1})

    for f in fonts:
        f.close()

    return {
        "ok": True,
        "route": route,
        "family_root": root,
        "faces": real,
        "unreadable": [f for f in faces if f.get("unreadable")],
        "variable_files": variable_files,
        "blocked_files": blocked,
        "ofl": ofl,
        # `reserved_names` is only what actually conflicts with this family's
        # own name -- that is what obliges a rename. `declared_names` is
        # everything the files reserve, conflicting or not.
        "reserved_names": reserved_names,
        "declared_reserved_names": declared_names,
        "rename_required": bool(reserved_names),
        "cff2_files": cff2,
        "can_graft_arabic": can_graft,
        "duplicate_ps_names": dupes,
        "name_problems": problems,
        "warnings": warnings,
        "total_bytes": sum(f["bytes"] for f in real),
    }


# ------------------------------------------------- variable-font advance fix

def _zero_variation_index(varstore):
    """A delta-set index that is guaranteed to resolve to zero for every axis.

    Prefers an all-zero row that already exists so the table does not grow;
    falls back to a region-less ItemVariationData, whose delta is zero by
    construction (a sum over no regions).
    """
    for outer, vd in enumerate(varstore.VarData):
        for inner, item in enumerate(vd.Item):
            if all(v == 0 for v in item):
                return (outer << 16) | inner
    vd = ot.VarData()
    vd.VarRegionIndex = []
    vd.VarRegionCount = 0
    vd.Item = [[]]
    vd.ItemCount = 1
    vd.NumShorts = 0
    varstore.VarData.append(vd)
    varstore.VarDataCount = len(varstore.VarData)
    return ((len(varstore.VarData) - 1) << 16) | 0


def snapshot_advance_maps(font):
    """Materialise HVAR/VVAR index maps against the CURRENT glyph order.

    Must be called BEFORE any glyph is appended. `VarIdxMap.postRead` pads a
    short map by repeating its last entry, so if the table is first decompiled
    after a glyph was added, the new glyph silently inherits its neighbour's
    width deltas. Reading the maps here, while the glyph order is still the
    original one, makes that impossible.
    """
    snap = {}
    for tag in ("HVAR", "VVAR"):
        if tag not in font:
            continue
        table = font[tag].table
        for attr in ("AdvWidthMap", "AdvHeightMap", "LsbMap", "RsbMap",
                     "TsbMap", "BsbMap", "VOrgMap"):
            sub = getattr(table, attr, None)
            if sub is not None and getattr(sub, "mapping", None) is not None:
                snap[(tag, attr)] = dict(sub.mapping)
    return snap


def neutralise_advance_variation(font, glyph_names, snapshot):
    """Pin new glyphs to zero advance-width variation across every axis.

    Returns a short report so the UI can say what it did rather than claiming
    something happened invisibly.
    """
    report = {"applied": False, "maps": [], "note": ""}
    if not glyph_names:
        return report

    for tag in ("HVAR", "VVAR"):
        if tag not in font:
            continue
        table = font[tag].table
        zero = _zero_variation_index(table.VarStore)
        for attr in ("AdvWidthMap", "AdvHeightMap", "LsbMap", "RsbMap",
                     "TsbMap", "BsbMap", "VOrgMap"):
            sub = getattr(table, attr, None)
            if sub is None:
                continue
            base = snapshot.get((tag, attr))
            if base is None:
                continue
            mapping = dict(base)          # original glyphs, original indices
            for gn in glyph_names:
                mapping[gn] = zero
            sub.mapping = mapping
            report["maps"].append(f"{tag}.{attr}")
            report["applied"] = True

        # An implicit map (no VarIdxMap at all) means glyphID *is* the delta-set
        # index, so a glyph appended at index N would pick up row N of someone
        # else's data. Materialise identity for the old glyphs and zero for ours.
        if getattr(table, "AdvWidthMap", None) is None and tag == "HVAR":
            order = font.getGlyphOrder()
            new = set(glyph_names)
            mapping = {gn: (zero if gn in new else i)
                       for i, gn in enumerate(order)}
            vim = ot.VarIdxMap()
            vim.mapping = mapping
            table.AdvWidthMap = vim
            report["maps"].append("HVAR.AdvWidthMap (created; was implicit)")
            report["applied"] = True

    if report["applied"]:
        report["note"] = "new glyphs pinned to zero advance variation"
    return report


# -------------------------------------------------- differential verification

# Sampled rather than exhaustive: enough coverage to catch real damage without
# walking 60k codepoints on a phone.
_PROBE_RANGES = [
    (0x0020, 0x007E), (0x00A0, 0x017F), (0x0600, 0x06FF), (0x0750, 0x077F),
    (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF), (0x2000, 0x206F),
    (0x20A0, 0x20CF),
]


def signature(font, extra_codepoints=()):
    """What must not get worse. Compared against the source, never a standard.

    `extra_codepoints` are probed on top of the sampled ranges. Custom currency
    symbols live in the Private Use Area, which the ranges deliberately do not
    sample -- without this the verifier cannot see the very symbol it just
    added, and reports it missing.
    """
    cmap = font.getBestCmap()
    covered = {cp for lo, hi in _PROBE_RANGES for cp in range(lo, hi + 1)
               if cp in cmap}
    covered |= {cp for cp in extra_codepoints if cp in cmap}
    adv_bad = 0
    if "CFF " in font:
        hmtx = font["hmtx"]
        for gn in font.getGlyphOrder():
            try:
                if fk.cff_advance(font, gn) != hmtx[gn][0]:
                    adv_bad += 1
            except Exception:
                continue
    return {
        "codepoints": covered,
        "glyphs": len(font.getGlyphOrder()),
        "arabic": len(fk.arabic_letters(font)),
        "advance_mismatches": adv_bad,
        "gsub_features": sorted(fk.gsub_features(font)),
    }


def compare(before, after, expected_new):
    """Findings for one face. Only regressions relative to `before` are failures."""
    findings = []
    lost = sorted(before["codepoints"] - after["codepoints"])
    if lost:
        findings.append({
            "level": "fail", "kind": "codepoints_lost", "count": len(lost),
            "sample": ["U+%04X" % c for c in lost[:12]],
        })
    missing = sorted(set(expected_new) - after["codepoints"])
    if missing:
        findings.append({
            "level": "fail", "kind": "symbol_missing",
            "sample": ["U+%04X" % c for c in missing],
        })
    if after["arabic"] < before["arabic"]:
        findings.append({
            "level": "fail", "kind": "arabic_lost",
            "count": before["arabic"] - after["arabic"],
        })
    new_adv = after["advance_mismatches"] - before["advance_mismatches"]
    if new_adv > 0:
        findings.append({
            "level": "fail", "kind": "advance_mismatch_new", "count": new_adv,
        })
    lost_feats = sorted(set(before["gsub_features"]) - set(after["gsub_features"]))
    if lost_feats:
        findings.append({
            "level": "warn", "kind": "gsub_features_lost", "sample": lost_feats,
        })
    # Pre-existing damage is reported, but never as our failure.
    if before["advance_mismatches"]:
        findings.append({
            "level": "note", "kind": "advance_mismatch_pre_existing",
            "count": before["advance_mismatches"],
        })
    gained = sorted(after["codepoints"] - before["codepoints"])
    return {
        "findings": findings,
        "gained": ["U+%04X" % c for c in gained[:12]],
        "glyphs_before": before["glyphs"],
        "glyphs_after": after["glyphs"],
        "arabic_before": before["arabic"],
        "arabic_after": after["arabic"],
    }


# ------------------------------------------------------------------- build

def _load_currencies(manifest_path, only=None):
    """`only` is a list of currency ids, or None for all of them.

    Anything that is not a real list counts as "all". JavaScript's `null`
    crosses the Pyodide bridge as a JsNull sentinel rather than None, so an
    `is not None` test alone lets it through and then fails on `in`.
    """
    if not isinstance(only, (list, tuple, set)):
        only = None
    with open(manifest_path, encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for c in data["currencies"]:
        if only is not None and c["id"] not in only:
            continue
        cp = int(c["codepoint"], 16)
        out.append({
            "id": c["id"], "name": c["name"], "name_ar": c.get("name_ar", ""),
            "codepoint": cp, "glyph": "uni%04X" % cp,
            "svg": os.path.join(os.path.dirname(manifest_path), c["svg"]),
            "latin": c.get("latin", []), "arabic": c.get("arabic", []),
        })
    return out


# Unicode has assigned symbols to only a handful of currencies. A country whose
# symbol has not been encoded yet has no codepoint to put a glyph at, so the
# Private Use Area is the correct home: it is reserved precisely for characters
# that are not, and may never be, standardised. The cost is that PUA characters
# mean nothing outside fonts that define them, which the interface says plainly.
PUA_RANGE = (0xE000, 0xF8FF)
CURRENCY_BLOCK = (0x20A0, 0x20CF)


def validate_custom(entry, source_cmaps):
    """Check one user-supplied currency before it can damage anything.

    Returns a list of problems; empty means usable. The codepoint check is the
    one that matters: `add_symbol_glyph` writes straight into the cmap, so a
    codepoint that is already mapped would silently replace a real character --
    pick U+0041 and every capital A in the font becomes a currency symbol.
    """
    problems = []
    cp = entry.get("codepoint")
    if not isinstance(cp, int) or not (0 < cp <= 0x10FFFF):
        problems.append({"kind": "codepoint_invalid"})
        return problems
    if 0xD800 <= cp <= 0xDFFF:
        problems.append({"kind": "codepoint_surrogate"})
    for taken in source_cmaps:
        if cp in taken:
            problems.append({"kind": "codepoint_taken", "codepoint": cp})
            break
    svg = entry.get("svg")
    if not svg or not os.path.exists(svg):
        problems.append({"kind": "svg_missing"})
    else:
        try:
            w, h = fk.svg_viewbox(svg)
            if not (w > 0 and h > 0):
                problems.append({"kind": "svg_viewbox_empty"})
        except Exception:
            # fontkit needs a viewBox to scale the artwork to cap height.
            problems.append({"kind": "svg_no_viewbox"})
    return problems


def _shortcut_mapping(font, currencies):
    order = set(font.getGlyphOrder())
    mapping = []
    for cur in currencies:
        if cur["glyph"] not in order:
            continue
        for text in sorted(cur["latin"] + cur["arabic"], key=len, reverse=True):
            seq = fk.text_to_glyphs(font, text)
            if seq:
                mapping.append((seq, cur["glyph"]))
    return mapping


# The OpenType spec limits PostScript names to printable ASCII, minus the
# characters that are delimiters in PostScript itself.
_PS_ALLOWED = set(string.ascii_letters + string.digits + "-_.")


def _ascii_ps(value, fallback="Font"):
    return ("".join(ch for ch in value if ch in _PS_ALLOWED) or fallback)[:63]


def _prune_unencodable_names(font):
    """Drop name records their own platform encoding cannot represent.

    Mac platform records are mac_roman, which has no Arabic at all -- so a font
    whose family name is Arabic, which is precisely this tool's audience, fails
    to save with a UnicodeEncodeError before anything else can go wrong. The
    Windows records are UTF-16 and carry the name perfectly, and every current
    system reads those, so dropping the unencodable half is the correct fix
    rather than a workaround.
    """
    name = font["name"]
    kept, dropped = [], []
    for rec in name.names:
        try:
            rec.toBytes()
            kept.append(rec)
        except Exception:
            dropped.append((rec.nameID, rec.platformID))
    name.names = kept
    return dropped


def _renamed_ps_name(font, suffix, style):
    """A fresh PostScript name for a renamed font, guaranteed ASCII.

    Built from the OLD PostScript name rather than from the display family,
    because the display family may be Arabic while nameID 6 is ASCII by spec.
    Renaming matters here: under the OFL the reserved name must change, and
    leaving nameID 6 alone would leave it sitting in the file.
    """
    suf = _ascii_ps(suffix, "")
    old = _name(font, 6)
    if old:
        fam, sep, sty = old.partition("-")
        sty = sty or _ascii_ps(style.replace(" ", ""), "Regular")
        return _ascii_ps(f"{fam}{suf}-{sty}", "Font-Regular")
    return _ascii_ps(f"{suf}-{style.replace(' ', '')}", "Font-Regular")


def _stamp(font, version):
    """Leave a visible trace inside the file that it was modified, and by what."""
    fk.set_name(font, 5, f"Version {version}; {TOOL_STAMP}")


def _add_symbols(font, currencies, side_bearing, cap_ratio, slant=0.0):
    if not getattr(font["OS/2"], "sCapHeight", 0):
        font["OS/2"].sCapHeight = int(font["head"].unitsPerEm * 0.71)
    names = []
    for cur in currencies:
        fk.add_symbol_glyph(font, cur["svg"], cur["codepoint"], cur["glyph"],
                            cap_ratio=cap_ratio, side_bearing=side_bearing,
                            slant=slant)
        names.append(cur["glyph"])
    return names


def _apply_rename(font, suffix, style):
    """Install the new PostScript name before apply_naming reads nameID 6."""
    fk.set_name(font, 6, _renamed_ps_name(font, suffix, style))


def build(paths, opts, progress=None):
    """Run the whole job. Writes outputs into `out_dir`; returns a manifest."""
    def tell(pct, key, detail=""):
        if progress:
            progress(pct, key, detail)

    started = time.time()
    out_dir = opts["out_dir"]
    os.makedirs(out_dir, exist_ok=True)

    route = opts.get("route", "merge")
    version = str(opts.get("version", "2.000"))
    rename_suffix = (opts.get("rename_suffix") or "").strip()
    only = opts.get("currencies")            # list of ids; [] means none at all
    if not isinstance(only, (list, tuple, set)):
        only = None                          # see _load_currencies
    currencies = [] if only is not None and not only \
        else _load_currencies(opts["manifest"], only)

    # Currencies the user supplied artwork for, for symbols Unicode has not
    # encoded. Validated against the SOURCE fonts, before anything is written.
    custom = opts.get("custom_currencies") or []
    custom_problems = []
    if custom:
        source_cmaps = []
        for path in paths:
            probe = TTFont(path, lazy=True)
            source_cmaps.append(set(probe.getBestCmap()))
            probe.close()
        taken = {c["codepoint"] for c in currencies}
        for entry in custom:
            problems = validate_custom(entry, source_cmaps)
            if entry.get("codepoint") in taken:
                problems.append({"kind": "codepoint_duplicate"})
            if problems:
                custom_problems.append({"id": entry.get("id"), "problems": problems})
                continue
            taken.add(entry["codepoint"])
            currencies.append({
                "id": entry["id"],
                "name": entry.get("name") or entry["id"],
                "name_ar": entry.get("name_ar", ""),
                "codepoint": entry["codepoint"],
                "glyph": "uni%04X" % entry["codepoint"],
                "svg": entry["svg"],
                "latin": entry.get("latin", []),
                "arabic": entry.get("arabic", []),
                "custom": True,
            })
        if custom_problems and not currencies:
            raise ValueError("no usable currency: " + json.dumps(custom_problems))
    side_bearing = float(opts.get("side_bearing", 60))
    cap_ratio = float(opts.get("cap_ratio", 1.0))
    want_shortcuts = bool(opts.get("shortcuts", True))
    want_graft = bool(opts.get("arabic_graft", True))
    fmt = opts.get("format", "auto")         # auto | otc | ttc | single
    want_woff2 = bool(opts.get("woff2", False))

    probes = [TTFont(p, lazy=True) for p in paths]
    root = opts.get("family") or fk.family_root(probes)
    if rename_suffix:
        root = f"{root} {rename_suffix}"

    plan = []
    upright_by_weight = {}
    for path, font in zip(paths, probes):
        entry = {"path": path,
                 "style": fk.style_name(font, opts.get("family")
                                        or fk.family_root(probes)),
                 "weight": font["OS/2"].usWeightClass,
                 "italic": fk.is_italic(font),
                 "arabic": len(fk.arabic_letters(font))}
        plan.append(entry)
        if not entry["italic"]:
            upright_by_weight.setdefault(entry["weight"], entry)
    for f in probes:
        f.close()
    plan.sort(key=lambda e: (e["weight"], e["italic"]))

    # Probed explicitly in every signature, so a symbol outside the sampled
    # ranges (any custom one) is still verified.
    expected_codepoints = [c["codepoint"] for c in currencies]

    faces_out, reports = [], []
    n = len(plan)
    tmp = "/tmp/fcbuild"
    os.makedirs(tmp, exist_ok=True)

    for i, entry in enumerate(plan):
        base = 5 + int(75 * i / max(n, 1))
        tell(base, "face", entry["style"])
        src, grafted = entry["path"], False

        if (route == "merge" and want_graft and entry["italic"]
                and entry["arabic"] == 0):
            peer = upright_by_weight.get(entry["weight"])
            if peer and peer["arabic"] > 0:
                tell(base + 2, "graft", entry["style"])
                dest = os.path.join(tmp, f"graft_{i}.otf")
                try:
                    if fk.graft_arabic(src, peer["path"], tmp, dest):
                        src, grafted = dest, True
                except Exception:
                    grafted = False

        font = TTFont(src)
        before = signature(font, expected_codepoints)

        # Read the variation index maps while the glyph order is still original.
        var_snapshot = snapshot_advance_maps(font)

        for tag in ("DYNA", "GDYN"):
            if tag in font:
                del font[tag]

        tell(base + 4, "symbols", entry["style"])
        added = _add_symbols(font, currencies, side_bearing, cap_ratio) \
            if currencies else []

        var_report = neutralise_advance_variation(font, added, var_snapshot)

        shortcuts = 0
        if currencies and want_shortcuts:
            tell(base + 6, "shortcuts", entry["style"])
            shortcuts = fk.add_shortcuts(font, _shortcut_mapping(font, currencies))

        if route == "merge":
            if rename_suffix:
                _apply_rename(font, rename_suffix, entry["style"])
            ps = fk.apply_naming(font, root, entry["style"], version)
        else:
            # A single variable file: keep its structure, only touch identity.
            if rename_suffix:
                _apply_rename(font, rename_suffix, entry["style"])
                fk.set_name(font, 1, root)
                fk.set_name(font, 16, root)
                fk.set_name(font, 4, f"{root} {entry['style']}".strip())
            ps = _name(font, 6) or fk.ps_name(root, entry["style"])
        _stamp(font, version)

        fk.recalc_os2(font, extra_codepage_bits=(6,))

        if fmt == "ttc" and "CFF " in font:
            tell(base + 8, "outlines", entry["style"])
            fk.cff_to_glyf(font)

        dropped_names = _prune_unencodable_names(font)

        ext = ".otf" if "CFF " in font else ".ttf"
        face_path = os.path.join(out_dir, f"{_ascii_ps(ps, 'Font-Regular')}{ext}")
        font.save(face_path)

        after = signature(font, expected_codepoints)
        expected = expected_codepoints
        reports.append({
            "face": f"{root} {entry['style']}".strip(),
            "ps": ps, "file": os.path.basename(face_path),
            "bytes": os.path.getsize(face_path),
            "weight": entry["weight"], "italic": entry["italic"],
            "grafted": grafted, "symbols": len(added), "shortcuts": shortcuts,
            "dropped_mac_names": len(dropped_names),
            "variable_fix": var_report,
            "verify": compare(before, after, expected),
        })
        faces_out.append(face_path)

        font.close()
        del font, before, after, var_snapshot     # one face in memory at a time

    outputs = []
    for p in faces_out:
        outputs.append({"path": p, "name": os.path.basename(p), "kind": "face",
                        "bytes": os.path.getsize(p)})

    if route == "merge" and fmt in ("auto", "otc", "ttc") and len(faces_out) > 1:
        tell(85, "collection")
        reopened = [TTFont(p) for p in faces_out]
        ext = ".otc" if "CFF " in reopened[0] else ".ttc"
        if fmt == "otc":
            ext = ".otc"
        coll_path = os.path.join(out_dir, f"{root}{ext}")
        fk.save_collection(reopened, coll_path)
        for f in reopened:
            f.close()
        del reopened
        outputs.insert(0, {"path": coll_path, "name": os.path.basename(coll_path),
                           "kind": "collection",
                           "bytes": os.path.getsize(coll_path)})

    if want_woff2:
        tell(92, "woff2")
        web_dir = os.path.join(out_dir, "web")
        os.makedirs(web_dir, exist_ok=True)
        css = []
        for p in faces_out:
            f = TTFont(p)
            weight = f["OS/2"].usWeightClass
            ital = fk.is_italic(f)
            f.flavor = "woff2"
            w2 = os.path.splitext(os.path.basename(p))[0] + ".woff2"
            w2_path = os.path.join(web_dir, w2)
            f.save(w2_path)
            f.close()
            del f
            outputs.append({"path": w2_path, "name": w2, "kind": "woff2",
                            "bytes": os.path.getsize(w2_path)})
            css.append("@font-face{\n"
                       f"  font-family: '{root}';\n"
                       f"  src: url('{w2}') format('woff2');\n"
                       f"  font-weight: {weight};\n"
                       f"  font-style: {'italic' if ital else 'normal'};\n"
                       "  font-display: swap;\n}\n")
        css_path = os.path.join(web_dir, "fonts.css")
        with open(css_path, "w", encoding="utf-8") as fh:
            fh.write("".join(css))
        outputs.append({"path": css_path, "name": "fonts.css", "kind": "css",
                        "bytes": os.path.getsize(css_path)})

    tell(100, "done")
    fails = sum(1 for r in reports
                for f in r["verify"]["findings"] if f["level"] == "fail")
    return {
        "ok": True,
        "route": route,
        "family": root,
        "version": version,
        "faces": reports,
        "outputs": outputs,
        "failures": fails,
        "custom_problems": custom_problems,
        "custom_added": [c["id"] for c in currencies if c.get("custom")],
        "seconds": round(time.time() - started, 2),
        "ps_names": [r["ps"] for r in reports],
    }
