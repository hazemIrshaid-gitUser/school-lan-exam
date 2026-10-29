"""طبقة الويب: معالج الطلبات H (http.server) بدالة لكل مسار. make_handler(ctx, app): ctx = حالة النسخة، app = نافذة على متغيرات server.py (دوال التشغيل والصحة والبروفة والدخول...)."""
import hmac, http.server, json, os, secrets, time, urllib.parse, html
from collections import Counter, defaultdict
from .constants import MAX_BODY, GRACE
from .questions import IMG_EXT
from .util import DataError, norm_pass, num
from .constants import PROTECTED
from .views import REHEARSAL_PAGE, files_page
from . import admin, auth, domain, rehearsal, storage, uploads


def make_handler(ctx, app):
    class H(http.server.BaseHTTPRequestHandler):
        timeout = 20                                      # اتصال معلّق بدون بيانات بينقطع (كان بيضل مفتوح للأبد)
        def send(self, body, ctype="text/plain; charset=utf-8", code=200, extra=None):
            b = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", (extra or {}).get("Cache-Control", "no-store"))
            self.send_header("Content-Length", str(len(b)))
            for k, v in (extra or {}).items():
                if k != "Cache-Control": self.send_header(k, v)
            self.end_headers(); self.wfile.write(b)
        def teacher(self): return self.client_address[0] in ("127.0.0.1", "::1")
        def not_local(self, path):
            """صفحة معلم انطلبت من غير جهاز السيرفر، أو من جهاز السيرفر برابط الشبكة (192.168...) بدل localhost"""
            u = f"http://localhost{'' if app.PORT == 80 else ':' + str(app.PORT)}{path}"
            return self.send("<meta charset=utf-8><body style='font-family:Tahoma;padding:30px;line-height:1.9'><h3>للمعلم فقط (من جهاز السيرفر)</h3>"
                             f"صفحات المعلم بتفتح من جهاز السيرفر نفسه على localhost (مش على رابط الطلاب):<br><b dir=ltr>{html.escape(u)}</b>", "text/html; charset=utf-8", 403)
        def authed(self):
            ck = dict(p.strip().split("=", 1) for p in self.headers.get("Cookie", "").split(";") if "=" in p)
            return ck.get("exam_t") in ctx.TOKENS
        # ===== GET: بدون دخول، ثم بوابة كلمة السر، ثم صفحات المعلم والصور (الترتيب نفسه بالضبط) =====
        OPEN_GET = {
            "/": "get_index",
            "/index.html": "get_index",
            "/ok": "get_ok",
            "/rehearsal": "get_rehearsal",
            "/rehearsal.json": "get_rehearsal_json",
            "/health": "get_health",
            "/health.json": "get_health",
            "/taken": "get_taken",
            "/link": "get_link"}
        AUTH_GET = {
            "/login": "get_login",
            "/authcheck": "get_authcheck",
            "/logout": "get_logout"}
        TEACHER_GET = ('/monitor', '/monitor-old', '/monitor.json', '/admin', '/report', '/report.xlsx', '/sheet', '/key', '/codes', '/teacher', '/settings', '/settings.json', '/files', '/files.json', '/template/questions.xlsx', '/template/students.xlsx')
        def do_GET(self):
            u = urllib.parse.urlparse(self.path); q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}; path = u.path
            app.note_client(self)
            f = self.OPEN_GET.get(path)
            if f: return getattr(self, f)(path, q)
            if path in PROTECTED or path == '/login': auth.refresh_tpass(ctx)
            f = self.AUTH_GET.get(path)
            if f: return getattr(self, f)(path, q)
            if path in PROTECTED and ctx.SET['tpass'] and self.teacher() and (not self.authed()):
                return self.send("", code=302, extra={"Location": "/login?next=" + urllib.parse.quote(self.path)})
            if path.startswith("/monitor-ui/"): return self.get_monitor_ui(path, q)
            if path in self.TEACHER_GET: return self.get_teacher_page(path, q)
            if path.startswith("/img/"): return self.get_img(path, q)
            self.send("", code=404)
        def get_index(self, path, q):
            return self.send(ctx.PAGE, "text/html; charset=utf-8")
        def get_ok(self, path, q):
            return self.send("OK\n")                       # للتجربة من جوال الطالب/المعلم: لو انفتحت بيوصل للسيرفر
        def get_rehearsal(self, path, q):
            return self.send(REHEARSAL_PAGE, "text/html; charset=utf-8")         # صفحة بروفة الضغط (بتشتغل بس لما المشرف يفعّلها)
        def get_rehearsal_json(self, path, q):
            with ctx.LOCK:
                rehearsal.reh_tick(ctx); o = {"on": ctx.REH["on"], "at": ctx.REH["at"], "gen": ctx.REH["gen"], "full": ctx.REH["full"]}
            o["now"] = time.time()
            return self.send(json.dumps(o), "application/json")
        def get_health(self, path, q):
            if not self.teacher(): return self.not_local(path)
            d_ = app.health_data()
            if path == "/health.json": return self.send(json.dumps(d_, ensure_ascii=False), "application/json; charset=utf-8")
            return self.send(app.health_page(d_), "text/html; charset=utf-8")
        def get_taken(self, path, q):
            with ctx.LOCK: t = [k for k, d in ctx.CLAIMS.items() if d != q.get("dev")]
            return self.send(json.dumps({"taken": t}, ensure_ascii=False), "application/json; charset=utf-8")
        def get_link(self, path, q):
            if not self.teacher(): return self.send("", code=403)
            return self.send("<meta charset=utf-8><body style='font-family:Tahoma;text-align:center;margin-top:15vh'><div style='font-size:28px'>رابط الامتحان</div>"
                             f"<div dir=ltr style='font-size:72px;font-weight:bold;color:#14566b'>http://{app.ip()}{'' if app.PORT == 80 else ':' + str(app.PORT)}</div>" + "".join(f"<div style='font-size:18px;color:#5d6b7a;margin-top:14px'>{app.IP_LABEL_AR[k]}: <b dir=ltr>{html.escape(u)}</b></div>" for u, k in app.alt_links('' if app.PORT == 80 else ':' + str(app.PORT)) if k != "virtual"), "text/html; charset=utf-8")
        def get_login(self, path, q):
            if not self.teacher(): return self.not_local(path)
            if not ctx.SET["tpass"]: return self.send("", code=302, extra={"Location": "/monitor"})
            nxt = q.get("next", "")
            nxt = nxt if nxt.split("?")[0] in PROTECTED and not nxt.startswith("//") else "/monitor"
            return self.send(app.login_page(nxt), "text/html; charset=utf-8")
        def get_authcheck(self, path, q):
            if not self.teacher(): return self.send("", code=403)
            return self.send(json.dumps({"authed": self.authed()}), "application/json")
        def get_logout(self, path, q):
            ctx.TOKENS.discard(dict(p.strip().split("=", 1) for p in self.headers.get("Cookie", "").split(";") if "=" in p).get("exam_t"))
            return self.send("", code=302, extra={"Location": "/monitor", "Set-Cookie": "exam_t=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
        def get_monitor_ui(self, path, q):
            if not self.teacher(): return self.not_local(path)
            a = app.monitor_ui_asset(urllib.parse.unquote(path[len("/monitor-ui/"):]))
            return self.send(a[0], a[1], extra={"Cache-Control": "no-cache"}) if a else self.send("غير موجود", code=404)
        def get_img(self, path, q):
            name = urllib.parse.unquote(path[5:])
            ext = os.path.splitext(name)[1].lower()
            fp = os.path.join(ctx.IMG_DIR, name)
            if not name or name != os.path.basename(name) or ext not in IMG_EXT or not os.path.isfile(fp): return self.send("", code=404)
            hdr = {"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"}
            if ext == ".svg": hdr["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
            with open(fp, "rb") as f: return self.send(f.read(), IMG_EXT[ext], 200, hdr)
        def get_teacher_page(self, path, q):
            if not self.teacher(): return self.not_local(path)
            with ctx.LOCK:
                if path in ("/monitor", "/admin"):
                    return self.send(app.monitor_ui_page() or app.monitor_old_page(), "text/html; charset=utf-8")      # الجديدة، أو القديمة لو مجلد monitor_ui مش موجود
                if path == "/monitor-old": return self.send(app.monitor_old_page(), "text/html; charset=utf-8")
                if path == "/monitor.json":
                    rows = app.student_rows(); secs = defaultdict(list)
                    for r in rows: secs[f"{r['grade']} — شعبة {r['section']}"].append(r)
                    c = Counter(r["status"] for r in rows); rehearsal.reh_tick(ctx)
                    return self.send(json.dumps({"sections": secs, "closed": bool(ctx.STATE["closed_at"]), "msg": ctx.STATE["msg"]["text"], "comp": ctx.STATE.get("comp"), "bank_changed": app.bank_changed(), "reh": rehearsal.reh_summary(ctx), "c": {k: c.get(k, 0) for k in ("done", "live", "lost", "none")}}, ensure_ascii=False), "application/json; charset=utf-8")
                if path == "/settings": return self.send(app.settings_page(), "text/html; charset=utf-8", extra={"Cache-Control": "no-store"})
                if path == "/settings.json": return self.send(json.dumps(admin.settings_state(ctx), ensure_ascii=False), "application/json; charset=utf-8", extra={"Cache-Control": "no-store"})
                if path == "/files": return self.send(files_page(ctx), "text/html; charset=utf-8", extra={"Cache-Control": "no-store"})
                if path == "/files.json": return self.send(json.dumps(uploads.files_state(ctx), ensure_ascii=False), "application/json; charset=utf-8", extra={"Cache-Control": "no-store"})
                if path.startswith("/template/"):
                    kind = path[len("/template/"):-len(".xlsx")]
                    return self.send(uploads.template_bytes(ctx, kind), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", extra={"Content-Disposition": f"attachment; filename={kind}_template.xlsx"})
                if path == "/key": return self.send(app.key_page(), "text/html; charset=utf-8")
                if path == "/teacher": return self.send(ctx.PREVIEW, "text/html; charset=utf-8")
                if path == "/codes": return self.send(app.codes_page(), "text/html; charset=utf-8")
                if path == "/sheet": return self.send(app.sheet_page(q), "text/html; charset=utf-8")
                if path == "/report": return self.send(app.report_page(), "text/html; charset=utf-8")
                return self.send(app.build_xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", extra={"Content-Disposition": "attachment; filename=exam_report.xlsx"})
        # ===== POST: مسار لكل دالة (الجسم بيتقرا مرة وحدة، وبعدين بيتوزّع) =====
        POST = {
            "/login": "post_login",
            "/settings": "post_settings",
            "/monitor": "post_monitor",
            "/rehearsal/join": "post_rehearsal_join",
            "/rehearsal/report": "post_rehearsal_report",
            "/start": "post_start",
            "/resume": "post_resume",
            "/review": "post_review",
            "/ping": "post_ping",
            "/submit": "post_submit"}
        def do_POST(self):
            app.note_client(self)
            app.gap_check()
            if urllib.parse.urlparse(self.path).path == "/upload": return self.post_upload()
            try: n = int(self.headers["Content-Length"])
            except Exception: return self.send("bad", code=400)
            if n < 0: return self.send("bad", code=400)
            if n > MAX_BODY: self.close_connection = True; return self.send("too large", code=413)       # ما نقرأ جسم ضخم بالذاكرة
            try: d = json.loads(self.rfile.read(n))
            except Exception: return self.send("bad", code=400)
            if not isinstance(d, dict): return self.send("bad", code=400)
            J = lambda o, code=200: self.send(json.dumps(o, ensure_ascii=False), "application/json; charset=utf-8", code)
            k, dev = d.get("key", ""), d.get("dev", "")
            f = self.POST.get(self.path)
            if f is None: return self.send("", code=404)
            return getattr(self, f)(d, k, dev, J)
        def post_login(self, d, k, dev, J):
            if not self.teacher() or self.headers.get("X-Exam-Action") != "1": return self.send("للمعلم فقط", code=403)
            now = time.time()
            if ctx.TFAIL[1] > now: return J({"ok": False, "locked": int(ctx.TFAIL[1] - now) + 1})
            auth.refresh_tpass(ctx)
            if ctx.SET["tpass"] and hmac.compare_digest(norm_pass(d.get("password", "")).encode(), norm_pass(ctx.SET["tpass"]).encode()):
                ctx.TFAIL[0] = 0; tok = secrets.token_urlsafe(24); ctx.TOKENS.add(tok)
                return self.send(json.dumps({"ok": True}), "application/json", 200, {"Set-Cookie": f"exam_t={tok}; Path=/; HttpOnly; SameSite=Strict"})
            ctx.TFAIL[0] += 1
            if ctx.TFAIL[0] >= 5: ctx.TFAIL[0] = 0; ctx.TFAIL[1] = now + 30; ctx.print("تنبيه: محاولات كثيرة خاطئة لكلمة سر المعلم — القفل 30 ثانية")
            return J({"ok": False})
        def post_settings(self, d, k, dev, J):
            if not self.teacher() or self.headers.get("X-Exam-Action") != "1": return self.send("للمعلم فقط", code=403)
            auth.refresh_tpass(ctx)
            if ctx.SET["tpass"] and not self.authed(): return self.send("للمعلم فقط", code=403)
            with ctx.LOCK:
                try: return J(admin.apply_settings(ctx, d))
                except DataError as e: return J({"ok": False, "error": str(e)}, 400)
                except OSError as e: return J({"ok": False, "error": f"تعذّرت كتابة الملف: {e}"}, 500)
        def post_upload(self):
            """رفع ملف (أسئلة/طلاب/صورة/zip صور): الجسم هو الملف نفسه (مش JSON)، والنوع والاسم بالرابط. حد حجم لكل نوع"""
            if not self.teacher() or self.headers.get("X-Exam-Action") != "1": return self.send("للمعلم فقط", code=403)
            auth.refresh_tpass(ctx)
            if ctx.SET["tpass"] and not self.authed(): return self.send("للمعلم فقط", code=403)
            J = lambda o, code=200: self.send(json.dumps(o, ensure_ascii=False), "application/json; charset=utf-8", code)
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query); kind, name = q.get("kind", [""])[0], q.get("name", [""])[0]
            lim = uploads.LIMITS.get(kind)
            if lim is None: return J({"ok": False, "error": "نوع الرفع غير معروف"}, 400)
            try: n = int(self.headers["Content-Length"])
            except Exception: return J({"ok": False, "error": "طلب غير صالح"}, 400)
            if n <= 0: return J({"ok": False, "error": "الملف فاضي"}, 400)
            if n > lim: self.close_connection = True; return J({"ok": False, "error": f"حجم الملف أكبر من المسموح ({lim // 1048576} MB)"}, 413)
            data = self.rfile.read(n)
            if len(data) != n: return J({"ok": False, "error": "الرفع انقطع قبل ما يكتمل، جرّب من جديد"}, 400)
            with ctx.LOCK:
                try: return J({"ok": True, **uploads.handle_upload(ctx, kind, name, data)})
                except DataError as e: return J({"ok": False, "error": str(e)}, 400)
                except OSError as e: return J({"ok": False, "error": f"تعذّرت كتابة الملف: {e}"}, 500)
        def post_monitor(self, d, k, dev, J):
            if not self.teacher() or self.headers.get("X-Exam-Action") != "1": return self.send("للمعلم فقط", code=403)
            with ctx.LOCK:
                if d.get("rehearsal"):                   # بروفة الضغط: on / go / off
                    err = rehearsal.reh_command(ctx, str(d["rehearsal"]), d)
                    return J({"error": err}, 400) if err else J({"ok": 1})
                rk = d.get("release")
                if rk in ctx.CLAIMS and rk not in ctx.SUBS:
                    del ctx.CLAIMS[rk]; ctx.PAPERS.pop(rk, None); ctx.LIVE.pop(rk, None); ctx.ANS.pop(rk, None); ctx.ANS_DIRTY[0] = True; app.save_claims(); app.save_papers(); ctx.print("فك حجز:", rk.split("|")[-1])
                ro = d.get("reopen")                     # إعادة فتح طالب سلّم بالغلط (بإجاباته ووقته)
                if ro:
                    try: err = app.reopen_student(ro)
                    except OSError as e: err = f"تعذّرت الكتابة بسجل التسليمات: {e}"
                    if err: return J({"error": err}, 400)
                    ctx.print("إعادة فتح الطالب:", str(ro).split("|")[-1])
                pk = d.get("pause")                      # إيقاف مؤقت لطالب (حمّام مثلاً): شاشته بتتغطّى ووقته بيتجمّد لحد «متابعة»؛ حجز الاسم والجهاز بيضل
                if pk:
                    if ctx.STATE["closed_at"]: return J({"error": "الامتحان منتهٍ، ما في داعي للإيقاف"}, 400)
                    if pk not in ctx.CLAIMS or pk not in ctx.PAPERS or pk in ctx.SUBS: return J({"error": "الطالب مش بالامتحان الآن (سلّم أو ما بدأ)"}, 400)
                    if "paused" not in ctx.PAPERS[pk]: ctx.PAPERS[pk]["paused"] = time.time(); app.save_papers(); ctx.print("إيقاف مؤقت:", pk.split("|")[-1])
                rk2 = d.get("resume")                    # متابعة طالب موقوف: وقته بيكمل من حيث وقف
                if rk2 and rk2 in ctx.PAPERS and "paused" in ctx.PAPERS[rk2]:
                    ctx.print("متابعة بعد الإيقاف:", rk2.split("|")[-1], f"({int(app.settle_pause(ctx.PAPERS[rk2]))} ث)"); app.save_papers()
                mk = d.get("move")                       # نقل الطالب لجهاز آخر: نفس الورقة والإجابات، والوقت المتبقي يتجمّد لحد ما يبدأ من الجهاز الجديد
                if mk in ctx.CLAIMS and mk in ctx.PAPERS and mk not in ctx.SUBS:
                    app.settle_pause(ctx.PAPERS[mk]); ctx.PAPERS[mk]["frozen"] = app.remain_of(mk); del ctx.CLAIMS[mk]; ctx.LIVE.pop(mk, None); app.save_claims(); app.save_papers()
                    ctx.print("نقل لجهاز آخر:", mk.split("|")[-1], "— المتبقي", ctx.PAPERS[mk]["frozen"], "ث")
                sf = d.get("submitfor")                  # تسليم عن طالب (مفتاحه) أو "all" = كل من بدأ ولم يسلّم
                if sf:
                    keys = [x for x in list(ctx.PAPERS) if x in ctx.CLAIMS and x not in ctx.SUBS] if sf == "all" else [sf]
                    done_n = 0
                    for x in keys:
                        try: done_n += 1 if app.submit_for(x) else 0
                        except OSError as e: ctx.print("خطأ: تعذّر حفظ التسليم", e)
                    if done_n: app.write_results_csv()
                    ctx.print(f"تسليم عن الطلاب: {done_n}")
                if d.get("newexam"): ctx.print("أرشفة ->", app.archive_all())
                if d.get("bankok"): ctx.STATE["bank_fp"] = ctx.BANK_FP; ctx.STATE.pop("bank_changed", None); app.save_state(); ctx.print("المشرف أكّد: ملف الأسئلة المعدّل لنفس الامتحان")
                try: mins = int(d.get("extend", 0))
                except (TypeError, ValueError): return J({"error": "bad minutes"}, 400)
                if mins:
                    if not 1 <= mins <= 120 or d.get("scope") not in ("all", "section", "student"): return J({"error": "bad extend"}, 400)
                    ctx.print(f"تمديد {mins} د ({d['scope']}):", app.extend_time(mins, d["scope"], d), "طالب")
                if "close" in d:                          # إنهاء الامتحان للجميع (الصفحات بتسلّم تلقائياً) أو إعادة فتحه
                    ctx.STATE["closed_at"] = time.time() if d["close"] else 0; app.save_state(); ctx.print("الامتحان", "أُنهي" if d["close"] else "أُعيد فتحه")
                if "message" in d:
                    txt = str(d["message"]).strip()[:300]
                    if txt: ctx.STATE["msg"] = {"id": ctx.STATE["msg"]["id"] + 1, "text": txt}; app.save_state(); ctx.print("رسالة للطلاب:", txt)
            return J({"ok": 1})
        def post_rehearsal_join(self, d, k, dev, J):
            with ctx.LOCK:
                rehearsal.reh_tick(ctx)
                if not ctx.REH["on"]: return J({"status": "off"})
                if not isinstance(dev, str) or not 0 < len(dev) <= 64: return J({"status": "bad"}, 400)
                r = rehearsal.reh_assign(ctx, dev)
                if r is None: return J({"status": "full"})
                return J({"status": "ok", "n": r["n"], "key": r["key"], "name": r["name"], "grade": r["grade"], "section": r["section"], "total": len(ctx.REH["devs"])})
        def post_rehearsal_report(self, d, k, dev, J):
            with ctx.LOCK:
                rehearsal.reh_tick(ctx)
                r = ctx.REH["devs"].get(dev) if isinstance(dev, str) else None
                if r is None or d.get("stage") not in ("start", "submit"): return J({"status": "bad"}, 400)
                def num_(x, lo, hi):
                    try: return int(max(lo, min(hi, float(x))))
                    except (TypeError, ValueError): return 0
                r["res"][d["stage"]] = {"ok": bool(d.get("ok")), "ms": num_(d.get("ms"), 0, 600000), "status": str(d.get("status", ""))[:20],
                                        "skew": num_(d.get("skew"), -600000, 600000), "rtt": num_(d.get("rtt"), 0, 600000)}
                return J({"status": "ok"})
        def post_start(self, d, k, dev, J):
            t_arr = time.time()                          # لحظة وصول الطلب (قبل انتظار القفل): بتفيد بقياس «بنفس اللحظة» ببروفة الضغط
            with ctx.LOCK:
                if not dev or app.parse_key(k) is None: return J({"status": "bad"}, 400)
                if k in ctx.REH["keys"]: ctx.REH["arr"].setdefault(k, t_arr)
                if k in ctx.SUBS: return J({"status": "done"})
                if k in ctx.CLAIMS and ctx.CLAIMS[k] != dev: return J({"status": "taken"})
                if k not in ctx.CLAIMS or k not in ctx.PAPERS:
                    if ctx.STATE["closed_at"] and k not in ctx.PAPERS: return J({"status": "closed"})   # المنقول يقدر يكمل ويسلّم حتى بعد الإنهاء
                    if ctx.SET["needCode"]:
                        bad = app.check_code(k, d.get("code"))
                        if bad: return J({"status": bad})
                    p = ctx.PAPERS.get(k)
                    if p is None: ctx.PAPERS[k] = app.make_paper(); ctx.print("بدأ:", k.split("|")[-1])
                    else:                                # طالب منقول: نفس الورقة، ونرجّع الوقت اللي كان باقيله
                        if "frozen" in p: p["start"] = time.time() + p.pop("frozen") - (ctx.SET["minutes"] * 60 + p.get("extra", 0))
                        ctx.print("استئناف من جهاز جديد:", k.split("|")[-1])
                    ctx.CLAIMS[k] = dev; app.save_claims(); app.save_papers()
                return J(app.paper_reply(k))
        def post_resume(self, d, k, dev, J):
            with ctx.LOCK:
                if k in ctx.SUBS: return J({"status": "done"})
                if ctx.CLAIMS.get(k) == dev and k in ctx.PAPERS: return J(app.paper_reply(k))
                return J({"status": "none"})
        def post_review(self, d, k, dev, J):
            with ctx.LOCK:
                mode = ctx.SET["review"]
                if mode == "no" or k not in ctx.SUBS or ctx.CLAIMS.get(k) != dev: return J({"status": "off"})
                if mode == "after" and not ctx.STATE["closed_at"]: return J({"status": "wait"})
                return J({"status": "ok", "items": [{"n": w["n"], "given": w["given"], "correct": w["correct"], "q": app.pub_q(w["n"])["q"], "o": app.pub_q(w["n"])["o"]} for w in app.wrong_items(ctx.SUBS[k]["ids"], ctx.SUBS[k]["answers"])]})
        def post_ping(self, d, k, dev, J):
            with ctx.LOCK:
                if k in ctx.SUBS: return J({"submitted": True}) if ctx.CLAIMS.get(k) == dev else J({"released": True})      # سلّم (مثلاً المعلم سلّم عنه): الصفحة تعرض نتيجته
                if ctx.CLAIMS.get(k) != dev or k not in ctx.PAPERS: return J({"released": True})                             # أُلغي حجزه أو نُقل لجهاز آخر: الصفحة ترجع لشاشة الدخول
                a = app.clean_ans(k, d.get("ans"))
                if a is not None and a != ctx.ANS.get(k, {}): ctx.ANS[k] = a; ctx.ANS_DIRTY[0] = True
                ctx.LIVE[k] = {"t": time.time(), "answered": int(d.get("answered", 0)), "total": int(d.get("total", 0)), "remain": int(d.get("remain", 0)),
                           "leaveN": int(d.get("leaveN", 0)), "leaveSec": int(d.get("leaveSec", 0))}
                return J({"remain": app.remain_of(k), "msg": ctx.STATE["msg"], "paused": "paused" in ctx.PAPERS[k]})
        def post_submit(self, d, k, dev, J):
            with ctx.LOCK:
                if k in ctx.SUBS: s = ctx.SUBS[k]; return J({"score": s["score"], "total": s["total"], "dup": True})
                who = app.parse_key(k); p = ctx.PAPERS.get(k)
                if who is None: return self.send("bad", code=400)
                if p is None or ctx.CLAIMS.get(k) != dev: return self.send("taken", code=409)
                try:
                    ids = [int(x) for x in d["ids"]]; answers = [int(x) for x in str(d["answers"]).split(",")]
                    assert ids == p["ids"] and len(answers) == len(ids) and all(-1 <= a < len(ctx.BANK[n]["o"]) for n, a in zip(ids, answers))
                except Exception: return self.send("bad", code=400)
                now = time.time(); over = int(now - app.deadline(k)); app.settle_pause(p)         # لو كان موقوفاً لحظة التسليم (مثلاً انتهى الامتحان): نثبّت الإيقاف قبل حساب المدة
                extra = {"dur": max(0, int(now - p["start"] - p.get("down", 0) - p.get("pz", 0)))}   # مدة الحل: من «ابدأ» لـ «تسليم» بساعة السيرفر، بدون وقت توقف السيرفر وبدون إيقاف المعلم له
                if p.get("pz"): extra["pause"] = int(p["pz"])
                rec = domain.build_record(ctx, k, who, ids, answers, str(d.get("auto", ""))[:40], str(d.get("leave", ""))[:60], over if over > GRACE else 0, now, **extra)
                try: storage.record_submission(ctx, rec)
                except OSError as e:
                    ctx.print("خطأ: تعذّر حفظ التسليم", e); return self.send("save failed", code=500)
                app.write_results_csv()
                ctx.print("استلمت:", rec["section"], rec["name"], rec["score"], "/", rec["total"], f"(متأخر {over} ث)" if rec["late"] else "")
            J({"score": rec["score"], "total": rec["total"]})
        def log_message(self, *a): pass
    return H
