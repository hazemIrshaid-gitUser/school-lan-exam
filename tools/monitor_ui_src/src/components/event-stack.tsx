import { useEffect } from 'react';
import type { Ev, Kind } from '../lib/events';

const ICON: Record<Kind, string> = { start: '▶', done: '✓', lost: '⚠', back: '↺', leave: '↗', reopen: '↩' };

function Card({ ev, onClose }: { ev: Ev; onClose: (id: number) => void }) {
  useEffect(() => {
    const timer = window.setTimeout(() => onClose(ev.id), ev.level === 'warn' ? 12000 : 7000);   // التحذيرات بتبقى أطول
    return () => window.clearTimeout(timer);
  }, [ev.id, ev.level, onClose]);
  return (
    <div className={`ev ${ev.level}`}>
      <span className="ev-icon" aria-hidden="true">{ICON[ev.kind]}</span>
      <div className="ev-body">
        <span className="ev-who"><b>{ev.who}</b>{ev.section && <small> · {ev.section}</small>}</span>
        <span className="ev-text">{ev.text}</span>
      </div>
      <span className="ev-at num">{ev.at}</span>
      <button className="ev-x" type="button" aria-label="إغلاق الإشعار" onClick={() => onClose(ev.id)}>×</button>
    </div>
  );
}

/** إشعارات حية بزاوية الشاشة (أحدثها أسفل). الحاوية ما بتمسك ضغطات الماوس، بس البطاقات نفسها. */
export function EventStack({ events, onClose }: { events: Ev[]; onClose: (id: number) => void }) {
  return (
    <div className="ev-stack" role="log" aria-live="polite" aria-label="إشعارات حية">
      {events.map((ev) => <Card key={ev.id} ev={ev} onClose={onClose} />)}
    </div>
  );
}
