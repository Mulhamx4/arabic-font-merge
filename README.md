# Arabic Font Merge

**[العربية](README.ar.md)** · English

[![smoke test](https://github.com/Mulhamx4/arabic-font-merge/actions/workflows/smoke-test.yml/badge.svg)](https://github.com/Mulhamx4/arabic-font-merge/actions/workflows/smoke-test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A [Claude skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) that turns a folder of font weight files into **one installable font file**, checks that Arabic actually works in every weight, and adds the Gulf currency symbols — Saudi Riyal (U+20C1), UAE Dirham (U+20C3) and Omani Rial (U+20C4) — with typed shortcuts like `SAR`, `AED`, `OMR` and `ر.س`, `د.إ`, `ر.ع`.

It also works as a plain command-line toolkit. Claude is optional.

![Eight weights of Poppins merged into one file, with the three currency symbols and their typing shortcuts](examples/demo.png)

<sub>Demo built from [Poppins](https://github.com/itfoundry/Poppins) (OFL). Poppins ships no Arabic, so the Arabic lines above fall back to a system font — which is exactly the condition `inspect_fonts.py` reports before you build.</sub>

## Why this exists

Retail font families arrive as 8–20 separate files. Installing them is tedious, they scatter across the font menu, and three things go wrong so consistently that they are worth automating:

- **Italics ship without Arabic.** Many families put Arabic in the uprights only, so Arabic typed in an italic run silently falls back to a system font.
- **The family menu is a mess.** Fonts commonly carry a broken Windows nameID 2 — literally "Regular" on every face, Bold Italic included — so apps split one family into six.
- **A new currency symbol has nowhere to come from.** U+20C1/20C3/20C4 are recent Unicode additions. Almost no shipped font has them, and drawing one by hand is not an option: they are state symbols, and an approximation is wrong.

## What it does

| | |
| --- | --- |
| **One file** | Writes an OpenType Collection — every weight inside a single `.otc` (macOS) or `.ttc` (Windows), outlines untouched, one double-click to install |
| **Arabic in italics** | Copies the matching upright weight's Arabic into any italic that lacks it, upright, as Arabic convention requires |
| **One menu entry** | Rebuilds nameIDs 16/17 alongside correct legacy 1/2 pairs, so the family collapses to one name with a weight dropdown |
| **Currency symbols** | Adds the official SAMA / CBUAE / Central Bank of Oman artwork at the right codepoints, scaled to each weight's cap height |
| **Typing shortcuts** | `SAR` → ⃁ via contextual `calt`, with blocking rules so `COMRADE`, `SARAH`, `Caesar`, `sarcasm` and `aedile` stay intact |
| **Real verification** | Shapes an Arabic corpus through HarfBuzz, fires every shortcut, checks 15 near-miss words do *not* fire, and compares CFF advance widths against `hmtx` for every glyph |
| **Proof you can send** | A `proof.png` and a self-contained `selftest.html` with the font embedded as base64 |

It also tells you honestly when a **variable font** is impossible — which, for retail static weights, it almost always is. See [the variable-font question](#the-variable-font-question).

## Install

### As a Claude skill

```bash
git clone https://github.com/Mulhamx4/arabic-font-merge.git ~/.claude/skills/arabic-font-merge
pip install fonttools brotli uharfbuzz
```

That is the whole install. Claude picks the skill up automatically and triggers it when you hand over font files and ask for them merged, or mention Arabic not working, or a currency symbol. In Claude Code you can also invoke it directly with `/arabic-font-merge`.

For [Cowork](https://claude.ai) or the Claude apps, zip the repository contents and upload it as a skill:

```bash
cd arabic-font-merge && zip -r ../arabic-font-merge.skill . -x '.git/*' 'examples/*'
```

### As a command-line tool

```bash
git clone https://github.com/Mulhamx4/arabic-font-merge.git
cd arabic-font-merge
pip install -r requirements.txt
```

Python 3.9+. `make_proof.py` additionally uses [Playwright](https://playwright.dev/python/) for the PNG and degrades to writing only the HTML without it.

## Usage

Four commands, in order. Do not skip step 1, and do not stop at step 2.

```bash
# 1. survey — decides everything downstream
python scripts/inspect_fonts.py ~/Fonts/MyFamily

# 2. build — collection + standalone files + currency symbols
python scripts/build_family.py ~/Fonts/MyFamily --out build/ --version 2.000 --format ttc

# 3. verify — exits non-zero on any failure
python scripts/verify_font.py "build/MyFamily.ttc"

# 4. proof — a picture and a self-contained test page
python scripts/make_proof.py "build/MyFamily.ttc" --out build/
```

Step 2 reports what it *intended* to do. Step 3 checks what actually landed in the binary. They are not the same thing, and the difference is where bugs live.

Output:

```
build/
├── MyFamily.ttc        the one file
├── otf/                the same faces as standalone files
├── web/                woff2 + fonts.css   (with --woff2)
├── proof.png
└── selftest.html
```

### Which format do you need?

**Ask before you build.** The format is not a detail you can settle afterwards.

| Where it will be used | Build | Why |
| --- | --- | --- |
| Windows, or "everywhere" | `--format ttc` | **`.otc` does not install on Windows at all** — Explorer offers no Install action for that extension. The file is valid; Windows just will not open it |
| macOS / Adobe only | default `.otc` | outlines stay byte-identical |
| Figma, or anything that misbehaves | the `otf/` folder | collection support there is undocumented |
| Websites | `--woff2` | browsers cannot load collections at all |

`--format ttc` converts the CFF (cubic) outlines to TrueType (quadratic). Measured on a 2170-glyph family: largest bounding-box shift **0.05 units on a 1000-unit em**, zero advance widths changed. What you lose is CFF hinting, which matters only at very small sizes.

### Flags worth knowing

| flag | when |
| --- | --- |
| `--version 2.100` | **bump on every rebuild** — font caches are keyed by PostScript name and will serve you stale data forever otherwise |
| `--format ttc` | Windows is a target |
| `--woff2` | you also need it on a website |
| `--family "Name"` | the auto-derived family name is wrong |
| `--only omani-rial` | build just some currencies (ids from `assets/currencies.json`) |
| `--no-symbols` | no currency symbols at all |
| `--no-arabic-graft` | keep italics exactly as the foundry shipped them |
| `--side-bearing 24` | the symbol reads too loose |
| `--slant-symbols-in-italics` | oblique the symbols in italics (off by default — they are official marks) |
| `--single-family` | one legacy family name for every face. Read the warning in [SKILL.md](SKILL.md) first: GDI-era apps address only four styles per family, so a 16-weight family loses 12 of them |

## The currency symbols

| currency | codepoint | Unicode | artwork source |
| --- | --- | --- | --- |
| Saudi Riyal ⃁ | U+20C1 | 17.0 | Saudi Central Bank (SAMA) |
| UAE Dirham ⃃ | U+20C3 | 18.0 | Central Bank of the UAE |
| Omani Rial ⃄ | U+20C4 | 18.0 | Central Bank of Oman |

**These will not appear in your operating system's Character Map.** macOS Character Viewer and Windows Character Map read the *OS* Unicode database, not the font — a codepoint the OS does not know about is not listed even when the glyph is right there in the file. Use Adobe's `Type ▸ Glyphs` panel with `Show: Entire Font` (it reads the font directly, and the new glyphs land last), or paste the character, or type the shortcut.

### Adding another currency

Nothing in the scripts is per-currency. Drop the official SVG in `assets/` and append an entry to `assets/currencies.json`:

```json
{
  "id": "kuwaiti-dinar",
  "name": "Kuwaiti Dinar",
  "codepoint": "20C5",
  "unicode_version": "18.0",
  "authority": "Central Bank of Kuwait",
  "svg": "kuwaiti-dinar.svg",
  "latin": ["KWD", "kwd"],
  "arabic": ["د.ك.", "د.ك"]
}
```

Arabic shortcuts are written in **logical order** — the order GSUB sees, not the order you see on screen. As of Unicode 18 there is no official single-character symbol for the Kuwaiti, Bahraini, Qatari or Jordanian currency; the example above is illustrative.

## Two traps that cost real time

These are documented here because both shipped as real bugs before they were caught.

### A CFF glyph stores its advance width twice

Once in `hmtx`, once inside the charstring — and the charstring value is an **offset from `Private.nominalWidthX`**, not an absolute number. Write an absolute value and the glyph silently gains `nominalWidthX` units of dead space.

Browsers, HarfBuzz, and every web-based test read `hmtx` and look perfect. Adobe reads the charstring and shows a wide empty band. This survived a full round of browser testing and was only found when a user said the symbol "looks like the whole glyph is oversized".

`verify_font.py` now compares both values for every glyph. The general lesson is larger than the field: **never sign off on a font from browser rendering alone**, and always ask *which application* before theorising about a bug report.

### Font caches are keyed by PostScript name

The build deliberately keeps the foundry's PostScript names — renaming them breaks existing documents that reference them. The cost is that macOS and Adobe will happily serve the *old* font data for the *new* file, and your fix appears to do nothing.

Bump `--version` on every rebuild. Then: remove the old files, quit every Adobe app, delete `AdobeFnt*.lst`, install, and **restart the application** — apps enumerate fonts at launch.

## The variable font question

People ask for a variable font, because that is the modern one-file answer. With retail static weights it is almost always impossible, and it is much better to know that in the first minute than after an hour.

Interpolation requires every glyph to have **identical point structure in every weight**. Retail families are drawn separately per weight, so hundreds of glyphs differ. `inspect_fonts.py` measures this and gives you a number rather than an assertion — 504 of 2172 glyphs on one commercial family, 677 of 1060 on Poppins.

Do not try to force it by mechanically thickening or thinning outlines. It reliably destroys letterforms: thin weights break apart, heavy weights fill in their counters. Weight-matched artwork is a type designer's job.

An OpenType Collection is the honest one-file answer, and it is what this tool builds.

## Troubleshooting

Start with [`references/troubleshooting.md`](references/troubleshooting.md). The short version, in the order that saves the most time:

1. **Open `selftest.html`.** The font is embedded as base64, so installation is irrelevant. Green banner → the file is fine and you have an install, cache, or application problem; stop inspecting the font. Red → the font is wrong.
2. Are the old files still installed? Same internal names, so the system may still resolve to them.
3. Did you restart the application?
4. **Which application?** `calt` is a user toggle in Illustrator and InDesign (`Window ▸ Type ▸ OpenType`), Adobe has its own font cache, and Character Map is not a font inspector.

## Repository layout

```
SKILL.md                    what Claude reads — the judgement calls, not just the commands
scripts/fontkit.py          shared library; read this before changing behaviour
scripts/inspect_fonts.py    survey and variable-font feasibility
scripts/build_family.py     the build
scripts/verify_font.py      verification, exits non-zero on failure
scripts/make_proof.py       proof image and self-test page
assets/currencies.json      the currency manifest — edit this to add one
assets/*.svg                official artwork
references/troubleshooting.md
references/opentype-notes.md
tests/make_test_font.py     builds a synthetic family so CI needs no font binary
tests/check_manifest.py     validates currencies.json against the artwork
evals/evals.json            skill evaluation cases
```

## Contributing

Issues and pull requests are welcome — especially additional official currency artwork, and reports of applications where a collection misbehaves. See [CONTRIBUTING.md](CONTRIBUTING.md); the short version is that `verify_font.py` must exit 0 on a build before anything touching `scripts/` is merged.

## License and fonts

The code and documentation are MIT — see [LICENSE](LICENSE).

**This does not license any font.** You must own or be licensed to use and modify any font you run through this tool; most retail licenses restrict modification and redistribution. Currency artwork provenance and attribution are in [NOTICE.md](NOTICE.md).
