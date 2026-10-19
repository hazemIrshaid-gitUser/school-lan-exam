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

## Notes
- `window.MONITOR_CONFIG` in `index.html` is replaced by the server on every request (student link and exam title).
- Do not add external fonts, CDNs or analytics: the exam runs without internet.
- Tests: `tests/test_monitor_new_ui.py` drives this UI against the real server.
