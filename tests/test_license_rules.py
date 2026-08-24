#!/usr/bin/env python3
"""Renaming is a licence obligation only when the OFL actually imposes one.

The first version of this tool forced a rename on every OFL font, which is
wider than the licence asks. Clause 3 reads:

    No Modified Version of the Font Software may use the Reserved Font Name(s)
    unless explicit written permission is granted ... This restriction only
    applies to the primary font name as presented to the users.

So two conditions must BOTH hold before a rename is required: the file has to
declare a reserved name, and its own family name has to use it. Readex Pro is
the case that proves the second one matters -- it reserves "RevReading Lexend",
a name it does not itself carry.

    python3 tests/test_license_rules.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# web_build.py imports fontkit, which lives with the skill in scripts/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "web", "py"))
import web_build as wb
import fixtures

# (label, path, expect_ofl, expect_rename_required)
CASES = [
    ("OFL, declares no reserved name",
     "tests/fonts/plex-arabic/IBMPlexSansArabic-Regular.ttf", True, False),
    ("OFL, reserves a name it does not use",
     "tests/fonts/variable/ReadexPro[HEXP,wght].ttf", True, False),
    ("OFL, reserves the name it carries",
     "tests/fonts/reserved-name/Qamar-Regular.ttf", True, True),
]

PARSING = [
    ("Copyright (c) 2011, Foo (f@x.com), with Reserved Font Name Alpha.", ["Alpha"]),
    ('Copyright 2012 X, with Reserved Font Name "Beta" and "Gamma".', ["Beta", "Gamma"]),
    ("Copyright (c) 2013 X, with Reserved Font Names Delta and Epsilon.", ["Delta", "Epsilon"]),
    ("Copyright 2018 The Readex Pro Project Authors (https://x), "
     "with Reserved Font Name “RevReading Lexend”.", ["RevReading Lexend"]),
    ("Copyright 2019 IBM Corp. All rights reserved.", []),
]


def ensure_reserved_fixture():
    """An OFL font that reserves the very name it carries. Derived locally so it
    exists whether or not any font was downloaded."""
    out = os.path.join(ROOT, "tests/fonts/reserved-name/Qamar-Regular.ttf")
    if os.path.exists(out):
        return
    from fontTools.ttLib import TTFont
    os.makedirs(os.path.dirname(out), exist_ok=True)
    f = TTFont(fixtures.base_font())
    n = f["name"]
    n.setName("Copyright (c) 2024, Example Foundry (foundry@example.com), "
              "with Reserved Font Name Qamar.", 0, 3, 1, 0x409)
    n.setName("This Font Software is licensed under the SIL Open Font License, "
              "Version 1.1.", 13, 3, 1, 0x409)
    n.setName("https://openfontlicense.org", 14, 3, 1, 0x409)
    for nid, val in ((1, "Qamar"), (4, "Qamar Regular"), (16, "Qamar"),
                     (6, "Qamar-Regular")):
        for pid, eid, lid in ((3, 1, 0x409), (1, 0, 0)):
            n.setName(val, nid, pid, eid, lid)
    f.save(out)
    f.close()


def main():
    bad = 0

    print("reserved-name parsing")
    for text, expect in PARSING:
        got = wb._reserved_font_names(text)
        if got != expect:
            print(f"  FAIL {got} != {expect}   <- {text[:56]}")
            bad += 1
        else:
            print(f"  ok   {str(got):32} <- {text[:52]}")

    # The reserved-name fixture is derived from whatever base font is available,
    # so this case runs even when CI has downloaded nothing.
    ensure_reserved_fixture()

    print("\nrename obligation")
    for label, rel, expect_ofl, expect_required in CASES:
        path = os.path.join(ROOT, rel)
        if not os.path.exists(path):
            print(f"  SKIP {label}: needs a downloaded fixture "
                  f"({rel}) -- run tests/fetch_fonts.sh")
            continue
        r = wb.inspect_paths([path])
        ok = r["ofl"] == expect_ofl and r["rename_required"] == expect_required
        bad += 0 if ok else 1
        print(f"  {'ok  ' if ok else 'FAIL'} {label:38} "
              f"family={r['family_root']!r} declares={r['declared_reserved_names']} "
              f"conflicts={r['reserved_names']} required={r['rename_required']}")

    print("\n" + ("FAILED" if bad else
                  "PASS: a rename is required only when a reserved name is both "
                  "declared and used"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
