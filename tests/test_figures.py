"""figures_tool.py: أداة قص الأشكال من كتاب PDF (بيشغّلها Claude). ملفات PDF اصطناعية بأشكال ومواقع معروفة، فنقدر نتحقق من النتيجة بالضبط."""
import importlib.util, json, os, subprocess, sys, time

import pytest

pymupdf = pytest.importorskip("pymupdf")
Image = pytest.importorskip("PIL.Image")
from conftest import PKG_SRC, bank

TOOL = PKG_SRC / "figures_tool.py"
W, H = 595, 794


@pytest.fixture(scope="module")
def ft():
    spec = importlib.util.spec_from_file_location("figures_tool_under_test", TOOL)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def run(*args, env=None):
    e = dict(os.environ, PYTHONIOENCODING="utf-8"); e.update(env or {})
    return subprocess.run([sys.executable, "-X", "utf8", str(TOOL), *map(str, args)], capture_output=True, text=True, encoding="utf-8", env=e, timeout=180)


def make_pdf(path, *builders, pages=1):
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=W, height=H)
        for b in builders: b(page)
    doc.save(str(path)); doc.close()
    return str(path)


def circle_fig(cx=275, cy=360, r=60):
    def b(page):
        page.draw_circle((cx, cy), r, color=(0, 0, 0), width=1.5)
        page.draw_line((cx - r, cy), (cx + r, cy), color=(0, 0, 0), width=1.5)
        page.draw_line((cx, cy - r), (cx, cy + r), color=(0, 0, 0), width=1.5)
    return b


def badge(n, cx=120, cy=310):
    def b(page):
        page.draw_circle((cx, cy), 10, color=None, fill=(1, 0.8, 0.2))
        page.insert_text((cx - 4, cy + 4), str(n), fontsize=12)
    return b


def text_at(x, y, s, size=11):
    return lambda page: page.insert_text((x, y), s, fontsize=size)


def detect_cli(tmp_path, pdf, pages="1", dpi=None):
    out = tmp_path / "figs"
    args = ["detect", pdf, pages, "--out", out] + (["--dpi", dpi] if dpi else [])
    r = run(*args)
    idx = json.loads((out / "index.json").read_text(encoding="utf-8")) if (out / "index.json").exists() else None
    return r, idx, out


# ============================ وحدات صغيرة ============================
@pytest.mark.parametrize("spec,n,expected", [("1-3", 10, [1, 2, 3]), ("1-2,5", 10, [1, 2, 5]), (" 4 , 6-7 ", 10, [4, 6, 7]), ("3-1", 10, []), ("7", 7, [7])])
def test_parse_pages(ft, spec, n, expected):
    assert ft.parse_pages(spec, n) == expected


@pytest.mark.parametrize("spec", ["0", "11", "1-12", "5,99"])
def test_parse_pages_out_of_range_exits_with_message(ft, spec):
    with pytest.raises(SystemExit) as e:
        ft.parse_pages(spec, 10)
    assert "خارج الكتاب" in str(e.value)


def test_group_rects_merges_near_and_keeps_far(ft):
    R = pymupdf.Rect
    g = ft.group_rects([R(0, 0, 10, 10), R(15, 0, 25, 10), R(200, 0, 210, 10)], 14)
    assert sorted(map(sorted, g)) == [[0, 1], [2]]
    assert len(ft.group_rects([R(0, 0, 10, 10), R(15, 0, 25, 10)], 2)) == 2       # بمسافة أصغر ما بتندمج
    assert ft.group_rects([], 5) == []


def test_group_rects_is_transitive(ft):
    R = pymupdf.Rect
    g = ft.group_rects([R(0, 0, 10, 10), R(20, 0, 30, 10), R(40, 0, 50, 10)], 6)      # كل واحد بيلمس اللي جنبه
    assert len(g) == 1


@pytest.mark.parametrize("fill,size,expected", [((1, 0.8, 0.2), (20, 20), True), ((1, 0.8, 0.2), (40, 40), False), ((1, 0.8, 0.2), (6, 6), False),
                                                ((0, 0, 1), (20, 20), False), ((0.5, 0.5, 0.2), (20, 20), False), (None, (20, 20), False), ((0.9, 0.7, 0.3), (14, 14), True)])
def test_is_badge(ft, fill, size, expected):
    d = {"fill": fill, "rect": pymupdf.Rect(0, 0, *size)}
    assert bool(ft.is_badge(d)) is expected


def test_save_figure_resizes_and_picks_format(ft, tmp_path):
    big = Image.new("RGB", (1800, 600), "white")
    p = ft.save_figure(big, str(tmp_path / "a.png"))
    im = Image.open(p); assert p.endswith(".png") and im.size == (900, 300)
    small = Image.new("RGB", (300, 200), "white"); assert ft.save_figure(small, str(tmp_path / "b.png")).endswith(".png") and Image.open(tmp_path / "b.png").size == (300, 200)
    noise = Image.frombytes("RGB", (800, 800), os.urandom(800 * 800 * 3))             # صورة فوتوغرافية ثقيلة: PNG كبير
    p = ft.save_figure(noise, str(tmp_path / "c.png"))
    assert p.endswith(".jpg") and not (tmp_path / "c.png").exists() and Image.open(p).format == "JPEG"


def test_save_figure_handles_alpha_and_palette_images(ft, tmp_path):
    for mode in ("RGBA", "P", "L", "CMYK"):
        im = Image.new(mode, (100, 80)); p = ft.save_figure(im, str(tmp_path / f"{mode}.png"))
        assert Image.open(p).mode == "RGB"


def test_draw_grid_marks_page(ft):
    img = Image.new("RGB", (595, 794), "white")
    out = ft.draw_grid(img, 595, 794)
    px = out.load()
    assert px[100, 400] != (255, 255, 255) and px[300, 100] != (255, 255, 255)        # خطوط الشبكة على 100 نقطة


# ============================ detect ============================
def test_detect_single_figure_with_badge_and_text(tmp_path):
    pdf = make_pdf(tmp_path / "book.pdf", circle_fig(), badge(7), text_at(150, 280, "Find the measure of the angle x shown in the figure below"))
    r, idx, out = detect_cli(tmp_path, pdf)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(idx) == 1
    f = idx[0]
    x0, y0, x1, y1 = f["bbox"]
    assert 205 <= x0 <= 215 and 289 <= y0 <= 300 and 335 <= x1 <= 345 and 420 <= y1 <= 432
    assert f["question_badge"] == "7" and f["text_above"].startswith("Find the measure") and f["page"] == 1 and f["id"] == 1
    assert f["file"] == "p001_f1.png" and (out / "p001_f1.png").exists() and (out / "overview_p001.png").exists()
    im = Image.open(out / f["file"]); assert im.width <= 900 and (im.width, im.height) == (f["width_px"], f["height_px"])
    assert "1 شكل" in r.stdout and "سؤال=7" in r.stdout and f["kb"] == os.path.getsize(out / f["file"]) // 1024


def test_detect_crop_is_not_blank_and_excludes_page_text(tmp_path):
    pdf = make_pdf(tmp_path / "b.pdf", circle_fig(), text_at(150, 296, "A long sentence that sits right above the figure"), text_at(150, 440, "Another long sentence right under the figure"))
    r, idx, out = detect_cli(tmp_path, pdf)
    f = idx[0]
    doc = pymupdf.open(pdf); lines = [pymupdf.Rect(l["bbox"]) for b in doc[0].get_text("dict")["blocks"] for l in b["lines"]]
    above = next(l for l in lines if l.y1 < 330 and l.y0 > 270); below = next(l for l in lines if l.y0 > 420)
    assert f["bbox"][1] >= above.y1 - 0.5 and f["bbox"][3] <= below.y0 + 0.5            # القص ما بيدخل أسطر النص المجاورة
    im = Image.open(out / f["file"]).convert("L")
    assert min(im.convert('L').tobytes()) < 80                                                       # فيه خطوط سودا فعلاً (مش صورة بيضا)


def test_detect_ignores_header_footer_frames_and_tiny_marks(tmp_path):
    def decorations(page):
        page.draw_line((50, 20), (545, 20), color=(0, 0, 0), width=2)                  # خط الرأس
        page.draw_rect(pymupdf.Rect(50, 760, 545, 775), color=(0, 0, 0), fill=(0.9, 0.9, 0.9))   # تذييل
        page.draw_rect(pymupdf.Rect(30, 80, 565, 700), color=(0, 0, 0))                # إطار الصفحة كلها
        page.draw_rect(pymupdf.Rect(300, 600, 320, 615), color=(0, 0, 0))              # علامة صغيرة (أقل من 45x35)
    r, idx, _ = detect_cli(tmp_path, make_pdf(tmp_path / "d.pdf", decorations))
    assert r.returncode == 0 and idx == []


def test_detect_ignores_text_heavy_frames(tmp_path):
    def solved_example(page):
        rect = pymupdf.Rect(100, 200, 400, 360)
        page.draw_rect(rect, color=(0, 0, 0))
        page.insert_textbox(rect + (4, 4, -4, -4), " ".join(f"word{i}" for i in range(80)), fontsize=8)
    _, idx, _ = detect_cli(tmp_path, make_pdf(tmp_path / "t.pdf", solved_example))
    assert idx == []


def test_detect_raster_image_but_not_icons_or_backgrounds(tmp_path):
    for name, size, color in (("fig.png", (400, 240), "tomato"), ("icon.png", (30, 30), "blue"), ("bg.png", (100, 100), "lightgray")):
        Image.new("RGB", size, color).save(tmp_path / name)
    def imgs(page):
        page.insert_image(pymupdf.Rect(100, 200, 300, 320), filename=str(tmp_path / "fig.png"))      # شكل: بينكشف
        page.insert_image(pymupdf.Rect(400, 200, 430, 230), filename=str(tmp_path / "icon.png"))     # أيقونة: لأ
        page.insert_image(pymupdf.Rect(0, 0, W, H), filename=str(tmp_path / "bg.png"))               # خلفية الصفحة: لأ
    _, idx, out = detect_cli(tmp_path, make_pdf(tmp_path / "i.pdf", imgs))
    assert len(idx) == 1 and 90 <= idx[0]["bbox"][0] <= 105 and idx[0]["width_px"] <= 900


def test_detect_grouping_distance_and_reading_order(tmp_path):
    def shapes(page):
        for x in (60, 330):                                     # شكلين بنفس الصف (يسار ويمين) متباعدين
            page.draw_rect(pymupdf.Rect(x, 200, x + 100, 280), color=(0, 0, 0))
        page.draw_rect(pymupdf.Rect(120, 440, 200, 500), color=(0, 0, 0))            # شكل مركّب من قطعتين قريبتين (10 نقاط): لازم يندمجوا
        page.draw_rect(pymupdf.Rect(210, 440, 290, 500), color=(0, 0, 0))
    _, idx, _ = detect_cli(tmp_path, make_pdf(tmp_path / "g.pdf", shapes))
    assert len(idx) == 3
    assert idx[0]["bbox"][0] > idx[1]["bbox"][0]                  # الصف الأول: اليمين قبل اليسار (كتاب عربي)
    assert idx[2]["bbox"][1] > idx[1]["bbox"][1] and idx[2]["bbox"][2] - idx[2]["bbox"][0] > 150      # الثالث تحت، وعرضه = القطعتين مع بعض


def test_detect_figure_inside_figure_keeps_outer_only(tmp_path):
    def nested(page):
        page.draw_rect(pymupdf.Rect(100, 200, 400, 420), color=(0, 0, 0))
        page.draw_circle((250, 310), 40, color=(0, 0, 0))
    _, idx, _ = detect_cli(tmp_path, make_pdf(tmp_path / "n.pdf", nested))
    assert len(idx) == 1 and idx[0]["bbox"][0] <= 100 and idx[0]["bbox"][2] >= 400


def test_detect_includes_short_labels_but_not_question_badge(tmp_path):
    def labelled(page):
        page.draw_rect(pymupdf.Rect(200, 300, 340, 400), color=(0, 0, 0))
        for t, (x, y) in {"A": (188, 305), "B": (344, 305), "O": (265, 414)}.items(): page.insert_text((x, y), t, fontsize=11)
        badge(3, 170, 300)(page)                              # دائرة الرقم قريبة جداً من الشكل
    _, idx, _ = detect_cli(tmp_path, make_pdf(tmp_path / "l.pdf", labelled))
    x0, y0, x1, y1 = idx[0]["bbox"]
    assert x0 < 190 and x1 > 350 and y1 > 410                 # التسميات A و B و O مشمولة
    assert x0 > 180 and idx[0]["question_badge"] == "3"       # بس الدائرة الصفراء (170±10) مش جزء من القصّة


def test_detect_empty_page_and_multiple_pages(tmp_path):
    pdf = make_pdf(tmp_path / "m.pdf", text_at(100, 100, "just text, no figures at all"), pages=1)
    doc = pymupdf.open(pdf); p = doc.new_page(width=W, height=H); circle_fig()(p); doc.saveIncr(); doc.close()
    r, idx, out = detect_cli(tmp_path, pdf, "1-2")
    assert [(f["page"], f["id"]) for f in idx] == [(2, 1)] and "صفحة 1: 0 شكل" in r.stdout and (out / "overview_p001.png").exists() and (out / "p002_f1.png").exists()


def test_detect_dpi_option_changes_resolution(tmp_path):
    pdf = make_pdf(tmp_path / "r.pdf", circle_fig())
    _, lo, _ = detect_cli(tmp_path, pdf, dpi=72); (tmp_path / "figs" / "index.json").unlink()
    _, hi, _ = detect_cli(tmp_path, pdf, dpi=200)
    assert hi[0]["width_px"] > lo[0]["width_px"] * 2 or hi[0]["width_px"] == 900


def test_detect_arabic_paths_and_output_dir(tmp_path):
    d = tmp_path / "كتاب الفيزياء (العاشر)"; d.mkdir()
    pdf = make_pdf(d / "الوحدة الثانية.pdf", circle_fig())
    out = d / "أشكال"
    r = run("detect", pdf, "1", "--out", out)
    assert r.returncode == 0 and (out / "p001_f1.png").exists() and "1 شكل" in r.stdout


def test_detect_bad_pages_arguments(tmp_path):
    pdf = make_pdf(tmp_path / "e.pdf", circle_fig(), pages=2)
    r = run("detect", pdf, "5", "--out", tmp_path / "o")
    assert r.returncode != 0 and "خارج الكتاب" in r.stderr + r.stdout
    r = run("detect", pdf, "abc", "--out", tmp_path / "o")
    assert r.returncode != 0


def test_detect_non_pdf_or_missing_file_fails_cleanly(tmp_path):
    (tmp_path / "x.pdf").write_text("not a pdf")
    assert run("detect", tmp_path / "x.pdf", "1", "--out", tmp_path / "o").returncode != 0
    assert run("detect", tmp_path / "missing.pdf", "1", "--out", tmp_path / "o").returncode != 0


def test_detect_without_pymupdf_explains(tmp_path):
    r = run("detect", make_pdf(tmp_path / "p.pdf", circle_fig()), "1", "--out", tmp_path / "o", env={"NO_PYMUPDF": "1"})
    assert r.returncode != 0 and "PyMuPDF" in r.stdout + r.stderr


@pytest.mark.parametrize("n", [1500, 4000])
def test_detect_performance_on_pages_with_thousands_of_paths(tmp_path, n):
    """صفحة بخرائط/تظليل فيها آلاف المسارات الصغيرة: group_rects تربيعي، نقيس الوقت (الحد 90 ثانية)"""
    def hatch(page):
        for i in range(n):
            x, y = 50 + (i % 40) * 12, 100 + (i // 40) * 12
            page.draw_rect(pymupdf.Rect(x, y, x + 3, y + 3), color=(0, 0, 0))
    t0 = time.time(); r, idx, _ = detect_cli(tmp_path, make_pdf(tmp_path / "h.pdf", hatch)); dt = time.time() - t0
    print(f"[perf] {n} مسار: {dt:.1f}s")
    assert r.returncode == 0 and dt < 90, f"{dt:.1f}s"


# ============================ info / page / crop ============================
def test_info_counts_pages_with_and_without_pymupdf(tmp_path):
    pdf = make_pdf(tmp_path / "i.pdf", circle_fig(), pages=7)
    assert "صفحات: 7" in run("info", pdf).stdout
    assert "صفحات: 7" in run("info", pdf, env={"NO_PYMUPDF": "1"}).stdout


def test_page_grid_dimensions_and_file_name(tmp_path):
    pdf = make_pdf(tmp_path / "g.pdf", circle_fig(), pages=3)
    r = run("page", pdf, "3", "--out", tmp_path / "o")
    assert r.returncode == 0 and "595 x 794" in r.stdout
    im = Image.open(tmp_path / "o" / "page_003_grid.png"); assert abs(im.width - 595 * 110 / 72) <= 2 and abs(im.height - 794 * 110 / 72) <= 2
    r = run("page", pdf, "2", "--dpi", 72, "--out", tmp_path / "o")
    assert Image.open(tmp_path / "o" / "page_002_grid.png").size[0] in (595, 596)
    assert run("page", pdf, "9", "--out", tmp_path / "o").returncode != 0           # صفحة غير موجودة


def test_crop_exact_region_size_and_content(tmp_path):
    pdf = make_pdf(tmp_path / "c.pdf", circle_fig(275, 360, 60))
    out = tmp_path / "out" / "fig.png"
    r = run("crop", pdf, 1, 215, 300, 335, 420, out)
    assert r.returncode == 0 and out.exists()
    im = Image.open(out); assert abs(im.width - 120 * 170 / 72) <= 3 and abs(im.height - 120 * 170 / 72) <= 3
    assert min(im.convert("L").tobytes()) < 80                                       # فيه رسم
    assert "KB" in r.stdout


def test_crop_reversed_and_out_of_bounds_coordinates(tmp_path):
    pdf = make_pdf(tmp_path / "c.pdf", circle_fig())
    a = tmp_path / "a.png"; b = tmp_path / "b.png"; c = tmp_path / "c.png"
    run("crop", pdf, 1, 335, 420, 215, 300, a)                                       # إحداثيات معكوسة بتتصحّح
    run("crop", pdf, 1, 215, 300, 335, 420, b)
    assert Image.open(a).size == Image.open(b).size
    r = run("crop", pdf, 1, -50, -50, 100, 100, c)                                   # خارج الصفحة: بيقص الجزء الداخل
    assert r.returncode == 0 and abs(Image.open(c).width - 100 * 170 / 72) <= 3




@pytest.mark.parametrize("box", [("10", "10", "12", "12"), ("700", "10", "800", "50"), ("10", "900", "50", "950"), ("-80", "-80", "-10", "-10")])
def test_crop_tiny_or_outside_area_exits_with_message(tmp_path, box):
    r = run("crop", make_pdf(tmp_path / "c.pdf", circle_fig()), 1, *box, tmp_path / "x.png")
    assert r.returncode != 0 and "صغيرة جداً" in r.stdout + r.stderr and not (tmp_path / "x.png").exists()


def test_crop_wide_region_is_capped_at_900px(tmp_path):
    out = tmp_path / "wide.png"
    run("crop", make_pdf(tmp_path / "c.pdf", circle_fig()), 1, 0, 0, 595, 400, out, "--dpi", 300)
    assert Image.open(out).width == 900


def test_crop_heavy_photo_becomes_jpeg_under_limit(tmp_path):
    noise = Image.frombytes("RGB", (900, 900), os.urandom(900 * 900 * 3)); noise.save(tmp_path / "n.png")
    pdf = make_pdf(tmp_path / "ph.pdf", lambda p: p.insert_image(pymupdf.Rect(50, 50, 500, 500), filename=str(tmp_path / "n.png")))
    r = run("crop", pdf, 1, 50, 50, 500, 500, tmp_path / "ph.png")
    jpg = tmp_path / "ph.jpg"
    assert jpg.exists() and not (tmp_path / "ph.png").exists() and ".jpg" in r.stdout
    kb = jpg.stat().st_size // 1024
    print(f"[size] أسوأ حالة (ضجيج عشوائي 900px) = {kb}KB")
    assert kb < 1500


def test_crop_and_page_work_with_poppler_fallback_and_arabic_file_name(tmp_path):
    """بدون PyMuPDF بيستعمل pdftoppm، وعلى ويندوز ما بيقبل أسماء عربية: الأداة بتنسخ الملف باسم إنجليزي"""
    d = tmp_path / "مجلد عربي"; d.mkdir(); pdf = make_pdf(d / "كتاب.pdf", circle_fig())
    env = {"NO_PYMUPDF": "1"}
    r = run("crop", pdf, 1, 215, 300, 335, 420, d / "fig.png", env=env)
    if "pdftoppm" in r.stdout + r.stderr and r.returncode != 0 and "ما لقيت" in r.stdout + r.stderr:
        pytest.skip("pdftoppm غير موجود")
    assert r.returncode == 0, r.stdout + r.stderr
    a = Image.open(d / "fig.png"); run("crop", pdf, 1, 215, 300, 335, 420, d / "fig2.png")
    b = Image.open(d / "fig2.png")
    assert abs(a.width - b.width) <= 3 and abs(a.height - b.height) <= 3                  # نفس النتيجة تقريباً بالطريقتين
    assert run("page", pdf, 1, "--out", d / "o", env=env).returncode == 0


def test_no_renderer_available_message(tmp_path, monkeypatch):
    env = {"NO_PYMUPDF": "1", "PATH": os.path.dirname(sys.executable)}                    # ولا pdftoppm بالـ PATH
    r = run("crop", make_pdf(tmp_path / "c.pdf", circle_fig()), 1, 215, 300, 335, 420, tmp_path / "f.png", env=env)
    assert r.returncode != 0 and "pymupdf" in (r.stdout + r.stderr).lower()


def test_usage_when_no_args_or_unknown_command():
    assert "الأوامر" in run().stdout and "الأوامر" in run("frobnicate").stdout


# ============================ تكامل مع السيرفر ============================
def test_tool_output_works_inside_exam_questions(pkg, tmp_path):
    """صورة طلعت من الأداة ([img:p001_f1.png]) لازم تنقبل بالأسئلة وتنخدم للطلاب بدون تحذيرات"""
    from test_http import Server
    pdf = make_pdf(tmp_path / "book.pdf", circle_fig(), badge(1), text_at(150, 280, "Find the measure of the angle in the figure below"))
    _, idx, out = detect_cli(tmp_path, pdf)
    name = idx[0]["file"]
    (pkg.path / "images").mkdir(exist_ok=True); (pkg.path / "images" / name).write_bytes((out / name).read_bytes())
    rows = bank(); rows[0][0] = f"شاهد الشكل [img:{name}] ثم أجب"; rows[1][1] = f"[img:{name}]"
    pkg.questions(rows)
    r = subprocess.run([sys.executable, "-X", "utf8", "check_files.py"], cwd=pkg.path, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and "1 صورة" in pkg.p("check_report.txt").read_text(encoding="utf-8-sig")
    w = Server(pkg).start()
    try:
        st, _, body, hdr = w.get("/img/" + name)
        assert st == 200 and hdr["Content-Type"] == "image/png" and body[:8] == b"\x89PNG\r\n\x1a\n"
        from test_http import TEACHER
        ck = w.post("/login", {"password": "secret"}, TEACHER)[3]["Set-Cookie"].split(";")[0]
        assert f"/img/{name}" in w.get("/teacher", {"Cookie": ck})[2].decode("utf-8")              # صفحة الطالب ما فيها البنك؛ المعاينة فيها كل الأسئلة
    finally:
        w.stop()


def test_jpeg_output_is_accepted_by_server_too(pkg):
    from test_http import Server
    Image.frombytes("RGB", (400, 400), os.urandom(400 * 400 * 3)).save(pkg.path / "x.jpg", "JPEG", quality=85)
    pkg.image("fig.jpg", (pkg.path / "x.jpg").read_bytes())
    rows = bank(); rows[0][0] = "شاهد [img:fig.jpg]"; pkg.questions(rows)
    w = Server(pkg).start()
    try:
        st, _, _, hdr = w.get("/img/fig.jpg"); assert st == 200 and hdr["Content-Type"] == "image/jpeg"
    finally:
        w.stop()
