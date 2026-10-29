"""بيانات التقارير (بدون كتابة ملفات): صفوف الطلاب، تحليل الأسئلة، إحصاء الشعب، وملف Excel. كل دالة بتاخذ ctx."""
import io, time, zipfile, html
from collections import Counter, defaultdict
from .constants import L, LVL
from .domain import fmt_dur
from .text import noimg
from .util import E, num

def find_keys(ctx):
    idx = {}
    for k in list(ctx.CLAIMS) + list(ctx.SUBS):
        p = k.split("|")
        if len(p) >= 4: idx[(p[-3], p[-2], p[-1])] = k
    return idx
def student_rows(ctx):
    """كل طالب بالقائمة + حالته"""
    idx, now, rows = find_keys(ctx), time.time(), []
    for g, secs in ctx.ROSTER.items():
        for s, names in secs.items():
            for n in names:
                k = idx.get((g, s, n)); r = {"grade": g, "section": s, "name": n, "key": k, "status": "none"}
                if k in ctx.SUBS:
                    sub = ctx.SUBS[k]; r.update(status="done", score=sub["score"], total=sub["total"], leave=sub.get("leave", ""), late=sub.get("late", 0), durtxt=fmt_dur(ctx, sub.get("dur")))
                elif k in ctx.CLAIMS:
                    lv = ctx.LIVE.get(k)
                    if lv:
                        ago = now - lv["t"]
                        r.update(status="live" if ago < 25 else "lost", answered=lv["answered"], total=lv["total"], remain=lv["remain"],
                                 leaveN=lv["leaveN"], leaveSec=lv["leaveSec"], ago=int(ago))
                    else: r.update(status="lost", ago=None)
                    if "paused" in ctx.PAPERS.get(k, {}): r["paused"] = int(now - ctx.PAPERS[k]["paused"])      # موقوف مؤقتاً من المعلم (ثواني منذ الإيقاف)
                rows.append(r)
    return rows
def question_stats(ctx):
    app, cor, wr = Counter(), Counter(), defaultdict(Counter)
    for sub in ctx.SUBS.values():
        for n, v in zip(sub["ids"], sub["answers"]):
            if n not in ctx.BANK: continue
            app[n] += 1
            if v == ctx.BANK[n]["a"]: cor[n] += 1
            else: wr[n][v] += 1
    out = []
    for n, q in ctx.BANK.items():
        a = app[n]
        top = wr[n].most_common(1)
        topw = ""
        if top:
            v, c = top[0]
            topw = noimg("بدون إجابة" if v < 0 else f"{L[v]}) {q['o'][v]}") + f"  ({c})"
        pct = round(100 * cor[n] / a) if a else None
        note = ""
        if a >= 5 and pct is not None:
            if pct < 30: note = "نسبة نجاح منخفضة جداً — راجع صياغة السؤال/الجواب"
            elif pct > 95: note = "سهل جداً"
        out.append({"n": n, "level": q["level"], "page": q.get("page", ""), "appeared": a, "pct": pct, "top_wrong": topw, "note": note})
    return out
def section_stats(ctx):
    d = defaultdict(list); tot = Counter()
    for r in student_rows(ctx):
        tot[(r["grade"], r["section"])] += 1
        if r["status"] == "done": d[(r["grade"], r["section"])].append(r["score"] / r["total"] * 100 if r["total"] else 0)
    res = []
    for (g, s), n in tot.items():
        v = d.get((g, s), [])
        res.append({"grade": g, "section": s, "students": n, "submitted": len(v),
                    "avg": round(sum(v) / len(v), 1) if v else None, "max": round(max(v)) if v else None, "min": round(min(v)) if v else None,
                    "dist": [sum(1 for x in v if lo <= x < lo + 20 or (lo == 80 and x == 100)) for lo in (0, 20, 40, 60, 80)]})
    return res
def xlsx_bytes(ctx, sheets):
    def col(i):
        s = ""; i += 1
        while i: i, r = divmod(i - 1, 26); s = chr(65 + r) + s
        return s
    def cell(ref, v):
        if isinstance(v, (int, float)) and not isinstance(v, bool): return f'<c r="{ref}"><v>{v}</v></c>'
        t = html.escape(str(v if v is not None else ""))
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{t}</t></is></c>'
    z = io.BytesIO(); zf = zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED)
    n = len(sheets)
    zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + "".join(f'<Override PartName="/xl/worksheets/sheet{i+1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(n)) + "</Types>")
    zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
    zf.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + "".join(f'<sheet name="{html.escape(nm)}" sheetId="{i+1}" r:id="rId{i+1}"/>' for i, (nm, _, _) in enumerate(sheets)) + "</sheets></workbook>")
    zf.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(f'<Relationship Id="rId{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i+1}.xml"/>' for i in range(n)) + f'<Relationship Id="rId{n+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    zf.writestr("xl/styles.xml", '<?xml version="1.0" encoding="UTF-8"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Arial"/></font><font><b/><sz val="11"/><name val="Arial"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
    for i, (nm, widths, rows) in enumerate(sheets):
        x = ['<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView rightToLeft="1" workbookViewId="0"/></sheetViews><cols>']
        x += [f'<col min="{j+1}" max="{j+1}" width="{w}" customWidth="1"/>' for j, w in enumerate(widths)]
        x.append("</cols><sheetData>")
        for r, row in enumerate(rows, 1):
            x.append(f'<row r="{r}">' + "".join(cell(f"{col(c)}{r}", v).replace("<c ", '<c s="1" ', 1) if r == 1 else cell(f"{col(c)}{r}", v) for c, v in enumerate(row)) + "</row>")
        x.append("</sheetData></worksheet>")
        zf.writestr(f"xl/worksheets/sheet{i+1}.xml", "".join(x))
    zf.close(); return z.getvalue()
def build_xlsx(ctx):
    st = {"done": "سلّم", "live": "يمتحن", "lost": "بدأ ولم يسلّم", "none": "لم يبدأ"}
    sheets = []
    ss = section_stats(ctx)
    sheets.append(("ملخص", [10, 10, 12, 12, 14, 12, 12], [["الصف", "الشعبة", "عدد الطلاب", "سلّموا", "المتوسط %", "الأعلى %", "الأقل %"]] + [[r["grade"], r["section"], r["students"], r["submitted"], r["avg"] if r["avg"] is not None else "", r["max"] if r["max"] is not None else "", r["min"] if r["min"] is not None else ""] for r in ss]))
    rows = student_rows(ctx)
    for (g, s) in sorted({(r["grade"], r["section"]) for r in rows}):
        sh = [["م", "الاسم", "العلامة", "من", "النسبة %", "الحالة", "الخروج من الصفحة", "التأخير (ث)", "مدة الحل"]]
        for i, r in enumerate([r for r in rows if r["grade"] == g and r["section"] == s], 1):
            if r["status"] == "done": sh.append([i, r["name"], r["score"], r["total"], round(100 * r["score"] / r["total"]) if r["total"] else 0, st["done"], r["leave"], r["late"] or "", r["durtxt"]])
            else: sh.append([i, r["name"], "", "", "", st[r["status"]], "", "", ""])
        sheets.append((f"الشعبة {s}", [5, 40, 10, 8, 12, 16, 22, 12, 16], sh))
    qs = sorted(question_stats(ctx), key=lambda r: (r["pct"] is None, r["pct"] if r["pct"] is not None else 0))
    sheets.append(("تحليل الأسئلة", [8, 10, 10, 12, 14, 50, 45], [["السؤال", "المستوى", "الصفحة", "مرات الظهور", "نسبة الصح %", "أكثر إجابة خاطئة (العدد)", "ملاحظة"]] + [[r["n"], LVL.get(r["level"], ""), r["page"], r["appeared"], r["pct"] if r["pct"] is not None else "", r["top_wrong"], r["note"]] for r in qs]))
    return xlsx_bytes(ctx, sheets)
