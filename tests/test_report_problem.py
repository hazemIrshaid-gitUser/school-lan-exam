"""زر «جمع معلومات المشكلة» (report_problem.bat / report_problem.py): بيكتب تقرير نصي واحد، ما بيغيّر ولا ملف،
بيخفي كلمة السر ورموز الطلاب، وبيشتغل حتى لو السيرفر واقف أو الملفات تالفة أو المجلد فاضي أو بايثون مش مثبّت."""
import hashlib, importlib.util, json, os, pathlib, re, shutil, subprocess, sys

import pytest
from conftest import PKG_SRC
from test_http import Server

WIN = pytest.mark.skipif(os.name != "nt", reason="ويندوز فقط")
TOOL = ("report_problem.py", "report_problem.bat")


@pytest.fixture
def kit(pkg):
    for f in TOOL: shutil.copy(PKG_SRC / f, pkg.p(f))
    return pkg


def snapshot(d):
    return {str(f.relative_to(d)): hashlib.sha256(f.read_bytes()).hexdigest() for f in pathlib.Path(d).rglob("*")
            if f.is_file() and not f.name.startswith("problem_report_")}


def run_report(d, port=None):
    env = dict(os.environ); env.pop("EXAM_PORT", None)
    if port: env["EXAM_PORT"] = str(port)
    r = subprocess.run([sys.executable, "-X", "utf8", "report_problem.py"], cwd=d, env=env, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=120)
    assert r.returncode == 0, r.stderr
    reps = sorted(pathlib.Path(d).glob("problem_report_*.txt")); assert len(reps) == 1, reps
    t = reps[0].read_text(encoding="utf-8-sig"); reps[0].unlink()
    return t


def tool_module():
    spec = importlib.util.spec_from_file_location("report_problem_under_test", PKG_SRC / "report_problem.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


# ============================ مع سيرفر شغّال ============================
def test_report_with_running_server_has_health_and_hides_secrets(kit):
    kit.students([["العاشر", "أ", "طالب أ1", "483920"], ["العاشر", "أ", "طالب أ2", "771205"]])
    kit.settings(**{"كلمة_سر_المعلم": "S3cret!x", "رمز_الدخول": "نعم"})
    w = Server(kit).start()
    try:
        k, _, p = w.start_student("d1", code="483920"); w.submit(k, "d1", p["ids"], w.correct_answers(p["ids"]))
        w.start_student("d2", n="طالب أ2", code="771205")
        before = snapshot(kit.path); before.pop("alive.txt")
        t = run_report(kit.path, w.port)
        after = snapshot(kit.path); after.pop("alive.txt")                                    # السيرفر نفسه بيحدّث نبضته كل 3 ث
        assert after == before, "التقرير غيّر ملفات!"
    finally:
        w.stop()
    assert f"المنفذ {w.port}: السيرفر بيرد" in t and '"version": "v06' in t and '"done": 1' in t and '"started": 2' in t
    assert "S3cret!x" not in t and "483920" not in t and "771205" not in t and "*** (مخفية، 8 حرف)" in t
    assert "submissions.jsonl" in t and "1 تسليم سليم" in t and "JSON سليم" in t and "السيرفر شغّال الآن على الأغلب" in t
    assert "FOR THE ASSISTANT" in t and "وصف المشكلة (اكتب هون)" in t and "إصدار الحزمة (من server.py): v06" in t
    assert "10) exam_log.txt" in t and "11) start.bat" in t


# ============================ سيرفر واقف + ملفات تالفة ============================
def test_report_with_server_down_and_broken_files(kit):
    kit.p("papers.json").write_text("{broken", encoding="utf-8")
    kit.p("claims.json").write_text('{"a": "b"}', encoding="utf-8")
    kit.p("submissions.jsonl").write_text('{"key": "x|1", "score": 1}\n{"key": "x|2", "sco', encoding="utf-8")       # آخر سطر مقطوع
    kit.p("exam_error.txt").write_text("questions سطر 4: الصورة «p048.png» غير موجودة بمجلد images", encoding="utf-8")
    kit.p("alive.txt").write_text(repr(1.0), encoding="utf-8")
    kit.p("server (1).py").write_text("# نسخة ثانية بالغلط", encoding="utf-8")
    before = snapshot(kit.path)
    t = run_report(kit.path, port=1)
    assert snapshot(kit.path) == before
    assert "papers.json" in t and "JSON تالف" in t and "أسطر تالفة: [2]" in t and "claims.json" in t and "(1 عنصر)" in t
    assert "الصورة «p048.png» غير موجودة" in t and "ما في سيرفر بيرد" in t and "السيرفر واقف" in t and "server (1).py" in t


def test_report_in_an_empty_folder(tmp_path):
    shutil.copy(PKG_SRC / "report_problem.py", tmp_path / "report_problem.py")
    t = run_report(tmp_path, port=1)
    assert "server.py مش موجود" in t and "server.py" in t and "مش موجود ⚠" in t and "(نهاية التقرير)" in t


@WIN
def test_results_csv_locked_by_excel_is_reported(kit):
    import ctypes
    kit.p("results.csv").write_text("x\n", encoding="utf-8")
    k32 = ctypes.windll.kernel32; k32.CreateFileW.restype = ctypes.c_void_p
    h = k32.CreateFileW(str(kit.p("results.csv")), 0x80000000, 1, None, 3, 0, None)          # قراءة فقط ومشاركة قراءة فقط = زي Excel
    assert h not in (None, ctypes.c_void_p(-1).value)
    try:
        t = run_report(kit.path, port=1)
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))
    assert "مفتوح ببرنامج ثاني (Excel؟)" in t


# ============================ إخفاء كلمة السر ============================
@pytest.mark.parametrize("line,shown,hidden", [
    ("كلمة_سر_المعلم = Abc#12 3", "*** (مخفية، 8 حرف)", "Abc#12"),
    ("كلمة سر المعلم=xyz", "*** (مخفية، 3 حرف)", "xyz"),
    ("كلمة_سر_المعلم =", "(فاضية: ما في كلمة سر)", None),
    ("كلمة_سر_المعلم = 1234", "1234 (الافتراضية)", None),
    ("# كلمة_سر_المعلم = سطر تعليق بيضل", "# كلمة_سر_المعلم = سطر تعليق بيضل", None),
])
def test_password_masking(line, shown, hidden):
    out = tool_module().masked_settings("عنوان_الامتحان = x\n" + line + "\nالمدة_بالدقائق = 30")
    assert shown in out and "عنوان_الامتحان = x" in out and "المدة_بالدقائق = 30" in out
    if hidden: assert hidden not in out


def test_utf16_settings_are_read_and_masked(kit):
    kit.p("settings.txt").write_bytes(("عنوان_الامتحان = تجربة\nكلمة_سر_المعلم = Zz99\n").encode("utf-16"))
    t = run_report(kit.path, port=1)
    assert "Zz99" not in t and "ترميز utf-16" in t and "عنوان_الامتحان = تجربة" in t


def test_long_log_is_trimmed(kit):
    kit.p("exam_log.txt").write_text("".join(f"10:00:{i % 60:02d}  سطر رقم {i}\n" for i in range(5000)), encoding="utf-8")
    t = run_report(kit.path, port=1)
    assert "(آخر 300 سطر من أصل 5000)" in t and "سطر رقم 4999" in t and "سطر رقم 10\n" not in t and len(t) < 400_000


# ============================ ملف bat الحقيقي ============================
class _Out:
    def __init__(self, b): self.stdout = b


def _cmd(bat, env, cwd):
    """المخرجات لملف مش لأنبوب: المفكرة اللي بيفتحها الملف بتورث الأنبوب وبتخلّي الانتظار يعلق"""
    comspec = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
    log = pathlib.Path(cwd) / "bat_output.txt"
    with open(log, "wb") as f:
        subprocess.run(f'"{comspec}" /d /s /c ""{bat}""', cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=120)
    return _Out(log.read_bytes())


@WIN
def test_bat_in_arabic_folder_with_spaces_and_parentheses(kit, tmp_path):
    d = tmp_path / "امتحان (نسخة 2) الفيزياء"; shutil.copytree(kit.path, d)
    r = _cmd(d / "report_problem.bat", dict(os.environ), tmp_path)
    reps = list(d.glob("problem_report_*.txt"))
    assert len(reps) == 1 and "Saved: problem_report_" in r.stdout.decode("utf-8", "replace"), r.stdout[-400:]
    assert "تقرير معلومات مشكلة" in reps[0].read_text(encoding="utf-8-sig")


@WIN
def test_bat_without_python_still_leaves_a_small_report(kit, tmp_path):
    d = tmp_path / "بدون بايثون (1)"; shutil.copytree(kit.path, d)
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("PATH", "PYTHONPATH", "PYTHONHOME")}
    env["PATH"] = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")          # ما في python ولا py
    try:
        r = _cmd(d / "report_problem.bat", env, tmp_path)
        out = r.stdout.decode("utf-8", "replace")
        assert "Python was not found" in out and (d / "problem_report_no_python.txt").exists(), out[-400:]
        t = (d / "problem_report_no_python.txt").read_bytes().decode("utf-8", "replace")
        assert "PYTHON NOT FOUND" in t and "Windows" in t and "server.py" in t
    finally:
        ps = "Get-CimInstance Win32_Process -Filter \"Name='notepad.exe'\" | Where-Object { $_.CommandLine -like '*problem_report_no_python*' } | ForEach-Object { $_.ProcessId }"
        for pid in subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.split():
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)


def test_package_files_are_in_place():
    for f in TOOL: assert (PKG_SRC / f).exists(), f
    b = (PKG_SRC / "report_problem.bat").read_bytes()
    assert b"\r\n" in b and b.replace(b"\r\n", b"").find(b"\n") < 0 and b.isascii()               # CRLF وأحرف إنجليزية بس (عشان cmd)
    assert re.search(r'^VERSION = "v\d+', (PKG_SRC / "server.py").read_text(encoding="utf-8"), re.M)
