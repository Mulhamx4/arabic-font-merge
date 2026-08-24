#!/usr/bin/env python3
"""The web engine must produce the same font as the command-line tool.

Byte-equality is the goal, with one deliberate exception: the plan requires a
`modified with ...` stamp in nameID 5 (section 3.5) that build_family.py does
not write. This compares table by table so any OTHER difference is a failure,
rather than hiding behind a whole-file hash that can never match.

    python3 tests/test_parity.py <corpus-dir>
"""
import glob
import hashlib
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# web_build.py imports fontkit, which lives with the skill in scripts/.
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "web", "py"))
from fontTools.ttLib import TTFont
import web_build as wb

ALLOWED_NAME_IDS = {5}       # the mandated stamp, and nothing else
# Rewritten by fontTools on every save, from the clock and the file contents.
# Neither says anything about whether the two builds agree.
# `created` moves too whenever a face goes through the Arabic graft, because
# fontTools' Merger builds a fresh font rather than editing one in place.
ALLOWED_HEAD_FIELDS = {"modified", "created", "checkSumAdjustment"}


def table_hashes(path):
    f = TTFont(path)
    out = {}
    for tag in sorted(f.reader.keys()):
        out[tag] = hashlib.sha256(f.reader[tag]).hexdigest()[:16]
    f.close()
    return out


def head_fields(path):
    f = TTFont(path)
    head = f["head"]
    out = {k: getattr(head, k) for k in vars(head) if not k.startswith("_")}
    f.close()
    return out


def name_records(path):
    f = TTFont(path)
    recs = {(r.nameID, r.platformID, r.platEncID, r.langID): str(r)
            for r in f["name"].names}
    f.close()
    return recs


def main(corpus):
    paths = sorted(glob.glob(os.path.join(corpus, "*.ttf")) +
                   glob.glob(os.path.join(corpus, "*.otf")))
    label = os.path.basename(corpus.rstrip("/"))
    ref = os.path.join(ROOT, "tests/out/parity-ref", label)
    mine = os.path.join(ROOT, "tests/out/parity-web", label)
    for d in (ref, mine):
        shutil.rmtree(d, ignore_errors=True)

    subprocess.run([sys.executable, os.path.join(ROOT, "scripts/build_family.py"),
                    corpus, "--out", ref, "--version", "2.000"],
                   check=True, capture_output=True)
    wb.build(paths, {"out_dir": mine,
                     "manifest": os.path.join(ROOT, "assets/currencies.json"),
                     "route": "merge", "version": "2.000"}, progress=None)

    ref_faces = {os.path.basename(p): p
                 for p in glob.glob(os.path.join(ref, "otf", "*"))}
    my_faces = {os.path.basename(p): p
                for p in glob.glob(os.path.join(mine, "*.ttf")) +
                         glob.glob(os.path.join(mine, "*.otf"))}

    print(f"corpus {label}: {len(ref_faces)} reference faces, {len(my_faces)} web faces")
    if set(ref_faces) != set(my_faces):
        print(f"FAIL different file sets\n  only in ref: {sorted(set(ref_faces)-set(my_faces))}"
              f"\n  only in web: {sorted(set(my_faces)-set(ref_faces))}")
        return 1

    bad = 0
    for name in sorted(ref_faces):
        a, b = table_hashes(ref_faces[name]), table_hashes(my_faces[name])
        if set(a) != set(b):
            print(f"FAIL {name}: table sets differ {set(a) ^ set(b)}")
            bad += 1
            continue
        differing = sorted(t for t in a if a[t] != b[t])
        identical = len(a) - len(differing)
        extra = [t for t in differing if t not in ("name", "head")]
        notes = []
        if "head" in differing:
            ha, hb = head_fields(ref_faces[name]), head_fields(my_faces[name])
            changed = sorted(k for k in set(ha) | set(hb) if ha.get(k) != hb.get(k))
            unexpected = [k for k in changed if k not in ALLOWED_HEAD_FIELDS]
            notes.append("head: " + ", ".join(changed))
            if unexpected:
                extra.append("head")
                notes[-1] += f"  UNEXPECTED {unexpected}"
        if "name" in differing:
            ra, rb = name_records(ref_faces[name]), name_records(my_faces[name])
            keys = set(ra) | set(rb)
            changed = sorted({k for k in keys if ra.get(k) != rb.get(k)})
            unexpected = [k for k in changed if k[0] not in ALLOWED_NAME_IDS]
            notes.append(f"name: nameID {sorted({k[0] for k in changed})}")
            if unexpected:
                extra.append("name")
                notes[-1] += f"  UNEXPECTED {sorted({k[0] for k in unexpected})}"
        if extra:
            print(f"FAIL {name}: {identical}/{len(a)} tables identical; "
                  f"unexpected differences in {extra}  {'; '.join(notes)}")
            bad += 1
        else:
            print(f"  ok {name[:44]:44} {identical}/{len(a)} tables byte-identical"
                  f"{('; ' + '; '.join(notes)) if notes else ''}")
    if bad:
        print(f"\n{bad} face(s) differ beyond the mandated stamp")
        return 1
    print(f"\nPASS all {len(ref_faces)} faces match the command-line build; the only "
          f"differences are the nameID 5 stamp the plan requires and the save "
          f"timestamp/checksum")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1
                  else os.path.join(ROOT, "tests/fonts/plex-arabic")))
