"""شغلتين طلبهم المشرف:
1) العدّاد بصفحة الطالب بيقلب أحمر لما يضل أقل من دقيقة، وبيرجع عادي لو انضاف وقت.
2) مدة حل كل طالب: من «ابدأ» لـ «تسليم» بساعة السيرفر (مش ساعة جوال الطالب)، بدون وقت توقف السيرفر. بتنكتب بـ submissions.jsonl (dur بالثواني)
   وبتظهر بعمود «مدة الحل» بـ results.csv وexam_report.xlsx، وبورقة الطالب، وبصفحة المراقبة. التسليم عن الطالب وتسليمات ما قبل الميزة: فاضية."""
import csv, io, json, re, time, urllib.parse

import openpyxl
import pytest
from test_http import Server, TEACHER
from test_browser import browser, phone, login  # noqa: F401  (fixtures)


def subs(pkg):
    return {r["name"]: r for r in map(json.loads, pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines())}


def csv_rows(pkg):
    t = list(csv.reader(io.StringIO(pkg.p("results.csv").read_text(encoding="utf-8-sig"))))
    return t[0], {r[3]: r for r in t[1:]}


def monitor_rows(w):
    return {r["name"]: r for s in w.get("/monitor.json")[1]["sections"].values() for r in s}


def cookie(w):
    return w.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0]


def kill(s): s.proc.kill(); s.proc.wait()


@pytest.fixture
def servers():
    made = []
    def start(pkg):
        s = Server(pkg).start(); made.append(s); return s
    yield start
    for s in made: s.stop()


# ============================ التنسيق ============================
@pytest.mark.parametrize("sec, want", [(0, "0 ث"), (45, "45 ث"), (59, "59 ث"), (60, "1 د 00 ث"), (1421, "23 د 41 ث"), (3599, "59 د 59 ث"),
                                       (3600, "1 س 00 د 00 ث"), (3905, "1 س 05 د 05 ث"), (1421.9, "23 د 41 ث"),
                                       (None, ""), (-1, ""), ("12", ""), (True, "")])
def test_fmt_dur(srv, sec, want):
    assert srv.fmt_dur(sec) == want


# ============================ تسجيل المدة ============================
def test_duration_is_recorded_from_start_to_submit(pkg, servers):
    w = servers(pkg)
    k, _, p = w.start_student("d1", n="طالب أ1"); t0 = time.time()
    time.sleep(2.3)
    assert w.submit(k, "d1", p["ids"], w.correct_answers(p["ids"]))[0] == 200
    took = time.time() - t0
    d = subs(pkg)["طالب أ1"]["dur"]
    assert isinstance(d, int) and 2 <= d <= took + 0.5


def test_duration_shows_everywhere_the_teacher_looks(pkg, servers):
    """نحط بداية الطالب قبل 23 دقيقة و41 ثانية (والسيرفر واقف) عشان الرقم يكون محدد"""
    w = servers(pkg)
    ka, _, pa = w.start_student("dA", n="طالب أ1"); w.start_student("dB", n="طالب أ2")
    kill(w); pkg.p("alive.txt").unlink(missing_ok=True)                               # بدون alive.txt ما في تعويض توقف
    P = json.loads(pkg.p("papers.json").read_text(encoding="utf-8")); P[ka]["start"] = time.time() - 1421
    pkg.p("papers.json").write_text(json.dumps(P, ensure_ascii=False), encoding="utf-8")
    w = servers(pkg)
    assert w.submit(ka, "dA", pa["ids"], w.correct_answers(pa["ids"]))[0] == 200
    d = subs(pkg)["طالب أ1"]["dur"]; assert 1421 <= d <= 1432
    txt = f"{d // 60} د {d % 60:02d} ث"; assert txt.startswith("23 د")
    # results.csv: عمود جديد بالآخر، والأعمدة القديمة بمكانها
    head, rows = csv_rows(pkg)
    assert head[-3:] == ["الخروج من الصفحة", "التأخير (ث)", "مدة الحل"] and head[:5] == ["الاختبار", "الصف", "الشعبة", "الاسم", "العلامة"]
    assert rows["طالب أ1"][-1] == txt
    # المراقبة (JSON) وعمودها
    m = monitor_rows(w); assert m["طالب أ1"]["durtxt"] == txt and "durtxt" not in m["طالب أ2"]
    page = w.get("/monitor", {"Cookie": cookie(w)})[2].decode("utf-8"); assert "r.durtxt" in page and "استغرق" in page
    # ورقة الطالب
    ck = cookie(w)
    sheet = w.get("/sheet?key=" + urllib.parse.quote(ka), {"Cookie": ck})[2].decode("utf-8")
    assert "مدة الحل:</b> " + txt in sheet
    # تقرير Excel: آخر عمود بشيت الشعبة
    wb = openpyxl.load_workbook(io.BytesIO(w.get("/report.xlsx", {"Cookie": ck})[2]))
    ws = wb["الشعبة أ"]; table = [[c.value for c in r] for r in ws.iter_rows()]
    assert table[0][-2:] == ["التأخير (ث)", "مدة الحل"]
    got = {r[1]: r[-1] for r in table[1:]}
    assert got["طالب أ1"] == txt and got["طالب أ2"] in (None, "") and got["طالب أ3"] in (None, "")       # اللي ما سلّم: فاضي


def test_server_downtime_is_not_counted_as_solving_time(pkg, servers):
    s1 = servers(pkg)
    k, _, p = s1.start_student("d1", n="طالب أ1")
    time.sleep(4.2)                                                                    # لازم تمرّ نبضة حياة بعد البدء (عشان التعويض يشتغل)
    t0 = time.time(); kill(s1); time.sleep(8)
    s2 = servers(pkg)
    assert s2.submit(k, "d1", p["ids"], s2.correct_answers(p["ids"]))[0] == 200
    wall = time.time() - t0
    P = json.loads(pkg.p("papers.json").read_text(encoding="utf-8")); down = P[k]["down"]
    assert down >= 7 and P[k]["extra"] == down                                         # التعويض اللي بيشتغل أصلاً: زاد الوقت وسجّل مقدار التوقف
    d = subs(pkg)["طالب أ1"]["dur"]
    assert d <= 4.2 + wall - down + 1.5 and d < 4.2 + wall - 6                       # المدة بدون توقف السيرفر (8 ثواني)


def test_teacher_extension_does_not_change_the_duration(pkg, servers):
    w = servers(pkg)
    k, _, p = w.start_student("d1", n="طالب أ1"); w.teacher(extend=10, scope="student", key=k)
    time.sleep(2.2); w.submit(k, "d1", p["ids"], w.correct_answers(p["ids"]))
    assert 2 <= subs(pkg)["طالب أ1"]["dur"] <= 5                                       # التمديد (10 دقائق) وقت إضافي مش وقت استهلكه الطالب


def test_submitted_for_student_and_old_records_have_no_duration(pkg, servers):
    w = servers(pkg)
    ka, _, pa = w.start_student("dA", n="طالب أ1"); kb, _, pb = w.start_student("dB", n="طالب أ2")
    w.submit(ka, "dA", pa["ids"], w.correct_answers(pa["ids"]))
    w.teacher(submitfor=kb)                                                             # المعلم سلّم عن الطالب الثاني
    S = subs(pkg); assert "dur" in S["طالب أ1"] and "dur" not in S["طالب أ2"]
    kill(w)
    lines = [json.loads(l) for l in pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()]
    for r in lines: r.pop("dur", None)                                                  # سجلات قبل الميزة
    pkg.p("submissions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in lines), encoding="utf-8")
    w = servers(pkg)
    head, rows = csv_rows(pkg)                                                          # results.csv بيتولّد من جديد عند التشغيل
    assert rows["طالب أ1"][-1] == "" and rows["طالب أ2"][-1] == ""
    m = monitor_rows(w); assert m["طالب أ1"]["status"] == "done" and m["طالب أ1"]["durtxt"] == ""
    ck = cookie(w)
    for k in (ka, kb):
        assert "مدة الحل" not in w.get("/sheet?key=" + urllib.parse.quote(k), {"Cookie": ck})[2].decode("utf-8")
    assert w.get("/report.xlsx", {"Cookie": ck})[0] == 200


def test_monitor_page_shows_how_long_a_finished_student_took(pkg, servers, browser):
    w = servers(pkg)
    ka, _, pa = w.start_student("dA", n="طالب أ1"); w.start_student("dB", n="طالب أ2")
    time.sleep(2.2); w.submit(ka, "dA", pa["ids"], w.correct_answers(pa["ids"]))
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ar-JO"); page = ctx.new_page(); page.set_default_timeout(8000)
    try:
        page.goto(f"http://127.0.0.1:{w.port}/monitor"); page.wait_for_selector("#cards .card")
        row = lambda n: page.locator("details.sec tr", has_text=n)
        page.wait_for_selector("details.sec tr:has-text('طالب أ1') .score")
        assert row("طالب أ1").inner_text().count("استغرق") == 1 and re.search(r"استغرق [2-4] ث", row("طالب أ1").inner_text())
        assert "استغرق" not in row("طالب أ2").inner_text()                               # اللي لسا يمتحن: الوقت المتبقي مش المدة
    finally:
        ctx.close()


# ============================ العدّاد الأحمر ============================
CLOCK = """()=>{const c=document.getElementById('clock'),s=getComputedStyle(c);return {low:c.classList.contains('low'),bg:s.backgroundColor,fg:s.color,txt:c.textContent}}"""


def set_left(page, ms):
    page.evaluate(f"deadline=Date.now()+{ms}")


def test_clock_turns_red_in_the_last_minute(pkg, phone):
    w = Server(pkg).start()
    try:
        page = phone(); login(page, w)
        page.evaluate("clearInterval(hb)")                                                                        # نبضة السيرفر ما تغيّر الوقت وسط الفحص
        c = page.evaluate(CLOCK)
        assert not c["low"] and c["fg"] == "rgb(255, 255, 255)" and c["bg"] != "rgb(198, 40, 40)"              # أول الامتحان: عادي
        set_left(page, 120_000); page.wait_for_timeout(700); assert not page.evaluate(CLOCK)["low"]               # دقيقتين: عادي
        set_left(page, 61_500); page.wait_for_timeout(700); assert not page.evaluate(CLOCK)["low"]                # فوق الدقيقة بشوي: عادي
        set_left(page, 58_000); page.wait_for_timeout(700)
        c = page.evaluate(CLOCK); assert c["low"] and c["bg"] == "rgb(198, 40, 40)" and c["fg"] == "rgb(255, 255, 255)" and c["txt"].startswith("00:5")   # أقل من دقيقة: أحمر
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
        set_left(page, 300_000); page.wait_for_timeout(700); assert not page.evaluate(CLOCK)["low"]               # المعلم مدّد الوقت: بيرجع عادي
        assert not page.js_errors
    finally:
        w.stop()


def test_clock_is_red_after_reload_inside_the_last_minute(pkg, phone):
    """طالب عمل F5 بآخر دقيقة: الوقت من السيرفر، والعدّاد لازم يطلع أحمر مباشرة"""
    pkg.settings(**{"المدة_بالدقائق": 1}); w = Server(pkg).start()
    try:
        page = phone(); login(page, w)
        page.wait_for_function("document.getElementById('clock').classList.contains('low')", timeout=3000)
        page.reload(); page.wait_for_selector("#s-exam:not(.hide)")
        page.wait_for_function("document.getElementById('clock').classList.contains('low')", timeout=3000)
        assert not page.js_errors
    finally:
        w.stop()
