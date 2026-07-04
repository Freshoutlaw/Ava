"""
Ava — daemon.py  (Background service)
---------------------------------------
Runs Ava as a persistent Windows background process that:
  - Starts automatically at Windows login (via registry Run key)
  - Keeps the brain, heartbeat, and memory alive even with no window open
  - Exposes a named pipe (\\.\pipe\AvaDaemon) so any UI can connect/reconnect
  - Forwards events to the desktop UI when it's open
  - Writes a PID file so you always know if the daemon is running

Commands:
  python daemon.py start     — start the daemon in background
  python daemon.py stop      — stop a running daemon
  python daemon.py restart   — stop then start
  python daemon.py status    — check if daemon is running
  python daemon.py install   — add to Windows startup (registry)
  python daemon.py uninstall — remove from Windows startup

Pipe protocol (newline-delimited JSON):
  Client → Daemon:   {"type": "user_message", "content": "..."}
                     {"type": "ping"}
                     {"type": "shutdown"}
  Daemon → Client:   {"type": "message",   "data": {...}}
                     {"type": "tool_call", "data": {...}}
                     {"type": "memory",    "data": {...}}
                     {"type": "goal",      "data": {...}}
                     {"type": "notice",    "data": {...}}
                     {"type": "voice",     "data": {...}}
                     {"type": "status",    "data": {...}}
                     {"type": "pong"}
"""

import json
import os
import sys
import time
import threading
import subprocess
import signal
from pathlib import Path
from datetime import datetime

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT     = Path(__file__).parent
PID_FILE = ROOT / "data" / "ava_daemon.pid"
LOG_FILE = ROOT / "data" / "ava_daemon.log"
PIPE_NAME = r"\\.\pipe\AvaDaemon"

# ── Windows named pipe support ────────────────────────────────────────────────
try:
    import win32pipe
    import win32file
    import win32api
    import pywintypes
    WIN_PIPE = True
except ImportError:
    WIN_PIPE = False

# ── Logging ───────────────────────────────────────────────────────────────────

def _log(msg: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════════════
# DAEMON CLASS
# ═════════════════════════════════════════════════════════════════════════════

class AvaDaemon:
    """
    The Ava background service. Runs ava.py's core in-process and
    exposes a named pipe for UI clients to connect to.
    """

    def __init__(self):
        self._clients: list = []
        self._clients_lock  = threading.Lock()
        self._event_queue   = []
        self._eq_lock       = threading.Lock()
        self._running       = False

        # These are imported lazily so the daemon can start even if some
        # optional deps aren't installed — it just logs and degrades.
        self._ava_history: list[dict] = []
        self._agent_turn = None
        self._brain      = None

    def start(self):
        """Main entry point — called after daemonising."""
        _log("Ava daemon starting…")
        self._write_pid()
        self._running = True

        # Load ava modules
        try:
            self._load_ava_core()
        except Exception as e:
            _log(f"Failed to load Ava core: {e}")
            self._cleanup()
            return

        # Start pipe server
        if WIN_PIPE:
            threading.Thread(target=self._pipe_server, name="ava-pipe", daemon=True).start()
            _log(f"Named pipe ready: {PIPE_NAME}")
        else:
            _log("pywin32 not installed — named pipe unavailable. Run: pip install pywin32")

        # Start heartbeat
        try:
            from heartbeat import start_heartbeat
            start_heartbeat()
            _log("Heartbeat running.")
        except Exception as e:
            _log(f"Heartbeat failed: {e}")

        # Keep alive
        try:
            signal.signal(signal.SIGINT,  self._handle_signal)
            signal.signal(signal.SIGTERM, self._handle_signal)
        except Exception:
            pass

        _log("Ava daemon ready.")
        while self._running:
            time.sleep(1)

        self._cleanup()
        _log("Ava daemon stopped.")

    def _handle_signal(self, signum, frame):
        _log(f"Signal {signum} received — shutting down.")
        self._running = False

    def _write_pid(self):
        PID_FILE.parent.mkdir(exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))

    def _cleanup(self):
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    # ── Load Ava's core modules ───────────────────────────────────────────────

    def _load_ava_core(self):
        """Import ava.py's agent_turn so the daemon can run conversations."""
        sys.path.insert(0, str(ROOT))

        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")

        # Import key functions from ava.py
        import ava as _ava_module
        self._agent_turn  = _ava_module.agent_turn
        self._ava_history = []
        import brain as _brain
        self._brain = _brain
        _log("Ava core loaded.")

    # ── Named pipe server ─────────────────────────────────────────────────────

    def _pipe_server(self):
        """
        Accepts one client at a time on the named pipe.
        Each connected client gets a dedicated thread.
        """
        while self._running:
            try:
                pipe = win32pipe.CreateNamedPipe(
                    PIPE_NAME,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                    win32pipe.PIPE_UNLIMITED_INSTANCES,
                    65536, 65536,
                    0, None,
                )
                win32pipe.ConnectNamedPipe(pipe, None)
                _log("UI client connected via pipe.")
                threading.Thread(
                    target=self._pipe_client_handler,
                    args=(pipe,), daemon=True
                ).start()
            except Exception as e:
                if self._running:
                    _log(f"Pipe server error: {e}")
                time.sleep(1)

    def _pipe_client_handler(self, pipe):
        """Handle one connected UI client."""
        with self._clients_lock:
            self._clients.append(pipe)

        # Send current status on connect
        self._send_to_pipe(pipe, "status", {
            "model":     os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "heartbeat": True,
            "daemon":    True,
        })

        try:
            while self._running:
                try:
                    _, data = win32file.ReadFile(pipe, 65536)
                    text = data.decode("utf-8").strip()
                    if not text:
                        continue
                    msg = json.loads(text)
                    mtype = msg.get("type", "")

                    if mtype == "ping":
                        self._send_to_pipe(pipe, "pong", {})

                    elif mtype == "shutdown":
                        _log("Shutdown requested by UI client.")
                        self._running = False
                        break

                    elif mtype == "user_message":
                        content = msg.get("content", "").strip()
                        if content:
                            threading.Thread(
                                target=self._handle_user_message,
                                args=(content, pipe), daemon=True
                            ).start()

                except pywintypes.error as e:
                    if e.args[0] in (109, 232):  # broken pipe / client disconnected
                        break
                    _log(f"Pipe read error: {e}")
                    break
        finally:
            with self._clients_lock:
                if pipe in self._clients:
                    self._clients.remove(pipe)
            try:
                win32file.CloseHandle(pipe)
            except Exception:
                pass
            _log("UI client disconnected.")

    def _handle_user_message(self, text: str, pipe):
        """Run agent_turn and stream results back to the pipe client."""
        if not self._agent_turn:
            self._send_to_pipe(pipe, "error", {"message": "Ava core not loaded."})
            return
        self._send_to_pipe(pipe, "typing", {"active": True})
        try:
            # Patch speak/stream so outputs go to pipe instead of terminal
            reply = self._agent_turn(
                self._ava_history, text, voice_out=False
            )
            self._send_to_pipe(pipe, "message", {
                "role":    "assistant",
                "content": reply,
                "ts":      datetime.now().strftime("%H:%M"),
            })
        except Exception as e:
            self._send_to_pipe(pipe, "error", {"message": str(e)})
        finally:
            self._send_to_pipe(pipe, "typing", {"active": False})

    def _send_to_pipe(self, pipe, event_type: str, data: dict):
        try:
            msg = json.dumps({"type": event_type, "data": data}) + "\n"
            win32file.WriteFile(pipe, msg.encode("utf-8"))
        except Exception:
            pass

    def broadcast(self, event_type: str, data: dict):
        """Send an event to all connected pipe clients."""
        with self._clients_lock:
            dead = []
            for pipe in self._clients:
                try:
                    self._send_to_pipe(pipe, event_type, data)
                except Exception:
                    dead.append(pipe)
            for p in dead:
                self._clients.remove(p)


# ═════════════════════════════════════════════════════════════════════════════
# PIPE CLIENT  (used by ui_desktop.py to talk to the daemon)
# ═════════════════════════════════════════════════════════════════════════════

class PipeClient:
    """
    Connects to the AvaDaemon named pipe.
    Usage:
        client = PipeClient()
        if client.connect():
            client.send_message("hello Ava")
            event = client.read_event()   # blocking
    """

    def __init__(self, pipe_name: str = PIPE_NAME):
        self.pipe_name = pipe_name
        self._pipe     = None
        self._connected = False

    def connect(self, timeout: float = 5.0) -> bool:
        if not WIN_PIPE:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._pipe = win32file.CreateFile(
                    self.pipe_name,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None,
                    win32file.OPEN_EXISTING,
                    0, None,
                )
                win32pipe.SetNamedPipeHandleState(
                    self._pipe,
                    win32pipe.PIPE_READMODE_MESSAGE,
                    None, None,
                )
                self._connected = True
                return True
            except pywintypes.error:
                time.sleep(0.2)
        return False

    def send_message(self, text: str):
        self._write({"type": "user_message", "content": text})

    def ping(self):
        self._write({"type": "ping"})

    def read_event(self) -> dict | None:
        """Read one event from the daemon. Blocking. Returns None on disconnect."""
        if not self._connected or not self._pipe:
            return None
        try:
            _, data = win32file.ReadFile(self._pipe, 65536)
            return json.loads(data.decode("utf-8").strip())
        except Exception:
            self._connected = False
            return None

    def close(self):
        try:
            if self._pipe:
                win32file.CloseHandle(self._pipe)
        except Exception:
            pass
        self._connected = False

    def _write(self, obj: dict):
        if not self._connected or not self._pipe:
            return
        try:
            msg = json.dumps(obj) + "\n"
            win32file.WriteFile(self._pipe, msg.encode("utf-8"))
        except Exception:
            self._connected = False


# ═════════════════════════════════════════════════════════════════════════════
# CLI COMMANDS
# ═════════════════════════════════════════════════════════════════════════════

def _get_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except Exception:
        return None

def _is_running(pid: int) -> bool:
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        # Fallback without psutil
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

def cmd_start():
    pid = _get_pid()
    if pid and _is_running(pid):
        print(f"Ava daemon already running (PID {pid}).")
        return

    # Launch daemon as a detached background process
    python = sys.executable
    script = str(Path(__file__).resolve())
    proc   = subprocess.Popen(
        [python, script, "_run"],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            if sys.platform == "win32" else 0,
        stdout=open(LOG_FILE, "a"),
        stderr=subprocess.STDOUT,
        close_fds=True,
    )
    time.sleep(0.8)
    print(f"Ava daemon started (PID {proc.pid}).")

def cmd_stop():
    pid = _get_pid()
    if not pid:
        print("Ava daemon is not running.")
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], check=False, capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
        time.sleep(0.5)
        PID_FILE.unlink(missing_ok=True)
        print(f"Ava daemon stopped (PID {pid}).")
    except Exception as e:
        print(f"Could not stop daemon: {e}")

def cmd_restart():
    cmd_stop()
    time.sleep(1)
    cmd_start()

def cmd_status():
    pid = _get_pid()
    if not pid:
        print("Ava daemon: NOT running")
        return
    if _is_running(pid):
        print(f"Ava daemon: RUNNING  (PID {pid})")
        # Try a ping via pipe
        if WIN_PIPE:
            client = PipeClient()
            if client.connect(timeout=2):
                client.ping()
                ev = client.read_event()
                if ev and ev.get("type") == "pong":
                    print("  Pipe: responsive ✓")
                client.close()
    else:
        print(f"Ava daemon: STALE PID ({pid}) — daemon is not running")
        PID_FILE.unlink(missing_ok=True)

def cmd_install():
    """Add daemon to Windows startup via registry."""
    try:
        import winreg
        key  = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        cmd  = f'"{sys.executable}" "{Path(__file__).resolve()}" start'
        winreg.SetValueEx(key, "AvaDaemon", 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(key)
        print(f"Ava daemon installed to Windows startup:\n  {cmd}")
    except ImportError:
        print("winreg not available — not on Windows?")
    except Exception as e:
        print(f"Registry install failed: {e}")

def cmd_uninstall():
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE,
        )
        try:
            winreg.DeleteValue(key, "AvaDaemon")
            print("Ava daemon removed from Windows startup.")
        except FileNotFoundError:
            print("Ava daemon was not in Windows startup.")
        winreg.CloseKey(key)
    except Exception as e:
        print(f"Registry uninstall failed: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

COMMANDS = {
    "start":     cmd_start,
    "stop":      cmd_stop,
    "restart":   cmd_restart,
    "status":    cmd_status,
    "install":   cmd_install,
    "uninstall": cmd_uninstall,
    "_run":      lambda: AvaDaemon().start(),   # internal — launched by cmd_start
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    fn  = COMMANDS.get(cmd)
    if fn:
        fn()
    else:
        print(f"Unknown command '{cmd}'. Use: {' | '.join(k for k in COMMANDS if not k.startswith('_'))}")
