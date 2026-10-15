"""مخاطر خاصة بالآيفون (محرّك سفاري WebKit): التكبير التلقائي عند لمس خانة، تخزين محظور (تصفّح خاص/قيود)، شاشة آيفون SE الصغيرة،
إغلاق التاب وفتح الرابط من جديد (سفاري بيتجاهل تنبيه «متأكد بدك تطلع؟»)، وقفزة ساعة الجوال لما تنقفل الشاشة.
بتتخطّى لو WebKit مش مثبّت:  python -m playwright install webkit"""
import re

import pytest

pw = pytest.importorskip("playwright.sync_api")
from test_browser import clean, login, pick, show, solve, submit, url
from test_http import Server


@pytest.fixture(scope="module")
def wk():
    with pw.sync_playwright() as p:
        try:
            b = p.webkit.launch(headless=True)
        except Exception as e:                                           # noqa
            pytest.skip(f"WebKit غير مثبّت: {e}")
        b.pw_ = p
        yield b
        b.close()


@pytest.fixture
def iphone(wk):
    made = []
    def make(model="iPhone 13", init=None):
        d = {k: v for k, v in wk.pw_.devices[model].items() if k != "default_browser_type"}
        ctx = wk.new_context(**d, locale="ar-JO"); made.append(ctx)
        if init: ctx.add_init_script(init)
        page = ctx.new_page(); page.set_default_timeout(10000); page.js_errors = []
        page.on("pageerror", lambda e: page.js_errors.append(str(e))); page.on("dialog", lambda dl: dl.accept())
        return page
    yield make
    for c in made: c.close()


@pytest.fixture
def web(pkg):
    s = Server(pkg).start(); yield s; s.stop()


def submit_and_score(page):
    submit(page); page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
    return clean(page.inner_text("#score"))


def test_real_iphone_user_agent(iphone, web):
    page = iphone(); page.goto(url(web))
    ua = page.evaluate("navigator.userAgent"); assert "iPhone" in ua and "Safari" in ua and "AppleWebKit" in ua


def test_form_fields_do_not_trigger_ios_auto_zoom(pkg, iphone):
    """سفاري الآيفون بيكبّر الصفحة لما تلمس خانة خطّها أصغر من 16px، وبتضل مكبّرة (لازم الطالب يصغّرها بإصبعين)"""
    pkg.students([["العاشر", "أ", "طالب أ1", "111111"]]); pkg.settings(**{"رمز_الدخول": "نعم"}); w = Server(pkg).start()
    try:
        page = iphone(); page.goto(url(w))
        for sel in ("#g", "#sec", "#nm", "#code"):
            px = page.eval_on_selector(sel, "e=>parseFloat(getComputedStyle(e).fontSize)")
            assert px >= 16, f"{sel} خطّه {px}px"
    finally:
        w.stop()


def test_exam_works_when_browser_storage_is_blocked(iphone, web):
    """تخزين المتصفح محظور (قيود على الجهاز/وضع خاص قديم): الامتحان لازم يمشي عادي من أوله لآخره"""
    page = iphone(init="Object.defineProperty(window,'localStorage',{get(){throw new DOMException('blocked','SecurityError')}})")
    page.goto(url(web)); assert page.evaluate("()=>{try{localStorage;return false}catch(e){return true}}")       # فعلاً محظور
    login(page, web); solve(page)
    assert "8 / 8" in submit_and_score(page) and not page.js_errors, page.js_errors


def test_small_iphone_se_screen_has_no_sideways_scroll(iphone, web):
    page = iphone("iPhone SE")
    page.goto(url(web)); assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    login(page, web); assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert page.is_visible("[data-question-next]") and page.is_hidden("#submit") and page.is_visible("#clock") and not page.js_errors
    show(page, page.locator("#qs .card").count() - 1)                                              # زر التسليم بآخر سؤال
    assert page.is_visible("#submit") and page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_closing_the_tab_and_reopening_the_link_resumes(iphone, web):
    """سفاري الآيفون ما بيعرض «متأكد بدك تطلع؟»، فلو سكّر الطالب التاب بالغلط: يفتح الرابط من جديد ويكمل"""
    page = iphone(); login(page, web)
    for k in range(3): pick(page, k, 0)
    page.wait_for_timeout(6000)                                                                       # نبضة حفظ للسيرفر
    ctx = page.context; page.close()
    p2 = ctx.new_page(); p2.set_default_timeout(10000); p2.goto(url(web))
    p2.wait_for_selector("#s-exam:not(.hide)")
    assert p2.eval_on_selector_all("#qs input:checked", "e=>e.length") == 3
    solve(p2); submit(p2); p2.wait_for_function("document.getElementById('status').textContent.includes('✓')")
    assert "8 / 8" in clean(p2.inner_text("#score"))


def test_phone_clock_jump_is_corrected_by_the_server(iphone, web):
    """الجوال انقفلت شاشته وسفاري جمّد الصفحة، فساعة الصفحة بتقفز لقدّام: الوقت المعروض لازم يرجع لوقت السيرفر الصحيح، وما يسلّم لحاله غلط"""
    page = iphone(); page.clock.install(); login(page, web)
    def mins(): return int(re.search(r"(\d+):\d\d", clean(page.inner_text("#clock"))).group(1))
    assert mins() >= 29
    page.clock.fast_forward("10:00")                                                                 # الصفحة فكّرت إنه مرّ 10 دقائق
    page.wait_for_timeout(500); page.clock.run_for(6000)                                             # تشغيل مؤقتات النبض
    page.wait_for_function("parseInt(document.getElementById('clock').textContent.replace(/[^0-9:]/g,''))>=28", timeout=15000)
    assert mins() >= 28 and page.is_visible("#s-exam") and not page.js_errors


def test_exam_starts_at_the_top_on_iphone(iphone, web):
    """سفاري ما بيرجّع الصفحة لفوق لحاله: بدون scrollTo(0,0) الطالب بيبدأ والسؤال الأول مخفي فوق الشاشة"""
    page = iphone(); page.goto(url(web))
    page.select_option("#g", "العاشر"); page.select_option("#sec", "أ"); page.select_option("#nm", "طالب أ1")
    page.evaluate("scrollTo(0, document.body.scrollHeight)")
    page.click("#start"); page.wait_for_selector("#s-exam:not(.hide)"); page.wait_for_timeout(200)
    r = page.evaluate("""()=>{const q=document.querySelector('#qs .card:not(.question-hidden) .q').getBoundingClientRect();
        return {y:scrollY, top:q.top, bar:document.getElementById('bar').getBoundingClientRect().bottom, h:innerHeight}}""")
    assert r["y"] == 0 and r["bar"] <= r["top"] < r["h"], r
