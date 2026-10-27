"""قواعد السحب: أسطر «سحب = شرط | شرط | العدد:رقم» بـ settings.txt بتحدد كم سؤال ينسحب من أي أسئلة (حسب أي عمود بملف الأسئلة، مثل الوحدة والمستوى).
بدون سطور «سحب» السلوك القديم (أعداد المستويات) ما بتغير."""
import collections

import pytest
from conftest import Q_HEAD, LETTERS, q

HEAD = Q_HEAD + ["الوحدة"]
U1, U2 = "الوحدة الأولى", "الوحدة الثانية"


def rows(spec):
    """spec: قائمة (وحدة، مستوى، عدد) — كل سؤال له نص مميز"""
    out, i = [], 0
    for unit, lvl, n in spec:
        for _ in range(n):
            out.append(q(f"س {unit[-5:]} {lvl} {i}", (f"{i}-أ", f"{i}-ب", f"{i}-ج", f"{i}-د"), LETTERS[i % 4], lvl) + [unit]); i += 1
    return out


BANK = [(U1, "سهل", 6), (U1, "وسط", 4), (U1, "صعب", 3), (U2, "سهل", 5), (U2, "وسط", 6), (U2, "صعب", 4)]
RULES = ("سحب = الوحدة:الوحدة الأولى | المستوى:سهل | العدد:3\n"
         "سحب = الوحدة:الوحدة الثانية | المستوى:سهل | العدد:2\n"
         "سحب = الوحدة:الوحدة الثانية | المستوى:وسط | العدد:3\n"
         "سحب = الوحدة:الوحدة الثانية | المستوى:صعب | العدد:2\n")


def setup(pkg, rules=RULES, spec=BANK, extra="", head=HEAD, rws=None):
    pkg.questions(rows(spec) if rws is None else rws, head=head)
    pkg.raw_settings("عنوان_الامتحان = اختبار\nالمدة_بالدقائق = 30\n" + extra + rules)
    return pkg


def mix(m, ids):
    return collections.Counter((m.BANK[n]["cols"]["الوحدة"], m.BANK[n]["level"]) for n in ids)


def test_four_rules_give_exact_mix_on_every_paper(pkg):
    m = setup(pkg).load()
    assert m.PICK == {"r1": 3, "r2": 2, "r3": 3, "r4": 2} and sum(m.PICK.values()) == 10
    for _ in range(20):
        ids = m.make_paper()["ids"]
        assert len(ids) == len(set(ids)) == 10
        assert mix(m, ids) == {(U1, "easy"): 3, (U2, "easy"): 2, (U2, "medium"): 3, (U2, "hard"): 2}


def test_papers_differ_between_students(pkg):
    m = setup(pkg).load()
    papers = {tuple(sorted(m.make_paper()["ids"])) for _ in range(15)}
    assert len(papers) > 3


def test_not_enough_questions_names_the_rule(pkg):
    setup(pkg, "سحب = الوحدة:الوحدة الأولى | المستوى:صعب | العدد:9\n")
    pkg.expect_error("قواعد السحب", "القاعدة 1", "مطلوب 9 والموجود 3")


def test_unknown_column_lists_existing_columns(pkg):
    setup(pkg, "سحب = الفصل:الأول | العدد:2\n")
    msg = pkg.expect_error("سطر 3", "ما في عمود اسمه «الفصل»", "الوحدة")
    assert "المستوى" in msg


@pytest.mark.parametrize("rule,needle", [
    ("سحب = الوحدة:الوحدة الأولى\n", "بدون «العدد»"),
    ("سحب = العدد:3\n", "بدون أي شرط"),
    ("سحب = الوحدة:الوحدة الأولى | العدد:0\n", "أكبر من صفر"),
    ("سحب = الوحدة:الوحدة الأولى | العدد:ثلاثة\n", "رقم صحيح"),
    ("سحب = الوحدة الوحدة الأولى | العدد:3\n", "صيغة العمود:القيمة"),
])
def test_rule_syntax_errors_point_to_the_line(pkg, rule, needle):
    setup(pkg, rule)
    pkg.expect_error("settings.txt سطر 3", needle)


def test_alternatives_with_slash_and_contains(pkg):
    m = setup(pkg, "سحب = المستوى:وسط/صعب | العدد:5\nسحب = الوحدة~الثانية | العدد:4\n").load()
    ids = m.make_paper()["ids"]
    assert len(ids) == 9
    first = [n for n in ids if m.BANK[n]["grp"] == "r1"]
    assert len(first) == 5 and all(m.BANK[n]["level"] in ("medium", "hard") for n in first)
    assert all(m.BANK[n]["cols"]["الوحدة"] == U2 for n in ids if m.BANK[n]["grp"] == "r2")


def test_level_names_match_any_spelling(pkg):
    m = setup(pkg, "سحب = المستوى:سهلة | العدد:4\nسحب = المستوى:medium | العدد:2\n").load()
    assert mix(m, m.make_paper()["ids"]).total() == 6 and {l for (_, l) in mix(m, m.make_paper()["ids"])} == {"easy", "medium"}


def test_header_with_brackets_is_matched_without_them(pkg):
    m = setup(pkg, "سحب = المرجع:كتاب | العدد:2\n", rws=[q(f"س{i}", ans="أ", level="سهل", page="كتاب" if i < 4 else "غيره") + ["ا"] for i in range(8)],
              head=Q_HEAD[:7] + ["المرجع (اختياري)"] + Q_HEAD[8:] + ["الوحدة"]).load()
    assert m.PICK == {"r1": 2} and all(m.BANK[n]["page"] == "كتاب" for n in m.make_paper()["ids"])


def test_first_matching_rule_owns_the_question(pkg):
    setup(pkg, "سحب = المستوى:سهل | العدد:8\nسحب = الوحدة:الوحدة الأولى | المستوى:سهل | العدد:2\n")
    pkg.expect_error("القاعدة 2", "مطلوب 2 والموجود 0", "بعد استبعاد")


def test_old_counts_are_ignored_when_rules_exist(pkg, capsys):
    m = setup(pkg, extra="عدد_الأسئلة_الصعبة = 3\nعدد_الأسئلة_الكلي = 20\n").load()
    assert sum(m.PICK.values()) == 10 and "تجاهلت" in capsys.readouterr().out


def test_no_rules_keeps_the_old_behaviour(pkg):
    m = setup(pkg, rules="عدد_الأسئلة_الصعبة = 2\nعدد_الأسئلة_المتوسطة = 3\nعدد_الأسئلة_السهلة = 4\n").load()
    assert m.PICK == {"hard": 2, "medium": 3, "easy": 4}
    assert collections.Counter(m.BANK[n]["level"] for n in m.make_paper()["ids"]) == {"hard": 2, "medium": 3, "easy": 4}


def test_fixed_question_always_in_its_rule_group(pkg):
    rws = rows(BANK)
    rws[0][10] = "نعم"                      # أول سؤال: الوحدة الأولى سهل
    m = setup(pkg, rws=rws).load()
    fixed_n = next(q_["n"] for q_ in m.QLIST if q_["fixed"])
    assert all(fixed_n in m.make_paper()["ids"] for _ in range(15))


def test_too_many_fixed_for_a_rule_is_an_error(pkg):
    rws = rows(BANK)
    for r in rws[:4]: r[10] = "نعم"          # 4 ثوابت من الوحدة الأولى/سهل والقاعدة تطلب 3
    setup(pkg, rws=rws)
    pkg.expect_error("ثوابت 4", "قاعدة 1")


def test_final_mark_and_total_range_with_rules(pkg):
    m = setup(pkg, extra="العلامة_النهائية = 30\n").load()
    assert m.total_range(m.PICK) == (30, 30) and m.raw_range(m.PICK) == (10, 10)


def test_key_page_lists_rules_and_out_of_rules_questions(pkg):
    m = setup(pkg).load()
    h = m.key_page()
    assert "قاعدة 1: الوحدة = الوحدة الأولى، المستوى = سهل" in h and "أسئلة خارج قواعد السحب" in h
    assert "بالامتحان: 10" in h


def test_exam_page_total_matches_rules(pkg):
    m = setup(pkg).load()
    assert "pick: {\"hard\": 0, \"medium\": 10, \"easy\": 0}" in m.PAGE


def test_check_files_reports_rules(pkg):
    import subprocess, sys
    setup(pkg)
    r = subprocess.run([sys.executable, "-X", "utf8", str(pkg.p("check_files.py"))], cwd=pkg.path, capture_output=True, text=True, encoding="utf-8",
                       env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}, timeout=60)
    assert "قاعدة 1: الوحدة = الوحدة الأولى" in r.stdout and "بالامتحان      : 10 سؤال" in r.stdout


def test_rules_draw_is_balanced_inside_each_rule(pkg):
    m = setup(pkg).load()
    for i in range(30): m.PAPERS[f"k{i}"] = m.make_paper()
    use = collections.Counter(n for p in m.PAPERS.values() for n in p["ids"])
    for key in m.PICK:
        c = [use.get(x["n"], 0) for x in m.QLIST if x["grp"] == key]
        assert min(c) > 0 and max(c) - min(c) <= 1, (key, c)
