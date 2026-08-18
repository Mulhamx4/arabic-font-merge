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
