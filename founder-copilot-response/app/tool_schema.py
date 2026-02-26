import json
from typing import Any, Dict, List, Tuple

from jsonschema import Draft202012Validator

FILE_SEARCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"const": "file_search"},
        "vector_store_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        },
    },
    "required": ["type"],
}

CODE_INTERPRETER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "type": {"const": "code_interpreter"},
        "container": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "type": {"type": "string"},
                "file_ids": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
            },
            "required": ["type"],
        },
    },
    "required": ["type"],
}

TOOL_SCHEMA = {"oneOf": [FILE_SEARCH_SCHEMA, CODE_INTERPRETER_SCHEMA]}
_VALIDATOR = Draft202012Validator(TOOL_SCHEMA)


def validate_tool_args(tools: List[Dict[str, Any]]) -> Tuple[bool, str]:
    if tools is None:
        return True, ""
    if not isinstance(tools, list):
        return False, "tools must be a list"

    for idx, tool in enumerate(tools):
        errors = sorted(_VALIDATOR.iter_errors(tool), key=lambda e: e.path)
        if errors:
            first = errors[0]
            location = ".".join(str(x) for x in first.path) or "<root>"
            return False, f"tools[{idx}] invalid at {location}: {first.message}"
    return True, ""


def tool_count(tools: List[Dict[str, Any]]) -> int:
    return len(tools) if isinstance(tools, list) else 0


def tool_names(tools: List[Dict[str, Any]]) -> List[str]:
    if not isinstance(tools, list):
        return []
    out = []
    for tool in tools:
        t = tool.get("type") if isinstance(tool, dict) else None
        if isinstance(t, str):
            out.append(t)
    return out


def schema_error_payload(tool_name: str, error: str) -> Dict[str, Any]:
    return {
        "error": "TOOL_SCHEMA_VALIDATION_ERROR",
        "schema_valid": False,
        "tool_name": tool_name,
        "details": error,
    }


def schema_error_log(tool_name: str, error: str) -> str:
    return json.dumps(
        {"schema_valid": False, "tool_name": tool_name, "error": error},
        ensure_ascii=False,
    )
