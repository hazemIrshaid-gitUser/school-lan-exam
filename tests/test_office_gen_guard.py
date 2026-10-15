"""حماية office_gen.py: ما يترك Excel مخفي شغّال بعد timeout أو انقطاع أو استثناء، وما يلمس Excel المستخدم. بتشغّل Excel حقيقي (بتتخطى لو مش مثبّت أو لو في Excel شغّال)."""
import os, subprocess, time

import pytest
import office_gen

pytestmark = pytest.mark.skipif(os.name != "nt" or not os.path.exists(office_gen.EXCEL), reason="Excel غير مثبّت")

HOLD = r'''
$xl = New-Object -ComObject Excel.Application
Start-Sleep 120
'''


@pytest.fixture(autouse=True)
def no_excel_running_and_clean_after():
    if office_gen.excel_procs(): pytest.skip("Excel شغّال عند المستخدم: ما بنلمسه")
    yield
    for p in office_gen.excel_procs():                                          # تنظيف احتياطي للاختبار نفسه (كلها من الاختبار لأن ما كان في Excel قبل)
        if office_gen._is_automation(p): office_gen._kill(p["pid"])
    office_gen.PID_FILE.unlink(missing_ok=True)


def make_orphan(tmp_path):
    """نسخة Excel مخفية بدون عميل شغّال (مثل انقطاع سكربت التوليد): نبدأ سكربت يفتحها وبعدين نقتل السكربت بالقوة"""
    ps = tmp_path / "hold.ps1"; ps.write_text(HOLD, encoding="utf-8")
    exe = "C:/Windows/SysWOW64/WindowsPowerShell/v1.0/powershell.exe"
    proc = subprocess.Popen([exe if os.path.exists(exe) else "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        found = [p for p in office_gen.excel_procs() if office_gen._is_automation(p)]
        if found: break
        time.sleep(0.5)
    else:
        proc.kill(); pytest.skip("ما قدرنا نشغّل Excel عبر COM")
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)     # يقتل السكربت وبتضل Excel يتيمة
    time.sleep(0.5)
    return found[0]


def test_timeout_leaves_no_excel_behind(tmp_path):
    office_gen.make_bases(tmp_path)
    with pytest.raises(subprocess.TimeoutExpired):
        office_gen.run_excel(tmp_path, timeout=5)                              # يقطعه بنص الشغل (Excel بيكون فتح)
    time.sleep(1)
    assert office_gen.excel_procs() == [] and not office_gen.PID_FILE.exists()


def test_exception_inside_run_still_cleans_up(tmp_path, monkeypatch):
    office_gen.make_bases(tmp_path)
    real_run = subprocess.run
    def boom(cmd, *a, **k):
        if "gen.ps1" in " ".join(map(str, cmd)):
            time.sleep(4)                                                      # خلّي Excel يفتح
            raise KeyboardInterrupt("Ctrl+C")
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(office_gen.subprocess, "run", boom)
    with pytest.raises(KeyboardInterrupt):
        office_gen.run_excel(tmp_path, timeout=60)
    monkeypatch.undo(); time.sleep(1)
    assert office_gen.excel_procs() == []


def test_orphan_from_killed_previous_run_is_cleaned_at_next_start(tmp_path):
    orphan = make_orphan(tmp_path)
    office_gen._remember({orphan["pid"]: orphan["t"]})                         # زي ما بيسجّلها المراقب أثناء التشغيلة اللي انقطعت
    assert office_gen.cleanup_orphans() == [orphan["pid"]]
    time.sleep(1)
    assert office_gen.excel_procs() == [] and not office_gen.PID_FILE.exists()


def test_cleanup_does_not_touch_excel_with_different_start_time(tmp_path):
    """نفس الـ PID لكن وقت بدء مختلف = PID أُعيد استعماله لبرنامج ثاني: ما بنقفله"""
    orphan = make_orphan(tmp_path)
    office_gen._remember({orphan["pid"]: orphan["t"] - 5000})
    assert office_gen.cleanup_orphans() == []
    assert any(p["pid"] == orphan["pid"] for p in office_gen.excel_procs())


def test_cleanup_ignores_unregistered_excel(tmp_path):
    orphan = make_orphan(tmp_path)
    assert office_gen.cleanup_orphans() == []                                  # ما في ملف PIDs: ما بنلمس أي Excel
    assert any(p["pid"] == orphan["pid"] for p in office_gen.excel_procs())


def test_generate_refuses_when_users_excel_is_running(tmp_path):
    make_orphan(tmp_path)                                                      # بتتصرف مثل Excel المستخدم (غير مسجّلة عندنا)
    with pytest.raises(RuntimeError, match="Excel"):
        office_gen.generate(tmp_path)
    assert any(office_gen._is_automation(p) for p in office_gen.excel_procs())   # وما قفلها


def test_normal_run_still_works_and_leaves_nothing(tmp_path):
    files = office_gen.generate(tmp_path)
    assert "excel_plain.xlsx" in files and "excel_features.xlsx" in files and "excel_ansi_arabic.csv" in files
    time.sleep(1)
    assert office_gen.excel_procs() == [] and not office_gen.PID_FILE.exists()
