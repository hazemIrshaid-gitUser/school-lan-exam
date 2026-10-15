"""يولّد ملفات أسئلة بواسطة برامج Office الحقيقية (Excel عبر COM، LibreOffice عبر سطر الأوامر) لاختبار قارئ xlsx/csv الخاص بالسيرفر.
ما بيلمس أي نافذة Excel/LibreOffice مفتوحة عند المستخدم: بيرفض يشغّل Excel لو في نسخة شغّالة، وLibreOffice بيشتغل بملف إعدادات مستقل."""
import json, os, pathlib, shutil, subprocess, tempfile, threading, time

import openpyxl
from conftest import Q_HEAD, bank

EXCEL = r"C:\Program Files (x86)\Microsoft Office\Root\Office16\EXCEL.EXE"
SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"

PS_SCRIPT = r'''
param([string]$dir)
$ErrorActionPreference = "Stop"
if (Get-Process EXCEL -ErrorAction SilentlyContinue) { Write-Output "EXCEL_ALREADY_RUNNING"; exit 3 }
$bf = [Reflection.BindingFlags]
# استدعاء متأخر (late binding): مكتبة أنواع Excel عند المستخدم معطوبة فما بنقدر نستعمل الواجهة العادية
function G($o, $n, $a = @()) { $r = $o.GetType().InvokeMember($n, $bf::GetProperty, $null, $o, $a); return ,$r }
function S($o, $n, $v) { [void]$o.GetType().InvokeMember($n, $bf::SetProperty, $null, $o, @($v)) }
function C($o, $n, $a = @()) { $r = $o.GetType().InvokeMember($n, $bf::InvokeMethod, $null, $o, $a); return ,$r }
$xl = New-Object -ComObject Excel.Application
S $xl "Visible" $false; S $xl "DisplayAlerts" $false
$wbs = G $xl "Workbooks"
function P($n) { return [string]([System.IO.Path]::Combine($dir, $n)) }          # string عادي (Join-Path بيرجّع PSObject وCOM بيرفضه: Type mismatch)
function Open($name) { return ,(C $wbs "Open" @((P $name))) }
function SaveAs($wb, $name, $fmt) { [void](C $wb "SaveAs" @((P $name), [int]$fmt)) }
function Close($wb) { [void](C $wb "Close" @($false)) }
function Rng($ws, $a) { return ,(G $ws "Range" @($a)) }
function Put($ws, $a, $v) { S (Rng $ws $a) "Value2" $v }
try {
  foreach ($job in @(@("base.xlsx","excel_plain.xlsx",51), @("base.xlsx","excel_utf8.csv",62), @("ascii.xlsx","excel_ansi.csv",6), @("base.xlsx","excel_ansi_arabic.csv",6), @("ascii.xlsx","excel_mac.csv",22), @("base.xlsx","excel_old.xls",56))) {
    $wb = Open $job[0]; SaveAs $wb $job[1] $job[2]; Close $wb
  }

  # خصائص صعبة: صفوف 13..22
  $wb = Open "base.xlsx"; $ws = G $wb "ActiveSheet"
  function Row($r, $q) { Put $ws "A$r" $q; Put $ws "F$r" "a"; Put $ws "G$r" "easy" }
  Row 13 "Q13 booleans";  Put $ws "B13" $true; Put $ws "C13" $false; Put $ws "D13" "x"; Put $ws "E13" "y"
  Row 14 "Q14 formulas";  S (Rng $ws "B14") "Formula" "=2+3"; S (Rng $ws "C14") "Formula" '="ab"&"cd"'; S (Rng $ws "D14") "Formula" "=1/3"; S (Rng $ws "E14") "Formula" "=TRUE"
  Row 15 "Q15 rich text"; Put $ws "A15" "Bold start then normal text"
                          $f1 = G (G (Rng $ws "A15") "Characters" @(1,4)) "Font"; S $f1 "Bold" $true
                          $f2 = G (G (Rng $ws "A15") "Characters" @(6,5)) "Font"; S $f2 "Color" 255
                          Put $ws "B15" "b"; Put $ws "C15" "c"; Put $ws "D15" "d"
  Row 16 "Q16 dates";     S (Rng $ws "B16") "Formula" "=DATE(1948,1,2)"; S (Rng $ws "B16") "NumberFormat" "m/d/yyyy"
                          Put $ws "C16" "1/2"; S (Rng $ws "D16") "NumberFormat" "@"; Put $ws "D16" "1/2"; Put $ws "E16" "x"
  Row 17 "Q17 zeros";     S (Rng $ws "B17") "NumberFormat" "@"; Put $ws "B17" "012345"; Put $ws "C17" "012345"; Put $ws "D17" "'012345"; Put $ws "E17" "0.5"
  Row 18 ("Q18 line1" + [char]10 + "line2"); S (Rng $ws "A18") "WrapText" $true; Put $ws "B18" ("o1" + [char]10 + "o2"); Put $ws "C18" "c"; Put $ws "D18" "d"
  Row 19 "Q19 numbers";   Put $ws "B19" ([double]1234567890123456); S (Rng $ws "C19") "Formula" "=0.1+0.2"; Put $ws "D19" ([double]1e20); Put $ws "E19" ([double]-0.5)
  Row 20 "Q20 errors";    S (Rng $ws "B20") "Formula" "=NA()"; S (Rng $ws "C20") "Formula" "=1/0"; Put $ws "D20" "ok"
  Row 21 "Q21 percent";   Put $ws "B21" ([double]0.25); S (Rng $ws "B21") "NumberFormat" "0%"; Put $ws "C21" "25%"; Put $ws "D21" '$5'; Put $ws "E21" "1,000"
  Row 22 "Q22 spaces";    Put $ws "B22" "  padded  "; Put $ws "C22" ("tab" + [char]9 + "inside"); Put $ws "D22" "d"
  S (G (Rng $ws "A1:K1") "Font") "Bold" $true
  SaveAs $wb "excel_features.xlsx" 51; Close $wb

  # أول ورقة مش ورقة الأسئلة (الأستاذ أضاف ورقة ملاحظات قبلها)، ثم مخفية
  $wb = Open "base.xlsx"; $ws = G $wb "ActiveSheet"
  $new = C (G $wb "Worksheets") "Add" @($ws); S $new "Name" "Notes"; Put $new "A1" "notes"
  SaveAs $wb "excel_notes_first.xlsx" 51
  S $new "Visible" 0
  SaveAs $wb "excel_hidden_first.xlsx" 51; Close $wb

  # صف عنوان فوق الترويسة
  $wb = Open "base.xlsx"; $ws = G $wb "ActiveSheet"
  [void](C (G (G $ws "Rows") "Item" @(1)) "Insert"); Put $ws "A1" "Exam title row"
  SaveAs $wb "excel_title_row.xlsx" 51; Close $wb

  # جدول Excel (ListObject)
  $wb = Open "base.xlsx"; $ws = G $wb "ActiveSheet"
  [void](C (G $ws "ListObjects") "Add" @(1, (Rng $ws "A1:K12"), [Type]::Missing, 1))
  SaveAs $wb "excel_table.xlsx" 51; Close $wb
  Write-Output "EXCEL_DONE"
} finally {
  try { [void](C $xl "Quit") } catch {}
  [void][Runtime.InteropServices.Marshal]::ReleaseComObject($xl)
}
'''


def make_bases(d):
    d = pathlib.Path(d)
    for name, rows in (("base.xlsx", bank()), ("ascii.xlsx", [[c.replace("سؤال رقم", "Question").replace("خ", "o") if isinstance(c, str) else c for c in r] for r in bank()])):
        wb = openpyxl.Workbook(); ws = wb.active; ws.append(Q_HEAD)
        for r in rows:
            r = list(r); r[5] = "a" if name == "ascii.xlsx" else r[5]; r[6] = {"صعب": "hard", "وسط": "medium", "سهل": "easy"}[r[6]] if name == "ascii.xlsx" else r[6]
            ws.append(r)
        wb.save(d / name)


PID_FILE = pathlib.Path(tempfile.gettempdir()) / "office_gen_excel_pids.json"      # نسخ Excel اللي شغّلها هالمولّد (pid + وقت البدء)، عشان نقفلها لو انقطعت التشغيلة


def excel_procs():
    """كل عمليات Excel الشغّالة: [{pid, cmd, t}] (t = وقت البدء بالثواني)"""
    try:
        import psutil
        out = []
        for p in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
            if (p.info["name"] or "").lower() == "excel.exe":
                out.append({"pid": p.info["pid"], "cmd": " ".join(p.info["cmdline"] or []), "t": int(p.info["create_time"])})
        return out
    except ImportError:
        pass
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='EXCEL.EXE'\" | Select-Object ProcessId, CommandLine, "
          "@{n='t';e={[int64]([DateTimeOffset]$_.CreationDate).ToUnixTimeSeconds()}} | ConvertTo-Json -Compress")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60)
    if not r.stdout.strip(): return []
    data = json.loads(r.stdout); data = [data] if isinstance(data, dict) else data
    return [{"pid": d["ProcessId"], "cmd": d.get("CommandLine") or "", "t": int(d["t"])} for d in data]


def _is_automation(p): return "-Embedding" in p["cmd"]                                   # نسخة شغّلها برنامج عبر COM (مش نافذة المستخدم)


def _kill(pid): subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def _remember(mine):
    PID_FILE.write_text(json.dumps([[pid, t] for pid, t in mine.items()]), encoding="utf-8")


def cleanup_orphans():
    """يقفل بقايا Excel من تشغيلة سابقة انقطعت (مسجّلة بملف PIDs). بيقفل بس لو: نفس الـ PID ونفس وقت البدء ونسخة automation، فما بيلمس Excel المستخدم ولا PID أُعيد استعماله"""
    if not PID_FILE.exists(): return []
    try: saved = {(int(a), int(b)) for a, b in json.loads(PID_FILE.read_text(encoding="utf-8"))}
    except Exception: saved = set()
    killed = []
    for p in excel_procs():
        if (p["pid"], p["t"]) in saved and _is_automation(p):
            _kill(p["pid"]); killed.append(p["pid"])
    PID_FILE.unlink(missing_ok=True)
    return killed


def run_excel(d, timeout=240):
    """يشغّل سكربت Excel، ومهما صار (انتهى، timeout، استثناء، Ctrl+C) بيقفل أي نسخة Excel شغّلها بنفسه. وبيصلّح بقايا تشغيلة سابقة انقطعت بالكامل"""
    cleanup_orphans()
    before = {p["pid"] for p in excel_procs()}
    mine, stop = {}, threading.Event()

    def watch():
        while not stop.is_set():
            try:
                for p in excel_procs():
                    if p["pid"] not in before and p["pid"] not in mine and _is_automation(p):
                        mine[p["pid"]] = p["t"]; _remember(mine)
            except Exception:
                pass
            stop.wait(0.7)
    th = threading.Thread(target=watch, daemon=True); th.start()
    try:
        ps = pathlib.Path(d) / "gen.ps1"; ps.write_text(PS_SCRIPT, encoding="utf-8")
        PS32 = "C:/Windows/SysWOW64/WindowsPowerShell/v1.0/powershell.exe"      # Office 32-bit لازم PowerShell 32-bit وإلا TYPE_E_CANTLOADLIBRARY
        return subprocess.run([PS32 if os.path.exists(PS32) else "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps), "-dir", str(d)],
                              capture_output=True, text=True, timeout=timeout)
    finally:
        stop.set(); th.join(5)
        for p in excel_procs():                                                  # مسح أخير: أي automation جديد من بعد ما بدأنا (مش من before)
            if p["pid"] not in before and _is_automation(p): _kill(p["pid"])
        for pid in list(mine): _kill(pid)
        PID_FILE.unlink(missing_ok=True)


def run_soffice(src, outdir, fmt, profile):
    """تحويل بدون لمس نسخة LibreOffice المفتوحة عند المستخدم (ملف إعدادات مستقل)"""
    outdir = pathlib.Path(outdir); outdir.mkdir(exist_ok=True)
    uri = pathlib.Path(profile).as_uri()
    return subprocess.run([SOFFICE, f"-env:UserInstallation={uri}", "--headless", "--norestore", "--convert-to", fmt, "--outdir", str(outdir), str(src)],
                          capture_output=True, text=True, timeout=240)


def generate(d):
    """يرجّع dict: اسم الملف -> مسار (الغايب = فشل التوليد). بيرمي RuntimeError لو Excel شغّال عند المستخدم"""
    d = pathlib.Path(d); make_bases(d); out = {}
    if os.path.exists(EXCEL):
        r = run_excel(d)
        if "EXCEL_ALREADY_RUNNING" in r.stdout: raise RuntimeError("Excel شغّال عند المستخدم: ما بنلمسه")
        out["_excel_log"] = (r.stdout + r.stderr)[-1500:]
    if os.path.exists(SOFFICE):
        prof = d / "lo_profile"
        for src, fmt, name in (("base.xlsx", "xlsx", "lo_plain.xlsx"), ("base.xlsx", "csv:Text - txt - csv (StarCalc):44,34,76,1", "lo_utf8.csv"),
                               ("excel_features.xlsx", "xlsx", "lo_features.xlsx")):
            s = d / src
            if not s.exists(): continue
            sub = d / ("lo_" + name.replace(".", "_")); r = run_soffice(s, sub, fmt, prof)
            produced = list(sub.glob("*"))
            if produced: shutil.copy(produced[0], d / name)
            else: out["_lo_log_" + name] = (r.stdout + r.stderr)[-500:]
    for f in d.iterdir():
        if f.suffix.lower() in (".xlsx", ".csv", ".xls"): out[f.name] = f
    return out


if __name__ == "__main__":
    import sys, tempfile
    d = pathlib.Path(tempfile.mkdtemp(prefix="office_")); t0 = time.time()
    res = generate(d)
    print("dir:", d, "| seconds:", round(time.time() - t0))
    for k, v in sorted(res.items()): print(" ", k, "->", v if not str(k).startswith("_") else "\n" + str(v))
