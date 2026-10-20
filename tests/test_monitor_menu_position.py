"""قائمة ⋯ لصف الطالب بشاشة المراقبة الجديدة: لازم تظهر كاملة فوق كل شي، حتى لو كان بالجدول صف وحدة بس (إطار الجدول كان بيقصّها فيحتاج scroll)،
وتفتح لتحت أو لفوق حسب المكان، وتضل جوا الشاشة (حتى على الجوال)، وتنسكّر بـ Escape أو لما الصفحة تتحرّك أو يتغيّر حجمها."""
import threading

import pytest
from test_http import Server
from test_browser import browser, url  # noqa: F401  (fixture)

pw = pytest.importorskip("playwright.sync_api")
A1 = "طالب أ1"


@pytest.fixture
def lone(pkg, browser):
    """سيرفر فيه طالب واحد بس «يمتحن» (زي صورة المشكلة) وصفحة المراقبة مفتوحة عليه؛ بيرجّع (الصفحة، دالة لتغيير حجم النافذة)"""
    from test_monitor_new_ui import Ui, with_ui
    with_ui(pkg); w = Server(pkg).start()
    k, _, p = w.start_student("d1", n=A1); stop = threading.Event()
    def alive():
        while not stop.is_set():
            try: w.post("/ping", {"key": k, "dev": "d1", "answered": 0, "total": 8, "remain": 1700, "ans": {}})
            except Exception: pass
            stop.wait(2.5)
    threading.Thread(target=alive, daemon=True).start()
    ui = Ui(browser, w); ui.pg.wait_for_selector("tbody tr .kebab")
    try:
        yield ui.pg
    finally:
        stop.set(); ui.close(); w.stop()


def open_menu(pg):
    pg.locator("tbody tr", has_text=A1).locator("button.kebab").click(); pg.wait_for_selector(".row-popup")


def items_inside_screen(pg):
    """كل بند بالقائمة: داخل حدود الشاشة، وأي نقطة بوسطه بيلمسها هو (يعني مش مقصوص ولا تحت عنصر ثاني)"""
    return pg.evaluate("""()=>[...document.querySelectorAll('.row-popup button,.row-popup a')].map(e=>{
        const r=e.getBoundingClientRect(),el=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
        return {t:e.textContent.trim(),inside:r.top>=0&&r.left>=0&&r.bottom<=innerHeight&&r.right<=innerWidth,reachable:!!el&&e.contains(el)}})""")


def test_menu_is_fully_visible_with_a_single_student(lone):
    pg = lone; open_menu(pg)
    got = items_inside_screen(pg); assert len(got) >= 4, got
    assert all(g["inside"] and g["reachable"] for g in got), got                                    # كل البنود ظاهرة وقابلة للضغط بدون scroll
    assert pg.evaluate("(()=>{const s=document.querySelector('.table-scroll');return s.scrollHeight<=s.clientHeight+1})()")      # وإطار الجدول ما صار فيه scroll بسبب القائمة


def test_menu_opens_upwards_when_there_is_no_room_below(lone):
    pg = lone; pg.set_viewport_size({"width": 1366, "height": 400}); pg.wait_for_timeout(300)
    pg.evaluate("window.scrollTo(0, 0)"); open_menu(pg)
    got = items_inside_screen(pg); assert all(g["inside"] and g["reachable"] for g in got), got
    box = pg.locator(".row-popup").bounding_box(); kb = pg.locator("tbody tr", has_text=A1).locator("button.kebab").bounding_box()
    assert box["y"] + box["height"] <= kb["y"] + 4, (box, kb)                                      # فوق الزر (ما في مكان تحته)


def test_menu_opens_downwards_when_there_is_room(lone):
    pg = lone; open_menu(pg)
    box = pg.locator(".row-popup").bounding_box(); kb = pg.locator("tbody tr", has_text=A1).locator("button.kebab").bounding_box()
    assert box["y"] >= kb["y"] + kb["height"] - 2, (box, kb)                                       # تحت الزر لما في مكان


def test_menu_stays_inside_a_phone_screen(lone):
    pg = lone; pg.set_viewport_size({"width": 375, "height": 800}); pg.wait_for_timeout(400)
    open_menu(pg); got = items_inside_screen(pg)
    assert got and all(g["inside"] and g["reachable"] for g in got), got


def test_menu_closes_on_escape_scroll_and_resize(lone):
    pg = lone
    open_menu(pg); pg.keyboard.press("Escape"); assert pg.locator(".row-popup").count() == 0
    open_menu(pg); pg.evaluate("window.dispatchEvent(new Event('scroll'))"); pg.wait_for_timeout(200); assert pg.locator(".row-popup").count() == 0       # الصفحة تحرّكت
    open_menu(pg); pg.set_viewport_size({"width": 1200, "height": 700}); pg.wait_for_timeout(300); assert pg.locator(".row-popup").count() == 0           # تغيّر الحجم
    open_menu(pg); pg.locator("h1, header").first.click(); pg.wait_for_timeout(200); assert pg.locator(".row-popup").count() == 0                        # ضغطة برا


def test_menu_stays_inside_a_very_short_window(lone):
    """نافذة قصيرة جداً (ما في مكان كافي فوق الزر ولا تحته): القائمة بتنحشر جوا الشاشة وكل بنودها بتضل ظاهرة"""
    pg = lone; pg.set_viewport_size({"width": 1366, "height": 260}); pg.wait_for_timeout(300)
    open_menu(pg); got = items_inside_screen(pg)
    assert got and all(g["inside"] and g["reachable"] for g in got), got
