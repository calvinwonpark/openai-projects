import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from evalkit.adapters._fixtures import TOOL_CALL_FIXTURES
from evalkit.adapters.openai_responses import _parse_tool_calls_from_dump


def _arg_kind(value):
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, str):
        return "str"
    if value is None:
        return "none"
    return type(value).__name__


def run():
    for fixture in TOOL_CALL_FIXTURES:
        parsed = _parse_tool_calls_from_dump(fixture["dump"])
        names = [c.get("name") for c in parsed if c.get("name")]
        assert names == fixture["expected_names"], f"{fixture['name']}: names mismatch {names} != {fixture['expected_names']}"
        for call in parsed:
            name = call["name"]
            expected_kind = fixture["expected_args_type"].get(name)
            if expected_kind:
                got_kind = _arg_kind(call.get("arguments"))
                assert got_kind == expected_kind, f"{fixture['name']}[{name}]: arg type {got_kind} != {expected_kind}"
            assert "raw" in call and isinstance(call["raw"], dict), f"{fixture['name']}[{name}]: raw missing"
    print("openai parsing assertions passed")


if __name__ == "__main__":
    run()
