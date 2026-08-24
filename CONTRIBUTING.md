# Contributing

## Before you open a pull request

```bash
pip install -r requirements.txt
python tests/check_manifest.py            # manifest and artwork agree
python tests/make_test_font.py tests/fonts
python scripts/build_family.py tests/fonts --out build/ --version 1.000
python scripts/verify_font.py build/SmokeTest.ttc      # must exit 0
```

`tests/make_test_font.py` generates a small synthetic family, because no font
binary is committed here (see [NOTICE.md](NOTICE.md)). If your change touches
shaping, symbol placement, or naming, also run the four-step workflow on a real
family you are licensed to modify, and **look at `proof.png`**. A numeric pass
does not prove the spacing looks right.

## Changing the web tool

`web/` runs the same `scripts/` in a browser through Pyodide, so a change to
`fontkit.py` reaches both. Its own checks run headless and download nothing:

```bash
tests/run_all.sh                                   # everything
PY=./.venv-pyodide-parity/bin/python tests/run_all.sh   # against the fontTools Pyodide ships
```

They cover theme contrast in both palettes, i18n key hygiene, JavaScript syntax,
the variable-font advance regression, the engine on four corpora, byte-parity
with the command-line build, the licence rules, Arabic family names, custom
currency artwork, and `fsType` blocking.

Without `tests/fetch_fonts.sh` the fixtures fall back to synthetic fonts —
`make_test_font.py` for the static family and `make_variable_test_font.py` for a
variable one — so every check still runs. What skips is the richer *corpora*,
and those tests name what they skipped rather than pretending to have run. That
is what CI does.

Run `tests/fetch_fonts.sh` locally before submitting anything that touches
shaping or naming: the real corpora exercise Arabic coverage, CFF outlines and
an italic without Arabic, and the synthetic fonts exercise none of those.

Two web-specific invariants, both with a test behind them:

1. **Never append a glyph to a variable font without neutralising `HVAR`.**
   `VarIdxMap.postRead` pads a short map by repeating its last entry, so the new
   glyph inherits its neighbour's width deltas. fontTools' own instancer cannot
   see the damage — it rebuilds widths from `gvar` — but every real shaper can.
   `tests/test_variable_advance.py` measures it through HarfBuzz, and fails if
   the *unfixed* path stops drifting: a fixture that no longer reproduces the
   bug would otherwise turn the test green for the wrong reason.
2. **A user-supplied codepoint must never land on an existing glyph.**
   `add_symbol_glyph` writes straight into the cmap; U+0041 would turn every
   capital A into a currency symbol. `tests/test_custom_currency.py` guards it.

## Adding a currency

The scripts contain nothing per-currency. Add the entry to
`assets/currencies.json`, drop the SVG in `assets/`, and that is the change.

Two rules, both non-negotiable:

- **Source the artwork from the issuing monetary authority.** Do not trace it
  from a screenshot, and never draw it from memory. These are state symbols and
  an approximation is simply wrong.
- **Only use a codepoint Unicode has actually assigned.** If there is no assigned
  codepoint yet, there is no correct answer — a Private Use Area codepoint looks
  like it works and breaks the moment the text leaves the font.

Write Arabic shortcut strings in **logical order** — the order GSUB sees, not the
visual order. Include both the abbreviation with and without its final period
(`ر.س.` and `ر.س`); the builder tries the longer one first.

Then add near-miss words to `SHOULD_NOT_FIRE` in `scripts/verify_font.py` if your
new abbreviation appears inside ordinary words. The negative corpus matters as
much as the positive one: a bare `OMR` ligature silently rewrites `COMRADE` in
every all-caps heading.

## Changing the scripts

`scripts/fontkit.py` is the shared library — read it before changing behaviour in
any of the four entry points.

Two invariants have already cost real debugging time, and both are enforced by
`verify_font.py`. Do not weaken them:

1. **A CFF glyph's advance is stored twice** — in `hmtx`, and inside the
   charstring relative to `Private.nominalWidthX`. Browsers read `hmtx`, Adobe
   reads the charstring, and a mismatch is invisible in every browser test.
2. **Shortcut substitutions must be contextual, never plain ligatures.** The
   blocking subtables are what keep `SARAH` and `sarcasm` intact.

If you find yourself testing only in a browser, stop. That is exactly how the
first of these shipped.

## Reporting a problem with a built font

Please include:

- which **application** (this narrows it more than anything else — Adobe, Office,
  Figma and browsers all read different tables)
- the operating system
- whether `selftest.html` shows green or red
- the output of `python scripts/verify_font.py <your file>`

Reports of applications that mishandle `.otc`/`.ttc` collections are especially
welcome — that behaviour is under-documented everywhere.
