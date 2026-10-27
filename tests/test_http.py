"""المرحلة 3 + 4 + 5: السيرفر الحقيقي (عملية مستقلة) عبر HTTP — رحلة الطالب، صفحات المعلم، الأمان، الصمود بعد إعادة التشغيل، وحمل 60 طالب."""
import http.client, json, os, socket, subprocess, sys, threading, time, urllib.parse

import pytest
from conftest import bank, roster, q

H = {"Content-Type": "application/json"}
TEACHER = {"Content-Type": "application/json", "X-Exam-Action": "1"}
PKG_PYTHON = os.environ.get("EXAM_PYTHON") or sys.executable          # مفسّر السيرفر: EXAM_PYTHON=مسار python.exe يشغّل السيرفر بنسخة بايثون ثانية (مثل المحمول) وpytest يضل بمفسّره


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1)); ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except Exception:
        return None
    finally:
        s.close()


class Server:
    def __init__(self, pkg):
        self.pkg, self.proc, self.port = pkg, None, None

    def start(self, port=None):
        self.port = port or free_port()
        env = dict(os.environ, EXAM_PORT=str(self.port), PYTHONIOENCODING="utf-8")
        self.proc = subprocess.Popen([PKG_PYTHON, "-X", "utf8", "server.py"], cwd=self.pkg.path, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if self.proc.poll() is not None: raise RuntimeError("السيرفر وقف: " + (self.pkg.p("exam_error.txt").read_text(encoding="utf-8-sig") if self.pkg.p("exam_error.txt").exists() else "?"))
            try: socket.create_connection(("127.0.0.1", self.port), 0.2).close(); return self
            except OSError: time.sleep(0.1)
        raise RuntimeError("السيرفر ما فتح المنفذ")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(5)
            except subprocess.TimeoutExpired: self.proc.kill()

    retries = 0                                       # >0: يعيد المحاولة لو انقطع الاتصال (مثل الطالب اللي يضغط الزر مرة ثانية)

    def req(self, method, path, body=None, headers=None, host="127.0.0.1", raw=None):
        for attempt in range(self.retries + 1):
            c = http.client.HTTPConnection(host, self.port, timeout=20)
            try:
                data = raw if raw is not None else (json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
                c.request(method, path, body=data, headers=headers or {})
                r = c.getresponse(); b = r.read()
                try: j = json.loads(b)
                except Exception: j = None
                return r.status, j, b, dict(r.getheaders())
            except (ConnectionError, socket.timeout):
                if attempt == self.retries: raise
                time.sleep(0.3 * (attempt + 1))
            finally:
                c.close()

    def post(self, path, body, headers=H, host="127.0.0.1"):
        return self.req("POST", path, body, headers, host)

    def get(self, path, headers=None, host="127.0.0.1"):
        return self.req("GET", path, None, headers, host)

    def teacher(self, **cmd):
        return self.post("/monitor", cmd, TEACHER)[:2]

    # --- اختصارات الطالب ---
    def key(self, n="طالب أ1", s="أ", g="العاشر", title="اختبار الوحدة"):
        return f"{title}|{g}|{s}|{n}"

    def start_student(self, dev="dev1", **kw):
        code = kw.pop("code", None); k = self.key(**kw)
        body = {"key": k, "dev": dev}
        if code is not None: body["code"] = code
        st, j, _, _ = self.post("/start", body)
        return k, st, j

    @staticmethod
    def correct_answers(ids):
        return [(n - 1) % 4 for n in ids]            # حسب bank() بالـ conftest: الإجابة الصحيحة للسؤال n

    def submit(self, k, dev, ids, answers, **extra):
        body = {"key": k, "dev": dev, "ids": ids, "answers": ",".join(map(str, answers)), "auto": "يدوي", "leave": "لم يخرج"}; body.update(extra)
        st, j, raw, _ = self.post("/submit", body)
        return st, j, raw


@pytest.fixture
def web(pkg):
    s = Server(pkg).start()
    yield s
    s.stop()


@pytest.fixture
def web_for():
    started = []
    def make(pkg):
        s = Server(pkg).start(); started.append(s); return s
    yield make
    for s in started: s.stop()


# ======================= رحلة الطالب =======================
def test_student_page_and_name_list(web):
    st, _, body, hdr = web.get("/")
    t = body.decode("utf-8")
    assert st == 200 and "اختبار الوحدة" in t and hdr["Cache-Control"] == "no-store"
    assert "طالب أ1" in t                                            # قائمة الأسماء ظاهرة لاختيار الاسم
    st, j, _, _ = web.get("/taken?dev=x")
    assert st == 200 and j == {"taken": []}


def test_full_student_flow_correct_score_and_files(web, pkg):
    k, st, p = web.start_student()
    assert st == 200 and p["status"] == "ok" and len(p["ids"]) == 8 and 1790 <= p["remain"] <= 1800
    st, j, _ = web.submit(k, "dev1", p["ids"], web.correct_answers(p["ids"]))
    assert (st, j) == (200, {"score": 8, "total": 8})
    # تسليم ثاني (مثلاً ضغط مرتين): نفس النتيجة بدون تسجيل مرتين
    st, j, _ = web.submit(k, "dev1", p["ids"], [0] * 8)
    assert j == {"score": 8, "total": 8, "dup": True}
    assert len(pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    csv = pkg.p("results.csv").read_text(encoding="utf-8-sig")
    assert "طالب أ1" in csv and "— لا أخطاء —" in csv
    # بعد التسليم: /start و/resume بيرجعوا done
    assert web.start_student()[2] == {"status": "done"}
    assert web.post("/resume", {"key": k, "dev": "dev1"})[1] == {"status": "done"}


def test_partial_score_and_wrong_answers_listed(web, pkg):
    k, _, p = web.start_student()
    ans = web.correct_answers(p["ids"]); ans[0] = (ans[0] + 1) % 4; ans[1] = -1
    st, j, _ = web.submit(k, "dev1", p["ids"], ans)
    assert j == {"score": 6, "total": 8}
    csv = pkg.p("results.csv").read_text(encoding="utf-8-sig")
    assert "لم يجب" in csv and csv.count("س") >= 2


def test_submit_rejects_bad_payloads(web):
    k, _, p = web.start_student(); ids = p["ids"]; ok = web.correct_answers(ids)
    assert web.submit(k, "dev1", ids[::-1], ok)[0] == 400                    # ترتيب أسئلة غير ورقته
    assert web.submit(k, "dev1", ids[:-1], ok[:-1])[0] == 400               # ناقص سؤال
    assert web.submit(k, "dev1", ids, ok[:-1])[0] == 400                    # إجابات أقل
    assert web.submit(k, "dev1", ids, ok[:-1] + [9])[0] == 400              # خيار خارج المدى
    assert web.submit(k, "dev1", ids, ok[:-1] + [-2])[0] == 400
    assert web.submit(k, "dev1", ids, ok[:-1] + ["x"])[0] == 400
    assert web.submit(k, "other", ids, ok)[0] == 409                        # جهاز غير جهاز الطالب
    assert web.submit(web.key(n="غير موجود"), "dev1", ids, ok)[0] == 400
    assert web.submit(web.key(n="طالب أ2"), "dev9", ids, ok)[0] == 409      # ما بدأ أصلاً
    assert web.submit(k, "dev1", ids, ok)[0] == 200                         # وبعد كل هالمحاولات ما انخرب شي


@pytest.mark.parametrize("raw", [b"not json", b"[1,2]", b"\"str\"", b"", b"{"])
def test_malformed_bodies_return_400_not_crash(web, raw):
    for path in ("/start", "/submit", "/ping", "/resume", "/review"):
        assert web.req("POST", path, headers=H, raw=raw)[0] == 400
    assert web.get("/")[0] == 200                                            # السيرفر لسا حيّ


def test_post_without_content_length(web):
    c = socket.create_connection(("127.0.0.1", web.port), 3)
    c.sendall(b"POST /start HTTP/1.1\r\nHost: x\r\n\r\n"); data = c.recv(200); c.close()
    assert b"400" in data.split(b"\r\n")[0] and web.get("/")[0] == 200


def test_start_validation(web):
    assert web.post("/start", {"key": web.key(n="مجهول"), "dev": "d"})[0] == 400
    assert web.post("/start", {"key": web.key(), "dev": ""})[0] == 400
    assert web.post("/start", {"key": web.key(title="عنوان آخر"), "dev": "d"})[0] == 400
    assert web.post("/start", {"dev": "d"})[0] == 400


def test_name_claim_and_resume_semantics(web):
    k, _, p1 = web.start_student("devA")
    assert web.start_student("devB")[2] == {"status": "taken"}              # جهاز ثاني ما بياخد نفس الاسم
    assert web.get("/taken?dev=devB")[1]["taken"] == [k] and web.get("/taken?dev=devA")[1]["taken"] == []
    _, _, again = web.start_student("devA")                                  # نفس الجهاز يكمل بنفس الورقة
    assert again["ids"] == p1["ids"] and again["orders"] == p1["orders"]
    assert web.post("/resume", {"key": k, "dev": "devA"})[1]["ids"] == p1["ids"]
    assert web.post("/resume", {"key": k, "dev": "devB"})[1] == {"status": "none"}


def test_ping_saves_answers_and_resume_returns_them(web):
    k, _, p = web.start_student()
    ans = {str(p["ids"][0]): 2, str(p["ids"][1]): 1, "999": 1}
    r = web.post("/ping", {"key": k, "dev": "dev1", "ans": ans, "answered": 2, "total": 8, "remain": 1700, "leaveN": 1, "leaveSec": 4})[1]
    assert set(r) == {"remain", "msg", "paused"} and r["paused"] is False
    got = web.post("/resume", {"key": k, "dev": "dev1"})[1]["ans"]
    assert got == {str(p["ids"][0]): 2, str(p["ids"][1]): 1}                 # السؤال الغريب انحذف
    assert web.post("/ping", {"key": k, "dev": "wrong", "ans": {}})[1] == {"released": True}


def test_time_is_server_side(web):
    k, _, p = web.start_student()
    r = web.post("/ping", {"key": k, "dev": "dev1", "remain": 99999})[1]    # الطالب يكذب بالوقت المتبقي
    assert r["remain"] <= 1800


def test_student_endpoints_never_leak_answers(web):
    k, _, p = web.start_student()
    web.post("/ping", {"key": k, "dev": "dev1", "ans": {}})
    texts = [json.dumps(p), web.post("/resume", {"key": k, "dev": "dev1"})[2].decode(), web.post("/ping", {"key": k, "dev": "dev1"})[2].decode()]
    st, j, raw = web.submit(k, "dev1", p["ids"], [0] * 8); texts.append(raw.decode())
    for t in texts:                                                    # ردود JSON: ما فيها أي إشارة للجواب الصحيح
        assert "correct" not in t and '"sol"' not in t and '"a":' not in t
    page = web.get("/")[2].decode("utf-8")                              # صفحة الطالب: ما فيها بيانات الإجابات (كلمة correct موجودة بكود العرض بس)
    assert '"a":' not in page and '"sol"' not in page


def test_review_modes(pkg, web_for):
    for i, (mode, expect_first) in enumerate((("لا", "off"), ("نعم", "ok"), ("بعد_الإنهاء", "wait")), 1):
        pkg.settings(**{"مراجعة_الأخطاء": mode})
        w = web_for(pkg)
        nm = f"طالب أ{i}"                                       # طالب مختلف لكل جولة (الحالة بتنحفظ بين التشغيلات)
        k, _, p = w.start_student(f"d-{mode}", n=nm)
        assert w.post("/review", {"key": k, "dev": f"d-{mode}"})[1]["status"] == "off"        # قبل التسليم
        w.submit(k, f"d-{mode}", p["ids"], [(a + 1) % 4 for a in w.correct_answers(p["ids"])])
        st = w.post("/review", {"key": k, "dev": f"d-{mode}"})[1]
        assert st["status"] == expect_first
        if mode == "نعم": assert len(st["items"]) == 8 and set(st["items"][0]) == {"n", "given", "correct", "q", "o"}
        if mode == "بعد_الإنهاء":
            w.teacher(close=True)
            assert w.post("/review", {"key": k, "dev": f"d-{mode}"})[1]["status"] == "ok"
        w.stop()


def test_review_not_available_to_other_device(pkg, web_for):
    pkg.settings(**{"مراجعة_الأخطاء": "نعم"}); w = web_for(pkg)
    k, _, p = w.start_student("devA"); w.submit(k, "devA", p["ids"], [0] * 8)
    assert w.post("/review", {"key": k, "dev": "devB"})[1]["status"] == "off"


# ======================= أوامر المعلم =======================
def test_close_exam_blocks_new_starts_but_not_running_students(web):
    k, _, p = web.start_student("devA")
    assert web.teacher(close=True)[1] == {"ok": 1}
    assert web.start_student("devB", n="طالب أ2")[2] == {"status": "closed"}
    assert web.post("/ping", {"key": k, "dev": "devA"})[1]["remain"] == 0   # الطالب الشغال بيتسلّم تلقائياً من صفحته
    assert web.submit(k, "devA", p["ids"], web.correct_answers(p["ids"]))[1]["score"] == 8
    web.teacher(close=False)
    assert web.start_student("devB", n="طالب أ2")[2]["status"] == "ok"


def test_message_broadcast(web):
    k, _, _ = web.start_student()
    web.teacher(message="باقي 5 دقائق")
    m = web.post("/ping", {"key": k, "dev": "dev1"})[1]["msg"]
    assert m["text"] == "باقي 5 دقائق" and m["id"] == 1
    web.teacher(message="x" * 1000)
    assert len(web.post("/ping", {"key": k, "dev": "dev1"})[1]["msg"]["text"]) == 300


def test_extend_time_validation_and_effect(web):
    k, _, p = web.start_student()
    assert web.post("/monitor", {"extend": 10, "scope": "student", "key": k}, TEACHER)[0] == 200
    assert 2390 <= web.post("/ping", {"key": k, "dev": "dev1"})[1]["remain"] <= 2400
    for bad in ({"extend": 0}, {"extend": 500, "scope": "all"}, {"extend": -5, "scope": "all"}, {"extend": "x", "scope": "all"}, {"extend": 5, "scope": "weird"}):
        r = web.post("/monitor", bad, TEACHER)
        assert r[0] in (200, 400)
        if bad["extend"] != 0: assert r[0] == 400


def test_release_lets_student_restart_from_other_device(web):
    k, _, p = web.start_student("devA")
    web.teacher(release=k)
    assert web.post("/ping", {"key": k, "dev": "devA"})[1] == {"released": True}
    _, _, p2 = web.start_student("devB")
    assert p2["status"] == "ok" and p2["remain"] >= 1790                     # ورقة ووقت جديدين


def test_move_keeps_paper_answers_and_remaining_time(web):
    k, _, p = web.start_student("devA")
    web.post("/ping", {"key": k, "dev": "devA", "ans": {str(p["ids"][0]): 3}})
    web.teacher(extend=3, scope="student", key=k)
    time.sleep(2.2)
    web.teacher(move=k)
    assert web.post("/ping", {"key": k, "dev": "devA"})[1] == {"released": True}
    time.sleep(2.2)                                                         # الوقت لازم يكون متجمّد وقت النقل
    _, _, p2 = web.start_student("devB")
    assert p2["ids"] == p["ids"] and p2["orders"] == p["orders"] and p2["ans"] == {str(p["ids"][0]): 3}
    assert 1975 <= p2["remain"] <= 1980                                       # 1800+180 - ~3 ثواني، مش 7


def test_submit_for_one_and_all(web, pkg):
    ks = []
    for i, n in enumerate(("طالب أ1", "طالب أ2", "طالب أ3")):
        k, _, p = web.start_student(f"d{i}", n=n); ks.append((k, p))
        web.post("/ping", {"key": k, "dev": f"d{i}", "ans": {str(x): web.correct_answers([x])[0] for x in p["ids"][:i + 2]}})
    time.sleep(0.2)
    web.teacher(submitfor=ks[0][0])
    web.teacher(submitfor="all")
    lines = [json.loads(l) for l in pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sorted(l["score"] for l in lines) == [2, 3, 4] and all(l["auto"] == "تسليم من المعلم" for l in lines) and len(lines) == 3
    assert web.post("/ping", {"key": ks[0][0], "dev": "d0"})[1] == {"submitted": True}      # صفحة الطالب بتعرض نتيجته
    assert web.submit(ks[1][0], "d1", ks[1][1]["ids"], [0] * 8)[1]["dup"] is True             # ما بيقدر يكمل بعدها


def test_new_exam_archives_and_resets(web, pkg):
    k, _, p = web.start_student(); web.submit(k, "dev1", p["ids"], web.correct_answers(p["ids"]))
    web.teacher(newexam=True)
    assert web.start_student("devZ")[2]["status"] == "ok"                    # صار مسموح يبدأ من جديد
    arch = [d for d in os.listdir(pkg.path) if d.startswith("archive_")]
    assert arch and os.path.exists(pkg.path / arch[0] / "submissions.jsonl")


def test_monitor_json_and_reports(web):
    k, _, p = web.start_student()
    web.post("/ping", {"key": k, "dev": "dev1", "answered": 3, "total": 8, "remain": 1500, "ans": {}})
    j = web.get("/monitor.json")[1]
    assert j["c"] == {"done": 0, "live": 1, "lost": 0, "none": 4}
    web.submit(k, "dev1", p["ids"], web.correct_answers(p["ids"]))
    assert web.get("/monitor.json")[1]["c"]["done"] == 1
    for path in ("/monitor", "/report", "/report.xlsx", "/link"):
        pass
    st, _, body, hdr = web.get("/report.xlsx")
    assert st == 200 and body[:2] == b"PK" and "spreadsheetml" in hdr["Content-Type"]


# ======================= الأمان: صلاحيات =======================
TEACHER_GET = ["/monitor", "/monitor.json", "/admin", "/report", "/report.xlsx", "/sheet", "/key", "/codes", "/teacher", "/settings", "/settings.json", "/link"]


def test_teacher_pages_open_from_localhost_without_password_when_unset(pkg, web_for):
    pkg.settings(**{"كلمة_سر_المعلم": ""}); w = web_for(pkg)
    for path in TEACHER_GET: assert w.get(path)[0] == 200, path


@pytest.mark.skipif(lan_ip() is None, reason="ما في عنوان شبكة محلية: ما بنقدر نحاكي جهاز طالب")
def test_students_from_network_cannot_reach_any_teacher_page(pkg, web_for):
    pkg.settings(**{"كلمة_سر_المعلم": ""}); w = web_for(pkg); ip = lan_ip()
    assert w.get("/", host=ip)[0] == 200                                     # صفحة الطالب شغالة من الشبكة
    for path in TEACHER_GET + ["/login", "/logout?x=1"]:
        if path == "/logout?x=1": continue
        assert w.get(path, host=ip)[0] == 403, path
    for path, body in (("/monitor", {"close": True}), ("/monitor", {"newexam": True}), ("/login", {"password": "x"})):
        assert w.post(path, body, TEACHER, host=ip)[0] == 403
    assert w.get("/monitor.json")[1]["closed"] is False                      # ولا شي تغيّر


@pytest.mark.skipif(lan_ip() is None, reason="ما في عنوان شبكة محلية")
def test_network_student_cannot_bypass_password_with_headers(pkg, web_for):
    w = web_for(pkg); ip = lan_ip()
    hdr = {"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1", "Host": "localhost", "Cookie": "exam_t=guess"}
    for path in ("/key", "/teacher", "/sheet"): assert w.get(path, hdr, host=ip)[0] in (403,)


def test_teacher_post_requires_custom_header(web):
    for path, body in (("/monitor", {"close": True}), ("/login", {"password": "secret"})):
        assert web.post(path, body, H)[0] == 403                             # بدون X-Exam-Action (حماية CSRF من صفحات خارجية)
    assert web.get("/monitor.json")[1]["closed"] is False


def test_password_gate_login_logout_and_lockout(web):
    for path in ("/key", "/teacher", "/sheet", "/codes"):
        st, _, _, hdr = web.get(path)
        assert st == 302 and hdr["Location"].startswith("/login?next=")
    assert web.get("/login?next=/key")[0] == 200
    assert web.post("/login", {"password": "wrong"}, TEACHER)[1] == {"ok": False}
    st, j, _, hdr = web.post("/login", {"password": "secret"}, TEACHER)
    assert j == {"ok": True} and "HttpOnly" in hdr["Set-Cookie"] and "SameSite=Strict" in hdr["Set-Cookie"]
    cookie = hdr["Set-Cookie"].split(";")[0]
    st, _, body, _ = web.get("/key", {"Cookie": cookie})
    assert st == 200 and "✓" in body.decode("utf-8")                         # المفتاح فيه الإجابات الصحيحة
    assert web.get("/key", {"Cookie": "exam_t=forged"})[0] == 302
    web.get("/logout", {"Cookie": cookie})
    assert web.get("/key", {"Cookie": cookie})[0] == 302                     # الجلسة انتهت
    for _ in range(5): last = web.post("/login", {"password": "bad"}, TEACHER)[1]
    assert web.post("/login", {"password": "secret"}, TEACHER)[1].get("locked", 0) > 0     # حتى الصحيحة مرفوضة أثناء القفل


def test_login_next_cannot_redirect_offsite(web):
    t = web.get("/login?next=//evil.com/key")[2].decode("utf-8")
    assert "evil.com" not in t
    t = web.get("/login?next=https://evil.com")[2].decode("utf-8")
    assert "evil.com" not in t


def test_login_comparison_handles_unicode_and_types(web):
    for pw in ("كلمة", None, 123, ["secret"], {"a": 1}, "secret\u0000"):
        r = web.post("/login", {"password": pw}, TEACHER)
        assert r[0] in (200,) and r[1]["ok"] is False


def test_codes_required_to_start(pkg, web_for):
    pkg.settings(**{"رمز_الدخول": "نعم"})
    pkg.students([["العاشر", "أ", "طالب أ1", "123456"], ["العاشر", "أ", "طالب أ2", ""]]); w = web_for(pkg)
    assert w.start_student("d1")[2] == {"status": "badcode"} and w.start_student("d1", code="654321")[2] == {"status": "badcode"}
    assert w.start_student("d1", code="١٢٣٤٥٦")[2]["status"] == "ok"
    # الرمز بس لأول بدء: بعدها نفس الجهاز بيكمل بدون رمز
    assert w.start_student("d1")[2]["status"] == "ok"
    for _ in range(5): w.start_student("d2", n="طالب أ2", code="000000")
    assert w.start_student("d2", n="طالب أ2", code="000000")[2] == {"status": "locked"}


def test_codes_not_exposed_to_students_page(pkg, web_for):
    pkg.settings(**{"رمز_الدخول": "نعم"}); pkg.students([["العاشر", "أ", "طالب أ1", "987654"]]); w = web_for(pkg)
    assert "987654" not in w.get("/")[2].decode("utf-8")


# ======================= الصور وملفات السيرفر =======================
def test_image_serving_and_path_traversal(pkg, web_for):
    rows = bank(); rows[0][0] = "شاهد [img:fig.png]"; pkg.questions(rows); pkg.image("fig.png")
    pkg.image("pic.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>")
    (pkg.path / "secret.txt").write_text("TOPSECRET"); (pkg.path / "images" / "note.txt").write_text("TXT")
    w = web_for(pkg)
    st, _, body, hdr = w.get("/img/fig.png")
    assert st == 200 and hdr["Content-Type"] == "image/png" and hdr["X-Content-Type-Options"] == "nosniff"
    st, _, _, hdr = w.get("/img/pic.svg")
    assert st == 200 and "sandbox" in hdr["Content-Security-Policy"]
    for evil in ("/img/../server.py", "/img/..%2Fserver.py", "/img/%2e%2e/server.py", "/img/..%5Cserver.py", "/img/%2e%2e%5csettings.txt",
                 "/img/note.txt", "/img/", "/img/nope.png", "/img/fig.png%00.txt", "/img/..%2f..%2fsecret.txt", "/img//etc/passwd", "/img/C:%5Cwindows%5Cwin.ini"):
        st, _, body, _ = w.get(evil)
        assert st == 404 and b"TOPSECRET" not in body and b"import sys" not in body, evil


@pytest.mark.parametrize("path", ["/server.py", "/settings.txt", "/questions.xlsx", "/students.xlsx", "/submissions.jsonl", "/results.csv", "/papers.json", "/codes.json",
                                  "/../server.py", "/%2e%2e/server.py", "/template.html", "/state.json", "/answers.json"])
def test_data_files_not_served(web, path):
    st, _, body, _ = web.get(path)
    assert st == 404 and b"import sys" not in body and b"questions" not in body.lower()


def test_unknown_post_and_method_handling(web):
    assert web.post("/nope", {"a": 1})[0] == 404
    assert web.req("PUT", "/start", {"a": 1}, H)[0] in (501, 405, 404)
    assert web.req("DELETE", "/", None, {})[0] in (501, 405, 404)
    assert web.get("/")[0] == 200


# ======================= الصمود: إعادة التشغيل =======================
def test_restart_restores_everything(pkg, web_for):
    w = web_for(pkg)
    k1, _, p1 = w.start_student("d1"); k2, _, p2 = w.start_student("d2", n="طالب أ2")
    w.submit(k1, "d1", p1["ids"], w.correct_answers(p1["ids"]))
    w.post("/ping", {"key": k2, "dev": "d2", "ans": {str(p2["ids"][0]): 1}}); time.sleep(3.5)          # الحفظ التلقائي كل 3 ثواني
    w.teacher(message="مرحبا"); w.teacher(close=True)
    w.stop()
    w2 = web_for(pkg)
    assert w2.start_student("d1")[2] == {"status": "done"}
    r = w2.post("/resume", {"key": k2, "dev": "d2"})[1]
    assert r["ids"] == p2["ids"] and r["ans"] == {str(p2["ids"][0]): 1} and r["msg"]["text"] == "مرحبا"
    assert w2.get("/monitor.json")[1]["closed"] is True
    assert w2.submit(k2, "d2", p2["ids"], w2.correct_answers(p2["ids"]))[1]["score"] == 8


def test_graceful_stop_flushes_answers(pkg, web_for):
    """Ctrl+C قبل ما يمرّ 3 ثواني: آخر إجابات لازم تنحفظ (finally: flush_answers)"""
    w = web_for(pkg)
    k, _, p = w.start_student("d1")
    w.post("/ping", {"key": k, "dev": "d1", "ans": {str(p["ids"][0]): 2}})
    if os.name == "nt":
        pytest.skip("على ويندوز terminate() بيقتل العملية فجأة (ما في SIGINT): الاختبار الحقيقي هو إطفاء بـ Ctrl+C يدوياً")
    w.proc.send_signal(__import__("signal").SIGINT); w.proc.wait(10)
    assert json.loads(pkg.p("answers.json").read_text(encoding="utf-8"))[k] == {str(p["ids"][0]): 2}


def test_server_survives_corrupt_state_files(pkg, web_for):
    for f in ("claims.json", "papers.json", "state.json", "answers.json"): pkg.p(f).write_text("{broken", encoding="utf-8")
    # سطر تالف + JSON من نوع غلط + سطر مقطوع بنص (انقطاع كهرباء أثناء الكتابة)
    pkg.p("submissions.jsonl").write_text('not json\n[1,2]\n{"key": "a|b|c|d", "exam": "x", "gra', encoding="utf-8")
    w = web_for(pkg)
    assert w.start_student()[2]["status"] == "ok"


# ======================= الحمل: 60 طالب بنفس الوقت =======================
def test_sixty_students_concurrently(pkg, web_for):
    N = 60
    pkg.students([["العاشر", "أ", f"طالب {i}"] for i in range(N)])
    pkg.questions(bank(hard=6, medium=8, easy=8))
    w = web_for(pkg); w.retries = 3                      # المتصفح/الطالب بيعيد المحاولة عند انقطاع الاتصال
    results, errors = {}, []

    def student(i):
        try:
            name, dev = f"طالب {i}", f"dev{i}"
            k, st, p = w.start_student(dev, n=name)
            assert st == 200 and p["status"] == "ok", p
            correct = w.correct_answers(p["ids"]); n_ok = i % (len(correct) + 1)
            ans = correct[:n_ok] + [(c + 1) % 4 for c in correct[n_ok:]]
            for r in range(4):
                saved = {str(n): a for n, a in zip(p["ids"][:(r + 1) * 2], ans)}
                w.post("/ping", {"key": k, "dev": dev, "ans": saved, "answered": len(saved), "total": 8, "remain": 1500})
                time.sleep(0.05)
            st, j, _ = w.submit(k, dev, p["ids"], ans)
            results[i] = (st, j, n_ok)
        except Exception as e:                                               # noqa
            errors.append((i, repr(e)))

    t0 = time.time()
    ths = [threading.Thread(target=student, args=(i,)) for i in range(N)]
    [t.start() for t in ths]; [t.join(120) for t in ths]
    dt = time.time() - t0
    assert not errors, errors[:3]
    assert len(results) == N and all(st == 200 and j["score"] == n_ok and j["total"] == 8 for st, j, n_ok in results.values())
    lines = pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == N and len({json.loads(l)["key"] for l in lines}) == N          # ولا تسليم ضاع أو انكتب مرتين
    assert w.get("/monitor.json")[1]["c"]["done"] == N
    csv_lines = pkg.p("results.csv").read_text(encoding="utf-8-sig").splitlines()
    assert len([l for l in csv_lines if l.startswith("اختبار")]) >= N or len(csv_lines) > N
    assert dt < 60, f"بطيء: {dt:.1f}s"


# كانت مشكلة (request_queue_size=5): أُصلحت بـ server.py. الاختبار الآن عادي، لو رجعت المشكلة بيفشل
def test_simultaneous_start_burst_has_no_connection_failures(pkg, web_for):
    N = 60
    pkg.students([["العاشر", "أ", f"طالب {i}"] for i in range(N)]); pkg.questions(bank(6, 8, 8))
    w = web_for(pkg); gate = threading.Barrier(N); errs = []
    def go(i):
        gate.wait()
        try:
            assert w.start_student(f"d{i}", n=f"طالب {i}")[1] == 200
        except Exception as e:
            errs.append(type(e).__name__)
    ths = [threading.Thread(target=go, args=(i,)) for i in range(N)]; [t.start() for t in ths]; [t.join(60) for t in ths]
    assert not errs, f"{len(errs)} من {N} فشلوا: {set(errs)}"


def test_concurrent_double_submit_same_student(pkg, web_for):
    """ضغط مرتين بنفس اللحظة (أو إعادة إرسال): تسليم واحد بس"""
    w = web_for(pkg); k, _, p = w.start_student(); out = []
    def go(): out.append(w.submit(k, "dev1", p["ids"], w.correct_answers(p["ids"]))[1])
    ths = [threading.Thread(target=go) for _ in range(10)]; [t.start() for t in ths]; [t.join() for t in ths]
    assert len(pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert sum(1 for o in out if not o.get("dup")) == 1


def test_concurrent_name_claim_only_one_wins(pkg, web_for):
    w = web_for(pkg); out = []
    def go(i): out.append(w.start_student(f"dev{i}")[2]["status"])
    ths = [threading.Thread(target=go, args=(i,)) for i in range(15)]; [t.start() for t in ths]; [t.join() for t in ths]
    assert out.count("ok") == 1 and out.count("taken") == 14


# ============================ حماية من الطلبات الضخمة والاتصالات المعلّقة ============================
def test_body_over_limit_gets_413_without_reading_it(web):
    import socket as so
    s = so.create_connection(("127.0.0.1", web.port), 3); s.settimeout(5)
    s.sendall(b"POST /ping HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: 2000000\r\n\r\n" + b"{" * 1000)
    head = s.recv(100); s.close()
    assert b" 413 " in head.split(b"\r\n")[0]
    assert web.get("/")[0] == 200


def test_body_at_normal_size_still_accepted(web):
    k, st, p = web.start_student("d1")
    big_ans = {str(n): 0 for n in range(1, 200)}                         # أكبر بكثير من أي طلب حقيقي
    assert web.post("/ping", {"key": k, "dev": "d1", "ans": big_ans, "answered": 1, "total": 8, "remain": 100})[0] == 200


def test_idle_half_open_request_is_closed_by_server(web):
    import socket as so, time as t
    s = so.create_connection(("127.0.0.1", web.port), 3); s.sendall(b"POST /ping HTTP/1.1\r\nHost: x\r\n"); s.settimeout(30)
    t0 = t.time()
    try: data = s.recv(100)
    except so.timeout: data = None
    s.close()
    assert data == b"" and t.time() - t0 < 25
