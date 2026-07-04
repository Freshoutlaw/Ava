"""
Ava — ui_server.py  (Tier 10: Desktop UI)
-------------------------------------------
Lightweight WebSocket + HTTP server that powers Ava's real-time dashboard.

Architecture:
  - HTTP server (port 7333): serves the single-file HTML dashboard
  - WebSocket server (port 7334): real-time bridge between ava.py and the UI
  - ava.py calls  ui.push(event_type, data)  to send updates to the browser
  - Browser sends typed messages back (user typed a message in the UI)

Events pushed TO the browser:
  message     — conversation turn  {role, content, ts}
  tool_call   — tool being run     {name, inputs, result, ts}
  delegate    — agent delegation   {agent, task, result_len, ts}
  memory      — memory update      {facts: [...]}
  notice      — heartbeat notice   {label, message, priority, ts}
  goal        — goal progress      {current, target, pct, deadline}
  voice       — voice state        {listening, speaking, transcript}
  status      — system status      {model, memory_count, heartbeat, voice}
  error       — error event        {message, ts}

Events received FROM the browser:
  user_message — user typed a message in the UI chat box

Usage (from ava.py):
  from ui_server import UIServer
  ui = UIServer()
  ui.start()                       # launches server + opens browser
  ui.push("message", {...})        # send any event
  text = ui.get_user_input()       # drain typed messages from UI
  ui.stop()                        # clean shutdown
"""

import json
import threading
import time
import webbrowser
import queue
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# Optional websocket dep — graceful fallback if not installed
try:
    import websockets
    import asyncio
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

UI_HTTP_PORT = 7333
UI_WS_PORT   = 7334
UI_HOST      = "127.0.0.1"

# ── HTML dashboard ─────────────────────────────────────────────────────────────
# Single self-contained file — all CSS and JS inline.
# Served from memory so no file path headaches.

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ava — Executive Assistant</title>
<style>
  :root {
    --bg:       #0a0a0f;
    --surface:  #111118;
    --surface2: #18181f;
    --border:   #2a2a35;
    --accent:   #00e5a0;
    --accent2:  #d4af5a;
    --text:     #e8e8f0;
    --muted:    #666680;
    --error:    #ff5566;
    --warn:     #ffaa33;
    --radius:   10px;
    --font:     'Inter', system-ui, sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; background: var(--bg); color: var(--text); font-family: var(--font); font-size: 14px; overflow: hidden; }

  /* Layout */
  .shell { display: grid; grid-template-columns: 260px 1fr 260px; grid-template-rows: 56px 1fr 80px; height: 100vh; gap: 0; }

  /* Top bar */
  .topbar { grid-column: 1 / -1; display: flex; align-items: center; padding: 0 20px; gap: 16px; background: var(--surface); border-bottom: 1px solid var(--border); }
  .topbar-logo { font-size: 20px; font-weight: 700; letter-spacing: -0.5px; color: var(--accent); }
  .topbar-sub  { font-size: 12px; color: var(--muted); }
  .topbar-spacer { flex: 1; }
  .status-pill { display: flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 20px; border: 1px solid var(--border); font-size: 12px; color: var(--muted); }
  .status-dot  { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }
  .status-dot.on   { background: var(--accent); box-shadow: 0 0 6px var(--accent); }
  .status-dot.warn { background: var(--warn); }
  .status-dot.err  { background: var(--error); }

  /* Left sidebar */
  .sidebar-left { background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
  .sidebar-right { background: var(--surface); border-left: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }

  .panel { padding: 14px 16px; }
  .panel-title { font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin-bottom: 10px; }

  /* Goal ring */
  .goal-wrap { display: flex; flex-direction: column; align-items: center; padding: 16px; }
  .goal-ring  { position: relative; width: 100px; height: 100px; margin-bottom: 8px; }
  .goal-ring svg { transform: rotate(-90deg); }
  .goal-ring circle { fill: none; stroke-width: 8; }
  .goal-ring .track { stroke: var(--border); }
  .goal-ring .fill  { stroke: var(--accent); stroke-linecap: round; transition: stroke-dashoffset 0.6s ease; }
  .goal-pct   { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 700; color: var(--accent); }
  .goal-label { font-size: 12px; color: var(--muted); text-align: center; }
  .goal-nums  { font-size: 13px; font-weight: 600; color: var(--text); text-align: center; margin-top: 2px; }

  /* Memory */
  .memory-list { overflow-y: auto; flex: 1; padding: 0 16px 12px; }
  .memory-item { background: var(--surface2); border: 1px solid var(--border); border-radius: 6px; padding: 7px 10px; margin-bottom: 6px; font-size: 12px; color: var(--text); line-height: 1.4; }
  .memory-id   { font-size: 10px; color: var(--muted); margin-bottom: 2px; }

  /* Notices */
  .notices-list { overflow-y: auto; flex: 1; padding: 0 16px 12px; }
  .notice-item  { border-left: 3px solid var(--muted); padding: 7px 10px; margin-bottom: 6px; border-radius: 0 6px 6px 0; background: var(--surface2); }
  .notice-item.medium   { border-color: var(--accent2); }
  .notice-item.critical { border-color: var(--error); }
  .notice-label { font-size: 10px; color: var(--muted); margin-bottom: 2px; }
  .notice-msg   { font-size: 12px; line-height: 1.4; }

  /* Tool log */
  .tool-list { overflow-y: auto; flex: 1; padding: 0 16px 12px; }
  .tool-item  { background: var(--surface2); border: 1px solid var(--border); border-radius: 6px; padding: 7px 10px; margin-bottom: 6px; }
  .tool-name  { font-size: 11px; font-weight: 600; color: var(--accent); }
  .tool-result { font-size: 11px; color: var(--muted); margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tool-agent { color: var(--accent2) !important; }

  /* Chat */
  .chat-area { display: flex; flex-direction: column; overflow: hidden; }
  .chat-messages { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 14px; }
  .msg { display: flex; gap: 10px; animation: fadeIn 0.2s ease; }
  .msg.ava   { flex-direction: row; }
  .msg.user  { flex-direction: row-reverse; }
  .msg-avatar { width: 30px; height: 30px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; flex-shrink: 0; margin-top: 2px; }
  .msg.ava  .msg-avatar { background: linear-gradient(135deg, #00e5a0, #006644); color: #000; }
  .msg.user .msg-avatar { background: linear-gradient(135deg, #d4af5a, #8a6a2a); color: #000; }
  .msg-body { max-width: 75%; }
  .msg-name { font-size: 10px; color: var(--muted); margin-bottom: 3px; }
  .msg.user .msg-name { text-align: right; }
  .msg-bubble { background: var(--surface2); border: 1px solid var(--border); border-radius: 12px; padding: 10px 14px; font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
  .msg.ava  .msg-bubble { border-top-left-radius: 3px; }
  .msg.user .msg-bubble { border-top-right-radius: 3px; background: var(--surface); border-color: var(--accent); }
  .msg-ts { font-size: 10px; color: var(--muted); margin-top: 3px; }
  .msg.user .msg-ts { text-align: right; }

  /* Typing indicator */
  .typing { display: none; align-items: center; gap: 4px; padding: 4px 14px; }
  .typing.visible { display: flex; }
  .typing-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--accent); animation: bounce 1.2s infinite; }
  .typing-dot:nth-child(2) { animation-delay: 0.2s; }
  .typing-dot:nth-child(3) { animation-delay: 0.4s; }

  /* Voice indicator */
  .voice-bar { grid-column: 1 / -1; display: flex; align-items: center; gap: 12px; padding: 0 20px; background: var(--surface); border-top: 1px solid var(--border); }
  .voice-indicator { display: flex; align-items: center; gap: 8px; }
  .voice-waves { display: flex; align-items: center; gap: 3px; height: 24px; }
  .wave { width: 3px; background: var(--muted); border-radius: 2px; height: 8px; transition: height 0.1s, background 0.1s; }
  .voice-indicator.listening .wave { background: var(--accent); animation: wave 0.6s infinite alternate; }
  .voice-indicator.listening .wave:nth-child(2) { animation-delay: 0.1s; }
  .voice-indicator.listening .wave:nth-child(3) { animation-delay: 0.2s; }
  .voice-indicator.listening .wave:nth-child(4) { animation-delay: 0.1s; }
  .voice-indicator.speaking  .wave { background: var(--accent2); animation: wave 0.3s infinite alternate; }
  .voice-label { font-size: 12px; color: var(--muted); }
  .voice-transcript { font-size: 12px; color: var(--text); font-style: italic; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

  /* Input */
  .input-row { flex: 1; display: flex; gap: 10px; align-items: center; }
  .chat-input { flex: 1; background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; color: var(--text); font-family: var(--font); font-size: 14px; outline: none; transition: border-color 0.15s; }
  .chat-input:focus { border-color: var(--accent); }
  .send-btn { padding: 9px 18px; background: var(--accent); color: #000; border: none; border-radius: 8px; font-weight: 600; font-size: 14px; cursor: pointer; transition: opacity 0.15s; }
  .send-btn:hover { opacity: 0.85; }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  /* Animations */
  @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  @keyframes bounce { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
  @keyframes wave   { from { height: 4px; } to { height: 20px; } }
</style>
</head>
<body>
<div class="shell">
  <!-- Top bar -->
  <header class="topbar">
    <div class="topbar-logo">Ava</div>
    <div class="topbar-sub">Executive Assistant</div>
    <div class="topbar-spacer"></div>
    <div class="status-pill" id="ws-status">
      <div class="status-dot" id="ws-dot"></div>
      <span id="ws-label">Connecting…</span>
    </div>
    <div class="status-pill">
      <div class="status-dot on" id="hb-dot"></div>
      <span id="hb-label">Heartbeat</span>
    </div>
    <div class="status-pill" id="model-pill">
      <span id="model-label">llama-3.3-70b</span>
    </div>
  </header>

  <!-- Left sidebar: goal + memory -->
  <aside class="sidebar-left">
    <div class="goal-wrap">
      <p class="panel-title">Revenue Goal</p>
      <div class="goal-ring">
        <svg viewBox="0 0 100 100" width="100" height="100">
          <circle class="track" cx="50" cy="50" r="42"/>
          <circle class="fill" id="goal-circle" cx="50" cy="50" r="42"
                  stroke-dasharray="264" stroke-dashoffset="264"/>
        </svg>
        <div class="goal-pct" id="goal-pct">0%</div>
      </div>
      <div class="goal-nums" id="goal-nums">$0 / $500,000</div>
      <div class="goal-label" id="goal-deadline">by 2025-12-31</div>
    </div>

    <div class="panel">
      <p class="panel-title">Memory</p>
    </div>
    <div class="memory-list" id="memory-list">
      <div class="memory-item" style="color:var(--muted)">No memories yet.</div>
    </div>
  </aside>

  <!-- Main chat -->
  <main class="chat-area">
    <div class="chat-messages" id="chat-messages">
      <div style="text-align:center;color:var(--muted);font-size:12px;padding:20px 0">
        Connecting to Ava…
      </div>
    </div>
    <div class="typing" id="typing-indicator">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <span style="font-size:12px;color:var(--muted);margin-left:6px">Ava is thinking…</span>
    </div>
  </main>

  <!-- Right sidebar: notices + tool log -->
  <aside class="sidebar-right">
    <div class="panel">
      <p class="panel-title">Notices</p>
    </div>
    <div class="notices-list" id="notices-list" style="max-height: 200px;">
      <div style="color:var(--muted);font-size:12px;padding:0 0 8px">No notices.</div>
    </div>

    <div class="panel" style="padding-top:8px">
      <p class="panel-title">Tool Activity</p>
    </div>
    <div class="tool-list" id="tool-list">
      <div style="color:var(--muted);font-size:12px;padding:0 0 8px">No tool calls yet.</div>
    </div>
  </aside>

  <!-- Bottom voice bar + input -->
  <div class="voice-bar">
    <div class="voice-indicator" id="voice-indicator">
      <div class="voice-waves">
        <div class="wave"></div><div class="wave"></div>
        <div class="wave"></div><div class="wave"></div>
      </div>
      <span class="voice-label" id="voice-label">Voice off</span>
    </div>
    <span class="voice-transcript" id="voice-transcript"></span>
    <div class="input-row">
      <input class="chat-input" id="chat-input" type="text"
             placeholder="Type a message to Ava…" autocomplete="off"/>
      <button class="send-btn" onclick="sendMessage()">Send</button>
    </div>
  </div>
</div>

<script>
const WS_URL = 'ws://127.0.0.1:7334';
let ws = null, reconnectTimer = null;

function ts() {
  return new Date().toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit'});
}

function connect() {
  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    document.getElementById('ws-dot').className   = 'status-dot on';
    document.getElementById('ws-label').textContent = 'Connected';
    clearInterval(reconnectTimer);
  };

  ws.onclose = () => {
    document.getElementById('ws-dot').className   = 'status-dot err';
    document.getElementById('ws-label').textContent = 'Reconnecting…';
    reconnectTimer = setTimeout(connect, 2000);
  };

  ws.onerror = () => {};

  ws.onmessage = (e) => {
    let event;
    try { event = JSON.parse(e.data); } catch { return; }
    handleEvent(event);
  };
}

function handleEvent(ev) {
  const type = ev.type;
  const d    = ev.data || {};

  if (type === 'message') {
    appendMessage(d.role, d.content, d.ts || ts());
    setTyping(false);
  }
  else if (type === 'typing') {
    setTyping(d.active);
  }
  else if (type === 'tool_call') {
    appendTool(d.name, d.result || '', false);
  }
  else if (type === 'delegate') {
    appendTool(d.agent + ' agent', `${d.result_len} chars returned`, true);
  }
  else if (type === 'memory') {
    renderMemory(d.facts || []);
  }
  else if (type === 'notice') {
    appendNotice(d);
  }
  else if (type === 'goal') {
    renderGoal(d);
  }
  else if (type === 'voice') {
    renderVoice(d);
  }
  else if (type === 'status') {
    if (d.model)    document.getElementById('model-label').textContent = d.model.replace('llama-','').slice(0,16);
    if (d.heartbeat !== undefined) {
      document.getElementById('hb-dot').className = 'status-dot ' + (d.heartbeat ? 'on' : 'warn');
    }
  }
  else if (type === 'error') {
    appendMessage('system', '⚠ ' + (d.message || 'Unknown error'), ts());
  }
}

// ── Chat ──────────────────────────────────────────────────────────────────────

function appendMessage(role, content, time_str) {
  const container = document.getElementById('chat-messages');

  // Remove "connecting" placeholder on first message
  const placeholder = container.querySelector('[data-placeholder]');
  if (placeholder) placeholder.remove();

  const isAva  = role === 'assistant' || role === 'ava';
  const isUser = role === 'user';
  const name   = isAva ? 'Ava' : isUser ? 'You' : role;
  const cls    = isAva ? 'ava' : isUser ? 'user' : 'ava';
  const avatar = isAva ? 'A' : isUser ? 'Y' : '?';

  const msg = document.createElement('div');
  msg.className = `msg ${cls}`;
  msg.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div class="msg-body">
      <div class="msg-name">${name}</div>
      <div class="msg-bubble">${escHtml(content)}</div>
      <div class="msg-ts">${time_str}</div>
    </div>`;
  container.appendChild(msg);
  container.scrollTop = container.scrollHeight;
}

function setTyping(active) {
  document.getElementById('typing-indicator').className = 'typing' + (active ? ' visible' : '');
}

function sendMessage() {
  const inp = document.getElementById('chat-input');
  const text = inp.value.trim();
  if (!text || !ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({type: 'user_message', data: {content: text}}));
  appendMessage('user', text, ts());
  setTyping(true);
  inp.value = '';
}

document.getElementById('chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});

// ── Memory ────────────────────────────────────────────────────────────────────

function renderMemory(facts) {
  const list = document.getElementById('memory-list');
  if (!facts.length) {
    list.innerHTML = '<div class="memory-item" style="color:var(--muted)">No memories yet.</div>';
    return;
  }
  list.innerHTML = facts.map(f =>
    `<div class="memory-item">
       <div class="memory-id">${f.id} · ${f.saved || f.updated || ''}</div>
       ${escHtml(f.fact)}
     </div>`
  ).join('');
}

// ── Notices ───────────────────────────────────────────────────────────────────

function appendNotice(n) {
  const list = document.getElementById('notices-list');
  const placeholder = list.querySelector('[data-placeholder]');
  if (placeholder) placeholder.remove();

  const el = document.createElement('div');
  el.className = `notice-item ${n.priority || 'low'}`;
  el.innerHTML = `<div class="notice-label">${escHtml(n.label || '')} · ${n.ts || ts()}</div>
                  <div class="notice-msg">${escHtml(n.message || '')}</div>`;
  list.prepend(el);
}

// ── Tool log ──────────────────────────────────────────────────────────────────

function appendTool(name, result, isAgent) {
  const list = document.getElementById('tool-list');
  const placeholder = list.querySelector('[style*="color:var(--muted)"]');
  if (placeholder && placeholder.textContent.includes('No tool')) placeholder.remove();

  const el = document.createElement('div');
  el.className = 'tool-item';
  el.innerHTML = `<div class="tool-name ${isAgent ? 'tool-agent' : ''}">${isAgent ? '⬡ ' : '⚙ '}${escHtml(name)}</div>
                  <div class="tool-result">${escHtml(result.toString().slice(0, 80))}</div>`;
  list.prepend(el);
  // Keep log to 20 items
  while (list.children.length > 20) list.removeChild(list.lastChild);
}

// ── Goal ring ─────────────────────────────────────────────────────────────────

function renderGoal(d) {
  const pct  = Math.min(100, Math.max(0, d.pct || 0));
  const circ = 2 * Math.PI * 42;
  const offset = circ - (pct / 100) * circ;
  document.getElementById('goal-circle').style.strokeDashoffset = offset;
  document.getElementById('goal-pct').textContent = pct.toFixed(1) + '%';
  document.getElementById('goal-nums').textContent =
    '$' + (d.current || 0).toLocaleString() + ' / $' + (d.target || 500000).toLocaleString();
  if (d.deadline) document.getElementById('goal-deadline').textContent = 'by ' + d.deadline;
}

// ── Voice ─────────────────────────────────────────────────────────────────────

function renderVoice(d) {
  const ind   = document.getElementById('voice-indicator');
  const label = document.getElementById('voice-label');
  const trans = document.getElementById('voice-transcript');
  ind.className = 'voice-indicator';
  if (d.speaking)   { ind.classList.add('speaking');  label.textContent = 'Ava speaking'; }
  else if (d.listening) { ind.classList.add('listening'); label.textContent = 'Listening…'; }
  else                  { label.textContent = 'Voice off'; }
  if (d.transcript) trans.textContent = '"' + d.transcript + '"';
}

// ── Utils ─────────────────────────────────────────────────────────────────────

function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/\n/g,'<br>');
}

// Boot
connect();
</script>
</body>
</html>"""


# ── HTTP handler — serves the React build if present, else inline dashboard ───

import mimetypes
from pathlib import Path as _Path

_REACT_DIST = _Path(__file__).parent / "ui_react" / "dist"

class _DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Serve the built React app if it exists
        if _REACT_DIST.is_dir():
            req_path = self.path.split("?")[0]
            if req_path == "/":
                req_path = "/index.html"
            file_path = (_REACT_DIST / req_path.lstrip("/")).resolve()

            # Security: stay within dist/
            try:
                file_path.relative_to(_REACT_DIST.resolve())
            except ValueError:
                self.send_response(403); self.end_headers(); return

            if file_path.is_file():
                content_type, _ = mimetypes.guess_type(str(file_path))
                content_type = content_type or "application/octet-stream"
                data = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            # SPA fallback — unknown routes serve index.html so React Router works
            index = _REACT_DIST / "index.html"
            if index.is_file():
                data = index.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

        # Fallback: inline HTML dashboard (no React build present)
        html = DASHBOARD_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def log_message(self, *args):
        pass   # silence HTTP access log


# ── WebSocket server ──────────────────────────────────────────────────────────

class UIServer:
    """
    Manages the HTTP server, WebSocket server, and the event queue
    between ava.py and the browser.

    Usage:
        ui = UIServer()
        ui.start()
        ui.push("message", {"role": "assistant", "content": "Hi Alex"})
        typed = ui.get_user_input()   # returns None or str
        ui.stop()
    """

    def __init__(self, http_port: int = UI_HTTP_PORT, ws_port: int = UI_WS_PORT):
        self.http_port     = http_port
        self.ws_port       = ws_port
        self._clients:     set   = set()
        self._clients_lock        = threading.Lock()
        self._send_queue:  queue.Queue = queue.Queue()
        self._input_queue: queue.Queue = queue.Queue()
        self._http_server  = None
        self._ws_loop      = None
        self._running      = False

    def start(self, open_browser: bool = True):
        """Start HTTP + WebSocket servers and open the browser."""
        if not WS_AVAILABLE:
            print("[ui] websockets not installed — UI disabled. Run: pip install websockets")
            return

        self._running = True

        # HTTP server thread
        self._http_server = HTTPServer((UI_HOST, self.http_port), _DashboardHandler)
        threading.Thread(target=self._http_server.serve_forever,
                         name="ava-ui-http", daemon=True).start()

        # WebSocket server thread (runs its own asyncio loop)
        threading.Thread(target=self._ws_thread,
                         name="ava-ui-ws", daemon=True).start()

        time.sleep(0.3)   # brief settle

        if open_browser:
            url = f"http://{UI_HOST}:{self.http_port}"
            webbrowser.open(url)
            print(f"[ui] Dashboard opened at {url}")
        else:
            print(f"[ui] Dashboard ready at http://{UI_HOST}:{self.http_port}")

    def stop(self):
        self._running = False
        if self._http_server:
            self._http_server.shutdown()

    def push(self, event_type: str, data: dict):
        """Queue an event to be sent to all connected browser clients."""
        msg = json.dumps({"type": event_type, "data": data})
        self._send_queue.put(msg)

    def get_user_input(self) -> str | None:
        """Return a message the user typed in the browser, or None."""
        try:
            return self._input_queue.get_nowait()
        except queue.Empty:
            return None

    # ── WebSocket internals ───────────────────────────────────────────────────

    def _ws_thread(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._ws_loop = loop
        loop.run_until_complete(self._ws_serve())

    async def _ws_serve(self):
        import websockets
        async def handler(ws):
            with self._clients_lock:
                self._clients.add(ws)
            try:
                # Drain outgoing queue for this client on connection
                async for msg in ws:
                    try:
                        ev = json.loads(msg)
                        if ev.get("type") == "user_message":
                            content = ev.get("data", {}).get("content", "").strip()
                            if content:
                                self._input_queue.put(content)
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                with self._clients_lock:
                    self._clients.discard(ws)

        # Background broadcaster — drains _send_queue and fans out to all clients
        async def broadcaster():
            while self._running:
                try:
                    while not self._send_queue.empty():
                        msg = self._send_queue.get_nowait()
                        with self._clients_lock:
                            dead = set()
                            for ws in self._clients:
                                try:
                                    await ws.send(msg)
                                except Exception:
                                    dead.add(ws)
                            self._clients -= dead
                except Exception:
                    pass
                await asyncio.sleep(0.05)

        import websockets.server as _wss
        async with _wss.serve(handler, UI_HOST, self.ws_port):
            await broadcaster()