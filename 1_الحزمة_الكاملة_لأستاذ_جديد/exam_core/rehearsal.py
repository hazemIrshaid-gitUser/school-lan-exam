"""بروفة الضغط: أجهزة المختبر كلها بتطلب «ابدأ» بنفس اللحظة (حسب ساعة السيرفر). حالتها بـ ctx.REH، وكل الدوال بتتنادى داخل LOCK."""
import time
from .storage import save_claims, save_papers

REH_MAX_MIN = 60                              # أطول مدة بتضل فيها البروفة شغّالة (وبتنطفي لحالها)
REH_MAX_DEVS = 300
def reh_release(ctx):
    """بنفك حجز أسماء البروفة اللي ما سلّمت (ما فيها شغل حقيقي): عشان كل جولة تطلب ورقة جديدة، وعشان ما تضل أسماء محجوزة للامتحان الحقيقي"""
    n = 0
    for k in list(ctx.REH["keys"]):
        if k in ctx.SUBS: continue
        c = ctx.CLAIMS.pop(k, None) is not None; p = ctx.PAPERS.pop(k, None) is not None
        n += 1 if (c or p) else 0
        ctx.LIVE.pop(k, None)
        if ctx.ANS.pop(k, None) is not None: ctx.ANS_DIRTY[0] = True
    if n: save_claims(ctx); save_papers(ctx)
    return n
def reh_stop(ctx, why="أوقفها المشرف"):
    if ctx.REH["on"]: ctx.print("بروفة الضغط: انطفت (" + why + ")")
    reh_release(ctx)
    ctx.REH["on"] = False; ctx.REH["at"] = 0.0; ctx.REH["keys"] = set()
def reh_reset(ctx):
    ctx.REH.update(on=False, until=0.0, at=0.0, full=False, devs={}, arr={}); ctx.REH["keys"] = set()
def reh_tick(ctx):
    if ctx.REH["on"] and time.time() > ctx.REH["until"]: reh_stop(ctx, "انتهت مدتها")
def reh_assign(ctx, dev):
    r = ctx.REH["devs"].get(dev)
    if r or len(ctx.REH["devs"]) >= REH_MAX_DEVS: return r
    used = set(ctx.CLAIMS) | set(ctx.PAPERS) | set(ctx.SUBS) | {v["key"] for v in ctx.REH["devs"].values()}
    for g, secs in ctx.ROSTER.items():
        for s, names in secs.items():
            for nm in names:
                k = f'{ctx.SET["title"]}|{g}|{s}|{nm}'
                if k not in used:
                    r = {"n": len(ctx.REH["devs"]) + 1, "key": k, "grade": g, "section": s, "name": nm, "res": {}}
                    ctx.REH["devs"][dev] = r; ctx.REH["keys"].add(k)
                    return r
    return None
def reh_command(ctx, cmd, d):
    """أمر المشرف من صفحة المراقبة. بيرجّع نص الخطأ أو None"""
    reh_tick(ctx)
    try: secs = float(d.get("secs", 60)); mins = float(d.get("mins", 30))
    except (TypeError, ValueError): return "رقم غلط"
    if cmd == "on":
        if not 0.05 <= mins <= REH_MAX_MIN: return "المدة لازم تكون بين 1 و60 دقيقة"
        if ctx.SET["needCode"]: return "رمز الدخول مفعّل بـ settings.txt: البروفة بتجرّب الدخول بدون رمز، فعطّله مؤقتاً"
        if ctx.STATE["closed_at"]: return "الامتحان مُنهى: اضغط «إعادة فتح الامتحان» أول"
        dirty = len((set(ctx.CLAIMS) | set(ctx.PAPERS) | set(ctx.SUBS)) - ctx.REH["keys"])
        if dirty: return f"في {dirty} طالب بدأوا أو سلّموا امتحاناً (أو بيانات قديمة): اضغط «بداية امتحان جديد» أول، والبروفة بتنعمل قبل الامتحان الحقيقي"
        if not ctx.REH["on"]: ctx.REH["devs"] = {}; ctx.REH["arr"] = {}
        ctx.REH.update(on=True, until=time.time() + mins * 60, at=0.0, full=False)
        ctx.print(f"بروفة الضغط: شغّالة {mins:g} دقيقة — افتحوا على الأجهزة /rehearsal")
    elif cmd == "go":
        if not ctx.REH["on"]: return "البروفة مش شغّالة: اضغط «تفعيل البروفة» أول"
        if not ctx.REH["devs"]: return "ما في أجهزة جاهزة: افتحوا صفحة البروفة على الأجهزة أول"
        if not 1 <= secs <= 600: return "الموعد لازم يكون بين 1 و600 ثانية"
        if any(v["key"] in ctx.SUBS for v in ctx.REH["devs"].values()): return "في أجهزة سلّمت بالجولة السابقة: اضغط «بداية امتحان جديد» عشان تعيد البروفة"
        reh_release(ctx)
        ctx.REH.update(at=time.time() + secs, full=bool(d.get("full")), gen=ctx.REH["gen"] + 1, arr={})
        ctx.REH["until"] = max(ctx.REH["until"], ctx.REH["at"] + 300)
        for v in ctx.REH["devs"].values(): v["res"] = {}
        ctx.print(f"بروفة الضغط: الجولة بعد {secs:g} ث على {len(ctx.REH['devs'])} جهاز" + (" (مع حل وتسليم)" if ctx.REH["full"] else ""))
    elif cmd == "off": reh_stop(ctx)
    else: return "أمر غلط"
    return None
def reh_summary(ctx):
    if not ctx.REH["devs"] and not ctx.REH["on"]: return None
    devs = list(ctx.REH["devs"].values()); now = time.time()
    st = [v["res"]["start"] for v in devs if "start" in v["res"]]; sb = [v["res"]["submit"] for v in devs if "submit" in v["res"]]
    ok = [x for x in st if x["ok"]]; ms = sorted(x["ms"] for x in ok); sms = sorted(x["ms"] for x in sb if x["ok"])
    arr = list(ctx.REH["arr"].values())
    return {"on": ctx.REH["on"], "left": max(0, int(ctx.REH["until"] - now)) if ctx.REH["on"] else 0, "at_in": round(ctx.REH["at"] - now, 1) if ctx.REH["at"] > now else None,
            "full": ctx.REH["full"], "joined": len(devs), "reported": len(st), "ok": len(ok), "fail": len(st) - len(ok), "papers": sum(1 for v in devs if v["key"] in ctx.PAPERS),
            "ms_avg": int(sum(ms) / len(ms)) if ms else None, "ms_p95": ms[min(len(ms) - 1, int(0.95 * len(ms)))] if ms else None, "ms_max": ms[-1] if ms else None,
            "skew_max": max((abs(x["skew"]) for x in st), default=None), "spread_ms": int((max(arr) - min(arr)) * 1000) if len(arr) > 1 else 0,
            "submit_ok": sum(1 for x in sb if x["ok"]), "submit_fail": sum(1 for x in sb if not x["ok"]), "submit_ms_max": sms[-1] if sms else None,
            "fails": [{"n": v["n"], "name": v["name"], "status": v["res"]["start"]["status"]} for v in devs if "start" in v["res"] and not v["res"]["start"]["ok"]][:10]}
