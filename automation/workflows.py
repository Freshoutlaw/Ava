"""
Ava — automation/workflows.py  (Tier 19: Workflow Orchestrator)
----------------------------------------------------------------
Chain tools into named, reusable, scheduled workflows.

A workflow is a JSON file in data/workflows/ with this shape:
{
  "id":          "morning_brief",
  "name":        "Morning Brief",
  "description": "Check email, summarise, brief Alex",
  "trigger":     "daily 08:00",
  "steps": [
    {"tool": "read_emails",  "inputs": {"limit": 10, "unread_only": true}},
    {"tool": "get_goal",     "inputs": {}},
    {"tool": "get_notes",    "inputs": {"tag": "follow-up", "limit": 5}},
    {"agent": "writer",      "task": "Summarise these results into a 5-sentence morning brief: {step_0} {step_1} {step_2}"},
    {"notify": "medium",     "message": "{step_3}"}
  ]
}

Steps can be:
  {"tool": "tool_name",  "inputs": {...}}        — run a tool
  {"agent": "name",      "task": "..."}          — delegate to sub-agent
  {"shell": "...",       "shell_type": "ps"}     — run a shell command
  {"condition": "...",   "if_true": [...], "if_false": [...]} — branch
  {"notify": "priority", "message": "..."}       — push a heartbeat notice

Templates: {step_N} in inputs/task/message is replaced with the output of step N.
"""

import json, os, re, time, threading
from datetime import datetime, date
from pathlib import Path

ROOT      = Path(__file__).parent.parent
DATA_DIR  = ROOT / "data"
WF_DIR    = DATA_DIR / "workflows"
WF_LOG    = DATA_DIR / "workflow_log.jsonl"
DATA_DIR.mkdir(exist_ok=True)
WF_DIR.mkdir(exist_ok=True)


# ── Workflow storage ──────────────────────────────────────────────────────────

def list_workflows() -> list[dict]:
    workflows = []
    for f in WF_DIR.glob("*.json"):
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
            workflows.append(wf)
        except Exception:
            pass
    return workflows

def get_workflow(wf_id: str) -> dict | None:
    path = WF_DIR / f"{wf_id}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None

def save_workflow(wf: dict) -> str:
    wf_id = wf.get("id","").strip()
    if not wf_id:
        return "Error: workflow must have an 'id' field."
    path  = WF_DIR / f"{wf_id}.json"
    path.write_text(json.dumps(wf, indent=2), encoding="utf-8")
    return f"Workflow '{wf_id}' saved."

def delete_workflow(wf_id: str) -> str:
    path = WF_DIR / f"{wf_id}.json"
    if path.exists():
        path.unlink()
        return f"Workflow '{wf_id}' deleted."
    return f"Workflow '{wf_id}' not found."


# ── Template engine ───────────────────────────────────────────────────────────

def _apply_template(text: str, step_outputs: list[str]) -> str:
    """Replace {step_N} with the output of step N."""
    if not isinstance(text, str):
        return text
    for i, out in enumerate(step_outputs):
        text = text.replace(f"{{step_{i}}}", str(out)[:500])
    return text

def _apply_template_dict(d: dict, step_outputs: list[str]) -> dict:
    return {k: _apply_template(v, step_outputs) if isinstance(v,str) else v
            for k, v in d.items()}


# ── Workflow runner ───────────────────────────────────────────────────────────

def _wf_log(wf_id: str, status: str, detail: str = ""):
    entry = {"ts": datetime.now().isoformat(), "workflow": wf_id,
             "status": status, "detail": detail}
    try:
        with open(WF_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def run_workflow(wf: dict, verbose: bool = True) -> str:
    """
    Execute a workflow. Returns a summary string.
    Loads tool/agent runners lazily to avoid circular imports.
    """
    wf_id   = wf.get("id","unnamed")
    steps   = wf.get("steps", [])
    outputs = []
    summary = [f"Workflow: {wf.get('name', wf_id)}"]
    _wf_log(wf_id, "STARTED")

    # Lazy imports to avoid circular deps
    from tools import run_tool
    from memory import is_memory_tool, handle_memory_tool
    from agents import BUS

    for i, step in enumerate(steps):
        label = f"Step {i+1}"
        try:
            # ── Tool step ────────────────────────────────────────────────────
            if "tool" in step:
                tool_name = step["tool"]
                raw_inp   = step.get("inputs", {})
                inputs    = _apply_template_dict(raw_inp, outputs)
                if is_memory_tool(tool_name):
                    result = handle_memory_tool(tool_name, inputs)
                else:
                    result, _ = run_tool(tool_name, inputs)
                if verbose: print(f"  [{label}] tool:{tool_name} → {result[:60]}")
                outputs.append(result)
                summary.append(f"  {label} ({tool_name}): {result[:80]}")

            # ── Agent step ───────────────────────────────────────────────────
            elif "agent" in step:
                agent_name = step["agent"]
                task       = _apply_template(step.get("task",""), outputs)
                result     = BUS.delegate(agent_name, task, verbose=verbose)
                if verbose: print(f"  [{label}] agent:{agent_name} → {len(result)} chars")
                outputs.append(result)
                summary.append(f"  {label} (agent:{agent_name}): {result[:80]}")

            # ── Shell step ───────────────────────────────────────────────────
            elif "shell" in step:
                cmd      = _apply_template(step["shell"], outputs)
                shell    = step.get("shell_type","powershell")
                from tools.system import handle_run_command
                result   = handle_run_command({"command": cmd, "shell": shell})
                if verbose: print(f"  [{label}] shell → {result[:60]}")
                outputs.append(result)
                summary.append(f"  {label} (shell): {result[:80]}")

            # ── Condition step ───────────────────────────────────────────────
            elif "condition" in step:
                cond    = _apply_template(step["condition"], outputs)
                # Simple eval: check if last output contains a string
                last    = outputs[-1] if outputs else ""
                passed  = cond.lower() in last.lower()
                branch  = step.get("if_true",[]) if passed else step.get("if_false",[])
                if branch:
                    sub_result = run_workflow({"id":wf_id+"_branch","steps":branch}, verbose=verbose)
                    outputs.append(sub_result)
                else:
                    outputs.append(f"Condition {'passed' if passed else 'failed'}, no branch.")
                summary.append(f"  {label} (condition:{passed})")

            # ── Notify step ──────────────────────────────────────────────────
            elif "notify" in step:
                priority = step["notify"]
                message  = _apply_template(step.get("message","Workflow step complete."), outputs)
                from heartbeat import push_notice
                push_notice(
                    notice_id=f"wf_{wf_id}_{i}_{int(time.time())}",
                    label=wf.get("name", wf_id),
                    message=message,
                    priority=priority,
                )
                outputs.append(f"Notice pushed: {message[:80]}")
                summary.append(f"  {label} (notify:{priority}): {message[:60]}")

            else:
                outputs.append("(unknown step type)")

        except Exception as e:
            err = f"Step {i+1} error: {e}"
            if verbose: print(f"  [{label}] ERROR: {e}")
            outputs.append(err)
            summary.append(f"  {label} FAILED: {e}")
            _wf_log(wf_id, "STEP_ERROR", str(e))

    _wf_log(wf_id, "COMPLETED", f"{len(steps)} steps")
    return "\n".join(summary)


# ── Workflow scheduler ────────────────────────────────────────────────────────

WF_STATE_FILE = DATA_DIR / "workflow_state.json"

def _load_wf_state() -> dict:
    if WF_STATE_FILE.exists():
        try:
            return json.loads(WF_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_wf_state(state: dict):
    WF_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def _parse_trigger(trigger: str) -> float | None:
    """
    Parse a trigger string and return seconds-until-next-run.
    'daily HH:MM'  → seconds until that time today (or tomorrow)
    'hourly'       → seconds until next hour mark
    'every N min'  → N * 60 seconds
    """
    trigger = trigger.lower().strip()
    now     = datetime.now()
    if trigger.startswith("daily"):
        parts    = trigger.split()
        hm       = parts[-1] if len(parts) > 1 else "08:00"
        h, m     = map(int, hm.split(":"))
        target   = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target < now:
            target = target.replace(day=target.day+1)
        return (target - now).total_seconds()
    elif trigger == "hourly":
        return 3600 - (now.minute * 60 + now.second)
    elif "every" in trigger:
        mins = re.search(r"(\d+)\s*min", trigger)
        if mins: return int(mins.group(1)) * 60
    return None

def run_due_workflows() -> list[str]:
    """Check all workflows and run any that are due. Returns list of run IDs."""
    state     = _load_wf_state()
    workflows = list_workflows()
    ran       = []
    for wf in workflows:
        wf_id   = wf.get("id","")
        trigger = wf.get("trigger","")
        if not trigger or not wf_id:
            continue
        last_run = state.get(wf_id, {}).get("last_run", 0)
        due_in   = _parse_trigger(trigger)
        if due_in is None:
            continue
        # Due if never run, or enough time has passed
        time_since = time.time() - last_run
        cycle_secs = due_in + time_since if last_run == 0 else due_in
        if last_run == 0 or time_since >= (24*3600 if "daily" in trigger else due_in):
            try:
                run_workflow(wf, verbose=False)
                state.setdefault(wf_id, {})["last_run"] = time.time()
                ran.append(wf_id)
            except Exception as e:
                _wf_log(wf_id, "TRIGGER_ERROR", str(e))
    _save_wf_state(state)
    return ran


# ── Heartbeat integration ─────────────────────────────────────────────────────

def register_workflow_checks():
    def _check_workflows() -> bool:
        ran = run_due_workflows()
        return len(ran) > 0

    return [
        {"id": "workflow_runner", "label": "Workflow scheduler",
         "interval_minutes": 1, "fn": _check_workflows},
    ]


# ── Workflow tool handlers ─────────────────────────────────────────────────────

def handle_create_workflow(inputs: dict) -> str:
    wf = inputs.get("workflow")
    if isinstance(wf, str):
        try: wf = json.loads(wf)
        except Exception: return "Error: 'workflow' must be a valid JSON object."
    if not isinstance(wf, dict): return "Error: workflow must be a JSON object."
    return save_workflow(wf)

def handle_run_workflow(inputs: dict) -> str:
    wf_id = inputs.get("id","").strip()
    if not wf_id: return "Error: 'id' required."
    wf = get_workflow(wf_id)
    if not wf: return f"Workflow '{wf_id}' not found. Use list_workflows to see available."
    return run_workflow(wf, verbose=True)

def handle_list_workflows(inputs: dict) -> str:
    wfs = list_workflows()
    if not wfs: return "No workflows defined yet."
    lines = [f"Workflows ({len(wfs)}):"]
    for w in wfs:
        lines.append(f"  {w.get('id','?'):<20}  {w.get('trigger','manual'):<15}  {w.get('description','')[:60]}")
    return "\n".join(lines)

def handle_delete_workflow(inputs: dict) -> str:
    return delete_workflow(inputs.get("id","").strip())


# ── Tool schemas ──────────────────────────────────────────────────────────────

WORKFLOW_TOOLS = [
    {
        "name": "create_workflow",
        "description": (
            "Create a named automation workflow that chains multiple tools and agents. "
            "Workflows can run on a schedule (daily, hourly, every N min) or manually. "
            "Steps: {tool}, {agent}, {shell}, {condition}, {notify}. "
            "Use {step_N} in inputs to reference the output of previous steps."
        ),
        "input_schema": {
            "type":"object",
            "properties": {
                "workflow": {"type":"object","description":"Workflow definition JSON with id, name, trigger, steps array"},
            },
            "required": ["workflow"],
        },
        "handler":              handle_create_workflow,
        "requires_confirmation": False,
    },
    {
        "name": "run_workflow",
        "description": "Run a saved workflow immediately by its ID.",
        "input_schema": {
            "type":"object",
            "properties": {"id":{"type":"string","description":"Workflow ID to run"}},
            "required": ["id"],
        },
        "handler":              handle_run_workflow,
        "requires_confirmation": True,
    },
    {
        "name": "list_workflows",
        "description": "List all saved workflows with their triggers and descriptions.",
        "input_schema": {"type":"object","properties":{},"required":[]},
        "handler":              handle_list_workflows,
        "requires_confirmation": False,
    },
    {
        "name": "delete_workflow",
        "description": "Delete a workflow by ID.",
        "input_schema": {
            "type":"object",
            "properties": {"id":{"type":"string","description":"Workflow ID to delete"}},
            "required": ["id"],
        },
        "handler":              handle_delete_workflow,
        "requires_confirmation": True,
    },
]
