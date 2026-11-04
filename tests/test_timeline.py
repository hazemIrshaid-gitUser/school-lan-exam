"""السجل الزمني للطلاب (timeline.csv): لما طالب يشتكي «علقت الصفحة» أو «الأجوبة انحلّت لحالها» نشوف وقت كل حدث وكم سؤال كان مجاوب.
الأهم: السجل بينتقل لمجلد الأرشيف مع الامتحان (ما بيتصفّر ولا بيتحذف) وبعدها بيبدأ سجل جديد للامتحان الجديد."""
import csv, os, time

from conftest import DEFAULT_SETTINGS  # noqa: F401
from test_http import Server, web  # noqa: F401  (fixture)


def rows_of(path):
    with open(path, encoding="utf-8-sig", newline="") as f: return list(csv.reader(f))


def test_timeline_records_start_answers_leave_and_submit(web, pkg):
    k, _, p = web.start_student(n="طالب أ1")
    ans = {str(p["ids"][0]): 2}
    web.post("/ping", {"key": k, "dev": "dev1", "ans": ans, "answered": 1, "total": 8, "remain": 1700, "leaveN": 0, "leaveSec": 0})
    web.post("/ping", {"key": k, "dev": "dev1", "ans": ans, "answered": 1, "total": 8, "remain": 1690, "leaveN": 0, "leaveSec": 0})        # ما تغيّر شي: ما بينسجّل
    web.post("/ping", {"key": k, "dev": "dev1", "ans": ans, "answered": 7, "total": 8, "remain": 1680, "leaveN": 1, "leaveSec": 5})       # قفزة 6 أسئلة + خروج من الصفحة
    web.post("/resume", {"key": k, "dev": "dev1"})
    web.submit(k, "dev1", p["ids"], web.correct_answers(p["ids"]))
    rows = rows_of(pkg.path / "timeline.csv")
    assert rows[0] == ["الوقت", "الشعبة", "الطالب", "الحدث", "المجاب", "من", "ملاحظة", "الجهاز"]
    ev = [(r[3], r[4], r[5]) for r in rows[1:]]
    assert ev == [("بدأ", "0", "8"), ("أول نبضة", "1", "8"), ("أجاب", "7", "8"), ("خرج من الصفحة", "7", "8"), ("إعادة تحميل الصفحة", "1", "8"), ("سلّم", "8", "8")], ev
    assert all(r[1] == "أ" and r[2] == "طالب أ1" and r[7] == "dev1" for r in rows[1:])
    jump = next(r for r in rows if r[3] == "أجاب")
    assert "قفزة" in jump[6] and "+6" in jump[6]
    assert "يدوي" in rows[-1][6] and "علامة" in rows[-1][6] and "مدة" in rows[-1][6]


def test_timeline_moves_into_the_archive_and_is_not_wiped(web, pkg):
    k, _, p = web.start_student(n="طالب أ1")
    web.post("/ping", {"key": k, "dev": "dev1", "ans": {str(p["ids"][0]): 1}, "answered": 1, "total": 8, "remain": 1700, "leaveN": 0, "leaveSec": 0})
    web.submit(k, "dev1", p["ids"], web.correct_answers(p["ids"]))
    before = (pkg.path / "timeline.csv").read_bytes()
    web.teacher(newexam=True)
    arch = [d for d in os.listdir(pkg.path) if d.startswith("archive_")]
    assert arch and (pkg.path / arch[0] / "timeline.csv").read_bytes() == before        # نفس المحتوى بالضبط بالأرشيف
    assert not (pkg.path / "timeline.csv").exists()                                      # والامتحان الجديد بيبدأ بسجل فاضي
    k2, st, p2 = web.start_student("devZ", n="طالب أ2")
    assert st == 200
    rows = rows_of(pkg.path / "timeline.csv")
    assert [r[3] for r in rows[1:]] == ["بدأ"] and rows[1][2] == "طالب أ2"               # سجل جديد: بدون أي شي من الامتحان القديم
    assert len(rows_of(pkg.path / arch[0] / "timeline.csv")) == len(before.decode("utf-8-sig").splitlines())      # والقديم ما انلمس


def test_gap_between_pings_is_logged(pkg):
    srv = pkg.load(); from exam_core import storage
    k = "اختبار الوحدة|العاشر|أ|طالب أ1"
    prev = {"t": time.time() - 60, "answered": 3, "total": 8, "remain": 1000, "leaveN": 0, "leaveSec": 0}
    now = {"t": time.time(), "answered": 3, "total": 8, "remain": 940, "leaveN": 0, "leaveSec": 0}
    storage.log_ping(srv.ctx, k, "devXYZ9", prev, now)
    rows = rows_of(srv.ctx.TIMELINE_FILE)
    assert [r[3] for r in rows[1:]] == ["انقطاع النبضات"] and "60" in rows[1][6] and rows[1][7] == "XYZ9"


def test_rehearsal_names_stay_out_of_the_real_log(pkg):
    srv = pkg.load(); from exam_core import storage
    k = "اختبار الوحدة|العاشر|أ|طالب أ1"
    srv.ctx.REH["keys"].add(k)
    storage.log_event(srv.ctx, k, "بدأ")
    assert not os.path.exists(srv.ctx.TIMELINE_FILE)
