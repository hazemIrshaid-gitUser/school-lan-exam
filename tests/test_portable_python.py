"""بايثون المحمول: الحزمة الكاملة بتجي ومعها مجلد python جنب server.py، فالمشرف ما بيحتاج يثبّت بايثون. ملفات التشغيل (start.bat وcheck_files.bat
وreport_problem.bat) بتستعمله أول شي، وإن ما لقته بتستعمل بايثون النظام (python ثم py) مثل قبل.
المجلد نفسه مش بالمخزن (ثنائي وكبير؛ انظر tools/python_embed/README.md)، فالاختبارات اللي بتحتاجه بتنتخطّى لو مش موجود بنسخة التطوير."""
import os, re, shutil, subprocess

import pytest
from conftest import CODE_FILES, PKG_SRC, Pkg
from test_windows_env import Run, SYS32, free_port

pytestmark = pytest.mark.skipif(os.name != "nt", reason="ويندوز فقط")
BUNDLED = PKG_SRC / "python"
PKG2 = next(PKG_SRC.parent.glob("2_*"))
need_python = pytest.mark.skipif(not (BUNDLED / "python.exe").exists(), reason="مجلد python (بايثون المحمول) مش موجود بنسخة التطوير")
BATS = ("start.bat", "check_files.bat", "report_problem.bat")
NO_SYSTEM_PYTHON = SYS32 + ";" + os.environ.get("SystemRoot", r"C:\Windows")        # PATH فيه ويندوز بس: لو استعمل بايثون النظام بيفشل


# ============================ ملفات التشغيل (بدون بايثون المحمول) ============================
@pytest.mark.parametrize("name", BATS)
def test_bat_files_are_plain_ascii_crlf_and_prefer_the_bundled_python(name):
    b = (PKG_SRC / name).read_bytes()
    assert b.isascii() and b.count(b"\r\n") == b.count(b"\n") and b.endswith(b"\r\n"), name                  # cmd بيتعثّر بغير ASCII/CRLF
    t = b.decode("ascii"); bundled = t.index('if exist "%~dp0python\\python.exe" set "PY=%~dp0python\\python.exe"')
    assert bundled < t.index("python --version"), "المحمول لازم يجي قبل بايثون النظام"
    assert '"%PY%" ' in t or name == "report_problem.bat" and 'if defined PY "%PY%" report_problem.py' in t, name        # تشغيل بالمسار بين اقتباسين (المسار فيه مسافات وأقواس)
    assert not re.search(r"[A-Za-z]:\\", t.replace("https://", "")), "ما في مسار مطلق"


def test_report_problem_bat_is_the_same_in_the_update_folder():
    assert (PKG_SRC / "report_problem.bat").read_bytes() == (PKG2 / "report_problem.bat").read_bytes()


# ============================ التشغيل الفعلي ============================
@pytest.fixture
def portable(tmp_path):
    """نسخة الحزمة الكاملة بمسار عربي فيه مسافات وأقواس و& (مثل الأستاذ): مع مجلد python، وبدون أي ملف زيادة"""
    d = tmp_path / "امتحان (فيزياء) & كيمياء 2026"; d.mkdir()
    for f in (*CODE_FILES, *BATS, "report_problem.py"): shutil.copy(PKG_SRC / f, d / f)
    shutil.copytree(BUNDLED, d / "python")
    pk = Pkg(d); pk.questions(); pk.students(); pk.settings(); return pk


@pytest.fixture
def runs():
    made = []
    def go(*a, **k):
        r = Run(*a, **k); made.append(r); return r
    yield go
    for r in made: r.kill()


def bundled_version(d):
    return subprocess.run([str(d / "python" / "python.exe"), "-c", "import platform; print(platform.python_version())"], capture_output=True, text=True).stdout.strip()


def health(port):
    import json, urllib.request
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health.json", timeout=10).read())


@need_python
def test_start_bat_runs_the_exam_with_the_bundled_python_and_no_system_python(portable, runs):
    port = free_port(); r = runs("start.bat", portable.path, env={"EXAM_PORT": str(port)}, path=NO_SYSTEM_PYTHON)
    assert r.wait_for("Give students this link", 40), r.text[-600:]
    assert health(port)["python"] == bundled_version(portable.path), r.text[-300:]                          # السيرفر شغّال ببايثون المجلد
    assert "not recognized" not in r.text and "Python is not installed" not in r.text


@need_python
def test_check_files_bat_uses_the_bundled_python(portable, runs):
    r = runs("check_files.bat", portable.path, path=NO_SYSTEM_PYTHON); code = r.finish(60)
    assert code == 0 and "OK - the exam files are valid" in r.text, r.text[-500:]
    assert (portable.path / "check_report.txt").exists()


@need_python
def test_report_problem_bat_uses_the_bundled_python(portable, runs):
    r = runs("report_problem.bat", portable.path, path=NO_SYSTEM_PYTHON); code = r.finish(60)
    reps = list(portable.path.glob("problem_report_*.txt"))
    assert code == 0 and len(reps) == 1 and "Python was not found" not in r.text and not (portable.path / "problem_report_no_python.txt").exists(), r.text[-500:]


@need_python
@pytest.mark.skipif(not shutil.which("python"), reason="ما في بايثون نظام لنقارن معه")
def test_bundled_python_wins_even_when_the_system_has_python(portable, runs):
    psutil = pytest.importorskip("psutil")
    port = free_port(); r = runs("start.bat", portable.path, env={"EXAM_PORT": str(port)})                    # PATH عادي: فيه بايثون النظام
    assert r.wait_for("Give students this link", 40), r.text[-600:]
    exes = {p.info["exe"].lower() for p in psutil.process_iter(["exe", "cmdline"]) if p.info["cmdline"] and any("server.py" in c for c in p.info["cmdline"]) and p.info["exe"]}
    mine = str(portable.path / "python" / "python.exe").lower()
    assert mine in exes, exes


@need_python
def test_empty_python_folder_falls_back_to_the_system_python(portable, runs):
    """مجلد python موجود بس ما فيه python.exe (مثلاً مسح الأنتي فايروس الملف): بنرجع لبايثون النظام بدل ما نفشل"""
    for f in (portable.path / "python").iterdir():
        if f.name.lower() == "python.exe": f.unlink()
    port = free_port(); r = runs("start.bat", portable.path, env={"EXAM_PORT": str(port)})
    assert r.wait_for("Give students this link", 40), r.text[-600:]
    assert health(port)["python"]
