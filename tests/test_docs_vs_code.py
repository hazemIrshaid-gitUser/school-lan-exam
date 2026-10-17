"""الدليل ضد الكود: كل ملف ورابط وإعداد مذكور بدليل الأستاذ وقائمة الفحص لازم يكون موجود فعلاً."""
import re

import pytest
from conftest import LoadFailed, PKG_SRC
from test_http import Server

MDS = sorted(PKG_SRC.glob("_md_sources/0[0234]_*.md"))
TEXT = "\n".join(p.read_text(encoding="utf-8") for p in MDS)


def test_every_file_in_the_guide_folder_table_exists():
    guide = next(PKG_SRC.glob("_md_sources/00_*.md")).read_text(encoding="utf-8")
    i = guide.index("## ماذا في هذا المجلد؟"); sec = guide[i:guide.index("\n## ", i + 1)]           # لحد العنوان الرئيسي اللي بعده
    names = set(re.findall(r"\*\*([^*|]+\.(?:pdf|bat|py))\*\*", sec)) | set(re.findall(r"`([A-Za-z_0-9.]+)`", sec))
    assert len(names) >= 10, names
    for n in sorted(names): assert (PKG_SRC / n).exists(), f"الدليل بيذكر «{n}» وهو مش موجود بالحزمة"


def test_all_pdfs_listed_are_present_and_nothing_important_is_missing_from_the_table():
    guide = next(PKG_SRC.glob("_md_sources/00_*.md")).read_text(encoding="utf-8")
    for f in PKG_SRC.iterdir():
        if f.is_file() and f.suffix in (".pdf", ".bat", ".py", ".html", ".xlsx", ".txt") and not f.name.startswith("00_"):      # الدليل ما بيذكر نفسه
            assert f.name in guide, f"الملف {f.name} موجود بالحزمة وما في ذكر إله بالدليل"


def test_every_page_url_in_docs_is_served(pkg):
    routes = sorted(set(re.findall(r"localhost(?::\d+)?(/[a-z]+(?:\.xlsx)?)", TEXT)) | set(re.findall(r"(/ok)\b", TEXT)))      # بدون نقطة آخر الجملة
    assert {"/monitor", "/report", "/sheet", "/key", "/teacher", "/codes", "/link", "/health"} <= set(routes), routes
    w = Server(pkg).start()
    try:
        for r in routes:
            st = w.get(r)[0]
            assert st in (200, 302), f"{r} بيرجع {st}"
    finally:
        w.stop()


def test_every_setting_key_in_docs_is_known_to_the_server(pkg):
    keys = sorted(set(re.findall(r"`([\u0600-\u06FF]+(?:_[\u0600-\u06FF]+)+)(?: = [^`]*)?`", TEXT)))
    assert len(keys) >= 8, keys
    for k in keys:
        pkg.raw_settings(f"{k} = نعم\n")
        try:
            pkg.load()
        except LoadFailed as e:
            assert "غير معروف" not in str(e), f"الدليل بيذكر الإعداد «{k}» والسيرفر ما بيعرفه"


@pytest.mark.parametrize("stem, most", [("00_", 8), ("02_", 1), ("03_", 1), ("04_", 1)])
def test_every_guide_has_its_pdf_and_printed_sheets_stay_one_page(stem, most):
    """الأوراق اللي بتنطبع (قائمة الفحص، ورقة الأستاذ، ورقة الطوارئ) صفحة وحدة؛ وكل مصدر md إله PDF بنفس الاسم"""
    pymupdf = pytest.importorskip("pymupdf")
    md = next(PKG_SRC.glob(f"_md_sources/{stem}*.md"))
    pdf = PKG_SRC / (md.stem + ".pdf")
    assert pdf.exists(), pdf.name
    assert pymupdf.open(str(pdf)).page_count <= most, pdf.name

