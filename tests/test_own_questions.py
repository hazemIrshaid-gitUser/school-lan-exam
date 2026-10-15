"""صفحة الطالب ما فيها بنك الأسئلة: الطالب بياخذ أسئلة ورقته بس (من /start و/resume)، بدون الإجابة والحل والمستوى والمرجع.
قبل: أي حدا على الشبكة بيفتح الرابط (حتى قبل الامتحان) كان بيشوف كل البنك من «عرض المصدر» أو أدوات المطوّر."""
import json, time

import pytest
from test_http import Server, lan_ip
from test_browser import browser, phone, login, pick, solve, submit, url, web  # noqa: F401  (fixtures)

BANK_TEXTS = [f"سؤال رقم {i}" for i in range(1, 12)]
plain = lambda t: t.replace(chr(0x2066), "").replace(chr(0x2069), "")          # علامات عزل الاتجاه حوالين الأرقام


def test_student_page_has_no_question_bank(web):
    for host in ("127.0.0.1", lan_ip()):
        if not host: continue
        t = web.get("/", host=host)[2].decode("utf-8")
        assert "const QUESTIONS = [];" in t and not any(x in t for x in BANK_TEXTS) and "خ0-" not in t, host


def test_start_sends_only_this_students_questions_without_answers(web):
    k1, _, p1 = web.start_student("d1")
    k2, _, p2 = web.start_student("d2", n="طالب أ2")
    for p in (p1, p2):
        assert [q["n"] for q in p["qs"]] == p["ids"] and len(p["qs"]) == 8                    # ورقته هو بس (8 من 11)
        assert all(set(q) == {"n", "marks", "q", "o"} for q in p["qs"])                      # بدون a / sol / level / page
        assert all(plain(q["q"]) == f"سؤال رقم {q['n']}" for q in p["qs"])
    raw = json.dumps(p1, ensure_ascii=False)
    assert '"a"' not in raw and "الحل" not in raw
    st, r, *_ = web.post("/resume", {"key": k1, "dev": "d1"}); assert r["qs"] == p1["qs"]


def test_review_items_carry_their_question_text(pkg):
    pkg.settings(**{"مراجعة_الأخطاء": "نعم"}); w = Server(pkg).start()
    try:
        k, _, p = w.start_student("d1"); ans = w.correct_answers(p["ids"]); ans[0] = (ans[0] + 1) % 4
        w.submit(k, "d1", p["ids"], ans)
        st, r, *_ = w.post("/review", {"key": k, "dev": "d1"})
        it = r["items"][0]
        assert r["status"] == "ok" and len(r["items"]) == 1 and plain(it["q"]) == f"سؤال رقم {p['ids'][0]}" and len(it["o"]) == 4
    finally:
        w.stop()


def test_browser_only_ever_holds_its_own_paper(phone, web):
    page = phone(); page.goto(url(web))
    assert page.evaluate("QUESTIONS.length") == 0                                                 # قبل البدء: ولا سؤال
    login(page, web)
    assert page.evaluate("QUESTIONS.length") == 8 and page.locator("#qs .card").count() == 8
    assert page.evaluate("QUESTIONS.every(q=>q.a===undefined && q.level===undefined)")


def test_exam_survives_a_failed_resume_request(phone, web):
    """الصفحة انعاد تحميلها بس طلب الاستئناف فشل لحظياً (ضعف شبكة): أسئلة الورقة محفوظة على الجهاز، فالامتحان بيرجع بإجاباته
    (بدونها كان الطالب يرجع لشاشة الدخول)"""
    page = phone(); login(page, web)
    pick(page, 0, 0); pick(page, 1, 1); time.sleep(0.5)
    page.route("**/resume", lambda r: r.abort())
    page.reload(); page.wait_for_selector("#s-exam:not(.hide)", timeout=20000)
    assert page.locator("#qs .card").count() == 8 and page.eval_on_selector_all("#qs input:checked", "e=>e.length") == 2
    page.unroute("**/resume")
    solve(page); submit(page)
    page.wait_for_function("document.getElementById('status').textContent.includes('✓')", timeout=20000)
    assert "8 / 8" in plain(page.inner_text("#score"))


@pytest.mark.parametrize("path", ["/", "/index.html"])
def test_page_size_no_longer_grows_with_the_bank(pkg, path):
    from conftest import bank
    sizes = []
    for n in (4, 40):
        pkg.questions(bank(n, n, n)); w = Server(pkg).start()
        try: sizes.append(len(w.get(path)[2]))
        finally: w.stop()
    assert abs(sizes[1] - sizes[0]) < 200, sizes                                                   # 12 سؤال أو 120: نفس الصفحة
