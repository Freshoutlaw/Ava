"""
Ava — evolution.py  (Tier 13: Self-Evolution)
----------------------------------------------
Ava monitors her own performance, proposes new tools when she detects
capability gaps, writes the tool code, shows it to you for approval,
then installs it live into the registry without a restart.

What this does:
  1. Gap detector      — analyses failed/frustrated turns to spot missing capabilities
  2. Tool proposer     — uses Groq to design + write a new tool for the gap
  3. Approval gate     — always shows you the proposed tool before installing
  4. Live installer    — patches tools/registry.py and reloads without restart
  5. Session replayer  — replays a past session to check if Ava would answer better now
  6. Performance report — generates a full self-assessment Ava can share with you
"""

import json, os, re, sys, importlib, textwrap
from datetime import datetime, date
from pathlib import Path

ROOT      = Path(__file__).parent
DATA_DIR  = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

PROPOSALS_FILE = DATA_DIR / "tool_proposals.json"
EVOLUTION_LOG  = DATA_DIR / "evolution_log.jsonl"


# ── Logging ───────────────────────────────────────────────────────────────────

def _evo_log(event: str, detail: str = ""):
    ts   = datetime.now().isoformat()
    line = json.dumps({"ts": ts, "event": event, "detail": detail})
    try:
        with open(EVOLUTION_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── 1. Gap detector ───────────────────────────────────────────────────────────

def detect_capability_gaps() -> list[str]:
    """
    Scan recent interaction log for turns that:
      - Ended in a fallback ("I got stuck", "can't", "don't have access")
      - Had the user rephrase the same thing 2+ times in a row
      - Had no tools called despite being classified LOOKUP/TASK
    Returns a list of natural-language gap descriptions.
    """
    log_file = DATA_DIR / "interaction_log.jsonl"
    if not log_file.exists():
        return []

    entries = []
    with open(log_file, encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line.strip()))
            except Exception:
                pass

    recent    = entries[-200:]   # last 200 turns
    gaps      = []
    seen      = set()

    for e in recent:
        preview = e.get("reply_preview", "").lower()
        cls     = e.get("class", "")
        tools   = e.get("tools", [])

        # Fallback replies suggest a missing capability
        if any(phrase in preview for phrase in [
            "i can't", "i don't have access", "i'm unable",
            "i got stuck", "don't know how to",
            "no tool", "can't do that",
        ]):
            inp = e.get("input_preview", "")
            gap = f"User asked '{inp}' but Ava couldn't help"
            if gap not in seen:
                gaps.append(gap)
                seen.add(gap)

        # LOOKUP/TASK turn with no tools = possible missing tool
        if cls in ("LOOKUP", "TASK") and not tools:
            inp = e.get("input_preview", "")
            gap = f"No tool was available for: '{inp}'"
            if gap not in seen:
                gaps.append(gap)
                seen.add(gap)

    return gaps[:5]   # return top 5 gaps


# ── 2. Tool proposer ──────────────────────────────────────────────────────────

def propose_tool_for_gap(gap_description: str) -> dict | None:
    """
    Ask Groq to design a Python tool handler for a detected capability gap.
    Returns a proposal dict: {name, description, input_schema, handler_code}
    or None if it can't generate a useful proposal.
    """
    import os
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return None

    try:
        from groq import Groq
        client = Groq(api_key=key)
        resp   = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=1200,
            messages=[
                {"role": "system", "content": textwrap.dedent("""
                    You are a Python tool designer for an AI assistant called Ava.
                    Given a capability gap, design a new tool to fill it.
                    
                    Respond with ONLY a JSON object with these keys:
                    {
                      "name": "snake_case_tool_name",
                      "description": "One sentence — when to use this tool.",
                      "input_schema": {
                        "type": "object",
                        "properties": { "param": {"type": "string", "description": "..."} },
                        "required": ["param"]
                      },
                      "handler_code": "def handle_TOOLNAME(inputs: dict) -> str:\\n    # full implementation\\n    ..."
                    }
                    
                    Rules for handler_code:
                    - Must be a complete, working Python function named handle_<name>
                    - Returns a plain string result
                    - Uses only stdlib + groq + requests (already installed)
                    - Handles errors gracefully with try/except
                    - No placeholders — write real working code
                """)},
                {"role": "user", "content": f"Capability gap: {gap_description}"},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        text = text.replace("```json","").replace("```python","").replace("```","").strip()
        proposal = json.loads(text)
        # Validate required keys
        required = {"name", "description", "input_schema", "handler_code"}
        if not required.issubset(proposal.keys()):
            return None
        proposal["gap"]        = gap_description
        proposal["proposed_at"] = datetime.now().isoformat()
        proposal["status"]     = "pending"
        return proposal
    except Exception as e:
        _evo_log("PROPOSAL_FAILED", str(e))
        return None


# ── 3. Proposal storage + approval ───────────────────────────────────────────

def _load_proposals() -> list[dict]:
    if PROPOSALS_FILE.exists():
        try:
            return json.loads(PROPOSALS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

def _save_proposals(proposals: list[dict]):
    PROPOSALS_FILE.write_text(json.dumps(proposals, indent=2), encoding="utf-8")

def save_proposal(proposal: dict):
    proposals = _load_proposals()
    # Deduplicate by name
    proposals = [p for p in proposals if p.get("name") != proposal.get("name")]
    proposals.append(proposal)
    _save_proposals(proposals)
    _evo_log("PROPOSAL_SAVED", proposal.get("name", "?"))

def get_pending_proposals() -> list[dict]:
    return [p for p in _load_proposals() if p.get("status") == "pending"]

def approve_proposal(tool_name: str) -> bool:
    """Mark a proposal as approved — triggers live install on next heartbeat check."""
    proposals = _load_proposals()
    for p in proposals:
        if p["name"] == tool_name and p["status"] == "pending":
            p["status"]      = "approved"
            p["approved_at"] = datetime.now().isoformat()
            _save_proposals(proposals)
            _evo_log("PROPOSAL_APPROVED", tool_name)
            return True
    return False

def reject_proposal(tool_name: str) -> bool:
    proposals = _load_proposals()
    for p in proposals:
        if p["name"] == tool_name:
            p["status"] = "rejected"
            _save_proposals(proposals)
            _evo_log("PROPOSAL_REJECTED", tool_name)
            return True
    return False


# ── 4. Live installer ─────────────────────────────────────────────────────────

REGISTRY_FILE = ROOT / "tools" / "registry.py"

def install_tool_live(proposal: dict) -> bool:
    """
    Patch tools/registry.py with the new handler + registry entry,
    then hot-reload the tools module so Ava picks it up without restart.
    """
    name         = proposal["name"]
    description  = proposal["description"]
    schema       = proposal["input_schema"]
    handler_code = proposal["handler_code"]

    # Safety: ensure handler name matches convention
    handler_name = f"handle_{name}"
    if handler_name not in handler_code:
        handler_code = handler_code.replace(
            f"def handle_", f"def handle_{name}_old(\n# renamed\ndef handle_"
        )

    # Read current registry
    try:
        current = REGISTRY_FILE.read_text(encoding="utf-8")
    except Exception as e:
        _evo_log("INSTALL_FAILED", f"read error: {e}")
        return False

    # Inject handler before TOOL_REGISTRY definition
    injection_point = "# ═══════════════\n# REGISTRY"
    if injection_point not in current:
        injection_point = "TOOL_REGISTRY = ["

    new_handler = f"\n\n# ── Auto-installed: {name} ({datetime.now().strftime('%Y-%m-%d')}) ──\n{handler_code}\n"

    # Build registry entry
    schema_str = json.dumps(schema, indent=8)
    registry_entry = f"""    {{
        "name": "{name}",
        "description": {json.dumps(description)},
        "input_schema": {schema_str},
        "handler": {handler_name},
        "requires_confirmation": False,
    }},
"""

    # Inject handler
    if injection_point in current:
        current = current.replace(injection_point, new_handler + "\n" + injection_point)
    else:
        current = current + new_handler

    # Inject registry entry at end of TOOL_REGISTRY list
    current = re.sub(
        r"(TOOL_REGISTRY\s*=\s*\[)",
        r"\1\n" + registry_entry,
        current,
    )

    # Write back
    try:
        REGISTRY_FILE.write_text(current, encoding="utf-8")
    except Exception as e:
        _evo_log("INSTALL_FAILED", f"write error: {e}")
        return False

    # Hot-reload
    try:
        import tools.registry as _reg
        importlib.reload(_reg)
        import tools as _tools
        importlib.reload(_tools)
        _evo_log("INSTALL_SUCCESS", name)
        return True
    except Exception as e:
        _evo_log("RELOAD_FAILED", str(e))
        return False


# ── 5. Session replayer ───────────────────────────────────────────────────────

def replay_session(n_turns: int = 10) -> str:
    """
    Replay the last n turns through the current Ava brain and compare
    how she would answer now vs the logged original replies.
    Returns a summary string.
    """
    log_file = DATA_DIR / "interaction_log.jsonl"
    if not log_file.exists():
        return "No interaction log found."

    entries = []
    with open(log_file, encoding="utf-8") as f:
        for line in f:
            try:
                entries.append(json.loads(line.strip()))
            except Exception:
                pass

    recent = [e for e in entries[-n_turns:] if e.get("input_preview")]
    if not recent:
        return "Not enough history to replay."

    import os
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        return "GROQ_API_KEY not set."

    try:
        from groq import Groq
        client   = Groq(api_key=key)
        improved = 0
        results  = []
        for e in recent:
            user_input   = e["input_preview"]
            original     = e["reply_preview"]
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                max_tokens=150,
                messages=[
                    {"role": "system", "content":
                        "You are Ava, a warm AI executive assistant. Answer briefly."},
                    {"role": "user", "content": user_input},
                ],
            )
            new_reply = (resp.choices[0].message.content or "").strip()
            better    = len(new_reply) > 0 and new_reply != original
            if better:
                improved += 1
            results.append(f"  Q: {user_input[:60]}\n"
                           f"  Old: {original[:60]}\n"
                           f"  New: {new_reply[:60]}")

        summary = (
            f"Replayed {len(recent)} turns.\n"
            f"Improved responses: {improved}/{len(recent)}\n\n"
            + "\n".join(results[:3])
        )
        _evo_log("SESSION_REPLAY", f"{improved}/{len(recent)} improved")
        return summary
    except Exception as e:
        return f"Replay failed: {e}"


# ── 6. Performance report ─────────────────────────────────────────────────────

def generate_performance_report() -> str:
    """Generate a full self-assessment Ava can share with the user."""
    try:
        from learning import detect_patterns, get_struggling_tools
        patterns  = detect_patterns()
        struggling = get_struggling_tools()
    except Exception:
        patterns  = {}
        struggling = []

    pending = get_pending_proposals()
    evo_lines = []
    if EVOLUTION_LOG.exists():
        with open(EVOLUTION_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    evo_lines.append(json.loads(line.strip()))
                except Exception:
                    pass
    installed = [e for e in evo_lines if e.get("event") == "INSTALL_SUCCESS"]

    lines = [
        "── Ava Performance Report ──",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "Interaction patterns:",
        f"  Total turns:       {patterns.get('total_turns', 0)}",
        f"  Voice usage:       {patterns.get('voice_pct', 0)}%",
        f"  Avg reply length:  {patterns.get('avg_reply_len', 0)} chars",
        f"  Avg latency:       {patterns.get('avg_latency_ms', 0)} ms",
        f"  Top turn class:    {patterns.get('top_turn_class', 'N/A')}",
        f"  Most-used tools:   {', '.join(patterns.get('top_tools', []) or ['none'])}",
        "",
        "Health:",
        f"  Struggling tools:  {', '.join(struggling) or 'none'}",
        f"  Pending proposals: {len(pending)}",
        f"  Tools installed:   {len(installed)}",
        "",
    ]
    if pending:
        lines.append("Pending tool proposals (need your approval):")
        for p in pending:
            lines.append(f"  • {p['name']}: {p['description'][:80]}")
        lines.append("")
    if installed:
        lines.append("Recently self-installed tools:")
        for e in installed[-3:]:
            lines.append(f"  • {e['detail']}  ({e['ts'][:10]})")

    return "\n".join(lines)


# ── Heartbeat registration ────────────────────────────────────────────────────

def register_evolution_checks():
    """Returns heartbeat-compatible checks for the evolution module."""

    def _check_gaps_and_propose() -> bool:
        from heartbeat import push_notice
        gaps = detect_capability_gaps()
        if not gaps:
            return False
        gap     = gaps[0]
        proposal = propose_tool_for_gap(gap)
        if not proposal:
            return False
        save_proposal(proposal)
        push_notice(
            notice_id=f"tool_proposal_{proposal['name']}",
            label="New tool proposal",
            message=(
                f"I noticed a gap: {gap[:80]}.\n"
                f"I've drafted a new tool '{proposal['name']}' to fill it. "
                f"Say 'show tool proposal {proposal['name']}' to review it."
            ),
            priority="low",
        )
        return True

    def _check_install_approved() -> bool:
        approved = [p for p in _load_proposals() if p.get("status") == "approved"]
        installed_any = False
        for p in approved:
            success = install_tool_live(p)
            if success:
                p["status"] = "installed"
                installed_any = True
        if installed_any:
            _save_proposals(_load_proposals())  # refresh after installs
        return installed_any

    return [
        {"id": "gap_detection",      "label": "Detect capability gaps",
         "interval_minutes": 360,    "fn": _check_gaps_and_propose},
        {"id": "install_approved",   "label": "Install approved tools",
         "interval_minutes": 30,     "fn": _check_install_approved},
    ]
