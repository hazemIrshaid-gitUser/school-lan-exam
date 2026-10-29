"""قراءة ملفات المعلم (xlsx بدون مكتبات، أو csv): بترجّع صفوفاً من نصوص."""
import csv, io, os, re, zipfile
import xml.etree.ElementTree as ET
from .util import DataError

def _fmt_kind(fid, code):
    """نوع تنسيق خلية الأرقام بإكسل: تاريخ أو نسبة (غير هيك = رقم عادي)"""
    if fid == 9: return ("pct", 0)
    if fid == 10: return ("pct", 2)
    if fid in _BUILTIN_DATE_FMT: return ("date", fid in (18, 19, 20, 21, 22, 45, 46, 47))
    if not code: return None
    c = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.|\*.', "", code).lower()
    if "%" in c:
        m = re.search(r"\.([0#?]+)", c)
        return ("pct", len(m.group(1)) if m else 0)
    if re.search(r"[ymdhs]", c) and "general" not in c:
        return ("date", bool(re.search(r"[hs]", c)))
    return None
_BUILTIN_DATE_FMT = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))
def _xl_date(v, d1904, has_time):
    """الرقم التسلسلي لتاريخ إكسل -> نص (2026-01-02) أو (14:30) للوقت فقط"""
    import datetime
    f = float(v)
    dt = (datetime.datetime(1904, 1, 1) if d1904 else datetime.datetime(1899, 12, 30)) + datetime.timedelta(seconds=round(f * 86400))      # تقريب للثانية: 14:30 بإكسل بيتخزن 0.6041666666666666
    if has_time and 0 <= f < 1: return dt.strftime("%H:%M")
    s = "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)
    return s + dt.strftime(" %H:%M") if (has_time and f != int(f)) else s       # الوقت بس لو في كسر يوم (منتصف الليل بالضبط = تاريخ فقط)
def _pct_text(v, dec):
    x = round(float(v) * 100, dec)
    return (("%.*f" % (dec, x)) if dec else str(int(round(x)))) + "%"
def read_table(path, want=()):
    """يرجع قائمة صفوف (كل صف قائمة نصوص). xlsx بدون مكتبات، أو csv.
    want: كلمات بترويسة الجدول المطلوب (مثلاً «السؤال»): لو الملف فيه أكثر من ورقة بنختار الورقة اللي ترويستها فيها واحدة منها، وإلا أول ورقة ظاهرة"""
    if path.lower().endswith(".csv"):
        raw = open(path, "rb").read()
        try: txt = raw.decode("utf-8-sig")
        except UnicodeDecodeError: txt = raw.decode("cp1256")
        txt = txt.replace("\r\n", "\n").replace("\r", "\n")                 # «CSV (Macintosh)» أسطره CR فقط
        try: dia = csv.Sniffer().sniff(txt[:2000], delimiters=",;\t")
        except Exception: dia = csv.excel
        return [[c.strip() for c in r] for r in csv.reader(io.StringIO(txt), dia)]
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    M = "{%s}" % ns["m"]
    z = zipfile.ZipFile(path)
    names = z.namelist()
    sst = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            sst.append("".join(t.text or "" for t in si.iter(M + "t")))
    xf_kind = []                                                            # تنسيق كل خلية: تاريخ/نسبة (عشان ما يشوف الطالب الرقم التسلسلي 17534 أو 0.25 بدل 25%)
    if "xl/styles.xml" in names:
        st = ET.fromstring(z.read("xl/styles.xml"))
        custom = {int(n.attrib["numFmtId"]): n.attrib.get("formatCode", "") for n in st.iter(M + "numFmt")}
        cx = st.find("m:cellXfs", ns)
        for xf in (list(cx) if cx is not None else []):
            fid = int(xf.attrib.get("numFmtId", 0)); xf_kind.append(_fmt_kind(fid, custom.get(fid)))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    pr = wb.find("m:workbookPr", ns)
    d1904 = pr is not None and pr.attrib.get("date1904") in ("1", "true")
    rels = {r.attrib["Id"]: r.attrib["Target"] for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    sheets = []
    for sh in wb.find("m:sheets", ns):
        t = rels[sh.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]].lstrip("/")
        sheets.append((t if t.startswith("xl/") else "xl/" + t, sh.attrib.get("state", "visible")))

    def parse(target):
        rows = []
        for row in ET.fromstring(z.read(target)).iter(M + "row"):
            ri = int(row.attrib.get("r", len(rows) + 1))
            while len(rows) < ri - 1: rows.append([])                       # الصف الفاضي بالنص ما بينكتب بالملف: نحفظ مكانه عشان أرقام الأسطر بالرسائل تظل صح
            cells, last = {}, -1
            for c in row.findall("m:c", ns):
                if c.attrib.get("r"):
                    ci = 0
                    for ch in re.match(r"([A-Z]+)", c.attrib["r"]).group(1): ci = ci * 26 + ord(ch) - 64
                    ci -= 1
                else: ci = last + 1
                last = ci
                t = c.attrib.get("t")
                if t == "inlineStr": v = "".join(x.text or "" for x in c.iter(M + "t"))
                else:
                    ve = c.find("m:v", ns); v = ve.text if ve is not None and ve.text is not None else ""
                    if t == "s" and v != "": v = sst[int(v)]
                    elif t == "b": v = "TRUE" if v == "1" else "FALSE"      # كلمة TRUE/FALSE بإكسل بتتحوّل لقيمة منطقية: ما نعرضها للطالب «1» و«0»
                    elif t not in ("str", "e") and v:
                        try:
                            f = float(v); s_i = int(c.attrib.get("s", 0)); kind = xf_kind[s_i] if s_i < len(xf_kind) else None
                            if kind and kind[0] == "date": v = _xl_date(v, d1904, kind[1])
                            elif kind and kind[0] == "pct": v = _pct_text(v, kind[1])
                            elif f == int(f): v = str(int(f))
                            else:
                                g = "%.15g" % f; v = v if "e" in g else g   # 0.1+0.2 بإكسل = 0.30000000000000004: نعرضه 0.3 مثل إكسل
                        except (ValueError, OverflowError): pass
                cells[ci] = v.strip()
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
        return rows
    order = [s for s in sheets if s[1] == "visible"] + [s for s in sheets if s[1] != "visible"]
    if want:
        for target, _ in order:
            rows = parse(target)
            if rows and any(w in (c or "").strip().lower() for c in rows[0] for w in want): return rows
    return parse(order[0][0])
def find_file(base, stem):
    for ext in (".xlsx", ".csv"):
        p = os.path.join(base, stem + ext)
        if os.path.exists(p): return p
    raise DataError(f"ملف {stem}.xlsx (أو {stem}.csv) غير موجود جنب server.py\n(File {stem}.xlsx or {stem}.csv not found next to server.py)")
