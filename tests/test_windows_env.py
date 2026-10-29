"""المرحلة 7: بيئة ويندوز الحقيقية — تشغيل start.bat و check_files.bat كما بيعملها الأستاذ (مسار عربي فيه مسافات وأقواس، بدون بايثون، منفذ مشغول، ترميز settings.txt)."""
import codecs, os, shutil, socket, subprocess, sys, threading, time
import urllib.request

import pytest
from conftest import CODE_FILES, PKG_SRC, Pkg, bank, roster, copy_any

pytestmark = pytest.mark.skipif(os.name != "nt", reason="ويندوز فقط")
SYS32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture
def weird(tmp_path):
    """نسخة من الحزمة (مع start.bat و check_files.bat) بمسار عربي فيه مسافات وأقواس و&"""
    d = tmp_path / "امتحان (فيزياء) & كيمياء 2026"
    d.mkdir()
    for f in (*CODE_FILES, "start.bat", "check_files.bat"):
        copy_any(PKG_SRC / f, d / f)
    pk = Pkg(d); pk.questions(); pk.students(); pk.settings()
    return pk


class Run:
    """يشغّل .bat بدون نافذة، يجمع المخرجات، ويوقفه (مع كل فروعه) لما يوصل شرط معيّن أو ينتهي"""
    def __init__(self, bat, cwd, env=None, path=None):
        e = dict(os.environ, PYTHONUNBUFFERED="1", **(env or {}))      # بدون هاد بايثون بيخزّن المخرجات لما تروح لأنبوب (بالنافذة الحقيقية ما في مشكلة)
        if env is None: e.pop("EXAM_PORT", None)
        if path is not None: e["PATH"] = path
        self.out = []
        full = os.path.join(str(cwd), bat)
        cmdline = f'"{os.path.join(SYS32, "cmd.exe")}" /d /s /c ""{full}""'        # /s: يشيل أول وآخر اقتباس، فالمسار اللي فيه & وأقواس بيشتغل مثل الدبل كليك
        self.p = subprocess.Popen(cmdline, cwd=cwd, env=e, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        self.t = threading.Thread(target=self._read, daemon=True); self.t.start()

    def _read(self):
        for line in iter(self.p.stdout.readline, b""): self.out.append(line.decode("utf-8", "replace"))

    @property
    def text(self): return "".join(self.out)

    def wait_for(self, needle, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if needle in self.text: return True
            if self.p.poll() is not None: time.sleep(0.3); return needle in self.text
            time.sleep(0.1)
        return False

    def finish(self, timeout=20):
        try: self.p.wait(timeout)
        except subprocess.TimeoutExpired: self.kill()
        self.t.join(3); return self.p.returncode

    def kill(self):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.p.pid)], capture_output=True)
        try: self.p.wait(5)
        except Exception: pass


@pytest.fixture
def runs():
    made = []
    def go(*a, **k):
        r = Run(*a, **k); made.append(r); return r
    yield go
    for r in made: r.kill()


def link_of(text):
    import re
    m = re.search(r"Give students this link.*?(http://[\d.]+(?::\d+)?)", text, re.S)
    return m.group(1) if m else None


# ---------------- start.bat / check_files.bat ----------------
def test_start_bat_works_in_weird_arabic_path(weird, runs):
    port = free_port()
    r = runs("start.bat", weird.path, env={"EXAM_PORT": str(port)})
    assert r.wait_for("Give students this link"), r.text
    assert r.wait_for("Results saved"), r.text
    link = link_of(r.text); assert link and link.endswith(f":{port}"), r.text
    body = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode("utf-8")
    assert "اختبار الوحدة" in body and "طالب أ1" in body
    assert "Exam: " in r.text and "8 of 11 questions" in r.text and "5 students" in r.text
    assert "WARNING" not in r.text.split("Teacher pages")[0]


def test_start_bat_warns_about_default_password(weird, runs):
    weird.settings(**{"كلمة_سر_المعلم": "1234"})
    r = runs("start.bat", weird.path, env={"EXAM_PORT": str(free_port())})
    assert r.wait_for("default 1234"), r.text


def test_start_bat_warns_when_no_password(weird, runs):
    weird.settings(**{"كلمة_سر_المعلم": ""})
    r = runs("start.bat", weird.path, env={"EXAM_PORT": str(free_port())})
    assert r.wait_for("no teacher password"), r.text


def test_check_files_bat_ok_in_weird_path(weird, runs):
    r = runs("check_files.bat", weird.path); code = r.finish()
    assert code == 0 and "OK - the exam files are valid" in r.text and "Full report saved to" in r.text, r.text
    assert (weird.path / "check_report.txt").exists()


def test_start_bat_with_broken_files_shows_english_banner_and_error_file(weird, runs):
    rows = bank(); rows[0][5] = "ز"; weird.questions(rows)
    r = runs("start.bat", weird.path, env={"EXAM_PORT": str(free_port())})
    assert r.wait_for("SERVER IS RUNNING"), r.text                                          # وضع التجهيز: السيرفر شغّال وصفحة «الملفات» فيها الخطأ
    assert "has an error" in r.text and "/files" in r.text and "Give students this link" not in r.text
    assert "سطر 2" in (weird.path / "exam_error.txt").read_text(encoding="utf-8-sig")


def test_start_bat_missing_data_gives_actionable_hint(weird, runs):
    for n in ("questions.xlsx", "students.xlsx", "settings.txt"): (weird.path / n).unlink()
    r = runs("start.bat", weird.path, env={"EXAM_PORT": str(free_port())})
    assert r.wait_for("not uploaded yet"), r.text                                           # وضع التجهيز: بيقول للمعلم يرفع الملفات من صفحة «الملفات»
    assert "SERVER IS RUNNING" in r.text and "/files" in r.text and "Next step" in r.text


def test_start_bat_unpacks_zip_dropped_next_to_server(weird, runs):
    import io, zipfile
    from conftest import Q_HEAD, S_HEAD, DEFAULT_SETTINGS
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        for name, head, rows in (("questions.xlsx", Q_HEAD, bank()), ("students.xlsx", S_HEAD, roster())):
            weird.write_xlsx("_t.xlsx", head, rows); zf.write(weird.p("_t.xlsx"), name); weird.p("_t.xlsx").unlink()
        zf.writestr("settings.txt", "\n".join(f"{k} = {v}" for k, v in {**DEFAULT_SETTINGS, "عنوان_الامتحان": "من الزيب"}.items()))
    for n in ("questions.xlsx", "students.xlsx", "settings.txt"): (weird.path / n).unlink()
    (weird.path / "exam_data.zip").write_bytes(z.getvalue())
    port = free_port(); r = runs("start.bat", weird.path, env={"EXAM_PORT": str(port)})
    assert r.wait_for("Give students this link"), r.text
    assert "من الزيب" in urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode("utf-8")


def test_port_busy_falls_back_to_8000(weird, runs):
    s8000 = socket.socket()
    try: s8000.bind(("0.0.0.0", 8000))
    except OSError: pytest.skip("المنفذ 8000 مستخدم أصلاً بالجهاز")
    s8000.close()
    busy = socket.socket(); busy.bind(("0.0.0.0", 0)); busy.listen(1); p = busy.getsockname()[1]
    try:
        r = runs("start.bat", weird.path, env={"EXAM_PORT": str(p)})
        assert r.wait_for("Give students this link"), r.text
        assert link_of(r.text).endswith(":8000"), r.text
        assert b"" != urllib.request.urlopen("http://127.0.0.1:8000/", timeout=5).read()
    finally:
        busy.close()


# ---------------- Python غير موجود / غير مفعّل بالـ PATH ----------------
def test_no_python_anywhere_shows_install_hint_and_exits(weird, runs):
    r = runs("start.bat", weird.path, path=SYS32); code = r.finish(15)
    assert "not recognized" in r.text.lower() or "is not recognized" in r.text.lower()
    assert "Python is not installed" in r.text and "Add Python to PATH" in r.text and code is not None


def _fake_store_stub(tmp_path):
    """مثل Windows بدون بايثون: python.exe بمجلد WindowsApps بيفشل دايماً (نسخة من find.exe بترجّع خطأ). exe مش .cmd عشان تتصرف مثل بديل المتجر الحقيقي"""
    d = tmp_path / "WindowsApps"; d.mkdir()
    shutil.copy(os.path.join(SYS32, "find.exe"), d / "python.exe")
    return str(d)


# كانت مشكلة (python وهمي من المتجر يمنع الرجوع لـ py): أُصلحت بـ start.bat/check_files.bat


@pytest.mark.skipif(not os.path.exists(r"C:\Windows\py.exe"), reason="py launcher غير موجود")
def test_store_stub_python_falls_back_to_py_launcher(weird, runs, tmp_path):
    """السيناريو الواقعي لأستاذ ثبّت بايثون بدون Add to PATH: python = بديل المتجر الفاشل لكن py launcher شغّال، فالمفروض start.bat يجرّب py"""
    stub = _fake_store_stub(tmp_path)
    r = runs("start.bat", weird.path, env={"EXAM_PORT": str(free_port())}, path=stub + os.pathsep + SYS32 + os.pathsep + r"C:\Windows")
    assert r.wait_for("Give students this link", timeout=12), "start.bat استعمل python الوهمي وما جرّب py:\n" + r.text


def test_check_files_bat_same_python_fallback(weird, runs, tmp_path):
    stub = _fake_store_stub(tmp_path)
    r = runs("check_files.bat", weird.path, path=stub + os.pathsep + SYS32 + os.pathsep + r"C:\Windows"); r.finish(15)
    assert "OK - the exam files are valid" in r.text, r.text


# ---------------- ترميز الملفات كما بيحفظها المفكرة ----------------
@pytest.mark.parametrize("enc,nl", [("utf-8", "\n"), ("utf-8", "\r\n"), ("utf-8-sig", "\r\n"), ("cp1256", "\r\n")])
def test_settings_saved_by_notepad_variants(pkg, enc, nl):
    text = nl.join(["# إعدادات", "عنوان_الامتحان = اختبار عربي", "المدة_بالدقائق = 25", "عدد_الأسئلة_الصعبة = 2", "عدد_الأسئلة_المتوسطة = 3", "عدد_الأسئلة_السهلة = 3", ""])
    pkg.p("settings.txt").write_bytes(text.encode(enc))
    m = pkg.load()
    assert m.SET["title"] == "اختبار عربي" and m.SET["minutes"] == 25


@pytest.mark.parametrize("bom,enc", [(codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")])
def test_settings_saved_as_utf16(pkg, bom, enc):
    """المفكرة بخيار «Unicode» بتحفظ UTF-16 مع BOM: لازم يشتغل (كان يعطي «اسم غير معروف» بحروف مشوّهة)"""
    text = (chr(13) + chr(10)).join(["عنوان_الامتحان = اختبار", "المدة_بالدقائق = 25", "عدد_الأسئلة_الصعبة = 2", "عدد_الأسئلة_المتوسطة = 3", "عدد_الأسئلة_السهلة = 3", ""])
    pkg.p("settings.txt").write_bytes(bom + text.encode(enc))
    m = pkg.load()
    assert m.SET["title"] == "اختبار" and m.SET["minutes"] == 25


def test_csv_saved_by_excel_arabic_windows(pkg):
    """Excel بالعربي بيحفظ CSV بـ cp1256 وفاصلة منقوطة"""
    from conftest import Q_HEAD
    pkg.p("questions.xlsx").unlink()
    lines = [";".join(Q_HEAD)] + [";".join(str(c) for c in r) for r in bank()]
    pkg.p("questions.csv").write_bytes("\r\n".join(lines).encode("cp1256"))
    assert len(pkg.load().QLIST) == 11


def test_xlsx_with_extra_sheets_and_formulas_values(pkg):
    """ملف Excel فيه أكثر من ورقة، وخلايا ناتجة عن صيغة: لازم يقرأ الورقة الأولى والقيم المحسوبة"""
    import openpyxl
    from conftest import Q_HEAD
    wb = openpyxl.Workbook(); ws = wb.active; ws.append(Q_HEAD)
    for r in bank(): ws.append(r)
    wb.create_sheet("ملاحظات").append(["هذه ورقة ثانية يجب تجاهلها"])
    wb.save(pkg.p("questions.xlsx"))
    assert len(pkg.load().QLIST) == 11
