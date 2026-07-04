"""
Ava — deploy.py  (Tier 11: Cloud/Server Deployment)
-----------------------------------------------------
Commands:
  python deploy.py package       — bundle Ava into a deployable zip
  python deploy.py systemd       — print Linux systemd service file
  python deploy.py winservice    — install as Windows Service via NSSM
  python deploy.py ssh-tunnel    — tunnel remote Ava WebSocket to local
  python deploy.py health        — health check a running Ava instance
  python deploy.py push <host>   — rsync to remote server and restart

Add to .env:
  DEPLOY_HOST=user@your-vps.com
  DEPLOY_PATH=/home/user/ava
  DEPLOY_PORT=22
  AVA_REMOTE_WS_PORT=7334
  AVA_REMOTE_HTTP_PORT=7333
"""

import json, os, subprocess, sys, zipfile, urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent

def _env(key, default=""):
    try:
        from dotenv import dotenv_values
        return dotenv_values(ROOT / ".env").get(key, os.environ.get(key, default))
    except Exception:
        return os.environ.get(key, default)

def _run(cmd, check=True):
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)

EXCLUDE = {"__pycache__", ".git", ".qodo", "output.wav", ".env", "*.pyc"}

def cmd_package():
    out = ROOT / f"ava_deploy_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    print(f"[deploy] Packaging → {out.name}")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in ROOT.rglob("*"):
            if p.is_file() and not any(e.strip("*. ") in str(p) for e in EXCLUDE):
                zf.write(p, p.relative_to(ROOT))
    print(f"[deploy] Done — {out.stat().st_size//1024} KB")

def cmd_systemd():
    path   = _env("DEPLOY_PATH", "/home/ubuntu/ava")
    python = f"{path}/venv/bin/python"
    unit = f"""[Unit]
Description=Ava AI Executive Assistant
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory={path}
ExecStart={python} {path}/ava.py --headless --web-ui
Restart=always
RestartSec=5
EnvironmentFile={path}/.env
StandardOutput=append:{path}/data/ava.log
StandardError=append:{path}/data/ava_err.log

[Install]
WantedBy=multi-user.target
"""
    print(unit)
    print("Save as /etc/systemd/system/ava.service")
    print("sudo systemctl enable ava && sudo systemctl start ava")

def cmd_winservice():
    svc = "AvaAssistant"
    try:
        subprocess.run(["nssm","version"], capture_output=True, check=True)
    except Exception:
        print("[deploy] Install NSSM first: https://nssm.cc/download"); return
    for cmd in [
        ["nssm","install", svc, sys.executable, f'"{ROOT/"ava.py"}" --headless --web-ui'],
        ["nssm","set", svc, "AppDirectory", str(ROOT)],
        ["nssm","set", svc, "Start", "SERVICE_AUTO_START"],
        ["nssm","start", svc],
    ]:
        _run(cmd, check=False)
    print(f"[deploy] Service '{svc}' installed.")

def cmd_ssh_tunnel():
    host = _env("DEPLOY_HOST")
    if not host: print("[deploy] Set DEPLOY_HOST in .env"); return
    cmd = ["ssh","-N","-L","7333:localhost:7333","-L","7334:localhost:7334",
           "-p", _env("DEPLOY_PORT","22"), host]
    print(f"[deploy] Tunnel open to {host} — Ctrl-C to close")
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\n[deploy] Tunnel closed.")

def cmd_health():
    host = _env("DEPLOY_HOST","127.0.0.1").split("@")[-1]
    url  = f"http://{host}:{_env('AVA_REMOTE_HTTP_PORT','7333')}/"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            print(f"[deploy] ✓ Ava alive — HTTP {r.status}")
    except Exception as e:
        print(f"[deploy] ✗ Unreachable: {e}")

def cmd_push():
    host = _env("DEPLOY_HOST")
    path = _env("DEPLOY_PATH", "/home/ubuntu/ava")
    port = _env("DEPLOY_PORT", "22")
    if not host: print("[deploy] Set DEPLOY_HOST in .env"); return
    _run(["rsync","-avz","--delete",
          "--exclude=.env","--exclude=__pycache__","--exclude=*.pyc",
          "--exclude=.git","--exclude=data/","--exclude=output.wav",
          "-e", f"ssh -p {port}", f"{ROOT}/", f"{host}:{path}/"])
    _run(["ssh","-p",port,host,
          f"cd {path} && pip install -q -r requirements.txt && "
          "sudo systemctl restart ava || true"], check=False)
    print("[deploy] Push complete.")

COMMANDS = {
    "package":cmd_package,"systemd":cmd_systemd,"winservice":cmd_winservice,
    "ssh-tunnel":cmd_ssh_tunnel,"health":cmd_health,"push":cmd_push,
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    fn  = COMMANDS.get(cmd)
    if fn: fn()
    else:  print(f"Usage: python deploy.py [{' | '.join(COMMANDS)}]")
