#!/usr/bin/env python3
"""Every relative link and heading anchor in the repository's markdown resolves.

Documentation drifts silently: a section gets renamed, a file moves, a table of
contents keeps pointing at the old slug, and nothing complains until a reader
clicks. This walks every markdown file tracked by git and checks each relative
link — both that the file exists and that the `#anchor` matches a real heading.

External links are not fetched: that would make the check depend on somebody
else's uptime, which this repository deliberately avoids elsewhere too.

    python tests/check_docs.py
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def slug(heading):
    """GitHub's anchor rule: lowercase, drop punctuation, spaces to hyphens."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"\s+", "-", s).strip("-")


def main():
    files = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT,
                           capture_output=True, text=True).stdout.split()
    if not files:
        print("no markdown files found — is this a git checkout?")
        return 1

    anchors = {}
    for f in files:
        text = open(os.path.join(ROOT, f), encoding="utf-8").read()
        anchors[f] = {slug(m.group(1))
                      for m in re.finditer(r"^#{1,6}\s+(.+)$", text, re.M)}

    bad = 0
    for f in files:
        text = open(os.path.join(ROOT, f), encoding="utf-8").read()
        base = os.path.dirname(f)
        for m in re.finditer(r"\[([^\]]*)\]\(([^)]+)\)", text):
            label, target = m.group(1), m.group(2)
            if target.startswith(("http://", "https://", "mailto:", "#!")):
                continue
            path, _, frag = target.partition("#")
            if path:
                resolved = os.path.normpath(os.path.join(ROOT, base, path))
                if not os.path.exists(resolved):
                    print(f"  MISSING FILE  {f}: [{label}]({target})")
                    bad += 1
                    continue
                key = os.path.relpath(resolved, ROOT)
            else:
                key = f
            if frag and key in anchors and frag not in anchors[key]:
                print(f"  BAD ANCHOR    {f}: [{label}]({target})")
                bad += 1

    print(f"{len(files)} markdown files checked — "
          + (f"{bad} broken link(s)" if bad else "every link resolves"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
