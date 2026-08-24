"""Where the web-tool tests get a font to work on.

CI deliberately downloads nothing (see NOTICE.md), so it builds a synthetic
two-weight family with `make_test_font.py`. Locally, `fetch_fonts.sh` provides
real families with Arabic, CFF outlines and a variable font, which exercise far
more. Tests that only need *a* font should take whichever is available; tests
that need a specific property should say so and skip loudly when it is missing.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "tests", "fonts")

REAL_BASE = os.path.join(FONTS, "plex-arabic", "IBMPlexSansArabic-Regular.ttf")
SYNTHETIC = os.path.join(FONTS, "SmokeTest-Regular.ttf")


def base_font():
    """One readable font to derive fixtures from. Never returns None."""
    if os.path.exists(REAL_BASE):
        return REAL_BASE
    if not os.path.exists(SYNTHETIC):
        os.makedirs(FONTS, exist_ok=True)
        subprocess.run([sys.executable, os.path.join(ROOT, "tests", "make_test_font.py"),
                        FONTS], check=True, capture_output=True)
    return SYNTHETIC


def base_family():
    """A folder holding a family, for the tests that build a whole one."""
    real = os.path.join(FONTS, "plex-arabic")
    if os.path.isdir(real) and os.listdir(real):
        return real
    base_font()          # ensures the synthetic pair exists
    return FONTS


def variable_font():
    """A variable font whose last glyph carries a non-zero advance delta.

    Prefers the downloaded Readex Pro, which is where the bug was found in the
    wild. Falls back to a synthetic one built by `make_variable_font.py`, so
    the check runs in CI where nothing is downloaded.

    The synthetic font is not a stand-in for a real typeface -- it exists to
    recreate one specific arrangement: `VarIdxMap.postRead` pads a short map by
    repeating its last entry, so the trap is simply that the final glyph of the
    order points at a non-zero delta row. `test_variable_advance.py` refuses to
    pass if the unfixed path does not actually drift, so a fixture that stopped
    reproducing would be reported rather than quietly turning the test green.
    """
    real = os.path.join(FONTS, "variable", "ReadexPro[HEXP,wght].ttf")
    if os.path.exists(real):
        return real
    synthetic = os.path.join(FONTS, "variable", "SmokeTestVF.ttf")
    if not os.path.exists(synthetic):
        os.makedirs(os.path.dirname(synthetic), exist_ok=True)
        subprocess.run([sys.executable,
                        os.path.join(ROOT, "tests", "make_variable_font.py"),
                        os.path.dirname(synthetic)], check=True, capture_output=True)
    return synthetic


def using_real_fonts():
    return os.path.exists(REAL_BASE)
