"""المرحلة 1: اختبارات منطق السيرفر (سحب الأوراق، التصحيح، العلامات، الوقت، رموز الدخول، تقارير) بدون شبكة."""
import io, json, os, time
from collections import Counter

import openpyxl
import pytest
from conftest import bank, key_of, q, roster, start_paper


# ---------- دوال صغيرة ----------
@pytest.mark.parametrize("x,expected", [(3.0, 3), (2.5000001, 2.5), (2.499, 2.5), (0, 0), ("7", 7), (1.25, 1.25)])
def test_num(srv, x, expected):
    assert srv.num(x) == expected


@pytest.mark.parametrize("m,expected", [(1, "علامة واحدة"), (2, "علامتان"), (3, "3 علامات"), (10, "10 علامات"), (11, "11 علامة"), (2.5, "2.5 علامة"), (0.5, "0.5 علامة")])
def test_mtxt(srv, m, expected):
    assert srv.mtxt(m) == expected


@pytest.mark.parametrize("given", ["123456", "١٢٣٤٥٦", "۱۲۳۴۵۶", "  123456 \n"])
def test_norm_code_digit_variants(srv, given):
    assert srv.norm_code(given) == "123456"


def test_autoltr_wraps_math_and_is_idempotent(srv):
    s = "احسب x+1=2 الآن"
    out = srv.autoltr(s)
    assert "⁦x+1=2⁩" in out and srv.autoltr(out) == out


@pytest.mark.parametrize("s", ["ما هي عاصمة الأردن؟", "", "كلمات عربية فقط، بدون أرقام."])
def test_autoltr_leaves_pure_arabic(srv, s):
    assert srv.autoltr(s) == s


def test_atomic_write_overwrites_without_tmp(srv, tmp_path):
    p = str(tmp_path / "f.json")
    srv.atomic_write(p, "one"); srv.atomic_write(p, "اثنان")
    assert open(p, encoding="utf-8").read() == "اثنان" and not os.path.exists(p + ".tmp")


# ---------- سحب الورقة ----------
def _level_counts(m, ids):
    return Counter(m.BANK[n]["level"] for n in ids)


def test_paper_has_requested_counts_unique_and_valid_orders(srv):
    for _ in range(100):
        p = srv.make_paper()
        assert _level_counts(srv, p["ids"]) == Counter(srv.PICK) - Counter({k: 0 for k in srv.PICK}) or _level_counts(srv, p["ids"]) == Counter({k: v for k, v in srv.PICK.items() if v})
        assert len(set(p["ids"])) == len(p["ids"]) == 8
        for n, o in zip(p["ids"], p["orders"]):
            assert sorted(o) == list(range(len(srv.BANK[n]["o"])))


def test_every_question_eventually_appears_and_papers_differ(srv):
    papers = [srv.make_paper() for _ in range(300)]
    assert {n for p in papers for n in p["ids"]} == set(srv.BANK)
    assert len({tuple(p["ids"]) for p in papers}) > 20


def test_options_actually_shuffled(srv):
    orders = {tuple(o) for _ in range(60) for o in srv.make_paper()["orders"]}
    assert len(orders) > 5


def test_no_shuffle_gives_sorted_ids_and_identity_orders(pkg):
    pkg.settings(**{"خلط_الأسئلة": "لا", "خلط_الخيارات": "لا"})
    m = pkg.load()
    for _ in range(20):
        p = m.make_paper()
        assert p["ids"] == sorted(p["ids"]) and all(o == list(range(len(o))) for o in p["orders"])


def test_fixed_questions_in_every_paper(pkg):
    rows = bank()
    rows[0][10] = "نعم"; rows[3][10] = "نعم"          # صعب ثابت + وسط ثابت
    pkg.questions(rows)
    m = pkg.load()
    fixed = [qq["n"] for qq in m.QLIST if qq["fixed"]]
    assert len(fixed) == 2
    for _ in range(100):
        ids = m.make_paper()["ids"]
        assert set(fixed) <= set(ids) and len(ids) == 8


def test_all_fixed_at_a_level_equals_pick(pkg):
    rows = bank(hard=2, medium=4, easy=4)
    for r in rows[:2]: r[10] = "نعم"                  # كل الصعب (2) ثابت والمطلوب 2
    pkg.questions(rows)
    m = pkg.load()
    for _ in range(30): assert len(m.make_paper()["ids"]) == 8


def test_roster_ordering_does_not_break_parse_key(srv):
    assert srv.parse_key(key_of(srv)) == ("العاشر", "أ", "طالب أ1")
    assert srv.parse_key(key_of(srv, n="غير موجود")) is None
    assert srv.parse_key("عنوان آخر|العاشر|أ|طالب أ1") is None
    assert srv.parse_key("garbage") is None and srv.parse_key(None) is None and srv.parse_key(5) is None


def test_title_containing_pipe(pkg):
    pkg.settings(**{"عنوان_الامتحان": "فيزياء|وحدة 2"})
    m = pkg.load()
    k = f"{m.SET['title']}|العاشر|أ|طالب أ1"
    assert m.parse_key(k) == ("العاشر", "أ", "طالب أ1")
    start_paper(m, k)
    assert m.find_keys()[("العاشر", "أ", "طالب أ1")] == k


# ---------- تنظيف الإجابات المحفوظة ----------
def test_clean_ans_filters_foreign_and_out_of_range(srv):
    k = start_paper(srv); ids = srv.PAPERS[k]["ids"]
    other = next(n for n in srv.BANK if n not in ids)
    got = srv.clean_ans(k, {str(ids[0]): 2, str(ids[1]): "1", str(other): 0, str(ids[2]): 9, str(ids[3]): -1, "abc": 1, str(ids[4]): None})
    assert got == {str(ids[0]): 2, str(ids[1]): 1}


@pytest.mark.parametrize("bad", [None, [], "x", 5])
def test_clean_ans_rejects_non_dict(srv, bad):
    assert srv.clean_ans(start_paper(srv), bad) is None


# ---------- التصحيح وتسليم المعلم ----------
def _answers_for(m, ids, n_correct):
    """إجابات محفوظة: أول n_correct صحيحة والباقي خطأ"""
    out = {}
    for i, n in enumerate(ids):
        a = m.BANK[n]["a"]
        out[str(n)] = a if i < n_correct else (a + 1) % len(m.BANK[n]["o"])
    return out


def test_submit_for_scores_saved_answers(srv):
    k = start_paper(srv); ids = srv.PAPERS[k]["ids"]
    srv.ANS[k] = _answers_for(srv, ids, 5)
    assert srv.submit_for(k) is True
    s = srv.SUBS[k]
    assert (s["score"], s["total"]) == (5, 8) and s["auto"] == "تسليم من المعلم"
    assert k not in srv.ANS and s["answers"].count(-1) == 0
    line = json.loads(open(srv.SUBS_FILE, encoding="utf-8").read().splitlines()[-1])
    assert line["key"] == k and line["score"] == 5


def test_submit_for_unanswered_counts_wrong(srv):
    k = start_paper(srv); srv.ANS[k] = {}
    srv.submit_for(k)
    s = srv.SUBS[k]
    assert s["score"] == 0 and s["answers"] == [-1] * 8
    assert "لم يجب" in srv.wrong_text(srv.wrong_items(s["ids"], s["answers"]))


def test_submit_for_twice_and_unclaimed(srv):
    k = start_paper(srv)
    assert srv.submit_for(k) is True and srv.submit_for(k) is False
    k2 = key_of(srv, n="طالب أ2"); srv.PAPERS[k2] = srv.make_paper()          # ورقة بدون حجز
    assert srv.submit_for(k2) is False
    assert srv.submit_for(key_of(srv, n="مجهول")) is False
    assert len(open(srv.SUBS_FILE, encoding="utf-8").read().splitlines()) == 1


def test_submit_for_scales_to_final_mark(pkg):
    pkg.settings(**{"العلامة_النهائية": 20})
    m = pkg.load()
    k = start_paper(m); m.ANS[k] = _answers_for(m, m.PAPERS[k]["ids"], 4)
    m.submit_for(k)
    assert (m.SUBS[k]["score"], m.SUBS[k]["total"]) == (10, 20)


def test_submit_for_weighted_marks(pkg):
    rows = bank(); rows[0][9] = 3; rows[4][9] = 2          # أسئلة بعلامات 3 و2 والباقي 1
    pkg.questions(rows); pkg.settings(**{"عدد_الأسئلة_الصعبة": 3, "عدد_الأسئلة_المتوسطة": 4, "عدد_الأسئلة_السهلة": 4, "عدد_الأسئلة_الكلي": 11})
    m = pkg.load()
    k = start_paper(m); ids = m.PAPERS[k]["ids"]
    m.ANS[k] = {str(n): m.BANK[n]["a"] for n in ids}        # كلها صحيحة
    m.submit_for(k)
    assert m.SUBS[k]["score"] == m.SUBS[k]["total"] == 11 + 2 + 1


def test_qmark_setting_overrides_column_marks(pkg):
    rows = bank(); rows[0][9] = 5
    pkg.questions(rows); pkg.settings(**{"علامة_السؤال": 2})
    m = pkg.load()
    assert {qq["marks"] for qq in m.QLIST} == {2}
    assert m.total_range(m.PICK) == (16, 16)


# ---------- العلامات ----------
def test_total_range_with_and_without_final(pkg):
    m = pkg.load()
    assert m.total_range(m.PICK) == (8, 8)
    pkg.settings(**{"العلامة_النهائية": 30})
    m2 = pkg.load()
    assert m2.total_range(m2.PICK) == (30, 30)
    assert m2.key_mark(1) == 3.75
    ids = list(range(1, 9))
    assert m2.eff_mark(1, ids) == 3.75


def test_mixed_marks_range(pkg):
    rows = bank()
    for r in rows[:3]: r[9] = 3                                  # الصعب كلها 3 (لا تغير شي)
    for r in rows[3:7]: r[9] = 1
    rows[3][9] = 2                                               # وسط: 2,1,1,1 والمطلوب 3
    pkg.questions(rows)
    m = pkg.load()
    lo, hi = m.raw_range(m.PICK)
    assert (lo, hi) == (6 + 3 + 3, 6 + 4 + 3)


# ---------- الوقت ----------
def test_remaining_time_and_extension_scopes(srv):
    a = start_paper(srv); b = start_paper(srv, key_of(srv, n="طالب أ2"), "d2"); c = start_paper(srv, key_of(srv, s="ب", n="طالب ب1"), "d3")
    assert 1795 <= srv.remain_of(a) <= 1800
    assert srv.extend_time(5, "student", {"key": a}) == 1 and srv.PAPERS[a]["extra"] == 300
    assert srv.extend_time(2, "section", {"grade": "العاشر", "section": "أ"}) == 2
    assert (srv.PAPERS[a]["extra"], srv.PAPERS[b]["extra"], srv.PAPERS[c].get("extra", 0)) == (420, 120, 0)
    assert srv.extend_time(1, "all", {}) == 3 and srv.PAPERS[c]["extra"] == 60
    assert 2275 <= srv.remain_of(a) <= 2280                     # 1800 + 300 + 120 + 60


def test_extension_skips_submitted(srv):
    a = start_paper(srv); b = start_paper(srv, key_of(srv, n="طالب أ2"), "d2")
    srv.submit_for(a)
    assert srv.extend_time(5, "all", {}) == 1 and srv.PAPERS[a].get("extra", 0) == 0


def test_closing_exam_ends_all_deadlines(srv):
    a = start_paper(srv)
    srv.STATE["closed_at"] = time.time() - 1
    assert srv.remain_of(a) == 0
    srv.STATE["closed_at"] = time.time() + 10_000            # إنهاء بعيد: ما بيطوّل وقت الطالب
    assert srv.remain_of(a) <= 1800


def test_deadline_survives_restart(pkg):
    """إعادة تشغيل السيرفر: الأوراق والحجوزات ترجع من الملفات (الوقت يُحسب من وقت البدء الأصلي)"""
    m = pkg.load()
    k = start_paper(m); m.save_papers(); m.save_claims()
    m2 = pkg.load()
    assert k in m2.PAPERS and m2.CLAIMS[k] == "dev1" and m2.PAPERS[k]["ids"] == m.PAPERS[k]["ids"]


# ---------- رموز الدخول ----------
@pytest.fixture
def coded(pkg):
    pkg.settings(**{"رمز_الدخول": "نعم"})
    pkg.students([["العاشر", "أ", "طالب أ1", "٤٥٦٧٨٩"], ["العاشر", "أ", "طالب أ2", ""], ["العاشر", "ب", "طالب ب1", ""]])
    return pkg.load()


def test_codes_manual_and_generated(coded):
    k1 = key_of(coded); k2 = key_of(coded, n="طالب أ2")
    assert coded.CODES["العاشر|أ|طالب أ1"] == "456789"
    gen = coded.CODES["العاشر|أ|طالب أ2"]
    assert len(gen) == 6 and gen.isdigit()
    assert coded.check_code(k1, "456789") is None and coded.check_code(k1, "٤٥٦٧٨٩") is None
    assert coded.check_code(k2, gen) is None


def test_codes_persist_across_restarts(pkg):
    pkg.settings(**{"رمز_الدخول": "نعم"})
    c1 = dict(pkg.load().CODES); c2 = dict(pkg.load().CODES)
    assert c1 == c2 and len(c1) == 5


def test_wrong_code_lockout_and_expiry(coded, monkeypatch):
    k = key_of(coded)
    assert coded.check_code(k, "000000") == "badcode"
    assert coded.check_code(k, None) == "badcode"
    for _ in range(2): assert coded.check_code(k, "111111") == "badcode"
    assert coded.check_code(k, "222222") == "badcode"            # الخامسة: بتفعّل القفل
    assert coded.check_code(k, "456789") == "locked"             # حتى الرمز الصحيح مرفوض أثناء القفل
    real = time.time
    monkeypatch.setattr(coded.time, "time", lambda: real() + 61)
    assert coded.check_code(k, "456789") is None


def test_lockout_is_per_student(coded):
    a, b = key_of(coded), key_of(coded, n="طالب أ2")
    for _ in range(5): coded.check_code(a, "x")
    assert coded.check_code(a, "456789") == "locked"
    assert coded.check_code(b, "x") == "badcode"


# ---------- الأمان: تهريب HTML ----------
EVIL = "<script>alert(1)</script>"


def test_question_text_escaped_in_student_page_and_preview_and_key(pkg):
    rows = bank(); rows[0][0] = f"x<y & {EVIL}"; rows[0][1] = f"<img src=x onerror=alert(2)>"
    pkg.questions(rows)
    m = pkg.load()
    import json
    pq = json.dumps(m.pub_q(1), ensure_ascii=False)                              # أسئلة ورقة الطالب بتوصله من /start (البنك مش بالصفحة)
    for page in (m.PAGE, m.PREVIEW, m.key_page(), pq):
        assert EVIL not in page and "<img src=x onerror" not in page
    assert "&lt;script&gt;" in pq and "x&lt;y" in pq and "&amp;" in pq


def test_title_and_names_cannot_break_out_of_script(pkg):
    pkg.settings(**{"عنوان_الامتحان": "</script><b id=pwn>"})
    pkg.students([["العاشر", "أ", "</script><i id=pwn2>"]] + roster())
    m = pkg.load()
    base = open(pkg.p("template.html"), encoding="utf-8").read().count("</script>")
    # الاسم والعنوان بيدخلوا كنص JS: لازم </script> يتحوّل لـ <\/script> فما يزيد عدد وسوم الإغلاق، والعنوان بوسم <title> يتهرّب
    assert m.PAGE.count("</script>") == base and m.PREVIEW.count("</script>") == base
    assert "<title></script>" not in m.PAGE and "&lt;/script&gt;" in m.PAGE


def test_correct_answers_not_in_student_page(srv):
    """الصفحة اللي بتنبعت للطالب ما لازم تحتوي علامة الإجابة الصحيحة ولا الحل"""
    assert '"a":' not in srv.PAGE and '"sol"' not in srv.PAGE
    assert '"a":' in srv.PREVIEW                                   # المعاينة للمعلم فقط: فيها الإجابات (محمية بكلمة سر)


def test_paper_reply_has_no_answers(srv):
    k = start_paper(srv)
    r = srv.paper_reply(k)
    assert set(r) == {"status", "ids", "orders", "qs", "remain", "msg", "ans", "paused"} and r["paused"] is False     # paused: إيقاف المعلم المؤقت (بوليان فقط)
    assert [q["n"] for q in r["qs"]] == r["ids"] and all(set(q) == {"n", "marks", "q", "o"} for q in r["qs"])     # بدون الإجابة والحل والمستوى والمرجع


# ---------- التقارير ----------
def _fill_submissions(m, n_students=5):
    names = [(g, s, n) for g, secs in m.ROSTER.items() for s, ns in secs.items() for n in ns]
    for i, (g, s, n) in enumerate(names[:n_students]):
        k = f"{m.SET['title']}|{g}|{s}|{n}"
        start_paper(m, k, f"d{i}")
        m.ANS[k] = _answers_for(m, m.PAPERS[k]["ids"], i + 3)
        m.submit_for(k)
    m.write_results_csv()


def test_reports_smoke_and_numbers(srv):
    _fill_submissions(srv)
    rows = srv.student_rows()
    assert Counter(r["status"] for r in rows) == {"done": 5}
    sec = {(s["section"]): s for s in srv.section_stats()}
    assert sec["أ"]["submitted"] == 3 and sec["ب"]["submitted"] == 2
    # علامات الطلاب 3..7 من 8: متوسط شعبة أ = (3+4+5)/3/8
    assert sec["أ"]["avg"] == round(((3 + 4 + 5) / 3) / 8 * 100, 1)
    qs = srv.question_stats()
    assert sum(x["appeared"] for x in qs) == 5 * 8
    assert "<html" in srv.report_page().lower() or "<table" in srv.report_page().lower()
    wb = openpyxl.load_workbook(io.BytesIO(srv.build_xlsx()))
    assert len(wb.sheetnames) >= 2
    assert os.path.exists(srv.OUT) and open(srv.OUT, encoding="utf-8-sig").read().count("\n") >= 6


def test_reports_with_zero_submissions(srv):
    assert all(r["status"] == "none" for r in srv.student_rows())
    assert all(s["avg"] is None for s in srv.section_stats())
    srv.report_page(); srv.build_xlsx(); srv.write_results_csv()


def test_archive_moves_files_and_resets(srv):
    _fill_submissions(srv, 2)
    d = srv.archive_all()
    assert os.path.isfile(os.path.join(d, "submissions.jsonl"))
    assert not srv.SUBS and not srv.CLAIMS and not srv.PAPERS and not os.path.exists(srv.SUBS_FILE)
    assert all(r["status"] == "none" for r in srv.student_rows())


def test_roster_codes_column_and_many_students(pkg):
    pkg.students([["العاشر", "أ", f"ط{i}", ""] for i in range(200)])
    m = pkg.load()
    assert sum(len(n) for g in m.ROSTER.values() for n in g.values()) == 200
