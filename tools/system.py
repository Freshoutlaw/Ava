"""
Ava — tools/system.py  (Tier 14: System Automation)
-----------------------------------------------------
Gives Ava direct control over the Windows system:
  - Run any program or shell command
  - Manage processes (list, kill, start)
  - Control clipboard (read/write)
  - Keyboard and mouse automation
  - Take screenshots
  - Schedule Windows tasks
  - Manage Windows services
  - File operations at OS level
  - Volume / brightness control
  - Lock screen, sleep, restart, shutdown (all gated)

All destructive or irreversible actions are flagged requires_confirmation=True.
The confirmation gate in ava.py will stop them before execution.
"""

import os, sys, time, subprocess, shutil, json, threading
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# ── Optional deps (degrade gracefully) ────────────────────────────────────────
try:
    import psutil
    PSUTIL = True
except ImportError:
    PSUTIL = False

try:
    import pyautogui
    pyautogui.FAILSAFE = True   # move mouse to top-left corner to abort
    pyautogui.PAUSE    = 0.3
    PYAUTOGUI = True
except ImportError:
    PYAUTOGUI = False

try:
    import pyperclip
    PYPERCLIP = True
except ImportError:
    PYPERCLIP = False

try:
    from PIL import ImageGrab, Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ── 1. Shell command runner ───────────────────────────────────────────────────

# Commands that require confirmation before running
_DANGEROUS_PATTERNS = [
    "rm ", "del ", "rmdir", "format", "shutdown", "restart", "reboot",
    "reg delete", "taskkill", "net user", "cipher /w", "fdisk",
    "> ", "| del", "powershell -exec", "invoke-expression",
]

def _is_dangerous(cmd: str) -> bool:
    cmd_lower = cmd.lower()
    return any(p in cmd_lower for p in _DANGEROUS_PATTERNS)

def handle_run_command(inputs: dict) -> str:
    """
    Run a shell command and return its output.
    Uses PowerShell on Windows, bash on Linux/Mac.
    Timeout defaults to 30s — override with timeout_seconds.
    """
    cmd     = inputs.get("command", "").strip()
    shell   = inputs.get("shell", "powershell").lower()   # powershell | cmd | bash
    timeout = int(inputs.get("timeout_seconds", 30))
    workdir = inputs.get("working_directory", "").strip() or None

    if not cmd:
        return "Error: 'command' is required."

    # Build the actual shell invocation
    if sys.platform == "win32":
        if shell == "powershell":
            full_cmd = ["powershell", "-NonInteractive", "-Command", cmd]
        elif shell == "cmd":
            full_cmd = ["cmd", "/c", cmd]
        else:
            full_cmd = ["bash", "-c", cmd]
    else:
        full_cmd = ["bash", "-c", cmd]

    try:
        result = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir,
            encoding="utf-8",
            errors="replace",
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        code   = result.returncode

        if code == 0:
            return stdout or "(command completed with no output)"
        else:
            return f"Exit code {code}\nstdout: {stdout}\nstderr: {stderr}"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except FileNotFoundError as e:
        return f"Error: shell not found — {e}"
    except Exception as e:
        return f"Error running command: {e}"


def handle_run_script(inputs: dict) -> str:
    """
    Write a script to a temp file and run it.
    Supports: powershell (.ps1), python (.py), batch (.bat), bash (.sh)
    """
    code     = inputs.get("code", "").strip()
    lang     = inputs.get("language", "powershell").lower()
    timeout  = int(inputs.get("timeout_seconds", 60))
    if not code:
        return "Error: 'code' is required."

    import tempfile
    ext_map = {"powershell": ".ps1", "python": ".py", "batch": ".bat", "bash": ".sh"}
    ext     = ext_map.get(lang, ".ps1")

    with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False,
                                      encoding="utf-8") as f:
        f.write(code)
        tmp = f.name

    try:
        if lang == "powershell":
            cmd = ["powershell", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", tmp]
        elif lang == "python":
            cmd = [sys.executable, tmp]
        elif lang == "batch":
            cmd = ["cmd", "/c", tmp]
        else:
            cmd = ["bash", tmp]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                encoding="utf-8", errors="replace")
        out = result.stdout.strip()
        err = result.stderr.strip()
        return out if result.returncode == 0 else f"Exit {result.returncode}\n{out}\n{err}"
    except subprocess.TimeoutExpired:
        return f"Script timed out after {timeout}s"
    except Exception as e:
        return f"Script error: {e}"
    finally:
        try: os.unlink(tmp)
        except Exception: pass


# ── 2. Process management ─────────────────────────────────────────────────────

def handle_list_processes(inputs: dict) -> str:
    """List running processes, optionally filtered by name."""
    if not PSUTIL:
        return "Error: psutil not installed. Run: pip install psutil"
    filter_name = inputs.get("filter", "").strip().lower()
    procs = []
    for p in psutil.process_iter(["pid","name","cpu_percent","memory_mb","status"]):
        try:
            info = p.info
            if filter_name and filter_name not in info["name"].lower():
                continue
            mem = getattr(p, "memory_info", lambda: None)()
            mem_mb = round(mem.rss / 1024 / 1024, 1) if mem else 0
            procs.append(f"  PID {info['pid']:6d}  {info['name'][:35]:<35}  "
                         f"CPU {p.cpu_percent(interval=0.1):5.1f}%  MEM {mem_mb:7.1f}MB  {info['status']}")
        except Exception:
            pass
    if not procs:
        return f"No processes found{f' matching \"{filter_name}\"' if filter_name else ''}."
    header = f"{'PID':>10}  {'Name':<35}  {'CPU':>8}  {'Memory':>10}  Status"
    return f"Running processes ({len(procs)}):\n{header}\n" + "\n".join(procs[:50])


def handle_kill_process(inputs: dict) -> str:
    """Kill a process by PID or name."""
    if not PSUTIL:
        return "Error: psutil not installed. Run: pip install psutil"
    pid  = inputs.get("pid")
    name = inputs.get("name", "").strip()
    if not pid and not name:
        return "Error: provide 'pid' or 'name'."
    killed = []
    for p in psutil.process_iter(["pid","name"]):
        try:
            if (pid and p.pid == int(pid)) or (name and name.lower() in p.name().lower()):
                p.terminate()
                killed.append(f"{p.name()} (PID {p.pid})")
        except Exception:
            pass
    return f"Terminated: {', '.join(killed)}" if killed else "No matching processes found."


def handle_start_app(inputs: dict) -> str:
    """Launch an application by path or name."""
    app  = inputs.get("app", "").strip()
    args = inputs.get("args", "")
    if not app:
        return "Error: 'app' is required."
    try:
        full_cmd = f'"{app}" {args}'.strip() if args else f'"{app}"'
        if sys.platform == "win32":
            subprocess.Popen(full_cmd, shell=True,
                             creationflags=subprocess.DETACHED_PROCESS)
        else:
            subprocess.Popen(full_cmd, shell=True)
        return f"Launched: {app}"
    except Exception as e:
        return f"Error launching {app}: {e}"


# ── 3. Clipboard ──────────────────────────────────────────────────────────────

def handle_clipboard_read(inputs: dict) -> str:
    if not PYPERCLIP:
        return "Error: pyperclip not installed. Run: pip install pyperclip"
    try:
        content = pyperclip.paste()
        return f"Clipboard contents ({len(content)} chars):\n{content[:2000]}"
    except Exception as e:
        return f"Clipboard read error: {e}"

def handle_clipboard_write(inputs: dict) -> str:
    if not PYPERCLIP:
        return "Error: pyperclip not installed. Run: pip install pyperclip"
    text = inputs.get("text", "")
    if not text:
        return "Error: 'text' is required."
    try:
        pyperclip.copy(text)
        return f"Copied to clipboard ({len(text)} chars)."
    except Exception as e:
        return f"Clipboard write error: {e}"


# ── 4. Keyboard / mouse ───────────────────────────────────────────────────────

def handle_type_text(inputs: dict) -> str:
    """Type text as keyboard input into the active window."""
    if not PYAUTOGUI:
        return "Error: pyautogui not installed. Run: pip install pyautogui"
    text     = inputs.get("text", "")
    interval = float(inputs.get("interval", 0.05))
    if not text:
        return "Error: 'text' is required."
    try:
        time.sleep(0.5)   # brief pause so focus can settle
        pyautogui.typewrite(text, interval=interval)
        return f"Typed {len(text)} characters."
    except Exception as e:
        return f"Type error: {e}"

def handle_hotkey(inputs: dict) -> str:
    """Press a keyboard shortcut, e.g. 'ctrl+c', 'alt+f4', 'win+d'."""
    if not PYAUTOGUI:
        return "Error: pyautogui not installed. Run: pip install pyautogui"
    keys = inputs.get("keys", "").strip()
    if not keys:
        return "Error: 'keys' is required (e.g. 'ctrl+c')."
    try:
        parts = [k.strip() for k in keys.split("+")]
        pyautogui.hotkey(*parts)
        return f"Pressed: {keys}"
    except Exception as e:
        return f"Hotkey error: {e}"

def handle_mouse_click(inputs: dict) -> str:
    """Click at screen coordinates or a named location."""
    if not PYAUTOGUI:
        return "Error: pyautogui not installed. Run: pip install pyautogui"
    x      = inputs.get("x")
    y      = inputs.get("y")
    button = inputs.get("button", "left")
    clicks = int(inputs.get("clicks", 1))
    if x is None or y is None:
        return "Error: 'x' and 'y' coordinates required."
    try:
        pyautogui.click(int(x), int(y), button=button, clicks=clicks)
        return f"Clicked {button} at ({x},{y}) × {clicks}"
    except Exception as e:
        return f"Click error: {e}"


# ── 5. Screenshot ─────────────────────────────────────────────────────────────

def handle_screenshot(inputs: dict) -> str:
    """Take a screenshot and save it. Returns the file path."""
    if not PIL_AVAILABLE:
        return "Error: Pillow not installed. Run: pip install Pillow"
    save_path = inputs.get("path", "").strip()
    if not save_path:
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = str(DATA_DIR / f"screenshot_{ts}.png")
    try:
        img = ImageGrab.grab()
        img.save(save_path)
        w, h = img.size
        return f"Screenshot saved: {save_path}  ({w}×{h}px)"
    except Exception as e:
        return f"Screenshot error: {e}"


# ── 6. Windows task scheduler ─────────────────────────────────────────────────

def handle_schedule_task(inputs: dict) -> str:
    """
    Create a Windows Scheduled Task.
    trigger: 'daily HH:MM' | 'onlogon' | 'once YYYY-MM-DD HH:MM'
    """
    name    = inputs.get("name", "").strip()
    command = inputs.get("command", "").strip()
    trigger = inputs.get("trigger", "daily 09:00").strip()
    if not name or not command:
        return "Error: 'name' and 'command' are required."
    if sys.platform != "win32":
        return "Error: Windows Task Scheduler only available on Windows."
    # Build schtasks command
    if trigger.startswith("daily"):
        time_part = trigger.split()[-1]
        sched_cmd = f'schtasks /create /tn "{name}" /tr "{command}" /sc daily /st {time_part} /f'
    elif trigger == "onlogon":
        sched_cmd = f'schtasks /create /tn "{name}" /tr "{command}" /sc onlogon /f'
    else:
        sched_cmd = f'schtasks /create /tn "{name}" /tr "{command}" /sc once /st {trigger.split()[-1]} /f'
    result = subprocess.run(sched_cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip() or result.stderr.strip() or f"Task '{name}' scheduled."

def handle_list_scheduled_tasks(inputs: dict) -> str:
    """List Windows Scheduled Tasks, optionally filtered."""
    if sys.platform != "win32":
        return "Error: Windows only."
    filter_name = inputs.get("filter", "").strip()
    cmd = f'schtasks /query /fo list{f" /tn \"{filter_name}\"" if filter_name else ""}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.stdout.strip()[:3000] or "No tasks found."


# ── 7. Power management ───────────────────────────────────────────────────────

def handle_power_action(inputs: dict) -> str:
    """Lock, sleep, restart, or shutdown. All require confirmation."""
    action = inputs.get("action","").strip().lower()
    delay  = int(inputs.get("delay_seconds", 0))
    cmds = {
        "lock":     "rundll32.exe user32.dll,LockWorkStation",
        "sleep":    "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
        "restart":  f"shutdown /r /t {delay}",
        "shutdown": f"shutdown /s /t {delay}",
        "cancel":   "shutdown /a",
    }
    if action not in cmds:
        return f"Error: action must be one of {list(cmds.keys())}."
    result = subprocess.run(cmds[action], shell=True, capture_output=True, text=True)
    return f"{action.capitalize()} command sent." if result.returncode == 0 else result.stderr


# ── 8. Volume control ─────────────────────────────────────────────────────────

def handle_set_volume(inputs: dict) -> str:
    """Set system volume 0-100."""
    level = inputs.get("level")
    if level is None:
        return "Error: 'level' (0-100) is required."
    level = max(0, min(100, int(level)))
    if sys.platform == "win32":
        # Fallback: nircmd
        nircmd = shutil.which("nircmd")
        if nircmd:
            result = subprocess.run(f'nircmd setsysvolume {int(level * 655.35)}',
                                    shell=True, capture_output=True)
            return f"Volume set to {level}%"
        return f"Volume control requires nircmd. Download from https://www.nirsoft.net/utils/nircmd.html"
    else:
        result = subprocess.run(f"amixer sset Master {level}%", shell=True, capture_output=True)
        return f"Volume set to {level}%" if result.returncode == 0 else result.stderr.decode()


# ── Tool registry entries ─────────────────────────────────────────────────────

SYSTEM_TOOLS = [
    {
        "name": "run_command",
        "description": (
            "Run a shell command on the system and return its output. "
            "Use for anything that needs the OS: PowerShell, CMD, bash. "
            "Examples: 'Get-Date', 'ipconfig', 'ls -la', 'Get-Process'. "
            "Destructive commands (delete, format, shutdown) require confirmation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command":           {"type":"string", "description":"The command to run."},
                "shell":             {"type":"string", "description":"'powershell' (default), 'cmd', or 'bash'"},
                "timeout_seconds":   {"type":"integer","description":"Max seconds to wait (default 30)"},
                "working_directory": {"type":"string", "description":"Directory to run in (optional)"},
            },
            "required": ["command"],
        },
        "handler":              handle_run_command,
        "requires_confirmation": False,
    },
    {
        "name": "run_script",
        "description": (
            "Write and execute a multi-line script. "
            "Use for automation that needs more than one command: "
            "PowerShell scripts, Python snippets, batch files. "
            "Always requires confirmation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "code":             {"type":"string", "description":"The full script code."},
                "language":         {"type":"string", "description":"'powershell' (default), 'python', 'batch', 'bash'"},
                "timeout_seconds":  {"type":"integer","description":"Max seconds (default 60)"},
            },
            "required": ["code"],
        },
        "handler":              handle_run_script,
        "requires_confirmation": True,
    },
    {
        "name": "list_processes",
        "description": "List running processes. Optionally filter by name. Shows PID, CPU%, memory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter": {"type":"string","description":"Optional name filter (case-insensitive)"},
            },
            "required": [],
        },
        "handler":              handle_list_processes,
        "requires_confirmation": False,
    },
    {
        "name": "kill_process",
        "description": "Terminate a running process by PID or name. Requires confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pid":  {"type":"integer","description":"Process ID to kill"},
                "name": {"type":"string", "description":"Process name to kill (kills all matching)"},
            },
            "required": [],
        },
        "handler":              handle_kill_process,
        "requires_confirmation": True,
    },
    {
        "name": "start_app",
        "description": "Launch an application. Provide the exe path or app name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "app":  {"type":"string","description":"App path or name, e.g. 'notepad.exe' or 'C:/Apps/app.exe'"},
                "args": {"type":"string","description":"Optional command-line arguments"},
            },
            "required": ["app"],
        },
        "handler":              handle_start_app,
        "requires_confirmation": False,
    },
    {
        "name": "clipboard_read",
        "description": "Read the current contents of the clipboard.",
        "input_schema": {"type":"object","properties":{},"required":[]},
        "handler":              handle_clipboard_read,
        "requires_confirmation": False,
    },
    {
        "name": "clipboard_write",
        "description": "Write text to the clipboard.",
        "input_schema": {
            "type":"object",
            "properties": {"text":{"type":"string","description":"Text to copy to clipboard"}},
            "required": ["text"],
        },
        "handler":              handle_clipboard_write,
        "requires_confirmation": False,
    },
    {
        "name": "type_text",
        "description": "Type text as keyboard input into the currently focused window.",
        "input_schema": {
            "type":"object",
            "properties": {
                "text":     {"type":"string", "description":"Text to type"},
                "interval": {"type":"number","description":"Seconds between keystrokes (default 0.05)"},
            },
            "required": ["text"],
        },
        "handler":              handle_type_text,
        "requires_confirmation": True,
    },
    {
        "name": "hotkey",
        "description": "Press a keyboard shortcut. Examples: 'ctrl+c', 'alt+f4', 'win+d', 'ctrl+shift+esc'.",
        "input_schema": {
            "type":"object",
            "properties": {"keys":{"type":"string","description":"Keys joined by '+', e.g. 'ctrl+alt+del'"}},
            "required": ["keys"],
        },
        "handler":              handle_hotkey,
        "requires_confirmation": False,
    },
    {
        "name": "mouse_click",
        "description": "Click the mouse at specific screen coordinates.",
        "input_schema": {
            "type":"object",
            "properties": {
                "x":       {"type":"integer","description":"X screen coordinate"},
                "y":       {"type":"integer","description":"Y screen coordinate"},
                "button":  {"type":"string", "description":"'left' (default), 'right', 'middle'"},
                "clicks":  {"type":"integer","description":"Number of clicks (default 1)"},
            },
            "required": ["x","y"],
        },
        "handler":              handle_mouse_click,
        "requires_confirmation": True,
    },
    {
        "name": "screenshot",
        "description": "Take a screenshot of the entire screen. Returns the saved file path.",
        "input_schema": {
            "type":"object",
            "properties": {"path":{"type":"string","description":"Optional save path (auto-named if omitted)"}},
            "required": [],
        },
        "handler":              handle_screenshot,
        "requires_confirmation": False,
    },
    {
        "name": "schedule_task",
        "description": (
            "Create a Windows Scheduled Task to run something automatically. "
            "trigger: 'daily HH:MM' | 'onlogon' | 'once YYYY-MM-DD HH:MM'"
        ),
        "input_schema": {
            "type":"object",
            "properties": {
                "name":    {"type":"string","description":"Task name"},
                "command": {"type":"string","description":"Command or script to run"},
                "trigger": {"type":"string","description":"When to run: 'daily 09:00', 'onlogon', etc."},
            },
            "required": ["name","command"],
        },
        "handler":              handle_schedule_task,
        "requires_confirmation": True,
    },
    {
        "name": "power_action",
        "description": "Lock, sleep, restart, or shutdown the computer. ALWAYS requires confirmation.",
        "input_schema": {
            "type":"object",
            "properties": {
                "action":         {"type":"string","description":"'lock','sleep','restart','shutdown','cancel'"},
                "delay_seconds":  {"type":"integer","description":"Delay before restart/shutdown (default 0)"},
            },
            "required": ["action"],
        },
        "handler":              handle_power_action,
        "requires_confirmation": True,
    },
    {
        "name": "set_volume",
        "description": "Set system volume 0-100.",
        "input_schema": {
            "type":"object",
            "properties": {"level":{"type":"integer","description":"Volume level 0-100"}},
            "required": ["level"],
        },
        "handler":              handle_set_volume,
        "requires_confirmation": False,
    },
]
