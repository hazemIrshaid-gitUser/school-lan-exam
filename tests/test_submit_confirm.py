"""نافذة تأكيد التسليم: لما الطالب يضغط «تسليم الامتحان» بآخر سؤال بتطلع نافذة (دايماً، مش بس لو في أسئلة ناقصة):
«أنت بصدد تسليم إجاباتك... ما بتقدر تعيد الامتحان ولا تعدّل إجاباتك. متأكد؟». «نعم» = بيسلّم، «لا» = بيرجع لأسئلته وإجاباته وعدّاده.
النافذة من تصميم الصفحة (مش confirm) لأنه بعض متصفحات التطبيقات المدمجة ما بتعرض نوافذ المتصفح وبترجّع «لا» لحالها."""
import time

import pytest
from test_browser import ask_submit, browser, clean, login, phone, show, solve, submit, url, web  # noqa: F401  (fixtures)

DONE = "document.getElementById('status').textContent.includes('✓')"


def done_count(w): return w.get("/monitor.json")[1]["c"]["done"]
def sub_lines(w): return [l for l in w.pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if w.pkg.p("submissions.jsonl").exists() else []


def test_confirmation_always_appears_with_the_agreed_wording(phone, web):
    page = phone(); login(page, web); solve(page)                                                  # كل الأسئلة مجابة: لازم تطلع برضو
    ask_submit(page)
    t = clean(page.inner_text("#confirm-submit"))
    assert "أنت الآن بصدد تسليم إجاباتك للامتحان" in t and "لا يمكنك إعادة الامتحان مرة أخرى أو التعديل على إجاباتك" in t and "هل أنت متأكد من عملية التسليم؟" in t
    assert page.is_hidden("#cs-un") and page.is_visible("#cs-yes") and page.is_visible("#cs-no")
    assert page.is_visible("#s-exam") and page.is_hidden("#s-done") and done_count(web) == 0           # لسا ما تسلّم
    assert page.evaluate("document.activeElement.id") == "cs-no"                                    # التركيز على «لا»: Enter بالغلط ما يسلّم
    assert page.get_attribute("#confirm-submit", "role") == "dialog" and page.get_attribute("#confirm-submit", "aria-modal") == "true"
    assert not page.dialogs and not page.js_errors                                                  # بدون نوافذ المتصفح


def test_no_goes_back_to_the_exam_with_answers_and_time_intact(phone, web):
    page = phone(); login(page, web); solve(page); before = page.inner_text("#clock")
    ask_submit(page); page.click("#cs-no")
    assert page.is_hidden("#confirm-submit") and page.is_visible("#s-exam") and page.is_hidden("#s-done") and done_count(web) == 0
    assert page.eval_on_selector_all("#qs input:checked", "e=>e.length") == 8                      # إجاباته كلها محفوظة
    show(page, 0); assert page.eval_on_selector_all("#qs .card:not(.question-hidden)", "e=>e.length") == 1           # بيقدر يرجع يشوف الأسئلة
    time.sleep(1.2); assert page.inner_text("#clock") != before                                     # والعدّاد ماشي
    submit(page); page.wait_for_function(DONE)                                                      # ولسا بيقدر يسلّم بعدين
    assert done_count(web) == 1 and len(sub_lines(web)) == 1


def test_escape_and_backdrop_cancel(phone, web):
    page = phone(); login(page, web); solve(page)
    ask_submit(page); page.keyboard.press("Escape"); assert page.is_hidden("#confirm-submit") and done_count(web) == 0
    ask_submit(page); page.mouse.click(4, 4); assert page.is_hidden("#confirm-submit") and done_count(web) == 0        # الضغط برا البطاقة
    ask_submit(page); page.click(".modal-card h2"); assert page.is_visible("#confirm-submit")        # جوّا البطاقة ما بيسكّر
    ids = []
    for _ in range(4): page.keyboard.press("Tab"); ids.append(page.evaluate("document.activeElement.id"))
    assert ids == ["cs-no", "cs-yes", "cs-no", "cs-yes"]                                           # التنقل بـ Tab بيضل جوّا النافذة (ما بيطلع للصفحة ورا)
    page.keyboard.press("Escape")


def test_unanswered_count_is_shown_inside_the_same_window(phone, web):
    page = phone(); login(page, web); solve(page)
    for i in (2, 5, 7): page.query_selector_all("#qs .card")[i].evaluate("c=>c.querySelectorAll('input').forEach(i=>i.checked=false)")
    ask_submit(page)
    assert page.is_visible("#cs-un") and "باقي 3 سؤال بدون إجابة" in clean(page.inner_text("#cs-un"))
    assert "بصدد تسليم إجاباتك" in clean(page.inner_text("#confirm-submit"))                          # نافذة وحدة، مش اثنتين
    page.click("#cs-yes"); page.wait_for_function(DONE); assert done_count(web) == 1 and not page.dialogs


def test_double_click_on_yes_submits_once(phone, web):
    page = phone(); login(page, web); solve(page)
    ask_submit(page); page.dblclick("#cs-yes"); page.wait_for_function(DONE)
    time.sleep(0.5); assert done_count(web) == 1 and len(sub_lines(web)) == 1 and not page.js_errors


def test_time_up_while_the_window_is_open_submits_and_closes_it(phone, web):
    page = phone(); login(page, web); solve(page)
    ask_submit(page); page.evaluate("deadline=Date.now()-1")                                        # انتهى الوقت والنافذة مفتوحة
    page.wait_for_function(DONE, timeout=15000)
    assert page.is_hidden("#confirm-submit") and page.is_visible("#s-done") and len(sub_lines(web)) == 1
    assert "انتهى الوقت" in sub_lines(web)[0] and not page.js_errors


def test_time_up_without_the_window_never_shows_it(phone, web):
    page = phone(); login(page, web); solve(page)
    page.evaluate("deadline=Date.now()-1"); page.wait_for_function(DONE, timeout=15000)
    assert page.is_hidden("#confirm-submit") and len(sub_lines(web)) == 1                           # التسليم التلقائي بدون أي سؤال


def test_teacher_release_while_the_window_is_open_closes_it(phone, web):
    page = phone(); login(page, web); solve(page); ask_submit(page)
    title = web.get("/health.json")[1]["exam"]["title"]
    assert web.teacher(release=f"{title}|العاشر|أ|طالب أ1")[0] == 200
    page.wait_for_selector("#s-login:not(.hide)", timeout=20000)                                    # النبضة بترجّعه لشاشة الدخول
    assert page.is_hidden("#confirm-submit") and any("أعاد المعلم" in m for m in page.dialogs)


def test_window_fits_a_tiny_screen(browser, web):
    ctx = browser.new_context(viewport={"width": 320, "height": 480}, is_mobile=True, has_touch=True, locale="ar-JO")
    try:
        page = ctx.new_page(); page.set_default_timeout(8000); page.on("dialog", lambda d: d.accept()); errs = []; page.on("pageerror", lambda e: errs.append(str(e)))
        login(page, web); solve(page); ask_submit(page)
        r = page.evaluate("""()=>{const q=s=>document.querySelector(s).getBoundingClientRect();return {y:q('#cs-yes'),n:q('#cs-no'),c:q('.modal-card'),w:innerWidth,h:innerHeight,sx:document.documentElement.scrollWidth}}""")
        for b in (r["y"], r["n"]): assert 0 <= b["left"] and b["right"] <= r["w"] and 0 <= b["top"] and b["bottom"] <= r["h"], r        # الزرين ظاهرين كاملين
        assert r["c"]["left"] >= 0 and r["c"]["right"] <= r["w"] and r["sx"] <= r["w"] + 1 and not errs
        assert r["y"]["height"] >= 44 and r["n"]["height"] >= 44                                    # حجم مناسب للمس
    finally:
        ctx.close()


def test_double_tap_on_submit_cannot_confirm_or_dismiss_the_window(phone, web):
    """ضغطة مزدوجة على «تسليم الامتحان»: الضغطة الثانية بتنزل على النافذة (ممكن فوق «نعم»): لازم تتجاهلها النافذة بأول لحظات"""
    page = phone(); login(page, web); solve(page); show(page, page.locator("#qs .card").count() - 1)
    page.evaluate("()=>{document.getElementById('submit').click();document.getElementById('cs-yes').click();document.getElementById('cs-no').click();document.getElementById('confirm-submit').click()}")
    assert page.is_visible("#confirm-submit") and page.is_hidden("#s-done") and done_count(web) == 0        # ما سلّمت وما سكّرت
    time.sleep(0.6); page.click("#cs-yes"); page.wait_for_function(DONE); assert done_count(web) == 1       # وبعد لحظة «نعم» بتشتغل عادي
