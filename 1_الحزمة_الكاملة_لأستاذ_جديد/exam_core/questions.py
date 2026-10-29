"""طبقة الأسئلة والطلاب: تحميل الأسئلة والطلاب والصور وفك exam_data.zip. كل دالة بتاخذ ctx (حالة النسخة) كأول وسيط."""
import os, re, shutil, urllib.parse, zipfile
from . import files
from .constants import LET_IN, LVL_IN, NO, YES
from .settings import norm_hdr
from .text import _PUA, autoltr, qhtml_text
from .util import DataError, num

IMG_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml"}
_IMG_TOKEN = re.compile(r"\[\s*(?:img|IMG|Img|صورة)\s*[:：]\s*([^\]\n]+?)\s*\]")
def with_imgs(ctx, text, errs, i):
    """[img:اسم.png] داخل نص السؤال/الخيار -> رمز خاص بيتحوّل لصورة وقت العرض (imgify). بنتأكد إن الملف موجود بمجلد images"""
    def one(m):
        name = m.group(1).strip()
        if name != os.path.basename(name.replace("\\", "/")) or not name:
            errs.append(f"questions سطر {i}: اسم الصورة «{name}» لازم يكون اسم ملف بدون مجلدات"); return ""
        if os.path.splitext(name)[1].lower() not in IMG_EXT:
            errs.append(f"questions سطر {i}: الصورة «{name}» صيغتها غير مدعومة (المدعوم: png, jpg, gif, webp, svg)"); return ""
        if not os.path.isfile(os.path.join(ctx.IMG_DIR, name)):
            errs.append(f"questions سطر {i}: الصورة «{name}» غير موجودة بمجلد images"); return ""
        if name not in ctx.IMG_LIST: ctx.IMG_LIST.append(name)
        return chr(0xE100 + ctx.IMG_LIST.index(name))
    return _IMG_TOKEN.sub(one, text)
def imgify(ctx, text):
    return re.sub(_PUA, lambda m: '<img class="qimg" src="/img/%s" alt="" draggable="false">' % urllib.parse.quote(ctx.IMG_LIST[ord(m.group()) - 0xE100]), text)
def check_images(ctx):
    if not ctx.IMG_LIST: return
    ctx.print(f"الصور: {len(ctx.IMG_LIST)} صورة مستعملة بالأسئلة")
    for n in ctx.IMG_LIST:
        kb = os.path.getsize(os.path.join(ctx.IMG_DIR, n)) // 1024
        if kb > 500: ctx.print(f"تنبيه: الصورة «{n}» حجمها {kb}KB — يفضّل أقل من 500KB عشان تنفتح بسرعة على أجهزة الطلاب")
def unpack_data_zip(ctx):
    """لو بجانب server.py ملف exam_data.zip (الأسئلة + مجلد images، وأحياناً الطلاب والإعدادات) بنفكّه تلقائياً (مرة لكل نسخة من الملف).
    قائمة الطلاب والإعدادات الموجودة (تبع مشرف المختبر) ما بتنستبدل: نسخة الـzip بتنحفظ جنبها باسم *_from_zip"""
    zp = os.path.join(ctx.BASE, "exam_data.zip"); mk = os.path.join(ctx.BASE, ".exam_data_unpacked")
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
    os.makedirs(ctx.IMG_DIR, exist_ok=True)
    for info in z.infolist():
        if info.is_dir(): continue
        name = info.filename.replace("\\", "/").strip("/")
        if strip and name.startswith(strip): name = name[len(strip):]
        parts = name.split("/")
        if any(p in ("", ".", "..") for p in parts) or info.file_size > 25 * 1024 * 1024: skipped += 1; continue
        if len(parts) == 1 and parts[0].lower() in data:
            fn = parts[0].lower(); dest = os.path.join(ctx.BASE, fn)
            stem, ext = os.path.splitext(fn)
            mine = [e for e in ((".txt",) if stem == "settings" else (".xlsx", ".csv")) if os.path.exists(os.path.join(ctx.BASE, stem + e))] if stem in ("students", "settings") else []
            if mine:                                                    # قائمة الطلاب/الإعدادات تبع المشرف موجودة: ما نستبدلها، نحفظ نسخة الـzip جنبها
                dest = os.path.join(ctx.BASE, f"{stem}_from_zip{ext}"); kept.append(os.path.basename(dest))
            elif stem in ("questions", "students"):                    # الصيغة الجديدة بتلغي القديمة (السيرفر بيفضّل xlsx على csv)
                other = os.path.join(ctx.BASE, stem + (".csv" if ext == ".xlsx" else ".xlsx"))
                if os.path.exists(other): os.remove(other)
        elif len(parts) == 2 and parts[0].lower() == "images" and os.path.splitext(parts[1])[1].lower() in IMG_EXT:
            dest = os.path.join(ctx.IMG_DIR, parts[1])
        else: skipped += 1; continue
        with z.open(info) as src, open(dest, "wb") as out: shutil.copyfileobj(src, out)
        done += 1
    z.close()
    open(mk, "w", encoding="utf-8").write(sig)
    ctx.print(f"تم فك exam_data.zip: {done} ملف" + (f" (تجاهلت {skipped} ملف غير مألوف)" if skipped else ""))
    if kept: ctx.print("تنبيه: exam_data.zip فيه قائمة طلاب أو إعدادات، بس عندك نسختك فما استبدلناها. نسخة الـzip انحفظت باسم: " + "، ".join(kept))
def zip_leftovers(ctx):
    """نسخ طلاب/إعدادات جت مع exam_data.zip وما انستعملت (لأن تبع المشرف موجودة)"""
    try: return sorted(f for f in os.listdir(ctx.BASE) if f.split(".")[0] in ("students_from_zip", "settings_from_zip"))
    except OSError: return []                     # صفحة الفحص ما لازم توقع لو المجلد مش مقروء
def _lost_text(t):
    """«؟؟؟»: ملف CSV انحفظ بترميز ما بيدعم العربي (CSV عادي بإكسل على ويندوز غير عربي) فاستبدل الحروف بعلامات استفهام"""
    s = "".join(str(t).split())
    return len(s) >= 3 and s.count("?") >= 3 and s.count("?") / len(s) >= 0.6
def load_questions(ctx, auto_math=True, path=None):
    """path: ملف أسئلة بمكان ثاني (فحص ملف مرفوع قبل ما ينحفظ)؛ بدونه بنقرأ questions.xlsx من مجلد الامتحان"""
    rows = files.read_table(path or files.find_file(ctx.BASE, "questions"), ("السؤال", "question"))
    out, errs = [], []
    hdr = [norm_hdr(c) for c in rows[0]]
    for i, r in enumerate(rows[1:], 2):
        r = [c for c in r] + [""] * (max(11, len(hdr)) - len(r))
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
        if ctx.SET.get("qmark"): marks = ctx.SET["qmark"]                      # علامة_السؤال بالإعدادات بتغلب عمود العلامات بالملف
        f = autoltr if auto_math else (lambda x: x)
        out.append({"n": len(out) + 1, "level": lv, "page": page, "q": f(with_imgs(ctx, q, errs, i)), "o": [f(with_imgs(ctx, o, errs, i)) for o in opts], "a": a, "sol": sol, "marks": marks, "fixed": fx in YES, "row": i, "cols": {h: str(r[j]).strip() for j, h in enumerate(hdr) if h}})
    if errs: raise DataError("\n".join(errs))
    if not out: raise DataError("ملف الأسئلة فاضي")
    return out
def load_roster(ctx, path=None):
    """path: ملف طلاب بمكان ثاني (فحص ملف مرفوع قبل ما ينحفظ)؛ بدونه بنقرأ students.xlsx من مجلد الامتحان"""
    rows = files.read_table(path or files.find_file(ctx.BASE, "students"), ("الصف", "الاسم", "grade", "name")); ros, seen, errs = {}, set(), []
    for i, r in enumerate(rows[1:], 2):
        r = r + [""] * (4 - len(r))
        if not any(r): continue
        g, s, n = r[0].strip(), r[1].strip(), r[2].strip()
        if r[3].strip(): ctx.XCODES[(g, s, n)] = r[3].strip()
        if not (g and s and n): errs.append(f"students سطر {i}: لازم تعبّي الصف والشعبة والاسم"); continue
        if (g, s, n) in seen: errs.append(f"students سطر {i}: الاسم «{n}» مكرر بنفس الشعبة — غيّر أحدهما (مثلاً أضف حرف)"); continue
        seen.add((g, s, n)); ros.setdefault(g, {}).setdefault(s, []).append(n)
    if errs: raise DataError("\n".join(errs))
    if not ros: raise DataError("ملف الطلاب فاضي")
    return ros
def qhtml(ctx, text):
    """نص سؤال أو خيار زي ما بينعرض بأي صفحة: مهرّب، والكسور مرسومة، والصور"""
    return imgify(ctx, qhtml_text(text))
