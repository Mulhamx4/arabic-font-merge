---
name: arabic-font-merge
description: >
  Combine a set of font weight files into ONE installable font file, verify Arabic
  shaping works in every weight, and add the Gulf currency symbols — Saudi Riyal
  (U+20C1), UAE Dirham (U+20C3) and Omani Rial (U+20C4) — each with typed
  shortcuts like SAR / AED / OMR and ر.س / د.إ / ر.ع. Use this skill whenever someone hands over
  several font files (.ttf/.otf) and wants them merged, unified, or turned into
  "one file" — and also whenever they mention Arabic not working in a font,
  Arabic missing from italics, adding a currency symbol or custom glyph to a font,
  a font family showing up scattered across the font menu, .otc/.ttc collections,
  a currency symbol missing from a font or showing as an empty box,
  building a variable font out of static weights, or a font that behaves
  differently in Adobe than in a browser. Trigger it even for a bare "دمج الخطوط",
  "خل الخطوط ملف واحد", "أضف رمز الريال", or an upload of a folder of font weights
  with no explanation attached.
---

# Merging a font family into one file

Someone has 10–20 font files — one per weight — and wants a single file they can
install once. Along the way the Arabic usually needs checking and the Gulf
currency symbols need adding. The scripts here do the mechanical work; your job is
to make the right calls and to verify the result properly.

## Ask where it will be used, before building anything

The output format is not a detail you can settle at the end — it decides what
you build. Ask up front, in one short question, and offer the concrete choices:

- **Windows** (install, Office) → `--format ttc`
- **macOS** (install, Adobe, Office) → default `.otc` is fine
- **Adobe apps** → collection plus the standalone files as a fallback
- **Figma** → standalone files; collection support is undocumented there
- **Websites** → add `--woff2`

If they say "everywhere" — which is the common answer — build `--format ttc`
plus the standalone files. That combination installs on both systems and drops
into every app, and the cost of the conversion is negligible (see below).

Asking takes one turn. Guessing costs several: the user installs, it silently
fails or looks wrong, and you are debugging blind without knowing which
application you are debugging.

## Formats, and the Windows trap

**`.otc` does not install on Windows.** The OpenType spec is clear that a
collection of CFF fonts should use the `.otc` extension, and it is perfectly
valid — but the Windows shell never registered that extension as a font type, so
Explorer offers no "Install" action at all. The file is not broken; Windows just
will not open it. macOS handles `.otc` fine.

`--format ttc` solves this by converting the CFF (cubic) outlines to TrueType
(quadratic) and writing a `.ttc`, which Windows has supported for decades — its
own system fonts ship that way. Measure the conversion rather than fearing it:
on a 2170-glyph family the largest bounding-box shift was 0.05 units on a
1000-unit em, and no advance width changed. What you do lose is CFF hinting,
which only affects rendering at very small sizes. State that trade honestly and
keep the `.otc` as well when macOS matters.

| target | file | why |
| --- | --- | --- |
| Windows, or "everywhere" | `.ttc` (`--format ttc`) | the only collection Windows installs |
| macOS / Adobe only | `.otc` (default) | outlines stay byte-identical |
| Figma, or anything odd | `otf/` folder | no collection support to depend on |
| web | `web/` (`--woff2`) | browsers cannot load collections at all |

## The decision that comes first

People often ask for a **variable font**, because that is the modern one-file
answer. It is usually impossible with retail font files, and it is better to
know that in the first minute than to discover it after an hour.

A variable font interpolates between masters, which requires every glyph to have
identical point structure in every weight. Retail families are drawn separately
per weight, so hundreds of glyphs differ. `inspect_fonts.py` measures this and
gives you a number ("504 of 2172 glyphs differ"), which is far more convincing
than an assertion.

The honest one-file answer is an **OpenType Collection** (`.otc`, or `.ttc` for
TrueType outlines): every face inside a single file, outlines untouched,
installs with one double-click on macOS and Windows. That is the default here.

Do not attempt to force a variable font by mechanically thickening or thinning
outlines. It reliably destroys letterforms — thin weights break apart, heavy
weights fill in their counters. If someone wants true weight-matched artwork,
that is a type designer's job, and saying so plainly is more useful than
shipping something distorted.

## Workflow

```bash
# 1. survey — decides everything downstream, never skip it
python scripts/inspect_fonts.py <font-dir>

# 2. build — collection + standalone files + the currency symbols
#    add --format ttc if Windows is a target (see above)
python scripts/build_family.py <font-dir> --out build/ --version 2.000

# 3. verify — exits non-zero on any failure
python scripts/verify_font.py "build/<Family>.otc"

# 4. proof — a picture and a self-contained test page
python scripts/make_proof.py "build/<Family>.otc" --out build/
```

Run all four. Step 3 checks what actually landed in the binary; step 2 only
reports what it intended. Then **look at `proof.png` yourself** — numeric passes
say nothing about whether the spacing and weights look right.

`build_family.py` handles the whole job by default: Arabic grafting, all three
currency symbols, the shortcuts, and the naming. Useful flags:

| flag | when |
| --- | --- |
| `--version 2.100` | bump on **every** rebuild — see the caching trap below |
| `--family "Name"` | the auto-derived family name is wrong |
| `--side-bearing 24` | user says the symbol has too much air around it |
| `--only omani-rial` | build just some currencies (ids from the manifest) |
| `--no-symbols` | user explicitly wants no currency symbols |
| `--no-arabic-graft` | keep italics exactly as the foundry shipped them |
| `--format ttc` | Windows is a target — converts CFF to TrueType |
| `--woff2` | they also need it on a website |
| `--slant-symbols-in-italics` | only if they ask; see below |

## Two traps that cost real time

**A CFF glyph stores its advance width twice.** Once in `hmtx`, once inside the
charstring — and the charstring value is an *offset from* `Private.nominalWidthX`,
not an absolute number. Write an absolute value and the glyph silently gains
`nominalWidthX` units of dead space. Browsers, HarfBuzz, and every web-based test
read `hmtx` and look perfect; Adobe apps read the charstring and show a wide
empty band. `fontkit.add_symbol_glyph` gets this right and `verify_font.py`
compares the two for every glyph.

The general lesson is bigger than this one field: **never sign off on a font from
browser rendering alone.** Browsers and Adobe use different engines that read
different tables. If someone reports a problem you cannot reproduce, ask which
application before assuming the file is fine.

**Font caches are keyed by PostScript name.** Because merging keeps the original
PostScript names (deliberately — changing them breaks existing documents), the
operating system and Adobe will happily serve the *old* font data for the *new*
file. Symptoms: your fix does not appear no matter what you do. Bump `--version`
on every rebuild so caches see a different font, and tell the user to quit Adobe
apps, delete `AdobeFnt*.lst`, and restart.

## What the build does, and why

**Keeps the foundry's PostScript names.** Existing documents reference them, so
inventing new ones silently breaks those files. The cost is that font caches key
on them — hence the version bump.

**Unifies the naming.** Families ship RIBBI-split ("Foo", "Foo Light", "Foo
Black") because older Windows APIs allow only four styles per family. Setting
nameIDs 16/17 (typographic family/subfamily) alongside correct legacy 1/2 pairs
collapses the whole thing into one menu entry with a weight dropdown, while
staying compatible with apps that only read the legacy names.

Shipped fonts are frequently broken here in a specific way: the Windows nameID 2
says "Regular" for *every* face, Bold Italic included. Apps that read Windows
records then scatter the family. `inspect_fonts.py` reports this; the build fixes
it. Worth mentioning to the user — it explains messiness they have probably
lived with for years.

**Grafts Arabic into the italics.** Many families ship Arabic in the uprights
only, so Arabic typed in an italic run falls back to a system font. Copying the
matching upright weight's Arabic across is a real fix, and the glyphs stay
upright because Arabic has no italic tradition — upright Arabic inside slanted
Latin is the accepted convention. Only oblique it if the user asks.

**Adds the currency symbols and their shortcuts.** `assets/currencies.json` is
the whole configuration — id, codepoint, artwork file, and shortcut strings.
Adding a fourth currency means dropping its official SVG in `assets/` and
appending an entry; no script is per-currency. Never draw one of these from
memory: they are state symbols, and an approximation is wrong. Ask the user for
the official artwork (pasting the SVG source as text works well).

| currency | codepoint | Unicode |
| --- | --- | --- |
| Saudi Riyal | U+20C1 | 17.0 |
| UAE Dirham | U+20C3 | 18.0 |
| Omani Rial | U+20C4 | 18.0 |

These codepoints are new enough that the operating system's own character map
will not list them — it reads the OS Unicode database, not the font. Say this
proactively; otherwise the user reasonably concludes the glyphs are missing. In
Adobe apps, `Type ▸ Glyphs` with `Show: Entire Font` reads the font directly and
does show them, as the last glyphs.

The typed shortcuts (`SAR`, `AED`, `OMR`, and `ر.س`, `د.إ`, `ر.ع`) exist because a
brand-new codepoint is hard to type. They are **contextual** substitutions in
`calt`, with blocking rules so they only fire on standalone tokens. A plain
ligature would rewrite `COMRADE`, `SARAH`, `Caesar`, `sarcasm` and `aedile` — the
negative corpus in `verify_font.py` guards exactly this, and it matters as much
as the positive one.

## Delivering the result

Send the user:

- `<Family>.otc` or `.ttc` — the one file they asked for, in the format that
  matches where they said they would use it
- `otf/` zipped — same content as standalone files, a fallback for any app that
  handles collections poorly. Worth including unprompted when Adobe or Figma is
  the target.
- `proof.png` — shows them it works (fonts are embedded in the page, never
  installed and looked up by name — a same-named system font would otherwise win
  and you would screenshot the OLD font while every number passed)
- `selftest.html` — the font embedded as base64, so it tests the *file* with no
  installation involved

That last one is disproportionately useful. When a user says "it doesn't work",
it separates a broken font from a caching or install problem in one click,
instead of a round trip of guesswork. Point them at it first.

Tell them the install order too: remove the old files, install the new one,
**then restart the application** — apps read fonts at launch.

## When the user reports it still does not work

Read `references/troubleshooting.md`. Diagnose in this order, because the cheap
checks catch most cases:

1. Have them open `selftest.html`. Green means the file is fine and the problem
   is installation or the app — stop looking at the font.
2. Are the old files still installed? Same internal names, so the system may
   resolve to them.
3. Did they restart the app?
4. Which application? Character map vs. Adobe's Glyphs panel is a different
   question, and `calt` can be toggled off in Illustrator and InDesign.

Ask which app before theorising. It narrows the search more than anything else.

## Bundled files

- `scripts/fontkit.py` — shared library; read it before changing behaviour
- `scripts/inspect_fonts.py` — survey and feasibility
- `scripts/build_family.py` — the build
- `scripts/verify_font.py` — verification, exits non-zero on failure
- `scripts/make_proof.py` — proof image and self-test page
- `assets/currencies.json` — the currency manifest; edit this to add one
- `assets/*.svg` — official artwork (SAMA, CBUAE, Central Bank of Oman)
- `references/troubleshooting.md` — install, cache, and per-app problems
- `references/opentype-notes.md` — the format details behind the scripts

Dependencies: `pip install fonttools brotli uharfbuzz --break-system-packages`.
`make_proof.py` also wants Playwright and `fc-cache` for the PNG; it degrades to
writing only the HTML if they are missing.
