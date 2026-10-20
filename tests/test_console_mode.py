"""وضع «نافذة ويندوز ما بتعرض العربي»: بانر إنجليزي نظيف، exam_info.txt بالعربي (بيتفتح بالمفكرة)، وexam_log.txt لأحداث الطلاب.
EXAM_NO_ARABIC_CONSOLE=1 بيفرض الوضع على أنبوب (بدون نافذة حقيقية)، وآخر اختبار بيشغّل نافذة CMD حقيقية (بتظهر ثواني)."""
import json, os, re, socket, subprocess, sys, time

import pytest
from conftest import bank, roster
from test_http import Server, free_port, PKG_PYTHON
from test_windows_env import Run

ARABIC = re.compile("[\u0600-\u06FF]")


class Live:
    """سيرفر شغّال بالوضع المفروض: بنجمع المخرجات (بدون عربي) ونقدر نكلّمه عبر HTTP"""
    def __init__(self, pkg, force=True, extra_env=None):
        self.pkg, self.port, self.out, self.proc = pkg, free_port(), [], None
        env = dict(os.environ, EXAM_PORT=str(self.port), PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8"); env.pop("EXAM_NO_ARABIC_CONSOLE", None)
        if force: env["EXAM_NO_ARABIC_CONSOLE"] = "1"
        env.update(extra_env or {})
        self.proc = subprocess.Popen([PKG_PYTHON, "-X", "utf8", "server.py"], cwd=pkg.path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        import threading
        threading.Thread(target=self._read, daemon=True).start()
        self.web = Server(pkg); self.web.port = self.port

    def _read(self):
        for line in iter(self.proc.stdout.readline, b""): self.out.append(line.decode("utf-8", "replace"))

    @property
    def text(self): return "".join(self.out)

    def wait_for(self, needle, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            if needle in self.text: return True
            if self.proc.poll() is not None: time.sleep(0.3); return needle in self.text
            time.sleep(0.1)
        return False

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(5)
            except subprocess.TimeoutExpired: self.proc.kill()


@pytest.fixture
def live(pkg):
    made = []
    def make(**kw):
        l = Live(pkg, **kw); made.append(l); return l
    yield make
    for l in made: l.stop()


# ============================ البانر وexam_info.txt ============================
def test_console_banner_is_pure_ascii_and_info_file_has_arabic(pkg, live):
    pkg.settings(**{"كلمة_سر_المعلم": "1234", "رمز_الدخول": "نعم"})
    l = live(); assert l.wait_for("To stop: Ctrl+C"), l.text
    assert not ARABIC.search(l.text), l.text                                                 # ولا حرف عربي على الشاشة
    assert re.search(rf"http://[\d.]+:{l.port}\b", l.text) and "Give students this link" in l.text and "Monitor" in l.text and "Codes" in l.text
    assert "WARNING: teacher password is the default 1234" in l.text and "exam_info.txt" in l.text and "exam_log.txt" in l.text
    assert "8 of 11 questions" in l.text and "30 min" in l.text and "5 students" in l.text
    info = pkg.p("exam_info.txt").read_text(encoding="utf-8-sig")
    assert pkg.p("exam_info.txt").read_bytes()[:3] == b"\xef\xbb\xbf"                         # BOM: المفكرة بتعرفه UTF-8
    for need in ("الامتحان شغّال", "رابط الامتحان لتعطيه للطلاب", f":{l.port}", f"http://localhost:{l.port}/monitor", f"/codes", "⚠ كلمة سر المعلم هي الافتراضية (1234)",
                 "أسئلة الامتحان: 8 من 11 سؤال بالبنك", "المدة: 30 دقيقة", "عدد الطلاب: 5", "exam_log.txt", "Ctrl+C", "results.csv"):
        assert need in info, need


def test_info_file_without_codes_and_with_strong_password(pkg, live):
    pkg.settings(**{"كلمة_سر_المعلم": "Str0ng!pass"})
    l = live(); assert l.wait_for("To stop: Ctrl+C")
    info = pkg.p("exam_info.txt").read_text(encoding="utf-8-sig")
    assert "/codes" not in info and "⚠" not in info and "Str0ng" not in info and "WARNING" not in l.text           # وكلمة السر نفسها ما بتنكتب
    assert "(بكلمة سر المعلم)" in info


def test_no_password_warning_in_both_places(pkg, live):
    pkg.settings(**{"كلمة_سر_المعلم": ""})
    l = live(); assert l.wait_for("To stop: Ctrl+C")
    assert "WARNING: no teacher password" in l.text and "ما في كلمة سر للمعلم" in pkg.p("exam_info.txt").read_text(encoding="utf-8-sig")


def test_port_fallback_reflected_in_info_file(pkg, live):
    busy = socket.socket(); busy.bind(("0.0.0.0", 0)); busy.listen(1); p = busy.getsockname()[1]
    s8000 = socket.socket()
    try: s8000.bind(("0.0.0.0", 8000))
    except OSError: busy.close(); pytest.skip("8000 مشغول")
    s8000.close()
    try:
        l = live(extra_env={"EXAM_PORT": str(p)}); assert l.wait_for("To stop: Ctrl+C")
        assert ":8000" in l.text and ":8000/monitor" in pkg.p("exam_info.txt").read_text(encoding="utf-8-sig")
    finally:
        busy.close()


# ============================ سجل الأحداث exam_log.txt ============================
def test_student_events_go_to_log_not_console(pkg, live):
    l = live(); assert l.wait_for("To stop: Ctrl+C")
    w = l.web
    k, st, p = w.start_student("d1"); w.submit(k, "d1", p["ids"], w.correct_answers(p["ids"]))
    k2, _, p2 = w.start_student("d2", n="طالب أ2"); w.teacher(extend=3, scope="all"); w.teacher(message="مرحبا"); w.teacher(release=k2)
    time.sleep(0.5)
    assert not ARABIC.search(l.text), l.text                                                  # الشاشة نظيفة
    raw = pkg.p("exam_log.txt").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and raw.count(b"\xef\xbb\xbf") == 1                # BOM مرة وحدة بأول الملف
    log = raw.decode("utf-8-sig")
    for need in ("بدأ: طالب أ1", "استلمت: أ طالب أ1 8 / 8", "بدأ: طالب أ2", "تمديد 3 د (all)", "رسالة للطلاب: مرحبا", "فك حجز: طالب أ2"):
        assert need in log, (need, log)
    assert all(re.match(r"\d\d:\d\d:\d\d  ", ln) for ln in log.splitlines() if ln.strip())      # كل سطر بوقت


def test_warnings_show_ascii_notice_on_console(pkg, live):
    rows = bank(); rows[0][0] = "شاهد [img:big.png]"; pkg.questions(rows); pkg.image("big.png", b"\x89PNG\r\n\x1a\n" + b"0" * 600 * 1024)
    l = live(); assert l.wait_for("To stop: Ctrl+C")
    assert "[!]" in l.text and "exam_log.txt" in l.text and not ARABIC.search(l.text)
    assert "تنبيه: الصورة «big.png»" in pkg.p("exam_log.txt").read_text(encoding="utf-8-sig")


def test_zip_unpack_message_goes_to_log(pkg, live):
    import io, zipfile
    from conftest import Q_HEAD, S_HEAD, DEFAULT_SETTINGS
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        for name, head, rows in (("questions.xlsx", Q_HEAD, bank()), ("students.xlsx", S_HEAD, roster())):
            pkg.write_xlsx("_t.xlsx", head, rows); zf.write(pkg.p("_t.xlsx"), name); pkg.p("_t.xlsx").unlink()
        zf.writestr("settings.txt", "\n".join(f"{k} = {v}" for k, v in DEFAULT_SETTINGS.items()))
    pkg.p("exam_data.zip").write_bytes(z.getvalue())
    l = live(); assert l.wait_for("To stop: Ctrl+C") and not ARABIC.search(l.text)
    assert "تم فك exam_data.zip: 3 ملف" in pkg.p("exam_log.txt").read_text(encoding="utf-8-sig")


def test_error_path_in_forced_mode(pkg, live):
    rows = bank(); rows[0][5] = "ز"; pkg.questions(rows)
    l = live(); l.proc.wait(15)
    assert "PROBLEM WITH THE EXAM FILES" in l.text and not ARABIC.search(l.text) and "exam_error.txt" in l.text
    assert "سطر 2" in pkg.p("exam_error.txt").read_text(encoding="utf-8-sig") and "سطر 2" in pkg.p("exam_log.txt").read_text(encoding="utf-8-sig")


def test_normal_mode_unchanged_when_not_forced(pkg, live):
    """بدون الوضع (أنبوب/اختبارات/تشغيل من أداة): نفس المخرجات ثنائية اللغة القديمة وما بيكتب ملفات جديدة"""
    l = live(force=False); assert l.wait_for("To stop: Ctrl+C")
    assert "اعطِ الطلاب هذا الرابط" in l.text and "Give students this link" in l.text
    assert not pkg.p("exam_info.txt").exists() and not pkg.p("exam_log.txt").exists()
    l.web.start_student("d1"); time.sleep(0.4)
    assert "بدأ: طالب أ1" in l.text and not pkg.p("exam_log.txt").exists()


def test_start_bat_in_forced_mode_has_no_boxes(pkg, tmp_path):
    import shutil
    from conftest import CODE_FILES, PKG_SRC
    d = tmp_path / "امتحان (تجربة) & 1"; d.mkdir()
    for f in (*CODE_FILES, "start.bat"): shutil.copy(PKG_SRC / f, d / f)
    for n in ("questions.xlsx", "students.xlsx", "settings.txt"): shutil.copy(pkg.p(n), d / n)
    r = Run("start.bat", d, env={"EXAM_PORT": str(free_port()), "EXAM_NO_ARABIC_CONSOLE": "1"})
    try:
        assert r.wait_for("To stop: Ctrl+C"), r.text
        assert not ARABIC.search(r.text) and (d / "exam_info.txt").exists()
    finally:
        r.kill()


# ============================ نافذة CMD حقيقية (بتظهر على الشاشة ثواني) ============================
@pytest.mark.skipif(os.name != "nt", reason="ويندوز فقط")
def test_real_console_window_opens_info_file_in_notepad(pkg, tmp_path):
    import shutil
    from conftest import CODE_FILES, PKG_SRC
    d = tmp_path / "real console تجربة"; d.mkdir()
    for f in (*CODE_FILES, "start.bat"): shutil.copy(PKG_SRC / f, d / f)
    for n in ("questions.xlsx", "students.xlsx", "settings.txt"): shutil.copy(pkg.p(n), d / n)
    env = dict(os.environ, EXAM_PORT=str(free_port())); env.pop("EXAM_NO_ARABIC_CONSOLE", None)
    cmdline = f'"{os.path.join(os.environ.get("SystemRoot", "C:/Windows"), "System32", "cmd.exe")}" /d /s /c ""{d / "start.bat"}""'
    proc = subprocess.Popen(cmdline, cwd=d, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)         # نافذة حقيقية = isatty صحيح، بدون أي إجبار
    notepad_pids = []
    try:
        for _ in range(100):
            if (d / "exam_info.txt").exists() and (d / "exam_info.txt").stat().st_size > 100: break
            time.sleep(0.2)
        assert (d / "exam_info.txt").exists(), "السيرفر ما كتب exam_info.txt بالنافذة الحقيقية"
        info = (d / "exam_info.txt").read_text(encoding="utf-8-sig"); assert "رابط الامتحان لتعطيه للطلاب" in info
        time.sleep(2.5)                                                                                  # المفكرة تنفتح
        ps = "Get-CimInstance Win32_Process -Filter \"Name='notepad.exe'\" | Where-Object { $_.CommandLine -like '*exam_info.txt*' } | ForEach-Object { $_.ProcessId }"
        out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.split()
        notepad_pids = [int(x) for x in out]
        assert notepad_pids, "المفكرة ما انفتحت على exam_info.txt"
    finally:
        for pid in notepad_pids: subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)       # بس مفكرة هالملف
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)


# ============================ الإخراج المخفي (NUL) مش نافذة ============================
def _notepads_for(path_fragment):
    ps = f"Get-CimInstance Win32_Process -Filter \"Name='notepad.exe'\" | Where-Object {{ $_.CommandLine -like '*{path_fragment}*' }} | ForEach-Object {{ $_.ProcessId }}"
    return [int(x) for x in subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.split()]


@pytest.mark.skipif(os.name != "nt", reason="ويندوز فقط")
def test_hidden_stdout_nul_is_not_a_console_and_never_opens_notepad(pkg):
    """على ويندوز isatty() بترجع True لـ NUL: لما انشغّل السيرفر بإخراج مخفي (اختبارات/أداة) فتح مئة مفكرة. لازم يعتمد على GetConsoleMode"""
    frag = pkg.path.name
    s = Server(pkg).start()                                                                  # stdout = DEVNULL
    try:
        time.sleep(1.2)
        assert not pkg.p("exam_info.txt").exists() and not pkg.p("exam_log.txt").exists()
        s.start_student("d1"); time.sleep(0.3)
        assert not pkg.p("exam_log.txt").exists()
    finally:
        s.stop()
        for pid in _notepads_for(frag): subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)       # تنظيف احتياطي لو انكسر الإصلاح
    assert _notepads_for(frag) == [] and not [p for p in _notepads_for("pytest-of-T-User")]


@pytest.mark.skipif(os.name != "nt", reason="ويندوز فقط")
def test_hidden_stdout_with_broken_files_does_not_open_notepad_either(pkg):
    rows = bank(); rows[0][5] = "ز"; pkg.questions(rows)
    with pytest.raises(RuntimeError):
        Server(pkg).start()
    time.sleep(0.8)
    pids = _notepads_for(pkg.path.name)
    for pid in pids: subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    assert pids == []
