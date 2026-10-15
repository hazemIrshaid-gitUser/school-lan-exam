"""exam_data.zip جاي من أستاذ (فيه أحياناً قائمة طلابه وإعداداته): ما لازم يستبدل قائمة طلاب المختبر ولا إعدادات المشرف.
الأسئلة والصور بتنستبدل (هذا المطلوب)، ونسخ الطلاب/الإعدادات بتنحفظ جنب الأصلية باسم *_from_zip مع تنبيه."""
import subprocess, sys

from conftest import Q_HEAD, S_HEAD, bank, roster
from test_http import Server
from test_validation import _settings_text, _xlsx_bytes, _zip

TEACHER_ROSTER = [["التاسع", "ج", "طالب من قائمة الأستاذ"]]


def teacher_zip(pkg, with_students=True, with_settings=True, ext=".xlsx"):
    files = {"questions.xlsx": _xlsx_bytes(pkg, Q_HEAD, bank(4, 4, 4)), "images/fig.png": b"\x89PNG\r\n\x1a\n0000"}
    if with_students:
        files["students" + ext] = _xlsx_bytes(pkg, S_HEAD, TEACHER_ROSTER) if ext == ".xlsx" else "الصف,الشعبة,الاسم\nالتاسع,ج,طالب من قائمة الأستاذ\n".encode("utf-8-sig")
    if with_settings: files["settings.txt"] = _settings_text() + "\nكلمة_سر_المعلم = 0000\n"
    pkg.p("exam_data.zip").write_bytes(_zip(files))


def test_supervisor_roster_and_settings_are_kept(pkg):
    pkg.settings(**{"كلمة_سر_المعلم": "Lab-Secret"}); roster_before = pkg.p("students.xlsx").read_bytes(); settings_before = pkg.p("settings.txt").read_bytes()
    teacher_zip(pkg)
    m = pkg.load()
    assert pkg.p("students.xlsx").read_bytes() == roster_before and pkg.p("settings.txt").read_bytes() == settings_before
    assert m.SET["tpass"] == "Lab-Secret" and "التاسع" not in m.ROSTER and len(m.QLIST) == 12           # الأسئلة الجديدة انستعملت
    assert pkg.p("students_from_zip.xlsx").exists() and pkg.p("settings_from_zip.txt").exists() and (pkg.path / "images" / "fig.png").exists()
    assert m.zip_leftovers() == ["settings_from_zip.txt", "students_from_zip.xlsx"]
    assert any("exam_data.zip كان فيه قائمة طلاب" in w for w in m.health_data()["warnings"])


def test_csv_roster_counts_as_existing_too(pkg):
    pkg.p("students.xlsx").unlink(); pkg.p("students.csv").write_text("الصف,الشعبة,الاسم\nالعاشر,أ,طالب أ1\n", encoding="utf-8-sig")
    teacher_zip(pkg, with_settings=False)
    m = pkg.load()
    assert pkg.p("students.csv").exists() and not pkg.p("students.xlsx").exists() and pkg.p("students_from_zip.xlsx").exists()
    assert list(m.ROSTER) == ["العاشر"]


def test_first_time_folder_still_takes_everything_from_the_zip(pkg):
    for n in ("questions.xlsx", "students.xlsx", "settings.txt"): pkg.p(n).unlink()
    teacher_zip(pkg)
    m = pkg.load()
    assert list(m.ROSTER) == ["التاسع"] and m.SET["tpass"] == "0000" and not m.zip_leftovers()


def test_questions_only_zip_is_the_normal_case(pkg):
    teacher_zip(pkg, with_students=False, with_settings=False)
    m = pkg.load()
    assert len(m.QLIST) == 12 and not m.zip_leftovers() and list(m.ROSTER) == ["العاشر"]


def test_check_files_mentions_the_kept_copies(pkg):
    teacher_zip(pkg)
    r = subprocess.run([sys.executable, "-X", "utf8", "check_files.py"], cwd=pkg.path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0 and "exam_data.zip كان فيه قائمة طلاب أو إعدادات" in r.stdout and "students_from_zip.xlsx" in r.stdout


def test_server_runs_with_supervisor_roster(pkg):
    pkg.settings(); teacher_zip(pkg)
    w = Server(pkg).start()
    try:
        k, _, p = w.start_student("d1"); assert p["status"] == "ok"                                     # طالب من قائمة المختبر بيبدأ
        st, j, *_ = w.post("/start", {"key": "اختبار الوحدة|التاسع|ج|طالب من قائمة الأستاذ", "dev": "d9"}); assert j.get("status") != "ok"
    finally:
        w.stop()


def test_roster_unchanged_helper_sanity(pkg):
    assert roster()[0] == ["العاشر", "أ", "طالب أ1"]
