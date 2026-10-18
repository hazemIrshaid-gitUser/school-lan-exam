"""زر «طالب جديد» بشاشة التسليم: بدل ما المشرف يعمل refresh بإيده بين طالب وطالب على نفس الجهاز، بيضغط الزر وبترجع شاشة الدخول جاهزة.
الزر بيظهر بعد ما تنحفظ النتيجة بس (تسليم ما انحفظ ما بيضيع)، وبمعاينة المعلم كمان. بيشتغل على Edge وWebKit."""
import pytest
from test_http import Server, TEACHER
from test_browser import browser, phone, login, submit, solve, no_hscroll, url  # noqa: F401  (fixtures + helpers)

NEW = "#new-student"


@pytest.fixture
def web(pkg):
    s = Server(pkg).start()
    yield s
    s.stop()


def finish_one(page, w, name="طالب أ1"):
    login(page, w, name=name); solve(page); submit(page)
    page.wait_for_selector("#s-done:not(.hide)")


def test_button_returns_to_login_ready_for_the_next_student(phone, web):
    page = phone(); finish_one(page, web)
    page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
    assert page.locator(NEW).is_visible() and "طالب جديد" in page.inner_text(NEW)
    page.click(NEW)
    page.wait_for_selector("#s-login:not(.hide)")
    assert page.locator("#s-done").is_hidden() and page.locator("#s-exam").is_hidden()
    page.select_option("#g", "العاشر"); page.select_option("#sec", "أ")
    page.wait_for_function("document.querySelectorAll('#nm option').length > 1")                    # القائمة بتتعبّى بعد طلب «المحجوزة» من السيرفر
    names = page.eval_on_selector_all("#nm option", "o=>o.map(x=>x.textContent)")
    assert "طالب أ1" in names and "طالب أ2" in names                                               # نفس الجهاز: اسم اللي سلّم بيضل بالقائمة
    page.select_option("#nm", "طالب أ1")
    assert page.locator("#blocked").is_visible() and page.locator("#start").is_disabled()          # بس لو اختاره بيطلع «سلّم من هذا الجهاز» وما بيبدأ
    page.select_option("#nm", "طالب أ2"); page.click("#start"); page.wait_for_selector("#s-exam:not(.hide)")
    assert page.inner_text("#who") == "طالب أ2" and page.locator(NEW).is_hidden()                  # بدأ الطالب التالي، والزر ما ظهر بالامتحان
    assert not page.js_errors


def test_button_waits_until_the_result_is_saved(phone, web):
    """لو تعذّر حفظ التسليم ما بنخلّي أحد يغادر الشاشة (الإجابات لسا محفوظة بالجهاز للمحاولة من جديد)"""
    page = phone()
    login(page, web); solve(page)
    page.route("**/submit", lambda r: r.abort())
    submit(page); page.wait_for_selector("#s-done:not(.hide)")
    assert page.locator(NEW).count() == 1 and not page.locator(NEW).is_visible()                    # لسا بيحاول
    page.wait_for_function("document.getElementById('status').textContent.includes('تعذّر')", timeout=15000)
    assert not page.locator(NEW).is_visible()                                                       # وبعد الفشل كمان مخفي


def test_button_fits_a_phone_screen(phone, web):
    page = phone(); finish_one(page, web)
    page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
    box = page.locator(NEW).bounding_box(); card = page.locator("#s-done").bounding_box(); vw = page.evaluate("window.innerWidth")
    assert box["x"] >= 0 and box["x"] + box["width"] <= vw + 1 and box["height"] >= 40 and no_hscroll(page)
    assert box["x"] - card["x"] >= 8 and (card["x"] + card["width"]) - (box["x"] + box["width"]) >= 8      # الزر داخل البطاقة بهوامش مش لاصق بحافتها


def test_teacher_preview_has_the_button_and_restarts_the_preview(web, browser):
    ck = web.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0]
    name, val = ck.split("=", 1)
    ctx = browser.new_context(viewport={"width": 1100, "height": 800}, locale="ar-JO")
    ctx.add_cookies([{"name": name, "value": val, "url": url(web)}])
    page = ctx.new_page(); page.set_default_timeout(10000)
    try:
        page.goto(url(web) + "teacher"); page.wait_for_selector("#s-exam:not(.hide)")
        submit(page); page.wait_for_selector("#s-done:not(.hide)")
        page.wait_for_selector(NEW + ":not(.hide)")
        page.click(NEW)
        page.wait_for_selector("#s-exam:not(.hide)")                                                # معاينة جديدة من الأول
        assert page.locator("#s-done").is_hidden()
    finally:
        ctx.close()
