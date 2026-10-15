"""settings.txt اختياري (مشرف المختبر بياخذ من الأستاذ ملف الأسئلة والصور بس): بدونه السيرفر بيشتغل بقيم افتراضية —
كل أسئلة الملف، 30 دقيقة، بدون كلمة سر (مع تنبيه)، وعنوان تلقائي فريد لكل امتحان، ثابت بإعادة التشغيل وجديد مع «بداية امتحان جديد»
(عشان طالب امتحن على جهاز بالمختبر يقدر يمتحن الامتحان الجاي على نفس الجهاز)."""
import json, re, subprocess, sys, time

import pytest
from conftest import bank, q
from test_http import Server
from test_outage import kill


def no_settings(pkg): pkg.p("settings.txt").unlink(); return pkg


def title_of(w): return w.get("/health.json")[1]["exam"]["title"]


def state(pkg): return json.loads(pkg.p("state.json").read_text(encoding="utf-8"))


# ============================ القيم الافتراضية ============================
def test_no_settings_file_uses_all_questions_and_defaults(pkg):
    m = no_settings(pkg).load()
    assert m.SET["missing"] and m.SET["auto_title"] and re.fullmatch(r"امتحان \d\d-\d\d-\d{4} \d\d:\d\d", m.SET["title"])
    assert m.PICK == {"hard": 3, "medium": 4, "easy": 4} and m.SET["minutes"] == 30 and m.SET["tpass"] == ""
    assert m.SET["shuffleQ"] and m.SET["shuffleO"] and m.SET["showScore"] and not m.SET["needCode"]
    assert state(pkg)["auto_title"] == m.SET["title"]


def test_no_settings_and_no_levels_takes_every_question(pkg):
    pkg.questions([q(f"سؤال {i}", ans="أب"[i % 2]) for i in range(1, 8)])
    m = no_settings(pkg).load()
    assert sum(m.PICK.values()) == 7 and len(m.make_paper()["ids"]) == 7


def test_settings_without_count_lines_takes_all_of_each_level(pkg):
    pkg.raw_settings("عنوان_الامتحان = اختبار قصير\nالمدة_بالدقائق = 20\nعدد_الأسئلة_الصعبة = 2\n")
    m = pkg.load()
    assert m.PICK == {"hard": 2, "medium": 4, "easy": 4} and m.SET["title"] == "اختبار قصير" and not m.SET.get("auto_title") and m.SET["minutes"] == 20


def test_written_counts_still_win_and_are_still_checked(pkg):
    pkg.settings(**{"عدد_الأسئلة_الصعبة": 9})
    pkg.expect_error("عدد الأسئلة بالبنك أقل من المطلوب", "صعب: مطلوب 9 والموجود 3")


def test_empty_title_line_means_automatic_title(pkg):
    pkg.raw_settings("عنوان_الامتحان =\nالمدة_بالدقائق = 15\n")
    m = pkg.load(); assert m.SET["auto_title"] and m.SET["title"].startswith("امتحان ") and m.SET["minutes"] == 15


def test_explicit_title_clears_an_old_automatic_one(pkg):
    m = no_settings(pkg).load(); auto = m.SET["title"]; assert state(pkg)["auto_title"] == auto
    pkg.settings(); m2 = pkg.load()
    assert m2.SET["title"] == "اختبار الوحدة" and "auto_title" not in state(pkg)
    pkg.p("settings.txt").unlink(); m3 = pkg.load()
    assert m3.SET["title"] != "اختبار الوحدة" and m3.SET["auto_title"]


# ============================ ثبات العنوان ============================
def test_automatic_title_survives_restart_and_student_continues(pkg):
    no_settings(pkg); s1 = Server(pkg).start()
    try:
        t = title_of(s1); k, _, p = s1.start_student("d1", title=t); assert p["status"] == "ok"
        time.sleep(1); kill(s1)
        s2 = Server(pkg).start()
        try:
            assert title_of(s2) == t
            st, j, *_ = s2.post("/resume", {"key": k, "dev": "d1"}); assert j["status"] == "ok" and j["ids"] == p["ids"]
        finally:
            s2.stop()
    finally:
        s1.stop()


def test_title_recovered_from_papers_if_state_file_is_lost(pkg):
    no_settings(pkg); m = pkg.load(); t = m.SET["title"]
    k = f"{t}|العاشر|أ|طالب أ1"; m.PAPERS[k] = m.make_paper(); m.CLAIMS[k] = "d1"; m.save_papers(); m.save_claims()
    pkg.p("state.json").unlink()
    assert pkg.load().SET["title"] == t


def test_title_does_not_change_when_the_questions_file_is_edited(pkg):
    no_settings(pkg); t = pkg.load().SET["title"]
    time.sleep(1.1); pkg.questions(bank(4, 4, 4))                                          # تصليح سؤال وسط الامتحان
    assert pkg.load().SET["title"] == t


# ============================ بداية امتحان جديد ============================
def test_new_exam_gets_a_new_title_and_old_pages_are_released(pkg):
    no_settings(pkg); w = Server(pkg).start()
    try:
        t1 = title_of(w); k1, _, p1 = w.start_student("d1", title=t1); w.submit(k1, "d1", p1["ids"], w.correct_answers(p1["ids"]))
        k2, _, _ = w.start_student("d2", n="طالب أ2", title=t1)
        time.sleep(1.1 if time.strftime("%S") != "59" else 2.2)
        w.teacher(newexam=True)
        t2 = title_of(w); assert t2 != t1 and t2.startswith("امتحان ") and state(pkg)["auto_title"] == t2
        assert json.dumps(t2, ensure_ascii=False) in w.get("/")[2].decode("utf-8")              # صفحة الطالب انبنت بالعنوان الجديد
        assert w.post("/ping", {"key": k2, "dev": "d2"})[1] == {"released": True}               # صفحة قديمة مفتوحة بترجع لشاشة الدخول
        k3, _, p3 = w.start_student("d1", title=t2); assert p3["status"] == "ok"                 # نفس الطالب ونفس الجهاز: بيبدأ الامتحان الجديد
    finally:
        w.stop()
    w2 = Server(pkg).start()
    try: assert title_of(w2) == t2                                                              # وبيضل نفسه بعد إعادة التشغيل
    finally: w2.stop()


def test_new_exam_with_written_title_keeps_it(pkg):
    w = Server(pkg).start()
    try:
        w.teacher(newexam=True); assert title_of(w) == "اختبار الوحدة"
    finally:
        w.stop()


def test_same_lab_computer_can_take_the_next_exam(pkg):
    """الأهم: طالب سلّم على جهاز بالمختبر، وبعدين امتحان جديد — نفس الجهاز ما لازم يقول «تم التسليم من هذا الجهاز مسبقاً»"""
    pw = pytest.importorskip("playwright.sync_api")
    from test_browser import launch, phone_ctx, solve, submit, url
    no_settings(pkg); w = Server(pkg).start()
    try:
        with pw.sync_playwright() as p:
            b = launch(p); ctx = phone_ctx(p, b); page = ctx.new_page(); page.set_default_timeout(10000)
            page.on("dialog", lambda d: d.accept())
            try:
                page.goto(url(w)); page.select_option("#g", "العاشر"); page.select_option("#sec", "أ"); page.select_option("#nm", "طالب أ1")
                page.click("#start"); page.wait_for_selector("#s-exam:not(.hide)"); solve(page)
                submit(page); page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
                time.sleep(1.1 if time.strftime("%S") != "59" else 2.2)
                w.teacher(newexam=True)                                                           # المشرف بيبدأ الامتحان الجاي
                page.goto(url(w)); page.select_option("#g", "العاشر"); page.select_option("#sec", "أ")
                page.wait_for_function("document.getElementById('nm').options.length > 1"); page.select_option("#nm", "طالب أ1")
                assert page.is_hidden("#blocked") and page.is_enabled("#start")
                page.click("#start"); page.wait_for_selector("#s-exam:not(.hide)")
            finally:
                ctx.close(); b.close()
    finally:
        w.stop()


# ============================ التنبيهات ============================
def test_health_and_check_files_say_defaults_are_used(pkg):
    no_settings(pkg)
    r = subprocess.run([sys.executable, "-X", "utf8", "check_files.py"], cwd=pkg.path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0 and "ما في settings.txt" in r.stdout and "(تلقائي" in r.stdout and "بالامتحان      : 11 سؤال" in r.stdout
    w = Server(pkg).start()
    try:
        ws = w.get("/health.json")[1]["warnings"]
        assert any("ما في ملف settings.txt" in x for x in ws) and any("ما في كلمة سر" in x for x in ws)
    finally:
        w.stop()


def test_console_banner_notes_missing_settings(pkg):
    from test_console_mode import Live
    no_settings(pkg); l = Live(pkg, force=True)
    try:
        assert l.wait_for("To stop: Ctrl+C") and "NOTE: no settings.txt - using defaults" in l.text
        assert "ما في ملف settings.txt" in pkg.p("exam_info.txt").read_text(encoding="utf-8-sig")
    finally:
        l.stop()


def test_password_added_later_without_restart(pkg):
    no_settings(pkg); w = Server(pkg).start()
    try:
        t = title_of(w); assert w.get("/key")[0] == 200                                         # بدون كلمة سر: مفتوح
        pkg.raw_settings("كلمة_سر_المعلم = Lab2026\n")
        assert w.get("/key")[0] == 302 and title_of(w) == t                                       # كلمة السر اشتغلت فوراً، والعنوان ما تغيّر
    finally:
        w.stop()
