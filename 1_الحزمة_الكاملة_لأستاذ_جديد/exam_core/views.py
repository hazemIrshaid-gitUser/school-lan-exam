"""صفحات HTML للمعلم (تقرير، ورقات الطلاب، المفتاح، الرموز، المعاينة، الإعدادات) وتصميمها المشترك. كل دالة بتاخذ ctx."""
import json, os, html, urllib.parse
from collections import Counter
from .constants import L, LVL
from .domain import eff_mark, fmt_dur, glabel, key_mark, total_range
from .questions import qhtml
from .reports import find_keys, question_stats, section_stats, student_rows
from .text import FRAC_CSS, bdir
from .util import E, grp, mtxt, num
from .settings import rule_match
from .util import DataError

PASS_PCT = 50                                               # حد النجاح (% من العلامة الكاملة) للبطاقة والدائرة بصفحة التقرير
BANDS = ((85, "ممتاز", "85–100%", "#1b7f46"), (75, "جيد جداً", "75–84%", "#14566b"), (65, "جيد", "65–74%", "#3b6fb6"), (50, "مقبول", "50–64%", "#d49b20"), (0, "ضعيف", "أقل من 50%", "#b3261e"))
CSS = ("<meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><style>"
       ":root{--p:#14566b;--p2:#0e4355;--ink:#1c2733;--mut:#5d6b7a;--line:#dde3ea;--bg:#f4f6f8;--ok:#1b7f46;--okbg:#e6f6ec;--warn:#9a6200;--warnbg:#fff4d6;--bad:#b3261e;--badbg:#fde8e6}"
       "*{box-sizing:border-box}html{direction:rtl}body{font-family:Tahoma,'Segoe UI',Arial,sans-serif;max-width:1180px;margin:0 auto;padding:0 14px 30px;background:var(--bg);color:var(--ink);line-height:1.6}"
       "h2{color:var(--p);font-size:22px;margin:18px 0 8px}h3{font-size:17px;margin:22px 0 8px}a{color:var(--p)}"
       "table{border-collapse:collapse;width:100%;background:#fff;margin:8px 0 20px;border:1px solid var(--line);border-radius:10px;overflow:hidden}"
       "td,th{border-top:1px solid #e6ebf0;padding:8px 10px;text-align:right;vertical-align:top}th{background:#eef5f8;color:var(--p);border-top:0}"
       ".done{background:#e3f5e9}.live{background:#fff8dc}.lost{background:#fde5e5}.none{color:#888}"
       ".btn{display:inline-block;padding:7px 14px;background:var(--p);color:#fff;border-radius:8px;text-decoration:none;margin:2px;cursor:pointer;border:0;font:inherit;font-size:14px}"
       ".btn:hover{background:var(--p2)}.btn.red{background:var(--bad)}.btn.gray{background:#667}.btn.ghost{background:#fff;color:var(--p);border:1px solid var(--line)}"
       ".cards span{display:inline-block;background:#fff;border:1px solid var(--line);border-radius:8px;padding:8px 14px;margin:4px;font-weight:bold}"
       ".bar{display:inline-block;background:var(--p);height:14px;vertical-align:middle;border-radius:3px}"
       ".tnav{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:14px;flex-wrap:wrap;background:#fff;border-bottom:1px solid var(--line);margin:0 -14px 14px;padding:10px 14px;box-shadow:0 1px 4px #1c273314}"
       ".tnav .brand{font-weight:800;font-size:16px;white-space:nowrap;max-width:36ch;overflow:hidden;text-overflow:ellipsis}"
       ".tnav nav{display:flex;gap:4px;background:#eef2f5;padding:4px;border-radius:12px;overflow-x:auto;max-width:100%}"
       ".tnav nav a{padding:6px 12px;border-radius:9px;color:var(--mut);text-decoration:none;font-size:13px;font-weight:700;white-space:nowrap}"
       ".tnav nav a:hover{color:var(--ink)}.tnav nav a.on{background:#fff;color:var(--p);box-shadow:0 1px 3px #1c27331f}.tnav .lock{margin-inline-start:auto}"
       ".card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:12px 0}"
       ".pagehead{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin:6px 0}.pagehead h2{margin:0}.pagehead small{color:var(--mut)}"
       ".kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}"
       ".kpi{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 14px}.kpi b{display:block;font-size:26px;color:var(--p)}.kpi span{color:var(--mut);font-size:13px}"
       ".kpi.ok b{color:var(--ok)}.kpi.warn b{color:var(--warn)}.kpi.bad b{color:var(--bad)}"
       ".charts{display:grid;grid-template-columns:minmax(220px,300px) 1fr;gap:12px}@media(max-width:700px){.charts{grid-template-columns:1fr}}"
       ".charts h3{margin:0 0 8px;font-size:15px}.donut{display:block;margin:0 auto;max-width:190px}"
       ".hist{display:flex;align-items:flex-end;gap:10px;height:200px;padding:6px 6px 0;border-bottom:1px solid var(--line)}"
       ".hist .col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}.hist .col i{display:block;width:70%;max-width:72px;border-radius:6px 6px 0 0}.hist .col b{font-size:13px}"
       ".histlab{display:flex;gap:10px}.histlab span{flex:1;text-align:center;font-size:12px;color:var(--mut)}"
       ".badge{display:inline-block;padding:1px 9px;border-radius:99px;font-size:12px;font-weight:700}.badge.hard{background:var(--badbg);color:var(--bad)}.badge.medium{background:var(--warnbg);color:var(--warn)}.badge.easy{background:var(--okbg);color:var(--ok)}"
       ".pct{display:flex;align-items:center;gap:8px}.pct i{display:block;height:8px;border-radius:99px;background:var(--ok)}.pct i.mid{background:#d49b20}.pct i.low{background:var(--bad)}"
       "select{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:#fff}[hidden]{display:none!important}"
       ".tw{overflow-x:auto;margin:8px 0 20px}.tw table{margin:0;min-width:640px}"
       "@media print{.noprint{display:none}.tnav{display:none}body{background:#fff;max-width:none;margin:0;padding:0}.card,.kpi,table{border-radius:0}.tw{overflow:visible}.tw table{min-width:0}}"
       "</style>")
TABS = (("monitor", "/monitor", "المراقبة الحية"), ("report", "/report", "التقارير والتحليل"), ("sheet", "/sheet", "ورقات الطلاب"), ("key", "/key", "مفتاح الإجابات"),
        ("codes", "/codes", "رموز الدخول"), ("files", "/files", "الملفات"), ("settings", "/settings", "إعدادات الامتحان"), ("health", "/health", "فحص السيرفر"), ("teacher", "/teacher", "معاينة الامتحان"))
SHEET_CSS = "<style>" + FRAC_CSS + ".q{border:1px solid #bbb;border-radius:6px;padding:8px 10px;margin:8px 0;page-break-inside:avoid}.q.bad{border-color:#b3261e;background:#fff5f4}.q.good{border-color:#2e7d32}.o{margin:2px 14px}.o.right{color:#1b6b2a;font-weight:bold}.o.given.wrongc{color:#b3261e;font-weight:bold}.hd{border-bottom:2px solid #14566b;margin-bottom:8px}.pg{page-break-after:always}.pg:last-child{page-break-after:auto}@media print{.noprint{display:none}body{background:#fff;max-width:none;margin:0}}</style>"
FILES_BODY = r"""<style>
.fl h2{margin:0 0 4px;font-size:18px}.fl .sub{color:#5d6b7a;font-size:13px;margin:0 0 12px;line-height:1.7}
.fl .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px}
.fl .card{border:1px solid var(--line);border-radius:14px;padding:14px 16px;background:#fff}
.fl .card h3{margin:0 0 4px;font-size:16px}.fl .cur{font-size:13px;color:#33414f;margin:6px 0;line-height:1.8}
.fl .cur b{font-size:15px}.fl .pill{display:inline-block;background:#eef3f6;border-radius:999px;padding:1px 10px;margin:1px 2px;font-size:12px}
.fl .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:10px}
.fl input[type=file]{font:inherit;font-size:13px;max-width:100%}
.fl a.tpl{font-size:13px;color:#14566b}
.fl .setup{background:#fdeceb;border:1px solid #e9b3ae;border-radius:10px;padding:10px 14px;font-size:13px;margin:0 0 12px;line-height:1.8}.fl .setup b{color:#b3261e}.fl .setup pre{white-space:pre-wrap;font:inherit;margin:2px 0 6px;color:#7a1f18}
.fl .lock{background:#fff4d6;border:1px solid #ecd48a;border-radius:8px;padding:8px 12px;font-size:13px;margin:0 0 12px}
.fl .err{color:#b3261e;font-size:13px;margin:8px 0;white-space:pre-wrap;line-height:1.7;background:#fdeceb;border-radius:8px;padding:8px 12px}
.fl .okm{color:#1b7f46;font-size:13px;margin:8px 0;line-height:1.8;background:#eaf6ee;border-radius:8px;padding:8px 12px}
.fl .wm{color:#8a5a00;font-size:12px;margin-top:4px}
.fl button:disabled{opacity:.5;cursor:not-allowed}
</style>
<div class="fl" id="fl"><p class="sub">جاري التحميل…</p></div>
<script>
(function(){
const root=document.getElementById('fl');let S=null;const msgs={questions:'',students:'',images:''};
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function load(){
  try{const r=await fetch('/files.json',{cache:'no-store'});if(r.status!==200)throw 0;S=await r.json()}catch(e){root.innerHTML='<p class="err">تعذّر تحميل الصفحة. افتحها من جهاز السيرفر (localhost).</p>';return}
  render()}
function pills(o){return Object.entries(o).map(([k,v])=>'<span class="pill">'+esc(k)+': '+v+'</span>').join('')}
function fileLine(f){return f?'<div>الملف الحالي: <b>'+esc(f.name)+'</b> ('+f.kb+' KB، '+esc(f.time)+')</div>':'<div>ما في ملف حالياً</div>'}
function render(){
  const q=S.questions,st=S.students,im=S.images,lock=S.started;const nm={questions:'ملف الأسئلة',students:'ملف الطلاب',settings:'الإعدادات / قواعد السحب'};
  const su=Object.entries(S.setup||{});
  const cols=Object.entries(q.columns||{}).map(([c,vs])=>'<div>'+esc(c)+': '+vs.map(x=>'<span class="pill">'+esc(x[0])+' '+x[1]+'</span>').join('')+'</div>').join('');
  root.innerHTML='<h2>الملفات: الأسئلة والطلاب والصور</h2><p class="sub">ارفع ملفاتك من هون، وما بتحتاج تفتح مجلد النظام. كل ملف بينفحص مقابل <b>القالب الأصلي</b> قبل ما ينحفظ، ولو فيه خطأ ما بيتغير شي وبتشوف الأخطاء سطر سطر. أي تعديل بعدين بتعمله بملف Excel وبترفعه من جديد (بنحتفظ بنسخة من القديم).</p>'
  +(su.length?'<div class="setup"><b>الامتحان لسا غير جاهز</b> (وضع التجهيز): الطلاب بيشوفوا «الامتحان غير جاهز» لحد ما ترفع الناقص، وأول ما يكتمل بيجهز لحاله بدون إعادة تشغيل.'+su.map(([k,v])=>'<div>• <b>'+nm[k]+'</b>: '+(v?'فيه خطأ:<pre>'+esc(v)+'</pre>'+(k==='settings'?'عدّل <a href="/settings">إعدادات الامتحان</a> أو ارفع أسئلة ثانية.':'صحّحه وارفعه من جديد.'):'لسا ما انرفع، ارفعه من الخانة تحت.')+'</div>').join('')+'</div>':'')
  +(lock?'<div class="lock">الامتحان بدأ: <b>الأسئلة والصور مقفلة</b> (الأوراق انسحبت منها). بتقدر بس تضيف طلاب جدد. لأسئلة جديدة ابدأ امتحاناً جديداً من شاشة المراقبة.</div>':'')
  +'<div class="cards">'
  +'<div class="card"><h3>1) ملف الأسئلة</h3><div class="cur"><b>'+q.count+'</b> سؤال'+(q.picked?' | الورقة: '+q.picked+' سؤال':'')+(q.images_used?' | '+q.images_used+' صورة مستعملة':'')+'<div>'+pills(q.levels)+'</div>'+cols+fileLine(q.file)+'</div>'
  +'<a class="tpl" href="/template/questions.xlsx">تنزيل قالب الأسئلة</a>'
  +'<div class="row"><input type="file" id="fq" accept=".xlsx"'+(lock?' disabled':'')+'><button class="btn" id="bq"'+(lock?' disabled':'')+'>تحقق وارفع</button></div><div id="mq">'+msgs.questions+'</div>'
  +'<div class="wm">حد الحجم '+S.limits.questions+' MB. ارفع الصور (الخانة 3) <b>قبل</b> الأسئلة لو الأسئلة فيها [img:اسم.png].</div></div>'
  +'<div class="card"><h3>2) ملف الطلاب</h3><div class="cur"><b>'+st.count+'</b> طالب<div>'+st.sections.map(x=>'<span class="pill">'+esc(x[0])+' '+esc(x[1])+': '+x[2]+'</span>').join('')+'</div>'+fileLine(st.file)+'</div>'
  +'<a class="tpl" href="/template/students.xlsx">تنزيل قالب الطلاب</a>'
  +'<div class="row"><input type="file" id="fs" accept=".xlsx"><button class="btn" id="bs">تحقق وارفع</button></div><div id="ms">'+msgs.students+'</div>'
  +'<div class="wm">حد الحجم '+S.limits.students+' MB.'+(lock?' بعد بدء الامتحان بتقدر بس تضيف أسماء.':'')+'</div></div>'
  +'<div class="card"><h3>3) الصور</h3><div class="cur"><b>'+im.count+'</b> صورة بالمجلد'+(im.unused.length?'<div class="wm">غير مستعملة بالأسئلة: '+im.unused.slice(0,12).map(esc).join('، ')+(im.unused.length>12?' …':'')+'</div>':'')+'</div>'
  +'<div class="row"><input type="file" id="fi" accept=".zip,.png,.jpg,.jpeg,.gif,.webp,.svg" multiple'+(lock?' disabled':'')+'><button class="btn" id="bi"'+(lock?' disabled':'')+'>تحقق وارفع</button></div><div id="mi">'+msgs.images+'</div>'
  +'<div class="wm">ملف zip فيه الصور، أو صور مفردة (png, jpg, gif, webp, svg). حد الـ zip '+S.limits.images_zip+' MB والصورة '+S.limits.image+' MB. اسم الصورة هو اللي بتكتبه بالسؤال: [img:اسم.png].</div></div>'
  +'</div>';
  document.getElementById('bq').onclick=()=>up('questions','fq','mq',false);
  document.getElementById('bs').onclick=()=>up('students','fs','ms',false);
  document.getElementById('bi').onclick=()=>up('images','fi','mi',true)}
async function send(kind,name,file){
  let r;try{r=await fetch('/upload?kind='+kind+'&name='+encodeURIComponent(name),{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Exam-Action':'1'},body:file})}catch(e){return {ok:false,error:'انقطع الاتصال بالسيرفر'}}
  try{return await r.json()}catch(e){return {ok:false,error:r.status===403?'غير مسموح: افتح الصفحة من جهاز السيرفر وسجّل دخول المعلم':'ردّ غير متوقع من السيرفر ('+r.status+')'}}}
function pend(r){return (r.pending||[]).length?'<div class="wm">لسا ناقص: <b>'+r.pending.map(esc).join('، ')+'</b> (الامتحان بيجهز أول ما يكتمل).</div>':'<div class="wm">✔ الامتحان جاهز.</div>'}
function okq(r){return 'تم رفع الأسئلة: <b>'+r.count+'</b> سؤال'+(r.picked?'، والورقة '+r.picked+' سؤال':'')+(r.images_used?'، '+r.images_used+' صورة مستعملة':'')+'.<div>'+pills(r.levels)+'</div>'+Object.entries(r.columns||{}).map(([c,vs])=>'<div>'+esc(c)+': '+vs.map(x=>'<span class="pill">'+esc(x[0])+' '+x[1]+'</span>').join('')+'</div>').join('')+(r.warnings||[]).map(w=>'<div class="wm">'+esc(w)+'</div>').join('')+pend(r)}
function oks(r){return 'تم رفع الطلاب: <b>'+r.count+'</b> طالب'+(r.added||r.removed?' (أضفت '+r.added+'، وشلت '+r.removed+')':'')+'.<div>'+r.sections.map(x=>'<span class="pill">'+esc(x[0])+' '+esc(x[1])+': '+x[2]+'</span>').join('')+'</div>'+pend(r)}
async function up(kind,inp,box,multi){
  const el=document.getElementById(inp),fs=[...el.files];const m=document.getElementById(box);
  if(!fs.length){m.innerHTML='<div class="err">اختر ملفاً أولاً</div>';return}
  const btn=m.parentElement.querySelector('button');btn.disabled=true;m.innerHTML='<div class="sub">جاري الفحص والرفع…</div>';
  let html='';
  if(!multi){const r=await send(kind,fs[0].name,fs[0]);html=r.ok?'<div class="okm">'+(kind==='questions'?okq(r):oks(r))+'</div>':'<div class="err">'+esc(r.error||'فشل الرفع')+'</div>'}
  else if(fs.length===1&&/\.zip$/i.test(fs[0].name)){const r=await send('images_zip',fs[0].name,fs[0]);html=r.ok?'<div class="okm">تم: أضفت '+r.added+' صورة، واستبدلت '+r.replaced+(r.ignored?'، وتجاهلت '+r.ignored+' ملف مش صورة':'')+'.</div>':'<div class="err">'+esc(r.error||'فشل الرفع')+'</div>'}
  else{let ok=0,rep=0,errs=[];for(const f of fs){const r=await send('image',f.name,f);if(r.ok){ok++;if(r.replaced)rep++}else errs.push(r.error||('فشل رفع '+f.name))}
    html=(ok?'<div class="okm">تم رفع '+ok+' صورة'+(rep?' (منها '+rep+' استبدلت صورة بنفس الاسم)':'')+'.</div>':'')+(errs.length?'<div class="err">'+errs.map(esc).join('\n')+'</div>':'')}
  msgs[kind==='students'?'students':kind==='questions'?'questions':'images']=html;await load()}
load()})();
</script>
"""
SETTINGS_BODY = r"""<style>
.st h2{margin:0 0 4px;font-size:18px}.st .sub{color:#5d6b7a;font-size:13px;margin:0 0 10px}
.st .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.st label{display:block;font-size:13px;color:#33414f}.st label small{display:block;color:#7a8794;font-size:12px;margin-top:2px;line-height:1.5}
.st input,.st select,.st textarea{font:inherit;width:100%;padding:7px 10px;border:1px solid var(--line);border-radius:8px;background:#fff;margin-top:3px;box-sizing:border-box}
.st input:disabled,.st select:disabled{background:#f1f3f5;color:#7a8794}
.st .sel{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin:6px 0 12px}.st .sel label{min-width:170px;flex:0 1 220px}
.st .units{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px}
.st .unit{border:1px solid var(--line);border-radius:12px;padding:10px 12px;background:#f8fafb}
.st .unit .hd{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px}.st .unit .hd b{font-size:15px}.st .unit .hd span{font-size:12px;color:#5d6b7a}
.st .cells{display:grid;grid-template-columns:repeat(auto-fit,minmax(80px,1fr));gap:8px}
.st .over{border-color:#b3261e!important;background:#fdeceb!important}
.st .kp{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:12px 0}.st .kp div{background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px 12px}.st .kp small{display:block;color:#5d6b7a;font-size:12px}.st .kp b{font-size:21px}
.st .wbox{background:#fff4d6;border:1px solid #ecd48a;border-radius:8px;padding:8px 12px;font-size:13px;margin:8px 0}
.st .err{color:#b3261e;font-size:13px;margin:8px 0;white-space:pre-wrap}.st .okm{color:#1b7f46;font-size:13px;margin:8px 0}
.st .radios{display:flex;gap:16px;flex-wrap:wrap;margin:6px 0 10px;font-size:14px}.st .radios label{display:flex;gap:6px;align-items:center;color:inherit}.st .radios input{width:auto;margin:0}
.st textarea{min-height:110px;direction:rtl;font-family:Consolas,Tahoma,monospace;font-size:13px}
</style>
<div class="st" id="st"><p class="sub">جاري التحميل…</p></div>
<script>
(function(){
const root=document.getElementById('st');let S=null,mode='level',c1='',c2='',grid={},gen=0;
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function load(){
  try{const r=await fetch('/settings.json',{cache:'no-store'});if(r.status!==200)throw 0;S=await r.json()}catch(e){root.innerHTML='<p class="err">تعذّر تحميل الإعدادات. افتح هذه الصفحة من جهاز السيرفر (localhost).</p>';return}
  initDist();render();
}
function gridable(){
  const rs=S.rules;if(!rs.length)return null;let a=null,b=null;
  for(const r of rs){
    if(r.conds.length<1||r.conds.length>2)return null;
    if(r.conds.some(c=>c[1]!==':'||c[2].length!==1))return null;
    const ca=r.conds[0][0],cb=r.conds.length>1?r.conds[1][0]:'';
    if(a===null){a=ca;b=cb}else if(a!==ca||b!==cb)return null;
  }
  if(!S.columns.includes(a)||(b&&!S.columns.includes(b)))return null;
  return [a,b];
}
function initDist(){
  const g=gridable();grid={};
  if(S.rules.length){
    if(g){mode='grid';c1=g[0];c2=g[1];for(const r of S.rules){grid[r.conds[0][2][0]+'||'+(r.conds.length>1?r.conds[1][2][0]:'')]=r.n}}
    else mode='text';
  }else{mode='level';c1=S.columns.includes('الوحدة')?'الوحدة':(S.columns[0]||'');c2=S.columns.includes('المستوى')&&c1!=='المستوى'?'المستوى':''}
}
function avail(v1,v2){
  if(!c2){const e=(S.values[c1]||[]).find(x=>x[0]===v1);return e?e[1]:0}
  return (S.cross[c1+'||'+c2]||{})[v1+'||'+v2]||0;
}
function fieldHtml(f){
  const lock=S.started&&!f.free,d=lock?' disabled':'',h=f.help?`<small>${esc(f.help)}</small>`:'';
  let ctl;
  if(f.kind==='bool')ctl=`<select data-fk="${f.key}"${d}><option${f.value==='نعم'?' selected':''}>نعم</option><option${f.value==='لا'?' selected':''}>لا</option></select>`;
  else if(f.kind==='review')ctl=`<select data-fk="${f.key}"${d}>${['لا','نعم','بعد_الإنهاء'].map(o=>`<option${f.value===o?' selected':''}>${o}</option>`).join('')}</select>`;
  else ctl=`<input data-fk="${f.key}" value="${esc(f.value)}" placeholder="${esc(f.placeholder||(f.kind==='num'?'فاضي = غير مفعّل':''))}"${d}>`;
  return `<label>${esc(f.label)}${ctl}${h}</label>`;
}
function render(){
  const general=S.fields.filter(f=>f.kind!=='count'),legacy=S.fields.filter(f=>f.kind==='count');
  let h='';
  if(S.started)h+='<div class="wbox">🔒 بدأ الامتحان: الإعدادات اللي بتأثر على أوراق الطلاب مقفلة. المفتوح بس: كلمة السر وإظهار العلامة ومراجعة الأخطاء. لتعديل الباقي ابدأ امتحاناً جديداً من شاشة المراقبة.</div>';
  if(S.tpass_default)h+='<div class="wbox">⚠ كلمة سر المعلم هي الافتراضية (1234): غيّرها من هون.</div>';
  h+=`<div class="card"><h2>الإعدادات العامة</h2><p class="sub">كل تعديل بينكتب بملف settings.txt (ونسخة احتياطية قبل كل حفظ).</p><div class="grid">${general.map(fieldHtml).join('')}</div></div>`;
  h+='<div class="card"><h2>توزيع الأسئلة</h2><p class="sub">الأعمدة والقيم والأعداد المتاحة مقروءة من ملف الأسئلة نفسه.</p>';
  const dd=S.started?' disabled':'';
  h+=`<div class="radios"><label><input type="radio" name="md" value="grid"${mode==='grid'?' checked':''}${dd}> بالجدول (حسب عمود)</label><label><input type="radio" name="md" value="level"${mode==='level'?' checked':''}${dd}> حسب المستوى فقط (بدون قواعد)</label><label><input type="radio" name="md" value="text"${mode==='text'?' checked':''}${dd}> قواعد نصية متقدمة</label></div>`;
  h+='<div id="dist"></div></div>';
  h+='<div class="kp"><div><small>مجموع أسئلة الورقة</small><b id="k1">0</b></div><div><small>علامة كل سؤال</small><b id="k2">-</b></div><div><small>العلامة الكاملة</small><b id="k3">-</b></div><div><small>أسئلة البنك</small><b>'+S.bank+'</b></div></div>';
  h+='<div id="msg"></div><div><button class="btn" id="save">حفظ الإعدادات</button><button class="btn" id="reset" style="background:#5d6b7a"'+(S.started?' disabled':'')+'>رجوع للافتراضي</button></div>';
  root.innerHTML=h;
  root.querySelectorAll('input[name=md]').forEach(r=>r.onchange=()=>{mode=r.value;if(mode==='grid'&&!c1)c1=S.columns[0]||'';renderDist();totals()});
  root.querySelectorAll('[data-fk]').forEach(e=>e.addEventListener('input',totals));
  $('save').onclick=save;$('reset').onclick=doReset;
  renderDist();
}
const $=id=>document.getElementById(id);
function renderDist(){
  const box=$('dist'),dd=S.started?' disabled':'';let h='';
  if(mode==='level'){
    const lg=S.fields.filter(f=>f.kind==='count');
    h+='<p class="sub">كم سؤال يطلع لكل طالب من كل مستوى. فاضي = كل أسئلة المستوى. (ملف بدون مستويات: استعمل العدد الكلي.)</p><div class="grid">'+lg.map(fieldHtml).join('')+'</div>';
  }else if(mode==='grid'){
    const opts=(sel,none)=>(none?'<option value="">بدون تقسيم</option>':'')+S.columns.map(c=>`<option${c===sel?' selected':''}>${esc(c)}</option>`).join('');
    h+=`<div class="sel"><label>وزّع حسب عمود<select id="c1"${dd}>${opts(c1,false)}</select></label><label>وداخل كل قيمة حسب عمود<select id="c2"${dd}>${opts(c2,true)}</select></label></div>`;
    if(!c1)h+='<p class="sub">ما في أعمدة مناسبة بملف الأسئلة (لازم عمود مثل «الوحدة»).</p>';
    else{
      const v1=(S.values[c1]||[]),v2=c2?(S.values[c2]||[]):[['',0]];
      h+='<div class="units">'+v1.map(([a,na])=>`<div class="unit"><div class="hd"><b>${esc(a)}</b><span>المتاح ${na} سؤال</span></div><div class="cells">`+v2.map(([b])=>{
        const av=avail(a,b),k=a+'||'+b,val=grid[k]||'';
        return `<label>${c2?esc(b):'العدد'} <span style="color:#7a8794">(متاح ${av})</span><input type="number" min="0" data-g="${esc(k)}" data-av="${av}" value="${val}"${dd}></label>`}).join('')+'</div><div class="sub" data-sub="'+esc(a)+'" style="margin:6px 0 0"></div></div>').join('')+'</div>';
    }
  }else{
    const cur=S.rules.map(r=>r.text).join('\n');
    h+='<p class="sub">سطر لكل قاعدة، بالصيغة: <b dir="ltr">العمود:القيمة | العمود:القيمة | العدد:10</b>. «~» بدل «:» = القيمة تحتوي الكلمة. بدائل بـ / مثل وسط/صعب.</p>'
     +`<textarea id="rt"${dd} spellcheck="false">${esc(window.__rt!==undefined?window.__rt:cur)}</textarea>`;
  }
  box.innerHTML=h;
  if($('c1'))$('c1').onchange=e=>{c1=e.target.value;if(c2===c1)c2='';grid={};renderDist();totals()};
  if($('c2'))$('c2').onchange=e=>{c2=e.target.value;if(c2===c1)c2='';grid={};renderDist();totals()};
  box.querySelectorAll('[data-g]').forEach(i=>i.addEventListener('input',totals));
  if($('rt'))$('rt').addEventListener('input',e=>{window.__rt=e.target.value});
  totals();
}
function gridCells(){return [...root.querySelectorAll('[data-g]')].map(i=>({k:i.dataset.g,n:parseInt(i.value)||0,av:+i.dataset.av,el:i}))}
function val(fk){const e=root.querySelector(`[data-fk="${fk}"]`);return e?e.value:''}
function totals(){
  let tot=0;
  if(mode==='grid'){
    const per={};
    gridCells().forEach(c=>{tot+=c.n;c.el.classList.toggle('over',c.n>c.av);const u=c.k.split('||')[0];per[u]=(per[u]||0)+c.n});
    root.querySelectorAll('[data-sub]').forEach(e=>{e.textContent='من هذه القيمة: '+(per[e.dataset.sub]||0)+' سؤال'});
  }else if(mode==='level'){
    ['عدد_الأسئلة_الصعبة','عدد_الأسئلة_المتوسطة','عدد_الأسئلة_السهلة'].forEach(k=>{tot+=parseInt(val(k))||0});
    if(!tot)tot=S.picked;
  }else{
    const t=(window.__rt!==undefined?window.__rt:S.rules.map(r=>r.text).join('\n')).split('\n');
    t.forEach(l=>{const m=l.match(/العدد\s*:\s*(\d+)/);if(m)tot+=+m[1]});
  }
  const fin=parseFloat(val('العلامة_النهائية'))||0,qm=parseFloat(val('علامة_السؤال'))||0;
  $('k1').textContent=tot;
  $('k3').textContent=fin||(qm&&tot?Math.round(qm*tot*100)/100:'-');
  $('k2').textContent=qm||(fin&&tot?Math.round(fin/tot*100)/100:'-');
}
function msg(t,ok){$('msg').innerHTML=t?`<div class="${ok?'okm':'err'}">${esc(t)}</div>`:''}
function collect(){
  const values={};
  root.querySelectorAll('[data-fk]').forEach(e=>{if(!e.disabled)values[e.dataset.fk]=e.value});
  let rules=[];
  if(mode==='grid'){
    rules=gridCells().filter(c=>c.n>0).map(c=>{const [a,b]=c.k.split('||');return c2?`${c1}:${a} | ${c2}:${b} | العدد:${c.n}`:`${c1}:${a} | العدد:${c.n}`});
    if(!rules.length)return {error:'اكتب عدداً واحداً على الأقل بالجدول.'};
  }else if(mode==='text'){
    rules=(window.__rt!==undefined?window.__rt:S.rules.map(r=>r.text).join('\n')).split('\n').map(x=>x.replace(/^\s*سحب\s*=\s*/,'').trim()).filter(Boolean);
    if(!rules.length)return {error:'اكتب قاعدة واحدة على الأقل، أو اختر طريقة ثانية.'};
  }else{
    ['عدد_الأسئلة_الصعبة','عدد_الأسئلة_المتوسطة','عدد_الأسئلة_السهلة','عدد_الأسئلة_الكلي'].forEach(k=>{if(!(k in values))values[k]=val(k)});
  }
  if(mode!=='level'&&!S.started)['عدد_الأسئلة_الصعبة','عدد_الأسئلة_المتوسطة','عدد_الأسئلة_السهلة','عدد_الأسئلة_الكلي'].forEach(k=>values[k]='');
  return {values,rules};
}
async function post(o){
  const r=await fetch('/settings',{method:'POST',headers:{'Content-Type':'application/json','X-Exam-Action':'1'},body:JSON.stringify(o)});
  let j={};try{j=await r.json()}catch(e){}
  return {ok:r.ok&&j.ok,error:j.error||(r.status===403?'للمعلم فقط. سجّل الدخول من جديد.':'تعذّر الحفظ ('+r.status+')'),j};
}
async function save(){
  msg('');const o=collect();if(o.error){msg(o.error,false);return}
  if(mode==='grid'){const bad=gridCells().filter(c=>c.n>c.av);if(bad.length){msg('في أعداد أكبر من المتاح (الخانات الحمراء).',false);return}}
  $('save').disabled=true;
  try{const res=await post(o);if(!res.ok){msg(res.error,false);return}
    window.__rt=undefined;await load();msg('تم الحفظ وتطبيق الإعدادات ✓ (أسئلة كل ورقة: '+res.j.picked+')',true)}
  catch(e){msg('تعذّر الاتصال بالسيرفر.',false)}finally{const b=$('save');if(b)b.disabled=false}
}
async function doReset(){
  if(!confirm('رجوع كل الإعدادات للافتراضي (كلمة السر ما بتتغير)؟ بتنحفظ نسخة احتياطية قبل.'))return;
  msg('');try{const res=await post({reset:true});if(!res.ok){msg(res.error,false);return}
    window.__rt=undefined;await load();msg('رجعت الإعدادات للافتراضي ✓',true)}catch(e){msg('تعذّر الاتصال بالسيرفر.',false)}
}
load();
})();
</script>
"""
MONITOR = """<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>مراقبة الامتحان</title>
<style>
:root{--ink:#1c2733;--mut:#667788;--line:#dde3ea;--pri:#14566b;--ok:#1b7f4b;--okbg:#e6f6ec;--live:#9a6b00;--livebg:#fff6d9;--bad:#b3261e;--badbg:#fde8e6;--none:#7a8794;--nonebg:#f1f3f5}
*{box-sizing:border-box}body{margin:0;background:#f4f6f8;color:var(--ink);font-family:Tahoma,"Segoe UI",Arial,sans-serif;line-height:1.6}
.top{background:var(--pri);color:#fff;padding:14px 20px}.top h1{margin:0;font-size:22px}.top small{opacity:.85}
.nav{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.nav a{background:rgba(255,255,255,.15);color:#fff;text-decoration:none;padding:7px 14px;border-radius:8px;font-size:15px}.nav a:hover{background:rgba(255,255,255,.28)}
.wrap{max-width:1150px;margin:0 auto;padding:16px}
.linkbox{background:#fff;border:1px solid var(--line);border-radius:12px;padding:12px 16px;display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin-bottom:14px}
.linkbox b{font-size:15px;color:var(--mut)}.linkbox code{direction:ltr;font-size:20px;font-weight:bold;color:var(--pri);background:#eef5f8;padding:4px 12px;border-radius:8px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:10px}
.card{border-radius:12px;padding:12px 16px;border:1px solid var(--line);background:#fff;cursor:pointer;user-select:none}
.card .n{font-size:34px;font-weight:bold;line-height:1.1}.card .t{font-size:14px;color:var(--mut)}
.card.ok{background:var(--okbg);color:var(--ok)}.card.live{background:var(--livebg);color:var(--live)}.card.bad{background:var(--badbg);color:var(--bad)}.card.none{background:var(--nonebg);color:var(--none)}
.card.sel{outline:3px solid var(--pri)}
.prog{height:10px;background:#e3e8ee;border-radius:6px;overflow:hidden;margin:4px 0 14px}.prog i{display:block;height:100%;background:var(--ok);transition:width .4s}
.tools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:12px}
.tools input{flex:1;min-width:200px;padding:9px 12px;border:1px solid var(--line);border-radius:8px;font:inherit}
.chip{padding:7px 14px;border:1px solid var(--line);background:#fff;border-radius:20px;cursor:pointer;font-size:14px}.chip.sel{background:var(--pri);color:#fff;border-color:var(--pri)}
.sec{background:#fff;border:1px solid var(--line);border-radius:12px;margin-bottom:12px;overflow:hidden}
.sec>summary{list-style:none;cursor:pointer;padding:12px 16px;display:flex;align-items:center;gap:14px;flex-wrap:wrap;background:#fafbfc}
.sec>summary::-webkit-details-marker{display:none}.sec>summary::before{content:'◀';font-size:13px;color:var(--mut);transition:transform .2s}.sec[open]>summary::before{transform:rotate(-90deg)}.sec>summary:hover{background:#f1f5f8}.sec>summary .hint{margin-inline-start:auto;font-size:13px;color:var(--mut)}
.sec h3{margin:0;font-size:18px}.sec .cnt{color:var(--mut);font-size:14px}.sec .bar{flex:1;min-width:120px;max-width:260px}
table{border-collapse:collapse;width:100%}th{background:#f1f5f8;color:var(--mut);font-weight:normal;font-size:13px;text-align:right;padding:8px 12px}
td{padding:9px 12px;border-top:1px solid var(--line);text-align:right;vertical-align:middle}
tr.ok td:first-child,tr.live td:first-child,tr.bad td:first-child{border-right:5px solid transparent}
tr.ok td:first-child{border-right-color:var(--ok)}tr.live td:first-child{border-right-color:#e0a800}tr.bad td:first-child{border-right-color:var(--bad)}
.badge{display:inline-block;padding:2px 12px;border-radius:14px;font-size:13px;font-weight:bold}
.badge.ok{background:var(--okbg);color:var(--ok)}.badge.live{background:var(--livebg);color:var(--live)}.badge.bad{background:var(--badbg);color:var(--bad)}.badge.none{background:var(--nonebg);color:var(--none)}
.mini{display:inline-block;width:90px;height:8px;background:#e3e8ee;border-radius:5px;overflow:hidden;vertical-align:middle;margin-inline-start:8px}.mini i{display:block;height:100%;background:#2d8fb0}
.warn{color:#b45f00;font-weight:bold}.mut{color:var(--mut)}.score{font-size:18px;font-weight:bold;direction:ltr;display:inline-block}
.btn{display:inline-block;padding:6px 12px;border-radius:8px;border:1px solid var(--pri);background:var(--pri);color:#fff;text-decoration:none;cursor:pointer;font:inherit;font-size:14px}
.btn.o{background:#fff;color:var(--pri)}.btn.r{background:#fff;color:var(--bad);border-color:var(--bad)}
.foot{margin-top:26px;padding-top:14px;border-top:1px dashed var(--line);display:flex;flex-wrap:wrap;gap:14px;align-items:center;color:var(--mut);font-size:14px}
.empty{padding:30px;text-align:center;color:var(--mut)}
.comp{background:#e8f2f5;color:#14566b;border:1px solid #9cc6d4;border-radius:10px;padding:10px 16px;margin-bottom:12px;font-weight:bold}.comp.sk{background:var(--livebg);color:var(--live);border-color:#e0a800}
.closed{background:var(--badbg);color:var(--bad);border:1px solid var(--bad);border-radius:10px;padding:10px 16px;margin-bottom:12px;font-weight:bold}
.sec>summary .btn{font-size:12px;padding:3px 10px;margin-inline-start:6px}
.reh{background:#fff;border:1px solid var(--line);border-radius:12px;margin-bottom:12px}.reh>summary{cursor:pointer;padding:12px 16px}.rehin{padding:0 16px 12px}
.rehtools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:8px 0}.rehtools select{padding:7px 10px;border:1px solid var(--line);border-radius:8px;font:inherit}.reh table{margin:8px 0}
</style>
<div class=top><div class=wrap style="padding:0"><h1>مراقبة الامتحان</h1><small id=ttl>__TITLE__</small>
<div class=nav><a href=/report>📊 التقرير والتحليل</a><a href=/report.xlsx>⬇ تنزيل Excel</a><a href=/sheet>🖨 ورقات الطلاب / طباعة</a><a href=/key>🔑 مفتاح الإجابات</a><a href=/codes>🔢 رموز دخول الطلاب</a><a href=/teacher>🔍 معاينة الامتحان كاملاً</a><a href=/health>🩺 فحص السيرفر</a></div></div></div>
<div class=wrap>
<div class=linkbox><b>رابط الامتحان للطلاب:</b><code id=lnk>__LINK__</code><button class=btn onclick="cp()" id=cpb>نسخ الرابط</button><a class="btn o" href=/link target=_blank>عرض بخط كبير</a></div>
<div class=cards id=cards></div><div class=prog><i id=pg style="width:0"></i></div>
<div id=compbar class=comp style="display:none"></div>
<div id=bankbar class=closed style="display:none"></div>
<div id=closedbar class=closed style="display:none">⏹ الامتحان منتهٍ — الطلاب يُسلَّمون تلقائياً ولا يمكن البدء. <a href="#" onclick="closeExam(false);return false">إعادة فتح الامتحان</a></div>
<div class=tools><input id=q placeholder="🔍 ابحث عن اسم طالب..." oninput="draw()"><button class="btn o" onclick="allSec(true)">فتح كل الشعب</button><button class="btn o" onclick="allSec(false)">طي كل الشعب</button><span class=mut id=upd></span></div>
<div class=tools><button class="btn o" onclick="ext('all')">⏱ تمديد الوقت للجميع</button><button class="btn o" onclick="msg()">📢 رسالة للطلاب</button><button class="btn r" onclick="closeExam(true)">⏹ إنهاء الامتحان للجميع</button><button class="btn o" onclick="subAll()">📥 تسليم من لم يسلّم</button><span class=mut id=lastmsg></span></div>
<details class=reh id=rehbox><summary><b>🧪 بروفة الضغط</b> <span class=mut id=rehsum>— مطفية</span></summary><div class=rehin>
<p class=mut>كل أجهزة المختبر بتطلب «ابدأ» بنفس اللحظة حسب <b>ساعة السيرفر</b> (مش ساعة الأجهزة)، وبتشوف هون النتيجة. ① فعّلها. ② افتح على كل جهاز <b dir=ltr>__LINK__/rehearsal</b> وخلّي الشاشة شغّالة. ③ اضغط «ابدأ الجولة». ④ بعد ما تخلص اضغط زر الأرشفة والتصفير الأحمر أسفل الصفحة. بتنفع قبل الامتحان بس: لو في طلاب بدأوا ما بتتفعّل.</p>
<div class=rehtools><button class="btn o" id=rehon onclick="reh({rehearsal:'on'})">تفعيل البروفة (30 دقيقة)</button><select id=rehsecs><option value=30>بعد 30 ث</option><option value=60 selected>بعد 60 ث</option><option value=120>بعد 120 ث</option></select><label><input type=checkbox id=rehfull> حل عشوائي وتسليم</label><button class=btn id=rehgo onclick="rehGo()">▶ ابدأ الجولة</button><button class="btn r" onclick="reh({rehearsal:'off'})">إيقاف البروفة</button></div>
<div id=rehstat></div></div></details>
<div id=tbl></div>
<div class=foot><span>قبل ما تبدأ امتحان جديد: اطبع ورقات الطلاب ونزّل ملف النتائج أولاً، لأن هذا الزر بيصفّر الشاشة.</span>
<a class="btn r" href="#" onclick="newExam();return false">بداية امتحان جديد (أرشفة + تصفير)</a></div></div>
<script>
const ST={none:'لم يبدأ',live:'يمتحن',lost:'انقطع الاتصال',done:'سلّم'},CLS={none:'none',live:'live',lost:'bad',done:'ok'};
let J=null,FILTER='all',OPEN={};
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=s=>s==null?'':Math.floor(s/60)+':'+String(s%60).padStart(2,'0');
function cp(){navigator.clipboard&&navigator.clipboard.writeText(document.getElementById('lnk').textContent).then(()=>{const b=document.getElementById('cpb');b.textContent='تم النسخ ✓';setTimeout(()=>b.textContent='نسخ الرابط',1500)})}
async function act(o){await fetch('/monitor',{method:'POST',headers:{'Content-Type':'application/json','X-Exam-Action':'1'},body:JSON.stringify(o)});load()}
function releaseSt(k){if(confirm('فك الحجز بيخلّي الطالب يبدأ من جديد (من أي جهاز، حتى نفس الجهاز) بورقة ووقت جديدين، وبتضيع إجاباته السابقة، وصفحته الحالية بترجع لشاشة الدخول لحالها. متأكد؟\\nإذا بدك يكمل بنفس أسئلته وإجاباته ووقته المتبقي استخدم «نقل لجهاز آخر» بدل هذا.'))act({release:decodeURIComponent(k)})}
function mv(k){if(confirm('نقل الطالب لجهاز آخر: بيكمل بنفس الأسئلة والإجابات المحفوظة والوقت اللي كان باقيله، بعد ما يختار اسمه من الجهاز الجديد'+'.\\nلازم يكون الطالب جاهز على الجهاز الجديد (الاسم بيصير متاحاً لأي حدا لحد ما يبدأ؛ فعّل رمز الدخول لو بدك حماية). متأكد؟'))act({move:decodeURIComponent(k)})}
function newExam(){if(confirm('بداية امتحان جديد؟\\nبنحفظ النتائج الحالية بمجلد أرشيف وبنصفّر الحجوزات والشاشة.\\nتأكد إنك طبعت الأوراق ونزّلت Excel.')&&confirm('تأكيد أخير: تصفير الامتحان الحالي؟'))act({newexam:1})}
function ext(scope,key,grade,section){
 const lbl={all:'كل الطلاب اللي بدأوا ولم يسلّموا',section:'طلاب هذه الشعبة اللي بدأوا ولم يسلّموا',student:'هذا الطالب'}[scope];
 const m=parseInt(prompt('كم دقيقة تضيف لـ '+lbl+'؟ (1 – 120)\\nملاحظة: التمديد لازم يكون قبل ما ينتهي وقت الطالب.','5'),10);
 if(!m)return;if(m<1||m>120){alert('الرقم لازم يكون بين 1 و120');return}
 act({extend:m,scope:scope,key:key,grade:grade,section:section})}
function sub(k){if(confirm('تسليم إجابات هذا الطالب (المحفوظة على السيرفر) الآن وتصحيحها؟\\nالأسئلة اللي ما أجاب عنها بتنحسب خاطئة، وما بيقدر يكمل بعدها.'))act({submitfor:decodeURIComponent(k)})}
function subAll(){if(!J)return;const n=J.c.live+J.c.lost;if(!n){alert('ما في طلاب بدأوا ولم يسلّموا');return}
 if(confirm('تسليم '+n+' طالب بدأوا ولم يسلّموا (بما فيهم من يمتحن الآن) بإجاباتهم المحفوظة على السيرفر؟\\nالأفضل تضغط «إنهاء الامتحان للجميع» أولاً وتنتظر دقيقة ليسلّموا بأنفسهم، ثم تسلّم الباقي.\\nالأسئلة بدون إجابة بتنحسب خاطئة.'))act({submitfor:'all'})}
function msg(){const t=prompt('اكتب الرسالة (بتظهر على شاشة كل طالب يمتحن الآن):');if(t&&t.trim())act({message:t})}
function closeExam(v){if(v?confirm('إنهاء الامتحان للجميع؟ كل صفحة طالب بتسلّم تلقائياً خلال ثواني، ولا يقدر أحد يبدأ.'):confirm('إعادة فتح الامتحان؟ اللي سلّموا تلقائياً يبقى تسليمهم، واللي ما سلّموا يرجع إلهم وقتهم.'))act({close:v})}
function bankOk(){if(confirm('متأكد إن هذا نفس الامتحان وبس صلّحت أسئلة؟\\nإذا امتحان جديد اضغط «بداية امتحان جديد» بدل هذا.'))act({bankok:1})}
function allSec(v){if(J)for(const k of Object.keys(J.sections))OPEN[k]=v;draw()}
function setF(f){FILTER=FILTER===f?'all':f;draw()}
function draw(){
 if(!J)return;const c=J.c,tot=c.done+c.live+c.lost+c.none;
 const card=(k,cls,n,t)=>`<div class="card ${cls} ${FILTER===k?'sel':''}" onclick="setF('${k}')"><div class=n>${n}</div><div class=t>${t}</div></div>`;
 document.getElementById('cards').innerHTML=card('done','ok',c.done,'سلّموا')+card('live','live',c.live,'يمتحنون الآن')+card('lost','bad',c.lost,'انقطع اتصالهم')+card('none','none',c.none,'لم يبدأوا');
 document.getElementById('pg').style.width=(tot?Math.round(100*c.done/tot):0)+'%';
 document.getElementById('closedbar').style.display=J.closed?'block':'none';
 {const bb=document.getElementById('bankbar'),b=J.bank_changed;if(b){bb.innerHTML='⚠ ملف الأسئلة تغيّر بعد آخر امتحان، والسيرفر لسا فيه بيانات الامتحان السابق ('+b.subs+' تسليم و'+b.papers+' ورقة). إذا هذا <b>امتحان جديد</b>: اضغط «بداية امتحان جديد» (أسفل الصفحة) قبل ما يدخل الطلاب. إذا بس صلّحت سؤال بنفس الامتحان: <a href="#" onclick="bankOk();return false">هذا نفس الامتحان (أخفِ التنبيه)</a>';bb.style.display='block'}else bb.style.display='none'}
 {const cb=document.getElementById('compbar'),c=J.comp;if(c){const W=c.sleep?'جهاز السيرفر نام أو تجمّد ':'السيرفر كان متوقفاً ',m=Math.floor(c.downtime_s/60),s=c.downtime_s%60,t=(m?m+' دقيقة و':'')+s+' ثانية';cb.className=c.skipped||c.off?'comp sk':'comp';
  cb.textContent=c.skipped?('⚠ '+W+t+' (أطول من 30 دقيقة): ما عوّضنا الوقت تلقائياً. استعمل «⏱ تمديد الوقت للجميع» إذا لزم.'):c.off?('⚠ '+W+t+' والتعويض التلقائي مطفّأ (تعويض_توقف_السيرفر = لا). استعمل «⏱ تمديد الوقت للجميع» إذا لزم.'):('ℹ '+W+t+': مدّدنا تلقائياً وقت '+c.students+' طالب (اللي لم يسلّموا) بنفس المدة، فما خسروا شيئاً.');cb.style.display='block'}else cb.style.display='none'}
 document.getElementById('lastmsg').textContent=J.msg?'آخر رسالة: «'+J.msg+'»':'';
 const q=document.getElementById('q').value.trim();let h='';
 for(const [k,rows0] of Object.entries(J.sections)){
  const rows=rows0.filter(r=>(FILTER==='all'||r.status===FILTER)&&(!q||r.name.includes(q)));
  const dn=rows0.filter(r=>r.status==='done').length,lv=rows0.filter(r=>r.status==='live').length;
  if(!rows.length&&(q||FILTER!=='all'))continue;
  const busy=rows0.some(r=>r.status==='live'||r.status==='lost');const open=(q||FILTER!=='all')?true:(OPEN[k]!==undefined?OPEN[k]:busy);
  h+=`<details class=sec data-k="${esc(k)}" ${open?'open':''} ontoggle="if(!document.getElementById('q').value&&FILTER==='all')OPEN[this.dataset.k]=this.open"><summary><h3>${esc(k)}</h3><span class=cnt>سلّم ${dn} من ${rows0.length}${lv?' • يمتحن '+lv:''}</span><span class="prog bar" style="margin:0"><i style="width:${rows0.length?Math.round(100*dn/rows0.length):0}%"></i></span><span class=hint>${rows0.some(r=>r.status==='live')?`<button class="btn o" onclick="event.preventDefault();event.stopPropagation();ext('section',null,'${esc(rows0[0].grade)}','${esc(rows0[0].section)}')">⏱ تمديد الشعبة</button>`:'اضغط للفتح/الطي'}</span></summary>`;
  h+=`<table><tr><th>الاسم</th><th>الحالة</th><th>التقدّم</th><th>الوقت المتبقي</th><th>خرج من الصفحة</th><th>العلامة</th><th></th></tr>`;
  for(const r of rows){
   const cl=CLS[r.status];let prog='',lvv='';
   if(r.status==='live'||(r.status==='lost'&&r.answered!=null))prog=`${r.answered}/${r.total}<span class=mini><i style="width:${r.total?Math.round(100*r.answered/r.total):0}%"></i></span>`;
   if(r.status==='live')lvv=r.leaveN?`<span class=warn>⚠ ${r.leaveN} مرة — ${r.leaveSec} ث</span>`:'<span class=mut>—</span>';
   else if(r.status==='lost')lvv=r.leaveN?`<span class=warn>⚠ ${r.leaveN} مرة — ${r.leaveSec} ث</span>`:'';
   else if(r.status==='done'){lvv=(r.leave&&r.leave!=='لم يخرج')?`<span class=warn>⚠ ${esc(r.leave.replace(/\\((\\d+) ث\\)/,'— $1 ث'))}</span>`:'<span class=mut>لم يخرج</span>';if(r.late)lvv+=` <span class=warn>⏱ متأخر ${r.late} ث</span>`}
   const kk=r.key?encodeURIComponent(r.key).replace(/'/g,'%27'):'';
   let act='';
   if(r.status==='done')act=`<a class="btn o" target=_blank href="/sheet?key=${kk}">فتح الورقة</a>`;
   else if(r.status==='live'||r.status==='lost')act=`<a class="btn o" href="#" onclick="ext('student',decodeURIComponent('${kk}'));return false">+ وقت</a> <a class="btn o" href="#" onclick="mv('${kk}');return false" title="يكمل بنفس الأسئلة والإجابات والوقت المتبقي من جهاز آخر">نقل لجهاز آخر</a> <a class="btn o" href="#" onclick="sub('${kk}');return false" title="يصحّح إجاباته المحفوظة على السيرفر ويسجّلها كتسليم">تسليم عنه</a> <a class="btn r" href="#" onclick="releaseSt('${kk}');return false" title="للسماح للطالب بالبدء من جهاز آخر">فك الحجز</a>`;
   h+=`<tr class=${cl}><td>${esc(r.name)}</td><td><span class="badge ${cl}">${ST[r.status]}</span>${r.status==='lost'&&r.ago!=null?` <span class=mut>منذ ${r.ago} ث</span>`:''}</td><td>${prog}</td><td>${r.status==='live'?fmt(r.remain):(r.status==='done'&&r.durtxt?`<span class=mut>استغرق ${esc(r.durtxt)}</span>`:'')}</td><td>${lvv}</td><td>${r.status==='done'?`<span class=score>${r.score} / ${r.total}</span>`:''}</td><td>${act}</td></tr>`;
  }
  h+=rows.length?'</table>':'</table><div class=empty>لا نتائج</div>';h+='</details>';
 }
 document.getElementById('tbl').innerHTML=h||'<div class=empty>لا نتائج مطابقة</div>';
 document.getElementById('upd').textContent='آخر تحديث: '+new Date().toLocaleTimeString('en-GB');
 rehDraw();
}
async function reh(o){const r=await fetch('/monitor',{method:'POST',headers:{'Content-Type':'application/json','X-Exam-Action':'1'},body:JSON.stringify(o)});if(!r.ok){let m='';try{m=(await r.json()).error}catch(e){}alert(m||'ما زبط')}load()}
function rehGo(){reh({rehearsal:'go',secs:parseInt(document.getElementById('rehsecs').value,10),full:document.getElementById('rehfull').checked})}
function rehDraw(){
 const R=J.reh,s=document.getElementById('rehsum'),t=document.getElementById('rehstat');
 document.getElementById('rehon').disabled=!!(R&&R.on);document.getElementById('rehgo').disabled=!(R&&R.on&&R.joined);
 if(!R){s.textContent='— مطفية';t.innerHTML='';return}
 let sm=R.on?'— شغّالة (بتنطفي بعد '+Math.ceil(R.left/60)+' د) • أجهزة مسجّلة: '+R.joined:'— مطفية';
 if(R.at_in)sm+=' • الجولة بعد '+Math.ceil(R.at_in)+' ث';
 s.textContent=sm;
 let h='';
 if(R.joined){
  const f=x=>x==null?'—':x+' م.ث';
  h+='<table><tr><th>أجهزة مسجّلة</th><th>بدأوا بنجاح</th><th>فشلوا</th><th>أوراق انعملت بالسيرفر</th><th>وقت الرد (متوسط / 95% / أبطأ)</th><th>فرق وصول الطلبات للسيرفر</th><th>أكبر تأخر جهاز عن الموعد</th></tr><tr><td>'+R.joined+'</td><td>'+R.ok+' من '+R.reported+'</td><td>'+(R.fail?'<b class=warn>'+R.fail+'</b>':0)+'</td><td>'+R.papers+'</td><td>'+f(R.ms_avg)+' / '+f(R.ms_p95)+' / '+f(R.ms_max)+'</td><td>'+f(R.spread_ms)+'</td><td>'+f(R.skew_max)+'</td></tr></table>';
  if(R.full)h+='<p class=mut>التسليم: نجح '+R.submit_ok+'، فشل '+R.submit_fail+'، أبطأ تسليم '+f(R.submit_ms_max)+'</p>';
  if(R.fails&&R.fails.length)h+='<p class=warn>فشل: '+R.fails.map(x=>esc('جهاز '+x.n+' ('+x.name+') — '+x.status)).join('، ')+'</p>';
  if(!R.on||R.reported)h+='<p class=mut>بعد ما تخلص: اضغط زر الأرشفة والتصفير الأحمر أسفل الصفحة عشان تصفّر.</p>'
 }
 t.innerHTML=h;
}
async function load(){try{J=await (await fetch('/monitor.json')).json();draw()}catch(e){document.getElementById('upd').textContent='⚠ انقطع الاتصال بالسيرفر'}}
load();setInterval(load,4000);
</script>"""
REHEARSAL_PAGE = r"""<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>بروفة الضغط</title>
<style>
body{margin:0;padding:18px;background:#f4f6f8;color:#1c2733;font-family:Tahoma,"Segoe UI",Arial,sans-serif;text-align:center;line-height:1.7}
.card{max-width:460px;margin:0 auto;background:#fff;border:1px solid #dde3ea;border-radius:16px;padding:18px}
h1{font-size:20px;margin:0 0 6px;color:#14566b}
#big{font-size:76px;font-weight:bold;color:#14566b;direction:ltr;line-height:1.1;margin:10px 0}
#msg{font-size:18px;min-height:30px}.mut{color:#667788;font-size:14px}
.ok{color:#1b7f4b;font-weight:bold}.bad{color:#b3261e;font-weight:bold}
table{margin:12px auto 0;border-collapse:collapse;font-size:15px}td{padding:4px 12px;border-top:1px solid #eee}
</style>
<div class=card>
<h1>🧪 بروفة الضغط</h1>
<div class=mut>خلّي هالصفحة مفتوحة والشاشة شغّالة، ولا تطلع منها. المشرف بيبدأ الجولة من جهاز السيرفر.</div>
<div id=who class=mut style="margin-top:8px">...</div>
<div id=big>--</div>
<div id=msg></div>
<table id=res></table>
<div class=mut id=sync style="margin-top:10px"></div>
</div>
<script>
const $=id=>document.getElementById(id);
let DEV;try{DEV=localStorage.getItem('rehearsal|dev');if(!DEV){DEV='r'+Math.random().toString(36).slice(2,12)+Date.now().toString(36);localStorage.setItem('rehearsal|dev',DEV)}}catch(e){DEV='r'+Math.random().toString(36).slice(2,12)}
let S=[],off=0,rtt=0,me=null,st=null,lastAt=0,timer=null,pingT=null,P=null,busy=false;
const post=async(u,o)=>{const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});let j=null;try{j=await r.json()}catch(e){}return{http:r.status,j}};
const rep=o=>post('/rehearsal/report',Object.assign({dev:DEV},o)).catch(()=>{});
function row(label,ok,text){$('res').insertAdjacentHTML('beforeend','<tr><td>'+label+'</td><td class='+(ok?'ok':'bad')+'>'+(ok?'✓ ':'✗ ')+text+'</td></tr>')}
function stopRun(){clearInterval(pingT);clearTimeout(timer);P=null}
async function join(){const o=await post('/rehearsal/join',{dev:DEV});if(o.j&&o.j.status==='ok')me=o.j;else if(o.j&&o.j.status==='full')$('msg').textContent='ما في أسماء فاضية بقائمة الطلاب لهالجهاز'}
async function poll(){
 try{
  const t0=Date.now(),r=await fetch('/rehearsal.json?t='+t0,{cache:'no-store'}),t1=Date.now(),j=await r.json();
  S.push({rtt:t1-t0,off:j.now*1000-(t0+t1)/2});if(S.length>8)S.shift();
  const b=S.reduce((a,y)=>y.rtt<a.rtt?y:a);off=b.off;rtt=b.rtt;st=j;
  if(!j.on){if(me){me=null;stopRun();lastAt=0}}
  else{
   if(!me)await join();
   if(me&&j.at&&j.at!==lastAt){lastAt=j.at;schedule(j)}
  }
  draw();
 }catch(e){$('msg').textContent='⚠ انقطع الاتصال بالسيرفر'}
}
function draw(){
 if(!st)return;
 $('who').textContent=!st.on?'البروفة مطفية حالياً: المشرف بيشغّلها من صفحة المراقبة.':me?('جهاز رقم '+me.n+' — الاسم: '+me.name+' ('+me.grade+' '+me.section+')'):'جارٍ التسجيل...';
 $('sync').textContent='فرق ساعة هالجهاز عن ساعة السيرفر: '+(off/1000).toFixed(1)+' ث • تأخر الشبكة: '+Math.round(rtt)+' م.ث';
 if(!busy&&!P&&!$('msg').dataset.keep)$('msg').textContent=!st.on?'':me?(st.at&&st.at*1000-off>Date.now()-2000?'جاهز: البدء بنفس اللحظة مع باقي الأجهزة'+(st.full?' (مع حل عشوائي وتسليم)':''):'جاهز ✓ استنّى المشرف يبدأ الجولة'):''
}
function tickUI(){
 if(busy||P)return;
 if(!st||!st.on){$('big').textContent='--';return}
 if(!me){$('big').textContent='...';return}
 const left=(st.at*1000-off-Date.now())/1000;
 if(!st.at||left<-2){$('big').textContent='✓';return}
 $('big').textContent=left>0?Math.ceil(left):'الآن'
}
setInterval(tickUI,100);
function schedule(j){
 const target=j.at*1000-off,d=target-Date.now();
 $('res').innerHTML='';delete $('msg').dataset.keep;
 if(d<-1500){$('msg').textContent='فاتك موعد هالجولة: استنّى الجولة الجاية';$('msg').dataset.keep=1;return}
 clearTimeout(timer);timer=setTimeout(()=>{while(Date.now()<target){}fire(j,target)},Math.max(0,d-40));
}
async function fire(j,target){
 if(!me)return;
 const skew=Date.now()-target;busy=true;$('msg').textContent='جارٍ طلب الورقة...';
 const t0=performance.now();let o;try{o=await post('/start',{key:me.key,dev:DEV})}catch(e){o={http:0,j:{status:'network'}}}
 const ms=Math.round(performance.now()-t0),r=o.j||{},ok=r.status==='ok';
 await rep({stage:'start',ok,ms,status:ok?'ok':(r.status||('http'+o.http)),skew:Math.round(skew),rtt:Math.round(rtt)});
 row('بدء الامتحان',ok,ms+' م.ث'+(ok?' ('+r.ids.length+' سؤال)':' — '+(r.status||o.http))+' • انطلق بفرق '+Math.round(skew)+' م.ث عن الموعد');
 busy=false;
 if(!ok){$('msg').textContent='فشل الطلب ✗';$('msg').dataset.keep=1;return}
 P=r;P.mine={};P.full=!!j.full;P.at=j.at;$('msg').textContent=j.full?'جارٍ الحل العشوائي...':'نجح ✓ (الجهاز بيرسل نبضات مثل الطالب)';$('big').textContent='✓';
 runLoop(P)
}
function runLoop(p){
 clearInterval(pingT);const myAt=p.at;
 const step=async()=>{
  if(!st||!st.on||st.at!==myAt||P!==p){stopRun();return}
  p.qs.filter(q=>p.mine[q.n]===undefined).slice(0,6).forEach(q=>{p.mine[q.n]=Math.floor(Math.random()*q.o.length)});
  const answered=Object.keys(p.mine).length;
  if(p.full&&answered>=p.qs.length){clearInterval(pingT);await submit(p);return}
  try{await post('/ping',{key:me.key,dev:DEV,ans:p.mine,answered:answered,total:p.qs.length,remain:p.remain,leaveN:0,leaveSec:0})}catch(e){}
 };
 pingT=setInterval(step,8000);step()
}
async function submit(p){
 $('msg').textContent='جارٍ التسليم...';
 const answers=p.ids.map(n=>p.mine[n]!==undefined?p.mine[n]:0);
 const t0=performance.now();let o;try{o=await post('/submit',{key:me.key,dev:DEV,ids:p.ids,answers:answers.join(','),auto:'بروفة',leave:'لم يخرج'})}catch(e){o={http:0,j:{}}}
 const ms=Math.round(performance.now()-t0),r=o.j||{},ok=typeof r.score==='number';
 await rep({stage:'submit',ok,ms,status:ok?'ok':('http'+o.http),skew:0,rtt:Math.round(rtt)});
 row('التسليم',ok,ms+' م.ث'+(ok?' — العلامة '+r.score+' / '+r.total:''));
 $('msg').textContent=ok?'خلصت الجولة ✓':'فشل التسليم ✗';$('msg').dataset.keep=1;P=null
}
let wl=null;async function lock(){try{wl=await navigator.wakeLock.request('screen')}catch(e){}}
lock();document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')lock()});
poll();setInterval(poll,2000);
</script>"""
def band_of(ctx, pct): return next(i for i, b in enumerate(BANDS) if pct >= b[0])
def rv_block(ctx, key, pcts, n_students, hidden):
    """بلوك التقرير لمجموعة طلاب (كل الشعب أو شعبة): بطاقات الأرقام + دائرة النجاح + أعمدة توزيع العلامات. كل المجموعات بتنكتب بالصفحة (HTML جاهز) والقائمة بتبدّل بينها بدون ما تحسب شي"""
    n = len(pcts); ok = sum(1 for x in pcts if x >= PASS_PCT); rate = round(100 * ok / n) if n else None
    kp = (f"<div class=kpis><div class=kpi><span>إجمالي الطلاب</span><b>{n_students}</b></div><div class=kpi><span>سلّموا</span><b>{n}</b></div>"
          f"<div class=kpi><span>المتوسط %</span><b>{f'{sum(pcts) / n:.1f}' if n else '—'}</b></div>"
          f"<div class='kpi{'' if rate is None else ' ok' if rate >= PASS_PCT else ' bad'}'><span>نسبة النجاح (من {PASS_PCT}% وما فوق)</span><b>{'—' if rate is None else f'{rate}%'}</b></div>"
          f"<div class=kpi><span>الأعلى %</span><b>{round(max(pcts)) if n else '—'}</b></div><div class=kpi><span>الأدنى %</span><b>{round(min(pcts)) if n else '—'}</b></div></div>")
    head = f"<div class=rv data-k='{html.escape(key, True)}'{' hidden' if hidden else ''}>" + kp
    if not n: return head + "<div class=card>لا يوجد تسليم بعد.</div></div>"
    counts = [sum(1 for x in pcts if band_of(ctx, x) == i) for i in range(len(BANDS))]; mx = max(counts) or 1
    donut = (f"<svg class=donut viewBox='0 0 36 36' role=img aria-label='نسبة النجاح {rate}%'><circle cx=18 cy=18 r=15.9155 fill=none stroke='#fde8e6' stroke-width=4></circle>"
             f"<circle cx=18 cy=18 r=15.9155 fill=none stroke='#1b7f46' stroke-width=4 stroke-dasharray='{rate} {100 - rate}' stroke-dashoffset=25></circle>"
             f"<text x=18 y=19.5 text-anchor=middle font-size=7 font-weight=700 fill='#1c2733'>{rate}%</text></svg>"
             f"<p style='text-align:center;margin:6px 0 0'><small>نجح {ok} ورسب {n - ok}</small></p>")
    bars = "".join(f"<div class=col><b>{c}</b><i style='height:{max(2, int(100 * c / mx))}%;background:{b[3]}'></i></div>" for c, b in zip(counts, BANDS))
    labs = "".join(f"<span>{b[1]}<br><small>{b[2]}</small></span>" for b in BANDS)
    return head + (f"<div class=charts><div class=card><h3>نسبة النجاح والرسوب</h3>{donut}</div>"
                   f"<div class=card><h3>توزيع العلامات (عدد الطلاب بكل فئة)</h3><div class=hist>{bars}</div><div class=histlab>{labs}</div></div></div></div>")
def teacher_nav(ctx, active):
    """شريط تنقل واحد لكل صفحات المعلم (مخفي بالطباعة): اسم الامتحان + التبويبات، وزر القفل لو في كلمة سر. رموز الدخول بتبين بس لو مفعّلة"""
    tabs = "".join(f"<a href={u}{' class=on aria-current=page' if k == active else ''}>{n}</a>" for k, u, n in TABS if k != "codes" or ctx.SET["needCode"])
    lock = " <a class='btn ghost lock' href=/logout>🔒 قفل</a>" if ctx.SET["tpass"] else ""
    return f"<header class='tnav noprint'><div class=brand>{html.escape(ctx.SET['title'])}</div><nav>{tabs}</nav>{lock}</header>"
def teacher_page(ctx, body, active, title="", head=""):
    """صفحة معلم كاملة: الستايل المشترك + شريط التنقل + المحتوى"""
    return "<!doctype html>" + CSS + head + f"<title>{html.escape(title)}</title>" + "<body>" + teacher_nav(ctx, active) + body
def login_page(ctx, nxt):
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>دخول المعلم</title>"
            "<style>body{font-family:Tahoma,Arial;background:#f4f6f8;display:flex;justify-content:center;padding-top:12vh}"
            ".box{background:#fff;border:1px solid #d8dee4;border-radius:12px;padding:26px;width:min(92vw,360px);text-align:center}"
            "h2{color:#14566b;margin:0 0 6px}p{color:#5d6b7a;font-size:14px}input,button{font:inherit;width:100%;padding:11px;border-radius:8px;border:1px solid #d8dee4;margin-top:10px;box-sizing:border-box}"
            "button{background:#14566b;color:#fff;border:0;font-weight:bold;cursor:pointer}#m{color:#b3261e;margin-top:10px;min-height:22px}</style>"
            "<div class=box><h2>🔒 صفحة للمعلم فقط</h2><p>اكتب كلمة سر المعلم (مكتوبة بملف settings.txt)</p>"
            "<input id=p type=password autofocus autocomplete=off><button id=b>دخول</button><div id=m></div></div>"
            "<script>const NEXT=__NEXT__;const p=document.getElementById('p'),m=document.getElementById('m');"
            "const NOCK='كلمة السر صحيحة، بس المتصفح مانع الكوكيز (Cookies) فما بيقدر يحفظ دخولك. اسمح بالكوكيز لـ localhost أو افتح الصفحة بـ Edge أو Chrome.';"
            "async function go(){let j;try{const r=await fetch('/login',{method:'POST',headers:{'Content-Type':'application/json','X-Exam-Action':'1'},body:JSON.stringify({password:p.value})});j=await r.json()}"
            "catch(e){m.textContent='تعذّر الاتصال بالسيرفر: تأكد إن النافذة السوداء شغّالة، وافتح الصفحة من جهاز السيرفر على http://localhost';return}"
            "if(j.ok){let c={};try{c=await (await fetch('/authcheck',{cache:'no-store'})).json()}catch(e){}if(c.authed===false){m.textContent=NOCK;return}location.href=NEXT}"
            "else m.textContent=j.locked?('محاولات خاطئة كثيرة، انتظر '+j.locked+' ثانية'):'كلمة السر غير صحيحة. انتبه للغة الكيبورد (عربي/English) والأحرف الكبيرة والصغيرة.'}"
            "document.getElementById('b').onclick=go;p.onkeydown=e=>{if(e.key==='Enter')go()}</script>").replace("__NEXT__", json.dumps(nxt))
def report_page(ctx, arch_home=None):
    """التقرير: بطاقات وأعمدة بيانية (قائمة تبدّل بين كل الشعب وشعبة معيّنة)، ملخص الشعب، تحليل الأسئلة. arch_home: صفحة الأرشيف (بدون شريط التنقل وروابط نسبية)"""
    ss, qs = section_stats(ctx), question_stats(ctx); rows = student_rows(ctx)
    acts = (f"<a class=btn href='{html.escape(arch_home, True)}'>الرئيسية</a> <a class=btn href='report.xlsx'>تنزيل Excel (علامات الشعب + التحليل)</a>" if arch_home else "<a class=btn href=/report.xlsx>تنزيل Excel (علامات الشعب + التحليل)</a>") + " <button class='btn ghost' onclick=print()>طباعة</button>"
    secs = sorted({(r["grade"], r["section"]) for r in rows})
    sel = "<select id=secf aria-label='الشعبة'><option value=''>كل الشعب</option>" + "".join(f"<option value='{html.escape(g + '|' + s, True)}'>{html.escape(g)} — شعبة {html.escape(s)}</option>" for g, s in secs) + "</select>"
    done = [r for r in rows if r["status"] == "done"]
    blocks = rv_block(ctx, "", [r["score"] / r["total"] * 100 if r["total"] else 0 for r in done], len(rows), False)
    for g, s in secs:
        sec = [r for r in rows if r["grade"] == g and r["section"] == s]
        blocks += rv_block(ctx, f"{g}|{s}", [r["score"] / r["total"] * 100 if r["total"] else 0 for r in sec if r["status"] == "done"], len(sec), True)
    h = (f"<div class=pagehead><h2>تقرير الامتحان</h2><div class=noprint>{sel} {acts}</div></div>"
         + f"<p><small>{html.escape(ctx.SET['title'])}</small></p>" + blocks
         + "<script>var f=document.getElementById('secf');f.onchange=function(){document.querySelectorAll('.rv').forEach(function(b){b.hidden=b.dataset.k!==f.value})}</script>"
         + "<h3>ملخص الشعب</h3><div class=tw><table><tr><th>الصف</th><th>الشعبة</th><th>الطلاب</th><th>سلّموا</th><th>المتوسط %</th><th>الأعلى %</th><th>الأقل %</th><th>توزيع العلامات (0-20 / 20-40 / 40-60 / 60-80 / 80-100)</th></tr>")
    for r in sorted(ss, key=lambda r: (r["grade"], r["section"])):
        mx = max(r["dist"]) or 1
        bars = " ".join(f"<span class=bar style='width:{int(40*c/mx)+2}px' title={c}></span>{c}" for c in r["dist"])
        h += f"<tr><td>{html.escape(r['grade'])}</td><td>{html.escape(r['section'])}</td><td>{r['students']}</td><td>{r['submitted']}</td><td>{'' if r['avg'] is None else r['avg']}</td><td>{'' if r['max'] is None else r['max']}</td><td>{'' if r['min'] is None else r['min']}</td><td>{bars}</td></tr>"
    h += "</table></div><h3>تحليل الأسئلة (الأصعب أولاً)</h3><div class=tw><table><tr><th>السؤال</th><th>المستوى</th><th>الصفحة</th><th>مرات الظهور</th><th>نسبة الصح %</th><th>أكثر إجابة خاطئة</th><th>ملاحظة</th></tr>"
    for r in sorted(qs, key=lambda r: (r["pct"] is None, r["pct"] if r["pct"] is not None else 0)):
        pc = "" if r["pct"] is None else f"<div class=pct><span>{r['pct']}</span><i class='{'' if r['pct'] >= 70 else 'mid' if r['pct'] >= 40 else 'low'}' style='width:{max(2, round(r['pct'] * 0.8))}px'></i></div>"
        h += f"<tr><td>س{r['n']}</td><td><span class='badge {r['level']}'>{LVL.get(r['level'], '')}</span></td><td>{html.escape(str(r['page']))}</td><td>{r['appeared']}</td><td>{pc}</td><td>{html.escape(r['top_wrong'])}</td><td>{r['note']}</td></tr>"
    h += "</table></div>"
    if arch_home: return "<!doctype html>" + CSS + "<title>تقرير الامتحان</title><body>" + h
    return teacher_page(ctx, h, "report", "تقرير الامتحان")
def sheet_html(ctx, sub, wrong_only):
    ok = sub["score"]; tot = sub["total"]
    late_txt = f" &nbsp; <b style='color:#b3261e'>تسليم متأخر:</b> {sub['late']} ث" if sub.get("late") else ""
    if fmt_dur(ctx, sub.get("dur")): late_txt = f" &nbsp; <b>مدة الحل:</b> {fmt_dur(ctx, sub['dur'])}" + late_txt
    h = f"<div class=pg><div class=hd><h2 style='margin:4px 0'>{html.escape(sub['exam'])}</h2><b>الاسم:</b> {html.escape(sub['name'])} &nbsp; <b>الصف:</b> {html.escape(sub['grade'])} &nbsp; <b>الشعبة:</b> {html.escape(sub['section'])} &nbsp; <b>العلامة:</b> <span dir=ltr>{ok} / {tot}</span> &nbsp; <b>الخروج من الصفحة:</b> {html.escape(str(sub.get('leave','')))}{late_txt}</div>"
    for i, (n, v) in enumerate(zip(sub["ids"], sub["answers"]), 1):
        q = ctx.BANK[n]; right = v == q["a"]
        if wrong_only and right: continue
        h += f"<div class='q {'good' if right else 'bad'}'><div><b>{i}. (س{n} — {LVL.get(q['level'], '')} — {mtxt(eff_mark(ctx, q['marks'], sub['ids']))})</b> {'✓' if right else '✗'} <span dir={bdir(q['q'])}>{qhtml(ctx, q['q'])}</span></div>"
        for j, o in enumerate(q["o"]):
            c = "o" + (" right" if j == q["a"] else "") + (" given" if j == v else "") + (" wrongc" if j == v and not right else "")
            mark = (" ← إجابة الطالب" if j == v else "") + (" ✓ الصحيحة" if j == q["a"] else "")
            h += f"<div class='{c}'>{L[j]}) <span dir={bdir(o)}>{qhtml(ctx, o)}</span><small>{mark}</small></div>"
        if v < 0: h += "<div class=o style='color:#b3261e'>لم يجب</div>"
        h += "</div>"
    return h + "</div>"
def sheet_page(ctx, q):
    wo = q.get("wrong") == "1"
    def bar(extra=""): return f"<p class=noprint><a class='btn ghost' href=/sheet>قائمة الطلاب</a>{extra}</p>"
    if q.get("key"):
        sub = ctx.SUBS.get(q["key"])
        if not sub: return teacher_page(ctx, "لا يوجد تسليم لهذا الطالب.", "sheet", "ورقة طالب")
        tg = f"<a class=btn href='/sheet?key={urllib.parse.quote(q['key'])}{'' if wo else '&wrong=1'}'>{'عرض كل الأسئلة' if wo else 'عرض الخاطئة فقط'}</a> <button class=btn onclick=print()>طباعة</button>"
        return teacher_page(ctx, bar(" " + tg) + sheet_html(ctx, sub, wo), "sheet", "ورقة طالب", SHEET_CSS)
    if q.get("g") is not None and q.get("s") is not None:
        subs = [r for r in student_rows(ctx) if r["grade"] == q["g"] and r["section"] == q["s"] and r["status"] == "done"]
        tg = f"<a class=btn href='/sheet?g={urllib.parse.quote(q['g'])}&s={urllib.parse.quote(q['s'])}{'' if wo else '&wrong=1'}'>{'عرض كل الأسئلة' if wo else 'عرض الخاطئة فقط'}</a> <button class=btn onclick=print()>طباعة الكل ({len(subs)} ورقة)</button>"
        return teacher_page(ctx, bar(" " + tg) + "".join(sheet_html(ctx, ctx.SUBS[r["key"]], wo) for r in subs), "sheet", "ورقات الشعبة", SHEET_CSS)
    rows = student_rows(ctx); h = "<div class=pagehead><h2>ورقات الطلاب</h2></div>"
    for (g, s) in sorted({(r["grade"], r["section"]) for r in rows}):
        sec = [r for r in rows if r["grade"] == g and r["section"] == s]; dn = [r for r in sec if r["status"] == "done"]
        h += f"<h3>{html.escape(g)} — شعبة {html.escape(s)} ({len(dn)} سلّموا)</h3><p><a class=btn target=_blank href='/sheet?g={urllib.parse.quote(g)}&s={urllib.parse.quote(s)}'>طباعة ورقات الشعبة كلها</a></p><table><tr><th>الاسم</th><th>العلامة</th><th></th></tr>"
        for r in dn: h += f"<tr><td>{html.escape(r['name'])}</td><td>{r['score']} / {r['total']}</td><td><a class=btn target=_blank href='/sheet?key={urllib.parse.quote(r['key'])}'>فتح الورقة</a></td></tr>"
        h += "</table>"
    return teacher_page(ctx, h, "sheet", "ورقات الطلاب")
def codes_page(ctx):
    pr = "<p class=noprint><button class=btn onclick=print()>طباعة (قصاصات للقص)</button></p>"
    if not ctx.SET["needCode"]: return teacher_page(ctx, "<p>رمز الدخول غير مفعّل. فعّله بـ <b>رمز_الدخول = نعم</b> في settings.txt ثم شغّل السيرفر من جديد.</p>", "codes", "رموز الدخول", "<style>@media print{.noprint{display:none}body{background:#fff;max-width:none;margin:0}}</style>")
    head = "<style>.slip{box-sizing:border-box;display:inline-block;width:31%;border:1px dashed #888;padding:8px;margin:4px;vertical-align:top;page-break-inside:avoid;background:#fff}.code{font-size:28px;font-weight:bold;letter-spacing:4px;direction:ltr;display:block;text-align:center;color:#14566b}.sc{page-break-after:always}@media print{.noprint{display:none}body{background:#fff;max-width:none;margin:0}}</style>"
    h = pr + "<p class=noprint>كل طالب بياخذ رمزه بورقة صغيرة (اقصّها) ويكتبه عند بداية الامتحان. الرموز محفوظة بملف codes.json — امسحه لتوليد رموز جديدة. <b>لا تعرض هذه الصفحة على شاشة الصف.</b></p>"
    for g, secs in ctx.ROSTER.items():
        for s, names in secs.items():
            h += f"<div class=sc><h3>{html.escape(g)} — شعبة {html.escape(s)}</h3>"
            for n in names: h += f"<div class=slip>{html.escape(n)}<span class=code>{html.escape(ctx.CODES[f'{g}|{s}|{n}'])}</span></div>"
            h += "</div>"
    return teacher_page(ctx, h, "codes", "رموز الدخول", head)
def key_page(ctx, arch_home=None):
    """مفتاح الإجابات. arch_home: صفحة الأرشيف (بدون شريط التنقل)"""
    top = (f"<p class=noprint><a class=btn href='{html.escape(arch_home, True)}'>الرئيسية</a> " if arch_home else "<p class=noprint>") + "<button class=btn onclick=print()>طباعة</button></p>"
    h = top + f"<h2>مفتاح الإجابات — {html.escape(ctx.SET['title'])}</h2><p>عدد الأسئلة بالبنك: {len(ctx.QLIST)} | بالامتحان: {sum(ctx.PICK.values())} ({'، '.join(f'{glabel(ctx, k)} {v}' for k, v in ctx.PICK.items() if v)}) | مجموع علامات الامتحان: {'%s' % total_range(ctx, ctx.PICK)[0] if total_range(ctx, ctx.PICK)[0] == total_range(ctx, ctx.PICK)[1] else '%s إلى %s' % total_range(ctx, ctx.PICK)}</p>"
    for lv in (list(ctx.PICK) + ["_out"] if any(k not in LVL for k in ctx.PICK) else ("hard", "medium", "easy")):
        qs = [q for q in ctx.QLIST if (grp(q) == lv if lv != "_out" else grp(q) not in ctx.PICK)]
        if not qs: continue
        h += f"<h3>{glabel(ctx, lv) if lv != '_out' else 'أسئلة خارج قواعد السحب (ما رح تظهر بالامتحان)'} ({len(qs)})</h3>"
        for q in qs:
            h += f"<div class='q'><b>س{q['n']}</b> <small>(سطر {q['row']} بالملف{' — ' + html.escape(str(q['page'])) if q['page'] else ''} — {mtxt(key_mark(ctx, q['marks']))})</small> <span dir={bdir(q['q'])}>{qhtml(ctx, q['q'])}</span>"
            for j, o in enumerate(q["o"]): h += f"<div class='o{' right' if j == q['a'] else ''}'>{L[j]}) <span dir={bdir(o)}>{qhtml(ctx, o)}</span>{' ✓' if j == q['a'] else ''}</div>"
            if q["sol"]: h += f"<div class=o><small>الحل: {html.escape(q['sol'])}</small></div>"
            h += "</div>"
    if arch_home: return "<!doctype html>" + CSS + SHEET_CSS + "<title>مفتاح الإجابات</title><body>" + h
    return teacher_page(ctx, h, "key", "مفتاح الإجابات", SHEET_CSS)
def build_preview(ctx):
    """معاينة المعلم: كل أسئلة البنك بنفس واجهة الطالب، بترتيبها الأصلي، وتصحيح بالمتصفح (الإجابات الصحيحة موجودة بالصفحة، فهي محميّة بكلمة السر وللمعلم فقط). ما بتنحفظ نتيجتها"""
    lv = Counter(q["level"] for q in ctx.QLIST)
    pick = {k: lv.get(k, 0) for k in ("hard", "medium", "easy")}
    title = "معاينة المعلم — " + ctx.SET["title"]
    conf = ("const CONFIG = {examTitle: %s, minutes: 600, pick: %s, shuffleQuestions: false, shuffleOptions: false, showScore: true, oneAttemptPerDevice: false, "
            "serverGrading: false, claimNames: false, lockdown: false, reviewMode: \"no\", needCode: false, teacherPreview: true, endpoint: \"\"};" %
            (json.dumps(title, ensure_ascii=False).replace("</", "<\\/"), json.dumps(pick)))
    t = open(os.path.join(ctx.BASE, "template.html"), encoding="utf-8").read()
    i = t.index("const CONFIG = {"); j = t.index("};", i) + 2
    t = t[:i] + conf + t[j:]
    t = t.replace("/*ROSTER*/{}", json.dumps({"المعلم": {"معاينة": ["معاينة المعلم"]}}, ensure_ascii=False))
    qs = [{"n": q["n"], "level": q["level"], "page": q["page"], "marks": q.get("marks", 1), "q": qhtml(ctx, q["q"]), "o": [qhtml(ctx, o) for o in q["o"]], "a": q["a"]} for q in ctx.QLIST]
    i = t.index("const QUESTIONS = ["); j = t.index("];\nconst ROSTER", i)
    t = t[:i] + "const QUESTIONS = " + json.dumps(qs, ensure_ascii=False).replace("</", "<\\/") + t[j + 1:]
    t = t.replace("<title>الامتحان الإلكتروني</title>", "<title>معاينة المعلم</title>", 1)
    out = " &nbsp; <a href=/logout style='color:#fff'>🔒 قفل</a>" if ctx.SET["tpass"] else ""
    banner = ("<div style='background:#14566b;color:#fff;padding:8px 14px;font-weight:bold;display:flex;gap:12px;justify-content:space-between;flex-wrap:wrap'>"
              "<span>🔍 معاينة المعلم: كل أسئلة البنك (%d سؤال) بنفس واجهة الطالب. النتيجة ما بتنحفظ وما بتظهر بالمراقبة.</span>"
              "<span><a href=/monitor style='color:#fff'>المراقبة</a>%s</span></div>" % (len(qs), out))
    t = t.replace("<body>", "<body>" + banner, 1)
    auto = "(async()=>{const g=$('g');g.selectedIndex=1;g.onchange();const s=$('sec');s.selectedIndex=1;await s.onchange();const n=$('nm');n.selectedIndex=1;n.onchange();$('start').click()})();\n"
    return t.replace("</script>\n</body>", auto + "</script>\n</body>", 1)
def settings_page(ctx):
    return teacher_page(ctx, SETTINGS_BODY, "settings", "إعدادات الامتحان")
def not_ready_page(ctx):
    """صفحة الطالب لما الامتحان لسا غير جاهز (وضع التجهيز: الأسئلة أو الطلاب ما انرفعوا بعد): بتتحدّث لحالها كل 8 ثواني، وأول ما يجهز المعلم الامتحان بتفتح صفحة الدخول"""
    return ("<!doctype html><html lang=ar dir=rtl><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><meta http-equiv=refresh content=8><title>الامتحان غير جاهز</title>"
            "<body style='font-family:Tahoma,Segoe UI,Arial,sans-serif;background:#eaf1f4;margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center'>"
            "<div style='background:#fff;border-radius:16px;padding:28px 24px;max-width:420px;margin:16px;text-align:center;box-shadow:0 8px 28px #0001'>"
            "<div style='font-size:42px'>⏳</div><h2 style='color:#14566b;margin:8px 0'>الامتحان لسا غير جاهز</h2>"
            "<p style='color:#33414f;line-height:1.9;margin:6px 0'>انتظر المعلم، بيجهّز الامتحان هلأ.<br>هالصفحة بتتحدّث لحالها، وأول ما يجهز بتفتح لك صفحة الدخول.</p></div>")
def files_page(ctx):
    return teacher_page(ctx, FILES_BODY, "files", "الملفات")
def build_page(ctx):
    cfg, qs, ros = ctx.SET, ctx.QLIST, ctx.ROSTER
    lv = Counter(q["level"] for q in qs); given = cfg.get("given", set(cfg))
    ctx.GLBL.clear(); ctx.GLBL.update(LVL)
    rules = cfg.get("rules")
    if rules:                                                           # قواعد «سحب» من settings.txt: تلغي أعداد المستويات القديمة
        cols = set().union(*(q["cols"] for q in qs))
        for r in rules:
            for col, _, _ in r["conds"]:
                if col not in cols: raise DataError(f"settings.txt سطر {r['ln']}: ما في عمود اسمه «{col}» بملف الأسئلة — الأعمدة الموجودة: " + "، ".join(sorted(cols)))
        if given & {"hard", "medium", "easy", "count"}: ctx.print("تنبيه: فيه سطور «سحب» بـ settings.txt فتجاهلت عدد_الأسئلة_الصعبة/المتوسطة/السهلة/الكلي")
        for q in qs: q["grp"] = None
        pick, bad = {}, []
        for i, r in enumerate(rules, 1):
            key = f"r{i}"; ctx.GLBL[key] = f"قاعدة {i}: {r['label']}"
            for q in qs:
                if q["grp"] is None and rule_match(q, r["conds"]): q["grp"] = key
            have = sum(1 for q in qs if q["grp"] == key); pick[key] = r["n"]
            if r["n"] > have: bad.append(f"القاعدة {i} ({r['label']}): مطلوب {r['n']} والموجود {have}" + (" (بعد استبعاد أسئلة القواعد السابقة)" if i > 1 else ""))
        if bad: raise DataError("عدد الأسئلة بالبنك أقل من المطلوب بقواعد السحب — " + " | ".join(bad))
    elif set(lv) <= {""} or all(q.get("autolevel") for q in qs):     # ما في مستويات: نسحب العدد الكلي من الكل (autolevel: لو انبنت الصفحة من جديد)
        for q in qs: q["level"] = "medium"; q["autolevel"] = True
        n = cfg["count"] if "count" in given else len(qs)                # العدد مش مكتوب = كل أسئلة البنك
        pick = {"hard": 0, "medium": min(n, len(qs)), "easy": 0}
        if n > len(qs): ctx.print(f"تنبيه: عدد الأسئلة بالامتحان ({n}) أكبر من البنك ({len(qs)}) — رح ينسحب {len(qs)}")
    else:
        for q in qs:
            if q["level"] == "": raise DataError(f"questions سطر {q['row']}: المستوى فاضي، وباقي الأسئلة إلها مستوى — عبّيه أو امسح عمود المستوى كله")
        pick = {k: (cfg[k] if k in given else lv[k]) for k in ("hard", "medium", "easy")}     # مستوى مش مكتوب = كل أسئلته
        bad = [f"{LVL[k]}: مطلوب {pick[k]} والموجود {lv[k]}" for k in pick if pick[k] > lv[k]]
        if bad: raise DataError("عدد الأسئلة بالبنك أقل من المطلوب بالامتحان — " + " | ".join(bad))
    if not rules:
        for q in qs: q["grp"] = q["level"]
    fx = Counter(grp(q) for q in qs if q.get("fixed"))
    badf = [f"{glabel(ctx, k)}: ثوابت {fx[k]} والمطلوب بالامتحان {pick[k]}" for k in pick if fx[k] > pick[k]]
    if badf: raise DataError("عدد الأسئلة الثابتة (عمود «ثابت») أكبر من عدد أسئلة المستوى المطلوبة بالامتحان — " + " | ".join(badf))
    if cfg["qmark"] and cfg["final"]:                    # الاثنان مكتوبان: لازم يتطابقوا (مثلاً 20 سؤال × 1.5 = 30)
        N = sum(pick.values())
        if abs(N * cfg["qmark"] - cfg["final"]) > 0.005:
            raise DataError(f"settings.txt: عدد أسئلة الامتحان ({N}) × علامة_السؤال ({cfg['qmark']}) = {num(N * cfg['qmark'])} لكن العلامة_النهائية {cfg['final']} — صحّح أحدهما أو اترك واحداً منهما فاضياً")
    conf = ("const CONFIG = {examTitle: %s, minutes: %d, pick: %s, shuffleQuestions: %s, shuffleOptions: %s, showScore: %s, oneAttemptPerDevice: true, "
            "serverGrading: true, claimNames: true, lockdown: %s, reviewMode: \"%s\", needCode: %s, finalMark: %s, endpoint: \"/submit\"};" %
            (json.dumps(cfg["title"], ensure_ascii=False), cfg["minutes"], json.dumps({"hard": 0, "medium": sum(pick.values()), "easy": 0} if rules else pick), str(cfg["shuffleQ"]).lower(),
             str(cfg["shuffleO"]).lower(), str(cfg["showScore"]).lower(), str(cfg["lockdown"]).lower(), cfg["review"], str(cfg["needCode"]).lower(), json.dumps(cfg["final"])))
    t = open(os.path.join(ctx.BASE, "template.html"), encoding="utf-8").read()
    i = t.index("const CONFIG = {"); j = t.index("};", i) + 2
    sj = lambda o: json.dumps(o, ensure_ascii=False).replace("</", "<\\/")      # JSON آمن داخل <script>
    t = t[:i] + conf.replace("</", "<\\/") + t[j:]
    t = t.replace("/*ROSTER*/{}", sj(ros))
    i = t.index("const QUESTIONS = ["); j = t.index("];\nconst ROSTER", i)
    # نصوص الأسئلة بتنعرض كـ HTML بصفحة الطالب، فنهرّب < و > و & (مثلاً «x<y» أو «a&b» ما تخرّب العرض)
    cq = []                                    # بنك الأسئلة ما بينحط بالصفحة: كل طالب بياخذ أسئلة ورقته بس من /start (pub_q)
    t = t[:i] + "const QUESTIONS = " + sj(cq) + t[j + 1:]
    t = t.replace("<title>الامتحان الإلكتروني</title>", "<title>%s</title>" % html.escape(cfg["title"]), 1)
    for k in pick:                                        # تنبيه: مجموعة علاماتها مختلفة + سحب عشوائي = مجموع مختلف بين الطلاب
        ms = sorted({q["marks"] for q in qs if grp(q) == k})
        if pick[k] and not cfg["final"] and len(ms) > 1 and pick[k] < sum(1 for q in qs if grp(q) == k):
            ctx.print(f"تنبيه: أسئلة «{glabel(ctx, k)}» علاماتها مختلفة {ms} والامتحان يسحب منها عشوائياً — مجموع العلامات رح يختلف من طالب لطالب")
    return t, pick
