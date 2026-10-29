"""وضع التجهيز: السيرفر بيشتغل حتى لو ملف الأسئلة أو الطلاب ناقص أو فيه خطأ (بدل ما يقف)، والمعلم بيرفع الناقص من صفحة «الملفات»،
والطالب بيشوف «الامتحان غير جاهز»، وأول ما يكتمل بيجهز الامتحان لحاله بدون إعادة تشغيل."""
import io, json, os, subprocess, sys

import openpyxl
import pytest
from conftest import PKG_SRC, Q_HEAD, bank, q, roster
from test_http import Server, TEACHER
from test_uploads import PNG, cookie, qx, sx, up  # noqa: F401  (up/cookie/qx/sx: مساعدات الرفع)

sys.path.insert(0, str(PKG_SRC))
from exam_core import uploads  # noqa: E402
from exam_core.util import DataError  # noqa: E402

NOT_READY = "الامتحان لسا غير جاهز"


def drop(pkg, *names):
    for n in names: pkg.p(n).unlink()


@pytest.fixture
def web(pkg):
    drop(pkg, "questions.xlsx", "students.xlsx"); pkg.settings(**{"كلمة_سر_المعلم": "secret"}); s = Server(pkg).start()
    yield s
    s.stop()


# ============================ التشغيل بدون ملفات ============================
def test_server_starts_with_no_questions_and_no_students(pkg):
    drop(pkg, "questions.xlsx", "students.xlsx"); m = pkg.load()
    assert set(m.ctx.SETUP) == {"questions", "students"} and uploads.setup_view(m.ctx) == {"questions": "", "students": ""}        # "" = ما انرفع (مش خطأ)
    assert NOT_READY in m.ctx.PAGE and m.ctx.PREVIEW == "" and m.QLIST == [] and m.ROSTER == {} and m.PICK == {}
    assert not pkg.p("exam_error.txt").exists()                                       # ملف ناقص مش «مشكلة بالملف»: ما في داعي لنافذة خطأ


def test_only_the_missing_file_is_flagged(pkg):
    drop(pkg, "students.xlsx"); m = pkg.load()
    assert set(m.ctx.SETUP) == {"students"} and len(m.QLIST) == 11 and NOT_READY in m.ctx.PAGE
    pkg.students(); drop(pkg, "questions.xlsx"); m = pkg.load(); assert set(m.ctx.SETUP) == {"questions"} and sum(len(n) for g in m.ROSTER.values() for n in g.values()) == 5


def test_a_file_with_errors_also_starts_in_setup_mode_with_the_details(pkg):
    rows = bank(); rows[0][5] = "ز"; pkg.questions(rows); m = pkg.load()
    assert set(m.ctx.SETUP) == {"questions"} and "سطر 2" in m.ctx.SETUP["questions"] and uploads.setup_view(m.ctx)["questions"]
    assert "سطر 2" in pkg.p("exam_error.txt").read_text(encoding="utf-8-sig") and m.QLIST == [] and m.IMG_LIST == []        # التفاصيل بنافذة المفكرة وبصفحة الملفات


def test_a_corrupt_file_is_a_setup_problem_not_a_crash(pkg):
    pkg.p("questions.xlsx").write_bytes(b"not an excel file"); m = pkg.load()
    assert "خطأ بقراءة الملفات" in m.ctx.SETUP["questions"]


def test_a_settings_error_still_stops_the_server(pkg):
    pkg.raw_settings("هذا_إعداد_غلط = 5\n"); drop(pkg, "questions.xlsx"); pkg.expect_error("غير معروف")


def test_rules_that_need_more_questions_than_the_file_has_are_a_settings_problem(pkg):
    pkg.questions([r + ["وحدة 1"] for r in bank(3, 4, 4)], head=Q_HEAD + ["الوحدة"])
    pkg.raw_settings("عنوان_الامتحان = ت\nكلمة_سر_المعلم = secret\nسحب = الوحدة:وحدة 1 | المستوى:سهل | العدد:9\n"); m = pkg.load()
    assert set(m.ctx.SETUP) == {"settings"} and "قاعدة" in m.ctx.SETUP["settings"] or "سحب" in m.ctx.SETUP["settings"]
    assert len(m.QLIST) == 11 and NOT_READY in m.ctx.PAGE                                 # الملفات سليمة بس الامتحان مش جاهز


# ============================ الوصول بوضع التجهيز ============================
def test_students_see_not_ready_and_cannot_start(web):
    st, _, raw, _ = web.get("/"); h = raw.decode("utf-8")
    assert st == 200 and NOT_READY in h and "http-equiv=refresh" in h and "الأسئلة" not in h.replace("لسا", "")        # بدون تفاصيل
    assert web.get("/ok")[0] == 200 and web.get("/taken")[0] == 200
    for path in ("/start", "/resume", "/submit", "/ping", "/review"):
        st, j, _, _ = web.post(path, {"key": "x|y|z|w", "dev": "d"}); assert st == 503 and j["notready"] is True, path


def test_teacher_pages_are_limited_to_the_upload_page_in_setup_mode(web):
    ck = cookie(web)
    for path in ("/monitor", "/report", "/sheet", "/key", "/teacher", "/settings", "/codes", "/monitor.json"):
        st, _, _, h = web.get(path, ck); assert st == 302 and h["Location"] == "/files", path
    for path in ("/files", "/files.json", "/template/questions.xlsx", "/template/students.xlsx", "/health", "/health.json"):
        assert web.get(path, ck)[0] == 200, path
    st, j, _, _ = web.get("/files.json", ck); assert j["setup"] == {"questions": "", "students": ""} and j["questions"]["count"] == 0 and j["students"]["count"] == 0
    st, j, _, _ = web.get("/health.json", ck); assert j["level"] == "warn" and any("وضع التجهيز" in w for w in j["warnings"])
    assert web.post("/monitor", {"close": True}, {**TEACHER, **ck})[0] == 503 and web.post("/settings", {"values": {}, "rules": []}, {**TEACHER, **ck})[0] == 503


def test_files_page_explains_the_setup_state(web, pkg):
    ck = cookie(web); h = web.get("/files", ck)[2].decode("utf-8")
    assert "setup" in h and "وضع التجهيز" in h and "لسا ما انرفع" in h


# ============================ الانتقال للوضع العادي ============================
def go_live_in_order(web, first):
    ck = {**TEACHER, **cookie(web)}
    jobs = {"questions": lambda: up(web, "questions", qx(bank(2, 3, 3))), "students": lambda: up(web, "students", sx(roster(3, 2)))}
    other = "students" if first == "questions" else "questions"
    st, j, _, _ = jobs[first](); assert st == 200 and j["ok"]
    assert j["pending"] == (["الطلاب"] if first == "questions" else ["الأسئلة"])
    assert NOT_READY in web.get("/")[2].decode("utf-8") and web.post("/start", {"key": "a", "dev": "d"})[0] == 503      # لسا ناقص
    st, j, _, _ = jobs[other](); assert st == 200 and j["ok"] and j["pending"] == []
    h = web.get("/")[2].decode("utf-8"); assert NOT_READY not in h and 'id="g"' in h                              # صفحة الدخول العادية
    assert web.get("/files.json", ck)[1]["setup"] == {} and web.get("/monitor", ck)[0] == 200 and web.get("/key", ck)[0] == 200
    k, st, p = web.start_student("d1"); assert st == 200 and p["ids"]                                             # الطالب بيبدأ فعلاً بدون إعادة تشغيل


def test_questions_then_students_makes_the_exam_ready(web): go_live_in_order(web, "questions")
def test_students_then_questions_makes_the_exam_ready(web): go_live_in_order(web, "students")


def test_images_can_be_uploaded_before_the_questions_in_setup_mode(web, pkg):
    assert up(web, "image", PNG, name="fig1.png")[0] == 200
    rows = bank(2, 3, 3); rows[0][0] += " [img:fig1.png]"
    st, j, _, _ = up(web, "questions", qx(rows)); assert st == 200 and j["images_used"] == 1


def test_uploading_a_fixed_file_replaces_the_broken_one_and_clears_the_error(pkg):
    rows = bank(2, 3, 3); rows[0][5] = "ز"; pkg.questions(rows); m = pkg.load()
    assert "questions" in m.ctx.SETUP and pkg.p("exam_error.txt").exists()
    r = uploads.upload_questions(m.ctx, qx(bank(2, 3, 3)))
    assert r["pending"] == [] and m.ctx.SETUP == {} and NOT_READY not in m.ctx.PAGE and len(m.QLIST) == 8 and m.PICK
    assert not pkg.p("exam_error.txt").exists() and m.ctx.PREVIEW                       # الرسالة القديمة انشالت والمعاينة انبنت
    assert os.listdir(os.path.join(pkg.path, "نسخ_الملفات"))[0].startswith("questions_")          # الملف المعطوب انحفظ بالنسخ


def test_a_bad_upload_in_setup_mode_changes_nothing(pkg):
    drop(pkg, "questions.xlsx", "students.xlsx"); m = pkg.load()
    bad = bank(2, 3, 3); bad[1][5] = "ز"
    with pytest.raises(DataError, match="سطر 3"): uploads.upload_questions(m.ctx, qx(bad))
    assert set(m.ctx.SETUP) == {"questions", "students"} and m.QLIST == [] and not pkg.p("questions.xlsx").exists() and NOT_READY in m.ctx.PAGE


def test_rules_that_do_not_fit_are_rolled_back_in_setup_mode_when_students_exist(pkg):
    pkg.raw_settings("عنوان_الامتحان = ت\nكلمة_سر_المعلم = secret\n"); drop(pkg, "questions.xlsx"); m = pkg.load()       # الطلاب موجودين، الأسئلة ناقصة
    pkg.raw_settings("عنوان_الامتحان = ت\nعدد_الأسئلة_الصعبة = 5\nكلمة_سر_المعلم = secret\n")
    from exam_core import settings as S
    m.ctx.SET.clear(); m.ctx.SET.update(S.parse_settings(pkg.p("settings.txt").read_text(encoding="utf-8"), lambda: "ت"))
    with pytest.raises(DataError, match="إعدادات السحب"): uploads.upload_questions(m.ctx, qx(bank(1, 3, 3)))
    assert set(m.ctx.SETUP) == {"questions"} and m.QLIST == []


def test_fixing_the_settings_makes_a_settings_blocked_exam_ready(pkg):
    from exam_core import admin
    pkg.questions([r + ["وحدة 1"] for r in bank(3, 4, 4)], head=Q_HEAD + ["الوحدة"])
    pkg.raw_settings("عنوان_الامتحان = ت\nكلمة_سر_المعلم = secret\nسحب = الوحدة:وحدة 1 | المستوى:سهل | العدد:9\n"); m = pkg.load()
    assert set(m.ctx.SETUP) == {"settings"}
    admin.apply_settings(m.ctx, {"values": {}, "rules": ["الوحدة:وحدة 1 | المستوى:سهل | العدد:2"]})
    assert m.ctx.SETUP == {} and NOT_READY not in m.ctx.PAGE and sum(m.PICK.values()) == 2


def test_settings_page_is_reachable_when_only_the_rules_block_the_exam(pkg):
    pkg.questions([r + ["وحدة 1"] for r in bank(3, 4, 4)], head=Q_HEAD + ["الوحدة"])
    pkg.raw_settings("عنوان_الامتحان = ت\nكلمة_سر_المعلم = secret\nسحب = الوحدة:وحدة 1 | المستوى:سهل | العدد:9\n"); w = Server(pkg).start()
    try:
        ck = cookie(w); assert w.get("/settings", ck)[0] == 200 and w.get("/settings.json", ck)[0] == 200 and w.get("/monitor", ck)[0] == 302
        st, j, _, _ = w.post("/settings", {"values": {}, "rules": ["الوحدة:وحدة 1 | المستوى:سهل | العدد:2"]}, {**TEACHER, **ck}); assert st == 200 and j["ok"]
        assert w.get("/files.json", ck)[1]["setup"] == {} and w.get("/monitor", ck)[0] == 200
    finally:
        w.stop()


# ============================ فحص الملفات والأدوات ============================
def run_check(pkg):
    return subprocess.run([sys.executable, "-X", "utf8", "check_files.py"], cwd=pkg.path, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
                          env=dict(os.environ, PYTHONIOENCODING="utf-8"))


def test_check_files_fails_when_files_are_missing(pkg):
    drop(pkg, "questions.xlsx"); r = run_check(pkg)
    assert r.returncode != 0 and "PROBLEM WITH THE EXAM FILES" in r.stdout and "Missing file" in r.stdout and "OK - the exam files are valid" not in r.stdout
    assert "questions" in pkg.p("exam_error.txt").read_text(encoding="utf-8-sig")


def test_check_files_still_passes_with_good_files(pkg):
    r = run_check(pkg); assert r.returncode == 0 and "OK - the exam files are valid" in r.stdout


def test_the_update_folder_carries_the_same_check_files():
    p1 = PKG_SRC / "check_files.py"; p2 = next(PKG_SRC.parent.glob("2_*"), None)
    if p2 is None: pytest.skip("مجلد التحديث مش موجود (المخزن العام)")
    assert (p2 / "check_files.py").read_bytes() == p1.read_bytes()
