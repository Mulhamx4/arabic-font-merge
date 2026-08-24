#!/usr/bin/env python3
"""Exercise web_build.py outside the browser. Same code the worker runs."""
import glob, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# web_build.py imports fontkit, which lives with the skill in scripts/.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "web", "py"))
import web_build as wb
import fixtures

MANIFEST = os.path.join(ROOT, "assets", "currencies.json")


def run(label, folder, **opts):
    paths = sorted(glob.glob(os.path.join(folder, "*.ttf")) +
                   glob.glob(os.path.join(folder, "*.otf")))
    print(f"\n{'='*72}\n{label}  ({len(paths)} files)\n{'='*72}")
    info = wb.inspect_paths(paths)
    print(f"route={info['route']}  family={info['family_root']!r}  "
          f"ofl={info['ofl']}  graft={info['can_graft_arabic']}  "
          f"variable={info['variable_files']}  blocked={info['blocked_files']}")
    for w in info["warnings"]:
        print(f"  warn: {w['kind']} {w['detail']}")
    if info["name_problems"]:
        print(f"  name problems: {len(info['name_problems'])}")

    out = os.path.join(HERE, "out", label)
    shutil.rmtree(out, ignore_errors=True)
    o = {"out_dir": out, "manifest": MANIFEST, "route": info["route"],
         "version": "2.000"}
    o.update(opts)
    if info["ofl"] and not o.get("rename_suffix"):
        o["rename_suffix"] = "ZMKN"          # OFL forces a rename
    res = wb.build(paths, o, progress=None)

    print(f"\nbuilt in {res['seconds']}s   family={res['family']!r}   "
          f"failures={res['failures']}")
    print(f"{'face':38} {'glyphs':>13} {'sym':>4} {'calt':>5} {'graft':>6} {'VF fix':>7}  verdict")
    for r in res["faces"]:
        v = r["verify"]
        fails = [f for f in v["findings"] if f["level"] == "fail"]
        verdict = "PASS" if not fails else "FAIL " + ",".join(f["kind"] for f in fails)
        print(f"{r['face'][:38]:38} {v['glyphs_before']:>6}->{v['glyphs_after']:<6} "
              f"{r['symbols']:>4} {r['shortcuts']:>5} "
              f"{'yes' if r['grafted'] else '-':>6} "
              f"{'yes' if r['variable_fix']['applied'] else '-':>7}  {verdict}")
        for f in v["findings"]:
            if f["level"] != "fail":
                print(f"      {f['level']}: {f['kind']} {f.get('count','')} {f.get('sample','')}")
    print("outputs:")
    for x in res["outputs"]:
        print(f"  {x['kind']:11} {x['name'][:52]:52} {x['bytes']//1024:>6} KB")
    return res


CORPORA = {
    "glyf": "plex-arabic",
    "cff": "plex-cff",
    "mixed": "mixed-italic",
    "vf": "variable",
}

if __name__ == "__main__":
    sel = sys.argv[1] if len(sys.argv) > 1 else "all"
    chosen = CORPORA if sel == "all" else {sel: CORPORA[sel]}
    total, ran, skipped = 0, 0, []
    for label, folder in chosen.items():
        path = os.path.join(HERE, "fonts", folder)
        if not (os.path.isdir(path) and any(
                f.lower().endswith((".ttf", ".otf")) for f in os.listdir(path))):
            skipped.append(label)
            continue
        res = run(label, path)
        total += res["failures"]
        ran += 1

    # Never report success without having built anything: fall back to whatever
    # font is available, which in CI is the synthetic family.
    if ran == 0:
        res = run("fallback", fixtures.base_family())
        total += res["failures"]
        ran = 1

    print(f"\n{'-' * 72}")
    if skipped:
        print(f"skipped (no fixtures, run tests/fetch_fonts.sh): {', '.join(skipped)}")
    if total:
        print(f"{total} verification failure(s) across {ran} corpus/corpora")
    else:
        print(f"all {ran} corpus/corpora built clean")
    sys.exit(1 if total else 0)
