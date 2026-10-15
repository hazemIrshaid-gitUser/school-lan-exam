"""الكسور: (x + 7)/(x² − x − 6) و 5π/6 و −3/4 بتنعرض بسط فوق خط فوق مقام (x-fr) بكل صفحة فيها نص السؤال، بدون ما يتغيّر ملف الأسئلة.
والمعادلة جوّا جملة عربية بتنعرض كتلة وحدة (x-m) عشان ما تنقلب لما تلتفّ على سطرين بالجوال.
الحالات من بنك أستاذ رياضيات حقيقي (كسور جزئية، فترات، زوايا بالراديان، وحدات cm/s)."""
import re, urllib.parse

import pytest
from conftest import q
from test_http import Server
from test_browser import browser, phone, login, pick  # noqa: F401  (fixtures)

plain = lambda t: t.replace(chr(0x2066), "").replace(chr(0x2069), "")


def show(h):
    """HTML الكسور -> شكل مقروء للمقارنة: [بسط ÷ مقام]"""
    return re.sub(r"</?x-(?:fr|n|d|m)>", lambda m: {"<x-fr>": "[", "</x-fr>": "]", "</x-n>": " ÷ "}.get(m.group(), ""), h)


@pytest.mark.parametrize("src, want", [
    ("(x + 7)/(x² − x − 6) = A/(x − 3) + B/(x + 2)", "[x + 7 ÷ x² − x − 6] = [A ÷ x − 3] + [B ÷ x + 2]"),
    ("1 + 5/(2(x − 1)) − 3/(2(x + 1))", "1 + [5 ÷ 2(x − 1)] − [3 ÷ 2(x + 1)]"),
    ("(3x + 1)/((x − 1)(x + 2))", "[3x + 1 ÷ (x − 1)(x + 2)]"),                        # القوس الخارجي بيروح، الداخلية بتضل
    ("A/(x − 1) + B/(x − 1)²", "[A ÷ x − 1] + [B ÷ (x − 1)²]"),                          # القوس مع أُس بيضل
    ("(−∞, −5/3] ∪ [3, ∞)", "(−∞, −[5 ÷ 3]] ∪ [3, ∞)"),
    ("{−2, −1/2, 3}", "{−2, −[1 ÷ 2], 3}"),
    ("sin⁻¹(√3/2) في [−π/2, π/2]", "sin⁻¹([√3 ÷ 2]) في [−[π ÷ 2], [π ÷ 2]]"),
    ("(sin 5π/6)² + (cos 4π/3)²", "(sin [5π ÷ 6])² + (cos [4π ÷ 3])²"),
    ("x²/2 و 7.5/2 و (√3 − 3)/2", "[x² ÷ 2] و [7.5 ÷ 2] و [√3 − 3 ÷ 2]"),
    ("f(x)/g(x) و 1/sin(x)", "[f(x) ÷ g(x)] و [1 ÷ sin(x)]"),
    ("2/3(x + 1)", "[2 ÷ 3](x + 1)"),                                                    # ثلثين ضرب القوس، مش 2 على 3(x+1)
    ("(1/x)/(2) و a/(b/c)", "[[1 ÷ x] ÷ 2] و [a ÷ [b ÷ c]]"),                           # كسر جوّا كسر
    ("(x + 1) / (x − 1)", "[x + 1 ÷ x − 1]"),
    ("x/y", "[x ÷ y]"),
])
def test_fractions_are_drawn(srv, src, want):
    assert show(srv.fracs(src)) == want


@pytest.mark.parametrize("src", [
    "200π cm/s", "بوحدة in/s", "m/s", "km/h", "rad/s",                                     # وحدات
    "15/10/2026", "a/b/c", "http://x.com/a", "و/أو", "/x", "x/", "x²/²", "x/(y", "(x)/(",
    "ab/c",                                                                                # حرفين: غالباً وحدة، بيضل سطر
])
def test_things_that_are_not_fractions_stay_as_typed(srv, src):
    assert srv.fracs(src) == src


def test_html_is_still_escaped_inside_fractions(srv):
    h = srv.fracs("(<b>x</b> & 1)/(y > 2) <script>")
    assert "<b>" not in h and "<script>" not in h and "&lt;b&gt;x&lt;/b&gt; &amp; 1" in h and "y &gt; 2" in h and show(h).startswith("[")


def test_equation_in_arabic_sentence_is_one_block(srv):
    t = srv.autoltr("إذا كان (x + 7)/(x − 3) = 2، فما قيمة x؟")
    h = srv.qhtml(t)
    assert h.count("<x-m>") == 1 and "<x-fr>" in h.split("<x-m>")[1].split("</x-m>")[0]
    assert plain(re.sub("<[^>]+>", "", h)) == plain(re.sub("<[^>]+>", "", srv.fracs(t)))       # نفس الحروف، بس ملفوفة
    assert "<x-m>" in srv.qhtml(srv.autoltr("مجموعة حل |3x − 2| ≥ 7 هي:"))                   # متباينة بدون كسر كمان
    assert "<x-m>" not in srv.qhtml(srv.autoltr("قطرها 50 cm وسرعتها بوحدة in/s"))             # كلمات/وحدات: بدون تغيير
    assert "<x-m>" not in srv.qhtml(srv.autoltr("If x = 1/2, what is 2x?"))                     # سؤال إنجليزي: كله سطر عادي
    assert "<x-m>" not in srv.qhtml(srv.autoltr("(−∞, −5/3] ∪ [3, ∞)"))                         # خيار رياضي لحاله


def test_template_has_the_same_fraction_css(srv, pkg):
    assert srv.FRAC_CSS in pkg.p("template.html").read_text(encoding="utf-8")


FRAC_BANK = [q("إذا كان (x + 7)/(x² − x − 6) = A/(x − 3) + B/(x + 2)، فما قيمة B؟", ("1", "2", "−2", "−1"), "ب"),
             q("قيمة sin(3π/2) تساوي:", ("−1/2", "1/2", "−√3/2", "√3/2"), "أ"),
             q("قياس 7π/6 بالدرجات:", ("210°", "240°", "150°", "420°"), "أ"),
             q("سرعتها بوحدة cm/s:", ("200π", "8π", "100π", "400π"), "أ")]


@pytest.fixture
def fweb(pkg):
    pkg.questions(FRAC_BANK); pkg.settings(**{"عدد_الأسئلة_الصعبة": "", "عدد_الأسئلة_المتوسطة": "", "عدد_الأسئلة_السهلة": "", "عدد_الأسئلة_الكلي": "4",
                                              "خلط_الأسئلة": "لا", "خلط_الخيارات": "لا", "مراجعة_الأخطاء": "نعم"})
    w = Server(pkg).start()
    yield w
    w.stop()


def test_every_page_with_question_text_draws_fractions(fweb):
    from test_codes_sheets import cookie, tget, html_of
    k, _, p = fweb.start_student("d1")
    assert "<x-fr>" in p["qs"][0]["q"] and "<x-fr>" in p["qs"][1]["o"][0] and "<x-fr>" not in p["qs"][3]["q"]
    fweb.submit(k, "d1", p["ids"], [0, 0, 0, 0])                                             # الأول غلط
    st, r, *_ = fweb.post("/review", {"key": k, "dev": "d1"}); assert "<x-fr>" in r["items"][0]["q"]
    ck = cookie(fweb)
    for path in ("/teacher", "/key", "/sheet?key=" + urllib.parse.quote(k)):
        t = html_of(tget(fweb, path, ck)); assert "<x-fr>" in t and "x-fr{display:inline-flex" in t, path
    assert "x-fr" not in html_of(tget(fweb, "/monitor.json", ck))                                  # النصوص العادية (المراقبة والملفات) زي ما هي
    for f in ("results.csv", "submissions.jsonl", "papers.json"):
        assert "x-fr" not in fweb.pkg.p(f).read_text(encoding="utf-8-sig"), f


def test_fraction_renders_stacked_on_a_phone(fweb, phone):
    page = phone(); login(page, fweb)
    box = page.evaluate("""()=>{const f=document.querySelector('#qs .card .q x-fr');const r=e=>e.getBoundingClientRect();
        const n=f.querySelector('x-n'),d=f.querySelector('x-d');return {n:r(n),d:r(d),f:r(f),
        bar:getComputedStyle(d).borderTopStyle, m:!!f.closest('x-m'), mw:r(f.closest('x-m')).width, card:r(f.closest('.q')).width}}""")
    assert box["n"]["bottom"] <= box["d"]["top"] + 1 and box["bar"] == "solid"                  # البسط فوق المقام والخط بينهم
    assert abs(box["n"]["width"] - box["d"]["width"]) < 1                                      # الخط بعرض الأعرض فيهم
    assert box["m"] and box["mw"] <= box["card"] + 1
    xs = page.evaluate("""()=>[...document.querySelector('#qs .card .q').querySelectorAll('x-m x-fr')].map(f=>[f.getBoundingClientRect().left,f.getBoundingClientRect().top])""")
    assert len(xs) == 3 and (xs[0][0] < xs[1][0] < xs[2][0] or xs[0][1] < xs[2][1])          # المعادلة بترتيبها من اليسار (أو التفّت لتحت)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    pick(page, 1, 0); assert page.locator("#qs .card").nth(1).locator("input:checked").count() == 1   # الضغط على خيار فيه كسر بيختاره
    assert not page.js_errors
