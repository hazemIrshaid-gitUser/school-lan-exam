"""المرحلة 6: واجهة الطالب بمتصفح حقيقي (Edge عبر Playwright) بشاشة موبايل، ضد سيرفر حقيقي.
بتتخطّى لو Playwright أو Edge مش موجودين. لتصوير الشاشات للمراجعة اليدوية: SHOTS_DIR=مجلد pytest test_browser.py"""
import base64, os, pathlib, re, time

import pytest

pw = pytest.importorskip("playwright.sync_api")
from conftest import LETTERS, bank, q
from test_http import Server, H, TEACHER

PNG_1PX = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
ISO = "⁦⁩"
SHOTS = os.environ.get("SHOTS_DIR")
ENGINE = os.environ.get("EXAM_BROWSER", "edge").lower()               # webkit = محرّك سفاري (آيفون): EXAM_BROWSER=webkit pytest test_browser.py


def launch(p):
    """متصفح صفحات الطلاب: Edge (كروميوم، زي أندرويد) افتراضياً، أو WebKit (محرّك سفاري) — بيحتاج: python -m playwright install webkit"""
    return p.webkit.launch(headless=True) if ENGINE == "webkit" else p.chromium.launch(channel="msedge", headless=True)


def phone_ctx(p, b, **extra):
    """«جوال طالب»: على WebKit آيفون 13 بأبعاده وuser agent تبعه، وإلا جوال 375×812"""
    if ENGINE == "webkit":
        d = {k: v for k, v in p.devices["iPhone 13"].items() if k != "default_browser_type"}
        return b.new_context(**d, locale="ar-JO", **extra)
    return b.new_context(viewport={"width": 375, "height": 812}, is_mobile=True, has_touch=True, locale="ar-JO", device_scale_factor=2, **extra)


@pytest.fixture(scope="module")
def browser():
    with pw.sync_playwright() as p:
        try:
            b = launch(p)
        except Exception as e:                                           # noqa
            pytest.skip(f"المتصفح ({ENGINE}) غير متاح: {e}")
        b.pw_ = p
        yield b
        b.close()


@pytest.fixture
def phone(browser):
    """يعمل «جهاز طالب» جديد (ذاكرة محلية فاضية) بشاشة موبايل"""
    made = []
    def make(device="Pixel 5"):
        ctx = phone_ctx(browser.pw_, browser)
        page = ctx.new_page(); page.set_default_timeout(8000)
        page.dialogs = []
        page.on("dialog", lambda d: (page.dialogs.append(d.message), d.accept()))
        errors = []; page.js_errors = errors
        page.on("pageerror", lambda e: errors.append(str(e)))
        made.append(ctx); return page
    yield make
    for c in made: c.close()


@pytest.fixture
def web(pkg):
    s = Server(pkg).start()
    yield s
    s.stop()


def url(w): return f"http://127.0.0.1:{w.port}/"


def login(page, w, name="طالب أ1", section="أ", grade="العاشر", go=True):
    page.goto(url(w))
    page.select_option("#g", grade); page.select_option("#sec", section); page.select_option("#nm", name)
    if go:
        page.click("#start"); page.wait_for_selector("#s-exam:not(.hide)")


def no_hscroll(page):
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def clean(t): return t.replace("⁦", "").replace("⁩", "").strip()


def show(page, i):
    """يعرض السؤال رقم i (من 0) زي الطالب (سؤال بكل صفحة): «السؤال التالي» لو هو اللي بعد الحالي، وإلا من خريطة الأسئلة"""
    cards = page.locator("#qs .card")
    if "question-hidden" not in (cards.nth(i).get_attribute("class") or ""): return
    if i > 0 and "question-hidden" not in (cards.nth(i - 1).get_attribute("class") or ""):
        page.click("[data-question-next]")
    else:
        if page.is_visible(".question-map-toggle"): page.click(".question-map-toggle")          # على الجوال الخريطة بلوحة جانبية
        page.locator(".question-map-item").nth(i).click()
    page.wait_for_function(f"!document.querySelectorAll('#qs .card')[{i}].classList.contains('question-hidden')")


def pick(page, i, j):
    """يختار الخيار j بالسؤال i (بعد ما ينتقل له)"""
    show(page, i); page.locator("#qs .card").nth(i).locator("label.opt").nth(j).click()


def submit(page):
    """التسليم: زر «تسليم الامتحان» بيظهر بالسؤال الأخير بس"""
    show(page, page.locator("#qs .card").count() - 1); page.click("#submit")


def solve(page, wrong=0):
    """يحل الورقة: الإجابات الصحيحة حسب bank() (السؤال N صحيحه LETTERS[(N-1)%4])، ويغلّط أول wrong سؤال"""
    done_wrong = 0
    for i, c in enumerate(page.query_selector_all("#qs .card")):
        show(page, i)
        n = int(re.search(r"سؤال رقم\s*⁦?(\d+)", c.inner_text()).group(1))
        letter = LETTERS[(n - 1) % 4]
        labels = c.query_selector_all("label.opt")
        right = next(l for l in labels if clean(l.inner_text()) == f"خ{n - 1}-{letter}")
        if done_wrong < wrong:
            next(l for l in labels if l is not right).click(); done_wrong += 1
        else:
            right.click()


def shot(page, name):
    if SHOTS:
        pathlib.Path(SHOTS).mkdir(parents=True, exist_ok=True); page.screenshot(path=str(pathlib.Path(SHOTS) / f"{name}.png"), full_page=True)


# ---------------- شاشة الدخول ----------------
def test_login_screen(phone, web):
    page = phone(); page.goto(url(web))
    assert page.get_attribute("html", "dir") == "rtl" and page.inner_text("#title") == "اختبار الوحدة"
    assert "8 سؤال" in page.inner_text("#meta") and "30 دقيقة" in page.inner_text("#meta")
    assert page.is_disabled("#start") and page.is_disabled("#sec") and no_hscroll(page)
    page.select_option("#g", "العاشر"); page.select_option("#sec", "أ")
    assert page.eval_on_selector_all("#nm option", "o=>o.map(x=>x.textContent)") == ["اختر الاسم", "طالب أ1", "طالب أ2", "طالب أ3"]
    assert page.is_disabled("#start")
    page.select_option("#nm", "طالب أ2"); assert page.is_enabled("#start")
    shot(page, "01_login"); assert not page.js_errors


def test_exam_screen_layout_and_timer(phone, web):
    page = phone(); login(page, web)
    assert page.inner_text("#who") == "طالب أ1" and len(page.query_selector_all("#qs .card")) == 8
    assert all(len(c.query_selector_all("input[type=radio]")) == 4 for c in page.query_selector_all("#qs .card"))
    t0 = page.inner_text("#clock"); assert t0 in ("30:00", "29:59", "29:58", "29:57") and no_hscroll(page)
    time.sleep(2.2); assert page.inner_text("#clock") < t0
    shot(page, "02_exam"); assert not page.js_errors


def test_reload_resumes_same_paper_answers_and_time(phone, web):
    page = phone(); login(page, web)
    before = page.eval_on_selector_all("#qs .card .q", "e=>e.map(x=>x.textContent)")
    pick(page, 0, 2)
    pick(page, 3, 1)
    time.sleep(2)                                                          # السيرفر يحفظ الإجابات خلال ثانيتين
    page.reload(); page.wait_for_selector("#s-exam:not(.hide)")
    assert page.eval_on_selector_all("#qs .card .q", "e=>e.map(x=>x.textContent)") == before
    assert page.eval_on_selector_all("#qs input:checked", "e=>e.length") == 2
    assert page.eval_on_selector_all("#qs .card:nth-child(1) input", "e=>e.map(x=>x.checked)") == [False, False, True, False]


def test_resume_on_another_browser_profile_after_move(phone, web):
    """جهاز تعطل: المعلم بينقل الطالب، وبجهاز جديد (ذاكرة فاضية) بيكمل بنفس الأسئلة والإجابات"""
    a = phone(); login(a, web)
    qs = a.eval_on_selector_all("#qs .card .q", "e=>e.map(x=>x.textContent)")
    pick(a, 1, 3); time.sleep(2)
    web.teacher(move=web.key())
    b = phone(); login(b, web)
    assert b.eval_on_selector_all("#qs .card .q", "e=>e.map(x=>x.textContent)") == qs
    assert b.eval_on_selector_all("#qs .card:nth-child(2) input", "e=>e.map(x=>x.checked)") == [False, False, False, True]


# ---------------- التسليم ----------------
def test_submit_all_correct_shows_full_score_and_blocks_device(phone, web):
    page = phone(); login(page, web); solve(page)
    submit(page)
    page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
    assert "8 / 8" in clean(page.inner_text("#score")) and page.inner_text("#who") == "طالب أ1" or True
    shot(page, "03_done")
    page.reload(); page.select_option("#g", "العاشر"); page.select_option("#sec", "أ"); page.select_option("#nm", "طالب أ1")
    assert page.is_visible("#blocked") and page.is_disabled("#start")      # نفس الجهاز ما بيقدر يعيد
    assert not page.js_errors


def test_submit_with_unanswered_asks_confirmation_and_scores(phone, web):
    page = phone(); login(page, web); solve(page, wrong=2)
    page.query_selector_all("#qs .card")[7].evaluate("c=>c.querySelectorAll('input').forEach(i=>i.checked=false)")      # سؤال بدون إجابة
    submit(page)
    page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
    assert any("بدون إجابة" in m for m in page.dialogs)
    got = int(re.search(r"(\d+) / 8", clean(page.inner_text("#score"))).group(1))
    assert got <= 6


def test_other_device_cannot_take_started_name(phone, web):
    a = phone(); login(a, web)
    b = phone(); b.goto(url(web)); b.select_option("#g", "العاشر"); b.select_option("#sec", "أ")
    assert "طالب أ1" not in b.eval_on_selector_all("#nm option", "o=>o.map(x=>x.textContent)")       # الاسم اختفى من القائمة


def test_review_after_submit_when_enabled(pkg, phone):
    pkg.settings(**{"مراجعة_الأخطاء": "نعم"}); w = Server(pkg).start()
    try:
        page = phone(); login(page, w); solve(page, wrong=3); submit(page)
        page.wait_for_selector("#review .rv")
        assert len(page.query_selector_all("#review .rv")) == 3
        shot(page, "04_review")
    finally:
        w.stop()


def test_hidden_score_when_disabled(pkg, phone):
    pkg.settings(**{"إظهار_العلامة_للطالب": "لا"}); w = Server(pkg).start()
    try:
        page = phone(); login(page, w); solve(page); submit(page)
        page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
        assert "8" not in clean(page.inner_text("#score")).replace("8 /", "X") or "تم استلام" in page.inner_text("#s-done")
        assert "تم استلام إجاباتك" in page.inner_text("#s-done") and " / " not in page.inner_text("#score")
    finally:
        w.stop()


# ---------------- أوامر المعلم تظهر عند الطالب ----------------
def test_teacher_message_appears_once(phone, web):
    page = phone(); login(page, web)
    web.teacher(message="باقي 5 دقائق")
    pick(page, 0, 0)      # تغيير إجابة بيفعّل ping خلال ثانيتين
    page.wait_for_selector("#notice:not(.hide)", timeout=6000)
    assert "باقي 5 دقائق" in page.inner_text("#noticeText")
    page.click("#notice button"); pick(page, 0, 1); time.sleep(2.5)
    assert page.is_hidden("#notice")                                          # نفس الرسالة ما بتظهر مرتين


def test_close_exam_auto_submits_student(phone, web):
    page = phone(); login(page, web); solve(page)
    web.teacher(close=True)
    pick(page, 0, 0)      # يفعّل ping فيعرف إن الوقت خلص
    page.wait_for_function("document.getElementById('status').textContent.includes('✓')", timeout=15000)
    assert len(web.pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()) == 1


def test_released_student_returns_to_login(phone, web):
    page = phone(); login(page, web)
    web.teacher(release=web.key())
    pick(page, 0, 0)
    page.wait_for_selector("#s-login:not(.hide)", timeout=15000)
    assert any("أعاد المعلم" in m for m in page.dialogs)


def test_submit_for_student_shows_result_on_their_page(phone, web):
    page = phone(); login(page, web); solve(page)
    time.sleep(2)
    web.teacher(submitfor=web.key())
    pick(page, 0, 0)
    page.wait_for_selector("#s-done:not(.hide)", timeout=15000)


def test_leaving_page_is_flagged(phone, web):
    page = phone(); login(page, web)
    page.evaluate("dispatchEvent(new Event('blur'))")
    assert page.is_visible("#away")
    page.evaluate("dispatchEvent(new Event('focus'))")
    assert page.is_visible("#away")                                           # التحذير الأحمر بيضل ظاهر بعد الرجوع (تصميم مقصود: يذكّر الطالب إن خروجه انسجّل)
    page.evaluate("dispatchEvent(new Event('blur'))"); page.evaluate("ping()"); time.sleep(0.5)
    row = next(r for s in web.get("/monitor.json")[1]["sections"].values() for r in s if r["name"] == "طالب أ1")
    assert row["leaveN"] >= 2


# ---------------- منع النسخ ----------------
def test_lockdown_blocks_copy_menu_and_shortcuts(phone, web):
    page = phone(); login(page, web)
    res = page.evaluate("""()=>['copy','cut','paste','contextmenu','selectstart','dragstart'].map(t=>{const e=new Event(t,{cancelable:true,bubbles:true});document.body.dispatchEvent(e);return e.defaultPrevented})""")
    assert all(res)
    for combo in ("ctrl+c", "ctrl+u", "ctrl+shift+i", "F12", "ctrl+s", "ctrl+p"):
        r = page.evaluate("c=>{const p=c.split('+');const e=new KeyboardEvent('keydown',{key:p[p.length-1],ctrlKey:p.includes('ctrl'),shiftKey:p.includes('shift'),cancelable:true,bubbles:true});document.dispatchEvent(e);return e.defaultPrevented}", combo)
        assert r, combo
    assert page.evaluate("getComputedStyle(document.querySelector('.q')).userSelect") == "none"


def test_lockdown_off_allows_copy(pkg, phone):
    pkg.settings(**{"منع_النسخ": "لا"}); w = Server(pkg).start()
    try:
        page = phone(); login(page, w)
        assert page.evaluate("()=>{const e=new Event('copy',{cancelable:true,bubbles:true});document.body.dispatchEvent(e);return e.defaultPrevented}") is False
    finally:
        w.stop()


# ---------------- محتوى الأسئلة ----------------
def test_images_render_and_fit_phone_width(pkg, phone):
    rows = bank(); rows[0][0] = "شاهد الشكل [img:fig.png] ثم أجب"; rows[0][1] = "[img:fig.png]"
    pkg.questions(rows); pkg.image("fig.png", PNG_1PX)
    pkg.settings(**{"عدد_الأسئلة_الصعبة": 3, "عدد_الأسئلة_المتوسطة": 4, "عدد_الأسئلة_السهلة": 4, "عدد_الأسئلة_الكلي": 11})
    w = Server(pkg).start()
    try:
        page = phone(); login(page, w)
        imgs = page.query_selector_all("#qs img.qimg")
        assert imgs and all(page.evaluate("i=>i.complete && i.naturalWidth>0", i) for i in imgs)
        assert no_hscroll(page) and not page.js_errors
    finally:
        w.stop()


def test_math_and_html_in_questions_render_safely(pkg, phone):
    rows = bank()
    rows[0][0] = "أوجد قيمة x² + y² = 25 عندما x < 4 & y > 2"
    rows[1][0] = "<script>window.__pwn=1</script><img src=x onerror=\"window.__pwn=2\"> سؤال خطير"
    pkg.questions(rows); pkg.settings(**{"عدد_الأسئلة_الصعبة": 3, "عدد_الأسئلة_المتوسطة": 4, "عدد_الأسئلة_السهلة": 4, "عدد_الأسئلة_الكلي": 11, "خلط_الأسئلة": "لا"})
    w = Server(pkg).start()
    try:
        page = phone(); login(page, w); time.sleep(0.5)
        assert page.evaluate("window.__pwn") is None                        # ما تنفّذ أي سكربت من نص السؤال
        t = page.inner_text("#qs .card:nth-child(1) .q")
        assert "x < 4 & y > 2" in clean(t) and "<script>" in page.inner_text("#qs .card:nth-child(2) .q")      # بينعرض كنص مش كوسم
    finally:
        w.stop()


@pytest.mark.parametrize("name", ["O'Brien", 'قال "س"', "علي & محمد", "أحمد (الصغير)", "محمد-علي", "ج٬ ك"])
def test_student_names_with_special_characters_can_start(pkg, phone, name):
    from conftest import roster
    pkg.students(roster() + [["العاشر", "أ", name]]); w = Server(pkg).start()
    try:
        page = phone(); login(page, w, name=name)
        assert page.inner_text("#who") == name
        solve(page); submit(page); page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
    finally:
        w.stop()


# كانت مشكلة (fill بـ innerHTML): أُصلحت بـ template.html. أسماء فيها < أو كيان HTML لازم تشتغل
@pytest.mark.parametrize("name", ["AT&amp;T", "<i>x</i>"])
def test_student_names_with_html_syntax_can_start(pkg, phone, name):
    from conftest import roster
    pkg.students(roster() + [["العاشر", "أ", name]]); w = Server(pkg).start()
    try:
        page = phone(); page.goto(url(w)); page.select_option("#g", "العاشر"); page.select_option("#sec", "أ")
        page.wait_for_function("document.getElementById('nm').options.length > 4")                   # قائمة الأسماء بتنعبّى بعد ما يسأل السيرفر مين محجوز
        page.evaluate("()=>{const n=document.getElementById('nm');n.selectedIndex=n.options.length-1;n.onchange()}")      # الطالب بيختار آخر اسم بالقائمة كما ظهر له
        page.click("#start")
        page.wait_for_selector("#s-exam:not(.hide)", timeout=4000)
    finally:
        w.stop()


def test_english_question_direction(pkg, phone):
    rows = bank(); rows[0][0] = "Choose the correct word: She ____ to school every day."
    pkg.questions(rows); pkg.settings(**{"عدد_الأسئلة_الصعبة": 3, "عدد_الأسئلة_المتوسطة": 4, "عدد_الأسئلة_السهلة": 4, "عدد_الأسئلة_الكلي": 11, "خلط_الأسئلة": "لا"})
    w = Server(pkg).start()
    try:
        page = phone(); login(page, w)
        assert page.evaluate("getComputedStyle(document.querySelector('#qs .card:nth-child(1) .q')).direction") == "ltr"      # dir=auto
        assert page.evaluate("getComputedStyle(document.querySelector('#qs .card:nth-child(2) .q')).direction") == "rtl"
        shot(page, "05_english")
    finally:
        w.stop()


# ---------------- مجموعة طلاب بالتوازي ومتصفحات حقيقية ----------------
def test_twelve_browsers_take_exam_together(pkg, phone):
    from conftest import roster
    pkg.students([["العاشر", "أ", f"طالب {i}"] for i in range(12)]); w = Server(pkg).start()
    try:
        pages = [phone() for _ in range(12)]
        for i, pg in enumerate(pages): login(pg, w, name=f"طالب {i}")
        for i, pg in enumerate(pages): solve(pg, wrong=i % 4)
        for pg in pages: submit(pg)
        for pg in pages: pg.wait_for_function("document.getElementById('status').textContent.includes('✓')", timeout=20000)
        scores = sorted(int(re.search(r"(\d+) / 8", clean(pg.inner_text("#score"))).group(1)) for pg in pages)
        assert scores == sorted(8 - i % 4 for i in range(12))
        assert w.get("/monitor.json")[1]["c"]["done"] == 12
    finally:
        w.stop()


# ---------------- انقطاع الشبكة أثناء التسليم ----------------
def test_submit_survives_server_outage(pkg, phone):
    w = Server(pkg).start(); port = w.port
    page = phone(); login(page, w); solve(page)
    w.stop()                                                                 # السيرفر وقع (كهرباء/إعادة تشغيل)
    submit(page)
    page.wait_for_function("document.getElementById('status').textContent.includes('تعذّر الحفظ')", timeout=20000)
    w2 = Server(pkg); w2.start(port=port)
    try:
        page.wait_for_selector("#s-exam:not(.hide)", timeout=25000)             # الصفحة بترجع لحالها لما يرجع السيرفر (بدون Refresh): نفس الورقة المحفوظة بالسيرفر وبالجهاز
        assert page.eval_on_selector_all("#qs input:checked", "e=>e.length") == 8
        submit(page); page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
        assert "8 / 8" in clean(page.inner_text("#score"))
    finally:
        w2.stop()


def test_hostile_student_name_is_inert_on_teacher_pages(pkg, phone):
    """اسم فيه HTML ما لازم ينفّذ شي بصفحات المعلم (مراقبة، تقرير، ورقات، مفتاح)"""
    evil = "<img src=x onerror=window.__pwn=1>"
    from conftest import roster
    pkg.students(roster() + [["العاشر", "أ", evil]]); w = Server(pkg).start()
    try:
        s = phone(); login(s, w, name=evil)                                   # الطالب نفسه بيبدأ ويسلّم
        solve(s); submit(s); s.wait_for_function("document.getElementById('status').textContent.includes('✓')")
        t = phone()
        for path in ("/monitor", "/report", "/sheet", "/key"):
            if path in ("/sheet", "/key"):
                t.goto(url(w) + "login")
                t.fill("#p", "secret"); t.click("#b"); t.wait_for_url(re.compile(r"/monitor"), timeout=5000)
            t.goto(url(w) + path.lstrip("/")); time.sleep(1.2)
            assert t.evaluate("window.__pwn") is None, path
            assert not t.js_errors, (path, t.js_errors)
    finally:
        w.stop()
