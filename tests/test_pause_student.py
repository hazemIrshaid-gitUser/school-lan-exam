"""إيقاف مؤقت لطالب من المعلم (مثلاً يروح على الحمّام): شاشته بتتغطّى بدون ما يشوف الأسئلة، ووقته بيتجمّد، وبيرجع بنفس إجاباته لما المعلم يضغط «متابعة».
الاسم والجهاز بيضلوا محجوزين، ومدة الإيقاف ما بتنحسب من مدة الحل ولا بتتعوّض مرتين بعد توقف السيرفر. الأمر بس من المعلم (POST /monitor
مع ترويسة X-Exam-Action، بالمفتاح): {"pause": مفتاح الطالب} و{"resume": مفتاح الطالب}، وصفحة الطالب بتعرف من ردّ ping/resume/start."""
import json, time

import pytest
from test_http import Server, TEACHER
from test_browser import browser, phone, login, url  # noqa: F401  (fixtures + helpers)

pw = pytest.importorskip("playwright.sync_api")
A1, A2 = "طالب أ1", "طالب أ2"


def ping(w, k, dev, **kw):
    body = {"key": k, "dev": dev, "answered": 0, "total": 8, "remain": 1800, "ans": {}}; body.update(kw)
    return w.post("/ping", body)[1]


def rows(w):
    return {r["name"]: r for s in w.get("/monitor.json")[1]["sections"].values() for r in s}


def papers(pkg): return json.loads(pkg.p("papers.json").read_text(encoding="utf-8"))
def subs(pkg): return {r["name"]: r for r in map(json.loads, pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines())}
def kill(s): s.proc.kill(); s.proc.wait()


@pytest.fixture
def servers():
    made = []
    def start(pkg):
        s = Server(pkg).start(); made.append(s); return s
    yield start
    for s in made: s.stop()


# ============================ السيرفر: الوقت والحالة ============================
def test_pause_freezes_the_clock_and_marks_the_student_paused(pkg, servers):
    w = servers(pkg); k, _, p = w.start_student("d1", n=A1); r0 = p["remain"]
    assert ping(w, k, "d1")["paused"] is False and rows(w)[A1].get("paused") is None
    assert w.teacher(pause=k) == (200, {"ok": 1})
    time.sleep(2.4)
    j = ping(w, k, "d1")
    assert j["paused"] is True and r0 - 2 <= j["remain"] <= r0, (r0, j)                    # وقته ما نقص أثناء الإيقاف
    row = rows(w)[A1]; assert row["status"] == "live" and 2 <= row["paused"] <= 5, row     # بالمراقبة: موقوف من كم ثانية (وما اعتُبر منقطع)
    assert "paused" in papers(pkg)[k]                                                        # محفوظ بالملف: ما بيضيع لو وقف السيرفر
    assert w.teacher(resume=k) == (200, {"ok": 1})
    j = ping(w, k, "d1"); assert j["paused"] is False and r0 - 1.5 <= j["remain"] <= r0 + 1, (r0, j)    # الوقت رجع يمشي من حيث وقف
    assert rows(w)[A1].get("paused") is None and "paused" not in papers(pkg)[k]
    time.sleep(1.2); assert ping(w, k, "d1")["remain"] < j["remain"]                       # وبعد المتابعة بيمشي فعلاً


def test_pause_only_applies_to_a_student_who_is_in_the_exam(pkg, servers):
    w = servers(pkg)
    st, j = w.teacher(pause=w.key(n=A1)); assert st == 400 and "error" in j                      # ما بدأ
    k, _, p = w.start_student("d1", n=A1)
    assert w.submit(k, "d1", p["ids"], w.correct_answers(p["ids"]))[0] == 200
    st, j = w.teacher(pause=k); assert st == 400 and "error" in j                                # سلّم
    k2, _, _ = w.start_student("d2", n=A2)
    assert w.teacher(close=True) == (200, {"ok": 1})
    st, j = w.teacher(pause=k2); assert st == 400 and "error" in j                               # الامتحان منتهٍ
    assert w.teacher(resume=k) == (200, {"ok": 1})                                                # متابعة طالب مش موقوف: ما بتأذي


def test_pause_twice_does_not_restart_the_pause_clock(pkg, servers):
    w = servers(pkg); k, _, p = w.start_student("d1", n=A1)
    w.teacher(pause=k); t1 = papers(pkg)[k]["paused"]; time.sleep(1.2); w.teacher(pause=k)
    assert papers(pkg)[k]["paused"] == t1                                                          # ضغطة ثانية ما بتصفّر وقت الإيقاف


def test_the_paused_student_keeps_name_device_and_answers(pkg, servers):
    w = servers(pkg); k, _, p = w.start_student("d1", n=A1)
    qn = str(p["ids"][0]); ping(w, k, "d1", ans={qn: 2}, answered=1)
    w.teacher(pause=k)
    st, j, _, _ = w.post("/resume", {"key": k, "dev": "d1"})                                       # الصفحة انعاد تحميلها أثناء الإيقاف
    assert st == 200 and j["status"] == "ok" and j["paused"] is True and j["ans"] == {qn: 2}, j
    assert w.start_student("d2", n=A1)[2]["status"] == "taken"                                     # جهاز ثاني ما بياخذ اسمه
    st, j, _, _ = w.post("/start", {"key": k, "dev": "d1"}); assert j["status"] == "ok" and j["paused"] is True    # ونفس جهازه بيدخل ويضل موقوف
    w.teacher(resume=k)
    assert w.post("/resume", {"key": k, "dev": "d1"})[1]["paused"] is False


def test_pause_time_is_not_counted_in_the_solving_time(pkg, servers):
    w = servers(pkg); k, _, p = w.start_student("d1", n=A1); t0 = time.time()
    time.sleep(1.0); w.teacher(pause=k); time.sleep(3.2); w.teacher(resume=k); time.sleep(1.0)
    assert w.submit(k, "d1", p["ids"], w.correct_answers(p["ids"]))[0] == 200
    rec = subs(pkg)[A1]; total = time.time() - t0
    assert rec["dur"] <= total - 2.8 and rec["dur"] >= 1, (rec["dur"], total)                      # مدة الحل بدون الإيقاف
    assert 3 <= rec["pause"] <= 4 and rec["late"] == 0, rec                                         # ومدة الإيقاف محفوظة بالتسليم


def test_exam_closed_while_paused_still_accepts_the_submission(pkg, servers):
    """المعلم أنهى الامتحان والطالب موقوف: وقته بيصير صفر وصفحته بتسلّم تلقائياً، والتسليم بيتقبّل ومدة إيقافه ما بتنحسب"""
    w = servers(pkg); k, _, p = w.start_student("d1", n=A1); time.sleep(0.8)
    w.teacher(pause=k); time.sleep(1.6); w.teacher(close=True)
    j = ping(w, k, "d1"); assert j["remain"] == 0 and j["paused"] is True, j
    assert w.submit(k, "d1", p["ids"], w.correct_answers(p["ids"]), auto="انتهى الوقت")[0] == 200
    rec = subs(pkg)[A1]; assert rec["dur"] <= 2 and rec["pause"] >= 1, rec


def test_teacher_submit_for_a_paused_student_closes_the_pause(pkg, servers):
    w = servers(pkg); k, _, p = w.start_student("d1", n=A1); w.teacher(pause=k)
    assert w.teacher(submitfor=k) == (200, {"ok": 1})
    assert rows(w)[A1]["status"] == "done" and rows(w)[A1].get("paused") is None


def test_move_to_another_device_settles_the_pause_first(pkg, servers):
    """النقل بيجمّد الوقت المتبقي؛ لو كان موقوف بنثبّت الإيقاف أولاً عشان الوقت اللي بيرجع له يكون صحيح"""
    w = servers(pkg); k, _, p = w.start_student("d1", n=A1); r0 = p["remain"]
    w.teacher(pause=k); time.sleep(1.8); assert w.teacher(move=k) == (200, {"ok": 1})
    st, j, _, _ = w.post("/start", {"key": k, "dev": "d9"})
    assert st == 200 and j["status"] == "ok" and j["paused"] is False and r0 - 1.5 <= j["remain"] <= r0 + 1, (r0, j)
    time.sleep(1.3); assert ping(w, k, "d9")["remain"] < j["remain"]                                 # وبعد النقل الوقت بيمشي طبيعي


def test_extend_time_while_paused_is_kept(pkg, servers):
    w = servers(pkg); k, _, p = w.start_student("d1", n=A1); r0 = p["remain"]
    w.teacher(pause=k); assert w.teacher(extend=5, scope="student", key=k)[0] == 200
    assert 5 * 60 + r0 - 3 <= ping(w, k, "d1")["remain"] <= 5 * 60 + r0 + 1


def test_restart_while_paused_stays_paused_and_is_not_compensated_twice(pkg, servers):
    """السيرفر وقف وهو شغّال والطالب موقوف: بعد التشغيل بيضل موقوف ووقته بدون تغيير (وقته متجمّد أصلاً)، والتعويض بس للطلاب اللي وقتهم كان ماشي"""
    w = servers(pkg); k1, _, p1 = w.start_student("d1", n=A1); k2, _, _ = w.start_student("d2", n=A2)
    w.teacher(pause=k1); r1 = ping(w, k1, "d1")["remain"]; time.sleep(3.5)                         # ≥ 3 ثواني عشان التعويض يشتغل
    kill(w); time.sleep(3.5)
    w = servers(pkg); j = w.post("/resume", {"key": k1, "dev": "d1"})[1]
    assert j["paused"] is True and r1 - 2 <= j["remain"] <= r1 + 1, (r1, j)
    comp = w.get("/monitor.json")[1]["comp"]; assert comp and comp["students"] == 1, comp            # التعويض للطالب الشغّال بس
    assert rows(w)[A1]["paused"] >= 7


# ============================ صفحة الطالب ============================
def covered(page):
    """true لو أي نقطة بالشاشة (فوق، نص، تحت) بيلمسها المستخدم هي شاشة الإيقاف مش الأسئلة"""
    return page.evaluate("""()=>[[.5,.1],[.5,.5],[.5,.9],[.1,.5],[.9,.5]].every(([x,y])=>{
        const e=document.elementFromPoint(innerWidth*x,innerHeight*y);return !!e&&!!e.closest('#pause')})""")


def clock(page): return page.inner_text("#clock")


def test_student_screen_is_covered_while_paused_and_resumes_with_the_same_answers(phone, pkg, servers):
    w = servers(pkg); page = phone(); login(page, w, name=A1)
    opt = page.locator("#qs .card").first.locator("label.opt").nth(2); opt.click()
    page.wait_for_timeout(2000)                                                                      # الإجابة وصلت السيرفر (نبضة بعد تغيير الإجابة)
    k = w.key(n=A1); assert page.locator("#pause").is_hidden() and page.locator("#s-exam").evaluate("e=>!e.inert")
    assert w.teacher(pause=k)[0] == 200
    page.wait_for_selector("#pause:not(.hide)", timeout=12000)                                       # أول نبضة (حتى 8 ثواني)
    assert "موقوف" in page.inner_text("#pause") and covered(page)
    assert page.evaluate("document.getElementById('s-exam').inert===true")                          # ولا يقدر يصل للأسئلة بالكيبورد
    c1 = clock(page); page.wait_for_timeout(2300); assert clock(page) == c1, "الساعة لازم تضل متجمّدة"
    n0 = page.evaluate("leaveN"); page.evaluate("leaveStart(); leaveEnd()")
    assert page.evaluate("leaveN") == n0                                                             # خروجه من الصفحة وهو موقوف ما بينعدّ عليه
    assert w.teacher(resume=k)[0] == 200
    page.wait_for_selector("#pause.hide", state="attached", timeout=8000)
    assert page.locator("#pause").is_hidden() and page.evaluate("!document.getElementById('s-exam').inert")
    assert opt.locator("input").is_checked()                                                         # نفس إجابته
    c2 = clock(page); page.wait_for_timeout(2300); assert clock(page) != c2                          # والساعة رجعت تمشي
    assert not page.js_errors


def test_reload_while_paused_shows_the_cover_again_and_keeps_answers(phone, pkg, servers):
    w = servers(pkg); page = phone(); login(page, w, name=A1)
    opt = page.locator("#qs .card").first.locator("label.opt").nth(1); opt.click(); page.wait_for_timeout(2000)
    k = w.key(n=A1); w.teacher(pause=k); page.wait_for_selector("#pause:not(.hide)", timeout=12000)
    page.route("**/ping", lambda r: r.abort())                                                       # بدون نبضة: التغطية لازم تجي من ردّ /resume نفسه (ما في لحظة بتنكشف فيها الأسئلة)
    page.reload(); page.wait_for_selector("#s-exam:not(.hide)")
    page.wait_for_selector("#pause:not(.hide)", timeout=3000); assert covered(page)                  # ما بتنفتح الأسئلة بإعادة التحميل
    assert 0 < int(clock(page).split(":")[0]) <= 30
    page.unroute("**/ping"); w.teacher(resume=k); page.wait_for_selector("#pause.hide", state="attached", timeout=8000)
    assert page.locator("#qs .card").first.locator("label.opt").nth(1).locator("input").is_checked()


def test_closing_the_exam_while_paused_submits_the_page_automatically(phone, pkg, servers):
    w = servers(pkg); page = phone(); login(page, w, name=A1); page.locator("#qs .card").first.locator("label.opt").first.click()
    k = w.key(n=A1); w.teacher(pause=k); page.wait_for_selector("#pause:not(.hide)", timeout=12000)
    w.teacher(close=True)
    page.wait_for_selector("#s-done:not(.hide)", timeout=12000)
    assert page.locator("#pause").is_hidden()                                                       # الشاشة ما بتغطي نتيجته
    page.wait_for_function("document.getElementById('status').textContent.includes('✓')", timeout=8000)
    assert subs(pkg)[A1]["auto"] == "انتهى الوقت" and not page.js_errors


def test_cover_fits_the_phone_and_does_not_scroll(phone, pkg, servers):
    w = servers(pkg); page = phone(); login(page, w, name=A1)
    w.teacher(pause=w.key(n=A1)); page.wait_for_selector("#pause:not(.hide)", timeout=12000)
    box = page.locator("#pause").bounding_box(); vw, vh = page.evaluate("[innerWidth, innerHeight]")
    assert box["x"] <= 0 and box["y"] <= 0 and box["width"] >= vw - 1 and box["height"] >= vh - 1
    assert page.evaluate("document.body.style.overflow") == "hidden"
    assert page.evaluate("getComputedStyle(document.getElementById('pause')).backgroundColor").startswith("rgb(")     # خلفية معتمة تماماً: الأسئلة ما بتبين من وراها


# ============================ شاشة المراقبة الجديدة ============================
def monitor_pkg(pkg):
    from test_monitor_new_ui import with_ui
    with_ui(pkg)


def keepalive(w, k, dev):
    import threading
    stop = threading.Event()
    def run():
        while not stop.is_set():
            try: ping(w, k, dev)
            except Exception: pass
            stop.wait(2.5)
    t = threading.Thread(target=run, daemon=True); t.start()
    return stop


def test_new_monitor_pause_and_resume_from_the_row_menu(pkg, servers, browser):
    from test_monitor_new_ui import Ui, wait_for
    monitor_pkg(pkg); w = servers(pkg); k, _, p = w.start_student("d1", n=A1); stop = keepalive(w, k, "d1")
    ui = Ui(browser, w); pg = ui.pg
    try:
        row = ui.row(A1); n0 = len(ui.posts)
        row.locator("button.kebab").click()
        assert pg.locator(".row-popup").get_by_text("⏸ إيقاف مؤقت", exact=True).count() == 1 and pg.locator(".row-popup").get_by_text("▶ متابعة").count() == 0
        pg.locator(".row-popup").get_by_text("⏸ إيقاف مؤقت", exact=True).click()
        hdr, body = ui.posts[n0]; assert hdr == "1" and body == {"pause": k}, body                   # بدون نافذة تأكيد: أمر مباشر وقابل للعكس
        wait_for(lambda: "paused" in (rows(w).get(A1) or {}), 8, "server paused")
        pg.wait_for_function("(n)=>[...document.querySelectorAll('tbody tr')].find(r=>r.textContent.includes(n)).textContent.includes('موقوف')", arg=A1, timeout=9000)
        txt = row.inner_text(); assert "⏸ موقوف" in txt and "منذ" in txt and "يمتحن" not in txt, txt
        t1 = row.locator(".time-left").inner_text(); pg.wait_for_timeout(2200)
        assert row.locator(".time-left").inner_text() == t1                                           # الوقت المتبقي متجمّد بالجدول كمان
        assert "low" not in (row.locator(".time-left").get_attribute("class") or "")
        row.locator("button.kebab").click(); assert pg.locator(".row-popup").get_by_text("⏸ إيقاف مؤقت").count() == 0   # القائمة صارت «متابعة»
        pg.locator(".row-popup").get_by_text("▶ متابعة", exact=True).click(); pg.wait_for_timeout(300)
        assert ui.posts[-1][1] == {"resume": k}
        wait_for(lambda: "paused" not in rows(w)[A1], 8, "server resumed")
        pg.wait_for_function("(n)=>!([...document.querySelectorAll('tbody tr')].find(r=>r.textContent.includes(n)).textContent.includes('موقوف'))", arg=A1, timeout=9000)
        assert "يمتحن" in row.inner_text() and not ui.errors
    finally:
        stop.set(); ui.close()


def test_new_monitor_reminds_the_teacher_about_a_long_pause_and_resumes_from_there(pkg, servers, browser):
    from test_monitor_new_ui import Ui, wait_for
    monitor_pkg(pkg); w = servers(pkg); k, _, p = w.start_student("d1", n=A1)
    w.teacher(pause=k); kill(w)
    P = papers(pkg); P[k]["paused"] -= 200; pkg.p("papers.json").write_text(json.dumps(P, ensure_ascii=False), encoding="utf-8")        # موقوف من 200 ثانية
    w = servers(pkg); stop = keepalive(w, k, "d1"); ui = Ui(browser, w); pg = ui.pg
    try:
        att = pg.locator("section.attention"); att.wait_for(timeout=9000)
        pg.wait_for_function("document.querySelector('section.attention')?.textContent.includes('موقوف مؤقتاً منذ')", timeout=9000)
        assert A1 in att.inner_text() and "03:" in att.inner_text(), att.inner_text()                  # 200 ثانية = 03:20 تقريباً
        att.get_by_role("button", name="▶ متابعة").first.click()
        wait_for(lambda: "paused" not in rows(w)[A1], 8, "resumed from the attention card")
        pg.wait_for_function("document.querySelector('section.attention')===null", timeout=9000)
        j = ping(w, k, "d1"); assert j["paused"] is False and j["remain"] > 1500 and not ui.errors      # الـ 200 ثانية ما انحسبت من وقته
    finally:
        stop.set(); ui.close()
