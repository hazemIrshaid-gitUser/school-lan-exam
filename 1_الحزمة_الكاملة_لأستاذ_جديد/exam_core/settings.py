"""قراءة وتحليل settings.txt (بدون حالة): تحليل النص، قواعد السحب، مواصفات الإعدادات لصفحة الإعدادات، وتعديل نص الملف بمكانه."""
import re
from .constants import LVL, LVL_IN, YES, NO
from .util import DataError, num

def decode_settings(raw):
    if raw[:2] in (bytes([255, 254]), bytes([254, 255])): return raw.decode("utf-16")      # المفكرة بخيار «Unicode» بتحفظ UTF-16 (مع BOM)
    try: return raw.decode("utf-8-sig")
    except UnicodeDecodeError: return raw.decode("cp1256")
def norm_hdr(h):
    """اسم العمود بدون الأقواس: «المرجع (اختياري)» = «المرجع»"""
    return re.sub(r"\s*[\(（].*?[\)）]", "", str(h)).strip()
def parse_rule(v, ln):
    """سطر «سحب»: شروط مفصولة بـ | كل شرط «العمود:القيمة» (أو «العمود~جزء من القيمة»)، والقيمة تقبل بدائل بـ /، و«العدد:رقم» إلزامي"""
    conds, n = [], None
    for part in v.split("|"):
        part = part.strip()
        if not part: continue
        m = re.match(r"^(.+?)\s*([:：~])\s*(.+)$", part)
        if not m: raise DataError(f"settings.txt سطر {ln}: الشرط «{part}» لازم يكون بصيغة العمود:القيمة")
        col, op, val = norm_hdr(m.group(1)).replace("_", " "), m.group(2), m.group(3).strip()
        if col == "العدد":
            vv = val.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
            if not vv.isdigit() or int(vv) <= 0: raise DataError(f"settings.txt سطر {ln}: «العدد» لازم يكون رقم صحيح أكبر من صفر، لقيت «{val}»")
            n = int(vv); continue
        conds.append((col, "~" if op == "~" else ":", [x.strip() for x in val.split("/") if x.strip()]))
    if n is None: raise DataError(f"settings.txt سطر {ln}: قاعدة سحب بدون «العدد» (مثلاً العدد:10)")
    if not conds: raise DataError(f"settings.txt سطر {ln}: قاعدة سحب بدون أي شرط — اكتب مثلاً المستوى:سهل")
    label = "، ".join(f"{c} {'=' if o == ':' else 'يحوي'} {' أو '.join(vs)}" for c, o, vs in conds)
    return {"conds": conds, "n": n, "ln": ln, "label": label}
def _rn(col, s):
    s = str(s).strip().lower()
    return LVL_IN.get(s, s) if col == "المستوى" else s
def rule_match(q, conds):
    for col, op, vals in conds:
        v = _rn(col, q["cols"].get(col, ""))
        if not any((x in v) if op == "~" else (v == x) for x in (_rn(col, y) for y in vals)): return False
    return True
REVIEW_OUT = {"no": "لا", "now": "نعم", "after": "بعد_الإنهاء"}
SPEC = (   # (الحقل، اسم الإعداد بالملف، النوع، العنوان، الشرح، حر = بيتعدّل حتى بعد ما يبدأ الطلاب)
    ("title", "عنوان_الامتحان", "text", "عنوان الامتحان", "فاضي = عنوان تلقائي جديد لكل امتحان. جهاز الطالب بيتذكر «سلّم هذا الامتحان» حسب العنوان، فلا تكرر عنواناً قديماً.", False),
    ("minutes", "المدة_بالدقائق", "int", "المدة بالدقائق", "مدة الامتحان لكل طالب.", False),
    ("final", "العلامة_النهائية", "num", "العلامة النهائية", "الدرجة الكاملة للامتحان (مثلاً 30). فاضي = مجموع علامات الأسئلة.", False),
    ("qmark", "علامة_السؤال", "num", "علامة السؤال", "علامة كل سؤال. لو كتبتها مع العلامة النهائية لازم يتطابقوا. فاضي = من عمود العلامة بملف الأسئلة.", False),
    ("shuffleQ", "خلط_الأسئلة", "bool", "خلط ترتيب الأسئلة", "كل طالب بيشوف الأسئلة بترتيب مختلف.", False),
    ("shuffleO", "خلط_الخيارات", "bool", "خلط ترتيب الخيارات", "كل طالب بيشوف الخيارات بترتيب مختلف.", False),
    ("showScore", "إظهار_العلامة_للطالب", "bool", "إظهار العلامة للطالب بعد التسليم", "", True),
    ("review", "مراجعة_الأخطاء", "review", "مراجعة الأخطاء", "لا = الطالب ما يشوف أخطاءه. نعم = بعد التسليم مباشرة (ممكن اللي خلّص يشارك الأجوبة). بعد_الإنهاء = بعد ما تضغط «إنهاء الامتحان».", True),
    ("lockdown", "منع_النسخ", "bool", "منع النسخ واللصق والزر اليمين", "ردع فقط، مش حماية مطلقة.", False),
    ("needCode", "رمز_الدخول", "bool", "رمز دخول لكل طالب", "نعم = كل طالب لازم يكتب رمزه (من صفحة رموز الدخول).", False),
    ("tpass", "كلمة_سر_المعلم", "text", "كلمة سر المعلم", "بتحمي صفحات المعلم اللي فيها الإجابات. بتتغير فوراً. فاضية = بدون كلمة سر (مش مستحسن).", True),
    ("comp", "تعويض_توقف_السيرفر", "bool", "تعويض وقت توقف السيرفر", "نعم = بنزيد وقت كل طالب بدأ بنفس مدة التوقف (لحد 30 دقيقة).", False),
    ("hard", "عدد_الأسئلة_الصعبة", "count", "عدد الأسئلة الصعبة", "", False),
    ("medium", "عدد_الأسئلة_المتوسطة", "count", "عدد الأسئلة المتوسطة", "", False),
    ("easy", "عدد_الأسئلة_السهلة", "count", "عدد الأسئلة السهلة", "", False),
    ("count", "عدد_الأسئلة_الكلي", "count", "عدد الأسئلة الكلي (لملف بدون مستويات)", "", False),
)
SPEC_BY_KEY = {fk: (f, kind) for f, fk, kind, *_ in SPEC}
COL_SKIP = {"السؤال", "أ", "ب", "ج", "د", "الجواب", "الحل", "العلامة", "ثابت", "الصف", "الرمز"}
def _col_value(col, v):
    v = str(v).strip()
    if col == "المستوى" and LVL_IN.get(v.lower()): return LVL[LVL_IN[v.lower()]]
    return v
def edit_settings_text(old, values, rules, drop=()):
    """يعدّل نص settings.txt بمكانه: يغيّر سطور الإعدادات اللي مذكورة ويضيف الناقص، ويحافظ على التعليقات. rules: قائمة نصوص (None = بدون تغيير)"""
    out, done, rules_at = [], set(), None
    for line in old.splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k = s.split("=", 1)[0].strip().replace(" ", "_")
            if k == "سحب" and rules is not None:
                if rules_at is None: rules_at = len(out)
                continue
            if k in values or k in drop:
                if k in done: continue
                done.add(k)
                if k in values: out.append(f"{k} = {values[k]}")
                continue
        out.append(line)
    add = [f"{k} = {v}" for k, v in values.items() if k not in done]
    if add: out += ([""] if out and out[-1].strip() else []) + add
    if rules:
        block = [f"سحب = {r}" for r in rules]
        if rules_at is not None: out[rules_at:rules_at] = block
        else: out += ([""] if out and out[-1].strip() else []) + ["# قواعد السحب (مكتوبة من صفحة إعدادات الامتحان)"] + block
    return "\n".join(out).rstrip("\n") + "\n"
def _clean_setting(v):
    v = "" if v is None else str(v)
    if "\n" in v or "\r" in v: raise DataError("القيم ما بتقبل سطر جديد")
    return v.strip()
def default_cfg():
    return {"title": "الامتحان الإلكتروني", "minutes": 30, "hard": 3, "medium": 6, "easy": 6, "count": 15,
           "shuffleQ": True, "shuffleO": True, "showScore": True, "lockdown": True, "review": "no", "needCode": False, "tpass": "", "qmark": None, "final": None, "comp": True}

def parse_settings(txt, auto_title):
    """يحلّل نص settings.txt. auto_title: دالة بترجّع العنوان التلقائي (بتعتمد على مجلد الامتحان، فبتجي من server.py)"""
    cfg = default_cfg()
    keys = {"عنوان_الامتحان": "title", "المدة_بالدقائق": "minutes", "عدد_الأسئلة_الصعبة": "hard", "عدد_الأسئلة_المتوسطة": "medium",
            "عدد_الأسئلة_السهلة": "easy", "عدد_الأسئلة_الكلي": "count", "خلط_الأسئلة": "shuffleQ", "خلط_الخيارات": "shuffleO",
            "إظهار_العلامة_للطالب": "showScore", "منع_النسخ": "lockdown", "مراجعة_الأخطاء": "review", "رمز_الدخول": "needCode", "كلمة_سر_المعلم": "tpass", "علامة_السؤال": "qmark", "العلامة_النهائية": "final", "تعويض_توقف_السيرفر": "comp"}
    REVIEW = {"لا": "no", "no": "no", "نعم": "now", "yes": "now", "بعد_الإنهاء": "after"}
    cfg["given"] = set()                                 # الإعدادات اللي انكتبت فعلاً بالملف (الباقي افتراضي)
    for ln, line in enumerate(txt.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = [x.strip() for x in line.split("=", 1)]
        k = k.replace(" ", "_")
        if k == "سحب":                                   # قاعدة سحب: «سحب = الوحدة:الوحدة الأولى | المستوى:سهل | العدد:10»
            cfg.setdefault("rules", []).append(parse_rule(v, ln)); continue
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
