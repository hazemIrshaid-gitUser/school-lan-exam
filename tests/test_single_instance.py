"""سيرفر واحد بس لكل مجلد امتحان: لو المشرف شغّل start.bat مرتين من نفس المجلد، النسخة الثانية بترفض وبتكتب رسالة واضحة (بدل ما تاخد منفذاً ثانياً وتكتب على نفس ملفات الأولى).
القفل ملف server.lock بيمسكه السيرفر بقفل حصري طول ما هو شغّال؛ نظام التشغيل بيفكّه لحاله لو السيرفر وقف أو انقتل، فإعادة التشغيل الفورية (خطة الطوارئ) ما بتتأثر،
وملف قفل قديم متروك (مثلاً مجلد منسوخ من جهاز ثاني) ما بيمنع شي. استيراد server.py كمكتبة (الاختبارات، check_files) ما بياخد القفل."""
import hashlib, os, subprocess, sys, time

import pytest
from test_http import PKG_PYTHON, free_port
from test_two_servers import made, make_copy, pid_on, start  # noqa: F401  (made = fixture)
from test_windows_env import Run, SYS32

RUNTIME = ("papers.json", "claims.json", "state.json", "answers.json", "submissions.jsonl", "results.csv", "exam_info.txt")


def second(pkg, port, arabic=False, timeout=30):
    """بيشغّل server.py ثاني مرة من نفس المجلد وبينتظر ينتهي"""
    env = dict(os.environ, EXAM_PORT=str(port), PYTHONIOENCODING="utf-8"); env.pop("EXAM_NO_ARABIC_CONSOLE", None)
    if not arabic: env["EXAM_NO_ARABIC_CONSOLE"] = "1"
    t0 = time.time()
    r = subprocess.run([PKG_PYTHON, "-X", "utf8", "server.py"], cwd=pkg.path, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    return r, time.time() - t0


def digest(pkg):
    return {n: hashlib.sha256(pkg.p(n).read_bytes()).hexdigest() for n in RUNTIME if pkg.p(n).exists()}


def test_a_second_start_from_the_same_folder_refuses_and_leaves_the_first_alone(tmp_path, made):
    pkg = make_copy(tmp_path, "امتحان"); want = free_port(); s1 = start(pkg, want); made.append(s1)
    k, st, p = s1.start_student("d1", n="طالب أ1"); assert st == 200                                      # في بيانات حقيقية للسيرفر الأول
    time.sleep(0.6); before = digest(pkg)
    r, took = second(pkg, want)
    assert r.returncode != 0 and "ALREADY RUNNING" in r.stdout and "copy the whole folder" in r.stdout, (r.returncode, r.stdout[-400:], r.stderr[-300:])
    assert took < 15, took
    assert pid_on(s1.port) == s1.proc.pid and s1.proc.poll() is None                                         # الأول لسا شغّال ويجاوب
    assert digest(pkg) == before, "النسخة الثانية ما لازم تلمس ملفات الامتحان"


def test_the_refusal_names_the_other_process(tmp_path, made):
    pkg = make_copy(tmp_path, "امتحان"); s1 = start(pkg, free_port()); made.append(s1)
    r, _ = second(pkg, s1.port); assert f"PID {s1.proc.pid}" in r.stdout, r.stdout[-300:]


def test_the_refusal_is_also_written_in_arabic_when_the_console_can_show_it(tmp_path, made):
    pkg = make_copy(tmp_path, "امتحان"); s1 = start(pkg, free_port()); made.append(s1)
    r, _ = second(pkg, s1.port, arabic=True); assert "شغّال أصلاً" in r.stdout and "ALREADY RUNNING" in r.stdout, r.stdout[-400:]


def test_restart_right_after_a_kill_is_not_blocked(tmp_path, made):
    """خطة الطوارئ: وقف السيرفر وانشغّل من جديد فوراً بنفس المجلد (القفل بيتفك لما العملية بتنتهي)، وبنفس المنفذ"""
    pkg = make_copy(tmp_path, "امتحان"); want = free_port(); s1 = start(pkg, want); made.append(s1)
    s1.proc.kill(); s1.proc.wait(); pkg.p("exam_info.txt").unlink()
    s2 = start(pkg, want); made.append(s2)                                                                  # بدون أي انتظار بينهم
    assert s2.port == want and pid_on(want) == s2.proc.pid


def test_a_normal_stop_then_start_works(tmp_path, made):
    pkg = make_copy(tmp_path, "امتحان"); want = free_port(); s1 = start(pkg, want); made.append(s1)
    s1.stop(); pkg.p("exam_info.txt").unlink()
    s2 = start(pkg, want); made.append(s2); assert pid_on(s2.port) == s2.proc.pid


def test_a_stale_lock_file_does_not_block(tmp_path, made):
    pkg = make_copy(tmp_path, "امتحان"); pkg.p("server.lock").write_bytes(b"x99999")                         # ملف قفل متروك: ما في عملية ماسكته
    s = start(pkg, free_port()); made.append(s); assert pid_on(s.port) == s.proc.pid


def test_importing_the_module_does_not_take_the_lock(tmp_path):
    pkg = make_copy(tmp_path, "امتحان")
    r = subprocess.run([PKG_PYTHON, "-X", "utf8", "-c", "import server; print('imported')"], cwd=pkg.path, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert r.returncode == 0 and "imported" in r.stdout, r.stderr[-300:]
    assert not pkg.p("server.lock").exists()


@pytest.mark.skipif(os.name != "nt", reason="ويندوز فقط")
def test_start_bat_twice_from_the_same_folder_shows_the_message(tmp_path):
    import shutil
    from conftest import PKG_SRC
    pkg = make_copy(tmp_path, "امتحان (فيزياء) & كيمياء"); shutil.copy(PKG_SRC / "start.bat", pkg.path / "start.bat")
    port = str(free_port()); a = Run("start.bat", pkg.path, env={"EXAM_PORT": port}, path=None); b = None
    try:
        assert a.wait_for("Give students this link", 40), a.text[-500:]
        b = Run("start.bat", pkg.path, env={"EXAM_PORT": port})
        assert b.wait_for("ALREADY RUNNING", 30), b.text[-500:]
        assert a.p.poll() is None                                                                        # الأولى لسا شغّالة
    finally:
        a.kill()
        if b: b.kill()


def test_the_folder_can_be_copied_while_the_server_runs_and_the_copy_starts(tmp_path, made):
    """بالضبط شغلة المشرف لامتحان ثاني: ينسخ المجلد والسيرفر الأول شغّال (القفل ما لازم يمنع قراءة ملف server.lock)، وبعدين يشغّل النسخة"""
    import shutil
    pkg = make_copy(tmp_path, "امتحان 1"); s1 = start(pkg, free_port()); made.append(s1)
    assert pkg.p("server.lock").read_bytes().decode().strip() == str(s1.proc.pid)                          # بيتقرا والسيرفر ماسكه
    dst = tmp_path / "امتحان 2"; shutil.copytree(pkg.path, dst)                                              # نسخ كامل بدون PermissionError
    (dst / "exam_info.txt").unlink()                                                                         # (ورث رابط الأول؛ السيرفر الجديد بيكتب رابطه هو)
    from conftest import Pkg
    s2 = start(Pkg(dst), s1.port); made.append(s2)
    assert s2.port != s1.port and pid_on(s1.port) == s1.proc.pid and pid_on(s2.port) == s2.proc.pid
