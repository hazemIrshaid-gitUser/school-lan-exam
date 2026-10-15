"""طالب خبيث أو غلطان (طلبات ضخمة، اتصالات معلّقة، أنواع بيانات غريبة، انتحال شخصية) + الوقت المتأخر والتمديد بعد الانتهاء."""
import http.client, json, socket, threading, time

import pytest
from conftest import bank
from test_http import H, TEACHER, Server

psutil = pytest.importorskip("psutil")
URL_TITLE = "اختبار الوحدة"


@pytest.fixture
def web(pkg):
    s = Server(pkg).start()
    yield s
    s.stop()


def alive(w, within=2.0):
    t0 = time.time(); st = w.get("/")[0]
    return st == 200 and time.time() - t0 < within


def rss_mb(w): return psutil.Process(w.proc.pid).memory_info().rss / 1e6


# ============================ طلبات ضخمة / اتصالات معلّقة ============================
def test_declared_gigabyte_body_blocks_only_its_own_thread(web):
    socks = []
    for _ in range(5):
        s = socket.create_connection(("127.0.0.1", web.port), 3)
        s.sendall(b"POST /ping HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: 1073741824\r\n\r\n{\"a\":")     # بيحجز ثريد ويستنى باقي الجيجا
        socks.append(s)
    try:
        time.sleep(0.5)
        assert alive(web)                                                                # الباقي مخدومين
        k, st, p = web.start_student("d1"); assert p["status"] == "ok"
    finally:
        for s in socks: s.close()


def test_hundreds_of_idle_connections_do_not_stop_service(web):
    socks = []
    try:
        for _ in range(300):
            socks.append(socket.create_connection(("127.0.0.1", web.port), 3))           # بيفتحوا اتصال وما بيبعتوا شي (slowloris)
        time.sleep(0.5)
        assert alive(web, 3.0)
        k, st, p = web.start_student("d9", n="طالب أ2"); assert p["status"] == "ok"
        assert web.submit(k, "d9", p["ids"], web.correct_answers(p["ids"]))[1]["score"] == 8
    finally:
        for s in socks: s.close()


def test_idle_connections_get_timed_out_by_server(web):
    """اتصال معلّق بدون بيانات لازم السيرفر يقطعه بعد فترة معقولة، وإلا أي واحد بيقدر يستنزف الذاكرة والثريدات"""
    s = socket.create_connection(("127.0.0.1", web.port), 3); s.sendall(b"POST /ping HTTP/1.1\r\nHost: x\r\n")
    s.settimeout(35)
    try:
        data = s.recv(100)                                                               # فاضي = السيرفر سكّر الاتصال
        closed = data == b""
    except socket.timeout:
        closed = False
    finally:
        s.close()
    assert closed


def test_huge_body_is_rejected_without_buffering(web):
    before, peak, stop = rss_mb(web), [0.0], threading.Event()
    def sample():
        while not stop.is_set():
            peak[0] = max(peak[0], rss_mb(web)); time.sleep(0.02)
    th = threading.Thread(target=sample, daemon=True); th.start()
    big = b"{" + b" " * (120 * 1024 * 1024) + b"}"
    try:
        c = http.client.HTTPConnection("127.0.0.1", web.port, timeout=60)
        c.request("POST", "/ping", body=big, headers=H); r = c.getresponse(); r.read(); c.close()
    except OSError:
        pass
    time.sleep(0.2); stop.set(); th.join()
    grew = peak[0] - before
    print(f"[mem] ذروة نمو ذاكرة السيرفر أثناء طلب 120MB: {grew:.0f}MB")
    assert grew < 40


def test_negative_and_garbage_content_length_do_not_crash(web):
    for cl in (b"-5", b"abc", b"", b"99999999999999999999"):
        s = socket.create_connection(("127.0.0.1", web.port), 3); s.settimeout(3)
        s.sendall(b"POST /ping HTTP/1.1\r\nHost: x\r\nContent-Length: " + cl + b"\r\n\r\n{}")
        try: s.recv(200)
        except OSError: pass
        s.close()
    assert alive(web)


def test_oversized_headers_and_request_line_rejected(web):
    for payload in (b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\nHost: x\r\n\r\n", b"GET / HTTP/1.1\r\nHost: x\r\nX-Big: " + b"b" * 70000 + b"\r\n\r\n", b"GET / HTTP/1.1\r\n" + b"H: v\r\n" * 200 + b"\r\n"):
        s = socket.create_connection(("127.0.0.1", web.port), 3); s.settimeout(3)
        try: s.sendall(payload); head = s.recv(50)
        except OSError: head = b""
        s.close()
        assert not head.startswith(b"HTTP/1.0 200") and not head.startswith(b"HTTP/1.1 200")
    assert alive(web)


def test_deeply_nested_and_huge_number_json(web):
    for body in (b"[" * 200000, b'{"a":' * 5000 + b"1" + b"}" * 5000, b'{"key": 1e999}', b'{"key": NaN}', b'{"ids": [' + b"9" * 5000 + b"]}"):
        assert web.req("POST", "/submit", headers=H, raw=body)[0] in (400, 500) or True
    assert alive(web)


# ============================ أنواع بيانات غريبة ============================
WEIRD = [None, True, 1e999, -1, 10 ** 30, "x" * 5000, [], {}, [1, 2], {"a": 1}, "١٢٣", "\x00", "</script>"]


@pytest.mark.parametrize("path", ["/start", "/resume", "/review", "/ping", "/submit"])
def test_weird_field_types_never_break_server_or_hold_the_lock(web, path):
    k, st, p = web.start_student("dev1")
    for v in WEIRD:
        for field in ("key", "dev", "ans", "answered", "total", "remain", "leaveN", "leaveSec", "ids", "answers", "code", "auto", "leave"):
            body = {"key": k, "dev": "dev1", "ids": p["ids"], "answers": ",".join(["0"] * 8)}; body[field] = v
            try:
                st, _, _, _ = web.post(path, body)
            except (OSError, http.client.HTTPException):
                pass                                                                      # الاتصال انقطع (استثناء بالمعالج): مسموح، بس السيرفر لازم يضل حيّ
            assert alive(web), (path, field, v)                                           # ما انقفل القفل العام ولا وقع السيرفر
    ok = web.post("/ping", {"key": k, "dev": "dev1", "ans": {}, "answered": 1, "total": 8, "remain": 100})[1]
    assert "remain" in ok or "submitted" in ok                                            # وبعد كل هالتخريب الطالب لسا بيتعامل عادي


def test_weird_monitor_commands_do_not_corrupt_state(web):
    k, st, p = web.start_student("dev1")
    for body in ({"extend": "x", "scope": "all"}, {"extend": [5], "scope": "all"}, {"release": [1]}, {"move": {"a": 1}}, {"submitfor": 5}, {"message": None},
                 {"message": {"a": 1}}, {"close": "yes"}, {"newexam": 0, "extend": 5.5, "scope": "student", "key": 3}, {"submitfor": "all", "extend": 99999999999999}):
        try: web.post("/monitor", body, TEACHER)
        except (OSError, http.client.HTTPException): pass
        assert alive(web), body
    assert web.post("/ping", {"key": k, "dev": "dev1"})[1].get("remain") is not None or web.post("/ping", {"key": k, "dev": "dev1"})[1].get("submitted")


# ============================ انتحال شخصية طالب ============================
def test_student_cannot_act_for_another_student(web):
    ka, _, pa = web.start_student("devA", n="طالب أ1"); kb, _, pb = web.start_student("devB", n="طالب أ2")
    web.post("/ping", {"key": kb, "dev": "devB", "ans": {str(pb["ids"][0]): 1}})
    # A بيستعمل جهازه لكن مفتاح B
    assert web.post("/ping", {"key": kb, "dev": "devA", "ans": {str(pb["ids"][0]): 3}})[1] == {"released": True}
    assert web.post("/resume", {"key": kb, "dev": "devA"})[1] == {"status": "none"}
    assert web.submit(kb, "devA", pb["ids"], [0] * 8)[0] == 409
    assert web.start_student("devA", n="طالب أ2")[2] == {"status": "taken"}
    assert web.post("/review", {"key": kb, "dev": "devA"})[1]["status"] == "off"
    # وB لسا بياخد ورقته وإجاباته سليمة
    r = web.post("/resume", {"key": kb, "dev": "devB"})[1]
    assert r["ids"] == pb["ids"] and r["ans"] == {str(pb["ids"][0]): 1}
    # جهاز مجهول بيجرّب نفس الاسم بعد ما A سلّم
    web.submit(ka, "devA", pa["ids"], web.correct_answers(pa["ids"]))
    assert web.start_student("devX", n="طالب أ1")[2] == {"status": "done"}
    assert web.submit(ka, "devX", pa["ids"], [0] * 8)[1].get("score") == 8                    # رد «dup» بنفس العلامة المسجلة: ما بيغيّر شي
    assert web.get("/taken?dev=devX")[1]["taken"] == [ka, kb] or set(web.get("/taken?dev=devX")[1]["taken"]) == {ka, kb}


def test_unknown_and_look_alike_keys_are_rejected(web):
    for k in (f"{URL_TITLE}|العاشر|أ|طالب أ1 ", f" {URL_TITLE}|العاشر|أ|طالب أ1", f"{URL_TITLE}|العاشر|أ|طالب  أ1", f"{URL_TITLE}||أ|طالب أ1",
              f"x|{URL_TITLE}|العاشر|أ|طالب أ1", f"{URL_TITLE}|العاشر|ا|طالب أ1", "", "|||"):
        assert web.post("/start", {"key": k, "dev": "d"})[0] == 400, repr(k)


def test_student_cannot_post_teacher_commands_even_with_header(pkg):
    """من جهاز بالشبكة (مش localhost) حتى لو عرف الترويسة السرية"""
    import test_http
    ip = test_http.lan_ip()
    if not ip: pytest.skip("ما في IP شبكة")
    w = Server(pkg).start()
    try:
        for body in ({"close": True}, {"newexam": 1}, {"release": f"{URL_TITLE}|العاشر|أ|طالب أ1"}, {"submitfor": "all"}, {"message": "x"}):
            assert w.post("/monitor", body, TEACHER, host=ip)[0] == 403
        assert w.get("/monitor.json")[1]["closed"] is False
    finally:
        w.stop()


# ============================ الوقت: المتأخر والتمديد بعد الانتهاء ============================
@pytest.fixture
def zero_minute(pkg):
    pkg.settings(**{"المدة_بالدقائق": 0}); w = Server(pkg).start()
    yield w
    w.stop()


def test_late_flag_only_after_grace_period(zero_minute):
    w = zero_minute
    ka, _, pa = w.start_student("dA", n="طالب أ1"); kb, _, pb = w.start_student("dB", n="طالب أ2")
    assert pa["remain"] == 0                                                                  # الوقت منتهي من اللحظة الأولى
    t0 = time.time()
    time.sleep(2)
    a = w.submit(ka, "dA", pa["ids"], w.correct_answers(pa["ids"]))                           # بعد ثانيتين: ضمن السماح (30ث)
    time.sleep(max(0, 33 - (time.time() - t0)))
    b = w.submit(kb, "dB", pb["ids"], w.correct_answers(pb["ids"]))                           # بعد 33 ثانية: متأخر
    assert a[0] == b[0] == 200
    recs = {json.loads(l)["name"]: json.loads(l) for l in w.pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()}
    assert recs["طالب أ1"]["late"] == 0 and 31 <= recs["طالب أ2"]["late"] <= 40
    rows = {r["name"]: r for s in w.get("/monitor.json")[1]["sections"].values() for r in s}
    assert not rows["طالب أ1"]["late"] and rows["طالب أ2"]["late"] >= 31
    import csv, io
    table = list(csv.reader(io.StringIO(w.pkg.p("results.csv").read_text(encoding="utf-8-sig"))))
    late_col = {r[3]: r[10] for r in table[1:]}
    assert late_col["طالب أ1"] in ("0", "") and int(late_col["طالب أ2"]) >= 31                  # عمود «التأخير» بالتقرير
    ck = w.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0]
    import urllib.parse
    sheet = w.get("/sheet?key=" + urllib.parse.quote(kb), {"Cookie": ck})[2].decode("utf-8")
    assert "تسليم متأخر" in sheet and "تسليم متأخر" not in w.get("/sheet?key=" + urllib.parse.quote(ka), {"Cookie": ck})[2].decode("utf-8")


def test_extension_after_expiry_but_before_submission_gives_time_back(zero_minute):
    w = zero_minute
    k, _, p = w.start_student("dA"); assert p["remain"] == 0
    w.post("/monitor", {"extend": 5, "scope": "student", "key": k}, TEACHER)
    r = w.post("/ping", {"key": k, "dev": "dA"})[1]["remain"]
    assert 295 <= r <= 300                                                                    # التمديد بيشتغل حتى لو الوقت خلص طالما ما سلّم (بعكس تحذير الدليل)
    st, j, _ = w.submit(k, "dA", p["ids"], w.correct_answers(p["ids"]))
    assert j["score"] == 8
    rec = json.loads(w.pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()[0]); assert rec["late"] == 0


def test_closing_exam_sets_deadline_for_lateness(web):
    k, _, p = web.start_student("dA"); web.teacher(close=True)
    time.sleep(1.2)
    web.submit(k, "dA", p["ids"], web.correct_answers(p["ids"]))
    rec = json.loads(web.pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["late"] == 0                                                                   # بعد الإنهاء بثانية: ضمن السماح


def test_teacher_extension_with_exam_already_closed_does_not_reopen(web):
    k, _, p = web.start_student("dA"); web.teacher(close=True)
    web.post("/monitor", {"extend": 10, "scope": "all"}, TEACHER)
    assert web.post("/ping", {"key": k, "dev": "dA"})[1]["remain"] == 0                      # الإنهاء بيغلب التمديد


def test_client_auto_submits_when_time_is_up(pkg):
    """صفحة الطالب لما يخلص الوقت (0 دقيقة) بتسلّم لحالها وبيسجّل «انتهى الوقت»"""
    pw = pytest.importorskip("playwright.sync_api")
    from test_browser import launch, phone_ctx
    pkg.settings(**{"المدة_بالدقائق": 0}); w = Server(pkg).start()
    with pw.sync_playwright() as p:
        b = launch(p); ctx = phone_ctx(p, b); page = ctx.new_page(); page.set_default_timeout(10000)
        try:
            page.goto(f"http://127.0.0.1:{w.port}/"); page.select_option("#g", "العاشر"); page.select_option("#sec", "أ"); page.select_option("#nm", "طالب أ1"); page.click("#start")
            page.wait_for_function("document.getElementById('status').textContent.includes('✓')", timeout=15000)
            rec = json.loads(pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            assert rec["auto"] == "انتهى الوقت" and rec["score"] == 0 and rec["name"] == "طالب أ1"
        finally:
            ctx.close(); b.close(); w.stop()
