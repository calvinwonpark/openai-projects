import json, os
from typing import Dict

STATE_DIR = os.getenv("STATE_DIR", "state")
STATE_PATH = os.path.join(STATE_DIR, "copilot_state.json")

def _ensure_dir():
    os.makedirs(STATE_DIR, exist_ok=True)

def load_state():
    _ensure_dir()
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    return {}

def save_state(d):
    _ensure_dir()
    with open(STATE_PATH, "w") as f:
        json.dump(d, f, indent=2)

def set_ids(assistant_id: str, vector_store_id: str):
    """Legacy function for single assistant. Use set_assistant_ids instead."""
    state = load_state()
    state["assistant_id"] = assistant_id
    state["vector_store_id"] = vector_store_id
    save_state(state)

def get_ids():
    """Legacy function for single assistant. Use get_assistant_ids instead."""
    state = load_state()
    return state.get("assistant_id"), state.get("vector_store_id")

def set_assistant_ids(assistants: Dict[str, Dict[str, str]]):
    """
    Set IDs for multiple assistants.
    assistants: {
        "tech": {"assistant_id": "...", "vector_store_id": "..."},
        "marketing": {"assistant_id": "...", "vector_store_id": "..."},
        "investor": {"assistant_id": "...", "vector_store_id": "..."}
    }
    """
    state = load_state()
    state["assistants"] = assistants
    save_state(state)

def get_assistant_ids(label: str) -> tuple:
    """
    Get assistant_id and vector_store_id for a specific label.
    Returns (assistant_id, vector_store_id) or (None, None) if not found.
    """
    state = load_state()
    assistants = state.get("assistants", {})
    assistant_data = assistants.get(label, {})
    return assistant_data.get("assistant_id"), assistant_data.get("vector_store_id")

def get_all_assistant_ids() -> Dict[str, Dict[str, str]]:
    """Get all assistant IDs."""
    state = load_state()
    return state.get("assistants", {})
