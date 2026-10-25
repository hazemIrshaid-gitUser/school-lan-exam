"""السحب الموزّن بالعدّاد: كل سؤال بنعدّ كم ورقة طلع فيها، وورقة الطالب الجديد بتاخذ الأقل ظهوراً أول (والتعادل عشوائي).
النتيجة: الأسئلة بتتوزع على كل البنك، وما بيتكرر سؤال بكثرة بينما غيره ما طلع لحدا. العدّاد بيتحسب من PAPERS نفسها (فبيضل صح بعد إعادة التشغيل)."""
import collections

from conftest import bank, q


def draw(m, n):
    """n طلاب يبدأوا ورقة وحدة ورا وحدة (مثل /start): الورقة بتنحفظ بـ PAPERS قبل ما ياخذ اللي بعده"""
    for i in range(n): m.PAPERS[f"k{i}"] = m.make_paper()


def usage(m):
    return collections.Counter(n for p in m.PAPERS.values() for n in p["ids"])


def test_every_question_is_used_and_levels_stay_even(pkg):
    pkg.questions(bank(6, 10, 14)); pkg.settings(**{"عدد_الأسئلة_الصعبة": 2, "عدد_الأسئلة_المتوسطة": 3, "عدد_الأسئلة_السهلة": 4, "عدد_الأسئلة_الكلي": 9})
    m = pkg.load(); draw(m, 40); u = usage(m)
    for lv in ("hard", "medium", "easy"):
        c = [u.get(x["n"], 0) for x in m.QLIST if x["level"] == lv]
        assert min(c) > 0 and max(c) - min(c) <= 1, (lv, c)                  # كل سؤال طلع، والفرق بين الأكثر والأقل ظهوراً ورقة وحدة بالأكثر


def test_papers_still_have_exact_counts_and_no_duplicates(pkg):
    m = pkg.load(); draw(m, 25)
    for p in m.PAPERS.values():
        assert len(p["ids"]) == len(set(p["ids"])) == sum(m.PICK.values())
        assert collections.Counter(m.BANK[n]["level"] for n in p["ids"]) == {k: v for k, v in m.PICK.items() if v}


def test_papers_are_not_all_the_same(pkg):
    pkg.questions(bank(6, 10, 14)); m = pkg.load(); draw(m, 12)
    assert len({tuple(sorted(p["ids"])) for p in m.PAPERS.values()}) > 6      # التعادل عشوائي: مو ورقة وحدة لكل الطلاب


def test_ties_are_broken_randomly(pkg):
    pkg.questions(bank(6, 10, 14)); m = pkg.load()
    firsts = {tuple(sorted(m.make_paper()["ids"])) for _ in range(30)}       # من غير حفظ الأوراق: العدّاد صفر دائماً، فالسحب عشوائي
    assert len(firsts) > 5


def test_counter_survives_server_restart(pkg):
    pkg.questions(bank(6, 10, 14)); m = pkg.load(); draw(m, 10); m.save_papers()
    m2 = pkg.load(); assert len(m2.PAPERS) == 10
    for i in range(10, 30): m2.PAPERS[f"k{i}"] = m2.make_paper()
    u = usage(m2)
    for lv in ("hard", "medium", "easy"):
        c = [u.get(x["n"], 0) for x in m2.QLIST if x["level"] == lv]
        assert max(c) - min(c) <= 1, (lv, c)


def test_fixed_questions_are_always_in_and_do_not_break_the_balance(pkg):
    rows = bank(6, 10, 14); rows[0][10] = "نعم"                                  # أول سؤال صعب = ثابت
    pkg.questions(rows); m = pkg.load(); draw(m, 30)
    fixed = next(x["n"] for x in m.QLIST if x["fixed"])
    assert all(fixed in p["ids"] for p in m.PAPERS.values())
    c = [usage(m).get(x["n"], 0) for x in m.QLIST if x["level"] == "hard" and not x["fixed"]]
    assert max(c) - min(c) <= 1, c


def test_old_paper_records_without_ids_do_not_crash(pkg):
    m = pkg.load(); m.PAPERS["قديم"] = {"start": 0}
    assert len(m.make_paper()["ids"]) == sum(m.PICK.values())
