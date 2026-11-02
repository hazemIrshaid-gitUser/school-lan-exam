"""إرسال نسخة مضغوطة من نتائج الامتحان على إيميل المعلم لما يبدأ «امتحان جديد» (بعد ما تنجح الأرشفة). مكتبة بايثون الجاهزة بس (smtplib)، بدون تركيب شي.
الإرسال بخيط خلفي: فشله (إنترنت مقطوع، كلمة مرور غلط...) ما بيوقف الأرشفة ولا الامتحان الجديد، بيتكتب بالسجل وبيظهر بصفحة الإعدادات. كل دالة بتاخذ ctx."""
import email.message
import os
import re
import smtplib
import ssl
import tempfile
import threading
import time
import zipfile

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
    return {"from": s.get("mailFrom", ""), "to": s.get("mailTo", ""), "pass": s.get("mailPass", ""), "host": s.get("mailHost") or "smtp.gmail.com", "title": s.get("title", "")}


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


def _msg(conf, subject, body):
    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = conf["from"], ", ".join(check_emails(conf["to"])), subject
    m.set_content(body)
    return m


def _explain(e):
    if isinstance(e, smtplib.SMTPAuthenticationError): return "رفض الإيميل البريد أو كلمة المرور (بـ Gmail لازم «كلمة مرور تطبيق» مش كلمة مرور الحساب العادية)"
    if isinstance(e, (TimeoutError, ConnectionError, OSError)): return f"تعذّر الاتصال بخادم البريد (تأكد من الإنترنت): {e}"
    return f"{type(e).__name__}: {e}"


def _set(ctx, state, text):
    ctx.MAIL.update(state=state, text=text, at=time.strftime("%Y-%m-%d %H:%M"))


def _job(ctx, conf, d, n_students):
    fd, tmp = tempfile.mkstemp(suffix=".zip"); os.close(fd)           # خارج مجلد الأرشيف (وإلا الزيب بيضم نفسه)
    try:
        made = make_zip(d, tmp)
        if made is None:
            raise ValueError("حجم النتائج أكبر من حد الإيميل (20 ميجا) حتى بعد تصغيرها")
        kind, size = made
        stamp = time.strftime("%Y%m%d_%H%M")
        m = _msg(conf, f"نتائج امتحان: {conf['title']}",
                 f"نتائج الامتحان «{conf['title']}» ({n_students} طالب) انحفظت وانأرشفت بتاريخ {time.strftime('%Y-%m-%d %H:%M')}.\n"
                 + ("المرفق: كل ملفات الأرشيف (بدون الصور).\n" if kind == "full" else "المرفق: results.csv و submissions.jsonl و report.xlsx بس (الأرشيف كامل كبير على الإيميل؛ الباقي بمجلد الأرشيف عندك).\n")
                 + "أُرسل تلقائياً من سيرفر الامتحان عند الضغط على «بداية امتحان جديد».")
        with open(tmp, "rb") as f: m.add_attachment(f.read(), maintype="application", subtype="zip", filename=f"exam_results_{stamp}.zip")
        _send(conf, m)
        _set(ctx, "ok", f"انبعتت نسخة النتائج ({size // 1024} KB) على {conf['to']}")
    except Exception as e:                                       # أي فشل: الأرشيف سليم عندك، وبتقدر تبعته بنفسك
        _set(ctx, "fail", "تعذّر إرسال النتائج على الإيميل: " + (str(e) if isinstance(e, ValueError) else _explain(e)) + ". النتائج محفوظة بمجلد الأرشيف.")
    finally:
        try: os.remove(tmp)
        except OSError: pass
    ctx.print("إيميل النتائج:", ctx.MAIL["text"])


def send_archive(ctx, d, n_students):
    """بعد نجاح الأرشفة: لو إعدادات الإيميل معبّاة بيبعت zip الأرشيف بخيط خلفي. بيرجّع الخيط (أو None لو الإيميل مش مفعّل)"""
    if not configured(ctx): return None
    _set(ctx, "sending", "جاري إرسال النتائج على الإيميل...")
    t = threading.Thread(target=_job, args=(ctx, conf_of(ctx), d, n_students), daemon=True)
    t.start()
    return t


def send_test(ctx):
    """رسالة تجريبية (زر بصفحة الإعدادات) عشان يتأكد المعلم من الإعدادات قبل يوم الامتحان. بترجّع {"ok", "text"}"""
    if not configured(ctx): return {"ok": False, "text": "عبّي بريد المرسِل والمستلم وكلمة المرور واحفظ الإعدادات أولاً"}
    conf = conf_of(ctx)
    try:
        _send(conf, _msg(conf, "رسالة تجريبية من سيرفر الامتحان", "هذه رسالة تجريبية: إعدادات إرسال النتائج على الإيميل شغّالة."))
    except Exception as e:
        return {"ok": False, "text": _explain(e)}
    return {"ok": True, "text": f"انبعتت رسالة تجريبية على {conf['to']}"}
