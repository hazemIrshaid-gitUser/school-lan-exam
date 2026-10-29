"""أدوات مشتركة: كل اختبار ياخذ نسخة نظيفة من الحزمة بمجلد مؤقت، ويكتب ملفات الأسئلة/الطلاب/الإعدادات اللي بدو إياها، ويحمّل server.py منها.
(server.py بيقرأ كل شي لحظة الاستيراد من مجلده، فلازم نسخة مستقلة لكل سيناريو.)"""
import importlib.util, itertools, os, pathlib, shutil, sys, time

import openpyxl
import pytest

HERE = pathlib.Path(__file__).resolve().parent
PKG_SRC = pathlib.Path(os.environ["EXAM_PKG"]) if os.environ.get("EXAM_PKG") else next(HERE.parent.glob("1_*"))
CODE_FILES = ("server.py", "template.html", "check_files.py", "exam_core")        # exam_core = مجلد وحدات السيرفر (server.py بيستوردها من جنبه)
_counter = itertools.count()

Q_HEAD = ["السؤال", "أ", "ب", "ج", "د", "الجواب", "المستوى", "المرجع", "الحل", "العلامة", "ثابت"]
S_HEAD = ["الصف", "الشعبة", "الاسم", "الرمز"]
LETTERS = "أبجد"


def q(text, opts=("1", "2", "3", "4"), ans="أ", level="", page="", sol="", marks="", fixed=""):
    o = list(opts) + [""] * (4 - len(opts))
    return [text, *o, ans, level, page, sol, marks, fixed]


def bank(hard=3, medium=4, easy=4, marks=""):
    """بنك أسئلة سليم: كل سؤال إله نص مميز، والإجابات الصحيحة موزعة على أ-د"""
    rows, i = [], 0
    for lvl, n in (("صعب", hard), ("وسط", medium), ("سهل", easy)):
        for _ in range(n):
            rows.append(q(f"سؤال رقم {i + 1}", (f"خ{i}-أ", f"خ{i}-ب", f"خ{i}-ج", f"خ{i}-د"), LETTERS[i % 4], lvl, marks=marks))
            i += 1
    return rows


def roster(a=3, b=2):
    return [["العاشر", "أ", f"طالب أ{i}"] for i in range(1, a + 1)] + [["العاشر", "ب", f"طالب ب{i}"] for i in range(1, b + 1)]


DEFAULT_SETTINGS = {
    "عنوان_الامتحان": "اختبار الوحدة", "المدة_بالدقائق": "30",
    "عدد_الأسئلة_الصعبة": "2", "عدد_الأسئلة_المتوسطة": "3", "عدد_الأسئلة_السهلة": "3", "عدد_الأسئلة_الكلي": "8",
    "خلط_الأسئلة": "نعم", "خلط_الخيارات": "نعم", "كلمة_سر_المعلم": "secret",
}


def copy_any(src, dst):
    """ينسخ ملفاً أو مجلداً (exam_core) بدون __pycache__"""
    if os.path.isdir(src): shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    else: shutil.copy(src, dst)


class LoadFailed(Exception):
    """server.py رفض الملفات (sys.exit) — النص هو اللي انكتب بـ exam_error.txt"""


class Pkg:
    def __init__(self, path):
        self.path = path

    def p(self, name):
        return self.path / name

    def write_xlsx(self, name, head, rows):
        wb = openpyxl.Workbook(); ws = wb.active
        ws.append(head)
        for r in rows: ws.append(r)
        wb.save(self.p(name))

    def questions(self, rows=None, head=Q_HEAD):
        self.write_xlsx("questions.xlsx", head, bank() if rows is None else rows)

    def students(self, rows=None, head=S_HEAD):
        self.write_xlsx("students.xlsx", head, roster() if rows is None else rows)

    def settings(self, **over):
        kv = dict(DEFAULT_SETTINGS); kv.update({k: str(v) for k, v in over.items()})
        self.p("settings.txt").write_text("\n".join(f"{k} = {v}" for k, v in kv.items()) + "\n", encoding="utf-8")

    def raw_settings(self, text):
        self.p("settings.txt").write_text(text, encoding="utf-8")

    def image(self, name, data=b"\x89PNG\r\n\x1a\n0000"):
        (self.path / "images").mkdir(exist_ok=True)
        (self.path / "images" / name).write_bytes(data)

    def load(self):
        name = f"exam_server_{next(_counter)}"
        spec = importlib.util.spec_from_file_location(name, self.p("server.py"))
        mod = importlib.util.module_from_spec(spec)
        err = self.p("exam_error.txt")
        if err.exists(): err.unlink()
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            raise LoadFailed(err.read_text(encoding="utf-8-sig") if err.exists() else "(no exam_error.txt)")
        return mod

    def expect_error(self, *needles):
        """يتأكد إن التحميل فشل وإن رسالة الخطأ فيها كل الكلمات المطلوبة. يرجّع نص الرسالة"""
        with pytest.raises(LoadFailed) as e:
            self.load()
        msg = str(e.value)
        for n in needles:
            assert n in msg, f"الرسالة ما فيها «{n}»:\n{msg}"
        return msg


@pytest.fixture
def pkg(tmp_path):
    """نسخة نظيفة من الحزمة + ملفات سليمة افتراضية (الاختبار بيخرّب اللي بدو)"""
    for f in CODE_FILES:
        copy_any(PKG_SRC / f, tmp_path / f)
    pk = Pkg(tmp_path)
    pk.questions(); pk.students(); pk.settings()
    return pk


@pytest.fixture
def srv(pkg):
    """سيرفر محمّل جاهز بالإعدادات الافتراضية"""
    return pkg.load()


def key_of(mod, g="العاشر", s="أ", n="طالب أ1"):
    return f"{mod.SET['title']}|{g}|{s}|{n}"


def start_paper(mod, key=None, dev="dev1"):
    """يبدأ ورقة لطالب مباشرة بالذاكرة (نفس اللي بيعمله /start)"""
    k = key or key_of(mod)
    mod.PAPERS[k] = mod.make_paper(); mod.CLAIMS[k] = dev
    return k
