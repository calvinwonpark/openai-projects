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

def set_ids(response_id: str, vector_store_id: str):
    """Legacy function for single response. Use set_response_ids instead."""
    state = load_state()
    state["response_id"] = response_id
    state["vector_store_id"] = vector_store_id
    save_state(state)

def get_ids():
    """Legacy function for single response. Use get_response_ids instead."""
    state = load_state()
    return state.get("response_id"), state.get("vector_store_id")

def set_response_ids(responses: Dict[str, Dict[str, str]]):
    """
    Set IDs for multiple responses (replaces assistants).
    responses: {
        "tech": {"response_id": "...", "vector_store_id": "..."},
        "marketing": {"response_id": "...", "vector_store_id": "..."},
        "investor": {"response_id": "...", "vector_store_id": "..."}
    }
    """
    state = load_state()
    state["responses"] = responses
    save_state(state)

def get_response_ids(label: str) -> tuple:
    """
    Get response_id and vector_store_id for a specific label.
    Returns (response_id, vector_store_id) or (None, None) if not found.
    """
    state = load_state()
    responses = state.get("responses", {})
    response_data = responses.get(label, {})
    return response_data.get("response_id"), response_data.get("vector_store_id")

def get_all_response_ids() -> Dict[str, Dict[str, str]]:
    """Get all response IDs."""
    state = load_state()
    return state.get("responses", {})

# Legacy aliases for compatibility during migration
def set_assistant_ids(assistants: Dict[str, Dict[str, str]]):
    """Legacy alias - maps to set_response_ids."""
    set_response_ids(assistants)

def get_assistant_ids(label: str) -> tuple:
    """Legacy alias - maps to get_response_ids."""
    return get_response_ids(label)

def get_all_assistant_ids() -> Dict[str, Dict[str, str]]:
    """Legacy alias - maps to get_all_response_ids."""
    return get_all_response_ids()

