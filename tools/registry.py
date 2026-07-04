"""
Ava — tools/registry.py (Tier 2: Tool registry)
Core tools available to every turn, all tiers.
"""

import json
from pathlib import Path

def handle_think(inputs):
    """Internal scratchpad."""
    return f"[thinking] {inputs.get('content', '')}"

def handle_tell_user(inputs):
    """Send message to user."""
    return inputs.get('message', '')

def handle_remember(inputs):
    """Store in memory."""
    return f"Remembered: {inputs.get('key')} = {inputs.get('value')}"

def handle_recall(inputs):
    """Retrieve from memory."""
    return f"Recalled: {inputs.get('key')}"

def handle_feedback(inputs):
    """Rate a response."""
    return f"Feedback recorded: {inputs.get('target')} = {inputs.get('score')}/5"

def handle_add_note(inputs):
    """Add a note to memory."""
    return f"Note added: {inputs.get('content', '')}"

def handle_get_notes(inputs):
    """Retrieve notes from memory."""
    return "Notes retrieved"

TOOL_REGISTRY = [
    {
        'name': 'think',
        'description': 'Scratchpad for internal reasoning. What you write here is visible only to me, not the user.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'content': {
                    'type': 'string',
                    'description': 'Your internal thought process.'
                }
            },
            'required': ['content']
        },
        'handler': handle_think,
        'requires_confirmation': False
    },
    {
        'name': 'tell_user',
        'description': 'Send a message to the user in the conversation.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'message': {
                    'type': 'string',
                    'description': 'The message to send.'
                }
            },
            'required': ['message']
        },
        'handler': handle_tell_user,
        'requires_confirmation': False
    },
    {
        'name': 'remember',
        'description': 'Store something in persistent memory so you remember it across sessions.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'key': {
                    'type': 'string',
                    'description': 'Topic or category key.'
                },
                'value': {
                    'type': 'string',
                    'description': 'What to remember.'
                }
            },
            'required': ['key', 'value']
        },
        'handler': handle_remember,
        'requires_confirmation': False
    },
    {
        'name': 'recall',
        'description': 'Retrieve something from persistent memory.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'key': {
                    'type': 'string',
                    'description': 'Topic or category key to recall.'
                }
            },
            'required': ['key']
        },
        'handler': handle_recall,
        'requires_confirmation': False
    },
    {
        'name': 'feedback',
        'description': 'Rate my response or a tool call so I learn from it.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'target': {
                    'type': 'string',
                    'description': 'What you\'re rating: tool name, response quality, etc.'
                },
                'score': {
                    'type': 'number',
                    'description': '1-5 score. 1=bad, 5=perfect.',
                    'minimum': 1,
                    'maximum': 5
                },
                'comment': {
                    'type': 'string',
                    'description': 'Optional explanation.'
                }
            },
            'required': ['target', 'score']
        },
        'handler': handle_feedback,
        'requires_confirmation': False
    },
    {
        'name': 'add_note',
        'description': 'Add a note to memory.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'content': {
                    'type': 'string',
                    'description': 'Note content.'
                }
            },
            'required': ['content']
        },
        'handler': handle_add_note,
        'requires_confirmation': False
    },
    {
        'name': 'get_notes',
        'description': 'Retrieve notes from memory.',
        'input_schema': {
            'type': 'object',
            'properties': {}
        },
        'handler': handle_get_notes,
        'requires_confirmation': False
    }
]

_MAP = {tool['name']: tool for tool in TOOL_REGISTRY}

def run_tool(name, inputs):
    """Run a tool from the base registry."""
    tool = _MAP.get(name)
    if not tool:
        return f"Error: tool '{name}' not found in registry.", False
    try:
        result = tool['handler'](inputs)
    except Exception as e:
        result = f"Tool '{name}' failed: {e}"
    return result, tool.get('requires_confirmation', False)

def _load_goal():
    """Load current goal from data/workflow_state.json"""
    try:
        path = Path(__file__).parent.parent / "data" / "workflow_state.json"
        if path.exists():
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('goal', {'current': 0, 'target': 0, 'deadline': ''})
    except Exception:
        pass
    return {'current': 0, 'target': 0, 'deadline': ''}

