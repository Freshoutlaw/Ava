"""
Ava — agents_roster.py  (Tier 8)
----------------------------------
Defines and registers all of Ava's sub-agents onto the AgentBus.

To add a new specialist:
  1. Write its system prompt and tool subset here
  2. Call BUS.register(SubAgent(...))
  That's it — Ava sees it automatically as a delegate_to_<name> tool.

Current roster:
  researcher  — multi-step web research, returns structured report
  writer      — drafts, edits, and structures long-form content
  coder       — reads files, analyses code, writes implementations
"""

from .base import AgentBus, SubAgent

# Tool handlers shared across agents
# (importing from the tool files so handlers are always the same implementation)
from tools.web_search import (
    handle_web_search,
    handle_file_read,
    handle_file_write,
    handle_calculator,
    handle_list_dir,
    TIER7_TOOLS,
)
from tools.registry import (
    handle_add_note,
    handle_get_notes,
    TOOL_REGISTRY as BASE_TOOLS,
)

# ── Tool subsets ───────────────────────────────────────────────────────────────

_SEARCH_TOOLS = [t for t in TIER7_TOOLS if t["name"] == "web_search"]
_SEARCH_HANDLERS = {"web_search": handle_web_search}

_FILE_TOOLS = [t for t in TIER7_TOOLS if t["name"] in {"file_read", "file_write", "list_dir"}]
_FILE_HANDLERS = {
    "file_read":  handle_file_read,
    "file_write": handle_file_write,
    "list_dir":   handle_list_dir,
}

_CALC_TOOLS = [t for t in TIER7_TOOLS if t["name"] == "calculator"]
_CALC_HANDLERS = {"calculator": handle_calculator}

_NOTE_TOOLS = [t for t in BASE_TOOLS if t["name"] in {"add_note", "get_notes"}]
_NOTE_HANDLERS = {"add_note": handle_add_note, "get_notes": handle_get_notes}


# ── Agent 1: Researcher ────────────────────────────────────────────────────────

RESEARCHER = SubAgent(
    name="researcher",
    description=(
        "Deep research specialist. Use when a question needs multiple web searches, "
        "cross-referencing sources, or a structured research report. "
        "Examples: 'Research the top 5 HR SaaS competitors', "
        "'Find recent funding rounds in the HR tech space', "
        "'What are the best strategies for cold outreach to investors in 2025'."
    ),
    system="""You are a focused research agent. Your only job is to thoroughly research the given topic and return a clear, well-structured report.

Process:
1. Identify the 3–5 most important sub-questions that need answering
2. Search for each one specifically
3. Synthesise findings into a structured report with sections
4. Always include sources at the end

Format your final report with:
- **Summary** (3–4 sentences)
- **Key Findings** (bullet points)
- **Details** (per sub-topic)
- **Sources** (URLs)

Be factual, concise, and cite sources. Do not pad with filler.""",
    tools=_SEARCH_TOOLS + _NOTE_TOOLS,
    tool_handlers={**_SEARCH_HANDLERS, **_NOTE_HANDLERS},
    max_rounds=8,
    max_tokens=3000,
)


# ── Agent 2: Writer ────────────────────────────────────────────────────────────

WRITER = SubAgent(
    name="writer",
    description=(
        "Long-form writing specialist. Use when the task needs a full document, "
        "structured article, detailed report, proposal, or anything over 3 paragraphs. "
        "Examples: 'Write a cold email sequence for SaaS outreach', "
        "'Draft a one-page executive summary of my business', "
        "'Write a LinkedIn post about my HR SaaS launch'."
    ),
    system="""You are a focused writing agent. Your job is to produce complete, polished written content.

Process:
1. Understand the format, audience, and goal from the task
2. Plan the structure before writing
3. Write the complete piece — no placeholders, no "add X here"
4. Review for tone, clarity, and flow

Always deliver the full finished piece. If you need to search for context or facts first, do so.
Match the tone to the audience: professional for B2B, warm and direct for personal comms.
Never truncate. If the task is large, break it into clearly labelled sections.""",
    tools=_SEARCH_TOOLS + _FILE_TOOLS + _NOTE_TOOLS,
    tool_handlers={**_SEARCH_HANDLERS, **_FILE_HANDLERS, **_NOTE_HANDLERS},
    max_rounds=6,
    max_tokens=3000,
)


# ── Agent 3: Coder ─────────────────────────────────────────────────────────────

CODER = SubAgent(
    name="coder",
    description=(
        "Code specialist. Use when the task involves reading, writing, reviewing, "
        "debugging, or explaining code. "
        "Examples: 'Review my ava.py and find any bugs', "
        "'Write a Python script to parse this CSV', "
        "'Explain what this function does and suggest improvements'."
    ),
    system="""You are a focused code agent. Your job is to read, write, review, and explain code.

Process:
1. Read the relevant files before doing anything else
2. Understand the full context — don't guess at structure
3. Produce complete, working code — no TODO comments, no stubs
4. Explain what you changed and why

Rules:
- Never truncate code. Always write the full implementation.
- Prefer simple, readable code over clever one-liners.
- If you find a bug, explain the root cause before fixing it.
- If writing new code, include brief inline comments for non-obvious parts.
- Always test your logic mentally before returning it.""",
    tools=_FILE_TOOLS + _CALC_TOOLS,
    tool_handlers={**_FILE_HANDLERS, **_CALC_HANDLERS},
    max_rounds=8,
    max_tokens=4000,
)


# ── Build the bus ──────────────────────────────────────────────────────────────

BUS = AgentBus()
BUS.register(RESEARCHER)
BUS.register(WRITER)
BUS.register(CODER)
