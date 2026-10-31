"""طبقة التخزين: الحفظ بملفات الامتحان (claims/papers/state/answers/submissions/results.csv)، التسليم، إعادة الفتح، التمديد والتعويض، ورموز الدخول. كل دالة بتاخذ ctx."""
import csv, io, json, os, random, time, hmac
from .constants import HEAD
from .domain import build_record, deadline, fmt_dur, parse_key, settle_pause, wrong_items, wrong_text
from .util import atomic_write, load_json, norm_code, num
from collections import Counter
from .settings import decode_settings, default_cfg, parse_settings

def save_claims(ctx): atomic_write(ctx.CLAIMS_FILE, json.dumps(ctx.CLAIMS, ensure_ascii=False, indent=1))
def save_papers(ctx): atomic_write(ctx.PAPERS_FILE, json.dumps(ctx.PAPERS, ensure_ascii=False))
def save_state(ctx): atomic_write(ctx.STATE_FILE, json.dumps(ctx.STATE, ensure_ascii=False))
def beat(ctx):
    try: atomic_write(ctx.ALIVE_FILE, repr(time.time()))
    except OSError: pass
def flush_answers(ctx):
    with ctx.LOCK:
        if not ctx.ANS_DIRTY[0]: return
        try: atomic_write(ctx.ANS_FILE, json.dumps(ctx.ANS, ensure_ascii=False)); ctx.ANS_DIRTY[0] = False
        except OSError as e: ctx.print("تنبيه: تعذّر حفظ answers.json:", e)
def gap_check(ctx, tick=False):
    """الجهاز نام أو تجمّد وسط الامتحان ورجع: السيرفر ما انطفى فما في تعويض «بعد التشغيل»، فبنعوّض هون بنفس القواعد.
    بتتنادى من دورة الحفظ ومن أول كل طلب POST: طالب خلص وقته وقت النوم بيرجع لامتحانه بالوقت المعوّض بدل ما ينحسب عليه"""
    now = time.time(); last = ctx.LAST_TICK[0]
    if last is None or (not tick and now - last <= ctx.GAP_S): return None
    with ctx.LOCK:
        last = ctx.LAST_TICK[0]
        if last is None: return None
        rec = compensate_downtime(ctx, last, "sleep") if now - last > ctx.GAP_S else None
        ctx.LAST_TICK[0] = max(now, ctx.LAST_TICK[0])
        return rec
def extend_time(ctx, minutes, scope, d):
    """تمديد وقت الطلاب اللي بدأوا ولم يسلّموا: طالب واحد، شعبة، أو الكل"""
    n = 0
    for k, p in ctx.PAPERS.items():
        if k in ctx.SUBS: continue
        w = parse_key(ctx, k)
        if w is None: continue
        if scope == "student" and k != d.get("key"): continue
        if scope == "section" and (w[0], w[1]) != (d.get("grade"), d.get("section")): continue
        p["extra"] = p.get("extra", 0) + minutes * 60; n += 1
    if n: save_papers(ctx)
    return n
def compensate_downtime(ctx, last=None, why="restart"):
    """السيرفر وقف وانشغّل من جديد وسط الامتحان: الوقت كان يمشي أثناء التوقف. بنزيد وقت كل طالب بدأ ولم يسلّم وكان عنده وقت لحظة التوقف بنفس مدة التوقف
    (لحد 30 دقيقة؛ أكثر من هيك المعلم بيمدّد يدوياً). ما بنعوّض: المسلّمين، والمنقولين (وقتهم متجمّد)، ومن انتهى وقته قبل التوقف، ولا بعد إنهاء الامتحان"""
    if last is None:                                 # بعد إعادة التشغيل: آخر نبضة سجّلها التشغيل السابق. (gap_check بتبعث last بنفسها لما الجهاز ينام ويصحى)
        ctx.STATE.pop("comp", None)
        try: last = float(open(ctx.ALIVE_FILE, encoding="utf-8").read().strip())
        except (OSError, ValueError): return None
    now = time.time(); down = now - last
    if down < 3 or not ctx.PAPERS: return None
    rec = {"at": now, "downtime_s": int(down), "students": 0}
    if why == "sleep": rec["sleep"] = True
    if not ctx.SET.get("comp", True): rec["off"] = True
    elif down > ctx.MAX_COMP: rec["skipped"] = True
    else:
        for k, p in ctx.PAPERS.items():
            if k in ctx.SUBS or "frozen" in p or "paused" in p or deadline(ctx, k) <= last: continue
            p["extra"] = p.get("extra", 0) + int(down); p["down"] = p.get("down", 0) + int(down); rec["students"] += 1       # down: وقت التوقف بنطرحه من مدة الحل
        if rec["students"]: save_papers(ctx)
    ctx.STATE["comp"] = rec; save_state(ctx)
    ctx.print(f"تعويض التوقف: {'جهاز السيرفر نام أو تجمّد' if why == 'sleep' else 'السيرفر كان متوقفاً'} {int(down)} ثانية — " + ("التعويض مطفّأ بالإعدادات" if rec.get("off") else "أطول من 30 دقيقة: ما عوّضنا تلقائياً" if rec.get("skipped") else f"مدّدنا وقت {rec['students']} طالب"))
    return rec
def record_submission(ctx, rec):
    """تسجيل تسليم: السطر بيتكتب بـ submissions.jsonl ويتأكد إنه وصل للقرص (fsync) قبل ما نغيّر الذاكرة؛ فلو فشلت الكتابة بيرمي OSError وما بيتغير شي"""
    k = rec["key"]
    with open(ctx.SUBS_FILE, "a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
    ctx.SUBS[k] = rec; ctx.LIVE.pop(k, None)
    if ctx.ANS.pop(k, None) is not None: ctx.ANS_DIRTY[0] = True
def submit_for(ctx, k):
    """تسليم عن الطالب (من المعلم): بنصحّح إجاباته المحفوظة على السيرفر (الأسئلة اللي ما أجاب عنها = خاطئة) وبنسجّلها كتسليم. بتتنادى داخل LOCK"""
    if k in ctx.SUBS or k not in ctx.PAPERS or k not in ctx.CLAIMS: return False
    w = parse_key(ctx, k)
    if w is None: return False
    settle_pause(ctx, ctx.PAPERS[k]); ids = ctx.PAPERS[k]["ids"]; saved = ctx.ANS.get(k, {})
    answers = []
    for n in ids:
        try: answers.append(int(saved.get(str(n), -1)))
        except (TypeError, ValueError): answers.append(-1)
    lv = ctx.LIVE.get(k) or {}
    rec = build_record(ctx, k, w, ids, answers, "تسليم من المعلم", f"{lv['leaveN']} مرة ({lv.get('leaveSec', 0)} ث)" if lv.get("leaveN") else "لم يخرج", 0, time.time())
    record_submission(ctx, rec)
    ctx.print("تسليم من المعلم:", w[1], w[2], rec["score"], "/", rec["total"], f"({sum(1 for a in answers if a >= 0)} إجابة محفوظة)")
    return True
def reopen_student(ctx, k):
    """إعادة فتح طالب سلّم بالغلط: تسليمه بينلغى (بيضل بـ submissions.jsonl كأرشيف وبعده سطر «reopen»)، وبيرجع لأسئلته بإجاباته المحفوظة ووقته اللي كان باقيله لحظة
    التسليم (التمديدات محسوبة، وعلى الأقل ctx.REOPEN_MIN). الاسم والجهاز بيضلوا محجوزين، وصفحته (لو لسا مفتوحة) بترجع للأسئلة خلال ثواني. بترجّع نص الخطأ أو None"""
    if k not in ctx.SUBS: return "الطالب ما سلّم (أو ما بدأ)"
    if ctx.STATE["closed_at"]: return "الامتحان منتهٍ: أعد فتحه أولاً ثم أعد فتح الطالب"
    p = ctx.PAPERS.get(k)
    if p is None or k not in ctx.CLAIMS: return "ما في ورقة محفوظة لهالطالب (انفكّ حجزه)"
    rec = ctx.SUBS[k]; now = time.time(); ts = rec.get("ts")
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):                 # تسليم من نسخة أقدم: نقرأ الوقت من النص
        try: ts = time.mktime(time.strptime(rec["time"], "%Y-%m-%d %H:%M:%S"))
        except (KeyError, TypeError, ValueError, OverflowError): ts = now
    ts = min(ts, now)
    target = max(int(p["start"] + ctx.SET["minutes"] * 60 + p.get("extra", 0) - ts), ctx.REOPEN_MIN)
    saved = {str(n): a for n, a in zip(rec["ids"], rec["answers"]) if isinstance(a, int) and not isinstance(a, bool) and a >= 0}
    with open(ctx.SUBS_FILE, "a", encoding="utf-8") as f:                              # أول شي بنكتب السطر؛ لو فشلت الكتابة ما بيتغيّر شي
        f.write(json.dumps({"key": k, "reopen": round(now, 2), "exam": ctx.SET["title"], "time": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False) + "\n"); f.flush(); os.fsync(f.fileno())
    p.pop("paused", None); p["extra"] = now + target - p["start"] - ctx.SET["minutes"] * 60; p["pz"] = p.get("pz", 0) + (now - ts)      # مدة «سلّم» ما بتنحسب من مدة حله
    ctx.SUBS.pop(k); ctx.ANS[k] = saved; ctx.ANS_DIRTY[0] = True
    try: atomic_write(ctx.ANS_FILE, json.dumps(ctx.ANS, ensure_ascii=False)); ctx.ANS_DIRTY[0] = False             # الإجابات المستعادة بتنكتب فوراً (لو وقف السيرفر الآن ما بتضيع)
    except OSError: pass
    ctx.LIVE[k] = {"t": now, "answered": len(saved), "total": len(rec["ids"]), "remain": target, "leaveN": 0, "leaveSec": 0}
    save_papers(ctx); write_results_csv(ctx)
    return None
def write_results_csv(ctx):
    """results.csv يتولّد من التسليمات. لو كان مفتوح بـ Excel نتجاوز (التسليم محفوظ بـ jsonl أصلاً)"""
    if ctx.SETUP or ctx.STATE.get("bank_changed"): return          # وضع التجهيز أو بنك مختلف عن بنك التسليمات: البنك الحالي ما بيفسّر أخطاء الامتحان السابق، فنترك results.csv القديم زي ما هو
    buf = io.StringIO(); w = csv.writer(buf); w.writerow(HEAD)
    for rec in ctx.SUBS.values():
        try: wrong = wrong_text(ctx, wrong_items(ctx, rec["ids"], rec["answers"]))
        except (KeyError, IndexError): wrong = "— تعذّر عرض الأخطاء: بنك الأسئلة تغيّر —"
        w.writerow([rec["exam"], rec["grade"], rec["section"], rec["name"], rec["score"], rec["total"],
                    wrong, rec.get("auto", ""), rec.get("time", ""), rec.get("leave", ""), rec.get("late", 0), fmt_dur(ctx, rec.get("dur"))])
    try: atomic_write(ctx.OUT, "﻿" + buf.getvalue(), tries=2)          # مفتوح بـ Excel = ممسوك طول الوقت: ما نستنّى عليه مع كل تسليم
    except OSError as e: ctx.print("تنبيه: تعذّر تحديث results.csv (مفتوح بـ Excel؟) — التسليمات محفوظة بـ submissions.jsonl:", e)
def init_codes(ctx):
    """رمز لكل طالب: من عمود «الرمز» بملف الطلاب إن وُجد، وإلا مولَّد عشوائياً ومحفوظ بـ codes.json"""
    saved, gen, rng = load_json(ctx.CODES_FILE, {}), {}, random.SystemRandom()
    for g, secs in ctx.ROSTER.items():
        for s, names in secs.items():
            for n in names:
                ck = f"{g}|{s}|{n}"
                if (g, s, n) in ctx.XCODES: ctx.CODES[ck] = norm_code(ctx.XCODES[(g, s, n)])
                else: ctx.CODES[ck] = gen[ck] = saved.get(ck) or "%06d" % rng.randrange(10 ** 6)
    if gen != saved: atomic_write(ctx.CODES_FILE, json.dumps(gen, ensure_ascii=False, indent=1))
def check_code(ctx, k, given):
    """None = صحيح، وإلا "badcode" أو "locked" (5 محاولات خاطئة = قفل دقيقة لهذا الاسم)"""
    now, f = time.time(), ctx.FAILS.get(k)
    if f and f[1] > now: return "locked"
    if hmac.compare_digest(norm_code(given or "").encode(), ctx.CODES["|".join(parse_key(ctx, k))].encode()):
        ctx.FAILS.pop(k, None); return None
    f = ctx.FAILS.setdefault(k, [0, 0]); f[0] += 1
    if f[0] >= 5: f[0] = 0; f[1] = now + 60
    return "badcode"
def read_settings(ctx, txt=None):
    """txt: نص جاهز (صفحة الإعدادات بتجرّب النص الجديد قبل ما تكتبه بالملف). بدونه: settings.txt من مجلد الامتحان (الملف اختياري)"""
    if txt is None:
        p = os.path.join(ctx.BASE, "settings.txt")
        if not os.path.exists(p):                        # الملف اختياري: مشرف المختبر بيعمله لما الأستاذ يطلب إعدادات خاصة
            cfg = default_cfg(); cfg["given"] = set(); cfg["missing"] = True; cfg["title"] = auto_title(ctx); cfg["auto_title"] = True
            return cfg
        txt = decode_settings(open(p, "rb").read())
    return parse_settings(txt, lambda: auto_title(ctx))
def auto_title(ctx):
    """ما في عنوان بـ settings.txt: عنوان تلقائي فريد لكل امتحان (عنوان ثابت لكل الامتحانات كان رح يخلّي جهاز امتحن عليه طالب
    يقول «تم التسليم مسبقاً» بالامتحان الجاي). ثابت لما ينعاد تشغيل السيرفر بنفس الامتحان: محفوظ بـ state.json، أو من مفاتيح الأوراق الموجودة"""
    t = load_json(ctx.STATE_FILE, {}).get("auto_title")
    if isinstance(t, str) and t.strip(): return t
    for f in (ctx.PAPERS_FILE, ctx.CLAIMS_FILE):
        ks = [k for k in load_json(f, {}) if isinstance(k, str) and k.count("|") >= 3]
        if ks: return Counter(k.rsplit("|", 3)[0] for k in ks).most_common(1)[0][0]
    return "امتحان " + time.strftime("%d-%m-%Y %H:%M")
