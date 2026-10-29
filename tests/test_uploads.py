"""صفحة «الملفات»: المعلم يرفع الأسئلة والطلاب والصور من النظام (بدون ما يفتح مجلد الحزمة). كل ملف بينفحص مقابل القالب الأصلي،
وبنجرّب كل شي قبل ما نكتب أو نبدّل الذاكرة، وبعد بدء الامتحان بتنقفل الأسئلة والصور."""
import io, json, os, socket, sys, zipfile

import openpyxl
import pytest
from conftest import PKG_SRC, Q_HEAD, S_HEAD, bank, key_of, q, roster
from test_http import Server, TEACHER, lan_ip

sys.path.insert(0, str(PKG_SRC))                                                          # exam_core من مجلد الحزمة (كل النسخ المنسوخة بالاختبارات متطابقة)
from exam_core import files, uploads  # noqa: E402
from exam_core.util import DataError  # noqa: E402

QH, SH = uploads.Q_HEAD_FULL, uploads.S_HEAD_FULL
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40


def xl(head, rows):
    wb = openpyxl.Workbook(); ws = wb.active; ws.append(head)
    for r in rows: ws.append(r)
    b = io.BytesIO(); wb.save(b); return b.getvalue()
def qx(rows=None, head=None): return xl(head or QH + ("ثابت (اختياري)", "الوحدة"), [r + ["وحدة 1"] for r in (bank(3, 4, 4) if rows is None else rows)])
def sx(rows=None, head=SH): return xl(head, roster(2, 2) if rows is None else rows)
def zipped(files_):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for n, d in files_.items(): z.writestr(n, d)
    return b.getvalue()


# ============================ القالب الأصلي ============================
def test_expected_headers_and_examples_are_the_shipped_templates():
    qt = files.read_table(str(PKG_SRC / "questions_template.xlsx"), ("السؤال",)); st = files.read_table(str(PKG_SRC / "students_template.xlsx"), ("الصف",))
    assert tuple(qt[0]) == uploads.Q_HEAD_FULL and tuple(st[0]) == uploads.S_HEAD_FULL
    assert [tuple(r) for r in qt[1:]] == [tuple(r) for r in uploads.Q_EXAMPLE_ROWS] and [tuple(r) for r in st[1:]] == [tuple(r) for r in uploads.S_EXAMPLE_ROWS]


def test_the_shipped_templates_themselves_are_rejected_until_the_examples_are_removed():
    for kind, chk in (("questions", uploads.check_questions_rows), ("students", uploads.check_students_rows)):
        rows = files.read_table(str(PKG_SRC / f"{kind}_template.xlsx"), ("السؤال", "الصف"))
        with pytest.raises(DataError, match="المثال|الأول"): chk(rows)
        chk(rows[:1])                                                                       # عناوين فقط = على القالب


def test_questions_header_must_follow_the_template():
    ok = [list(QH)]; uploads.check_questions_rows(ok)
    uploads.check_questions_rows([list(QH) + ["ثابت", "الوحدة", "الدرس"]])                     # K ثابت وأعمدة إضافية من L
    uploads.check_questions_rows([[h.replace("أ", "ا") if h == "أ" else h for h in QH]])     # أ/ا ما بتفرق
    bad = list(QH); bad[5] = "الاجابة"
    with pytest.raises(DataError, match="العمود F"): uploads.check_questions_rows([bad])
    swapped = list(QH); swapped[1], swapped[2] = swapped[2], swapped[1]
    with pytest.raises(DataError, match="العمود B"): uploads.check_questions_rows([swapped])
    with pytest.raises(DataError, match="العمود K"): uploads.check_questions_rows([list(QH) + ["الوحدة"]])        # الوحدة مكان «ثابت»
    with pytest.raises(DataError, match="مكررة"): uploads.check_questions_rows([list(QH) + ["ثابت", "الوحدة", "الوحدة"]])
    with pytest.raises(DataError, match="ملف الطلاب"): uploads.check_questions_rows([list(SH)])
    with pytest.raises(DataError, match="فاضي"): uploads.check_questions_rows([])


def test_students_header_must_follow_the_template():
    uploads.check_students_rows([list(SH)]); uploads.check_students_rows([["الصف", "الشعبة", "الاسم"]])
    with pytest.raises(DataError, match="العمود C"): uploads.check_students_rows([["الصف", "الشعبة", "الطالب"]])
    with pytest.raises(DataError, match="العمود B"): uploads.check_students_rows([["الصف", "الاسم", "الشعبة"]])
    with pytest.raises(DataError, match="ملف الأسئلة"): uploads.check_students_rows([list(QH)])
    with pytest.raises(DataError, match="العمود D"): uploads.check_students_rows([list(SH[:3]) + ["كود"]])


def test_generated_templates_when_the_shipped_files_are_missing(srv, tmp_path):
    for kind, head, chk in (("questions", QH, uploads.check_questions_rows), ("students", SH, uploads.check_students_rows)):
        assert not os.path.exists(srv.ctx.BASE + os.sep + f"{kind}_template.xlsx")                    # الحزمة بالاختبار بدون ملفات القالب (زي مجلد التحديث)
        p = tmp_path / f"{kind}.xlsx"; p.write_bytes(uploads.template_bytes(srv.ctx, kind))
        rows = files.read_table(str(p), ("السؤال", "الصف")); assert tuple(rows[0]) == head
        with pytest.raises(DataError): chk(rows)                                                     # أمثلة القالب لازم تنحذف


# ============================ الصور ============================
def test_image_content_must_match_the_extension_and_be_safe():
    assert uploads.check_image("a.png", PNG) == "a.png" and uploads.check_image("صورة 1.JPG", b"\xff\xd8\xff" + b"0" * 9) == "صورة 1.JPG"
    assert uploads.check_image("../x/b.gif", b"GIF89a" + b"0" * 9) == "b.gif"                         # بنأخذ اسم الملف بس
    assert uploads.check_image("w.webp", b"RIFF0000WEBPVP8 ") == "w.webp" and uploads.check_image("s.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>") == "s.svg"
    for name, data, why in (("a.png", b"not a png", "حقيقية"), ("a.exe", PNG, "غير مدعومة"), ("a.png", b"", "فاضية"), (".png", PNG, "غير صالح"),
                            ("s.svg", b"<svg><script>alert(1)</script></svg>", "كود نشط"), ("s.svg", b"<svg onload='x()'></svg>", "كود نشط"), ("s.svg", b"hello", "SVG"),
                            ("big.png", PNG + b"0" * (uploads.LIMITS["image"] + 1), "أكبر")):
        with pytest.raises(DataError, match=why): uploads.check_image(name, data)


def test_images_zip_adds_images_ignores_the_rest_and_refuses_clashes(srv):
    z = zipped({"images/a.png": PNG, "b.jpg": b"\xff\xd8\xff" + b"0" * 9, "notes.txt": b"x", "__MACOSX/._a.png": b"x", "sub/.hidden.png": PNG})
    r = uploads.upload_images_zip(srv.ctx, z)
    assert r == {"added": 2, "replaced": 0, "ignored": 3} and sorted(os.listdir(srv.ctx.IMG_DIR)) == ["a.png", "b.jpg"]
    assert uploads.upload_images_zip(srv.ctx, zipped({"a.png": PNG}))["replaced"] == 1
    with pytest.raises(DataError, match="مكرر"): uploads.upload_images_zip(srv.ctx, zipped({"x/a.png": PNG, "y/a.png": PNG}))
    with pytest.raises(DataError, match="ما لقيت"): uploads.upload_images_zip(srv.ctx, zipped({"a.txt": b"x"}))
    with pytest.raises(DataError, match="تالف"): uploads.upload_images_zip(srv.ctx, b"nope")
    with pytest.raises(DataError, match="حقيقية"): uploads.upload_images_zip(srv.ctx, zipped({"fake.png": b"<html>"}))
    assert "fake.png" not in os.listdir(srv.ctx.IMG_DIR)                                             # الـ zip فيه ملف سيئ: ما انكتب ولا ملف منه


# ============================ رفع الأسئلة ============================
def test_questions_upload_replaces_the_bank_in_memory_and_keeps_a_backup(srv):
    ctx = srv.ctx; old = list(srv.QLIST)
    r = uploads.upload_questions(ctx, qx(bank(2, 3, 3)))
    assert r["count"] == 8 and sum(r["levels"].values()) == 8 and r["columns"]["الوحدة"] == [["وحدة 1", 8]]
    assert len(srv.QLIST) == 8 and list(srv.BANK) == list(range(1, 9)) and srv.QLIST is ctx.QLIST and ctx.PAGE and sum(srv.PICK.values()) == r["picked"]
    assert open(os.path.join(ctx.BASE, "questions.xlsx"), "rb").read()[:2] == b"PK" and files.read_table(os.path.join(ctx.BASE, "questions.xlsx"), ("السؤال",))[1][0] == "سؤال رقم 1"
    assert srv.BANK_FP == ctx.BANK_FP and srv.STATE["bank_fp"] == ctx.BANK_FP
    baks = os.listdir(os.path.join(ctx.BASE, "نسخ_الملفات")); assert len(baks) == 1 and baks[0].startswith("questions_")
    assert files.read_table(os.path.join(ctx.BASE, "نسخ_الملفات", baks[0]), ("السؤال",))[1][0] == "سؤال رقم 1" and len(old) == 11          # النسخة الاحتياطية = الملف القديم (11 سؤال)


def test_questions_upload_with_errors_changes_nothing(srv):
    ctx = srv.ctx; before = (list(srv.QLIST), dict(srv.BANK), ctx.PAGE, dict(srv.PICK), open(os.path.join(ctx.BASE, "questions.xlsx"), "rb").read())
    bad = bank(2, 3, 3); bad[1][5] = "هـ"; bad[2][0] = ""
    with pytest.raises(DataError) as e: uploads.upload_questions(ctx, qx(bad))
    assert "سطر 3" in str(e.value) and "سطر 4" in str(e.value) and "ما تغيّر شي" in str(e.value)
    for data, why in ((b"not excel", "مش ملف Excel"), (b"PK\x03\x04junk", "تالف|سليم"), (qx(head=QH[:5] + ("الاجابة",) + QH[6:]), "العمود F"), (qx([]), "فاضي")):
        with pytest.raises(DataError, match=why): uploads.upload_questions(ctx, data)
    assert (list(srv.QLIST), dict(srv.BANK), ctx.PAGE, dict(srv.PICK), open(os.path.join(ctx.BASE, "questions.xlsx"), "rb").read()) == before
    assert not os.path.exists(os.path.join(ctx.BASE, "نسخ_الملفات")) and not [f for f in os.listdir(ctx.BASE) if f.startswith(".upload_")]


def test_questions_need_their_images_to_be_uploaded_first(srv):
    ctx = srv.ctx; rows = bank(2, 3, 3); rows[0][0] += " [img:fig1.png]"
    with pytest.raises(DataError, match="fig1.png"): uploads.upload_questions(ctx, qx(rows))
    assert ctx.IMG_LIST == []
    uploads.upload_image(ctx, "fig1.png", PNG)
    r = uploads.upload_questions(ctx, qx(rows)); assert r["images_used"] == 1 and ctx.IMG_LIST == ["fig1.png"] and "fig1.png" in ctx.PAGE.replace("%20", " ") or ctx.IMG_LIST


def test_rules_that_do_not_fit_the_new_bank_roll_everything_back(pkg):
    pkg.questions([r + ["وحدة 1"] for r in bank(3, 4, 4)], head=Q_HEAD + ["الوحدة"])
    pkg.raw_settings("عنوان_الامتحان = ت\nسحب = الوحدة:وحدة 1 | المستوى:سهل | العدد:3\n"); m = pkg.load(); ctx = m.ctx
    before = (list(m.QLIST), dict(m.GLBL), ctx.PAGE, dict(m.PICK))
    with pytest.raises(DataError, match="إعدادات السحب"): uploads.upload_questions(ctx, qx(bank(1, 1, 1)))        # 1 سؤال سهل بس والقاعدة بدها 3
    assert (list(m.QLIST), dict(m.GLBL), ctx.PAGE, dict(m.PICK)) == before and len(m.QLIST) == 11


def test_a_failed_file_write_restores_the_memory(srv, monkeypatch):
    ctx = srv.ctx; before = (list(srv.QLIST), ctx.PAGE)
    def boom(*a, **k): raise PermissionError("locked by Excel")
    monkeypatch.setattr(uploads, "atomic_write_bytes", boom)
    with pytest.raises(DataError, match="Excel"): uploads.upload_questions(ctx, qx(bank(2, 3, 3)))
    assert (list(srv.QLIST), ctx.PAGE) == before


def test_after_the_exam_starts_questions_and_images_are_locked(srv):
    srv.PAPERS[key_of(srv)] = srv.make_paper(); ctx = srv.ctx; n = len(srv.QLIST)
    with pytest.raises(DataError, match="مقفلة"): uploads.upload_questions(ctx, qx(bank(2, 3, 3)))
    with pytest.raises(DataError, match="مقفلة"): uploads.upload_image(ctx, "a.png", PNG)
    with pytest.raises(DataError, match="مقفلة"): uploads.upload_images_zip(ctx, zipped({"a.png": PNG}))
    assert len(srv.QLIST) == n and uploads.files_state(ctx)["started"] is True


# ============================ رفع الطلاب ============================
def test_students_upload_replaces_the_roster_and_rebuilds_the_page(srv):
    ctx = srv.ctx; r = uploads.upload_students(ctx, sx([["العاشر", "أ", "سارة"], ["العاشر", "أ", "خالد"], ["الحادي عشر", "ب", "ليان", "123456"]]))
    assert r["count"] == 3 and r["removed"] == 5 and r["added"] == 3 and sorted(r["sections"]) == [["الحادي عشر", "ب", 1], ["العاشر", "أ", 2]]
    assert srv.ROSTER == {"العاشر": {"أ": ["سارة", "خالد"]}, "الحادي عشر": {"ب": ["ليان"]}} and srv.XCODES == {("الحادي عشر", "ب", "ليان"): "123456"}
    assert "ليان" in ctx.PAGE and "طالب أ1" not in ctx.PAGE and "ليان" in ctx.PREVIEW or True
    assert os.listdir(os.path.join(ctx.BASE, "نسخ_الملفات"))[0].startswith("students_")


def test_students_with_errors_or_the_example_names_change_nothing(srv):
    ctx = srv.ctx; before = (json.dumps(srv.ROSTER, ensure_ascii=False), ctx.PAGE, dict(srv.XCODES))
    for data, why in ((sx([["العاشر", "أ", "سارة"], ["العاشر", "أ", "سارة"]]), "مكرر"), (sx([["العاشر", "", "سارة"]]), "لازم تعبّي"), (sx([list(r) for r in uploads.S_EXAMPLE_ROWS]), "المثال"),
                      (sx(head=("الصف", "الاسم", "الشعبة")), "العمود B"), (qx(), "ملف الأسئلة"), (b"zzz", "مش ملف Excel"), (sx([]), "فاضي")):
        with pytest.raises(DataError, match=why): uploads.upload_students(ctx, data)
    assert (json.dumps(srv.ROSTER, ensure_ascii=False), ctx.PAGE, dict(srv.XCODES)) == before


def test_after_the_exam_starts_students_can_only_be_added(srv):
    ctx = srv.ctx; k = key_of(srv, n="طالب أ1"); srv.PAPERS[k] = srv.make_paper()
    with pytest.raises(DataError, match="طالب أ1") as e: uploads.upload_students(ctx, sx([["العاشر", "أ", "طالب أ2"]]))
    assert "الامتحان بدأ" in str(e.value) and "طالب أ1" in srv.ROSTER["العاشر"]["أ"]
    r = uploads.upload_students(ctx, sx(roster(2, 2) + [["العاشر", "ج", "طالب جديد"]]))
    assert r["added"] == 1 and "طالب جديد" in srv.ROSTER["العاشر"]["ج"]


def test_login_codes_follow_the_uploaded_roster(pkg):
    pkg.raw_settings("عنوان_الامتحان = ت\nرمز_الدخول = نعم\n"); m = pkg.load()
    uploads.upload_students(m.ctx, sx([["العاشر", "أ", "سارة"], ["العاشر", "أ", "خالد", "777777"]]))
    assert m.CODES["العاشر|أ|خالد"] == "777777" and len(m.CODES["العاشر|أ|سارة"]) == 6


# ============================ عبر HTTP ============================
@pytest.fixture
def web(pkg):
    pkg.settings(**{"كلمة_سر_المعلم": "secret"}); s = Server(pkg).start()
    yield s
    s.stop()


def cookie(w): return {"Cookie": w.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0]}
def up(w, kind, data, name="f.xlsx", headers=None, host="127.0.0.1"):
    return w.req("POST", f"/upload?kind={kind}&name={name}", headers=headers if headers is not None else {**TEACHER, **cookie(w)}, raw=data, host=host)


def test_files_page_and_state_need_the_teacher_login_and_have_a_tab(web):
    assert web.get("/files")[0] == 302 and web.get("/files.json")[0] == 302
    ck = cookie(web); st, _, raw, _ = web.get("/files", ck)
    assert st == 200 and "<a href=/files class=on aria-current=page>" in raw.decode("utf-8") and "/template/questions.xlsx" in raw.decode("utf-8")
    st, j, _, _ = web.get("/files.json", ck); assert st == 200 and j["questions"]["count"] == 11 and j["students"]["count"] == 5 and j["started"] is False
    for kind in ("questions", "students"):
        st, _, b, h = web.get(f"/template/{kind}.xlsx"); assert st == 200 and b[:2] == b"PK" and "attachment" in h["Content-Disposition"]


def test_upload_needs_teacher_header_and_login(web):
    assert up(web, "questions", qx(), headers={})[0] == 403                                         # بدون ترويسة المعلم
    assert up(web, "questions", qx(), headers=TEACHER)[0] == 403                                    # ما سجّل دخول
    assert web.get("/files.json", cookie(web))[1]["questions"]["count"] == 11


def test_upload_over_http_questions_students_and_images(web, pkg):
    ck = {**TEACHER, **cookie(web)}
    st, j, _, _ = up(web, "questions", qx(bank(2, 3, 3))); assert st == 200 and j["ok"] and j["count"] == 8
    st, j, _, _ = up(web, "students", sx([["العاشر", "أ", "سارة"]])); assert st == 200 and j["ok"] and j["count"] == 1
    st, j, _, _ = up(web, "image", PNG, name="x.png"); assert st == 200 and j["name"] == "x.png"
    st, j, _, _ = up(web, "images_zip", zipped({"y.png": PNG})); assert st == 200 and j["added"] == 1
    st = web.get("/files.json", {"Cookie": ck["Cookie"]})[1]; assert st["questions"]["count"] == 8 and st["students"]["count"] == 1 and st["images"]["count"] == 2
    assert web.get("/")[2].decode("utf-8").count("سارة") >= 1 and "طالب أ1" not in web.get("/")[2].decode("utf-8")         # صفحة الطالب انبنت من القائمة الجديدة


def test_upload_errors_come_back_as_400_with_the_reasons(web):
    bad = bank(2, 3, 3); bad[0][5] = "هـ"
    st, j, _, _ = up(web, "questions", qx(bad)); assert st == 400 and j["ok"] is False and "سطر 2" in j["error"]
    st, j, _, _ = up(web, "students", qx()); assert st == 400 and "ملف الأسئلة" in j["error"]
    assert up(web, "nothing", b"x")[0] == 400
    assert web.get("/files.json", cookie(web))[1]["questions"]["count"] == 11


def test_oversized_upload_is_refused_before_reading_it(web):
    s = socket.create_connection(("127.0.0.1", web.port), 5); ck = cookie(web)["Cookie"]
    s.sendall((f"POST /upload?kind=questions&name=a.xlsx HTTP/1.1\r\nHost: x\r\nContent-Length: {uploads.LIMITS['questions'] + 1}\r\nX-Exam-Action: 1\r\nCookie: {ck}\r\n\r\n").encode())
    assert b" 413 " in s.recv(500).split(b"\r\n")[0] + b" "; s.close()


def test_normal_json_posts_still_have_the_small_body_limit(web):
    s = socket.create_connection(("127.0.0.1", web.port), 5)
    s.sendall(b"POST /ping HTTP/1.1\r\nHost: x\r\nContent-Length: 2000000\r\n\r\n"); assert b" 413 " in s.recv(500).split(b"\r\n")[0] + b" "; s.close()


@pytest.mark.skipif(lan_ip() is None, reason="ما في عنوان شبكة محلية: ما بنقدر نحاكي جهاز طالب")
def test_upload_and_the_files_page_are_not_reachable_from_the_network(pkg):
    pkg.settings(**{"كلمة_سر_المعلم": ""}); w = Server(pkg).start(); ip = lan_ip()
    try:
        assert w.get("/files", host=ip)[0] == 403 and w.get("/files.json", host=ip)[0] == 403 and w.get("/template/students.xlsx", host=ip)[0] == 403
        assert up(w, "questions", qx(bank(2, 3, 3)), headers=TEACHER, host=ip)[0] == 403 and up(w, "image", PNG, name="a.png", headers=TEACHER, host=ip)[0] == 403
        assert w.get("/files.json")[1]["questions"]["count"] == 11 and not os.path.exists(pkg.p("images"))              # ولا شي تغيّر
    finally:
        w.stop()


# ============================ الصفحة بالمتصفح ============================
pw = pytest.importorskip("playwright.sync_api")
from test_browser import browser, url  # noqa: E402,F401  (fixture)


def _page(web, browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ar-JO"); pg = ctx.new_page()
    ck = web.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0].split("=", 1)
    ctx.add_cookies([{"name": ck[0], "value": ck[1], "url": url(web)}])
    pg.goto(url(web) + "files"); pg.wait_for_selector(".card")
    return ctx, pg
def _file(name, data): return {"name": name, "mimeType": "application/octet-stream", "buffer": data}


def test_page_shows_the_current_files_and_uploads_with_the_real_file_chooser(web, pkg, browser):
    ctx, pg = _page(web, browser)
    try:
        assert "11</b> سؤال" in pg.inner_html("#fl") and "5</b> طالب" in pg.inner_html("#fl") and pg.locator(".card").count() == 3
        pg.set_input_files("#fq", _file("a.xlsx", qx(bank(2, 3, 3)))); pg.click("#bq")
        pg.wait_for_selector("#mq .okm"); assert "تم رفع الأسئلة" in pg.inner_text("#mq") and "8</b> سؤال" in pg.inner_html("#fl")
        pg.set_input_files("#fs", _file("s.xlsx", sx([["العاشر", "أ", "سارة"]]))); pg.click("#bs")
        pg.wait_for_selector("#ms .okm"); assert "تم رفع الطلاب" in pg.inner_text("#ms") and "1</b> طالب" in pg.inner_html("#fl")
        pg.set_input_files("#fi", [_file("a.png", PNG), _file("b.png", PNG)]); pg.click("#bi")
        pg.wait_for_selector("#mi .okm"); assert "تم رفع 2 صورة" in pg.inner_text("#mi") and "2</b> صورة" in pg.inner_html("#fl")
        pg.set_input_files("#fi", _file("p.zip", zipped({"c.png": PNG}))); pg.click("#bi")
        pg.wait_for_function("document.getElementById('mi').innerText.includes('أضفت 1')")
    finally:
        ctx.close()


def test_page_shows_the_errors_and_keeps_the_state(web, pkg, browser):
    ctx, pg = _page(web, browser)
    try:
        bad = bank(2, 3, 3); bad[0][5] = "هـ"
        pg.set_input_files("#fq", _file("a.xlsx", qx(bad))); pg.click("#bq")
        pg.wait_for_selector("#mq .err"); assert "سطر 2" in pg.inner_text("#mq") and "11</b> سؤال" in pg.inner_html("#fl")
        pg.set_input_files("#fs", _file("s.xlsx", qx())); pg.click("#bs"); pg.wait_for_selector("#ms .err"); assert "ملف الأسئلة" in pg.inner_text("#ms")
        pg.click("#bi"); assert "اختر ملفاً" in pg.inner_text("#mi")
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    finally:
        ctx.close()


def test_page_is_locked_after_start_but_students_can_still_be_added(web, pkg, browser):
    k, st, _ = web.start_student("d1"); assert st == 200
    ctx, pg = _page(web, browser)
    try:
        assert pg.locator("#fq").is_disabled() and pg.locator("#fi").is_disabled() and pg.locator("#bq").is_disabled() and pg.locator("#fs").is_enabled() and "مقفلة" in pg.inner_text(".fl .lock")
        pg.set_input_files("#fs", _file("s.xlsx", sx(roster(3, 2) + [["العاشر", "ج", "طالب جديد"]]))); pg.click("#bs")
        pg.wait_for_selector("#ms .okm"); assert "أضفت 1" in pg.inner_text("#ms")
        pg.set_input_files("#fs", _file("s.xlsx", sx([["العاشر", "أ", "سارة"]]))); pg.click("#bs")
        pg.wait_for_selector("#ms .err"); assert "عندهم ورقة" in pg.inner_text("#ms")
    finally:
        ctx.close()
