"""صفحة الطالب بتصميم «سؤال بكل صفحة» مع خريطة الأسئلة: التنقل، الخريطة، زر التسليم بآخر سؤال بس، بداية الامتحان من أول الصفحة،
والاستئناف عند نفس السؤال بعد إعادة التحميل."""
import time

import pytest
from test_browser import browser, phone, login, pick, show, solve, submit, url, web  # noqa: F401  (fixtures)

pytestmark = pytest.mark.filterwarnings("ignore")


def state(page):
    return page.evaluate("""()=>({visible:[...document.querySelectorAll('#qs .card')].map((c,i)=>c.classList.contains('question-hidden')?null:i).filter(x=>x!==null),
      counter:document.querySelector('.current-question-count').textContent, pager:document.querySelector('.question-pager-count').textContent,
      prev:document.querySelector('[data-question-prev]').disabled, next:document.querySelector('[data-question-next]').disabled,
      submit:getComputedStyle(document.getElementById('submit')).display!=='none', hint:getComputedStyle(document.querySelector('.submit-hint')).display!=='none',
      items:document.querySelectorAll('.question-map-item').length, answered:document.querySelectorAll('.question-map-item.is-answered').length})""")


def test_one_question_per_page_and_navigation(phone, web):
    page = phone(); login(page, web)
    s = state(page)
    assert s["visible"] == [0] and s["counter"] == "السؤال 1 من 8" and s["pager"] == "1 / 8" and s["prev"] and not s["next"] and s["items"] == 8
    page.click("[data-question-next]"); s = state(page)
    assert s["visible"] == [1] and s["counter"] == "السؤال 2 من 8" and not s["prev"]
    page.click("[data-question-prev]"); assert state(page)["visible"] == [0]
    assert not page.js_errors


def test_submit_only_on_last_question(phone, web):
    page = phone(); login(page, web)
    s = state(page); assert not s["submit"] and s["hint"]
    show(page, 7); s = state(page)
    assert s["visible"] == [7] and s["submit"] and not s["hint"] and s["next"]
    show(page, 3); assert not state(page)["submit"]


def test_map_marks_answers_and_jumps(phone, web):
    page = phone(); login(page, web)
    pick(page, 0, 1); pick(page, 5, 2)
    s = state(page); assert s["answered"] == 2 and s["visible"] == [5]
    assert page.inner_text(".map-toggle-count") == "مجاب 2 · باقي 6"
    page.click(".question-map-toggle"); page.wait_for_selector(".question-map", state="visible")
    page.locator(".question-map-item").nth(2).click()                                             # الضغط على رقم بيسكّر اللوحة وبيفتح السؤال
    page.wait_for_function("!document.getElementById('s-exam').classList.contains('map-open')")
    assert state(page)["visible"] == [2]


def test_exam_starts_at_the_top_with_the_first_question_visible(phone, web):
    page = phone(); page.goto(url(web))
    page.select_option("#g", "العاشر"); page.select_option("#sec", "أ"); page.select_option("#nm", "طالب أ1")
    page.evaluate("scrollTo(0, document.body.scrollHeight)")                                          # الطالب نزل لتحت ليضغط «ابدأ»
    page.click("#start"); page.wait_for_selector("#s-exam:not(.hide)"); page.wait_for_timeout(200)
    r = page.evaluate("""()=>{const q=document.querySelector('#qs .card:not(.question-hidden) .q').getBoundingClientRect();
        return {y:scrollY, top:q.top, bar:document.getElementById('bar').getBoundingClientRect().bottom, h:innerHeight}}""")
    assert r["y"] == 0 and r["bar"] <= r["top"] < r["h"], r


def test_reload_returns_to_the_same_question(phone, web):
    page = phone(); login(page, web)
    pick(page, 0, 0); pick(page, 4, 1); time.sleep(0.3)
    page.reload(); page.wait_for_selector("#s-exam:not(.hide)")
    s = state(page); assert s["visible"] == [4] and s["answered"] == 2


def test_full_exam_through_pages(phone, web):
    page = phone(); login(page, web); solve(page)
    assert state(page)["answered"] == 8
    submit(page); page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
    assert "8 / 8" in page.inner_text("#score").replace("⁦", "").replace("⁩", "") and not page.js_errors


def test_teacher_preview_uses_pages_too(pkg, browser):
    from test_http import Server
    w = Server(pkg).start()
    try:
        ctx = browser.new_context(viewport={"width": 1280, "height": 860}); page = ctx.new_page(); errs = []
        page.on("pageerror", lambda e: errs.append(str(e))); page.on("dialog", lambda d: d.accept())
        ck = w.post("/login", {"password": "secret"}, {"Content-Type": "application/json", "X-Exam-Action": "1"})[3]["Set-Cookie"].split(";")[0]
        ctx.add_cookies([{"name": ck.split("=")[0], "value": ck.split("=", 1)[1], "url": url(w)}])
        page.goto(url(w) + "teacher"); page.wait_for_selector("#s-exam:not(.hide)")                # المعاينة بتبدأ لحالها (بدون اختيار اسم)
        assert page.locator("#qs .card").count() == 11 and page.locator(".question-map-item").count() == 11 and page.is_visible(".question-map")   # الخريطة جانبية عالكمبيوتر
        page.locator(".question-map-item").nth(10).click(); page.click("#submit")
        page.wait_for_function("document.getElementById('status').textContent.includes('معاينة المعلم')")
        assert not errs
        ctx.close()
    finally:
        w.stop()
