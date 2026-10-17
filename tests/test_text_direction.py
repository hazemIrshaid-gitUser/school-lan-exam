"""اتجاه النص: سؤال أو خيار فيه جملة عربية وبيبدأ بحرف لاتيني (f(x) = ... عندما x < 3) كان يطلع LTR وتنقلب كلماته،
لأن dir=auto بيقرأ أول حرف قوي بس. الحل: فيه حرف عربي (خارج المقاطع الرياضية المعزولة) ← dir=rtl، وغير هيك auto
(الإنجليزي والرياضي لحاله ما بيتأثر). مصدر الحالة: سؤال 6 بامتحان أستاذ رياضيات حقيقي (|3x − 9| بدون رمز القيمة المطلقة)."""
import re, urllib.parse

import pytest
from conftest import q
from test_http import Server
from test_browser import browser, phone, login, pick, show, submit, no_hscroll, url  # noqa: F401  (fixtures + helpers)

I, P = chr(0x2066), chr(0x2069)
AR_STEM = "إعادة تعريف الاقتران f(x) = |3x − 9| بدون رمز القيمة المطلقة تكون:"
AR_OPT_1 = "f(x) = −3x + 9 عندما x < 3، و f(x) = 3x − 9 عندما x ≥ 3"
AR_OPT_2 = "f(x) = 3x − 9 عندما x < 3، و f(x) = −3x + 9 عندما x ≥ 3"
LATIN_STEM_AR = "f(x) = |x| معرّف على مجموعة الأعداد الحقيقية جميعها، صحيح؟"       # بيبدأ بحرف لاتيني وفيه عربي
EN_STEM = "If f(x) = 2x + 1, what is f(3)?"

DIR_BANK = [q(AR_STEM, (AR_OPT_1, AR_OPT_2, "f(x) = 3x − 9", "f(x) = −3x + 9"), "أ"),
            q(LATIN_STEM_AR, ("نعم", "لا", "f(x) = x", "f(x) = −x"), "أ"),
            q(EN_STEM, ("7", "5", "9", "3"), "أ"),
            q("قيمة x التي تحقق المعادلة:", ("2", "x² + 1", "(−∞, −5/3]", "f(x) = 3"), "أ")]
SETTINGS = {"عدد_الأسئلة_الصعبة": "", "عدد_الأسئلة_المتوسطة": "", "عدد_الأسئلة_السهلة": "", "عدد_الأسئلة_الكلي": "4",
            "خلط_الأسئلة": "لا", "خلط_الخيارات": "لا", "مراجعة_الأخطاء": "نعم"}


@pytest.mark.parametrize("text, want", [
    (I + "f(x) = −3x + 9" + P + " عندما " + I + "x < 3" + P, "rtl"),               # الخيار الأصلي: بيبدأ لاتيني وفيه عربي
    ("إعادة تعريف الاقتران " + I + "f(x)" + P, "rtl"),
    ("نعم", "rtl"),
    (I + "f(x) = 3x − 9" + P, "auto"),                                             # رياضي لحاله: ما بيتغيّر
    (I + "(−∞, −5/3]" + P, "auto"),
    ("7", "auto"),
    ("If f(x) = 2x + 1, what is f(3)?", "auto"),                                   # إنجليزي
    ("", "auto"),
    (I + "عربي جوّا العزل" + P, "auto"),                                            # الحرف العربي لازم يكون خارج المقاطع المعزولة
])
def test_bdir_rule(srv, text, want):
    assert srv.bdir(text) == want


def test_server_pages_use_the_rule(pkg):
    pkg.questions(DIR_BANK); pkg.settings(**SETTINGS)
    w = Server(pkg).start()
    try:
        from test_codes_sheets import cookie, tget, html_of
        k, _, p = w.start_student("d1")
        w.submit(k, "d1", p["ids"], [0, 0, 0, 0])
        ck = cookie(w)
        for path in ("/key", "/sheet?key=" + urllib.parse.quote(k)):
            t = html_of(tget(w, path, ck))
            spans = re.findall(r"<span dir=(\w+)>(.*?)</span>", t, re.S)
            by = {}
            for d, body in spans: by.setdefault(d, []).append(re.sub("<[^>]+>", "", body))
            assert any("القيمة المطلقة" in b for b in by.get("rtl", [])), path                       # السؤال العربي
            assert any(b.startswith("f(x) = |x|") or I + "f(x) = |x|" in b for b in by.get("rtl", [])), path   # بيبدأ لاتيني وفيه عربي
            assert any(AR_OPT_1[:12] in b for b in by.get("rtl", [])), path                          # الخيار المختلط
            assert any("If f(x)" in b for b in by.get("auto", [])), path                              # الإنجليزي ما اتغيّر
            assert any("(−∞, −" in b for b in by.get("auto", [])), path                                  # والرياضي لحاله
            assert not any("If f(x)" in b for b in by.get("rtl", [])), path
        t = html_of(tget(w, "/teacher", ck))
        assert "const D=t=>" in t and t.count('dir="${D(') == 4                                       # القالب: البطاقة والخيار ومراجعتان
    finally:
        w.stop()


def test_page_rule_equals_server_rule(pkg, srv, browser):
    """نفس القاعدة بالمتصفح (على HTML جاهز) وبالسيرفر (على النص الخام)"""
    pkg.questions(DIR_BANK); pkg.settings(**SETTINGS)
    samples = [I + "f(x)" + P + " " + "عندما", "x", "نعم", I + "f(x) = 3" + P, "If x = 1/2", "(x + 7)/(x − 3) = 2 ما قيمة x؟",
               "ما قيمة (x + 7)/(x − 3) = 2", "قيمة " + I + "x < 3" + P, I + "عربي" + P]
    want = ["rtl", "auto", "rtl", "auto", "auto", "rtl", "rtl", "rtl", "auto"]
    assert [srv.bdir(s) for s in samples] == want
    w = Server(pkg).start()
    try:
        ctx = browser.new_context(locale="ar-JO"); page = ctx.new_page()
        page.goto(url(w))
        assert page.evaluate("(a)=>a.map(t=>D(t))", [srv.qhtml(s) for s in samples]) == want
        # الوسوم (x-fr وx-m والصور وحتى لو اسم الصورة عربي) ما بتحسب كأنها نص عربي
        assert page.evaluate("""()=>[D('<x-fr><x-n>1</x-n><x-d>2</x-d></x-fr>'),D('<img alt="صورة" src="/img/x.png">'),D('<x-m>⁦x⁩</x-m> نص')]""") == ["auto", "auto", "rtl"]
        ctx.close()
    finally:
        w.stop()


def lay(page, i):
    """ترتيب الشرطين بالخيار الأول على السطر: بالـ RTL الشرط الأول (أول x-m) لازم يكون على يمين الثالث"""
    return page.evaluate("""(i)=>{const sp=document.querySelectorAll('#qs .card')[i].querySelector('label.opt span');
        const m=[...sp.querySelectorAll('x-m')].map(e=>e.getBoundingClientRect());
        return {n:m.length, firstRight:m[0].left>m[2].left, sameLine:Math.abs(m[0].top-m[2].top)<4, dir:getComputedStyle(sp).direction}}""", i)


def test_student_page_desktop(pkg, browser):
    pkg.questions(DIR_BANK); pkg.settings(**SETTINGS)
    w = Server(pkg).start()
    try:
        ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ar-JO"); page = ctx.new_page(); page.set_default_timeout(8000)
        errors = []; page.on("pageerror", lambda e: errors.append(str(e)))
        login(page, w)
        cards = page.locator("#qs .card")
        info = page.evaluate("""()=>[...document.querySelectorAll('#qs .card')].map(c=>({card:c.getAttribute('dir'),cc:getComputedStyle(c).direction,
            opts:[...c.querySelectorAll('label.opt span')].map(s=>[s.getAttribute('dir'),getComputedStyle(s).direction])}))""")
        # 1) سؤال عربي، خياراته الأولى مختلطة (بتبدأ لاتيني) والباقي رياضي
        assert info[0]["card"] == "rtl" and info[0]["cc"] == "rtl"
        assert info[0]["opts"] == [["rtl", "rtl"], ["rtl", "rtl"], ["auto", "ltr"], ["auto", "ltr"]]
        # 2) سؤال بيبدأ بـ f(x) وفيه جملة عربية: كان LTR
        assert info[1]["card"] == "rtl" and info[1]["cc"] == "rtl" and info[1]["opts"][0] == ["rtl", "rtl"] and info[1]["opts"][2] == ["auto", "ltr"]
        # 3) إنجليزي: ما اتغيّر
        assert info[2]["card"] == "auto" and info[2]["cc"] == "ltr" and all(o == ["auto", "ltr"] for o in info[2]["opts"])
        # 4) أرقام ومعادلات بدون عربي بالخيارات
        assert info[3]["card"] == "rtl" and all(o == ["auto", "ltr"] for o in info[3]["opts"])
        L = lay(page, 0)
        assert L["n"] == 4 and L["sameLine"] and L["firstRight"] and L["dir"] == "rtl"                      # الشرط الأول على اليمين: بترتيب القراءة العربي
        # مراجعة الأخطاء: السؤالان الأولان غلط
        pick(page, 0, 3); pick(page, 1, 1); pick(page, 2, 0); pick(page, 3, 0)
        submit(page)
        page.wait_for_selector("#review .rv")
        rv = page.evaluate("""()=>[...document.querySelectorAll('#review .rv')].map(r=>[r.getAttribute('dir'),getComputedStyle(r).direction])""")
        assert rv == [["rtl", "rtl"], ["rtl", "rtl"]]
        assert not errors
        ctx.close()
    finally:
        w.stop()


def test_student_page_phone(pkg, phone):
    pkg.questions(DIR_BANK); pkg.settings(**SETTINGS)
    w = Server(pkg).start()
    try:
        page = phone(); login(page, w)
        d = page.evaluate("""()=>[...document.querySelectorAll('#qs .card')[0].querySelectorAll('label.opt span')].map(s=>getComputedStyle(s).direction)""")
        assert d == ["rtl", "rtl", "ltr", "ltr"]
        assert no_hscroll(page)
        pick(page, 0, 0); assert page.locator("#qs .card").nth(0).locator("input:checked").count() == 1
        show(page, 1)
        assert page.evaluate("getComputedStyle(document.querySelectorAll('#qs .card')[1]).direction") == "rtl" and no_hscroll(page)
        assert not page.js_errors
    finally:
        w.stop()
