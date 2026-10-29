"""رفع الأسئلة والطلاب والصور من صفحة «الملفات»: كل ملف بينفحص مقابل القالب الأصلي (أعمدته بترتيبها)، وبنجرّب كل شي (قراءة الملف وبناء الصفحات) قبل ما نكتب أو نبدّل الذاكرة. كل دالة بتاخذ ctx كأول وسيط."""
import io, os, re, shutil, time, zipfile
from .admin import settings_columns, settings_started
from .domain import bank_fp, check_bank_change
from .constants import LVL
from .files import read_table
from .questions import IMG_EXT, load_questions, load_roster
from .reports import xlsx_bytes
from .settings import norm_hdr
from .storage import init_codes, save_state
from .util import DataError, atomic_write_bytes
from .views import build_page, build_preview

MB = 1024 * 1024
LIMITS = {"questions": 5 * MB, "students": 5 * MB, "image": 5 * MB, "images_zip": 20 * MB}      # أكبر حجم لكل نوع رفع (بايت)
ZIP_MAX_TOTAL, ZIP_MAX_FILES = 100 * MB, 1000                                                    # حماية من zip ضخم بعد الفك
# القالب الأصلي (questions_template.xlsx / students_template.xlsx): العناوين بالأسماء الكاملة، وأمثلة القالب (اختبار بيتأكد إنها متطابقة مع ملفي القالب)
Q_HEAD_FULL = ("السؤال", "أ", "ب", "ج", "د", "الجواب", "المستوى", "المرجع (اختياري)", "الحل (اختياري)", "العلامة (اختياري)")
Q_HEAD = tuple(norm_hdr(h) for h in Q_HEAD_FULL)
Q_FIXED = "ثابت"                                          # العمود K (اختياري)؛ أعمدة المعلم الإضافية (الوحدة...) من L
Q_EXAMPLE_ROWS = (("مثال: ما قيمة 2 + 3 × 4؟", "14", "20", "24", "10", "أ", "سهل", "ص 5", "الضرب قبل الجمع: 3 × 4 = 12 ثم 2 + 12 = 14", "1"),
                  ("Example: Choose the correct word: She ____ to school every day.", "go", "goes", "going", "gone", "ب", "وسط", "Unit 2", "Third person singular takes -es", "2"),
                  ("مثال بثلاثة خيارات فقط (الخيار د فاضي): أي هذه الأعداد أولي؟", "9", "7", "15", "", "ب", "صعب", "", "7 لا يقبل القسمة إلا على 1 ونفسه", "3"))
S_HEAD_FULL = ("الصف", "الشعبة", "الاسم", "الرمز (اختياري)")
S_HEAD = tuple(norm_hdr(h) for h in S_HEAD_FULL)
S_EXAMPLE_ROWS = (("العاشر", "أ", "اسم الطالب الأول", ""), ("العاشر", "أ", "اسم الطالب الثاني", ""), ("العاشر", "ب", "اسم الطالب الثالث", ""))
LOCK_MSG = "الامتحان بدأ، فالأسئلة والصور مقفلة (الأوراق انسحبت منها). لأسئلة جديدة ابدأ امتحاناً جديداً من شاشة المراقبة أولاً."
KEEP_BACKUPS = 20
_ALEF = str.maketrans("إأآ", "ااا")

def _n(s): return str(s).translate(_ALEF).strip()
def _col(i):
    s = ""; i += 1
    while i: i, r = divmod(i - 1, 26); s = chr(65 + r) + s
    return s
def _errors(head, errs, tail):
    return DataError(head + "\n" + "\n".join(errs) + ("\n" + tail if tail else ""))
def check_questions_rows(rows):
    """هل الجدول على قالب الأسئلة؟ الأعمدة A–J بعناوينها وترتيبها، والعمود K «ثابت» أو فاضي، وما في عناوين مكررة، وسطور المثال محذوفة"""
    if not rows or not any(c for c in rows[0]): raise DataError("الملف فاضي: لازم السطر الأول فيه عناوين الأعمدة حسب القالب")
    hdr = [_n(norm_hdr(c)) for c in rows[0]]
    if hdr[:3] == [_n(h) for h in S_HEAD[:3]]: raise DataError("هذا ملف الطلاب (الأعمدة: الصف، الشعبة، الاسم) مش ملف الأسئلة. ارفعه بخانة «الطلاب».")
    want = [_n(h) for h in Q_HEAD]
    errs = [f"العمود {_col(j)}: لازم عنوانه «{w}» حسب القالب، لقيت «{rows[0][j] if j < len(rows[0]) and rows[0][j] else 'فاضي'}»" for j, w in enumerate(want) if (hdr[j] if j < len(hdr) else "") != w]
    if errs: raise _errors("هذا الملف مش على قالب الأسئلة:", errs, "نزّل القالب من نفس الصفحة وانسخ أسئلتك فيه، وما تغيّر أعمدته الأولى (من A إلى J).")
    if len(hdr) > 10 and hdr[10] and hdr[10] != Q_FIXED:
        raise DataError(f"العمود K لازم عنوانه «{Q_FIXED}» أو يبقى فاضي. أعمدتك الإضافية (مثل «الوحدة») حطها من العمود L.")
    named = [h for h in hdr if h]
    dup = sorted({h for h in named if named.count(h) > 1})
    if dup: raise DataError("عناوين أعمدة مكررة: " + "، ".join(dup) + " — كل عمود لازم يكون له عنوان مختلف.")
    ex = {r[0] for r in Q_EXAMPLE_ROWS}
    left = [str(i) for i, r in enumerate(rows[1:], 2) if r and r[0].strip() in ex]
    if left: raise DataError("سطر المثال من القالب لساتو موجود (سطر " + "، ".join(left) + "): احذفه أو بدّله بسؤالك.")
def check_students_rows(rows):
    """هل الجدول على قالب الطلاب؟ A–C: الصف والشعبة والاسم، و D «الرمز» أو فاضي، وأسماء المثال محذوفة"""
    if not rows or not any(c for c in rows[0]): raise DataError("الملف فاضي: لازم السطر الأول فيه عناوين الأعمدة حسب القالب")
    hdr = [_n(norm_hdr(c)) for c in rows[0]]
    if hdr and hdr[0] == _n(Q_HEAD[0]): raise DataError("هذا ملف الأسئلة (العمود الأول «السؤال») مش ملف الطلاب. ارفعه بخانة «الأسئلة».")
    want = [_n(h) for h in S_HEAD]
    errs = [f"العمود {_col(j)}: لازم عنوانه «{w}» حسب القالب، لقيت «{rows[0][j] if j < len(rows[0]) and rows[0][j] else 'فاضي'}»" for j, w in enumerate(want[:3]) if (hdr[j] if j < len(hdr) else "") != w]
    if errs: raise _errors("هذا الملف مش على قالب الطلاب:", errs, "نزّل القالب من نفس الصفحة وانسخ أسماء طلابك فيه.")
    if len(hdr) > 3 and hdr[3] and hdr[3] != _n(S_HEAD[3]): raise DataError(f"العمود D لازم عنوانه «{S_HEAD[3]}» أو يبقى فاضي.")
    ex = {r[2] for r in S_EXAMPLE_ROWS}
    left = [str(i) for i, r in enumerate(rows[1:], 2) if len(r) > 2 and r[2].strip() in ex]
    if left: raise DataError("أسماء المثال من القالب (اسم الطالب الأول...) لساتها موجودة (سطر " + "، ".join(left) + "): احذفها أو بدّلها بأسماء طلابك.")
def check_image(name, data):
    """اسم الصورة (ملف بدون مجلدات) وصيغتها وحجمها ومحتواها الفعلي (مش بس الامتداد). بيرجّع الاسم النظيف"""
    base = os.path.basename(str(name).replace("\\", "/")).strip()
    if not base or base.startswith(".") or re.search(r'[<>:"|?*\x00-\x1f]', base): raise DataError(f"اسم الصورة «{name}» غير صالح")
    ext = os.path.splitext(base)[1].lower()
    if ext not in IMG_EXT: raise DataError(f"الصورة «{base}» صيغتها غير مدعومة (المدعوم: png, jpg, gif, webp, svg)")
    if not data: raise DataError(f"الصورة «{base}» فاضية")
    if len(data) > LIMITS["image"]: raise DataError(f"الصورة «{base}» أكبر من {LIMITS['image'] // MB} MB")
    ok = {".png": data[:8] == b"\x89PNG\r\n\x1a\n", ".jpg": data[:3] == b"\xff\xd8\xff", ".jpeg": data[:3] == b"\xff\xd8\xff", ".gif": data[:4] == b"GIF8",
          ".webp": data[:4] == b"RIFF" and data[8:12] == b"WEBP"}.get(ext)
    if ext == ".svg":
        try: s = data.decode("utf-8-sig")
        except UnicodeDecodeError: raise DataError(f"الصورة «{base}» ملف SVG تالف")
        if "<svg" not in s[:2000].lower(): raise DataError(f"الملف «{base}» مش صورة SVG سليمة")
        if re.search(r"<script|javascript:|\son[a-z]+\s*=|<foreignobject", s, re.I): raise DataError(f"الصورة «{base}» (SVG) فيها كود نشط مش مسموح")
    elif not ok: raise DataError(f"الملف «{base}» مش صورة {ext[1:]} حقيقية (محتواه ما بيطابق صيغته)")
    return base
def _check_xlsx(data):
    if not data.startswith(b"PK"): raise DataError("هذا مش ملف Excel (xlsx). افتحه بـ Excel واحفظه «Save as» بصيغة Excel Workbook (xlsx).")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        if "xl/workbook.xml" not in z.namelist(): raise DataError("هذا مش ملف Excel (xlsx) سليم. احفظه من Excel بصيغة Workbook (xlsx).")
        if sum(i.file_size for i in z.infolist()) > 60 * MB: raise DataError("الملف ضخم بشكل غير طبيعي بعد الفك — مرفوض")
    except zipfile.BadZipFile: raise DataError("ملف Excel تالف أو مش مكتمل — احفظه من جديد وارفعه")
def _read(path, want):
    try: return read_table(path, want)
    except DataError: raise
    except Exception: raise DataError("ما قدرت أقرأ الملف. لازم يكون Excel (xlsx) سليم، محفوظ من Excel أو LibreOffice.")
def _stage(ctx, kind, data):
    _check_xlsx(data)
    path = os.path.join(ctx.BASE, f".upload_{kind}.xlsx")
    with open(path, "wb") as f: f.write(data)
    return path
def _unstage(path):
    try: os.remove(path)
    except OSError: pass
def _save(ctx, stem, data):
    """بيحفظ الملف الجديد مكان القديم، وبيحتفظ بنسخة من القديم بمجلد نسخ_الملفات (آخر 20 لكل نوع)"""
    path = os.path.join(ctx.BASE, stem + ".xlsx")
    if os.path.exists(path):
        bdir = os.path.join(ctx.BASE, "نسخ_الملفات"); os.makedirs(bdir, exist_ok=True)
        nm = f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}"; i = 0
        while os.path.exists(os.path.join(bdir, nm + (f"_{i}" if i else "") + ".xlsx")): i += 1
        shutil.copy2(path, os.path.join(bdir, nm + (f"_{i}" if i else "") + ".xlsx"))
        for f in sorted(f for f in os.listdir(bdir) if f.startswith(stem + "_") and f.endswith(".xlsx"))[:-KEEP_BACKUPS]:
            try: os.remove(os.path.join(bdir, f))
            except OSError: pass
    try: atomic_write_bytes(path, data)
    except OSError as e: raise DataError(f"تعذّرت كتابة {stem}.xlsx: {e}\nإذا الملف مفتوح بـ Excel سكّره وارفع من جديد.")
def _rebuild(ctx):
    page, pick = build_page(ctx); prev = build_preview(ctx)
    ctx.PAGE = page; ctx.PICK.clear(); ctx.PICK.update(pick); ctx.PREVIEW = prev
def _snap(ctx): return (list(ctx.QLIST), dict(ctx.BANK), list(ctx.IMG_LIST), ctx.PAGE, dict(ctx.PICK), ctx.PREVIEW, dict(ctx.GLBL), ctx.BANK_FP, {k: {a: dict(b) if isinstance(b, dict) else list(b) for a, b in v.items()} for k, v in ctx.ROSTER.items()}, dict(ctx.XCODES))
def _restore(ctx, s):
    ctx.QLIST[:] = s[0]; ctx.BANK.clear(); ctx.BANK.update(s[1]); ctx.IMG_LIST[:] = s[2]; ctx.PAGE = s[3]; ctx.PICK.clear(); ctx.PICK.update(s[4]); ctx.PREVIEW = s[5]
    ctx.GLBL.clear(); ctx.GLBL.update(s[6]); ctx.BANK_FP = s[7]; ctx.ROSTER.clear(); ctx.ROSTER.update(s[8]); ctx.XCODES.clear(); ctx.XCODES.update(s[9])
def _img_files(ctx):
    try: return sorted(f for f in os.listdir(ctx.IMG_DIR) if os.path.splitext(f)[1].lower() in IMG_EXT and os.path.isfile(os.path.join(ctx.IMG_DIR, f)))
    except OSError: return []
def _shown(names):
    """أعمدة الأسئلة اللي بنعرض توزيعها بملخص الصفحة: الوحدة وأي عمود تصنيف للمعلم (المستوى بينعرض لحاله، والمرجع قيمه كثيرة)"""
    return [c for c in names if c not in ("المستوى", "المرجع")][:3]
def _levels(ctx):
    lv = {}
    for q in ctx.QLIST: k = LVL.get(q["level"], "بدون مستوى"); lv[k] = lv.get(k, 0) + 1
    return lv
def upload_questions(ctx, data):
    if settings_started(ctx): raise DataError(LOCK_MSG)
    path = _stage(ctx, "questions", data); snap = _snap(ctx)
    try:
        check_questions_rows(_read(path, ("السؤال", "question")))
        ctx.IMG_LIST[:] = []
        try: new = load_questions(ctx, path=path)
        except DataError as e:
            lines = str(e).split("\n")
            raise DataError("\n".join(lines[:25]) + (f"\n… و{len(lines) - 25} ملاحظة أخرى" if len(lines) > 25 else "") + "\nصحّح الملف وارفعه من جديد. ما تغيّر شي.")
        ctx.QLIST[:] = new; ctx.BANK.clear(); ctx.BANK.update({q["n"]: q for q in new})
        try: _rebuild(ctx)
        except DataError as e: raise DataError(f"الأسئلة سليمة بس ما بتناسب إعدادات السحب الحالية: {e}\nعدّل الإعدادات (تبويب «إعدادات الامتحان») أو الأسئلة وارفع من جديد. ما تغيّر شي.")
        _save(ctx, "questions", data)
        ctx.BANK_FP = bank_fp(ctx); check_bank_change(ctx); save_state(ctx)
    except BaseException:
        _restore(ctx, snap); raise
    finally: _unstage(path)
    names, cols, _ = settings_columns(ctx)
    big = [f"{n} ({os.path.getsize(os.path.join(ctx.IMG_DIR, n)) // 1024}KB)" for n in ctx.IMG_LIST if os.path.getsize(os.path.join(ctx.IMG_DIR, n)) > 500 * 1024]
    return {"count": len(ctx.QLIST), "levels": _levels(ctx), "columns": {c: cols[c] for c in _shown(names)}, "images_used": len(ctx.IMG_LIST),
            "picked": sum(ctx.PICK.values()), "warnings": ([f"صور كبيرة (يفضّل أقل من 500KB): {'، '.join(big)}"] if big else [])}
def upload_students(ctx, data):
    path = _stage(ctx, "students", data); snap = _snap(ctx); old = {(g, s, n) for g, ss in ctx.ROSTER.items() for s, ns in ss.items() for n in ns}
    try:
        check_students_rows(_read(path, ("الصف", "الاسم", "grade", "name")))
        ctx.XCODES.clear()
        try: ros = load_roster(ctx, path=path)
        except DataError as e:
            lines = str(e).split("\n")
            raise DataError("\n".join(lines[:25]) + (f"\n… و{len(lines) - 25} ملاحظة أخرى" if len(lines) > 25 else "") + "\nصحّح الملف وارفعه من جديد. ما تغيّر شي.")
        new = {(g, s, n) for g, ss in ros.items() for s, ns in ss.items() for n in ns}
        if settings_started(ctx):                                  # الامتحان بدأ: ممنوع تنحذف أسماء طلاب عندهم ورقة أو تسليم (الإضافة مسموحة)
            used = set()
            for k in list(ctx.PAPERS) + list(ctx.CLAIMS) + list(ctx.SUBS):
                p = k.rsplit("|", 3) if isinstance(k, str) else []
                if len(p) == 4 and p[0] == ctx.SET["title"]: used.add(tuple(p[1:]))
            gone = sorted(used - new)
            if gone: raise DataError("الامتحان بدأ، وهدول الطلاب عندهم ورقة أو تسليم وما لاقيتهم بالملف الجديد: " + "، ".join(n for _, _, n in gone[:10]) + (" …" if len(gone) > 10 else "") + "\nبعد بدء الامتحان بتقدر بس تضيف طلاب، مش تحذف أو تغيّر أسماء.")
        ctx.ROSTER.clear(); ctx.ROSTER.update(ros)
        _rebuild(ctx)
        _save(ctx, "students", data)
    except BaseException:
        _restore(ctx, snap); raise
    finally: _unstage(path)
    if ctx.SET["needCode"]: init_codes(ctx)
    return {"count": len(new), "sections": [[g, s, len(ns)] for g, ss in ros.items() for s, ns in ss.items()], "added": len(new - old), "removed": len(old - new)}
def upload_image(ctx, name, data):
    if settings_started(ctx): raise DataError(LOCK_MSG)
    base = check_image(name, data); os.makedirs(ctx.IMG_DIR, exist_ok=True); path = os.path.join(ctx.IMG_DIR, base); replaced = os.path.exists(path)
    try: atomic_write_bytes(path, data)
    except OSError as e: raise DataError(f"تعذّر حفظ الصورة «{base}»: {e}")
    return {"name": base, "replaced": replaced}
def upload_images_zip(ctx, data):
    if settings_started(ctx): raise DataError(LOCK_MSG)
    try: z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile: raise DataError("ملف الصور تالف أو مش zip صحيح")
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > ZIP_MAX_FILES or sum(i.file_size for i in infos) > ZIP_MAX_TOTAL: raise DataError("الـ zip فيه ملفات كثيرة أو حجمه بعد الفك ضخم جداً — مرفوض")
    found, ignored, seen = {}, 0, set()
    for i in infos:
        parts = i.filename.replace("\\", "/").split("/")
        if parts[0] == "__MACOSX" or parts[-1].startswith(".") or os.path.splitext(parts[-1])[1].lower() not in IMG_EXT: ignored += 1; continue
        if i.file_size > LIMITS["image"]: raise DataError(f"الصورة «{parts[-1]}» أكبر من {LIMITS['image'] // MB} MB")
        b = parts[-1]
        if b in seen: raise DataError(f"اسم الصورة «{b}» مكرر بمجلدين مختلفين بالـ zip — غيّر أحدهما")
        seen.add(b); found[b] = check_image(b, z.read(i))
    if not found: raise DataError("ما لقيت أي صورة (png, jpg, gif, webp, svg) داخل الـ zip")
    added = replaced = 0
    os.makedirs(ctx.IMG_DIR, exist_ok=True)
    for i in infos:
        b = i.filename.replace("\\", "/").split("/")[-1]
        if b not in found: continue
        path = os.path.join(ctx.IMG_DIR, b); replaced += os.path.exists(path); added += not os.path.exists(path)
        try: atomic_write_bytes(path, z.read(i))
        except OSError as e: raise DataError(f"تعذّر حفظ الصورة «{b}»: {e}")
    return {"added": added, "replaced": replaced, "ignored": ignored}
def handle_upload(ctx, kind, name, data):
    """نقطة الدخول الوحيدة للرفع: kind = questions | students | image | images_zip"""
    if kind == "questions": return upload_questions(ctx, data)
    if kind == "students": return upload_students(ctx, data)
    if kind == "image": return upload_image(ctx, name, data)
    if kind == "images_zip": return upload_images_zip(ctx, data)
    raise DataError("نوع الرفع غير معروف")
def _fileinfo(ctx, stem):
    for ext in (".xlsx", ".csv"):
        p = os.path.join(ctx.BASE, stem + ext)
        if os.path.exists(p): return {"name": stem + ext, "kb": max(1, os.path.getsize(p) // 1024), "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p)))}
    return None
def files_state(ctx):
    """حالة صفحة «الملفات»: الأسئلة والطلاب والصور الحالية والأقفال"""
    names, cols, _ = settings_columns(ctx); imgs = _img_files(ctx)
    return {"started": settings_started(ctx), "limits": {k: v // MB for k, v in LIMITS.items()},
            "questions": {"count": len(ctx.QLIST), "levels": _levels(ctx), "columns": {c: cols[c] for c in _shown(names)}, "images_used": len(ctx.IMG_LIST), "picked": sum(ctx.PICK.values()), "file": _fileinfo(ctx, "questions")},
            "students": {"count": sum(len(ns) for ss in ctx.ROSTER.values() for ns in ss.values()), "sections": [[g, s, len(ns)] for g, ss in ctx.ROSTER.items() for s, ns in ss.items()], "file": _fileinfo(ctx, "students")},
            "images": {"count": len(imgs), "unused": [f for f in imgs if f not in ctx.IMG_LIST]}}
def template_bytes(ctx, kind):
    """قالب للتنزيل: ملف القالب الأصلي جنب server.py لو موجود، وإلا بنولّده من نفس العناوين والأمثلة"""
    p = os.path.join(ctx.BASE, f"{kind}_template.xlsx")
    if os.path.exists(p):
        with open(p, "rb") as f: return f.read()
    if kind == "questions": return xlsx_bytes(ctx, [("الأسئلة", [48, 14, 14, 14, 14, 10, 10, 16, 36, 12], [list(Q_HEAD_FULL)] + [list(r) for r in Q_EXAMPLE_ROWS])])
    return xlsx_bytes(ctx, [("الطلاب", [16, 12, 36, 18], [list(S_HEAD_FULL)] + [list(r) for r in S_EXAMPLE_ROWS])])
