"""توقف السيرفر وسط الامتحان: نبضة الحياة، تعويض الوقت التلقائي بعد إعادة التشغيل، وإعادة اتصال صفحة الطالب لحالها."""
import json, time

import pytest
from conftest import bank
from test_http import Server

KEY = lambda n="طالب أ1", s="أ": f"اختبار الوحدة|العاشر|{s}|{n}"


def kill(s): s.proc.kill(); s.proc.wait()
def papers(pkg): return json.loads(pkg.p("papers.json").read_text(encoding="utf-8"))
def remain(s, k, dev): return s.post("/ping", {"key": k, "dev": dev})[1]["remain"]
def comp(s): return s.get("/monitor.json")[1]["comp"]


@pytest.fixture
def servers():
    made = []
    def start(pkg, port=None):
        s = Server(pkg); s.start(port=port); made.append(s); return s
    yield start
    for s in made: s.stop()


def exam_with_students(pkg, servers):
    """3 طلاب: A بيمتحن، B سلّم، C منقول (وقته متجمّد). بيرجّع (سيرفر، مفاتيح)"""
    s = servers(pkg)
    kA, _, _ = s.start_student("dA", n="طالب أ1")
    kB, _, pB = s.start_student("dB", n="طالب أ2"); s.submit(kB, "dB", pB["ids"], s.correct_answers(pB["ids"]))
    kC, _, _ = s.start_student("dC", n="طالب أ3"); s.teacher(move=kC)
    time.sleep(4.2)                                                                # لازم تمرّ نبضة بعد البدء
    return s, kA, kB, kC


# ============================ نبضة الحياة ============================
def test_heartbeat_file_is_refreshed_every_few_seconds(pkg, servers):
    servers(pkg)
    t = float(pkg.p("alive.txt").read_text()); assert time.time() - t < 3                        # بتنكتب فوراً عند التشغيل
    time.sleep(4.5); t2 = float(pkg.p("alive.txt").read_text())
    assert t2 > t and time.time() - t2 < 4 and not pkg.p("alive.txt.tmp").exists()


# ============================ التعويض ============================
def test_restart_compensates_only_students_still_taking_the_exam(pkg, servers):
    s1, kA, kB, kC = exam_with_students(pkg, servers)
    r0 = remain(s1, kA, "dA"); t0 = time.time()
    kill(s1); time.sleep(10)
    s2 = servers(pkg)
    r1 = remain(s2, kA, "dA"); elapsed = time.time() - t0
    assert elapsed > 10.5
    assert r0 - r1 < 7, f"خسر {r0 - r1} ثانية من أصل {elapsed:.0f} (بدون تعويض كان رح يخسر كلها)"
    c = comp(s2); assert c["students"] == 1 and 9 <= c["downtime_s"] <= 16 and not c.get("skipped") and not c.get("off")
    P = papers(pkg)
    assert P[kA]["extra"] == c["downtime_s"]
    assert "extra" not in P[kB] and "extra" not in P[kC]                                         # المسلّم والمنقول ما تمسّوا
    assert s2.start_student("dB", n="طالب أ2")[2] == {"status": "done"}


def test_extension_adds_on_top_of_compensation(pkg, servers):
    s1, kA, *_ = exam_with_students(pkg, servers)
    s1.teacher(extend=5, scope="student", key=kA)
    kill(s1); time.sleep(5)
    s2 = servers(pkg); c = comp(s2)
    assert papers(pkg)[kA]["extra"] == 300 + c["downtime_s"]


def test_two_outages_accumulate(pkg, servers):
    s, kA, *_ = exam_with_students(pkg, servers)
    total = 0
    for _ in range(2):
        kill(s); time.sleep(4); s = servers(pkg); total += comp(s)["downtime_s"]; time.sleep(3.5)
    assert papers(pkg)[kA]["extra"] == total and total >= 8


def test_graceful_stop_is_compensated_too(pkg, servers):
    s1, kA, *_ = exam_with_students(pkg, servers)
    s1.proc.terminate(); s1.proc.wait(); time.sleep(5)
    s2 = servers(pkg); assert comp(s2)["students"] == 1


def test_setting_can_turn_compensation_off(pkg, servers):
    pkg.settings(**{"تعويض_توقف_السيرفر": "لا"})
    s1, kA, *_ = exam_with_students(pkg, servers)
    r0 = remain(s1, kA, "dA"); kill(s1); time.sleep(10)
    s2 = servers(pkg); r1 = remain(s2, kA, "dA")
    assert r0 - r1 >= 10 and comp(s2)["off"] is True and comp(s2)["students"] == 0 and "extra" not in papers(pkg)[kA]


def test_very_long_outage_is_not_compensated_automatically(pkg, servers):
    s1, kA, *_ = exam_with_students(pkg, servers)
    s1.proc.terminate(); s1.proc.wait()
    pkg.p("alive.txt").write_text(repr(time.time() - 40 * 60))
    s2 = servers(pkg); c = comp(s2)
    assert c["skipped"] is True and c["students"] == 0 and c["downtime_s"] >= 2390 and "extra" not in papers(pkg)[kA]


def test_student_whose_time_was_already_over_is_not_extended(pkg):
    pkg.settings(**{"المدة_بالدقائق": 0}); s1 = Server(pkg).start()
    try:
        kA, _, p = s1.start_student("dA"); assert p["remain"] == 0
        time.sleep(4.2); kill(s1); time.sleep(4)
        s2 = Server(pkg).start()
        try:
            assert comp(s2)["students"] == 0 and "extra" not in papers(pkg)[kA] and remain(s2, kA, "dA") == 0
        finally:
            s2.stop()
    finally:
        s1.stop()


def test_closed_exam_is_not_extended_by_restart(pkg, servers):
    s1, kA, *_ = exam_with_students(pkg, servers)
    s1.teacher(close=True); time.sleep(3.5)
    kill(s1); time.sleep(4)
    s2 = servers(pkg)
    assert comp(s2)["students"] == 0 and "extra" not in papers(pkg)[kA] and remain(s2, kA, "dA") == 0
    assert s2.get("/monitor.json")[1]["closed"] is True


@pytest.mark.parametrize("content", [None, "garbage", "", "1e999", "-5"])
def test_missing_or_corrupt_heartbeat_file_is_harmless(pkg, servers, content):
    s1, kA, *_ = exam_with_students(pkg, servers)
    s1.proc.terminate(); s1.proc.wait()
    if content is None: pkg.p("alive.txt").unlink()
    else: pkg.p("alive.txt").write_text(content)
    s2 = servers(pkg)
    c = comp(s2)
    assert c is None or c.get("skipped") or c["students"] == 0                                    # ما انهار وما مدّد بالغلط
    assert s2.start_student("dA")[2]["status"] == "ok"


def test_short_blip_under_three_seconds_is_ignored(pkg, servers):
    s1, kA, *_ = exam_with_students(pkg, servers)
    s1.proc.terminate(); s1.proc.wait(); pkg.p("alive.txt").write_text(repr(time.time() - 0.5))
    s2 = servers(pkg); assert comp(s2) is None and "extra" not in papers(pkg)[kA]


def test_no_students_started_means_nothing_to_compensate(pkg, servers):
    s1 = servers(pkg); time.sleep(0.5); s1.proc.terminate(); s1.proc.wait(); time.sleep(4)
    s2 = servers(pkg); assert comp(s2) is None


def test_new_exam_clears_the_compensation_notice(pkg, servers):
    s1, kA, *_ = exam_with_students(pkg, servers)
    kill(s1); time.sleep(4); s2 = servers(pkg)
    assert comp(s2)["students"] == 1
    s2.teacher(newexam=True); assert comp(s2) is None


def test_health_reports_the_compensation(pkg, servers):
    s1, kA, *_ = exam_with_students(pkg, servers)
    kill(s1); time.sleep(4); s2 = servers(pkg)
    d = s2.get("/health.json")[1]; assert d["compensation"]["students"] == 1
    assert "تعويض الوقت بعد التوقف" in s2.get("/health")[2].decode("utf-8")


def test_banner_mentions_compensation(pkg):
    from test_console_mode import Live
    s1 = Live(pkg, force=False); s1.wait_for("To stop: Ctrl+C")
    k, _, _ = s1.web.start_student("dA"); time.sleep(4.2); s1.proc.kill(); s1.proc.wait(); time.sleep(4)
    s2 = Live(pkg, force=False)
    try:
        assert s2.wait_for("To stop: Ctrl+C") and "Downtime compensation: the server was down" in s2.text and "extended 1 student(s)" in s2.text
    finally:
        s2.stop(); s1.stop()
    pkg.p("alive.txt").write_text(repr(time.time() - 5)); s3 = Live(pkg, force=True)
    try:
        assert s3.wait_for("To stop: Ctrl+C") and "Downtime compensation" in s3.text and "extended" in s3.text
    finally:
        s3.stop()


# ============================ المتصفح ============================
def _browser_bits():
    pw = pytest.importorskip("playwright.sync_api")
    from test_browser import browser, phone, url, login, solve, clean               # noqa: F401
    return pw


def test_monitor_shows_the_compensation_notice(pkg, servers):
    pw = _browser_bits(); from test_browser import url
    s1, kA, *_ = exam_with_students(pkg, servers)
    kill(s1); time.sleep(4); s2 = servers(pkg)
    with pw.sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True); pg = b.new_page(viewport={"width": 1280, "height": 800}); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        try:
            pg.goto(url(s2) + "monitor"); pg.wait_for_selector("#compbar", state="visible", timeout=8000)
            t = pg.inner_text("#compbar"); assert "السيرفر كان متوقفاً" in t and "مدّدنا تلقائياً وقت 1 طالب" in t and not errs
            s2.teacher(newexam=True); pg.evaluate("load()"); pg.wait_for_selector("#compbar", state="hidden")
        finally:
            b.close()


def test_student_page_reconnects_by_itself_after_failed_save(pkg, browser_phone=None):
    pw = _browser_bits()
    from test_browser import url, login, solve, clean, launch, phone_ctx, submit
    with pw.sync_playwright() as p:
        b = launch(p)
        ctx = phone_ctx(p, b); page = ctx.new_page(); page.set_default_timeout(25000)
        s1 = Server(pkg).start(); port = s1.port; s2 = None
        try:
            login(page, s1); solve(page); page.wait_for_timeout(2500)
            kill(s1)                                                                      # السيرفر وقع والطالب لسا ما سلّم
            submit(page)
            page.wait_for_function("document.getElementById('status').textContent.includes('تعذّر الحفظ')", timeout=20000)
            assert "لا تسكّر الصفحة" in page.inner_text("#status")
            time.sleep(3); s2 = Server(pkg); s2.start(port=port)                           # رجع السيرفر (تعويض الوقت بيشتغل)
            page.wait_for_selector("#s-exam:not(.hide)", timeout=25000)                    # رجعت لحالها لشاشة الامتحان بدون ما نعمل Refresh
            assert page.eval_on_selector_all("#qs input:checked", "e=>e.length") == 8 and page.inner_text("#clock")[:2] in ("29", "30", "31", "32", "33")
            submit(page); page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
            assert "8 / 8" in clean(page.inner_text("#score"))
        finally:
            ctx.close(); b.close(); (s2 or s1).stop(); s1.stop()
