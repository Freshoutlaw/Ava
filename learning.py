"""
Ava — learning.py  (Tier 12: Adaptive Learning)
-------------------------------------------------
Ava tracks every interaction, scores her own responses, detects your
patterns, builds a preference model, and feeds it into the system prompt.

What this does:
  1. Interaction logger    — every turn stored with timestamp, class, latency
  2. Response scorer       — Ava rates her own replies on clarity + helpfulness
  3. Pattern detector      — finds: peak hours, frequent topics, preferred reply length
  4. Preference model      — builds a live profile injected into system prompt
  5. Tool accuracy tracker — which tools get called for which inputs; flags misfires
"""

import json, os, time, threading
from datetime import datetime, date
from pathlib import Path
from collections import Counter, defaultdict

ROOT      = Path(__file__).parent
DATA_DIR  = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

LOG_FILE   = DATA_DIR / "interaction_log.jsonl"
PREFS_FILE = DATA_DIR / "preference_model.json"


# ── 1. Interaction logger ─────────────────────────────────────────────────────

def log_interaction(user_input: str, reply: str, turn_class: str,
                    tools_called: list[str], latency_ms: float,
                    voice: bool = False, satisfaction: str = "unknown"):
    entry = {
        "ts":         datetime.now().isoformat(),
        "hour":       datetime.now().hour,
        "weekday":    datetime.now().weekday(),
        "class":      turn_class,
        "voice":      voice,
        "input_len":  len(user_input),
        "reply_len":  len(reply),
        "tools":      tools_called,
        "latency_ms": round(latency_ms),
        "satisfaction": satisfaction,
        "input_preview":  user_input[:80],
        "reply_preview":  reply[:80],
    }
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ── 2. Response self-scorer ───────────────────────────────────────────────────

def score_response(user_input: str, reply: str, turn_class: str) -> dict:
    """
    Ava scores her own reply using the fast model.
    Returns {"clarity": 1-5, "helpfulness": 1-5, "brevity": 1-5, "overall": 1-5}
    Only fires for non-SIMPLE turns to save tokens.
    """
    if turn_class == "SIMPLE" or len(reply) < 50:
        return {"clarity": 5, "helpfulness": 5, "brevity": 5, "overall": 5}
    try:
        from groq import Groq
        key = os.environ.get("GROQ_API_KEY", "").strip()
        if not key: return {}
        client = Groq(api_key=key)
        resp   = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            max_tokens=60,
            messages=[
                {"role": "system", "content": (
                    "Rate this AI reply on 4 dimensions from 1-5. "
                    "Reply ONLY with compact JSON: "
                    '{"clarity":N,"helpfulness":N,"brevity":N,"overall":N}'
                )},
                {"role": "user", "content":
                    f"User asked: {user_input[:200]}\n\nReply: {reply[:400]}"},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        # strip markdown fences if present
        text = text.replace("```json","").replace("```","").strip()
        return json.loads(text)
    except Exception:
        return {}


# ── 3. Pattern detector ───────────────────────────────────────────────────────

def _load_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    entries = []
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line.strip()))
            except Exception:
                pass
    return entries


def detect_patterns() -> dict:
    """
    Analyse interaction log and return a pattern summary dict.
    """
    entries = _load_log()
    if not entries:
        return {}

    hour_counts  = Counter(e["hour"] for e in entries)
    class_counts = Counter(e["class"] for e in entries)
    tool_counts  = Counter(t for e in entries for t in e.get("tools", []))
    voice_count  = sum(1 for e in entries if e.get("voice"))
    avg_reply    = sum(e["reply_len"] for e in entries) / len(entries)
    avg_latency  = sum(e["latency_ms"] for e in entries) / len(entries)

    # Peak working hour
    peak_hour    = hour_counts.most_common(1)[0][0] if hour_counts else 9
    top_class    = class_counts.most_common(1)[0][0] if class_counts else "SIMPLE"
    top_tools    = [t for t, _ in tool_counts.most_common(3)]

    # Preferred reply length based on actual usage
    if avg_reply < 150:
        reply_pref = "very brief"
    elif avg_reply < 400:
        reply_pref = "concise"
    elif avg_reply < 800:
        reply_pref = "moderate"
    else:
        reply_pref = "detailed"

    return {
        "total_turns":     len(entries),
        "peak_hour":       peak_hour,
        "top_turn_class":  top_class,
        "top_tools":       top_tools,
        "voice_pct":       round(voice_count / len(entries) * 100),
        "avg_reply_len":   round(avg_reply),
        "avg_latency_ms":  round(avg_latency),
        "reply_preference": reply_pref,
    }


# ── 4. Preference model ───────────────────────────────────────────────────────

def _load_prefs() -> dict:
    if PREFS_FILE.exists():
        try:
            return json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "reply_length":    "concise",
        "tone":            "warm and plain-spoken",
        "peak_hour":       9,
        "top_topics":      [],
        "voice_preferred": False,
        "last_updated":    "",
    }

def _save_prefs(prefs: dict):
    prefs["last_updated"] = datetime.now().isoformat()
    PREFS_FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")

def update_preference_model():
    """
    Rebuild the preference model from the interaction log.
    Called by the heartbeat every few hours.
    """
    patterns = detect_patterns()
    if not patterns:
        return
    prefs = _load_prefs()
    prefs["reply_length"]    = patterns.get("reply_preference", prefs["reply_length"])
    prefs["peak_hour"]       = patterns.get("peak_hour", prefs["peak_hour"])
    prefs["top_topics"]      = patterns.get("top_tools", prefs["top_topics"])
    prefs["voice_preferred"] = patterns.get("voice_pct", 0) > 50
    _save_prefs(prefs)
    return prefs

def preference_context() -> str:
    """
    Return a short string injected into the system prompt each turn.
    Tells Ava how this specific user likes to interact.
    """
    prefs = _load_prefs()
    if not prefs.get("last_updated"):
        return ""
    lines = [
        f"Reply style: {prefs['reply_length']}.",
        f"Tone: {prefs['tone']}.",
    ]
    if prefs.get("voice_preferred"):
        lines.append("User often uses voice — keep spoken answers especially brief.")
    return "Learned preferences: " + "  ".join(lines)


# ── 5. Tool accuracy tracker ──────────────────────────────────────────────────

TOOL_ACCURACY_FILE = DATA_DIR / "tool_accuracy.json"

def _load_accuracy() -> dict:
    if TOOL_ACCURACY_FILE.exists():
        try:
            return json.loads(TOOL_ACCURACY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_accuracy(data: dict):
    TOOL_ACCURACY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def record_tool_call(tool_name: str, succeeded: bool):
    """Record whether a tool call succeeded or failed."""
    data = _load_accuracy()
    if tool_name not in data:
        data[tool_name] = {"calls": 0, "failures": 0}
    data[tool_name]["calls"]    += 1
    if not succeeded:
        data[tool_name]["failures"] += 1
    _save_accuracy(data)

def get_struggling_tools(failure_rate_threshold: float = 0.3) -> list[str]:
    """Return tool names with a failure rate above the threshold."""
    data     = _load_accuracy()
    flagged  = []
    for name, stats in data.items():
        if stats["calls"] >= 3:
            rate = stats["failures"] / stats["calls"]
            if rate >= failure_rate_threshold:
                flagged.append(name)
    return flagged


# ── Heartbeat registration ────────────────────────────────────────────────────

def register_learning_checks():
    """
    Returns heartbeat-compatible check functions for the learning module.
    Called from heartbeat.py _CHECKS list.
    """
    def _check_preference_update() -> bool:
        prefs = _load_prefs()
        last  = prefs.get("last_updated", "")
        # Update preferences every 4 hours
        if last:
            from datetime import datetime
            age = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
            if age < 4 * 3600:
                return False
        update_preference_model()
        return False   # silent — no notice needed

    def _check_struggling_tools() -> bool:
        flagged = get_struggling_tools()
        if flagged:
            from heartbeat import push_notice
            push_notice(
                notice_id=f"tool_struggles_{date.today().isoformat()}",
                label="Tool health",
                message=f"These tools have been failing often: {', '.join(flagged)}. Consider reviewing them.",
                priority="medium",
            )
            return True
        return False

    return [
        {"id": "preference_update", "label": "Update preference model",
         "interval_minutes": 240, "fn": _check_preference_update},
        {"id": "tool_health",       "label": "Tool accuracy check",
         "interval_minutes": 60,   "fn": _check_struggling_tools},
    ]
