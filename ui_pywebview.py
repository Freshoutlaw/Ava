"""
Ava — ui_pywebview.py  (Native React Desktop UI)
--------------------------------------------------
Renders Ava's React interface inside a native OS window using PyWebView.
No browser required. Looks like a real desktop app.

Architecture:
  - PyWebView opens a native window (WebKit on Mac/Linux, Edge WebView2 on Windows)
  - The React build is served from a local HTTP server on port 7333
  - Real-time data flows over WebSocket on port 7334 (same as web UI)
  - ava.py calls ui.push(event, data) exactly like before — both UIs share the bridge

Install:
  pip install pywebview

Usage from ava.py (replaces ui_desktop.py):
  from ui_pywebview import PyWebViewUI
  ui = PyWebViewUI()
  ui.start()
  ui.push("message", {...})
  text = ui.get_user_input()
  ui.stop()

Or launch standalone for development:
  python ui_pywebview.py
"""

import sys, threading, time, json, queue, os
from pathlib import Path

try:
    import webview
    WEBVIEW_AVAILABLE = True
except ImportError:
    WEBVIEW_AVAILABLE = False

# Reuse the existing HTTP + WebSocket server from ui_server.py
try:
    from ui_server import UIServer
    SERVER_AVAILABLE = True
except ImportError:
    SERVER_AVAILABLE = False

UI_HTTP_PORT = 7333
UI_WS_PORT   = 7334
UI_HOST      = "127.0.0.1"
WINDOW_TITLE = "Ava — Executive Assistant"
WINDOW_W     = 1280
WINDOW_H     = 800


class PyWebViewUI:
    """
    Native desktop UI using PyWebView + React.
    Drop-in replacement for DesktopUI — same push() / get_user_input() API.
    """

    def __init__(self):
        self._server       = UIServer(http_port=UI_HTTP_PORT, ws_port=UI_WS_PORT) if SERVER_AVAILABLE else None
        self._window       = None
        self._thread       = None
        self._stop_flag    = threading.Event()
        self._ready        = threading.Event()

    def push(self, event_type: str, data: dict):
        if self._server:
            self._server.push(event_type, data)

    def get_user_input(self) -> str | None:
        if self._server:
            return self._server.get_user_input()
        return None

    def start(self, block: bool = False):
        if not WEBVIEW_AVAILABLE:
            print("[ui] pywebview not installed. Run: pip install pywebview")
            print("[ui] Falling back to web UI — open http://127.0.0.1:7333 in your browser.")
            if self._server:
                self._server.start(open_browser=True)
            return

        if not SERVER_AVAILABLE:
            print("[ui] ui_server.py not found — cannot start UI.")
            return

        self._thread = threading.Thread(target=self._run, name="ava-webview", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=8)

        if block:
            self._thread.join()

    def stop(self):
        self._stop_flag.set()
        if self._server:
            try: self._server.stop()
            except Exception: pass
        if self._window:
            try: self._window.destroy()
            except Exception: pass

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        # Start HTTP + WebSocket server first
        if self._server:
            self._server.start(open_browser=False)
            time.sleep(0.4)   # let server settle

        url = f"http://{UI_HOST}:{UI_HTTP_PORT}"

        try:
            self._window = webview.create_window(
                title      = WINDOW_TITLE,
                url        = url,
                width      = WINDOW_W,
                height     = WINDOW_H,
                min_size   = (900, 600),
                resizable  = True,
                text_select= True,
                # Remove browser chrome — looks like a native app
                frameless  = False,
                easy_drag  = False,
            )
            self._ready.set()
            # start() blocks until the window is closed
            webview.start(debug=False)
        except Exception as e:
            print(f"[ui] PyWebView error: {e}")
            self._ready.set()


# ── Standalone launch for development ────────────────────────────────────────

if __name__ == "__main__":
    import os, sys
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    print("[ui] Starting Ava native desktop window…")
    ui = PyWebViewUI()
    ui.start(block=True)