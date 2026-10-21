# monitor_ui_src: source of the teacher monitor screen (/monitor)

React + Vite + Tailwind. Built into static files that the exam server serves, so the teacher laptop needs nothing installed.
It uses only `GET /monitor.json` and `POST /monitor` (header `X-Exam-Action: 1`) and never contacts anything outside the server.

## Build and ship
```
cd tools/monitor_ui_src
npm install
npm run build        # writes dist/
```
Then copy the **contents of `dist/`** into the package folder `monitor_ui/` (next to `server.py`):
`1_الحزمة_الكاملة_لأستاذ_جديد/monitor_ui/` (and the same folder inside `2_تحديث_لمن_عنده_النسخة_القديمة/`).
If that folder is missing the server shows the old monitor page, which is always available at `/monitor-old`.

## Try it without a server
Open `http://localhost:5173/monitor-ui/?mock=1` after `npm run dev`; it loads `public/mock/monitor.json` and simulates a live exam.

## Navigation and live notifications (phase B)
- The top bar is the same one the server renders on the other teacher pages. The server injects `tabs` (`[[href, label], ...]`, from `TABS` in `server.py`, the codes tab only when login codes are on) and `lock` (teacher password set) into `window.MONITOR_CONFIG`; `DEFAULT_TABS` in `App.tsx` is only for `npm run dev`.
- `src/lib/events.ts` turns two consecutive `/monitor.json` snapshots into events (started, submitted, lost, back, left the page, reopened). A student who just pressed Start shows as lost with `ago: null` until the first heartbeat: that is tracked in `starting` and reported as "started", never as "lost". More than 3 events of one kind in one update become one card; the same student/kind is not repeated within 60 s; at most 4 cards.
- Sound is WebAudio tones (no audio files), off by default. Preferences (`exam_monitor_notify`, `exam_monitor_sound`) live in `localStorage` of the teacher browser.
- Events are disabled when `?state=` is in the URL (deterministic mock screenshots).

## Notes
- `window.MONITOR_CONFIG` in `index.html` is replaced by the server on every request (student link and exam title).
- Do not add external fonts, CDNs or analytics: the exam runs without internet.
- Tests: `tests/test_monitor_new_ui.py` drives this UI against the real server.
