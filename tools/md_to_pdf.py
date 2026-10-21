# -*- coding: utf-8 -*-
"""
يحوّل ملف markdown عربي (دليل الأستاذ / تعليمات Claude) إلى PDF بنفس تصميم الأدلة الحالية، باستعمال Microsoft Edge (Chromium) على ويندوز.
الاستعمال:
    python md_to_pdf.py INPUT.md OUTPUT.pdf [--title "عنوان المستند"]
بيحتاج: pip install markdown     وEdge مثبّت (موجود افتراضياً بويندوز 10/11).
"""
import argparse, os, pathlib, re, subprocess, sys, tempfile

import markdown

EDGES = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]

CSS = """
@page { size: A4; margin: 16mm 15mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Tahoma, Arial, sans-serif; font-size: 13.5px; line-height: 1.85; color: #1c2733; margin: 0; }
h1 { font-size: 25px; color: #14566b; border-bottom: 2px solid #14566b; padding-bottom: 6px; margin: 0 0 14px; }
h2 { font-size: 19px; color: #1c2733; border-right: 5px solid #14566b; padding-right: 11px; margin: 26px 0 10px; page-break-after: avoid; }
h3 { font-size: 16px; color: #1c2733; margin: 20px 0 6px; page-break-after: avoid; }
p { margin: 6px 0 9px; }
ul, ol { margin: 6px 0 10px; padding-right: 24px; padding-left: 0; }
li { margin: 3px 0; }
li > ul, li > ol { margin: 3px 0; }
blockquote { background: #eef5f8; border-right: 4px solid #14566b; margin: 10px 0; padding: 6px 14px; page-break-inside: avoid; }
blockquote p { margin: 5px 0; }
code { font-family: Consolas, "Courier New", monospace; background: #eef1f4; padding: 1px 6px; border-radius: 4px; font-size: 12px; direction: ltr; unicode-bidi: embed; }
pre { background: #eef1f4; padding: 8px 12px; border-radius: 6px; direction: ltr; text-align: left; page-break-inside: avoid; overflow-wrap: anywhere; }
pre code { background: none; padding: 0; }
table { width: 100%; border-collapse: collapse; margin: 10px 0 14px; font-size: 13px; }
th { background: #e8f2f5; color: #14566b; text-align: right; }
th, td { border: 1px solid #cfd8de; padding: 7px 10px; text-align: right; vertical-align: top; }
tr { page-break-inside: avoid; }
hr { border: 0; border-top: 1px solid #cfd8de; margin: 22px 0 10px; }
em { color: #5d6b7a; }
strong { color: #0f3f50; }
img { max-width: 100%; height: auto; }
.fig { margin: 12px 0 16px; text-align: center; page-break-inside: avoid; }
.fig img { border: 1px solid #cfd8de; border-radius: 6px; box-shadow: 0 2px 8px #1c273318; }
.fig.narrow img { max-width: 62%; }
.fig.half { display: inline-block; width: 48.5%; vertical-align: top; margin: 8px 0.5%; }
.fig.half img { max-width: 100%; }
.fig.third { display: inline-block; width: 31.5%; vertical-align: top; margin: 8px 0.4%; }
.fig.third img { max-width: 100%; }
.fig figcaption { margin-top: 5px; color: #5d6b7a; font-size: 12px; line-height: 1.5; }
.ph { margin: 12px 0 16px; padding: 18px 16px; border: 2px dashed #d97706; border-radius: 8px; background: #fffbeb; text-align: center; color: #92400e; page-break-inside: avoid; }
.ph b { color: #92400e; }
.step { display: inline-block; min-width: 26px; padding: 0 8px; border-radius: 99px; background: #c2410c; color: #fff; font-weight: bold; text-align: center; }
.prompt { margin: 10px 0 14px; padding: 10px 14px; border: 1px solid #14566b; border-right-width: 5px; border-radius: 6px; background: #f4fafc; white-space: pre-wrap; page-break-inside: avoid; }
.warn { margin: 10px 0; padding: 8px 14px; border-right: 5px solid #b3261e; background: #fdeceb; border-radius: 4px; page-break-inside: avoid; }
.ok { margin: 10px 0; padding: 8px 14px; border-right: 5px solid #1b7f46; background: #e9f7ee; border-radius: 4px; page-break-inside: avoid; }
"""


COMPACT_CSS = """
@page { margin: 11mm 12mm; }
body { font-size: 12.9px; line-height: 1.66; }
h1 { font-size: 23px; margin-bottom: 6px; }
h2 { font-size: 16px; margin: 13px 0 4px; padding-right: 9px; border-right-width: 4px; }
ul { margin: 3px 0 5px; padding-right: 4px; list-style: none; }
li { margin: 1px 0; }
p { margin: 3px 0 5px; }
table { font-size: 12px; margin: 5px 0; }
th, td { padding: 4px 9px; }
code { font-size: 11.5px; }
"""


def find_edge():
    for p in EDGES:
        if os.path.exists(p): return p
    sys.exit("ما لقيت Microsoft Edge. ثبّته، أو عدّل EDGES بأول الملف.")


_LIST = re.compile(r"^\s*([-*+]|\d+\.)\s+")


def fix_lists(text):
    """GitHub بيعرض القائمة حتى لو جاءت مباشرة بعد سطر عادي؛ python-markdown بدّه سطر فاضي قبلها، وإلا بتنضغط كلها بفقرة وحدة"""
    NL, indent = chr(10), (chr(32), chr(9))
    out, prev = [], ""
    for line in text.split(NL):
        if _LIST.match(line) and not line.startswith(indent) and prev.strip() and not _LIST.match(prev) and not prev.lstrip().startswith(">") and not prev.startswith(indent):
            out.append("")
        out.append(line); prev = line
    return NL.join(out)


def inline_images(html, base):
    """الصور المحلية (src نسبي) بتنحط جوّا الصفحة نفسها (base64) عشان الـ PDF يطلع كامل بدون ملفات جانبية"""
    import base64, mimetypes
    def one(m):
        ref = m.group(2)
        if ref.startswith(("data:", "http:", "https:", "file:")): return m.group(0)
        f = (pathlib.Path(base) / ref).resolve()
        if not f.is_file(): sys.exit(f"الصورة غير موجودة: {ref}")
        return f'{m.group(1)}data:{mimetypes.guess_type(f.name)[0] or "image/png"};base64,{base64.b64encode(f.read_bytes()).decode()}"'
    return re.sub(r'(<img [^>]*?src=")([^"]+)"', one, html)


def md_to_html(md_text, title, compact=False, base=None):
    md_text = fix_lists(md_text)
    md_text = re.sub(r"^   - ", "    - ", md_text, flags=re.M)                  # python-markdown بدّه 4 مسافات للقوائم المتداخلة (الدليل بيستعمل 3)
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists", "attr_list"])
    if base is not None: body = inline_images(body, base)
    return f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>{title}</title><style>{CSS}{COMPACT_CSS if compact else ""}</style></head><body>{body}</body></html>'


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("input"); ap.add_argument("output"); ap.add_argument("--title"); ap.add_argument("--compact", action="store_true", help="خط أصغر وهوامش أقل (لقوائم الفحص بصفحة وحدة)")
    a = ap.parse_args()
    src = pathlib.Path(a.input); out = pathlib.Path(a.output).resolve()
    title = a.title or (re.search(r"^#\s+(.+)$", src.read_text(encoding="utf-8"), re.M) or [None, src.stem])[1]
    html = md_to_html(src.read_text(encoding="utf-8"), title, a.compact, base=src.parent)
    out.unlink(missing_ok=True)                           # بدونها: لو Edge ما أنتج شي، بنعتبر الـ PDF القديم هو الناتج ونطبع «تمّ» وهو ما اتغيّر
    with tempfile.TemporaryDirectory() as d:
        h = pathlib.Path(d) / "doc.html"; h.write_text(html, encoding="utf-8")
        # ملف تعريف (profile) مؤقت: بدونه، لو Edge مفتوح عند المستخدم بيتحوّل الطلب للنافذة المفتوحة وما بيطلع PDF
        with tempfile.TemporaryDirectory(prefix="md2pdf_edge_") as prof:
            r = subprocess.run([find_edge(), "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={prof}", f"--print-to-pdf={out}", h.as_uri()], capture_output=True, text=True, timeout=180)
        if not out.exists():                              # Edge بسطر الأوامر أحياناً بيرجع بدون ما يطبع شي (Edge مفتوح، أو برنامج حماية): نجرّب Playwright لو موجود
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    br = pw.chromium.launch(channel="msedge", headless=True); pg = br.new_page(); pg.goto(h.as_uri())
                    pg.pdf(path=str(out), prefer_css_page_size=True, print_background=True); br.close()
            except Exception as e: r.stderr += f"\n(Playwright: {e!r})"
    if not out.exists(): sys.exit("فشل توليد الـ PDF:\n" + r.stdout + r.stderr)
    print(f"تمّ: {out}  ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
