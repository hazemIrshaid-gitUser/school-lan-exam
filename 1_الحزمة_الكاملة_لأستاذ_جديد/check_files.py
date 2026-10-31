# فحص ملفات الامتحان بدون تشغيل السيرفر:   python check_files.py     (أو دبل كليك على check_files.bat)
# بيقرأ settings.txt + questions.xlsx + students.xlsx بنفس طريقة السيرفر بالضبط، ويقول لك إذا في مشكلة،
# وبيطبع ملخص (عدد الأسئلة بكل مستوى، توزيع الإجابات الصحيحة، مجموع العلامات، عدد الطلاب بكل شعبة) + تنبيهات.
# ملاحظة: نافذة ويندوز السوداء ما بتعرض العربي (مربعات)، فالتقرير الكامل بيتحفظ بـ check_report.txt وبيفتح بالمفكرة تلقائياً.
import os, sys, collections
sys.dont_write_bytecode = True
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
here = os.path.dirname(os.path.abspath(__file__)); os.chdir(here); sys.path.insert(0, here)
try: os.remove(os.path.join(here, "check_report.txt"))   # تقرير قديم («سليمة ✔») ما لازم يضل لو الفحص هالمرة فشل؛ بيرجع ينكتب لو نجح
except OSError: pass
import server as S          # لو في خطأ بالإعدادات: بيطبعه ويفتح exam_error.txt بالمفكرة ويوقف هون (نفس رسالة السيرفر)
if S.ctx.SETUP:             # السيرفر بيشتغل بوضع التجهيز لو الأسئلة أو الطلاب ناقصين/فيهم خطأ، فالفحص لازم يفشل ويقول ليش
    _msg = "\n\n".join(S.ctx.SETUP.values()); _path = S.report_problem("في مشكلة بالملفات — صلّحها وشغّل من جديد:\n\n" + _msg + "\n")
    print("\n" + "=" * 56 + "\n  PROBLEM WITH THE EXAM FILES  /  في مشكلة بالملفات\n" + "=" * 56)
    if any(S.core_uploads.is_missing(v) for v in S.ctx.SETUP.values()): print("  Missing file: put exam_data.zip (or questions.xlsx + students.xlsx; settings.txt is optional) next to server.py, then run again.")
    print("  Details in Arabic were saved to: " + _path + ("  (opened in Notepad)" if S.REAL_CONSOLE else ""))
    print(_msg); print("=" * 56)
    sys.exit(1)

lines = []
def P(s=""):
    print(s); lines.append(s)

warn = []
P("\n" + "=" * 56)
P("  OK - the exam files are valid  /  الملفات سليمة وقابلة للتشغيل")
P("=" * 56)
if S.SET.get("missing"): P("الإعدادات      : ما في settings.txt — افتراضية (كل أسئلة الملف، 30 دقيقة، خلط، بدون كلمة سر)")
P(f"عنوان الامتحان : {S.SET['title']}" + ("   (تلقائي؛ لعنوان ثاني اكتب عنوان_الامتحان بـ settings.txt)" if S.SET.get("auto_title") else ""))
P(f"المدة          : {S.SET['minutes']} دقيقة")
lv = collections.Counter(q["level"] for q in S.QLIST)
P("بنك الأسئلة    : %d سؤال  (%s)" % (len(S.QLIST), "، ".join(f"{S.LVL[k]} {lv[k]}" for k in ("hard", "medium", "easy") if lv[k])))
P("بالامتحان      : %d سؤال  (%s)" % (sum(S.PICK.values()), "، ".join(f"{S.glabel(k)} {v}" for k, v in S.PICK.items() if v)))
lo, hi = S.total_range(S.PICK)
P("العلامة الكاملة: " + (str(lo) if lo == hi else f"{lo} إلى {hi} (تختلف حسب الأسئلة المسحوبة)"))
P("الطلاب         : %d" % sum(len(n) for g in S.ROSTER.values() for n in g.values()))
if S.IMG_LIST: P("الصور          : %d صورة بالأسئلة (كلها موجودة)" % len(S.IMG_LIST))
for g, secs in S.ROSTER.items():
    P("   " + g + " — " + "، ".join(f"شعبة {s}: {len(n)}" for s, n in secs.items()))

# فحوصات إضافية (تنبيهات فقط، مش أخطاء)
dist = collections.Counter(q["a"] for q in S.QLIST)
P("توزيع الإجابات الصحيحة: " + "  ".join(f"{S.L[i]}={dist[i]}" for i in range(4)))
for i in range(4):
    if len(S.QLIST) >= 10 and dist[i] > 0.4 * len(S.QLIST): warn.append(f"الإجابة ({S.L[i]}) هي الصحيحة بـ {dist[i]} من {len(S.QLIST)} سؤال — وزّع الإجابات الصحيحة أكثر بين الخيارات")
seen = {}
for q in S.QLIST:
    key = " ".join(q["q"].split())
    if key in seen: warn.append(f"سؤال مكرر: سطر {q['row']} مثل سطر {seen[key]}")
    seen.setdefault(key, q["row"])
    if len({" ".join(o.split()) for o in q["o"]}) < len(q["o"]): warn.append(f"سطر {q['row']}: فيه خياران متطابقان")
for g, secs in S.ROSTER.items():              # | بيكسر مفتاح الطالب (العنوان|الصف|الشعبة|الاسم): الطالب ما بيقدر يبدأ الامتحان
    for s, names in secs.items():
        for n in names:
            for what, x in (("الاسم", n), ("الصف", g), ("الشعبة", s)):
                if "|" in x: warn.append(f"{what} «{x}» فيه الرمز | (الصف {g}، شعبة {s}، الاسم {n}) — الطالب ما رح يقدر يبدأ الامتحان. احذف هذا الرمز من ملف الطلاب")
nosol = sum(1 for q in S.QLIST if not q["sol"])
if nosol: warn.append(f"{nosol} سؤال بدون حل مكتوب (عمود الحل اختياري، لكنه بيسهّل مراجعة المفتاح)")
if S.SET["needCode"]: P("رمز الدخول     : مفعّل (اطبع الرموز من /codes)")
if S.zip_leftovers():
    warn.insert(0, "exam_data.zip كان فيه قائمة طلاب أو إعدادات وما استبدلنا تبعك (المستعمل students.xlsx وsettings.txt). النسخ اللي جت معه: " + "، ".join(S.zip_leftovers()))
if S.STATE.get("bank_changed"):
    warn.insert(0, f"ملف الأسئلة تغيّر بعد آخر امتحان، وبالمجلد لسا بيانات الامتحان السابق ({len(S.SUBS)} تسليم و{len(S.PAPERS)} ورقة): "
                   "إذا هذا امتحان جديد، شغّل start.bat واضغط «بداية امتحان جديد» من المراقبة قبل ما يدخل الطلاب")
if S.ctx.UNCONF: warn.insert(0, "إعدادات الامتحان لسا ما انعبّت (" + "، ".join(S.ctx.UNCONF) + "): الطلاب بيشوفوا «الامتحان غير جاهز» لحد ما تعبّيها وتحفظ من صفحة /settings بعد تشغيل السيرفر.")
if warn:
    P("\nتنبيهات (مش أخطاء، بس انتبه):")
    for w in warn[:40]: P(" ⚠ " + w)
    if len(warn) > 40: P(f" ... و{len(warn) - 40} تنبيه آخر")
P("\nالخطوة الجاية: شغّل start.bat، وراجع صفحة المفتاح /key قبل الامتحان.\n")

# تقرير مقروء: نافذة الكونسول ما بتعرض العربي، فنحفظه بملف ونفتحه بالمفكرة
rp = os.path.join(here, "check_report.txt")
try:
    with open(rp, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines) + "\n")
    print("Full report saved to: " + rp + ("  (opened in Notepad)" if S.REAL_CONSOLE else ""))
    if S.REAL_CONSOLE:
        os.startfile(rp)
except Exception:
    pass
