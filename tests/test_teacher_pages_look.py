"""المظهر الموحّد لصفحات المعلم (التقارير، ورقات الطلاب، المفتاح، الرموز، فحص السيرفر): شريط تنقل واحد (اسم الامتحان + التبويبات، مخفي بالطباعة)، ستايل مشترك من اليمين لليسار،
وتقرير بطاقات ودائرة نجاح وأعمدة توزيع العلامات (قائمة بتبدّل بين كل الشعب وشعبة معيّنة) بدون أي مكتبة أو طلب خارجي. صفحات الأرشيف بتستعمل نفس الدوال بدون الشريط."""
import re

import pytest
from test_http import Server, TEACHER
from test_browser import browser, url  # noqa: F401  (fixture)

pw = pytest.importorskip("playwright.sync_api")
TABS = ("/monitor", "/report", "/sheet", "/key", "/health", "/teacher")
PAGES = ("/report", "/sheet", "/key", "/codes", "/health")
A, B = ["طالب أ1", "طالب أ2", "طالب أ3"], ["طالب ب1", "طالب ب2"]


@pytest.fixture
def web(pkg):
    s = Server(pkg).start()
    yield s
    s.stop()


def cookie(w):
    return {"Cookie": w.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0]}


def page(w, path, ck=None):
    st, _, raw, _ = w.get(path, ck); assert st == 200, (path, st); return raw.decode("utf-8")


def submit_with_wrong(w, name, section, wrong):
    """يسلّم طالب وفيه `wrong` أسئلة غلط (الباقي صح): العلامة = (8 - wrong) من 8"""
    k, _, p = w.start_student("d-" + name, n=name, s=section); ans = w.correct_answers(p["ids"])
    for i in range(wrong): ans[i] = -1
    assert w.submit(k, "d-" + name, p["ids"], ans)[0] == 200


def block(html_, key):
    m = re.search(r"<div class=rv data-k='%s'( hidden)?>(.*?)(?=<div class=rv data-k=|<script>)" % re.escape(key), html_, re.S); assert m, key
    return m.group(2), bool(m.group(1))


def kpis(b): return dict(re.findall(r"<span>([^<]*)</span><b>([^<]*)</b>", b))
def hist(b): return [int(x) for x in re.findall(r"<div class=col><b>(\d+)</b>", b)]


# ============================ شريط التنقل ============================
def test_every_teacher_page_has_the_same_nav_with_the_right_active_tab(pkg):
    pkg.settings(**{"رمز_الدخول": "نعم"}); w = Server(pkg).start()
    try:
        ck = cookie(w); want = {"/report": "/report", "/sheet": "/sheet", "/key": "/key", "/codes": "/codes", "/health": "/health"}
        for path, active in want.items():
            t = page(w, path, ck)
            nav = re.search(r"<header class='tnav noprint'>(.*?)</header>", t, re.S); assert nav, path
            hrefs = re.findall(r"<a href=(/\w+)( class=on aria-current=page)?>", nav.group(1))
            assert [h for h, _ in hrefs] == ["/monitor", "/report", "/sheet", "/key", "/codes", "/health", "/teacher"], (path, hrefs)
            assert [h for h, on in hrefs if on] == [active], (path, hrefs)                                  # تبويب واحد بس نشط وهو صفحتها
            assert "/logout" in t                                                                              # في كلمة سر: زر القفل
    finally:
        w.stop()


def test_codes_tab_only_shows_when_login_codes_are_on(web):
    t = page(web, "/report"); assert "/codes" not in t and "/monitor" in t


def test_no_lock_button_without_a_teacher_password(pkg):
    pkg.settings(**{"كلمة_سر_المعلم": ""}); w = Server(pkg).start()
    try:
        for path in ("/report", "/health", "/sheet", "/key"): assert "/logout" not in page(w, path), path
    finally:
        w.stop()


def test_the_exam_title_is_escaped_in_the_nav_and_the_pages(pkg):
    pkg.settings(**{"عنوان_الامتحان": 'امتحان <b>خطر</b> & "x"'}); w = Server(pkg).start()
    try:
        ck = cookie(w)
        for path in PAGES[:-2] + ("/health",):
            t = page(w, path, ck); assert "<b>خطر</b>" not in t and "&lt;b&gt;خطر&lt;/b&gt;" in t, path
    finally:
        w.stop()


def test_pages_are_standalone_no_external_requests(pkg):
    pkg.settings(**{"رمز_الدخول": "نعم"}); w = Server(pkg).start()
    try:
        ck = cookie(w)
        for path in PAGES:
            t = page(w, path, ck); assert not re.search(r"""(src|href)=["']?https?://""", t) and "<link " not in t and "@import" not in t, path
    finally:
        w.stop()


# ============================ التقرير ============================
def test_report_numbers_and_charts_match_the_submissions(web):
    for n, wrong in zip(A, (0, 0, 2)): submit_with_wrong(web, n, "أ", wrong)
    for n, wrong in zip(B, (4, 6)): submit_with_wrong(web, n, "ب", wrong)
    t = page(web, "/report")
    allb, hidden = block(t, ""); assert not hidden
    k = kpis(allb); assert k["إجمالي الطلاب"] == "5" and k["سلّموا"] == "5" and k["المتوسط %"] == "70.0" and k["الأعلى %"] == "100" and k["الأدنى %"] == "25", k
    assert k["نسبة النجاح (من 50% وما فوق)"] == "80%" and hist(allb) == [2, 1, 0, 1, 1], (k, hist(allb))        # ممتاز 2 (100,100) | جيد جداً 1 (75) | جيد 0 | مقبول 1 (50) | ضعيف 1 (25)
    assert "stroke-dasharray='80 20'" in allb and ">80%</text>" in allb and "نجح 4 ورسب 1" in allb
    ba, hid = block(t, "العاشر|أ"); assert hid
    assert kpis(ba)["المتوسط %"] == "91.7" and kpis(ba)["إجمالي الطلاب"] == "3" and hist(ba) == [2, 1, 0, 0, 0]
    bb, _ = block(t, "العاشر|ب"); assert kpis(bb)["نسبة النجاح (من 50% وما فوق)"] == "50%" and hist(bb) == [0, 0, 0, 1, 1]
    assert "ملخص الشعب" in t and "تحليل الأسئلة" in t and re.search(r"<span class='badge (hard|medium|easy)'>", t)
    assert t.count("<div class=tw>") == 2 and t.count("</table></div>") == 2                                 # جدولا الملخص والتحليل بإطار تمرير أفقي (للجوال)


def test_band_edges_and_the_pass_line(web):
    """علامات على حدود الفئات: 87.5 ممتاز (من 85)، 75 جيد جداً (من 75)، 62.5 و50 مقبول، 37.5 ضعيف؛ وحد النجاح 50% شامل"""
    for n, s, wrong in (("طالب أ1", "أ", 1), ("طالب أ2", "أ", 2), ("طالب أ3", "أ", 3), ("طالب ب1", "ب", 4), ("طالب ب2", "ب", 5)): submit_with_wrong(web, n, s, wrong)
    allb, _ = block(page(web, "/report"), ""); k = kpis(allb)
    assert hist(allb) == [1, 1, 0, 2, 1], hist(allb)
    assert k["نسبة النجاح (من 50% وما فوق)"] == "80%" and k["المتوسط %"] == "62.5", k                          # 4 من 5 (الـ 50 ناجح)


def test_report_without_submissions_renders_safely(web):
    t = page(web, "/report"); allb, _ = block(t, "")
    assert "لا يوجد تسليم بعد" in allb and "<svg" not in allb and kpis(allb)["إجمالي الطلاب"] == "5" and kpis(allb)["المتوسط %"] == "—"


def test_report_section_filter_switches_the_block_in_the_browser(web, browser):
    for n, wrong in zip(A, (0, 0, 2)): submit_with_wrong(web, n, "أ", wrong)
    for n, wrong in zip(B, (4, 6)): submit_with_wrong(web, n, "ب", wrong)
    ctx = browser.new_context(viewport={"width": 1366, "height": 800}, locale="ar-JO"); pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    try:
        pg.goto(url(web) + "report"); vis = lambda: pg.eval_on_selector_all(".rv", "e=>e.filter(x=>!x.hidden).map(x=>x.dataset.k)")
        assert vis() == [""] and pg.locator(".rv:not([hidden]) .kpi b").nth(2).inner_text() == "70.0"
        pg.select_option("#secf", "العاشر|ب"); assert vis() == ["العاشر|ب"] and pg.locator(".rv:not([hidden]) .kpi b").nth(2).inner_text() == "37.5"
        pg.select_option("#secf", ""); assert vis() == [""]
        assert pg.evaluate("getComputedStyle(document.documentElement).direction") == "rtl" and not errs
    finally:
        ctx.close()


# ============================ الاتجاه والطباعة والجوال ============================
def test_nav_is_hidden_in_print_and_the_brand_sits_on_the_right(web, browser):
    submit_with_wrong(web, A[0], "أ", 0)
    ctx = browser.new_context(viewport={"width": 1366, "height": 800}, locale="ar-JO"); pg = ctx.new_page()
    try:
        ck = web.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0].split("=", 1)
        ctx.add_cookies([{"name": ck[0], "value": ck[1], "url": url(web)}])
        for path in ("report", "key", "sheet", "health"):
            pg.goto(url(web) + path)
            b = pg.eval_on_selector(".tnav .brand", "e=>e.getBoundingClientRect().left"); n = pg.eval_on_selector(".tnav nav", "e=>e.getBoundingClientRect().left")
            assert b > n, (path, b, n)                                                                       # اسم الامتحان أول عنصر من اليمين، والتبويبات على يساره
            pg.emulate_media(media="print")
            assert pg.eval_on_selector(".tnav", "e=>getComputedStyle(e).display") == "none", path
            assert pg.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(255, 255, 255)", path
            pg.emulate_media(media="screen")
    finally:
        ctx.close()


@pytest.mark.parametrize("path", ["report", "sheet", "key", "health"])
def test_no_horizontal_page_scroll_on_a_phone(web, browser, path):
    for n, wrong in zip(A, (0, 1, 2)): submit_with_wrong(web, n, "أ", wrong)
    ctx = browser.new_context(viewport={"width": 375, "height": 800}, is_mobile=True, locale="ar-JO"); pg = ctx.new_page()
    try:
        ck = web.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0].split("=", 1)
        ctx.add_cookies([{"name": ck[0], "value": ck[1], "url": url(web)}])
        pg.goto(url(web) + path); pg.wait_for_timeout(300)
        assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), path          # الجداول العريضة بتتمرّر جوا إطارها
    finally:
        ctx.close()


# ============================ الأرشيف ============================
def test_archive_report_and_key_have_no_teacher_nav_and_relative_links(srv):
    r = srv.report_page(arch_home="index.html"); k = srv.key_page(arch_home="index.html")
    for t in (r, k):
        assert "<header" not in t and "/monitor" not in t and "/logout" not in t and "href='index.html'" in t
    assert "href='report.xlsx'" in r and "href=/report.xlsx" not in r and "<script>" in r                    # القائمة بتشتغل بالأرشيف كمان (JS صغير بدون مكتبات)
