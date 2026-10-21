// إشعارات حية على شاشة المراقبة: بنقارن كل تحديث (كل 4 ثواني) بالتحديث اللي قبله ونطلع منه أحداث (بدأ، سلّم، انقطع، رجع، خرج من الصفحة).
// الدوال هون صافية (ما بتلمس الصفحة) ما عدا الصوت والتفضيلات.

export type Level = 'info' | 'ok' | 'warn';
export type Kind = 'start' | 'done' | 'lost' | 'back' | 'leave' | 'reopen';
export type Ev = { id: number; kind: Kind; level: Level; who: string; section: string; text: string; at: string; student?: string };
export type EvDraft = Omit<Ev, 'id' | 'at'>;

type Row = { name: string; status: 'done' | 'live' | 'lost' | 'none'; leaveN?: number; score?: number; total?: number; ago?: number | null };
type Sections = Record<string, Row[]>;

const LEVEL: Record<Kind, Level> = { start: 'info', done: 'ok', lost: 'warn', back: 'info', leave: 'warn', reopen: 'info' };
const GROUP_TEXT: Record<Kind, string> = {
  start: 'بدؤوا الامتحان', done: 'سلّموا', lost: 'انقطع اتصالهم', back: 'عاد اتصالهم', leave: 'خرجوا من الصفحة', reopen: 'أُعيد فتحهم',
};
export const MAX_GROUP_SINGLES = 3;   // أكثر من 3 أحداث من نفس النوع بنفس التحديث بتتجمّع بإشعار واحد

export function studentId(section: string, name: string) { return `${section}::${name}`; }

/**
 * الأحداث بين تحديثين. فك الحجز وبداية امتحان جديد («لم يبدأ») ما بنعتبرهم حدث.
 * الطالب اللي ضغط «ابدأ» بيطلع «انقطع/لم يتصل بعد» لحد ما توصل نبضته الأولى (ثواني): هذا مش انقطاع، فبنسجّله بـ `starting`
 * ولما يصير «يمتحن» بنعلن «بدأ الامتحان». (`starting` بتتعدّل جوّا الدالة وبيحتفظ فيها المستدعي بين التحديثات.)
 */
export function diffEvents(before: Sections, after: Sections, starting: Set<string> = new Set()): EvDraft[] {
  const old = new Map<string, Row>();
  Object.entries(before).forEach(([section, rows]) => rows.forEach((row) => old.set(studentId(section, row.name), row)));
  const out: EvDraft[] = [];
  Object.entries(after).forEach(([section, rows]) => rows.forEach((row) => {
    const id = studentId(section, row.name), prev = old.get(id), wasStarting = starting.has(id);
    if (row.status !== 'lost' || row.ago != null) starting.delete(id);
    if (!prev) return;
    const add = (kind: Kind, text: string) => out.push({ kind, level: LEVEL[kind], who: row.name, section, text, student: id });
    if (row.status === 'done' && prev.status !== 'done') add('done', row.total ? `سلّم · ${row.score ?? 0} / ${row.total}` : 'سلّم');
    else if (row.status === 'lost' && row.ago == null && prev.status === 'none') starting.add(id);
    else if (row.status === 'live' && (prev.status === 'none' || (prev.status === 'lost' && wasStarting))) add('start', 'بدأ الامتحان');
    else if (row.status === 'live' && prev.status === 'lost') add('back', 'عاد اتصاله');
    else if (row.status === 'live' && prev.status === 'done') add('reopen', 'أُعيد فتحه');
    else if (row.status === 'lost' && prev.status === 'live') add('lost', 'انقطع اتصاله');
    else if (row.status === 'live' && prev.status === 'live' && (row.leaveN || 0) > (prev.leaveN || 0)) add('leave', `خرج من الصفحة (للمرة ${row.leaveN})`);
  }));
  return out;
}

function countWord(n: number) { return `${n} ${n > 10 ? 'طالباً' : 'طلاب'}`; }

/** أكثر من 3 من نفس النوع = إشعار واحد («6 طلاب سلّموا») بدل ما يغرق الشاشة. */
export function groupEvents(drafts: EvDraft[]): EvDraft[] {
  const byKind = new Map<Kind, EvDraft[]>();
  drafts.forEach((d) => byKind.set(d.kind, [...(byKind.get(d.kind) || []), d]));
  const out: EvDraft[] = [];
  byKind.forEach((list, kind) => {
    if (list.length <= MAX_GROUP_SINGLES) { out.push(...list); return; }
    out.push({ kind, level: LEVEL[kind], who: countWord(list.length), section: '', text: GROUP_TEXT[kind] });
  });
  return out;
}

// ---------- الصوت: نغمات قصيرة من WebAudio (بدون ملفات صوت) ----------
let audio: AudioContext | null = null;
function context(): AudioContext | null {
  try {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return null;
    audio = audio || new AC();
    if (audio.state === 'suspended') void audio.resume();
    return audio;
  } catch { return null; }
}
/** المتصفح بيمنع الصوت قبل ما المستخدم يتفاعل مع الصفحة: بنفتحه مع أول ضغطة. */
export function unlockAudio() { context(); }
export function playTone(level: Level) {
  const ctx = context();
  if (!ctx) return;
  try {
    const notes = level === 'warn' ? [660, 440] : level === 'ok' ? [880] : [660];
    const t0 = ctx.currentTime;
    notes.forEach((freq, i) => {
      const osc = ctx.createOscillator(), gain = ctx.createGain(), at = t0 + i * 0.17;
      osc.type = 'sine'; osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.linearRampToValueAtTime(0.16, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.3);
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start(at); osc.stop(at + 0.32);
    });
  } catch { /* الصوت إضافة: لو فشل ما بنوقف الشاشة */ }
}

// ---------- تفضيلات المعلم (على هذا المتصفح بس) ----------
export function readPref(name: string, fallback: boolean) {
  try { const v = window.localStorage.getItem(`exam_monitor_${name}`); return v === null ? fallback : v === '1'; } catch { return fallback; }
}
export function writePref(name: string, value: boolean) {
  try { window.localStorage.setItem(`exam_monitor_${name}`, value ? '1' : '0'); } catch { /* وضع خاص أو تخزين ممنوع */ }
}
