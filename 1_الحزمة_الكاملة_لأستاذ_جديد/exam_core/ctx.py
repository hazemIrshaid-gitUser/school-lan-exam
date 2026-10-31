"""حالة نسخة الامتحان الواحدة. الحاويات (SET, QLIST, BANK, PICK, ROSTER, IMG_LIST, XCODES) بتتحدّث مكانها (clear/update) وما بتنعاد تعيينها أبداً،
فكل مين بيحمل مرجعاً لها (server.py والوحدات) بيشوف نفس الكائن. PAGE و PREVIEW نصوص بتتبدّل فبتنقرأ من ctx. كل نسخة سيرفر إلها ctx خاص فيها
(مش كائن مشترك بالوحدة)، فتحميل أكثر من نسخة بنفس العملية (الاختبارات) ما بيخلط حالتهم."""
import os, threading
from .constants import LVL


class Ctx:
    def __init__(self, base):
        self.BASE = base
        self.IMG_DIR = os.path.join(base, "images")
        self.SET, self.QLIST, self.BANK, self.PICK, self.ROSTER = {}, [], {}, {}, {}
        self.GLBL = dict(LVL)                      # اسم كل مجموعة سحب: المستويات الثلاثة، أو قواعد «سحب» من settings.txt (r1, r2...)
        self.IMG_LIST = []                         # أسماء الصور المستعملة بالأسئلة (كل صورة = رمز واحد بنص السؤال)
        self.XCODES = {}                           # رموز مكتوبة يدوياً بعمود رابع «الرمز» بملف الطلاب (اختياري)
        self.PAGE = self.PREVIEW = ""
        self.PAPERS, self.CLAIMS, self.ANS, self.LIVE, self.SUBS, self.CODES, self.FAILS = {}, {}, {}, {}, {}, {}, {}    # أوراق الطلاب، حجز الأسماء، إجاباتهم، نبضاتهم، تسليماتهم، رموز الدخول، المحاولات الخاطئة
        self.STATE = {}                            # حالة الامتحان (إنهاء المعلم، الرسالة...)؛ server.py بيعبّيها من state.json
        self.ANS_DIRTY, self.LAST_TICK = [False], [None]
        self.BANK_FP = ""
        self.UNCONF = []                           # إعدادات الامتحان الأساسية الناقصة (عنوان، توزيع الأسئلة): فاضي = المعلم عبّاها وحفظها من صفحة «إعدادات الامتحان». غير هيك صفحة الطالب بتضل «غير جاهز»
        self.SETUP = {}                            # وضع التجهيز: فاضي = الامتحان جاهز. غير هيك: ملف ناقص أو فيه خطأ ({"questions"|"students"|"settings": رسالة الخطأ، أو "" لو الملف لسا ما انرفع}) والطلاب بيشوفوا «غير جاهز»
        self.REH = {"on": False, "until": 0.0, "at": 0.0, "full": False, "gen": 0, "devs": {}, "keys": set(), "arr": {}}          # بروفة الضغط (rehearsal.py)
        self.TOKENS = set()                        # جلسات المعلم المسجّلة (بالذاكرة فقط: بتنتهي بإطفاء السيرفر)
        self.TFAIL = [0, 0]                        # محاولات كلمة سر خاطئة [العدد، قفل لحد وقت]
        self.SET_MTIME = [None]                    # وقت تعديل settings.txt (auth.refresh_tpass بتلاحظ تغيّر كلمة السر)
        j = lambda f: os.path.join(base, f)
        self.OUT = j("results.csv")                # يُولَّد من submissions.jsonl (المصدر الأساسي) — آمن لو كان مفتوحاً بـ Excel
        self.SUBS_FILE = j("submissions.jsonl")
        self.CLAIMS_FILE = j("claims.json")
        self.PAPERS_FILE = j("papers.json")        # ورقة كل طالب (الأسئلة وترتيب الخيارات ووقت البدء) — يحددها السيرفر
        self.STATE_FILE = j("state.json")          # حالة الامتحان: إنهاء من المعلم + آخر رسالة للطلاب
        self.ANS_FILE = j("answers.json")          # إجابات الطلاب أثناء الامتحان (نسخة احتياطية على السيرفر)
        self.CODES_FILE = j("codes.json")          # رموز دخول الطلاب المولَّدة (تبقى بين الامتحانات؛ امسح الملف لتوليد رموز جديدة)
        self.ALIVE_FILE = j("alive.txt")           # آخر لحظة كان فيها السيرفر شغّال (بتتحدّث كل 3 ثواني): منها بنعرف مدة التوقف
        self.LOCK = threading.Lock()
        self.MAX_COMP = 30 * 60                    # أكبر توقف بنعوّضه تلقائياً (ثانية)
        self.GAP_S = 20                            # قفزة أكبر من هيك بين دورتين = الجهاز نام (انسكّر غطاء اللابتوب) أو تجمّد
        self.REOPEN_MIN = 120                      # أقل وقت بنعطيه لطالب أُعيد فتحه (ثواني)، حتى لو سلّم قبل نهاية وقته
        self.print = print                         # server.py بيحط هون print تبعه (بيكتب العربي بملف بدل نافذة ما بتعرضه)
