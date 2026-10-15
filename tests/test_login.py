"""دخول المعلم بكلمة السر: تغيير كلمة السر بملف settings.txt بدون إعادة تشغيل، الأرقام العربية، ورسائل صفحة الدخول
(كلمة سر غلط، سيرفر واقف، متصفح مانع الكوكيز)، ورسالة صفحات المعلم لما تنفتح برابط الشبكة بدل localhost."""
import os, time

import pytest
from test_http import Server, TEACHER, lan_ip


@pytest.fixture
def web(pkg):
    pkg.settings(**{"كلمة_سر_المعلم": "1234"})
    s = Server(pkg).start(); yield s; s.stop()


def login(w, pw): return w.post("/login", {"password": pw}, TEACHER)


def cookie(w, pw):
    st, j, _, hdr = login(w, pw); assert j == {"ok": True}, (pw, j)
    return hdr["Set-Cookie"].split(";")[0]


def change_password(pkg, pw):
    old = os.path.getmtime(pkg.p("settings.txt"))
    pkg.settings(**{"كلمة_سر_المعلم": pw})
    os.utime(pkg.p("settings.txt"), (old + 2, old + 2))                                   # تأكيد إن وقت التعديل تغيّر (دقة الوقت بويندوز)


# ============================ تغيير كلمة السر والسيرفر شغّال ============================
def test_new_password_works_without_restart(pkg, web):
    assert login(web, "1234")[1] == {"ok": True}
    change_password(pkg, "NewPass9")
    assert login(web, "NewPass9")[1] == {"ok": True} and login(web, "1234")[1] == {"ok": False}
    ck = cookie(web, "NewPass9"); assert web.get("/key", {"Cookie": ck})[0] == 200
    assert "default" not in str(web.get("/health.json")[1]["warnings"]) and not any("1234" in w for w in web.get("/health.json")[1]["warnings"])


def test_old_sessions_stay_valid_after_password_change(pkg, web):
    ck = cookie(web, "1234"); change_password(pkg, "Other#77")
    assert web.get("/key", {"Cookie": ck})[0] == 200


def test_half_written_settings_file_keeps_the_current_password(pkg, web):
    s = pkg.p("settings.txt").read_text(encoding="utf-8") + "سطر_غلط = بدون معنى\n"
    old = os.path.getmtime(pkg.p("settings.txt")); pkg.p("settings.txt").write_text(s, encoding="utf-8"); os.utime(pkg.p("settings.txt"), (old + 2, old + 2))
    assert login(web, "1234")[1] == {"ok": True}


def test_removing_the_password_opens_the_pages_like_the_file_says(pkg, web):
    assert web.get("/key")[0] == 302
    change_password(pkg, "")
    assert web.get("/key")[0] == 200 and any("ما في كلمة سر" in w for w in web.get("/health.json")[1]["warnings"])


def test_monitor_page_still_works_after_password_change(pkg, web):
    change_password(pkg, "abc")
    assert web.get("/monitor")[0] == 200 and web.get("/login")[0] == 200


# ============================ أرقام عربية ومسافات ============================
@pytest.mark.parametrize("typed", ["1234", "١٢٣٤", "۱۲۳۴", " 1234 ", "1234\t"])
def test_arabic_digits_and_spaces_match(web, typed):
    assert login(web, typed)[1] == {"ok": True}


def test_arabic_digits_in_settings_file(pkg):
    pkg.settings(**{"كلمة_سر_المعلم": "٥٦٧٨"}); w = Server(pkg).start()
    try:
        assert login(w, "5678")[1] == {"ok": True} and login(w, "٥٦٧٨")[1] == {"ok": True} and login(w, "5679")[1] == {"ok": False}
    finally:
        w.stop()


def test_letters_still_case_sensitive(pkg):
    pkg.settings(**{"كلمة_سر_المعلم": "Teacher"}); w = Server(pkg).start()
    try:
        assert login(w, "teacher")[1] == {"ok": False} and login(w, "Teacher")[1] == {"ok": True}
    finally:
        w.stop()


# ============================ /authcheck و 403 ============================
def test_authcheck(web):
    assert web.get("/authcheck")[1] == {"authed": False}
    assert web.get("/authcheck", {"Cookie": cookie(web, "1234")})[1] == {"authed": True}
    ip = lan_ip()
    if ip: assert web.get("/authcheck", host=ip)[0] == 403


def test_teacher_page_on_network_address_explains_localhost(web):
    ip = lan_ip()
    if not ip: pytest.skip("ما في IP شبكة")
    for path in ("/monitor", "/key", "/health", "/login"):
        st, _, body, hdr = web.get(path, host=ip); t = body.decode("utf-8")
        assert st == 403 and "للمعلم فقط" in t and f"http://localhost:{web.port}{path}" in t and hdr["Content-Type"].startswith("text/html"), path


# ============================ صفحة الدخول بمتصفح حقيقي ============================
@pytest.fixture
def edge():
    pw = pytest.importorskip("playwright.sync_api")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True); yield b; b.close()


def open_key(b, w):
    pg = b.new_context().new_page(); pg.set_default_timeout(8000)
    pg.goto(f"http://localhost:{w.port}/monitor"); pg.click("text=مفتاح الإجابات"); pg.wait_for_selector("#p")
    return pg


def test_browser_login_after_changing_password_without_restart(pkg, web, edge):
    change_password(pkg, "صف10-ب")
    pg = open_key(edge, web); pg.fill("#p", "صف10-ب"); pg.keyboard.press("Enter")
    pg.wait_for_url(lambda u: "/login" not in u)                                                # («**/key» كان بيطابق رابط صفحة الدخول نفسها: /login?next=/key)
    assert pg.url.endswith("/key") and "مفتاح" in pg.inner_text("body")


def test_browser_wrong_password_mentions_keyboard_language(web, edge):
    pg = open_key(edge, web); pg.fill("#p", "ضصثق"); pg.click("#b")                              # 1234 مكتوبة والكيبورد عربي
    pg.wait_for_function("document.getElementById('m').textContent.length>0")
    assert "لغة الكيبورد" in pg.inner_text("#m") and "/login" in pg.url


def test_browser_blocking_cookies_gets_a_clear_message(web, edge):
    pg = open_key(edge, web)
    pg.route("**/login", lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok": true}'))   # الدخول نجح بس ما وصل كوكي (زي متصفح مانع الكوكيز)
    pg.fill("#p", "1234"); pg.click("#b")
    pg.wait_for_function("document.getElementById('m').textContent.length>0")
    assert "الكوكيز" in pg.inner_text("#m") and "/login" in pg.url


def test_browser_server_stopped_gets_a_clear_message(pkg, edge):
    pkg.settings(**{"كلمة_سر_المعلم": "1234"}); w = Server(pkg).start()
    pg = open_key(edge, w); w.stop(); time.sleep(0.5)
    pg.fill("#p", "1234"); pg.click("#b")
    pg.wait_for_function("document.getElementById('m').textContent.length>0", timeout=15000)
    assert "النافذة السوداء" in pg.inner_text("#m")
