"""Where the web-tool tests get a font to work on.

CI deliberately downloads nothing (see NOTICE.md), so it builds what it needs:
a synthetic two-weight family with `make_test_font.py`, and a synthetic
variable font with `make_variable_test_font.py`. Locally, `fetch_fonts.sh`
provides real families with Arabic and CFF outlines, which exercise far more.
Tests that only need *a* font should take whichever is available; tests that
need a specific property should say so and skip loudly when it is missing.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "tests", "fonts")

REAL_BASE = os.path.join(FONTS, "plex-arabic", "IBMPlexSansArabic-Regular.ttf")
SYNTHETIC = os.path.join(FONTS, "SmokeTest-Regular.ttf")
REAL_VARIABLE = os.path.join(FONTS, "variable", "ReadexPro[HEXP,wght].ttf")
SYNTHETIC_VARIABLE = os.path.join(FONTS, "variable", "SmokeTestVF[wght].ttf")


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
    """A font with an fvar, a gvar and a populated HVAR. Never returns None.

    Prefers the downloaded Readex Pro, which is where the bug was found in the
    wild. Falls back to a synthetic one whose trailing index-map rows repeat a
    non-zero delta -- the arrangement `VarIdxMap.preWrite` trims and `postRead`
    then pads, which is the mechanism the whole check exists for. The generator
    refuses to write a fixture that did not actually get trimmed, and
    `test_variable_advance.py` fails rather than passes if the unfixed path
    stops drifting, so a fixture that quietly stopped reproducing is reported
    instead of turning the check green for the wrong reason.
    """
    if os.path.exists(REAL_VARIABLE):
        return REAL_VARIABLE
    if not os.path.exists(SYNTHETIC_VARIABLE):
        os.makedirs(os.path.dirname(SYNTHETIC_VARIABLE), exist_ok=True)
        subprocess.run([sys.executable,
                        os.path.join(ROOT, "tests", "make_variable_test_font.py"),
                        os.path.dirname(SYNTHETIC_VARIABLE)],
                       check=True, capture_output=True)
    return SYNTHETIC_VARIABLE


def using_real_fonts():
    return os.path.exists(REAL_BASE)
