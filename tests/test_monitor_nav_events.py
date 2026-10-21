"""شاشة المراقبة بنفس مظهر صفحات المعلم (مرحلة ب): شريط تنقل موحّد (نفس تبويبات الصفحات الثانية من السيرفر، وزر القفل لو في كلمة سر)،
وإشعارات حية (بدأ/سلّم/انقطع/رجع/خرج من الصفحة) بصوت اختياري مطفّأ افتراضياً. فحص بمتصفح حقيقي ضد السيرفر الحقيقي؛
والحالات اللي بيصعب صنعها بالوقت الحقيقي (تجميع، تهدئة التكرار، سقف 4 بطاقات) بنعدّل ردّ /monitor.json اللي بيوصل للمتصفح فقط (السيرفر حقيقي)."""
import copy, json, re, time

import pytest
from conftest import bank
from test_http import Server
from test_browser import browser, url  # noqa: F401  (fixture)
from test_monitor_new_ui import UI_SRC, A, servers, with_ui, raw_get  # noqa: F401  (servers = fixture)

pw = pytest.importorskip("playwright.sync_api")
expect = pw.expect
pytestmark = pytest.mark.skipif(not (UI_SRC / "index.html").exists(), reason="مجلد monitor_ui مش موجود بالحزمة")
TITLE = "اختبار الوحدة"

SPY = """(() => {                                                                   // بدل الصوت الحقيقي: بنسجّل كل نغمة (تردّدها) عشان نعرف شو انعزف
  window.__tones = [];
  class FakeAudio {
    constructor() { this.state = 'running'; this.currentTime = 0; this.destination = {}; }
    resume() { return Promise.resolve(); }
    createOscillator() { const o = { type: '', frequency: { value: 0 }, connect() {}, start() { window.__tones.push(o.frequency.value); }, stop() {} }; return o; }
    createGain() { return { gain: { setValueAtTime() {}, linearRampToValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect() {} }; }
  }
  window.AudioContext = FakeAudio; window.webkitAudioContext = FakeAudio;
})();"""


def light(pkg, servers, **settings):
    """سيرفر بـ 7 طلاب (بدون أي تسليم) وواجهة المراقبة الجديدة"""
    with_ui(pkg); pkg.students([["العاشر", "أ", n, ""] for n in A]); pkg.questions(bank()); pkg.settings(**settings)
    return servers(pkg)


def cfg_of(w):
    page = raw_get(w, "/monitor")[2].decode("utf-8")
    return json.loads(re.search(r"window\.MONITOR_CONFIG = (\{.*?\});", page, re.S).group(1))


def nav_of(w, path="/report"):
    """تبويبات شريط التنقل اللي بتقدّمه صفحات المعلم الثانية: ([[رابط، اسم]...]، في زر قفل؟)"""
    t = raw_get(w, path)[2].decode("utf-8"); header = re.search(r"<header class='tnav noprint'>(.*?)</header>", t, re.S).group(1)
    return [[h, n] for h, n in re.findall(r"<a href=(/\w+)[^>]*>([^<]+)</a>", re.search(r"<nav>(.*?)</nav>", header, re.S).group(1))], "/logout" in header


class Feed:
    """بيتحكم بردّ /monitor.json اللي بيوصل للمتصفح: كما هو، أو معدّل بخطوات (steps) بنقدّمها بأنفسنا (feed.level = 1 ← أول خطوة بالتحديث الجاي).
    بيلغي الاعتماد على توقيت التحديث (كل 4 ثواني) بالاختبارات اللي بتتطلب أحداث بنفس اللحظة"""
    def __init__(self, pg):
        self.base = None; self.steps = None; self.level = 0
        pg.route("**/monitor.json", self.handle)

    def handle(self, route):
        real = route.fetch().json()
        if self.steps is None: self.base = real; body = real
        else:
            body = copy.deepcopy(self.base)
            for step in self.steps[:self.level]: step(body)
        route.fulfill(status=200, headers={"content-type": "application/json; charset=utf-8", "cache-control": "no-store"}, body=json.dumps(body, ensure_ascii=False))

    def script(self, *steps): self.steps = list(steps); self.level = 0


def row(body, name):
    for rows in body["sections"].values():
        for r in rows:
            if r["name"] == name: return r
    raise KeyError(name)


def live(name, answered=1):
    def step(body): row(body, name).update(status="live", key=f"k-{name}", answered=answered, total=8, remain=900, ago=1, leaveN=0, leaveSec=0)
    return step


def lost(name, ago=40):
    def step(body): row(body, name).update(status="lost", key=f"k-{name}", ago=ago)
    return step


def never_pinged(name):
    def step(body): row(body, name).update(status="lost", key=f"k-{name}", ago=None)
    return step


def done(name):
    def step(body): row(body, name).update(status="done", key=f"k-{name}", score=6, total=8, durtxt="5 د", leave="لم يخرج", late=0)
    return step


def reset(*names):
    def step(body):
        for n in names: row(body, n).update(status="none", key=None)
    return step


def together(*steps):
    def step(body):
        for s in steps: s(body)
    return step


def open_monitor(browser, w, width=1366, height=800, spy=False, mobile=False):
    ctx = browser.new_context(viewport={"width": width, "height": height}, locale="ar-JO", is_mobile=mobile)
    if spy: ctx.add_init_script(SPY)
    pg = ctx.new_page(); pg.set_default_timeout(10000); errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    feed = Feed(pg)
    pg.goto(url(w) + "monitor"); pg.wait_for_selector(".kpi"); pg.wait_for_timeout(400)
    return ctx, pg, feed, errors


def cards(pg):
    """بطاقات الإشعارات الظاهرة: (اسم أو عدد، النص، المستوى)"""
    return [(c.locator(".ev-who b").inner_text(), c.locator(".ev-text").inner_text(), c.get_attribute("class").split()[-1]) for c in pg.locator(".ev").all()]


def tones(pg): return pg.evaluate("window.__tones")
def bell(pg): return pg.get_by_role("button", name="الإشعارات الحية")
def speaker(pg): return pg.get_by_role("button", name="صوت الإشعارات")


# ============================ شريط التنقل ============================
@pytest.mark.parametrize("over,codes,lock", [({}, False, True), ({"رمز_الدخول": "نعم"}, True, True), ({"كلمة_سر_المعلم": ""}, False, False)])
def test_monitor_config_carries_the_same_tabs_as_the_other_pages(pkg, servers, over, codes, lock):
    w = light(pkg, servers, **over); cfg = cfg_of(w); tabs, has_lock = nav_of(w)
    assert cfg["tabs"] == tabs and cfg["lock"] is has_lock is lock, (cfg, tabs)          # مصدر واحد: السيرفر
    assert any(u == "/codes" for u, _ in cfg["tabs"]) is codes and cfg["tabs"][0] == ["/monitor", "المراقبة الحية"]
    assert cfg["title"] == TITLE and cfg["link"].startswith("http://")


def test_nav_has_the_other_pages_and_moves_between_them_in_the_same_tab(pkg, servers, browser):
    w = light(pkg, servers, **{"رمز_الدخول": "نعم"}); ctx, pg, feed, errors = open_monitor(browser, w)
    try:
        want = nav_of(w)[0]
        got = [[a.get_attribute("href"), a.inner_text()] for a in pg.locator(".tnav nav a").all()]
        assert got == want and [a.get_attribute("href") for a in pg.locator(".tnav nav a.on").all()] == ["/monitor"]
        assert pg.locator(".tnav nav a[aria-current=page]").get_attribute("href") == "/monitor" and pg.locator(".tnav .brand").inner_text() == TITLE
        b = pg.eval_on_selector(".tnav .brand", "e=>e.getBoundingClientRect().left"); n = pg.eval_on_selector(".tnav nav", "e=>e.getBoundingClientRect().left")
        assert b > n                                                                       # اسم الامتحان أول عنصر من اليمين، زي باقي الصفحات
        assert pg.get_by_role("link", name="🔒 قفل").get_attribute("href") == "/logout"
        pg.locator(".tnav nav").get_by_text("التقارير والتحليل").click(); pg.wait_for_url("**/report")
        assert pg.locator(".tnav nav a.on").inner_text() == "التقارير والتحليل"            # نفس التبويبات بالصفحة الثانية، والمراقبة فيها
        pg.locator(".tnav nav").get_by_text("المراقبة الحية").click(); pg.wait_for_url("**/monitor"); pg.wait_for_selector(".kpi")
        assert not errors, errors
    finally:
        ctx.close()


def test_no_lock_button_without_a_teacher_password(pkg, servers, browser):
    w = light(pkg, servers, **{"كلمة_سر_المعلم": ""}); ctx, pg, feed, errors = open_monitor(browser, w)
    try:
        assert pg.get_by_role("link", name="🔒 قفل").count() == 0
    finally:
        ctx.close()


def test_tools_menu_keeps_only_the_monitor_tools(pkg, servers, browser):
    w = light(pkg, servers); ctx, pg, feed, errors = open_monitor(browser, w)
    try:
        pg.get_by_role("button", name="أدوات ▾").click()
        assert [a.get_attribute("href") for a in pg.locator(".popup a").all()] == ["/report.xlsx", "/link"]       # باقي الصفحات صارت بالشريط
        assert pg.locator(".popup button").all_inner_texts() == ["🧪 بروفة الضغط"]
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [1366, 900, 375])
def test_nav_stays_on_top_and_the_filter_bar_sticks_right_under_it(pkg, servers, browser, width):
    w = light(pkg, servers); ctx, pg, feed, errors = open_monitor(browser, w, width=width, height=300, mobile=width < 500)
    try:
        feed.script(together(*[live(n) for n in A])); feed.level = 1                           # كل الطلاب يمتحنون: الشعبة بتنفتح وبتصير الصفحة طويلة
        expect(pg.locator(".student-table tbody tr")).to_have_count(len(A), timeout=10000)
        natural = pg.evaluate("document.querySelector('.toolbar').getBoundingClientRect().top + window.scrollY")      # مكان الفلاتر الطبيعي بالصفحة
        pg.evaluate("window.scrollTo(0, %d)" % (natural + 40)); pg.wait_for_timeout(300)
        assert pg.evaluate("window.scrollY") >= natural + 30                                 # فعلاً نزلنا بعد مكانها الطبيعي: يعني هي لازقة مش ماشية مع الصفحة
        head = pg.eval_on_selector(".tnav", "e=>{const r=e.getBoundingClientRect();return [r.top,r.bottom]}"); bar = pg.eval_on_selector(".toolbar", "e=>e.getBoundingClientRect().top")
        assert abs(head[0]) <= 1 and abs(bar - head[1]) <= 1.5, (width, head, bar)           # الفلاتر تلزق تحت الشريط حتى لو الشريط لفّ بسطرين
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        if width == 375:
            assert head[1] < 130                                                              # الشريط ما بياكل الشاشة بالجوال
            assert pg.eval_on_selector(".tnav nav", "e=>e.scrollWidth > e.clientWidth")      # والتبويبات بتتمرّر داخل إطارها
            for label in ("الإشعارات الحية", "صوت الإشعارات", "أدوات ▾"):
                r = pg.get_by_role("button", name=label).bounding_box(); assert r and r["x"] >= 0 and r["x"] + r["width"] <= 376, label
        assert not errors, errors
    finally:
        ctx.close()


# ============================ الإشعارات الحية (سيرفر حقيقي) ============================
def test_live_notifications_follow_a_real_student_from_start_to_submit(pkg, servers, browser):
    w = light(pkg, servers)
    k0, st, j0 = w.start_student("d0", n="طالب أ2", s="أ"); w.post("/ping", {"key": k0, "dev": "d0", "answered": 0, "total": 8, "remain": 1500, "ans": {}})
    k1, st, j1 = w.start_student("d1", n="طالب أ3", s="أ"); assert w.submit(k1, "d1", j1["ids"], w.correct_answers(j1["ids"]))[0] == 200   # موجودين قبل فتح الصفحة
    ctx, pg, feed, errors = open_monitor(browser, w)
    try:
        pg.wait_for_timeout(5500); assert cards(pg) == []                                   # اللي صار قبل فتح الصفحة مش «حدث»
        assert bell(pg).get_attribute("aria-pressed") == "true" and speaker(pg).get_attribute("aria-pressed") == "false"   # الإشعارات مفعّلة والصوت مطفّأ افتراضياً
        k, st, j = w.start_student("d9", n="طالب أ1", s="أ")
        ping = lambda **extra: w.post("/ping", dict({"key": k, "dev": "d9", "answered": 1, "total": 8, "remain": 1500, "ans": {}}, **extra))
        ping()
        mine = pg.locator(".ev", has_text="طالب أ1")                                         # (طالب أ2 اللي نبض قبل فتح الصفحة بينقطع هو كمان بنص الاختبار)
        expect(mine).to_contain_text("بدأ الامتحان", timeout=10000); assert "العاشر" in mine.inner_text() and mine.get_attribute("class").split()[-1] == "info"
        ping(leaveN=1, leaveSec=6); expect(mine.filter(has_text="خرج من الصفحة")).to_contain_text("للمرة 1", timeout=10000)
        t0 = time.time()                                                                    # بنوقف النبضات: بعد 25 ثانية بيصير «انقطع»
        lost_card = mine.filter(has_text="انقطع اتصاله"); expect(lost_card).to_be_visible(timeout=45000)
        assert time.time() - t0 > 15 and lost_card.get_attribute("class").split()[-1] == "warn"
        ping(); expect(mine.filter(has_text="عاد اتصاله")).to_be_visible(timeout=10000)
        assert w.submit(k, "d9", j["ids"], w.correct_answers(j["ids"]))[0] == 200
        expect(mine.filter(has_text="سلّم")).to_have_text(re.compile(r"سلّم · \d+ / \d+"), timeout=10000); assert mine.filter(has_text="سلّم").get_attribute("class").split()[-1] == "ok"
        assert not errors, errors
    finally:
        ctx.close()


# ============================ الإشعارات: منطق الأحداث (ردّ المراقبة معدّل) ============================
def test_started_student_with_no_first_ping_yet_is_not_reported_as_lost(pkg, servers, browser):
    """بين ضغطة «ابدأ» وأول نبضة (ثواني) الطالب بيطلع «لم يتصل بعد»: هذا مش انقطاع، وبيصير إشعار «بدأ الامتحان» لما توصل نبضته"""
    w = light(pkg, servers); ctx, pg, feed, errors = open_monitor(browser, w)
    try:
        feed.script(never_pinged("طالب أ1"), live("طالب أ1"), lost("طالب أ1"))
        feed.level = 1; pg.wait_for_timeout(9000); assert cards(pg) == []                  # لسا ما وصلت النبضة الأولى: ولا إشعار (خصوصاً مش «انقطع»)
        feed.level = 2; expect(pg.locator(".ev")).to_have_count(1, timeout=10000); assert cards(pg) == [("طالب أ1", "بدأ الامتحان", "info")]
        feed.level = 3; expect(pg.locator(".ev", has_text="انقطع اتصاله")).to_have_count(1, timeout=10000)   # الانقطاع الحقيقي بعد ما كان يتصل
        assert not errors, errors
    finally:
        ctx.close()


def test_more_than_three_of_a_kind_become_one_card(pkg, servers, browser):
    w = light(pkg, servers); ctx, pg, feed, errors = open_monitor(browser, w)
    try:
        feed.script(together(*[live(n) for n in A[:4]]), together(done(A[4]), done(A[5])))
        feed.level = 1; expect(pg.locator(".ev")).to_have_count(1, timeout=10000); assert cards(pg) == [("4 طلاب", "بدؤوا الامتحان", "info")]
        feed.level = 2; expect(pg.locator(".ev")).to_have_count(3, timeout=10000)          # 2 سلّموا = أقل من الحد: كل واحد ببطاقة
        assert sorted(c[0] for c in cards(pg)) == sorted(["4 طلاب", A[4], A[5]])
        assert not errors, errors
    finally:
        ctx.close()


def test_exactly_three_of_a_kind_stay_separate_cards(pkg, servers, browser):
    w = light(pkg, servers); ctx, pg, feed, errors = open_monitor(browser, w)
    try:
        feed.script(together(*[live(n) for n in A[:3]])); feed.level = 1
        expect(pg.locator(".ev")).to_have_count(3, timeout=10000); assert sorted(c[0] for c in cards(pg)) == sorted(A[:3])
    finally:
        ctx.close()


def test_a_student_going_back_and_forth_does_not_spam_a_second_lost_card(pkg, servers, browser):
    w = light(pkg, servers); ctx, pg, feed, errors = open_monitor(browser, w)
    try:
        feed.script(live(A[0]), lost(A[0]), live(A[0]), lost(A[0]))
        for level, want, icon in ((1, "بدأ الامتحان", "▶"), (2, "انقطع اتصاله", "⚠"), (3, "عاد اتصاله", "↺")):
            feed.level = level; expect(pg.locator(".ev", has_text=want)).to_have_count(1, timeout=10000)
            assert pg.locator(".ev", has_text=want).locator(".ev-icon").inner_text() == icon                   # لكل نوع حدث أيقونته
        for _ in range(pg.locator(".ev").count()): pg.locator(".ev .ev-x").first.click()
        expect(pg.locator(".ev")).to_have_count(0)
        feed.level = 4; pg.wait_for_timeout(9500)                                          # انقطع مرة ثانية خلال دقيقة: ما بنزعج المعلم فيه
        assert cards(pg) == [], cards(pg)
    finally:
        ctx.close()


def test_reopened_student_gets_a_card(pkg, servers, browser):
    w = light(pkg, servers); ctx, pg, feed, errors = open_monitor(browser, w)
    try:
        feed.script(done(A[0]), live(A[0]))
        feed.level = 1; expect(pg.locator(".ev", has_text="سلّم")).to_have_count(1, timeout=10000)
        feed.level = 2; expect(pg.locator(".ev", has_text="أُعيد فتحه")).to_have_count(1, timeout=10000)
        assert pg.locator(".ev", has_text="أُعيد فتحه").get_attribute("class").split()[-1] == "info"
    finally:
        ctx.close()


def test_release_and_new_exam_do_not_raise_cards(pkg, servers, browser):
    w = light(pkg, servers); ctx, pg, feed, errors = open_monitor(browser, w)
    try:
        feed.script(together(live(A[0]), live(A[1]), done(A[2])), reset(*A[:3]))
        feed.level = 1; expect(pg.locator(".ev")).to_have_count(3, timeout=10000)
        for _ in range(3): pg.locator(".ev .ev-x").first.click()
        expect(pg.locator(".ev")).to_have_count(0)                                         # زر × بيقفل البطاقة
        feed.level = 2; pg.wait_for_timeout(9500); assert cards(pg) == []                  # فك حجز / امتحان جديد: ما في إشعار
    finally:
        ctx.close()


def test_at_most_four_cards_and_the_stack_does_not_block_the_page(pkg, servers, browser):
    w = light(pkg, servers); ctx, pg, feed, errors = open_monitor(browser, w)
    try:
        feed.script(together(*[live(n) for n in A[:3]], *[done(n) for n in A[3:6]])); feed.level = 1
        expect(pg.locator(".ev")).to_have_count(4, timeout=10000); pg.wait_for_timeout(5000); assert pg.locator(".ev").count() == 4   # 6 أحداث بتحديث واحد: بتبقى 4 بطاقات
        assert pg.eval_on_selector(".ev-stack", "e=>getComputedStyle(e).pointerEvents") == "none" and pg.eval_on_selector(".ev", "e=>getComputedStyle(e).pointerEvents") == "auto"
        box = pg.eval_on_selector(".ev-stack", "e=>{const r=e.getBoundingClientRect();return [r.left,r.top,r.width,r.height]}"); bottom = pg.get_by_role("button", name="↻ بداية امتحان جديد").bounding_box()
        assert box[1] + box[3] <= bottom["y"] + 1                                          # فوق شريط الأزرار السفلي مش فوقه
    finally:
        ctx.close()


def test_info_cards_fade_after_a_few_seconds_but_warnings_stay_longer(pkg, servers, browser):
    w = light(pkg, servers)
    k, st, j = w.start_student("d1", n="طالب أ1", s="أ"); w.post("/ping", {"key": k, "dev": "d1", "answered": 1, "total": 8, "remain": 1500, "ans": {}})
    ctx, pg, feed, errors = open_monitor(browser, w)
    try:
        feed.script(together(live(A[1]), lost(A[0]))); feed.level = 1
        expect(pg.locator(".ev")).to_have_count(2, timeout=10000)
        expect(pg.locator(".ev.info")).to_have_count(0, timeout=9000)                      # «بدأ» بيختفي بعد ~7 ثواني
        assert pg.locator(".ev.warn").count() == 1                                         # و«انقطع» لسا ظاهر
        expect(pg.locator(".ev.warn")).to_have_count(0, timeout=9000)                      # وبيختفي بعد ~12
    finally:
        ctx.close()


# ============================ الصوت والتفضيلات ============================
def test_sound_is_off_by_default_and_plays_only_for_submit_and_warnings(pkg, servers, browser):
    w = light(pkg, servers); ctx, pg, feed, errors = open_monitor(browser, w, spy=True)
    try:
        feed.script(done(A[0]), together(done(A[0]), done(A[1])), together(done(A[0]), done(A[1]), live(A[2])), together(done(A[0]), done(A[1]), lost(A[2])))
        feed.level = 1; expect(pg.locator(".ev", has_text=A[0])).to_have_count(1, timeout=10000); assert tones(pg) == []     # مطفّأ: ولا نغمة
        speaker(pg).click(); assert speaker(pg).get_attribute("aria-pressed") == "true" and tones(pg) == [880]                 # نغمة تجريبية عند التفعيل
        feed.level = 2; expect(pg.locator(".ev", has_text=A[1])).to_have_count(1, timeout=10000); assert tones(pg) == [880, 880]   # سلّم: نغمة وحدة
        feed.level = 3; expect(pg.locator(".ev", has_text=A[2])).to_have_count(1, timeout=10000); assert tones(pg) == [880, 880]   # بدأ: بدون صوت
        feed.level = 4; expect(pg.locator(".ev", has_text="انقطع اتصاله")).to_have_count(1, timeout=10000); assert tones(pg) == [880, 880, 660, 440]   # انقطع: نغمتين
    finally:
        ctx.close()


def test_one_tone_per_update_even_with_many_events(pkg, servers, browser):
    w = light(pkg, servers); ctx, pg, feed, errors = open_monitor(browser, w, spy=True)
    try:
        speaker(pg).click(); assert tones(pg) == [880]
        feed.script(together(*[done(n) for n in A[:3]])); feed.level = 1                      # 3 سلّموا = 3 بطاقات منفصلة، بس نغمة وحدة
        expect(pg.locator(".ev")).to_have_count(3, timeout=10000); pg.wait_for_timeout(500); assert tones(pg) == [880, 880]
    finally:
        ctx.close()


def test_preferences_survive_reload_and_notifications_off_silences_everything(pkg, servers, browser):
    w = light(pkg, servers); ctx, pg, feed, errors = open_monitor(browser, w, spy=True)
    try:
        speaker(pg).click(); bell(pg).click()
        assert bell(pg).get_attribute("aria-pressed") == "false" and speaker(pg).is_disabled()      # إيقاف الإشعارات بيعطّل زر الصوت
        feed.script(done(A[0])); feed.level = 1; pg.wait_for_timeout(9000)
        assert cards(pg) == [] and tones(pg) == [880]                                                  # لا بطاقة ولا نغمة (الواحدة هي التجريبية)
        pg.reload(); pg.wait_for_selector(".kpi")
        assert bell(pg).get_attribute("aria-pressed") == "false" and speaker(pg).is_disabled()          # بتنحفظ على هذا المتصفح
        bell(pg).click(); assert speaker(pg).is_enabled() and speaker(pg).get_attribute("aria-pressed") == "true"   # والصوت لسا مفعّل من قبل
        pg.reload(); pg.wait_for_selector(".kpi")
        assert bell(pg).get_attribute("aria-pressed") == "true" and speaker(pg).get_attribute("aria-pressed") == "true"
    finally:
        ctx.close()


def test_storage_blocked_does_not_break_the_screen(pkg, servers, browser):
    w = light(pkg, servers); ctx = browser.new_context(viewport={"width": 1366, "height": 800}, locale="ar-JO"); errors = []
    ctx.add_init_script("Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } });")
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
    try:
        pg.goto(url(w) + "monitor"); pg.wait_for_selector(".kpi")
        assert bell(pg).get_attribute("aria-pressed") == "true"; bell(pg).click(); assert bell(pg).get_attribute("aria-pressed") == "false" and not errors, errors
    finally:
        ctx.close()
