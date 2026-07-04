"""
Ava — tools/__init__.py  (updated: Tiers 2, 7, 14, 15, 16, 17, 18, 19, 20)
Merges ALL tool registries into one unified run_tool / tools_for_model.
"""

from .registry   import run_tool as _base_run, TOOL_REGISTRY, _MAP as _BASE_MAP
from .web_search import TIER7_TOOLS

try:
    from .system import SYSTEM_TOOLS
except Exception:
    SYSTEM_TOOLS = []

try:
    from .kali import KALI_TOOLS
except Exception:
    KALI_TOOLS = []

try:
    from .browser import BROWSER_TOOLS
except Exception:
    BROWSER_TOOLS = []

try:
    from .comms import COMMS_TOOLS
except Exception:
    COMMS_TOOLS = []

try:
    from .vision import VISION_TOOLS
except Exception:
    VISION_TOOLS = []

try:
    from automation.workflows import WORKFLOW_TOOLS
except Exception:
    WORKFLOW_TOOLS = []

try:
    from automation.autonomous import AUTONOMOUS_TOOLS
except Exception:
    AUTONOMOUS_TOOLS = []

_ALL_EXTRA = (
    TIER7_TOOLS + SYSTEM_TOOLS + KALI_TOOLS +
    BROWSER_TOOLS + COMMS_TOOLS + VISION_TOOLS +
    WORKFLOW_TOOLS + AUTONOMOUS_TOOLS
)
_ALL_MAP = {**_BASE_MAP, **{t["name"]: t for t in _ALL_EXTRA}}


def tools_for_model() -> list[dict]:
    """Return all tool schemas for the model."""
    all_tools = TOOL_REGISTRY + _ALL_EXTRA
    return [
        {
            "name":         t["name"],
            "description":  t["description"],
            "input_schema": t["input_schema"],
        }
        for t in all_tools
    ]


def run_tool(name: str, inputs: dict) -> tuple[str, bool]:
    """Execute any tool across all tiers."""
    tool = _ALL_MAP.get(name)
    if not tool:
        return f"Error: no tool named '{name}'.", False
    # The model sometimes calls zero-arg tools (e.g. see_me, screenshot) with
    # null/missing arguments instead of {}. Every handler assumes a dict it
    # can call .get() on, so normalise here rather than in every handler.
    if not isinstance(inputs, dict):
        inputs = {}
    try:
        result = tool["handler"](inputs)
    except Exception as e:
        result = f"Tool '{name}' failed: {e}"
    return result, tool.get("requires_confirmation", False)
