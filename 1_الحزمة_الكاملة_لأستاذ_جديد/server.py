# سيرفر الامتحان المحلي — يشتغل على جهاز المعلم (بايثون فقط، بدون تثبيت مكتبات)
# التشغيل:  python server.py     ثم يظهر الرابط اللي بتعطيه للطلاب
# صفحات المعلم (من نفس جهاز السيرفر فقط):
#    http://localhost/monitor   مراقبة حية + فك حجز + بدء امتحان جديد
#    http://localhost/sheet     ورقة كل طالب (أسئلته وإجاباته) + طباعة
#    http://localhost/key       مفتاح الإجابات (للمعلم فقط)
#    http://localhost/report    تقرير العلامات وتحليل الأسئلة + تنزيل Excel
# الملفات المطلوبة جنب هالملف: template.html ، settings.txt ، questions.xlsx ، students.xlsx
import sys, http.server, json, csv, os, socket, threading, time, urllib.parse, html, zipfile, io, shutil, random, hmac, secrets, hashlib
from collections import Counter, defaultdict
VERSION = "v06 — 2026-10-15"                      # بيظهر بصفحة الفحص وبتقرير المشكلة (report_problem.bat)
for _s in (sys.stdout, sys.stderr):                 # ترميز UTF-8 دائماً (حتى لو المخرجات محوّلة لملف أو أداة)، عشان طباعة العربي ما تنهار
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
BASE = os.path.dirname(os.path.abspath(__file__))
# نافذة ويندوز السوداء ما بتعرض الحروف العربية (بتطلع مربعات □□□): بهالحالة أي سطر فيه عربي بينكتب بملف exam_log.txt (UTF-8) بدل الشاشة،
# والمعلومات المهمة (الرابط، صفحات المعلم، التحذيرات) بتنكتب بـ exam_info.txt وبتنفتح لحالها بالمفكرة. EXAM_NO_ARABIC_CONSOLE=1 بيفرض هالوضع (للاختبار)
def _real_console():
    """True بس لو الإخراج نافذة كونسول حقيقية على ويندوز. (isatty() بترجع True كمان لـ NUL، فكان يفتح المفكرة لما يتشغّل السيرفر بإخراج مخفي)"""
    if os.name != "nt": return False
    try:
        import ctypes
        k = ctypes.windll.kernel32
        return bool(k.GetConsoleMode(k.GetStdHandle(-11), ctypes.byref(ctypes.c_uint32())))
    except Exception:
        return False
REAL_CONSOLE = _real_console()
CONSOLE_NO_ARABIC = REAL_CONSOLE or os.environ.get("EXAM_NO_ARABIC_CONSOLE") == "1"
LOG_FILE = os.path.join(BASE, "exam_log.txt")
INFO_FILE = os.path.join(BASE, "exam_info.txt")
if CONSOLE_NO_ARABIC:
    import re as _re_log
    _real_print = print
    def print(*args, **kw):
        text = kw.get("sep", " ").join(str(a) for a in args)
        if kw.get("file") is None and _re_log.search("[\u0600-\u06FF]", text):
            stamp = time.strftime("%H:%M:%S")
            try:
                new = not os.path.exists(LOG_FILE)
                with open(LOG_FILE, "a", encoding="utf-8-sig" if new else "utf-8") as _f:
                    for _ln in text.strip("\n").split("\n"): _f.write(f"{stamp}  {_ln}\n")
            except OSError: pass
            if text.lstrip().startswith(("تنبيه", "خطأ")): _real_print(f"  [!] {stamp} A warning/error was logged in Arabic: see exam_log.txt")
            elif "  /  " in text:                                          # سطر ثنائي اللغة «English  /  عربي»: الجزء الإنجليزي بيظهر على الشاشة
                left = text.split("  /  ")[0].rstrip()
                if len(left.strip()) >= 8 and not _re_log.search("[\u0600-\u06FF]", left): _real_print(left)
            return
        _real_print(*args, **kw)
LOCK_FILE = os.path.join(BASE, "server.lock")
_LOCK_FH = None
LOCK_AT = 1 << 30                                   # مكان القفل: بعد نهاية الملف بكتير (ما حدا بيقرا هالمنطقة)
def take_folder_lock(wait=3.0):
    """سيرفر واحد بس لكل مجلد امتحان: ملف server.lock بنمسكه بقفل حصري طول ما العملية شغّالة. سيرفران على نفس المجلد بيكتبوا على نفس ملفات النتائج والحالة فبيخرّبوها؛ وكنا نعتمد على المشرف إنه ما يضغط start.bat مرتين.
    نظام التشغيل بيفك القفل لحاله لو العملية وقفت أو انقتلت (فما بيضل قفل عالق، وإعادة التشغيل الفورية بتزبط؛ بنعيد المحاولة 3 ثواني لأن العملية اللي قبلها ممكن تكون لسا بتسكّر)، وملف قفل قديم متروك ما بيمنع شي.
    القفل على بايت بعيد جداً (بعد نهاية الملف) مش على محتواه: على ويندوز القفل بيمنع القراءة، فلو قفلنا أول بايت كان نسخ المجلد والسيرفر شغّال (اللي بيعمله المشرف لامتحان ثاني) بيفشل عند هالملف. محتوى الملف هو رقم العملية (PID) لرسالة الرفض. بترجّع False لو في سيرفر ثاني ماسك المجلد"""
    global _LOCK_FH
    fh = open(LOCK_FILE, "a+b"); end = time.time() + wait
    while True:
        try:
            fh.seek(LOCK_AT)
            if os.name == "nt":
                import msvcrt; msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl; fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() >= end: fh.close(); return False
            time.sleep(0.1)
    _LOCK_FH = fh
    try: fh.truncate(0); fh.write(str(os.getpid()).encode("ascii")); fh.flush()
    except OSError: pass
    return True
if __name__ == "__main__" and not take_folder_lock():
    try:
        with open(LOCK_FILE, "rb") as _f: _pid = _f.read().decode("ascii", "replace").strip()
    except OSError: _pid = ""
    _who = f", PID {_pid}" if _pid.isdigit() else ""
    print("=" * 60); print(f"  ALREADY RUNNING: this exam folder already has a server running (another black window{_who}).")
    print("  Do not start it twice: two servers writing the same files would corrupt the results.")
    print("  - Use the first window (its student link is still valid), or close it first and then start again.")
    print("  - For a second exam at the same time, copy the whole folder and start the copy."); print("=" * 60)
    if not CONSOLE_NO_ARABIC: print(f"  هذا المجلد شغّال أصلاً من نافذة سوداء ثانية{_who}. لا تشغّله مرتين: استعمل النافذة الأولى (رابط الطلاب نفسه)، أو سكّرها أولاً. لامتحان ثاني بنفس الوقت انسخ المجلد كاملاً وشغّل النسخة.")
    sys.exit(1)
OUT = os.path.join(BASE, "results.csv")            # يُولَّد من submissions.jsonl (المصدر الأساسي) — آمن لو كان مفتوحاً بـ Excel
SUBS_FILE = os.path.join(BASE, "submissions.jsonl")
CLAIMS_FILE = os.path.join(BASE, "claims.json")
PAPERS_FILE = os.path.join(BASE, "papers.json")    # ورقة كل طالب (الأسئلة وترتيب الخيارات ووقت البدء) — يحددها السيرفر
STATE_FILE = os.path.join(BASE, "state.json")      # حالة الامتحان: إنهاء من المعلم + آخر رسالة للطلاب
ANS_FILE = os.path.join(BASE, "answers.json")      # إجابات الطلاب أثناء الامتحان (نسخة احتياطية على السيرفر)
CODES_FILE = os.path.join(BASE, "codes.json")     # رموز دخول الطلاب المولَّدة (تبقى بين الامتحانات؛ امسح الملف لتوليد رموز جديدة)
LOCK = threading.Lock()
MAX_BODY = 1_000_000                                # أكبر جسم طلب مقبول (بايت): الطلبات الحقيقية أقل من 10KB
GRACE = 30                                          # ثواني سماح بعد انتهاء الوقت قبل ما نعلّم التسليم "متأخر"
L = "أبجدهوزحطي"
LVL = {"hard": "صعب", "medium": "وسط", "easy": "سهل"}
HEAD = ["الاختبار","الصف","الشعبة","الاسم","العلامة","من","الأسئلة الخاطئة وإجابة الطالب","نوع التسليم","الوقت","الخروج من الصفحة","التأخير (ث)","مدة الحل"]

def mtxt(m):
    """علامة السؤال بصياغة عربية سليمة: علامة واحدة / علامتان / 3 علامات / 2.5 علامة"""
    return "علامة واحدة" if m == 1 else "علامتان" if m == 2 else f"{m} علامات" if isinstance(m, int) and 3 <= m <= 10 else f"{m} علامة"
E = lambda s: html.escape(s, quote=False)              # تهريب نص السؤال قبل ما ينحط بصفحة HTML
def num(x):
    """رقم نظيف للعلامات: 3.0 -> 3 ، و2.5000001 -> 2.5"""
    x = round(float(x), 2)
    return int(x) if x == int(x) else x
def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except Exception: return default
def atomic_write(path, text, tries=10):
    """كتابة ذرية: ملف مؤقت ثم استبدال — انقطاع الكهرباء ما بيخرّب الملف.
    على ويندوز برنامج ثاني (مضاد فيروسات، مزامنة OneDrive، الفهرسة) ممكن يمسك الملف لحظة فيفشل الاستبدال: بنعيد المحاولة (لحد ~نص ثانية)"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text); f.flush(); os.fsync(f.fileno())
    for i in range(tries):
        try: os.replace(tmp, path); return
        except PermissionError:
            if i == tries - 1: raise
            time.sleep(0.05)

# ---------- قراءة ملفات المعلم: settings.txt + questions.xlsx/csv + students.xlsx/csv ----------
import re, xml.etree.ElementTree as ET
class DataError(Exception): pass
def find_file(stem):
    for ext in (".xlsx", ".csv"):
        p = os.path.join(BASE, stem + ext)
        if os.path.exists(p): return p
    raise DataError(f"ملف {stem}.xlsx (أو {stem}.csv) غير موجود جنب server.py\n(File {stem}.xlsx or {stem}.csv not found next to server.py)")
def _fmt_kind(fid, code):
    """نوع تنسيق خلية الأرقام بإكسل: تاريخ أو نسبة (غير هيك = رقم عادي)"""
    if fid == 9: return ("pct", 0)
    if fid == 10: return ("pct", 2)
    if fid in _BUILTIN_DATE_FMT: return ("date", fid in (18, 19, 20, 21, 22, 45, 46, 47))
    if not code: return None
    c = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", code).lower()
    if "%" in c:
        m = re.search(r"\.([0#?]+)", c)
        return ("pct", len(m.group(1)) if m else 0)
    if re.search(r"[ymdhs]", c) and "general" not in c:
        return ("date", bool(re.search(r"[hs]", c)))
    return None
_BUILTIN_DATE_FMT = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))
def _xl_date(v, d1904, has_time):
    """الرقم التسلسلي لتاريخ إكسل -> نص (2026-01-02) أو (14:30) للوقت فقط"""
    import datetime
    f = float(v)
    dt = (datetime.datetime(1904, 1, 1) if d1904 else datetime.datetime(1899, 12, 30)) + datetime.timedelta(seconds=round(f * 86400))      # تقريب للثانية: 14:30 بإكسل بيتخزن 0.6041666666666666
    if has_time and 0 <= f < 1: return dt.strftime("%H:%M")
    s = "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)
    return s + dt.strftime(" %H:%M") if (has_time and f != int(f)) else s       # الوقت بس لو في كسر يوم (منتصف الليل بالضبط = تاريخ فقط)
def _pct_text(v, dec):
    x = round(float(v) * 100, dec)
    return (("%.*f" % (dec, x)) if dec else str(int(round(x)))) + "%"
def read_table(path, want=()):
    """يرجع قائمة صفوف (كل صف قائمة نصوص). xlsx بدون مكتبات، أو csv.
    want: كلمات بترويسة الجدول المطلوب (مثلاً «السؤال»): لو الملف فيه أكثر من ورقة بنختار الورقة اللي ترويستها فيها واحدة منها، وإلا أول ورقة ظاهرة"""
    if path.lower().endswith(".csv"):
        raw = open(path, "rb").read()
        try: txt = raw.decode("utf-8-sig")
        except UnicodeDecodeError: txt = raw.decode("cp1256")
        txt = txt.replace("\r\n", "\n").replace("\r", "\n")                 # «CSV (Macintosh)» أسطره CR فقط
        try: dia = csv.Sniffer().sniff(txt[:2000], delimiters=",;\t")
        except Exception: dia = csv.excel
        return [[c.strip() for c in r] for r in csv.reader(io.StringIO(txt), dia)]
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    M = "{%s}" % ns["m"]
    z = zipfile.ZipFile(path)
    names = z.namelist()
    sst = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            sst.append("".join(t.text or "" for t in si.iter(M + "t")))
    xf_kind = []                                                            # تنسيق كل خلية: تاريخ/نسبة (عشان ما يشوف الطالب الرقم التسلسلي 17534 أو 0.25 بدل 25%)
    if "xl/styles.xml" in names:
        st = ET.fromstring(z.read("xl/styles.xml"))
        custom = {int(n.attrib["numFmtId"]): n.attrib.get("formatCode", "") for n in st.iter(M + "numFmt")}
        cx = st.find("m:cellXfs", ns)
        for xf in (list(cx) if cx is not None else []):
            fid = int(xf.attrib.get("numFmtId", 0)); xf_kind.append(_fmt_kind(fid, custom.get(fid)))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    pr = wb.find("m:workbookPr", ns)
    d1904 = pr is not None and pr.attrib.get("date1904") in ("1", "true")
    rels = {r.attrib["Id"]: r.attrib["Target"] for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    sheets = []
    for sh in wb.find("m:sheets", ns):
        t = rels[sh.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]].lstrip("/")
        sheets.append((t if t.startswith("xl/") else "xl/" + t, sh.attrib.get("state", "visible")))

    def parse(target):
        rows = []
        for row in ET.fromstring(z.read(target)).iter(M + "row"):
            ri = int(row.attrib.get("r", len(rows) + 1))
            while len(rows) < ri - 1: rows.append([])                       # الصف الفاضي بالنص ما بينكتب بالملف: نحفظ مكانه عشان أرقام الأسطر بالرسائل تظل صح
            cells, last = {}, -1
            for c in row.findall("m:c", ns):
                if c.attrib.get("r"):
                    ci = 0
                    for ch in re.match(r"([A-Z]+)", c.attrib["r"]).group(1): ci = ci * 26 + ord(ch) - 64
                    ci -= 1
                else: ci = last + 1
                last = ci
                t = c.attrib.get("t")
                if t == "inlineStr": v = "".join(x.text or "" for x in c.iter(M + "t"))
                else:
                    ve = c.find("m:v", ns); v = ve.text if ve is not None and ve.text is not None else ""
                    if t == "s" and v != "": v = sst[int(v)]
                    elif t == "b": v = "TRUE" if v == "1" else "FALSE"      # كلمة TRUE/FALSE بإكسل بتتحوّل لقيمة منطقية: ما نعرضها للطالب «1» و«0»
                    elif t not in ("str", "e") and v:
                        try:
                            f = float(v); s_i = int(c.attrib.get("s", 0)); kind = xf_kind[s_i] if s_i < len(xf_kind) else None
                            if kind and kind[0] == "date": v = _xl_date(v, d1904, kind[1])
                            elif kind and kind[0] == "pct": v = _pct_text(v, kind[1])
                            elif f == int(f): v = str(int(f))
                            else:
                                g = "%.15g" % f; v = v if "e" in g else g   # 0.1+0.2 بإكسل = 0.30000000000000004: نعرضه 0.3 مثل إكسل
                        except (ValueError, OverflowError): pass
                cells[ci] = v.strip()
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
        return rows
    order = [s for s in sheets if s[1] == "visible"] + [s for s in sheets if s[1] != "visible"]
    if want:
        for target, _ in order:
            rows = parse(target)
            if rows and any(w in (c or "").strip().lower() for c in rows[0] for w in want): return rows
    return parse(order[0][0])

YES = {"نعم", "yes", "true", "1", "y", "نعم.", "ايوا", "أجل"}
NO = {"لا", "no", "false", "0", "n", "لا."}
def read_settings():
    cfg = {"title": "الامتحان الإلكتروني", "minutes": 30, "hard": 3, "medium": 6, "easy": 6, "count": 15,
           "shuffleQ": True, "shuffleO": True, "showScore": True, "lockdown": True, "review": "no", "needCode": False, "tpass": "", "qmark": None, "final": None, "comp": True}
    keys = {"عنوان_الامتحان": "title", "المدة_بالدقائق": "minutes", "عدد_الأسئلة_الصعبة": "hard", "عدد_الأسئلة_المتوسطة": "medium",
            "عدد_الأسئلة_السهلة": "easy", "عدد_الأسئلة_الكلي": "count", "خلط_الأسئلة": "shuffleQ", "خلط_الخيارات": "shuffleO",
            "إظهار_العلامة_للطالب": "showScore", "منع_النسخ": "lockdown", "مراجعة_الأخطاء": "review", "رمز_الدخول": "needCode", "كلمة_سر_المعلم": "tpass", "علامة_السؤال": "qmark", "العلامة_النهائية": "final", "تعويض_توقف_السيرفر": "comp"}
    REVIEW = {"لا": "no", "no": "no", "نعم": "now", "yes": "now", "بعد_الإنهاء": "after"}
    p = os.path.join(BASE, "settings.txt")
    cfg["given"] = set()                                 # الإعدادات اللي انكتبت فعلاً بالملف (الباقي افتراضي)
    if not os.path.exists(p):                            # الملف اختياري: مشرف المختبر بيعمله لما الأستاذ يطلب إعدادات خاصة
        cfg["missing"] = True; cfg["title"] = auto_title(); cfg["auto_title"] = True
        return cfg
    raw = open(p, "rb").read()
    if raw[:2] in (bytes([255, 254]), bytes([254, 255])): txt = raw.decode("utf-16")      # المفكرة بخيار «Unicode» بتحفظ UTF-16 (مع BOM)
    else:
        try: txt = raw.decode("utf-8-sig")
        except UnicodeDecodeError: txt = raw.decode("cp1256")
    for ln, line in enumerate(txt.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = [x.strip() for x in line.split("=", 1)]
        k = k.replace(" ", "_")
        if k not in keys: raise DataError(f"settings.txt سطر {ln}: الاسم «{k}» غير معروف")
        f = keys[k]
        if v == "" and f not in ("tpass", "qmark", "final"): continue     # قيمة فاضية = الافتراضي (العنوان تلقائي، العدد = كل الأسئلة...). كلمة السر الفاضية = بدون كلمة سر
        cfg["given"].add(f)
        if f in ("qmark", "final"):                      # علامة_السؤال / العلامة_النهائية: رقم موجب (يقبل كسور وأرقام عربية) أو فاضي = غير مفعّل
            vv = v.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫،,", "0123456789..."))
            if not vv: cfg[f] = None; continue
            try: cfg[f] = num(vv)
            except ValueError: raise DataError(f"settings.txt سطر {ln}: «{k}» لازم يكون رقم (مثلاً 1.5 أو 30)، لقيت «{v}»")
            if not 0 < cfg[f] <= 1000: raise DataError(f"settings.txt سطر {ln}: «{k}» لازم يكون أكبر من 0 وأقل من أو يساوي 1000، لقيت «{v}»")
            continue
        if f == "review":
            if v.lower().replace(" ", "_") not in REVIEW: raise DataError(f"settings.txt سطر {ln}: «{k}» لازم يكون لا أو نعم أو بعد_الإنهاء، لقيت «{v}»")
            cfg[f] = REVIEW[v.lower().replace(" ", "_")]
        elif isinstance(cfg[f], bool):
            if v.lower() not in YES | NO: raise DataError(f"settings.txt سطر {ln}: «{k}» لازم يكون نعم أو لا، لقيت «{v}»")
            cfg[f] = v.lower() in YES
        elif isinstance(cfg[f], int):
            try: cfg[f] = int(v)
            except ValueError: raise DataError(f"settings.txt سطر {ln}: «{k}» لازم يكون رقم")
        else: cfg[f] = v
    if "title" not in cfg["given"] or not cfg["title"].strip():
        cfg["title"] = auto_title(); cfg["auto_title"] = True
    return cfg
def auto_title():
    """ما في عنوان بـ settings.txt: عنوان تلقائي فريد لكل امتحان (عنوان ثابت لكل الامتحانات كان رح يخلّي جهاز امتحن عليه طالب
    يقول «تم التسليم مسبقاً» بالامتحان الجاي). ثابت لما ينعاد تشغيل السيرفر بنفس الامتحان: محفوظ بـ state.json، أو من مفاتيح الأوراق الموجودة"""
    t = load_json(STATE_FILE, {}).get("auto_title")
    if isinstance(t, str) and t.strip(): return t
    for f in (PAPERS_FILE, CLAIMS_FILE):
        ks = [k for k in load_json(f, {}) if isinstance(k, str) and k.count("|") >= 3]
        if ks: return Counter(k.rsplit("|", 3)[0] for k in ks).most_common(1)[0][0]
    return "امتحان " + time.strftime("%d-%m-%Y %H:%M")

LVL_IN = {"صعب": "hard", "صعبة": "hard", "hard": "hard", "وسط": "medium", "متوسط": "medium", "متوسطة": "medium", "medium": "medium",
          "سهل": "easy", "سهلة": "easy", "easy": "easy", "": ""}
LET_IN = {"أ": 0, "ا": 0, "إ": 0, "a": 0, "1": 0, "ب": 1, "b": 1, "2": 1, "ج": 2, "c": 2, "3": 2, "د": 3, "d": 3, "4": 3}
_MATH = r"[A-Za-z0-9Ͱ-Ͽ←-⋿°π√∞∑∫±×÷−=<>≤≥≠≈^_/|()\[\]{}\u2070-\u209F²³¹.,:;%+\-'’ ]"
_MATH_RUN = re.compile(r"(?:%s)+" % _MATH)
def autoltr(t):
    """يلف المقاطع الرياضية/اللاتينية بعزل LTR عشان ما تنعكس داخل الجملة العربية"""
    if "⁦" in t: return t
    def fix(m):
        s = m.group(0); core = s.strip(" .,:;")
        if not re.search(r"[A-Za-z0-9Ͱ-Ͽ°π√∞]", core): return s
        lead = s[:len(s) - len(s.lstrip(" .,:;"))]; tail = s[len(lead) + len(core):]
        return lead + "⁦" + core + "⁩" + tail
    return _MATH_RUN.sub(fix, t)

IMG_DIR = os.path.join(BASE, "images")
IMG_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}
IMG_LIST = []                                 # أسماء الصور المستعملة بالأسئلة (كل صورة = رمز واحد بنص السؤال، من المنطقة الخاصة بيونيكود)
_IMG_TOKEN = re.compile(r"\[\s*(?:img|IMG|Img|صورة)\s*[:：]\s*([^\]\n]+?)\s*\]")
_PUA = "[-]"
def with_imgs(text, errs, i):
    """[img:اسم.png] داخل نص السؤال/الخيار -> رمز خاص بيتحوّل لصورة وقت العرض (imgify). بنتأكد إن الملف موجود بمجلد images"""
    def one(m):
        name = m.group(1).strip()
        if name != os.path.basename(name.replace("\\", "/")) or not name:
            errs.append(f"questions سطر {i}: اسم الصورة «{name}» لازم يكون اسم ملف بدون مجلدات"); return ""
        if os.path.splitext(name)[1].lower() not in IMG_EXT:
            errs.append(f"questions سطر {i}: الصورة «{name}» صيغتها غير مدعومة (المدعوم: png, jpg, gif, webp, svg)"); return ""
        if not os.path.isfile(os.path.join(IMG_DIR, name)):
            errs.append(f"questions سطر {i}: الصورة «{name}» غير موجودة بمجلد images"); return ""
        if name not in IMG_LIST: IMG_LIST.append(name)
        return chr(0xE100 + IMG_LIST.index(name))
    return _IMG_TOKEN.sub(one, text)
def imgify(text):
    return re.sub(_PUA, lambda m: '<img class="qimg" src="/img/%s" alt="" draggable="false">' % urllib.parse.quote(IMG_LIST[ord(m.group()) - 0xE100]), text)
def noimg(text):
    return re.sub(_PUA, "[صورة]", text)

# ---------- الكسور: (x + 7)/(x² − 1) و 5π/6 و −3/4 بتنعرض بسط فوق خط فوق مقام ----------
_SUPS = "²³¹" + "".join(map(chr, range(0x2070, 0x20A0)))       # أُسس ودلائل مرفوعة/منخفضة بتلحق آخر الحد: x² و (x − 1)²
_STOP = "\n\u2066\u2067\u2068\u2069"                                     # القوس ما بيعبر سطر جديد ولا علامة عزل اتجاه
def _wc(s, i):
    """حرف من «كلمة» رياضية: أرقام وحروف لاتينية ويونانية و√ و∞، والنقطة العشرية بين رقمين (7.5)"""
    c = s[i]
    if (c.isascii() and c.isalnum()) or "Ͱ" <= c <= "Ͽ" or c in "√∞": return True
    return c == "." and 0 < i < len(s) - 1 and s[i - 1] in "0123456789" and s[i + 1] in "0123456789"
def _pair(s, i, step):
    """مكان القوس المقابل للقوس اللي عند i (step=1 لـ «(» و -1 لـ «)»)، أو -1"""
    d, k = 0, i
    while 0 <= k < len(s):
        if s[k] in _STOP: return -1
        d += (s[k] == "(") - (s[k] == ")")
        if d == 0: return k
        k += step
    return -1
def _frac_at(s, j):
    """الحدّين حوالين «/» اللي عند j: (بداية البسط، نهاية المقام، البسط، المقام) أو None لو مش كسر"""
    a = j
    while a > 0 and s[a - 1] == " ": a -= 1
    e = a
    while a > 0 and s[a - 1] in _SUPS: a -= 1
    if a > 0 and s[a - 1] == ")":
        a = _pair(s, a - 1, -1)
        if a < 0: return None
    while a > 0 and _wc(s, a - 1): a -= 1
    b = j + 1
    while b < len(s) and s[b] == " ": b += 1
    st = b
    while b < len(s) and _wc(s, b): b += 1
    if b < len(s) and s[b] == "(" and (b == st or re.search("[A-Za-zͰ-Ͽ]", s[st:b])):   # 1/(x+1) و 1/sin(x)، بس 2/3(x+1) = ثلثين ضرب القوس
        c = _pair(s, b, 1)
        if c > 0: b = c + 1
    while b < len(s) and s[b] in _SUPS: b += 1
    num, den = s[a:e], s[st:b]
    if not num.strip(_SUPS) or not den.strip(_SUPS): return None
    if (a > 0 and s[a - 1] == "/") or (b < len(s) and s[b] == "/"): return None       # تاريخ 15/10/2026 أو a/b/c: بيضل زي ما هو
    if num.isascii() and den.isascii() and num.isalpha() and den.isalpha() and (len(num) > 1 or len(den) > 1 or (num in "mshgl" and den in "mshgl")):
        return None                                                                       # وحدات: cm/s و in/s و km/h و m/s
    return a, b, num, den
def _unwrap(t):
    return t[1:-1] if t[:1] == "(" and _pair(t, 0, 1) == len(t) - 1 else t                    # (x + 7) فوق الخط بتصير x + 7
def fracs(s):
    """نص السؤال -> HTML (مهرّب) والكسور فيه عناصر x-fr. عناصر خاصة مش span، لأن تنسيق الخيارات بالقالب بيغيّر كل span جوّاتها"""
    d, cands = 0, []
    for k, c in enumerate(s):
        if c == "(": d += 1
        elif c == ")": d = max(0, d - 1)
        elif c == "/": cands.append((d, k))
    done = []
    for _, j in sorted(cands):                       # الأقل عمقاً أول: (1/x)/2 هو كسر بسطه 1/x، والكسر الداخلي بيترسم جوّا البسط
        if any(a <= j < b for a, b, *_ in done): continue
        m = _frac_at(s, j)
        if m and not any(m[0] < b and a < m[1] for a, b, *_ in done): done.append(m)
    out, last = [], 0
    for a, b, num, den in sorted(done):
        out += [E(s[last:a]), "<x-fr><x-n>", fracs(_unwrap(num)), "</x-n><x-d>", fracs(_unwrap(den)), "</x-d></x-fr>"]
        last = b
    return "".join(out) + E(s[last:])
_ISO = re.compile("⁦([^⁦-⁩]*)⁩")
_MATH_OPS = ("<x-fr>", "=", "+", "−", "×", "÷", "±", "≤", "≥", "≠", "≈", "|", "∪", "∩", "&lt;", "&gt;")
def qhtml(text):
    """نص سؤال أو خيار زي ما بينعرض بأي صفحة: مهرّب، والكسور مرسومة، والصور.
    المعادلة جوّا جملة عربية بتنعرض كتلة وحدة من اليسار لليمين (x-m): لو ما وسعها السطر بالجوال بتنزل كاملة أو بتلتفّ جوّا حالها
    بترتيبها — بدونها كان نصها الثاني يطلع بالسطر اللي بعده قبل الأول بترتيب القراءة. النص الإنجليزي والرياضي لحاله ما بيتأثر"""
    h = fracs(text)
    if re.search("[؀-ۿ]", text):
        h = _ISO.sub(lambda m: "⁦<x-m>" + m.group(1) + "</x-m>⁩" if any(c in m.group(1) for c in _MATH_OPS) else m.group(0), h)
    return imgify(h)
def bdir(text):
    """اتجاه نص السؤال/الخيار بصفحات السيرفر: فيه حرف عربي (خارج المقاطع الرياضية المعزولة) ← rtl، وغيره auto.
    dir=auto لوحده بيقرأ أول حرف قوي: خيار بيبدأ بـ f(x) وبعده جملة عربية كان يطلع LTR وتنقلب كلماته"""
    return "rtl" if re.search("[؀-ۿ]", _ISO.sub("", text)) else "auto"
FRAC_CSS = ("x-fr{display:inline-flex;flex-direction:column;align-items:stretch;vertical-align:middle;direction:ltr;unicode-bidi:isolate;"
            "margin:0 .12em;font-size:.92em;line-height:1.25;text-align:center}x-fr x-fr{font-size:1em}"
            "x-n,x-d{display:block;padding:0 .2em;white-space:nowrap}x-d{border-top:.09em solid currentColor}"
            "x-m{display:inline-block;direction:ltr;max-width:100%}")
def check_images():
    if not IMG_LIST: return
    print(f"الصور: {len(IMG_LIST)} صورة مستعملة بالأسئلة")
    for n in IMG_LIST:
        kb = os.path.getsize(os.path.join(IMG_DIR, n)) // 1024
        if kb > 500: print(f"تنبيه: الصورة «{n}» حجمها {kb}KB — يفضّل أقل من 500KB عشان تنفتح بسرعة على أجهزة الطلاب")
def unpack_data_zip():
    """لو بجانب server.py ملف exam_data.zip (الأسئلة + مجلد images، وأحياناً الطلاب والإعدادات) بنفكّه تلقائياً (مرة لكل نسخة من الملف).
    قائمة الطلاب والإعدادات الموجودة (تبع مشرف المختبر) ما بتنستبدل: نسخة الـzip بتنحفظ جنبها باسم *_from_zip"""
    zp = os.path.join(BASE, "exam_data.zip"); mk = os.path.join(BASE, ".exam_data_unpacked")
    if not os.path.exists(zp): return
    sig = f"{os.path.getsize(zp)}:{int(os.path.getmtime(zp))}"
    if os.path.exists(mk) and open(mk, encoding="utf-8").read().strip() == sig: return
    try: z = zipfile.ZipFile(zp)
    except zipfile.BadZipFile: raise DataError("ملف exam_data.zip تالف أو مش ملف zip صحيح — نزّله من جديد")
    names = [i.filename.replace("\\", "/").strip("/") for i in z.infolist() if not i.is_dir()]
    tops = {n.split("/")[0] for n in names if "/" in n}
    strip = (next(iter(tops)) + "/") if names and all("/" in n for n in names) and len(tops) == 1 and next(iter(tops)).lower() != "images" else ""
    data = {"questions.xlsx", "questions.csv", "students.xlsx", "students.csv", "settings.txt"}
    done, skipped, kept = 0, 0, []
    os.makedirs(IMG_DIR, exist_ok=True)
    for info in z.infolist():
        if info.is_dir(): continue
        name = info.filename.replace("\\", "/").strip("/")
        if strip and name.startswith(strip): name = name[len(strip):]
        parts = name.split("/")
        if any(p in ("", ".", "..") for p in parts) or info.file_size > 25 * 1024 * 1024: skipped += 1; continue
        if len(parts) == 1 and parts[0].lower() in data:
            fn = parts[0].lower(); dest = os.path.join(BASE, fn)
            stem, ext = os.path.splitext(fn)
            mine = [e for e in ((".txt",) if stem == "settings" else (".xlsx", ".csv")) if os.path.exists(os.path.join(BASE, stem + e))] if stem in ("students", "settings") else []
            if mine:                                                    # قائمة الطلاب/الإعدادات تبع المشرف موجودة: ما نستبدلها، نحفظ نسخة الـzip جنبها
                dest = os.path.join(BASE, f"{stem}_from_zip{ext}"); kept.append(os.path.basename(dest))
            elif stem in ("questions", "students"):                    # الصيغة الجديدة بتلغي القديمة (السيرفر بيفضّل xlsx على csv)
                other = os.path.join(BASE, stem + (".csv" if ext == ".xlsx" else ".xlsx"))
                if os.path.exists(other): os.remove(other)
        elif len(parts) == 2 and parts[0].lower() == "images" and os.path.splitext(parts[1])[1].lower() in IMG_EXT:
            dest = os.path.join(IMG_DIR, parts[1])
        else: skipped += 1; continue
        with z.open(info) as src, open(dest, "wb") as out: shutil.copyfileobj(src, out)
        done += 1
    z.close()
    open(mk, "w", encoding="utf-8").write(sig)
    print(f"تم فك exam_data.zip: {done} ملف" + (f" (تجاهلت {skipped} ملف غير مألوف)" if skipped else ""))
    if kept: print("تنبيه: exam_data.zip فيه قائمة طلاب أو إعدادات، بس عندك نسختك فما استبدلناها. نسخة الـzip انحفظت باسم: " + "، ".join(kept))
def zip_leftovers():
    """نسخ طلاب/إعدادات جت مع exam_data.zip وما انستعملت (لأن تبع المشرف موجودة)"""
    try: return sorted(f for f in os.listdir(BASE) if f.split(".")[0] in ("students_from_zip", "settings_from_zip"))
    except OSError: return []                     # صفحة الفحص ما لازم توقع لو المجلد مش مقروء

def _lost_text(t):
    """«؟؟؟»: ملف CSV انحفظ بترميز ما بيدعم العربي (CSV عادي بإكسل على ويندوز غير عربي) فاستبدل الحروف بعلامات استفهام"""
    s = "".join(str(t).split())
    return len(s) >= 3 and s.count("?") >= 3 and s.count("?") / len(s) >= 0.6
def load_questions(auto_math=True):
    rows = read_table(find_file("questions"), ("السؤال", "question"))
    out, errs = [], []
    for i, r in enumerate(rows[1:], 2):
        r = [c for c in r] + [""] * (11 - len(r))
        if not any(r): continue
        q, opts, ans, lvl, page, sol = r[0], [x for x in r[1:5]], r[5], r[6], r[7], r[8]
        mk = r[9].strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٫،,", "0123456789..."))      # العلامة (اختياري): فاضي = 1، وتقبل كسور مثل 0.5 أو 2.5
        try: marks = num(mk) if mk else 1
        except ValueError: errs.append(f"questions سطر {i}: عمود «العلامة» لازم يكون رقم (مثلاً 1 أو 2 أو 0.5)، لقيت «{r[9]}»"); continue
        if not 0 < marks <= 100: errs.append(f"questions سطر {i}: العلامة لازم تكون أكبر من 0 وأقل من أو تساوي 100، لقيت «{r[9]}»"); continue
        if not q: errs.append(f"questions سطر {i}: نص السؤال فاضي"); continue
        if _lost_text(q) or any(_lost_text(o) for o in opts):
            errs.append(f"questions سطر {i}: النص علامات استفهام (؟؟؟) — الملف انحفظ بترميز ما بيدعم العربي. احفظه بصيغة Excel (xlsx) أو «CSV UTF-8»"); continue
        # الخيارات: المفروض متتالية من أ، ونسمح بـ 2–4 خيارات
        k = len(opts)
        while k and not opts[k - 1]: k -= 1
        opts = opts[:k]
        if k < 2 or any(not o for o in opts): errs.append(f"questions سطر {i}: لازم خيارين على الأقل بدون فراغ بينهم"); continue
        a = LET_IN.get(ans.strip().lower().replace(".", ""))
        if a is None or a >= k: errs.append(f"questions سطر {i}: عمود «الجواب» لازم يكون أ أو ب أو ج أو د (وضمن عدد الخيارات)، لقيت «{ans}»"); continue
        fx = r[10].strip().lower()                                      # ثابت (اختياري، العمود K): «نعم» = السؤال يظهر بكل ورقة طالب دائماً
        if fx not in YES | NO | {""}: errs.append(f"questions سطر {i}: عمود «ثابت» لازم يكون نعم أو فاضي، لقيت «{r[10]}»"); continue
        lv = LVL_IN.get(lvl.strip().lower())
        if lv is None: errs.append(f"questions سطر {i}: المستوى لازم يكون صعب أو وسط أو سهل (أو فاضي)، لقيت «{lvl}»"); continue
        if SET.get("qmark"): marks = SET["qmark"]                      # علامة_السؤال بالإعدادات بتغلب عمود العلامات بالملف
        f = autoltr if auto_math else (lambda x: x)
        out.append({"n": len(out) + 1, "level": lv, "page": page, "q": f(with_imgs(q, errs, i)), "o": [f(with_imgs(o, errs, i)) for o in opts], "a": a, "sol": sol, "marks": marks, "fixed": fx in YES, "row": i})
    if errs: raise DataError("\n".join(errs))
    if not out: raise DataError("ملف الأسئلة فاضي")
    return out

XCODES = {}                                  # رموز مكتوبة يدوياً بعمود رابع «الرمز» بملف الطلاب (اختياري)
def load_roster():
    rows = read_table(find_file("students"), ("الصف", "الاسم", "grade", "name")); ros, seen, errs = {}, set(), []
    for i, r in enumerate(rows[1:], 2):
        r = r + [""] * (4 - len(r))
        if not any(r): continue
        g, s, n = r[0].strip(), r[1].strip(), r[2].strip()
        if r[3].strip(): XCODES[(g, s, n)] = r[3].strip()
        if not (g and s and n): errs.append(f"students سطر {i}: لازم تعبّي الصف والشعبة والاسم"); continue
        if (g, s, n) in seen: errs.append(f"students سطر {i}: الاسم «{n}» مكرر بنفس الشعبة — غيّر أحدهما (مثلاً أضف حرف)"); continue
        seen.add((g, s, n)); ros.setdefault(g, {}).setdefault(s, []).append(n)
    if errs: raise DataError("\n".join(errs))
    if not ros: raise DataError("ملف الطلاب فاضي")
    return ros

def build_page():
    cfg, qs, ros = SET, QLIST, ROSTER
    lv = Counter(q["level"] for q in qs); given = cfg.get("given", set(cfg))
    if set(lv) <= {""} or all(q.get("autolevel") for q in qs):     # ما في مستويات: نسحب العدد الكلي من الكل (autolevel: لو انبنت الصفحة من جديد)
        for q in qs: q["level"] = "medium"; q["autolevel"] = True
        n = cfg["count"] if "count" in given else len(qs)                # العدد مش مكتوب = كل أسئلة البنك
        pick = {"hard": 0, "medium": min(n, len(qs)), "easy": 0}
        if n > len(qs): print(f"تنبيه: عدد الأسئلة بالامتحان ({n}) أكبر من البنك ({len(qs)}) — رح ينسحب {len(qs)}")
    else:
        for q in qs:
            if q["level"] == "": raise DataError(f"questions سطر {q['row']}: المستوى فاضي، وباقي الأسئلة إلها مستوى — عبّيه أو امسح عمود المستوى كله")
        pick = {k: (cfg[k] if k in given else lv[k]) for k in ("hard", "medium", "easy")}     # مستوى مش مكتوب = كل أسئلته
        bad = [f"{LVL[k]}: مطلوب {pick[k]} والموجود {lv[k]}" for k in pick if pick[k] > lv[k]]
        if bad: raise DataError("عدد الأسئلة بالبنك أقل من المطلوب بالامتحان — " + " | ".join(bad))
    fx = Counter(q["level"] for q in qs if q.get("fixed"))
    badf = [f"{LVL[k]}: ثوابت {fx[k]} والمطلوب بالامتحان {pick[k]}" for k in pick if fx[k] > pick[k]]
    if badf: raise DataError("عدد الأسئلة الثابتة (عمود «ثابت») أكبر من عدد أسئلة المستوى المطلوبة بالامتحان — " + " | ".join(badf))
    if cfg["qmark"] and cfg["final"]:                    # الاثنان مكتوبان: لازم يتطابقوا (مثلاً 20 سؤال × 1.5 = 30)
        N = sum(pick.values())
        if abs(N * cfg["qmark"] - cfg["final"]) > 0.005:
            raise DataError(f"settings.txt: عدد أسئلة الامتحان ({N}) × علامة_السؤال ({cfg['qmark']}) = {num(N * cfg['qmark'])} لكن العلامة_النهائية {cfg['final']} — صحّح أحدهما أو اترك واحداً منهما فاضياً")
    conf = ("const CONFIG = {examTitle: %s, minutes: %d, pick: %s, shuffleQuestions: %s, shuffleOptions: %s, showScore: %s, oneAttemptPerDevice: true, "
            "serverGrading: true, claimNames: true, lockdown: %s, reviewMode: \"%s\", needCode: %s, finalMark: %s, endpoint: \"/submit\"};" %
            (json.dumps(cfg["title"], ensure_ascii=False), cfg["minutes"], json.dumps(pick), str(cfg["shuffleQ"]).lower(),
             str(cfg["shuffleO"]).lower(), str(cfg["showScore"]).lower(), str(cfg["lockdown"]).lower(), cfg["review"], str(cfg["needCode"]).lower(), json.dumps(cfg["final"])))
    t = open(os.path.join(BASE, "template.html"), encoding="utf-8").read()
    i = t.index("const CONFIG = {"); j = t.index("};", i) + 2
    sj = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")      # JSON آمن داخل <script>
    t = t[:i] + conf.replace("</", "<\\/") + t[j:]
    t = t.replace("/*ROSTER*/{}", sj(ros))
    i = t.index("const QUESTIONS = ["); j = t.index("];\nconst ROSTER", i)
    # نصوص الأسئلة بتنعرض كـ HTML بصفحة الطالب، فنهرّب < و > و & (مثلاً «x<y» أو «a&b» ما تخرّب العرض)
    cq = []                                    # بنك الأسئلة ما بينحط بالصفحة: كل طالب بياخذ أسئلة ورقته بس من /start (pub_q)
    t = t[:i] + "const QUESTIONS = " + sj(cq) + t[j + 1:]
    t = t.replace("<title>الامتحان الإلكتروني</title>", "<title>%s</title>" % html.escape(cfg["title"]), 1)
    for k in ("hard", "medium", "easy"):                  # تنبيه: مستوى علاماته مختلفة + سحب عشوائي = مجموع مختلف بين الطلاب
        ms = sorted({q["marks"] for q in qs if q["level"] == k})
        if pick[k] and not cfg["final"] and len(ms) > 1 and pick[k] < sum(1 for q in qs if q["level"] == k):
            print(f"تنبيه: أسئلة مستوى «{LVL[k]}» علاماتها مختلفة {ms} والامتحان يسحب منها عشوائياً — مجموع العلامات رح يختلف من طالب لطالب")
    return t, pick
def raw_range(pick):
    """أقل وأعلى مجموع علامات ممكن لورقة طالب"""
    lo = hi = 0
    for k, n in pick.items():
        ms = sorted(q["marks"] for q in QLIST if q["level"] == k)
        lo += sum(ms[:n]); hi += sum(ms[len(ms) - n:]) if n else 0
    return num(lo), num(hi)
def total_range(pick):
    """العلامة الكاملة: العلامة_النهائية إن انكتبت، وإلا مجموع علامات الأسئلة"""
    return (SET["final"], SET["final"]) if SET["final"] else raw_range(pick)
def eff_mark(m, ids):
    """علامة السؤال الفعلية على ورقة طالب: لو في علامة نهائية بتتناسب مع مجموع علامات ورقته"""
    if not SET["final"]: return m
    return num(m * SET["final"] / sum(BANK[i]["marks"] for i in ids))
def key_mark(m):
    """علامة السؤال بصفحة المفتاح (لو العلامة الكاملة ثابتة لكل الأوراق)"""
    lo, hi = raw_range(PICK)
    return num(m * SET["final"] / lo) if SET["final"] and lo == hi else m

def report_problem(text):
    """نافذة ويندوز السوداء ما بتعرض العربي (مربعات): بنكتب التفاصيل بملف نصي UTF-8 وبنفتحه بالمفكرة (على ويندوز وبنافذة حقيقية)"""
    path = os.path.join(BASE, "exam_error.txt")
    try:
        with open(path, "w", encoding="utf-8-sig") as f: f.write(text)
        if REAL_CONSOLE: os.startfile(path)
    except Exception: pass
    return path
try:
    unpack_data_zip()
    SET = read_settings(); QLIST = load_questions(); ROSTER = load_roster(); check_images()
    BANK = {q["n"]: q for q in QLIST}
    PAGE, PICK = build_page()
except DataError as e:
    msg = str(e)
    hint = "  Missing file: put exam_data.zip (or questions.xlsx + students.xlsx; settings.txt is optional) next to server.py, then run again." if "غير موجود جنب" in msg else ""
    path = report_problem("في مشكلة بالملفات — صلّحها وشغّل من جديد:\n\n" + msg + "\n")
    print("\n" + "=" * 56 + "\n  PROBLEM WITH THE EXAM FILES  /  في مشكلة بالملفات\n" + "=" * 56)
    if hint: print(hint)
    print("  Details in Arabic were saved to: " + path + ("  (opened in Notepad)" if REAL_CONSOLE else ""))
    print(msg); print("=" * 56)
    sys.exit(1)
except Exception as e:
    path = report_problem("خطأ بقراءة الملفات: " + repr(e) + "\nتأكد إن ملفات الأسئلة والطلاب مش مفتوحة بـ Excel وإنها محفوظة بصيغة xlsx أو csv.\n")
    print("\nERROR READING THE EXAM FILES: " + repr(e) + "\nMake sure the questions/students files are not open in Excel and are saved as xlsx or csv.\nDetails: " + path)
    print("\nخطأ بقراءة الملفات:", repr(e), "\nتأكد إن ملفات الأسئلة والطلاب مش مفتوحة بـ Excel وإنها محفوظة بصيغة xlsx أو csv.")
    sys.exit(1)
try: os.remove(os.path.join(BASE, "exam_error.txt"))   # الملفات سليمة: رسالة خطأ قديمة (من تشغيل سابق) ما بتعود صحيحة، فبنشيلها حتى ما تضلّل المعلم
except OSError: pass
CLAIMS = load_json(CLAIMS_FILE, {})        # مفتاح الطالب -> الجهاز اللي بدأ منه
PAPERS = load_json(PAPERS_FILE, {})        # مفتاح الطالب -> {start, ids, orders, extra}
STATE = load_json(STATE_FILE, {"closed_at": 0, "msg": {"id": 0, "text": ""}})
if STATE.get("auto_title") != (SET["title"] if SET.get("auto_title") else None):   # العنوان التلقائي بينحفظ عشان يضل نفسه لو انعاد تشغيل السيرفر
    if SET.get("auto_title"): STATE["auto_title"] = SET["title"]
    else: STATE.pop("auto_title", None)                # عنوان مكتوب بالإعدادات: ما نخلّي عنوان تلقائي قديم يرجع بعدين
    try: atomic_write(STATE_FILE, json.dumps(STATE, ensure_ascii=False))
    except OSError: pass
ANS = load_json(ANS_FILE, {})              # مفتاح الطالب -> {رقم السؤال: رقم الخيار}
ANS_DIRTY = [False]
LIVE = {}                                   # مفتاح الطالب -> آخر نبضة من صفحة الطالب
SUBS = {}                                   # مفتاح الطالب -> التسليم (أول تسليم فقط بعد آخر «إعادة فتح»)
if os.path.exists(SUBS_FILE):
    try:                                           # انقطاع كهرباء أثناء الكتابة ممكن يخلّي آخر سطر مقطوع بدون newline، فأول تسليم بعده كان يلتصق فيه ويضيع
        with open(SUBS_FILE, "rb+") as _f:
            _f.seek(0, 2)
            if _f.tell() > 0:
                _f.seek(-1, 2)
                if _f.read(1) != b"\n": _f.write(b"\n")
    except OSError: pass
    for line in open(SUBS_FILE, encoding="utf-8"):
        try:
            r = json.loads(line)
            if r.get("reopen"): SUBS.pop(r["key"], None)          # المعلم أعاد فتح الطالب: تسليمه اللي قبل هالسطر ما بيعدّ (بيضل بالسجل كأرشيف)
            else: SUBS.setdefault(r["key"], r)
        except Exception: pass

def bank_fp():
    """بصمة محتوى بنك الأسئلة (النصوص والخيارات والإجابات والمستويات): بتتغير بس لما يتغير محتوى ملف الأسئلة فعلاً، مش لما ينحفظ من جديد"""
    return hashlib.sha256(json.dumps([[q["q"], q["o"], q["a"], q["level"]] for q in QLIST], ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
BANK_FP = bank_fp()
def check_bank_change():
    """ملف أسئلة جديد والسيرفر لسا فيه أوراق/تسليمات امتحان سابق: لازم «بداية امتحان جديد» قبل ما يدخل الطلاب. بترجّع True لو STATE تغيّرت"""
    old, had = STATE.get("bank_fp"), "bank_changed" in STATE
    if not (PAPERS or SUBS):                       # ما في بيانات امتحان سابق: هذا البنك هو بنك الامتحان الحالي
        STATE.pop("bank_changed", None); STATE["bank_fp"] = BANK_FP
        return old != BANK_FP or had
    if old is None: STATE["bank_fp"] = BANK_FP; return True       # بيانات من نسخة أقدم ما فيها بصمة: البنك الحالي هو الأساس
    if old != BANK_FP and not had: STATE["bank_changed"] = {"at": time.time()}; return True
    if old == BANK_FP and had: STATE.pop("bank_changed"); return True
    return False
if check_bank_change():
    try: atomic_write(STATE_FILE, json.dumps(STATE, ensure_ascii=False))
    except OSError: pass
def bank_changed():
    return {"subs": len(SUBS), "papers": len(PAPERS)} if STATE.get("bank_changed") else None

CODES = {}                                  # "صف|شعبة|اسم" -> رمز الدخول
FAILS = {}                                  # مفتاح الطالب -> [عدد المحاولات الخاطئة، قفل لحد وقت]
def norm_code(c): return str(c).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")).strip()
def init_codes():
    """رمز لكل طالب: من عمود «الرمز» بملف الطلاب إن وُجد، وإلا مولَّد عشوائياً ومحفوظ بـ codes.json"""
    saved, gen, rng = load_json(CODES_FILE, {}), {}, random.SystemRandom()
    for g, secs in ROSTER.items():
        for s, names in secs.items():
            for n in names:
                ck = f"{g}|{s}|{n}"
                if (g, s, n) in XCODES: CODES[ck] = norm_code(XCODES[(g, s, n)])
                else: CODES[ck] = gen[ck] = saved.get(ck) or "%06d" % rng.randrange(10 ** 6)
    if gen != saved: atomic_write(CODES_FILE, json.dumps(gen, ensure_ascii=False, indent=1))
def check_code(k, given):
    """None = صحيح، وإلا "badcode" أو "locked" (5 محاولات خاطئة = قفل دقيقة لهذا الاسم)"""
    now, f = time.time(), FAILS.get(k)
    if f and f[1] > now: return "locked"
    if hmac.compare_digest(norm_code(given or "").encode(), CODES["|".join(parse_key(k))].encode()):
        FAILS.pop(k, None); return None
    f = FAILS.setdefault(k, [0, 0]); f[0] += 1
    if f[0] >= 5: f[0] = 0; f[1] = now + 60
    return "badcode"
if SET["needCode"]: init_codes()
PROTECTED = ("/key", "/teacher", "/sheet", "/codes")      # صفحات المعلم اللي بتحتاج كلمة السر (فيها الإجابات الصحيحة أو رموز الطلاب)
TOKENS = set()                               # جلسات المعلم المسجّلة (بالذاكرة فقط: بتنتهي بإطفاء السيرفر)
TFAIL = [0, 0]                               # محاولات كلمة سر خاطئة [العدد، قفل لحد وقت]
_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
def norm_pass(s):
    """كلمة السر للمقارنة: الأرقام العربية (١٢٣٤) زي الإنجليزية (1234)، والمسافات بالأطراف ما بتفرق"""
    return str(s).translate(_DIG).strip()
try: SET_MTIME = [os.path.getmtime(os.path.join(BASE, "settings.txt"))]
except OSError: SET_MTIME = [None]
def refresh_tpass():
    """المعلم غيّر كلمة السر بملف settings.txt والسيرفر شغّال: بنقرأها من جديد (كلمة السر بس؛ باقي الإعدادات بتحتاج إعادة تشغيل)"""
    try: m = os.path.getmtime(os.path.join(BASE, "settings.txt"))
    except OSError: return
    if m == SET_MTIME[0]: return
    SET_MTIME[0] = m
    try: new = read_settings()["tpass"]
    except Exception: return                     # الملف لسا بينكتب أو فيه خطأ: بنضل على كلمة السر الحالية
    if new != SET["tpass"]:
        SET["tpass"] = new; print("كلمة سر المعلم تغيّرت من settings.txt (اشتغلت بدون إعادة تشغيل)")

def login_page(nxt):
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>دخول المعلم</title>"
            "<style>body{font-family:Tahoma,Arial;background:#f4f6f8;display:flex;justify-content:center;padding-top:12vh}"
            ".box{background:#fff;border:1px solid #d8dee4;border-radius:12px;padding:26px;width:min(92vw,360px);text-align:center}"
            "h2{color:#14566b;margin:0 0 6px}p{color:#5d6b7a;font-size:14px}input,button{font:inherit;width:100%;padding:11px;border-radius:8px;border:1px solid #d8dee4;margin-top:10px;box-sizing:border-box}"
            "button{background:#14566b;color:#fff;border:0;font-weight:bold;cursor:pointer}#m{color:#b3261e;margin-top:10px;min-height:22px}</style>"
            "<div class=box><h2>🔒 صفحة للمعلم فقط</h2><p>اكتب كلمة سر المعلم (مكتوبة بملف settings.txt)</p>"
            "<input id=p type=password autofocus autocomplete=off><button id=b>دخول</button><div id=m></div></div>"
            "<script>const NEXT=__NEXT__;const p=document.getElementById('p'),m=document.getElementById('m');"
            "const NOCK='كلمة السر صحيحة، بس المتصفح مانع الكوكيز (Cookies) فما بيقدر يحفظ دخولك. اسمح بالكوكيز لـ localhost أو افتح الصفحة بـ Edge أو Chrome.';"
            "async function go(){let j;try{const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json','X-Exam-Action':'1'},body:JSON.stringify({password:p.value})});j=await r.json()}"
            "catch(e){m.textContent='تعذّر الاتصال بالسيرفر: تأكد إن النافذة السوداء شغّالة، وافتح الصفحة من جهاز السيرفر على http://localhost';return}"
            "if(j.ok){let c={};try{c=await (await fetch('/authcheck',{cache:'no-store'})).json()}catch(e){}if(c.authed===false){m.textContent=NOCK;return}location.href=NEXT}"
            "else m.textContent=j.locked?('محاولات خاطئة كثيرة، انتظر '+j.locked+' ثانية'):'كلمة السر غير صحيحة. انتبه للغة الكيبورد (عربي/English) والأحرف الكبيرة والصغيرة.'}"
            "document.getElementById('b').onclick=go;p.onkeydown=e=>{if(e.key==='Enter')go()}</script>").replace("__NEXT__", json.dumps(nxt))

def build_preview():
    """معاينة المعلم: كل أسئلة البنك بنفس واجهة الطالب، بترتيبها الأصلي، وتصحيح بالمتصفح (الإجابات الصحيحة موجودة بالصفحة، فهي محميّة بكلمة السر وللمعلم فقط). ما بتنحفظ نتيجتها"""
    lv = Counter(q["level"] for q in QLIST)
    pick = {k: lv.get(k, 0) for k in ("hard", "medium", "easy")}
    title = "معاينة المعلم — " + SET["title"]
    conf = ("const CONFIG = {examTitle: %s, minutes: 600, pick: %s, shuffleQuestions: false, shuffleOptions: false, showScore: true, oneAttemptPerDevice: false, "
            "serverGrading: false, claimNames: false, lockdown: false, reviewMode: \"no\", needCode: false, teacherPreview: true, endpoint: \"\"};" %
            (json.dumps(title, ensure_ascii=False).replace("</", "<\\/"), json.dumps(pick)))
    t = open(os.path.join(BASE, "template.html"), encoding="utf-8").read()
    i = t.index("const CONFIG = {"); j = t.index("};", i) + 2
    t = t[:i] + conf + t[j:]
    t = t.replace("/*ROSTER*/{}", json.dumps({"المعلم": {"معاينة": ["معاينة المعلم"]}}, ensure_ascii=False))
    qs = [{"n": q["n"], "level": q["level"], "page": q["page"], "marks": q.get("marks", 1), "q": qhtml(q["q"]), "o": [qhtml(o) for o in q["o"]], "a": q["a"]} for q in QLIST]
    i = t.index("const QUESTIONS = ["); j = t.index("];\nconst ROSTER", i)
    t = t[:i] + "const QUESTIONS = " + json.dumps(qs, ensure_ascii=False).replace("</", "<\\/") + t[j + 1:]
    t = t.replace("<title>الامتحان الإلكتروني</title>", "<title>معاينة المعلم</title>", 1)
    out = " &nbsp; <a href=/logout style='color:#fff'>🔒 قفل</a>" if SET["tpass"] else ""
    banner = ("<div style='background:#14566b;color:#fff;padding:8px 14px;font-weight:bold;display:flex;gap:12px;justify-content:space-between;flex-wrap:wrap'>"
              "<span>🔍 معاينة المعلم: كل أسئلة البنك (%d سؤال) بنفس واجهة الطالب. النتيجة ما بتنحفظ وما بتظهر بالمراقبة.</span>"
              "<span><a href=/monitor style='color:#fff'>المراقبة</a>%s</span></div>" % (len(qs), out))
    t = t.replace("<body>", "<body>" + banner, 1)
    auto = "(async()=>{const g=$('g');g.selectedIndex=1;g.onchange();const s=$('sec');s.selectedIndex=1;await s.onchange();const n=$('nm');n.selectedIndex=1;n.onchange();$('start').click()})();\n"
    return t.replace("</script>\n</body>", auto + "</script>\n</body>", 1)
PREVIEW = build_preview()
def save_claims(): atomic_write(CLAIMS_FILE, json.dumps(CLAIMS, ensure_ascii=False, indent=1))
def save_papers(): atomic_write(PAPERS_FILE, json.dumps(PAPERS, ensure_ascii=False))
def parse_key(k):
    """مفتاح الطالب: العنوان|الصف|الشعبة|الاسم — يرجّع (صف، شعبة، اسم) لو الطالب موجود بالقائمة وإلا None"""
    p = k.rsplit("|", 3) if isinstance(k, str) else []
    if len(p) != 4 or p[0] != SET["title"]: return None
    g, s, n = p[1:]
    return (g, s, n) if n in ROSTER.get(g, {}).get(s, []) else None
def make_paper():
    """السيرفر هو اللي يسحب الأسئلة ويخلطها (مش جهاز الطالب)"""
    ids = []
    for lv in ("hard", "medium", "easy"):
        fixed = [q["n"] for q in QLIST if q["level"] == lv and q.get("fixed")]          # الأسئلة الثابتة تدخل كل ورقة
        rest = [q["n"] for q in QLIST if q["level"] == lv and not q.get("fixed")]
        ids += fixed + random.sample(rest, PICK[lv] - len(fixed))
    ids.sort()
    if SET["shuffleQ"]: random.shuffle(ids)
    orders = []
    for n in ids:
        o = list(range(len(BANK[n]["o"])))
        if SET["shuffleO"]: random.shuffle(o)
        orders.append(o)
    return {"start": time.time(), "ids": ids, "orders": orders}
def save_state(): atomic_write(STATE_FILE, json.dumps(STATE, ensure_ascii=False))
def paused_for(p):
    """كم ثانية صار الطالب موقوفاً (إيقاف مؤقت من المعلم، مثلاً للحمّام)؛ 0 لو مش موقوف. وقته متجمّد: هالمدة بتنضاف لنهاية وقته أول بأول"""
    return time.time() - p["paused"] if "paused" in p else 0
def settle_pause(p):
    """إنهاء الإيقاف: المدة بتثبت بنهاية وقت الطالب (extra) وبمجموع الإيقاف (pz) اللي بنطرحه من مدة الحل. بترجّع المدة بالثواني"""
    if "paused" not in p: return 0
    gap = max(0.0, time.time() - p.pop("paused")); p["extra"] = p.get("extra", 0) + gap; p["pz"] = p.get("pz", 0) + gap
    return gap
def deadline(k):
    """نهاية وقت الطالب: البدء + المدة + التمديد (+ الإيقاف الجاري)، أو لحظة إنهاء المعلم للامتحان (الأبكر)"""
    p = PAPERS[k]; d = p["start"] + SET["minutes"] * 60 + p.get("extra", 0) + paused_for(p)
    return min(d, STATE["closed_at"]) if STATE["closed_at"] else d
def remain_of(k): return max(0, int(deadline(k) - time.time()))
def fmt_dur(s):
    """مدة الحل للعرض: 45 ث، 23 د 41 ث، 1 س 05 د 10 ث. فاضية لو ما انسجّلت (تسليم قبل الميزة، أو تسليم من المعلم).
    نص عربي وليس 23:41 لأن Excel بيقرأ هاي الصيغة كساعة من اليوم"""
    if not isinstance(s, (int, float)) or isinstance(s, bool) or s < 0: return ""
    s = int(s); h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h} س {m:02d} د {sec:02d} ث" if h else (f"{m} د {sec:02d} ث" if m else f"{sec} ث")
def pub_q(n):
    """السؤال زي ما بينعرض للطالب: النص والخيارات والعلامة بس (بدون الإجابة الصحيحة والحل والمستوى والمرجع)"""
    q = BANK[n]
    return {"n": n, "marks": q["marks"], "q": qhtml(q["q"]), "o": [qhtml(o) for o in q["o"]]}
def paper_reply(k):
    p = PAPERS[k]
    return {"status": "ok", "ids": p["ids"], "orders": p["orders"], "qs": [pub_q(n) for n in p["ids"]], "remain": remain_of(k), "msg": STATE["msg"], "ans": ANS.get(k, {}), "paused": "paused" in p}
def clean_ans(k, a):
    """إجابات الطالب المحفوظة: {رقم السؤال: رقم الخيار الأصلي} — نتأكد إنها ضمن ورقته فقط"""
    if not isinstance(a, dict): return None
    ids, out = set(PAPERS[k]["ids"]), {}
    for n, j in a.items():
        try: n, j = int(n), int(j)
        except (TypeError, ValueError): continue
        if n in ids and 0 <= j < len(BANK[n]["o"]): out[str(n)] = j
    return out
ALIVE_FILE = os.path.join(BASE, "alive.txt")          # آخر لحظة كان فيها السيرفر شغّال (بتتحدّث كل 3 ثواني): منها بنعرف مدة التوقف
MAX_COMP = 30 * 60                                   # أكبر توقف بنعوّضه تلقائياً (ثانية)
COMP = None                                          # نتيجة التعويض عند آخر تشغيل (للبانر)
def beat():
    try: atomic_write(ALIVE_FILE, repr(time.time()))
    except OSError: pass
def flusher():
    """الإجابات بتتغير كل بضع ثواني لـ 80 طالب، فنحفظها على الملف كل 3 ثواني (مش مع كل نبضة). ونفس الدورة بتسجّل «السيرفر لسا شغّال» بـ alive.txt"""
    while True:
        time.sleep(3)
        try: gap_check(tick=True); flush_answers(); beat()
        except Exception as e: print("تنبيه: خطأ بدورة الحفظ (بتكمل):", repr(e))      # ما نخلّي الدورة تموت: هي اللي بتحفظ الإجابات
LAST_TICK = [None]          # آخر لحظة كان فيها السيرفر «صاحي» (دورة الحفظ بتحدّثها كل 3 ث). None = الدورة مش شغّالة (مثلاً وقت check_files)
GAP_S = 20                  # قفزة أكبر من هيك بين دورتين = الجهاز نام (انسكّر غطاء اللابتوب) أو تجمّد
def gap_check(tick=False):
    """الجهاز نام أو تجمّد وسط الامتحان ورجع: السيرفر ما انطفى فما في تعويض «بعد التشغيل»، فبنعوّض هون بنفس القواعد.
    بتتنادى من دورة الحفظ ومن أول كل طلب POST: طالب خلص وقته وقت النوم بيرجع لامتحانه بالوقت المعوّض بدل ما ينحسب عليه"""
    now = time.time(); last = LAST_TICK[0]
    if last is None or (not tick and now - last <= GAP_S): return None
    with LOCK:
        last = LAST_TICK[0]
        if last is None: return None
        rec = compensate_downtime(last, "sleep") if now - last > GAP_S else None
        LAST_TICK[0] = max(now, LAST_TICK[0])
        return rec
def flush_answers():
    with LOCK:
        if not ANS_DIRTY[0]: return
        try: atomic_write(ANS_FILE, json.dumps(ANS, ensure_ascii=False)); ANS_DIRTY[0] = False
        except OSError as e: print("تنبيه: تعذّر حفظ answers.json:", e)
def extend_time(minutes, scope, d):
    """تمديد وقت الطلاب اللي بدأوا ولم يسلّموا: طالب واحد، شعبة، أو الكل"""
    n = 0
    for k, p in PAPERS.items():
        if k in SUBS: continue
        w = parse_key(k)
        if w is None: continue
        if scope == "student" and k != d.get("key"): continue
        if scope == "section" and (w[0], w[1]) != (d.get("grade"), d.get("section")): continue
        p["extra"] = p.get("extra", 0) + minutes * 60; n += 1
    if n: save_papers()
    return n
def compensate_downtime(last=None, why="restart"):
    """السيرفر وقف وانشغّل من جديد وسط الامتحان: الوقت كان يمشي أثناء التوقف. بنزيد وقت كل طالب بدأ ولم يسلّم وكان عنده وقت لحظة التوقف بنفس مدة التوقف
    (لحد 30 دقيقة؛ أكثر من هيك المعلم بيمدّد يدوياً). ما بنعوّض: المسلّمين، والمنقولين (وقتهم متجمّد)، ومن انتهى وقته قبل التوقف، ولا بعد إنهاء الامتحان"""
    if last is None:                                 # بعد إعادة التشغيل: آخر نبضة سجّلها التشغيل السابق. (gap_check بتبعث last بنفسها لما الجهاز ينام ويصحى)
        STATE.pop("comp", None)
        try: last = float(open(ALIVE_FILE, encoding="utf-8").read().strip())
        except (OSError, ValueError): return None
    now = time.time(); down = now - last
    if down < 3 or not PAPERS: return None
    rec = {"at": now, "downtime_s": int(down), "students": 0}
    if why == "sleep": rec["sleep"] = True
    if not SET.get("comp", True): rec["off"] = True
    elif down > MAX_COMP: rec["skipped"] = True
    else:
        for k, p in PAPERS.items():
            if k in SUBS or "frozen" in p or "paused" in p or deadline(k) <= last: continue
            p["extra"] = p.get("extra", 0) + int(down); p["down"] = p.get("down", 0) + int(down); rec["students"] += 1       # down: وقت التوقف بنطرحه من مدة الحل
        if rec["students"]: save_papers()
    STATE["comp"] = rec; save_state()
    print(f"تعويض التوقف: {'جهاز السيرفر نام أو تجمّد' if why == 'sleep' else 'السيرفر كان متوقفاً'} {int(down)} ثانية — " + ("التعويض مطفّأ بالإعدادات" if rec.get("off") else "أطول من 30 دقيقة: ما عوّضنا تلقائياً" if rec.get("skipped") else f"مدّدنا وقت {rec['students']} طالب"))
    return rec
def submit_for(k):
    """تسليم عن الطالب (من المعلم): بنصحّح إجاباته المحفوظة على السيرفر (الأسئلة اللي ما أجاب عنها = خاطئة) وبنسجّلها كتسليم. بتتنادى داخل LOCK"""
    if k in SUBS or k not in PAPERS or k not in CLAIMS: return False
    w = parse_key(k)
    if w is None: return False
    settle_pause(PAPERS[k]); ids = PAPERS[k]["ids"]; saved = ANS.get(k, {})
    answers = []
    for n in ids:
        try: answers.append(int(saved.get(str(n), -1)))
        except (TypeError, ValueError): answers.append(-1)
    got = sum(BANK[n]["marks"] for n, a in zip(ids, answers) if a == BANK[n]["a"])
    W = sum(BANK[n]["marks"] for n in ids)
    if SET["final"]: score, total = num(got / W * SET["final"]), num(SET["final"])
    else: score, total = num(got), num(W)
    lv = LIVE.get(k) or {}
    rec = {"key": k, "exam": SET["title"], "grade": w[0], "section": w[1], "name": w[2], "ids": ids, "answers": answers,
           "score": score, "total": total, "auto": "تسليم من المعلم", "time": time.strftime("%Y-%m-%d %H:%M:%S"),
           "leave": f"{lv['leaveN']} مرة ({lv.get('leaveSec', 0)} ث)" if lv.get("leaveN") else "لم يخرج", "late": 0, "ts": round(time.time(), 2)}
    with open(SUBS_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
    SUBS[k] = rec; LIVE.pop(k, None)
    if ANS.pop(k, None) is not None: ANS_DIRTY[0] = True
    print("تسليم من المعلم:", w[1], w[2], score, "/", total, f"({sum(1 for a in answers if a >= 0)} إجابة محفوظة)")
    return True
REOPEN_MIN = 120                                # أقل وقت بنعطيه لطالب أُعيد فتحه (ثواني)، حتى لو سلّم قبل نهاية وقته بلحظات
def reopen_student(k):
    """إعادة فتح طالب سلّم بالغلط: تسليمه بينلغى (بيضل بـ submissions.jsonl كأرشيف وبعده سطر «reopen»)، وبيرجع لأسئلته بإجاباته المحفوظة ووقته اللي كان باقيله لحظة
    التسليم (التمديدات محسوبة، وعلى الأقل REOPEN_MIN). الاسم والجهاز بيضلوا محجوزين، وصفحته (لو لسا مفتوحة) بترجع للأسئلة خلال ثواني. بترجّع نص الخطأ أو None"""
    if k not in SUBS: return "الطالب ما سلّم (أو ما بدأ)"
    if STATE["closed_at"]: return "الامتحان منتهٍ: أعد فتحه أولاً ثم أعد فتح الطالب"
    p = PAPERS.get(k)
    if p is None or k not in CLAIMS: return "ما في ورقة محفوظة لهالطالب (انفكّ حجزه)"
    rec = SUBS[k]; now = time.time(); ts = rec.get("ts")
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):                 # تسليم من نسخة أقدم: نقرأ الوقت من النص
        try: ts = time.mktime(time.strptime(rec["time"], "%Y-%m-%d %H:%M:%S"))
        except (KeyError, TypeError, ValueError, OverflowError): ts = now
    ts = min(ts, now)
    target = max(int(p["start"] + SET["minutes"] * 60 + p.get("extra", 0) - ts), REOPEN_MIN)
    saved = {str(n): a for n, a in zip(rec["ids"], rec["answers"]) if isinstance(a, int) and not isinstance(a, bool) and a >= 0}
    with open(SUBS_FILE, "a", encoding="utf-8") as f:                              # أول شي بنكتب السطر؛ لو فشلت الكتابة ما بيتغيّر شي
        f.write(json.dumps({"key": k, "reopen": round(now, 2), "exam": SET["title"], "time": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
    p.pop("paused", None); p["extra"] = now + target - p["start"] - SET["minutes"] * 60; p["pz"] = p.get("pz", 0) + (now - ts)      # مدة «سلّم» ما بتنحسب من مدة حله
    SUBS.pop(k); ANS[k] = saved; ANS_DIRTY[0] = True
    try: atomic_write(ANS_FILE, json.dumps(ANS, ensure_ascii=False)); ANS_DIRTY[0] = False             # الإجابات المستعادة بتنكتب فوراً (لو وقف السيرفر الآن ما بتضيع)
    except OSError: pass
    LIVE[k] = {"t": now, "answered": len(saved), "total": len(rec["ids"]), "remain": target, "leaveN": 0, "leaveSec": 0}
    save_papers(); write_results_csv()
    return None
def write_results_csv():
    """results.csv يتولّد من التسليمات. لو كان مفتوح بـ Excel نتجاوز (التسليم محفوظ بـ jsonl أصلاً)"""
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(HEAD)
    for rec in SUBS.values():
        w.writerow([rec["exam"], rec["grade"], rec["section"], rec["name"], rec["score"], rec["total"],
                    wrong_text(wrong_items(rec["ids"], rec["answers"])), rec.get("auto", ""), rec.get("time", ""), rec.get("leave", ""), rec.get("late", 0), fmt_dur(rec.get("dur"))])
    try: atomic_write(OUT, "﻿" + buf.getvalue(), tries=2)          # مفتوح بـ Excel = ممسوك طول الوقت: ما نستنّى عليه مع كل تسليم
    except OSError as e: print("تنبيه: تعذّر تحديث results.csv (مفتوح بـ Excel؟) — التسليمات محفوظة بـ submissions.jsonl:", e)

def wrong_items(ids, answers):
    """الأسئلة الخاطئة فقط (حسب البنك الأصلي)"""
    out = []
    for n, v in zip(ids, answers):
        q = BANK[n]
        if v != q["a"]: out.append({"n": n, "level": q["level"], "q": q["q"], "o": q["o"], "given": v, "correct": q["a"]})
    return out
def wrong_text(items):
    lines = []
    for w in items:
        given = "لم يجب" if w["given"] < 0 else f"{L[w['given']]}) {w['o'][w['given']]}"
        lines.append(f"س{w['n']} ({LVL.get(w['level'], '')}): {w['q']}  ← أجاب: {given}  |  الصحيح: {L[w['correct']]}) {w['o'][w['correct']]}")
    return noimg("\n".join(lines)) if lines else "— لا أخطاء —"

def safe_fn(s):
    """اسم ملف آمن على ويندوز من اسم طالب: الحروف والأرقام والمسافة والشرطة، وأي شي ثاني بيصير _"""
    return "".join(c if (c.isalnum() or c in " -") else "_" for c in s).strip(" _")[:50] or "x"
ST_AR = {"done": "سلّم", "live": "بدأ ولم يسلّم", "lost": "بدأ ولم يسلّم", "none": "لم يبدأ"}
def export_static(d, secs):
    """نتائج جاهزة تنفتح بأي متصفح بدون Python ولا سيرفر: مجلد «نتائج» بالأرشيف لحاله (فيه صوره كمان، فبيتنقل أو بيتبعت كمجلد واحد): صفحة رئيسية (العلامات
    ومدة الحل)، وورقة كل طالب، وورقات كل شعبة للطباعة، والتقرير وملف Excel، والأسئلة مع الإجابات. كلها من نفس دوال السيرفر (student_rows وsheet_html وreport_page
    وbuild_xlsx وkey_page) على بيانات الذاكرة، ونحط الشعب اللي امتحنت بس (نبدّل ROSTER مؤقتاً داخل القفل). بتنادى قبل تصفير الذاكرة"""
    global ROSTER
    root = os.path.join(d, "نتائج"); sheets = os.path.join(root, "ورقات"); home = "ابدأ_من_هنا.html"
    os.makedirs(sheets)
    if os.path.isdir(IMG_DIR): shutil.copytree(IMG_DIR, os.path.join(root, "images"))
    saved = ROSTER
    ROSTER = {g: {s: ns for s, ns in ss.items() if (g, s) in secs} for g, ss in saved.items()}
    ROSTER = {g: ss for g, ss in ROSTER.items() if ss}
    try:
        def put(path, h, depth):                                             # الصور: /img/اسم -> مسار نسبي لمجلد images اللي جوّا «نتائج» (depth = كم مستوى تحت «نتائج»)
            with open(path, "w", encoding="utf-8", newline="") as f: f.write(h.replace('"/img/', '"' + "../" * depth + "images/"))
        def nav(up): return f"<p class=noprint><a class=btn href='{up}{home}'>الرئيسية</a> <button class=btn onclick=print()>طباعة</button></p>"
        wo = "<style>.wo .q.good{display:none}</style>"
        tog = " <button class=btn onclick=\"document.body.classList.toggle('wo')\">عرض الخاطئة فقط / الكل</button>"
        rows = student_rows()
        h = CSS + "<body>" + f"<h2>{html.escape(SET['title'])}: نتائج الامتحان</h2>"
        h += "<p><a class=btn href='التقرير.html'>التقرير (ملخص الشعب وتحليل الأسئلة)</a> <a class=btn href='report.xlsx'>ملف Excel</a> <a class=btn href='الأسئلة_والإجابات.html'>الأسئلة مع الإجابات</a></p>"
        n = 0
        for (g, s) in sorted({(r["grade"], r["section"]) for r in rows}):
            sec = [r for r in rows if r["grade"] == g and r["section"] == s]; dn = [r for r in sec if r["status"] == "done"]
            h += f"<h3>{html.escape(g)} — شعبة {html.escape(s)} ({len(dn)} سلّموا من {len(sec)})</h3>"
            if dn:
                fn = f"الشعبة_{safe_fn(g)}_{safe_fn(s)}_كل_الورقات.html"
                put(os.path.join(sheets, fn), CSS + SHEET_CSS + "<body>" + nav("../") + "".join(sheet_html(SUBS[r["key"]], False) for r in dn), 1)
                h += f"<p><a class=btn href='ورقات/{urllib.parse.quote(fn)}'>ورقات الشعبة كلها (للطباعة)</a></p>"
            h += "<table><tr><th>الاسم</th><th>الحالة</th><th>العلامة</th><th>مدة الحل</th><th>الخروج من الصفحة</th><th></th></tr>"
            for r in sec:
                n += 1; link = ""
                if r["status"] == "done":
                    fn = f"{n:03d}_{safe_fn(r['name'])}.html"
                    put(os.path.join(sheets, fn), CSS + SHEET_CSS + wo + "<body>" + nav("../") + tog + sheet_html(SUBS[r["key"]], False), 1)
                    link = f"<a class=btn href='ورقات/{urllib.parse.quote(fn)}'>فتح الورقة</a>"
                h += (f"<tr class={r['status']}><td>{html.escape(r['name'])}</td><td>{ST_AR[r['status']]}</td>"
                      f"<td>{'%s / %s' % (r['score'], r['total']) if r['status'] == 'done' else ''}</td><td>{html.escape(r.get('durtxt', ''))}</td>"
                      f"<td>{html.escape(str(r.get('leave', '')))}</td><td>{link}</td></tr>")
            h += "</table>"
        put(os.path.join(root, home), h, 0)
        rp = report_page(arch_home=home)
        put(os.path.join(root, "التقرير.html"), rp, 0)
        with open(os.path.join(root, "report.xlsx"), "wb") as f: f.write(build_xlsx())
        kp = key_page(arch_home=home)
        put(os.path.join(root, "الأسئلة_والإجابات.html"), kp, 0)
    finally:
        ROSTER = saved
def export_results(d, keys):
    """كبسة «بداية امتحان جديد» بتحط بمجلد الأرشيف، غير ملفات البيانات، مجلد «نتائج» جاهز للأستاذ (export_static): بدون سيرفر ولا إعدادات ولا أسئلة ولا قائمة طلاب.
    لو ما حدا بدأ ما بنعمل شي. ولو ما زبط (مثلاً السيرفر انشغّل من جديد على ملف أسئلة جديد: أسئلة الذاكرة مش أسئلة هالامتحان) بنكتب ملاحظة قصيرة
    اقرأني.txt بالأرشيف تقول ليش (أحسن من صفحات بأسئلة غلط). بترجّع True لو انعمل المجلد"""
    secs = {tuple(k.rsplit("|", 3)[1:3]) for k in keys if isinstance(k, str) and k.count("|") >= 3}
    if not secs: return None
    why = ""
    try:
        if STATE.get("bank_changed"): why = "أسئلة السيرفر مش أسئلة هذا الامتحان (ملف الأسئلة انبدّل وانشغّل السيرفر من جديد)."
        else: export_static(d, secs)
    except Exception as e:
        why = f"تعذّر تجهيز النتائج: {e!r}"; shutil.rmtree(os.path.join(d, "نتائج"), ignore_errors=True)
    if why:
        try:
            with open(os.path.join(d, "اقرأني.txt"), "w", encoding="utf-8-sig", newline="") as f:
                f.write("".join(x + chr(13) + chr(10) for x in [f"أرشيف امتحان: {SET['title']}   (انحفظ {time.strftime('%Y-%m-%d %H:%M')})", "=" * 40,
                                                                  "هذا المجلد فيه بيانات الامتحان بس، وما انعمل مجلد «نتائج» لأن:", why]))
        except OSError: pass
        print("تنبيه:", why)
    return not why
def archive_all():
    """بداية امتحان جديد: نحفظ كل الملفات القديمة بمجلد أرشيف ونصفّر الحجوزات"""
    d = os.path.join(BASE, "archive_" + time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(d, exist_ok=True)
    keys = set(PAPERS) | set(SUBS) | set(CLAIMS)
    STATE.update(closed_at=0, msg={"id": 0, "text": ""}); STATE.pop("comp", None); STATE.pop("auto_title", None)
    if ANS_DIRTY[0]:                             # آخر إجابات لسا ما انحفظت: نكتبها قبل ما ننقل الملف للأرشيف (هذه الدالة تُستدعى داخل القفل)
        try: atomic_write(ANS_FILE, json.dumps(ANS, ensure_ascii=False))
        except OSError: pass
    for f in (SUBS_FILE, CLAIMS_FILE, PAPERS_FILE, STATE_FILE, ANS_FILE):
        if os.path.exists(f): shutil.move(f, os.path.join(d, os.path.basename(f)))
    if os.path.exists(OUT):                      # ننسخ (مش ننقل) لأنه ممكن يكون مفتوح بـ Excel
        shutil.copy2(OUT, os.path.join(d, os.path.basename(OUT)))
    try: export_results(d, keys)
    except Exception as e: print("تنبيه: تعذّر تجهيز مجلد النتائج:", repr(e))            # الأرشفة نفسها (نقل الملفات) ما لازم تفشل بسبب هاي الإضافة
    CLAIMS.clear(); LIVE.clear(); SUBS.clear(); PAPERS.clear(); ANS.clear(); ANS_DIRTY[0] = False
    reh_reset()                                  # أي بروفة كانت شغّالة بتنتهي مع الامتحان القديم
    STATE["bank_fp"] = BANK_FP; STATE.pop("bank_changed", None)
    if SET.get("auto_title"): new_auto_title()
    else: save_state()
    write_results_csv()
    return d
def new_auto_title():
    """امتحان جديد والعنوان تلقائي: عنوان جديد (حتى ما يتعارض مع الامتحان اللي خلص على نفس الأجهزة)، ونعيد بناء صفحة الطالب والمعاينة فيه"""
    global PAGE, PICK, PREVIEW
    old = SET["title"]
    t = "امتحان " + time.strftime("%d-%m-%Y %H:%M")
    if t == old: t = "امتحان " + time.strftime("%d-%m-%Y %H:%M:%S")
    SET["title"] = t
    try: page, pick = build_page(); prev = build_preview()
    except Exception as e:                               # ما زبط نبني الصفحة: بنضل على العنوان القديم (أحسن من صفحة وعنوان مش متطابقين)
        SET["title"] = old; STATE["auto_title"] = old; save_state(); print("تنبيه: تعذّر تجهيز عنوان جديد للامتحان:", repr(e)); return
    PAGE, PICK, PREVIEW = page, pick, prev; STATE["auto_title"] = t; save_state()
    print("عنوان الامتحان الجديد:", t)

# ---------- بروفة الضغط: كل أجهزة المختبر بتطلب «ابدأ» بنفس اللحظة (حسب ساعة السيرفر، مش ساعة الأجهزة) ----------
# بالذاكرة بس (بتنطفي بإعادة تشغيل السيرفر). كل الدوال هون بتتنادى داخل LOCK. البروفة بتستعمل مسار الطالب الحقيقي (/start و/ping و/submit)
REH_MAX_MIN = 60                              # أطول مدة بتضل فيها البروفة شغّالة (وبتنطفي لحالها)
REH_MAX_DEVS = 300
REH = {"on": False, "until": 0.0, "at": 0.0, "full": False, "gen": 0, "devs": {}, "keys": set(), "arr": {}}
def reh_release():
    """بنفك حجز أسماء البروفة اللي ما سلّمت (ما فيها شغل حقيقي): عشان كل جولة تطلب ورقة جديدة، وعشان ما تضل أسماء محجوزة للامتحان الحقيقي"""
    n = 0
    for k in list(REH["keys"]):
        if k in SUBS: continue
        c = CLAIMS.pop(k, None) is not None; p = PAPERS.pop(k, None) is not None
        n += 1 if (c or p) else 0
        LIVE.pop(k, None)
        if ANS.pop(k, None) is not None: ANS_DIRTY[0] = True
    if n: save_claims(); save_papers()
    return n
def reh_stop(why="أوقفها المشرف"):
    if REH["on"]: print("بروفة الضغط: انطفت (" + why + ")")
    reh_release()
    REH["on"] = False; REH["at"] = 0.0; REH["keys"] = set()
def reh_reset():
    REH.update(on=False, until=0.0, at=0.0, full=False, devs={}, arr={}); REH["keys"] = set()
def reh_tick():
    if REH["on"] and time.time() > REH["until"]: reh_stop("انتهت مدتها")
def reh_assign(dev):
    r = REH["devs"].get(dev)
    if r or len(REH["devs"]) >= REH_MAX_DEVS: return r
    used = set(CLAIMS) | set(PAPERS) | set(SUBS) | {v["key"] for v in REH["devs"].values()}
    for g, secs in ROSTER.items():
        for s, names in secs.items():
            for nm in names:
                k = f'{SET["title"]}|{g}|{s}|{nm}'
                if k not in used:
                    r = {"n": len(REH["devs"]) + 1, "key": k, "grade": g, "section": s, "name": nm, "res": {}}
                    REH["devs"][dev] = r; REH["keys"].add(k)
                    return r
    return None
def reh_command(cmd, d):
    """أمر المشرف من صفحة المراقبة. بيرجّع نص الخطأ أو None"""
    reh_tick()
    try: secs = float(d.get("secs", 60)); mins = float(d.get("mins", 30))
    except (TypeError, ValueError): return "رقم غلط"
    if cmd == "on":
        if not 0.05 <= mins <= REH_MAX_MIN: return "المدة لازم تكون بين 1 و60 دقيقة"
        if SET["needCode"]: return "رمز الدخول مفعّل بـ settings.txt: البروفة بتجرّب الدخول بدون رمز، فعطّله مؤقتاً"
        if STATE["closed_at"]: return "الامتحان مُنهى: اضغط «إعادة فتح الامتحان» أول"
        dirty = len((set(CLAIMS) | set(PAPERS) | set(SUBS)) - REH["keys"])
        if dirty: return f"في {dirty} طالب بدأوا أو سلّموا امتحاناً (أو بيانات قديمة): اضغط «بداية امتحان جديد» أول، والبروفة بتنعمل قبل الامتحان الحقيقي"
        if not REH["on"]: REH["devs"] = {}; REH["arr"] = {}
        REH.update(on=True, until=time.time() + mins * 60, at=0.0, full=False)
        print(f"بروفة الضغط: شغّالة {mins:g} دقيقة — افتحوا على الأجهزة /rehearsal")
    elif cmd == "go":
        if not REH["on"]: return "البروفة مش شغّالة: اضغط «تفعيل البروفة» أول"
        if not REH["devs"]: return "ما في أجهزة جاهزة: افتحوا صفحة البروفة على الأجهزة أول"
        if not 1 <= secs <= 600: return "الموعد لازم يكون بين 1 و600 ثانية"
        if any(v["key"] in SUBS for v in REH["devs"].values()): return "في أجهزة سلّمت بالجولة السابقة: اضغط «بداية امتحان جديد» عشان تعيد البروفة"
        reh_release()
        REH.update(at=time.time() + secs, full=bool(d.get("full")), gen=REH["gen"] + 1, arr={})
        REH["until"] = max(REH["until"], REH["at"] + 300)
        for v in REH["devs"].values(): v["res"] = {}
        print(f"بروفة الضغط: الجولة بعد {secs:g} ث على {len(REH['devs'])} جهاز" + (" (مع حل وتسليم)" if REH["full"] else ""))
    elif cmd == "off": reh_stop()
    else: return "أمر غلط"
    return None
def reh_summary():
    if not REH["devs"] and not REH["on"]: return None
    devs = list(REH["devs"].values()); now = time.time()
    st = [v["res"]["start"] for v in devs if "start" in v["res"]]; sb = [v["res"]["submit"] for v in devs if "submit" in v["res"]]
    ok = [x for x in st if x["ok"]]; ms = sorted(x["ms"] for x in ok); sms = sorted(x["ms"] for x in sb if x["ok"])
    arr = list(REH["arr"].values())
    return {"on": REH["on"], "left": max(0, int(REH["until"] - now)) if REH["on"] else 0, "at_in": round(REH["at"] - now, 1) if REH["at"] > now else None,
            "full": REH["full"], "joined": len(devs), "reported": len(st), "ok": len(ok), "fail": len(st) - len(ok), "papers": sum(1 for v in devs if v["key"] in PAPERS),
            "ms_avg": int(sum(ms) / len(ms)) if ms else None, "ms_p95": ms[min(len(ms) - 1, int(0.95 * len(ms)))] if ms else None, "ms_max": ms[-1] if ms else None,
            "skew_max": max((abs(x["skew"]) for x in st), default=None), "spread_ms": int((max(arr) - min(arr)) * 1000) if len(arr) > 1 else 0,
            "submit_ok": sum(1 for x in sb if x["ok"]), "submit_fail": sum(1 for x in sb if not x["ok"]), "submit_ms_max": sms[-1] if sms else None,
            "fails": [{"n": v["n"], "name": v["name"], "status": v["res"]["start"]["status"]} for v in devs if "start" in v["res"] and not v["res"]["start"]["ok"]][:10]}

# ---------- تجميع البيانات للمراقبة والتقارير ----------
def find_keys():
    idx = {}
    for k in list(CLAIMS) + list(SUBS):
        p = k.split("|")
        if len(p) >= 4: idx[(p[-3], p[-2], p[-1])] = k
    return idx
def student_rows():
    """كل طالب بالقائمة + حالته"""
    idx, now, rows = find_keys(), time.time(), []
    for g, secs in ROSTER.items():
        for s, names in secs.items():
            for n in names:
                k = idx.get((g, s, n)); r = {"grade": g, "section": s, "name": n, "key": k, "status": "none"}
                if k in SUBS:
                    sub = SUBS[k]; r.update(status="done", score=sub["score"], total=sub["total"], leave=sub.get("leave", ""), late=sub.get("late", 0), durtxt=fmt_dur(sub.get("dur")))
                elif k in CLAIMS:
                    lv = LIVE.get(k)
                    if lv:
                        ago = now - lv["t"]
                        r.update(status="live" if ago < 25 else "lost", answered=lv["answered"], total=lv["total"], remain=lv["remain"],
                                 leaveN=lv["leaveN"], leaveSec=lv["leaveSec"], ago=int(ago))
                    else: r.update(status="lost", ago=None)
                    if "paused" in PAPERS.get(k, {}): r["paused"] = int(now - PAPERS[k]["paused"])      # موقوف مؤقتاً من المعلم (ثواني منذ الإيقاف)
                rows.append(r)
    return rows
def question_stats():
    app, cor, wr = Counter(), Counter(), defaultdict(Counter)
    for sub in SUBS.values():
        for n, v in zip(sub["ids"], sub["answers"]):
            if n not in BANK: continue
            app[n] += 1
            if v == BANK[n]["a"]: cor[n] += 1
            else: wr[n][v] += 1
    out = []
    for n, q in BANK.items():
        a = app[n]
        top = wr[n].most_common(1)
        topw = ""
        if top:
            v, c = top[0]
            topw = noimg("بدون إجابة" if v < 0 else f"{L[v]}) {q['o'][v]}") + f"  ({c})"
        pct = round(100 * cor[n] / a) if a else None
        note = ""
        if a >= 5 and pct is not None:
            if pct < 30: note = "نسبة نجاح منخفضة جداً — راجع صياغة السؤال/الجواب"
            elif pct > 95: note = "سهل جداً"
        out.append({"n": n, "level": q["level"], "page": q.get("page", ""), "appeared": a, "pct": pct, "top_wrong": topw, "note": note})
    return out
def section_stats():
    d = defaultdict(list); tot = Counter()
    for r in student_rows():
        tot[(r["grade"], r["section"])] += 1
        if r["status"] == "done": d[(r["grade"], r["section"])].append(r["score"] / r["total"] * 100 if r["total"] else 0)
    res = []
    for (g, s), n in tot.items():
        v = d.get((g, s), [])
        res.append({"grade": g, "section": s, "students": n, "submitted": len(v),
                    "avg": round(sum(v) / len(v), 1) if v else None, "max": round(max(v)) if v else None, "min": round(min(v)) if v else None,
                    "dist": [sum(1 for x in v if lo <= x < lo + 20 or (lo == 80 and x == 100)) for lo in (0, 20, 40, 60, 80)]})
    return res

# ---------- ملف Excel بسيط (بدون مكتبات) ----------
def xlsx_bytes(sheets):
    def col(i):
        s = ""; i += 1
        while i: i, r = divmod(i - 1, 26); s = chr(65 + r) + s
        return s
    def cell(ref, v):
        if isinstance(v, (int, float)) and not isinstance(v, bool): return f'<c r="{ref}"><v>{v}</v></c>'
        t = html.escape(str(v if v is not None else ""))
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{t}</t></is></c>'
    z = io.BytesIO(); zf = zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED)
    n = len(sheets)
    zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + "".join(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(n)) + "</Types>")
    zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    zf.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + "".join(f'<sheet name="{html.escape(nm)}" sheetId="{i+1}" r:id="rId{i+1}"/>' for i, (nm, _, _) in enumerate(sheets)) + "</sheets></workbook>")
    zf.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>' for i in range(n)) + f'<Relationship Id="rId{n+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    zf.writestr("xl/styles.xml", '<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Arial"/></font><font><b/><sz val="11"/><name val="Arial"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    for i, (nm, widths, rows) in enumerate(sheets):
        x = ['<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView rightToLeft="1" workbookViewId="0"/></sheetViews><cols>']
        x += [f'<col min="{j+1}" max="{j+1}" width="{w}" customWidth="1"/>' for j, w in enumerate(widths)]
        x.append("</cols><sheetData>")
        for r, row in enumerate(rows, 1):
            x.append(f'<row r="{r}">' + "".join(cell(f"{col(c)}{r}", v).replace("<c ", '<c s="1" ', 1) if r == 1 else cell(f"{col(c)}{r}", v) for c, v in enumerate(row)) + "</row>")
        x.append("</sheetData></worksheet>")
        zf.writestr(f"xl/worksheets/sheet{i+1}.xml", "".join(x))
    zf.close(); return z.getvalue()
def build_xlsx():
    st = {"done": "سلّم", "live": "يمتحن", "lost": "بدأ ولم يسلّم", "none": "لم يبدأ"}
    sheets = []
    ss = section_stats()
    sheets.append(("ملخص", [10, 10, 12, 12, 14, 12, 12], [["الصف", "الشعبة", "عدد الطلاب", "سلّموا", "المتوسط %", "الأعلى %", "الأقل %"]] + [[r["grade"], r["section"], r["students"], r["submitted"], r["avg"] if r["avg"] is not None else "", r["max"] if r["max"] is not None else "", r["min"] if r["min"] is not None else ""] for r in ss]))
    rows = student_rows()
    for (g, s) in sorted({(r["grade"], r["section"]) for r in rows}):
        sh = [["م", "الاسم", "العلامة", "من", "النسبة %", "الحالة", "الخروج من الصفحة", "التأخير (ث)", "مدة الحل"]]
        for i, r in enumerate([r for r in rows if r["grade"] == g and r["section"] == s], 1):
            if r["status"] == "done": sh.append([i, r["name"], r["score"], r["total"], round(100 * r["score"] / r["total"]) if r["total"] else 0, st["done"], r["leave"], r["late"] or "", r["durtxt"]])
            else: sh.append([i, r["name"], "", "", "", st[r["status"]], "", "", ""])
        sheets.append((f"الشعبة {s}", [5, 40, 10, 8, 12, 16, 22, 12, 16], sh))
    qs = sorted(question_stats(), key=lambda r: (r["pct"] is None, r["pct"] if r["pct"] is not None else 0))
    sheets.append(("تحليل الأسئلة", [8, 10, 10, 12, 14, 50, 45], [["السؤال", "المستوى", "الصفحة", "مرات الظهور", "نسبة الصح %", "أكثر إجابة خاطئة (العدد)", "ملاحظة"]] + [[r["n"], LVL.get(r["level"], ""), r["page"], r["appeared"], r["pct"] if r["pct"] is not None else "", r["top_wrong"], r["note"]] for r in qs]))
    return xlsx_bytes(sheets)

# ---------- صفحات المعلم ----------
CSS = ("<meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>"
       ":root{--p:#14566b;--p2:#0e4355;--ink:#1c2733;--mut:#5d6b7a;--line:#dde3ea;--bg:#f4f6f8;--ok:#1b7f46;--okbg:#e6f6ec;--warn:#9a6200;--warnbg:#fff4d6;--bad:#b3261e;--badbg:#fde8e6}"
       "*{box-sizing:border-box}html{direction:rtl}body{font-family:Tahoma,'Segoe UI',Arial,sans-serif;max-width:1180px;margin:0 auto;padding:0 14px 30px;background:var(--bg);color:var(--ink);line-height:1.6}"
       "h2{color:var(--p);font-size:22px;margin:18px 0 8px}h3{font-size:17px;margin:22px 0 8px}a{color:var(--p)}"
       "table{border-collapse:collapse;width:100%;background:#fff;margin:8px 0 20px;border:1px solid var(--line);border-radius:10px;overflow:hidden}"
       "td,th{border-top:1px solid #e6ebf0;padding:8px 10px;text-align:right;vertical-align:top}th{background:#eef5f8;color:var(--p);border-top:0}"
       ".done{background:#e3f5e9}.live{background:#fff8dc}.lost{background:#fde5e5}.none{color:#888}"
       ".btn{display:inline-block;padding:7px 14px;background:var(--p);color:#fff;border-radius:8px;text-decoration:none;margin:2px;cursor:pointer;border:0;font:inherit;font-size:14px}"
       ".btn:hover{background:var(--p2)}.btn.red{background:var(--bad)}.btn.gray{background:#667}.btn.ghost{background:#fff;color:var(--p);border:1px solid var(--line)}"
       ".cards span{display:inline-block;background:#fff;border:1px solid var(--line);border-radius:8px;padding:8px 14px;margin:4px;font-weight:bold}"
       ".bar{display:inline-block;background:var(--p);height:14px;vertical-align:middle;border-radius:3px}"
       ".tnav{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:14px;flex-wrap:wrap;background:#fff;border-bottom:1px solid var(--line);margin:0 -14px 14px;padding:10px 14px;box-shadow:0 1px 4px #1c273314}"
       ".tnav .brand{font-weight:800;font-size:16px;white-space:nowrap;max-width:36ch;overflow:hidden;text-overflow:ellipsis}"
       ".tnav nav{display:flex;gap:4px;background:#eef2f5;padding:4px;border-radius:12px;overflow-x:auto;max-width:100%}"
       ".tnav nav a{padding:6px 12px;border-radius:9px;color:var(--mut);text-decoration:none;font-size:13px;font-weight:700;white-space:nowrap}"
       ".tnav nav a:hover{color:var(--ink)}.tnav nav a.on{background:#fff;color:var(--p);box-shadow:0 1px 3px #1c27331f}.tnav .lock{margin-inline-start:auto}"
       ".card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:12px 0}"
       ".pagehead{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin:6px 0}.pagehead h2{margin:0}.pagehead small{color:var(--mut)}"
       ".kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}"
       ".kpi{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 14px}.kpi b{display:block;font-size:26px;color:var(--p)}.kpi span{color:var(--mut);font-size:13px}"
       ".kpi.ok b{color:var(--ok)}.kpi.warn b{color:var(--warn)}.kpi.bad b{color:var(--bad)}"
       ".charts{display:grid;grid-template-columns:minmax(220px,300px) 1fr;gap:12px}@media(max-width:700px){.charts{grid-template-columns:1fr}}"
       ".charts h3{margin:0 0 8px;font-size:15px}.donut{display:block;margin:0 auto;max-width:190px}"
       ".hist{display:flex;align-items:flex-end;gap:10px;height:200px;padding:6px 6px 0;border-bottom:1px solid var(--line)}"
       ".hist .col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}.hist .col i{display:block;width:70%;max-width:72px;border-radius:6px 6px 0 0}.hist .col b{font-size:13px}"
       ".histlab{display:flex;gap:10px}.histlab span{flex:1;text-align:center;font-size:12px;color:var(--mut)}"
       ".badge{display:inline-block;padding:1px 9px;border-radius:99px;font-size:12px;font-weight:700}.badge.hard{background:var(--badbg);color:var(--bad)}.badge.medium{background:var(--warnbg);color:var(--warn)}.badge.easy{background:var(--okbg);color:var(--ok)}"
       ".pct{display:flex;align-items:center;gap:8px}.pct i{display:block;height:8px;border-radius:99px;background:var(--ok)}.pct i.mid{background:#d49b20}.pct i.low{background:var(--bad)}"
       "select{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:#fff}[hidden]{display:none!important}"
       ".tw{overflow-x:auto;margin:8px 0 20px}.tw table{margin:0;min-width:640px}"
       "@media print{.noprint{display:none}.tnav{display:none}body{background:#fff;max-width:none;margin:0;padding:0}.card,.kpi,table{border-radius:0}.tw{overflow:visible}.tw table{min-width:0}}"
       "</style>")
TABS = (("monitor", "/monitor", "المراقبة الحية"), ("report", "/report", "التقارير والتحليل"), ("sheet", "/sheet", "ورقات الطلاب"), ("key", "/key", "مفتاح الإجابات"),
        ("codes", "/codes", "رموز الدخول"), ("health", "/health", "فحص السيرفر"), ("teacher", "/teacher", "معاينة الامتحان"))
def teacher_nav(active):
    """شريط تنقل واحد لكل صفحات المعلم (مخفي بالطباعة): اسم الامتحان + التبويبات، وزر القفل لو في كلمة سر. رموز الدخول بتبين بس لو مفعّلة"""
    tabs = "".join(f"<a href={u}{' class=on aria-current=page' if k == active else ''}>{n}</a>" for k, u, n in TABS if k != "codes" or SET["needCode"])
    lock = " <a class='btn ghost lock' href=/logout>🔒 قفل</a>" if SET["tpass"] else ""
    return f"<header class='tnav noprint'><div class=brand>{html.escape(SET['title'])}</div><nav>{tabs}</nav>{lock}</header>"
def teacher_page(body, active, title="", head=""):
    """صفحة معلم كاملة: الستايل المشترك + شريط التنقل + المحتوى"""
    return "<!doctype html>" + CSS + head + f"<title>{html.escape(title)}</title>" + "<body>" + teacher_nav(active) + body
MONITOR_UI = os.path.join(BASE, "monitor_ui")     # واجهة المراقبة الجديدة: ملفات ثابتة جاهزة (مصدرها tools/monitor_ui_src). لو المجلد مش موجود بتنعرض الصفحة القديمة
_UI_TYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
             ".json": "application/json; charset=utf-8", ".ico": "image/x-icon", ".png": "image/png", ".txt": "text/plain; charset=utf-8"}
def student_link(): return f"http://{ip()}{'' if PORT == 80 else ':' + str(PORT)}"
def monitor_ui_page():
    """صفحة المراقبة الجديدة مع رابط الطلاب وعنوان الامتحان (بنبدّل window.MONITOR_CONFIG بالصفحة الجاهزة). None لو ملفات الواجهة مش موجودة"""
    try:
        with open(os.path.join(MONITOR_UI, "index.html"), encoding="utf-8") as f: page = f.read()
    except OSError: return None
    tabs = [[u, n] for k, u, n in TABS if k != "codes" or SET["needCode"]]                                              # نفس تبويبات شريط التنقل بصفحات المعلم الثانية (مصدر واحد)
    cfg = json.dumps({"link": student_link(), "title": SET["title"], "tabs": tabs, "lock": bool(SET["tpass"])}, ensure_ascii=False).replace("<", "\\u003c")     # العنوان نص من المعلم: ما بنسمح بإغلاق وسم script
    return re.sub(r"window\.MONITOR_CONFIG\s*=\s*\{.*?\};", lambda m: "window.MONITOR_CONFIG = " + cfg + ";", page, count=1, flags=re.S)
def monitor_ui_asset(rel):
    """ملف ثابت من مجلد monitor_ui (جوّا المجلد بس، حتى لو فيه .. أو رابط رمزي): (بايتات، نوع المحتوى) أو None"""
    if "\\" in rel or "\x00" in rel: return None
    root = os.path.realpath(MONITOR_UI)
    try: p = os.path.realpath(os.path.join(root, *[x for x in rel.split("/") if x]))
    except (ValueError, OSError): return None
    if not p.startswith(root + os.sep) or not os.path.isfile(p) or os.path.splitext(p)[1].lower() not in _UI_TYPES: return None
    with open(p, "rb") as f: return f.read(), _UI_TYPES[os.path.splitext(p)[1].lower()]
def monitor_old_page():
    """صفحة المراقبة القديمة: بتضل شغّالة على /monitor-old، وبتنعرض على /monitor لو مجلد monitor_ui مش موجود"""
    return MONITOR.replace("__LINK__", student_link()).replace("__TITLE__", html.escape(SET["title"]))
MONITOR = """<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>مراقبة الامتحان</title>
<style>
:root{--ink:#1c2733;--mut:#667788;--line:#dde3ea;--pri:#14566b;--ok:#1b7f4b;--okbg:#e6f6ec;--live:#9a6b00;--livebg:#fff6d9;--bad:#b3261e;--badbg:#fde8e6;--none:#7a8794;--nonebg:#f1f3f5}
*{box-sizing:border-box}body{margin:0;background:#f4f6f8;color:var(--ink);font-family:Tahoma,"Segoe UI",Arial,sans-serif;line-height:1.6}
.top{background:var(--pri);color:#fff;padding:14px 20px}.top h1{margin:0;font-size:22px}.top small{opacity:.85}
.nav{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.nav a{background:rgba(255,255,255,.15);color:#fff;text-decoration:none;padding:7px 14px;border-radius:8px;font-size:15px}.nav a:hover{background:rgba(255,255,255,.28)}
.wrap{max-width:1150px;margin:0 auto;padding:16px}
.linkbox{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 16px;display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-bottom:14px}
.linkbox b{font-size:15px;color:var(--mut)}.linkbox code{direction:ltr;font-size:20px;font-weight:bold;color:var(--pri);background:#eef5f8;padding:4px 12px;border-radius:8px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:10px}
.card{border-radius:12px;padding:12px 16px;border:1px solid var(--line);background:#fff;cursor:pointer;user-select:none}
.card .n{font-size:34px;font-weight:bold;line-height:1.1}.card .t{font-size:14px;color:var(--mut)}
.card.ok{background:var(--okbg);color:var(--ok)}.card.live{background:var(--livebg);color:var(--live)}.card.bad{background:var(--badbg);color:var(--bad)}.card.none{background:var(--nonebg);color:var(--none)}
.card.sel{outline:3px solid var(--pri)}
.prog{height:10px;background:#e3e8ee;border-radius:6px;overflow:hidden;margin:4px 0 14px}.prog i{display:block;height:100%;background:var(--ok);transition:width .4s}
.tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:12px}
.tools input{flex:1;min-width:200px;padding:9px 12px;border:1px solid var(--line);border-radius:8px;font:inherit}
.chip{padding:7px 14px;border:1px solid var(--line);background:#fff;border-radius:20px;cursor:pointer;font-size:14px}.chip.sel{background:var(--pri);color:#fff;border-color:var(--pri)}
.sec{background:#fff;border:1px solid var(--line);border-radius:12px;margin-bottom:12px;overflow:hidden}
.sec>summary{list-style:none;cursor:pointer;padding:12px 16px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;background:#fafbfc}
.sec>summary::-webkit-details-marker{display:none}.sec>summary::before{content:'◀';font-size:13px;color:var(--mut);transition:transform .2s}.sec[open]>summary::before{transform:rotate(-90deg)}.sec>summary:hover{background:#f1f5f8}.sec>summary .hint{margin-inline-start:auto;font-size:13px;color:var(--mut)}
.sec h3{margin:0;font-size:18px}.sec .cnt{color:var(--mut);font-size:14px}.sec .bar{flex:1;min-width:120px;max-width:260px}
table{border-collapse:collapse;width:100%}th{background:#f1f5f8;color:var(--mut);font-weight:normal;font-size:13px;text-align:right;padding:8px 12px}
td{padding:9px 12px;border-top:1px solid var(--line);text-align:right;vertical-align:middle}
tr.ok td:first-child,tr.live td:first-child,tr.bad td:first-child{border-right:5px solid transparent}
tr.ok td:first-child{border-right-color:var(--ok)}tr.live td:first-child{border-right-color:#e0a800}tr.bad td:first-child{border-right-color:var(--bad)}
.badge{display:inline-block;padding:2px 12px;border-radius:14px;font-size:13px;font-weight:bold}
.badge.ok{background:var(--okbg);color:var(--ok)}.badge.live{background:var(--livebg);color:var(--live)}.badge.bad{background:var(--badbg);color:var(--bad)}.badge.none{background:var(--nonebg);color:var(--none)}
.mini{display:inline-block;width:90px;height:8px;background:#e3e8ee;border-radius:5px;overflow:hidden;vertical-align:middle;margin-inline-start:8px}.mini i{display:block;height:100%;background:#2d8fb0}
.warn{color:#b45f00;font-weight:bold}.mut{color:var(--mut)}.score{font-size:18px;font-weight:bold;direction:ltr;display:inline-block}
.btn{display:inline-block;padding:6px 12px;border-radius:8px;border:1px solid var(--pri);background:var(--pri);color:#fff;text-decoration:none;cursor:pointer;font:inherit;font-size:14px}
.btn.o{background:#fff;color:var(--pri)}.btn.r{background:#fff;color:var(--bad);border-color:var(--bad)}
.foot{margin-top:26px;padding-top:14px;border-top:1px dashed var(--line);display:flex;flex-wrap:wrap;gap:14px;align-items:center;color:var(--mut);font-size:14px}
.empty{padding:30px;text-align:center;color:var(--mut)}
.comp{background:#e8f2f5;color:#14566b;border:1px solid #9cc6d4;border-radius:10px;padding:10px 16px;margin-bottom:12px;font-weight:bold}.comp.sk{background:var(--livebg);color:var(--live);border-color:#e0a800}
.closed{background:var(--badbg);color:var(--bad);border:1px solid var(--bad);border-radius:10px;padding:10px 16px;margin-bottom:12px;font-weight:bold}
.sec>summary .btn{font-size:12px;padding:3px 10px;margin-inline-start:6px}
.reh{background:#fff;border:1px solid var(--line);border-radius:12px;margin-bottom:12px}.reh>summary{cursor:pointer;padding:12px 16px}.rehin{padding:0 16px 12px}
.rehtools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:8px 0}.rehtools select{padding:7px 10px;border:1px solid var(--line);border-radius:8px;font:inherit}.reh table{margin:8px 0}
</style>
<div class=top><div class=wrap style="padding:0"><h1>مراقبة الامتحان</h1><small id=ttl>__TITLE__</small>
<div class=nav><a href=/report>📊 التقرير والتحليل</a><a href=/report.xlsx>⬇ تنزيل Excel</a><a href=/sheet>🖨 ورقات الطلاب / طباعة</a><a href=/key>🔑 مفتاح الإجابات</a><a href=/codes>🔢 رموز دخول الطلاب</a><a href=/teacher>🔍 معاينة الامتحان كاملاً</a><a href=/health>🩺 فحص السيرفر</a></div></div></div>
<div class=wrap>
<div class=linkbox><b>رابط الامتحان للطلاب:</b><code id=lnk>__LINK__</code><button class=btn onclick="cp()" id=cpb>نسخ الرابط</button><a class="btn o" href=/link target=_blank>عرض بخط كبير</a></div>
<div class=cards id=cards></div><div class=prog><i id=pg style="width:0"></i></div>
<div id=compbar class=comp style="display:none"></div>
<div id=bankbar class=closed style="display:none"></div>
<div id=closedbar class=closed style="display:none">⏹ الامتحان منتهٍ — الطلاب يُسلَّمون تلقائياً ولا يمكن البدء. <a href="#" onclick="closeExam(false);return false">إعادة فتح الامتحان</a></div>
<div class=tools><input id=q placeholder="🔍 ابحث عن اسم طالب..." oninput="draw()"><button class="btn o" onclick="allSec(true)">فتح كل الشعب</button><button class="btn o" onclick="allSec(false)">طي كل الشعب</button><span class=mut id=upd></span></div>
<div class=tools><button class="btn o" onclick="ext('all')">⏱ تمديد الوقت للجميع</button><button class="btn o" onclick="msg()">📢 رسالة للطلاب</button><button class="btn r" onclick="closeExam(true)">⏹ إنهاء الامتحان للجميع</button><button class="btn o" onclick="subAll()">📥 تسليم من لم يسلّم</button><span class=mut id=lastmsg></span></div>
<details class=reh id=rehbox><summary><b>🧪 بروفة الضغط</b> <span class=mut id=rehsum>— مطفية</span></summary><div class=rehin>
<p class=mut>كل أجهزة المختبر بتطلب «ابدأ» بنفس اللحظة حسب <b>ساعة السيرفر</b> (مش ساعة الأجهزة)، وبتشوف هون النتيجة. ① فعّلها. ② افتح على كل جهاز <b dir=ltr>__LINK__/rehearsal</b> وخلّي الشاشة شغّالة. ③ اضغط «ابدأ الجولة». ④ بعد ما تخلص اضغط زر الأرشفة والتصفير الأحمر أسفل الصفحة. بتنفع قبل الامتحان بس: لو في طلاب بدأوا ما بتتفعّل.</p>
<div class=rehtools><button class="btn o" id=rehon onclick="reh({rehearsal:'on'})">تفعيل البروفة (30 دقيقة)</button><select id=rehsecs><option value=30>بعد 30 ث</option><option value=60 selected>بعد 60 ث</option><option value=120>بعد 120 ث</option></select><label><input type=checkbox id=rehfull> حل عشوائي وتسليم</label><button class=btn id=rehgo onclick="rehGo()">▶ ابدأ الجولة</button><button class="btn r" onclick="reh({rehearsal:'off'})">إيقاف البروفة</button></div>
<div id=rehstat></div></div></details>
<div id=tbl></div>
<div class=foot><span>قبل ما تبدأ امتحان جديد: اطبع ورقات الطلاب ونزّل ملف النتائج أولاً، لأن هذا الزر بيصفّر الشاشة.</span>
<a class="btn r" href="#" onclick="newExam();return false">بداية امتحان جديد (أرشفة + تصفير)</a></div></div>
<script>
const ST={none:'لم يبدأ',live:'يمتحن',lost:'انقطع الاتصال',done:'سلّم'},CLS={none:'none',live:'live',lost:'bad',done:'ok'};
let J=null,FILTER='all',OPEN={};
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=s=>s==null?'':Math.floor(s/60)+':'+String(s%60).padStart(2,'0');
function cp(){navigator.clipboard&&navigator.clipboard.writeText(document.getElementById('lnk').textContent).then(()=>{const b=document.getElementById('cpb');b.textContent='تم النسخ ✓';setTimeout(()=>b.textContent='نسخ الرابط',1500)})}
async function act(o){await fetch('/monitor',{method:'POST',headers:{'Content-Type':'application/json','X-Exam-Action':'1'},body:JSON.stringify(o)});load()}
function releaseSt(k){if(confirm('فك الحجز بيخلّي الطالب يبدأ من جديد (من أي جهاز، حتى نفس الجهاز) بورقة ووقت جديدين، وبتضيع إجاباته السابقة، وصفحته الحالية بترجع لشاشة الدخول لحالها. متأكد؟\\nإذا بدك يكمل بنفس أسئلته وإجاباته ووقته المتبقي استخدم «نقل لجهاز آخر» بدل هذا.'))act({release:decodeURIComponent(k)})}
function mv(k){if(confirm('نقل الطالب لجهاز آخر: بيكمل بنفس الأسئلة والإجابات المحفوظة والوقت اللي كان باقيله، بعد ما يختار اسمه من الجهاز الجديد'+'.\\nلازم يكون الطالب جاهز على الجهاز الجديد (الاسم بيصير متاحاً لأي حدا لحد ما يبدأ؛ فعّل رمز الدخول لو بدك حماية). متأكد؟'))act({move:decodeURIComponent(k)})}
function newExam(){if(confirm('بداية امتحان جديد؟\\nبنحفظ النتائج الحالية بمجلد أرشيف وبنصفّر الحجوزات والشاشة.\\nتأكد إنك طبعت الأوراق ونزّلت Excel.')&&confirm('تأكيد أخير: تصفير الامتحان الحالي؟'))act({newexam:1})}
function ext(scope,key,grade,section){
 const lbl={all:'كل الطلاب اللي بدأوا ولم يسلّموا',section:'طلاب هذه الشعبة اللي بدأوا ولم يسلّموا',student:'هذا الطالب'}[scope];
 const m=parseInt(prompt('كم دقيقة تضيف لـ '+lbl+'؟ (1 – 120)\\nملاحظة: التمديد لازم يكون قبل ما ينتهي وقت الطالب.','5'),10);
 if(!m)return;if(m<1||m>120){alert('الرقم لازم يكون بين 1 و120');return}
 act({extend:m,scope:scope,key:key,grade:grade,section:section})}
function sub(k){if(confirm('تسليم إجابات هذا الطالب (المحفوظة على السيرفر) الآن وتصحيحها؟\\nالأسئلة اللي ما أجاب عنها بتنحسب خاطئة، وما بيقدر يكمل بعدها.'))act({submitfor:decodeURIComponent(k)})}
function subAll(){if(!J)return;const n=J.c.live+J.c.lost;if(!n){alert('ما في طلاب بدأوا ولم يسلّموا');return}
 if(confirm('تسليم '+n+' طالب بدأوا ولم يسلّموا (بما فيهم من يمتحن الآن) بإجاباتهم المحفوظة على السيرفر؟\\nالأفضل تضغط «إنهاء الامتحان للجميع» أولاً وتنتظر دقيقة ليسلّموا بأنفسهم، ثم تسلّم الباقي.\\nالأسئلة بدون إجابة بتنحسب خاطئة.'))act({submitfor:'all'})}
function msg(){const t=prompt('اكتب الرسالة (بتظهر على شاشة كل طالب يمتحن الآن):');if(t&&t.trim())act({message:t})}
function closeExam(v){if(v?confirm('إنهاء الامتحان للجميع؟ كل صفحة طالب بتسلّم تلقائياً خلال ثواني، ولا يقدر أحد يبدأ.'):confirm('إعادة فتح الامتحان؟ اللي سلّموا تلقائياً يبقى تسليمهم، واللي ما سلّموا يرجع إلهم وقتهم.'))act({close:v})}
function bankOk(){if(confirm('متأكد إن هذا نفس الامتحان وبس صلّحت أسئلة؟\\nإذا امتحان جديد اضغط «بداية امتحان جديد» بدل هذا.'))act({bankok:1})}
function allSec(v){if(J)for(const k of Object.keys(J.sections))OPEN[k]=v;draw()}
function setF(f){FILTER=FILTER===f?'all':f;draw()}
function draw(){
 if(!J)return;const c=J.c,tot=c.done+c.live+c.lost+c.none;
 const card=(k,cls,n,t)=>`<div class="card ${cls} ${FILTER===k?'sel':''}" onclick="setF('${k}')"><div class=n>${n}</div><div class=t>${t}</div></div>`;
 document.getElementById('cards').innerHTML=card('done','ok',c.done,'سلّموا')+card('live','live',c.live,'يمتحنون الآن')+card('lost','bad',c.lost,'انقطع اتصالهم')+card('none','none',c.none,'لم يبدأوا');
 document.getElementById('pg').style.width=(tot?Math.round(100*c.done/tot):0)+'%';
 document.getElementById('closedbar').style.display=J.closed?'block':'none';
 {const bb=document.getElementById('bankbar'),b=J.bank_changed;if(b){bb.innerHTML='⚠ ملف الأسئلة تغيّر بعد آخر امتحان، والسيرفر لسا فيه بيانات الامتحان السابق ('+b.subs+' تسليم و'+b.papers+' ورقة). إذا هذا <b>امتحان جديد</b>: اضغط «بداية امتحان جديد» (أسفل الصفحة) قبل ما يدخل الطلاب. إذا بس صلّحت سؤال بنفس الامتحان: <a href="#" onclick="bankOk();return false">هذا نفس الامتحان (أخفِ التنبيه)</a>';bb.style.display='block'}else bb.style.display='none'}
 {const cb=document.getElementById('compbar'),c=J.comp;if(c){const W=c.sleep?'جهاز السيرفر نام أو تجمّد ':'السيرفر كان متوقفاً ',m=Math.floor(c.downtime_s/60),s=c.downtime_s%60,t=(m?m+' دقيقة و':'')+s+' ثانية';cb.className=c.skipped||c.off?'comp sk':'comp';
  cb.textContent=c.skipped?('⚠ '+W+t+' (أطول من 30 دقيقة): ما عوّضنا الوقت تلقائياً. استعمل «⏱ تمديد الوقت للجميع» إذا لزم.'):c.off?('⚠ '+W+t+' والتعويض التلقائي مطفّأ (تعويض_توقف_السيرفر = لا). استعمل «⏱ تمديد الوقت للجميع» إذا لزم.'):('ℹ '+W+t+': مدّدنا تلقائياً وقت '+c.students+' طالب (اللي لم يسلّموا) بنفس المدة، فما خسروا شيئاً.');cb.style.display='block'}else cb.style.display='none'}
 document.getElementById('lastmsg').textContent=J.msg?'آخر رسالة: «'+J.msg+'»':'';
 const q=document.getElementById('q').value.trim();let h='';
 for(const [k,rows0] of Object.entries(J.sections)){
  const rows=rows0.filter(r=>(FILTER==='all'||r.status===FILTER)&&(!q||r.name.includes(q)));
  const dn=rows0.filter(r=>r.status==='done').length,lv=rows0.filter(r=>r.status==='live').length;
  if(!rows.length&&(q||FILTER!=='all'))continue;
  const busy=rows0.some(r=>r.status==='live'||r.status==='lost');const open=(q||FILTER!=='all')?true:(OPEN[k]!==undefined?OPEN[k]:busy);
  h+=`<details class=sec data-k="${esc(k)}" ${open?'open':''} ontoggle="if(!document.getElementById('q').value&&FILTER==='all')OPEN[this.dataset.k]=this.open"><summary><h3>${esc(k)}</h3><span class=cnt>سلّم ${dn} من ${rows0.length}${lv?' • يمتحن '+lv:''}</span><span class="prog bar" style="margin:0"><i style="width:${rows0.length?Math.round(100*dn/rows0.length):0}%"></i></span><span class=hint>${rows0.some(r=>r.status==='live')?`<button class="btn o" onclick="event.preventDefault();event.stopPropagation();ext('section',null,'${esc(rows0[0].grade)}','${esc(rows0[0].section)}')">⏱ تمديد الشعبة</button>`:'اضغط للفتح/الطي'}</span></summary>`;
  h+=`<table><tr><th>الاسم</th><th>الحالة</th><th>التقدّم</th><th>الوقت المتبقي</th><th>خرج من الصفحة</th><th>العلامة</th><th></th></tr>`;
  for(const r of rows){
   const cl=CLS[r.status];let prog='',lvv='';
   if(r.status==='live'||(r.status==='lost'&&r.answered!=null))prog=`${r.answered}/${r.total}<span class=mini><i style="width:${r.total?Math.round(100*r.answered/r.total):0}%"></i></span>`;
   if(r.status==='live')lvv=r.leaveN?`<span class=warn>⚠ ${r.leaveN} مرة — ${r.leaveSec} ث</span>`:'<span class=mut>—</span>';
   else if(r.status==='lost')lvv=r.leaveN?`<span class=warn>⚠ ${r.leaveN} مرة — ${r.leaveSec} ث</span>`:'';
   else if(r.status==='done'){lvv=(r.leave&&r.leave!=='لم يخرج')?`<span class=warn>⚠ ${esc(r.leave.replace(/\\((\\d+) ث\\)/,'— $1 ث'))}</span>`:'<span class=mut>لم يخرج</span>';if(r.late)lvv+=` <span class=warn>⏱ متأخر ${r.late} ث</span>`}
   const kk=r.key?encodeURIComponent(r.key).replace(/'/g,'%27'):'';
   let act='';
   if(r.status==='done')act=`<a class="btn o" target=_blank href="/sheet?key=${kk}">فتح الورقة</a>`;
   else if(r.status==='live'||r.status==='lost')act=`<a class="btn o" href="#" onclick="ext('student',decodeURIComponent('${kk}'));return false">+ وقت</a> <a class="btn o" href="#" onclick="mv('${kk}');return false" title="يكمل بنفس الأسئلة والإجابات والوقت المتبقي من جهاز آخر">نقل لجهاز آخر</a> <a class="btn o" href="#" onclick="sub('${kk}');return false" title="يصحّح إجاباته المحفوظة على السيرفر ويسجّلها كتسليم">تسليم عنه</a> <a class="btn r" href="#" onclick="releaseSt('${kk}');return false" title="للسماح للطالب بالبدء من جهاز آخر">فك الحجز</a>`;
   h+=`<tr class=${cl}><td>${esc(r.name)}</td><td><span class="badge ${cl}">${ST[r.status]}</span>${r.status==='lost'&&r.ago!=null?` <span class=mut>منذ ${r.ago} ث</span>`:''}</td><td>${prog}</td><td>${r.status==='live'?fmt(r.remain):(r.status==='done'&&r.durtxt?`<span class=mut>استغرق ${esc(r.durtxt)}</span>`:'')}</td><td>${lvv}</td><td>${r.status==='done'?`<span class=score>${r.score} / ${r.total}</span>`:''}</td><td>${act}</td></tr>`;
  }
  h+=rows.length?'</table>':'</table><div class=empty>لا نتائج</div>';h+='</details>';
 }
 document.getElementById('tbl').innerHTML=h||'<div class=empty>لا نتائج مطابقة</div>';
 document.getElementById('upd').textContent='آخر تحديث: '+new Date().toLocaleTimeString('en-GB');
 rehDraw();
}
async function reh(o){const r=await fetch('/monitor',{method:'POST',headers:{'Content-Type':'application/json','X-Exam-Action':'1'},body:JSON.stringify(o)});if(!r.ok){let m='';try{m=(await r.json()).error}catch(e){}alert(m||'ما زبط')}load()}
function rehGo(){reh({rehearsal:'go',secs:parseInt(document.getElementById('rehsecs').value,10),full:document.getElementById('rehfull').checked})}
function rehDraw(){
 const R=J.reh,s=document.getElementById('rehsum'),t=document.getElementById('rehstat');
 document.getElementById('rehon').disabled=!!(R&&R.on);document.getElementById('rehgo').disabled=!(R&&R.on&&R.joined);
 if(!R){s.textContent='— مطفية';t.innerHTML='';return}
 let sm=R.on?'— شغّالة (بتنطفي بعد '+Math.ceil(R.left/60)+' د) • أجهزة مسجّلة: '+R.joined:'— مطفية';
 if(R.at_in)sm+=' • الجولة بعد '+Math.ceil(R.at_in)+' ث';
 s.textContent=sm;
 let h='';
 if(R.joined){
  const f=x=>x==null?'—':x+' م.ث';
  h+='<table><tr><th>أجهزة مسجّلة</th><th>بدأوا بنجاح</th><th>فشلوا</th><th>أوراق انعملت بالسيرفر</th><th>وقت الرد (متوسط / 95% / أبطأ)</th><th>فرق وصول الطلبات للسيرفر</th><th>أكبر تأخر جهاز عن الموعد</th></tr><tr><td>'+R.joined+'</td><td>'+R.ok+' من '+R.reported+'</td><td>'+(R.fail?'<b class=warn>'+R.fail+'</b>':0)+'</td><td>'+R.papers+'</td><td>'+f(R.ms_avg)+' / '+f(R.ms_p95)+' / '+f(R.ms_max)+'</td><td>'+f(R.spread_ms)+'</td><td>'+f(R.skew_max)+'</td></tr></table>';
  if(R.full)h+='<p class=mut>التسليم: نجح '+R.submit_ok+'، فشل '+R.submit_fail+'، أبطأ تسليم '+f(R.submit_ms_max)+'</p>';
  if(R.fails&&R.fails.length)h+='<p class=warn>فشل: '+R.fails.map(x=>esc('جهاز '+x.n+' ('+x.name+') — '+x.status)).join('، ')+'</p>';
  if(!R.on||R.reported)h+='<p class=mut>بعد ما تخلص: اضغط زر الأرشفة والتصفير الأحمر أسفل الصفحة عشان تصفّر.</p>'
 }
 t.innerHTML=h;
}
async function load(){try{J=await (await fetch('/monitor.json')).json();draw()}catch(e){document.getElementById('upd').textContent='⚠ انقطع الاتصال بالسيرفر'}}
load();setInterval(load,4000);
</script>"""
REHEARSAL_PAGE = r"""<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>بروفة الضغط</title>
<style>
body{margin:0;padding:18px;background:#f4f6f8;color:#1c2733;font-family:Tahoma,"Segoe UI",Arial,sans-serif;text-align:center;line-height:1.7}
.card{max-width:460px;margin:0 auto;background:#fff;border:1px solid #dde3ea;border-radius:16px;padding:18px}
h1{font-size:20px;margin:0 0 6px;color:#14566b}
#big{font-size:76px;font-weight:bold;color:#14566b;direction:ltr;line-height:1.1;margin:10px 0}
#msg{font-size:18px;min-height:30px}.mut{color:#667788;font-size:14px}
.ok{color:#1b7f4b;font-weight:bold}.bad{color:#b3261e;font-weight:bold}
table{margin:12px auto 0;border-collapse:collapse;font-size:15px}td{padding:4px 12px;border-top:1px solid #eee}
</style>
<div class=card>
<h1>🧪 بروفة الضغط</h1>
<div class=mut>خلّي هالصفحة مفتوحة والشاشة شغّالة، ولا تطلع منها. المشرف بيبدأ الجولة من جهاز السيرفر.</div>
<div id=who class=mut style="margin-top:8px">...</div>
<div id=big>--</div>
<div id=msg></div>
<table id=res></table>
<div class=mut id=sync style="margin-top:10px"></div>
</div>
<script>
const $=id=>document.getElementById(id);
let DEV;try{DEV=localStorage.getItem('rehearsal|dev');if(!DEV){DEV='r'+Math.random().toString(36).slice(2,12)+Date.now().toString(36);localStorage.setItem('rehearsal|dev',DEV)}}catch(e){DEV='r'+Math.random().toString(36).slice(2,12)}
let S=[],off=0,rtt=0,me=null,st=null,lastAt=0,timer=null,pingT=null,P=null,busy=false;
const post=async(u,o)=>{const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});let j=null;try{j=await r.json()}catch(e){}return{http:r.status,j}};
const rep=o=>post('/rehearsal/report',Object.assign({dev:DEV},o)).catch(()=>{});
function row(label,ok,text){$('res').insertAdjacentHTML('beforeend','<tr><td>'+label+'</td><td class='+(ok?'ok':'bad')+'>'+(ok?'✓ ':'✗ ')+text+'</td></tr>')}
function stopRun(){clearInterval(pingT);clearTimeout(timer);P=null}
async function join(){const o=await post('/rehearsal/join',{dev:DEV});if(o.j&&o.j.status==='ok')me=o.j;else if(o.j&&o.j.status==='full')$('msg').textContent='ما في أسماء فاضية بقائمة الطلاب لهالجهاز'}
async function poll(){
 try{
  const t0=Date.now(),r=await fetch('/rehearsal.json?t='+t0,{cache:'no-store'}),t1=Date.now(),j=await r.json();
  S.push({rtt:t1-t0,off:j.now*1000-(t0+t1)/2});if(S.length>8)S.shift();
  const b=S.reduce((a,y)=>y.rtt<a.rtt?y:a);off=b.off;rtt=b.rtt;st=j;
  if(!j.on){if(me){me=null;stopRun();lastAt=0}}
  else{
   if(!me)await join();
   if(me&&j.at&&j.at!==lastAt){lastAt=j.at;schedule(j)}
  }
  draw();
 }catch(e){$('msg').textContent='⚠ انقطع الاتصال بالسيرفر'}
}
function draw(){
 if(!st)return;
 $('who').textContent=!st.on?'البروفة مطفية حالياً: المشرف بيشغّلها من صفحة المراقبة.':me?('جهاز رقم '+me.n+' — الاسم: '+me.name+' ('+me.grade+' '+me.section+')'):'جارٍ التسجيل...';
 $('sync').textContent='فرق ساعة هالجهاز عن ساعة السيرفر: '+(off/1000).toFixed(1)+' ث • تأخر الشبكة: '+Math.round(rtt)+' م.ث';
 if(!busy&&!P&&!$('msg').dataset.keep)$('msg').textContent=!st.on?'':me?(st.at&&st.at*1000-off>Date.now()-2000?'جاهز: البدء بنفس اللحظة مع باقي الأجهزة'+(st.full?' (مع حل عشوائي وتسليم)':''):'جاهز ✓ استنّى المشرف يبدأ الجولة'):''
}
function tickUI(){
 if(busy||P)return;
 if(!st||!st.on){$('big').textContent='--';return}
 if(!me){$('big').textContent='...';return}
 const left=(st.at*1000-off-Date.now())/1000;
 if(!st.at||left<-2){$('big').textContent='✓';return}
 $('big').textContent=left>0?Math.ceil(left):'الآن'
}
setInterval(tickUI,100);
function schedule(j){
 const target=j.at*1000-off,d=target-Date.now();
 $('res').innerHTML='';delete $('msg').dataset.keep;
 if(d<-1500){$('msg').textContent='فاتك موعد هالجولة: استنّى الجولة الجاية';$('msg').dataset.keep=1;return}
 clearTimeout(timer);timer=setTimeout(()=>{while(Date.now()<target){}fire(j,target)},Math.max(0,d-40));
}
async function fire(j,target){
 if(!me)return;
 const skew=Date.now()-target;busy=true;$('msg').textContent='جارٍ طلب الورقة...';
 const t0=performance.now();let o;try{o=await post('/start',{key:me.key,dev:DEV})}catch(e){o={http:0,j:{status:'network'}}}
 const ms=Math.round(performance.now()-t0),r=o.j||{},ok=r.status==='ok';
 await rep({stage:'start',ok,ms,status:ok?'ok':(r.status||('http'+o.http)),skew:Math.round(skew),rtt:Math.round(rtt)});
 row('بدء الامتحان',ok,ms+' م.ث'+(ok?' ('+r.ids.length+' سؤال)':' — '+(r.status||o.http))+' • انطلق بفرق '+Math.round(skew)+' م.ث عن الموعد');
 busy=false;
 if(!ok){$('msg').textContent='فشل الطلب ✗';$('msg').dataset.keep=1;return}
 P=r;P.mine={};P.full=!!j.full;P.at=j.at;$('msg').textContent=j.full?'جارٍ الحل العشوائي...':'نجح ✓ (الجهاز بيرسل نبضات مثل الطالب)';$('big').textContent='✓';
 runLoop(P)
}
function runLoop(p){
 clearInterval(pingT);const myAt=p.at;
 const step=async()=>{
  if(!st||!st.on||st.at!==myAt||P!==p){stopRun();return}
  p.qs.filter(q=>p.mine[q.n]===undefined).slice(0,6).forEach(q=>{p.mine[q.n]=Math.floor(Math.random()*q.o.length)});
  const answered=Object.keys(p.mine).length;
  if(p.full&&answered>=p.qs.length){clearInterval(pingT);await submit(p);return}
  try{await post('/ping',{key:me.key,dev:DEV,ans:p.mine,answered:answered,total:p.qs.length,remain:p.remain,leaveN:0,leaveSec:0})}catch(e){}
 };
 pingT=setInterval(step,8000);step()
}
async function submit(p){
 $('msg').textContent='جارٍ التسليم...';
 const answers=p.ids.map(n=>p.mine[n]!==undefined?p.mine[n]:0);
 const t0=performance.now();let o;try{o=await post('/submit',{key:me.key,dev:DEV,ids:p.ids,answers:answers.join(','),auto:'بروفة',leave:'لم يخرج'})}catch(e){o={http:0,j:{}}}
 const ms=Math.round(performance.now()-t0),r=o.j||{},ok=typeof r.score==='number';
 await rep({stage:'submit',ok,ms,status:ok?'ok':('http'+o.http),skew:0,rtt:Math.round(rtt)});
 row('التسليم',ok,ms+' م.ث'+(ok?' — العلامة '+r.score+' / '+r.total:''));
 $('msg').textContent=ok?'خلصت الجولة ✓':'فشل التسليم ✗';$('msg').dataset.keep=1;P=null
}
let wl=null;async function lock(){try{wl=await navigator.wakeLock.request('screen')}catch(e){}}
lock();document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')lock()});
poll();setInterval(poll,2000);
</script>"""
PASS_PCT = 50                                               # حد النجاح (% من العلامة الكاملة) للبطاقة والدائرة بصفحة التقرير
BANDS = ((85, "ممتاز", "85–100%", "#1b7f46"), (75, "جيد جداً", "75–84%", "#14566b"), (65, "جيد", "65–74%", "#3b6fb6"), (50, "مقبول", "50–64%", "#d49b20"), (0, "ضعيف", "أقل من 50%", "#b3261e"))
def band_of(pct): return next(i for i, b in enumerate(BANDS) if pct >= b[0])
def rv_block(key, pcts, n_students, hidden):
    """بلوك التقرير لمجموعة طلاب (كل الشعب أو شعبة): بطاقات الأرقام + دائرة النجاح + أعمدة توزيع العلامات. كل المجموعات بتنكتب بالصفحة (HTML جاهز) والقائمة بتبدّل بينها بدون ما تحسب شي"""
    n = len(pcts); ok = sum(1 for x in pcts if x >= PASS_PCT); rate = round(100 * ok / n) if n else None
    kp = (f"<div class=kpis><div class=kpi><span>إجمالي الطلاب</span><b>{n_students}</b></div><div class=kpi><span>سلّموا</span><b>{n}</b></div>"
          f"<div class=kpi><span>المتوسط %</span><b>{f'{sum(pcts) / n:.1f}' if n else '—'}</b></div>"
          f"<div class='kpi{'' if rate is None else ' ok' if rate >= PASS_PCT else ' bad'}'><span>نسبة النجاح (من {PASS_PCT}% وما فوق)</span><b>{'—' if rate is None else f'{rate}%'}</b></div>"
          f"<div class=kpi><span>الأعلى %</span><b>{round(max(pcts)) if n else '—'}</b></div><div class=kpi><span>الأدنى %</span><b>{round(min(pcts)) if n else '—'}</b></div></div>")
    head = f"<div class=rv data-k='{html.escape(key, True)}'{' hidden' if hidden else ''}>" + kp
    if not n: return head + "<div class=card>لا يوجد تسليم بعد.</div></div>"
    counts = [sum(1 for x in pcts if band_of(x) == i) for i in range(len(BANDS))]; mx = max(counts) or 1
    donut = (f"<svg class=donut viewBox='0 0 36 36' role=img aria-label='نسبة النجاح {rate}%'><circle cx=18 cy=18 r=15.9155 fill=none stroke='#fde8e6' stroke-width=4></circle>"
             f"<circle cx=18 cy=18 r=15.9155 fill=none stroke='#1b7f46' stroke-width=4 stroke-dasharray='{rate} {100 - rate}' stroke-dashoffset=25></circle>"
             f"<text x=18 y=19.5 text-anchor=middle font-size=7 font-weight=700 fill='#1c2733'>{rate}%</text></svg>"
             f"<p style='text-align:center;margin:6px 0 0'><small>نجح {ok} ورسب {n - ok}</small></p>")
    bars = "".join(f"<div class=col><b>{c}</b><i style='height:{max(2, int(100 * c / mx))}%;background:{b[3]}'></i></div>" for c, b in zip(counts, BANDS))
    labs = "".join(f"<span>{b[1]}<br><small>{b[2]}</small></span>" for b in BANDS)
    return head + (f"<div class=charts><div class=card><h3>نسبة النجاح والرسوب</h3>{donut}</div>"
                   f"<div class=card><h3>توزيع العلامات (عدد الطلاب بكل فئة)</h3><div class=hist>{bars}</div><div class=histlab>{labs}</div></div></div></div>")
def report_page(arch_home=None):
    """التقرير: بطاقات وأعمدة بيانية (قائمة تبدّل بين كل الشعب وشعبة معيّنة)، ملخص الشعب، تحليل الأسئلة. arch_home: صفحة الأرشيف (بدون شريط التنقل وروابط نسبية)"""
    ss, qs = section_stats(), question_stats(); rows = student_rows()
    acts = (f"<a class=btn href='{html.escape(arch_home, True)}'>الرئيسية</a> <a class=btn href='report.xlsx'>تنزيل Excel (علامات الشعب + التحليل)</a>" if arch_home else "<a class=btn href=/report.xlsx>تنزيل Excel (علامات الشعب + التحليل)</a>") + " <button class='btn ghost' onclick=print()>طباعة</button>"
    secs = sorted({(r["grade"], r["section"]) for r in rows})
    sel = "<select id=secf aria-label='الشعبة'><option value=''>كل الشعب</option>" + "".join(f"<option value='{html.escape(g + '|' + s, True)}'>{html.escape(g)} — شعبة {html.escape(s)}</option>" for g, s in secs) + "</select>"
    done = [r for r in rows if r["status"] == "done"]
    blocks = rv_block("", [r["score"] / r["total"] * 100 if r["total"] else 0 for r in done], len(rows), False)
    for g, s in secs:
        sec = [r for r in rows if r["grade"] == g and r["section"] == s]
        blocks += rv_block(f"{g}|{s}", [r["score"] / r["total"] * 100 if r["total"] else 0 for r in sec if r["status"] == "done"], len(sec), True)
    h = (f"<div class=pagehead><h2>تقرير الامتحان</h2><div class=noprint>{sel} {acts}</div></div>"
         + f"<p><small>{html.escape(SET['title'])}</small></p>" + blocks
         + "<script>var f=document.getElementById('secf');f.onchange=function(){document.querySelectorAll('.rv').forEach(function(b){b.hidden=b.dataset.k!==f.value})}</script>"
         + "<h3>ملخص الشعب</h3><div class=tw><table><tr><th>الصف</th><th>الشعبة</th><th>الطلاب</th><th>سلّموا</th><th>المتوسط %</th><th>الأعلى %</th><th>الأقل %</th><th>توزيع العلامات (0-20 / 20-40 / 40-60 / 60-80 / 80-100)</th></tr>")
    for r in sorted(ss, key=lambda r: (r["grade"], r["section"])):
        mx = max(r["dist"]) or 1
        bars = " ".join(f"<span class=bar style='width:{int(40*c/mx)+2}px' title={c}></span>{c}" for c in r["dist"])
        h += f"<tr><td>{html.escape(r['grade'])}</td><td>{html.escape(r['section'])}</td><td>{r['students']}</td><td>{r['submitted']}</td><td>{'' if r['avg'] is None else r['avg']}</td><td>{'' if r['max'] is None else r['max']}</td><td>{'' if r['min'] is None else r['min']}</td><td>{bars}</td></tr>"
    h += "</table></div><h3>تحليل الأسئلة (الأصعب أولاً)</h3><div class=tw><table><tr><th>السؤال</th><th>المستوى</th><th>الصفحة</th><th>مرات الظهور</th><th>نسبة الصح %</th><th>أكثر إجابة خاطئة</th><th>ملاحظة</th></tr>"
    for r in sorted(qs, key=lambda r: (r["pct"] is None, r["pct"] if r["pct"] is not None else 0)):
        pc = "" if r["pct"] is None else f"<div class=pct><span>{r['pct']}</span><i class='{'' if r['pct'] >= 70 else 'mid' if r['pct'] >= 40 else 'low'}' style='width:{max(2, round(r['pct'] * 0.8))}px'></i></div>"
        h += f"<tr><td>س{r['n']}</td><td><span class='badge {r['level']}'>{LVL.get(r['level'], '')}</span></td><td>{html.escape(str(r['page']))}</td><td>{r['appeared']}</td><td>{pc}</td><td>{html.escape(r['top_wrong'])}</td><td>{r['note']}</td></tr>"
    h += "</table></div>"
    if arch_home: return "<!doctype html>" + CSS + "<title>تقرير الامتحان</title><body>" + h
    return teacher_page(h, "report", "تقرير الامتحان")

# ---------- ورقة الطالب (للمعلم فقط) ----------
SHEET_CSS = "<style>" + FRAC_CSS + ".q{border:1px solid #bbb;border-radius:6px;padding:8px 10px;margin:8px 0;page-break-inside:avoid}.q.bad{border-color:#b3261e;background:#fff5f4}.q.good{border-color:#2e7d32}.o{margin:2px 14px}.o.right{color:#1b6b2a;font-weight:bold}.o.given.wrongc{color:#b3261e;font-weight:bold}.hd{border-bottom:2px solid #14566b;margin-bottom:8px}.pg{page-break-after:always}.pg:last-child{page-break-after:auto}@media print{.noprint{display:none}body{background:#fff;max-width:none;margin:0}}</style>"
def sheet_html(sub, wrong_only):
    ok = sub["score"]; tot = sub["total"]
    late_txt = f" &nbsp; <b style='color:#b3261e'>تسليم متأخر:</b> {sub['late']} ث" if sub.get("late") else ""
    if fmt_dur(sub.get("dur")): late_txt = f" &nbsp; <b>مدة الحل:</b> {fmt_dur(sub['dur'])}" + late_txt
    h = f"<div class=pg><div class=hd><h2 style='margin:4px 0'>{html.escape(sub['exam'])}</h2><b>الاسم:</b> {html.escape(sub['name'])} &nbsp; <b>الصف:</b> {html.escape(sub['grade'])} &nbsp; <b>الشعبة:</b> {html.escape(sub['section'])} &nbsp; <b>العلامة:</b> <span dir=ltr>{ok} / {tot}</span> &nbsp; <b>الخروج من الصفحة:</b> {html.escape(str(sub.get('leave','')))}{late_txt}</div>"
    for i, (n, v) in enumerate(zip(sub["ids"], sub["answers"]), 1):
        q = BANK[n]; right = v == q["a"]
        if wrong_only and right: continue
        h += f"<div class='q {'good' if right else 'bad'}'><div><b>{i}. (س{n} — {LVL.get(q['level'], '')} — {mtxt(eff_mark(q['marks'], sub['ids']))})</b> {'✓' if right else '✗'} <span dir={bdir(q['q'])}>{qhtml(q['q'])}</span></div>"
        for j, o in enumerate(q["o"]):
            c = "o" + (" right" if j == q["a"] else "") + (" given" if j == v else "") + (" wrongc" if j == v and not right else "")
            mark = (" ← إجابة الطالب" if j == v else "") + (" ✓ الصحيحة" if j == q["a"] else "")
            h += f"<div class='{c}'>{L[j]}) <span dir={bdir(o)}>{qhtml(o)}</span><small>{mark}</small></div>"
        if v < 0: h += "<div class=o style='color:#b3261e'>لم يجب</div>"
        h += "</div>"
    return h + "</div>"
def sheet_page(q):
    wo = q.get("wrong") == "1"
    def bar(extra=""): return f"<p class=noprint><a class='btn ghost' href=/sheet>قائمة الطلاب</a>{extra}</p>"
    if q.get("key"):
        sub = SUBS.get(q["key"])
        if not sub: return teacher_page("لا يوجد تسليم لهذا الطالب.", "sheet", "ورقة طالب")
        tg = f"<a class=btn href='/sheet?key={urllib.parse.quote(q['key'])}{'' if wo else '&wrong=1'}'>{'عرض كل الأسئلة' if wo else 'عرض الخاطئة فقط'}</a> <button class=btn onclick=print()>طباعة</button>"
        return teacher_page(bar(" " + tg) + sheet_html(sub, wo), "sheet", "ورقة طالب", SHEET_CSS)
    if q.get("g") is not None and q.get("s") is not None:
        subs = [r for r in student_rows() if r["grade"] == q["g"] and r["section"] == q["s"] and r["status"] == "done"]
        tg = f"<a class=btn href='/sheet?g={urllib.parse.quote(q['g'])}&s={urllib.parse.quote(q['s'])}{'' if wo else '&wrong=1'}'>{'عرض كل الأسئلة' if wo else 'عرض الخاطئة فقط'}</a> <button class=btn onclick=print()>طباعة الكل ({len(subs)} ورقة)</button>"
        return teacher_page(bar(" " + tg) + "".join(sheet_html(SUBS[r["key"]], wo) for r in subs), "sheet", "ورقات الشعبة", SHEET_CSS)
    rows = student_rows(); h = "<div class=pagehead><h2>ورقات الطلاب</h2></div>"
    for (g, s) in sorted({(r["grade"], r["section"]) for r in rows}):
        sec = [r for r in rows if r["grade"] == g and r["section"] == s]; dn = [r for r in sec if r["status"] == "done"]
        h += f"<h3>{html.escape(g)} — شعبة {html.escape(s)} ({len(dn)} سلّموا)</h3><p><a class=btn target=_blank href='/sheet?g={urllib.parse.quote(g)}&s={urllib.parse.quote(s)}'>طباعة ورقات الشعبة كلها</a></p><table><tr><th>الاسم</th><th>العلامة</th><th></th></tr>"
        for r in dn: h += f"<tr><td>{html.escape(r['name'])}</td><td>{r['score']} / {r['total']}</td><td><a class=btn target=_blank href='/sheet?key={urllib.parse.quote(r['key'])}'>فتح الورقة</a></td></tr>"
        h += "</table>"
    return teacher_page(h, "sheet", "ورقات الطلاب")

def codes_page():
    pr = "<p class=noprint><button class=btn onclick=print()>طباعة (قصاصات للقص)</button></p>"
    if not SET["needCode"]: return teacher_page("<p>رمز الدخول غير مفعّل. فعّله بـ <b>رمز_الدخول = نعم</b> في settings.txt ثم شغّل السيرفر من جديد.</p>", "codes", "رموز الدخول", "<style>@media print{.noprint{display:none}body{background:#fff;max-width:none;margin:0}}</style>")
    head = "<style>.slip{box-sizing:border-box;display:inline-block;width:31%;border:1px dashed #888;padding:8px;margin:4px;vertical-align:top;page-break-inside:avoid;background:#fff}.code{font-size:28px;font-weight:bold;letter-spacing:4px;direction:ltr;display:block;text-align:center;color:#14566b}.sc{page-break-after:always}@media print{.noprint{display:none}body{background:#fff;max-width:none;margin:0}}</style>"
    h = pr + "<p class=noprint>كل طالب بياخذ رمزه بورقة صغيرة (اقصّها) ويكتبه عند بداية الامتحان. الرموز محفوظة بملف codes.json — امسحه لتوليد رموز جديدة. <b>لا تعرض هذه الصفحة على شاشة الصف.</b></p>"
    for g, secs in ROSTER.items():
        for s, names in secs.items():
            h += f"<div class=sc><h3>{html.escape(g)} — شعبة {html.escape(s)}</h3>"
            for n in names: h += f"<div class=slip>{html.escape(n)}<span class=code>{html.escape(CODES[f'{g}|{s}|{n}'])}</span></div>"
            h += "</div>"
    return teacher_page(h, "codes", "رموز الدخول", head)

def key_page(arch_home=None):
    """مفتاح الإجابات. arch_home: صفحة الأرشيف (بدون شريط التنقل)"""
    top = (f"<p class=noprint><a class=btn href='{html.escape(arch_home, True)}'>الرئيسية</a> " if arch_home else "<p class=noprint>") + "<button class=btn onclick=print()>طباعة</button></p>"
    h = top + f"<h2>مفتاح الإجابات — {html.escape(SET['title'])}</h2><p>عدد الأسئلة بالبنك: {len(QLIST)} | بالامتحان: {sum(PICK.values())} ({'، '.join(f'{LVL[k]} {v}' for k, v in PICK.items() if v)}) | مجموع علامات الامتحان: {'%s' % total_range(PICK)[0] if total_range(PICK)[0] == total_range(PICK)[1] else '%s إلى %s' % total_range(PICK)}</p>"
    for lv in ("hard", "medium", "easy"):
        qs = [q for q in QLIST if q["level"] == lv]
        if not qs: continue
        h += f"<h3>{LVL[lv]} ({len(qs)})</h3>"
        for q in qs:
            h += f"<div class='q'><b>س{q['n']}</b> <small>(سطر {q['row']} بالملف{' — ' + html.escape(str(q['page'])) if q['page'] else ''} — {mtxt(key_mark(q['marks']))})</small> <span dir={bdir(q['q'])}>{qhtml(q['q'])}</span>"
            for j, o in enumerate(q["o"]): h += f"<div class='o{' right' if j == q['a'] else ''}'>{L[j]}) <span dir={bdir(o)}>{qhtml(o)}</span>{' ✓' if j == q['a'] else ''}</div>"
            if q["sol"]: h += f"<div class=o><small>الحل: {html.escape(q['sol'])}</small></div>"
            h += "</div>"
    if arch_home: return "<!doctype html>" + CSS + SHEET_CSS + "<title>مفتاح الإجابات</title><body>" + h
    return teacher_page(h, "key", "مفتاح الإجابات", SHEET_CSS)

class H(http.server.BaseHTTPRequestHandler):
    timeout = 20                                      # اتصال معلّق بدون بيانات بينقطع (كان بيضل مفتوح للأبد)
    def send(self, body, ctype="text/plain; charset=utf-8", code=200, extra=None):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", (extra or {}).get("Cache-Control", "no-store"))
        self.send_header("Content-Length", str(len(b)))
        for k, v in (extra or {}).items():
            if k != "Cache-Control": self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)
    def teacher(self): return self.client_address[0] in ("127.0.0.1", "::1")
    def not_local(self, path):
        """صفحة معلم انطلبت من غير جهاز السيرفر، أو من جهاز السيرفر برابط الشبكة (192.168...) بدل localhost"""
        u = f"http://localhost{'' if PORT == 80 else ':' + str(PORT)}{path}"
        return self.send("<meta charset=utf-8><body style='font-family:Tahoma;padding:30px;line-height:1.9'><h3>للمعلم فقط (من جهاز السيرفر)</h3>"
                         f"صفحات المعلم بتفتح من جهاز السيرفر نفسه على localhost (مش على رابط الطلاب):<br><b dir=ltr>{html.escape(u)}</b>", "text/html; charset=utf-8", 403)
    def authed(self):
        ck = dict(p.strip().split("=", 1) for p in self.headers.get("Cookie", "").split(";") if "=" in p)
        return ck.get("exam_t") in TOKENS
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}; path = u.path
        note_client(self)
        if path in ("/", "/index.html"):
            return self.send(PAGE, "text/html; charset=utf-8")
        if path == "/ok": return self.send("OK\n")                       # للتجربة من جوال الطالب/المعلم: لو انفتحت بيوصل للسيرفر
        if path == "/rehearsal": return self.send(REHEARSAL_PAGE, "text/html; charset=utf-8")         # صفحة بروفة الضغط (بتشتغل بس لما المشرف يفعّلها)
        if path == "/rehearsal.json":                                    # حالة البروفة + ساعة السيرفر (الأجهزة بتحسب فرق ساعتها عن ساعة السيرفر منها)
            with LOCK:
                reh_tick(); o = {"on": REH["on"], "at": REH["at"], "gen": REH["gen"], "full": REH["full"]}
            o["now"] = time.time()
            return self.send(json.dumps(o), "application/json")
        if path in ("/health", "/health.json"):                          # فحص جاهزية السيرفر (للمعلم فقط، من جهاز السيرفر)
            if not self.teacher(): return self.not_local(path)
            d_ = health_data()
            if path == "/health.json": return self.send(json.dumps(d_, ensure_ascii=False), "application/json; charset=utf-8")
            return self.send(health_page(d_), "text/html; charset=utf-8")
        if path == "/taken":
            with LOCK: t = [k for k, d in CLAIMS.items() if d != q.get("dev")]
            return self.send(json.dumps({"taken": t}, ensure_ascii=False), "application/json; charset=utf-8")
        if path == "/link":
            if not self.teacher(): return self.send("", code=403)
            return self.send("<meta charset=utf-8><body style='font-family:Tahoma;text-align:center;margin-top:15vh'><div style='font-size:28px'>رابط الامتحان</div>"
                             f"<div dir=ltr style='font-size:72px;font-weight:bold;color:#14566b'>http://{ip()}{'' if PORT == 80 else ':' + str(PORT)}</div>" + "".join(f"<div style='font-size:18px;color:#5d6b7a;margin-top:14px'>{IP_LABEL_AR[k]}: <b dir=ltr>{html.escape(u)}</b></div>" for u, k in alt_links('' if PORT == 80 else ':' + str(PORT)) if k != "virtual"), "text/html; charset=utf-8")
        if path in PROTECTED or path == "/login": refresh_tpass()
        if path == "/login":
            if not self.teacher(): return self.not_local(path)
            if not SET["tpass"]: return self.send("", code=302, extra={"Location": "/monitor"})
            nxt = q.get("next", "")
            nxt = nxt if nxt.split("?")[0] in PROTECTED and not nxt.startswith("//") else "/monitor"
            return self.send(login_page(nxt), "text/html; charset=utf-8")
        if path == "/authcheck":                       # صفحة الدخول بتسأل: هل المتصفح حفظ كوكي الدخول فعلاً؟
            if not self.teacher(): return self.send("", code=403)
            return self.send(json.dumps({"authed": self.authed()}), "application/json")
        if path == "/logout":
            TOKENS.discard(dict(p.strip().split("=", 1) for p in self.headers.get("Cookie", "").split(";") if "=" in p).get("exam_t"))
            return self.send("", code=302, extra={"Location": "/monitor", "Set-Cookie": "exam_t=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
        if path in PROTECTED and SET["tpass"] and self.teacher() and not self.authed():
            return self.send("", code=302, extra={"Location": "/login?next=" + urllib.parse.quote(self.path)})
        if path.startswith("/monitor-ui/"):                  # ملفات واجهة المراقبة الجديدة (للمعلم فقط، زي صفحة المراقبة نفسها)
            if not self.teacher(): return self.not_local(path)
            a = monitor_ui_asset(urllib.parse.unquote(path[len("/monitor-ui/"):]))
            return self.send(a[0], a[1], extra={"Cache-Control": "no-cache"}) if a else self.send("غير موجود", code=404)
        if path in ("/monitor", "/monitor-old", "/monitor.json", "/admin", "/report", "/report.xlsx", "/sheet", "/key", "/codes", "/teacher"):
            if not self.teacher(): return self.not_local(path)
            with LOCK:
                if path in ("/monitor", "/admin"):
                    return self.send(monitor_ui_page() or monitor_old_page(), "text/html; charset=utf-8")      # الجديدة، أو القديمة لو مجلد monitor_ui مش موجود
                if path == "/monitor-old": return self.send(monitor_old_page(), "text/html; charset=utf-8")
                if path == "/monitor.json":
                    rows = student_rows(); secs = defaultdict(list)
                    for r in rows: secs[f"{r['grade']} — شعبة {r['section']}"].append(r)
                    c = Counter(r["status"] for r in rows); reh_tick()
                    return self.send(json.dumps({"sections": secs, "closed": bool(STATE["closed_at"]), "msg": STATE["msg"]["text"], "comp": STATE.get("comp"), "bank_changed": bank_changed(), "reh": reh_summary(), "c": {k: c.get(k, 0) for k in ("done", "live", "lost", "none")}}, ensure_ascii=False), "application/json; charset=utf-8")
                if path == "/key": return self.send(key_page(), "text/html; charset=utf-8")
                if path == "/teacher": return self.send(PREVIEW, "text/html; charset=utf-8")
                if path == "/codes": return self.send(codes_page(), "text/html; charset=utf-8")
                if path == "/sheet": return self.send(sheet_page(q), "text/html; charset=utf-8")
                if path == "/report": return self.send(report_page(), "text/html; charset=utf-8")
                return self.send(build_xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", extra={"Content-Disposition": "attachment; filename=exam_report.xlsx"})
        if path.startswith("/img/"):                   # صور الأسئلة (عامة للطلاب): فقط ملفات مجلد images بصيغ الصور المسموحة
            name = urllib.parse.unquote(path[5:])
            ext = os.path.splitext(name)[1].lower()
            fp = os.path.join(IMG_DIR, name)
            if not name or name != os.path.basename(name) or ext not in IMG_EXT or not os.path.isfile(fp): return self.send("", code=404)
            hdr = {"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"}
            if ext == ".svg": hdr["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
            with open(fp, "rb") as f: return self.send(f.read(), IMG_EXT[ext], 200, hdr)
        self.send("", code=404)
    def do_POST(self):
        note_client(self)
        gap_check()
        try: n = int(self.headers["Content-Length"])
        except Exception: return self.send("bad", code=400)
        if n < 0: return self.send("bad", code=400)
        if n > MAX_BODY: self.close_connection = True; return self.send("too large", code=413)       # ما نقرأ جسم ضخم بالذاكرة
        try: d = json.loads(self.rfile.read(n))
        except Exception: return self.send("bad", code=400)
        if not isinstance(d, dict): return self.send("bad", code=400)
        J = lambda o, code=200: self.send(json.dumps(o, ensure_ascii=False), "application/json; charset=utf-8", code)
        k, dev = d.get("key", ""), d.get("dev", "")
        if self.path == "/login":                       # دخول المعلم بكلمة السر (POST + ترويسة مخصصة)
            if not self.teacher() or self.headers.get("X-Exam-Action") != "1": return self.send("للمعلم فقط", code=403)
            now = time.time()
            if TFAIL[1] > now: return J({"ok": False, "locked": int(TFAIL[1] - now) + 1})
            refresh_tpass()
            if SET["tpass"] and hmac.compare_digest(norm_pass(d.get("password", "")).encode(), norm_pass(SET["tpass"]).encode()):
                TFAIL[0] = 0; tok = secrets.token_urlsafe(24); TOKENS.add(tok)
                return self.send(json.dumps({"ok": True}), "application/json", 200, {"Set-Cookie": f"exam_t={tok}; Path=/; HttpOnly; SameSite=Strict"})
            TFAIL[0] += 1
            if TFAIL[0] >= 5: TFAIL[0] = 0; TFAIL[1] = now + 30; print("تنبيه: محاولات كثيرة خاطئة لكلمة سر المعلم — القفل 30 ثانية")
            return J({"ok": False})
        if self.path == "/monitor":                     # أوامر المعلم: POST + ترويسة مخصصة (تمنع الطلبات من صفحات خارجية)
            if not self.teacher() or self.headers.get("X-Exam-Action") != "1": return self.send("للمعلم فقط", code=403)
            with LOCK:
                if d.get("rehearsal"):                   # بروفة الضغط: on / go / off
                    err = reh_command(str(d["rehearsal"]), d)
                    return J({"error": err}, 400) if err else J({"ok": 1})
                rk = d.get("release")
                if rk in CLAIMS and rk not in SUBS:
                    del CLAIMS[rk]; PAPERS.pop(rk, None); LIVE.pop(rk, None); ANS.pop(rk, None); ANS_DIRTY[0] = True; save_claims(); save_papers(); print("فك حجز:", rk.split("|")[-1])
                ro = d.get("reopen")                     # إعادة فتح طالب سلّم بالغلط (بإجاباته ووقته)
                if ro:
                    try: err = reopen_student(ro)
                    except OSError as e: err = f"تعذّرت الكتابة بسجل التسليمات: {e}"
                    if err: return J({"error": err}, 400)
                    print("إعادة فتح الطالب:", str(ro).split("|")[-1])
                pk = d.get("pause")                      # إيقاف مؤقت لطالب (حمّام مثلاً): شاشته بتتغطّى ووقته بيتجمّد لحد «متابعة»؛ حجز الاسم والجهاز بيضل
                if pk:
                    if STATE["closed_at"]: return J({"error": "الامتحان منتهٍ، ما في داعي للإيقاف"}, 400)
                    if pk not in CLAIMS or pk not in PAPERS or pk in SUBS: return J({"error": "الطالب مش بالامتحان الآن (سلّم أو ما بدأ)"}, 400)
                    if "paused" not in PAPERS[pk]: PAPERS[pk]["paused"] = time.time(); save_papers(); print("إيقاف مؤقت:", pk.split("|")[-1])
                rk2 = d.get("resume")                    # متابعة طالب موقوف: وقته بيكمل من حيث وقف
                if rk2 and rk2 in PAPERS and "paused" in PAPERS[rk2]:
                    print("متابعة بعد الإيقاف:", rk2.split("|")[-1], f"({int(settle_pause(PAPERS[rk2]))} ث)"); save_papers()
                mk = d.get("move")                       # نقل الطالب لجهاز آخر: نفس الورقة والإجابات، والوقت المتبقي يتجمّد لحد ما يبدأ من الجهاز الجديد
                if mk in CLAIMS and mk in PAPERS and mk not in SUBS:
                    settle_pause(PAPERS[mk]); PAPERS[mk]["frozen"] = remain_of(mk); del CLAIMS[mk]; LIVE.pop(mk, None); save_claims(); save_papers()
                    print("نقل لجهاز آخر:", mk.split("|")[-1], "— المتبقي", PAPERS[mk]["frozen"], "ث")
                sf = d.get("submitfor")                  # تسليم عن طالب (مفتاحه) أو "all" = كل من بدأ ولم يسلّم
                if sf:
                    keys = [x for x in list(PAPERS) if x in CLAIMS and x not in SUBS] if sf == "all" else [sf]
                    done_n = 0
                    for x in keys:
                        try: done_n += 1 if submit_for(x) else 0
                        except OSError as e: print("خطأ: تعذّر حفظ التسليم", e)
                    if done_n: write_results_csv()
                    print(f"تسليم عن الطلاب: {done_n}")
                if d.get("newexam"): print("أرشفة ->", archive_all())
                if d.get("bankok"): STATE["bank_fp"] = BANK_FP; STATE.pop("bank_changed", None); save_state(); print("المشرف أكّد: ملف الأسئلة المعدّل لنفس الامتحان")
                try: mins = int(d.get("extend", 0))
                except (TypeError, ValueError): return J({"error": "bad minutes"}, 400)
                if mins:
                    if not 1 <= mins <= 120 or d.get("scope") not in ("all", "section", "student"): return J({"error": "bad extend"}, 400)
                    print(f"تمديد {mins} د ({d['scope']}):", extend_time(mins, d["scope"], d), "طالب")
                if "close" in d:                          # إنهاء الامتحان للجميع (الصفحات بتسلّم تلقائياً) أو إعادة فتحه
                    STATE["closed_at"] = time.time() if d["close"] else 0; save_state(); print("الامتحان", "أُنهي" if d["close"] else "أُعيد فتحه")
                if "message" in d:
                    txt = str(d["message"]).strip()[:300]
                    if txt: STATE["msg"] = {"id": STATE["msg"]["id"] + 1, "text": txt}; save_state(); print("رسالة للطلاب:", txt)
            return J({"ok": 1})
        if self.path == "/rehearsal/join":              # جهاز بيسجّل نفسه ببروفة الضغط: بياخذ اسم فاضي من قائمة الطلاب بالترتيب
            with LOCK:
                reh_tick()
                if not REH["on"]: return J({"status": "off"})
                if not isinstance(dev, str) or not 0 < len(dev) <= 64: return J({"status": "bad"}, 400)
                r = reh_assign(dev)
                if r is None: return J({"status": "full"})
                return J({"status": "ok", "n": r["n"], "key": r["key"], "name": r["name"], "grade": r["grade"], "section": r["section"], "total": len(REH["devs"])})
        if self.path == "/rehearsal/report":            # الجهاز بيبلّغ نتيجة كل مرحلة (بدء/تسليم) ووقتها
            with LOCK:
                reh_tick()
                r = REH["devs"].get(dev) if isinstance(dev, str) else None
                if r is None or d.get("stage") not in ("start", "submit"): return J({"status": "bad"}, 400)
                def num_(x, lo, hi):
                    try: return int(max(lo, min(hi, float(x))))
                    except (TypeError, ValueError): return 0
                r["res"][d["stage"]] = {"ok": bool(d.get("ok")), "ms": num_(d.get("ms"), 0, 600000), "status": str(d.get("status", ""))[:20],
                                        "skew": num_(d.get("skew"), -600000, 600000), "rtt": num_(d.get("rtt"), 0, 600000)}
                return J({"status": "ok"})
        if self.path == "/start":                       # بدء الطالب: حجز الاسم + السيرفر يسحب الأسئلة ويبدأ العدّاد
            t_arr = time.time()                          # لحظة وصول الطلب (قبل انتظار القفل): بتفيد بقياس «بنفس اللحظة» ببروفة الضغط
            with LOCK:
                if not dev or parse_key(k) is None: return J({"status": "bad"}, 400)
                if k in REH["keys"]: REH["arr"].setdefault(k, t_arr)
                if k in SUBS: return J({"status": "done"})
                if k in CLAIMS and CLAIMS[k] != dev: return J({"status": "taken"})
                if k not in CLAIMS or k not in PAPERS:
                    if STATE["closed_at"] and k not in PAPERS: return J({"status": "closed"})   # المنقول يقدر يكمل ويسلّم حتى بعد الإنهاء
                    if SET["needCode"]:
                        bad = check_code(k, d.get("code"))
                        if bad: return J({"status": bad})
                    p = PAPERS.get(k)
                    if p is None: PAPERS[k] = make_paper(); print("بدأ:", k.split("|")[-1])
                    else:                                # طالب منقول: نفس الورقة، ونرجّع الوقت اللي كان باقيله
                        if "frozen" in p: p["start"] = time.time() + p.pop("frozen") - (SET["minutes"] * 60 + p.get("extra", 0))
                        print("استئناف من جهاز جديد:", k.split("|")[-1])
                    CLAIMS[k] = dev; save_claims(); save_papers()
                return J(paper_reply(k))
        if self.path == "/resume":                      # استئناف بعد إعادة تحميل الصفحة: نفس الورقة والوقت المتبقي من السيرفر
            with LOCK:
                if k in SUBS: return J({"status": "done"})
                if CLAIMS.get(k) == dev and k in PAPERS: return J(paper_reply(k))
                return J({"status": "none"})
        if self.path == "/review":                      # مراجعة الأخطاء للطالب بعد التسليم (حسب إعداد مراجعة_الأخطاء)
            with LOCK:
                mode = SET["review"]
                if mode == "no" or k not in SUBS or CLAIMS.get(k) != dev: return J({"status": "off"})
                if mode == "after" and not STATE["closed_at"]: return J({"status": "wait"})
                return J({"status": "ok", "items": [{"n": w["n"], "given": w["given"], "correct": w["correct"], "q": pub_q(w["n"])["q"], "o": pub_q(w["n"])["o"]} for w in wrong_items(SUBS[k]["ids"], SUBS[k]["answers"])]})
        if self.path == "/ping":
            with LOCK:
                if k in SUBS: return J({"submitted": True}) if CLAIMS.get(k) == dev else J({"released": True})      # سلّم (مثلاً المعلم سلّم عنه): الصفحة تعرض نتيجته
                if CLAIMS.get(k) != dev or k not in PAPERS: return J({"released": True})                             # أُلغي حجزه أو نُقل لجهاز آخر: الصفحة ترجع لشاشة الدخول
                a = clean_ans(k, d.get("ans"))
                if a is not None and a != ANS.get(k, {}): ANS[k] = a; ANS_DIRTY[0] = True
                LIVE[k] = {"t": time.time(), "answered": int(d.get("answered", 0)), "total": int(d.get("total", 0)), "remain": int(d.get("remain", 0)),
                           "leaveN": int(d.get("leaveN", 0)), "leaveSec": int(d.get("leaveSec", 0))}
                return J({"remain": remain_of(k), "msg": STATE["msg"], "paused": "paused" in PAPERS[k]})
        if self.path != "/submit": return self.send("", code=404)
        with LOCK:
            if k in SUBS: s = SUBS[k]; return J({"score": s["score"], "total": s["total"], "dup": True})
            who = parse_key(k); p = PAPERS.get(k)
            if who is None: return self.send("bad", code=400)
            if p is None or CLAIMS.get(k) != dev: return self.send("taken", code=409)
            try:
                ids = [int(x) for x in d["ids"]]; answers = [int(x) for x in str(d["answers"]).split(",")]
                assert ids == p["ids"] and len(answers) == len(ids) and all(-1 <= a < len(BANK[n]["o"]) for n, a in zip(ids, answers))
            except Exception: return self.send("bad", code=400)
            now = time.time(); over = int(now - deadline(k)); settle_pause(p)         # لو كان موقوفاً لحظة التسليم (مثلاً انتهى الامتحان): نثبّت الإيقاف قبل حساب المدة
            got = sum(BANK[n]["marks"] for n, a in zip(ids, answers) if a == BANK[n]["a"])        # مجموع علامات (أوزان) الأسئلة الصحيحة
            W = sum(BANK[n]["marks"] for n in ids)
            if SET["final"]: score, total = num(got / W * SET["final"]), num(SET["final"])           # العلامة النهائية: كل ورقة بتتحوّل لتصير من الرقم نفسه
            else: score, total = num(got), num(W)
            rec = {"key": k, "exam": SET["title"], "grade": who[0], "section": who[1], "name": who[2], "ids": ids, "answers": answers,
                   "score": score, "total": total, "auto": str(d.get("auto", ""))[:40], "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "leave": str(d.get("leave", ""))[:60], "late": over if over > GRACE else 0, "ts": round(now, 2),
                   "dur": max(0, int(now - p["start"] - p.get("down", 0) - p.get("pz", 0)))}   # مدة الحل: من «ابدأ» لـ «تسليم» بساعة السيرفر، بدون وقت توقف السيرفر وبدون إيقاف المعلم له
            if p.get("pz"): rec["pause"] = int(p["pz"])
            try:
                with open(SUBS_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
            except OSError as e:
                print("خطأ: تعذّر حفظ التسليم", e); return self.send("save failed", code=500)
            SUBS[k] = rec; LIVE.pop(k, None)
            if ANS.pop(k, None) is not None: ANS_DIRTY[0] = True
            write_results_csv()
            print("استلمت:", rec["section"], rec["name"], score, "/", total, f"(متأخر {over} ث)" if rec["late"] else "")
        J({"score": score, "total": total})
    def log_message(self, *a): pass

def ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(("10.255.255.255", 1)); a = s.getsockname()[0]
    except Exception: a = "127.0.0.1"
    finally: s.close()
    if a.startswith(("127.", "0.")):         # ما في طريق افتراضي (شبكة بدون بوابة، أو هوتسبوت بدون إنترنت): بنختار من كروت الشبكة نفسها
        try: c = {ai[4][0] for ai in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
        except OSError: c = set()
        c = sorted(x for x in c if not x.startswith(("127.", "169.254.", "0.")))
        if c: a = min(c, key=lambda x: {"hotspot": 0, "other": 1}.get(ip_kind(x, None), 2))
    return a

STARTED = time.time()
SEEN = {}                                   # عنوان IP جهاز (مش جهاز المعلم) -> آخر طلب منه: دليل إن جوالات الطلاب بتوصل للسيرفر فعلاً
KEEP_AWAKE = [False]                        # هل منع النوم شغّال
QUICKEDIT = [None]                          # True = أُوقف تجميد النافذة السوداء بالضغط داخلها، False = فشل، None = مش نافذة حقيقية


def keep_awake(on=True):
    """يمنع ويندوز من النوم (idle sleep) طول ما السيرفر شغّال. بيتسجّل على الثريد اللي بينادي، فلازم يكون الثريد الرئيسي (اللي بيضل شغّال). لا بيمنع النوم اليدوي (زر الطاقة/إغلاق الغطاء)"""
    if os.name != "nt": return False
    try:
        import ctypes
        f = ctypes.windll.kernel32.SetThreadExecutionState
        f.argtypes = [ctypes.c_uint32]; f.restype = ctypes.c_uint32
        return bool(f(0x80000000 | (0x00000001 if on else 0))) and on          # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except Exception:
        return False


def disable_quickedit():
    """ضغطة ماوس داخل نافذة CMD (QuickEdit) بتجمّد البرنامج لحد ما تضغط Enter، وممكن توقف السيرفر وسط الامتحان. بنطفّيه لهالنافذة"""
    if not REAL_CONSOLE: return None
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.GetStdHandle.restype = ctypes.c_void_p
        k.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        k.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        h = k.GetStdHandle(-10); mode = ctypes.c_uint32()                       # STD_INPUT_HANDLE
        if not k.GetConsoleMode(h, ctypes.byref(mode)): return None
        if not k.SetConsoleMode(h, (mode.value & ~0x0040) | 0x0080): return False      # شيل ENABLE_QUICK_EDIT_MODE وفعّل ENABLE_EXTENDED_FLAGS
        k.GetConsoleMode(h, ctypes.byref(mode))
        return not (mode.value & 0x0040)
    except Exception:
        return None


def note_client(h):
    """بنسجّل عناوين الأجهزة (غير جهاز المعلم) اللي بتطلب من السيرفر: بتبيّن للمعلم إن جوالات الطلاب فعلاً بتوصل"""
    a = h.client_address[0]
    if a in ("127.0.0.1", "::1"): return
    SEEN[a] = time.time()
    if len(SEEN) > 2000:
        try: SEEN.pop(min(SEEN, key=SEEN.get))
        except (ValueError, KeyError): pass


def lan_ips():
    ips = set()
    try:
        for ai in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET): ips.add(ai[4][0])
    except OSError: pass
    main = ip(); ips.add(main)
    return main, sorted(i for i in ips if not i.startswith("127.") and not i.startswith("169.254.")) or [main]


def ip_kind(a, main):
    """نوع عنوان شبكة على جهاز المعلم: main = اللي عليه الإنترنت/الشبكة الأساسية، hotspot = هوتسبوت ويندوز (دايماً 192.168.137.1)،
    virtual = كرت وهمي (VirtualBox 192.168.56.x، Hyper-V/WSL/Docker 172.16-31.x)، other = شبكة حقيقية ثانية"""
    if a == main: return "main"
    if a.startswith("192.168.137."): return "hotspot"
    p = a.split(".")
    if a.startswith("192.168.56.") or (p[0] == "172" and p[1].isdigit() and 16 <= int(p[1]) <= 31): return "virtual"
    return "other"
IP_LABEL_AR = {"main": "الشبكة الأساسية (الواي فاي أو الكابل)", "hotspot": "هوتسبوت ويندوز: استعمله لو الطلاب متصلين بهوتسبوت جهازك",
               "virtual": "شبكة وهمية (VirtualBox أو Hyper-V أو WSL): تجاهلها", "other": "شبكة ثانية: استعمله بس لو الطلاب على تلك الشبكة"}
IP_LABEL_EN = {"main": "main network", "hotspot": "Windows hotspot - use it if students joined this PC's hotspot", "virtual": "virtual adapter - ignore", "other": "another network"}
def alt_links(sfx):
    """الروابط البديلة (غير الأساسي) مع نوع كل واحد"""
    main, ips = lan_ips()
    return [(f"http://{a}{sfx}", ip_kind(a, main)) for a in ips if a != main]


def in_onedrive(p=None):
    """مجلد الامتحان داخل مجلد بيتزامن مع OneDrive (سطح المكتب غالباً هيك على ويندوز 10/11): المزامنة بتمسك الملفات لحظات وبتبطّئ الحفظ"""
    p = os.path.normcase(os.path.abspath(p or BASE)) + os.sep
    roots = [os.environ.get(v) for v in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")]
    return any(r and p.startswith(os.path.normcase(os.path.abspath(r)) + os.sep) for r in roots) or any(x.lower() == "onedrive" or x.lower().startswith("onedrive - ") for x in p.split(os.sep))


def health_data():
    import platform
    refresh_tpass()
    main, ips = lan_ips()
    with LOCK:
        rows = student_rows(); c = Counter(r["status"] for r in rows)
        n_papers, n_subs, closed = len(PAPERS), len(SUBS), bool(STATE["closed_at"])
    now = time.time(); seen = sorted((now - t, a) for a, t in list(SEEN.items()))
    try: free = shutil.disk_usage(BASE).free
    except OSError: free = None
    writable = True
    try:
        pth = os.path.join(BASE, ".health_probe"); open(pth, "w").close(); os.remove(pth)
    except OSError: writable = False
    sfx = "" if PORT == 80 else ":" + str(PORT)
    warns = []
    if main.startswith("127."): warns.append("السيرفر ما لقى عنوان شبكة (127.0.0.1): الجهاز مش متصل بواي فاي أو شبكة، فالطلاب ما رح يقدروا يفتحوا الرابط.")
    kinds = {a: ip_kind(a, main) for a in ips}
    real_alts = [a for a, k in kinds.items() if k in ("hotspot", "other")]
    if real_alts: warns.append("في أكثر من شبكة على هذا الجهاز: الرابط الأساسي للطلاب على نفس شبكتك؛ لو الطلاب على " + ("هوتسبوت جهازك" if any(kinds[a] == "hotspot" for a in real_alts) else "شبكة ثانية") + " استعمل الرابط البديل (القائمة تحت).")
    if zip_leftovers(): warns.append("ملف exam_data.zip كان فيه قائمة طلاب أو إعدادات، وما استبدلنا تبعك (المستعمل: students.xlsx وsettings.txt). النسخ اللي جت معه: " + "، ".join(zip_leftovers()) + " — إذا ما بدك إياها امسحها، وإذا بدك تستعمل وحدة منها غيّر اسمها مكان الأصلي.")
    if STATE.get("bank_changed"): warns.append("ملف الأسئلة تغيّر بعد آخر امتحان، والسيرفر لسا فيه بيانات الامتحان السابق: إذا هذا امتحان جديد اضغط «بداية امتحان جديد» من المراقبة قبل ما يدخل الطلاب (وإلا اللي امتحنوا قبل بيطلعوا «سلّم» وما بيقدروا يبدأوا). إذا بس صلّحت سؤال بنفس الامتحان: اضغط «هذا نفس الامتحان» بالمراقبة.")
    if SET.get("missing"): warns.append("ما في ملف settings.txt: شغّالين بالإعدادات الافتراضية (كل أسئلة البنك، 30 دقيقة، بدون كلمة سر). إذا الأستاذ طلب غير هيك، اعمل settings.txt (انسخه من الحزمة وعدّله) وشغّل السيرفر من جديد.")
    if in_onedrive(): warns.append("مجلد الامتحان داخل OneDrive (بيتزامن مع الإنترنت): المزامنة ممكن تمسك ملفات الامتحان لحظات وتبطّئ الحفظ. الأفضل تنقل المجلد كاملاً لمكان خارج OneDrive (مثل C:\\exam) قبل الامتحان.")
    if not SET["tpass"]: warns.append("ما في كلمة سر للمعلم: مفتاح الإجابات والمعاينة وورقات الطلاب مفتوحة على هذا الجهاز.")
    elif SET["tpass"] == "1234": warns.append("كلمة سر المعلم هي الافتراضية (1234): غيّرها بملف settings.txt.")
    if os.name == "nt" and not KEEP_AWAKE[0]: warns.append("منع النوم مش شغّال: عطّل وضع السكون من إعدادات الطاقة قبل الامتحان.")
    if REAL_CONSOLE and QUICKEDIT[0] is not True: warns.append("ما قدرنا نطفّي تجميد النافذة السوداء: لا تضغط بالماوس داخلها أثناء الامتحان.")
    if not writable: warns.append("السيرفر ما بيقدر يكتب بمجلده: النتائج ما رح تنحفظ! تأكد من صلاحيات المجلد.")
    if free is not None and free < 200 * 1024 * 1024: warns.append("المساحة الفاضية على القرص أقل من 200MB.")
    if closed: warns.append("الامتحان منتهٍ (أنهيته من المراقبة): الطلاب ما بيقدروا يبدأوا.")
    level = "bad" if (not writable or main.startswith("127.")) else ("warn" if warns else "ok")
    lo, hi = total_range(PICK)
    return {"status": "ok", "level": level, "uptime_s": int(now - STARTED), "time": time.strftime("%Y-%m-%d %H:%M:%S"), "python": platform.python_version(), "platform": platform.platform(),
            "version": VERSION, "pid": os.getpid(), "port": PORT, "student_url": f"http://{main}{sfx}", "ips": ips, "ip_kinds": kinds,
            "exam": {"title": SET["title"], "minutes": SET["minutes"], "per_student": sum(PICK.values()), "bank": len(QLIST), "students": len(rows), "marks": lo if lo == hi else f"{lo}-{hi}", "closed": closed},
            "counts": {"done": c.get("done", 0), "live": c.get("live", 0), "lost": c.get("lost", 0), "none": c.get("none", 0), "started": n_papers, "submitted": n_subs},
            "seen_clients": {"last_5min": sum(1 for age, _ in seen if age <= 300), "total": len(seen), "last_age_s": int(seen[0][0]) if seen else None,
                             "recent": [{"ip": a, "age_s": int(age)} for age, a in seen[:30]]},
            "disk": {"free_mb": None if free is None else int(free / 1048576), "writable": writable, "results": OUT, "results_age_s": int(now - os.path.getmtime(OUT)) if os.path.exists(OUT) else None},
            "compensation": STATE.get("comp"), "keep_awake": KEEP_AWAKE[0], "console": {"real": REAL_CONSOLE, "quickedit_disabled": QUICKEDIT[0]}, "warnings": warns}


def health_page(d):
    E_ = html.escape
    def row(label, value, lvl="ok"): return f"<tr class={lvl}><th>{label}</th><td>{value}</td><td class=dot>{ {'ok': '●', 'warn': '▲', 'bad': '✖', 'info': '○'}[lvl] }</td></tr>"
    up = d["uptime_s"]; upt = f"{up // 3600}:{up % 3600 // 60:02d}:{up % 60:02d}"
    sc, ex, cn = d["seen_clients"], d["exam"], d["counts"]
    rows = [row("حالة السيرفر", f"شغّال ✔ منذ {upt} (ساعة:دقيقة:ثانية) &nbsp; الوقت الآن {E_(d['time'])}"),
            row("رابط الطلاب", f"<span class=big dir=ltr>{E_(d['student_url'])}</span><br><small>من جوالك افتح <b dir=ltr>{E_(d['student_url'])}/ok</b>: لازم تشوف كلمة OK. وإن ما فتح: الجوال مش على نفس الشبكة، أو جدار الحماية حاجب Python.</small>", "bad" if d["student_url"].startswith("http://127.") else "ok"),
            row("عناوين الشبكة بهذا الجهاز", "<br>".join(f"<code dir=ltr>{E_(i)}</code> &nbsp;<small>{IP_LABEL_AR[d['ip_kinds'].get(i, 'other')]}</small>" for i in d["ips"]), "warn" if any(k in ("hotspot", "other") for k in d["ip_kinds"].values()) else "ok"),
            row("أجهزة الطلاب اللي وصلت للسيرفر", (f"{sc['last_5min']} جهاز آخر 5 دقائق (من {sc['total']} بالمجموع)، وآخر طلب قبل {sc['last_age_s']} ثانية" if sc["total"] else "ما وصل ولا جهاز طالب لحد الآن (جرّب /ok من جوالك)"), "ok" if sc["total"] else "info"),
            row("الامتحان", f"{E_(str(ex['title']))} &nbsp;|&nbsp; {ex['per_student']} سؤال لكل طالب من {ex['bank']} بالبنك &nbsp;|&nbsp; {ex['minutes']} دقيقة &nbsp;|&nbsp; العلامة {ex['marks']}", "warn" if ex["closed"] else "ok"),
            row("الطلاب", f"سلّموا {cn['done']} &nbsp;|&nbsp; يمتحنون {cn['live']} &nbsp;|&nbsp; انقطع اتصالهم {cn['lost']} &nbsp;|&nbsp; لم يبدأوا {cn['none']} &nbsp;(من {ex['students']})", "warn" if cn["lost"] else "ok"),
            row("منع النوم", "شغّال ✔" if d["keep_awake"] else "مش شغّال", "ok" if d["keep_awake"] or os.name != "nt" else "warn"),
            row("النافذة السوداء", "محميّة من التجميد بضغطة الماوس ✔" if d["console"]["quickedit_disabled"] else ("مش نافذة حقيقية (تشغيل مخفي)" if not d["console"]["real"] else "ممكن تتجمّد بضغطة ماوس داخلها: لا تضغط داخلها"), "ok" if d["console"]["quickedit_disabled"] or not d["console"]["real"] else "warn"),
            row("القرص", f"فاضي {d['disk']['free_mb']} MB &nbsp;|&nbsp; الكتابة بمجلد السيرفر: {'تمام' if d['disk']['writable'] else 'فاشلة!'}", "bad" if not d["disk"]["writable"] else ("warn" if (d["disk"]["free_mb"] or 9999) < 200 else "ok")),
            row("ملف النتائج", f"<code dir=ltr>{E_(str(d['disk']['results']))}</code>", "ok"),
            row("الإصدار / بايثون / النظام", f"{E_(d['version'])} &nbsp;|&nbsp; {E_(d['python'])} &nbsp;|&nbsp; {E_(d['platform'])} &nbsp;|&nbsp; PID {d['pid']}", "info")]
    if d.get("compensation"):
        c_ = d["compensation"]; rows.insert(1, row("تعويض الوقت بعد التوقف", (f"{'جهاز السيرفر نام أو تجمّد' if c_.get('sleep') else 'السيرفر كان متوقفاً'} {c_['downtime_s']} ثانية: " + ("التعويض مطفّأ" if c_.get("off") else "أطول من 30 دقيقة، ما عوّضنا تلقائياً" if c_.get("skipped") else f"مدّدنا وقت {c_['students']} طالب")), "warn" if (c_.get("off") or c_.get("skipped")) else "info"))
    warn = "".join(f"<li>{E_(w)}</li>" for w in d["warnings"])
    banner = {"ok": ("ok", "كل شي تمام ✔ السيرفر جاهز"), "warn": ("warn", "السيرفر شغّال، بس في تنبيهات تحت"), "bad": ("bad", "في مشكلة تحتاج تصليح قبل الامتحان")}[d["level"]]
    hstyle = ("<style>.b{border-radius:10px;padding:12px 16px;font-weight:bold;font-size:18px;margin-bottom:12px}.b.ok{background:#e6f6ec;color:#1b7f4b}.b.warn{background:#fff6d9;color:#9a6b00}.b.bad{background:#fde8e6;color:#b3261e}"
              "table.hl th{width:26%;background:#fff;color:#5d6b7a;font-weight:normal;white-space:nowrap;border-top:1px solid #e6ebf0}table.hl tr:first-child th,table.hl tr:first-child td{border-top:0}"
              ".dot{width:30px;text-align:center;font-size:18px}tr.ok .dot{color:#1b7f4b}tr.warn .dot{color:#d39a00}tr.bad .dot{color:#b3261e}tr.info .dot{color:#7a8794}.big{font-size:26px;font-weight:bold;color:#14566b}"
              "code{background:#eef1f4;padding:1px 6px;border-radius:4px}ul{margin:6px 0 12px;padding-right:22px}small{color:#5d6b7a}</style>")
    return ("<!doctype html>" + CSS + "<meta http-equiv=refresh content=5><title>فحص السيرفر</title>" + hstyle + "<body>" + teacher_nav("health")
            + "<div class=pagehead><h2>🩺 فحص السيرفر</h2><small>بتتحدّث لحالها كل 5 ثواني</small></div>"
            + f"<div class='b {banner[0]}'>{banner[1]}</div>" + (f"<ul>{warn}</ul>" if warn else "") + f"<table class=hl>{''.join(rows)}</table>")


PORT = int(os.environ.get("EXAM_PORT", 80))
http.server.ThreadingHTTPServer.request_queue_size = 128     # الافتراضي 5: لما عشرات الطلاب يضغطون «ابدأ» بنفس اللحظة كانت بعض الاتصالات تُرفض
def show_console_banner(sfx):
    """بانر إنجليزي نظيف للنافذة + ملف exam_info.txt بالعربي (بيتفتح بالمفكرة على ويندوز الحقيقي)"""
    link, loc = f"http://{ip()}{sfx}", f"http://localhost{sfx}"
    alts = alt_links(sfx)
    lo_, hi_ = total_range(PICK); marks_ = str(lo_) if lo_ == hi_ else f"{lo_}-{hi_}"
    n_students = sum(len(n) for g in ROSTER.values() for n in g.values())
    warn_en, warn_ar = [], []
    if STATE.get("bank_changed"):
        warn_en.append("WARNING: the questions file changed and data of the previous exam is still here. NEW exam? Open the monitor and press the 'new exam' button BEFORE students log in.")
        warn_ar.append("⚠ ملف الأسئلة تغيّر بعد آخر امتحان، والسيرفر لسا فيه بيانات الامتحان السابق: إذا هذا امتحان جديد اضغط «بداية امتحان جديد» من المراقبة قبل ما يدخل الطلاب (وإلا اللي امتحنوا قبل بيطلعوا «سلّم» وما بيقدروا يبدأوا). إذا بس صلّحت سؤال بنفس الامتحان: اضغط «هذا نفس الامتحان» بالمراقبة.")
    if SET.get("missing"):
        warn_en.append("NOTE: no settings.txt - using defaults (all questions in the file, 30 minutes, no teacher password)")
        warn_ar.append("ℹ ما في ملف settings.txt: الإعدادات الافتراضية (كل أسئلة الملف، 30 دقيقة، بدون كلمة سر). العنوان التلقائي: " + SET["title"])
    if not SET["tpass"]:
        warn_en.append("WARNING: no teacher password - key/preview/sheets are open on this computer. Set the teacher password in settings.txt")
        warn_ar.append("⚠ ما في كلمة سر للمعلم: المفتاح والمعاينة وورقات الطلاب مفتوحة على هذا الجهاز. اكتب كلمة سر بملف settings.txt (سطر كلمة_سر_المعلم).")
    elif SET["tpass"] == "1234":
        warn_en.append("WARNING: teacher password is the default 1234 - change it in settings.txt")
        warn_ar.append("⚠ كلمة سر المعلم هي الافتراضية (1234): غيّرها بملف settings.txt (سطر كلمة_سر_المعلم).")
    pwt = "   (بكلمة سر المعلم)" if SET["tpass"] else ""
    info = ["الامتحان شغّال ✔  —  خلّي نافذة CMD السوداء مفتوحة طوال الامتحان.",
            "(النافذة السوداء ما بتعرض الحروف العربية فبتطلع مربعات؛ هذا الملف فيه نفس المعلومات بالعربي.)", "",
            "رابط الامتحان لتعطيه للطلاب:", "", f"        {link}", ""] + ([ "روابط بديلة على هذا الجهاز (استعمل الأساسي فوق إلا إذا انطبق الوصف):"] + [f"    {u}   ← {IP_LABEL_AR[k]}" for u, k in alts] + [""] if alts else []) + [
            "صفحات المعلم (بتفتح من هذا الجهاز فقط):",
            f"    مراقبة حية            : {loc}/monitor", f"    التقرير               : {loc}/report",
            f"    ورقات الطلاب          : {loc}/sheet" + pwt, f"    مفتاح الإجابات        : {loc}/key" + pwt,
            f"    معاينة الامتحان كاملاً: {loc}/teacher" + pwt, f"    رابط بخط كبير للعرض   : {loc}/link", f"    فحص السيرفر (شبكة، نوم...): {loc}/health", f"    اختبار من جوالك         : {link}/ok   (لازم تطلع كلمة OK)"]
    if SET["needCode"]: info.append(f"    رموز دخول الطلاب      : {loc}/codes" + pwt)
    if warn_ar: info += ["", "تحذيرات:"] + ["    " + w for w in warn_ar]
    info += ["", f"الامتحان: {SET['title']}", f"    أسئلة الامتحان: {sum(PICK.values())} من {len(QLIST)} سؤال بالبنك  |  المدة: {SET['minutes']} دقيقة  |  العلامة: {marks_}  |  عدد الطلاب: {n_students}", "",
             f"النتائج بتنحفظ في: {OUT}", f"سجل الأحداث بالعربي (من بدأ، من سلّم، تنبيهات...): {LOG_FILE}", "    (بيتحدّث لحاله؛ افتحه بالمفكرة وقت ما بدك)", "",
             "للإيقاف: اضغط Ctrl+C أو سكّر النافذة السوداء.", "تذكير: قبل ما تسكّر، تأكد من شاشة المراقبة إن كل الطلاب سلّموا."]
    try:
        with open(INFO_FILE, "w", encoding="utf-8-sig") as f: f.write("\n".join(info) + "\n")
        if REAL_CONSOLE: os.startfile(INFO_FILE)
    except OSError: pass
    _real_print("\n" + "=" * 56)
    _real_print("  Give students this link:\n\n        " + link + "\n")
    for u, k in alts:
        if k != "virtual": _real_print(f"  Other link ({IP_LABEL_EN[k]}): {u}")
    _real_print("  Teacher pages (this computer only):")
    for nm, pth in (("Monitor ", "monitor"), ("Report  ", "report"), ("Sheets  ", "sheet"), ("Key     ", "key"), ("Preview ", "teacher"), ("Big link", "link"), ("Health  ", "health")) + ((("Codes   ", "codes"),) if SET["needCode"] else ()):
        _real_print(f"     {nm}: {loc}/{pth}" + ("   (teacher password)" if SET["tpass"] and pth in ("sheet", "key", "teacher", "codes") else ""))
    for w in warn_en: _real_print("  " + w)
    _real_print(f"  Exam: {sum(PICK.values())} of {len(QLIST)} questions | {SET['minutes']} min | marks: {marks_} | {n_students} students")
    _real_print(f"  Sleep prevention: {'ON' if KEEP_AWAKE[0] else 'off'} | Console freeze guard (QuickEdit): {'ON' if QUICKEDIT[0] else 'n/a'}")
    _real_print(f"  Phone test: open {link}/ok  (you should see OK)")
    if COMP: _real_print(f"  Downtime compensation: the server was down {COMP['downtime_s']}s -> " + ("OFF in settings" if COMP.get('off') else "longer than 30 min, not compensated (extend time manually)" if COMP.get('skipped') else f"extended {COMP['students']} student(s) by the same time"))
    _real_print("=" * 56)
    _real_print("  The Arabic details of this screen were saved to exam_info.txt (opened in Notepad).")
    _real_print("  Student events (Arabic) are logged to exam_log.txt.")
    _real_print("  To stop: Ctrl+C or close this window\n")


def port_in_use(p):
    """في برنامج بيسمع عالمنفذ؟ على ويندوز http.server بيفتح المنفذ بـ SO_REUSEADDR، وبهالخاصية سيرفران (نسختان من الحزمة) بيفتحوا نفس المنفذ بدون أي خطأ والطلبات بتتوزّع بينهم عشوائياً،
    فما بنعتمد على فشل bind: بنجرّب نتصل. وسيرفر وقف قبل شوي ما بيسمع حدا (TIME_WAIT ما بيرد على اتصال)، فإعادة التشغيل الفورية بتضل على نفس المنفذ"""
    try: socket.create_connection(("127.0.0.1", p), 0.5).close(); return True
    except OSError: return False
def bind_server(first, fallbacks=range(8000, 8010)):
    """بيفتح السيرفر على أول منفذ فاضي: المطلوب (80 أو EXAM_PORT) ثم 8000..8009 (لحد 10 نسخ من الحزمة بنفس الجهاز). بيرجّع (السيرفر، المنفذ)، وبيرفع OSError لو كلها مشغولة"""
    tried, last = [], None
    for p in dict.fromkeys([first, *fallbacks]):
        tried.append(p)
        if port_in_use(p): continue
        try: return http.server.ThreadingHTTPServer(("0.0.0.0", p), H), p       # مثلاً بدون صلاحية مدير على المنفذ 80: بنكمل للي بعده
        except OSError as e: last = e
    raise OSError(f"ما لقيت منفذ فاضي بين: {tried} (سيرفرات ثانية شغّالة؟ سكّر اللي مش لازم)") from last


if __name__ == "__main__":
    srv, PORT = bind_server(PORT)
    write_results_csv()
    COMP = compensate_downtime()                 # قبل أول نبضة جديدة: بنقرأ آخر لحظة كان فيها السيرفر شغّال ونعوّض الطلاب عن التوقف
    beat(); LAST_TICK[0] = time.time()
    threading.Thread(target=flusher, daemon=True).start()
    KEEP_AWAKE[0] = keep_awake(True)            # منع النوم طول ما السيرفر شغّال
    QUICKEDIT[0] = disable_quickedit()          # وما تتجمّد النافذة السوداء بضغطة ماوس
    sfx = "" if PORT == 80 else ":" + str(PORT)
    if CONSOLE_NO_ARABIC:
        show_console_banner(sfx)
        try: srv.serve_forever()
        finally: flush_answers(); keep_awake(False)
        sys.exit(0)
    print("\n" + "=" * 56)
    pw = "   (teacher password / بكلمة سر المعلم)" if SET["tpass"] else ""
    lo_, hi_ = total_range(PICK)
    marks_ = str(lo_) if lo_ == hi_ else f"{lo_}-{hi_}"
    print("  Give students this link  /  اعطِ الطلاب هذا الرابط:")
    print(f"\n        http://{ip()}{sfx}\n")
    for u, k in alt_links(sfx):
        if k != "virtual": print(f"  Other link / رابط بديل ({IP_LABEL_EN[k]}): {u}")
    print("  Teacher pages (this computer only)  /  صفحات المعلم:")
    print(f"     Monitor  / مراقبة حية : http://localhost{sfx}/monitor")
    print(f"     Report   / التقرير    : http://localhost{sfx}/report")
    print(f"     Sheets   / ورقات الطلاب: http://localhost{sfx}/sheet" + pw)
    print(f"     Key      / مفتاح الإجابات: http://localhost{sfx}/key" + pw)
    print(f"     Preview  / معاينة الامتحان كاملاً: http://localhost{sfx}/teacher" + pw)
    print(f"     Big link / رابط بخط كبير للعرض: http://localhost{sfx}/link")
    print(f"     Health   / فحص السيرفر: http://localhost{sfx}/health")
    if SET["needCode"]: print(f"     Codes    / رموز الدخول: http://localhost{sfx}/codes" + pw)
    if STATE.get("bank_changed"): print("  WARNING: the questions file changed and data of the previous exam is still here. NEW exam? Monitor -> 'new exam' BEFORE students log in.  /  ملف أسئلة جديد: اضغط «بداية امتحان جديد»")
    if SET.get("missing"): print("  NOTE: no settings.txt - using defaults (all questions, 30 minutes, no password)  /  ما في settings.txt: إعدادات افتراضية")
    if not SET["tpass"]: print("  WARNING: no teacher password - key/preview/sheets are open on this computer. Set كلمة_سر_المعلم in settings.txt  /  ⚠ ما في كلمة سر للمعلم")
    elif SET["tpass"] == "1234": print("  WARNING: teacher password is the default 1234 - change it in settings.txt  /  ⚠ كلمة سر المعلم هي الافتراضية (1234) — غيّرها")
    print(f"  Exam: {SET['title']} | {sum(PICK.values())} of {len(QLIST)} questions | {SET['minutes']} min | marks/العلامة: {marks_} | {sum(len(n) for g in ROSTER.values() for n in g.values())} students")
    print(f"  Sleep prevention: {'ON' if KEEP_AWAKE[0] else 'off'} | Console freeze guard (QuickEdit): {'ON' if QUICKEDIT[0] else 'n/a'}")
    if COMP: print(f"  Downtime compensation: the server was down {COMP['downtime_s']}s -> " + ("OFF in settings" if COMP.get('off') else "longer than 30 min, not compensated (extend time manually)" if COMP.get('skipped') else f"extended {COMP['students']} student(s) by the same time"))
    print("=" * 56)
    print(f"  Results saved in / النتائج تنحفظ في: {OUT}\n  To stop: Ctrl+C or close this window / للإيقاف\n")
    try: srv.serve_forever()
    finally: flush_answers(); keep_awake(False)
