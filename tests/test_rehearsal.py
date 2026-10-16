"""بروفة الضغط: كل أجهزة المختبر بتفتح /rehearsal وبتطلب «ابدأ» بنفس اللحظة حسب ساعة السيرفر (مش ساعة الجهاز).
المشرف بيفعّلها من المراقبة، وهي مطفية افتراضياً، وبتتفعّل بس على امتحان فاضي (قبل الامتحان الحقيقي)، وبتنطفي لحالها."""
import re, threading, time

import pytest
from conftest import bank
from test_http import Server, H, lan_ip
from test_browser import browser, phone, web, url  # noqa: F401  (fixtures)


@pytest.fixture
def w(pkg):
    s = Server(pkg).start()
    yield s
    s.stop()


def summary(w): return w.get("/monitor.json")[1]["reh"]
def status(w): return w.get("/rehearsal.json")[1]


def sim_device(w, i, out, full=False, skip_at=0):
    """نفس بروتوكول صفحة /rehearsal: تسجيل، قياس فرق الساعة، انتظار الموعد، /start وبعدها تبليغ (واختيارياً حل وتسليم)"""
    dev = f"sim{i}"; r = {"i": i}; out.append(r)
    r["join"] = w.post("/rehearsal/join", {"dev": dev})[1]
    deadline = time.time() + 25
    while time.time() < deadline:
        t0 = time.time(); js = w.get("/rehearsal.json")[1]; t1 = time.time()
        if js["on"] and js["at"] and js["at"] != skip_at:                      # موعد جديد بس (الصفحة الحقيقية بتتجاهل القديم)
            off = js["now"] - (t0 + t1) / 2; target = js["at"] - off           # الموعد بساعة هالجهاز
            break
        time.sleep(0.1)
    else: r["err"] = "no go"; return
    time.sleep(max(0, target - time.time()))
    t = time.time(); st, p, *_ = w.post("/start", {"key": r["join"]["key"], "dev": dev}); ms = int((time.time() - t) * 1000)
    r["start"] = p; w.post("/rehearsal/report", {"dev": dev, "stage": "start", "ok": p.get("status") == "ok", "ms": ms, "status": p.get("status"), "skew": int((time.time() - target) * 1000), "rtt": 3})
    if full and p.get("status") == "ok":
        answers = [0] * len(p["ids"])
        st, s, *_ = w.post("/submit", {"key": r["join"]["key"], "dev": dev, "ids": p["ids"], "answers": ",".join(map(str, answers)), "auto": "بروفة", "leave": "لم يخرج"})
        r["submit"] = s; w.post("/rehearsal/report", {"dev": dev, "stage": "submit", "ok": "score" in (s or {}), "ms": 5, "status": "ok", "skew": 0, "rtt": 3})


def run_round(w, n, secs=3, full=False):
    """n جهاز وهمي بيسجّلوا، والمشرف بيبدأ الجولة، وبنستنى لحد ما يخلصوا"""
    out = []; skip = status(w)["at"]; ths = [threading.Thread(target=sim_device, args=(w, i, out, full, skip)) for i in range(1, n + 1)]
    [t.start() for t in ths]
    end = time.time() + 15
    while time.time() < end and (summary(w) or {}).get("joined", 0) < n: time.sleep(0.1)
    st, j = w.teacher(rehearsal="go", secs=secs, full=full); assert st == 200, j
    [t.join(60) for t in ths]
    return sorted(out, key=lambda r: r["i"])


# ============================ مطفية افتراضياً ومحمية ============================
def test_off_by_default(w):
    assert status(w)["on"] is False and summary(w) is None
    assert w.post("/rehearsal/join", {"dev": "x"})[1] == {"status": "off"}
    assert w.post("/rehearsal/report", {"dev": "x", "stage": "start"})[0] == 400
    st, _, body, _ = w.get("/rehearsal"); assert st == 200 and "بروفة الضغط".encode() in body


def test_only_the_teacher_can_control_it(w):
    assert w.post("/monitor", {"rehearsal": "on"}, H)[0] == 403                       # بدون الترويسة المخصصة
    if lan_ip(): assert w.post("/monitor", {"rehearsal": "on"}, host=lan_ip())[0] == 403            # من جهاز غير السيرفر
    assert status(w)["on"] is False
    assert w.teacher(rehearsal="on")[0] == 200 and status(w)["on"] is True
    assert w.teacher(rehearsal="launch")[0] == 400                                     # أمر غلط


def test_refuses_while_a_real_exam_is_running(w):
    k, _, p = w.start_student("d1")
    st, j = w.teacher(rehearsal="on"); assert st == 400 and "بداية امتحان جديد" in j["error"] and status(w)["on"] is False
    w.teacher(newexam=True)
    assert w.teacher(rehearsal="on")[0] == 200


def test_refuses_with_login_codes_or_closed_exam(pkg):
    pkg.settings(**{"رمز_الدخول": "نعم"}); s = Server(pkg).start()
    try:
        st, j = s.teacher(rehearsal="on"); assert st == 400 and "رمز الدخول" in j["error"]
    finally: s.stop()
    pkg.settings(); s = Server(pkg).start()
    try:
        s.teacher(close=True)
        st, j = s.teacher(rehearsal="on"); assert st == 400 and "مُنهى" in j["error"]
    finally: s.stop()


def test_bad_numbers_are_rejected(w):
    assert w.teacher(rehearsal="on", mins=500)[0] == 400 and w.teacher(rehearsal="on", mins="x")[0] == 400
    w.teacher(rehearsal="on"); w.post("/rehearsal/join", {"dev": "a"})
    assert w.teacher(rehearsal="go", secs=0)[0] == 400 and w.teacher(rehearsal="go", secs=9999)[0] == 400


# ============================ تسجيل الأجهزة ============================
def test_join_gives_distinct_names_in_roster_order_and_is_idempotent(w):
    w.teacher(rehearsal="on")
    js = [w.post("/rehearsal/join", {"dev": f"d{i}"})[1] for i in range(1, 6)]
    assert [j["name"] for j in js] == ["طالب أ1", "طالب أ2", "طالب أ3", "طالب ب1", "طالب ب2"] and [j["n"] for j in js] == [1, 2, 3, 4, 5]
    assert w.post("/rehearsal/join", {"dev": "d2"})[1]["name"] == "طالب أ2"                         # نفس الجهاز: نفس الاسم
    assert w.post("/rehearsal/join", {"dev": "d6"})[1] == {"status": "full"}                      # ما في أسماء زيادة
    assert w.post("/rehearsal/join", {"dev": ""})[0] == 400 and w.post("/rehearsal/join", {"dev": "x" * 65})[0] == 400


def test_join_skips_names_a_real_student_already_took(w):
    w.start_student("real", n="طالب أ1")                                                           # طالب فعلي بدأ قبل ما تتفعّل البروفة
    assert w.teacher(rehearsal="on")[0] == 400                                                      # فبتتعطّل (ما بنخلط بروفة بامتحان)


# ============================ جولة متزامنة ============================
def test_synchronized_round_every_device_starts_in_the_same_moment(w):
    w.teacher(rehearsal="on")
    out = run_round(w, 5, secs=3)
    assert all(r["start"]["status"] == "ok" and len(r["start"]["qs"]) == 8 for r in out)
    s = summary(w)
    assert s["joined"] == 5 and s["ok"] == 5 and s["fail"] == 0 and s["papers"] == 5 and s["reported"] == 5
    assert s["spread_ms"] < 1500 and s["ms_max"] is not None and s["skew_max"] is not None        # وصلت الطلبات خلال ثانية ونص أو أقل
    rows = [r for secs in w.get("/monitor.json")[1]["sections"].values() for r in secs]
    assert sum(1 for r in rows if r["status"] != "none") == 5                                     # الأوراق ظاهرة بالمراقبة زي أي امتحان


def test_each_round_asks_for_new_papers(w):
    w.teacher(rehearsal="on")
    run_round(w, 3, secs=2)
    first = {k: dict(p) for k, p in __import__("json").loads(w.pkg.p("papers.json").read_text(encoding="utf-8")).items()}
    time.sleep(0.3)
    out = []
    skip = status(w)["at"]; ths = [threading.Thread(target=sim_device, args=(w, i, out, False, skip)) for i in range(1, 4)]; [t.start() for t in ths]       # الأجهزة نفسها، جولة ثانية
    time.sleep(0.5)
    st, j = w.teacher(rehearsal="go", secs=2); assert st == 200
    [t.join(40) for t in ths]
    second = __import__("json").loads(w.pkg.p("papers.json").read_text(encoding="utf-8"))
    assert set(second) == set(first) and all(second[k]["start"] > first[k]["start"] for k in first)    # ورقة جديدة وقت جديد، مش استئناف قديمة
    assert summary(w)["ok"] == 3


def test_full_round_answers_and_submits_then_needs_a_new_exam_to_repeat(w):
    w.teacher(rehearsal="on")
    out = run_round(w, 3, secs=2, full=True)
    assert all("score" in r["submit"] for r in out)
    s = summary(w); assert s["submit_ok"] == 3 and s["submit_fail"] == 0 and s["full"] is True
    st, j = w.teacher(rehearsal="go", secs=2); assert st == 400 and "بداية امتحان جديد" in j["error"]
    w.teacher(newexam=True)
    assert summary(w) is None and status(w)["on"] is False                                        # الامتحان الجديد بيصفّر البروفة كمان
    assert w.post("/rehearsal/join", {"dev": "x"})[1] == {"status": "off"}


def test_stopping_frees_the_names_for_the_real_exam(w):
    w.teacher(rehearsal="on")
    run_round(w, 2, secs=2)
    assert w.teacher(rehearsal="off")[0] == 200 and status(w)["on"] is False
    k, _, p = w.start_student("real", n="طالب أ1")                                                 # الاسم رجع متاح للطالب الفعلي
    assert p["status"] == "ok"


def test_rehearsal_switches_itself_off(w):
    assert w.teacher(rehearsal="on", mins=0.05)[0] == 200 and status(w)["on"] is True
    time.sleep(4); assert status(w)["on"] is False
    assert w.post("/rehearsal/join", {"dev": "late"})[1] == {"status": "off"}


def test_server_restart_forgets_the_rehearsal_and_needs_a_clean_exam(pkg):
    s = Server(pkg).start()
    try: s.teacher(rehearsal="on"); run_round(s, 2, secs=2)
    finally: s.stop()
    s = Server(pkg).start()
    try:
        assert status(s)["on"] is False
        st, j = s.teacher(rehearsal="on"); assert st == 400                                        # ورق البروفة لسا بالملفات: لازم امتحان جديد أول
    finally: s.stop()


def test_report_validation(w):
    w.teacher(rehearsal="on"); w.post("/rehearsal/join", {"dev": "a"})
    assert w.post("/rehearsal/report", {"dev": "nobody", "stage": "start"})[0] == 400
    assert w.post("/rehearsal/report", {"dev": "a", "stage": "launch"})[0] == 400
    assert w.post("/rehearsal/report", {"dev": "a", "stage": "start", "ok": 1, "ms": "junk", "skew": 10 ** 12, "status": "y" * 99})[0] == 200
    r = summary(w); assert r["reported"] == 1 and r["ms_avg"] == 0 and r["skew_max"] == 600000


# ============================ بمتصفح حقيقي (ساعات الأجهزة مغلوطة عمداً) ============================
def shifted(page, ms):
    page.add_init_script("(()=>{const n=Date.now.bind(Date);Date.now=()=>n()+(%d)})()" % ms)


def test_browsers_with_wrong_clocks_still_start_together(phone, web):
    web.teacher(rehearsal="on")
    pages = []
    for d in (0, 41000, -23000):                                                                   # ساعات: صح، متقدّمة 41 ث، متأخرة 23 ث
        pg = phone(); shifted(pg, d); pg.goto(url(web) + "rehearsal"); pages.append((pg, d))
    for pg, d in pages: pg.wait_for_function("document.getElementById('who').textContent.includes('جهاز رقم')", timeout=15000)
    assert sorted(re.search(r"جهاز رقم (\d)", pg.inner_text("#who")).group(1) for pg, d in pages) == ["1", "2", "3"]
    pages[0][0].wait_for_timeout(2500)                                                              # كذا قراءة لساعة السيرفر
    for pg, d in pages:
        shown = float(re.search(r"السيرفر: (-?[\d.]+) ث", pg.inner_text("#sync")).group(1))
        assert abs(shown + d / 1000) < 1.5, (d, shown)                                               # كل جهاز عرف فرق ساعته (≈ -الفرق)
    assert web.teacher(rehearsal="go", secs=5)[0] == 200
    for pg, d in pages:
        pg.wait_for_function("document.getElementById('res').textContent.includes('بدء الامتحان')", timeout=25000)
        assert "✓" in pg.inner_text("#res") and "8 سؤال" in pg.inner_text("#res")
    s = summary(web)
    assert s["ok"] == 3 and s["papers"] == 3 and s["spread_ms"] < 2000, s                           # رغم فرق الساعات: وصلوا بنفس الوقت تقريباً
    assert all(not pg.js_errors for pg, d in pages)


def test_browser_full_round_solves_and_submits(phone, web):
    web.teacher(rehearsal="on")
    pages = [phone() for _ in range(2)]
    for pg in pages: pg.goto(url(web) + "rehearsal"); pg.wait_for_function("document.getElementById('who').textContent.includes('جهاز رقم')", timeout=15000)
    assert web.teacher(rehearsal="go", secs=4, full=True)[0] == 200
    for pg in pages:
        pg.wait_for_function("document.getElementById('res').textContent.includes('التسليم')", timeout=60000)
        assert "العلامة" in pg.inner_text("#res") and "خلصت الجولة" in pg.inner_text("#msg")
    s = summary(web); assert s["submit_ok"] == 2 and s["ok"] == 2


def test_monitor_panel_turns_it_on_and_shows_devices(phone, web):
    pg = phone(); pg.on("dialog", lambda d: d.accept())
    pg.goto(url(web) + "monitor"); pg.wait_for_selector("#rehbox")
    pg.click("#rehbox > summary"); assert pg.is_disabled("#rehgo")                                 # ما في بروفة: زر الجولة مقفول
    pg.click("#rehon"); pg.wait_for_function("document.getElementById('rehsum').textContent.includes('شغّالة')", timeout=10000)
    dev = phone(); dev.goto(url(web) + "rehearsal"); dev.wait_for_function("document.getElementById('who').textContent.includes('جهاز رقم')", timeout=15000)
    pg.wait_for_function("document.getElementById('rehsum').textContent.includes('أجهزة مسجّلة: 1')", timeout=12000)
    assert not pg.is_disabled("#rehgo") and pg.is_disabled("#rehon")
    pg.click("#rehgo"); pg.wait_for_function("document.getElementById('rehstat').textContent.includes('بدأوا بنجاح')", timeout=90000)
    assert not pg.js_errors and not dev.js_errors


def test_new_exam_button_stays_unique_on_the_monitor_page(phone, web):
    """اختبارات المراقبة بتدوّر على الزر بنصه «بداية امتحان جديد»: لوحة البروفة ما لازم تكرر هالنص (أول مرة كررته فعلّق e2e على عنصر مخفي)"""
    pg = phone(); pg.goto(url(web) + "monitor"); pg.wait_for_selector("#rehbox")
    assert pg.locator("text=بداية امتحان جديد").count() == 1
    pg.click("#rehbox > summary"); web.teacher(rehearsal="on"); pg.wait_for_function("document.getElementById('rehsum').textContent.includes('شغّالة')", timeout=12000)
    assert pg.locator("text=بداية امتحان جديد").count() == 1
