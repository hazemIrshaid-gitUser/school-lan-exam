"""رموز دخول الطلاب (عمود «الرمز» + المولَّدة) وصفحات المعلم: /codes و/sheet — المحتوى والروابط والأمان (بدون متصفح؛ الطباعة الفعلية بـ test_print.py)."""
import json, re, urllib.parse

import pytest
from conftest import LETTERS, bank, key_of, roster, start_paper
from test_http import H, TEACHER, Server

TITLE = "اختبار الوحدة"


@pytest.fixture
def web(pkg):
    s = Server(pkg).start()
    yield s
    s.stop()


def cookie(w):
    return w.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0]


def tget(w, path, ck=None):
    return w.get(path, {"Cookie": ck or cookie(w)})


def html_of(resp): return resp[2].decode("utf-8")


def do_exam(w, name, section="أ", right=8, wrong=0, blank=0, dev=None):
    """طالب يبدأ ويسلّم: right صحيحة، wrong خاطئة، blank بدون إجابة (المجموع 8)"""
    dev = dev or f"d-{name}"
    k, _, p = w.start_student(dev, n=name, s=section)
    ok = w.correct_answers(p["ids"])
    ans = [ok[i] if i < right else (ok[i] + 1) % 4 if i < right + wrong else -1 for i in range(8)]
    assert w.submit(k, dev, p["ids"], ans)[0] == 200
    return k, p["ids"], ans


# =============================== رموز الدخول ===============================
def cell_codes(pkg, codes):
    pkg.students([["العاشر", "أ", f"طالب {i}", c] for i, c in enumerate(codes)])
    pkg.settings(**{"رمز_الدخول": "نعم"})
    return pkg.load()


def test_manual_codes_from_excel_cell_types(pkg):
    m = cell_codes(pkg, [123456, 654321.0, "012345", "  777777 ", "٣٣٣٣٣٣", "ab12cd", ""])
    got = [m.CODES[f"العاشر|أ|طالب {i}"] for i in range(7)]
    assert got[:6] == ["123456", "654321", "012345", "777777", "333333", "ab12cd"]
    assert len(got[6]) == 6 and got[6].isdigit()                       # الفاضي بيتولّد


def test_excel_dropped_leading_zero_matches_what_teacher_sees(pkg):
    """إكسل بيحوّل 012345 لرقم 12345 وبيعرضه 12345: الأستاذ بيعطي الطالب اللي بيشوفه"""
    m = cell_codes(pkg, [12345])
    assert m.check_code(f"{TITLE}|العاشر|أ|طالب 0", "12345") is None


def test_generated_codes_format_and_persistence_across_roster_changes(pkg):
    pkg.settings(**{"رمز_الدخول": "نعم"})
    c1 = dict(pkg.load().CODES)
    assert all(len(c) == 6 and c.isdigit() for c in c1.values()) and len(c1) == 5
    pkg.students(roster(a=4, b=1)); c2 = dict(pkg.load().CODES)           # أضفنا طالب وحذفنا طالب
    for k in set(c1) & set(c2): assert c1[k] == c2[k]                      # الباقين بيحتفظوا برموزهم
    assert "العاشر|أ|طالب أ4" in c2 and "العاشر|ب|طالب ب2" not in c2
    saved = json.loads(pkg.p("codes.json").read_text(encoding="utf-8"))
    assert set(saved) == set(c2)


def test_codes_json_holds_only_generated_codes(pkg):
    pkg.students([["العاشر", "أ", "يدوي", "111222"], ["العاشر", "أ", "مولّد", ""]]); pkg.settings(**{"رمز_الدخول": "نعم"})
    pkg.load()
    assert set(json.loads(pkg.p("codes.json").read_text(encoding="utf-8"))) == {"العاشر|أ|مولّد"}


def test_manual_code_overrides_previously_generated(pkg):
    pkg.settings(**{"رمز_الدخول": "نعم"}); old = pkg.load().CODES["العاشر|أ|طالب أ1"]
    rows = roster(); rows[0] = rows[0] + ["909090"]
    pkg.students(rows, head=["الصف", "الشعبة", "الاسم", "الرمز"])
    assert pkg.load().CODES["العاشر|أ|طالب أ1"] == "909090" != old


def test_no_code_column_or_disabled_means_no_codes(pkg):
    assert pkg.load().CODES == {} and not pkg.p("codes.json").exists()


def test_code_of_one_student_does_not_open_another(pkg, web_for=None):
    m = cell_codes(pkg, ["111111", "222222"])
    a, b = f"{TITLE}|العاشر|أ|طالب 0", f"{TITLE}|العاشر|أ|طالب 1"
    assert m.check_code(b, "111111") == "badcode" and m.check_code(b, "222222") is None and m.check_code(a, "111111") is None


@pytest.fixture
def coded(pkg):
    pkg.students([["العاشر", "أ", "طالب أ1", "111111"], ["العاشر", "أ", "طالب أ2", "222222"], ["العاشر", "أ", "طالب أ3", "333333"]])
    pkg.settings(**{"رمز_الدخول": "نعم"})
    s = Server(pkg).start()
    yield s
    s.stop()


def test_moved_student_needs_code_on_new_device(coded):
    w = coded
    k, st, p = w.start_student("devA", code="111111")
    assert p["status"] == "ok"
    w.teacher(move=k)
    assert w.start_student("devB")[2] == {"status": "badcode"}               # الجهاز الجديد بدون رمز: مرفوض
    assert w.start_student("devB", code="000000")[2] == {"status": "badcode"}
    again = w.start_student("devB", code="111111")[2]
    assert again["status"] == "ok" and again["ids"] == p["ids"]               # بالرمز بيكمل بنفس الورقة


def test_released_student_needs_code_again(coded):
    w = coded
    k, _, p = w.start_student("devA", code="111111")
    w.teacher(release=k)
    assert w.start_student("devA")[2] == {"status": "badcode"}
    assert w.start_student("devA", code="111111")[2]["status"] == "ok"


def test_code_not_needed_to_resume_on_same_device_but_needed_for_other(coded):
    w = coded
    k, _, p = w.start_student("devA", code="111111")
    assert w.start_student("devA")[2]["status"] == "ok"                      # نفس الجهاز: يكمل
    assert w.start_student("devB", code="111111")[2] == {"status": "taken"}   # جهاز ثاني حتى بالرمز الصحيح: الاسم محجوز لحد ما المعلم ينقله


def test_grief_lockout_is_per_name_only(coded):
    w = coded
    for _ in range(5): w.start_student("evil", n="طالب أ1", code="000000")
    assert w.start_student("devA", n="طالب أ1", code="111111")[2] == {"status": "locked"}     # معروف: زميل بيقدر يقفل اسم دقيقة
    assert w.start_student("devB", n="طالب أ2", code="222222")[2]["status"] == "ok"            # بس الباقي ما بتأثر


def test_codes_survive_new_exam(pkg):
    pkg.settings(**{"رمز_الدخول": "نعم"}); w = Server(pkg).start()
    try:
        before = json.loads(pkg.p("codes.json").read_text(encoding="utf-8"))
        k, _, p = w.start_student("d1", code=before["العاشر|أ|طالب أ1"]); assert p["status"] == "ok"
        w.teacher(newexam=True)
        assert json.loads(pkg.p("codes.json").read_text(encoding="utf-8")) == before
        assert w.start_student("d2", code=before["العاشر|أ|طالب أ1"])[2]["status"] == "ok"        # نفس الرمز بالامتحان الجديد
    finally:
        w.stop()


# =============================== صفحة /codes ===============================
def test_codes_page_lists_every_student_with_matching_code(coded):
    t = html_of(tget(coded, "/codes"))
    for n, c in (("طالب أ1", "111111"), ("طالب أ2", "222222"), ("طالب أ3", "333333")):
        assert re.search(rf"<div class=slip>{n}<span class=code>{c}</span></div>", t), n
    assert t.count("class=slip") == 3 and "شعبة أ" in t and "codes.json" in t


def test_codes_page_groups_by_section_and_page_break(pkg):
    pkg.students([["العاشر", "أ", "ا1", "111111"], ["العاشر", "ب", "ب1", "222222"], ["الحادي عشر", "أ", "ج1", "333333"]]); pkg.settings(**{"رمز_الدخول": "نعم"})
    w = Server(pkg).start()
    try:
        t = html_of(tget(w, "/codes"))
        assert t.count("<div class=sc>") == 3 and "page-break-after:always" in t and "page-break-inside:avoid" in t
        assert "@media print{.noprint{display:none}" in t
    finally:
        w.stop()


def test_codes_page_when_disabled_explains(pkg):
    w = Server(pkg).start()
    try:
        t = html_of(tget(w, "/codes"))
        assert "غير مفعّل" in t and "class=slip" not in t
    finally:
        w.stop()


def test_codes_page_escapes_names(pkg):
    evil = "<img src=x onerror=alert(1)>"
    pkg.students([["العاشر", "أ", evil, ""], ["<b>صف</b>", "<i>ش</i>", "عادي", ""]]); pkg.settings(**{"رمز_الدخول": "نعم"})
    w = Server(pkg).start()
    try:
        t = html_of(tget(w, "/codes"))
        assert evil not in t and "<b>صف</b>" not in t and "<i>ش</i>" not in t and "&lt;img" in t
    finally:
        w.stop()


def test_codes_page_matches_server_codes_for_many_students(pkg):
    pkg.students([["العاشر", ["أ", "ب", "ج"][i % 3], f"طالب {i}", ""] for i in range(90)]); pkg.settings(**{"رمز_الدخول": "نعم"})
    m = pkg.load(); w = Server(pkg).start()
    try:
        t = html_of(tget(w, "/codes"))
        slips = re.findall(r"<div class=slip>(.*?)<span class=code>(\d+)</span></div>", t)
        assert len(slips) == 90
        by_name = {n: c for (g, s, n), c in ((k.split("|"), v) for k, v in m.CODES.items())}
        assert all(by_name[n] == c for n, c in slips)
    finally:
        w.stop()


def test_names_with_pipe_cannot_start_known_limitation(pkg):
    """اسم فيه | بيكسر تحليل المفتاح (العنوان|الصف|الشعبة|الاسم): نتأكد على الأقل إن السيرفر ما بيقع وبيرد برسالة"""
    pkg.students(roster() + [["العاشر", "أ", "علي|محمد", ""]]); w = Server(pkg).start()
    try:
        st, j = w.start_student("d1", n="علي|محمد")[1:]
        assert st in (200, 400) and w.get("/")[0] == 200
    finally:
        w.stop()


# =============================== ورقات الطلاب /sheet ===============================
def test_sheet_for_student_marks_right_wrong_and_blank(web):
    k, ids, ans = do_exam(web, "طالب أ1", right=5, wrong=2, blank=1)
    t = html_of(tget(web, "/sheet?key=" + urllib.parse.quote(k)))
    assert t.count("class='q good'") == 5 and t.count("class='q bad'") == 3
    assert t.count("لم يجب") == 1 and t.count("✓ الصحيحة") == 8 and t.count("← إجابة الطالب") == 7
    assert "<span dir=ltr>5 / 8</span>" in t and "طالب أ1" in t and TITLE in t and t.count("علامة واحدة") == 8
    for i, n in enumerate(ids, 1): assert f"<b>{i}. (س{n} " in t                  # بنفس ترتيب ورقة الطالب
    assert t.count("class='o right given'") + t.count("class='o right given wrongc'") == 5


def test_sheet_shows_correct_option_text_for_each_question(web):
    k, ids, ans = do_exam(web, "طالب أ1", right=0, wrong=8)
    t = html_of(tget(web, "/sheet?key=" + urllib.parse.quote(k)))
    for n in ids:
        right_txt = f"خ{n - 1}-{LETTERS[(n - 1) % 4]}"
        assert re.search(rf"class='o right'>[^<]*<span dir=auto>[^<]*{re.escape(right_txt.split('-')[0])}", t) or right_txt.split("-")[1] in t


def test_sheet_wrong_only_filter(web):
    k, _, _ = do_exam(web, "طالب أ1", right=5, wrong=2, blank=1)
    t = html_of(tget(web, "/sheet?key=" + urllib.parse.quote(k) + "&wrong=1"))
    assert t.count("class='q bad'") == 3 and t.count("class='q good'") == 0 and "عرض كل الأسئلة" in t
    full = html_of(tget(web, "/sheet?key=" + urllib.parse.quote(k)))
    assert "عرض الخاطئة فقط" in full


def test_sheet_all_correct_wrong_only_is_empty_but_has_header(web):
    k, _, _ = do_exam(web, "طالب أ1")
    t = html_of(tget(web, "/sheet?key=" + urllib.parse.quote(k) + "&wrong=1"))
    assert "class='q bad'" not in t and "<span dir=ltr>8 / 8</span>" in t


def test_sheet_unknown_and_unsubmitted_student(web):
    k, _, _ = web.start_student("devX", n="طالب أ2")                          # بدأ ولم يسلّم
    assert "لا يوجد تسليم" in html_of(tget(web, "/sheet?key=" + urllib.parse.quote(k)))
    assert "لا يوجد تسليم" in html_of(tget(web, "/sheet?key=nope"))
    assert tget(web, "/sheet?key=")[0] == 200


def test_sheet_section_print_contains_only_submitted_of_that_section(web):
    do_exam(web, "طالب أ1", right=8); do_exam(web, "طالب أ2", right=4, wrong=4); do_exam(web, "طالب ب1", section="ب", right=2, wrong=6)
    web.start_student("devP", n="طالب أ3")                                    # ما سلّم
    t = html_of(tget(web, "/sheet?g=" + urllib.parse.quote("العاشر") + "&s=" + urllib.parse.quote("أ")))
    assert t.count("<div class=pg>") == 2 and "طالب أ1" in t and "طالب أ2" in t
    assert "طالب أ3" not in t and "طالب ب1" not in t and "طباعة الكل (2 ورقة)" in t
    t2 = html_of(tget(web, "/sheet?g=" + urllib.parse.quote("العاشر") + "&s=" + urllib.parse.quote("ب") + "&wrong=1"))
    assert t2.count("<div class=pg>") == 1 and t2.count("class='q bad'") == 6 and "class='q good'" not in t2
    assert "طباعة الكل (0 ورقة)" in html_of(tget(web, "/sheet?g=x&s=y"))


def test_sheet_index_lists_sections_and_links(web):
    do_exam(web, "طالب أ1"); do_exam(web, "طالب ب1", section="ب", right=3, wrong=5)
    t = html_of(tget(web, "/sheet"))
    assert "(1 سلّموا)" in t and t.count("طباعة ورقات الشعبة كلها") == 2 and "3 / 8" in t and "8 / 8" in t
    for href in re.findall(r"href='(/sheet\?[^']+)'", t):
        assert tget(web, href)[0] == 200, href


def test_sheet_links_roundtrip_for_names_with_special_characters(pkg):
    odd = ["علي #1 & 50%+ x", "O'Brien \"Q\"", "اسم؟ مع=علامات", "a b/c"]
    pkg.students([["العاشر", "أ", n, ""] for n in odd]); w = Server(pkg).start()
    try:
        for n in odd: do_exam(w, n)
        t = html_of(tget(w, "/sheet"))
        links = re.findall(r"<tr><td>(.*?)</td><td>8 / 8</td><td><a class=btn target=_blank href='(/sheet\?key=[^']+)'", t)
        assert len(links) == 4
        import html as H_
        for name, href in links:
            body = html_of(tget(w, href))
            assert H_.escape(H_.unescape(name)) in body and "<span dir=ltr>8 / 8</span>" in body, name
    finally:
        w.stop()


def test_monitor_open_sheet_link_encoding_matches_server(pkg):
    """رابط «فتح الورقة» بالمراقبة بيستعمل encodeURIComponent: لازم السيرفر يفكّه صح"""
    n = "علي #1 & 50%+ x"
    pkg.students([["العاشر", "أ", n, ""]]); w = Server(pkg).start()
    try:
        k, _, _ = do_exam(w, n)
        href = "/sheet?key=" + urllib.parse.quote(k, safe="-_.!~*'()")           # نفس ناتج encodeURIComponent
        import html as H_
        assert H_.escape(n) in html_of(tget(w, href))
    finally:
        w.stop()


def _evil_setup(pkg):
    evil = "<script>window.__x=1</script>"
    rows = bank(); rows[0][0] = "سؤال " + evil; rows[0][1] = "<b>خيار</b>"; rows[0][8] = "حل <u>مسطّر</u>"; rows[0][7] = "ص <i>5</i>"
    pkg.questions(rows); pkg.students([["<u>صف</u>", "<i>ش</i>", evil, ""]])
    pkg.settings(**{"عنوان_الامتحان": "عنوان " + evil, "عدد_الأسئلة_الصعبة": 3, "عدد_الأسئلة_المتوسطة": 4, "عدد_الأسئلة_السهلة": 4, "عدد_الأسئلة_الكلي": 11, "خلط_الأسئلة": "لا"})
    w = Server(pkg).start(); ck = cookie(w)
    k = f"عنوان {evil}|<u>صف</u>|<i>ش</i>|{evil}"
    p = w.post("/start", {"key": k, "dev": "d1"})[1]
    assert w.submit(k, "d1", p["ids"], [0] * len(p["ids"]))[0] == 200
    return w, ck, k


def test_print_pages_escape_names_title_questions_and_reference(pkg):
    w, ck, k = _evil_setup(pkg)
    try:
        q = urllib.parse.quote
        for path in ("/sheet", "/sheet?key=" + q(k), "/sheet?g=" + q("<u>صف</u>") + "&s=" + q("<i>ش</i>"), "/key", "/codes"):
            t = html_of(tget(w, path, ck))
            for bad in ("<script>window", "<b>خيار</b>", "<u>صف</u>", "<i>ش</i>", "<u>مسطّر</u>", "<i>5</i>"): assert bad not in t, (path, bad)
    finally:
        w.stop()


# كانت مشكلة (report_page بدون escape للصف/الشعبة/المرجع): أُصلحت بـ server.py
def test_report_page_escapes_grade_section_and_reference(pkg):
    w, ck, k = _evil_setup(pkg)
    try:
        t = html_of(tget(w, "/report", ck))
        for bad in ("<u>صف</u>", "<i>ش</i>", "<i>5</i>"): assert bad not in t, bad
    finally:
        w.stop()


def test_sheet_embeds_images_and_marks_with_final_score(pkg):
    rows = bank(); rows[0][0] = "شاهد [img:fig.png]"; pkg.questions(rows); pkg.image("fig.png")
    pkg.settings(**{"العلامة_النهائية": 30, "عدد_الأسئلة_الصعبة": 3, "عدد_الأسئلة_المتوسطة": 4, "عدد_الأسئلة_السهلة": 4, "عدد_الأسئلة_الكلي": 11, "خلط_الأسئلة": "لا"})
    w = Server(pkg).start()
    try:
        k, p = w.key(), w.start_student("d1")[2]
        w.submit(k, "d1", p["ids"], [w.correct_answers([n])[0] for n in p["ids"]])
        t = html_of(tget(w, "/sheet?key=" + urllib.parse.quote(k)))
        assert "<img class=\"qimg\" src=\"/img/fig.png\"" in t and "<span dir=ltr>30 / 30</span>" in t
        assert re.search(r"\(س1 — صعب — 2\.73 علامة\)", t)                            # 30 / 11 سؤال
    finally:
        w.stop()


def test_sheet_flags_teacher_submission_and_leaves(web):
    k, _, p = web.start_student("d1")
    web.post("/ping", {"key": k, "dev": "d1", "ans": {str(p["ids"][0]): 0}, "leaveN": 2, "leaveSec": 14}); import time; time.sleep(0.2)
    web.teacher(submitfor=k)
    t = html_of(tget(web, "/sheet?key=" + urllib.parse.quote(k)))
    assert "2 مرة (14 ث)" in t and "<span dir=ltr>" in t and t.count("لم يجب") >= 7


def test_sheet_for_student_submitted_by_browser_with_leave_text(web):
    k, p = web.key(), web.start_student("d1")[2]
    web.submit(k, "d1", p["ids"], web.correct_answers(p["ids"]), leave="3 مرة (40 ث)")
    assert "3 مرة (40 ث)" in html_of(tget(web, "/sheet?key=" + urllib.parse.quote(k)))


# =============================== حماية صفحات الطباعة ===============================
def test_login_redirect_preserves_sheet_query_exactly(web):
    k, _, _ = do_exam(web, "طالب أ1")
    path = "/sheet?key=" + urllib.parse.quote(k) + "&wrong=1"
    st, _, _, hdr = web.get(path)
    assert st == 302
    login = web.get(hdr["Location"])
    assert login[0] == 200
    nxt = json.loads(re.search(r"const NEXT=(\".*?\");", html_of(login)).group(1))
    assert nxt == path                                                              # بعد الدخول بيرجع لنفس الورقة
    ck = cookie(web)
    assert "طالب أ1" in html_of(web.get(nxt, {"Cookie": ck}))


@pytest.mark.parametrize("path", ["/sheet", "/sheet?key=x", "/sheet?g=a&s=b", "/codes", "/key"])
def test_print_pages_need_password(web, path):
    assert web.get(path)[0] == 302 and web.get(path, {"Cookie": "exam_t=bogus"})[0] == 302


def test_logout_link_present_only_with_password(pkg):
    w = Server(pkg).start()
    try:
        for path in ("/sheet", "/codes", "/key"): assert "/logout" in html_of(tget(w, path))
    finally:
        w.stop()
    pkg.settings(**{"كلمة_سر_المعلم": ""}); w2 = Server(pkg).start()
    try:
        for path in ("/sheet", "/codes", "/key"): assert "/logout" not in html_of(w2.get(path))
    finally:
        w2.stop()


def test_key_page_matches_bank_and_hides_nothing_from_teacher(web):
    t = html_of(tget(web, "/key"))
    assert "عدد الأسئلة بالبنك: 11" in t and "بالامتحان: 8" in t and t.count("class='q'") == 11
    assert t.count("✓") == 11 and "صعب (3)" in t and "وسط (4)" in t and "سهل (4)" in t
    for n in range(1, 12): assert f"<b>س{n}</b>" in t
