"""قفل الكيبورد وقت الامتحان (منع_الكيبورد): من لحظة ظهور الأسئلة لحد التسليم الصفحة بتتجاهل كل كبسات الكيبورد؛ قبل البداية وبعد التسليم الكيبورد شغال.
الإعداد افتراضياً «نعم»، وبمعاينة المعلم مطفي. بيتحكم فيه الإعداد «منع_الكيبورد»."""
import pytest
from conftest import DEFAULT_SETTINGS
from test_browser import browser, login, phone, solve, submit, url, web  # noqa: F401  (fixtures)
from test_browser import Server

KEYS = ("a", "Enter", "Tab", "Escape", "ArrowLeft", " ", "F5", "F12", "Backspace", "1")

# بيرسل كبسة اصطناعية ويرجّع هل انمنعت (defaultPrevented)
SEND = """([t,k,ctrl])=>{const e=new KeyboardEvent(t,{key:k,ctrlKey:ctrl,cancelable:true,bubbles:true});document.dispatchEvent(e);return e.defaultPrevented}"""


def blocked(page, t, k, ctrl=False): return page.evaluate(SEND, [t, k, ctrl])


@pytest.fixture
def locked(pkg, phone):
    pkg.settings(**{"منع_الكيبورد": "نعم"}); w = Server(pkg).start()
    try:
        yield w, phone
    finally:
        w.stop()


def test_every_key_is_blocked_while_the_questions_are_showing(locked):
    w, phone = locked
    page = phone(); login(page, w)
    for k in KEYS:
        for t in ("keydown", "keypress", "keyup"):
            assert blocked(page, t, k), (t, k)
    for k in ("a", "c", "r", "w", "p"):
        assert blocked(page, "keydown", k, ctrl=True), k


def test_keyboard_works_before_start_and_after_submit(locked):
    w, phone = locked
    page = phone(); page.goto(url(w))
    assert not blocked(page, "keydown", "a")                              # شاشة اختيار الاسم
    page.select_option("#g", "العاشر"); page.select_option("#sec", "أ"); page.select_option("#nm", "طالب أ1")
    page.click("#start"); page.wait_for_selector("#s-exam:not(.hide)")
    assert blocked(page, "keydown", "a")
    solve(page); submit(page)
    page.wait_for_function("document.getElementById('status').textContent.includes('✓')")
    assert not blocked(page, "keydown", "a")                              # بعد التسليم رجع شغال


def test_blocked_keys_do_not_reach_the_submit_modal_or_other_handlers(locked):
    w, phone = locked
    page = phone(); login(page, w); solve(page)
    from test_browser import ask_submit
    ask_submit(page)
    page.keyboard.press("Escape")
    assert page.is_visible("#confirm-submit")                             # Escape ما بيسكّر النافذة؛ بالضغط بس
    page.click("#cs-no"); assert page.is_hidden("#confirm-submit")


def test_default_is_on_and_off_switch_works(pkg, phone):
    lines = [f"{k} = {v}" for k, v in DEFAULT_SETTINGS.items() if k != "منع_الكيبورد"]
    pkg.raw_settings("\n".join(lines) + "\n")                              # الملف ما فيه الإعداد: الافتراضي «نعم»
    w = Server(pkg).start()
    try:
        page = phone(); login(page, w)
        assert blocked(page, "keydown", "a")
    finally:
        w.stop()
    pkg.settings(**{"منع_الكيبورد": "لا"}); w = Server(pkg).start()
    try:
        page = phone(); login(page, w, name="طالب أ2")                    # أ1 محجوز من التشغيل الأول
        assert not blocked(page, "keydown", "a")
    finally:
        w.stop()


def test_printscreen_wipes_the_clipboard(locked):
    w, phone = locked
    page = phone(); login(page, w)
    page.evaluate("()=>{window.__wiped=0; const o=window.wipeClipboard; window.wipeClipboard=function(){window.__wiped++; return o()}}")
    blocked(page, "keyup", "PrintScreen"); blocked(page, "keyup", "a")
    assert page.evaluate("window.__wiped") == 1                            # PrintScreen بس


def test_bad_value_is_rejected(pkg):
    pkg.settings(**{"منع_الكيبورد": "ربما"})
    pkg.expect_error("منع_الكيبورد")


def test_teacher_preview_is_not_locked(pkg):
    pkg.settings(**{"منع_الكيبورد": "نعم"}); srv = pkg.load()
    assert "keyLock: false" in srv.ctx.PREVIEW and "keyLock: true" in srv.ctx.PAGE
