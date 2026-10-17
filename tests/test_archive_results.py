"""كبسة «بداية امتحان جديد» بتحط بمجلد الأرشيف (archive_...) مجلد «نتائج» جاهز للأستاذ: صفحات HTML تنفتح بأي متصفح بدون Python ولا سيرفر، وفيه صوره كمان
فبيتنقل كمجلد واحد. بدون نسخة سيرفر: ما بينحط server.py ولا start.bat ولا settings.txt ولا الأسئلة ولا قائمة الطلاب. مبني بنفس دوال السيرفر من ذاكرته،
وبشعب الامتحان بس. ولو ما زبط (السيرفر انشغّل من جديد على أسئلة ثانية) بنكتب ملاحظة قصيرة بدل صفحات بأسئلة غلط."""
import os, re, shutil, urllib.parse

import openpyxl
import pytest
from conftest import bank
from test_http import Server
from test_browser import browser, PNG_1PX  # noqa: F401  (fixture)

BAT = "@echo off" + chr(13) + chr(10) + "python server.py" + chr(13) + chr(10)
IMG_Q = "سؤال فيه صورة [img:p1.png] وبعدها كلام"
DATA = {"claims.json", "papers.json", "state.json", "answers.json", "submissions.jsonl", "results.csv"}      # اللي كان يتحفظ بالأرشيف قبل
NOT_FOR_TEACHER = ("server.py", "template.html", "start.bat", "settings.txt", "questions.xlsx", "students.xlsx", "images")


def archives(pkg): return sorted(d for d in os.listdir(pkg.path) if d.startswith("archive_"))


@pytest.fixture
def servers():
    made = []
    def start(pk):
        s = Server(pk).start(); made.append(s); return s
    yield start
    for s in made: s.stop()


def exam(pkg, servers, students=("طالب أ1", "طالب أ2")):
    """امتحان فيه صورة بسؤال ثابت (بكل ورقة): students بيسلّموا كلهم صح. بيرجّع (السيرفر، {اسم: مفتاح})"""
    rows = bank(); rows[0][0] = IMG_Q; rows[0][10] = "نعم"
    pkg.image("p1.png"); pkg.questions(rows); pkg.p("start.bat").write_bytes(BAT.encode("ascii"))
    w = servers(pkg); keys = {}
    for i, n in enumerate(students):
        k, _, p = w.start_student(f"d{i}", n=n); keys[n] = k
        assert w.submit(k, f"d{i}", p["ids"], w.correct_answers(p["ids"]))[0] == 200
    pkg.image("p1.png", PNG_1PX)                                                                               # صورة حقيقية (فوق كتبنا ملف تجريبي)
    return w, keys


def static_files(d):
    root = d / "نتائج"
    return root, sorted(p.name for p in root.iterdir()), sorted(p.name for p in (root / "ورقات").iterdir())


def read(p): return p.read_text(encoding="utf-8")


def test_archive_has_only_the_data_files_and_the_results_folder(pkg, servers):
    w, keys = exam(pkg, servers)
    originals = {n: pkg.p(n).read_bytes() for n in ("server.py", "template.html", "start.bat", "settings.txt", "questions.xlsx", "students.xlsx")}
    w.teacher(newexam=True)
    (a,) = archives(pkg); d = pkg.path / a
    names = set(os.listdir(d))
    assert "نتائج" in names and names <= DATA | {"نتائج"}, sorted(names - DATA)                                # لا سيرفر ولا إعدادات ولا أسئلة ولا طلاب ولا ملاحظة
    for n in NOT_FOR_TEACHER + ("اقرأني.txt",): assert n not in names, n
    assert {"submissions.jsonl", "papers.json", "results.csv"} <= names                                        # بيانات الامتحان زي قبل
    for n, b in originals.items(): assert pkg.p(n).read_bytes() == b, n                                     # ملفات المشرف الأصلية ما انلمست
    assert w.start_student("devZ")[2]["status"] == "ok"                                                      # والامتحان الجديد بيشتغل عادي


def test_results_folder_has_everything(pkg, servers):
    w, keys = exam(pkg, servers)
    w.teacher(newexam=True)
    d = pkg.path / archives(pkg)[0]; root, top, sheets = static_files(d)
    assert top == sorted(["ابدأ_من_هنا.html", "التقرير.html", "report.xlsx", "الأسئلة_والإجابات.html", "ورقات", "images"])
    assert len(sheets) == 3 and sum(s.startswith("001_") or s.startswith("002_") for s in sheets) == 2          # ورقتان (أ1 وأ2) + ورقات الشعبة كلها
    assert any(s.startswith("الشعبة_") and s.endswith("_كل_الورقات.html") for s in sheets)
    home = read(root / "ابدأ_من_هنا.html")
    for n in ("طالب أ1", "طالب أ2", "طالب أ3"): assert n in home
    assert "ب1" not in home and "شعبة ب" not in home and "لم يبدأ" in home                                      # الشعبة اللي ما امتحنت مش موجودة
    assert "8 / 8" in home and re.search(r"[0-9]+ ث", home)                                                     # العلامة ومدة الحل
    assert "الرئيسية" in read(root / "التقرير.html") and "href='report.xlsx'" in read(root / "التقرير.html")
    assert openpyxl.load_workbook(root / "report.xlsx").sheetnames == ["ملخص", "الشعبة أ", "تحليل الأسئلة"]       # بدون شعبة ب
    assert (root / "images" / "p1.png").read_bytes() == PNG_1PX


def test_results_folder_is_self_contained(pkg, servers):
    w, keys = exam(pkg, servers)
    w.teacher(newexam=True)
    d = pkg.path / archives(pkg)[0]; root, top, sheets = static_files(d)
    pages = [root / n for n in top if n.endswith(".html")] + [root / "ورقات" / n for n in sheets]
    for pg in pages:
        h = read(pg)
        assert not re.search(r"""(href|src|action)=['"]?/""", h), pg.name                                      # لا روابط مطلقة للسيرفر
        for link in re.findall(r"""href='([^']+)'""", h):
            if link.startswith("http"): continue
            assert (pg.parent / urllib.parse.unquote(link)).exists(), (pg.name, link)                           # كل رابط محلي بيفتح ملف موجود
        for src in re.findall(r'src="([^"]+)"', h):
            assert (pg.parent / urllib.parse.unquote(src)).exists(), (pg.name, src)                             # وكل صورة موجودة (جوّا مجلد نتائج نفسه)
    sheet = next(read(root / "ورقات" / n) for n in sheets if n.startswith("001_"))
    assert 'src="../images/p1.png"' in sheet and "طالب أ1" in sheet and "عرض الخاطئة فقط" in sheet
    assert 'src="images/p1.png"' in read(root / "الأسئلة_والإجابات.html")
    assert "logout" not in read(root / "الأسئلة_والإجابات.html") and "/monitor" not in read(root / "الأسئلة_والإجابات.html")


def test_results_folder_opens_in_a_real_browser_after_being_moved_alone(pkg, servers, browser, tmp_path_factory):
    """الأستاذ بياخد مجلد «نتائج» بس (مش الأرشيف): ننسخه لمكان ثاني ونفتحه من هناك"""
    w, keys = exam(pkg, servers)
    w.teacher(newexam=True)
    moved = tmp_path_factory.mktemp("teacher") / "نتائج"
    shutil.copytree(pkg.path / archives(pkg)[0] / "نتائج", moved)
    ctx = browser.new_context(viewport={"width": 1100, "height": 800}, locale="ar-JO"); page = ctx.new_page(); page.set_default_timeout(8000)
    errors = []; page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto((moved / "ابدأ_من_هنا.html").as_uri())
        assert "طالب أ1" in page.inner_text("body")
        page.locator("tr", has_text="طالب أ1").get_by_text("فتح الورقة").click()
        page.wait_for_selector(".q")
        assert page.locator(".q").count() == 8 and "طالب أ1" in page.inner_text(".hd")
        assert page.locator("img").count() >= 1 and page.evaluate("[...document.images].every(i=>i.complete&&i.naturalWidth>0)")      # الصورة انحملت من images جنبه
        page.get_by_text("عرض الخاطئة فقط").click()
        assert page.locator(".q.good:visible").count() == 0 and page.locator(".q.bad:visible").count() == 0                      # كله صح: ما في خاطئ ولا صح ظاهر
        page.get_by_text("الرئيسية").first.click(); page.wait_for_selector("h2")
        assert "نتائج الامتحان" in page.inner_text("h2")
        page.get_by_text("الأسئلة مع الإجابات").click(); page.wait_for_selector(".q")
        assert page.locator("img").count() >= 1 and page.evaluate("[...document.images].every(i=>i.complete&&i.naturalWidth>0)")
        assert not errors
    finally:
        ctx.close()


def test_results_survive_a_hot_edited_questions_file(pkg, servers):
    """المشرف بدّل ملف الأسئلة بدون إعادة تشغيل: النتائج (من ذاكرة السيرفر) بتضل بأسئلة الامتحان الصحيحة"""
    w, keys = exam(pkg, servers)
    new = bank(); new[0][0] = "سؤال من امتحان ثاني تماماً"; pkg.questions(new)
    w.teacher(newexam=True)
    d = pkg.path / archives(pkg)[0]; root, top, sheets = static_files(d)
    allsheets = "".join(read(root / "ورقات" / n) for n in sheets)
    assert "سؤال رقم" in allsheets and "من امتحان ثاني" not in allsheets and "من امتحان ثاني" not in read(root / "الأسئلة_والإجابات.html")
    assert not (d / "اقرأني.txt").exists() and not (d / "questions.xlsx").exists()


def test_no_results_after_restart_with_new_questions(pkg, servers):
    w, keys = exam(pkg, servers); w.stop()
    new = bank(); new[0][0] = "أسئلة الامتحان الجديد"; pkg.questions(new)
    w2 = servers(pkg); w2.teacher(newexam=True)
    d = pkg.path / archives(pkg)[0]
    assert not (d / "نتائج").exists() and (d / "papers.json").exists()                                         # الذاكرة صارت أسئلة ثانية: أحسن بدون
    note = (d / "اقرأني.txt").read_text(encoding="utf-8-sig"); assert "ما انعمل مجلد «نتائج»" in note and "انبدّل" in note
    assert set(os.listdir(d)) <= DATA | {"اقرأني.txt"}


def test_empty_exam_gets_nothing_extra(pkg, servers):
    w = servers(pkg)
    w.teacher(newexam=True)
    d = pkg.path / archives(pkg)[0]
    assert not (d / "نتائج").exists() and not (d / "اقرأني.txt").exists()


def test_a_failure_is_cleaned_up_and_never_breaks_archiving(pkg, monkeypatch):
    m = pkg.load(); k = f"{m.SET['title']}|العاشر|أ|طالب أ1"
    m.PAPERS[k] = m.make_paper(); m.CLAIMS[k] = "d1"; m.save_papers()
    ros = {g: {s: list(ns) for s, ns in ss.items()} for g, ss in m.ROSTER.items()}
    monkeypatch.setattr(m, "report_page", lambda: 1 / 0)
    d = m.archive_all()
    assert os.path.isfile(os.path.join(d, "papers.json")) and not m.PAPERS                                    # الأرشفة نفسها تمت
    assert not os.path.exists(os.path.join(d, "نتائج"))                                                          # وما بقي مجلد ناقص
    assert "تعذّر تجهيز النتائج" in open(os.path.join(d, "اقرأني.txt"), encoding="utf-8-sig").read()
    assert m.ROSTER == ros                                                                                      # قائمة الطلاب رجعت كاملة حتى بعد الفشل
    m.PAPERS[k] = m.make_paper(); m.CLAIMS[k] = "d1"; m.save_papers()
    monkeypatch.setattr(m, "export_results", lambda *a: 1 / 0)
    d2 = m.archive_all()
    assert os.path.isfile(os.path.join(d2, "papers.json"))                                                    # حتى لو الدالة كلها انهارت


def test_odd_student_names_make_valid_unique_file_names(pkg):
    names = ['أحمد/محمد: "س"', "أحمد?محمد* <س>", "أحمد" + chr(92) + "محمد", "ط" * 80]
    pkg.write_xlsx("students.xlsx", ["الصف", "الشعبة", "الاسم"], [["العاشر", "أ", n] for n in names])
    m = pkg.load()
    for i, n in enumerate(names):
        k = f"{m.SET['title']}|العاشر|أ|{n}"; m.PAPERS[k] = m.make_paper(); m.CLAIMS[k] = f"d{i}"
        m.SUBS[k] = {"key": k, "exam": m.SET["title"], "grade": "العاشر", "section": "أ", "name": n, "ids": m.PAPERS[k]["ids"], "answers": [0] * len(m.PAPERS[k]["ids"]),
                     "score": 0, "total": 8, "auto": "", "time": "", "leave": "", "late": 0, "dur": 65}
    out = pkg.path / "out"; out.mkdir()
    m.export_static(str(out), {("العاشر", "أ")})
    files = [p.name for p in (out / "نتائج" / "ورقات").iterdir() if p.name[:3].isdigit()]
    assert len(files) == 4 and len(set(files)) == 4 and not any(c in f for f in files for c in "/:*?<>|" + chr(92))
    assert "1 د 05 ث" in (out / "نتائج" / "ابدأ_من_هنا.html").read_text(encoding="utf-8")
