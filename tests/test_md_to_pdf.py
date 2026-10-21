"""tools/md_to_pdf.py: أداة توليد PDF الدليل من الـ markdown (Edge)."""
import importlib.util, os, pathlib, re, subprocess, sys

import pytest
from conftest import PKG_SRC

TOOL = PKG_SRC.parent / "tools" / "md_to_pdf.py"
pytestmark = pytest.mark.skipif(not TOOL.exists() or os.name != "nt", reason="الأداة أو ويندوز غير موجودين")
pymupdf = pytest.importorskip("pymupdf")
pytest.importorskip("markdown")


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("md_to_pdf_under_test", TOOL)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_list_after_plain_line_becomes_real_list(mod):
    html = mod.md_to_html("**عنوان**" + chr(10) + "- أول" + chr(10) + "- ثاني" + chr(10), "t")
    assert html.count("<li>") == 2 and "<ul>" in html


def test_three_space_nested_lists_are_nested(mod):
    html = mod.md_to_html("1. أول" + chr(10) + "   - فرعي" + chr(10) + "2. ثاني" + chr(10), "t")
    assert re.search(r"<li>أول\s*<ul>\s*<li>فرعي</li>", html)


def test_table_blockquote_code_and_rtl_html(mod):
    html = mod.md_to_html("| أ | ب |" + chr(10) + "|---|---|" + chr(10) + "| `x.py` | y |" + chr(10) + chr(10) + "> اقتباس **مهم**" + chr(10), "العنوان")
    assert "<table>" in html and "<code>x.py</code>" in html and "<blockquote>" in html and 'dir="rtl"' in html and "<title>العنوان</title>" in html


def test_real_guide_converts_to_pdf_with_new_sections(tmp_path):
    md = next(PKG_SRC.glob("_md_sources/00_*.md")); out = tmp_path / "دليل.pdf"
    r = subprocess.run([sys.executable, "-B", "-X", "utf8", str(TOOL), str(md), str(out), "--title", "دليل الأستاذ"], capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert r.returncode == 0 and out.exists(), r.stdout + r.stderr
    d = pymupdf.open(out); text = "".join(p.get_text() for p in d)
    assert 5 <= len(d) <= 10 and d.metadata.get("title") == "دليل الأستاذ"
    assert "exam_info.txt" in text and "exam_log.txt" in text and "check_report.txt" in text


@pytest.mark.parametrize("prefix", ["00_", "02_", "05_"])
def test_shipped_pdf_matches_current_markdown(prefix):
    """الـ PDF اللي بالحزمة لازم يكون مولّد من آخر نسخة من الـ markdown (ما ينسى حدا يحدّثه بعد تعديل الدليل)"""
    md = next(PKG_SRC.glob(f"_md_sources/{prefix}*.md")).read_text(encoding="utf-8")
    pdf = pymupdf.open(next(PKG_SRC.glob(f"{prefix}*.pdf"))); text = "".join(p.get_text() for p in pdf)
    for token in sorted(set(re.findall(r"`([A-Za-z_]+\.(?:txt|py|bat|html|xlsx|json|csv))`", md))):
        assert token in text, f"الـ PDF ما فيه «{token}» اللي بالـ markdown: ولّده من جديد بـ tools/md_to_pdf.py"
    for route in sorted(set(re.findall(r"localhost(?::\d+)?(/[a-z]+)", md))):
        assert route in text, f"الـ PDF ما فيه الرابط {route}"


def test_checklist_is_a_single_printable_page():
    pdf = pymupdf.open(next(PKG_SRC.glob("02_*.pdf")))
    assert len(pdf) == 1 and pdf.metadata.get("title") == "قائمة فحص الامتحان"
    text = pdf[0].get_text()
    for need in ("check_files.bat", "start.bat", "/health", "/ok", "/monitor", "results.csv", "report.xlsx", "python --version"): assert need in text, need


def test_compact_mode_is_smaller(mod):
    long_md = "# عنوان" + chr(10) * 2 + chr(10).join(f"- بند رقم {i}" for i in range(60))
    assert "font-size: 12.9px" in mod.md_to_html(long_md, "t", compact=True) and "font-size: 12.9px" not in mod.md_to_html(long_md, "t")
