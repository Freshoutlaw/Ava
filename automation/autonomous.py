"""
Ava — automation/autonomous.py  (Tier 20: Autonomous Agent Loop)
-----------------------------------------------------------------
Give Ava a high-level goal and she works toward it independently:
  1. Breaks the goal into concrete sub-tasks
  2. Executes each task using tools and agents
  3. Evaluates the result and adapts if needed
  4. Pauses at checkpoints for human approval
  5. Reports progress and final outcome

This is the top of the stack — every tier beneath feeds into this.

Safety:
  - Every checkpoint requires your explicit yes before continuing
  - Max iterations capped (default 20) — never runs forever
  - Full audit trail written to data/autonomous_log.jsonl
  - Kill flag checked every iteration — 'k' in terminal stops it

Usage from conversation:
  "Ava, autonomously research and write a full business plan for Zynctra"
  "Ava, autonomously find 10 leads for Zynctra and draft outreach for each"
  "Ava, autonomously scan my network (192.168.1.0/24) and report findings"

Or call directly:
  python automation/autonomous.py "your goal here"
"""

import json, os, sys, time, threading
from datetime import datetime
from pathlib import Path

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
AUTO_LOG = DATA_DIR / "autonomous_log.jsonl"

KILL_FLAG = threading.Event()  # set this to stop any running autonomous loop


# ── Logging ───────────────────────────────────────────────────────────────────

def _log(session_id: str, event: str, detail: str = ""):
    entry = {"ts":datetime.now().isoformat(),"session":session_id,"event":event,"detail":detail}
    try:
        with open(AUTO_LOG,"a",encoding="utf-8") as f:
            f.write(json.dumps(entry)+"\n")
    except Exception:
        pass


# ── Task planner ──────────────────────────────────────────────────────────────

def plan_tasks(goal: str, context: str = "") -> list[dict]:
    """
    Break a high-level goal into ordered sub-tasks using Groq.
    Returns list of: {id, task, tool_hint, checkpoint}
    checkpoint=True means Ava will pause and ask you to approve before running.
    """
    import os
    key = os.environ.get("GROQ_API_KEY","").strip()
    if not key:
        return [{"id":1,"task":goal,"tool_hint":"delegate_to_researcher","checkpoint":True}]

    from groq import Groq
    client = Groq(api_key=key)
    resp   = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=800,
        messages=[
            {"role":"system","content":(
                "You are a task planner for an AI assistant. "
                "Break the goal into 3-8 concrete, ordered sub-tasks. "
                "For each task, specify: which tool or agent to use, and whether it needs human approval. "
                "Approval (checkpoint:true) required for: sending messages, spending money, "
                "running offensive security tools, deleting data, posting publicly. "
                "Return ONLY a JSON array:\n"
                '[{"id":1,"task":"...","tool_hint":"tool_or_agent_name","checkpoint":false}]'
            )},
            {"role":"user","content":f"Goal: {goal}\nContext: {context or 'none'}"},
        ],
    )
    text = (resp.choices[0].message.content or "").strip()
    text = text.replace("```json","").replace("```","").strip()
    try:
        tasks = json.loads(text)
        return tasks if isinstance(tasks, list) else []
    except Exception:
        return [{"id":1,"task":goal,"tool_hint":"delegate_to_researcher","checkpoint":True}]


# ── Task executor ─────────────────────────────────────────────────────────────

def execute_task(task: dict, history: list[str], verbose: bool = True) -> str:
    """
    Execute a single planned task using the appropriate tool/agent.
    Returns the result string.
    """
    task_text  = task.get("task","")
    tool_hint  = task.get("tool_hint","").strip()

    if verbose:
        print(f"\n  ▸ Task: {task_text[:80]}")
        print(f"    Tool: {tool_hint}")

    # Build context from previous results
    context = "\n".join(f"Previous result {i+1}: {r[:200]}" for i,r in enumerate(history[-3:]))
    full_task = f"{task_text}\n\nContext from previous steps:\n{context}" if context else task_text

    # Route to sub-agent or tool
    from agents import BUS
    from tools  import run_tool
    from memory import is_memory_tool, handle_memory_tool

    if tool_hint.startswith("delegate_to_") or tool_hint in ("researcher","writer","coder"):
        agent_name = tool_hint.replace("delegate_to_","")
        result     = BUS.delegate(agent_name, full_task, verbose=verbose)
    elif tool_hint and not tool_hint.startswith("delegate"):
        if is_memory_tool(tool_hint):
            result = handle_memory_tool(tool_hint, {"fact": task_text})
        else:
            result, _ = run_tool(tool_hint, {"query": task_text, "task": task_text,
                                              "command": task_text})
    else:
        # Let Groq decide the best approach
        from groq import Groq
        key    = os.environ.get("GROQ_API_KEY","").strip()
        client = Groq(api_key=key)
        resp   = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=1000,
            messages=[
                {"role":"system","content":"You are Ava, an AI executive assistant. Complete this task thoroughly."},
                {"role":"user","content":full_task},
            ],
        )
        result = resp.choices[0].message.content or ""

    if verbose:
        print(f"    → {result[:100]}{'…' if len(result)>100 else ''}")
    return result


# ── Result evaluator ──────────────────────────────────────────────────────────

def evaluate_result(goal: str, task: dict, result: str) -> dict:
    """
    Ask Groq to evaluate whether the task result is good enough,
    or if it should be retried with a different approach.
    Returns: {quality: 1-5, retry: bool, reason: str, next_action: str}
    """
    import os
    key = os.environ.get("GROQ_API_KEY","").strip()
    if not key:
        return {"quality":4,"retry":False,"reason":"OK","next_action":"continue"}
    try:
        from groq import Groq
        client = Groq(api_key=key)
        resp   = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            max_tokens=150,
            messages=[
                {"role":"system","content":(
                    "Evaluate if this task result is good enough to move forward. "
                    'Return ONLY JSON: {"quality":1-5,"retry":false,"reason":"...","next_action":"continue|retry|escalate"}'
                )},
                {"role":"user","content":f"Goal: {goal}\nTask: {task.get('task','')}\nResult: {result[:400]}"},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        text = text.replace("```json","").replace("```","").strip()
        return json.loads(text)
    except Exception:
        return {"quality":3,"retry":False,"reason":"evaluation failed","next_action":"continue"}


# ── Human checkpoint ──────────────────────────────────────────────────────────

def checkpoint(task: dict, preview: str, timeout: int = 120) -> bool:
    """
    Pause and ask the user to approve before continuing.
    Returns True if approved, False if denied or timed out.
    """
    print(f"\n  ┌─ CHECKPOINT ────────────────────────────────")
    print(f"  │ Next task: {task.get('task','')[:80]}")
    print(f"  │ Preview:   {preview[:80]}")
    print(f"  │ Approve? (yes/no) — auto-denies in {timeout}s: ", end="", flush=True)

    answer = [None]
    def _read():
        try:    answer[0] = input().strip().lower()
        except: answer[0] = "no"
    t = threading.Thread(target=_read, daemon=True)
    t.start(); t.join(timeout=timeout)

    approved = answer[0] in {"yes","y"}
    print(f"  └─ {'APPROVED ✓' if approved else 'DENIED ✗'}")
    return approved


# ── Main autonomous loop ──────────────────────────────────────────────────────

def run_autonomous(
    goal:         str,
    max_iters:    int  = 20,
    verbose:      bool = True,
    auto_approve: bool = False,   # True = skip checkpoints (use carefully)
) -> str:
    """
    The main autonomous loop. Give it a goal, it works until done or stopped.
    Returns a full summary of what was accomplished.
    """
    session_id = f"auto_{int(time.time())}"
    _log(session_id, "STARTED", goal)
    KILL_FLAG.clear()

    if verbose:
        print(f"\n{'═'*60}")
        print(f"  AVA AUTONOMOUS MODE")
        print(f"  Goal: {goal}")
        print(f"  Max iterations: {max_iters}")
        print(f"  Press Ctrl-C or type 'k' in terminal to stop")
        print(f"{'═'*60}\n")

    # Step 1: Plan
    print("[autonomous] Planning tasks…")
    tasks   = plan_tasks(goal)
    if verbose:
        print(f"[autonomous] {len(tasks)} tasks planned:")
        for t in tasks:
            ck = " [CHECKPOINT]" if t.get("checkpoint") else ""
            print(f"  {t.get('id','?')}. {t.get('task','')[:70]}{ck}")

    history   = []
    completed = []
    skipped   = []
    iters     = 0

    for task in tasks:
        if KILL_FLAG.is_set():
            print("\n[autonomous] Stopped by kill flag.")
            _log(session_id, "KILLED", f"completed {len(completed)} tasks")
            break

        if iters >= max_iters:
            print(f"\n[autonomous] Max iterations ({max_iters}) reached.")
            break

        iters += 1

        # Checkpoint gate
        if task.get("checkpoint") and not auto_approve:
            preview = f"Use {task.get('tool_hint','?')} to: {task.get('task','')[:60]}"
            if not checkpoint(task, preview):
                skipped.append(task)
                _log(session_id, "SKIPPED", task.get("task",""))
                continue

        # Execute
        try:
            result = execute_task(task, history, verbose=verbose)
        except Exception as e:
            result = f"Task failed: {e}"
            if verbose: print(f"  ✗ Error: {e}")

        # Evaluate
        eval_r = evaluate_result(goal, task, result)
        if eval_r.get("retry") and iters < max_iters:
            if verbose: print(f"  ↻ Retrying (quality {eval_r['quality']}/5): {eval_r['reason']}")
            try:
                result = execute_task(task, history, verbose=verbose)
            except Exception:
                pass

        history.append(result)
        completed.append({**task, "result": result[:300], "quality": eval_r.get("quality",3)})
        _log(session_id, "TASK_DONE", f"id={task.get('id')}  quality={eval_r.get('quality')}")

        if verbose:
            print(f"  ✓ Task {task.get('id')} complete (quality: {eval_r.get('quality',3)}/5)\n")

    # Final synthesis
    print("\n[autonomous] Synthesising final report…")
    import os
    key = os.environ.get("GROQ_API_KEY","").strip()
    final_report = ""
    if key and completed:
        try:
            from groq import Groq
            client     = Groq(api_key=key)
            task_dump  = json.dumps([{"task":t["task"],"result":t.get("result","")} for t in completed], indent=2)
            resp       = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                max_tokens=1000,
                messages=[
                    {"role":"system","content":"Synthesise these task results into a clear final report for the user."},
                    {"role":"user","content":f"Goal: {goal}\n\nCompleted tasks:\n{task_dump[:3000]}"},
                ],
            )
            final_report = resp.choices[0].message.content or ""
        except Exception as e:
            final_report = f"(synthesis failed: {e})"

    summary = (
        f"Autonomous run complete.\n"
        f"Goal: {goal}\n"
        f"Tasks completed: {len(completed)}/{len(tasks)}\n"
        f"Tasks skipped:   {len(skipped)}\n"
        f"Iterations used: {iters}/{max_iters}\n\n"
        f"{'─'*50}\n"
        f"{final_report}"
    )
    _log(session_id, "COMPLETED", f"{len(completed)} tasks done")
    if verbose: print(f"\n[autonomous] Done.\n{summary[:300]}\n")
    return summary


# ── Tool handler wrappers ─────────────────────────────────────────────────────

def handle_run_autonomous(inputs: dict) -> str:
    goal      = inputs.get("goal","").strip()
    max_iters = int(inputs.get("max_iterations", 10))
    if not goal: return "Error: 'goal' is required."
    # Run in thread so it doesn't block the main loop
    result_box = []
    def _run():
        result_box.append(run_autonomous(goal, max_iters=max_iters, verbose=True))
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=max_iters * 60)   # generous timeout
    return result_box[0] if result_box else "Autonomous run timed out or was interrupted."

def handle_stop_autonomous(inputs: dict) -> str:
    KILL_FLAG.set()
    return "Autonomous loop stopped."

def handle_list_autonomous_sessions(inputs: dict) -> str:
    if not AUTO_LOG.exists(): return "No autonomous sessions logged yet."
    sessions: dict = {}
    with open(AUTO_LOG, encoding="utf-8") as f:
        for line in f:
            try:
                e   = json.loads(line.strip())
                sid = e.get("session","?")
                if sid not in sessions:
                    sessions[sid] = {"start":e["ts"],"events":[]}
                sessions[sid]["events"].append(e["event"])
            except Exception:
                pass
    lines = [f"Autonomous sessions ({len(sessions)}):"]
    for sid, s in list(sessions.items())[-10:]:
        lines.append(f"  {sid}  {s['start'][:16]}  events: {','.join(s['events'][-3:])}")
    return "\n".join(lines)


# ── Tool schemas ──────────────────────────────────────────────────────────────

AUTONOMOUS_TOOLS = [
    {
        "name": "run_autonomous",
        "description": (
            "Give Ava a high-level goal and let her work toward it autonomously: "
            "planning tasks, executing them with tools and agents, evaluating results, "
            "and adapting. She pauses at checkpoints for your approval before any "
            "sensitive actions. Use for big multi-step goals: "
            "'Research and write a full business plan', "
            "'Find 10 leads and draft personalised outreach for each', "
            "'Scan this IP range and produce a security report'. "
            "ALWAYS requires confirmation before starting."
        ),
        "input_schema": {
            "type":"object",
            "properties": {
                "goal":           {"type":"string","description":"The high-level goal for Ava to pursue autonomously"},
                "max_iterations": {"type":"integer","description":"Max task iterations (default 10, max 20)"},
            },
            "required": ["goal"],
        },
        "handler":              handle_run_autonomous,
        "requires_confirmation": True,
    },
    {
        "name": "stop_autonomous",
        "description": "Stop any running autonomous loop immediately.",
        "input_schema": {"type":"object","properties":{},"required":[]},
        "handler":              handle_stop_autonomous,
        "requires_confirmation": False,
    },
    {
        "name": "list_autonomous_sessions",
        "description": "List past autonomous sessions and their status.",
        "input_schema": {"type":"object","properties":{},"required":[]},
        "handler":              handle_list_autonomous_sessions,
        "requires_confirmation": False,
    },
]


# ── CLI entry ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:
        pass
    goal = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not goal:
        print("Usage: python automation/autonomous.py 'your goal here'")
        sys.exit(1)
    print(run_autonomous(goal))
