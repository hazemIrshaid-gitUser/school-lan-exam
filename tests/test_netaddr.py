"""عناوين الشبكة على جهاز المعلم: تصنيفها (أساسي/هوتسبوت ويندوز/وهمي/شبكة ثانية)، وعرض الروابط البديلة بالبانر وexam_info.txt و/link و/health.
كرت VirtualBox أو Hyper-V ما لازم يقلب فحص السيرفر أصفر (المعلم بيدوّر على «أخضر»)، بس هوتسبوت الجهاز أو شبكة ثانية حقيقية لازم يبيّنوا."""
import http.server, threading, urllib.request

import pytest

MAIN = "192.168.1.20"
CASES = [(MAIN, "main"), ("192.168.137.1", "hotspot"), ("192.168.56.1", "virtual"), ("172.16.0.1", "virtual"), ("172.31.255.254", "virtual"),
         ("172.24.208.1", "virtual"), ("172.15.0.1", "other"), ("172.32.0.1", "other"), ("10.0.0.5", "other"), ("192.168.1.30", "other"), ("192.168.0.7", "other")]


def with_ips(m, monkeypatch, *alts):
    monkeypatch.setattr(m, "lan_ips", lambda: (MAIN, sorted([MAIN, *alts])))
    monkeypatch.setattr(m, "ip", lambda: MAIN)


def net_warns(d): return [w for w in d["warnings"] if "شبكة" in w and "أكثر" in w]


def net_row(page):
    i = page.index("عناوين الشبكة بهذا الجهاز"); return page[page.rindex("<tr", 0, i):page.index("</tr>", i)]


@pytest.mark.parametrize("a,kind", CASES)
def test_ip_kind(srv, a, kind):
    assert srv.ip_kind(a, MAIN) == kind


def test_main_is_main_even_if_it_looks_like_hotspot_or_virtual(srv):
    """لو الجهاز ما عليه غير الهوتسبوت (أو شبكة 172.x) فهذا هو الأساسي، مش «تجاهله»"""
    assert srv.ip_kind("192.168.137.1", "192.168.137.1") == "main" and srv.ip_kind("172.20.1.5", "172.20.1.5") == "main"


def test_every_kind_has_labels(srv):
    for _, k in CASES: assert srv.IP_LABEL_AR[k] and srv.IP_LABEL_EN[k]


def test_single_network_is_green(srv, monkeypatch):
    with_ips(srv, monkeypatch)
    d = srv.health_data(); assert not net_warns(d) and d["ip_kinds"] == {MAIN: "main"}
    assert "<tr class=ok>" in net_row(srv.health_page(d))


def test_virtual_adapters_do_not_turn_health_yellow(srv, monkeypatch):
    with_ips(srv, monkeypatch, "192.168.56.1", "172.24.208.1")
    d = srv.health_data()
    assert not net_warns(d) and d["ip_kinds"] == {MAIN: "main", "192.168.56.1": "virtual", "172.24.208.1": "virtual"}
    row = net_row(srv.health_page(d))
    assert "<tr class=ok>" in row and row.count("تجاهلها") == 2 and "الشبكة الأساسية" in row and "192.168.56.1" in row


def test_hotspot_warns_and_names_it(srv, monkeypatch):
    with_ips(srv, monkeypatch, "192.168.137.1", "192.168.56.1")
    d = srv.health_data(); w = net_warns(d)
    assert len(w) == 1 and "هوتسبوت جهازك" in w[0] and d["level"] in ("warn", "bad")
    row = net_row(srv.health_page(d)); assert "<tr class=warn>" in row and "هوتسبوت ويندوز" in row and "تجاهلها" in row


def test_second_real_network_warns(srv, monkeypatch):
    with_ips(srv, monkeypatch, "10.0.0.5")
    w = net_warns(srv.health_data()); assert len(w) == 1 and "شبكة ثانية" in w[0] and "هوتسبوت" not in w[0]


def test_alt_links(srv, monkeypatch):
    with_ips(srv, monkeypatch, "192.168.137.1", "192.168.56.1")
    assert srv.alt_links(":8000") == [("http://192.168.137.1:8000", "hotspot"), ("http://192.168.56.1:8000", "virtual")]
    with_ips(srv, monkeypatch); assert srv.alt_links("") == []


def test_banner_and_exam_info_show_alternates(pkg, monkeypatch):
    m = pkg.load(); with_ips(m, monkeypatch, "192.168.137.1", "192.168.56.1")
    out = []; monkeypatch.setattr(m, "_real_print", lambda *a, **k: out.append(" ".join(map(str, a))), raising=False)
    monkeypatch.setattr(m, "REAL_CONSOLE", False)                                              # ما نفتح المفكرة
    m.show_console_banner(":8000"); con = "\n".join(out)
    assert "http://192.168.1.20:8000" in con and "Other link (Windows hotspot" in con and "http://192.168.137.1:8000" in con
    assert "192.168.56.1" not in con and not any("؀" <= c <= "ۿ" for c in con)       # الوهمي ما بيظهر بالنافذة، والنافذة بدون عربي
    info = pkg.p("exam_info.txt").read_text(encoding="utf-8-sig")
    assert "روابط بديلة" in info and "http://192.168.137.1:8000   ← هوتسبوت ويندوز" in info and "192.168.56.1:8000   ← شبكة وهمية" in info
    assert info.index("http://192.168.1.20:8000") < info.index("روابط بديلة") < info.index("صفحات المعلم")


def test_exam_info_has_no_alternates_section_on_single_network(pkg, monkeypatch):
    m = pkg.load(); with_ips(m, monkeypatch); monkeypatch.setattr(m, "_real_print", lambda *a, **k: None, raising=False); monkeypatch.setattr(m, "REAL_CONSOLE", False)
    m.show_console_banner("")
    info = pkg.p("exam_info.txt").read_text(encoding="utf-8-sig")
    assert "روابط بديلة" not in info and "        http://192.168.1.20\n\nصفحات المعلم" in info


def test_link_page_shows_hotspot_but_not_virtual(pkg, monkeypatch):
    m = pkg.load(); with_ips(m, monkeypatch, "192.168.137.1", "192.168.56.1"); monkeypatch.setattr(m, "PORT", 8123)
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), m.H); threading.Thread(target=s.serve_forever, daemon=True).start()
    try:
        t = urllib.request.urlopen(f"http://127.0.0.1:{s.server_address[1]}/link", timeout=10).read().decode("utf-8")
        assert "http://192.168.1.20:8123</div>" in t and "هوتسبوت ويندوز" in t and "http://192.168.137.1:8123" in t and "192.168.56.1" not in t
        with_ips(m, monkeypatch)
        t = urllib.request.urlopen(f"http://127.0.0.1:{s.server_address[1]}/link", timeout=10).read().decode("utf-8")
        assert "http://192.168.1.20:8123</div>" in t and "هوتسبوت" not in t
    finally:
        s.shutdown(); s.server_close()


# ============================ ip() بدون طريق افتراضي ============================
class NoRoute:
    """سوكيت وهمي: الجهاز ما عليه بوابة/راوتر، فـ connect بيفشل (مثل هوتسبوت بدون إنترنت أو شبكة بدون راوتر)"""
    def __init__(self, *a): pass
    def connect(self, addr): raise OSError(10051, "network unreachable")
    def close(self): pass


def adapters(*ips): return lambda host, port, fam=0, *a: [(fam, 2, 17, "", (x, 0)) for x in ips]


@pytest.mark.parametrize("ips,want", [
    (("127.0.0.1", "192.168.56.1", "192.168.137.1", "169.254.7.7"), "192.168.137.1"),        # الهوتسبوت أولاً
    (("192.168.56.1", "10.1.2.3"), "10.1.2.3"),                                                # شبكة حقيقية قبل الوهمية
    (("10.0.0.9", "192.168.137.1", "192.168.1.5"), "192.168.137.1"),                          # الهوتسبوت قبل شبكة ثانية
    (("192.168.56.1",), "192.168.56.1"),                                                       # أحسن من 127
    (("127.0.0.1", "169.254.1.1"), "127.0.0.1"),                                               # ما في شي: بنضل على 127 (والفحص بيقول «ما في عنوان شبكة»)
])
def test_ip_without_default_route_picks_best_adapter(srv, monkeypatch, ips, want):
    monkeypatch.setattr(srv.socket, "socket", NoRoute); monkeypatch.setattr(srv.socket, "getaddrinfo", adapters(*ips))
    assert srv.ip() == want


def test_ip_without_default_route_and_no_hostname(srv, monkeypatch):
    def boom(*a): raise OSError("no host")
    monkeypatch.setattr(srv.socket, "socket", NoRoute); monkeypatch.setattr(srv.socket, "getaddrinfo", boom)
    assert srv.ip() == "127.0.0.1"


def test_ip_with_default_route_is_unchanged(srv, monkeypatch):
    class Routed(NoRoute):
        def connect(self, addr): assert addr == ("10.255.255.255", 1)
        def getsockname(self): return ("192.168.1.20", 50000)
    monkeypatch.setattr(srv.socket, "socket", Routed); monkeypatch.setattr(srv.socket, "getaddrinfo", adapters("192.168.137.1", "192.168.1.20"))
    assert srv.ip() == "192.168.1.20"


def test_hotspot_only_pc_gets_hotspot_as_main_link(srv, monkeypatch):
    monkeypatch.setattr(srv.socket, "socket", NoRoute); monkeypatch.setattr(srv.socket, "getaddrinfo", adapters("192.168.137.1", "192.168.56.1"))
    main, ips = srv.lan_ips()
    assert main == "192.168.137.1" and srv.ip_kind(main, main) == "main" and srv.alt_links("") == [("http://192.168.56.1", "virtual")]
    d = srv.health_data(); assert d["student_url"] == "http://192.168.137.1" + ("" if srv.PORT == 80 else f":{srv.PORT}") and not net_warns(d)
