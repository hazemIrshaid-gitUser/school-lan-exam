"""مجلد الأرشيف (archive_...) اللي بتعمله كبسة «بداية امتحان جديد» صار قابل للفتح عند الأستاذ لحاله: بنحط فيه نفس server.py وtemplate.html
وstart.bat مع ملف الأسئلة والصور وsettings.txt، وقائمة الطلاب للشعب اللي امتحنت بس. بدون أي كود جديد للعرض: نفس السيرفر.
ولو ملف الأسئلة اللي على القرص مش بنك الامتحان (المشرف بدّله قبل الكبسة) ما بنحطه، عشان ما ينفتح الأرشيف بأسئلة غلط."""
import os, time, urllib.parse

import openpyxl
import pytest
from conftest import bank, q
from test_http import Server, TEACHER

BAT = "@echo off" + chr(13) + chr(10) + "python server.py" + chr(13) + chr(10)
IMG_Q = "سؤال فيه صورة [img:p1.png] وبعدها كلام"


def archives(pkg): return sorted(d for d in os.listdir(pkg.path) if d.startswith("archive_"))


def cookie(w): return w.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0]


def table(path):
    ws = openpyxl.load_workbook(path).active
    return [[c.value for c in r] for r in ws.iter_rows()]


@pytest.fixture
def servers():
    made = []
    def start(pk):
        s = Server(pk).start(); made.append(s); return s
    yield start
    for s in made: s.stop()


def exam(pkg, servers, students=("طالب أ1", "طالب أ2")):
    """امتحان فيه صورة بسؤال: students بيسلّموا كلهم صح. بيرجّع (السيرفر، {اسم: مفتاح})"""
    rows = bank(); rows[0][0] = IMG_Q
    pkg.image("p1.png"); pkg.questions(rows); pkg.p("start.bat").write_bytes(BAT.encode("ascii"))
    w = servers(pkg); keys = {}
    for i, n in enumerate(students):
        k, _, p = w.start_student(f"d{i}", n=n); keys[n] = k
        assert w.submit(k, f"d{i}", p["ids"], w.correct_answers(p["ids"]))[0] == 200
    return w, keys


class Folder:
    """يخلّي Server(...) يشتغل على أي مجلد (الأرشيف)"""
    def __init__(self, path): self.path = path
    def p(self, name): return self.path / name


def test_archive_carries_everything_needed_to_open_it(pkg, servers):
    w, keys = exam(pkg, servers)
    originals = {n: pkg.p(n).read_bytes() for n in ("server.py", "template.html", "start.bat", "settings.txt", "questions.xlsx", "students.xlsx")}
    w.teacher(newexam=True)
    (a,) = archives(pkg); d = pkg.path / a
    for n in ("server.py", "template.html", "start.bat", "settings.txt", "questions.xlsx"):
        assert (d / n).read_bytes() == originals[n], n                                         # نسخ طبق الأصل، بدون أي تعديل
    assert (d / "images" / "p1.png").read_bytes() == pkg.p("images/p1.png").read_bytes()
    for n in ("submissions.jsonl", "papers.json", "claims.json", "results.csv"): assert (d / n).exists(), n    # اللي كان يتحفظ قبل هيك
    t = table(d / "students.xlsx")
    assert t[0] == ["الصف", "الشعبة", "الاسم"] and sorted(r[2] for r in t[1:]) == ["طالب أ1", "طالب أ2", "طالب أ3"]      # شعبة أ بس (ب ما امتحنت)
    note = (d / "اقرأني.txt").read_text(encoding="utf-8-sig")
    assert "start.bat" in note and "/monitor" in note and "اختبار الوحدة" in note
    for n, b in originals.items(): assert pkg.p(n).read_bytes() == b, n                       # ملفات المشرف الأصلية ما انلمست
    assert len(table(pkg.p("students.xlsx"))) == 6
    assert w.start_student("devZ")[2]["status"] == "ok"                                        # والامتحان الجديد بيشتغل عادي


def test_archive_really_opens_and_shows_the_old_exam(pkg, servers):
    w, keys = exam(pkg, servers)
    w.teacher(newexam=True)
    d = pkg.path / archives(pkg)[0]
    old = servers(Folder(d)); ck = cookie(old)
    sections = old.get("/monitor.json")[1]["sections"]
    assert list(sections) == ["العاشر — شعبة أ"]                                             # شعبة ب مش موجودة
    rows = {r["name"]: r for r in sections["العاشر — شعبة أ"]}
    assert rows["طالب أ1"]["status"] == rows["طالب أ2"]["status"] == "done" and rows["طالب أ1"]["score"] == 8
    assert rows["طالب أ3"]["status"] == "none"
    for path in ("/key", "/report", "/report.xlsx", "/sheet", "/sheet?key=" + urllib.parse.quote(keys["طالب أ1"])):
        st, _, body, _ = old.get(path, {"Cookie": ck}); assert st == 200 and body, path
    assert "طالب أ1" in old.get("/sheet?key=" + urllib.parse.quote(keys["طالب أ1"]), {"Cookie": ck})[2].decode("utf-8")
    assert old.get("/img/p1.png")[0] == 200                                                  # صور الأسئلة موجودة


def test_bank_without_levels_is_recognised(pkg, servers):
    pkg.questions([q(f"سؤال {i}", ("1", "2", "3", "4"), "أ") for i in range(6)])
    pkg.settings(**{"عدد_الأسئلة_الصعبة": "", "عدد_الأسئلة_المتوسطة": "", "عدد_الأسئلة_السهلة": "", "عدد_الأسئلة_الكلي": "4"})
    pkg.p("start.bat").write_bytes(BAT.encode("ascii"))
    w = servers(pkg); k, _, p = w.start_student("d0"); w.submit(k, "d0", p["ids"], [0] * len(p["ids"]))
    w.teacher(newexam=True)
    assert (pkg.path / archives(pkg)[0] / "server.py").exists()                                # البنك بدون مستويات ما انحسب مختلف


def test_questions_replaced_before_the_button_are_not_archived(pkg, servers):
    w, keys = exam(pkg, servers)
    new = bank(); new[0][0] = "سؤال من امتحان ثاني تماماً"
    pkg.questions(new)                                                                       # المشرف بدّل الملف وما أعاد التشغيل
    w.teacher(newexam=True)
    d = pkg.path / archives(pkg)[0]
    assert (d / "submissions.jsonl").exists()                                                # الأرشفة نفسها اشتغلت
    for n in ("server.py", "template.html", "start.bat", "questions.xlsx", "students.xlsx", "settings.txt", "images"): assert not (d / n).exists(), n
    assert "ما انحفظ" in (d / "اقرأني.txt").read_text(encoding="utf-8-sig")
    assert w.get("/monitor.json")[0] == 200 and w.start_student("devZ")[2]["status"] == "ok"
    assert len(table(pkg.p("questions.xlsx"))) == len(new) + 1                              # ملف المشرف الجديد ما انلمس


def test_questions_replaced_and_server_restarted(pkg, servers):
    w, keys = exam(pkg, servers)
    w.stop()
    new = bank(); new[0][0] = "أسئلة الامتحان الجديد"
    pkg.questions(new)
    w2 = servers(pkg)
    assert w2.get("/monitor.json")[1]["bank_changed"]                                       # التنبيه الأحمر المعروف
    w2.teacher(newexam=True)
    d = pkg.path / archives(pkg)[0]
    assert (d / "papers.json").exists() and not (d / "server.py").exists() and not (d / "questions.xlsx").exists()
    assert "ما انحفظ" in (d / "اقرأني.txt").read_text(encoding="utf-8-sig")


def test_empty_exam_gets_no_viewer_files(pkg, servers):
    pkg.p("start.bat").write_bytes(BAT.encode("ascii"))
    w = servers(pkg)
    w.teacher(newexam=True)
    d = pkg.path / archives(pkg)[0]
    assert not any((d / n).exists() for n in ("server.py", "questions.xlsx", "students.xlsx", "اقرأني.txt"))


def test_login_codes_are_kept_for_kept_students(pkg):
    pkg.write_xlsx("students.xlsx", ["الصف", "الشعبة", "الاسم", "الرمز"], [["العاشر", "أ", "طالب أ1", "123456"], ["العاشر", "أ", "طالب أ2", ""], ["العاشر", "ب", "طالب ب1", "654321"]])
    m = pkg.load(); k = f"{m.SET['title']}|العاشر|أ|طالب أ1"
    out = pkg.path / "out"; out.mkdir()
    assert m.export_viewer(str(out), {k}) is True
    t = table(out / "students.xlsx")
    assert t[0] == ["الصف", "الشعبة", "الاسم", "الرمز"] and len(t) == 3
    got = {r[2]: r[3] for r in t[1:]}; assert got["طالب أ1"] == "123456" and got["طالب أ2"] in ("", None) and len(got) == 2


def test_a_failure_in_the_extra_copy_never_breaks_archiving(pkg, monkeypatch):
    m = pkg.load(); k = f"{m.SET['title']}|العاشر|أ|طالب أ1"
    pkg.p("start.bat").write_bytes(BAT.encode("ascii"))
    m.PAPERS[k] = m.make_paper(); m.CLAIMS[k] = "d1"; m.save_papers()
    monkeypatch.setattr(m, "xlsx_bytes", lambda *a: 1 / 0)                                    # النسخ بيفشل بنص الطريق
    d = m.archive_all()
    assert os.path.isfile(os.path.join(d, "papers.json")) and not m.PAPERS                     # الأرشفة نفسها تمت
    assert not os.path.exists(os.path.join(d, "server.py")) and not os.path.exists(os.path.join(d, "images"))     # وما بقي نسخ ناقص
    assert "تعذّر" in open(os.path.join(d, "اقرأني.txt"), encoding="utf-8-sig").read()
    m.PAPERS[k] = m.make_paper(); m.CLAIMS[k] = "d1"; m.save_papers()
    monkeypatch.setattr(m, "export_viewer", lambda *a: 1 / 0)
    d2 = m.archive_all()
    assert os.path.isfile(os.path.join(d2, "papers.json"))                                    # حتى لو الدالة كلها انهارت
