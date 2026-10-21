"""دليل الاستخدام المصوّر (05_): كل صورة مذكورة موجودة وما في صورة يتيمة، كل إعداد بـ settings.txt مشروح، كل رابط مذكور بيشتغل،
والـ PDF مولّد من آخر نسخة من الـ markdown وفيه الصور والخطوات العشر."""
import re

import pymupdf
import pytest
from conftest import PKG_SRC
from test_http import Server

MD_PATH = next(PKG_SRC.glob("_md_sources/05_*.md")); MD = MD_PATH.read_text(encoding="utf-8")
IMG_DIR = PKG_SRC / "_md_sources" / "guide_images"


def test_every_referenced_image_exists_and_none_is_orphan():
    refs = set(re.findall(r'src="guide_images/([^"]+)"', MD)); files = {f.name for f in IMG_DIR.iterdir()}
    assert refs and refs <= files, sorted(refs - files)
    assert files <= refs, f"صور مش مستعملة بالدليل: {sorted(files - refs)}"


def test_every_setting_in_settings_txt_is_explained():
    keys = re.findall(r"^([؀-ۿ_]+)\s*=", (PKG_SRC / "settings.txt").read_text(encoding="utf-8"), re.M)
    assert len(keys) >= 14
    for k in keys: assert f"`{k}`" in MD, f"الإعداد {k} مش مشروح بدليل الاستخدام المصوّر"


def test_every_page_in_the_guide_is_served(pkg):
    routes = sorted(set(re.findall(r"localhost(?::\d+)?(/[a-z-]+(?:\.xlsx)?)", MD)))
    assert {"/monitor", "/report", "/report.xlsx", "/sheet", "/key", "/teacher", "/codes", "/health", "/link", "/monitor-old"} <= set(routes), routes
    w = Server(pkg).start()
    try:
        for r in routes: assert w.get(r)[0] in (200, 302), r
    finally:
        w.stop()


def test_ten_steps_and_the_prompt_example_are_there():
    for n in range(1, 11): assert re.search(rf"^## الخطوة {n}:", MD, re.M), n
    assert 'class="prompt"' in MD and "01_تعليمات_Claude" in MD and "exam_data.zip" in MD and "figures_tool.py" in MD
    for f in ("questions_template.xlsx", "students_template.xlsx", "check_files.bat", "start.bat", "settings.txt", "report_problem.bat"): assert (PKG_SRC / f).exists() and f in MD, f


def test_shipped_pdf_is_current_and_has_the_images():
    pdf = pymupdf.open(next(PKG_SRC.glob("05_*.pdf"))); text = "".join(p.get_text() for p in pdf)
    assert pdf.metadata.get("title") == "دليل الاستخدام المصوّر" and 15 <= len(pdf) <= 45
    assert sum(len(p.get_images()) for p in pdf) >= len(set(re.findall(r'src="guide_images/', MD))) - 2
    for token in sorted(set(re.findall(r"`([A-Za-z_]+\.(?:txt|py|bat|html|xlsx|json|csv|zip|pdf))`", MD))): assert token in text, token
