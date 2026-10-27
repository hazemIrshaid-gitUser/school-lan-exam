"""صفحة «إعدادات الامتحان»: بتقرأ وبتكتب نفس settings.txt (الملف هو المصدر) بدون ما يضيع شي: التعليقات بتضل، ونسخة احتياطية قبل كل حفظ،
والأعمدة والقيم مقروءة من ملف الأسئلة نفسه (مش ثابتة بالكود)، وبعد ما يبدأ أول طالب بتنقفل الإعدادات اللي بتأثر على الأوراق."""
import json, re

import pytest
from conftest import Q_HEAD, LETTERS, bank, q
from test_http import Server, TEACHER, lan_ip

pw = pytest.importorskip("playwright.sync_api")
from test_browser import browser, url  # noqa: F401  (fixture)

HEAD = Q_HEAD + ["الوحدة"]
RULES = ["الوحدة:وحدة 1 | المستوى:سهل | العدد:2", "الوحدة:وحدة 2 | المستوى:سهل | العدد:1"]


def unit_bank(spec):
    """spec: قائمة (وحدة، مستوى، عدد)"""
    rows, i = [], 0
    for unit, lvl, n in spec:
        for _ in range(n):
            rows.append(q(f"س{i}", (f"{i}-أ", f"{i}-ب", f"{i}-ج", f"{i}-د"), LETTERS[i % 4], lvl) + [unit]); i += 1
    return rows


UB = [("وحدة 1", "سهل", 4), ("وحدة 1", "وسط", 3), ("وحدة 2", "سهل", 3), ("وحدة 2", "وسط", 2), ("وحدة 3", "صعب", 2)]
FILE = ("# ملاحظة: هذا التعليق لازم يضل\nعنوان_الامتحان = اختبار الوحدة\nالمدة_بالدقائق = 30\n# سطر ثاني للتعليق\nكلمة_سر_المعلم = secret\nخلط_الأسئلة = نعم\n")


@pytest.fixture
def web(pkg):
    pkg.questions(unit_bank(UB), head=HEAD); pkg.raw_settings(FILE)
    s = Server(pkg).start()
    yield s
    s.stop()


def cookie(w): return {"Cookie": w.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0]}


class Api:
    def __init__(self, w, ck=None): self.w, self.ck = w, (ck if ck is not None else cookie(w))

    def state(self):
        st, j, _, _ = self.w.get("/settings.json", self.ck); assert st == 200; return j

    def save(self, values=None, rules=None, **extra):
        body = {"values": values or {}, "rules": rules or []}; body.update(extra)
        st, j, _, _ = self.w.post("/settings", body, {**TEACHER, **self.ck}); return st, j

    def field(self, key): return next(f for f in self.state()["fields"] if f["key"] == key)


def text(pkg): return pkg.p("settings.txt").read_text(encoding="utf-8")


# ============================ الوصول ============================
def test_page_needs_the_teacher_login_and_has_its_tab(web):
    assert web.get("/settings")[0] == 302 and web.get("/settings.json")[0] == 302
    ck = cookie(web); st, _, raw, _ = web.get("/settings", ck); h = raw.decode("utf-8")
    assert st == 200 and "إعدادات الامتحان" in h and "<a href=/settings class=on aria-current=page>" in h


def test_post_needs_teacher_header_and_login(web):
    body = {"values": {"المدة_بالدقائق": "50"}, "rules": []}
    assert web.post("/settings", body)[0] == 403                                       # بدون ترويسة المعلم
    assert web.post("/settings", body, TEACHER)[0] == 403                              # ما سجّل دخول (في كلمة سر)


@pytest.mark.skipif(lan_ip() is None, reason="ما في عنوان شبكة محلية: ما بنقدر نحاكي جهاز طالب")
def test_page_and_save_are_not_reachable_from_the_network(pkg):
    pkg.questions(unit_bank(UB), head=HEAD); pkg.settings(**{"كلمة_سر_المعلم": ""}); w = Server(pkg).start(); ip = lan_ip()
    try:
        assert w.get("/settings", host=ip)[0] == 403 and w.get("/settings.json", host=ip)[0] == 403
        assert w.post("/settings", {"values": {"المدة_بالدقائق": "5"}, "rules": []}, TEACHER, host=ip)[0] == 403
        assert w.get("/settings")[0] == 200 and "المدة_بالدقائق = 5" not in text(pkg)
    finally:
        w.stop()


# ============================ تغطية كل الإعدادات ============================
def test_every_setting_of_the_file_is_on_the_page_and_nothing_else(pkg):
    src = (pkg.path / "server.py").read_text(encoding="utf-8")
    block = src[src.index("    keys = {"): src.index("    REVIEW = {")]
    file_keys = set(re.findall(r'"([^"]+)": "[A-Za-z]+"', block))
    m = pkg.load()
    assert file_keys == {fk for _, fk, *_ in m.SPEC} and len(file_keys) == 16, file_keys ^ {fk for _, fk, *_ in m.SPEC}


def test_state_has_every_field_with_the_current_values(web):
    f = {x["key"]: x for x in Api(web).state()["fields"]}
    assert f["المدة_بالدقائق"]["value"] == "30" and f["كلمة_سر_المعلم"]["value"] == "secret" and f["خلط_الأسئلة"]["value"] == "نعم"
    assert f["عنوان_الامتحان"]["value"] == "اختبار الوحدة" and f["مراجعة_الأخطاء"]["value"] == "لا"
    assert f["العلامة_النهائية"]["value"] == "" and f["عدد_الأسئلة_الصعبة"]["value"] == ""            # مش مكتوبة بالملف = فاضية


# ============================ ديناميكي من ملف الأسئلة ============================
def test_columns_values_and_counts_come_from_the_questions_file(web):
    s = Api(web).state()
    assert s["columns"][:2] == ["الوحدة", "المستوى"] and "السؤال" not in s["columns"] and "الجواب" not in s["columns"]
    assert s["values"]["الوحدة"] == [["وحدة 1", 7], ["وحدة 2", 5], ["وحدة 3", 2]]                    # 3 وحدات: ما في شي ثابت بالكود
    assert s["values"]["المستوى"] == [["سهل", 7], ["وسط", 5], ["صعب", 2]]
    assert s["cross"]["الوحدة||المستوى"]["وحدة 1||سهل"] == 4 and s["cross"]["المستوى||الوحدة"]["صعب||وحدة 3"] == 2


def test_a_new_column_shows_up_without_any_code_change(pkg):
    rows = [r + ["ف1" if i % 2 else "ف2"] for i, r in enumerate(unit_bank(UB))]
    pkg.questions(rows, head=HEAD + ["الفصل"]); pkg.raw_settings(FILE); w = Server(pkg).start()
    try:
        s = Api(w).state(); assert "الفصل" in s["columns"] and sorted(v for v, _ in s["values"]["الفصل"]) == ["ف1", "ف2"]
    finally:
        w.stop()


def test_a_file_without_unit_column_still_lists_the_level_column(pkg):
    pkg.questions(bank(3, 4, 4)); pkg.raw_settings(FILE); w = Server(pkg).start()
    try:
        s = Api(w).state(); assert s["columns"] == ["المستوى"] and s["values"]["المستوى"] == [["سهل", 4], ["وسط", 4], ["صعب", 3]]
    finally:
        w.stop()


# ============================ الحفظ ============================
def test_saving_edits_the_file_in_place_keeps_comments_and_makes_a_backup(web, pkg):
    old = text(pkg); a = Api(web)
    st, j = a.save({"المدة_بالدقائق": "45", "عنوان_الامتحان": "اختبار الوحدة"}, RULES)
    assert st == 200 and j["ok"] and j["picked"] == 3
    new = text(pkg)
    assert "# ملاحظة: هذا التعليق لازم يضل" in new and "# سطر ثاني للتعليق" in new and "المدة_بالدقائق = 45" in new
    assert new.count("سحب = ") == 2 and "سحب = الوحدة:وحدة 1 | المستوى:سهل | العدد:2" in new
    assert "كلمة_سر_المعلم = secret" in new and "المدة_بالدقائق = 30" not in new
    bk = sorted((pkg.path / "نسخ_الإعدادات").glob("settings_*.txt")); assert len(bk) == 1 and bk[0].read_text(encoding="utf-8") == old
    assert web.get("/health.json", a.ck)[1]["exam"]["minutes"] == 45 and web.get("/health.json", a.ck)[1]["exam"]["per_student"] == 3     # طُبّق فوراً بدون إعادة تشغيل


def test_unchanged_defaults_are_not_added_to_the_file(web, pkg):
    a = Api(web); vals = {f["key"]: f["value"] for f in a.state()["fields"]}
    before = text(pkg); st, j = a.save(vals, []); assert st == 200, j
    after = text(pkg)
    assert after.count("=") == before.count("=") and "العلامة_النهائية" not in after and "علامة_السؤال" not in after and "عدد_الأسئلة" not in after


def test_rules_round_trip_through_the_state(web):
    a = Api(web); assert a.save({}, RULES)[0] == 200
    r = a.state()["rules"]
    assert [x["text"] for x in r] == RULES and r[0]["conds"] == [["الوحدة", ":", ["وحدة 1"]], ["المستوى", ":", ["سهل"]]] and r[0]["n"] == 2


def test_rules_replace_each_other_without_duplicating_lines(web, pkg):
    a = Api(web); a.save({}, RULES); a.save({}, RULES[:1]); a.save({}, RULES[:1])
    assert text(pkg).count("سحب = ") == 1
    assert a.save({}, [])[0] == 200 and "سحب =" not in text(pkg)


def test_switching_from_level_counts_to_rules_clears_the_old_counts(web, pkg):
    a = Api(web); assert a.save({"عدد_الأسئلة_الصعبة": "1", "عدد_الأسئلة_المتوسطة": "2", "عدد_الأسئلة_السهلة": "3"}, [])[0] == 200
    assert "عدد_الأسئلة_السهلة = 3" in text(pkg)
    assert a.save({"عدد_الأسئلة_الصعبة": "", "عدد_الأسئلة_المتوسطة": "", "عدد_الأسئلة_السهلة": ""}, RULES)[0] == 200
    assert a.field("عدد_الأسئلة_السهلة")["value"] == "" and a.state()["picked"] == 3


def test_invalid_value_is_rejected_and_nothing_changes(web, pkg):
    before = text(pkg); a = Api(web)
    st, j = a.save({"المدة_بالدقائق": "abc"}, []); assert st == 400 and "رقم" in j["error"]
    assert text(pkg) == before and not (pkg.path / "نسخ_الإعدادات").exists()
    assert web.get("/health.json", a.ck)[1]["exam"]["minutes"] == 30


def test_asking_for_more_than_available_is_rejected_and_nothing_changes(web, pkg):
    before = text(pkg); a = Api(web); per = a.state()["picked"]
    st, j = a.save({"المدة_بالدقائق": "99"}, ["الوحدة:وحدة 3 | المستوى:صعب | العدد:9"])
    assert st == 400 and "مطلوب 9 والموجود 2" in j["error"] and text(pkg) == before
    h = web.get("/health.json", a.ck)[1]["exam"]; assert h["minutes"] == 30 and h["per_student"] == per


def test_bad_rule_syntax_and_unknown_column_are_rejected(web, pkg):
    before = text(pkg); a = Api(web)
    assert "بدون «العدد»" in a.save({}, ["الوحدة:وحدة 1"])[1]["error"]
    assert "ما في عمود اسمه «الفصل»" in a.save({}, ["الفصل:ف1 | العدد:1"])[1]["error"]
    assert text(pkg) == before


def test_unknown_setting_and_newlines_are_rejected(web, pkg):
    before = text(pkg); a = Api(web)
    assert a.save({"إعداد_وهمي": "1"})[0] == 400
    assert a.save({"عنوان_الامتحان": "سطر\nسحب = المستوى:سهل | العدد:1"})[0] == 400
    assert text(pkg) == before


def test_written_file_loads_the_same_way_after_a_restart(web, pkg):
    a = Api(web); assert a.save({"المدة_بالدقائق": "41", "علامة_السؤال": "2"}, RULES)[0] == 200
    web.stop(); w2 = Server(pkg).start()
    try:
        h = w2.get("/health.json", cookie(w2))[1]["exam"]; assert h["minutes"] == 41 and h["per_student"] == 3
    finally:
        w2.stop()


# ============================ بعد ما يبدأ الامتحان ============================
def test_started_exam_locks_everything_that_changes_papers_but_not_the_free_ones(web, pkg):
    a = Api(web); assert a.save({}, RULES)[0] == 200
    web.start_student("d1")                                                                  # أول طالب بدأ
    assert a.state()["started"] is True
    before = text(pkg)
    for vals, rules, label in (({"المدة_بالدقائق": "99"}, RULES, "المدة"), ({"عنوان_الامتحان": "عنوان جديد"}, RULES, "عنوان"), ({"خلط_الأسئلة": "لا"}, RULES, "خلط"),
                               ({}, RULES[:1], "قواعد"), ({"العلامة_النهائية": "10"}, RULES, "العلامة")):
        st, j = a.save(vals, rules); assert st == 400 and "مقفلة" in j["error"], (label, j)
    assert text(pkg) == before
    st, j = a.save({"كلمة_سر_المعلم": "new1", "إظهار_العلامة_للطالب": "لا", "مراجعة_الأخطاء": "بعد_الإنهاء"}, RULES)
    assert st == 200, j
    assert "كلمة_سر_المعلم = new1" in text(pkg) and "مراجعة_الأخطاء = بعد_الإنهاء" in text(pkg)
    assert web.post("/login", {"password": "new1"}, TEACHER)[1]["ok"] is True                # كلمة السر الجديدة اشتغلت فوراً


def test_reset_is_blocked_after_start_and_a_new_exam_unlocks_it(web, pkg):
    a = Api(web); a.save({}, RULES); web.start_student("d1")
    assert a.save(reset=True)[0] == 400 and a.save({"المدة_بالدقائق": "55"}, RULES)[0] == 400
    assert web.teacher(newexam=True)[0] == 200 and a.state()["started"] is False
    assert a.save({"المدة_بالدقائق": "55"}, RULES)[0] == 200 and "المدة_بالدقائق = 55" in text(pkg)


def test_reset_keeps_the_password_and_the_comments(web, pkg):
    a = Api(web); a.save({"المدة_بالدقائق": "45"}, RULES)
    st, j = a.save(reset=True); assert st == 200, j
    t = text(pkg)
    assert "كلمة_سر_المعلم = secret" in t and "# ملاحظة: هذا التعليق لازم يضل" in t
    assert "المدة_بالدقائق" not in t and "عنوان_الامتحان" not in t and "سحب =" not in t and "خلط_الأسئلة" not in t
    f = {x["key"]: x for x in a.state()["fields"]}; assert f["المدة_بالدقائق"]["value"] == "30" and f["عنوان_الامتحان"]["value"] == ""
    assert len(list((pkg.path / "نسخ_الإعدادات").glob("settings_*.txt"))) == 2                # نسخة قبل كل عملية


def test_backups_are_capped_at_fifty(web, pkg):
    a = Api(web); d = pkg.path / "نسخ_الإعدادات"; d.mkdir()
    for i in range(55): (d / f"settings_20200101_{i:06d}.txt").write_text("x", encoding="utf-8")
    assert a.save({"المدة_بالدقائق": "33"}, [])[0] == 200
    assert len(list(d.glob("settings_*.txt"))) == 50 and not (d / "settings_20200101_000000.txt").exists()


def test_missing_settings_file_is_created_by_the_first_save(pkg):
    pkg.questions(unit_bank(UB), head=HEAD); pkg.p("settings.txt").unlink(); pkg.p("exam_error.txt").unlink(missing_ok=True)
    w = Server(pkg).start()
    try:
        a = Api(w, {}); st, j, _, _ = w.post("/settings", {"values": {"المدة_بالدقائق": "25", "كلمة_سر_المعلم": "k"}, "rules": []}, TEACHER)
        assert st == 200 and j["ok"] and "المدة_بالدقائق = 25" in text(pkg)
    finally:
        w.stop()


# ============================ الواجهة بالمتصفح ============================
def test_page_ui_draws_unit_cards_and_saves(web, pkg, browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ar-JO"); pg = ctx.new_page()
    try:
        ck = web.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0].split("=", 1)
        ctx.add_cookies([{"name": ck[0], "value": ck[1], "url": url(web)}])
        pg.goto(url(web) + "settings"); pg.wait_for_selector("#dist")
        pg.click("input[name=md][value=grid]"); pg.wait_for_selector(".unit")
        assert pg.locator(".unit").count() == 3                                              # 3 وحدات = 3 بطاقات (من الملف)
        assert "المتاح 7" in pg.inner_text(".unit >> nth=0")
        pg.fill('[data-g="وحدة 1||سهل"]', "2"); pg.fill('[data-g="وحدة 2||سهل"]', "1")
        assert pg.inner_text("#k1") == "3"
        pg.fill('[data-g="وحدة 3||صعب"]', "9"); assert "over" in pg.get_attribute('[data-g="وحدة 3||صعب"]', "class")        # أكثر من المتاح: أحمر
        pg.click("#save"); assert "أكبر من المتاح" in pg.inner_text("#msg")
        pg.fill('[data-g="وحدة 3||صعب"]', "0"); pg.fill('[data-fk="المدة_بالدقائق"]', "44"); pg.click("#save")
        pg.wait_for_function("document.getElementById('msg').innerText.includes('تم الحفظ')")
        t = text(pkg); assert "المدة_بالدقائق = 44" in t and "سحب = الوحدة:وحدة 1 | المستوى:سهل | العدد:2" in t and "9" not in t.split("سحب")[-1]
        assert pg.locator('[data-g="وحدة 1||سهل"]').input_value() == "2"                     # أعاد التحميل من الملف
    finally:
        ctx.close()


def test_page_ui_is_locked_after_start(web, pkg, browser):
    web.start_student("d1")
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, locale="ar-JO"); pg = ctx.new_page()
    try:
        ck = web.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0].split("=", 1)
        ctx.add_cookies([{"name": ck[0], "value": ck[1], "url": url(web)}])
        pg.goto(url(web) + "settings"); pg.wait_for_selector(".wbox")
        assert pg.is_disabled('[data-fk="المدة_بالدقائق"]') and not pg.is_disabled('[data-fk="كلمة_سر_المعلم"]') and pg.is_disabled("#reset")
        assert "بدأ الامتحان" in pg.inner_text(".wbox >> nth=0")
    finally:
        ctx.close()
