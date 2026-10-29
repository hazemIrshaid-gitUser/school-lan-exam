"""منطق الامتحان (بدون كتابة ملفات): سحب الورقة، الوقت والتوقف المؤقت، رد الورقة للطالب، العلامات، التحقق من تغيّر البنك. كل دالة بتاخذ ctx (حالة النسخة) كأول وسيط."""
import hashlib, json, random, time
from .constants import L, LVL
from .questions import qhtml
from .text import noimg
from .util import grp, num

def make_paper(ctx):
    """السيرفر هو اللي يسحب الأسئلة ويخلطها (مش جهاز الطالب).
    السحب موزّن بعدّاد: كل سؤال بنعدّ كم ورقة طلع فيها، وبنسحب الأقل ظهوراً أول (والتعادل عشوائي)، فتتوزع الأسئلة على كل البنك
    وما بيتكرر سؤال وفي أسئلة ما طلعت لحدا. العدّاد بيتحسب من ctx.PAPERS نفسها (بتتحفظ بالملف) فبيضل صح بعد إعادة تشغيل السيرفر. بتتنادى داخل LOCK"""
    used = {}
    for p in ctx.PAPERS.values():
        for n in p.get("ids", ()): used[n] = used.get(n, 0) + 1
    ids = []
    for lv in [k for k in ("hard", "medium", "easy") if k in ctx.PICK] + [k for k in ctx.PICK if k not in ("hard", "medium", "easy")]:
        fixed = [q["n"] for q in ctx.QLIST if grp(q) == lv and q.get("fixed")]          # الأسئلة الثابتة تدخل كل ورقة
        rest = [q["n"] for q in ctx.QLIST if grp(q) == lv and not q.get("fixed")]
        random.shuffle(rest)                                                            # التعادل بالعدّاد يتحسم عشوائياً
        rest.sort(key=lambda n: used.get(n, 0))                                         # sort ثابت: الأقل ظهوراً أول
        ids += fixed + rest[:ctx.PICK[lv] - len(fixed)]
    ids.sort()
    if ctx.SET["shuffleQ"]: random.shuffle(ids)
    orders = []
    for n in ids:
        o = list(range(len(ctx.BANK[n]["o"])))
        if ctx.SET["shuffleO"]: random.shuffle(o)
        orders.append(o)
    return {"start": time.time(), "ids": ids, "orders": orders}
def paused_for(ctx, p):
    """كم ثانية صار الطالب موقوفاً (إيقاف مؤقت من المعلم، مثلاً للحمّام)؛ 0 لو مش موقوف. وقته متجمّد: هالمدة بتنضاف لنهاية وقته أول بأول"""
    return time.time() - p["paused"] if "paused" in p else 0
def settle_pause(ctx, p):
    """إنهاء الإيقاف: المدة بتثبت بنهاية وقت الطالب (extra) وبمجموع الإيقاف (pz) اللي بنطرحه من مدة الحل. بترجّع المدة بالثواني"""
    if "paused" not in p: return 0
    gap = max(0.0, time.time() - p.pop("paused")); p["extra"] = p.get("extra", 0) + gap; p["pz"] = p.get("pz", 0) + gap
    return gap
def deadline(ctx, k):
    """نهاية وقت الطالب: البدء + المدة + التمديد (+ الإيقاف الجاري)، أو لحظة إنهاء المعلم للامتحان (الأبكر)"""
    p = ctx.PAPERS[k]; d = p["start"] + ctx.SET["minutes"] * 60 + p.get("extra", 0) + paused_for(ctx, p)
    return min(d, ctx.STATE["closed_at"]) if ctx.STATE["closed_at"] else d
def remain_of(ctx, k): return max(0, int(deadline(ctx, k) - time.time()))
def fmt_dur(ctx, s):
    """مدة الحل للعرض: 45 ث، 23 د 41 ث، 1 س 05 د 10 ث. فاضية لو ما انسجّلت (تسليم قبل الميزة، أو تسليم من المعلم).
    نص عربي وليس 23:41 لأن Excel بيقرأ هاي الصيغة كساعة من اليوم"""
    if not isinstance(s, (int, float)) or isinstance(s, bool) or s < 0: return ""
    s = int(s); h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h} س {m:02d} د {sec:02d} ث" if h else (f"{m} د {sec:02d} ث" if m else f"{sec} ث")
def pub_q(ctx, n):
    """السؤال زي ما بينعرض للطالب: النص والخيارات والعلامة بس (بدون الإجابة الصحيحة والحل والمستوى والمرجع)"""
    q = ctx.BANK[n]
    return {"n": n, "marks": q["marks"], "q": qhtml(ctx, q["q"]), "o": [qhtml(ctx, o) for o in q["o"]]}
def paper_reply(ctx, k):
    p = ctx.PAPERS[k]
    return {"status": "ok", "ids": p["ids"], "orders": p["orders"], "qs": [pub_q(ctx, n) for n in p["ids"]], "remain": remain_of(ctx, k), "msg": ctx.STATE["msg"], "ans": ctx.ANS.get(k, {}), "paused": "paused" in p}
def clean_ans(ctx, k, a):
    """إجابات الطالب المحفوظة: {رقم السؤال: رقم الخيار الأصلي} — نتأكد إنها ضمن ورقته فقط"""
    if not isinstance(a, dict): return None
    ids, out = set(ctx.PAPERS[k]["ids"]), {}
    for n, j in a.items():
        try: n, j = int(n), int(j)
        except (TypeError, ValueError): continue
        if n in ids and 0 <= j < len(ctx.BANK[n]["o"]): out[str(n)] = j
    return out
def wrong_items(ctx, ids, answers):
    """الأسئلة الخاطئة فقط (حسب البنك الأصلي)"""
    out = []
    for n, v in zip(ids, answers):
        q = ctx.BANK[n]
        if v != q["a"]: out.append({"n": n, "level": q["level"], "q": q["q"], "o": q["o"], "given": v, "correct": q["a"]})
    return out
def wrong_text(ctx, items):
    lines = []
    for w in items:
        given = "لم يجب" if w["given"] < 0 else f"{L[w['given']]}) {w['o'][w['given']]}"
        lines.append(f"س{w['n']} ({LVL.get(w['level'], '')}): {w['q']}  ← أجاب: {given}  |  الصحيح: {L[w['correct']]}) {w['o'][w['correct']]}")
    return noimg("\n".join(lines)) if lines else "— لا أخطاء —"
def parse_key(ctx, k):
    """مفتاح الطالب: العنوان|الصف|الشعبة|الاسم — يرجّع (صف، شعبة، اسم) لو الطالب موجود بالقائمة وإلا None"""
    p = k.rsplit("|", 3) if isinstance(k, str) else []
    if len(p) != 4 or p[0] != ctx.SET["title"]: return None
    g, s, n = p[1:]
    return (g, s, n) if n in ctx.ROSTER.get(g, {}).get(s, []) else None
def raw_range(ctx, pick):
    """أقل وأعلى مجموع علامات ممكن لورقة طالب"""
    lo = hi = 0
    for k, n in pick.items():
        ms = sorted(q["marks"] for q in ctx.QLIST if grp(q) == k)
        lo += sum(ms[:n]); hi += sum(ms[len(ms) - n:]) if n else 0
    return num(lo), num(hi)
def total_range(ctx, pick):
    """العلامة الكاملة: العلامة_النهائية إن انكتبت، وإلا مجموع علامات الأسئلة"""
    return (ctx.SET["final"], ctx.SET["final"]) if ctx.SET["final"] else raw_range(ctx, pick)
def eff_mark(ctx, m, ids):
    """علامة السؤال الفعلية على ورقة طالب: لو في علامة نهائية بتتناسب مع مجموع علامات ورقته"""
    if not ctx.SET["final"]: return m
    return num(m * ctx.SET["final"] / sum(ctx.BANK[i]["marks"] for i in ids))
def key_mark(ctx, m):
    """علامة السؤال بصفحة المفتاح (لو العلامة الكاملة ثابتة لكل الأوراق)"""
    lo, hi = raw_range(ctx, ctx.PICK)
    return num(m * ctx.SET["final"] / lo) if ctx.SET["final"] and lo == hi else m
def bank_fp(ctx):
    """بصمة محتوى بنك الأسئلة (النصوص والخيارات والإجابات والمستويات): بتتغير بس لما يتغير محتوى ملف الأسئلة فعلاً، مش لما ينحفظ من جديد"""
    return hashlib.sha256(json.dumps([[q["q"], q["o"], q["a"], q["level"]] for q in ctx.QLIST], ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
def check_bank_change(ctx):
    """ملف أسئلة جديد والسيرفر لسا فيه أوراق/تسليمات امتحان سابق: لازم «بداية امتحان جديد» قبل ما يدخل الطلاب. بترجّع True لو ctx.STATE تغيّرت"""
    old, had = ctx.STATE.get("bank_fp"), "bank_changed" in ctx.STATE
    if not (ctx.PAPERS or ctx.SUBS):                       # ما في بيانات امتحان سابق: هذا البنك هو بنك الامتحان الحالي
        ctx.STATE.pop("bank_changed", None); ctx.STATE["bank_fp"] = ctx.BANK_FP
        return old != ctx.BANK_FP or had
    if old is None: ctx.STATE["bank_fp"] = ctx.BANK_FP; return True       # بيانات من نسخة أقدم ما فيها بصمة: البنك الحالي هو الأساس
    if old != ctx.BANK_FP and not had: ctx.STATE["bank_changed"] = {"at": time.time()}; return True
    if old == ctx.BANK_FP and had: ctx.STATE.pop("bank_changed"); return True
    return False
def bank_changed(ctx):
    return {"subs": len(ctx.SUBS), "papers": len(ctx.PAPERS)} if ctx.STATE.get("bank_changed") else None
def glabel(ctx, k): return ctx.GLBL.get(k) or LVL.get(k, str(k))        # اسم مجموعة السحب: المستوى أو قاعدة «سحب» (من ctx.GLBL)
def score_paper(ctx, ids, answers):
    """علامة الورقة: مجموع أوزان الأسئلة الصحيحة. مع العلامة_النهائية بتتحوّل لتصير من الرقم نفسه لكل الأوراق. بترجّع (العلامة، المجموع)"""
    got = sum(ctx.BANK[n]["marks"] for n, a in zip(ids, answers) if a == ctx.BANK[n]["a"])        # مجموع علامات (أوزان) الأسئلة الصحيحة
    W = sum(ctx.BANK[n]["marks"] for n in ids)
    if ctx.SET["final"]: return num(got / W * ctx.SET["final"]), num(ctx.SET["final"])
    return num(got), num(W)
def build_record(ctx, k, who, ids, answers, auto, leave, late, now, **extra):
    """سجل التسليم (سطر submissions.jsonl) لتسليم الطالب ولتسليم المعلم عنه: نفس الحقول بنفس الترتيب، و extra للحقول الزيادة (dur، pause)"""
    score, total = score_paper(ctx, ids, answers)
    rec = {"key": k, "exam": ctx.SET["title"], "grade": who[0], "section": who[1], "name": who[2], "ids": ids, "answers": answers,
           "score": score, "total": total, "auto": auto, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
           "leave": leave, "late": late, "ts": round(now, 2)}
    rec.update(extra)
    return rec
