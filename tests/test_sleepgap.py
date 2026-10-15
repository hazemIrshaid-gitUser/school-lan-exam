"""جهاز المعلم نام (انسكّر غطاء اللابتوب) أو تجمّد وسط الامتحان ثم رجع: السيرفر ما انطفى، فلازم يكتشف القفزة بالوقت ويعوّض الطلاب
بنفس قواعد تعويض التوقف (المسلّم والمنقول ومن خلص وقته قبل النوم ما بيتعوّضوا، وأكثر من 30 دقيقة ما بنعوّض تلقائياً).
الاختبارات الحقيقية بتجمّد عملية السيرفر فعلاً (suspend) وبترجّعها."""
import http.server, json, threading, time, types, urllib.request

import psutil
import pytest
from conftest import key_of, start_paper
from test_http import Server
from test_outage import comp, kill, papers, remain


def three(m):
    """A بيمتحن، B سلّم، C منقول (وقته متجمّد)"""
    kA = start_paper(m, key_of(m, n="طالب أ1"), "dA")
    kB = start_paper(m, key_of(m, n="طالب أ2"), "dB"); m.SUBS[kB] = {"key": kB, "score": 1, "total": 1}
    kC = start_paper(m, key_of(m, n="طالب أ3"), "dC"); m.PAPERS[kC]["frozen"] = 600
    return kA, kB, kC


# ============================ وحدة: gap_check ============================
def test_no_tracking_until_the_save_loop_runs(srv):
    """check_files.py بيستورد السيرفر بدون دورة الحفظ: ما لازم يصير أي تعويض"""
    kA, *_ = three(srv)
    assert srv.LAST_TICK[0] is None and srv.gap_check() is None and srv.gap_check(tick=True) is None
    assert "extra" not in srv.PAPERS[kA] and "comp" not in srv.STATE


def test_normal_ticks_do_nothing_but_move_the_clock(srv):
    kA, *_ = three(srv)
    srv.LAST_TICK[0] = time.time() - 10
    assert srv.gap_check() is None and time.time() - srv.LAST_TICK[0] >= 9                # طلب عادي ما بيحرّك الساعة
    assert srv.gap_check(tick=True) is None and time.time() - srv.LAST_TICK[0] < 1          # دورة الحفظ بتحرّكها
    assert "extra" not in srv.PAPERS[kA] and "comp" not in srv.STATE


def test_sleep_gap_compensates_only_students_still_taking_the_exam(srv):
    kA, kB, kC = three(srv)
    srv.LAST_TICK[0] = time.time() - 300
    rec = srv.gap_check()
    assert rec and rec["sleep"] is True and 299 <= rec["downtime_s"] <= 301 and rec["students"] == 1 and srv.STATE["comp"] == rec
    assert srv.PAPERS[kA]["extra"] == rec["downtime_s"] and "extra" not in srv.PAPERS[kB] and "extra" not in srv.PAPERS[kC]
    assert srv.gap_check() is None and srv.gap_check(tick=True) is None and srv.PAPERS[kA]["extra"] == rec["downtime_s"]   # مرة وحدة بس
    assert json.loads(open(srv.PAPERS_FILE, encoding="utf-8").read())[kA]["extra"] == rec["downtime_s"]                   # انحفظ على الملف


def test_student_whose_time_ended_before_the_sleep_is_not_extended(srv):
    kA, *_ = three(srv)
    srv.PAPERS[kA]["start"] -= srv.SET["minutes"] * 60 + 400                                # خلص وقته قبل 400 ث
    srv.LAST_TICK[0] = time.time() - 300
    assert srv.gap_check()["students"] == 0 and "extra" not in srv.PAPERS[kA]


def test_long_sleep_is_not_compensated_automatically(srv):
    kA, *_ = three(srv)
    srv.LAST_TICK[0] = time.time() - 31 * 60
    rec = srv.gap_check(); assert rec["skipped"] and rec["sleep"] and "extra" not in srv.PAPERS[kA]


def test_setting_off_applies_to_sleep_too(pkg):
    pkg.settings(**{"تعويض_توقف_السيرفر": "لا"}); m = pkg.load()
    kA, *_ = three(m)
    m.LAST_TICK[0] = time.time() - 120
    rec = m.gap_check(); assert rec["off"] and "extra" not in m.PAPERS[kA]


def test_sleep_notice_wording_on_health_page(srv):
    three(srv); srv.LAST_TICK[0] = time.time() - 120; srv.gap_check()
    t = srv.health_page(srv.health_data()); assert "جهاز السيرفر نام أو تجمّد" in t and "مدّدنا وقت 1 طالب" in t


def test_any_student_request_detects_the_gap_first(srv):
    """أول طلب بعد ما يصحى الجهاز (قبل دورة الحفظ): التعويض لازم يصير قبل ما نحسب الوقت المتبقي"""
    kA, *_ = three(srv)
    srv.PAPERS[kA]["start"] -= srv.SET["minutes"] * 60 - 100                                # باقيله 100 ث
    srv.LAST_TICK[0] = time.time() - 200                                                     # ونام الجهاز 200 ث: من غير تعويض الوقت خالص
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), srv.H); threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        rq = urllib.request.Request(f"http://127.0.0.1:{s.server_address[1]}/ping", json.dumps({"key": kA, "dev": "dA"}).encode(), {"Content-Type": "application/json"})
        r = json.loads(urllib.request.urlopen(rq, timeout=10).read())
        assert 290 <= r["remain"] <= 301 and srv.STATE["comp"]["sleep"]
    finally:
        s.shutdown(); s.server_close()


class _Stop(BaseException): pass


def test_save_loop_survives_unexpected_errors(srv, monkeypatch):
    """لو صار خطأ غير متوقع بدورة الحفظ، الدورة بتكمل (هي اللي بتحفظ الإجابات وبتكتب نبضة alive.txt)"""
    calls = {"n": 0}
    def flaky():
        calls["n"] += 1
        if calls["n"] <= 2: raise RuntimeError("boom")
    def fast_sleep(_):
        if calls["n"] >= 5: raise _Stop()
        time.sleep(0.01)
    monkeypatch.setattr(srv, "flush_answers", flaky)
    monkeypatch.setattr(srv, "time", types.SimpleNamespace(sleep=fast_sleep, time=time.time, strftime=time.strftime))
    monkeypatch.setattr(threading, "excepthook", lambda a: None)
    t = threading.Thread(target=srv.flusher, daemon=True); t.start(); t.join(10)
    assert not t.is_alive() and calls["n"] >= 5 and float(open(srv.ALIVE_FILE).read()) > time.time() - 5


def test_save_loop_detects_the_gap_even_without_any_student_request(srv, monkeypatch):
    """ما في ولا طلب بعد ما صحي الجهاز (مثلاً الطلاب كلهم سلّموا إلا واحد جواله مقفول): دورة الحفظ نفسها بتعوّض"""
    kA, *_ = three(srv); srv.LAST_TICK[0] = time.time() - 200
    n = {"i": 0}
    def one_round(_):
        n["i"] += 1
        if n["i"] > 1: raise _Stop()
    monkeypatch.setattr(srv, "time", types.SimpleNamespace(sleep=one_round, time=time.time, strftime=time.strftime))
    monkeypatch.setattr(threading, "excepthook", lambda a: None)
    t = threading.Thread(target=srv.flusher, daemon=True); t.start(); t.join(10)
    assert srv.STATE["comp"]["sleep"] and 199 <= srv.PAPERS[kA]["extra"] <= 201 and time.time() - srv.LAST_TICK[0] < 2


# ============================ حقيقي: تجميد عملية السيرفر ============================
def freeze(s, sec):
    p = psutil.Process(s.proc.pid); p.suspend()
    try: time.sleep(sec)
    finally: p.resume()


@pytest.fixture
def servers():
    made = []
    def start(pkg):
        s = Server(pkg).start(); made.append(s); return s
    yield start
    for s in made:
        try: psutil.Process(s.proc.pid).resume()
        except psutil.Error: pass
        s.stop()


def test_frozen_server_compensates_when_it_wakes(pkg, servers):
    s = servers(pkg)
    kA, _, _ = s.start_student("dA")
    kB, _, pB = s.start_student("dB", n="طالب أ2"); s.submit(kB, "dB", pB["ids"], s.correct_answers(pB["ids"]))
    time.sleep(4.2)
    r0 = remain(s, kA, "dA"); freeze(s, 25)
    r1 = remain(s, kA, "dA")
    assert r0 - r1 < 8, f"خسر {r0 - r1} ث"
    c = comp(s); assert c["sleep"] is True and c["students"] == 1 and 22 <= c["downtime_s"] <= 33
    assert papers(pkg)[kA]["extra"] == c["downtime_s"] and "extra" not in papers(pkg)[kB]


def test_student_whose_time_ran_out_during_the_freeze_gets_it_back(pkg, servers):
    pkg.settings(**{"المدة_بالدقائق": 1})
    s1 = servers(pkg); kA, _, _ = s1.start_student("dA"); kill(s1)
    P = papers(pkg); P[kA]["start"] -= 46; pkg.p("papers.json").write_text(json.dumps(P, ensure_ascii=False), encoding="utf-8")   # باقيله ~14 ث
    pkg.p("alive.txt").write_text(repr(time.time()))                                       # ما في تعويض «إعادة تشغيل»
    s2 = servers(pkg); time.sleep(4.2)
    assert 0 < remain(s2, kA, "dA") <= 12
    freeze(s2, 20)                                                                           # وقته خلص وهو متجمّد
    st, j, *_ = s2.post("/resume", {"key": kA, "dev": "dA"})                                # صفحة الطالب بتعمل هيك بعد ما ترجع تتصل
    assert st == 200 and j["status"] == "ok" and j["remain"] > 3, j                          # رجع لامتحانه بالوقت المعوّض
    ids = j["ids"]; st, r = s2.submit(kA, "dA", ids, s2.correct_answers(ids))[:2]
    assert st == 200 and r["score"] == r["total"]
    sub = [json.loads(x) for x in pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()][-1]
    assert sub["late"] == 0 and comp(s2)["sleep"]


def test_monitor_shows_the_sleep_notice_in_a_real_browser(srv):
    pw = pytest.importorskip("playwright.sync_api")
    three(srv); srv.LAST_TICK[0] = time.time() - 125; srv.gap_check()
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), srv.H); threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch(channel="msedge", headless=True); pg = b.new_page(); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            try:
                pg.goto(f"http://127.0.0.1:{s.server_address[1]}/monitor"); pg.wait_for_selector("#compbar", state="visible", timeout=8000)
                t = pg.inner_text("#compbar")
                assert "جهاز السيرفر نام أو تجمّد 2 دقيقة و5 ثانية" in t and "مدّدنا تلقائياً وقت 1 طالب" in t and "السيرفر كان متوقفاً" not in t and not errs, t
            finally:
                b.close()
    finally:
        s.shutdown(); s.server_close()
