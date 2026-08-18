#!/usr/bin/env python3
"""Validate assets/currencies.json against the artwork on disk.

Catches the two mistakes that adding a currency actually invites: a codepoint
typo, and an SVG that is referenced but missing or unparseable.

    python tests/check_manifest.py
"""

import json
import os
import sys

from fontTools.svgLib.path import SVGPath

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
REQUIRED = ("id", "name", "codepoint", "svg", "latin", "arabic")


def main():
    with open(os.path.join(ASSETS, "currencies.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)

    errors, seen_cp, seen_id = [], {}, set()
    for cur in manifest["currencies"]:
        cid = cur.get("id", "<no id>")
        for key in REQUIRED:
            if key not in cur:
                errors.append(f"{cid}: missing '{key}'")
        if "codepoint" not in cur or "svg" not in cur:
            continue

        try:
            cp = int(cur["codepoint"], 16)
        except ValueError:
            errors.append(f"{cid}: codepoint {cur['codepoint']!r} is not hex")
            continue
        if cp in seen_cp:
            errors.append(f"{cid}: codepoint U+{cp:04X} already used by {seen_cp[cp]}")
        seen_cp[cp] = cid
        if cid in seen_id:
            errors.append(f"{cid}: duplicate id")
        seen_id.add(cid)

        if not cur["latin"] and not cur["arabic"]:
            errors.append(f"{cid}: no shortcuts defined")

        path = os.path.join(ASSETS, cur["svg"])
        if not os.path.exists(path):
            errors.append(f"{cid}: missing artwork {cur['svg']}")
            continue
        try:
            pen_source = SVGPath(path)
        except Exception as exc:                       # noqa: BLE001 - report any parse failure
            errors.append(f"{cid}: cannot parse {cur['svg']}: {exc}")
            continue

        shortcuts = ", ".join(cur["latin"] + cur["arabic"])
        print(f"ok  {cid:14} U+{cp:04X}  {cur['svg']:18} {shortcuts}")
        del pen_source

    if errors:
        print("\n" + "\n".join("FAIL " + e for e in errors), file=sys.stderr)
        return 1
    print(f"\n{len(seen_id)} currencies, manifest and artwork agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
