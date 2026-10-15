"""اختبار الفوضى: السيرفر بيتقتل فجأة (مثل انقطاع الكهرباء أو إغلاق النافذة بالغلط) وبيرجع يشتغل، والطلاب بيعيدوا المحاولة.
القاعدة الذهبية: أي طالب أخذ «تم الحفظ» (200 + علامة) لازم تسليمه يكون موجود مرة وحدة بالملفات بعد الفوضى، بنفس العلامة."""
import http.client, json, random, socket, threading, time

import pytest
from conftest import bank
from test_http import Server, free_port


def call(port, path, body, tries=80):
    """نفس سلوك الطالب: لو انقطع الاتصال أو رجع خطأ سيرفر بيعيد المحاولة"""
    last = None
    for _ in range(tries):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            c.request("POST", path, json.dumps(body, ensure_ascii=False).encode(), {"Content-Type": "application/json"})
            r = c.getresponse(); raw = r.read()
            if r.status >= 500: last = r.status; time.sleep(0.2); continue
            try: return r.status, json.loads(raw)
            except Exception: return r.status, None
        except (OSError, http.client.HTTPException) as e:                     # الاتصال انقطع/رُفض/انقطع بنص الرد
            last = e; time.sleep(0.2)
        finally:
            c.close()
    raise RuntimeError(f"فشلت كل المحاولات: {last!r}")


class Chaos:
    """يقتل السيرفر (TerminateProcess = أقسى من Ctrl+C) ويشغّله من جديد على نفس المنفذ كل فترة"""
    def __init__(self, pkg, port):
        self.pkg, self.port, self.kills, self.stop_evt, self.server = pkg, port, 0, threading.Event(), None
        self.errors = []

    def boot(self):
        for _ in range(30):
            s = Server(self.pkg)
            try:
                s.start(port=self.port); self.server = s; return
            except RuntimeError:
                s.stop(); time.sleep(0.3)
        raise RuntimeError("السيرفر ما رجع يشتغل على نفس المنفذ")

    def loop(self, kills, rng):
        try:
            for _ in range(kills):
                if self.stop_evt.wait(rng.uniform(0.3, 0.9)): break
                self.server.proc.kill(); self.server.proc.wait(); self.kills += 1
                time.sleep(rng.uniform(0.1, 0.6))
                self.boot()
        except Exception as e:                                                  # noqa
            self.errors.append(repr(e))


def student_flow(port, i, name, results, errors, title="اختبار الوحدة"):
    try:
        k, dev = f"{title}|العاشر|أ|{name}", f"dev{i}"
        starts = []
        st, p = call(port, "/start", {"key": k, "dev": dev})
        assert st == 200 and p["status"] == "ok", (st, p); starts.append(p["ids"])
        ids = p["ids"]; correct = [(n - 1) % 4 for n in ids]
        n_ok = i % 9; ans = correct[:n_ok] + [(c + 1) % 4 for c in correct[n_ok:]]
        for r in range(6):
            call(port, "/ping", {"key": k, "dev": dev, "ans": {str(n): a for n, a in zip(ids, ans)}, "answered": 8, "total": 8, "remain": 1500})
            time.sleep(random.uniform(0.2, 0.6))
            st, again = call(port, "/start", {"key": k, "dev": dev})            # الطالب بيعيد فتح الصفحة (مثلاً بعد انقطاع)
            assert again.get("status") == "ok" and again["ids"] == ids and again["orders"] == p["orders"], again   # نفس الورقة دائماً
        st, j = call(port, "/submit", {"key": k, "dev": dev, "ids": ids, "answers": ",".join(map(str, ans)), "auto": "t", "leave": ""})
        assert st == 200 and "score" in j, (st, j)
        results[name] = (j["score"], n_ok)
    except Exception as e:                                                      # noqa
        errors.append((name, repr(e)))


@pytest.mark.parametrize("seed", [1, 2])
def test_server_killed_repeatedly_under_load_loses_no_acknowledged_submission(pkg, seed):
    N = 40
    pkg.students([["العاشر", "أ", f"طالب {i:02d}", ""] for i in range(N)]); pkg.questions(bank(6, 8, 8))
    port = free_port(); ch = Chaos(pkg, port); ch.boot(); rng = random.Random(seed)
    results, errors = {}, []
    killer = threading.Thread(target=ch.loop, args=(12, rng), daemon=True); killer.start()
    ths = [threading.Thread(target=student_flow, args=(port, i, f"طالب {i:02d}", results, errors)) for i in range(N)]
    for t in ths: t.start(); time.sleep(0.1)
    for t in ths: t.join(240)
    ch.stop_evt.set(); killer.join(30)
    try:
        assert not ch.errors, ch.errors
        assert not errors, errors[:3]
        assert ch.kills >= 3, f"الفوضى ما صارت كفاية: {ch.kills} قتلات"
        assert len(results) == N
        # ---- بعد الفوضى: سيرفر نظيف يقرأ الملفات ----
        ch.server.stop(); ch.boot()
        final = ch.server
        lines = pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()
        recs = []
        for ln in lines:
            recs.append(json.loads(ln))                                          # ما في سطر تالف
        by_name = {}
        for r in recs: by_name.setdefault(r["name"], []).append(r)
        assert all(len(v) == 1 for v in by_name.values()), {k: len(v) for k, v in by_name.items() if len(v) > 1}     # ولا تسليم مكرر
        for name, (score, n_ok) in results.items():
            assert name in by_name, f"ضاع تسليم {name} رغم إنه أخذ «تم»"
            assert by_name[name][0]["score"] == score == n_ok                    # نفس العلامة اللي أخذها الطالب = الصحيح
        mj = final.get("/monitor.json")[1]
        assert mj["c"] == {"done": N, "live": 0, "lost": 0, "none": 0}
        import csv, io
        csv_rows = list(csv.reader(io.StringIO(pkg.p("results.csv").read_text(encoding="utf-8-sig"))))    # عمود الأخطاء فيه أسطر متعددة داخل الحقل
        assert len(csv_rows) == N + 1 and len({r[3] for r in csv_rows[1:]}) == N          # الترويسة + صف لكل طالب بدون تكرار
        for f in ("claims.json", "papers.json", "state.json", "answers.json"):   # ملفات الحالة سليمة (الكتابة ذرّية)
            if pkg.p(f).exists(): json.loads(pkg.p(f).read_text(encoding="utf-8"))
        print(f"[chaos seed={seed}] قتلات: {ch.kills} | تسليمات: {len(recs)} | ضاع: 0")
    finally:
        ch.server.stop()


def test_restart_between_start_and_submit_keeps_same_paper_and_score(pkg):
    """سيناريو بسيط ومحدد: بدأ ← قتل ← رجع ← تسليم: نفس الورقة والعلامة"""
    port = free_port(); ch = Chaos(pkg, port); ch.boot()
    try:
        k, dev = "اختبار الوحدة|العاشر|أ|طالب أ1", "d1"
        p = call(port, "/start", {"key": k, "dev": dev})[1]
        ch.server.proc.kill(); ch.server.proc.wait(); ch.boot()
        again = call(port, "/start", {"key": k, "dev": dev})[1]
        assert again["ids"] == p["ids"] and again["orders"] == p["orders"] and again["remain"] <= p["remain"]
        correct = [(n - 1) % 4 for n in p["ids"]]
        st, j = call(port, "/submit", {"key": k, "dev": dev, "ids": p["ids"], "answers": ",".join(map(str, correct))})
        assert (st, j["score"]) == (200, 8)
    finally:
        ch.server.stop()


def test_kill_right_after_submit_ack_then_resubmit_returns_same_result(pkg):
    port = free_port(); ch = Chaos(pkg, port); ch.boot()
    try:
        k, dev = "اختبار الوحدة|العاشر|أ|طالب أ1", "d1"
        p = call(port, "/start", {"key": k, "dev": dev})[1]
        ans = ",".join(str((n - 1) % 4) for n in p["ids"])
        first = call(port, "/submit", {"key": k, "dev": dev, "ids": p["ids"], "answers": ans})[1]
        ch.server.proc.kill(); ch.server.proc.wait(); ch.boot()
        again = call(port, "/submit", {"key": k, "dev": dev, "ids": p["ids"], "answers": "0,0,0,0,0,0,0,0"})[1]   # إعادة إرسال (حتى بإجابات مختلفة): بتنرد بالنتيجة المحفوظة
        assert again == {"score": first["score"], "total": first["total"], "dup": True}
        assert len(pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    finally:
        ch.server.stop()


def test_torn_last_line_in_submissions_does_not_swallow_next_submission(pkg):
    """انقطاع كهرباء أثناء كتابة سطر تسليم: سطر مقطوع بدون \\n. التسليم اللي بعده لازم ما يضيع (ما ينلصق بالمقطوع)"""
    pkg.p("submissions.jsonl").write_text('{"key": "x|y|z|w", "exam": "اختبار الوحدة", "grade": "العاشر", "sec', encoding="utf-8")     # بدون newline بالنهاية
    port = free_port(); ch = Chaos(pkg, port); ch.boot()
    try:
        k, dev = "اختبار الوحدة|العاشر|أ|طالب أ1", "d1"
        p = call(port, "/start", {"key": k, "dev": dev})[1]
        st, j = call(port, "/submit", {"key": k, "dev": dev, "ids": p["ids"], "answers": ",".join(str((n - 1) % 4) for n in p["ids"])})
        assert (st, j["score"]) == (200, 8)
        ch.server.stop(); ch.boot()
        assert call(port, "/start", {"key": k, "dev": dev})[1] == {"status": "done"}          # بعد إعادة التشغيل لسا مسلّم
        assert ch.server.get("/monitor.json")[1]["c"]["done"] == 1
    finally:
        ch.server.stop()
