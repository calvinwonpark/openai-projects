import json, os

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
    state = load_state()
    state["assistant_id"] = assistant_id
    state["vector_store_id"] = vector_store_id
    save_state(state)

def get_ids():
    state = load_state()
    return state.get("assistant_id"), state.get("vector_store_id")
