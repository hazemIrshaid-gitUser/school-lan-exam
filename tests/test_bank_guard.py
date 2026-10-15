"""حماية «ملف أسئلة جديد وبيانات الامتحان السابق لسا موجودة»: المشرف بيحط ملف الأسئلة الجديد ويشغّل start.bat — لو نسي «بداية امتحان جديد»
لازم يطلعله تنبيه واضح (المراقبة، الفحص، النافذة السوداء، check_files) لحد ما يضغطها، أو يأكّد «هذا نفس الامتحان» (تصليح سؤال)."""
import json, subprocess, sys

import pytest
from conftest import bank, q
from test_http import Server


def new_questions(pkg):
    pkg.questions([q(f"سؤال جديد {i}", (f"ج{i}-أ", f"ج{i}-ب", f"ج{i}-ج", f"ج{i}-د"), "أبجد"[i % 4], ("صعب", "وسط", "سهل")[i % 3]) for i in range(12)])


def bank_warn(w):
    return [x for x in w.get("/health.json")[1]["warnings"] if "ملف الأسئلة تغيّر" in x]


def state(pkg): return json.loads(pkg.p("state.json").read_text(encoding="utf-8"))


@pytest.fixture
def exam1(pkg):
    """امتحان أول: طالب سلّم وطالب بدأ وما سلّم، وبعدين السيرفر انطفى"""
    pkg.p("settings.txt").unlink()                                                          # سيناريو المشرف: بدون settings.txt
    w = Server(pkg).start(); t = w.get("/health.json")[1]["exam"]["title"]
    k1, _, p1 = w.start_student("d1", title=t); w.submit(k1, "d1", p1["ids"], w.correct_answers(p1["ids"]))
    w.start_student("d2", n="طالب أ2", title=t)
    assert not bank_warn(w) and w.get("/monitor.json")[1]["bank_changed"] is None
    w.stop()
    return pkg


def test_new_questions_without_new_exam_warns_everywhere(exam1):
    new_questions(exam1)
    r = subprocess.run([sys.executable, "-X", "utf8", "check_files.py"], cwd=exam1.path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert "ملف الأسئلة تغيّر بعد آخر امتحان" in r.stdout and "(1 تسليم و2 ورقة)" in r.stdout
    w = Server(exam1).start()
    try:
        assert len(bank_warn(w)) == 1 and w.get("/health.json")[1]["level"] in ("warn", "bad")
        assert w.get("/monitor.json")[1]["bank_changed"] == {"subs": 1, "papers": 2}
        w.teacher(newexam=True)                                                              # المشرف ضغط «بداية امتحان جديد»
        assert not bank_warn(w) and w.get("/monitor.json")[1]["bank_changed"] is None
        t2 = w.get("/health.json")[1]["exam"]["title"]
        k, _, p = w.start_student("d1", title=t2); assert p["status"] == "ok" and all("سؤال جديد" in q["q"] for q in p["qs"])      # أسئلة الملف الجديد
    finally:
        w.stop()
    w = Server(exam1).start()
    try: assert not bank_warn(w)                                                              # وما بيرجع بعد إعادة التشغيل
    finally: w.stop()


def test_right_order_never_warns(pkg):
    w = Server(pkg).start()
    try:
        k, _, p = w.start_student("d1"); w.submit(k, "d1", p["ids"], w.correct_answers(p["ids"]))
        w.teacher(newexam=True)                                                              # الترتيب الصحيح: بداية امتحان جديد أول
    finally:
        w.stop()
    new_questions(pkg); w = Server(pkg).start()
    try: assert not bank_warn(w) and w.get("/monitor.json")[1]["bank_changed"] is None
    finally: w.stop()


def test_resaving_the_same_questions_does_not_warn(exam1):
    exam1.questions(bank())                                                                  # نفس المحتوى، ملف جديد (وقت حفظ مختلف)
    w = Server(exam1).start()
    try: assert not bank_warn(w)
    finally: w.stop()


def test_typo_fix_mid_exam_can_be_confirmed_and_students_continue(exam1):
    rows = bank(); rows[0][0] = "سؤال رقم 1 (مصحّح)"; exam1.questions(rows)
    w = Server(exam1).start()
    try:
        assert bank_warn(w)
        w.teacher(bankok=1)
        assert not bank_warn(w) and w.get("/monitor.json")[1]["bank_changed"] is None and state(exam1)["bank_fp"]
        t = w.get("/health.json")[1]["exam"]["title"]
        st, j, *_ = w.post("/resume", {"key": f"{t}|العاشر|أ|طالب أ2", "dev": "d2"}); assert j["status"] == "ok"   # الطالب اللي كان بيمتحن بيكمل
    finally:
        w.stop()
    w = Server(exam1).start()
    try: assert not bank_warn(w)
    finally: w.stop()


def test_explicit_title_is_protected_too(pkg):
    w = Server(pkg).start()
    try: k, _, p = w.start_student("d1"); w.submit(k, "d1", p["ids"], w.correct_answers(p["ids"]))
    finally: w.stop()
    new_questions(pkg); w = Server(pkg).start()
    try:
        assert bank_warn(w) and w.start_student("d1")[2] == {"status": "done"}                  # هذا بالضبط الفخ اللي التنبيه بيمنعه
    finally:
        w.stop()


def test_data_from_older_version_without_fingerprint_does_not_warn(exam1):
    st = state(exam1); st.pop("bank_fp"); exam1.p("state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    new_questions(exam1); w = Server(exam1).start()
    try: assert not bank_warn(w) and state(exam1)["bank_fp"]
    finally: w.stop()


def test_console_banner_warns(exam1):
    from test_console_mode import Live
    new_questions(exam1); l = Live(exam1, force=True)
    try:
        assert l.wait_for("To stop: Ctrl+C") and "WARNING: the questions file changed" in l.text
        assert "ملف الأسئلة تغيّر بعد آخر امتحان" in exam1.p("exam_info.txt").read_text(encoding="utf-8-sig")
    finally:
        l.stop()


def test_monitor_bar_and_same_exam_button_in_browser(exam1):
    pw = pytest.importorskip("playwright.sync_api")
    new_questions(exam1); w = Server(exam1).start()
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch(channel="msedge", headless=True); pg = b.new_page(); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("dialog", lambda d: d.accept())
            try:
                pg.goto(f"http://127.0.0.1:{w.port}/monitor"); pg.wait_for_selector("#bankbar", state="visible")
                t = pg.inner_text("#bankbar"); assert "ملف الأسئلة تغيّر" in t and "1 تسليم و2 ورقة" in t and "بداية امتحان جديد" in t
                pg.click("text=هذا نفس الامتحان"); pg.wait_for_selector("#bankbar", state="hidden")
                assert not errs and not bank_warn(w)
            finally:
                b.close()
    finally:
        w.stop()
