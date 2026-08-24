# Troubleshooting a delivered font

Symptoms users report are rarely the actual cause. Work the list in order — the
early items are cheap and catch most cases.

## Contents

- [Step 0: is it the file at all?](#step-0-is-it-the-file-at-all)
- [The symbol is not in the character map](#the-symbol-is-not-in-the-character-map)
- [Nothing changed after installing](#nothing-changed-after-installing)
- [Extra space around a glyph](#extra-space-around-a-glyph)
- [The symbol's width changes with the weight axis](#the-symbols-width-changes-with-the-weight-axis)
- [Shortcuts do not substitute](#shortcuts-do-not-substitute)
- [Windows shows no "Install" option](#windows-shows-no-install-option)
- [Per-application notes](#per-application-notes)
- [The family is scattered across the font menu](#the-family-is-scattered-across-the-font-menu)
- [Arabic renders in the wrong font](#arabic-renders-in-the-wrong-font)

## Step 0: is it the file at all?

Have them open `selftest.html` in any browser. The font is embedded as base64,
so installation is irrelevant. `make_proof.py` writes one, and so does the
browser tool at <https://mulhamx4.github.io/arabic-font-merge/> — if the user
has the built file but no Python, that page will produce the self-test for them
without installing anything.

- **Green banner** → the file is correct. Everything below the fold is an install,
  cache, or application problem. Stop inspecting the font.
- **Red or amber** → the font itself is wrong. Ask for a screenshot.

Doing this first saves the round trips. It is the single most useful artifact to
hand over with a font.

If you cannot reproduce what they are seeing at all, having them run the file
through <https://mulhamx4.github.io/arabic-font-merge/> is often faster than a
round of questions: its verification report compares the file against its own
source and names any codepoint, symbol or advance that regressed.

## The symbol is not in the character map

Expected, not a bug, for anything added recently to Unicode. U+20C4 (Omani Rial)
landed in Unicode 18, September 2026. macOS Character Viewer and Windows
Character Map read the *operating system's* Unicode database, not the font, so a
codepoint the OS does not know about will not be listed even when the font
contains the glyph.

Where to look instead:

- **Adobe apps**: `Type ▸ Glyphs` (or `Window ▸ Type ▸ Glyphs`), set
  `Show: Entire Font`, scroll to the end. Newly added glyphs land last. This
  panel reads the font directly. Double-click inserts.
- **Anywhere**: paste the character, or use a typed shortcut.
- **Figma / web**: paste the character.

Say this proactively when delivering. Otherwise the user reasonably concludes the
glyph is missing, and you will spend a turn on a non-problem.

## Nothing changed after installing

Almost always caching, because merged fonts deliberately keep their original
PostScript names (renaming them would break existing documents that reference
them).

1. **Bump the font version** and rebuild — `--version 2.100`, etc. Caches keyed
   by PostScript name plus version then see a different font. This is the fix
   that actually works; the rest is hygiene.
2. **Remove the old files first.** Same internal names means the system may
   resolve to the originals. macOS: Font Book, select the family, Remove.
3. **Adobe cache**: quit every Adobe app, delete `AdobeFnt*.lst` (several
   locations, search for the pattern), relaunch.
4. **Restart the application.** Apps enumerate fonts at launch. This alone fixes
   a surprising share of reports.
5. macOS font cache, as a last resort:
   `sudo atsutil databases -remove` then log out and back in.

## Extra space around a glyph

Check the *encoded* advance width before touching side bearings — dead space is
usually a bug, not a spacing choice.

Run `verify_font.py`; it compares `hmtx` against the CFF charstring for every
glyph and reports mismatches with the exact unit delta. A CFF charstring stores
its width relative to `Private.nominalWidthX`, so an absolute value there adds
`nominalWidthX` units of invisible space. Browsers read `hmtx` and look correct,
so this class of bug survives any amount of browser testing and appears only in
Adobe apps.

Once the widths agree, judge the spacing proportionally rather than by absolute
numbers. A 60-unit side bearing on a 1327-unit-wide glyph is 4.5%; on a 464-unit
digit it is 13%. A wide symbol with 60 units per side is already tighter than the
digits next to it, so if it still reads loose the cause is elsewhere — most often
a space the user typed. `--side-bearing 24` if they still want it tighter.

Also remember that a typed space stays a space. `OMR 10.500` becomes
`⃄ 10.500` — symbol, full word space, number. That gap belongs to their text, not
the font. (The Central Bank's own guideline does put a space there.)

## The symbol's width changes with the weight axis

Only possible in a variable font, and it means the glyph was appended without
neutralising `HVAR` — it inherited the delta row of whatever glyph was last in
the order. See [Adding a glyph to a variable
font](opentype-notes.md#adding-a-glyph-to-a-variable-font).

Two things make this hard to catch. It is invisible to `fontTools`, because
instancing rebuilds `hmtx` from `gvar` phantom points, so a generated instance
measures correct while the variable font is wrong. And it is often small — two
units in the case that prompted the fix — so it reads as a rendering quirk
rather than a defect. Measure the glyph's advance through HarfBuzz at several
points on each axis; a correct symbol does not move at all.

## Shortcuts do not substitute

- **Contextual Alternates off.** The shortcuts live in `calt`, which is on by
  default nearly everywhere but is a toggle in Illustrator and InDesign
  (`Window ▸ Type ▸ OpenType`) and in Photoshop's Character panel.
- **Stale font data** — see the caching section; the old font has no `calt` rules.
- **Not a standalone token.** Working as designed: the blocking rules stop the
  substitution when a letter sits immediately before or after, so `COMRADE` stays
  intact. Confirm they typed the sequence with a space or line start before it.
- **Wrong Arabic sequence.** `ر.ع` needs reh, period, ain — with the period, no
  spaces inside.

## Windows shows no "Install" option

The file is almost certainly `.otc`. Windows never registered that extension as a
font type, so Explorer has no Install action and Font Settings rejects it — even
though the file is spec-valid and installs fine on macOS. This is not corruption
and re-downloading will not help.

Rebuild with `--format ttc`, which converts the outlines to TrueType and writes a
`.ttc`. Windows has supported `.ttc` for decades. Renaming `.otc` to `.ttc`
without converting does **not** work: the extension changes but the fonts inside
still carry CFF outlines, and the Windows font driver rejects them.

## Per-application notes

**Adobe (Illustrator, Photoshop, InDesign)**
Reads advance widths from the CFF charstring, not `hmtx` — the reason
advance-parity verification exists. Has its own font cache (`AdobeFnt*.lst`). Has
a Glyphs panel that shows everything in the font. `calt` is user-toggleable. For
Arabic, the Middle-East/World-Ready composer must be active for correct shaping.

**Figma**
Local fonts arrive through Font Helper, which must be running. Support for
`.otc`/`.ttc` collections is not documented either way — if a collection behaves
oddly, install the standalone files from `otf/` instead. Restart the desktop app
after installing.

**Microsoft Office**
Reads the legacy nameID 1/2 pairs, which is why RIBBI grouping has to be correct.
Handles collections once the OS has installed them — which on Windows means a
`.ttc`, never an `.otc`.

**Browsers**
`@font-face` cannot load `.otc`/`.ttc` collections. Use the `--woff2` bundle,
which emits one file per style plus a ready `fonts.css`.

## The family is scattered across the font menu

Two causes, both fixed by the build but worth recognising in a user's *original*
files:

1. Missing nameIDs 16/17, so apps only see the RIBBI-split legacy families.
2. Windows nameID 2 saying "Regular" for every face — extremely common in shipped
   fonts, including from major foundries. `inspect_fonts.py` reports it per file.

If it is still scattered after installing the merged font, it is cached old data.

## Arabic renders in the wrong font

- **Italic faces with no Arabic.** The usual cause: the family shipped Arabic in
  the uprights only, so the app falls back for Arabic in italic runs.
  `inspect_fonts.py` flags it and the build grafts it across.
- **Missing single characters.** Check the source font, not the merged one. Some
  characters are absent from the original — U+FDFB (ﷻ) is missing from many
  otherwise complete Arabic fonts. Verify against the input before assuming the
  merge dropped something.
- **Marks in the wrong place** after any glyph copying: GPOS anchors are not
  transformed by copying. If you ever oblique Arabic glyphs, the mark anchors
  need the same shear or diacritics will drift.
