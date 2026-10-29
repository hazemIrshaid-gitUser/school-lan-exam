"""تقسيم server.py لطبقات (المرحلة 1): مجلد exam_core فيه وحدات بدون حالة (constants و util و files)، و server.py بيستوردها من جنبه ويعيد تصدير أسماءها
(فالاختبارات والأدوات اللي بتقول m.num أو m.read_table بتضل شغالة). وهالوحدات ما بتعتمد على مجلد الامتحان ولا على server.py، ومتطابقة بين 1_ و2_."""
import ast, importlib, subprocess, sys
from conftest import PKG_SRC, bank

CORE = PKG_SRC / "exam_core"
UPDATE = next(PKG_SRC.parent.glob("2_*"), None)


def mods(): return sorted(p for p in CORE.glob("*.py") if p.name != "__init__.py")


def test_core_modules_exist():
    assert {p.stem for p in mods()} >= {"constants", "util", "files", "settings", "text"}


def test_core_never_imports_server_or_depends_on_the_exam_folder():
    for p in [*mods(), CORE / "__init__.py"]:
        src = p.read_text(encoding="utf-8"); t = ast.parse(src)
        for n in ast.walk(t):
            if isinstance(n, ast.Import): assert not any(a.name.split(".")[0] in ("server", "check_files") for a in n.names), p.name
            if isinstance(n, ast.ImportFrom): assert (n.module or "").split(".")[0] not in ("server", "check_files"), p.name
        names = {n.id for n in ast.walk(t) if isinstance(n, ast.Name)}
        assert not names & {"BASE", "SET", "PAPERS", "CLAIMS", "STATE", "QLIST", "BANK", "PICK"}, (p.name, names & {"BASE", "SET", "PAPERS"})     # بدون حالة ولا مسارات


def test_core_has_no_module_level_side_effects(tmp_path):
    """استيراد الوحدات بمجلد فاضي ما بيكتب ولا بيقرأ ملفات الامتحان"""
    code = ("import sys, os; sys.path.insert(0, sys.argv[1]); import exam_core.constants, exam_core.util, exam_core.files, exam_core.settings, exam_core.text; "
            "print(sorted(os.listdir('.')))")
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code, str(PKG_SRC)], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0 and r.stdout.strip() == "[]", r.stderr + r.stdout


def test_server_reexports_the_moved_names_as_the_same_objects(srv):
    from exam_core import constants, files, util
    for name in ("L", "LVL", "HEAD", "MAX_BODY", "GRACE", "YES", "NO", "LVL_IN", "LET_IN"): assert getattr(srv, name) is getattr(constants, name), name
    for name in ("mtxt", "E", "num", "load_json", "atomic_write", "DataError", "norm_pass", "norm_code", "grp"): assert getattr(srv, name) is getattr(util, name), name
    assert srv.read_table is files.read_table and srv.files is files
    from exam_core import settings as cs, text as ct
    for name in ("default_cfg", "parse_settings", "decode_settings", "norm_hdr", "parse_rule", "rule_match", "REVIEW_OUT", "SPEC", "SPEC_BY_KEY", "COL_SKIP", "edit_settings_text"): assert getattr(srv, name) is getattr(cs, name), name
    for name in ("autoltr", "fracs", "bdir", "noimg", "FRAC_CSS", "qhtml_text"): assert getattr(srv, name) is getattr(ct, name), name


def test_find_file_wrapper_uses_the_exam_folder(pkg):
    m = pkg.load(); assert m.find_file("questions") == str(pkg.p("questions.xlsx"))
    from exam_core import files
    assert files.find_file(str(pkg.path), "students") == str(pkg.p("students.xlsx"))
    try: files.find_file(str(pkg.path), "غير_موجود")
    except m.DataError as e: assert "غير موجود" in str(e)
    else: raise AssertionError("لازم يرمي DataError")


def test_update_folder_carries_the_same_core_byte_for_byte():
    assert UPDATE is not None
    a, b = sorted(p.name for p in CORE.glob("*.py")), sorted(p.name for p in (UPDATE / "exam_core").glob("*.py"))
    assert a == b, (a, b)
    for n in a: assert (CORE / n).read_bytes() == (UPDATE / "exam_core" / n).read_bytes(), n
    assert (PKG_SRC / "server.py").read_bytes() == (UPDATE / "server.py").read_bytes()


def test_server_imports_core_from_its_own_folder_even_from_another_cwd(pkg, tmp_path):
    """server.py بيشتغل من أي مجلد عمل: بيحط مجلده بأول مسار البحث"""
    code = ("import runpy, sys; sys.argv=['x']; "
            "import importlib.util as u; s=u.spec_from_file_location('exam_server_x', sys.argv[0] if False else r'%s'); m=u.module_from_spec(s); s.loader.exec_module(m); print(m.num(2.50), m.files.__name__)" % pkg.p("server.py"))
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0 and "2.5 exam_core.files" in r.stdout, r.stderr[-400:] + r.stdout


# ============================ الوحدتان الجديدتان (المرحلة 2) ============================
def test_parse_settings_works_without_the_exam_folder():
    from exam_core.settings import parse_settings
    cfg = parse_settings("المدة_بالدقائق = 40\nكلمة_سر_المعلم = k\nسحب = المستوى:سهل | العدد:3\n", lambda: "عنوان تلقائي")
    assert cfg["minutes"] == 40 and cfg["tpass"] == "k" and cfg["title"] == "عنوان تلقائي" and cfg["auto_title"] and cfg["given"] == {"minutes", "tpass"}
    assert cfg["rules"] == [{"conds": [("المستوى", ":", ["سهل"])], "n": 3, "ln": 3, "label": "المستوى = سهل"}]


def test_parse_settings_errors_are_the_same_data_errors():
    import pytest
    from exam_core.settings import parse_settings
    from exam_core.util import DataError
    for txt, needle in (("المدة_بالدقائق = abc", "رقم"), ("اسم_وهمي = 1", "غير معروف"), ("خلط_الأسئلة = ربما", "نعم أو لا"), ("سحب = المستوى:سهل", "بدون «العدد»")):
        with pytest.raises(DataError) as e: parse_settings(txt, lambda: "x")
        assert needle in str(e.value), (txt, str(e.value))


def test_qhtml_text_is_pure_and_the_server_wrapper_adds_the_images(srv):
    from exam_core.text import qhtml_text
    assert srv.qhtml("س <b>1</b>") == qhtml_text("س <b>1</b>")                       # بدون صور: نفس الناتج
    assert "x-fr" in qhtml_text("(x + 7)/(x² − 1)") and srv.qhtml("(x + 7)/(x² − 1)") == qhtml_text("(x + 7)/(x² − 1)")
    srv.IMG_LIST[:] = ["a.png"]; out = srv.qhtml(""); assert 'src="/img/a.png"' in out and "" not in out
    assert "" in qhtml_text("")                                          # النقي ما بيعرف الصور


# ============================ صندوق الحالة ctx وطبقة الأسئلة (المرحلة 3) ============================
STATE_NAMES = ("SET", "QLIST", "BANK", "PICK", "ROSTER", "IMG_LIST", "XCODES")


def test_server_names_are_the_same_objects_as_ctx(srv):
    for n in STATE_NAMES: assert getattr(srv, n) is getattr(srv.ctx, n), n
    assert srv.IMG_DIR == srv.ctx.IMG_DIR and srv.ctx.BASE == srv.BASE
    assert srv.PAGE == srv.ctx.PAGE and srv.PREVIEW == srv.ctx.PREVIEW and "const CONFIG" in srv.PAGE        # PAGE و PREVIEW بتنقرأ من ctx
    assert srv.ctx.print is (srv.__dict__.get("print") or print)                    # print تبع السيرفر (لو الكونسول ما بيعرض العربي فهو مبدّل) أو العادي


def test_no_state_name_is_ever_rebound_with_global():
    import re
    src = (PKG_SRC / "server.py").read_text(encoding="utf-8")
    assert not re.findall(r"^\s*global\s+[^\n]*\b(?:SET|QLIST|BANK|PAGE|PICK|PREVIEW|ROSTER|IMG_LIST|XCODES)\b", src, re.M)


def test_apply_settings_updates_the_state_in_place_and_restores_it_on_failure(pkg):
    import pytest
    m = pkg.load(); ids = {n: id(getattr(m, n)) for n in STATE_NAMES}; page0 = m.PAGE
    assert m.apply_settings({"values": {"المدة_بالدقائق": "44"}, "rules": []})["ok"]
    assert {n: id(getattr(m, n)) for n in STATE_NAMES} == ids                            # نفس الكائنات (محدّثة مكانها)
    assert m.SET["minutes"] == 44 and m.ctx.SET["minutes"] == 44 and "minutes: 44" in m.PAGE and m.PAGE != page0
    page1 = m.PAGE
    with pytest.raises(m.DataError): m.apply_settings({"values": {"عدد_الأسئلة_الصعبة": "99"}, "rules": []})       # أكثر من الموجود
    assert {n: id(getattr(m, n)) for n in STATE_NAMES} == ids
    assert m.SET["minutes"] == 44 and m.PAGE == page1 and len(m.BANK) == len(m.QLIST) and sum(m.PICK.values()) > 0       # رجعت زي ما كانت


def test_new_auto_title_updates_page_and_pick_in_place(pkg):
    pkg.p("settings.txt").unlink(); m = pkg.load(); ids = {n: id(getattr(m, n)) for n in STATE_NAMES}; old = m.SET["title"]
    import time; time.sleep(1.1); m.new_auto_title()
    assert m.SET["title"] != old and m.SET["title"] in m.PAGE and m.SET["title"] in m.PREVIEW and {n: id(getattr(m, n)) for n in STATE_NAMES} == ids


def test_two_server_instances_in_one_process_do_not_share_state(pkg, tmp_path_factory):
    import shutil
    from conftest import CODE_FILES, Pkg, copy_any
    d = tmp_path_factory.mktemp("second")
    for f in CODE_FILES: copy_any(PKG_SRC / f, d / f)
    pk2 = Pkg(d); pk2.questions(); pk2.students(); pk2.settings(**{"عنوان_الامتحان": "امتحان ثاني"})
    m1, m2 = pkg.load(), pk2.load()
    assert m1.ctx is not m2.ctx and m1.SET is not m2.SET and m1.BANK is not m2.BANK and m1.BASE != m2.BASE
    m1.SET["minutes"] = 77
    assert m2.SET["minutes"] != 77 and m2.SET["title"] == "امتحان ثاني" and m1.SET["title"] != "امتحان ثاني"


def test_questions_layer_works_from_an_explicit_ctx(pkg):
    from exam_core import questions
    from exam_core.ctx import Ctx
    m = pkg.load(); c = Ctx(str(pkg.path)); c.SET.update(m.SET)
    qs = questions.load_questions(c); ros = questions.load_roster(c)
    assert [q["q"] for q in qs] == [q["q"] for q in m.QLIST] and ros == m.ROSTER
    assert not m.XCODES and c.XCODES == {} and c.IMG_LIST == []                           # حالة الـctx الجديد منفصلة


def test_check_images_prints_through_the_ctx_print(pkg):
    from exam_core import questions
    from exam_core.ctx import Ctx
    pkg.image("fig.png"); rows = bank(); rows[0][0] += " [img:fig.png]"; pkg.questions(rows)
    m = pkg.load(); said = []; c = Ctx(str(pkg.path)); c.SET.update(m.SET); c.print = said.append
    questions.load_questions(c); questions.check_images(c)
    assert c.IMG_LIST == ["fig.png"] and any("صورة" in str(x) for x in said)


# ============================ منطق الامتحان domain وحاويات الحالة الجديدة (المرحلة 4) ============================
STATE_NAMES2 = ("PAPERS", "CLAIMS", "ANS", "LIVE", "SUBS", "CODES", "FAILS", "STATE", "ANS_DIRTY", "LAST_TICK")
DOMAIN = ("make_paper", "paused_for", "settle_pause", "deadline", "remain_of", "fmt_dur", "pub_q", "paper_reply", "clean_ans", "wrong_items", "wrong_text",
          "parse_key", "raw_range", "total_range", "eff_mark", "key_mark", "bank_fp", "check_bank_change", "bank_changed")


def test_new_state_names_are_the_ctx_objects(srv):
    for n in STATE_NAMES2: assert getattr(srv, n) is getattr(srv.ctx, n), n
    assert srv.BANK_FP == srv.ctx.BANK_FP == srv.bank_fp()


def test_domain_functions_in_server_are_partials_of_the_domain_module(srv):
    from exam_core import domain
    for n in DOMAIN:
        f = getattr(srv, n); assert f.func is getattr(domain, n) and f.args == (srv.ctx,), n


def test_domain_module_does_no_file_io():
    src = (CORE / "domain.py").read_text(encoding="utf-8")
    for bad in ("open(", "atomic_write", "os.", "import os", "print("): assert bad not in src, bad            # بدون كتابة ملفات ولا طباعة: منطق نقي على ctx


def test_domain_works_from_a_hand_built_ctx_without_the_server(srv):
    from exam_core import domain
    from exam_core.ctx import Ctx
    c = Ctx("غير_موجود"); c.SET.update(srv.SET); c.QLIST[:] = srv.QLIST; c.BANK.update(srv.BANK); c.PICK.update(srv.PICK); c.STATE.update({"closed_at": 0})
    p = domain.make_paper(c); assert len(p["ids"]) == sum(c.PICK.values()) and len(p["orders"]) == len(p["ids"])
    c.PAPERS["k"] = p
    assert abs(domain.remain_of(c, "k") - c.SET["minutes"] * 60) <= 2 and domain.fmt_dur(c, 83) == "1 د 23 ث"
    c.STATE["closed_at"] = p["start"] + 5; assert domain.remain_of(c, "k") <= 5                             # إنهاء المعلم بيقصّ الوقت
    n = p["ids"][0]; assert domain.pub_q(c, n) == srv.pub_q(n)
    assert domain.total_range(c, c.PICK) == srv.total_range(srv.PICK) and domain.bank_fp(c) == srv.bank_fp()


def test_two_instances_do_not_share_the_new_state(pkg, tmp_path_factory):
    from conftest import CODE_FILES, Pkg, copy_any
    d = tmp_path_factory.mktemp("third")
    for f in CODE_FILES: copy_any(PKG_SRC / f, d / f)
    pk2 = Pkg(d); pk2.questions(); pk2.students(); pk2.settings(**{"عنوان_الامتحان": "امتحان آخر"})
    m1, m2 = pkg.load(), pk2.load()
    m1.PAPERS["x"] = m1.make_paper(); m1.CLAIMS["x"] = "d"
    assert m2.PAPERS == {} and m2.CLAIMS == {} and m1.PAPERS is not m2.PAPERS and m1.STATE is not m2.STATE


# ============================ طبقة التخزين storage ومسارات الملفات في ctx (المرحلة 5) ============================
STORAGE = ("save_claims", "save_papers", "save_state", "beat", "flush_answers", "gap_check", "extend_time", "compensate_downtime", "submit_for", "reopen_student",
           "write_results_csv", "init_codes", "check_code")
CTX_PATHS = ("OUT", "SUBS_FILE", "CLAIMS_FILE", "PAPERS_FILE", "STATE_FILE", "ANS_FILE", "CODES_FILE", "ALIVE_FILE")


def test_storage_functions_in_server_are_partials_of_the_storage_module(srv):
    from exam_core import storage
    for n in STORAGE:
        f = getattr(srv, n); assert f.func is getattr(storage, n) and f.args == (srv.ctx,), n
    assert callable(srv.flusher) and not hasattr(srv.flusher, "func")                           # حلقة الخلفية بتبقى بـ server.py (اختبارات النوم بتبدّل time وflush_answers جواها)


def test_file_paths_and_constants_come_from_ctx_and_nothing_else(srv, pkg):
    for n in CTX_PATHS: assert getattr(srv, n) == getattr(srv.ctx, n) and getattr(srv.ctx, n).startswith(str(pkg.path)), n
    assert srv.MAX_COMP == srv.ctx.MAX_COMP == 1800 and srv.GAP_S == srv.ctx.GAP_S and srv.REOPEN_MIN == srv.ctx.REOPEN_MIN and srv.LOCK is srv.ctx.LOCK
    import re
    code = re.sub(r"_CTX_NAMES = \(.*?\)", "", (PKG_SRC / "server.py").read_text(encoding="utf-8"), count=1)
    assert not re.findall(r"(?<![\w.\"'])(?:%s)\b(?![\"'])" % "|".join(CTX_PATHS), code)       # server.py ما بيستعمل الأسماء القديمة: كله ctx.X


def test_storage_module_never_rebinds_globals_or_imports_the_server():
    src = (CORE / "storage.py").read_text(encoding="utf-8")
    assert "global " not in src and "import server" not in src and "from server" not in src
    assert "BASE" not in src.replace("ctx.BASE", "")


def test_storage_writes_through_the_ctx_paths_only(srv, tmp_path):
    import json
    from exam_core import storage
    from exam_core.constants import HEAD
    from exam_core.ctx import Ctx
    c = Ctx(str(tmp_path)); c.print = lambda *a, **k: None
    c.CLAIMS["k"] = "d1"; c.PAPERS["k"] = {"start": 1.5, "ids": [1], "orders": [[0]]}; c.STATE.update({"closed_at": 0}); c.ANS["k"] = {"1": 0}; c.ANS_DIRTY[0] = True
    storage.save_claims(c); storage.save_papers(c); storage.save_state(c); storage.flush_answers(c); storage.beat(c); storage.write_results_csv(c)
    assert json.loads((tmp_path / "claims.json").read_text(encoding="utf-8")) == {"k": "d1"} and json.loads((tmp_path / "papers.json").read_text(encoding="utf-8"))["k"]["ids"] == [1]
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8")) == {"closed_at": 0} and json.loads((tmp_path / "answers.json").read_text(encoding="utf-8")) == {"k": {"1": 0}}
    assert c.ANS_DIRTY[0] is False and float((tmp_path / "alive.txt").read_text()) > 0
    assert (tmp_path / "results.csv").read_text(encoding="utf-8-sig").splitlines()[0] == ",".join(HEAD)


def test_login_codes_through_storage_from_a_ctx(srv):
    from exam_core import storage
    from exam_core.ctx import Ctx
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        c = Ctx(d); c.ROSTER.update(srv.ROSTER); c.SET.update(srv.SET); storage.init_codes(c)
        k = f"{srv.SET['title']}|العاشر|أ|طالب أ1"
        assert len(c.CODES) == sum(len(n) for g in srv.ROSTER.values() for n in g.values())
        assert storage.check_code(c, k, c.CODES["العاشر|أ|طالب أ1"]) is None and storage.check_code(c, k, "000000") == "badcode"


# ============================ طبقتا التقارير reports والصفحات views (المرحلة 6) ============================
REPORTS = ("find_keys", "student_rows", "question_stats", "section_stats", "xlsx_bytes", "build_xlsx")
VIEWS = ("band_of", "rv_block", "teacher_nav", "teacher_page", "login_page", "report_page", "sheet_html", "sheet_page", "codes_page", "key_page", "build_preview", "settings_page")


def test_reports_and_views_in_server_are_partials_of_their_modules(srv):
    from exam_core import reports, views
    for n in REPORTS: f = getattr(srv, n); assert f.func is getattr(reports, n) and f.args == (srv.ctx,), n
    for n in VIEWS: f = getattr(srv, n); assert f.func is getattr(views, n) and f.args == (srv.ctx,), n
    for n in ("CSS", "TABS", "SHEET_CSS", "SETTINGS_BODY", "MONITOR", "REHEARSAL_PAGE", "PASS_PCT", "BANDS"): assert getattr(srv, n) is getattr(views, n), n
    assert srv.GLBL is srv.ctx.GLBL and srv.glabel.func.__name__ == "glabel" and srv.glabel("hard") == "صعب"


def test_reports_do_no_file_io_and_views_only_read_the_template():
    import ast

    def calls(path):
        names, attrs = [], []
        for n in ast.walk(ast.parse((CORE / path).read_text(encoding="utf-8"))):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name): names.append(f.id)
                elif isinstance(f, ast.Attribute): attrs.append(f.attr)
        return names, attrs
    rn, ra = calls("reports.py")
    for bad in ("open", "print", "atomic_write", "write"): assert bad not in rn and bad not in ra, bad                              # بدون كتابة ملفات ولا طباعة (ملاحظة: onclick=print() بصفحات HTML نص مش استدعاء)
    vn, va = calls("views.py")
    assert vn.count("open") == 2 and "atomic_write" not in vn and "print" not in vn and "write" not in va                              # بتقرأ template.html بس (build_page و build_preview)
    assert (CORE / "views.py").read_text(encoding="utf-8").count('os.path.join(ctx.BASE, "template.html")') == 2


def test_pages_from_a_hand_built_ctx_equal_the_servers_pages(srv):
    from exam_core import reports, views
    from exam_core.ctx import Ctx
    c = Ctx(srv.BASE); c.SET.update(srv.SET); c.QLIST[:] = srv.QLIST; c.BANK.update(srv.BANK); c.PICK.update(srv.PICK); c.ROSTER.update(srv.ROSTER); c.STATE.update(srv.STATE)
    assert views.key_page(c) == srv.key_page() and views.teacher_nav(c, "key") == srv.teacher_nav("key") and views.login_page(c, "/x") == srv.login_page("/x")
    assert views.build_preview(c) == srv.PREVIEW and reports.student_rows(c) == srv.student_rows() and reports.question_stats(c) == srv.question_stats()
    assert views.report_page(c) == srv.report_page()


def test_teacher_preview_keeps_its_roster_placeholder_replaced(srv):
    assert "/*ROSTER*/" not in srv.PREVIEW and "ctx.ROSTER" not in srv.PREVIEW and "معاينة المعلم" in srv.PREVIEW        # (اتصلّح بالمرحلة 6: نص الـplaceholder كان انكتب بالغلط)


def test_glabel_follows_the_rules_in_ctx_glbl(pkg):
    pkg.raw_settings("عنوان_الامتحان = ت\nسحب = المستوى:سهل | العدد:2\n"); m = pkg.load()
    assert m.glabel("r1").startswith("قاعدة 1") and m.GLBL is m.ctx.GLBL and "r1" in m.ctx.GLBL


# ============================ طبقة الويب web: معالج الطلبات H بدالة لكل مسار (المرحلة 7) ============================
import pytest
from test_http import Server


@pytest.fixture
def web(pkg):
    s = Server(pkg).start()
    yield s
    s.stop()


GET_OPEN = {"/", "/index.html", "/ok", "/rehearsal", "/rehearsal.json", "/health", "/health.json", "/taken", "/link"}
GET_AUTH = {"/login", "/authcheck", "/logout"}
GET_TEACHER = {"/monitor", "/monitor-old", "/monitor.json", "/admin", "/report", "/report.xlsx", "/sheet", "/key", "/codes", "/teacher", "/settings", "/settings.json", "/files", "/files.json", "/template/questions.xlsx", "/template/students.xlsx"}
POST_ROUTES = {"/login", "/settings", "/monitor", "/rehearsal/join", "/rehearsal/report", "/start", "/resume", "/review", "/ping", "/submit"}


def test_handler_lives_in_the_web_module_with_a_method_per_route(srv):
    H = srv.H
    assert H.__module__ == "exam_core.web" and issubclass(H, __import__("http.server").server.BaseHTTPRequestHandler)
    assert set(H.OPEN_GET) == GET_OPEN and set(H.AUTH_GET) == GET_AUTH and set(H.TEACHER_GET) == GET_TEACHER and set(H.POST) == POST_ROUTES
    for table in (H.OPEN_GET, H.AUTH_GET, H.POST):
        for path, name in table.items(): assert callable(getattr(H, name)), (path, name)
    for name in ("get_teacher_page", "get_monitor_ui", "get_img", "do_GET", "do_POST", "send", "teacher", "not_local", "authed"): assert callable(getattr(H, name)), name
    assert H.timeout == 20


def test_unknown_get_and_post_paths_are_404(web):
    assert web.get("/nope")[0] == 404 and web.post("/nope", {"a": 1})[0] == 404 and web.get("/img/")[0] == 404


def test_web_module_has_no_server_import_and_no_global_state():
    import ast
    src = (CORE / "web.py").read_text(encoding="utf-8"); t = ast.parse(src)
    for n in ast.walk(t):
        if isinstance(n, ast.Import): assert not any(a.name.split(".")[0] in ("server", "check_files") for a in n.names)
        if isinstance(n, ast.ImportFrom): assert (n.module or "").split(".")[0] not in ("server", "check_files")
        assert not isinstance(n, ast.Global)
    assert "def make_handler(ctx, app):" in src


def test_handler_reaches_server_functions_through_app_at_request_time(srv, monkeypatch):
    """app = نافذة على متغيرات server.py: تبديل دالة بالاختبارات (m.ip) بيوصل للمعالج"""
    import http.client, http.server, threading
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), srv.H); threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(srv, "ip", lambda: "10.9.8.7")
        c = http.client.HTTPConnection("127.0.0.1", s.server_address[1], timeout=10); c.request("GET", "/link"); body = c.getresponse().read().decode("utf-8"); c.close()
        assert "10.9.8.7" in body
    finally:
        s.shutdown(); s.server_close()


def test_handler_state_comes_from_this_instances_ctx(pkg, srv):
    """معالجان من نسختين مختلفتين ما بيخلطوا الحالة (كل واحد بيحمل ctx تبعه)"""
    import http.client, http.server, threading
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), srv.H); threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        srv.CLAIMS["مفتاح|1|2|3"] = "devA"
        c = http.client.HTTPConnection("127.0.0.1", s.server_address[1], timeout=10); c.request("GET", "/taken?dev=other"); body = c.getresponse().read().decode("utf-8"); c.close()
        assert "مفتاح|1|2|3" in body
    finally:
        s.shutdown(); s.server_close()


# ============================ بروفة الضغط rehearsal، الدخول auth، خدمة الإعدادات admin (المرحلة 8) ============================
NEW8 = {"rehearsal": ("reh_release", "reh_stop", "reh_reset", "reh_tick", "reh_assign", "reh_command", "reh_summary"), "auth": ("refresh_tpass",),
        "admin": ("settings_started", "_eff", "settings_columns", "settings_state", "apply_settings", "new_auto_title")}


def test_every_call_to_a_ctx_function_passes_ctx():
    """فحص عام لكل وحدات exam_core: أي دالة أول وسيط لها ctx لازم تنتادى بـ ctx (غلطة نقل كانت ممكن تمرّ: glabel(k) بدل glabel(ctx, k))"""
    import ast
    trees = {p.name: ast.parse(p.read_text(encoding="utf-8")) for p in CORE.glob("*.py")}
    ctx_fns = {n.name for t in trees.values() for n in t.body if isinstance(n, ast.FunctionDef) and n.args.args and n.args.args[0].arg == "ctx"}
    assert len(ctx_fns) > 60
    bad = []
    for fname, t in trees.items():
        for fn in [n for n in ast.walk(t) if isinstance(n, ast.FunctionDef)]:
            params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
            for c in ast.walk(fn):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in ctx_fns and c.func.id not in params:
                    if not (c.args and isinstance(c.args[0], ast.Name) and c.args[0].id == "ctx"): bad.append((fname, c.lineno, c.func.id))
    assert not bad, bad


def test_rehearsal_auth_and_admin_in_server_are_partials_of_their_modules(srv):
    from exam_core import admin, auth, rehearsal
    for mod, names in NEW8.items():
        m = {"rehearsal": rehearsal, "auth": auth, "admin": admin}[mod]
        for n in names: f = getattr(srv, n); assert f.func is getattr(m, n) and f.args == (srv.ctx,), (mod, n)
    for n in ("REH", "TOKENS", "TFAIL", "SET_MTIME"): assert getattr(srv, n) is getattr(srv.ctx, n), n
    from exam_core.constants import PROTECTED
    assert srv.PROTECTED is PROTECTED and "/settings" in PROTECTED and "/key" in PROTECTED and "/files" in PROTECTED and "/files.json" in PROTECTED


def test_rehearsal_from_a_hand_built_ctx(srv):
    from exam_core import rehearsal
    from exam_core.ctx import Ctx
    c = Ctx("x"); c.print = lambda *a, **k: None; c.SET.update(srv.SET); c.ROSTER.update(srv.ROSTER); c.STATE.update({"closed_at": 0})
    assert c.REH["on"] is False and c.REH is not srv.REH
    err = rehearsal.reh_command(c, "on", {}); assert err is None and c.REH["on"] is True and srv.REH["on"] is False            # الحالة منفصلة بين ctx والتاني
    assert rehearsal.reh_assign(c, "dev-1")["n"] == 1
    rehearsal.reh_command(c, "off", {}); assert c.REH["on"] is False


def test_auth_refresh_tpass_follows_the_settings_file(pkg):
    import os, time
    m = pkg.load(); old = m.SET["tpass"]
    pkg.raw_settings("عنوان_الامتحان = اختبار الوحدة\nكلمة_سر_المعلم = جديدة123\n"); os.utime(pkg.p("settings.txt"), (time.time() + 5, time.time() + 5))
    m.refresh_tpass(); assert m.SET["tpass"] == "جديدة123" and old != "جديدة123"


def test_admin_state_and_title_from_a_hand_built_server(pkg):
    m = pkg.load(); s = m.settings_state()
    assert s["bank"] == len(m.QLIST) and s["started"] is False and {f["key"] for f in s["fields"]} == {fk for _, fk, *_ in m.SPEC}
    m.PAPERS["x"] = m.make_paper(); assert m.settings_state()["started"] is True and m.settings_started() is True


# ============================ توحيد منطق التسليم (تسليم الطالب وتسليم المعلم بنفس الدوال) ============================
from conftest import key_of, q, start_paper

REC_BASE = ["key", "exam", "grade", "section", "name", "ids", "answers", "score", "total", "auto", "time", "leave", "late", "ts"]


def _lines(pkg):
    import json
    return [json.loads(l) for l in pkg.p("submissions.jsonl").read_text(encoding="utf-8").splitlines()]


def test_student_and_teacher_submissions_are_built_by_the_same_functions(web, pkg):
    """السجل الأصلي: تسليم الطالب = الحقول الأساسية + dur (+ pause)، وتسليم المعلم = الحقول الأساسية بنفس الترتيب"""
    k, _, p = web.start_student("d1", n="طالب أ1"); ids = p["ids"]
    st, j, _ = web.submit(k, "d1", ids, web.correct_answers(ids)); assert st == 200 and j["score"] == j["total"]
    k2, _, p2 = web.start_student("d2", n="طالب أ2")
    web.teacher(submitfor=k2)                                                                       # المعلم بيسلّم عنه (ما أجاب شي: كله خاطئ)
    recs = {r["name"]: r for r in _lines(pkg)}
    assert list(recs["طالب أ1"]) == REC_BASE + ["dur"] and list(recs["طالب أ2"]) == REC_BASE
    assert recs["طالب أ1"]["auto"] == "يدوي" and recs["طالب أ2"]["auto"] == "تسليم من المعلم" and recs["طالب أ2"]["score"] == 0 and recs["طالب أ2"]["late"] == 0


def test_score_paper_applies_marks_weights_and_the_final_mark(pkg):
    from exam_core import domain
    pkg.questions([q(f"س{i}", ans="أ", level="سهل", marks=m) for i, m in enumerate(("1", "2", "3", "2"), 1)]); pkg.raw_settings("عنوان_الامتحان = ت\n"); m = pkg.load()
    ids = [x["n"] for x in m.QLIST]; right = [0] * 4
    assert domain.score_paper(m.ctx, ids, right) == (8, 8) and domain.score_paper(m.ctx, ids, [-1] * 4) == (0, 8) and domain.score_paper(m.ctx, ids, [0, 1, 1, 0]) == (3, 8)
    pkg.raw_settings("عنوان_الامتحان = ت\nالعلامة_النهائية = 20\n"); m2 = pkg.load()
    assert domain.score_paper(m2.ctx, ids, [0, 1, 1, 0]) == (7.5, 20)                                 # 3/8 × 20


def test_record_submission_failure_changes_nothing_and_success_updates_the_state(srv, pkg, tmp_path):
    import pytest
    from exam_core import domain, storage
    k = start_paper(srv, key_of(srv), "d1"); ids = srv.PAPERS[k]["ids"]; srv.ANS[k] = {str(ids[0]): 0}; srv.LIVE[k] = {"t": 1}
    rec = domain.build_record(srv.ctx, k, srv.parse_key(k), ids, [0] * len(ids), "t", "", 0, 5.0)
    good = srv.ctx.SUBS_FILE; bad = tmp_path / "مجلد"; bad.mkdir(); srv.ctx.SUBS_FILE = str(bad)
    with pytest.raises(OSError): storage.record_submission(srv.ctx, rec)
    assert k not in srv.SUBS and k in srv.LIVE and k in srv.ANS                                              # الكتابة فشلت: الذاكرة ما تغيّرت
    srv.ctx.SUBS_FILE = good
    storage.record_submission(srv.ctx, rec)
    assert srv.SUBS[k] is rec and k not in srv.LIVE and k not in srv.ANS and srv.ANS_DIRTY[0] is True
    assert _lines(pkg)[-1]["key"] == k


def test_build_record_extra_fields_come_last_and_values_are_taken_as_given(srv):
    from exam_core import domain
    k = key_of(srv); rec = domain.build_record(srv.ctx, k, ("العاشر", "أ", "طالب أ1"), [1], [0], "يدوي", "لم يخرج", 7, 123.456, dur=9, pause=3)
    assert list(rec) == REC_BASE + ["dur", "pause"] and rec["late"] == 7 and rec["ts"] == 123.46 and rec["grade"] == "العاشر" and rec["dur"] == 9
