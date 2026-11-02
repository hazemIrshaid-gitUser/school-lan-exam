"""إرسال نسخة مضغوطة من النتائج على الإيميل لما المعلم يضغط «بداية امتحان جديد» (exam_core/mailer.py).
المنطق بنختبره داخل العملية مع smtplib مزيّف (ما بنبعت إيميل حقيقي)؛ صفحة الإعدادات وزر التجربة بنختبرهم عبر HTTP (فشل الاتصال حقيقي)."""
import io, os, time, zipfile
import smtplib
from test_browser import browser  # noqa: F401  (fixture)

import pytest
from conftest import DEFAULT_SETTINGS
from test_http import Server, TEACHER
from test_logic import _fill_submissions
from test_settings_page import Api, cookie, text

MAIL = {"بريد_المرسل": "me@gmail.com", "بريد_المستلم": "teacher@example.com", "كلمة_مرور_البريد": "abcd efgh ijkl mnop"}


class FakeSMTP:
    """يحل مكان smtplib.SMTP_SSL / SMTP: بيسجّل كل شي بدل الاتصال"""
    sent, calls, fail = [], [], None

    def __init__(self, host, port, timeout=None, context=None):
        FakeSMTP.calls.append(("connect", host, port, type(self).__name__))

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self, context=None): FakeSMTP.calls.append(("starttls",))

    def login(self, user, pw):
        FakeSMTP.calls.append(("login", user, pw))
        if FakeSMTP.fail: raise FakeSMTP.fail

    def send_message(self, msg): FakeSMTP.sent.append(msg)


class FakeSSL(FakeSMTP): pass


@pytest.fixture
def fake(monkeypatch):
    FakeSMTP.sent, FakeSMTP.calls, FakeSMTP.fail = [], [], None
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSSL)
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def wait_mail(srv, secs=10):
    end = time.time() + secs
    while time.time() < end and srv.ctx.MAIL["state"] in ("", "sending"): time.sleep(0.05)
    return srv.ctx.MAIL["state"]


def zip_of(msg):
    att = next(p for p in msg.iter_attachments())
    return att.get_filename(), zipfile.ZipFile(io.BytesIO(att.get_payload(decode=True)))


# ---------------- الإرسال بعد الأرشفة ----------------
def test_archive_sends_a_zip_of_the_results_when_configured(pkg, fake):
    pkg.settings(**MAIL); srv = pkg.load(); _fill_submissions(srv, 2)
    d = srv.archive_all()
    assert wait_mail(srv) == "ok", srv.ctx.MAIL
    assert fake.calls[0][:3] == ("connect", "smtp.gmail.com", 465) and ("login", "me@gmail.com", MAIL["كلمة_مرور_البريد"]) in fake.calls
    (msg,) = fake.sent
    assert msg["To"] == "teacher@example.com" and msg["From"] == "me@gmail.com" and "اختبار الوحدة" in msg["Subject"]
    name, z = zip_of(msg)
    assert name.startswith("exam_results_") and name.endswith(".zip")
    names = set(z.namelist())
    assert {"results.csv", "submissions.jsonl"} <= names and not any(n.startswith("images") for n in names)
    assert not any(n.endswith(".zip") for n in names)                              # الزيب ما ضم نفسه
    assert os.path.isdir(d) and "teacher@example.com" in srv.ctx.MAIL["text"]


def test_nothing_is_sent_without_settings_or_without_an_exam(pkg, fake):
    srv = pkg.load(); _fill_submissions(srv, 2); srv.archive_all()                  # الإعدادات فاضية
    assert fake.calls == [] and srv.ctx.MAIL["state"] == ""
    pkg.settings(**MAIL); srv2 = pkg.load(); srv2.archive_all()                     # معبّاة بس ما حدا امتحن
    assert fake.calls == [] and srv2.ctx.MAIL["state"] == ""
    pkg.settings(**{"بريد_المرسل": "me@gmail.com", "بريد_المستلم": "t@example.com"}); srv3 = pkg.load(); _fill_submissions(srv3, 1); srv3.archive_all()      # بدون كلمة مرور
    assert fake.calls == []


def test_a_failed_send_never_breaks_the_archive_and_says_why(pkg, fake):
    pkg.settings(**MAIL); srv = pkg.load(); _fill_submissions(srv, 2)
    fake.fail = smtplib.SMTPAuthenticationError(535, b"bad")
    d = srv.archive_all()
    assert wait_mail(srv) == "fail" and "كلمة مرور تطبيق" in srv.ctx.MAIL["text"]
    assert os.path.isfile(os.path.join(d, "submissions.jsonl")) and not srv.SUBS and not fake.sent
    fake.fail = ConnectionRefusedError("no net"); _fill_submissions(srv, 1)
    srv.archive_all(); assert wait_mail(srv) == "fail" and "الإنترنت" in srv.ctx.MAIL["text"]


def test_port_587_uses_starttls_and_custom_host(pkg, fake):
    pkg.settings(**MAIL, **{"خادم_البريد": "smtp.office365.com:587"}); srv = pkg.load(); _fill_submissions(srv, 1)
    srv.archive_all(); assert wait_mail(srv) == "ok"
    assert fake.calls[0][:3] == ("connect", "smtp.office365.com", 587) and ("starttls",) in fake.calls


def test_oversize_results_fall_back_to_the_small_set_or_skip(pkg, fake, monkeypatch):
    pkg.settings(**MAIL); srv = pkg.load(); _fill_submissions(srv, 2)
    monkeypatch.setattr(srv.core_mailer, "MAX_BYTES", 1500)                         # الأرشيف الكامل أكبر، الصغير (csv+jsonl+xlsx) بيدخل أو لا
    srv.archive_all(); st = wait_mail(srv)
    if st == "ok":
        _, z = zip_of(fake.sent[-1]); assert set(z.namelist()) <= {"results.csv", "submissions.jsonl", "نتائج/report.xlsx"}
    monkeypatch.setattr(srv.core_mailer, "MAX_BYTES", 10); _fill_submissions(srv, 1)
    srv.archive_all(); end = time.time() + 5
    while time.time() < end and srv.ctx.MAIL["state"] == "sending": time.sleep(0.05)
    assert srv.ctx.MAIL["state"] == "fail" and "20 ميجا" in srv.ctx.MAIL["text"]


def test_several_recipients_are_accepted(pkg, fake):
    pkg.settings(**{**MAIL, "بريد_المستلم": "a@x.com, b@y.org"}); srv = pkg.load(); _fill_submissions(srv, 1)
    srv.archive_all(); assert wait_mail(srv) == "ok" and fake.sent[0]["To"] == "a@x.com, b@y.org"


# ---------------- التحقق من الإعدادات ----------------
@pytest.mark.parametrize("k,v", [("بريد_المرسل", "not-an-email"), ("بريد_المستلم", "a@x.com b"), ("خادم_البريد", "smtp gmail com")])
def test_bad_values_are_rejected(pkg, k, v):
    pkg.settings(**{**MAIL, k: v}); pkg.expect_error(k)


# ---------------- صفحة الإعدادات (HTTP) ----------------
@pytest.fixture
def web(pkg):
    pkg.settings(**MAIL, **{"خادم_البريد": "127.0.0.1:9"}); s = Server(pkg).start()   # منفذ 9 مسكّر: الاتصال بيفشل فعلاً
    yield s
    s.stop()


def test_password_is_masked_in_the_state_and_survives_a_save(web):
    api = Api(web); f = api.field("كلمة_مرور_البريد")
    assert f["kind"] == "secret" and f["value"] not in ("", MAIL["كلمة_مرور_البريد"]) and MAIL["كلمة_مرور_البريد"] not in web.get("/settings.json", api.ck)[1].__str__()
    st, j = api.save({"كلمة_مرور_البريد": f["value"], "بريد_المستلم": "new@example.com"})              # القناع المرجّع = ما تغيّرت
    assert st == 200 and j["ok"], j
    t = text(web.pkg); assert MAIL["كلمة_مرور_البريد"] in t and "new@example.com" in t
    st, j = api.save({"كلمة_مرور_البريد": "other pass"}); assert st == 200 and "other pass" in text(web.pkg)
    st, j = api.save({"كلمة_مرور_البريد": ""}); assert st == 200 and api.field("كلمة_مرور_البريد")["value"] == ""
    assert api.state()["mail"]["on"] is False


def test_mail_fields_are_free_after_the_exam_started(web):
    web.start_student("d1")
    api = Api(web); assert all(api.field(k)["free"] for k in ("بريد_المرسل", "بريد_المستلم", "كلمة_مرور_البريد", "خادم_البريد"))
    st, j = api.save({"بريد_المستلم": "later@example.com"}); assert st == 200 and j["ok"], j


def test_reset_keeps_the_mail_settings(web):
    api = Api(web); st, j = api.save(reset=True)
    assert st == 200 and MAIL["كلمة_مرور_البريد"] in text(web.pkg) and "teacher@example.com" in text(web.pkg)


def test_test_button_reports_a_connection_failure_and_needs_the_teacher(web):
    api = Api(web)
    st, j, _, _ = web.post("/settings", {"mailtest": 1}, {**TEACHER, **api.ck})
    assert st == 200 and j["ok"] is False and "الإنترنت" in j["text"]
    assert web.post("/settings", {"mailtest": 1}, TEACHER)[0] == 403                                  # بدون تسجيل دخول


def test_test_button_without_settings(pkg):
    pkg.settings(); w = Server(pkg).start()
    try:
        api = Api(w); st, j, _, _ = w.post("/settings", {"mailtest": 1}, {**TEACHER, **api.ck})
        assert st == 200 and j["ok"] is False and "عبّي" in j["text"]
    finally:
        w.stop()


def test_the_problem_report_hides_the_mail_password():
    import importlib.util
    from conftest import PKG_SRC
    spec = importlib.util.spec_from_file_location("rp_mail", PKG_SRC / "report_problem.py")
    rp = importlib.util.module_from_spec(spec); spec.loader.exec_module(rp)
    out = rp.masked_settings("\n".join(["كلمة_مرور_البريد = abcd efgh", "كلمة_سر_المعلم = zzz", "بريد_المستلم = t@x.com"]))
    assert "abcd" not in out and "zzz" not in out and "***" in out and "t@x.com" in out


# ---------------- الواجهة بالمتصفح ----------------
def test_settings_page_shows_the_mail_card_and_the_test_button(web, browser):
    from test_browser import url
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ar-JO"); pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    try:
        ck = web.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0].split("=", 1)
        ctx.add_cookies([{"name": ck[0], "value": ck[1], "url": url(web)}])
        pg.goto(url(web) + "settings"); pg.wait_for_selector("#mailtest")
        assert "إرسال النتائج على الإيميل" in pg.inner_text("body")
        assert pg.get_attribute('[data-fk="كلمة_مرور_البريد"]', "type") == "password"
        assert MAIL["كلمة_مرور_البريد"] not in pg.content() and pg.input_value('[data-fk="بريد_المستلم"]') == "teacher@example.com"
        pg.fill('[data-fk="بريد_المستلم"]', "changed@example.com"); pg.click("#mailtest")
        assert "احفظ الإعدادات أولاً" in pg.inner_text("#mailst")                              # الحقول ما انحفظت: ما بنجرّب بقيم قديمة
        pg.fill('[data-fk="بريد_المستلم"]', "teacher@example.com"); pg.click("#mailtest")
        pg.wait_for_function("document.getElementById('mailst').textContent.includes('الإنترنت')", timeout=20000)    # الخادم 127.0.0.1:9 مسكّر
        assert not errs, errs
    finally:
        ctx.close()
