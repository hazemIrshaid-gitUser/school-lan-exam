"""ملفات ممسوكة من برنامج ثاني على ويندوز (مضاد فيروسات، مزامنة OneDrive، الفهرسة، Excel): الحفظ لازم يصبر شوي بدل ما يضيع،
بس ما يعلّق التسليمات لما results.csv مفتوح بـ Excel طول الوقت. وصفحة الفحص بتنبّه لو مجلد الامتحان داخل OneDrive."""
import os, threading, time

import pytest

WIN = pytest.mark.skipif(os.name != "nt", reason="ويندوز فقط: فتح الملف بيمنع استبداله")


def hold(path, sec):
    """يفتح الملف (بايثون على ويندوز بيفتح بدون FILE_SHARE_DELETE، زي ما بيعمل مضاد الفيروسات أو Excel) لمدة sec"""
    ready = threading.Event()
    def run():
        with open(path, "rb"):
            ready.set(); time.sleep(sec)
    t = threading.Thread(target=run, daemon=True); t.start(); ready.wait(5)
    return t


@WIN
def test_save_waits_for_a_briefly_locked_file(srv, tmp_path):
    p = str(tmp_path / "papers.json"); srv.atomic_write(p, "old")
    t = hold(p, 0.25); t0 = time.time()
    srv.atomic_write(p, "new")
    assert open(p, encoding="utf-8").read() == "new" and 0.15 <= time.time() - t0 < 1.5 and not os.path.exists(p + ".tmp")
    t.join()


@WIN
def test_save_gives_up_after_half_a_second_and_keeps_the_old_file(srv, tmp_path):
    p = str(tmp_path / "state.json"); srv.atomic_write(p, "old")
    t = hold(p, 3); t0 = time.time()
    with pytest.raises(PermissionError):
        srv.atomic_write(p, "new")
    assert 0.3 <= time.time() - t0 < 1.5
    t.join(); assert open(p, encoding="utf-8").read() == "old"


@WIN
def test_answers_flush_retries_next_cycle_when_locked(srv):
    srv.ANS["k"] = {"1": 2}; srv.ANS_DIRTY[0] = True
    open(srv.ANS_FILE, "w").close(); t = hold(srv.ANS_FILE, 1.5)
    srv.flush_answers(); assert srv.ANS_DIRTY[0] is True                                    # فشل: بيضل «متغيّر» عشان الدورة الجاية تحفظ
    t.join(); srv.flush_answers(); assert srv.ANS_DIRTY[0] is False and '"k"' in open(srv.ANS_FILE, encoding="utf-8").read()


@WIN
def test_results_csv_open_in_excel_does_not_slow_down_submits(srv, capsys):
    srv.write_results_csv(); t = hold(srv.OUT, 3)
    t0 = time.time()
    for _ in range(5): srv.write_results_csv()
    assert time.time() - t0 < 1.0, "كل تسليم كان رح يستنّى نص ثانية على ملف Excel"
    assert "results.csv" in capsys.readouterr().out
    t.join()


def test_non_permission_errors_are_not_retried(srv, tmp_path, monkeypatch):
    calls = []
    def boom(a, b): calls.append(1); raise OSError(28, "No space left on device")
    monkeypatch.setattr(srv.os, "replace", boom)
    with pytest.raises(OSError): srv.atomic_write(str(tmp_path / "x.json"), "x")
    assert len(calls) == 1


# ============================ OneDrive ============================
@pytest.mark.parametrize("env,base,expect", [
    ({"OneDrive": r"C:\Users\t\OneDrive"}, r"C:\Users\t\OneDrive\Desktop\exam", True),
    ({"OneDriveCommercial": r"C:\Users\t\OneDrive - School"}, r"C:\Users\t\OneDrive - School\Desktop\exam", True),
    ({}, r"C:\Users\t\OneDrive\Desktop\exam", True),                                            # حتى لو المتغير مش موجود: الاسم بالمسار
    ({"OneDriveConsumer": r"E:\Cloud\Sync"}, r"E:\Cloud\Sync\Desktop\exam", True),             # مجلد OneDrive منقول لمكان باسم ثاني
    ({"OneDrive": r"C:\Users\t\OneDrive"}, r"C:\Users\t\Desktop\exam", False),
    ({"OneDrive": r"C:\Users\t\OneDrive"}, r"C:\Users\t\OneDriveBackup\exam", False),          # مجلد اسمه بيشبه بس مش هو
    ({}, r"D:\exam", False),
])
def test_in_onedrive(srv, monkeypatch, env, base, expect):
    if os.name != "nt": pytest.skip("مسارات ويندوز")
    for v in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"): monkeypatch.delenv(v, raising=False)
    for k, v in env.items(): monkeypatch.setenv(k, v)
    assert srv.in_onedrive(base) is expect


def test_health_warns_when_exam_folder_is_in_onedrive(srv, monkeypatch):
    monkeypatch.setattr(srv, "in_onedrive", lambda p=None: True)
    w = [x for x in srv.health_data()["warnings"] if "OneDrive" in x]
    assert len(w) == 1 and "C:\\exam" in w[0] and "C:\\\\exam" not in w[0]
    monkeypatch.setattr(srv, "in_onedrive", lambda p=None: False)
    assert not [x for x in srv.health_data()["warnings"] if "OneDrive" in x]


def test_this_test_folder_is_not_reported_as_onedrive(srv):
    assert srv.in_onedrive() is False
