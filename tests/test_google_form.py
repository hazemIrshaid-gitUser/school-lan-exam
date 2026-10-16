"""الفورم الاحتياطي (05_برنامج_الفورم_الاحتياطي.txt): برنامج Google Apps Script بيعمل Google Form من ملف الأسئلة نفسه.
بيشتغل هون بدون إنترنت ضد نسخة وهمية من Google (gform_harness.js، بـ Node): الوهمي فيه بس الأوامر الموجودة فعلاً،
والاختبارات بتتأكد إن قواعد قراءة الملف والسحب والثوابت والعلامات نفس السيرفر."""
import json, re, shutil, subprocess

import pytest
from conftest import PKG_SRC, bank, q

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="Node.js مش مثبّت")
SCRIPT = PKG_SRC / "05_برنامج_الفورم_الاحتياطي.txt"
HARNESS = PKG_SRC.parent / "tests" / "gform_harness.js"
HEAD = ["السؤال", "أ", "ب", "ج", "د", "الجواب", "المستوى", "المرجع", "الحل", "العلامة", "ثابت"]


def run(tmp_path, rows, settings=None, **extra):
    inp = {"rows": [HEAD] + [[str(c) for c in r] for r in rows], "settings": settings or {}, **extra}
    f = tmp_path / "inp.json"; f.write_text(json.dumps(inp, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([NODE, str(HARNESS), str(SCRIPT), str(f)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def mcs(form): return [i for i in form["items"] if i["type"] == "mc"]
plain = lambda t: t.replace(chr(0x2066), "").replace(chr(0x2069), "")
links = lambda o: o["sheets"]["روابط الفورم"]


def test_default_bank_makes_one_closed_quiz_with_right_answers(tmp_path):
    o = run(tmp_path, bank())
    assert o["error"] is None and len(o["forms"]) == 1
    f = o["forms"][0]
    assert f["quiz"] is True and f["accepting"] is False and f["shuffle"] is True and f["dest"] == ["SPREADSHEET", "ss1"] and f["again"] is False
    assert [i["type"] for i in f["items"][:3]] == ["text", "text", "page"] and all(i["required"] for i in f["items"][:2])
    qs = mcs(f); assert len(qs) == 11                                                     # فاضي = كل أسئلة الملف (زي السيرفر)
    for it in qs:
        n = int(re.search(r"\d+", it["title"]).group()); i = n - 1                     # bank(): الصحيح للسؤال n هو الخيار (n-1)%4
        right = [plain(v) for v, c in it["choices"] if c]
        assert right == [f"خ{i}-{'أبجد'[i % 4]}"] and len(it["choices"]) == 4 and it["points"] == 1 and it["required"] is False
    assert "عدد الأسئلة: 11، والعلامة من 11." in f["description"]
    assert links(o)[1][1].startswith("https://forms.gle/") and "قبول الردود" in "".join(map(str, sum(links(o), [])))
    assert o["moved"] == ["form1"]                                                         # الفورم بنفس مجلد ملف الأسئلة


def test_counts_fixed_questions_and_versions(tmp_path):
    rows = bank(6, 6, 6); rows[0][10] = "نعم"; rows[7][10] = "نعم"                      # ثابت: صعب 1، وسط 8
    o = run(tmp_path, rows, {"hard": 2, "medium": 3, "easy": 1, "versions": 3, "title": "الرياضيات", "minutes": 40}, seed=7)
    assert o["error"] is None and [f["title"] for f in o["forms"]] == ["الرياضيات (نموذج أ)", "الرياضيات (نموذج ب)", "الرياضيات (نموذج ج)"]
    sets = []
    for f in o["forms"]:
        ns = [int(re.search(r"\d+", i["title"]).group()) for i in mcs(f)]
        assert len(ns) == 6 and 1 in ns and 8 in ns                                        # الثابتة بكل نموذج
        lv = [("صعب" if n <= 6 else "وسط" if n <= 12 else "سهل") for n in ns]
        assert lv.count("صعب") == 2 and lv.count("وسط") == 3 and lv.count("سهل") == 1
        assert "مدته 40 دقيقة" in f["description"]; sets.append(frozenset(ns))
    assert len(set(sets)) > 1                                                               # النماذج مختلفة
    assert "نموذجين" not in o["logs"][0] and "3 نماذج" in o["logs"][0]


def test_no_levels_uses_total(tmp_path):
    rows = [q(f"سؤال {i}", ("1", "2", "3"), "ج") for i in range(10)]
    o = run(tmp_path, rows, {"total": 4})
    assert o["error"] is None and len(mcs(o["forms"][0])) == 4 and all(len(i["choices"]) == 3 for i in mcs(o["forms"][0]))


@pytest.mark.parametrize("rows, settings, needle", [
    ([q("س", ("1", "2"), "ج")], {}, "سطر 2: عمود «الجواب»"),
    ([q("س", ("1", "", "3"))], {}, "سطر 2: لازم خيارين"),
    ([q("", ("1", "2"))], {}, "سطر 2: نص السؤال فاضي"),
    ([q("س", ("1", "2"), level="صعبه جداً")], {}, "سطر 2: المستوى"),
    ([q("س", ("1", "2"), marks="كثير")], {}, "سطر 2: عمود «العلامة»"),
    ([q("س", ("1", "2"), fixed="ربما")], {}, "سطر 2: عمود «ثابت»"),
    ([q("س", ("1", "1"))], {}, "سطر 2: في خيارين متطابقين"),
    ([q("س", ("1", "2"), level="constructor")], {}, "سطر 2: المستوى"),           # كلمة خاصة بجافاسكربت ما بتمرق كمستوى
    (bank(1, 1, 1), {"hard": 2}, "صعب مطلوب 2 والموجود 1"),
    ([q("س1", level="صعب", fixed="نعم"), q("س2", level="صعب", fixed="نعم")], {"hard": 1}, "الأسئلة الثابتة"),
    (bank(), {"versions": 11}, "versions"),
])
def test_bad_file_stops_with_a_clear_reason_and_makes_nothing(tmp_path, rows, settings, needle):
    o = run(tmp_path, rows, settings)
    assert not o["forms"] and o["error"] and needle in o["error"]                          # من المحرّر: الخطأ بيطلع بالأحمر
    assert needle in links(o)[1 + [needle in r[0] for r in links(o)[1:]].index(True)][0]   # ومكتوب بورقة الروابط كمان


def test_error_shows_as_alert_when_run_from_the_menu(tmp_path):
    o = run(tmp_path, [q("س", ("1", "2"), "د")], ui=True)
    assert o["error"] is None and o["alerts"] and "سطر 2" in o["alerts"][0]


def test_menu(tmp_path):
    o = run(tmp_path, bank(), call="onOpen", ui=True)
    assert o["menus"] and o["menus"][0]["items"] == [["إنشاء الفورم من الأسئلة", "makeForm"]]


def test_half_marks_are_scaled_to_whole_points(tmp_path):
    rows = [q("س1", marks="0.5"), q("س2", marks="٢٫٥"), q("س3")]
    o = run(tmp_path, rows)
    assert sorted(i["points"] for i in mcs(o["forms"][0])) == [1, 2, 5] and "انضربت بـ 2" in o["logs"][0]
    o = run(tmp_path, rows, {"questionMark": 2})
    assert [i["points"] for i in mcs(o["forms"][0])] == [2, 2, 2]


def test_images_go_right_before_their_question_and_stop_shuffling(tmp_path):
    rows = [q("شو الشكل؟ [img:a.png]"), q("[img:b.png]"), q("بدون صورة")]
    o = run(tmp_path, rows, images=["a.png", "b.png"])
    f = o["forms"][0]; it = f["items"]
    assert f["shuffle"] is False
    for i, x in enumerate(it):
        if x["type"] == "image": assert it[i + 1]["type"] == "mc"
    titles = {plain(x["title"]) for x in mcs(f)}
    assert {"شو الشكل؟", "اختر الإجابة الصحيحة حسب الصورة", "بدون صورة"} == titles and sorted(x["image"] for x in it if x["type"] == "image") == ["a.png", "b.png"]
    o = run(tmp_path, rows, images=["a.png"])
    assert not o["forms"] and "«b.png» مش موجودة" in o["error"]
    o = run(tmp_path, rows, images=[], imagesFolder=False)
    assert not o["forms"] and "ما في مجلد اسمه images" in o["error"]


def test_image_inside_an_option_is_left_out_with_a_note(tmp_path):
    o = run(tmp_path, [q("س1", ("[img:x.png]", "2")), q("س2")])
    assert [plain(x["title"]) for x in mcs(o["forms"][0])] == ["س2"] and "سطر 2: فيه صورة داخل الخيارات" in o["logs"][0]


def test_math_inside_arabic_is_isolated_like_the_server(tmp_path, srv):
    t = "إذا كان (x + 7)/(x − 3) = 2، فما قيمة x؟"
    o = run(tmp_path, [q(t, ("x = 1", "2"))])
    it = mcs(o["forms"][0])[0]
    assert it["title"] == srv.autoltr(t) and it["title"] != t and plain(it["title"]) == t
    assert it["choices"][0][0] == "x = 1"                                                  # خيار رياضي لحاله (بدون عربي) بيضل زي ما هو


def test_options_keep_their_text_when_shuffled(tmp_path):
    o = run(tmp_path, bank(), seed=3)
    f = o["forms"][0]
    assert any([v for v, _ in i["choices"]] != sorted(v for v, _ in i["choices"]) for i in mcs(f))   # انخلطت
    o = run(tmp_path, bank(), {"shuffleOptions": False})
    assert all([v for v, _ in i["choices"]] == sorted(v for v, _ in i["choices"]) for i in mcs(o["forms"][0]))


def test_six_versions_of_twenty_with_one_and_a_half_marks_out_of_thirty(tmp_path):
    """طلب حقيقي: 6 نماذج × 20 سؤال من بنك 60، 3 ثوابت، 40 دقيقة، كل سؤال 1.5 والعلامة من 30"""
    rows = bank(20, 20, 20); rows[26][10] = "نعم"; rows[21][10] = "نعم"; rows[43][10] = "نعم"      # ثوابت: صعب 27، وسط 22 و44
    o = run(tmp_path, rows, {"hard": 6, "medium": 7, "easy": 7, "versions": 6, "questionMark": 1.5, "minutes": 40, "title": "امتحان"})
    assert o["error"] is None and [f["title"][-2] for f in o["forms"]] == list("أبجدهو")
    for f in o["forms"]:
        ns = [int(re.search(r"\d+", i["title"]).group()) for i in mcs(f)]
        assert len(ns) == 20 and {27, 22, 44} <= set(ns) and all(i["points"] == 3 for i in mcs(f))
        assert "مدته 40 دقيقة" in f["description"] and "والعلامة من 30 (الفورم بيعرضها من 60، يعني مضروبة بـ 2)" in f["description"]


def test_make_form_is_the_first_function_so_run_picks_it(tmp_path):
    src = SCRIPT.read_text(encoding="utf-8")
    assert re.findall(r"^function (\w+)", src, re.M)[0] == "makeForm"


def test_google_rejecting_the_closed_message_does_not_stop_the_form(tmp_path):
    """أول تشغيل حقيقي عند Google: setCustomClosedFormMessage رجّعت «Invalid data updating form» ووقّفت كل شي بعد أول نموذج"""
    o = run(tmp_path, bank(), {"versions": 2}, rejectClosedMessage=True)
    assert o["error"] is None and len(o["forms"]) == 2 and all(f["accepting"] is False and f["dest"] for f in o["forms"])
    assert links(o)[2][1].startswith("https://forms.gle/")
