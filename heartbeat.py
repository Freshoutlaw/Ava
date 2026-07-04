"""
Ava — heartbeat.py  (updated: Tiers 5, 12, 13, 19)
----------------------------------------------------
Background loop that runs all registered checks:
  Base:       goal nudge, daily brief
  Tier 12:    preference update, tool health
  Tier 12:    weekly plan, goal progress
  Tier 13:    gap detection, install approved tools
  Tier 19:    workflow scheduler
"""

import json, threading, time
from datetime import datetime, date
from pathlib import Path

DATA_DIR     = Path(__file__).parent / "data"
CONFIG_FILE  = Path(__file__).parent / "config.json"
NOTICES_FILE = DATA_DIR / "heartbeat_notices.json"
STATE_FILE   = DATA_DIR / "heartbeat_state.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

HEARTBEAT_KILL = threading.Event()

_notice_queue: list[dict] = []
_queue_lock   = threading.Lock()
_check_locks: dict[str, threading.Lock] = {}


# ── Config ────────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _hb_config() -> dict:
    return _load_config().get("heartbeat", {})

def _in_quiet_hours() -> bool:
    cfg   = _hb_config()
    start = cfg.get("quiet_hours_start", "22:00")
    end   = cfg.get("quiet_hours_end",   "07:00")
    now   = datetime.now().strftime("%H:%M")
    if start <= end:
        return start <= now < end
    return now >= start or now < end


# ── State (schedule survives restarts) ───────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def _next_due(check_id: str, interval_minutes: int) -> float:
    state = _load_state()
    last  = state.get(check_id, {}).get("last_run", 0)
    return last + interval_minutes * 60

def _mark_ran(check_id: str):
    state = _load_state()
    state.setdefault(check_id, {})["last_run"] = time.time()
    _save_state(state)


# ── Notice management ─────────────────────────────────────────────────────────

def _load_persisted_notices() -> list[dict]:
    if NOTICES_FILE.exists():
        try:
            return json.loads(NOTICES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

def _persist_notices(notices: list[dict]):
    try:
        NOTICES_FILE.write_text(json.dumps(notices, indent=2), encoding="utf-8")
    except PermissionError:
        pass  # file locked by another thread — skip this cycle

def push_notice(notice_id: str, label: str, message: str, priority: str = "low"):
    notice = {
        "id":        notice_id,
        "label":     label,
        "message":   message,
        "priority":  priority,
        "ts":        datetime.now().strftime("%Y-%m-%d %H:%M"),
        "dismissed": False,
    }
    with _queue_lock:
        _notice_queue.append(notice)
    persisted = _load_persisted_notices()
    persisted.append(notice)
    _persist_notices(persisted)

def drain_notices() -> list[dict]:
    persisted = [n for n in _load_persisted_notices() if not n.get("dismissed")]
    with _queue_lock:
        queue_ids = {n["id"] for n in _notice_queue}
        for n in persisted:
            if n["id"] not in queue_ids:
                _notice_queue.append(n)
        result = [n for n in _notice_queue if not n.get("dismissed")]
        _notice_queue.clear()
    all_p = _load_persisted_notices()
    for n in all_p:
        n["dismissed"] = True
    _persist_notices(all_p)
    return result

def dismiss_notice(notice_id: str):
    with _queue_lock:
        for n in _notice_queue:
            if n["id"] == notice_id:
                n["dismissed"] = True
    persisted = _load_persisted_notices()
    for n in persisted:
        if n["id"] == notice_id:
            n["dismissed"] = True
    _persist_notices(persisted)


# ── Base checks ───────────────────────────────────────────────────────────────

def _check_goal_nudge() -> bool:
    try:
        goal_file = DATA_DIR / "goal.json"
        if not goal_file.exists():
            return False
        goal  = json.loads(goal_file.read_text(encoding="utf-8"))
        today = date.today().isoformat()
        entries_today = [e for e in goal.get("entries", []) if e.get("date") == today]
        if not entries_today and datetime.now().weekday() < 5:
            pct = round((goal["current"] / goal["target"]) * 100, 1) if goal["target"] else 0
            push_notice(
                notice_id=f"goal_nudge_{today}",
                label="Revenue goal",
                message=(f"No revenue logged today. You're at {pct}% "
                         f"(${goal['current']:,.0f} of ${goal['target']:,.0f})."),
                priority="low",
            )
            return True
    except Exception:
        pass
    return False

def _check_daily_brief() -> bool:
    try:
        today = date.today().isoformat()
        state = _load_state()
        if state.get("daily_brief", {}).get("last_date") == today:
            return False
        hour = datetime.now().hour
        if 7 <= hour < 11:
            push_notice(
                notice_id=f"daily_brief_{today}",
                label="Daily brief",
                message="Good morning. Want a quick brief — goal status, notes, and top priority for today?",
                priority="medium",
            )
            state.setdefault("daily_brief", {})["last_date"] = today
            _save_state(state)
            return True
    except Exception:
        pass
    return False


# ── Build full check list ─────────────────────────────────────────────────────

def _build_checks() -> list[dict]:
    checks = [
        {"id": "goal_nudge",  "label": "Revenue goal nudge", "interval_minutes": 120, "fn": _check_goal_nudge},
        {"id": "daily_brief", "label": "Daily briefing",     "interval_minutes": 480, "fn": _check_daily_brief},
    ]

    # Tier 12: adaptive learning
    try:
        from learning import register_learning_checks
        checks.extend(register_learning_checks())
    except Exception:
        pass

    # Tier 12: autonomous goal pursuit
    try:
        from goals import register_goal_checks
        checks.extend(register_goal_checks())
    except Exception:
        pass

    # Tier 13: self-evolution
    try:
        from evolution import register_evolution_checks
        checks.extend(register_evolution_checks())
    except Exception:
        pass

    # Tier 19: workflow scheduler
    try:
        from automation.workflows import register_workflow_checks
        checks.extend(register_workflow_checks())
    except Exception:
        pass

    return checks

def _get_interval(check_id: str, default_minutes: int) -> int:
    cfg_checks = _hb_config().get("checks", [])
    for c in cfg_checks:
        if c.get("id") == check_id:
            if not c.get("enabled", True):
                return -1
            return c.get("interval_minutes", default_minutes)
    return default_minutes


# ── Main loop ─────────────────────────────────────────────────────────────────

def _heartbeat_loop():
    print("[heartbeat] Background loop started.")
    checks = _build_checks()
    while not HEARTBEAT_KILL.is_set():
        poll_seconds = _hb_config().get("poll_interval_seconds", 60)
        if not HEARTBEAT_KILL.is_set() and not _in_quiet_hours():
            for check in checks:
                cid      = check["id"]
                interval = _get_interval(cid, check["interval_minutes"])
                if interval < 0:
                    continue
                if time.time() < _next_due(cid, interval):
                    continue
                lock = _check_locks.setdefault(cid, threading.Lock())
                if not lock.acquire(blocking=False):
                    continue
                try:
                    check["fn"]()
                    _mark_ran(cid)
                except Exception as e:
                    print(f"[heartbeat] Check '{cid}' error: {e}")
                finally:
                    lock.release()
        HEARTBEAT_KILL.wait(timeout=poll_seconds)
    print("[heartbeat] Loop stopped.")

def start_heartbeat() -> threading.Thread:
    t = threading.Thread(target=_heartbeat_loop, name="ava-heartbeat", daemon=True)
    t.start()
    return t

def stop_heartbeat():
    HEARTBEAT_KILL.set()

def heartbeat_is_running() -> bool:
    return not HEARTBEAT_KILL.is_set()




