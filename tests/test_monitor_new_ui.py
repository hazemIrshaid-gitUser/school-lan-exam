"""واجهة المراقبة الجديدة (/monitor): ملفات ثابتة جاهزة بمجلد monitor_ui بتقدّمها السيرفر، ومصدرها tools/monitor_ui_src (React).
فحص المسارات (الحقن، الملفات الثابتة، منع الخروج من المجلد، للمعلم فقط، الرجوع للقديمة)، وفحص الواجهة بمتصفح حقيقي ضد السيرفر الحقيقي:
العدادات، لوحة «يحتاجون انتباهك»، كل أوامر المعلم، شاشة البروجكتر، انقطاع السيرفر وتعويض الوقت وتغيّر ملف الأسئلة وبداية امتحان جديد.
الصفحة القديمة بتضل على /monitor-old (وبتنعرض على /monitor لو مجلد monitor_ui مش موجود) وتختبرها test_monitor_ui.py."""
import http.client, json, os, re, shutil, threading, time, urllib.parse

import pytest
from conftest import PKG_SRC, bank
from test_http import Server, TEACHER, lan_ip
from test_browser import browser, url  # noqa: F401  (fixture)

pw = pytest.importorskip("playwright.sync_api")
expect = pw.expect
UI_SRC = PKG_SRC / "monitor_ui"
pytestmark = pytest.mark.skipif(not (UI_SRC / "index.html").exists(), reason="مجلد monitor_ui مش موجود بالحزمة")
TITLE = "اختبار الوحدة"
A = [f"طالب أ{i}" for i in range(1, 8)]; B = [f"طالب ب{i}" for i in range(1, 6)]


def with_ui(pkg):
    shutil.copytree(UI_SRC, pkg.path / "monitor_ui", dirs_exist_ok=True)


def raw_get(w, path, host="127.0.0.1"):
    c = http.client.HTTPConnection(host, w.port, timeout=10)
    try:
        c.request("GET", path); r = c.getresponse(); return r.status, dict(r.getheaders()), r.read()
    finally:
        c.close()


@pytest.fixture
def servers():
    made = []
    def start(pk, port=None):
        s = Server(pk).start(port=port); made.append(s); return s
    yield start
    for s in made: s.stop()


# ============================ المسارات (بدون متصفح) ============================
def test_monitor_serves_the_new_ui_with_the_real_link_and_title(pkg, servers):
    with_ui(pkg); pkg.settings(**{"عنوان_الامتحان": 'امتحان "خاص" </script><script>alert(1)</script>'}); w = servers(pkg)
    for path in ("/monitor", "/admin"):
        st, hdr, body = raw_get(w, path); page = body.decode("utf-8")
        assert st == 200 and hdr["Content-Type"].startswith("text/html") and 'id="root"' in page and "/monitor-ui/assets/" in page, path
        m = re.search(r"window\.MONITOR_CONFIG = (\{.*?\});", page, re.S); cfg = json.loads(m.group(1))
        assert cfg["title"] == 'امتحان "خاص" </script><script>alert(1)</script>' and cfg["link"].startswith("http://")        # العنوان بعينه، بدون ما ينكسر السكربت
        assert "</script><script>alert(1)" not in page and "192.168.43.253" not in page                                         # ما بقي رابط ولا عنوان الديمو
    assert w.get("/monitor.json")[0] == 200


def test_static_files_and_content_types(pkg, servers):
    with_ui(pkg); w = servers(pkg)
    page = raw_get(w, "/monitor")[2].decode("utf-8")
    js = re.search(r'src="(/monitor-ui/assets/[^"]+\.js)"', page).group(1); css = re.search(r'href="(/monitor-ui/assets/[^"]+\.css)"', page).group(1)
    for path, ctype in ((js, "application/javascript"), (css, "text/css"), ("/monitor-ui/favicon.svg", "image/svg+xml"), ("/monitor-ui/mock/monitor.json", "application/json"), ("/monitor-ui/index.html", "text/html")):
        st, hdr, body = raw_get(w, path); assert st == 200 and hdr["Content-Type"].startswith(ctype) and body and hdr["Cache-Control"] == "no-cache", (path, st, hdr.get("Content-Type"))
    assert raw_get(w, "/monitor-ui/assets/nope.js")[0] == 404 and raw_get(w, "/monitor-ui/")[0] == 404 and raw_get(w, "/monitor-ui/assets")[0] == 404


@pytest.mark.parametrize("path", ["/monitor-ui/../server.py", "/monitor-ui/..%2fserver.py", "/monitor-ui/%2e%2e/server.py", "/monitor-ui/assets/../../server.py",
                                  "/monitor-ui/assets/..%2f..%2fsettings.txt", "/monitor-ui/..%5cserver.py", "/monitor-ui/%00", "/monitor-ui//server.py", "/monitor-ui/mock/../../template.html"])
def test_static_route_cannot_leave_the_folder(pkg, servers, path):
    with_ui(pkg); w = servers(pkg)
    st, hdr, body = raw_get(w, path)
    assert st in (404, 400) and b"class H" not in body and b"CONFIG" not in body, (path, st)


def test_ui_files_open_only_from_the_server_computer(pkg, servers):
    ip = lan_ip()
    if not ip: pytest.skip("ما في IP شبكة")
    with_ui(pkg); w = servers(pkg)
    for path in ("/monitor", "/admin", "/monitor-old", "/monitor-ui/index.html", "/monitor-ui/assets/x.js", "/monitor-ui/mock/monitor.json"):
        assert raw_get(w, path, host=ip)[0] == 403, path


def test_old_page_stays_available_and_is_the_fallback(pkg, servers):
    w = servers(pkg)                                                                           # بدون monitor_ui: /monitor = القديمة
    old = raw_get(w, "/monitor")[2].decode("utf-8")
    assert "id=cards" in old and raw_get(w, "/monitor-old")[2].decode("utf-8") == old and raw_get(w, "/monitor-ui/index.html")[0] == 404
    with_ui(pkg)                                                                               # وبعد ما ينحط المجلد: /monitor جديدة، و/monitor-old لسا القديمة
    new = raw_get(w, "/monitor")[2].decode("utf-8")
    assert 'id="root"' in new and "id=cards" not in new and raw_get(w, "/monitor-old")[2].decode("utf-8") == old


# ============================ الواجهة بمتصفح حقيقي ضد السيرفر الحقيقي ============================
class Lab:
    """امتحان وهمي بـ 12 طالب: 4 سلّموا، 3 يمتحنون (نبضات حية)، واحد انقطع اتصاله، والباقي لم يبدأ"""
    def __init__(self, pkg, servers):
        with_ui(pkg); self.pkg = pkg
        pkg.students([["العاشر", "أ", n, ""] for n in A] + [["العاشر", "ب", n, ""] for n in B]); pkg.questions(bank()); pkg.settings()
        self.w = servers(pkg); self.dev = {n: f"d{i}" for i, n in enumerate(A + B)}; self.papers = {}
        for n in ("طالب أ1", "طالب أ2", "طالب أ3", "طالب ب1"):
            k = self.start(n); time.sleep(1.1); assert self.w.submit(k, self.dev[n], self.papers[n]["ids"], self.w.correct_answers(self.papers[n]["ids"]))[0] == 200
        self.live = {"طالب أ4": 4, "طالب أ5": 7, "طالب ب2": 2}
        for n in list(self.live) + ["طالب أ6"]: self.start(n)                                 # أ6 بدأ ولا يبعت نبضات => «انقطع الاتصال»
        self.remain = {n: self.papers[n]["remain"] for n in self.live}; self.stop = threading.Event()
        threading.Thread(target=self.pinger, daemon=True).start(); time.sleep(1.5)

    def sec(self, n): return "أ" if n in A else "ب"
    def key(self, n): return self.w.key(n=n, s=self.sec(n))
    def start(self, n):
        k, st, j = self.w.start_student(self.dev[n], n=n, s=self.sec(n)); assert st == 200 and j["status"] == "ok", (n, st, j); self.papers[n] = j; return k
    def ping(self, n, **extra):
        body = {"key": self.key(n), "dev": self.dev[n], "answered": self.live.get(n, 0), "total": 8, "remain": self.remain.get(n, 0), "ans": {}}; body.update(extra)
        return self.w.post("/ping", body)[1]
    def pinger(self):
        while not self.stop.is_set():
            for n in self.live:
                try:
                    j = self.ping(n, leaveN=2 if n == "طالب ب2" else 0, leaveSec=40 if n == "طالب ب2" else 0)
                    if isinstance(j, dict) and "remain" in j: self.remain[n] = j["remain"]
                except Exception: pass
            self.stop.wait(3)
    def mon(self):
        try: return self.w.get("/monitor.json")[1]
        except Exception: return {"sections": {}, "c": {}}
    def row(self, n):
        for rows in self.mon()["sections"].values():
            for r in rows:
                if r["name"] == n: return r


def wait_for(cond, secs=10, what=""):
    t = time.time()
    while time.time() - t < secs:
        if cond(): return
        time.sleep(0.3)
    raise AssertionError("timeout: " + what)


class Ui:
    def __init__(self, browser, w):
        self.ctx = browser.new_context(viewport={"width": 1366, "height": 768}, locale="ar-JO"); self.pg = self.ctx.new_page(); self.pg.set_default_timeout(8000)
        self.errors = []; self.posts = []
        self.pg.on("pageerror", lambda e: self.errors.append(str(e)))
        self.pg.on("request", lambda r: r.method == "POST" and r.url.endswith("/monitor") and self.posts.append((r.headers.get("x-exam-action"), json.loads(r.post_data or "{}"))))
        self.pg.goto(url(w) + "monitor"); self.pg.wait_for_selector(".kpi"); self.pg.wait_for_timeout(1200)
    modal = property(lambda self: self.pg.locator("section.modal"))
    def row(self, n): return self.pg.locator("tbody tr", has_text=n)
    def kebab(self, n, item):
        self.row(n).locator("button.kebab").click(); self.pg.locator(".row-popup").get_by_text(item, exact=True).click()
    def text(self): return self.pg.locator("main").inner_text()
    def close(self): self.ctx.close()


def test_new_ui_shows_the_real_exam_and_every_teacher_command_works(pkg, servers, browser):
    lab = Lab(pkg, servers); ui = Ui(browser, lab.w); pg = ui.pg
    try:
        # 1) عدادات الواجهة = عدادات السيرفر، وعدد الصفوف = عدد الطلاب
        c = lab.mon()["c"]; nums = [int(t.split()[0]) for t in pg.locator(".kpi").all_inner_texts()]
        assert nums == [c["done"], c["live"], c["lost"], c["none"]] and pg.locator("tbody tr").count() == 12
        # 2) مدة الحل ظاهرة، ولوحة الانتباه فيها المنقطع واللي خرج من الصفحة
        assert "ث" in ui.row("طالب أ1").inner_text()
        att = pg.locator("section.attention").inner_text(); assert "طالب أ6" in att and "طالب ب2" in att, att
        # 3) تحديث تلقائي: تسليم عبر API بيظهر بالواجهة
        k, st, j = lab.w.start_student("d99", n="طالب أ7", s="أ"); lab.w.submit(k, "d99", j["ids"], lab.w.correct_answers(j["ids"]))
        wait_for(lambda: "سلّم" in ui.row("طالب أ7").inner_text(), 8, "row أ7 done")
        # 4) تمديد وقت لطالب: الأمر والترويسة، والوقت زاد فعلاً
        before = lab.ping("طالب أ4")["remain"]; n0 = len(ui.posts)
        ui.row("طالب أ4").get_by_role("button", name="+ وقت").click(); ui.modal.locator("input").fill("7"); ui.modal.get_by_role("button", name="تأكيد").click(); pg.wait_for_timeout(900)
        hdr, body = ui.posts[n0]; assert hdr == "1" and body == {"extend": 7, "scope": "student", "key": lab.key("طالب أ4")}, body
        assert lab.ping("طالب أ4")["remain"] - before >= 400
        # 5) تمديد الشعبة وتمديد الجميع
        n0 = len(ui.posts)
        pg.locator("details.section-card").first.get_by_text("تمديد الشعبة").click(); ui.modal.locator("input").fill("2"); ui.modal.get_by_role("button", name="تأكيد").click(); pg.wait_for_timeout(700)
        pg.get_by_text("تمديد الوقت للجميع").first.click(); ui.modal.locator("input").fill("3"); ui.modal.get_by_role("button", name="تأكيد").click(); pg.wait_for_timeout(700)
        b1, b2 = ui.posts[n0][1], ui.posts[n0 + 1][1]
        assert b1["scope"] == "section" and b1["grade"] == "العاشر" and b1["section"] == "أ" and b1["extend"] == 2, b1
        assert b2 == {"extend": 3, "scope": "all"}, b2
        # 6) رسالة للطلاب
        pg.get_by_text("رسالة للطلاب").first.click(); ui.modal.locator("textarea").fill("رسالة تجريبية"); ui.modal.get_by_role("button", name="تأكيد").click(); pg.wait_for_timeout(900)
        assert lab.mon()["msg"] == "رسالة تجريبية" and "رسالة تجريبية" in ui.text()
        # 7) النقل لجهاز آخر للمنقطع (من لوحة الانتباه)
        pg.locator("section.attention").locator("div", has_text="طالب أ6").locator("button", has_text="نقل لجهاز آخر").first.click()
        expect(ui.modal).to_be_visible(); ui.modal.get_by_role("button", name="نقل الطالب").click(); pg.wait_for_timeout(900)
        assert lab.row("طالب أ6")["status"] == "none"
        # 8) تسليم عن طالب بيمتحن
        ui.kebab("طالب أ5", "تسليم عنه"); ui.modal.get_by_role("button", name="تسليم الآن").click(); pg.wait_for_timeout(1000)
        assert lab.row("طالب أ5")["status"] == "done"
        # 9) فك الحجز
        ui.kebab("طالب ب2", "فك الحجز"); ui.modal.get_by_role("button", name="فك الحجز").click(); pg.wait_for_timeout(1000)
        assert lab.row("طالب ب2")["status"] == "none"
        # 10) الفلاتر والبحث (أ/إ/ا متساوية)
        pg.locator(".kpi").first.click(); pg.wait_for_timeout(300); assert pg.locator("tbody tr").count() == lab.mon()["c"]["done"]; pg.locator(".kpi").first.click(); pg.wait_for_timeout(300)
        box = pg.get_by_placeholder("ابحث عن اسم طالب..."); box.fill("ب3"); pg.wait_for_timeout(300); assert pg.locator("tbody tr").count() == 1; box.fill("")
        # 11) شاشة كبيرة: بلاطة لكل طالب
        pg.get_by_text("شاشة كبيرة").first.click(); pg.wait_for_timeout(600); assert pg.locator(".projector-tile").count() == 12
        pg.get_by_text("رجوع للوضع العادي").click(); pg.wait_for_selector(".kpi")
        # 12) إنهاء الامتحان للجميع ثم إعادة فتحه
        pg.get_by_role("button", name="■ إنهاء الامتحان للجميع").click(); ui.modal.get_by_role("button", name="إنهاء الامتحان").click(); pg.wait_for_timeout(1200)
        assert lab.mon()["closed"] is True and "الامتحان منتهٍ" in ui.text()
        pg.locator(".notice.danger", has_text="الامتحان منتهٍ").get_by_role("button").first.click(); ui.modal.get_by_role("button").last.click(); pg.wait_for_timeout(1200)
        assert lab.mon()["closed"] is False and "الامتحان منتهٍ" not in ui.text()
        # 13) تسليم من لم يسلّم
        pg.get_by_text("تسليم من لم يسلّم").first.click(); ui.modal.get_by_role("button", name="تسليم الآن").click(); pg.wait_for_timeout(1200)
        c = lab.mon()["c"]; assert c["live"] == 0 and c["lost"] == 0, c
        assert all(h == "1" for h, _ in ui.posts) and len(ui.posts) >= 9                       # كل الأوامر مرّت بترويسة X-Exam-Action
        assert not ui.errors, ui.errors
    finally:
        lab.stop.set(); ui.close()


def test_rehearsal_panel_opens_from_the_tools_menu_and_shows_server_errors(pkg, servers, browser):
    lab = Lab(pkg, servers); ui = Ui(browser, lab.w); pg = ui.pg
    try:
        pg.get_by_role("button", name="أدوات ▾").click(); pg.get_by_role("button", name="🧪 بروفة الضغط").click(); pg.wait_for_timeout(700)
        assert pg.evaluate("document.querySelector('details.rehearsal').open") is True         # كانت بس تنزّل للوحة وهي مطويّة
        pg.get_by_role("button", name="تفعيل البروفة (30 دقيقة)").click(); pg.wait_for_timeout(900)
        t = pg.locator(".toast").inner_text(); assert "بدأوا" in t or "بداية امتحان جديد" in t, t   # خطأ السيرفر بالعربي بيطلع كتوست
    finally:
        lab.stop.set(); ui.close()


def test_new_exam_button_runs_both_confirmations_and_archives(pkg, servers, browser):
    lab = Lab(pkg, servers); ui = Ui(browser, lab.w); pg = ui.pg
    try:
        n0 = len(ui.posts); pg.get_by_role("button", name="↻ بداية امتحان جديد").click(); expect(ui.modal).to_be_visible()
        ui.modal.get_by_role("button", name="متابعة").click(); expect(ui.modal).to_contain_text("تأكيد أخير")
        assert not any(b.get("newexam") for _, b in ui.posts[n0:])                              # لسا ما انبعت شي قبل التأكيد الأخير
        ui.modal.get_by_role("button", name="تصفير الامتحان").click(); pg.wait_for_timeout(1500)   # كانت تفتح نفسها للأبد وما بتنفّذ
        assert [b for _, b in ui.posts[n0:] if b.get("newexam")] == [{"newexam": 1}]
        assert any(d.startswith("archive_") for d in os.listdir(pkg.path))
        c = lab.mon()["c"]; assert c["done"] == c["live"] == c["lost"] == 0 and c["none"] == 12, c
        expect(ui.modal).to_have_count(0)
    finally:
        lab.stop.set(); ui.close()


def test_server_down_notices_and_question_file_changed_alert(pkg, servers, browser):
    lab = Lab(pkg, servers); ui = Ui(browser, lab.w); pg = ui.pg; port = lab.w.port
    try:
        lab.start("طالب ب3"); lab.ping("طالب ب3", answered=1, remain=1500)                      # طالب يمتحن لما ينقطع السيرفر (بيتعوّض وقته)
        time.sleep(4.2)                                                                        # لازم تمر نبضة حياة
        lab.w.proc.kill(); lab.w.proc.wait()
        wait_for(lambda: pg.locator(".notice.danger[role=alert]").count() > 0, 16, "offline banner")
        assert "انقطع الاتصال بالسيرفر" in pg.locator(".notice.danger[role=alert]").inner_text()
        rows = [list(r) for r in bank()]; rows[0][0] += " (معدّل)"; pkg.questions(rows)           # المشرف بدّل سؤال والسيرفر واقف
        time.sleep(5)
        lab.w = servers(pkg, port=port)
        wait_for(lambda: pg.locator(".notice.danger[role=alert]").count() == 0, 14, "banner gone")
        wait_for(lambda: lab.mon().get("comp") and lab.mon().get("bank_changed"), 6, "comp + bank_changed")
        pg.wait_for_timeout(4500); txt = ui.text()
        assert "السيرفر كان متوقفاً" in txt and "ملف الأسئلة تغيّر" in txt
        assert pg.get_by_role("button", name="هذا نفس الامتحان").count() == 1 and pg.locator(".notice", has_text="ملف الأسئلة").get_by_role("button", name="بداية امتحان جديد").count() >= 1
        n0 = len(ui.posts); pg.get_by_role("button", name="هذا نفس الامتحان").click(); ui.modal.get_by_role("button").last.click(); pg.wait_for_timeout(1500)
        assert ui.posts[n0][1] == {"bankok": 1} and lab.mon()["bank_changed"] is None and "ملف الأسئلة تغيّر" not in ui.text()
    finally:
        lab.stop.set(); ui.close()
