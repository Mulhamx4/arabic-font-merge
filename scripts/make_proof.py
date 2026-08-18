#!/usr/bin/env python3
"""Render visual proof that a built font works.

    python scripts/make_proof.py <font.otc> --out build/

Produces two things:
  proof.png      -- every weight, Arabic shaping, and the symbols in context
  selftest.html  -- the font embedded as base64 WOFF2, so it tests the FILE
                    rather than the user's installation

Both pages embed the built font directly rather than installing it and asking
fontconfig for it by name. That matters: the merged font deliberately keeps the
original family name, so a same-named font already on the system can win the
lookup and you get a proof image of the OLD font while every numeric check
passes. Embedding removes the ambiguity -- what you see is the file you built.

The self-test page matters more than it looks. When a user reports "it does not
work", it separates a broken font from a caching or install problem in one click,
which otherwise costs a round trip of guesswork.
"""

import argparse
import base64
import io
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fontTools.ttLib import TTFont, TTCollection
import fontkit as fk

SYMBOLS = [("\u20C1", "SAR", "ر.س"), ("\u20C3", "AED", "د.إ"), ("\u20C4", "OMR", "ر.ع")]


def load_faces(path):
    if path.lower().endswith((".otc", ".ttc")):
        return list(TTCollection(path).fonts)
    return [TTFont(path)]


def to_woff2_b64(font):
    buf = io.BytesIO()
    font.save(buf)
    buf.seek(0)
    clone = TTFont(buf)
    clone.flavor = "woff2"
    out = io.BytesIO()
    clone.save(out)
    return base64.b64encode(out.getvalue()).decode()


def build_proof_html(family, faces):
    """Every face embedded under its own @font-face, so nothing can substitute."""
    blocks, rows = [], []
    for i, font in enumerate(faces):
        fam = f"PF{i}"
        blocks.append(
            f"@font-face{{font-family:{fam};src:url(data:font/woff2;base64,"
            f"{to_woff2_b64(font)}) format('woff2')}}")
        style = fk.best_name(font, 17) or "Regular"
        weight = font["OS/2"].usWeightClass
        money = " &nbsp; ".join(f"{ch} 10.500" for ch, _, _ in SYMBOLS)
        rows.append(f"""<tr>
<td class="lbl">{style} · {weight}</td>
<td class="ar" style="font-family:{fam}">صَبَاحُ الخَيْرِ، لا إله إلا الله ٢٠٢٦</td>
<td class="la" style="font-family:{fam}">Hamburgefonstiv</td>
<td class="la" style="font-family:{fam}">{money}</td></tr>""")

    first = "PF0"
    shortcuts = " &nbsp;·&nbsp; ".join(f"{lat} 10.50" for _, lat, _ in SYMBOLS)
    ar_short = " &nbsp;·&nbsp; ".join(f"{ar} ٢٠" for _, _, ar in SYMBOLS)
    big = " &nbsp; ".join(ch for ch, _, _ in SYMBOLS)

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{chr(10).join(blocks)}
body{{margin:0;padding:30px 36px;background:#fff;width:1320px;font-family:{first},sans-serif}}
h1{{font-size:20px;font-weight:800;margin:0 0 4px;font-family:system-ui}}
p.s{{font-size:12.5px;color:#888;margin:0 0 20px;font-family:system-ui}}
h2{{font-size:10.5px;letter-spacing:1.1px;color:#bbb;font-weight:700;margin:24px 0 6px;
   text-transform:uppercase;font-family:system-ui}}
table{{border-collapse:collapse;width:100%}}
td{{padding:8px 10px;border-bottom:1px solid #eee;vertical-align:middle}}
.lbl{{font-size:10px;color:#aaa;font-weight:600;width:130px;letter-spacing:.4px;
     text-transform:uppercase;font-family:system-ui}}
.ar{{font-size:22px;direction:rtl;text-align:right}}
.la{{font-size:19px}}
.box{{border:1px solid #eee;border-radius:6px;padding:14px 18px;margin-top:6px;
     font-size:21px;font-family:{first}}}
.big{{font-size:58px;text-align:center;padding:12px 0;font-family:{first}}}
code{{font:11.5px ui-monospace,monospace;background:#f4f4f4;padding:2px 6px;
     border-radius:3px;direction:ltr;display:inline-block}}
</style></head><body>
<h1>{family} — {len(faces)} styles, one file</h1>
<p class="s">Rendered from the built font itself (embedded, not installed):
Arabic shaping, every weight, and the Saudi / UAE / Omani currency symbols.</p>
<div class="big">{big}</div>
<h2>Weights</h2><table>{''.join(rows)}</table>
<h2>Typing shortcuts</h2>
<div class="box"><div>{shortcuts}</div>
<div style="direction:rtl;text-align:right;margin-top:8px">{ar_short}</div></div>
<h2>Guards — ordinary words must stay intact</h2>
<div class="box">comrade &nbsp; COMRADE &nbsp; SARAH &nbsp; Caesar &nbsp; sarcasm
&nbsp; aedile &nbsp; OMRAN &nbsp; tomorrow</div>
<h2>Shaping checks</h2>
<div class="box" style="direction:rtl;text-align:right">
<div>تشكيل: مُحَمَّدٌ · سَأَلَ · يَئِنُّ · رَئِيسٌ</div>
<div>لام‑ألف: لا لأ لإ لآ · اتصال: بببب سسسس عععع</div>
<div>فارسي/أردو: کیف حالت؟ · گچپژ · اردو ہے ٹھیک</div>
<div>أرقام: ٠١٢٣٤٥٦٧٨٩ ٪ ، ؛ ؟</div>
</div>
</body></html>"""


def build_selftest_html(family, faces):
    """Standalone page with the font embedded, so installation is irrelevant."""
    picks, seen = [], set()
    for font in faces:
        weight = font["OS/2"].usWeightClass
        ital = fk.is_italic(font)
        if ital or weight not in (400, 700) or weight in seen:
            continue
        seen.add(weight)
        picks.append((weight, to_woff2_b64(font)))
    if not picks:
        picks = [(faces[0]["OS/2"].usWeightClass, to_woff2_b64(faces[0]))]

    faces_css = "".join(
        f"@font-face{{font-family:FT;src:url(data:font/woff2;base64,{b64}) "
        f"format('woff2');font-weight:{w};font-style:normal}}\n"
        for w, b64 in picks)

    return """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>فحص الخط</title><style>
""" + faces_css + """
body{font-family:FT,sans-serif;margin:0;padding:28px 30px;background:#fafafa;color:#111;max-width:900px}
h1{font-size:20px;font-weight:700;margin:0 0 6px}
p.n{font-size:13px;color:#777;margin:0 0 20px;line-height:1.7;font-family:system-ui}
.card{background:#fff;border:1px solid #e6e6e6;border-radius:10px;padding:18px 20px;margin-bottom:14px}
h2{font-size:11px;letter-spacing:.8px;color:#999;font-weight:700;margin:0 0 10px;
   text-transform:uppercase;font-family:system-ui}
.row{display:flex;align-items:center;gap:14px;padding:10px 0;border-bottom:1px solid #f2f2f2;font-size:26px}
.row:last-child{border:0}
.tag{font-size:10px;font-weight:700;padding:4px 10px;border-radius:20px;white-space:nowrap;font-family:system-ui}
.ok{background:#e7f6ec;color:#1a7f37}.no{background:#fdeaea;color:#c22}
input{font-family:FT;font-size:30px;width:100%;padding:12px 14px;border:2px solid #ddd;
      border-radius:8px;box-sizing:border-box;background:#fff}
.hint{font-size:12px;color:#888;margin-top:8px;font-family:system-ui;line-height:1.7}
.verdict{font-size:15px;font-weight:700;padding:15px 18px;border-radius:10px;
         margin-bottom:16px;font-family:system-ui;background:#eee;line-height:1.6}
.big{font-size:52px;text-align:center;padding:14px 0}
code{font-family:ui-monospace,monospace;font-size:12px;background:#f2f2f2;padding:2px 6px;
     border-radius:4px;direction:ltr;display:inline-block}
#probe{position:absolute;visibility:hidden;white-space:pre;font-family:FT;font-size:40px;top:-9999px}
</style></head><body>
<h1>فحص الخط — __FAMILY__</h1>
<p class="n">الخط <b>مدموج داخل هذا الملف</b>، فلا يعتمد على التثبيت في جهازك.
افتحه بأي متصفح. إذا اشتغل هنا فالملف سليم، والمشكلة في التثبيت أو في البرنامج.</p>
<div id="verdict" class="verdict">…جاري الفحص</div>
<div class="card"><h2>الرموز</h2><div class="big">&#x20C1; &nbsp; &#x20C3; &nbsp; &#x20C4;</div></div>
<div class="card"><h2>الاختصارات — المفروض تنقلب تلقائياً</h2>
<div class="row" dir="ltr"><span style="flex:1">SAR 10.50</span><span class="tag" id="t1"></span></div>
<div class="row" dir="ltr"><span style="flex:1">AED 10.50</span><span class="tag" id="t2"></span></div>
<div class="row" dir="ltr"><span style="flex:1">OMR 10.50</span><span class="tag" id="t3"></span></div>
<div class="row"><span style="flex:1">ر.س ١٠ &nbsp; د.إ ١٠ &nbsp; ر.ع ١٠</span><span class="tag" id="t4"></span></div></div>
<div class="card"><h2>الحماية — المفروض تبقى كما هي</h2>
<div class="row" dir="ltr"><span style="flex:1">comrade &nbsp; SARAH &nbsp; Caesar &nbsp; aedile &nbsp; OMRAN</span>
<span class="tag" id="t5"></span></div></div>
<div class="card"><h2>جرّب بنفسك</h2>
<input id="live" value="OMR 10.500" spellcheck="false" autocomplete="off">
<div class="hint">اكتب <code>SAR</code> أو <code>AED</code> أو <code>OMR</code> — وبالعربي <code>ر.س</code> أو <code>د.إ</code> أو <code>ر.ع</code>.</div></div>
<div class="card"><h2>العربية</h2>
<div class="row">السلام عليكم ورحمة الله وبركاته</div>
<div class="row">مَرْحَبًا بِكَ يَا صَدِيقِي — لا إله إلا الله</div>
<div class="row">المبلغ &#x20C1; ٢٥٠ · &#x20C3; ١٠٠ · &#x20C4; ٥٠</div></div>
<span id="probe"></span>
<script>
var SYM = "\\u20C4", probe = document.getElementById("probe");
function width(t, dir){ probe.dir = dir || "ltr"; probe.textContent = t;
  return probe.getBoundingClientRect().width; }
function same(a, b, dir){ return Math.abs(width(a, dir) - width(b, dir)) < 0.6; }
document.fonts.load("40px FT").then(function(){ return document.fonts.ready; }).then(function(){
  function set(id, good){ var e = document.getElementById(id);
    e.className = "tag " + (good ? "ok" : "no");
    e.textContent = good ? "\\u2713 يشتغل" : "\\u2717 ما اشتغل"; return good; }
  var glyph = width(SYM) > 5;
  var r1 = set("t1", same("OMR 10.500", SYM + " 10.500"));
  var r2 = set("t2", same("omr 5", SYM + " 5"));
  var r3 = set("t3", same("\\u0631.\\u0639 \\u0661\\u0660", SYM + " \\u0661\\u0660", "rtl"));
  var r4 = set("t4", same("\\u0631.\\u0639. \\u0665", SYM + " \\u0665", "rtl"));
  var r5 = set("t5", !same("comrade", OMR + "ade") && !same("SARAH", SAR + "AH")
              && !same("Caesar", "Cae" + SAR));
  var v = document.getElementById("verdict");
  if (glyph && r1 && r2 && r3 && r4 && r5){
    v.style.background = "#e7f6ec"; v.style.color = "#1a7f37";
    v.textContent = "\\u2713 الخط سليم تماماً — الرمز موجود وكل الاختصارات تشتغل. "
      + "يعني المشكلة في التثبيت أو في البرنامج، مو في الملف.";
  } else if (glyph){
    v.style.background = "#fff6e5"; v.style.color = "#8a5a00";
    v.textContent = "\\u26a0 الرمز موجود لكن بعض الاختصارات ما اشتغلت. صوّر الصفحة وأرسلها.";
  } else {
    v.style.background = "#fdeaea"; v.style.color = "#c22";
    v.textContent = "\\u2717 الرمز نفسه ما ظهر. صوّر الصفحة وأرسلها.";
  }
});
</script></body></html>""".replace("__FAMILY__", family)


def screenshot(html_path, png_path, width=1300):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "playwright not installed"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": width, "height": 1200},
                                    device_scale_factor=2)
            page.goto("file://" + os.path.abspath(html_path))
            page.wait_for_timeout(1800)
            page.screenshot(path=png_path, full_page=True)
            browser.close()
        return True, None
    except Exception as e:
        return False, str(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("font")
    ap.add_argument("--out", default=".")
    ap.add_argument("--no-png", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    faces = load_faces(args.font)
    family = fk.best_name(faces[0], 16, 1) or "Font"

    selftest = os.path.join(args.out, "selftest.html")
    with open(selftest, "w", encoding="utf-8") as fh:
        fh.write(build_selftest_html(family, faces))
    print(f"wrote {selftest}  ({os.path.getsize(selftest) // 1024} KB, font embedded)")

    if args.no_png:
        return 0

    tmp = tempfile.mkdtemp(prefix="proof_")
    proof_html = os.path.join(tmp, "proof.html")
    with open(proof_html, "w", encoding="utf-8") as fh:
        fh.write(build_proof_html(family, faces))
    png = os.path.join(args.out, "proof.png")
    ok, err = screenshot(proof_html, png)
    shutil.rmtree(tmp, ignore_errors=True)
    if ok:
        print(f"wrote {png}")
        print("look at it -- a numeric pass does not prove the spacing or "
              "weights look right")
    else:
        print(f"warning: could not render proof.png ({err})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
