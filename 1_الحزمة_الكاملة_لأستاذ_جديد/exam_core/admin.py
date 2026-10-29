"""خدمة إعدادات الامتحان: حالة الصفحة (الحقول والأعمدة المتاحة)، الحفظ بـ settings.txt مع تجربة كل شي قبل الكتابة وتطبيقه فوراً، وعنوان الامتحان التلقائي الجديد. كل دالة بتاخذ ctx."""
from collections import Counter
import os
import time
from .questions import load_questions
from .settings import COL_SKIP, REVIEW_OUT, SPEC, SPEC_BY_KEY, _clean_setting, _col_value, decode_settings, edit_settings_text, parse_rule
from .storage import init_codes, read_settings, save_state
from .util import DataError, atomic_write, num
from .views import build_page, build_preview

def settings_started(ctx): return bool(ctx.PAPERS or ctx.CLAIMS or ctx.SUBS)
def _eff(ctx, f, kind):
    v, given = ctx.SET.get(f), f in ctx.SET.get("given", set())
    if kind == "bool": return "نعم" if v else "لا"
    if kind == "review": return REVIEW_OUT.get(v, "لا")
    if kind == "count": return str(v) if given else ""
    if kind == "num": return "" if v is None else str(num(v))
    if f == "title": return "" if ctx.SET.get("auto_title") else str(v)
    return str(v)
def settings_columns(ctx):
    """الأعمدة اللي بتنفع للتوزيع (فيها قيم قليلة متكررة) والأعداد المتاحة، مقروءة من ملف الأسئلة نفسه + أعداد كل زوج أعمدة"""
    cnt = {}
    for q in ctx.QLIST:
        for c, v in q.get("cols", {}).items():
            if c in COL_SKIP or not v.strip(): continue
            cnt.setdefault(c, Counter())[_col_value(c, v)] += 1
    first = ("الوحدة", "المستوى")
    names = sorted((c for c in cnt if len(cnt[c]) <= 40), key=lambda c: (first.index(c) if c in first else 2, c))
    lvl_order = ["سهل", "وسط", "صعب"]
    cols = {}
    for c in names:
        items = list(cnt[c].items())
        if c == "المستوى": items.sort(key=lambda x: lvl_order.index(x[0]) if x[0] in lvl_order else 9)
        cols[c] = [[v, n] for v, n in items]
    cross = {}
    for a in names:
        for b in names:
            if a == b: continue
            cc = Counter((_col_value(a, q["cols"].get(a, "")), _col_value(b, q["cols"].get(b, ""))) for q in ctx.QLIST)
            cross[a + "||" + b] = {x + "||" + y: n for (x, y), n in cc.items() if x and y}
    return names, cols, cross
def settings_state(ctx):
    names, cols, cross = settings_columns(ctx)
    fields = [{"key": fk, "field": f, "kind": kind, "label": label, "help": hp, "free": free, "value": _eff(ctx, f, kind), "given": f in ctx.SET.get("given", set()),
               "placeholder": ctx.SET["title"] if f == "title" and ctx.SET.get("auto_title") else ""} for f, fk, kind, label, hp, free in SPEC]
    rules = [{"text": " | ".join(f"{c}{':' if o == ':' else '~'}{'/'.join(vs)}" for c, o, vs in r["conds"]) + f" | العدد:{r['n']}", "conds": [[c, o, vs] for c, o, vs in r["conds"]], "n": r["n"]} for r in ctx.SET.get("rules", [])]
    return {"fields": fields, "rules": rules, "started": settings_started(ctx), "columns": names, "values": cols, "cross": cross, "bank": len(ctx.QLIST),
            "picked": sum(ctx.PICK.values()), "tpass_default": ctx.SET.get("tpass") == "1234"}
def apply_settings(ctx, d):
    """يكتب الإعدادات الجديدة بـ settings.txt (بعد ما يجرّبها كلها: لو في خطأ ما بيتغير شي) ويطبّقها فوراً. بعد ما يبدأ أول طالب بتنقفل الإعدادات اللي بتأثر على الأوراق. لازم تتنادى داخل LOCK"""
    old_txt = decode_settings(open(os.path.join(ctx.BASE, "settings.txt"), "rb").read()) if os.path.exists(os.path.join(ctx.BASE, "settings.txt")) else ""
    if d.get("reset"):                                   # رجوع للافتراضي: بنشيل كل الإعدادات ما عدا كلمة السر (حتى ما تنمسح بالغلط)
        new_txt = edit_settings_text(old_txt, {}, [], {fk for f, fk, *_ in SPEC if f != "tpass"})
    else:
        raw, rules = d.get("values", {}), d.get("rules", [])
        if not isinstance(raw, dict) or not isinstance(rules, list): raise DataError("طلب غير صالح")
        given, vals = ctx.SET.get("given", set()), {}
        for fk, v in raw.items():
            if fk not in SPEC_BY_KEY: raise DataError(f"إعداد غير معروف: {fk}")
            f, kind = SPEC_BY_KEY[fk]; v = _clean_setting(v)
            if f in given or v != _eff(ctx, f, kind): vals[fk] = v
        lines = []
        for r in rules:
            r = _clean_setting(r)
            if r: parse_rule(r, len(lines) + 1); lines.append(r)
        new_txt = edit_settings_text(old_txt, vals, lines)
    newcfg = read_settings(ctx, new_txt)
    if settings_started(ctx):
        bad = []
        for f, fk, kind, label, _, free in SPEC:
            if free: continue
            a, b = ctx.SET.get(f), newcfg.get(f)
            if kind == "count": a = ctx.SET[f] if f in ctx.SET["given"] else None; b = newcfg[f] if f in newcfg["given"] else None
            if a != b: bad.append(label)
        sig = lambda c: [(r["conds"], r["n"]) for r in c.get("rules", [])]
        if sig(ctx.SET) != sig(newcfg): bad.append("قواعد السحب")
        if bad: raise DataError("الامتحان بدأ، فهذه الإعدادات مقفلة: " + "، ".join(bad) + ". ابدأ امتحاناً جديداً من شاشة المراقبة أولاً.")
    snap = (dict(ctx.SET), list(ctx.QLIST), dict(ctx.BANK), ctx.PAGE, dict(ctx.PICK), ctx.PREVIEW)
    try:                                                 # نجرّب كل شي قبل ما نكتب الملف: الأسئلة والصفحة والمعاينة
        ctx.SET.clear(); ctx.SET.update(newcfg); ctx.QLIST[:] = load_questions(ctx); ctx.BANK.clear(); ctx.BANK.update({q["n"]: q for q in ctx.QLIST})
        _page, _pick = build_page(ctx); ctx.PAGE = _page; ctx.PICK.clear(); ctx.PICK.update(_pick); ctx.PREVIEW = build_preview(ctx)
    except BaseException:
        ctx.SET.clear(); ctx.SET.update(snap[0]); ctx.QLIST[:] = snap[1]; ctx.BANK.clear(); ctx.BANK.update(snap[2]); ctx.PAGE = snap[3]; ctx.PICK.clear(); ctx.PICK.update(snap[4]); ctx.PREVIEW = snap[5]; raise
    path = os.path.join(ctx.BASE, "settings.txt")
    if old_txt:                                          # نسخة احتياطية قبل كل حفظ (آخر 50)
        bdir = os.path.join(ctx.BASE, "نسخ_الإعدادات"); os.makedirs(bdir, exist_ok=True)
        nm = "settings_" + time.strftime("%Y%m%d_%H%M%S"); i = 0
        while os.path.exists(os.path.join(bdir, nm + (f"_{i}" if i else "") + ".txt")): i += 1          # حفظين بنفس الثانية: ما نكتب فوق النسخة الأولى
        atomic_write(os.path.join(bdir, nm + (f"_{i}" if i else "") + ".txt"), old_txt)
        olds = sorted(f for f in os.listdir(bdir) if f.startswith("settings_") and f.endswith(".txt"))
        for f in olds[:-50]:
            try: os.remove(os.path.join(bdir, f))
            except OSError: pass
    atomic_write(path, new_txt)
    try: ctx.SET_MTIME[0] = os.path.getmtime(path)
    except OSError: pass
    if ctx.STATE.get("auto_title") != (ctx.SET["title"] if ctx.SET.get("auto_title") else None):
        if ctx.SET.get("auto_title"): ctx.STATE["auto_title"] = ctx.SET["title"]
        else: ctx.STATE.pop("auto_title", None)
        save_state(ctx)
    if ctx.SET["needCode"]: init_codes(ctx)
    return {"ok": True, "picked": sum(ctx.PICK.values())}
def new_auto_title(ctx):
    """امتحان جديد والعنوان تلقائي: عنوان جديد (حتى ما يتعارض مع الامتحان اللي خلص على نفس الأجهزة)، ونعيد بناء صفحة الطالب والمعاينة فيه"""
    old = ctx.SET["title"]
    t = "امتحان " + time.strftime("%d-%m-%Y %H:%M")
    if t == old: t = "امتحان " + time.strftime("%d-%m-%Y %H:%M:%S")
    ctx.SET["title"] = t
    try: page, pick = build_page(ctx); prev = build_preview(ctx)
    except Exception as e:                               # ما زبط نبني الصفحة: بنضل على العنوان القديم (أحسن من صفحة وعنوان مش متطابقين)
        ctx.SET["title"] = old; ctx.STATE["auto_title"] = old; save_state(ctx); ctx.print("تنبيه: تعذّر تجهيز عنوان جديد للامتحان:", repr(e)); return
    ctx.PAGE = page; ctx.PICK.clear(); ctx.PICK.update(pick); ctx.PREVIEW = prev; ctx.STATE["auto_title"] = t; save_state(ctx)
    ctx.print("عنوان الامتحان الجديد:", t)
