ROUTING_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "route": {"type": "string", "enum": ["tech", "marketing", "investor", "unknown"]},
        "answer": {"type": "string"},
        "refusal": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "is_refusal": {"type": "boolean"},
                "reason": {"type": ["string", "null"]},
            },
            "required": ["is_refusal", "reason"],
        },
    },
    "required": ["route", "answer", "refusal"],
}
