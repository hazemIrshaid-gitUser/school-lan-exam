"""أدوات عامة بدون حالة: أرقام العلامات، قراءة/كتابة الملفات الذرية، مقارنة كلمات السر."""
import html, json, os, time

def grp(q): return q.get("grp", q["level"])      # مجموعة السحب للسؤال (بدون قواعد = المستوى)
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
class DataError(Exception): pass
def norm_code(c): return str(c).translate(str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")).strip()
_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
def norm_pass(s):
    """كلمة السر للمقارنة: الأرقام العربية (١٢٣٤) زي الإنجليزية (1234)، والمسافات بالأطراف ما بتفرق"""
    return str(s).translate(_DIG).strip()
