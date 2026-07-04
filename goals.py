"""
Ava — goals.py  (Tier 12: Autonomous Goal Pursuit)
----------------------------------------------------
Ava breaks your $500K goal into milestones, tracks them,
assigns herself weekly tasks, and runs them proactively.

Goal hierarchy:
  Annual target ($500K)
    → Monthly milestones (~$41.7K/month)
      → Weekly targets   (~$9.6K/week)
        → Daily actions  (prospecting, outreach, follow-ups)

Ava checks progress weekly, generates a suggested action plan,
and surfaces it as a heartbeat notice.
"""

import json
from datetime import datetime, date, timedelta
from pathlib import Path

ROOT      = Path(__file__).parent
DATA_DIR  = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
GOALS_FILE = DATA_DIR / "autonomous_goals.json"


# ── Goal breakdown ────────────────────────────────────────────────────────────

def _weeks_remaining() -> int:
    today     = date.today()
    year_end  = date(today.year, 12, 31)
    return max(1, (year_end - today).days // 7)

def _days_remaining() -> int:
    today    = date.today()
    year_end = date(today.year, 12, 31)
    return max(1, (year_end - today).days)

def compute_milestones(target: float, current: float) -> dict:
    remaining     = max(0, target - current)
    weeks_left    = _weeks_remaining()
    days_left     = _days_remaining()
    weekly_needed = remaining / weeks_left
    daily_needed  = remaining / days_left
    month_needed  = remaining / max(1, days_left / 30)

    return {
        "target":          target,
        "current":         current,
        "remaining":       remaining,
        "pct_complete":    round((current / target) * 100, 1) if target else 0,
        "days_left":       days_left,
        "weeks_left":      weeks_left,
        "daily_needed":    round(daily_needed, 2),
        "weekly_needed":   round(weekly_needed, 2),
        "monthly_needed":  round(month_needed, 2),
        "on_track":        current >= (target * (1 - days_left / 365)),
        "computed_at":     datetime.now().isoformat(),
    }


# ── Autonomous action plan ────────────────────────────────────────────────────

def generate_action_plan(milestones: dict) -> list[str]:
    """
    Generate concrete weekly actions based on progress.
    Uses Groq to produce personalised recommendations.
    """
    import os
    try:
        from groq import Groq
        key = os.environ.get("GROQ_API_KEY", "").strip()
        if not key:
            return _fallback_plan(milestones)

        client = Groq(api_key=key)
        resp   = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            max_tokens=300,
            messages=[
                {"role": "system", "content": (
                    "You are a business strategy assistant. "
                    "Generate exactly 5 specific, actionable tasks for this week "
                    "to help reach the revenue goal. "
                    "Format as a JSON array of strings. No preamble."
                )},
                {"role": "user", "content": (
                    f"Revenue target: ${milestones['target']:,.0f}\n"
                    f"Current: ${milestones['current']:,.0f} "
                    f"({milestones['pct_complete']}%)\n"
                    f"This week I need: ${milestones['weekly_needed']:,.0f}\n"
                    f"Days remaining: {milestones['days_left']}\n"
                    f"On track: {milestones['on_track']}\n\n"
                    "Generate 5 specific revenue-driving tasks for this week."
                )},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        text = text.replace("```json","").replace("```","").strip()
        tasks = json.loads(text)
        return tasks if isinstance(tasks, list) else _fallback_plan(milestones)
    except Exception:
        return _fallback_plan(milestones)


def _fallback_plan(m: dict) -> list[str]:
    weekly = m["weekly_needed"]
    return [
        f"Identify 10 new prospects and add to outreach list",
        f"Follow up on all leads older than 3 days",
        f"Send at least 5 personalised cold outreach messages",
        f"Schedule 2 discovery calls with warm leads",
        f"Review pipeline and update deal stages — target ${weekly:,.0f} this week",
    ]


# ── Persistent plan storage ───────────────────────────────────────────────────

def _load_goals_state() -> dict:
    if GOALS_FILE.exists():
        try:
            return json.loads(GOALS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"weekly_plan": [], "last_plan_date": "", "history": []}

def _save_goals_state(state: dict):
    GOALS_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def get_current_plan() -> list[str]:
    return _load_goals_state().get("weekly_plan", [])

def refresh_weekly_plan(target: float, current: float) -> list[str]:
    """Generate and store a new weekly action plan."""
    milestones = compute_milestones(target, current)
    plan       = generate_action_plan(milestones)
    state      = _load_goals_state()
    # Archive old plan
    if state["weekly_plan"]:
        state["history"].append({
            "week_of": state["last_plan_date"],
            "plan":    state["weekly_plan"],
        })
        state["history"] = state["history"][-8:]  # keep 8 weeks
    state["weekly_plan"]     = plan
    state["last_plan_date"]  = date.today().isoformat()
    state["last_milestones"] = milestones
    _save_goals_state(state)
    return plan


# ── Heartbeat check ───────────────────────────────────────────────────────────

def register_goal_checks():
    """Returns heartbeat-compatible checks for autonomous goal pursuit."""

    def _check_weekly_plan() -> bool:
        from heartbeat import push_notice
        state    = _load_goals_state()
        last_str = state.get("last_plan_date", "")

        # Refresh plan on Monday or if never generated
        today   = date.today()
        refresh = (today.weekday() == 0) or not last_str
        if not refresh and last_str:
            last = date.fromisoformat(last_str)
            refresh = (today - last).days >= 7

        if not refresh:
            return False

        try:
            goal_file = DATA_DIR / "goal.json"
            if not goal_file.exists():
                return False
            goal    = json.loads(goal_file.read_text(encoding="utf-8"))
            target  = goal["target"]
            current = goal["current"]
            plan    = refresh_weekly_plan(target, current)
            summary = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(plan[:3]))
            push_notice(
                notice_id=f"weekly_plan_{today.isoformat()}",
                label="Weekly action plan",
                message=f"This week's top priorities:\n{summary}\n(and {len(plan)-3} more — ask Ava for the full plan)",
                priority="medium",
            )
            return True
        except Exception:
            return False

    def _check_goal_progress() -> bool:
        from heartbeat import push_notice
        try:
            goal_file = DATA_DIR / "goal.json"
            if not goal_file.exists():
                return False
            goal      = json.loads(goal_file.read_text(encoding="utf-8"))
            m         = compute_milestones(goal["target"], goal["current"])
            today_str = date.today().isoformat()

            if not m["on_track"] and m["pct_complete"] < 95:
                push_notice(
                    notice_id=f"goal_offtrack_{today_str}",
                    label="Goal alert",
                    message=(
                        f"You're at {m['pct_complete']}% (${m['current']:,.0f}). "
                        f"To stay on track you need ${m['daily_needed']:,.0f}/day "
                        f"or ${m['weekly_needed']:,.0f} this week."
                    ),
                    priority="medium",
                )
                return True
        except Exception:
            pass
        return False

    return [
        {"id": "weekly_plan",    "label": "Weekly action plan",
         "interval_minutes": 1440, "fn": _check_weekly_plan},
        {"id": "goal_progress",  "label": "Goal progress check",
         "interval_minutes": 360,  "fn": _check_goal_progress},
    ]
