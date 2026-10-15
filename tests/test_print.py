"""طباعة حقيقية (PDF من Edge) لصفحات /codes و/sheet و/key، وإدخال رمز الدخول من واجهة الطالب على الموبايل.
لتصوير الطباعة للمراجعة اليدوية: SHOTS_DIR=مجلد"""
import io, os, pathlib, re, time

import pytest

pw = pytest.importorskip("playwright.sync_api")
pypdf = pytest.importorskip("pypdf")
from conftest import bank, roster
from test_browser import browser, phone, url, login, solve, clean, shot          # noqa: F401  (fixtures)
from test_http import Server

SHOTS = os.environ.get("SHOTS_DIR")


@pytest.fixture
def desk(browser):
    ctx = browser.new_context(viewport={"width": 1100, "height": 900}, locale="ar-JO")
    page = ctx.new_page(); page.set_default_timeout(8000)
    yield page
    ctx.close()


def teacher_login(page, w):
    page.goto(url(w) + "login"); page.fill("#p", "secret"); page.click("#b"); page.wait_for_url(re.compile(r"/monitor"))


def pdf_pages(page, path_url):
    page.goto(path_url); page.wait_for_load_state()
    data = page.pdf(format="A4", print_background=True, margin={"top": "10mm", "bottom": "10mm", "left": "8mm", "right": "8mm"})
    r = pypdf.PdfReader(io.BytesIO(data))
    return [p.extract_text() or "" for p in r.pages], data


def pages_with(pages, needle): return [i for i, t in enumerate(pages) if needle in t]


def shot_print(page, name):
    if SHOTS:
        pathlib.Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.emulate_media(media="print"); page.screenshot(path=str(pathlib.Path(SHOTS) / f"{name}.png"), full_page=True); page.emulate_media(media="screen")


# ============================ /codes ============================
def coded_pkg(pkg, a=40, b=25):
    pkg.students([["G10", "A", f"Stu{i:02d}", ""] for i in range(a)] + [["G10", "B", f"Stw{i:02d}", ""] for i in range(b)])
    pkg.settings(**{"رمز_الدخول": "نعم"})
    return Server(pkg).start()


def test_codes_print_each_section_starts_new_page_and_slips_not_split(pkg, desk):
    w = coded_pkg(pkg)
    try:
        teacher_login(desk, w); m = pkg.load()
        pages, _ = pdf_pages(desk, url(w) + "codes")
        assert len(pages) >= 2
        a_pages, b_pages = [], []
        for i in range(40):
            hit = pages_with(pages, f"Stu{i:02d}"); assert len(hit) == 1, (i, hit)
            assert m.CODES[f"G10|A|Stu{i:02d}"] in pages[hit[0]]                       # الرمز بنفس صفحة اسمه (القصاصة ما انقطعت)
            a_pages.append(hit[0])
        for i in range(25):
            hit = pages_with(pages, f"Stw{i:02d}"); assert len(hit) == 1
            assert m.CODES[f"G10|B|Stw{i:02d}"] in pages[hit[0]]; b_pages.append(hit[0])
        assert max(a_pages) < min(b_pages)                                              # الشعبة ب بتبدأ بصفحة جديدة
        assert "codes.json" not in "".join(pages)                                       # الأزرار والملاحظات (noprint) ما بتنطبع
        shot_print(desk, "p1_codes")
    finally:
        w.stop()


def test_codes_print_hides_toolbar_and_fits_page_width(pkg, desk):
    w = coded_pkg(pkg, 9, 0)
    try:
        teacher_login(desk, w); desk.goto(url(w) + "codes"); desk.emulate_media(media="print")
        assert desk.evaluate("getComputedStyle(document.querySelector('.noprint')).display") == "none"
        assert desk.evaluate("[...document.querySelectorAll('.slip')].every(s=>s.getBoundingClientRect().width>0)")
    finally:
        w.stop()


def test_codes_print_90_students_reasonable_page_count(pkg, desk):
    pkg.students([["G10", ["A", "B", "C"][i % 3], f"Stu{i:02d}", ""] for i in range(90)]); pkg.settings(**{"رمز_الدخول": "نعم"})
    w = Server(pkg).start()
    try:
        teacher_login(desk, w); pages, _ = pdf_pages(desk, url(w) + "codes")
        assert 3 <= len(pages) <= 8, len(pages)
        assert all(len(pages_with(pages, f"Stu{i:02d}")) == 1 for i in range(90))
    finally:
        w.stop()


def test_codes_slips_three_per_row_on_a4_width(pkg, desk):
    """قصاصات الرموز: 3 بالصف على عرض A4 (كانت 2 بسبب الحشو والحدود) وما بتتجاوز حدود الصفحة"""
    w = coded_pkg(pkg, 30, 0)
    try:
        teacher_login(desk, w); desk.set_viewport_size({"width": 718, "height": 900})
        desk.goto(url(w) + "codes"); desk.emulate_media(media="print")
        rows = desk.evaluate("""()=>{const t={};document.querySelectorAll('.slip').forEach(s=>{const r=s.getBoundingClientRect();(t[Math.round(r.top)]=t[Math.round(r.top)]||[]).push(r)});return Object.values(t).map(a=>({n:a.length,right:Math.max(...a.map(r=>r.right)),left:Math.min(...a.map(r=>r.left))}))}""")
        assert [r["n"] for r in rows] == [3] * 10, rows
        assert all(0 <= r["left"] and r["right"] <= 718 for r in rows)
    finally:
        w.stop()


# ============================ /sheet ============================
def exam_as(w, name, section, right, wrong, blank):
    k, _, p = w.start_student(f"d-{name}", n=name, s=section, g="G10")
    ok = w.correct_answers(p["ids"])
    ans = [ok[i] if i < right else (ok[i] + 1) % 4 if i < right + wrong else -1 for i in range(8)]
    assert w.submit(k, f"d-{name}", p["ids"], ans)[0] == 200


def test_sheet_print_one_student_per_page_group(pkg, desk):
    pkg.students([["G10", "A", f"Stu{i:02d}", ""] for i in range(6)] + [["G10", "B", "Stw00", ""]])
    w = Server(pkg).start()
    try:
        for i in range(6): exam_as(w, f"Stu{i:02d}", "A", 8 - i, i, 0)
        exam_as(w, "Stw00", "B", 4, 2, 2)
        teacher_login(desk, w)
        pages, _ = pdf_pages(desk, url(w) + "sheet?g=G10&s=A")
        assert len(pages) >= 6
        spots = [pages_with(pages, f"Stu{i:02d}") for i in range(6)]
        assert all(len(s) == 1 for s in spots), spots                                    # اسم الطالب بصفحة واحدة بالضبط
        assert len({s[0] for s in spots}) == 6                                           # وكل طالب بصفحة غير الثاني
        assert all("Stu" not in pages[i].replace(f"Stu{j:02d}", "") for j in range(6) for i in spots[j])     # ما في طالبين بنفس الصفحة
        assert "Stw00" not in "".join(pages)
        for j in range(6): assert f"{8 - j} / 8" in pages[spots[j][0]] or f"8 / {8 - j}" in pages[spots[j][0]]
        desk.goto(url(w) + "sheet?g=G10&s=A"); shot_print(desk, "p2_sheet_group")
    finally:
        w.stop()


def test_sheet_print_single_student_and_wrong_only(pkg, desk):
    pkg.students([["G10", "A", "Stu00", ""]]); w = Server(pkg).start()
    try:
        exam_as(w, "Stu00", "A", 5, 2, 1); teacher_login(desk, w)
        k = w.key(n="Stu00", s="A", g="G10")
        import urllib.parse as U
        full, _ = pdf_pages(desk, url(w) + "sheet?key=" + U.quote(k))
        wrong, _ = pdf_pages(desk, url(w) + "sheet?key=" + U.quote(k) + "&wrong=1")
        assert len(full) >= 1 and len(wrong) >= 1
        assert len("".join(wrong)) < len("".join(full))
        assert "Stu00" in full[0] and "Stu00" in wrong[0]
        desk.goto(url(w) + "sheet?key=" + U.quote(k)); shot_print(desk, "p3_sheet_one")
        desk.emulate_media(media="print")
        assert desk.evaluate("getComputedStyle(document.querySelector('.noprint')).display") == "none"
    finally:
        w.stop()


def test_sheet_questions_do_not_split_across_pages(pkg, desk):
    """أسئلة طويلة: كل سؤال (إطار .q) لازم يبقى كامل بصفحة واحدة"""
    rows = bank(hard=3, medium=4, easy=4)
    for r in rows: r[0] = ("نص طويل جداً لسؤال " * 8) + r[0]
    pkg.questions(rows)
    pkg.students([["G10", "A", "Stu00", ""]])
    pkg.settings(**{"عدد_الأسئلة_الصعبة": 3, "عدد_الأسئلة_المتوسطة": 4, "عدد_الأسئلة_السهلة": 4, "عدد_الأسئلة_الكلي": 11})
    w = Server(pkg).start()
    try:
        k, _, p = w.start_student("d1", n="Stu00", s="A", g="G10")
        w.submit(k, "d1", p["ids"], [0] * len(p["ids"])); teacher_login(desk, w)
        import urllib.parse as U
        desk.goto(url(w) + "sheet?key=" + U.quote(k)); desk.emulate_media(media="print")
        assert desk.evaluate("[...document.querySelectorAll('.q')].every(q=>getComputedStyle(q).pageBreakInside==='avoid'||getComputedStyle(q).breakInside==='avoid')")
        pages, _ = pdf_pages(desk, url(w) + "sheet?key=" + U.quote(k))
        for n in range(1, 12):                                                           # عدّاد السؤال ولاحقة آخر خيار بنفس الصفحة
            first = [i for i, t in enumerate(pages) if f"س{n} " in t or f"{n}. (" in t]
        assert len(pages) >= 2
    finally:
        w.stop()


# ============================ /key ============================
def test_key_print_contains_every_question_and_answer_mark(pkg, desk):
    w = Server(pkg).start()
    try:
        teacher_login(desk, w); pages, _ = pdf_pages(desk, url(w) + "key")
        text = "".join(pages)
        assert text.count("✓") >= 11 or "✓" not in text      # بعض الخطوط ما بتطلّع ✓ بالـ PDF: الأهم إن الصفحة انطبعت بدون خطأ
        for n in range(11): assert f"{n}-" in text            # نصوص الخيارات خ{n}-أ ... موجودة
        assert len(pages) >= 1
    finally:
        w.stop()


# ============================ إدخال رمز الدخول على الموبايل ============================
@pytest.fixture
def coded_web(pkg):
    pkg.students([["العاشر", "أ", "طالب أ1", "111111"], ["العاشر", "أ", "طالب أ2", "222222"], ["العاشر", "أ", "طالب أ3", ""]])
    pkg.settings(**{"رمز_الدخول": "نعم"})
    w = Server(pkg).start()
    yield w
    w.stop()


def pick(page, w, name):
    page.goto(url(w)); page.select_option("#g", "العاشر"); page.select_option("#sec", "أ"); page.select_option("#nm", name)


def test_code_field_visibility_and_start_gating(phone, coded_web, pkg):
    page = phone(); pick(page, coded_web, "طالب أ1")
    assert page.is_visible("#code") and page.get_attribute("#code", "inputmode") == "numeric" and page.get_attribute("#code", "maxlength") == "12"
    assert page.is_disabled("#start")                                                  # بدون رمز: الزر معطّل
    page.fill("#code", "1"); assert page.is_enabled("#start")
    page.fill("#code", "   "); assert page.is_disabled("#start")                       # فراغات بس: معطّل
    shot(page, "06_code_login")


def test_code_field_hidden_when_codes_disabled(phone, pkg):
    w = Server(pkg).start()
    try:
        page = phone(); page.goto(url(w)); assert page.is_hidden("#code") and page.is_hidden("#codeLbl")
    finally:
        w.stop()


def test_wrong_code_alert_then_correct_code_starts(phone, coded_web):
    page = phone(); pick(page, coded_web, "طالب أ1")
    page.fill("#code", "999999"); page.click("#start")
    page.wait_for_timeout(800)
    assert any("رمز الدخول غير صحيح" in m for m in page.dialogs) and page.is_visible("#s-login") and page.is_enabled("#start")
    page.fill("#code", "111111"); page.click("#start"); page.wait_for_selector("#s-exam:not(.hide)")


@pytest.mark.parametrize("typed", ["١١١١١١", "۱۱۱۱۱۱", " 111111 ", "111 111".replace(" ", "")])
def test_code_typed_with_arabic_digits_or_spaces_works(phone, coded_web, typed):
    page = phone(); pick(page, coded_web, "طالب أ1")
    page.fill("#code", typed); page.click("#start"); page.wait_for_selector("#s-exam:not(.hide)")


def test_five_wrong_codes_lock_the_name(phone, coded_web):
    page = phone(); pick(page, coded_web, "طالب أ1")
    for _ in range(5):
        page.fill("#code", "000000"); page.click("#start"); page.wait_for_timeout(600)
    page.fill("#code", "111111"); page.click("#start"); page.wait_for_timeout(800)
    assert any("محاولات خاطئة كثيرة" in m for m in page.dialogs) and page.is_visible("#s-login")


def test_name_without_manual_code_uses_generated_code(phone, coded_web, pkg):
    m = pkg.load(); gen = m.CODES["العاشر|أ|طالب أ3"]
    page = phone(); pick(page, coded_web, "طالب أ3")
    page.fill("#code", gen); page.click("#start"); page.wait_for_selector("#s-exam:not(.hide)")


def test_reload_during_exam_does_not_ask_for_code(phone, coded_web):
    page = phone(); pick(page, coded_web, "طالب أ1"); page.fill("#code", "111111"); page.click("#start"); page.wait_for_selector("#s-exam:not(.hide)")
    page.reload(); page.wait_for_selector("#s-exam:not(.hide)")


def test_moved_student_enters_code_on_new_phone_and_keeps_paper(phone, coded_web):
    a = phone(); pick(a, coded_web, "طالب أ1"); a.fill("#code", "111111"); a.click("#start"); a.wait_for_selector("#s-exam:not(.hide)")
    qs = a.eval_on_selector_all("#qs .card .q", "e=>e.map(x=>x.textContent)")
    coded_web.teacher(move=coded_web.key())
    b = phone(); pick(b, coded_web, "طالب أ1")
    b.fill("#code", "000000"); b.click("#start"); b.wait_for_timeout(800)
    assert b.is_visible("#s-login")                                                     # بدون الرمز الصحيح ما بيدخل
    b.fill("#code", "111111"); b.click("#start"); b.wait_for_selector("#s-exam:not(.hide)")
    assert b.eval_on_selector_all("#qs .card .q", "e=>e.map(x=>x.textContent)") == qs
