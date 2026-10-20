# -*- coding: utf-8 -*-
"""جمع معلومات المشكلة: بيكتب ملف نصي واحد (problem_report_....txt) فيه كل اللي بيحتاجه حدا (أو Claude) ليفهم شو صار:
حالة السيرفر الآن، الشبكة، سلامة ملفات الامتحان، والسجلات. بيقرأ بس — ما بيغيّر ولا ملف من ملفات الامتحان.
كلمة سر المعلم ورموز دخول الطلاب بتنخفي. ما بيستورد server.py (عشان يشتغل حتى لو ملفات الامتحان فيها مشكلة).
التشغيل: دبل كليك على report_problem.bat"""
import hashlib, json, os, platform, re, shutil, socket, subprocess, sys, time, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NOW = time.time()
MAX_CHARS = 60000                                  # أكبر حجم لكل ملف منسوخ بالتقرير
LOG_TAIL = 300                                     # آخر كم سطر من exam_log.txt
DATA_JSON = ("claims.json", "papers.json", "state.json", "answers.json")
CODE_FILES = ("server.py", "template.html", "check_files.py", "figures_tool.py", "report_problem.py", "start.bat", "check_files.bat", "report_problem.bat")
KNOWN = set(CODE_FILES) | set(DATA_JSON) | {
    "questions.xlsx", "questions.csv", "students.xlsx", "students.csv", "settings.txt", "exam_data.zip", "codes.json", "submissions.jsonl",
    "results.csv", "alive.txt", "exam_log.txt", "exam_error.txt", "exam_info.txt", "check_report.txt", "questions_template.xlsx",
    "students_template.xlsx", "00_دليل_المشرف.pdf", "01_تعليمات_Claude.pdf", "02_قائمة_فحص_قبل_الامتحان.pdf", "03_ورقة_الأستاذ.pdf",
    "students_from_zip.xlsx", "students_from_zip.csv", "settings_from_zip.txt"}

FOR_ASSISTANT = """=== FOR THE ASSISTANT (e.g. Claude) - please read this first ===
You are helping a school teacher (Arabic speaker, NOT technical) with an OFFLINE exam system that runs on the school Wi-Fi:
- server.py (Python standard library) runs on the teacher's Windows laptop via start.bat (black console window).
  Students open http://<laptop-ip> on their phones (page = template.html). Teacher pages open ONLY on the laptop:
  http://localhost/monitor, /health, /report, /sheet, /key, /codes, /teacher, /link.
- Data files in the exam folder:
  submissions.jsonl = SOURCE OF TRUTH for submitted exams (one JSON per line; results.csv is regenerated from it);
  papers.json = each started student's questions + start time + extra time; claims.json = student -> device;
  answers.json = answers autosaved every ~3 s during the exam; state.json = exam closed / teacher message / downtime compensation;
  alive.txt = server heartbeat every 3 s (its age shows whether the server is running); codes.json = student entry codes;
  exam_log.txt = Arabic event log; exam_error.txt = why the exam files failed to load (if any); check_report.txt = output of check_files.bat.
- Restarting start.bat from the SAME folder restores everything (papers, answers, submissions); time lost while the server was down
  (or while the laptop slept) is compensated automatically up to 30 minutes.
- Monitor actions: "نقل لجهاز آخر" (move to another device: keeps answers and remaining time), "تسليم عنه" (submit for the student
  using the answers saved on the server), "فك الحجز" (release: ERASES the student's answers - avoid during an exam),
  "إنهاء الامتحان للجميع" (close the exam), "تسليم من لم يسلّم" (submit for everyone who started), "⏱" (extend time).
- In this report the teacher password and the student entry codes are hidden on purpose.
How to help: reply in simple Arabic, step by step. Prefer actions in the monitor page or restarting start.bat over editing files.
Never ask the teacher to edit server.py or template.html during an exam. If data might be at risk, first tell them to copy
the whole exam folder as a backup. Point out anything unusual you see below (two servers running, port 8000 instead of 80,
a stale alive.txt, invalid JSON, a torn last line in submissions.jsonl, results.csv locked by Excel, folder inside OneDrive...).
"""


def p(name): return os.path.join(HERE, name)
def when(t): return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))
def ago(t):
    s = int(NOW - t)
    return f"قبل {s} ث" if s < 120 else f"قبل {s // 60} د" if s < 7200 else f"قبل {s // 3600} س"


def read_text(path):
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"): return raw.decode("utf-16", "replace"), "utf-16"
    try: return raw.decode("utf-8-sig"), ("utf-8 (BOM)" if raw[:3] == b"\xef\xbb\xbf" else "utf-8")
    except UnicodeDecodeError: return raw.decode("cp1256", "replace"), "cp1256"


def clip(t, limit=MAX_CHARS):
    return t if len(t) <= limit else t[:limit] + f"\n... (قُصّ: الملف أطول من {limit} حرف)"


def masked_settings(text):
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s and s.split("=", 1)[0].strip().replace(" ", "_") == "كلمة_سر_المعلم":
            v = s.split("=", 1)[1].strip()
            line = "كلمة_سر_المعلم = " + ("(فاضية: ما في كلمة سر)" if not v else "1234 (الافتراضية)" if v == "1234" else f"*** (مخفية، {len(v)} حرف)")
        out.append(line)
    return "\n".join(out)


def run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)
        enc = "oem" if os.name == "nt" else "utf-8"
        return (r.stdout + r.stderr).decode(enc, "replace").strip()
    except Exception as e:
        return f"(تعذّر: {e!r})"


def section(title):
    return "\n\n" + "=" * 78 + "\n" + title + "\n" + "=" * 78 + "\n"


def safe(fn):
    try: return fn()
    except Exception as e: return f"(تعذّر جمع هذا القسم: {e!r})"


# ---------------- الأقسام ----------------
def basics():
    lines = [f"وقت التقرير: {when(NOW)}", f"مجلد الامتحان: {HERE}", f"طول المسار: {len(HERE)} حرف"]
    low = HERE.lower()
    od = [os.environ.get(v) for v in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")]
    named = any(x == "onedrive" or x.startswith("onedrive - ") for x in low.split(os.sep))
    lines.append("داخل OneDrive: " + ("نعم ⚠ (المزامنة ممكن تمسك الملفات لحظات)" if any(r and (low + os.sep).startswith(r.lower().rstrip(os.sep) + os.sep) for r in od) or named else "لا"))
    lines.append(f"النظام: {platform.platform()}")
    lines.append(f"بايثون: {sys.version.split()[0]}  ({sys.executable})")
    try:
        m = re.search(r'^VERSION\s*=\s*"([^"]*)"', read_text(p("server.py"))[0], re.M)
        lines.append("إصدار الحزمة (من server.py): " + (m.group(1) if m else "غير مكتوب (نسخة أقدم من v06)"))
    except OSError: lines.append("إصدار الحزمة: server.py مش موجود!")
    try:
        u = shutil.disk_usage(HERE); lines.append(f"المساحة الفاضية على القرص: {u.free // 2**20} MB")
    except OSError as e: lines.append(f"المساحة: تعذّر ({e})")
    try:
        t = float(open(p("alive.txt"), encoding="utf-8").read().strip())
        st = "السيرفر شغّال الآن على الأغلب" if NOW - t < 15 else "السيرفر واقف (أو نام الجهاز)"
        lines.append(f"آخر نبضة للسيرفر (alive.txt): {when(t)} — {ago(t)} → {st}")
    except (OSError, ValueError): lines.append("آخر نبضة للسيرفر: ما في alive.txt (السيرفر ما اشتغل من هذا المجلد بنسخة حديثة)")
    return "\n".join(lines)


def server_now():
    ports = []
    for x in (os.environ.get("EXAM_PORT"), "80", "8000"):
        if x and x.isdigit() and int(x) not in ports: ports.append(int(x))
    out = []
    for port in ports:
        base = f"http://127.0.0.1:{port}"
        try:
            ok = urllib.request.urlopen(base + "/ok", timeout=3).read().decode("utf-8", "replace").strip()
        except Exception as e:
            out.append(f"المنفذ {port}: ما في سيرفر بيرد ({type(e).__name__})"); continue
        out.append(f"المنفذ {port}: السيرفر بيرد (/ok → {ok})")
        try:
            h = json.loads(urllib.request.urlopen(base + "/health.json", timeout=5).read().decode("utf-8"))
            out.append(json.dumps(h, ensure_ascii=False, indent=1))
        except Exception as e:
            out.append(f"  /health.json تعذّر ({e!r}) — نسخة قديمة من السيرفر أو مش من جهاز السيرفر")
    if sum(1 for x in out if "السيرفر بيرد" in x) > 1: out.insert(0, "⚠ في أكثر من سيرفر شغّال على هذا الجهاز (غالباً نافذة سوداء قديمة لسا مفتوحة)")
    return "\n".join(out)


def processes():
    if os.name != "nt": return "(مش ويندوز)"
    out = ["المنافذ اللي في حدا بيسمع عليها (80 و8000):"]
    net = run(["netstat", "-ano", "-p", "tcp"])
    pids = set()
    for line in net.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3].upper() == "LISTENING" and re.search(r":(80|8000)$", parts[1]):
            out.append("  " + " ".join(parts)); pids.add(parts[4])
    if len(out) == 1: out.append("  (ولا واحد)")
    for pid in sorted(pids):
        out.append(f"  PID {pid}: " + run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"]))
    out.append("\nعمليات بايثون الشغّالة:")
    out.append(run(["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV", "/NH"]) + "\n" + run(["tasklist", "/FI", "IMAGENAME eq py.exe", "/FO", "CSV", "/NH"]))
    return "\n".join(out)


def network():
    out = [f"اسم الجهاز: {socket.gethostname()}"]
    try: out.append("عناوين IPv4: " + ", ".join(sorted({a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)})))
    except OSError as e: out.append(f"عناوين: تعذّر ({e})")
    if os.name == "nt": out.append(run(["ipconfig"]))
    return "\n".join(out)


def files_check():
    rows = []
    def add(name, note): rows.append(f"{name:<34} {note}")
    for name in ("settings.txt", "questions.xlsx", "questions.csv", "students.xlsx", "students.csv", "exam_data.zip"):
        f = p(name)
        if not os.path.exists(f): add(name, "مش موجود"); continue
        st = os.stat(f); note = f"{st.st_size} بايت، آخر تعديل {when(st.st_mtime)}"
        if name.endswith(".xlsx") or name.endswith(".zip"): note += "، ملف Excel/zip سليم" if zipfile.is_zipfile(f) else "، ⚠ مش ملف xlsx/zip سليم (تالف؟ أو .xls قديم باسم xlsx؟)"
        if name == "settings.txt": note += f"، ترميز {read_text(f)[1]}"
        add(name, note)
    imgs = p("images")
    if os.path.isdir(imgs):
        fs = [x for x in os.listdir(imgs) if os.path.isfile(os.path.join(imgs, x))]
        add("images/", f"{len(fs)} ملف، {sum(os.path.getsize(os.path.join(imgs, x)) for x in fs) // 1024} KB")
    else: add("images/", "مش موجود")
    for name in DATA_JSON + ("codes.json",):
        f = p(name)
        if not os.path.exists(f): add(name, "مش موجود"); continue
        st = os.stat(f); note = f"{st.st_size} بايت، {ago(st.st_mtime)}"
        try:
            d = json.load(open(f, encoding="utf-8")); note += f"، JSON سليم ({len(d)} عنصر)" if isinstance(d, (dict, list)) else "، JSON سليم"
            if name == "state.json" and isinstance(d, dict):
                note += f"، الامتحان {'منتهٍ منذ ' + when(d['closed_at']) if d.get('closed_at') else 'مفتوح'}" + (f"، تعويض: {d['comp']}" if d.get("comp") else "")
                if d.get("auto_title"): note += f"، عنوان تلقائي: {d['auto_title']}"
                if d.get("bank_changed"): note += "، ⚠ ملف الأسئلة تغيّر وفي بيانات امتحان سابق (ما انضغط «بداية امتحان جديد»؟)"
        except Exception as e: note += f"، ⚠ JSON تالف: {e}"
        add(name, note)
    f = p("submissions.jsonl")
    if os.path.exists(f):
        st = os.stat(f); good, bad, active, dup, reopens = 0, [], set(), 0, 0
        for i, line in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
            if not line.strip(): continue
            try: r = json.loads(line); k = r["key"]
            except Exception: bad.append(i); continue
            if r.get("reopen"): reopens += 1; active.discard(k); continue              # المعلم أعاد فتح الطالب: تسليمه السابق ما بيعدّ، وتسليمه الجديد مش «مكرر»
            good += 1; dup += k in active; active.add(k)
        add("submissions.jsonl", f"{st.st_size} بايت، {ago(st.st_mtime)}، {good} تسليم سليم" + (f"، {reopens} إعادة فتح" if reopens else "") + (f"، ⚠ أسطر تالفة: {bad[:20]}" if bad else "") + (f"، ⚠ مكرر: {dup}" if dup else ""))
    else: add("submissions.jsonl", "مش موجود (ما في ولا تسليم بعد)")
    f = p("results.csv")
    if os.path.exists(f):
        st = os.stat(f); note = f"{st.st_size} بايت، {ago(st.st_mtime)}"
        try:
            with open(f, "r+b"): pass                     # فتح للقراءة/الكتابة بدون ما نكتب: بيكشف إذا Excel ماسكه
        except PermissionError: note += "، ⚠ مفتوح ببرنامج ثاني (Excel؟) — عادي، التسليمات محفوظة بـ submissions.jsonl"
        except OSError as e: note += f"، ({e})"
        add("results.csv", note)
    for name in ("exam_log.txt", "exam_error.txt", "exam_info.txt", "check_report.txt"):
        f = p(name); add(name, f"{os.path.getsize(f)} بايت، {ago(os.path.getmtime(f))}" if os.path.exists(f) else "مش موجود")
    rows.append("\nملفات الكود:")
    for name in CODE_FILES:
        f = p(name)
        if not os.path.exists(f): add(name, "مش موجود" + (" ⚠" if name in ("server.py", "template.html", "start.bat") else "")); continue
        b = open(f, "rb").read(); add(name, f"{len(b)} بايت، sha256 {hashlib.sha256(b).hexdigest()[:12]}، آخر تعديل {when(os.path.getmtime(f))}")
    arch = sorted(x for x in os.listdir(HERE) if x.startswith("archive_") and os.path.isdir(p(x)))
    rows.append("\nمجلدات أرشيف (امتحانات سابقة): " + (", ".join(arch) if arch else "ولا واحد"))
    extra = sorted(x for x in os.listdir(HERE) if os.path.isfile(p(x)) and x not in KNOWN and not x.startswith("problem_report_") and not x.endswith(".tmp"))
    rows.append("ملفات ثانية بالمجلد: " + (", ".join(extra) if extra else "ولا واحد"))
    tmps = sorted(x for x in os.listdir(HERE) if x.endswith(".tmp"))
    if tmps: rows.append("ملفات .tmp (حفظ ما كمل؟): " + ", ".join(tmps))
    return "\n".join(rows)


def file_dump(name, tail=None, transform=None):
    f = p(name)
    if not os.path.exists(f): return "(مش موجود)"
    t, enc = read_text(f)
    if transform: t = transform(t)
    if tail:
        lines = t.splitlines()
        if len(lines) > tail: t = f"(آخر {tail} سطر من أصل {len(lines)})\n" + "\n".join(lines[-tail:])
    return clip(t)


def build_report():
    head = ("تقرير معلومات مشكلة — نظام الامتحان\n"
            "=====================================\n"
            "شو تعمل هلّق:\n"
            "1) اكتب تحت «وصف المشكلة» شو صار بالضبط ومتى (مثلاً: الساعة 10:20 طالبين ما قدروا يسلّموا وطلعتلهم رسالة ...).\n"
            "2) احفظ الملف (Ctrl+S).\n"
            "3) افتح محادثة مع Claude وارفع هذا الملف، واكتب:\n"
            "   «هذا تقرير مشكلة من نظام الامتحان. اشرحلي السبب وشو أعمل خطوة بخطوة، بدون ما تعدّل الكود.»\n"
            "ملاحظة: كلمة سر المعلم ورموز دخول الطلاب مخفية بهذا التقرير، بس فيه أسماء طلاب من سجل الامتحان: لا تنشره بمكان عام.\n\n"
            "وصف المشكلة (اكتب هون):\n\n\n\n")
    parts = [head, FOR_ASSISTANT,
             section("1) معلومات أساسية"), safe(basics),
             section("2) السيرفر الآن (من /health.json)"), safe(server_now),
             section("3) المنافذ وعمليات بايثون"), safe(processes),
             section("4) الشبكة"), safe(network),
             section("5) سلامة ملفات الامتحان"), safe(files_check),
             section("6) settings.txt (كلمة السر مخفية)"), safe(lambda: file_dump("settings.txt", transform=masked_settings)),
             section("7) exam_error.txt (سبب رفض ملفات الامتحان، إن وُجد)"), safe(lambda: file_dump("exam_error.txt")),
             section("8) check_report.txt (آخر فحص للملفات)"), safe(lambda: file_dump("check_report.txt")),
             section("9) exam_info.txt (معلومات آخر تشغيل)"), safe(lambda: file_dump("exam_info.txt")),
             section("10) exam_log.txt (سجل الامتحان)"), safe(lambda: file_dump("exam_log.txt", tail=LOG_TAIL)),
             section("11) start.bat"), safe(lambda: file_dump("start.bat")),
             "\n\n(نهاية التقرير)\n"]
    return "".join(parts)


def _real_console():
    if os.name != "nt": return False
    try:
        import ctypes
        k = ctypes.windll.kernel32
        return bool(k.GetConsoleMode(k.GetStdHandle(-11), ctypes.byref(ctypes.c_uint32())))
    except Exception:
        return False


def main():
    print("Collecting problem information... (this only reads files, it changes nothing)")
    text = build_report()
    out = p("problem_report_" + time.strftime("%Y%m%d_%H%M%S") + ".txt")
    with open(out, "w", encoding="utf-8-sig", newline="\r\n") as f: f.write(text)
    print("\n  Saved: " + os.path.basename(out))
    print("  Next: write what happened at the top of the file, save it, and send the file to Claude (or whoever helps you).\n")
    if _real_console():
        try: os.startfile(out)
        except OSError: pass
        try: subprocess.Popen(["explorer", "/select,", out])
        except OSError: pass
    return out


if __name__ == "__main__":
    main()
