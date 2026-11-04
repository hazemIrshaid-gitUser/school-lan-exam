"""إرسال نسخة مضغوطة من نتائج الامتحان على إيميل المعلم لما يبدأ «امتحان جديد» (بعد ما تنجح الأرشفة). مكتبة بايثون الجاهزة بس (smtplib)، بدون تركيب شي.
الإرسال بخيط خلفي: فشله (إنترنت مقطوع، كلمة مرور غلط...) ما بيوقف الأرشفة ولا الامتحان الجديد، بيتكتب بالسجل وبيظهر بصفحة الإعدادات. كل دالة بتاخذ ctx."""
import email.message
import html
import os
import re
import smtplib
import ssl
import tempfile
import threading
import time
import zipfile

from .constants import BANDS

MAX_BYTES = 20 * 1024 * 1024                    # Gmail بيقبل لحد 25 ميجا؛ نترك هامش للترميز
MASK = "••••••••"
EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
HOST_RE = re.compile(r"^[A-Za-z0-9.-]+(:\d{1,5})?$")
SMALL = ("results.csv", "submissions.jsonl")    # لو الأرشيف كبير: هدول بس مع report.xlsx


def check_emails(v):
    """قائمة عناوين مفصولة بفاصلة/فاصلة منقوطة/مسافة. ترجّع القائمة أو ترفع ValueError لو أي عنوان مش صحيح"""
    out = [x for x in re.split(r"[,;\s]+", v.strip()) if x]
    if not out or not all(EMAIL_RE.match(x) for x in out): raise ValueError(v)
    return out


def configured(ctx):
    s = ctx.SET
    return bool(s.get("mailFrom") and s.get("mailTo") and s.get("mailPass"))


def conf_of(ctx):
    """لقطة من الإعدادات وقت النداء (الإعدادات ممكن تتغير بعد الأرشفة: عنوان الامتحان الجديد...)"""
    s = ctx.SET
    return {"from": s.get("mailFrom", ""), "to": s.get("mailTo", ""), "pass": s.get("mailPass", ""), "host": s.get("mailHost") or "smtp.gmail.com", "title": s.get("title", ""), "sign": s.get("mailSign", "")}


def _files(d, small=False):
    out = []
    for root, dirs, names in os.walk(d):
        dirs[:] = [x for x in dirs if x != "images"]          # الصور كبيرة وبتنضاف للأرشيف من مجلد الامتحان نفسه
        for n in names:
            p = os.path.join(root, n); rel = os.path.relpath(p, d)
            if small and not (rel in SMALL or rel.replace("\\", "/") == "نتائج/report.xlsx"): continue
            out.append((p, rel))
    return out


def make_zip(d, dest):
    """يعمل zip لمجلد الأرشيف (بدون الصور). لو أكبر من الحد: بس results.csv وsubmissions.jsonl وreport.xlsx. بيرجّع (اسم النوع, حجم) أو None لو لسا كبير"""
    for kind in ("full", "small"):
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
            for p, rel in _files(d, kind == "small"): z.write(p, rel)
        size = os.path.getsize(dest)
        if size <= MAX_BYTES: return kind, size
    return None


def _send(conf, msg):
    host, _, port = conf["host"].partition(":"); port = int(port or 465)
    tls = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=tls) as s:
            s.login(conf["from"], conf["pass"]); s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=tls); s.login(conf["from"], conf["pass"]); s.send_message(msg)


def _msg(conf, subject, body, html_body=None):
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = conf["from"], ", ".join(check_emails(conf["to"])), subject
    m.set_content(body)
    if html_body: m.add_alternative(html_body, subtype="html")
    return m


def sign_lines(conf):
    """التوقيع من الإعداد: الأسطر مفصولة بالرمز |"""
    return [x.strip() for x in conf.get("sign", "").split("|") if x.strip()]


def exam_date(ctx):
    """تاريخ عقد الامتحان: يوم أول طالب بدأ (وإلا أول تسليم، وإلا اليوم). بيتنادى قبل تصفير الأوراق"""
    ts = [p["start"] for p in ctx.PAPERS.values() if p.get("start")] or [s["ts"] for s in ctx.SUBS.values() if s.get("ts")]
    return time.strftime("%Y-%m-%d", time.localtime(min(ts))) if ts else time.strftime("%Y-%m-%d")


SUM_HEAD = ["الصف", "الشعبة", "عدد الطلاب", "سلّموا", "المتوسط %", "الأعلى %", "الأقل %"]


def _ltr(s):
    """أرقام وعناوين إيميل جوّا نص عربي: كتلة LTR عشان ما تنقلب (+962... و name@x.com)"""
    return re.sub(r"(\+?\d[\d\s-]{5,}\d|[\w.+-]+@[\w-]+(?:\.[\w-]+)+)", r'<bdi dir="ltr">\1</bdi>', s)


def summary_html(rows):
    if not rows: return ""
    th = "padding:6px 10px;border:1px solid #cfd8e0;text-align:center;font-size:13px;"
    td = "padding:6px 10px;border:1px solid #cfd8e0;text-align:center;"
    head = "".join(f'<th style="{th}background:#eef5f8;color:#14566b">{h}</th>' for h in SUM_HEAD)
    head += "".join(f'<th style="{th}background:{b[3]};color:#fff">{b[1]}<br><span style="font-weight:normal;font-size:11px"><bdi dir="ltr">{b[2]}</bdi></span></th>' for b in BANDS)
    body = ""
    for r in rows:
        cells = "".join(f'<td style="{td}">{html.escape(str(v))}</td>' for v in r[:7])
        cells += "".join(f'<td style="{td}"><span style="display:inline-block;min-width:28px;padding:2px 6px;border-radius:6px;font-weight:bold;'
                         + (f'background:{b[3]};color:#fff">' if v else 'background:#e6ebf0;color:#9aa6b2;font-weight:normal">') + f'{v}</span></td>' for v, b in zip(r[7:], BANDS))
        body += f"<tr>{cells}</tr>"
    return f'<table style="border-collapse:collapse;margin:8px 0" dir="rtl"><tr>{head}</tr>{body}</table>'


def summary_text(rows):
    if not rows: return ""
    head = SUM_HEAD + [f"{b[1]} ({b[2].replace(chr(8211), ' إلى ')})" for b in BANDS]
    return "\n".join(" | ".join(str(v) for v in r) for r in [head] + rows)


def _body(conf, n_students, kind, date, at, rows):
    """نص الإيميل (نص عادي + HTML)، بالفصحى"""
    title = conf["title"]; sign = sign_lines(conf)
    attach = ("المرفق: جميع ملفات الأرشيف (بدون الصور)." if kind == "full" else
              "المرفق: الملفات results.csv و submissions.jsonl و report.xlsx فقط، لأن الأرشيف الكامل أكبر من أن يُرسل بالبريد، والباقي محفوظ في مجلد الأرشيف لديكم.")
    auto = "أُرسلت هذه الرسالة تلقائياً من سيرفر الامتحان عند الضغط على «بداية امتحان جديد»."
    thanks = "نشكر لك استخدامك نظام الامتحانات، ويسعدنا تواصلك معنا لأي استفسار أو ملاحظة."
    intro = f"نفيدك بأن نتائج الامتحان «{title}» ({n_students} طالباً) قد حُفظت وأُرشفت."
    text = "\n".join(["السلام عليكم ورحمة الله وبركاته،", "", intro, "", f"تاريخ عقد الامتحان: {date}", f"وقت الأرشفة: {at}", ""]
                     + (["ملخص النتائج:", summary_text(rows), ""] if rows else []) + [attach, "", auto, "", thanks] + ([""] + sign if sign else []))
    e = html.escape
    h = ['<div dir="rtl" style="font-family:Tahoma,Arial,sans-serif;font-size:15px;line-height:1.8;color:#1c2733">',
         "<p>السلام عليكم ورحمة الله وبركاته،</p>", f"<p>{e(intro)}</p>",
         f'<p><b>تاريخ عقد الامتحان:</b> <bdi dir="ltr">{date}</bdi><br><b>وقت الأرشفة:</b> <bdi dir="ltr">{at}</bdi></p>']
    if rows: h += ["<p><b>ملخص النتائج:</b></p>", summary_html(rows)]
    h += [f"<p>{e(attach)}</p>", f'<p style="color:#5d6b7a;font-size:13px">{e(auto)}</p>', f"<p>{e(thanks)}</p>"]
    if sign: h.append('<p style="margin-top:18px">' + "<br>".join(_ltr(e(x)) for x in sign) + "</p>")
    h.append("</div>")
    return text, "".join(h)


def _explain(e):
    if isinstance(e, smtplib.SMTPAuthenticationError): return "رفض الإيميل البريد أو كلمة المرور (بـ Gmail لازم «كلمة مرور تطبيق» مش كلمة مرور الحساب العادية)"
    if isinstance(e, (TimeoutError, ConnectionError, OSError)): return f"تعذّر الاتصال بخادم البريد (تأكد من الإنترنت): {e}"
    return f"{type(e).__name__}: {e}"


def _set(ctx, state, text):
    ctx.MAIL.update(state=state, text=text, at=time.strftime("%Y-%m-%d %H:%M"))


def _job(ctx, conf, d, n_students, date, rows):
    fd, tmp = tempfile.mkstemp(suffix=".zip"); os.close(fd)           # خارج مجلد الأرشيف (وإلا الزيب بيضم نفسه)
    try:
        made = make_zip(d, tmp)
        if made is None:
            raise ValueError("حجم النتائج أكبر من حد الإيميل (20 ميجا) حتى بعد تصغيرها")
        kind, size = made
        stamp = time.strftime("%Y%m%d_%H%M")
        at = time.strftime("%Y-%m-%d %H:%M")
        text, page = _body(conf, n_students, kind, date, at, rows)
        m = _msg(conf, f"نتائج امتحان: {conf['title']}", text, page)
        with open(tmp, "rb") as f: m.add_attachment(f.read(), maintype="application", subtype="zip", filename=f"exam_results_{stamp}.zip")
        _send(conf, m)
        _set(ctx, "ok", f"انبعتت نسخة النتائج ({size // 1024} KB) على {conf['to']}")
    except Exception as e:                                       # أي فشل: الأرشيف سليم عندك، وبتقدر تبعته بنفسك
        _set(ctx, "fail", "تعذّر إرسال النتائج على الإيميل: " + (str(e) if isinstance(e, ValueError) else _explain(e)) + ". النتائج محفوظة بمجلد الأرشيف.")
    finally:
        try: os.remove(tmp)
        except OSError: pass
    ctx.print("إيميل النتائج:", ctx.MAIL["text"])


def send_archive(ctx, d, n_students, rows=()):
    """بعد نجاح الأرشفة: لو إعدادات الإيميل معبّاة بيبعت zip الأرشيف بخيط خلفي. بيرجّع الخيط (أو None لو الإيميل مش مفعّل)"""
    if not configured(ctx): return None
    _set(ctx, "sending", "جاري إرسال النتائج على الإيميل...")
    t = threading.Thread(target=_job, args=(ctx, conf_of(ctx), d, n_students, exam_date(ctx), list(rows)), daemon=True)
    t.start()
    return t


def send_test(ctx):
    """رسالة تجريبية (زر بصفحة الإعدادات) عشان يتأكد المعلم من الإعدادات قبل يوم الامتحان. بترجّع {"ok", "text"}"""
    if not configured(ctx): return {"ok": False, "text": "عبّي بريد المرسِل والمستلم وكلمة المرور واحفظ الإعدادات أولاً"}
    conf = conf_of(ctx)
    try:
        sign = sign_lines(conf)
        body = "\n".join(["السلام عليكم ورحمة الله وبركاته،", "", "هذه رسالة تجريبية للتأكد من أن إعدادات إرسال النتائج على البريد الإلكتروني تعمل بصورة صحيحة."] + ([""] + sign if sign else []))
        page = ('<div dir="rtl" style="font-family:Tahoma,Arial,sans-serif;font-size:15px;line-height:1.8"><p>السلام عليكم ورحمة الله وبركاته،</p><p>هذه رسالة تجريبية للتأكد من أن إعدادات إرسال النتائج على البريد الإلكتروني تعمل بصورة صحيحة.</p>'
                + ("<p>" + "<br>".join(_ltr(html.escape(x)) for x in sign) + "</p>" if sign else "") + "</div>")
        _send(conf, _msg(conf, "رسالة تجريبية من سيرفر الامتحان", body, page))
    except Exception as e:
        return {"ok": False, "text": _explain(e)}
    return {"ok": True, "text": f"انبعتت رسالة تجريبية على {conf['to']}"}
