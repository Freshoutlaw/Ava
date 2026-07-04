"""
Ava — memory.py
----------------
Tier 4: Long-term persistent memory.

Stores durable facts about the user across restarts.
File: data/memory.json  (plain JSON — open and edit any time)

DESIGN RULES
  - One fact per entry, written as a plain statement
  - Facts are background knowledge injected into the system prompt
  - Memory is NEVER a source of commands — it never bypasses the safety gate
  - The model can read, write, and delete facts via three tools
  - You can edit memory.json directly at any time; changes take effect next turn

MEMORY TOOLS (registered into the agent's tool list)
  remember_fact   — save a new fact or update an existing one
  forget_fact     — delete a fact by ID
  show_memory     — return all stored facts (so the model can introspect)
"""

import json
from datetime import datetime
from pathlib import Path

# ── Storage ───────────────────────────────────────────────────────────────────
DATA_DIR    = Path(__file__).parent / "data"
MEMORY_FILE = DATA_DIR / "memory.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_memory() -> dict:
    """Return the full memory store. Always returns a valid dict."""
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"facts": []}


def _save_memory(store: dict):
    MEMORY_FILE.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Context injection ─────────────────────────────────────────────────────────

def memory_context() -> str:
    """
    Return a plain-text block of all stored facts for injection into the
    system prompt. Returns "" if there are no facts yet.
    """
    store = load_memory()
    facts = store.get("facts", [])
    if not facts:
        return ""
    lines = []
    for f in facts:
        lines.append(f"- [{f['id']}] {f['fact']}")
    return "\n".join(lines)


# ── Tool handlers ─────────────────────────────────────────────────────────────

def handle_remember_fact(inputs: dict) -> str:
    """
    Save a new fact, or update an existing one if update_id is provided.
    Input: {fact: str, update_id?: str}
    """
    fact_text = inputs.get("fact", "").strip()
    if not fact_text:
        return "Error: 'fact' cannot be empty."

    store      = load_memory()
    facts      = store.get("facts", [])
    update_id  = inputs.get("update_id", "").strip()

    if update_id:
        # Update existing
        for f in facts:
            if f["id"] == update_id:
                old       = f["fact"]
                f["fact"] = fact_text
                f["updated"] = datetime.now().strftime("%Y-%m-%d")
                _save_memory({"facts": facts})
                return f"Updated memory [{update_id}]: \"{old}\" → \"{fact_text}\""
        return f"Error: no memory with id '{update_id}'."

    # New fact
    new_id = f"m{len(facts) + 1:03d}"
    facts.append({
        "id":      new_id,
        "fact":    fact_text,
        "saved":   datetime.now().strftime("%Y-%m-%d"),
    })
    _save_memory({"facts": facts})
    return f"Remembered [{new_id}]: \"{fact_text}\""


def handle_forget_fact(inputs: dict) -> str:
    """
    Delete a fact by ID.
    Input: {id: str}
    """
    fact_id = inputs.get("id", "").strip()
    if not fact_id:
        return "Error: 'id' is required. Use show_memory to find the ID."

    store  = load_memory()
    facts  = store.get("facts", [])
    before = len(facts)
    facts  = [f for f in facts if f["id"] != fact_id]

    if len(facts) == before:
        return f"No memory found with id '{fact_id}'."

    _save_memory({"facts": facts})
    return f"Forgotten memory [{fact_id}]."


def handle_show_memory(inputs: dict) -> str:
    """
    Return all stored facts.
    Input: {} (no inputs required)
    """
    store = load_memory()
    facts = store.get("facts", [])
    if not facts:
        return "No memories stored yet."
    lines = [f"Stored memories ({len(facts)}):"]
    for f in facts:
        date = f.get("updated") or f.get("saved", "")
        lines.append(f"  [{f['id']}] ({date})  {f['fact']}")
    return "\n".join(lines)


# ── Tool registry integration ─────────────────────────────────────────────────

_MEMORY_TOOLS = [
    {
        "name": "remember_fact",
        "description": (
            "Save a durable fact about the user that should persist across conversations. "
            "Use for: names, preferences, decisions, goals, relationships, working style, "
            "anything the user mentions that they'd want you to know next time. "
            "Don't ask permission — just save it and confirm you have. "
            "To update an existing fact, pass update_id with the fact's ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fact":      {"type": "string", "description": "The fact to remember, as a plain statement. e.g. 'User's name is Alex.'"},
                "update_id": {"type": "string", "description": "ID of an existing memory to update (optional). Get IDs from show_memory."},
            },
            "required": ["fact"],
        },
        "handler":              handle_remember_fact,
        "requires_confirmation": False,
    },
    {
        "name": "forget_fact",
        "description": (
            "Delete a stored memory by its ID. "
            "Use when the user asks you to forget something, or when a fact is outdated. "
            "Get the ID first with show_memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Memory ID to delete, e.g. 'm001'."},
            },
            "required": ["id"],
        },
        "handler":              handle_forget_fact,
        "requires_confirmation": False,
    },
    {
        "name": "show_memory",
        "description": (
            "List all facts currently stored in long-term memory with their IDs and dates. "
            "Use when the user asks what you remember, or before updating/deleting a fact."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler":              handle_show_memory,
        "requires_confirmation": False,
    },
]

_MEMORY_TOOL_NAMES = {t["name"] for t in _MEMORY_TOOLS}
_MEMORY_TOOL_MAP   = {t["name"]: t for t in _MEMORY_TOOLS}


def register_memory_tools() -> list[dict]:
    """Return memory tool schemas for the model (no internal fields)."""
    return [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in _MEMORY_TOOLS
    ]


def is_memory_tool(name: str) -> bool:
    return name in _MEMORY_TOOL_NAMES


def handle_memory_tool(name: str, inputs: dict) -> str:
    """Execute a memory tool by name. Returns result string."""
    tool = _MEMORY_TOOL_MAP.get(name)
    if not tool:
        return f"Error: no memory tool named '{name}'."
    try:
        return tool["handler"](inputs)
    except Exception as e:
        return f"Memory tool '{name}' failed: {e}"
