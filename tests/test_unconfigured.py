"""إعدادات الامتحان الأساسية (العنوان وتوزيع الأسئلة): الطالب بيشوف «غير جاهز» لحد ما المعلم يحفظها من صفحة /settings"""
import json
from conftest import bank, roster
from test_http import Server, TEACHER
from test_uploads import cookie

NOT_READY = "الامتحان لسا غير جاهز"


def unconfigure(pkg, **over):
    pkg.settings(**{"كلمة_سر_المعلم": "secret", **over}); pkg.p("state.json").unlink()


def teacher(w): return {**TEACHER, **cookie(w)}


def test_saved_settings_file_is_not_enough_the_page_must_be_saved_once(pkg):
    unconfigure(pkg); w = Server(pkg).start()
    try:
        assert NOT_READY in w.get("/")[2].decode("utf-8")
        st, j, _, _ = w.post("/start", {"key": "a|b|c|d", "dev": "x"}); assert st == 503 and j["notready"]
        assert w.get("/monitor", teacher(w))[0] == 200                                        # صفحات المعلم عادية
        assert w.get("/files.json", teacher(w))[1]["unconf"] and w.get("/settings.json", teacher(w))[1]["unconf"]
        assert w.get("/health.json")[1]["warnings"]
        st, j, _, _ = w.post("/settings", {"values": {}, "rules": []}, teacher(w)); assert st == 200 and j["ok"]
        assert NOT_READY not in w.get("/")[2].decode("utf-8") and w.get("/settings.json", teacher(w))[1]["unconf"] == []
        k, st, p = w.start_student(); assert st == 200 and p["ids"]                            # بدون إعادة تشغيل
    finally: w.stop()
    assert json.loads(pkg.p("state.json").read_text(encoding="utf-8"))["configured"] is True


def test_empty_title_and_distribution_are_listed_and_keep_it_closed(pkg):
    unconfigure(pkg, **{"عنوان_الامتحان": "", "عدد_الأسئلة_الصعبة": "", "عدد_الأسئلة_المتوسطة": "", "عدد_الأسئلة_السهلة": "", "عدد_الأسئلة_الكلي": ""}); w = Server(pkg).start()
    try:
        need = w.get("/settings.json", teacher(w))[1]["unconf"]; assert "عنوان الامتحان" in need and any("توزيع" in x for x in need)
        w.post("/settings", {"values": {"عنوان_الامتحان": "امتحان الوحدة"}, "rules": []}, teacher(w))            # العنوان بس
        assert NOT_READY in w.get("/")[2].decode("utf-8") and [x for x in w.get("/settings.json", teacher(w))[1]["unconf"] if "توزيع" in x]
        w.post("/settings", {"values": {"عدد_الأسئلة_الصعبة": "2", "عدد_الأسئلة_المتوسطة": "3", "عدد_الأسئلة_السهلة": "3"}, "rules": []}, teacher(w))
        assert NOT_READY not in w.get("/")[2].decode("utf-8")
    finally: w.stop()


def test_a_running_exam_is_never_closed_and_the_flag_survives_a_restart(pkg):
    first = Server(pkg).start()
    try:
        k, st, p = first.start_student(); assert st == 200                                      # الامتحان بدأ (الإعدادات محفوظة من الصفحة حسب الـ fixture)
    finally: first.stop()
    pkg.p("state.json").unlink()                                                               # العلامة ضاعت لكن في ورقة طالب
    w = Server(pkg).start()
    try:
        assert NOT_READY not in w.get("/")[2].decode("utf-8") and w.post("/resume", {"key": k, "dev": "dev1"})[0] == 200
    finally: w.stop()


def test_the_flag_in_state_keeps_the_exam_open_after_restart(pkg):
    w = Server(pkg).start()
    try: assert NOT_READY not in w.get("/")[2].decode("utf-8")
    finally: w.stop()
    w = Server(pkg).start()
    try: assert NOT_READY not in w.get("/")[2].decode("utf-8")
    finally: w.stop()


def test_check_files_warns_but_still_passes(pkg):
    import subprocess, sys
    unconfigure(pkg)
    r = subprocess.run([sys.executable, str(pkg.p("check_files.py"))], cwd=pkg.path, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0 and "OK" in r.stdout and "لسا ما انعبّت" in r.stdout
