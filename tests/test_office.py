"""ملفات أسئلة طلعت من Excel وLibreOffice الحقيقيين (مش من openpyxl): قارئ xlsx/csv الخاص بالسيرفر لازم يقرأها زي ما الأستاذ بيشوفها.
بتتخطّى لو Excel أو LibreOffice مش مثبّتين. لتسريع التشغيل المتكرر: OFFICE_DIR=مجلد ملفات مولّدة سابقاً (بيطبعه office_gen.py)."""
import os, pathlib, re

import openpyxl
import pytest
from conftest import Pkg, CODE_FILES, PKG_SRC, copy_any
import office_gen

pytestmark = pytest.mark.skipif(os.name != "nt" or not os.path.exists(office_gen.SOFFICE) or not os.path.exists(office_gen.EXCEL), reason="Excel/LibreOffice غير مثبّتين")


@pytest.fixture(scope="session")
def office(tmp_path_factory):
    d = os.environ.get("OFFICE_DIR")
    if d and pathlib.Path(d).exists():
        d = pathlib.Path(d)
        return {f.name: f for f in d.iterdir() if f.suffix.lower() in (".xlsx", ".csv", ".xls")}
    try:
        files = office_gen.generate(tmp_path_factory.mktemp("office"))
    except RuntimeError as e:
        pytest.skip(str(e))
    if not any(k.startswith("excel_") for k in files): pytest.skip("Excel COM ما اشتغل: " + files.get("_excel_log", "")[:200])
    return files


def need(office, name):
    if name not in office: pytest.skip(f"{name} ما انولّد")
    return office[name]


@pytest.fixture
def shell(tmp_path):
    """مجلد حزمة سليم لنقدر نستعمل read_table ونحمّل السيرفر بملف الأسئلة اللي بدنا إياه"""
    import shutil
    for f in CODE_FILES: copy_any(PKG_SRC / f, tmp_path / f)
    pk = Pkg(tmp_path); pk.questions(); pk.students(); pk.settings()
    return pk


def oracle(path):
    ws = openpyxl.load_workbook(path, data_only=True).worksheets[0]
    return [[("" if c is None else c) for c in r] for r in ws.iter_rows(values_only=True)]


def norm(v):
    if isinstance(v, float) and v == int(v): v = int(v)
    return str(v)


# ============================ إعادة حفظ عادية: لازم تنقرأ مطابقة 100% ============================
@pytest.mark.parametrize("name", ["excel_plain.xlsx", "lo_plain.xlsx", "excel_table.xlsx"])
def test_plain_resave_matches_openpyxl_cell_by_cell(office, shell, name):
    f = need(office, name); m = shell.load()
    got, ref = m.read_table(str(f)), oracle(f)
    assert len(got) == len(ref) == 12
    for i, (g, r) in enumerate(zip(got, ref), 1):
        for j in range(max(len(g), len(r))):
            a = g[j] if j < len(g) else ""; b = r[j] if j < len(r) else ""
            assert a == norm(b) or (a == "" and b == ""), (name, i, j + 1, a, b)


@pytest.mark.parametrize("name", ["excel_plain.xlsx", "lo_plain.xlsx", "excel_table.xlsx"])
def test_plain_resave_loads_as_exam_identically_to_original(office, shell, name):
    f = need(office, name)
    base = shell.load().QLIST
    (shell.path / "questions.xlsx").write_bytes(f.read_bytes())
    m = shell.load()
    assert [(q["q"], q["o"], q["a"], q["level"]) for q in m.QLIST] == [(q["q"], q["o"], q["a"], q["level"]) for q in base]


@pytest.mark.parametrize("name", ["excel_utf8.csv", "lo_utf8.csv"])
def test_csv_utf8_from_office_loads_identically(office, shell, name):
    f = need(office, name)
    base = shell.load().QLIST
    shell.p("questions.xlsx").unlink(); (shell.path / "questions.csv").write_bytes(f.read_bytes())
    m = shell.load()
    assert [(q["q"], q["o"], q["a"], q["level"]) for q in m.QLIST] == [(q["q"], q["o"], q["a"], q["level"]) for q in base]


def test_features_file_whole_exam_still_loads_in_excel_and_libreoffice(office, shell):
    for name in ("excel_features.xlsx", "lo_features.xlsx"):
        f = need(office, name); (shell.path / "questions.xlsx").write_bytes(f.read_bytes())
        shell.settings(**{"عدد_الأسئلة_الصعبة": 3, "عدد_الأسئلة_المتوسطة": 4, "عدد_الأسئلة_السهلة": 4 + 0, "عدد_الأسئلة_الكلي": 11})
        m = shell.load()
        assert len(m.QLIST) == 22 - 1


# ============================ خصائص صعبة (صفوف 13..22 بملف الـ features) ============================
@pytest.fixture(params=["excel_features.xlsx", "lo_features.xlsx"])
def feat(request, office, shell):
    f = need(office, request.param); m = shell.load()
    rows = m.read_table(str(f))
    return {r[0].split()[0]: r for r in rows[12:]}, request.param


def test_formulas_numeric_and_text_results(feat):
    r, _ = feat; r = r["Q14"]
    assert r[1] == "5" and r[2] == "abcd"


def test_rich_text_cell_is_plain_text(feat):
    r, _ = feat
    assert r["Bold"][0] == "Bold start then normal text"


def test_line_breaks_inside_cells_preserved(feat):
    r, _ = feat; r = r["Q18"]
    assert r[0] == "Q18 line1\nline2" and r[1] == "o1\no2"


def test_text_formatted_and_apostrophe_cells_keep_leading_zero(feat):
    r, _ = feat; r = r["Q17"]
    assert r[1] == "012345" and r[3] == "012345"                             # نص: الصفر محفوظ
    assert r[2] == "12345" and r[4] == "0.5"                                 # رقم عادي: إكسل نفسه بيشيل الصفر


def test_error_values_become_visible_text_not_crash(feat):
    r, _ = feat; r = r["Q20"]
    assert r[1] == "#N/A" and r[2] == "#DIV/0!" and r[3] == "ok"


def test_padded_text_is_trimmed_and_inner_tabs_kept(feat):
    r, _ = feat; r = r["Q22"]
    assert r[1] == "padded" and r[2] == "tab\tinside"


def test_big_numbers_not_in_scientific_notation(feat):
    r, _ = feat; r = r["Q19"]
    assert r[1] == "1234567890123456" and r[4] == "-0.5" and r[3] == "100000000000000000000"


# ---- اكتشافات: الطالب بيشوف غير اللي شافه الأستاذ بإكسل ----


def test_boolean_cells_keep_their_words(feat):
    r, _ = feat; r = r["Q13"]
    assert r[1].upper() == "TRUE" and r[2].upper() == "FALSE"


def test_formula_returning_true_keeps_word(feat):
    r, _ = feat
    assert r["Q14"][4].upper() == "TRUE"


def test_float_noise_is_not_shown_to_students(feat):
    r, name = feat
    ok = r["Q14"][3] in ("0.333333333333333", "0.3333333333333333") and r["Q19"][2] == "0.3"
    assert ok, (r["Q14"][3], r["Q19"][2])


def test_date_cells_are_not_bare_serial_numbers(feat):
    r, _ = feat; r = r["Q16"]
    assert r[1] == "1948-01-02" and re.fullmatch(r"\d{4}-01-02", r[2])        # تاريخ مكتوب: بيطلع بصيغة ISO بدل الرقم التسلسلي 17534
    assert r[3] == "1/2"                                                      # الخلية النصية سليمة


def test_percent_cells_keep_percent_sign(feat):
    r, _ = feat; r = r["Q21"]
    assert r[1] == "25%" and r[2] == "25%"
    assert r[3] == "5" and r[4] == "1000"                                    # العملة والفاصلة بتنقرأ كأرقام (مقبول)


# ============================ ورقة غلط / صف عنوان فوق الترويسة ============================


@pytest.mark.parametrize("name", ["excel_notes_first.xlsx", "excel_hidden_first.xlsx"])
def test_questions_found_even_if_not_first_sheet(office, shell, name):
    f = need(office, name); (shell.path / "questions.xlsx").write_bytes(f.read_bytes())
    assert len(shell.load().QLIST) == 11


@pytest.mark.parametrize("name", ["excel_notes_first.xlsx", "excel_hidden_first.xlsx"])
def test_wrong_first_sheet_today_gives_error_not_silent_wrong_exam(office, shell, name):
    """على الأقل مش بيمتحن الطلاب بورقة غلط: بيوقف برسالة (وإن كانت مضللة «فاضي»)"""
    f = need(office, name); (shell.path / "questions.xlsx").write_bytes(f.read_bytes())
    from conftest import LoadFailed
    try:
        shell.load()
    except LoadFailed as e:
        assert "فاضي" in str(e) or "سطر" in str(e)


def test_title_row_above_header_gives_row_numbered_error(office, shell):
    f = need(office, "excel_title_row.xlsx"); (shell.path / "questions.xlsx").write_bytes(f.read_bytes())
    msg = shell.expect_error("سطر 2")
    assert "العلامة" in msg                       # الرسالة بتشير للسطر 2 وبتعرض نص الترويسة «العلامة» اللي انقرأت كبيانات: كافية ليعرف الأستاذ


# ============================ CSV وصيغ قديمة ============================


def test_ansi_csv_with_lost_arabic_is_flagged(office, shell):
    f = need(office, "excel_ansi_arabic.csv"); data = f.read_bytes()
    if b"???" not in data: pytest.skip("هذا الجهاز بيحفظ ANSI بعربي (cp1256): ما في فقد")
    shell.p("questions.xlsx").unlink(); (shell.path / "questions.csv").write_bytes(data)
    msg = shell.expect_error("علامات استفهام", "UTF-8")                         # رسالة واضحة بدل امتحان أسئلته «؟؟؟»
    assert "سطر 2" in msg


def test_mac_csv_line_endings_load(office, shell):
    f = need(office, "excel_mac.csv"); shell.p("questions.xlsx").unlink(); (shell.path / "questions.csv").write_bytes(f.read_bytes())
    assert len(shell.load().QLIST) == 11


def test_saving_as_old_xls_gives_clear_not_found_message(office, shell):
    need(office, "excel_old.xls")
    shell.p("questions.xlsx").unlink()
    (shell.path / "questions.xls").write_bytes(office["excel_old.xls"].read_bytes())
    shell.expect_error("questions.xlsx")                                       # الرسالة بتذكر الاسم المطلوب
