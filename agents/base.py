"""
Ava — agents/base.py  (Tier 8)
--------------------------------
Sub-agent framework with:
  - Robust malformed tool-call parsing (3 formats Groq emits)
  - Rate-limit retry with exponential backoff
  - Graceful error recovery (never raises, always returns a string)
"""

import json
import os
import re
import time
from dataclasses import dataclass, field


# ── Rate-limit retry ──────────────────────────────────────────────────────────

def _retry_on_rate_limit(fn, *args, retries: int = 4, base_wait: float = 3.0, **kwargs):
    """Exponential backoff on 429 rate-limit errors."""
    last_exc = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            if "429" in msg or "rate_limit_exceeded" in msg or "Rate limit" in msg:
                last_exc = e
                wait = base_wait * (2 ** attempt)
                print(f"\n  [rate limit] waiting {wait:.0f}s before retry ({attempt+1}/{retries})…")
                time.sleep(wait)
            else:
                raise  # not a rate-limit — propagate immediately
    raise last_exc  # type: ignore


# ── Malformed tool-call parser ────────────────────────────────────────────────
# Groq's Llama models emit tool calls in several broken formats depending on
# context size and model version. We handle all observed variants here.

_PATTERNS = [
    # Format 1: <function=name,{"key":"val"}>
    (r'<function=([^,>\[]+),(\{[^>]*\})>', True),
    # Format 2: <function=name[]{"key":"val"}</function>
    (r'<function=([^\[>]+)\[\]\s*(\{.*?\})\s*</function>', True),
    # Format 3: <function=name {"key":"val"}> (space instead of comma)
    (r'<function=([^{>]+?)\s+(\{.*?\})>', True),
    # Format 4: bare function call text  func_name({"key":"val"})
    (r'\b([a-z_][a-z0-9_]*)\(\s*(\{[^)]*\})\s*\)', False),
]

def _parse_malformed_tool_calls(content: str, known_tool_names: set[str]) -> list[dict] | None:
    """
    Try every known malformed format. Return list of call dicts or None.
    Only returns calls whose tool name is in known_tool_names.
    """
    calls = []
    seen  = set()

    for pattern, is_tag in _PATTERNS:
        for name, args_str in re.findall(pattern, content, re.DOTALL | re.IGNORECASE):
            name = name.strip().strip('"').strip("'")
            if name not in known_tool_names:
                continue
            if name in seen:
                continue
            seen.add(name)
            # Clean up args_str — remove trailing garbage
            args_str = args_str.strip()
            # Try to find a valid JSON object within the string
            try:
                inputs = json.loads(args_str)
            except json.JSONDecodeError:
                # Try extracting just the {...} portion
                m = re.search(r'\{.*\}', args_str, re.DOTALL)
                if m:
                    try:
                        inputs = json.loads(m.group())
                    except Exception:
                        inputs = {}
                else:
                    inputs = {}
            calls.append({
                "id":     f"fb_{name}_{int(time.time()*1000)}",
                "name":   name,
                "inputs": inputs,
            })

    return calls if calls else None


# ── SubAgent ──────────────────────────────────────────────────────────────────

@dataclass
class SubAgent:
    name:          str
    description:   str
    system:        str
    tools:         list[dict]
    tool_handlers: dict
    max_rounds:    int = 8
    max_tokens:    int = 2048

    def run(self, task: str, verbose: bool = True) -> str:
        """Run the agent on a task. Always returns a string, never raises."""
        from groq import Groq
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            return "Error: GROQ_API_KEY not set."

        client          = Groq(api_key=api_key)
        history         = [{"role": "user", "content": task}]
        known_tools     = {t["name"] for t in self.tools}

        if verbose:
            print(f"\n  ┌─ agent:{self.name} ─ {task[:70]}…")

        for round_num in range(self.max_rounds):
            kwargs: dict = {
                "model":      "llama-3.3-70b-versatile",
                "max_tokens": self.max_tokens,
                "messages":   [{"role": "system", "content": self.system}] + history,
            }
            if self.tools:
                kwargs["tools"] = [
                    {"type": "function", "function": {
                        "name":        t["name"],
                        "description": t["description"],
                        "parameters":  t["input_schema"],
                    }} for t in self.tools
                ]
                kwargs["tool_choice"] = "auto"

            try:
                response = _retry_on_rate_limit(
                    client.chat.completions.create, **kwargs
                )
            except Exception as e:
                err = str(e)
                if verbose:
                    print(f"  └─ agent:{self.name} API error: {err[:120]}")
                return f"[{self.name}] API call failed: {err[:300]}"

            msg     = response.choices[0].message
            content = msg.content or ""

            # ── Proper tool_calls ─────────────────────────────────────────────
            if getattr(msg, "tool_calls", None):
                history.append({
                    "role":       "assistant",
                    "content":    content,
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in msg.tool_calls
                    ],
                })
                for tc in msg.tool_calls:
                    try:
                        inputs = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        inputs = {}
                    if verbose:
                        print(f"  │  tool: {tc.function.name}")
                    handler = self.tool_handlers.get(tc.function.name)
                    try:
                        result = handler(inputs) if handler else f"No handler for '{tc.function.name}'."
                    except Exception as e:
                        result = f"Tool error: {e}"
                    history.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                continue

            # ── Malformed tool-call tags in text content ──────────────────────
            if content and known_tools:
                fb_calls = _parse_malformed_tool_calls(content, known_tools)
                if fb_calls:
                    # Strip the tag text and keep any surrounding prose
                    clean = re.sub(
                        r'<function=[^>]*>.*?</function>|<function=[^>]*>|\b[a-z_]+\(\{[^)]*\}\)',
                        '', content, flags=re.DOTALL
                    ).strip()
                    if clean:
                        history.append({"role": "assistant", "content": clean})

                    for call in fb_calls:
                        if verbose:
                            print(f"  │  tool: {call['name']} (recovered)")
                        handler = self.tool_handlers.get(call["name"])
                        try:
                            result = handler(call["inputs"]) if handler else f"No handler for '{call['name']}'."
                        except Exception as e:
                            result = f"Tool error: {e}"
                        # Groq requires tool_call_id to match a prior assistant tool_calls entry.
                        # Since we synthesised this, append as a user message instead.
                        history.append({
                            "role":    "user",
                            "content": f"[Tool result for {call['name']}]: {result}",
                        })
                    continue

            # ── Plain text reply — done ───────────────────────────────────────
            if verbose:
                print(f"  └─ agent:{self.name} done ({round_num+1} round(s))")
            return content if content else "[No response from agent]"

        last = history[-1].get("content", "")[:200] if history else ""
        return f"[{self.name}] Max rounds reached. Last: {last}"


# ── AgentBus ──────────────────────────────────────────────────────────────────

class AgentBus:
    def __init__(self):
        self._agents: dict[str, SubAgent] = {}

    def register(self, agent: SubAgent):
        self._agents[agent.name] = agent

    def delegate(self, agent_name: str, task: str, verbose: bool = True) -> str:
        agent = self._agents.get(agent_name)
        if not agent:
            return f"Error: no sub-agent '{agent_name}'. Available: {', '.join(self._agents)}"
        return agent.run(task, verbose=verbose)

    def agent_schemas(self) -> list[dict]:
        return [
            {
                "name": f"delegate_to_{a.name}",
                "description": (
                    f"Delegate a task to the {a.name} specialist. "
                    f"{a.description} "
                    f"Include all context the specialist needs to complete the task independently."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type":        "string",
                            "description": "Full task description with all relevant context.",
                        },
                    },
                    "required": ["task"],
                },
            }
            for a in self._agents.values()
        ]

    def handle_delegation(self, tool_name: str, inputs: dict) -> tuple[str, bool] | None:
        if not tool_name.startswith("delegate_to_"):
            return None
        agent_name = tool_name[len("delegate_to_"):]
        task       = inputs.get("task", "").strip()
        if not task:
            return "Error: 'task' is required for delegation.", False
        return self.delegate(agent_name, task), False
