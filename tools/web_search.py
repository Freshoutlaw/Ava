"""
Ava — tools/web_search.py  (Tier 7)
-------------------------------------
Web search using DuckDuckGo Instant Answer API (free, no key required).
Falls back to a Groq-powered summarisation pass on the raw results.

Also: file_read, file_write, file_edit, calculator, list_dir.
"""

import json
import math
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path


# ── Web search (DuckDuckGo → Groq summarise) ─────────────────────────────────

def _ddg_search(query: str, max_results: int = 8) -> list[dict]:
    """
    Hit DuckDuckGo's free Instant Answer / HTML endpoint.
    Returns list of {title, url, snippet} dicts.
    No API key required.
    """
    try:
        import requests as _req
        url     = "https://api.duckduckgo.com/"
        params  = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
        resp    = _req.get(url, params=params, timeout=10, headers={"User-Agent": "Ava/1.0"})
        data    = resp.json()
        results = []

        if data.get("AbstractText"):
            results.append({
                "title":   data.get("Heading", query),
                "url":     data.get("AbstractURL", ""),
                "snippet": data["AbstractText"],
            })

        for topic in data.get("RelatedTopics", [])[:max_results]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title":   topic.get("Text", "")[:80],
                    "url":     topic.get("FirstURL", ""),
                    "snippet": topic.get("Text", ""),
                })

        return results[:max_results]
    except Exception:
        return []


def _groq_web_search_fallback(query: str) -> str:
    """Use Groq's built-in web_search_preview tool."""
    try:
        from groq import Groq
        api_key = os.environ.get("GROQ_API_KEY", "").strip() or os.environ.get("GROQ_API_KEY_1", "").strip()
        if not api_key:
            return ""
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": query}],
            tools=[{"type": "web_search_preview", "name": "web_search_preview"}],
            tool_choice="required",
            max_tokens=1024,
        )
        msg = response.choices[0].message
        return msg.content or ""
    except Exception:
        return ""


def handle_web_search(inputs: dict) -> str:
    """Search the web. Tries DuckDuckGo first, then Groq native search."""
    query = inputs.get("query", "").strip()
    if not query:
        return "Error: 'query' cannot be empty."

    results = _ddg_search(query)
    if results:
        lines = [f"Search results for: {query}\n"]
        for r in results:
            if r.get("snippet"):
                lines.append(f"• {r['snippet'][:300]}")
                if r.get("url"):
                    lines.append(f"  Source: {r['url']}")
        if len(lines) > 1:
            return "\n".join(lines)

    groq_result = _groq_web_search_fallback(query)
    if groq_result:
        return f"Search results for: {query}\n\n{groq_result}"

    return (
        f"Web search for '{query}' did not return live results. "
        f"Answer from your training knowledge and note the information may not be current."
    )


# ── File read ─────────────────────────────────────────────────────────────────

_ALLOWED_READ_EXTENSIONS = {
    ".txt", ".md", ".json", ".csv", ".log", ".py",
    ".js", ".ts", ".html", ".css", ".yaml", ".yml", ".toml", ".ini",
}
_MAX_READ_CHARS = 8000


def handle_file_read(inputs: dict) -> str:
    path_str = inputs.get("path", "").strip()
    if not path_str:
        return "Error: 'path' is required."
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        return f"Error: file not found — {path}"
    if not path.is_file():
        return f"Error: not a file — {path}"
    if path.suffix.lower() not in _ALLOWED_READ_EXTENSIONS:
        return f"Error: file type '{path.suffix}' not in allow-list. Allowed: {', '.join(sorted(_ALLOWED_READ_EXTENSIONS))}"
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"
    truncated = len(content) > _MAX_READ_CHARS
    if truncated:
        content = content[:_MAX_READ_CHARS]
    lines  = content.count("\n")
    header = f"File: {path}  ({lines} lines{', truncated' if truncated else ''})\n{'─'*40}\n"
    return header + content


# ── File write ────────────────────────────────────────────────────────────────

def handle_file_write(inputs: dict) -> str:
    path_str = inputs.get("path", "").strip()
    content  = inputs.get("content", "")
    mode     = inputs.get("mode", "write").strip().lower()
    if not path_str:
        return "Error: 'path' is required."
    if not content:
        return "Error: 'content' cannot be empty."
    if mode not in {"write", "append"}:
        return "Error: 'mode' must be 'write' or 'append'."
    path = Path(path_str).expanduser().resolve()
    forbidden = [Path("C:/Windows"), Path("C:/Program Files"), Path("/usr"), Path("/etc"), Path("/bin")]
    for fp in forbidden:
        try:
            path.relative_to(fp)
            return f"Error: writing to system directory '{fp}' is not allowed."
        except ValueError:
            pass
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a" if mode == "append" else "w", encoding="utf-8") as f:
            f.write(content)
        return f"{'Appended to' if mode=='append' else 'Written'} {path}  ({path.stat().st_size:,} bytes)"
    except Exception as e:
        return f"Error writing file: {e}"


# ── File edit ─────────────────────────────────────────────────────────────────
#
# Real editing, not just overwrite/append: find-and-replace a snippet,
# insert/replace/delete specific lines. Mirrors the str_replace pattern —
# `old_text` must match EXACTLY ONCE in the file, or the edit is rejected,
# so Ava can't accidentally clobber the wrong occurrence.

def handle_file_edit(inputs: dict) -> str:
    """
    Edit an existing file in place. Two modes:
      mode="replace"  — find `old_text` (must appear exactly once) and
                         swap it for `new_text`.
      mode="line"     — operate on a specific 1-indexed line number:
                         line_action="replace" | "insert_before" |
                         "insert_after" | "delete"
    """
    path_str = inputs.get("path", "").strip()
    mode     = inputs.get("mode", "replace").strip().lower()

    if not path_str:
        return "Error: 'path' is required."
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        return f"Error: file not found — {path}"
    if not path.is_file():
        return f"Error: not a file — {path}"

    forbidden = [Path("C:/Windows"), Path("C:/Program Files"), Path("/usr"), Path("/etc"), Path("/bin")]
    for fp in forbidden:
        try:
            path.relative_to(fp)
            return f"Error: editing system directory '{fp}' is not allowed."
        except ValueError:
            pass

    try:
        original = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file before edit: {e}"

    # ── Mode: find-and-replace a text snippet ──────────────────────────────────
    if mode == "replace":
        old_text = inputs.get("old_text", "")
        new_text = inputs.get("new_text", "")
        if not old_text:
            return "Error: 'old_text' is required for mode='replace'."

        count = original.count(old_text)
        if count == 0:
            return (f"Error: 'old_text' not found in {path.name}. "
                     "Nothing was changed — check it matches exactly, including whitespace.")
        if count > 1:
            return (f"Error: 'old_text' appears {count} times in {path.name} — "
                     "must match exactly once so the edit is unambiguous. "
                     "Include more surrounding context to make it unique.")

        updated = original.replace(old_text, new_text, 1)

    # ── Mode: line-number operations ────────────────────────────────────────────
    elif mode == "line":
        try:
            line_num = int(inputs.get("line_number", 0))
        except (TypeError, ValueError):
            return "Error: 'line_number' must be an integer."
        action = inputs.get("line_action", "replace").strip().lower()
        text   = inputs.get("text", "")

        lines = original.splitlines(keepends=True)
        if line_num < 1 or line_num > len(lines) + 1:
            return f"Error: line_number {line_num} out of range (file has {len(lines)} lines)."

        idx = line_num - 1
        if action == "replace":
            if idx >= len(lines):
                return f"Error: line {line_num} doesn't exist — use insert_after on the last line instead."
            newline = text if text.endswith("\n") else text + "\n"
            lines[idx] = newline
        elif action == "insert_before":
            newline = text if text.endswith("\n") else text + "\n"
            lines.insert(idx, newline)
        elif action == "insert_after":
            newline = text if text.endswith("\n") else text + "\n"
            lines.insert(idx + 1, newline)
        elif action == "delete":
            if idx >= len(lines):
                return f"Error: line {line_num} doesn't exist."
            del lines[idx]
        else:
            return "Error: 'line_action' must be replace, insert_before, insert_after, or delete."

        updated = "".join(lines)

    else:
        return "Error: 'mode' must be 'replace' or 'line'."

    try:
        path.write_text(updated, encoding="utf-8")
    except Exception as e:
        return f"Error writing edited file: {e}"

    diff_chars = len(updated) - len(original)
    sign = "+" if diff_chars >= 0 else ""
    return f"Edited {path.name} ({mode} mode) — {sign}{diff_chars} chars. New size: {len(updated):,} chars."


# ── Calculator ────────────────────────────────────────────────────────────────

def handle_calculator(inputs: dict) -> str:
    expression = inputs.get("expression", "").strip()
    if not expression:
        return "Error: 'expression' is required."
    allowed = {k: v for k, v in math.__dict__.items() if not k.startswith("_")}
    allowed.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum, "pow": pow})
    safe_expr = re.sub(r"[^0-9+\-*/().%,_ a-zA-Z]", "", expression)
    try:
        result = eval(safe_expr, {"__builtins__": {}}, allowed)  # noqa: S307
        if isinstance(result, float) and result == int(result):
            result = int(result)
        formatted = f"{result:,}" if isinstance(result, (int, float)) and abs(result) >= 1000 else str(result)
        return f"{expression} = {formatted}"
    except Exception as e:
        return f"Calculation error: {e}  (expression: {expression})"


# ── List directory ─────────────────────────────────────────────────────────────

def handle_list_dir(inputs: dict) -> str:
    path_str = inputs.get("path", "").strip() or "."
    path     = Path(path_str).expanduser().resolve()
    if not path.exists():
        return f"Error: path not found — {path}"
    if not path.is_dir():
        return f"Error: not a directory — {path}"
    try:
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        lines   = [f"Directory: {path}", "─" * 40]
        for e in entries[:60]:
            kind = "DIR " if e.is_dir() else "FILE"
            size = f"  {e.stat().st_size:>10,} B" if e.is_file() else ""
            lines.append(f"  [{kind}]  {e.name}{size}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing directory: {e}"


# ── Tier 7 tool registry entries ──────────────────────────────────────────────

TIER7_TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Search the web for current information. "
            "Use for news, prices, people, companies, events, or anything needing live data. "
            "Always search before saying you don't know something that could be looked up."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Specific search query."},
            },
            "required": ["query"],
        },
        "handler":              handle_web_search,
        "requires_confirmation": False,
    },
    {
        "name": "file_read",
        "description": (
            "Read a text file (txt, md, json, csv, py, js, etc.). "
            "Use when asked to look at, review, or load a file. Provide the full path."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Full file path, e.g. C:/Users/ADMIN/notes.txt"},
            },
            "required": ["path"],
        },
        "handler":              handle_file_read,
        "requires_confirmation": False,
    },
    {
        "name": "file_write",
        "description": (
            "Write or append text to a file. Requires confirmation. "
            "mode='write' overwrites; mode='append' adds to end. "
            "Use file_edit instead if you're modifying part of an existing file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "Full file path to write."},
                "content": {"type": "string", "description": "Text content to write."},
                "mode":    {"type": "string", "description": "'write' or 'append'. Default: write."},
            },
            "required": ["path", "content"],
        },
        "handler":              handle_file_write,
        "requires_confirmation": True,
    },
    {
        "name": "file_edit",
        "description": (
            "Edit an EXISTING file in place — real editing, not just overwrite/append. "
            "Use this instead of file_write whenever you're changing part of a file "
            "rather than replacing the whole thing. Two modes:\n"
            "  mode='replace': find 'old_text' (must match exactly once in the file) "
            "and swap it for 'new_text'. Best for targeted code/text changes.\n"
            "  mode='line': operate on a specific line_number with line_action "
            "'replace'|'insert_before'|'insert_after'|'delete' and 'text'. "
            "Best for adding/removing whole lines.\n"
            "Always requires confirmation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path":        {"type": "string", "description": "Full path of the file to edit."},
                "mode":        {"type": "string", "description": "'replace' (find/swap text) or 'line' (line-number op). Default: replace."},
                "old_text":    {"type": "string", "description": "[replace mode] Exact text to find — must appear exactly once."},
                "new_text":    {"type": "string", "description": "[replace mode] Text to put in its place."},
                "line_number": {"type": "integer", "description": "[line mode] 1-indexed line number to act on."},
                "line_action": {"type": "string", "description": "[line mode] 'replace', 'insert_before', 'insert_after', or 'delete'."},
                "text":        {"type": "string", "description": "[line mode] Text for replace/insert actions."},
            },
            "required": ["path"],
        },
        "handler":              handle_file_edit,
        "requires_confirmation": True,
    },
    {
        "name": "calculator",
        "description": (
            "Evaluate a math expression. Use for financial projections, percentages, growth rates. "
            "Supports: +, -, *, /, **, %, sqrt, log, sin, cos, pi, e, round, abs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "Math expression, e.g. '1400 + 100 + 2000'"},
            },
            "required": ["expression"],
        },
        "handler":              handle_calculator,
        "requires_confirmation": False,
    },
    {
        "name": "list_dir",
        "description": "List files and folders at a directory path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list."},
            },
            "required": [],
        },
        "handler":              handle_list_dir,
        "requires_confirmation": False,
    },
]
