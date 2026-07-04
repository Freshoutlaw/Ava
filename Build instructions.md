# Building Ava's React UI

One-time setup, then Ava always uses the built version — no dev server needed at runtime.

## 1. Install Node.js
Download from https://nodejs.org (LTS version) if you don't have it.

## 2. Install dependencies
```cmd
cd C:\Users\ADMIN\OneDrive\Desktop\Ava\ui_react
npm install
```

## 3. Build for production
```cmd
npm run build
```
This creates `ui_react/dist/` — a folder of static HTML/JS/CSS.

## 4. Point Ava at the build
`ui_server.py` is updated to serve `ui_react/dist/index.html` instead of
the inline HTML string, when that folder exists. No extra config needed —
it auto-detects the build.

## 5. Run Ava
```cmd
cd C:\Users\ADMIN\OneDrive\Desktop\Ava
python ava.py
```
The native window (PyWebView) now renders the React app instead of the
old tkinter interface.

---

## Developing / iterating on the UI

While actively changing the React code, run a hot-reload dev server instead
of rebuilding every time:

```cmd
cd ui_react
npm run dev
```
This starts Vite on http://localhost:5173 with instant hot reload.
Point your browser there while editing — once happy, `npm run build` again
to bake it into the desktop app.

## Troubleshooting

**"npm not found"** — Node.js isn't installed or not in PATH. Reinstall
from nodejs.org and restart your terminal.

**Blank window** — Check `ui_react/dist/` exists and has an `index.html`
inside it. If not, the build failed — check the npm run build output for
errors.

**Still seeing the old tkinter window** — Make sure `ava.py` is using
`ui_pywebview.py` (not `ui_desktop.py`). See the import line near the top
of `ava.py`.