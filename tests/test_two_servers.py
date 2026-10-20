"""امتحانان بنفس الوقت على جهاز واحد (نسختان من مجلد الحزمة): كل سيرفر لازم يأخذ منفذه الخاص، والنسخة الثانية ترجع تلقائياً لأول منفذ فاضي (8000 ثم 8001...).
على ويندوز http.server بيفتح المنفذ بـ SO_REUSEADDR، وبهالخاصية سيرفران بيفتحوا نفس المنفذ بدون خطأ (والطلبات بتتوزّع بينهم عشوائياً)، فما كان يكفي نعتمد على فشل bind؛
صرنا نتأكد بمحاولة اتصال قبل الفتح (وبعد إعادة تشغيل سيرفر وقف قبل شوي ما في مين بيسمع، فإعادة التشغيل الفورية بتضل على نفس المنفذ)."""
import json, os, re, shutil, socket, time, urllib.request

import pytest
from conftest import CODE_FILES, PKG_SRC, Pkg
from test_http import Server, free_port


def make_copy(tmp_path, name):
    d = tmp_path / name; d.mkdir()
    for f in CODE_FILES: shutil.copy(PKG_SRC / f, d / f)
    pk = Pkg(d); pk.questions(); pk.students(); pk.settings(); return pk


def start(pkg, port):
    """بيشغّل السيرفر بدون ما ينتظر المنفذ المطلوب (ممكن يكون مشغول بسيرفر ثاني)، وبيرجّع (الكائن، المنفذ اللي فتحه فعلاً من exam_info.txt)"""
    s = Server(pkg); env = dict(os.environ, EXAM_PORT=str(port), PYTHONIOENCODING="utf-8", EXAM_NO_ARABIC_CONSOLE="1")        # هالوضع بيكتب الرابط بـ exam_info.txt (بدون ما يفتح المفكرة لأن الإخراج مخفي)
    import subprocess, sys
    s.proc = subprocess.Popen([sys.executable, "-X", "utf8", "server.py"], cwd=pkg.path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    info = pkg.p("exam_info.txt")
    for _ in range(150):
        if s.proc.poll() is not None: raise RuntimeError("السيرفر وقف: " + (pkg.p("exam_error.txt").read_text(encoding="utf-8-sig") if pkg.p("exam_error.txt").exists() else ""))
        if info.exists() and "http://" in info.read_text(encoding="utf-8-sig", errors="replace"): break
        time.sleep(0.1)
    m = re.search(r"http://[\d.]+(?::(\d+))?", info.read_text(encoding="utf-8-sig"))
    s.port = int(m.group(1) or 80); return s


def pid_on(port):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/health.json", timeout=10).read())["pid"]


@pytest.fixture
def made():
    servers = []
    yield servers
    for s in servers: s.stop()


def test_a_second_copy_does_not_share_the_port_of_the_first(tmp_path, made):
    p1 = make_copy(tmp_path, "امتحان 1"); p2 = make_copy(tmp_path, "امتحان 2"); want = free_port()
    s1 = start(p1, want); made.append(s1); s2 = start(p2, want); made.append(s2)
    assert s1.port == want and s2.port != want and 8000 <= s2.port <= 8009, (s1.port, s2.port)                  # الثاني أخذ منفذ غيره
    for _ in range(6):                                                                                       # وكل منفذ بيرد عليه سيرفره هو (مش بالتناوب بين الاثنين)
        assert pid_on(s1.port) == s1.proc.pid and pid_on(s2.port) == s2.proc.pid


def test_three_copies_get_three_different_ports(tmp_path, made):
    pk = [make_copy(tmp_path, f"امتحان {i}") for i in (1, 2, 3)]; want = free_port(); got = []
    for p in pk:
        s = start(p, want); made.append(s); got.append(s)
    assert len({s.port for s in got}) == 3, [s.port for s in got]
    assert all(pid_on(s.port) == s.proc.pid for s in got)


def test_restart_right_after_a_stop_keeps_the_same_port(tmp_path, made):
    """خطة الطوارئ: وقف السيرفر وانشغّل من جديد فوراً بنفس المجلد: لازم يرجع لنفس المنفذ (رابط الطلاب ما بيتغيّر) رغم اتصالات TIME_WAIT"""
    pk = make_copy(tmp_path, "امتحان 1"); want = free_port()
    s = start(pk, want); made.append(s)
    for _ in range(5): urllib.request.urlopen(f"http://127.0.0.1:{want}/ok", timeout=5).read()                    # اتصالات بتخلّي TIME_WAIT
    s.proc.kill(); s.proc.wait(); pk.p("exam_info.txt").unlink()
    s2 = start(pk, want); made.append(s2)
    assert s2.port == want


def test_bind_server_takes_the_first_free_port_and_reports_when_none(srv):
    ports = [free_port() for _ in range(3)]
    busy = []
    for p in ports[:2]:                                                  # منفذان مشغولان بـ socket يسمع (ببيئة ويندوز بالـ REUSEADDR نفسه)
        s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("0.0.0.0", p)); s.listen(5); busy.append(s)
    try:
        server, port = srv.bind_server(ports[0], fallbacks=ports[1:]); server.server_close()
        assert port == ports[2]
        with pytest.raises(OSError): srv.bind_server(ports[0], fallbacks=ports[1:2])
    finally:
        for s in busy: s.close()
