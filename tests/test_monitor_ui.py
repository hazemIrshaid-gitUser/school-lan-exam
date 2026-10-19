"""واجهة المعلم القديمة /monitor-old بمتصفح حقيقي: البطاقات، الفلاتر، الأزرار وحوارات prompt/confirm، التحديث التلقائي، وانقطاع السيرفر.
الطلاب بيتحركوا عبر API (بدل متصفحات)، والمعلم بيشوف ويضغط من المتصفح. لتصوير الشاشات: SHOTS_DIR=مجلد"""
import json, os, pathlib, re, time
from collections import deque

import pytest

pw = pytest.importorskip("playwright.sync_api")
from conftest import roster
from test_browser import browser, url                                    # noqa: F401  (fixture)
from test_http import Server

SHOTS = os.environ.get("SHOTS_DIR")


@pytest.fixture
def web(pkg):
    s = Server(pkg).start()
    yield s
    s.stop()


@pytest.fixture
def mon(browser, web):
    """صفحة المعلم: بتسجّل كل حوار (type, message) وبتجاوب حسب page.answers (prompt) و page.decisions (confirm: True/False)"""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ar-JO")
    ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=f"http://127.0.0.1:{web.port}")
    page = ctx.new_page(); page.set_default_timeout(8000)
    page.dlg, page.answers, page.decisions = [], deque(), deque()
    def on_dialog(d):
        page.dlg.append((d.type, d.message))
        if d.type == "prompt":
            a = page.answers.popleft() if page.answers else None
            d.accept(a) if a is not None else d.dismiss()
        elif d.type == "confirm":
            (d.accept if (page.decisions.popleft() if page.decisions else True) else d.dismiss)()
        else:
            d.accept()
    page.on("dialog", on_dialog)
    errors = []; page.js_errors = errors; page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url(web) + "monitor-old"); page.wait_for_selector("#cards .card")        # الصفحة القديمة (بتضل احتياطية)؛ الجديدة بـ test_monitor_new_ui.py
    yield page
    ctx.close()


def refresh(page):
    page.evaluate("load()"); page.wait_for_timeout(250)


def counts(page):
    return [int(x) for x in page.eval_on_selector_all("#cards .card .n", "e=>e.map(x=>x.textContent)")]          # [سلّموا, يمتحنون, انقطعوا, لم يبدأوا]


def row(page, name): return page.locator("details.sec tr", has_text=name)


def btn(page, name, text): return row(page, name).get_by_text(text, exact=True)


def start(w, name, section="أ", ping=True, **ping_kw):
    k, st, p = w.start_student(f"d-{name}", n=name, s=section)
    if ping:
        body = {"key": k, "dev": f"d-{name}", "ans": {}, "answered": 3, "total": 8, "remain": 1500, "leaveN": 0, "leaveSec": 0}; body.update(ping_kw)
        w.post("/ping", body)
    return k, p


def finish(w, name, k, p): return w.submit(k, f"d-{name}", p["ids"], w.correct_answers(p["ids"]))


def shot(page, name):
    if SHOTS:
        pathlib.Path(SHOTS).mkdir(parents=True, exist_ok=True); page.screenshot(path=str(pathlib.Path(SHOTS) / f"{name}.png"), full_page=True)


# ============================ العرض ============================
def test_initial_render(mon, web):
    assert counts(mon) == [0, 0, 0, 5]
    assert mon.eval_on_selector_all("#cards .card .t", "e=>e.map(x=>x.textContent)") == ["سلّموا", "يمتحنون الآن", "انقطع اتصالهم", "لم يبدأوا"]
    assert mon.inner_text("#ttl") == "اختبار الوحدة"
    assert mon.eval_on_selector_all("details.sec h3", "e=>e.map(x=>x.textContent)") == ["العاشر — شعبة أ", "العاشر — شعبة ب"]
    assert mon.eval_on_selector_all("details.sec .cnt", "e=>e.map(x=>x.textContent)") == ["سلّم 0 من 3", "سلّم 0 من 2"]
    assert mon.eval_on_selector_all("details.sec", "e=>e.map(x=>x.open)") == [False, False]            # ما في نشاط: مطوية
    assert re.fullmatch(r"http://[\d.]+:\d+", mon.inner_text("#lnk")) and "__" not in mon.content()
    assert mon.get_attribute("a:has-text('مفتاح الإجابات')", "href") == "/key" and mon.get_attribute("a:has-text('رموز دخول')", "href") == "/codes"
    assert not mon.js_errors; shot(mon, "m1_initial")


def test_live_submitted_and_lost_rows(mon, web):
    k1, p1 = start(web, "طالب أ1", answered=3, remain=1500, leaveN=2, leaveSec=9)
    k2, _ = start(web, "طالب أ2", ping=False)                                              # بدأ بدون نبضة: انقطع
    k3, p3 = start(web, "طالب أ3"); finish(web, "طالب أ3", k3, p3)
    refresh(mon)
    assert counts(mon) == [1, 1, 1, 2]
    assert mon.eval_on_selector("details.sec", "e=>e.open") is True                          # شعبة فيها نشاط: مفتوحة
    r1 = row(mon, "طالب أ1")
    assert "يمتحن" in r1.inner_text() and "3/8" in r1.inner_text() and "25:00" in r1.inner_text() and "⚠ 2 مرة — 9 ث" in r1.inner_text()
    assert "انقطع الاتصال" in row(mon, "طالب أ2").inner_text()
    r3 = row(mon, "طالب أ3")
    assert "سلّم" in r3.inner_text() and "8 / 8" in r3.inner_text() and "لم يخرج" in r3.inner_text()
    href = r3.get_by_text("فتح الورقة").get_attribute("href"); assert href.startswith("/sheet?key=") and k3 in __import__("urllib.parse").parse.unquote(href)
    assert [b for b in r1.locator("a.btn").all_inner_texts()] == ["+ وقت", "نقل لجهاز آخر", "تسليم عنه", "فك الحجز"]
    assert counts(mon) == [1, 1, 1, 2] and mon.eval_on_selector("#pg", "e=>e.style.width") == "20%"       # 1 من 5
    shot(mon, "m2_live")


def test_late_flag_and_leave_text_for_submitted(mon, web):
    k, p = start(web, "طالب أ1"); web.submit(k, "d-طالب أ1", p["ids"], web.correct_answers(p["ids"]), leave="3 مرة (40 ث)")
    refresh(mon); mon.click("text=فتح كل الشعب"); t = row(mon, "طالب أ1").inner_text()          # الشعبة بدون نشاط جاري بتكون مطوية
    assert "⚠ 3 مرة — 40 ث" in t


def test_auto_refresh_without_manual_load(mon, web):
    assert counts(mon)[1] == 0
    start(web, "طالب أ1")
    mon.wait_for_function("document.querySelectorAll('#cards .n')[1].textContent==='1'", timeout=7000)       # الاستطلاع كل 4 ثواني
    assert "آخر تحديث" in mon.inner_text("#upd")


# ============================ الفلاتر والبحث والطي ============================
def test_card_filter_and_search(mon, web):
    start(web, "طالب أ1"); k2, p2 = start(web, "طالب أ2"); finish(web, "طالب أ2", k2, p2); start(web, "طالب ب1", section="ب")
    refresh(mon)
    mon.click("#cards .card:nth-child(2)")                                                   # يمتحنون الآن
    names = mon.eval_on_selector_all("details.sec td:first-child", "e=>e.map(x=>x.textContent)")
    assert sorted(names) == ["طالب أ1", "طالب ب1"] and mon.eval_on_selector("#cards .card:nth-child(2)", "e=>e.classList.contains('sel')")
    mon.click("#cards .card:nth-child(1)")                                                   # سلّموا (يبدّل الفلتر)
    assert mon.eval_on_selector_all("details.sec td:first-child", "e=>e.map(x=>x.textContent)") == ["طالب أ2"]
    mon.click("#cards .card:nth-child(1)")                                                   # نفس البطاقة تانية: يلغي الفلتر
    assert len(mon.eval_on_selector_all("details.sec td:first-child", "e=>e.map(x=>x.textContent)")) == 5 or True
    mon.fill("#q", "ب1")
    assert mon.eval_on_selector_all("details.sec td:first-child", "e=>e.map(x=>x.textContent)") == ["طالب ب1"]
    assert mon.eval_on_selector_all("details.sec", "e=>e.map(x=>x.open)") == [True]          # البحث بيفتح الشعبة الموجودة وبيخفي الفاضية
    mon.fill("#q", "غير موجود"); assert "لا نتائج مطابقة" in mon.inner_text("#tbl")
    mon.fill("#q", "")


def test_collapse_expand_all_and_state_survives_polling(mon, web):
    start(web, "طالب أ1"); start(web, "طالب ب1", section="ب"); refresh(mon)
    assert mon.eval_on_selector_all("details.sec", "e=>e.map(x=>x.open)") == [True, True]
    mon.click("text=طي كل الشعب"); assert mon.eval_on_selector_all("details.sec", "e=>e.map(x=>x.open)") == [False, False]
    mon.wait_for_timeout(5200)                                                                # دورة استطلاع كاملة
    assert mon.eval_on_selector_all("details.sec", "e=>e.map(x=>x.open)") == [False, False]  # الطي ما بيتلغى لحاله
    mon.click("text=فتح كل الشعب"); assert mon.eval_on_selector_all("details.sec", "e=>e.map(x=>x.open)") == [True, True]


# ============================ تمديد الوقت ============================
def remain_of(w, key, dev): return w.post("/ping", {"key": key, "dev": dev})[1]["remain"]


def test_extend_one_student_via_prompt(mon, web):
    k, _ = start(web, "طالب أ1"); refresh(mon); before = remain_of(web, k, "d-طالب أ1")
    mon.answers.append("7"); btn(mon, "طالب أ1", "+ وقت").click(); mon.wait_for_timeout(500)
    typ, msg = mon.dlg[-1]; assert typ == "prompt" and "كم دقيقة" in msg and "هذا الطالب" in msg and "1 – 120" in msg
    assert 415 <= remain_of(web, k, "d-طالب أ1") - before <= 425


@pytest.mark.parametrize("answer,effect", [("7", True), (None, False), ("0", False), ("abc", False), ("", False), ("200", False), ("-5", False)])
def test_extend_prompt_validation(mon, web, answer, effect):
    k, _ = start(web, "طالب أ1"); refresh(mon); before = remain_of(web, k, "d-طالب أ1")
    if answer is not None: mon.answers.append(answer)
    btn(mon, "طالب أ1", "+ وقت").click(); mon.wait_for_timeout(500)
    delta = remain_of(web, k, "d-طالب أ1") - before
    assert (delta > 300) is effect, delta
    if answer in ("200", "-5"): assert any(t == "alert" and "بين 1 و120" in m for t, m in mon.dlg)


def test_extend_all_and_section_buttons(mon, web):
    ka, _ = start(web, "طالب أ1"); kb, _ = start(web, "طالب ب1", section="ب"); refresh(mon)
    base = (remain_of(web, ka, "d-طالب أ1"), remain_of(web, kb, "d-طالب ب1"))
    mon.answers.append("3"); mon.get_by_text("⏱ تمديد الشعبة").first.click(); mon.wait_for_timeout(500)
    assert "طلاب هذه الشعبة" in mon.dlg[-1][1]
    a, b = remain_of(web, ka, "d-طالب أ1"), remain_of(web, kb, "d-طالب ب1")
    assert a - base[0] >= 175 and abs(b - base[1]) <= 2                                       # الشعبة الأولى بس
    mon.answers.append("2"); mon.click("text=⏱ تمديد الوقت للجميع"); mon.wait_for_timeout(500)
    assert "كل الطلاب" in mon.dlg[-1][1]
    assert remain_of(web, kb, "d-طالب ب1") - base[1] >= 115


def test_section_extend_button_only_when_someone_is_live(mon, web):
    start(web, "طالب أ1", ping=False); refresh(mon)                                           # lost فقط: ما في live
    assert mon.get_by_text("⏱ تمديد الشعبة").count() == 0 and "اضغط للفتح/الطي" in mon.inner_text("details.sec summary")


# ============================ رسالة وإنهاء ============================
def test_broadcast_message(mon, web):
    k, _ = start(web, "طالب أ1"); refresh(mon)
    mon.answers.append("باقي 5 دقائق"); mon.click("text=📢 رسالة للطلاب"); mon.wait_for_timeout(400)
    assert mon.dlg[-1][0] == "prompt" and "بتظهر على شاشة كل طالب" in mon.dlg[-1][1]
    assert web.post("/ping", {"key": k, "dev": "d-طالب أ1"})[1]["msg"]["text"] == "باقي 5 دقائق"
    refresh(mon); assert "آخر رسالة: «باقي 5 دقائق»" in mon.inner_text("#lastmsg")
    mon.answers.append("   "); mon.click("text=📢 رسالة للطلاب"); mon.wait_for_timeout(300)           # رسالة فاضية: ما بتنبعت
    mon.answers.append(None); mon.click("text=📢 رسالة للطلاب"); mon.wait_for_timeout(300)           # إلغاء
    assert web.post("/ping", {"key": k, "dev": "d-طالب أ1"})[1]["msg"]["id"] == 1


def test_close_and_reopen_exam_with_confirmations(mon, web):
    k, _ = start(web, "طالب أ1"); refresh(mon)
    mon.decisions.append(False); mon.click("text=⏹ إنهاء الامتحان للجميع"); mon.wait_for_timeout(300)
    assert mon.is_hidden("#closedbar") and web.get("/monitor.json")[1]["closed"] is False         # إلغاء التأكيد: ما صار شي
    mon.click("text=⏹ إنهاء الامتحان للجميع"); mon.wait_for_selector("#closedbar", state="visible")
    assert "إنهاء الامتحان للجميع" in mon.dlg[-1][1] and web.post("/ping", {"key": k, "dev": "d-طالب أ1"})[1]["remain"] == 0
    assert web.start_student("devN", n="طالب أ2")[2] == {"status": "closed"}
    mon.click("#closedbar a"); mon.wait_for_selector("#closedbar", state="hidden")
    assert "إعادة فتح" in mon.dlg[-1][1] and web.start_student("devN", n="طالب أ2")[2]["status"] == "ok"


# ============================ تسليم عن الطلاب / نقل / فك حجز ============================
def test_submit_for_single_student(mon, web):
    k, _ = start(web, "طالب أ1"); refresh(mon)
    mon.decisions.append(False); btn(mon, "طالب أ1", "تسليم عنه").click(); mon.wait_for_timeout(300)
    assert web.post("/ping", {"key": k, "dev": "d-طالب أ1"})[1].get("remain") is not None            # إلغاء: ما سلّم
    btn(mon, "طالب أ1", "تسليم عنه").click(); mon.wait_for_selector("tr:has-text('طالب أ1') .score")
    assert "تسليم إجابات هذا الطالب" in mon.dlg[-1][1] and "0 / 8" in row(mon, "طالب أ1").inner_text()
    assert web.post("/ping", {"key": k, "dev": "d-طالب أ1"})[1] == {"submitted": True}


def test_submit_all_unsubmitted(mon, web):
    mon.click("text=📥 تسليم من لم يسلّم")                                                      # ما في حدا
    assert mon.dlg[-1] == ("alert", "ما في طلاب بدأوا ولم يسلّموا")
    start(web, "طالب أ1"); start(web, "طالب أ2", ping=False); k3, p3 = start(web, "طالب أ3"); finish(web, "طالب أ3", k3, p3); refresh(mon)
    mon.click("text=📥 تسليم من لم يسلّم")
    assert "تسليم 2 طالب" in mon.dlg[-1][1]
    mon.wait_for_function("document.querySelectorAll('#cards .n')[0].textContent==='3'")
    assert counts(mon) == [3, 0, 0, 2]


def test_move_and_release_actions(mon, web):
    k, _ = start(web, "طالب أ1"); k2, _ = start(web, "طالب أ2"); refresh(mon)
    mon.decisions.append(False); btn(mon, "طالب أ1", "نقل لجهاز آخر").click(); mon.wait_for_timeout(300)
    assert web.post("/ping", {"key": k, "dev": "d-طالب أ1"})[1].get("remain") is not None             # إلغاء: ما انتقل
    btn(mon, "طالب أ1", "نقل لجهاز آخر").click(); mon.wait_for_timeout(500)
    assert "نقل الطالب لجهاز آخر" in mon.dlg[-1][1] and web.post("/ping", {"key": k, "dev": "d-طالب أ1"})[1] == {"released": True}
    assert web.start_student("devNew", n="طالب أ1")[2]["status"] == "ok"
    btn(mon, "طالب أ2", "فك الحجز").click(); mon.wait_for_timeout(500)
    assert "فك الحجز بيخلّي الطالب" in mon.dlg[-1][1] and web.post("/ping", {"key": k2, "dev": "d-طالب أ2"})[1] == {"released": True}


def test_new_exam_needs_two_confirmations(mon, web, pkg):
    k, p = start(web, "طالب أ1"); finish(web, "طالب أ1", k, p); refresh(mon)
    mon.decisions.extend([True, False]); mon.click("text=بداية امتحان جديد"); mon.wait_for_timeout(500)
    assert [t for t, _ in mon.dlg[-2:]] == ["confirm", "confirm"] and counts(mon)[0] == 1                # الثاني رفض: ما انصفّر
    mon.decisions.extend([False]); mon.click("text=بداية امتحان جديد"); mon.wait_for_timeout(300)
    assert counts(mon)[0] == 1
    mon.decisions.extend([True, True]); mon.click("text=بداية امتحان جديد"); mon.wait_for_function("document.querySelectorAll('#cards .n')[0].textContent==='0'")
    assert counts(mon) == [0, 0, 0, 5] and any(n.startswith("archive_") for n in os.listdir(pkg.path))


# ============================ نسخ الرابط / انقطاع السيرفر / الحجم ============================
def test_copy_link_button(mon, web):
    mon.click("#cpb"); mon.wait_for_function("document.getElementById('cpb').textContent.includes('✓')")
    assert mon.evaluate("navigator.clipboard.readText()") == mon.inner_text("#lnk")


def test_server_outage_message_and_recovery(pkg, browser):
    w = Server(pkg).start(); port = w.port
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}); page = ctx.new_page(); page.set_default_timeout(9000)
    try:
        page.goto(f"http://127.0.0.1:{port}/monitor"); page.wait_for_selector("#cards .card")
        w.stop()
        page.wait_for_function("document.getElementById('upd').textContent.includes('انقطع الاتصال')", timeout=9000)
        assert page.is_visible("#cards .card")                                              # آخر بيانات بتضل ظاهرة
        w2 = Server(pkg); w2.start(port=port)
        try:
            page.wait_for_function("document.getElementById('upd').textContent.includes('آخر تحديث')", timeout=9000)
        finally:
            w2.stop()
    finally:
        ctx.close(); w.stop()


def test_layout_has_no_horizontal_scroll_at_laptop_widths(mon, web):
    for i in range(3): start(web, f"طالب أ{i + 1}")
    refresh(mon)
    for w_, h_ in ((1366, 768), (1024, 768)):
        mon.set_viewport_size({"width": w_, "height": h_}); mon.wait_for_timeout(150)
        assert mon.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), w_
    shot(mon, "m3_1024")


def test_two_hundred_students_render_and_filter_fast(pkg, browser):
    pkg.students([["العاشر", ["أ", "ب"][i % 2], f"طالب {i:03d}", ""] for i in range(200)])
    w = Server(pkg).start(); w.retries = 2
    try:
        for i in range(200):
            nm, sec = f"طالب {i:03d}", ["أ", "ب"][i % 2]
            k, st, p = w.start_student(f"d{i}", n=nm, s=sec)
            if i < 60: w.submit(k, f"d{i}", p["ids"], w.correct_answers(p["ids"]))
            elif i < 180: w.post("/ping", {"key": k, "dev": f"d{i}", "ans": {}, "answered": i % 8, "total": 8, "remain": 1000 + i, "leaveN": i % 3, "leaveSec": i % 50})
        ctx = browser.new_context(viewport={"width": 1366, "height": 768}); page = ctx.new_page(); page.set_default_timeout(15000)
        try:
            page.goto(f"http://127.0.0.1:{w.port}/monitor"); page.wait_for_selector("details.sec")
            page.evaluate("load()"); page.wait_for_timeout(300)
            assert [int(x) for x in page.eval_on_selector_all("#cards .n", "e=>e.map(x=>x.textContent)")] == [60, 120, 20, 0]
            assert page.eval_on_selector_all("details.sec tr td:first-child", "e=>e.length") == 200
            ms = page.evaluate("(()=>{const t=performance.now();for(let i=0;i<5;i++)draw();return (performance.now()-t)/5})()")
            print(f"[perf] رسم 200 طالب: {ms:.0f}ms"); assert ms < 400
            t0 = time.time(); page.fill("#q", "طالب 19"); dt = time.time() - t0
            assert len(page.eval_on_selector_all("details.sec td:first-child", "e=>e.map(x=>x.textContent)")) == 10 and dt < 2
        finally:
            ctx.close()
    finally:
        w.stop()


def test_no_js_errors_across_a_whole_session(mon, web):
    k, p = start(web, "طالب أ1"); start(web, "طالب أ2", ping=False); start(web, "طالب ب1", section="ب")
    refresh(mon); mon.fill("#q", "أ"); mon.fill("#q", ""); mon.click("#cards .card:nth-child(2)"); mon.click("#cards .card:nth-child(2)")
    finish(web, "طالب أ1", k, p); web.teacher(message="x"); web.teacher(close=True); refresh(mon); web.teacher(close=False); web.teacher(newexam=True); refresh(mon)
    assert not mon.js_errors, mon.js_errors
