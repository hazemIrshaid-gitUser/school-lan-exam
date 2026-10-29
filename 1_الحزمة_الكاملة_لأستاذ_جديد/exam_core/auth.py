"""دخول المعلم: ملاحظة تغيّر كلمة السر بملف settings.txt وتطبيقها بدون إعادة تشغيل. جلسات المعلم (TOKENS) والمحاولات الخاطئة (TFAIL) بـ ctx."""
import os
from .storage import read_settings

def refresh_tpass(ctx):
    """المعلم غيّر كلمة السر بملف settings.txt والسيرفر شغّال: بنقرأها من جديد (كلمة السر بس؛ باقي الإعدادات بتحتاج إعادة تشغيل)"""
    try: m = os.path.getmtime(os.path.join(ctx.BASE, "settings.txt"))
    except OSError: return
    if m == ctx.SET_MTIME[0]: return
    ctx.SET_MTIME[0] = m
    try: new = read_settings(ctx)["tpass"]
    except Exception: return                     # الملف لسا بينكتب أو فيه خطأ: بنضل على كلمة السر الحالية
    if new != ctx.SET["tpass"]:
        ctx.SET["tpass"] = new; ctx.print("كلمة سر المعلم تغيّرت من settings.txt (اشتغلت بدون إعادة تشغيل)")
