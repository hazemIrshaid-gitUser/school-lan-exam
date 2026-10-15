# -*- coding: utf-8 -*-
"""
أداة استخراج الأشكال والصور من كتاب PDF لاستعمالها بالأسئلة.
بيشغّلها Claude أثناء تجهيز الامتحان (الأستاذ ما بحتاج يشغّلها بنفسه).

الأوامر:
  python figures_tool.py detect BOOK.pdf 38-42 [--out figs] [--dpi 170]
      بيكتشف الأشكال تلقائياً بالصفحات ويقصّها صوراً جاهزة + overview لكل صفحة + index.json
      (رقم السؤال المكتوب على الشكل إن وُجد، والنص اللي حوله، ومكانه بالصفحة)
  python figures_tool.py page BOOK.pdf 40 [--out figs] [--dpi 110]
      بيرسم الصفحة مع شبكة إحداثيات (بوحدة نقطة PDF، الصفحة ~ 595 x 794) لتحديد مكان الشكل بالنظر
  python figures_tool.py crop BOOK.pdf 40 x0 y0 x1 y1 out.png [--dpi 170]
      بيقصّ منطقة محددة (بنفس إحداثيات شبكة أمر page) ويحفظها صورة
  python figures_tool.py info BOOK.pdf
      عدد الصفحات ومقاسها

يعمل بمكتبة PyMuPDF إن وُجدت (pip install pymupdf) — وهي اللازمة لأمر detect.
بدونها بيستعمل pdftoppm (من poppler) لأوامر page و crop.
بحاجة لـ Pillow (PIL) بكل الأحوال.
"""
import os, sys, json, shutil, subprocess, tempfile, glob, re, warnings

warnings.filterwarnings("ignore")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    sys.exit("هالأداة بحاجة لمكتبة Pillow:  pip install pillow")
try:
    if os.environ.get("NO_PYMUPDF"):
        raise ImportError
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
except Exception:
    fitz = None

_ASCII_COPY = {}     # نسخة مؤقتة من الكتاب باسم إنجليزي (للـ fallback)
MAX_W = 900          # أقصى عرض لصورة الشكل بالبكسل (نحافظ على حجم صغير للهاتف)
BIG_KB = 300         # لو صورة PNG أكبر من هيك نحوّلها JPEG


# ---------------------------------------------------------------- رسم الصفحات
def parse_pages(spec, n):
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    bad = [p for p in out if not 1 <= p <= n]
    if bad:
        sys.exit(f"أرقام صفحات خارج الكتاب (عدد الصفحات {n}): {bad}")
    return out


def page_count(pdf):
    if fitz:
        return len(fitz.open(pdf))
    try:
        from pypdf import PdfReader
        return len(PdfReader(pdf).pages)
    except Exception:
        out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout
        m = re.search(r"Pages:\s+(\d+)", out)
        if m:
            return int(m.group(1))
    sys.exit("تعذّر قراءة عدد صفحات الملف")


def render_page(pdf, pno, dpi):
    """يرجّع (صورة PIL للصفحة كاملة، عرض الصفحة بالنقاط، ارتفاعها بالنقاط)"""
    if fitz:
        page = fitz.open(pdf)[pno - 1]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return img, page.rect.width, page.rect.height
    tmp = tempfile.mkdtemp(prefix="figtool_")
    try:
        src = pdf
        try:
            pdf.encode("ascii")
        except UnicodeEncodeError:                            # pdftoppm على ويندوز ما بيقبل أسماء ملفات عربية: ننسخ الكتاب باسم إنجليزي
            if pdf not in _ASCII_COPY or not os.path.exists(_ASCII_COPY[pdf]):
                keep = tempfile.mkdtemp(prefix="figtool_book_")
                _ASCII_COPY[pdf] = os.path.join(keep, "book.pdf")
                shutil.copyfile(pdf, _ASCII_COPY[pdf])
            src = _ASCII_COPY[pdf]
        subprocess.run(["pdftoppm", "-r", str(dpi), "-f", str(pno), "-l", str(pno), "-png", src, os.path.join(tmp, "p")],
                       check=True, capture_output=True)
        fn = glob.glob(os.path.join(tmp, "p*.png"))[0]
        img = Image.open(fn).convert("RGB")
        img.load()
        return img, img.width * 72.0 / dpi, img.height * 72.0 / dpi
    except FileNotFoundError:
        sys.exit("ما لقيت PyMuPDF ولا pdftoppm. ثبّت واحداً منهما:  pip install pymupdf")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def font(size):
    for f in ("arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            pass
    return ImageFont.load_default()


def draw_grid(img, wpt, hpt, step=50):
    """شبكة إحداثيات بالنقاط فوق الصفحة، ليقرأ Claude مكان الشكل بدقة"""
    d = ImageDraw.Draw(img, "RGBA")
    sx, sy = img.width / wpt, img.height / hpt
    f = font(max(11, int(img.width / 70)))
    def label(xy, txt, color):
        b = d.textbbox(xy, txt, font=f)
        d.rectangle((b[0] - 2, b[1] - 1, b[2] + 2, b[3] + 1), fill=(255, 255, 255, 235))
        d.text(xy, txt, fill=color, font=f)

    x = 0
    while x <= wpt:
        d.line([(x * sx, 0), (x * sx, img.height)], fill=(220, 30, 30, 110 if x % 100 == 0 else 55), width=1)
        label((x * sx + 3, 3), str(int(x)), (200, 0, 0, 255))
        x += step
    y = 0
    while y <= hpt:
        d.line([(0, y * sy), (img.width, y * sy)], fill=(30, 30, 220, 110 if y % 100 == 0 else 55), width=1)
        label((3, y * sy + 3), str(int(y)), (0, 0, 200, 255))
        y += step
    return img


# ---------------------------------------------------------------- حفظ صورة الشكل
def save_figure(img, path):
    """يصغّر العرض إن لزم، ويحفظ PNG (أو JPEG للصور الفوتوغرافية الكبيرة)"""
    if img.width > MAX_W:
        img = img.resize((MAX_W, round(img.height * MAX_W / img.width)), Image.LANCZOS)
    img = img.convert("RGB")
    pal = img.quantize(colors=96, method=Image.Quantize.MEDIANCUT).convert("RGB") if False else None
    img.save(path, "PNG", optimize=True)
    if os.path.getsize(path) > BIG_KB * 1024:
        jp = os.path.splitext(path)[0] + ".jpg"
        img.save(jp, "JPEG", quality=85, optimize=True)
        os.remove(path)
        return jp
    return path


# ---------------------------------------------------------------- اكتشاف الأشكال (PyMuPDF)
def group_rects(rects, gap):
    """يدمج المستطيلات المتداخلة أو القريبة (ضمن gap نقطة) بمجموعات"""
    n = len(rects)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    inflated = [r + (-gap, -gap, gap, gap) for r in rects]
    order = sorted(range(n), key=lambda k: inflated[k].x0)      # مسح من اليسار: بدل مقارنة كل زوج (صفحات فيها آلاف المسارات كانت بطيئة)
    for a in range(n):
        i = order[a]
        for b in range(a + 1, n):
            j = order[b]
            if inflated[j].x0 > inflated[i].x1:
                break
            if inflated[i].intersects(inflated[j]):
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def is_badge(d):
    """دائرة صفراء صغيرة فيها رقم السؤال (بالكتب الأردنية): نستثنيها من الشكل ونسجّل رقمها"""
    fill = d.get("fill")
    r = d["rect"]
    if not fill or max(r.width, r.height) > 30 or min(r.width, r.height) < 8:
        return False
    return fill[0] > 0.85 and fill[1] > 0.65 and fill[2] < 0.45


def detect(page):
    W, H = page.rect.width, page.rect.height
    drawings = page.get_drawings()
    badges = []
    for d in drawings:
        if is_badge(d):
            r = d["rect"]
            txt = page.get_text("text", clip=r).strip()
            badges.append((r, txt))
    items = []
    for d in drawings:
        r = d["rect"] & page.rect
        if r.is_empty or is_badge(d):
            continue
        if r.width > W * 0.7 or r.height > H * 0.55:         # شرائط وإطارات وخلفيات الصفحة
            continue
        if r.y1 < 55 or r.y0 > H - 55:                        # رأس وتذييل الصفحة
            continue
        items.append(r)
    for img in page.get_image_info():
        r = fitz.Rect(img["bbox"]) & page.rect
        if r.width <= 40 or r.height <= 40:                   # أيقونات صغيرة
            continue
        if r.width > W * 0.7 or r.width * r.height > W * H * 0.15:   # خلفيات وإطارات كبيرة
            continue
        if r.y0 < 60:                                         # ترويسة الصفحة
            continue
        items.append(r)

    def too_big(c):
        return c.width > W * 0.8 or c.height > H * 0.5

    def build(idx, gaps):
        """يجمّع العناصر القريبة؛ وأي تجمّع ضخم (غالباً خلفية الصفحة) يُعاد تفتيته بمسافة أصغر"""
        res = []
        sub = [items[i] for i in idx]
        for g in group_rects(sub, gaps[0]):
            members = [idx[i] for i in g]
            c = fitz.Rect()
            for i in members:
                c |= items[i]
            if too_big(c) and len(gaps) > 1:
                res += build(members, gaps[1:])
            else:
                res.append(c)
        return res

    clusters = build(list(range(len(items))), (14, 7, 3))
    figs = []
    labels = []
    for b in page.get_text("dict")["blocks"]:                 # تسميات الشكل: أسطر نص قصيرة جداً (زاوية 78°، نقطة O، محور x...)
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            t = "".join(s["text"] for s in ln["spans"]).strip()
            if t and len(t) <= 6:
                labels.append(fitz.Rect(ln["bbox"]))
    for c in clusters:
        if too_big(c) or c.width < 45 or c.height < 35:
            continue
        if c.y0 < 30 or c.y1 > H - 30:                        # زخارف الرأس والتذييل الملاصقة لحافة الصفحة
            continue
        # إطار فيه فقرات نص (مثال محلول، أتحقق من فهمي...) مش شكل: الأشكال الحقيقية فيها تسميات قليلة فقط
        n_words = sum(1 for w in page.get_text("words") if c.contains(fitz.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)))
        if n_words > 30:
            continue
        box = c + (-8, -8, 8, 8)
        for lr in labels:
            if box.intersects(lr) and not any(b[0].intersects(lr) for b in badges):
                c |= lr
        figs.append(c)
    # شكل داخل شكل (مثلاً مثال داخل شكل) نبقي الأكبر
    figs = [c for k, c in enumerate(figs) if not any(k != j and (o.contains(c) and o != c) for j, o in enumerate(figs))]
    figs.sort(key=lambda r: (round(r.y0 / 40), -r.x1))        # من فوق لتحت، ومن اليمين لليسار (كتاب عربي)
    long_lines = []                                           # أسطر نص عادية (مش تسميات): بنبعد القصّ عنها
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") != 0:
            continue
        for ln in b["lines"]:
            t = "".join(s["text"] for s in ln["spans"]).strip()
            if len(t) > 8:
                long_lines.append(fitz.Rect(ln["bbox"]))
    out = []
    for c in figs:
        clip = (c + (-6, -6, 6, 6)) & page.rect
        for lr in long_lines:                                 # لا تدخل أطراف أسطر النص المجاورة بالصورة
            if not lr.intersects(clip):
                continue
            cy = (lr.y0 + lr.y1) / 2
            if lr.y1 <= c.y0 + 5 and cy < c.y0:
                clip.y0 = max(clip.y0, lr.y1 + 0.5)
            elif lr.y0 >= c.y1 - 5 and cy > c.y1:
                clip.y1 = min(clip.y1, lr.y0 - 0.5)
            elif lr.x1 <= c.x0 + 3:
                clip.x0 = max(clip.x0, lr.x1 + 0.5)
            elif lr.x0 >= c.x1 - 3:
                clip.x1 = min(clip.x1, lr.x0 - 0.5)
        # أقرب رقم سؤال (دائرة صفراء) فوق الشكل أو بجانبه
        # (الرقم فوق الشكل أو بجانبه؛ بالكتب العربية غالباً على يمين النص والشكل على اليسار، فنعتمد على القرب الرأسي)
        best, bd = None, 1e9
        for r, t in badges:
            cy = (r.y0 + r.y1) / 2
            if not t.isdigit() or not (c.y0 - 80 <= cy <= c.y1):
                continue
            score = abs(cy - (c.y0 + 20)) + 0.05 * max(c.x0 - r.x1, r.x0 - c.x1, 0)
            if score < bd:
                best, bd = t, score
        # أقرب سطر نص طويل فوق الشكل (يساعد بمطابقة الشكل مع السؤال)
        near = ""
        top = None
        for b in page.get_text("blocks"):
            br = fitz.Rect(b[:4])
            txt = " ".join(str(b[4]).split())
            if len(txt) > 25 and br.y1 <= c.y0 + 4 and c.y0 - br.y1 < 90 and br.x0 < c.x1 and br.x1 > c.x0:
                if top is None or br.y1 > top:
                    top, near = br.y1, txt[:160]
        out.append({"bbox": [round(clip.x0, 1), round(clip.y0, 1), round(clip.x1, 1), round(clip.y1, 1)], "question_badge": best, "text_above": near})
    return out, [(r, t) for r, t in badges]


def cmd_detect(pdf, spec, out, dpi):
    if not fitz:
        sys.exit("أمر detect بحاجة لمكتبة PyMuPDF:  pip install pymupdf\n(بدونها استعمل: page ثم crop)")
    os.makedirs(out, exist_ok=True)
    doc = fitz.open(pdf)
    index = []
    for p in parse_pages(spec, len(doc)):
        page = doc[p - 1]
        figs, badges = detect(page)
        ov, wpt, hpt = render_page(pdf, p, 100)
        d = ImageDraw.Draw(ov, "RGBA")
        sx, sy = ov.width / wpt, ov.height / hpt
        f = font(16)
        for i, fg in enumerate(figs, 1):
            x0, y0, x1, y1 = fg["bbox"]
            clip = fitz.Rect(x0, y0, x1, y1)
            img = Image.frombytes("RGB", (0, 0), b"") if False else None
            pix = page.get_pixmap(clip=clip, dpi=dpi)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            fn = save_figure(im, os.path.join(out, f"p{p:03d}_f{i}.png"))
            fg.update({"page": p, "id": i, "file": os.path.basename(fn), "kb": os.path.getsize(fn) // 1024, "width_px": im.width, "height_px": im.height})
            index.append(fg)
            d.rectangle([x0 * sx, y0 * sy, x1 * sx, y1 * sy], outline=(255, 0, 255, 255), width=3)
            d.rectangle([x0 * sx, y0 * sy, x0 * sx + 26, y0 * sy + 22], fill=(255, 0, 255, 255))
            d.text((x0 * sx + 4, y0 * sy + 2), str(i), fill=(255, 255, 255, 255), font=f)
        ov.save(os.path.join(out, f"overview_p{p:03d}.png"))
        print(f"صفحة {p}: {len(figs)} شكل" + "".join(f"\n   f{fg['id']}: {fg['file']} ({fg['kb']}KB)  bbox={fg['bbox']}  سؤال={fg['question_badge']}" for fg in figs))
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f"\nتمّ: {len(index)} شكل → {out}  (راجع overview_pXXX.png لكل صفحة وتأكد من القصّ، وإن لزم عدّل بأمر crop)")


def cmd_page(pdf, pno, out, dpi):
    os.makedirs(out, exist_ok=True)
    img, wpt, hpt = render_page(pdf, int(pno), dpi)
    fn = os.path.join(out, f"page_{int(pno):03d}_grid.png")
    draw_grid(img, wpt, hpt).save(fn)
    print(f"{fn}  (الصفحة {wpt:.0f} x {hpt:.0f} نقطة؛ الأرقام الحمراء = x، الزرقاء = y)")


def cmd_crop(pdf, pno, box, outfile, dpi):
    x0, y0, x1, y1 = [float(v) for v in box]
    img, wpt, hpt = render_page(pdf, int(pno), dpi)
    sx, sy = img.width / wpt, img.height / hpt
    x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
    x0, x1 = max(0, x0), min(wpt, x1)                         # رتّب ثم قصّ على حدود الصفحة (منطقة كلها خارج الصفحة = خطأ مش صورة سودا)
    y0, y1 = max(0, y0), min(hpt, y1)
    if x1 - x0 < 5 or y1 - y0 < 5:
        sys.exit("منطقة القصّ صغيرة جداً أو خارج الصفحة")
    crop = img.crop((round(x0 * sx), round(y0 * sy), round(x1 * sx), round(y1 * sy)))
    os.makedirs(os.path.dirname(os.path.abspath(outfile)), exist_ok=True)
    fn = save_figure(crop, outfile)
    print(f"{fn}  ({os.path.getsize(fn) // 1024}KB، {crop.width}x{crop.height}px)")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    opts = {"--out": "figs", "--dpi": None}
    rest = []
    i = 0
    while i < len(a):
        if a[i] in opts and i + 1 < len(a):
            opts[a[i]] = a[i + 1]
            i += 2
        else:
            rest.append(a[i])
            i += 1
    cmd = rest[0] if rest else ""
    if cmd == "info":
        n = page_count(rest[1])
        print("صفحات:", n)
    elif cmd == "detect":
        cmd_detect(rest[1], rest[2], opts["--out"], int(opts["--dpi"] or 170))
    elif cmd == "page":
        cmd_page(rest[1], rest[2], opts["--out"], int(opts["--dpi"] or 110))
    elif cmd == "crop":
        cmd_crop(rest[1], rest[2], rest[3:7], rest[7], int(opts["--dpi"] or 170))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
