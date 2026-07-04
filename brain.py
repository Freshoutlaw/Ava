"""
Ava — brain.py  (Tier 9: Intelligence layer)
---------------------------------------------
Smarter reasoning sits between user input and the raw LLM call.

What this module adds:
  1. Conversation summarisation — when history gets long, compress older turns
     into a summary so we never blow the token limit or lose context
  2. Structured reasoning — for complex questions, Ava thinks step-by-step
     in a hidden scratchpad before producing her final answer
  3. Self-critique — for long outputs (documents, reports), Ava reviews her
     own draft and improves it before returning it to the user
  4. Smart tool hint — analyses the user's message and pre-selects the most
     likely relevant tools so the model doesn't get distracted by a menu of 14
  5. Context classifier — labels each user turn so the right strategy fires:
     SIMPLE (direct answer), LOOKUP (needs a tool), RESEARCH (needs agent),
     TASK (multi-step), MEMORY (store/retrieve)

All functions return plain data — ava.py calls them and decides what to do.
Nothing here touches the UI or audio.
"""

import json
import os
import re
import time
import threading
from groq import Groq

# ── Groq client (key-rotation aware) ─────────────────────────────────────────
#
# Mirrors ava.py's key rotation: reads GROQ_API_KEY_1..GROQ_API_KEY_5,
# falls back to plain GROQ_API_KEY for backward compatibility.
# brain.py's calls are all "fast model" / low-stakes (classify, summarise,
# reason, critique) so on a 429 we simply rotate and retry once rather
# than building out the full backoff ladder ava.py has for the main chat.

def _load_keys() -> list[str]:
    keys = []
    i = 1
    while True:
        k = os.environ.get(f"GROQ_API_KEY_{i}", "").strip()
        if not k:
            break
        keys.append(k)
        i += 1
    if not keys:
        single = os.environ.get("GROQ_API_KEY", "").strip()
        if single:
            keys.append(single)
    return keys

_KEYS       = _load_keys()
_KEY_INDEX  = 0
_KEY_LOCK   = threading.Lock()

def _current_key() -> str:
    if not _KEYS:
        raise RuntimeError("No Groq API key found. Set GROQ_API_KEY_1 in .env")
    with _KEY_LOCK:
        return _KEYS[_KEY_INDEX % len(_KEYS)]

def _rotate_key():
    global _KEY_INDEX
    with _KEY_LOCK:
        _KEY_INDEX = (_KEY_INDEX + 1) % max(1, len(_KEYS))

def _client() -> Groq:
    return Groq(api_key=_current_key())

def _call_with_rotation(fn):
    """Run fn() (a zero-arg call to the Groq client); on 429 rotate once and retry."""
    try:
        return fn()
    except Exception as e:
        if "429" in str(e) or "rate_limit" in str(e).lower():
            _rotate_key()
            return fn()
        raise

MODEL         = "llama-3.3-70b-versatile"
FAST_MODEL    = "llama-3.1-8b-instant"   # cheap model for classify/summarise tasks
MAX_TOKENS    = 2048

# ── Token budget ───────────────────────────────────────────────────────────────
# Rough token estimate: ~1 token per 3.5 chars.
# We summarise when history exceeds this estimated token count.
SUMMARISE_THRESHOLD_CHARS = 12_000    # ~3,400 tokens — leaves headroom for context
SUMMARY_KEEP_TURNS        = 4         # keep this many recent turns verbatim after summarising

def _estimate_chars(history: list[dict]) -> int:
    return sum(len(m.get("content") or "") for m in history)


# ── 1. Conversation summariser ────────────────────────────────────────────────

def maybe_summarise(history: list[dict], system_prompt: str) -> list[dict]:
    """
    If history is getting long, compress the oldest turns into a summary
    and replace them with a single system-injected summary message.
    Returns the (possibly compressed) history — never mutates the original.

    Structure after summarisation:
      [{"role":"system", "content": "CONVERSATION SUMMARY: ..."},
       <last N raw turns>]
    """
    if _estimate_chars(history) < SUMMARISE_THRESHOLD_CHARS:
        return history   # no action needed

    # Split: everything except the last N turns gets summarised
    cutoff     = max(0, len(history) - SUMMARY_KEEP_TURNS * 2)
    to_summarise = history[:cutoff]
    to_keep      = history[cutoff:]

    if not to_summarise:
        return history

    # Build a transcript of what to compress
    transcript = "\n".join(
        f"{m['role'].upper()}: {(m.get('content') or '')[:300]}"
        for m in to_summarise
        if m.get("content")
    )

    try:
        resp = _call_with_rotation(lambda: _client().chat.completions.create(
            model=FAST_MODEL,
            max_tokens=512,
            messages=[
                {"role": "system", "content": (
                    "You are a conversation summariser. "
                    "Compress the following conversation into a concise factual summary "
                    "that preserves: decisions made, facts shared, tasks completed, and "
                    "anything the user wants remembered. Max 200 words. "
                    "Start with 'CONVERSATION SUMMARY:'"
                )},
                {"role": "user", "content": transcript},
            ],
        ))
        summary = resp.choices[0].message.content or ""
    except Exception:
        return history   # if summarisation fails, just return original

    compressed = [{"role": "system", "content": summary}] + list(to_keep)
    return compressed


# ── 2. Turn classifier ────────────────────────────────────────────────────────

TURN_CLASSES = {
    "SIMPLE":   "Casual chat, factual question answerable from memory, no tools needed.",
    "LOOKUP":   "Needs a tool call: goal check, notes, calculator, file read, web search.",
    "RESEARCH": "Needs multi-step research or a sub-agent (researcher/writer/coder).",
    "TASK":     "Multi-step action: draft + send, research + write, review + fix.",
    "MEMORY":   "User is explicitly telling Ava something to remember or asking what she knows.",
}

# Heuristic keyword patterns — checked instantly, no network call.
# Ordered by specificity: more specific/expensive classes checked first
# so a message matching multiple patterns lands in the right bucket.
_RESEARCH_PATTERNS = re.compile(
    r"\b(research|deep dive|investigate|compare .* (vs|versus)|"
    r"comprehensive|thorough analysis|full report)\b", re.I)
_TASK_PATTERNS = re.compile(
    r"\b(write (me )?(a|an|the) (full|complete)|draft and send|"
    r"create (a|an) (workflow|automation)|autonomous(ly)?|"
    r"review .* and fix|find .* and draft)\b", re.I)
_MEMORY_PATTERNS = re.compile(
    r"\b(remember (that|this|my)|don'?t forget|note that|"
    r"what do you (know|remember)|forget (that|about)|my name is|"
    r"i prefer|i like|i work (at|on)|i'?m building)\b", re.I)
_LOOKUP_PATTERNS = re.compile(
    r"\b(search|look up|find|what'?s|how much|calculate|compute|"
    r"goal|revenue|note|notes|file|read|open|weather|price|news|"
    r"who is|when is|where is|status of)\b", re.I)
_SIMPLE_PATTERNS = re.compile(
    r"^(hi|hey|hello|thanks|thank you|ok|okay|cool|nice|good|yes|no|"
    r"sure|got it|sounds good|bye|goodbye)\b", re.I)

def _heuristic_classify(user_input: str) -> str | None:
    """
    Instant pattern-based classification — no API call.
    Returns a class name, or None if genuinely ambiguous (falls back to API).
    """
    text = user_input.strip()
    if not text:
        return "SIMPLE"

    # Very short messages are almost always SIMPLE
    word_count = len(text.split())
    if word_count <= 3 and _SIMPLE_PATTERNS.search(text):
        return "SIMPLE"

    if _TASK_PATTERNS.search(text):
        return "TASK"
    if _RESEARCH_PATTERNS.search(text):
        return "RESEARCH"
    if _MEMORY_PATTERNS.search(text):
        return "MEMORY"
    if _LOOKUP_PATTERNS.search(text):
        return "LOOKUP"
    if word_count <= 6:
        return "SIMPLE"

    # Longer message with no clear signal — let the model decide
    return None


def classify_turn(user_input: str) -> str:
    """
    Classify the user's message into one of the TURN_CLASSES.
    Tries an instant heuristic first (no network call); only falls back
    to the fast model for genuinely ambiguous longer messages.
    """
    guess = _heuristic_classify(user_input)
    if guess is not None:
        return guess

    # Ambiguous — ask the fast model (rare path)
    class_list = "\n".join(f"  {k}: {v}" for k, v in TURN_CLASSES.items())
    try:
        resp = _call_with_rotation(lambda: _client().chat.completions.create(
            model=FAST_MODEL,
            max_tokens=10,
            messages=[
                {"role": "system", "content": (
                    f"Classify the following user message into exactly one of these classes:\n"
                    f"{class_list}\n"
                    f"Reply with ONLY the class name, nothing else."
                )},
                {"role": "user", "content": user_input},
            ],
        ))
        result = (resp.choices[0].message.content or "").strip().upper()
        return result if result in TURN_CLASSES else "LOOKUP"
    except Exception:
        return "LOOKUP"


# ── 3. Tool hint (pre-selection) ──────────────────────────────────────────────

# Map of keywords / patterns → likely tool names
# Ava still sees all tools — this is a description-ordering hint, not a filter.
_TOOL_HINTS: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"\b(revenue|goal|$\d|earned|made|closed|deal|payment)\b", re.I),
     ["get_goal", "log_revenue", "calculator"]),
    (re.compile(r"\b(note|remind|remember|capture|jot|wrote|idea)\b", re.I),
     ["add_note", "get_notes", "remember_fact"]),
    (re.compile(r"\b(search|look up|find|latest|news|current|who is|what is|price|rate)\b", re.I),
     ["web_search"]),
    (re.compile(r"\b(file|read|open|folder|directory|path|\.py|\.txt|\.json)\b", re.I),
     ["file_read", "list_dir"]),
    (re.compile(r"\b(write|save|export|create file|output to)\b", re.I),
     ["file_write"]),
    (re.compile(r"\b(calculate|compute|how much|percent|sum|total|divide|multiply)\b", re.I),
     ["calculator"]),
    (re.compile(r"\b(draft|message|email|outreach|linkedin|write to)\b", re.I),
     ["draft_message", "delegate_to_writer"]),
    (re.compile(r"\b(research|investigate|report on|deep dive|compare)\b", re.I),
     ["delegate_to_researcher"]),
    (re.compile(r"\b(code|review|debug|fix|bug|script|function|class|ava\.py)\b", re.I),
     ["delegate_to_coder", "file_read"]),
    (re.compile(r"\b(memory|know|recall|remember me|what do you know)\b", re.I),
     ["show_memory", "remember_fact"]),
]

def hint_tools(user_input: str, all_tools: list[dict]) -> list[dict]:
    """
    Re-order the tool list so the most likely tools appear first.
    The model sees all tools — ordering helps it pick faster and reduces
    the chance of a malformed tool call on a large tool list.
    """
    priority: list[str] = []
    for pattern, tools in _TOOL_HINTS:
        if pattern.search(user_input):
            priority.extend(tools)

    if not priority:
        return all_tools

    # Build ordered list: priority tools first (deduplicated), then rest
    seen   = set()
    result = []
    for name in priority:
        for t in all_tools:
            if t["name"] == name and name not in seen:
                result.append(t)
                seen.add(name)
    for t in all_tools:
        if t["name"] not in seen:
            result.append(t)
            seen.add(t["name"])
    return result


# ── 4. Structured reasoning (chain-of-thought scratchpad) ────────────────────

def reason_before_answer(user_input: str, context: str = "") -> str:
    """
    For complex / multi-step questions, produce a hidden reasoning chain
    before the main model call. Returns the reasoning as a string that
    gets prepended as a system note.

    Only called for TASK and RESEARCH turn classes — not on every message.
    Uses the fast model to keep latency low.
    """
    try:
        resp = _call_with_rotation(lambda: _client().chat.completions.create(
            model=FAST_MODEL,
            max_tokens=300,
            messages=[
                {"role": "system", "content": (
                    "You are a reasoning assistant. Think through the following request step by step. "
                    "Identify: (1) what the user actually needs, (2) what information or tools are required, "
                    "(3) the best order of operations. Be concise — this is internal planning, not the final answer."
                )},
                {"role": "user", "content": f"Request: {user_input}\nContext: {context or 'none'}"},
            ],
        ))
        return resp.choices[0].message.content or ""
    except Exception:
        return ""


# ── 5. Self-critique pass ─────────────────────────────────────────────────────

def self_critique(draft: str, task: str) -> str:
    """
    For long outputs (>400 chars), ask the model to review its own draft
    and return an improved version. Only fires for TASK / RESEARCH turns
    where quality matters more than speed.

    Returns improved text, or the original draft if critique fails.
    """
    if len(draft) < 400:
        return draft   # short replies don't need it

    try:
        resp = _call_with_rotation(lambda: _client().chat.completions.create(
            model=FAST_MODEL,
            max_tokens=len(draft) // 3 + 200,   # allow meaningful revision
            messages=[
                {"role": "system", "content": (
                    "You are an editor. Review the following draft for the given task. "
                    "Improve clarity, remove filler, fix any factual gaps or logical jumps. "
                    "Return ONLY the improved text — no commentary, no preamble."
                )},
                {"role": "user", "content": f"Task: {task}\n\nDraft:\n{draft}"},
            ],
        ))
        improved = resp.choices[0].message.content or ""
        return improved if improved.strip() else draft
    except Exception:
        return draft