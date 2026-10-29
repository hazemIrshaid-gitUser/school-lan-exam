# سيرفر الامتحان المحلي — يشتغل على جهاز المعلم (بايثون فقط، بدون تثبيت مكتبات)
# التشغيل:  python server.py     ثم يظهر الرابط اللي بتعطيه للطلاب
# صفحات المعلم (من نفس جهاز السيرفر فقط):
#    http://localhost/monitor   مراقبة حية + فك حجز + بدء امتحان جديد
#    http://localhost/sheet     ورقة كل طالب (أسئلته وإجاباته) + طباعة
#    http://localhost/key       مفتاح الإجابات (للمعلم فقط)
#    http://localhost/report    تقرير العلامات وتحليل الأسئلة + تنزيل Excel
# الملفات المطلوبة جنب هالملف: template.html ، settings.txt ، questions.xlsx ، students.xlsx
import sys, http.server, json, csv, os, socket, threading, time, urllib.parse, html, zipfile, io, shutil, random, hmac, secrets, hashlib, functools
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))          # مجلد الوحدات exam_core جنب هالملف
from exam_core import files
from exam_core.constants import L, LVL, HEAD, MAX_BODY, GRACE, YES, NO, LVL_IN, LET_IN
from exam_core.util import mtxt, E, num, load_json, atomic_write, DataError, _DIG, norm_pass, norm_code, grp
from exam_core.files import read_table, _fmt_kind, _xl_date, _pct_text, _BUILTIN_DATE_FMT
from exam_core.ctx import Ctx
from exam_core import questions as core_q, domain as core_domain, storage as core_storage, reports as core_reports, views as core_views, web as core_web, rehearsal as core_rehearsal, auth as core_auth, admin as core_admin
from exam_core.constants import PROTECTED
from exam_core.views import PASS_PCT, BANDS, CSS, TABS, SHEET_CSS, SETTINGS_BODY, MONITOR, REHEARSAL_PAGE
from exam_core.questions import IMG_EXT, _IMG_TOKEN
from exam_core.settings import default_cfg, parse_settings, decode_settings, norm_hdr, parse_rule, _rn, rule_match, _col_value, REVIEW_OUT, SPEC, SPEC_BY_KEY, COL_SKIP, edit_settings_text, _clean_setting
from exam_core.text import _MATH, _MATH_RUN, autoltr, _PUA, noimg, _SUPS, _STOP, _wc, _pair, _frac_at, _unwrap, fracs, _ISO, _MATH_OPS, qhtml_text, bdir, FRAC_CSS
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
ctx = Ctx(BASE); ctx.print = print                  # حالة هالنسخة: الحاويات بتتحدّث مكانها (ما بتنعاد تعيينها)، فهالأسماء كلها نفس كائنات ctx
SET, QLIST, BANK, PICK, ROSTER, IMG_LIST, XCODES, IMG_DIR = ctx.SET, ctx.QLIST, ctx.BANK, ctx.PICK, ctx.ROSTER, ctx.IMG_LIST, ctx.XCODES, ctx.IMG_DIR
PAPERS, CLAIMS, ANS, LIVE, SUBS, CODES, FAILS, STATE, ANS_DIRTY, LAST_TICK = ctx.PAPERS, ctx.CLAIMS, ctx.ANS, ctx.LIVE, ctx.SUBS, ctx.CODES, ctx.FAILS, ctx.STATE, ctx.ANS_DIRTY, ctx.LAST_TICK
LOCK = ctx.LOCK
REH, TOKENS, TFAIL, SET_MTIME = ctx.REH, ctx.TOKENS, ctx.TFAIL, ctx.SET_MTIME
GLBL = ctx.GLBL
_CTX_NAMES = ("OUT", "SUBS_FILE", "CLAIMS_FILE", "PAPERS_FILE", "STATE_FILE", "ANS_FILE", "CODES_FILE", "ALIVE_FILE", "MAX_COMP", "GAP_S", "REOPEN_MIN")         # مسارات الملفات والثوابت: مصدرها ctx (m.SUBS_FILE بالاختبارات والأدوات)
def __getattr__(name):                              # PAGE و PREVIEW نصوص بتتبدّل: بتنقرأ من ctx (مثلاً m.PAGE بالاختبارات)
    if name in ("PAGE", "PREVIEW") or name in _CTX_NAMES: return getattr(ctx, name)
    raise AttributeError(name)
glabel = functools.partial(core_domain.glabel, ctx)


# ---------- قراءة ملفات المعلم: settings.txt + questions.xlsx/csv + students.xlsx/csv ----------
import re, xml.etree.ElementTree as ET
def find_file(stem): return files.find_file(BASE, stem)

read_settings = functools.partial(core_storage.read_settings, ctx)
auto_title = functools.partial(core_storage.auto_title, ctx)


def with_imgs(text, errs, i): return core_q.with_imgs(ctx, text, errs, i)
def imgify(text): return core_q.imgify(ctx, text)

# ---------- الكسور: (x + 7)/(x² − 1) و 5π/6 و −3/4 بتنعرض بسط فوق خط فوق مقام ----------
def qhtml(text):
    """نص سؤال أو خيار زي ما بينعرض بأي صفحة: مهرّب، والكسور مرسومة، والصور (الصور بتعتمد على قائمة الصور فبتبقى هون)"""
    return core_q.qhtml(ctx, text)
def check_images(): return core_q.check_images(ctx)
def unpack_data_zip(): return core_q.unpack_data_zip(ctx)
def zip_leftovers(): return core_q.zip_leftovers(ctx)

def load_questions(auto_math=True): return core_q.load_questions(ctx, auto_math)

def load_roster(): return core_q.load_roster(ctx)

build_page = functools.partial(core_views.build_page, ctx)
raw_range = functools.partial(core_domain.raw_range, ctx)
total_range = functools.partial(core_domain.total_range, ctx)
eff_mark = functools.partial(core_domain.eff_mark, ctx)
key_mark = functools.partial(core_domain.key_mark, ctx)

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
    SET.update(read_settings()); QLIST[:] = load_questions(); ROSTER.update(load_roster()); check_images()
    BANK.update({q["n"]: q for q in QLIST})
    _page, _pick = build_page(); ctx.PAGE = _page; PICK.update(_pick)
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
CLAIMS.update(load_json(ctx.CLAIMS_FILE, {}))        # مفتاح الطالب -> الجهاز اللي بدأ منه
PAPERS.update(load_json(ctx.PAPERS_FILE, {}))        # مفتاح الطالب -> {start, ids, orders, extra}
STATE.update(load_json(ctx.STATE_FILE, {"closed_at": 0, "msg": {"id": 0, "text": ""}}))
if STATE.get("auto_title") != (SET["title"] if SET.get("auto_title") else None):   # العنوان التلقائي بينحفظ عشان يضل نفسه لو انعاد تشغيل السيرفر
    if SET.get("auto_title"): STATE["auto_title"] = SET["title"]
    else: STATE.pop("auto_title", None)                # عنوان مكتوب بالإعدادات: ما نخلّي عنوان تلقائي قديم يرجع بعدين
    try: atomic_write(ctx.STATE_FILE, json.dumps(STATE, ensure_ascii=False))
    except OSError: pass
ANS.update(load_json(ctx.ANS_FILE, {}))              # مفتاح الطالب -> {رقم السؤال: رقم الخيار}
# (ANS_DIRTY: مرجع من ctx)
# (LIVE: مرجع من ctx)                                   # مفتاح الطالب -> آخر نبضة من صفحة الطالب
# (SUBS: مرجع من ctx)                                   # مفتاح الطالب -> التسليم (أول تسليم فقط بعد آخر «إعادة فتح»)
if os.path.exists(ctx.SUBS_FILE):
    try:                                           # انقطاع كهرباء أثناء الكتابة ممكن يخلّي آخر سطر مقطوع بدون newline، فأول تسليم بعده كان يلتصق فيه ويضيع
        with open(ctx.SUBS_FILE, "rb+") as _f:
            _f.seek(0, 2)
            if _f.tell() > 0:
                _f.seek(-1, 2)
                if _f.read(1) != b"\n": _f.write(b"\n")
    except OSError: pass
    for line in open(ctx.SUBS_FILE, encoding="utf-8"):
        try:
            r = json.loads(line)
            if r.get("reopen"): SUBS.pop(r["key"], None)          # المعلم أعاد فتح الطالب: تسليمه اللي قبل هالسطر ما بيعدّ (بيضل بالسجل كأرشيف)
            else: SUBS.setdefault(r["key"], r)
        except Exception: pass

bank_fp = functools.partial(core_domain.bank_fp, ctx)
BANK_FP = ctx.BANK_FP = bank_fp()
check_bank_change = functools.partial(core_domain.check_bank_change, ctx)
if check_bank_change():
    try: atomic_write(ctx.STATE_FILE, json.dumps(STATE, ensure_ascii=False))
    except OSError: pass
bank_changed = functools.partial(core_domain.bank_changed, ctx)

# (CODES: مرجع من ctx)                                  # "صف|شعبة|اسم" -> رمز الدخول
# (FAILS: مرجع من ctx)                                  # مفتاح الطالب -> [عدد المحاولات الخاطئة، قفل لحد وقت]
init_codes = functools.partial(core_storage.init_codes, ctx)
check_code = functools.partial(core_storage.check_code, ctx)
if SET["needCode"]: init_codes()
try: ctx.SET_MTIME[0] = os.path.getmtime(os.path.join(BASE, "settings.txt"))
except OSError: pass
refresh_tpass = functools.partial(core_auth.refresh_tpass, ctx)

login_page = functools.partial(core_views.login_page, ctx)

build_preview = functools.partial(core_views.build_preview, ctx)
ctx.PREVIEW = build_preview()
save_claims = functools.partial(core_storage.save_claims, ctx)
save_papers = functools.partial(core_storage.save_papers, ctx)
parse_key = functools.partial(core_domain.parse_key, ctx)
make_paper = functools.partial(core_domain.make_paper, ctx)
save_state = functools.partial(core_storage.save_state, ctx)
paused_for = functools.partial(core_domain.paused_for, ctx)
settle_pause = functools.partial(core_domain.settle_pause, ctx)
deadline = functools.partial(core_domain.deadline, ctx)
remain_of = functools.partial(core_domain.remain_of, ctx)
fmt_dur = functools.partial(core_domain.fmt_dur, ctx)
pub_q = functools.partial(core_domain.pub_q, ctx)
paper_reply = functools.partial(core_domain.paper_reply, ctx)
clean_ans = functools.partial(core_domain.clean_ans, ctx)
COMP = None                                          # نتيجة التعويض عند آخر تشغيل (للبانر)
beat = functools.partial(core_storage.beat, ctx)
def flusher():
    """الإجابات بتتغير كل بضع ثواني لـ 80 طالب، فنحفظها على الملف كل 3 ثواني (مش مع كل نبضة). ونفس الدورة بتسجّل «السيرفر لسا شغّال» بـ alive.txt"""
    while True:
        time.sleep(3)
        try: gap_check(tick=True); flush_answers(); beat()
        except Exception as e: print("تنبيه: خطأ بدورة الحفظ (بتكمل):", repr(e))      # ما نخلّي الدورة تموت: هي اللي بتحفظ الإجابات
# (LAST_TICK: مرجع من ctx)          # آخر لحظة كان فيها السيرفر «صاحي» (دورة الحفظ بتحدّثها كل 3 ث). None = الدورة مش شغّالة (مثلاً وقت check_files)
gap_check = functools.partial(core_storage.gap_check, ctx)
flush_answers = functools.partial(core_storage.flush_answers, ctx)
extend_time = functools.partial(core_storage.extend_time, ctx)
compensate_downtime = functools.partial(core_storage.compensate_downtime, ctx)
submit_for = functools.partial(core_storage.submit_for, ctx)
reopen_student = functools.partial(core_storage.reopen_student, ctx)
write_results_csv = functools.partial(core_storage.write_results_csv, ctx)

wrong_items = functools.partial(core_domain.wrong_items, ctx)
wrong_text = functools.partial(core_domain.wrong_text, ctx)

def safe_fn(s):
    """اسم ملف آمن على ويندوز من اسم طالب: الحروف والأرقام والمسافة والشرطة، وأي شي ثاني بيصير _"""
    return "".join(c if (c.isalnum() or c in " -") else "_" for c in s).strip(" _")[:50] or "x"
ST_AR = {"done": "سلّم", "live": "بدأ ولم يسلّم", "lost": "بدأ ولم يسلّم", "none": "لم يبدأ"}
def export_static(d, secs):
    """نتائج جاهزة تنفتح بأي متصفح بدون Python ولا سيرفر: مجلد «نتائج» بالأرشيف لحاله (فيه صوره كمان، فبيتنقل أو بيتبعت كمجلد واحد): صفحة رئيسية (العلامات
    ومدة الحل)، وورقة كل طالب، وورقات كل شعبة للطباعة، والتقرير وملف Excel، والأسئلة مع الإجابات. كلها من نفس دوال السيرفر (student_rows وsheet_html وreport_page
    وbuild_xlsx وkey_page) على بيانات الذاكرة، ونحط الشعب اللي امتحنت بس (نبدّل ROSTER مؤقتاً داخل القفل). بتنادى قبل تصفير الذاكرة"""
    root = os.path.join(d, "نتائج"); sheets = os.path.join(root, "ورقات"); home = "ابدأ_من_هنا.html"
    os.makedirs(sheets)
    if os.path.isdir(IMG_DIR): shutil.copytree(IMG_DIR, os.path.join(root, "images"))
    saved = {g: dict(ss) for g, ss in ROSTER.items()}
    _lim = {g: {s: ns for s, ns in ss.items() if (g, s) in secs} for g, ss in saved.items()}
    ROSTER.clear(); ROSTER.update({g: ss for g, ss in _lim.items() if ss})
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
        ROSTER.clear(); ROSTER.update(saved)
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
        try: atomic_write(ctx.ANS_FILE, json.dumps(ANS, ensure_ascii=False))
        except OSError: pass
    for f in (ctx.SUBS_FILE, ctx.CLAIMS_FILE, ctx.PAPERS_FILE, ctx.STATE_FILE, ctx.ANS_FILE):
        if os.path.exists(f): shutil.move(f, os.path.join(d, os.path.basename(f)))
    if os.path.exists(ctx.OUT):                      # ننسخ (مش ننقل) لأنه ممكن يكون مفتوح بـ Excel
        shutil.copy2(ctx.OUT, os.path.join(d, os.path.basename(ctx.OUT)))
    try: export_results(d, keys)
    except Exception as e: print("تنبيه: تعذّر تجهيز مجلد النتائج:", repr(e))            # الأرشفة نفسها (نقل الملفات) ما لازم تفشل بسبب هاي الإضافة
    CLAIMS.clear(); LIVE.clear(); SUBS.clear(); PAPERS.clear(); ANS.clear(); ANS_DIRTY[0] = False
    reh_reset()                                  # أي بروفة كانت شغّالة بتنتهي مع الامتحان القديم
    STATE["bank_fp"] = BANK_FP; STATE.pop("bank_changed", None)
    if SET.get("auto_title"): new_auto_title()
    else: save_state()
    write_results_csv()
    return d
new_auto_title = functools.partial(core_admin.new_auto_title, ctx)

# ---------- بروفة الضغط: كل أجهزة المختبر بتطلب «ابدأ» بنفس اللحظة (حسب ساعة السيرفر، مش ساعة الأجهزة) ----------
# بالذاكرة بس (بتنطفي بإعادة تشغيل السيرفر). كل الدوال هون بتتنادى داخل LOCK. البروفة بتستعمل مسار الطالب الحقيقي (/start و/ping و/submit)
reh_release = functools.partial(core_rehearsal.reh_release, ctx)
reh_stop = functools.partial(core_rehearsal.reh_stop, ctx)
reh_reset = functools.partial(core_rehearsal.reh_reset, ctx)
reh_tick = functools.partial(core_rehearsal.reh_tick, ctx)
reh_assign = functools.partial(core_rehearsal.reh_assign, ctx)
reh_command = functools.partial(core_rehearsal.reh_command, ctx)
reh_summary = functools.partial(core_rehearsal.reh_summary, ctx)

# ---------- تجميع البيانات للمراقبة والتقارير ----------
find_keys = functools.partial(core_reports.find_keys, ctx)
student_rows = functools.partial(core_reports.student_rows, ctx)
question_stats = functools.partial(core_reports.question_stats, ctx)
section_stats = functools.partial(core_reports.section_stats, ctx)

# ---------- ملف Excel بسيط (بدون مكتبات) ----------
xlsx_bytes = functools.partial(core_reports.xlsx_bytes, ctx)
build_xlsx = functools.partial(core_reports.build_xlsx, ctx)

# ---------- صفحات المعلم ----------
teacher_nav = functools.partial(core_views.teacher_nav, ctx)
teacher_page = functools.partial(core_views.teacher_page, ctx)
# ---------- صفحة «إعدادات الامتحان»: بتقرأ وبتكتب نفس settings.txt (الملف يضل هو المصدر) ----------
settings_started = functools.partial(core_admin.settings_started, ctx)
_eff = functools.partial(core_admin._eff, ctx)
settings_columns = functools.partial(core_admin.settings_columns, ctx)
settings_state = functools.partial(core_admin.settings_state, ctx)
apply_settings = functools.partial(core_admin.apply_settings, ctx)
settings_page = functools.partial(core_views.settings_page, ctx)
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
band_of = functools.partial(core_views.band_of, ctx)
rv_block = functools.partial(core_views.rv_block, ctx)
report_page = functools.partial(core_views.report_page, ctx)

# ---------- ورقة الطالب (للمعلم فقط) ----------
sheet_html = functools.partial(core_views.sheet_html, ctx)
sheet_page = functools.partial(core_views.sheet_page, ctx)

codes_page = functools.partial(core_views.codes_page, ctx)

key_page = functools.partial(core_views.key_page, ctx)

class _App:
    """نافذة على متغيرات server.py (بتنقرأ وقت الاستعمال): web.py بيوصل لدوال التشغيل والصحة والبروفة عبرها، فتبديلها بالاختبارات (m.ip = ...) بيوصل للمعالج"""
    def __getattr__(self, n):
        try: return globals()[n]
        except KeyError: raise AttributeError(n)
H = core_web.make_handler(ctx, _App())

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
            "disk": {"free_mb": None if free is None else int(free / 1048576), "writable": writable, "results": ctx.OUT, "results_age_s": int(now - os.path.getmtime(ctx.OUT)) if os.path.exists(ctx.OUT) else None},
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
             f"النتائج بتنحفظ في: {ctx.OUT}", f"سجل الأحداث بالعربي (من بدأ، من سلّم، تنبيهات...): {LOG_FILE}", "    (بيتحدّث لحاله؛ افتحه بالمفكرة وقت ما بدك)", "",
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
    print(f"  Results saved in / النتائج تنحفظ في: {ctx.OUT}\n  To stop: Ctrl+C or close this window / للإيقاف\n")
    try: srv.serve_forever()
    finally: flush_answers(); keep_awake(False)
