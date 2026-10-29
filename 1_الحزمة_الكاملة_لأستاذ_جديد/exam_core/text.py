"""تنسيق نصوص الأسئلة للعرض (بدون حالة): عزل المقاطع الرياضية، الكسور، اتجاه النص."""
import re
from .util import E

_MATH = r"[A-Za-z0-9Ͱ-Ͽ←-⋿°π√∞∑∫±×÷−=<>≤≥≠≈^_/|()\[\]{}\u2070-\u209F²³¹.,:;%+\-'’ ]"
_MATH_RUN = re.compile(r"(?:%s)+" % _MATH)
def autoltr(t):
    """يلف المقاطع الرياضية/اللاتينية بعزل LTR عشان ما تنعكس داخل الجملة العربية"""
    if "⁦" in t: return t
    def fix(m):
        s = m.group(0); core = s.strip(" .,:;")
        if not re.search(r"[A-Za-z0-9Ͱ-Ͽ°π√∞]", core): return s
        lead = s[:len(s) - len(s.lstrip(" .,:;"))]; tail = s[len(lead) + len(core):]
        return lead + "⁦" + core + "⁩" + tail
    return _MATH_RUN.sub(fix, t)
_PUA = "[-]"
def noimg(text):
    return re.sub(_PUA, "[صورة]", text)
_SUPS = "²³¹" + "".join(map(chr, range(0x2070, 0x20A0)))       # أُسس ودلائل مرفوعة/منخفضة بتلحق آخر الحد: x² و (x − 1)²
_STOP = "\n\u2066\u2067\u2068\u2069"                                     # القوس ما بيعبر سطر جديد ولا علامة عزل اتجاه
def _wc(s, i):
    """حرف من «كلمة» رياضية: أرقام وحروف لاتينية ويونانية و√ و∞، والنقطة العشرية بين رقمين (7.5)"""
    c = s[i]
    if (c.isascii() and c.isalnum()) or "Ͱ" <= c <= "Ͽ" or c in "√∞": return True
    return c == "." and 0 < i < len(s) - 1 and s[i - 1] in "0123456789" and s[i + 1] in "0123456789"
def _pair(s, i, step):
    """مكان القوس المقابل للقوس اللي عند i (step=1 لـ «(» و -1 لـ «)»)، أو -1"""
    d, k = 0, i
    while 0 <= k < len(s):
        if s[k] in _STOP: return -1
        d += (s[k] == "(") - (s[k] == ")")
        if d == 0: return k
        k += step
    return -1
def _frac_at(s, j):
    """الحدّين حوالين «/» اللي عند j: (بداية البسط، نهاية المقام، البسط، المقام) أو None لو مش كسر"""
    a = j
    while a > 0 and s[a - 1] == " ": a -= 1
    e = a
    while a > 0 and s[a - 1] in _SUPS: a -= 1
    if a > 0 and s[a - 1] == ")":
        a = _pair(s, a - 1, -1)
        if a < 0: return None
    while a > 0 and _wc(s, a - 1): a -= 1
    b = j + 1
    while b < len(s) and s[b] == " ": b += 1
    st = b
    while b < len(s) and _wc(s, b): b += 1
    if b < len(s) and s[b] == "(" and (b == st or re.search("[A-Za-zͰ-Ͽ]", s[st:b])):   # 1/(x+1) و 1/sin(x)، بس 2/3(x+1) = ثلثين ضرب القوس
        c = _pair(s, b, 1)
        if c > 0: b = c + 1
    while b < len(s) and s[b] in _SUPS: b += 1
    num, den = s[a:e], s[st:b]
    if not num.strip(_SUPS) or not den.strip(_SUPS): return None
    if (a > 0 and s[a - 1] == "/") or (b < len(s) and s[b] == "/"): return None       # تاريخ 15/10/2026 أو a/b/c: بيضل زي ما هو
    if num.isascii() and den.isascii() and num.isalpha() and den.isalpha() and (len(num) > 1 or len(den) > 1 or (num in "mshgl" and den in "mshgl")):
        return None                                                                       # وحدات: cm/s و in/s و km/h و m/s
    return a, b, num, den
def _unwrap(t):
    return t[1:-1] if t[:1] == "(" and _pair(t, 0, 1) == len(t) - 1 else t                    # (x + 7) فوق الخط بتصير x + 7
def fracs(s):
    """نص السؤال -> HTML (مهرّب) والكسور فيه عناصر x-fr. عناصر خاصة مش span، لأن تنسيق الخيارات بالقالب بيغيّر كل span جوّاتها"""
    d, cands = 0, []
    for k, c in enumerate(s):
        if c == "(": d += 1
        elif c == ")": d = max(0, d - 1)
        elif c == "/": cands.append((d, k))
    done = []
    for _, j in sorted(cands):                       # الأقل عمقاً أول: (1/x)/2 هو كسر بسطه 1/x، والكسر الداخلي بيترسم جوّا البسط
        if any(a <= j < b for a, b, *_ in done): continue
        m = _frac_at(s, j)
        if m and not any(m[0] < b and a < m[1] for a, b, *_ in done): done.append(m)
    out, last = [], 0
    for a, b, num, den in sorted(done):
        out += [E(s[last:a]), "<x-fr><x-n>", fracs(_unwrap(num)), "</x-n><x-d>", fracs(_unwrap(den)), "</x-d></x-fr>"]
        last = b
    return "".join(out) + E(s[last:])
_ISO = re.compile("⁦([^⁦-⁩]*)⁩")
_MATH_OPS = ("<x-fr>", "=", "+", "−", "×", "÷", "±", "≤", "≥", "≠", "≈", "|", "∪", "∩", "&lt;", "&gt;")
def bdir(text):
    """اتجاه نص السؤال/الخيار بصفحات السيرفر: فيه حرف عربي (خارج المقاطع الرياضية المعزولة) ← rtl، وغيره auto.
    dir=auto لوحده بيقرأ أول حرف قوي: خيار بيبدأ بـ f(x) وبعده جملة عربية كان يطلع LTR وتنقلب كلماته"""
    return "rtl" if re.search("[؀-ۿ]", _ISO.sub("", text)) else "auto"
FRAC_CSS = ("x-fr{display:inline-flex;flex-direction:column;align-items:stretch;vertical-align:middle;direction:ltr;unicode-bidi:isolate;"
            "margin:0 .12em;font-size:.92em;line-height:1.25;text-align:center}x-fr x-fr{font-size:1em}"
            "x-n,x-d{display:block;padding:0 .2em;white-space:nowrap}x-d{border-top:.09em solid currentColor}"
            "x-m{display:inline-block;direction:ltr;max-width:100%}")
def qhtml_text(text):
    """نص سؤال أو خيار زي ما بينعرض بأي صفحة: مهرّب، والكسور مرسومة، والصور.
    المعادلة جوّا جملة عربية بتنعرض كتلة وحدة من اليسار لليمين (x-m): لو ما وسعها السطر بالجوال بتنزل كاملة أو بتلتفّ جوّا حالها
    بترتيبها — بدونها كان نصها الثاني يطلع بالسطر اللي بعده قبل الأول بترتيب القراءة. النص الإنجليزي والرياضي لحاله ما بيتأثر"""
    h = fracs(text)
    if re.search("[؀-ۿ]", text):
        h = _ISO.sub(lambda m: "⁦<x-m>" + m.group(1) + "</x-m>⁩" if any(c in m.group(1) for c in _MATH_OPS) else m.group(0), h)
    return h
