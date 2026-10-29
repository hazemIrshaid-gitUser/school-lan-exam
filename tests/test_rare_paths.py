"""مسارات نادرة طلعت بقياس التغطية إنها ما انجرّبت: تسجيل خروج المعلم، طلبات مشوّهة، فشل حفظ التسليم على القرص، وتحذيرات كلمة السر بالنافذة السوداء."""
import http.client, http.server, json, threading, urllib.request

import pytest
from conftest import key_of, start_paper
from test_http import Server, TEACHER


@pytest.fixture
def inproc(srv):
    """السيرفر نفسه بنفس العملية (عشان نقدر نخرّب أشياء جواته)"""
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), srv.H); threading.Thread(target=s.serve_forever, daemon=True).start()
    yield srv, s.server_address[1]
    s.shutdown(); s.server_close()


def post(port, path, body):
    rq = urllib.request.Request(f"http://127.0.0.1:{port}{path}", json.dumps(body, ensure_ascii=False).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(rq, timeout=10) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()


def test_logout_ends_the_teacher_session(pkg):
    w = Server(pkg).start()
    try:
        ck = w.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0]
        assert w.get("/key", {"Cookie": ck})[0] == 200
        st, _, _, hdr = w.get("/logout", {"Cookie": ck})
        assert st == 302 and hdr["Location"] == "/monitor" and "Max-Age=0" in hdr["Set-Cookie"]
        st, _, _, hdr = w.get("/key", {"Cookie": ck}); assert st == 302 and hdr["Location"].startswith("/login")   # الجلسة القديمة ما عادت تنفع
        assert w.get("/logout", {"Cookie": "x; =; exam_t=bogus; y=1"})[0] == 302                                 # كوكي مشوّه ما بيوقّع السيرفر
    finally:
        w.stop()


@pytest.mark.parametrize("raw,headers", [
    (b"{not json", {"Content-Length": "9"}),
    (b"[1,2,3]", {"Content-Length": "7"}),
    (b'"text"', {"Content-Length": "6"}),
    (b"\xff\xfe\x00", {"Content-Length": "3"}),
    (b"", {"Content-Length": "abc"}),
    (b"", {"Content-Length": "-5"}),
])
def test_malformed_posts_get_400_and_server_keeps_going(inproc, raw, headers):
    _, port = inproc
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.putrequest("POST", "/ping"); [c.putheader(k, v) for k, v in headers.items()]; c.endheaders(); c.send(raw)
    r = c.getresponse(); assert r.status == 400; c.close()
    assert urllib.request.urlopen(f"http://127.0.0.1:{port}/ok", timeout=5).read().strip() == b"OK"


def test_submit_that_cannot_be_saved_returns_500_and_loses_nothing(inproc, monkeypatch, tmp_path):
    m, port = inproc
    k = start_paper(m, key_of(m), "d1"); ids = m.PAPERS[k]["ids"]
    body = {"key": k, "dev": "d1", "ids": ids, "answers": ",".join(str(m.BANK[n]["a"]) for n in ids), "auto": "يدوي", "leave": "لم يخرج"}
    good = m.SUBS_FILE; bad = tmp_path / "مش ملف"; bad.mkdir()
    monkeypatch.setattr(m.ctx, "SUBS_FILE", str(bad))                                                  # فتح «مجلد» للكتابة بيفشل (زي قرص ممتلئ أو ملف ممسوك)
    st, txt = post(port, "/submit", body)
    assert st == 500 and txt == b"save failed" and k not in m.SUBS and k in m.PAPERS and m.CLAIMS[k] == "d1"   # الطالب لسا بامتحانه
    st, txt = post(port, "/resume", {"key": k, "dev": "d1"}); assert st == 200 and json.loads(txt)["status"] == "ok"
    monkeypatch.setattr(m.ctx, "SUBS_FILE", good)
    st, txt = post(port, "/submit", body); r = json.loads(txt)
    assert st == 200 and r["score"] == r["total"] and k in m.SUBS
    assert len(open(good, encoding="utf-8").read().splitlines()) == 1


@pytest.mark.parametrize("pw,en,ar", [("", "WARNING: no teacher password", "ما في كلمة سر للمعلم"), ("1234", "default 1234", "الافتراضية (1234)")])
def test_console_banner_password_warnings(pkg, monkeypatch, pw, en, ar):
    pkg.settings(**{"كلمة_سر_المعلم": pw}); m = pkg.load()
    out = []; monkeypatch.setattr(m, "_real_print", lambda *a, **k: out.append(" ".join(map(str, a))), raising=False)
    monkeypatch.setattr(m, "REAL_CONSOLE", False)
    m.show_console_banner(":8000")
    assert any(en in x for x in out)
    info = pkg.p("exam_info.txt").read_text(encoding="utf-8-sig"); assert "تحذيرات:" in info and ar in info
