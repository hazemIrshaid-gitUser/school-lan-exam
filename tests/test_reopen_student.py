"""إعادة فتح طالب سلّم بالغلط (زر «↩ إعادة فتح للطالب» بقائمة ⋯ لصف «سلّم»، أمر المعلم {"reopen": مفتاح الطالب}):
تسليمه بينلغى (بيضل بـ submissions.jsonl كأرشيف وبعده سطر {"key","reopen"})، وبيرجع لأسئلته بإجاباته المحفوظة ووقته اللي كان باقيله لحظة التسليم
(على الأقل دقيقتين)، والاسم والجهاز بيضلوا محجوزين، ومدة «سلّم» ما بتنحسب من مدة حله. صفحته (لو لسا مفتوحة أو انعاد تحميلها) بترجع للأسئلة بنفسها."""
import csv, io, json, shutil, subprocess, sys, time

import pytest
from conftest import PKG_SRC
from test_http import Server
from test_browser import browser, phone, login, solve, submit, url  # noqa: F401  (fixtures + helpers)

A1, A2 = "طالب أ1", "طالب أ2"


def lines(pkg): return [json.loads(l) for l in pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
def rows(w): return {r["name"]: r for s in w.get("/monitor.json")[1]["sections"].values() for r in s}
def csv_names(pkg):
    f = pkg.p("results.csv")
    return [r[3] for r in list(csv.reader(io.StringIO(f.read_text(encoding="utf-8-sig"))))[1:]] if f.exists() else []
def csv_score(pkg, name): return next(r[4] for r in csv.reader(io.StringIO(pkg.p("results.csv").read_text(encoding="utf-8-sig"))) if len(r) > 4 and r[3] == name)
def kill(s): s.proc.kill(); s.proc.wait()


@pytest.fixture
def servers():
    made = []
    def start(pkg):
        s = Server(pkg).start(); made.append(s); return s
    yield start
    for s in made: s.stop()


def submitted(w, name=A1, dev="d1", wrong=False, **kw):
    """يبدأ طالب ويسلّم (صح أو كله بلا إجابة) ويرجّع (المفتاح، ورقته، إجاباته)"""
    k, _, p = w.start_student(dev, n=name)
    answers = [-1] * len(p["ids"]) if wrong else w.correct_answers(p["ids"])
    assert w.submit(k, dev, p["ids"], answers, **kw)[0] == 200
    return k, p, answers


# ============================ السيرفر ============================
def test_reopen_cancels_the_submission_and_restores_answers_name_and_time(pkg, servers):
    w = servers(pkg); k, p, answers = submitted(w); r0 = p["remain"]
    assert A1 in csv_names(pkg) and rows(w)[A1]["status"] == "done"
    time.sleep(4.0)                                                                                  # مدة «سلّم» (ما لازم تنحسب من وقته)
    assert w.teacher(reopen=k) == (200, {"ok": 1})
    row = rows(w)[A1]; assert row["status"] == "live" and "score" not in row and row["answered"] == len(answers), row
    assert A1 not in csv_names(pkg)                                                                  # العلامة القديمة اختفت من results.csv
    st, j, _, _ = w.post("/resume", {"key": k, "dev": "d1"})
    assert st == 200 and j["status"] == "ok" and j["paused"] is False
    assert j["ans"] == {str(n): a for n, a in zip(p["ids"], answers)}, j["ans"]                      # إجاباته نفسها
    assert r0 - 2 <= j["remain"] <= r0 + 1, (r0, j["remain"])                                        # وقته اللي كان باقيله، مش اللي ضاع وهو «سلّم»
    assert w.start_student("d2", n=A1)[2]["status"] == "taken"                                       # الاسم محجوز لجهازه
    assert w.start_student("d1", n=A1)[2]["status"] == "ok"
    last = lines(pkg)[-1]; assert last["key"] == k and last["reopen"] and "score" not in last         # سطر الإلغاء بالسجل (والتسليم القديم قبله بيضل)
    assert [l.get("score") for l in lines(pkg)[:-1]] == [8]


def test_resubmitting_after_a_reopen_replaces_the_result_everywhere(pkg, servers):
    w = servers(pkg); k, p, _ = submitted(w, wrong=True)
    assert csv_score(pkg, A1) == "0"
    w.teacher(reopen=k)
    st, j, _ = w.submit(k, "d1", p["ids"], w.correct_answers(p["ids"])); assert (st, j) == (200, {"score": 8, "total": 8})
    assert csv_score(pkg, A1) == "8" and rows(w)[A1]["status"] == "done" and rows(w)[A1]["score"] == 8
    assert [("reopen" in l, l.get("score")) for l in lines(pkg)] == [(False, 0), (True, None), (False, 8)]      # السجل كامل: تسليم، إلغاء، تسليم
    kill(w); w = servers(pkg)                                                                          # بعد إعادة تشغيل السيرفر: آخر تسليم هو اللي بيعدّ
    assert rows(w)[A1]["status"] == "done" and rows(w)[A1]["score"] == 8 and csv_names(pkg).count(A1) == 1


def test_a_server_restart_right_after_the_reopen_keeps_the_student_open_with_his_answers(pkg, servers):
    w = servers(pkg); k, p, answers = submitted(w); w.teacher(reopen=k)
    kill(w); w = servers(pkg)
    row = rows(w)[A1]; assert row["status"] in ("live", "lost") and "score" not in row, row           # سطر الإلغاء انقرأ: ما رجع «سلّم»
    j = w.post("/resume", {"key": k, "dev": "d1"})[1]
    assert j["status"] == "ok" and j["ans"] == {str(n): a for n, a in zip(p["ids"], answers)}, j      # والإجابات انحفظت على القرص فوراً
    assert w.post("/submit", {"key": k, "dev": "d1", "ids": p["ids"], "answers": ",".join(map(str, answers))})[0] == 200


def test_the_reopened_students_solving_time_skips_the_submitted_gap(pkg, servers):
    w = servers(pkg); t0 = time.time(); k, p, answers = submitted(w)
    time.sleep(3.2); w.teacher(reopen=k); time.sleep(1.0)
    assert w.submit(k, "d1", p["ids"], answers)[0] == 200
    new = lines(pkg)[-1]; total = time.time() - t0
    assert new["dur"] <= total - 2.8 and new["dur"] >= 1 and new["late"] == 0, (new["dur"], total)     # بدون الـ 3 ثواني اللي كان فيها «سلّم»


def test_reopen_gives_at_least_two_minutes(pkg, servers):
    pkg.settings(**{"المدة_بالدقائق": 1}); w = servers(pkg)
    k, p, _ = submitted(w)                                                                             # سلّم وباقيله حوالي 59 ثانية
    w.teacher(reopen=k); j = w.post("/resume", {"key": k, "dev": "d1"})[1]
    assert 118 <= j["remain"] <= 121, j["remain"]


def test_reopen_includes_extensions_the_student_already_had(pkg, servers):
    w = servers(pkg); k, _, p = w.start_student("d1", n=A1); r0 = p["remain"]
    w.teacher(extend=5, scope="student", key=k)                                                        # مدّدنا وقته قبل ما يسلّم (التمديد ما بيشمل اللي سلّم أصلاً)
    assert w.submit(k, "d1", p["ids"], w.correct_answers(p["ids"]))[0] == 200
    w.teacher(reopen=k); j = w.post("/resume", {"key": k, "dev": "d1"})[1]
    assert r0 + 300 - 3 <= j["remain"] <= r0 + 300 + 1, (r0, j["remain"])


def test_reopen_works_for_a_teacher_submitted_student_and_for_records_without_ts(pkg, servers):
    w = servers(pkg); k1, _, p1 = w.start_student("d1", n=A1); k2, _, p2 = w.start_student("d2", n=A2)
    assert w.teacher(submitfor=k1) == (200, {"ok": 1}) and "ts" in lines(pkg)[-1]                       # تسليم المعلم كمان بيسجّل الوقت
    assert w.teacher(reopen=k1) == (200, {"ok": 1}) and rows(w)[A1]["status"] in ("live", "lost")
    assert w.submit(k2, "d2", p2["ids"], w.correct_answers(p2["ids"]))[0] == 200
    kill(w)                                                                                            # سجل من نسخة أقدم: بدون ts (الوقت من نص «time»)
    recs = lines(pkg); old = [dict((a, b) for a, b in r.items() if a != "ts") for r in recs]
    pkg.p("submissions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in old), encoding="utf-8")
    w = servers(pkg); assert rows(w)[A2]["status"] == "done"; time.sleep(2.5)
    assert w.teacher(reopen=k2) == (200, {"ok": 1})
    assert w.post("/resume", {"key": k2, "dev": "d2"})[1]["remain"] >= p2["remain"] - 1.5               # الوقت من نص «time» (وقت التسليم)، مش من لحظة إعادة الفتح


@pytest.mark.parametrize("case", ["not_started", "not_submitted", "closed", "unknown"])
def test_reopen_refuses_when_there_is_nothing_to_reopen(pkg, servers, case):
    w = servers(pkg)
    if case == "not_started": key = w.key(n=A1)
    elif case == "not_submitted": key, _, _ = w.start_student("d1", n=A1)
    elif case == "unknown": key = "غير|موجود|x|y"
    else:
        key, p, answers = submitted(w); w.teacher(close=True)
    st, j = w.teacher(reopen=key); assert st == 400 and j["error"], (case, st, j)
    if case == "closed": assert "أعد فتحه" in j["error"] and rows(w)[A1]["status"] == "done"
    if case == "closed":
        w.teacher(close=False); assert w.teacher(reopen=key) == (200, {"ok": 1})                       # وبعد إعادة فتح الامتحان بيزبط


def test_only_the_teacher_can_reopen(pkg, servers):
    w = servers(pkg); k, p, answers = submitted(w)
    assert w.post("/monitor", {"reopen": k}, {"Content-Type": "application/json"})[0] == 403             # بدون ترويسة المعلم
    assert rows(w)[A1]["status"] == "done"


def test_problem_report_counts_the_reopen_and_does_not_call_it_a_duplicate(pkg, servers):
    w = servers(pkg); k, p, answers = submitted(w); w.teacher(reopen=k); w.submit(k, "d1", p["ids"], answers)
    shutil.copy(PKG_SRC / "report_problem.py", pkg.path / "report_problem.py")
    r = subprocess.run([sys.executable, "-X", "utf8", "report_problem.py"], cwd=pkg.path, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    rep = next(pkg.path.glob("problem_report_*.txt")).read_text(encoding="utf-8-sig")
    line = next(l for l in rep.splitlines() if "submissions.jsonl" in l and "تسليم سليم" in l)
    assert "2 تسليم سليم" in line and "1 إعادة فتح" in line and "مكرر" not in line, (line, r.stderr[-200:])


# ============================ صفحة الطالب ============================
def checked(page): return page.evaluate("document.querySelectorAll('#qs input:checked').length")


def test_student_page_goes_back_to_the_questions_with_the_same_answers(phone, pkg, servers):
    w = servers(pkg); page = phone(); login(page, w, name=A1); solve(page); submit(page)
    page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
    n_before = checked(page); assert n_before == 8 and page.locator("#s-done").is_visible()
    k = w.key(n=A1); assert w.teacher(reopen=k) == (200, {"ok": 1})
    page.wait_for_selector("#s-exam:not(.hide)", timeout=15000)                                        # الصفحة بتسأل كل 5 ثواني
    assert page.locator("#s-done").is_hidden() and page.locator("#new-student").is_hidden()
    assert checked(page) == n_before                                                                   # إجاباته كلها بمكانها
    c1 = page.inner_text("#clock"); page.wait_for_timeout(2300); assert page.inner_text("#clock") != c1          # والساعة ماشية
    submit(page); page.wait_for_function("document.getElementById('status').textContent.includes('✓')", timeout=10000)
    assert page.locator("#s-done").is_visible() and rows(w)[A1]["status"] == "done" and rows(w)[A1]["score"] == 8
    assert not page.js_errors


def test_a_reloaded_page_is_unblocked_after_the_reopen(phone, pkg, servers):
    """الطالب سكّر الصفحة أو عمل refresh بعد التسليم: بيبين «سلّم من هذا الجهاز»، ولما المعلم يعيد فتحه بيتفكّ الحظر بدون ما نلمس شي"""
    w = servers(pkg); page = phone(); login(page, w, name=A1); solve(page); submit(page)
    page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
    page.goto(url(w)); page.select_option("#g", "العاشر"); page.select_option("#sec", "أ")
    page.wait_for_function("document.querySelectorAll('#nm option').length > 1"); page.select_option("#nm", A1)
    assert page.locator("#blocked").is_visible() and page.locator("#start").is_disabled()
    assert w.teacher(reopen=w.key(n=A1)) == (200, {"ok": 1})
    page.wait_for_function("document.getElementById('blocked').classList.contains('hide')", timeout=15000)
    assert page.locator("#start").is_enabled()
    page.click("#start"); page.wait_for_selector("#s-exam:not(.hide)")
    assert page.inner_text("#who") == A1 and checked(page) == 8 and not page.js_errors


# ============================ شاشة المراقبة الجديدة ============================
def test_new_monitor_reopens_a_student_from_the_row_menu(pkg, servers, browser):
    from test_monitor_new_ui import Ui, wait_for, with_ui
    with_ui(pkg); w = servers(pkg); k, p, answers = submitted(w)
    ui = Ui(browser, w); pg = ui.pg
    try:
        pg.locator("details.section-card", has_text="شعبة أ").locator("summary").first.click()                  # الشعبة اللي كلها سلّمت بتكون مطويّة
        row = ui.row(A1); row.wait_for(); assert "سلّم" in row.inner_text() and row.locator("button.kebab").count() == 1
        row.locator("button.kebab").click()
        assert pg.locator(".row-popup").get_by_text("↩ إعادة فتح للطالب", exact=True).count() == 1
        n0 = len(ui.posts); pg.locator(".row-popup").get_by_text("↩ إعادة فتح للطالب", exact=True).click()
        assert ui.modal.is_visible() and "علامته الحالية" in ui.modal.inner_text() and len(ui.posts) == n0       # نافذة تأكيد، وما انبعت شي لسا
        ui.modal.get_by_role("button", name="إعادة فتح الطالب").click(); pg.wait_for_timeout(800)
        hdr, body = ui.posts[n0]; assert hdr == "1" and body == {"reopen": k}, body
        wait_for(lambda: rows(w)[A1]["status"] != "done", 8, "server reopened")
        pg.wait_for_function("(n)=>{const r=[...document.querySelectorAll('tbody tr')].find(x=>x.textContent.includes(n));return !!r&&!r.textContent.includes('سلّم')&&r.textContent.includes('يمتحن')}", arg=A1, timeout=10000)
        assert not ui.errors
    finally:
        ui.close()
