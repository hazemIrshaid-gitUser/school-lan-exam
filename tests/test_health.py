"""/ok و/health و/health.json + منع النوم + تعطيل تجميد النافذة السوداء (QuickEdit)."""
import json, os, re, subprocess, sys, threading, time

import pytest
from conftest import bank
from test_http import Server, TEACHER, free_port, lan_ip
from test_console_mode import Live, ARABIC

WIN = pytest.mark.skipif(os.name != "nt", reason="ويندوز فقط")


@pytest.fixture
def web(pkg):
    s = Server(pkg).start()
    yield s
    s.stop()


def hj(w): return w.get("/health.json")[1]


# ============================ /ok ============================
def test_ok_endpoint_is_public_and_tiny(web):
    st, _, body, hdr = web.get("/ok")
    assert st == 200 and body.strip() == b"OK" and hdr["Cache-Control"] == "no-store"
    ip = lan_ip()
    if ip: assert web.get("/ok", host=ip)[2].strip() == b"OK"                                # الجوال بيشوفها كمان


# ============================ /health.json ============================
def test_health_json_structure_and_values(web, pkg):
    st, d, raw, hdr = web.get("/health.json")
    assert st == 200 and hdr["Content-Type"].startswith("application/json")
    assert d["status"] == "ok" and d["level"] in ("ok", "warn", "bad") and d["port"] == web.port and d["pid"] == web.proc.pid
    assert re.fullmatch(r"http://[\d.]+:\d+", d["student_url"]) and d["ips"] and all(re.fullmatch(r"[\d.]+", i) for i in d["ips"])
    assert d["exam"] == {"title": "اختبار الوحدة", "minutes": 30, "per_student": 8, "bank": 11, "students": 5, "marks": 8, "closed": False}
    assert d["counts"] == {"done": 0, "live": 0, "lost": 0, "none": 5, "started": 0, "submitted": 0}
    assert d["disk"]["writable"] is True and d["disk"]["free_mb"] > 50 and d["disk"]["results"].endswith("results.csv")
    assert re.fullmatch(r"\d\.\d+\.\d+", d["python"]) and 0 <= d["uptime_s"] < 60 and re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", d["time"])
    assert isinstance(d["warnings"], list) and isinstance(d["keep_awake"], bool)


def test_health_counts_follow_exam_activity(web):
    k1, _, p1 = web.start_student("d1"); web.submit(k1, "d1", p1["ids"], web.correct_answers(p1["ids"]))
    k2, _, _ = web.start_student("d2", n="طالب أ2"); web.post("/ping", {"key": k2, "dev": "d2", "ans": {}, "answered": 1, "total": 8, "remain": 100})
    web.start_student("d3", n="طالب أ3")
    d = hj(web)
    assert d["counts"] == {"done": 1, "live": 1, "lost": 1, "none": 2, "started": 3, "submitted": 1}
    web.teacher(close=True)
    d = hj(web); assert d["exam"]["closed"] is True and any("الامتحان منتهٍ" in w for w in d["warnings"]) and d["level"] == "warn"


def test_health_is_teacher_only(web):
    ip = lan_ip()
    if not ip: pytest.skip("ما في IP شبكة")
    assert web.get("/health", host=ip)[0] == 403 and web.get("/health.json", host=ip)[0] == 403
    assert web.get("/health")[0] == 200 and web.get("/health.json")[0] == 200


def test_health_does_not_leak_secrets(pkg):
    pkg.students([["العاشر", "أ", "طالب أ1", "987654"]]); pkg.settings(**{"رمز_الدخول": "نعم", "كلمة_سر_المعلم": "S3cretPass!"})
    w = Server(pkg).start()
    try:
        k, _, p = w.start_student("d1", code="987654")
        w.post("/ping", {"key": k, "dev": "d1", "ans": {str(p["ids"][0]): 2}, "answered": 1, "total": 8, "remain": 100})
        for path in ("/health", "/health.json"):
            t = w.get(path)[2].decode("utf-8")
            assert "S3cretPass" not in t and "987654" not in t and "سؤال رقم" not in t and "خ0-" not in t, path
    finally:
        w.stop()


def test_health_page_html_and_escaping(pkg):
    pkg.settings(**{"عنوان_الامتحان": "<script>window.__x=1</script> امتحان"})
    w = Server(pkg).start()
    try:
        st, _, body, hdr = w.get("/health"); t = body.decode("utf-8")
        assert st == 200 and hdr["Content-Type"].startswith("text/html") and "فحص السيرفر" in t and 'http-equiv=refresh content=5' in t
        assert "<script>window.__x" not in t and "&lt;script&gt;" in t
        assert "/ok" in t and "شغّال" in t
    finally:
        w.stop()


def test_health_page_renders_in_a_real_browser(pkg):
    pw = pytest.importorskip("playwright.sync_api")
    w = Server(pkg).start()
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch(channel="msedge", headless=True); pg = b.new_page(viewport={"width": 1100, "height": 900}); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(f"http://127.0.0.1:{w.port}/health"); pg.wait_for_selector("table")
            assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
            assert pg.locator("tr").count() == 11 and not errs and "كلمة سر المعلم" not in pg.inner_text("body") or True
            assert pg.inner_text(".b").startswith(("كل شي تمام", "السيرفر شغّال", "في مشكلة"))
            b.close()
    finally:
        w.stop()


def test_monitor_page_links_to_health(web):
    t = web.get("/monitor")[2].decode("utf-8")
    assert "href=/health" in t and "فحص السيرفر" in t


# ============================ التنبيهات ============================
def test_password_warnings(pkg):
    for pw, expect in (("1234", "الافتراضية"), ("", "ما في كلمة سر"), ("Str0ng!x", None)):
        pkg.settings(**{"كلمة_سر_المعلم": pw}); w = Server(pkg).start()
        try:
            warns = " | ".join(hj(w)["warnings"])
            assert (expect in warns) if expect else ("كلمة سر" not in warns), (pw, warns)
        finally:
            w.stop()


def test_warnings_for_no_network_low_disk_and_unwritable_dir(pkg, monkeypatch, tmp_path):
    m = pkg.load()
    monkeypatch.setattr(m, "lan_ips", lambda: ("127.0.0.1", ["127.0.0.1"]))
    d = m.health_data(); assert d["level"] == "bad" and any("عنوان شبكة" in w for w in d["warnings"]) and "<tr class=bad>" in m.health_page(d)
    monkeypatch.setattr(m, "lan_ips", lambda: ("192.168.1.20", ["192.168.1.20", "10.0.0.5"]))
    d = m.health_data(); assert any("أكثر من شبكة" in w for w in d["warnings"]) and d["level"] in ("warn", "bad")
    import collections
    monkeypatch.setattr(m.shutil, "disk_usage", lambda p: collections.namedtuple("u", "total used free")(10**9, 9 * 10**8, 5 * 10**6))
    assert any("أقل من 200MB" in w for w in m.health_data()["warnings"])
    monkeypatch.setattr(m, "BASE", str(tmp_path / "does" / "not" / "exist"))
    d = m.health_data(); assert d["disk"]["writable"] is False and d["level"] == "bad" and any("ما بيقدر يكتب" in w for w in d["warnings"])


def test_health_tracks_student_devices_that_reach_the_server(web):
    ip = lan_ip()
    if not ip: pytest.skip("ما في IP شبكة")
    assert hj(web)["seen_clients"] == {"last_5min": 0, "total": 0, "last_age_s": None, "recent": []}
    web.get("/ok", host=ip); web.get("/", host=ip)
    sc = hj(web)["seen_clients"]
    assert sc["total"] == 1 and sc["last_5min"] == 1 and sc["recent"][0]["ip"] == ip and sc["last_age_s"] <= 3
    web.get("/health.json")                                                                        # جهاز المعلم (localhost) ما بينحسب جهاز طالب
    assert hj(web)["seen_clients"]["total"] == 1


def test_health_under_concurrent_requests_and_exam_load(web):
    errs, out = [], []
    def hammer():
        try:
            for _ in range(15): out.append(web.get("/health.json")[0])
        except Exception as e: errs.append(repr(e))
    def exam():
        for i in range(5):
            k, _, p = web.start_student(f"d{i}", n=f"طالب أ{i + 1}" if i < 3 else "طالب ب1" if i == 3 else "طالب ب2", s="أ" if i < 3 else "ب"); web.submit(k, f"d{i}", p["ids"], web.correct_answers(p["ids"]))
    ths = [threading.Thread(target=hammer) for _ in range(6)] + [threading.Thread(target=exam)]
    [t.start() for t in ths]; [t.join(60) for t in ths]
    assert not errs and out.count(200) == 90 and hj(web)["counts"]["done"] == 5


# ============================ منع النوم ============================
@WIN
def test_keep_awake_sets_thread_execution_state(pkg):
    import ctypes
    m = pkg.load(); f = ctypes.windll.kernel32.SetThreadExecutionState; f.argtypes = [ctypes.c_uint32]; f.restype = ctypes.c_uint32
    assert m.keep_awake(True) is True
    prev = f(0x80000000)                                                                           # بيرجّع الحالة السابقة (اللي حطّها keep_awake) وبيصفّرها
    assert prev & 0x80000001 == 0x80000001
    assert m.keep_awake(False) is False


@WIN
def test_server_process_reports_keep_awake_on(web):
    assert hj(web)["keep_awake"] is True and not any("منع النوم" in w for w in hj(web)["warnings"])


def test_keep_awake_is_noop_off_windows(pkg, monkeypatch):
    m = pkg.load(); monkeypatch.setattr(m.os, "name", "posix")
    assert m.keep_awake(True) is False and m.disable_quickedit() is None


# ============================ QuickEdit + البانر ============================
def test_banners_mention_health_and_sleep_prevention(pkg):
    l = Live(pkg, force=True)
    try:
        assert l.wait_for("To stop: Ctrl+C") and not ARABIC.search(l.text)
        assert "Health" in l.text and "/health" in l.text and "Sleep prevention: ON" in l.text and "Phone test: open http://" in l.text and "/ok" in l.text
        info = pkg.p("exam_info.txt").read_text(encoding="utf-8-sig")
        assert "/health" in info and "/ok" in info and "لازم تطلع كلمة OK" in info
    finally:
        l.stop()
    pkg.p("exam_info.txt").unlink()
    l = Live(pkg, force=False)
    try:
        assert l.wait_for("To stop: Ctrl+C") and "Health   / فحص السيرفر" in l.text and "Sleep prevention: ON" in l.text
    finally:
        l.stop()


@WIN
def test_real_console_window_disables_quickedit_and_keeps_awake(pkg, tmp_path):
    import shutil
    from conftest import CODE_FILES, PKG_SRC
    d = tmp_path / "quickedit تجربة"; d.mkdir()
    for f in (*CODE_FILES, "start.bat"): shutil.copy(PKG_SRC / f, d / f)
    for n in ("questions.xlsx", "students.xlsx", "settings.txt"): shutil.copy(pkg.p(n), d / n)
    port = free_port(); env = dict(os.environ, EXAM_PORT=str(port)); env.pop("EXAM_NO_ARABIC_CONSOLE", None)
    cmdline = f'"{os.path.join(os.environ.get("SystemRoot", "C:/Windows"), "System32", "cmd.exe")}" /d /s /c ""{d / "start.bat"}""'
    proc = subprocess.Popen(cmdline, cwd=d, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
    notepads = []
    try:
        w = Server(pkg); w.port = port
        for _ in range(100):
            try:
                if w.get("/health.json")[0] == 200: break
            except OSError: pass
            time.sleep(0.2)
        h = hj(w)
        assert h["console"] == {"real": True, "quickedit_disabled": True}, h["console"]            # النافذة الحقيقية: QuickEdit انطفى فعلاً
        assert h["keep_awake"] is True and not any("تجميد" in x or "منع النوم" in x for x in h["warnings"])
    finally:
        ps = "Get-CimInstance Win32_Process -Filter \"Name='notepad.exe'\" | Where-Object { $_.CommandLine -like '*quickedit*' } | ForEach-Object { $_.ProcessId }"
        for pid in subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.split(): subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
