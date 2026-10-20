import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

declare global {
  interface Window {
    MONITOR_CONFIG?: { link?: string; title?: string };
  }
}

type Status = 'done' | 'live' | 'lost' | 'none';
type Student = {
  grade: string;
  section: string;
  name: string;
  key: string | null;
  status: Status;
  score?: number;
  total?: number;
  leave?: string;
  late?: number;
  durtxt?: string;
  answered?: number;
  remain?: number;
  leaveN?: number;
  leaveSec?: number;
  ago?: number | null;
  paused?: number;   // موقوف مؤقتاً من المعلم: ثواني منذ الإيقاف (الحقل غير موجود = مش موقوف)
};
type Rehearsal = {
  on?: boolean; left?: number; at_in?: number; full?: boolean; joined?: number;
  reported?: number; ok?: number; fail?: number; papers?: number; ms_avg?: number;
  ms_p95?: number; ms_max?: number; skew_max?: number; spread_ms?: number;
  submit_ok?: number; submit_fail?: number; submit_ms_max?: number;
  fails?: { n: number; name: string; status: string }[];
};
type MonitorData = {
  sections: Record<string, Student[]>;
  closed: boolean;
  msg: string;
  comp: null | { at?: number; downtime_s: number; students: number; sleep?: boolean; skipped?: boolean; off?: boolean };
  bank_changed: null | { subs: number; papers: number };
  reh: Rehearsal | null;
  c?: Record<Status, number>;
};
type ModalState = {
  kind: 'confirm' | 'extend' | 'message';
  title: string;
  copy?: string;
  command?: Record<string, unknown>;
  danger?: boolean;
  safeLabel?: string;
  dangerLabel?: string;
  scopeText?: string;
  final?: boolean;   // آخر تأكيد قبل التنفيذ (بداية امتحان جديد): الضغط عليه بينفّذ الأمر
} | null;
type Filter = 'all' | Status;

const STATUS: Record<Status, string> = {
  done: 'سلّم', live: 'يمتحن', lost: 'انقطع الاتصال', none: 'لم يبدأ',
};
const SUMMARY: { key: Status; label: string; style: string }[] = [
  { key: 'done', label: 'سلّموا', style: 'done' },
  { key: 'live', label: 'يمتحنون الآن', style: 'live' },
  { key: 'lost', label: 'انقطع اتصالهم', style: 'lost' },
  { key: 'none', label: 'لم يبدؤوا', style: 'none' },
];
const ATTENTION_LIMITS = { leaveCount: 2, leaveSeconds: 30, lowTimeSeconds: 120, lowAnsweredPercent: 50, pausedSeconds: 120 };
const NAV_LINKS = [
  { href: '/report', text: '📊 التقرير والتحليل', group: 0 },
  { href: '/report.xlsx', text: '⬇ تنزيل Excel', group: 0 },
  { href: '/sheet', text: '🖨 ورقات الطلاب / طباعة', group: 0 },
  { href: '/key', text: '🔑 مفتاح الإجابات', group: 1 },
  { href: '/codes', text: '🔢 رموز دخول الطلاب', group: 1 },
  { href: '/teacher', text: '🔍 معاينة الامتحان كاملاً', group: 1 },
  { href: '/health', text: '🩺 فحص السيرفر', group: 2 },
  { href: '/link', text: '🔗 رابط الامتحان بخط كبير', group: 2 },
];
const CONFIRM_COPY = {
  release: 'فك الحجز بيخلّي الطالب يبدأ من جديد (من أي جهاز، حتى نفس الجهاز) بورقة ووقت جديدين، وبتضيع إجاباته السابقة، وصفحته الحالية بترجع لشاشة الدخول لحالها. متأكد؟\nإذا بدك يكمل بنفس أسئلته وإجاباته ووقته المتبقي استخدم «نقل لجهاز آخر» بدل هذا.',
  move: 'نقل الطالب لجهاز آخر: بيكمل بنفس الأسئلة والإجابات المحفوظة والوقت اللي كان باقيله، بعد ما يختار اسمه من الجهاز الجديد.\nلازم يكون الطالب جاهز على الجهاز الجديد (الاسم بيصير متاحاً لأي حدا لحد ما يبدأ؛ فعّل رمز الدخول لو بدك حماية). متأكد؟',
  newExam: 'بداية امتحان جديد؟\nبنحفظ النتائج الحالية بمجلد أرشيف وبنصفّر الحجوزات والشاشة.\nتأكد إنك طبعت الأوراق ونزّلت Excel.',
  submit: 'تسليم إجابات هذا الطالب (المحفوظة على السيرفر) الآن وتصحيحها؟\nالأسئلة اللي ما أجاب عنها بتنحسب خاطئة، وما بيقدر يكمل بعدها.',
  close: 'إنهاء الامتحان للجميع؟ كل صفحة طالب بتسلّم تلقائياً خلال ثواني، ولا يقدر أحد يبدأ.',
  reopen: 'إعادة فتح الامتحان؟ اللي سلّموا تلقائياً يبقى تسليمهم، واللي ما سلّموا يرجع إلهم وقتهم.',
  bank: 'متأكد إن هذا نفس الامتحان وبس صلّحت أسئلة؟\nإذا امتحان جديد اضغط «بداية امتحان جديد» بدل هذا.',
};
const mockRequested = new URLSearchParams(window.location.search).get('mock') === '1';
const deterministicState = new URLSearchParams(window.location.search).get('state');
const localTitle = window.MONITOR_CONFIG?.title || 'اختبار الفيزياء — الوحدة الثانية (معاينة)';
const localLink = window.MONITOR_CONFIG?.link || 'http://192.168.43.253';

function flatten(sections: Record<string, Student> | Record<string, Student[]>): Student[] {
  return Object.values(sections).flat() as Student[];
}
function statusCounts(data: MonitorData | null): Record<Status, number> {
  const result: Record<Status, number> = { done: 0, live: 0, lost: 0, none: 0 };
  if (data) flatten(data.sections).forEach((student) => { result[student.status] += 1; });
  return result;
}
function normalizeArabic(value: string) {
  return value
    .normalize('NFD')
    .replace(/[\u064B-\u065F\u0670\u0640]/g, '')
    .replace(/[أإآٱ]/g, 'ا')
    .replace(/ى/g, 'ي')
    .toLocaleLowerCase('ar');
}
function formatTime(seconds: number) {
  const safe = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(safe / 60)).padStart(2, '0')}:${String(safe % 60).padStart(2, '0')}`;
}
function timeNow() {
  return new Date().toLocaleTimeString('en-GB', { hour12: false });
}
function percent(part: number, total: number) {
  return total ? Math.round((part / total) * 100) : 0;
}
function keyFor(row: Student, group: string) {
  return `${group}::${row.key || row.name}`;
}

function App() {
  const [data, setData] = useState<MonitorData | null>(null);
  const [filter, setFilter] = useState<Filter>(() => {
    const requested = deterministicState?.startsWith('filter-') ? deterministicState.slice(7) : '';
    return ['done', 'live', 'lost', 'none'].includes(requested) ? requested as Status : 'all';
  });
  const [query, setQuery] = useState('');
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({});
  const [openRowMenu, setOpenRowMenu] = useState<string | null>(null);
  const [rowMenuOpensUp, setRowMenuOpensUp] = useState(false);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [attentionOpen, setAttentionOpen] = useState(true);
  const [modal, setModal] = useState<ModalState>(null);
  const [toast, setToast] = useState('');
  const [loading, setLoading] = useState(true);
  const [mockMode, setMockMode] = useState(mockRequested);
  const [failureCount, setFailureCount] = useState(0);
  const [lastUpdate, setLastUpdate] = useState('');
  const [secondsSinceSync, setSecondsSinceSync] = useState(0);
  const [projector, setProjector] = useState(window.location.hash === '#big');
  const [copied, setCopied] = useState(false);
  const [extendMinutes, setExtendMinutes] = useState('5');
  const [messageText, setMessageText] = useState('');
  const safeButtonRef = useRef<HTMLButtonElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const mockCycle = useRef(0);
  const dataRef = useRef<MonitorData | null>(null);
  const fallbackTried = useRef(false);
  const failureCountRef = useRef(0);
  const demoStateApplied = useRef(false);
  const largeFixtureApplied = useRef(false);

  useEffect(() => { dataRef.current = data; }, [data]);
  useEffect(() => {
    const hashChange = () => setProjector(window.location.hash === '#big');
    window.addEventListener('hashchange', hashChange);
    return () => window.removeEventListener('hashchange', hashChange);
  }, []);
  useEffect(() => {
    if (!modal) return;
    safeButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setModal(null); return; }
      if (event.key !== 'Tab' || !modalRef.current) return;
      const elements = Array.from(modalRef.current.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled)'));
      if (!elements.length) return;
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [modal]);
  useEffect(() => {
    if (!openRowMenu && !toolsOpen) return;
    const closeFromOutside = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Element && !target.closest('.row-menu-wrap') && !target.closest('.top-menu')) {
        setOpenRowMenu(null);
        setToolsOpen(false);
      }
    };
    const closeFromEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpenRowMenu(null);
        setToolsOpen(false);
      }
    };
    document.addEventListener('pointerdown', closeFromOutside);
    window.addEventListener('keydown', closeFromEscape);
    return () => {
      document.removeEventListener('pointerdown', closeFromOutside);
      window.removeEventListener('keydown', closeFromEscape);
    };
  }, [openRowMenu, toolsOpen]);
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(''), 4200);
    return () => window.clearTimeout(id);
  }, [toast]);
  useEffect(() => {
    const id = window.setInterval(() => setSecondsSinceSync((value) => value + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  const acceptData = useCallback((next: MonitorData) => {
    if (deterministicState === 'empty' && mockMode) {
      const emptySections = Object.fromEntries(Object.entries(next.sections).map(([name, rows]) => [name, rows.map((row) => ({ ...row, status: 'none' as Status, key: null }))]));
      next = { ...next, sections: emptySections, closed: false, comp: null, bank_changed: null, msg: '' };
    }
    if (deterministicState === 'notices' && mockMode) {
      next = { ...next, closed: true, bank_changed: { subs: 14, papers: 24 }, comp: { downtime_s: 95, students: 9 } };
    }
    if (deterministicState === 'large' && mockMode && !largeFixtureApplied.current) {
      largeFixtureApplied.current = true;
      const sections = Object.fromEntries(Object.entries(next.sections).map(([section, rows]) => [
        section,
        Array.from({ length: 8 }, (_, batch) => rows.map((row) => ({
          ...row,
          key: row.key ? `${row.key}-demo-${batch + 1}` : null,
          name: `${row.name} ${batch + 1}`,
        }))).flat(),
      ]));
      const expanded = { ...next, sections };
      next = { ...expanded, c: statusCounts(expanded) };
    }
    setData(next);
    dataRef.current = next;
    setLastUpdate(timeNow());
    setSecondsSinceSync(0);
    if (failureCountRef.current >= 2) setToast('عاد الاتصال بالسيرفر.');
    failureCountRef.current = 0;
    setFailureCount(0);
    setLoading(false);
  }, [mockMode]);

  const loadData = useCallback(async () => {
    try {
      if (mockMode) {
        if (deterministicState === 'offline' && dataRef.current) {
          throw new Error('المحاكاة: انقطع الاتصال');
        }
        const response = await fetch(`${import.meta.env.BASE_URL}mock/monitor.json`, { cache: 'no-store' });
        if (!response.ok) throw new Error('تعذر تحميل بيانات المحاكاة');
        const result = await response.json() as MonitorData;
        if (dataRef.current && deterministicState !== 'empty' && deterministicState !== 'notices') {
          mockCycle.current += 1;
          result.sections = Object.fromEntries(Object.entries(dataRef.current.sections).map(([section, rows]) => [section, rows.map((row) => ({ ...row }))]));
          const candidates = flatten(result.sections).filter((row) => row.status === 'live');
          const active = candidates[mockCycle.current % Math.max(candidates.length, 1)];
          if (active) {
            if (mockCycle.current % 7 === 0) {
              active.status = 'done';
              active.score = Math.max(0, Math.round(((active.answered || 0) / (active.total || 1)) * (active.total || 10)));
              active.total = active.total || 10;
              active.durtxt = '23 د 41 ث';
              active.leave = active.leaveN ? `${active.leaveN} مرة (${active.leaveSec || 0} ث)` : 'لم يخرج';
              active.late = 0;
              delete active.remain;
            } else if (mockCycle.current % 4 === 0) {
              active.status = 'lost';
              active.ago = 31;
            } else {
              active.answered = Math.min((active.answered || 0) + 1, active.total || 10);
              active.remain = Math.max(0, (active.remain || 60) - 4);
            }
          }
          const lost = flatten(result.sections).find((row) => row.status === 'lost');
          if (lost && mockCycle.current % 5 === 0) { lost.status = 'live'; lost.ago = 2; }
          const counts = statusCounts(result);
          result.c = counts;
        }
        acceptData(result);
        return;
      }
      const response = await fetch('/monitor.json', { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json() as MonitorData;
      acceptData(result);
    } catch {
      if (!mockMode && import.meta.env.DEV && !fallbackTried.current) {
        fallbackTried.current = true;
        setMockMode(true);
        setToast('تعذر الاتصال بالسيرفر؛ بدأ وضع المحاكاة المحلي.');
        return;
      }
      setLoading(false);
      failureCountRef.current += 1;
      setFailureCount(failureCountRef.current);
    }
  }, [acceptData, mockMode]);

  useEffect(() => {
    void loadData();
    const timer = window.setInterval(() => { void loadData(); }, 4000);
    return () => window.clearInterval(timer);
  }, [loadData]);

  const counts = useMemo(() => statusCounts(data), [data]);
  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const normalizedQuery = normalizeArabic(query.trim());
  const sectionEntries = useMemo(() => {
    if (!data) return [];
    return Object.entries(data.sections).map(([section, rows]) => {
      const matching = rows.filter((row) => (filter === 'all' || row.status === filter) && (!normalizedQuery || normalizeArabic(row.name).includes(normalizedQuery)));
      return { section, rows, matching };
    }).filter(({ matching }) => matching.length > 0);
  }, [data, filter, normalizedQuery]);

  const attentionItems = useMemo(() => {
    const result: { row: Student; section: string; reason: string; urgency: number }[] = [];
    if (!data) return result;
    Object.entries(data.sections).forEach(([section, rows]) => rows.forEach((row) => {
      const leaveAlert = (row.leaveN || 0) >= ATTENTION_LIMITS.leaveCount || (row.leaveSec || 0) >= ATTENTION_LIMITS.leaveSeconds;
      const doneLeaveAlert = row.status === 'done' && row.leave && row.leave !== 'لم يخرج' && (() => {
        const number = Number(row.leave.match(/(\d+)\s*مرة/)?.[1] || 0);
        const seconds = Number(row.leave.match(/\((\d+)\s*ث\)/)?.[1] || 0);
        return number >= ATTENTION_LIMITS.leaveCount || seconds >= ATTENTION_LIMITS.leaveSeconds;
      })();
      if (row.status === 'lost') result.push({ row, section, reason: row.ago == null ? 'لم يتصل بعد' : `انقطع اتصاله منذ ${row.ago} ث`, urgency: row.ago == null ? 0 : 1000 + row.ago });
      if ((row.status === 'live' || row.status === 'done') && (leaveAlert || doneLeaveAlert)) {
        const num = row.leaveN ?? Number(row.leave?.match(/(\d+)\s*مرة/)?.[1] || 0);
        const secs = row.leaveSec ?? Number(row.leave?.match(/\((\d+)\s*ث\)/)?.[1] || 0);
        result.push({ row, section, reason: `خرج من الصفحة ${num} مرات · ${secs} ث`, urgency: 800 + num * 10 + secs });
      }
      if (row.status === 'done' && (row.late || 0) > 0) result.push({ row, section, reason: `تسليم متأخر ${row.late} ث`, urgency: 700 + (row.late || 0) });
      if (row.status === 'live' && row.paused === undefined && (row.remain || 9999) < ATTENTION_LIMITS.lowTimeSeconds && row.total && ((row.answered || 0) / row.total) * 100 < ATTENTION_LIMITS.lowAnsweredPercent) {
        result.push({ row, section, reason: `وقته يقترب وما أجاب إلا ${row.answered || 0} من ${row.total}`, urgency: 600 + (120 - (row.remain || 0)) });
      }
      if (row.paused !== undefined && row.paused >= ATTENTION_LIMITS.pausedSeconds) result.push({ row, section, reason: `موقوف مؤقتاً منذ ${formatTime(row.paused)}`, urgency: 500 + row.paused });   // تذكير: لا تنسى «متابعة»
    }));
    return result.sort((a, b) => b.urgency - a.urgency);
  }, [data]);

  const getRemain = (row: Student) => row.paused !== undefined ? (row.remain || 0) : Math.max(0, (row.remain || 0) - secondsSinceSync);   // الموقوف وقته متجمّد
  const showModal = (next: Exclude<ModalState, null>) => { setModal(next); setToolsOpen(false); setOpenRowMenu(null); };

  const openExtend = (scope: 'student' | 'section' | 'all', row?: Student) => {
    const scopeText = scope === 'student' ? 'هذا الطالب' : scope === 'section' ? 'طلاب هذه الشعبة اللي بدأوا ولم يسلّموا' : 'كل الطلاب اللي بدأوا ولم يسلّموا';
    const command: Record<string, unknown> = { extend: 5, scope };
    if (scope === 'student' && row) command.key = row.key;
    if (scope === 'section' && row) { command.grade = row.grade; command.section = row.section; }
    setExtendMinutes('5');
    showModal({ kind: 'extend', title: 'تمديد الوقت', scopeText, command });
  };

  const runCommand = async (command: Record<string, unknown>) => {
    setModal(null);
    setToast('');
    if (mockMode) {
      const current = dataRef.current;
      if (!current) return;
      const next: MonitorData = { ...current, sections: Object.fromEntries(Object.entries(current.sections).map(([section, rows]) => [section, rows.map((row) => ({ ...row }))])) };
      const matches = (row: Student) => {
        if (command.scope === 'student') return row.key === command.key;
        if (command.scope === 'section') return row.grade === command.grade && row.section === command.section;
        return true;
      };
      if ('extend' in command) {
        flatten(next.sections).filter((row) => matches(row) && (row.status === 'live' || row.status === 'lost')).forEach((row) => { row.remain = (row.remain || 0) + Number(command.extend) * 60; });
      } else if ('message' in command) next.msg = String(command.message);
      else if ('close' in command) next.closed = Boolean(command.close);
      else if ('bankok' in command) next.bank_changed = null;
      else if ('release' in command) {
        const row = flatten(next.sections).find((item) => item.key === command.release);
        if (row) { row.status = 'none'; row.key = null; delete row.answered; delete row.remain; }
      } else if ('move' in command) {
        const row = flatten(next.sections).find((item) => item.key === command.move);
        if (row) { row.status = 'live'; row.ago = 2; }
      } else if ('pause' in command) {
        const row = flatten(next.sections).find((item) => item.key === command.pause);
        if (row) row.paused = 0;
      } else if ('resume' in command) {
        const row = flatten(next.sections).find((item) => item.key === command.resume);
        if (row) delete row.paused;
      } else if ('submitfor' in command) {
        const key = command.submitfor;
        flatten(next.sections).filter((row) => row.status === 'live' || row.status === 'lost').filter((row) => key === 'all' || row.key === key).forEach((row) => {
          row.status = 'done'; row.score = Math.round(((row.answered || 0) / (row.total || 10)) * (row.total || 10));
          row.total = row.total || 10; row.durtxt = '٢٣ د ٤١ ث'; row.leave = row.leaveN ? `${row.leaveN} مرة (${row.leaveSec || 0} ث)` : 'لم يخرج'; row.late = 0; delete row.remain;
        });
      } else if ('newexam' in command) {
        next.closed = false; next.msg = ''; next.comp = null; next.bank_changed = null;
        flatten(next.sections).forEach((row) => { row.status = 'none'; row.key = null; delete row.score; delete row.answered; delete row.remain; delete row.durtxt; });
      } else if ('rehearsal' in command) {
        const type = command.rehearsal;
        if (type === 'off') next.reh = null;
        else if (type === 'on') next.reh = { on: true, left: Number(command.mins || 30) * 60, joined: 8, reported: 8, ok: 8, fail: 0, papers: 8 };
        else if (type === 'go' && next.reh) next.reh = { ...next.reh, at_in: Number(command.secs || 60), full: Boolean(command.full) };
      }
      next.c = statusCounts(next);
      acceptData(next);
      setToast('تم تنفيذ الإجراء في وضع المحاكاة.');
      return;
    }
    try {
      const response = await fetch('/monitor', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Exam-Action': '1' },
        body: JSON.stringify(command),
      });
      let body: { ok?: number; error?: string } = {};
      try { body = await response.json() as { ok?: number; error?: string }; } catch { /* server may return an empty response */ }
      if (!response.ok || body.error) {
        await loadData();
        setToast(body.error || 'ما زبط');
        return;
      }
      await loadData();
    } catch {
      setToast('انقطع الاتصال بالسيرفر — لم يتم تنفيذ الأمر.');
      failureCountRef.current += 1;
      setFailureCount(failureCountRef.current);
    }
  };

  const confirmAction = (type: keyof typeof CONFIRM_COPY, command: Record<string, unknown>) => {
    showModal({
      kind: 'confirm',
      title: type === 'newExam' ? 'بداية امتحان جديد' : type === 'close' ? 'إنهاء الامتحان للجميع' : type === 'reopen' ? 'إعادة فتح الامتحان' : type === 'bank' ? 'تأكيد ملف الأسئلة' : 'تأكيد الإجراء',
      copy: CONFIRM_COPY[type],
      command,
      danger: type === 'newExam' || type === 'close' || type === 'release' || type === 'submit',
      safeLabel: 'إلغاء',
      dangerLabel: type === 'release' ? 'فك الحجز' : type === 'move' ? 'نقل الطالب' : type === 'newExam' ? 'متابعة' : type === 'submit' ? 'تسليم الآن' : type === 'close' ? 'إنهاء الامتحان' : type === 'reopen' ? 'إعادة الفتح' : 'تأكيد',
    });
  };

  const submitAll = () => {
    const started = counts.live + counts.lost;
    if (!started) { setToast('ما في طلاب بدأوا ولم يسلّموا'); return; }
    showModal({
      kind: 'confirm', title: 'تسليم من لم يسلّم',
      copy: `تسليم ${started} طالب بدأوا ولم يسلّموا (بما فيهم من يمتحن الآن) بإجاباتهم المحفوظة على السيرفر؟\nالأفضل تضغط «إنهاء الامتحان للجميع» أولاً وتنتظر دقيقة ليسلّموا بأنفسهم، ثم تسلّم الباقي.\nالأسئلة بدون إجابة بتنحسب خاطئة.`,
      command: { submitfor: 'all' }, danger: true, safeLabel: 'إلغاء', dangerLabel: 'تسليم الآن',
    });
  };

  const submitModal = () => {
    if (!modal) return;
    if (modal.kind === 'extend') {
      const minutes = Number(extendMinutes);
      if (!Number.isInteger(minutes) || minutes < 1 || minutes > 120) { setToast('الرقم لازم يكون بين 1 و120'); return; }
      void runCommand({ ...modal.command, extend: minutes });
    } else if (modal.kind === 'message') {
      const text = messageText.trim();
      if (!text) { setToast('اكتب الرسالة أولاً'); return; }
      void runCommand({ message: text.slice(0, 300) });
    } else if (modal.command) void runCommand(modal.command);
  };

  const openNewExam = () => showModal({
    kind: 'confirm', title: 'بداية امتحان جديد', copy: CONFIRM_COPY.newExam,
    safeLabel: 'إلغاء', dangerLabel: 'متابعة', danger: true,
    command: { newexam: 1 },
  });

  const handleConfirm = () => {
    if (!modal) return;
    if (modal.command && 'newexam' in modal.command && !modal.final) {
      setModal({
        kind: 'confirm', title: 'تأكيد أخير', copy: 'تأكيد أخير: تصفير الامتحان الحالي؟',
        command: { newexam: 1 }, danger: true, safeLabel: 'إلغاء', dangerLabel: 'تصفير الامتحان', final: true,
      });
      return;
    }
    submitModal();
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(localLink);
    } catch {
      const input = document.createElement('textarea');
      input.value = localLink; input.style.position = 'fixed'; input.style.opacity = '0';
      document.body.appendChild(input); input.select(); document.execCommand('copy'); input.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  const setProjectorMode = (value: boolean) => {
    if (value) window.location.hash = 'big';
    else if (window.location.hash === '#big') window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    setProjector(value);
  };
  const changeAllSections = (value: boolean) => {
    if (!data) return;
    setOpenSections(Object.fromEntries(Object.keys(data.sections).map((section) => [section, value])));
  };
  const toggleSection = (section: string, open: boolean) => setOpenSections((existing) => ({ ...existing, [section]: open }));
  const changeFilter = (value: Filter) => setFilter((current) => current === value ? 'all' : value);
  const goToRehearsal = () => {
    setToolsOpen(false);
    const panel = document.getElementById('rehearsal');
    if (panel instanceof HTMLDetailsElement) panel.open = true;   // كانت بس تنزّل للّوحة وهي مطويّة
    panel?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  useEffect(() => {
    if (!data || !mockMode || demoStateApplied.current) return;
    demoStateApplied.current = true;
    if (deterministicState === 'offline') {
      failureCountRef.current = 2;
      setFailureCount(2);
    } else if (deterministicState === 'tools-menu') {
      setToolsOpen(true);
    } else if (deterministicState === 'row-menu') {
      const entry = Object.entries(data.sections).find(([, rows]) => rows.some((row) => row.status === 'live' || row.status === 'done'));
      const row = entry?.[1].find((candidate) => candidate.status === 'live' || candidate.status === 'done');
      if (entry && row) {
        setOpenRowMenu(keyFor(row, entry[0]));
        setRowMenuOpensUp(window.innerHeight < 820);
      }
    } else if (deterministicState === 'modal-extend') {
      openExtend('all');
    } else if (deterministicState === 'modal-message') {
      setMessageText('يرجى مراجعة الإجابات قبل التسليم.');
      showModal({ kind: 'message', title: 'رسالة للطلاب' });
    } else if (deterministicState === 'modal-close') {
      confirmAction('close', { close: true });
    } else if (deterministicState === 'modal-submit') {
      const row = flatten(data.sections).find((candidate) => candidate.status === 'live' && candidate.key);
      if (row?.key) confirmAction('submit', { submitfor: row.key });
    } else if (deterministicState === 'modal-submit-all') {
      submitAll();
    } else if (deterministicState === 'modal-release') {
      const row = flatten(data.sections).find((candidate) => candidate.status === 'done' && candidate.key);
      if (row?.key) confirmAction('release', { release: row.key });
    } else if (deterministicState === 'modal-move') {
      const row = flatten(data.sections).find((candidate) => candidate.status === 'lost' && candidate.key);
      if (row?.key) confirmAction('move', { move: row.key });
    } else if (deterministicState === 'modal-newexam') {
      openNewExam();
    } else if (deterministicState === 'modal-newexam-confirm') {
      setModal({ kind: 'confirm', title: 'تأكيد أخير', copy: 'تأكيد أخير: تصفير الامتحان الحالي؟', command: { newexam: 1 }, danger: true, safeLabel: 'إلغاء', dangerLabel: 'تصفير الامتحان', final: true });
    } else if (deterministicState === 'modal-bank') {
      confirmAction('bank', { bankok: 1 });
    }
  }, [data, mockMode]);

  const toolItems = NAV_LINKS.map((item, index) => (
    <span key={item.href}>
      {index > 0 && item.group !== NAV_LINKS[index - 1].group ? <hr /> : null}
      <a href={item.href} target="_blank" rel="noreferrer" onClick={() => setToolsOpen(false)}>{item.text}</a>
    </span>
  ));

  if (loading && !data) {
    return <main dir="rtl" className="loading-shell" aria-label="جارٍ تحميل شاشة المراقبة"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></main>;
  }
  if (!data) {
    return <main dir="rtl" className="wrap"><div className="empty-state"><strong>لا يمكن الوصول إلى بيانات الامتحان</strong><p>تحقق من اتصال هذا الجهاز بالسيرفر ثم أعد المحاولة.</p><button className="btn" type="button" onClick={() => { setLoading(true); void loadData(); }}>إعادة المحاولة</button></div></main>;
  }

  const isOffline = failureCount >= 2;
  const isEmptyExam = total > 0 && counts.none === total;
  const overall = (
    <div className="overall" aria-label="التقدم الإجمالي">
      <div className="segment-bar" aria-hidden="true">
        <i className="s-done" style={{ width: `${percent(counts.done, total)}%` }} />
        <i className="s-live" style={{ width: `${percent(counts.live, total)}%` }} />
        <i className="s-lost" style={{ width: `${percent(counts.lost, total)}%` }} />
      </div>
      <span className="overall-text">سلّم <b className="num">{counts.done}</b> من <b className="num">{total}</b> ({percent(counts.done, total)}%) · يمتحن <b className="num">{counts.live}</b></span>
    </div>
  );

  return (
    <div dir="rtl">
      {projector ? (
        <main className="projector">
          <header className="projector-top">
            <h1>مراقبة الامتحان</h1><span className="exam-title">{localTitle}</span><span className="spacer" />
            <span className="projector-clock num">{timeNow().slice(0, 5)}</span>
          </header>
          <button className="btn outline projector-back" type="button" onClick={() => setProjectorMode(false)}>← رجوع للوضع العادي</button>
          <div className="projector-wrap">
            <section className="projector-kpis" aria-label="ملخص حالات الطلاب">
              {SUMMARY.map((item) => <div key={item.key} className={`projector-kpi ${item.style}`}><b className="num">{counts[item.key]}</b><span>{item.label}</span></div>)}
            </section>
            <div className="projector-progress" aria-hidden="true">
              <i style={{ width: `${percent(counts.done, total)}%`, background: 'var(--done)' }} />
              <i style={{ width: `${percent(counts.live, total)}%`, background: '#d49b20' }} />
              <i style={{ width: `${percent(counts.lost, total)}%`, background: 'var(--lost)' }} />
            </div>
            <div className="projector-progress-text">سلّم <b className="num">{counts.done}</b> من <b className="num">{total}</b> طالب ({percent(counts.done, total)}%)</div>
            {Object.entries(data.sections).map(([section, rows]) => {
              const ordered = [...rows].sort((a, b) => ['lost', 'live', 'none', 'done'].indexOf(a.status) - ['lost', 'live', 'none', 'done'].indexOf(b.status));
              return <section key={section}><h2 className="projector-section">{section}</h2><div className="projector-tiles">
                {ordered.map((row) => <div key={keyFor(row, section)} className={`projector-tile ${row.status}`}><span>{row.name}</span><small className="num">{row.status === 'done' ? `${row.score ?? 0} / ${row.total ?? 0}` : row.status === 'live' ? formatTime(getRemain(row)) : row.status === 'lost' ? 'منقطع' : ''}</small></div>)}
              </div></section>;
            })}
          </div>
        </main>
      ) : (
        <>
          <header className="topbar">
            <div className="top-inner">
              <strong className="brand">مراقبة الامتحان</strong>
              <span className="exam-title">{localTitle}</span><span className="spacer" />
              <span className="live-indicator"><i />تحديث مباشر · <span className="num">{lastUpdate || timeNow()}</span></span>
              <button className="top-button" type="button" onClick={() => setProjectorMode(true)}>🖥 شاشة كبيرة</button>
              <div className="top-menu">
              <button className="top-button" type="button" aria-haspopup="menu" aria-expanded={toolsOpen} onClick={() => { setOpenRowMenu(null); setToolsOpen((value) => !value); }}>أدوات ▾</button>
                {toolsOpen && <div className="popup" role="menu">{toolItems}<hr /><button type="button" onClick={goToRehearsal}>🧪 بروفة الضغط</button></div>}
              </div>
            </div>
          </header>
          <main className={`wrap ${isOffline ? 'offline-dim' : ''}`}>
            {isOffline && <div className="notice danger" role="alert"><span>انقطع الاتصال بالسيرفر — آخر تحديث <b className="num">{lastUpdate}</b></span><button type="button" onClick={() => void loadData()}>إعادة المحاولة</button></div>}
            <section className="summary-grid" aria-label="ملخص حالات الطلاب">
              {SUMMARY.map((item) => <button key={item.key} type="button" className={`kpi ${item.style} ${filter === item.key ? 'selected' : ''}`} onClick={() => changeFilter(item.key)} aria-pressed={filter === item.key}>
                <span className="kpi-count num">{counts[item.key]}</span><span className="kpi-label">{item.label}</span><span className="kpi-percent"><b className="num">{percent(counts[item.key], total)}%</b> من <b className="num">{total}</b></span>
              </button>)}
              <section className="link-card">
                <small>رابط الامتحان للطلاب</small>
                <code dir="ltr">{localLink}</code>
                <div className="button-row"><button type="button" className="btn small" onClick={() => void copyLink()}>{copied ? 'تم النسخ ✓' : 'نسخ الرابط'}</button><a className="btn outline small" href="/link" target="_blank" rel="noreferrer">عرض بخط كبير</a></div>
              </section>
            </section>
            {overall}
            {data.comp && (() => {
              const comp = data.comp!;
              const unitText = `${Math.floor(comp.downtime_s / 60) ? `${Math.floor(comp.downtime_s / 60)} دقيقة و` : ''}${comp.downtime_s % 60} ثانية`;
              const source = comp.sleep ? 'جهاز السيرفر نام أو تجمّد ' : 'السيرفر كان متوقفاً ';
              const text = comp.skipped
                ? `⚠ ${source}${unitText} (أطول من 30 دقيقة): ما عوّضنا الوقت تلقائياً. استعمل «⏱ تمديد الوقت للجميع» إذا لزم.`
                : comp.off
                  ? `⚠ ${source}${unitText} والتعويض التلقائي مطفّأ (تعويض_توقف_السيرفر = لا). استعمل «⏱ تمديد الوقت للجميع» إذا لزم.`
                  : `ℹ️ ${source}${unitText}: مدّدنا تلقائياً وقت ${comp.students} طالب (اللي لم يسلّموا) بنفس المدة، فما خسروا شيئاً.`;
              return <div className={`notice ${comp.skipped || comp.off ? 'warning' : ''}`} role="status">{text}</div>;
            })()}
            {data.closed && <div className="notice danger"><span>⏹ الامتحان منتهٍ — الطلاب يُسلَّمون تلقائياً ولا يمكن البدء.</span><button type="button" onClick={() => confirmAction('reopen', { close: false })}>إعادة فتح الامتحان</button></div>}
            {data.bank_changed && <div className="notice danger"><span>⚠ ملف الأسئلة تغيّر بعد آخر امتحان، والسيرفر لسا فيه بيانات الامتحان السابق ({data.bank_changed.subs} تسليم و{data.bank_changed.papers} ورقة). إذا هذا <b>امتحان جديد</b>: اضغط «بداية امتحان جديد» قبل ما يدخل الطلاب. إذا بس صلّحت سؤال بنفس الامتحان:</span><button type="button" onClick={() => confirmAction('bank', { bankok: 1 })}>هذا نفس الامتحان (أخفِ التنبيه)</button><button type="button" onClick={openNewExam}>بداية امتحان جديد</button></div>}
            {data.msg && <div className="notice"><span>آخر رسالة: «{data.msg}»</span></div>}
            {attentionItems.length > 0 && <section className="attention" aria-label="يحتاجون انتباهك">
              <div className="attention-head"><span>⚠ يحتاجون انتباهك</span><b className="attention-count num">{attentionItems.length}</b><span className="spacer" /><button className="btn outline small" type="button" aria-expanded={attentionOpen} onClick={() => setAttentionOpen((value) => !value)}>{attentionOpen ? 'طي' : 'فتح'}</button></div>
              {attentionOpen && <div className="attention-list">{attentionItems.map(({ row, section, reason }, index) => <article className="attention-card" key={`${keyFor(row, section)}-${index}`}>
                <span className="attention-name">{row.name} <small>· {section}</small></span><span className="attention-reason">{reason}</span>
                <div className="attention-actions">
                  {row.paused !== undefined && <button className="btn small" type="button" onClick={() => row.key && void runCommand({ resume: row.key })}>▶ متابعة</button>}
                  {row.status === 'lost' ? <>
                    <button className="btn small" type="button" onClick={() => openExtend('student', row)}>+ وقت</button>
                    <button className="btn outline small" type="button" onClick={() => row.key && confirmAction('move', { move: row.key })}>نقل لجهاز آخر</button>
                    <button className="btn outline small" type="button" onClick={() => row.key && confirmAction('submit', { submitfor: row.key })}>تسليم عنه</button>
                  </> : <>
                    {row.status === 'done' && <a className="btn outline small" href={`/sheet?key=${encodeURIComponent(row.key || '')}`} target="_blank" rel="noreferrer">فتح الورقة</a>}
                    {row.status === 'live' && <button className="btn outline small" type="button" onClick={() => openExtend('student', row)}>+ وقت</button>}
                  </>}
                </div>
              </article>)}</div>}
            </section>}
            <div className="toolbar">
              <label className="search-box"><span aria-hidden="true">🔍</span><input aria-label="ابحث عن اسم طالب" placeholder="ابحث عن اسم طالب..." value={query} onChange={(event) => setQuery(event.target.value)} autoComplete="off" /></label>
              <div className="chips" aria-label="تصفية حسب الحالة">
                {[['all', 'الكل', total], ['live', 'يمتحنون', counts.live], ['done', 'سلّموا', counts.done], ['lost', 'انقطعوا', counts.lost], ['none', 'لم يبدؤوا', counts.none]].map(([key, label, count]) => <button type="button" key={key} className={`chip ${filter === key ? 'active' : ''}`} onClick={() => key === 'all' ? setFilter('all') : changeFilter(key as Status)} aria-pressed={filter === key}>{label}<b className="num">{count}</b></button>)}
              </div>
              <div className="group-actions">
                <button className="btn outline" type="button" onClick={() => openExtend('all')}>⏱ تمديد الوقت للجميع</button>
                <button className="btn outline" type="button" onClick={() => { setMessageText(''); showModal({ kind: 'message', title: 'رسالة للطلاب' }); }}>📣 رسالة للطلاب</button>
                <button className="btn outline" type="button" onClick={submitAll}>📥 تسليم من لم يسلّم</button>
              </div>
              {data.msg && <div className="last-message">آخر رسالة: «{data.msg}»</div>}
            </div>

            {isEmptyExam && <div className="empty-state"><strong>لم يبدأ أي طالب الامتحان بعد</strong><span>ستظهر حالة الطلاب هنا مباشرةً عند بدء الامتحان.</span></div>}
            {sectionEntries.length === 0 ? <div className="empty-state"><strong>لا نتائج مطابقة</strong><span>جرّب تغيير البحث أو تصفية الحالة.</span></div> : sectionEntries.map(({ section, rows, matching }) => {
              const doneCount = rows.filter((row) => row.status === 'done').length;
              const liveCount = rows.filter((row) => row.status === 'live').length;
              const groupBusy = rows.some((row) => row.status === 'live' || row.status === 'lost');
              const isForcedOpen = Boolean(query || filter !== 'all');
              const isOpen = openSections[section] ?? (isForcedOpen || groupBusy);
              return <details className="section-card" key={section} open={isOpen} onToggle={(event) => toggleSection(section, event.currentTarget.open)}>
                <summary>
                  <h2>{section}</h2>
                  <span className="section-count">سلّم <b className="num">{doneCount}</b> من <b className="num">{rows.length}</b> · يمتحن <b className="num">{liveCount}</b></span>
                  <span className="section-bar" aria-label="تقدم الشعبة">
                    <i style={{ width: `${percent(doneCount, rows.length)}%`, background: 'var(--done)' }} />
                    <i style={{ width: `${percent(liveCount, rows.length)}%`, background: '#d49b20' }} />
                    <i style={{ width: `${percent(rows.filter((row) => row.status === 'lost').length, rows.length)}%`, background: 'var(--lost)' }} />
                  </span>
                  <span className="section-spacer" />
                  {groupBusy && <button className="btn outline small" type="button" onClick={(event) => { event.preventDefault(); event.stopPropagation(); openExtend('section', rows[0]); }}>⏱ تمديد الشعبة</button>}
                </summary>
                <div className="table-scroll"><table className="student-table">
                  <thead><tr><th>الاسم</th><th>الحالة</th><th>التقدّم</th><th>الوقت المتبقي</th><th>خرج من الصفحة</th><th>العلامة</th><th>مدة الحل</th><th aria-label="الإجراءات" /></tr></thead>
                  <tbody>{matching.map((row) => {
                    const id = keyFor(row, section);
                    const hasProgress = (row.status === 'live' || row.status === 'lost') && row.total != null;
                    const leaveDetails = row.status === 'done' ? row.leave && row.leave !== 'لم يخرج' ? row.leave.replace(/\((\d+)\s*ث\)/, '· $1 ث') : 'لم يخرج' : row.leaveN ? `⚠ ${row.leaveN} مرة · ${row.leaveSec || 0} ث` : '—';
                    const menuItems = row.status === 'done'
                      ? [{ label: 'فتح الورقة', type: 'sheet' }, { label: 'فك الحجز', type: 'release' }]
                      : row.status === 'none' ? [] : [
                        { label: '+ وقت', type: 'extend' },
                        ...(row.paused !== undefined ? [{ label: '▶ متابعة', type: 'resume' }] : row.status === 'live' ? [{ label: '⏸ إيقاف مؤقت', type: 'pause' }] : []),
                        { label: 'نقل لجهاز آخر', type: 'move' },
                        { label: 'تسليم عنه', type: 'submit' }, { label: 'فك الحجز', type: 'release' },
                      ];
                    return <tr className={`student-row ${row.status}`} key={id}>
                      <td className="name-cell">{row.name}</td>
                      <td><span className={`status-pill ${row.paused !== undefined ? 'paused' : row.status}`}>{row.paused !== undefined ? '⏸ موقوف' : STATUS[row.status]}</span>{row.paused !== undefined ? <span className="muted"> منذ <b className="num">{formatTime(row.paused + secondsSinceSync)}</b></span> : row.status === 'lost' && row.ago != null && <span className="muted"> منذ <b className="num">{row.ago}</b> ث</span>}</td>
                      <td>{hasProgress ? <div className="progress-cell"><span className="num">{row.answered || 0}/{row.total}</span><span className="mini-bar"><i style={{ width: `${percent(row.answered || 0, row.total || 0)}%` }} /></span></div> : <span className="muted">—</span>}</td>
                      <td>{row.status === 'live' ? <span className={`time-left num ${row.paused === undefined && getRemain(row) < 120 ? 'low' : ''}`}>{formatTime(getRemain(row))}</span> : row.status === 'lost' && row.ago != null ? <span className="muted">منذ <b className="num">{row.ago}</b> ث</span> : row.status === 'done' && row.durtxt ? <span className="muted">استغرق {row.durtxt}</span> : <span className="muted">—</span>}</td>
                      <td>{leaveDetails !== '—' && leaveDetails ? <span className={`warning-chip ${row.status === 'done' && (row.late || 0) > 0 ? 'late' : ''}`}>{leaveDetails}</span> : <span className="muted">—</span>}{row.status === 'done' && (row.late || 0) > 0 && <span className="warning-chip late">⏱ متأخر {row.late} ث</span>}</td>
                      <td>{row.status === 'done' ? <span className="score num">{row.score ?? 0} / {row.total ?? 0}</span> : <span className="muted">—</span>}</td>
                      <td>{row.status === 'done' ? row.durtxt || <span className="muted">—</span> : <span className="muted">—</span>}</td>
                      <td className="action-cell">
                        {row.status === 'done' && <a className="btn outline small" href={`/sheet?key=${encodeURIComponent(row.key || '')}`} target="_blank" rel="noreferrer">فتح الورقة</a>}
                        {row.paused !== undefined && <button className="btn small" type="button" onClick={() => row.key && void runCommand({ resume: row.key })}>▶ متابعة</button>}
                        {(row.status === 'live' || row.status === 'lost') && <button className="btn outline small" type="button" onClick={() => openExtend('student', row)}>+ وقت</button>}
                        {menuItems.length > 0 && <span className={`row-menu-wrap ${openRowMenu === id && rowMenuOpensUp ? 'opens-up' : ''}`}>
                          <button className="kebab" type="button" aria-label={`إجراءات ${row.name}`} aria-expanded={openRowMenu === id} onClick={(event) => {
                            setToolsOpen(false);
                            const next = openRowMenu === id ? null : id;
                            if (next) {
                              const bounds = event.currentTarget.getBoundingClientRect();
                              setRowMenuOpensUp(window.innerHeight - bounds.bottom - 62 < 82);
                            } else setRowMenuOpensUp(false);
                            setOpenRowMenu(next);
                          }}>⋯</button>
                          {openRowMenu === id && <span className="row-popup" role="menu">
                            {menuItems.map((item) => item.type === 'sheet' ? <a key={item.type} role="menuitem" href={`/sheet?key=${encodeURIComponent(row.key || '')}`} target="_blank" rel="noreferrer" onClick={() => setOpenRowMenu(null)}>{item.label}</a> : <button key={item.type} role="menuitem" type="button" onClick={() => {
                              setOpenRowMenu(null);
                              if (item.type === 'extend') openExtend('student', row);
                              if (item.type === 'pause' && row.key) void runCommand({ pause: row.key });
                              if (item.type === 'resume' && row.key) void runCommand({ resume: row.key });
                              if (item.type === 'move' && row.key) confirmAction('move', { move: row.key });
                              if (item.type === 'submit' && row.key) confirmAction('submit', { submitfor: row.key });
                              if (item.type === 'release' && row.key) confirmAction('release', { release: row.key });
                            }}>{item.label}</button>)}
                          </span>}
                        </span>}
                      </td>
                    </tr>;
                  })}</tbody>
                </table></div>
              </details>;
            })}

            <details className="rehearsal" id="rehearsal">
              <summary>🧪 بروفة الضغط <span className="muted">{data.reh ? data.reh.on ? `— شغّالة (بتنطفي بعد ${Math.ceil((data.reh.left || 0) / 60)} د) • أجهزة مسجّلة: ${data.reh.joined || 0}${data.reh.at_in ? ` • الجولة بعد ${Math.ceil(data.reh.at_in)} ث` : ''}` : '— مطفية' : '— مطفية'}</span></summary>
              <div className="reh-content">
                <p className="reh-instructions">كل أجهزة المختبر بتطلب «ابدأ» بنفس اللحظة حسب <b>ساعة السيرفر</b> (مش ساعة الأجهزة)، وبتشوف هون النتيجة. ① فعّلها. ② افتح على كل جهاز <b dir="ltr">{localLink}/rehearsal</b> وخلّي الشاشة شغّالة. ③ اضغط «ابدأ الجولة». ④ بعد ما تخلص اضغط زر الأرشفة والتصفير الأحمر أسفل الصفحة عشان تصفّر. بتنفع قبل الامتحان بس: لو في طلاب بدأوا ما بتتفعّل.</p>
                <div className="reh-tools">
                  <button className="btn outline" type="button" disabled={Boolean(data.reh?.on)} onClick={() => void runCommand({ rehearsal: 'on', mins: 30 })}>تفعيل البروفة (30 دقيقة)</button>
                  <select id="reh-seconds" aria-label="وقت بدء جولة البروفة" defaultValue="60"><option value="30">بعد 30 ث</option><option value="60">بعد 60 ث</option><option value="120">بعد 120 ث</option></select>
                  <label><input id="reh-full" type="checkbox" /> حل عشوائي وتسليم</label>
                  <button className="btn" type="button" disabled={!(data.reh?.on && data.reh.joined)} onClick={() => {
                    const secs = Number((document.getElementById('reh-seconds') as HTMLSelectElement).value);
                    const full = (document.getElementById('reh-full') as HTMLInputElement).checked;
                    void runCommand({ rehearsal: 'go', secs, full });
                  }}>▶ ابدأ الجولة</button>
                  <button className="btn danger" type="button" onClick={() => void runCommand({ rehearsal: 'off' })}>إيقاف البروفة</button>
                </div>
                {data.reh?.joined ? <div className="reh-table-wrap"><table className="reh-table"><thead><tr><th>أجهزة مسجّلة</th><th>بدأوا بنجاح</th><th>فشلوا</th><th>أوراق انعملت بالسيرفر</th><th>وقت الرد (متوسط / 95% / أبطأ)</th><th>فرق وصول الطلبات للسيرفر</th><th>أكبر تأخر جهاز عن الموعد</th></tr></thead>
                  <tbody><tr><td>{data.reh.joined}</td><td>{data.reh.ok || 0} من {data.reh.reported || 0}</td><td>{data.reh.fail || 0}</td><td>{data.reh.papers || 0}</td><td>{data.reh.ms_avg ?? '—'} / {data.reh.ms_p95 ?? '—'} / {data.reh.ms_max ?? '—'} م.ث</td><td>{data.reh.spread_ms ?? '—'} م.ث</td><td>{data.reh.skew_max ?? '—'} م.ث</td></tr></tbody></table>
                  {data.reh.full && <p className="reh-instructions">التسليم: نجح {data.reh.submit_ok || 0}، فشل {data.reh.submit_fail || 0}، أبطأ تسليم {data.reh.submit_ms_max ?? '—'} م.ث</p>}
                  {data.reh.fails && data.reh.fails.length > 0 && <p className="reh-instructions">فشل: {data.reh.fails.map((item) => `جهاز ${item.n} (${item.name}) — ${item.status}`).join('، ')}</p>}
                  {(!data.reh.on || data.reh.reported) && <p className="reh-instructions">بعد ما تخلص: اضغط زر الأرشفة والتصفير الأحمر أسفل الصفحة عشان تصفّر.</p>}
                </div> : null}
              </div>
            </details>
          </main>
          <footer className="bottom-bar">
            <span className="bottom-hint">طي كل الشعب / فتحها:</span>
            <button className="btn outline small" type="button" onClick={() => changeAllSections(false)}>طي الكل</button>
            <button className="btn outline small" type="button" onClick={() => changeAllSections(true)}>فتح الكل</button>
            <span className="spacer" />
            <button className="btn danger" type="button" onClick={() => confirmAction('close', { close: true })}>■ إنهاء الامتحان للجميع</button>
            <button className="btn danger" type="button" onClick={openNewExam}>↻ بداية امتحان جديد</button>
          </footer>
        </>
      )}

      {toast && <div className="toast" role="status" aria-live="polite">{toast}</div>}
      {modal && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setModal(null); }}>
        <section className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" ref={modalRef}>
          <h2 id="modal-title">{modal.title}</h2>
          {modal.copy && <p className="modal-copy">{modal.copy}</p>}
          {modal.kind === 'extend' && <>
            <label htmlFor="extend-minutes">كم دقيقة تضيف لـ {modal.scopeText}؟</label>
            <input id="extend-minutes" type="number" min="1" max="120" step="1" value={extendMinutes} onChange={(event) => setExtendMinutes(event.target.value)} />
            <p className="modal-note">ملاحظة: التمديد لازم يكون قبل ما ينتهي وقت الطالب. (1 – 120)</p>
          </>}
          {modal.kind === 'message' && <>
            <label htmlFor="student-message">اكتب الرسالة (بتظهر على شاشة كل طالب يمتحن الآن):</label>
            <textarea id="student-message" maxLength={300} value={messageText} onChange={(event) => setMessageText(event.target.value)} />
            <p className="modal-note">{messageText.length} / 300</p>
          </>}
          <div className="modal-actions">
            <button ref={safeButtonRef} className="btn outline" type="button" onClick={() => setModal(null)}>{modal.safeLabel || 'إلغاء'}</button>
            {modal.kind === 'confirm' && <button className={`btn ${modal.danger ? 'danger' : ''}`} type="button" onClick={handleConfirm}>{modal.dangerLabel || 'تأكيد'}</button>}
            {modal.kind !== 'confirm' && <button className="btn" type="button" onClick={submitModal}>تأكيد</button>}
          </div>
        </section>
      </div>}
    </div>
  );
}

export default App;
