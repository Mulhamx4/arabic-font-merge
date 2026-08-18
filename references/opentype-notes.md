# OpenType details behind the scripts

Read this when changing `fontkit.py` or debugging something the scripts do not
cover. Each section explains why the code is shaped the way it is.

## Contents

- [Advance widths are stored twice](#advance-widths-are-stored-twice)
- [Adding a glyph to a CFF font](#adding-a-glyph-to-a-cff-font)
- [Naming: how one family stays one family](#naming-how-one-family-stays-one-family)
- [Contextual substitution with blocking rules](#contextual-substitution-with-blocking-rules)
- [Arabic and GSUB ordering](#arabic-and-gsub-ordering)
- [Collections](#collections)
- [Variable font feasibility](#variable-font-feasibility)
- [Grafting glyphs between fonts](#grafting-glyphs-between-fonts)

## Advance widths are stored twice

In a CFF/OTF font every glyph's advance appears in `hmtx` **and** as the optional
leading operand of its charstring. The charstring value is relative:

```
effective advance = Private.nominalWidthX + <charstring width operand>
```

If the operand equals `Private.defaultWidthX` it is omitted entirely.

`fontTools`' `T2CharStringPen(width, ...)` writes whatever you pass straight into
the program without subtracting `nominalWidthX`. So:

```python
nominal = getattr(top.Private, "nominalWidthX", 0)
default = getattr(top.Private, "defaultWidthX", 0)
cff_width = None if adv == default else adv - nominal
pen = T2CharStringPen(cff_width, font.getGlyphSet())
```

Consequences of getting it wrong are asymmetric and misleading: HarfBuzz,
browsers, and CoreText read `hmtx` and render correctly, while Adobe's CoolType
reads the charstring and shows `nominalWidthX` units of dead space. A font can
pass every browser-based test and be visibly broken in Illustrator.

`fk.cff_advance()` extracts the charstring value via `T2WidthExtractor` so the two
can be compared. `verify_font.py` does this for every glyph.

## Adding a glyph to a CFF font

`CharStrings.__setitem__` requires the name to exist already, so a new glyph has
to be appended to the underlying index:

```python
chs = top.CharStrings
if getattr(chs, "charStringsAreIndexed", False):
    chs.charStringsIndex.append(cs)
    chs.charStrings[glyph_name] = len(chs.charStringsIndex) - 1
else:
    chs.charStrings[glyph_name] = cs
top.charset.append(glyph_name)
```

`charset` and the charstring index must stay parallel — glyph names come from
`charset` on reload, and a mismatch produces invented names like `glyph02173`.

Capture the glyph order **before** touching `charset`. `TTFont.getGlyphOrder()`
for a CFF font can re-derive from `charset`, so reading it afterwards returns a
list that already contains the new glyph; appending again creates a duplicate and
an off-by-one `numGlyphs`.

Then: `hmtx.metrics`, `maxp.numGlyphs`, every Unicode `cmap` subtable, and
`GDEF.GlyphClassDef` (class 1 = base glyph, so mark positioning treats it
correctly).

For TrueType outlines use `TTGlyphPen` wrapped in `Cu2QuPen` — `glyf` stores
quadratics, and cubic Béziers from SVG need converting.

## Naming: how one family stays one family

| nameID | purpose |
| --- | --- |
| 1 / 2 | legacy family / subfamily — max 4 styles per family |
| 4 | full name |
| 3 | unique identifier — include the version so caches can tell builds apart |
| 6 | PostScript name — must be unique per face; documents reference it |
| 16 / 17 | typographic family / subfamily — the modern grouping |

Older Windows APIs allow only Regular/Italic/Bold/Bold Italic per family, which
is why foundries ship "Foo", "Foo Light", "Foo Black" as separate families. Set
16/17 to the real family and full style, and keep 1/2 as correct RIBBI groups:
modern apps read 16/17 and show one entry with a weight dropdown, older apps read
1/2 and still work.

`fsSelection` and `head.macStyle` have to agree with the names. Bit 8 of
`fsSelection` (WWS) asserts that the family/style names contain no width or
weight tokens beyond the standard ones.

Keep PostScript names unchanged from the originals when merging. They are what
existing documents reference; renaming silently breaks those files. The cost is
that caches key on them — hence version bumps.

## Contextual substitution with blocking rules

A plain `LigatureSubst` for `O M R` fires everywhere, rewriting `COMRADE` to
`C⃄ADE`. The fix mirrors what FEA's `ignore` statements compile to: one
`ChainContextSubst` lookup whose subtables are tried in order, where the first
match wins.

```
subtable 1  backtrack=[@Letter]  input=[O][M][R]                 (no action)
subtable 2                       input=[O][M][R]  lookahead=[@Letter]  (no action)
subtable 3                       input=[O][M][R]  -> ligature lookup at index 0
```

A subtable that matches with zero `SubstLookupRecord`s counts as applied, so
processing stops and the substitution is blocked. Because subtable 1 requires a
preceding glyph, a token at the start of a line falls through to subtable 3 and
still fires — which a plain negative-coverage backtrack could not achieve.

The ligature lookup is added to `LookupList` but registered in no feature; it is
only reachable from the chain context. Register the chain lookup in `calt` for
every script and language system — `calt` is on by default in most engines.
`@Letter` is built from the cmap by Unicode general category, so it covers Arabic
letters as well as Latin.

Ligature sets are ordered longest-first by `fontTools`, so a 4-glyph rule
(`ر.ع.`) is tried before the 3-glyph one (`ر.ع`) automatically. A ligature invoked
from a chain context may consume more glyphs than the input sequence declares.

## Arabic and GSUB ordering

GSUB operates in **logical** order. HarfBuzz reverses the buffer for display only,
so `ر.ع` is written as `reh, period, ain` in rules even though shaped output
appears reversed.

The Arabic shaper applies form features (`isol`, `fina`, `medi`, `init`) before
`calt`, so contextual rules must target post-shaping glyphs. This helps: a letter
adjacent to another Arabic letter has already become a joined form, so an
isolated-form rule cannot match mid-word — the shaper guards the sequence for
free.

## Collections

`.otc`/`.ttc` hold several fonts in one file with identical tables shared.
`TTCollection(...).save(path, shareTables=True)` deduplicates automatically.

Support: macOS and Windows 10+ install them natively; Office and Adobe generally
handle them; `@font-face` in browsers does **not**; Figma is undocumented. Ship
standalone files alongside as a fallback.

## Variable font feasibility

`varLib` needs every glyph to have identical point structure across masters. Test
it cheaply by recording each glyph with a `RecordingPen` and comparing
`(operator, argument-count)` sequences.

Retail static families fail heavily — typically 20–25% of glyphs. Mechanical
outline offsetting (dilate/erode via a polygon clipper) is not a fix: eroding
detaches thin joins, dilating closes counters. Report the count and recommend a
collection.

## Grafting glyphs between fonts

`fontTools.subset` then `fontTools.merge` moves a script's glyphs plus its GSUB,
GPOS, and GDEF rules from one font into another, including CFF outlines:

```python
opts.layout_features = ["*"]   # keep init/medi/fina/rlig/mark/kern
opts.notdef_outline = True
subsetter.populate(unicodes=arabic_codepoints)
...
Merger().merge([target, arabic_subset]).save(out)
```

Subset on the full Arabic ranges — including U+200C–U+200F joiners and marks,
which shaping needs. But *decide* whether a face lacks Arabic using letters only:
fonts with no Arabic still commonly map the joiners and the Arabic comma, so
counting the full ranges makes an Arabic-less italic look covered.

After merging, recompute `OS/2` Unicode ranges (`recalcUnicodeRanges`) and set the
Arabic codepage bit (bit 6, cp1256), or apps may not offer the font for Arabic.

Do not shear grafted Arabic to fake an italic without also shearing every GPOS
anchor — otherwise diacritics drift off their letters. Upright Arabic in italic
runs is the conventional choice anyway.
