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
    """The variable fixture, or None. There is no synthetic substitute: the bug
    it guards lives in HVAR, and building a variable font with a populated
    HVAR delta store just to test it would be testing our own construction."""
    p = os.path.join(FONTS, "variable", "ReadexPro[HEXP,wght].ttf")
    return p if os.path.exists(p) else None


def using_real_fonts():
    return os.path.exists(REAL_BASE)
