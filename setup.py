"""
Ava — setup.py  (Tiers 1-20 + React/PyWebView UI)
----------------------------------------------------
Run once after downloading/placing files to organise the project,
verify every tier is present, and check your .env keys.

  python setup.py
"""

import shutil, sys, json, subprocess
from pathlib import Path

ROOT = Path(__file__).parent
OK   = "✓"
WARN = "✗"


# ── Directories ───────────────────────────────────────────────────────────────

DIRS = [
    ROOT / "tools",
    ROOT / "agents",
    ROOT / "automation",
    ROOT / "data",
    ROOT / "data" / "workflows",
    ROOT / "data" / "browser_screenshots",
    ROOT / "ui_react",
    ROOT / "ui_react" / "src",
]

def create_dirs():
    print("Creating directories…")
    for d in DIRS:
        d.mkdir(parents=True, exist_ok=True)
        print(f"  {OK} {d.relative_to(ROOT)}/")


# ── Move flat files into packages ─────────────────────────────────────────────

MOVES = {
    "agents_base.py":           ROOT / "agents"     / "base.py",
    "agents_roster.py":         ROOT / "agents"     / "roster.py",
    "agents_placeholder.py":    None,
    "tools_registry.py":        ROOT / "tools"      / "registry.py",
    "tools_init.py":            None,
    "tools_system.py":          ROOT / "tools"      / "system.py",
    "tools_kali.py":            ROOT / "tools"      / "kali.py",
    "tools_browser.py":         ROOT / "tools"      / "browser.py",
    "tools_comms.py":           ROOT / "tools"      / "comms.py",
    "tools_vision.py":          ROOT / "tools"      / "vision.py",
    "automation_workflows.py":  ROOT / "automation" / "workflows.py",
    "automation_autonomous.py": ROOT / "automation" / "autonomous.py",
    # React UI — flat-named on download, sorted into ui_react/ here
    "reactui_package.json":          ROOT / "ui_react" / "package.json",
    "reactui_vite.config.js":        ROOT / "ui_react" / "vite.config.js",
    "reactui_tailwind.config.js":    ROOT / "ui_react" / "tailwind.config.js",
    "reactui_postcss.config.js":     ROOT / "ui_react" / "postcss.config.js",
    "reactui_index.html":            ROOT / "ui_react" / "index.html",
    "reactui_BUILD_INSTRUCTIONS.md": ROOT / "ui_react" / "BUILD_INSTRUCTIONS.md",
    "reactui_main.jsx":              ROOT / "ui_react" / "src" / "main.jsx",
    "reactui_App.jsx":               ROOT / "ui_react" / "src" / "App.jsx",
    "reactui_indexcss.css":          ROOT / "ui_react" / "src" / "index.css",
}

def move_files():
    print("\nMoving files into packages…")
    moved_any = False
    for src_name, dst in MOVES.items():
        src = ROOT / src_name
        if src.exists():
            moved_any = True
            if dst is None:
                src.unlink()
                print(f"  {OK} Removed: {src_name}")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                print(f"  {OK} {src_name} → {dst.relative_to(ROOT)}")
    if not moved_any:
        print("  (nothing to move — files already in place)")


# ── Package __init__.py files ─────────────────────────────────────────────────

def create_inits():
    print("\nCreating package init files…")

    tools_init = ROOT / "tools" / "__init__.py"
    if not tools_init.exists():
        tools_init.write_text(
            "from .registry   import run_tool as _base_run, TOOL_REGISTRY, _MAP as _BASE_MAP\n"
            "from .web_search import TIER7_TOOLS\n"
            "try:\n    from .system  import SYSTEM_TOOLS\nexcept Exception: SYSTEM_TOOLS=[]\n"
            "try:\n    from .kali    import KALI_TOOLS\nexcept Exception: KALI_TOOLS=[]\n"
            "try:\n    from .browser import BROWSER_TOOLS\nexcept Exception: BROWSER_TOOLS=[]\n"
            "try:\n    from .comms   import COMMS_TOOLS\nexcept Exception: COMMS_TOOLS=[]\n"
            "try:\n    from .vision  import VISION_TOOLS\nexcept Exception: VISION_TOOLS=[]\n"
            "try:\n    from automation.workflows  import WORKFLOW_TOOLS\nexcept Exception: WORKFLOW_TOOLS=[]\n"
            "try:\n    from automation.autonomous import AUTONOMOUS_TOOLS\nexcept Exception: AUTONOMOUS_TOOLS=[]\n\n"
            "_ALL_EXTRA=TIER7_TOOLS+SYSTEM_TOOLS+KALI_TOOLS+BROWSER_TOOLS+COMMS_TOOLS+VISION_TOOLS+WORKFLOW_TOOLS+AUTONOMOUS_TOOLS\n"
            "_ALL_MAP={**_BASE_MAP,**{t['name']:t for t in _ALL_EXTRA}}\n\n"
            "def tools_for_model():\n"
            "    all_t=TOOL_REGISTRY+_ALL_EXTRA\n"
            "    return [{'name':t['name'],'description':t['description'],'input_schema':t['input_schema']} for t in all_t]\n\n"
            "def run_tool(name,inputs):\n"
            "    tool=_ALL_MAP.get(name)\n"
            "    if not tool: return f\"Error: no tool named '{name}'.\",False\n"
            "    try: result=tool['handler'](inputs)\n"
            "    except Exception as e: result=f\"Tool '{name}' failed: {e}\"\n"
            "    return result,tool.get('requires_confirmation',False)\n",
            encoding="utf-8",
        )
        print(f"  {OK} tools/__init__.py")
    else:
        print(f"  {OK} tools/__init__.py (exists)")

    agents_init = ROOT / "agents" / "__init__.py"
    if not agents_init.exists():
        agents_init.write_text(
            "from .base   import SubAgent, AgentBus\nfrom .roster import BUS\n",
            encoding="utf-8",
        )
        print(f"  {OK} agents/__init__.py")
    else:
        print(f"  {OK} agents/__init__.py (exists)")

    auto_init = ROOT / "automation" / "__init__.py"
    if not auto_init.exists():
        auto_init.write_text("# Ava automation package\n", encoding="utf-8")
        print(f"  {OK} automation/__init__.py")
    else:
        print(f"  {OK} automation/__init__.py (exists)")


# ── Fix imports ───────────────────────────────────────────────────────────────

IMPORT_FIXES = {
    ROOT / "ava.py": [
        ("from agents_roster import BUS", "from agents import BUS"),
        ("from tools_registry import",    "from tools.registry import"),
    ],
    ROOT / "agents" / "roster.py": [
        ("from agents_base import", "from .base import"),
    ],
}

def fix_imports():
    print("\nFixing imports…")
    fixed_any = False
    for filepath, replacements in IMPORT_FIXES.items():
        if not filepath.exists():
            continue
        text    = filepath.read_text(encoding="utf-8")
        changed = False
        for old, new in replacements:
            if old in text and old != new:
                text    = text.replace(old, new)
                changed = True
        if changed:
            filepath.write_text(text, encoding="utf-8")
            print(f"  {OK} Fixed: {filepath.relative_to(ROOT)}")
            fixed_any = True
    if not fixed_any:
        print("  (no import fixes needed)")


# ── Tier presence check ───────────────────────────────────────────────────────

TIER_MODULES = {
    "Tier 1-6  core":       ["ava.py", "memory.py", "config.json"],
    "Tier 7    tools":      ["tools/registry.py", "tools/web_search.py"],
    "Tier 8    agents":     ["agents/base.py", "agents/roster.py"],
    "Tier 9    brain":      ["brain.py"],
    "Tier 10   UI":         ["ui_server.py", "ui_pywebview.py", "daemon.py"],
    "Tier 10   React UI":   ["ui_react/package.json", "ui_react/src/App.jsx"],
    "Tier 11   deploy":     ["deploy.py", "Dockerfile", "docker-compose.yml"],
    "Tier 12   learning":   ["learning.py", "goals.py"],
    "Tier 13   evolution":  ["evolution.py"],
    "Tier 14   system":     ["tools/system.py"],
    "Tier 15   kali":       ["tools/kali.py"],
    "Tier 16   browser":    ["tools/browser.py"],
    "Tier 17   comms":      ["tools/comms.py"],
    "Tier 18   vision":     ["tools/vision.py"],
    "Tier 19   workflows":  ["automation/workflows.py"],
    "Tier 20   autonomous": ["automation/autonomous.py"],
}

def check_tiers():
    print("\nTier module check:")
    all_ok = True
    for label, files in TIER_MODULES.items():
        missing = [f for f in files if not (ROOT / f).exists()]
        if missing:
            print(f"  {WARN} {label}: MISSING {missing}")
            all_ok = False
        else:
            print(f"  {OK} {label}")
    return all_ok


# ── .env check ────────────────────────────────────────────────────────────────

def check_env():
    print("\n.env key check:")
    env_file = ROOT / ".env"
    if not env_file.exists():
        print(f"  {WARN} .env not found — create it from .env.example")
        return
    text = env_file.read_text(encoding="utf-8")

    def _has(key: str) -> bool:
        for line in text.splitlines():
            if line.strip().startswith(f"{key}="):
                val = line.split("=", 1)[1].strip()
                return bool(val) and not val.startswith("your_") and len(val) > 4
        return False

    groq_rotation_keys = [f"GROQ_API_KEY_{i}" for i in range(1, 6) if _has(f"GROQ_API_KEY_{i}")]
    if groq_rotation_keys:
        print(f"  {OK} Groq rotation: {len(groq_rotation_keys)} key(s) set ({', '.join(groq_rotation_keys)})")
    elif _has("GROQ_API_KEY"):
        print(f"  {OK} GROQ_API_KEY (single key, no rotation)")
    else:
        print(f"  {WARN} No Groq key found — set GROQ_API_KEY_1 (required to run at all)")

    required = {
        "DEEPGRAM_API_KEY":  "Speech-to-text (Tier 3)",
        "HUME_API_KEY":      "Text-to-speech (Tier 3)",
        "HUME_VOICE_ID":     "TTS voice (Tier 3)",
    }
    optional = {
        "KALI_MODE":           "wsl|ssh|docker (Tier 15)",
        "EMAIL_SMTP_HOST":     "Email send (Tier 17)",
        "TELEGRAM_BOT_TOKEN":  "Telegram bot (Tier 17)",
        "TWILIO_SID":          "SMS via Twilio (Tier 17)",
        "DISCORD_WEBHOOK_URL": "Discord webhook (Tier 17)",
        "WHATSAPP_BRIDGE_URL": "WhatsApp bridge (Tier 17)",
        "DEPLOY_HOST":         "VPS deploy target (Tier 11)",
    }
    for key, desc in required.items():
        print(f"  {OK if _has(key) else WARN} {key} — {desc}")
    for key, desc in optional.items():
        print(f"  {OK if _has(key) else '○'} {key} — {desc}")


# ── React UI build check ──────────────────────────────────────────────────────

def check_react_build():
    print("\nReact UI check:")
    react_dir = ROOT / "ui_react"
    dist_dir  = react_dir / "dist"
    src_app   = react_dir / "src" / "App.jsx"

    if not src_app.exists():
        print(f"  {WARN} ui_react/src/App.jsx not found — React UI source missing.")
        return

    if dist_dir.exists() and (dist_dir / "index.html").exists():
        print(f"  {OK} React build exists at ui_react/dist/ — Ava will use it.")
        return

    print(f"  ○ React UI source found but not built yet.")
    node_ok = shutil.which("node") is not None
    npm_ok  = shutil.which("npm") is not None

    if not node_ok or not npm_ok:
        print(f"  {WARN} Node.js/npm not found in PATH.")
        print(f"      Install from https://nodejs.org, then run:")
        print(f"        cd ui_react && npm install && npm run build")
        return

    answer = input("  Build the React UI now? (y/n): ").strip().lower()
    if answer == "y":
        print("  Running npm install (this can take a minute)…")
        r1 = subprocess.run(["npm", "install"], cwd=str(react_dir), shell=(sys.platform=="win32"))
        if r1.returncode != 0:
            print(f"  {WARN} npm install failed. Run it manually in ui_react/.")
            return
        print("  Running npm run build…")
        r2 = subprocess.run(["npm", "run", "build"], cwd=str(react_dir), shell=(sys.platform=="win32"))
        if r2.returncode == 0 and (dist_dir / "index.html").exists():
            print(f"  {OK} React UI built successfully → ui_react/dist/")
        else:
            print(f"  {WARN} Build failed — check the npm output above.")
    else:
        print(f"  Skipped. Run later:  cd ui_react && npm install && npm run build")


# ── Requirements reminder ─────────────────────────────────────────────────────

def print_requirements():
    print("""
pip install commands by tier:

  # Core (always)
  pip install groq python-dotenv requests

  # Tier 3 — voice
  pip install sounddevice deepgram-sdk miniaudio numpy

  # Tier 10 — UI (native React window)
  pip install websockets pywebview
  # tkinter ships with Python (automatic fallback)

  # Tier 14 — system automation
  pip install psutil pyautogui pyperclip Pillow

  # Tier 15 — Kali (WSL2 recommended on Windows)
  wsl --install -d kali-linux             # PowerShell as admin
  # OR set KALI_MODE=ssh / KALI_MODE=docker in .env

  # Tier 16 — browser automation
  pip install playwright
  playwright install chromium

  # Tier 17 — comms
  pip install twilio
  # Email uses stdlib smtplib/imaplib
  # WhatsApp: cd whatsapp_bridge && npm install && node server.js

  # Tier 18 — vision (screen + webcam + OCR)
  pip install pytesseract PyMuPDF opencv-python
  # Windows: install Tesseract from https://github.com/UB-Mannheim/tesseract/wiki

  # Daemon (Windows background service)
  pip install pywin32

  # React UI (one-time)
  # Install Node.js from https://nodejs.org, then:
  cd ui_react && npm install && npm run build
""")


# ── Structure summary ─────────────────────────────────────────────────────────

def print_structure():
    print("""
Final project structure (Tiers 1-20 + React UI):
  Ava/
  ├── ava.py                  main entry point (all tiers wired in)
  ├── brain.py                Tier 9:  intelligence layer
  ├── memory.py               Tier 4:  persistent memory
  ├── heartbeat.py            Tier 5:  background checks (all tiers)
  ├── learning.py             Tier 12: adaptive learning
  ├── goals.py                Tier 12: autonomous goal pursuit
  ├── evolution.py            Tier 13: self-evolution
  ├── deploy.py               Tier 11: cloud deployment
  ├── daemon.py                Tier 10: Windows background service
  ├── ui_server.py             Tier 10: HTTP + WebSocket bridge (serves React build)
  ├── ui_pywebview.py          Tier 10: native window wrapper (React UI)
  ├── ui_desktop.py            Tier 10: tkinter fallback if pywebview missing
  ├── Dockerfile               Tier 11: container
  ├── docker-compose.yml       Tier 11: compose
  ├── config.json              all settings
  ├── setup.py                 this file
  ├── .env                     secrets
  ├── tools/
  │   ├── __init__.py          unified run_tool + tools_for_model
  │   ├── registry.py          Tier 2:  base tools
  │   ├── web_search.py        Tier 7:  web + file + calculator
  │   ├── system.py            Tier 14: system automation
  │   ├── kali.py               Tier 15: Kali Linux
  │   ├── browser.py            Tier 16: browser automation
  │   ├── comms.py               Tier 17: email/telegram/sms/whatsapp
  │   └── vision.py              Tier 18: vision + OCR + webcam + computer-use
  ├── agents/
  │   ├── __init__.py
  │   ├── base.py               SubAgent + AgentBus
  │   └── roster.py              researcher, writer, coder
  ├── automation/
  │   ├── __init__.py
  │   ├── workflows.py           Tier 19: workflow orchestrator
  │   └── autonomous.py          Tier 20: autonomous agent loop
  ├── ui_react/                  React desktop interface source
  │   ├── package.json
  │   ├── vite.config.js
  │   ├── tailwind.config.js
  │   ├── index.html
  │   ├── src/
  │   │   ├── main.jsx
  │   │   ├── App.jsx
  │   │   └── index.css
  │   └── dist/                  built output (after npm run build)
  └── data/                      all runtime data (auto-created)

Run:
  python ava.py                   full app — native React window
  python ava.py --no-ui           terminal only
  python ava.py --web-ui          + browser dashboard (uses same React build)
  python ava.py --headless        server/daemon mode
  python daemon.py start          Windows background service
  python deploy.py push           rsync to VPS
""")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 58)
    print("  Ava Setup — Tiers 1-20 + React UI")
    print("=" * 58)
    create_dirs()
    move_files()
    create_inits()
    fix_imports()
    all_ok = check_tiers()
    check_env()
    check_react_build()
    print_requirements()
    print()
    if all_ok:
        print(f"{OK} All tiers present. Run:  python ava.py")
    else:
        print(f"{WARN} Some modules missing — download them and place in the correct folder.")
        print("     Then run setup.py again.")
    print_structure()

if __name__ == "__main__":
    main()
