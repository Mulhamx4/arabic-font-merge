# Notice — fonts, artwork, and what this repository does not license

## The MIT license covers the code, not your fonts

The MIT license in [LICENSE](LICENSE) applies to the scripts and documentation in
this repository. It says nothing about the fonts you run through them.

**You are responsible for having the right to modify the fonts you process.** Most
retail font licenses (Monotype, Linotype, Adobe, and the rest) restrict
modification, embedding, and redistribution — sometimes forbidding modification
entirely, sometimes allowing it only for internal use. Merging weights into a
collection, adding a glyph, and rewriting name tables are all modifications.
Check your license before you build, and before you send the result to anyone.

Open licenses are usually more permissive: the SIL Open Font License explicitly
permits modification and redistribution, on the condition that the result stays
under the OFL and — where the original declares a Reserved Font Name — is
renamed. Apache-2.0 fonts are similar in spirit.

Nothing in this repository can grant you a permission your font license withholds.

## Currency artwork

The SVG files in `assets/` are the official symbol artwork published by the
issuing monetary authorities:

| file | symbol | authority |
| --- | --- | --- |
| `saudi-riyal.svg` | Saudi Riyal (U+20C1) | Saudi Central Bank (SAMA) |
| `uae-dirham.svg` | UAE Dirham (U+20C3) | Central Bank of the UAE |
| `omani-rial.svg` | Omani Rial (U+20C4) | Central Bank of Oman |

These are national currency symbols. They are reproduced here so that fonts can
render their assigned Unicode codepoints correctly, which is the purpose the
codepoints were assigned for. Use of a national currency symbol may be subject to
each authority's own usage guidelines, and those guidelines — not this
repository's license — govern how the mark itself may be used.

The artwork is deliberately used **unmodified in outline** at every weight. It is
not thickened or thinned to match Light or Black, because mechanically offsetting
these shapes destroys them: erosion detaches the hook of the ع in the Omani mark,
dilation closes its counter. A weight-matched drawing of an official symbol is a
type designer's job, and doing it badly produces an incorrect state symbol.

If you add another currency, source the artwork from the issuing authority. Do not
trace it from a screenshot and do not draw it from memory.

## Currency artwork you supply yourself

The web tool lets you add a currency of your own — for the many currencies whose
symbol Unicode has not encoded. Nothing about that changes the paragraph above:
**the artwork must come from the issuing monetary authority.** A currency symbol
is a state mark. Tracing one from a screenshot or drawing it from memory produces
an incorrect state symbol, and use of the mark is governed by that authority's
rules rather than by this repository's licence.

Artwork you upload is written only into the browser's own sandboxed filesystem
and never leaves your machine, so this repository never receives it and cannot
vouch for it. The responsibility for having the right to use a mark, and for the
mark being correct, is yours.

The tool defaults such symbols to the **Private Use Area** (U+E000–U+F8FF), which
exists for exactly this: characters that are not, and may never be, standardised.
It warns against the Currency Symbols block (U+20A0–U+20CF), because Unicode may
later assign one of those codepoints to a different currency and put your font at
odds with the standard. And it refuses outright any codepoint already mapped in
your font, because writing there would silently replace a real character.

## Demo image

`examples/demo.png` is rendered from a build of
[Poppins](https://github.com/itfoundry/Poppins), licensed under the SIL Open Font
License 1.1, copyright the Poppins Project Authors. The image is a rendering, not
font software; no font binary is distributed in this repository.

## The web tool

`web/` runs the same scripts in a browser through Pyodide. It loads
`scripts/` and `assets/` directly rather than keeping a copy, so there is one
source of truth for the engine.

| what | where | licence |
| --- | --- | --- |
| Readex Pro, subset for the interface | `web/assets/ui/ReadexPro.woff2` | [OFL 1.1](web/assets/ui/ReadexPro-OFL.txt), copyright the Readex Pro Project Authors |
| Pyodide | loaded at runtime from jsDelivr, version pinned in `web/worker.js` | MPL-2.0 |
| fontTools, Brotli | bundled inside Pyodide | MIT |

The interface font is subset to the ranges the UI needs and pinned to the weight
axis. Its full OFL text sits beside it, as the licence requires.

Readex Pro's OFL reserves the name `RevReading Lexend` — a name the font itself
does not carry. That distinction is not trivia: OFL clause 3 restricts "the
primary font name as presented to the users", so a font that reserves a name it
does not use needs no rename when modified. The tool implements exactly that
rule, and `tests/test_license_rules.py` holds it in place.

## Third-party dependencies

- [fontTools](https://github.com/fonttools/fonttools) — MIT
- [uharfbuzz](https://github.com/harfbuzz/uharfbuzz) / [HarfBuzz](https://github.com/harfbuzz/harfbuzz) — MIT
- [Brotli](https://github.com/google/brotli) — MIT
- [Playwright](https://github.com/microsoft/playwright-python) — Apache-2.0 (optional, for the proof image only)
- [Pyodide](https://github.com/pyodide/pyodide) — MPL-2.0 (the web tool only, loaded at runtime)
