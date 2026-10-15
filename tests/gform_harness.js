// بيشغّل 05_برنامج_الفورم_الاحتياطي.txt بدون إنترنت، ضد نسخة وهمية من Google (FormApp وSpreadsheetApp وDriveApp)،
// وبيطبع اللي انعمل كـ JSON. الوهمي فيه بس الأوامر اللي موجودة فعلاً بـ Apps Script، فأي أمر غلط بالبرنامج بيوقّع الاختبار.
// الاستعمال: node gform_harness.js SCRIPT.txt INPUT.json   (INPUT: rows, settings, images, imagesFolder, ui, seed, name)
"use strict";
const fs = require("fs"), vm = require("vm");
const [scriptPath, inputPath] = process.argv.slice(2);
const inp = JSON.parse(fs.readFileSync(inputPath, "utf8"));
const out = {forms: [], sheets: {}, alerts: [], logs: [], menus: [], moved: [], error: null};

const chain = (obj, names) => { for (const n of names) obj[n] = function (v) { this["_" + n] = v; return this; }; return obj; };
const iter = (arr) => { let i = 0; return {hasNext: () => i < arr.length, next: () => arr[i++]}; };

function item(type) {
  const it = {type};
  chain(it, ["setTitle", "setHelpText", "setRequired"]);
  if (type === "mc") {
    it.createChoice = (value, isCorrect) => {
      if (typeof value !== "string" || !value) throw new Error("createChoice: قيمة فاضية");
      return {value, isCorrect: !!isCorrect};
    };
    it.setChoices = function (cs) {
      const vals = cs.map((c) => c.value);
      if (new Set(vals).size !== vals.length) throw new Error("Invalid data updating form: خيارات مكررة");
      this._choices = cs; return this;
    };
    it.setPoints = function (p) { if (!Number.isInteger(p) || p < 0) throw new Error("setPoints: لازم رقم صحيح " + p); this._points = p; return this; };
  }
  if (type === "image") it.setImage = function (b) { if (!b || !b.isBlob) throw new Error("setImage: مش صورة"); this._image = b.name; return this; };
  return it;
}
let fid = 0;
const FormApp = {
  DestinationType: {SPREADSHEET: "SPREADSHEET"},
  create(title) {
    const f = {id: "form" + (++fid), title, items: []};
    chain(f, ["setIsQuiz", "setTitle", "setDescription", "setProgressBar", "setShowLinkToRespondAgain", "setConfirmationMessage",
              "setShuffleQuestions", "setAcceptingResponses", "setCustomClosedFormMessage", "setCollectEmail", "setAllowResponseEdits",
              "setPublishingSummary", "setLimitOneResponsePerUser"]);
    f.setDestination = function (type, id) { this._dest = [type, id]; return this; };
    const add = (t) => () => { const it = item(t); f.items.push(it); return it; };
    f.addTextItem = add("text"); f.addPageBreakItem = add("page"); f.addMultipleChoiceItem = add("mc"); f.addImageItem = add("image");
    f.getId = () => f.id;
    f.getPublishedUrl = () => "https://docs.google.com/forms/d/e/" + f.id + "/viewform";
    f.getEditUrl = () => "https://docs.google.com/forms/d/" + f.id + "/edit";
    f.shortenFormUrl = (u) => "https://forms.gle/" + f.id;
    out.forms.push(f);
    return f;
  },
};
function sheet(name, rows) {
  const sh = {name, rows: rows.map((r) => r.slice())};
  sh.getName = () => sh.name;
  sh.getLastColumn = () => Math.max(0, ...sh.rows.map((r) => r.length));
  sh.getLastRow = () => sh.rows.length;
  sh.getDataRange = () => ({getDisplayValues: () => {
    const w = sh.getLastColumn();
    return sh.rows.map((r) => Array.from({length: w}, (_, i) => (r[i] == null ? "" : String(r[i]))));
  }});
  sh.getRange = (r, c, nr, nc) => {
    if (!(r >= 1 && c >= 1 && nr >= 1 && nc >= 1)) throw new Error("getRange: أبعاد غلط");
    return {
      getDisplayValues: () => Array.from({length: nr}, (_, i) => Array.from({length: nc}, (_, j) => String((sh.rows[r - 1 + i] || [])[c - 1 + j] ?? ""))),
      setValues: (vals) => {
        if (vals.length !== nr || vals.some((v) => v.length !== nc)) throw new Error("setValues: الأبعاد مش مطابقة");
        vals.forEach((v, i) => { sh.rows[r - 1 + i] = sh.rows[r - 1 + i] || []; v.forEach((x, j) => { sh.rows[r - 1 + i][c - 1 + j] = x; }); });
      },
    };
  };
  sh.clear = () => { sh.rows = []; return sh; };
  sh.setRightToLeft = () => sh;
  out.sheets[name] = sh;
  return sh;
}
const ss = {sheets: [sheet(inp.sheetName || "questions", inp.rows)]};
for (const [n, r] of Object.entries(inp.extraSheets || {})) ss.sheets.push(sheet(n, r));
ss.getId = () => "ss1"; ss.getName = () => inp.name || "questions";
ss.getSheets = () => ss.sheets.slice();
ss.getSheetByName = (n) => ss.sheets.find((s) => s.name === n) || null;
ss.insertSheet = (n) => { const s = sheet(n, []); ss.sheets.push(s); return s; };
const ui = {
  alert(m) { out.alerts.push(m); },
  createMenu(t) { const m = {title: t, items: []}; out.menus.push(m); return {addItem(l, fn) { m.items.push([l, fn]); return this; }, addToUi() {}}; },
};
const SpreadsheetApp = {
  getActiveSpreadsheet: () => ss,
  getUi: () => { if (inp.ui) return ui; throw new Error("Cannot call SpreadsheetApp.getUi() from this context."); },
};
const blob = (n) => ({isBlob: true, name: n});
const imagesDir = {getFilesByName: (n) => iter((inp.images || []).includes(n) ? [{getBlob: () => blob(n)}] : [])};
const parent = {getFoldersByName: (n) => iter(n === "images" && inp.imagesFolder !== false ? [imagesDir] : [])};
const DriveApp = {
  getFileById: (id) => ({getParents: () => iter([parent]), moveTo: (f) => { out.moved.push(id); }}),
};
const Logger = {log: (m) => out.logs.push(String(m))};

let seed = inp.seed || 1;
const ctx = vm.createContext({FormApp, SpreadsheetApp, DriveApp, Logger});
vm.runInContext(fs.readFileSync(scriptPath, "utf8"), ctx, {filename: "gform.gs"});
vm.runInContext("Math.random = function(){ __s = (__s * 1103515245 + 12345) % 2147483648; return __s / 2147483648; }", Object.assign(ctx, {__s: seed}));
Object.assign(ctx.SETTINGS, inp.settings || {});
try {
  if (inp.call === "onOpen") ctx.onOpen(); else ctx.makeForm();
} catch (e) { out.error = String(e && e.message || e); }

const clean = (o) => JSON.parse(JSON.stringify(o, (k, v) => (typeof v === "function" ? undefined : v)));
out.forms = out.forms.map((f) => clean({id: f.id, title: f.title, quiz: f._setIsQuiz, description: f._setDescription, shuffle: f._setShuffleQuestions,
  accepting: f._setAcceptingResponses, dest: f._dest, progress: f._setProgressBar, again: f._setShowLinkToRespondAgain,
  items: f.items.map((i) => ({type: i.type, title: i._setTitle, help: i._setHelpText, required: i._setRequired, points: i._points, image: i._image,
    choices: i._choices && i._choices.map((c) => [c.value, c.isCorrect])}))}));
out.sheets = Object.fromEntries(Object.entries(out.sheets).map(([n, s]) => [n, s.rows]));
process.stdout.write(JSON.stringify(out));
