TOOL_CALL_FIXTURES = [
    {
        "name": "tool_call+json_args",
        "dump": {
            "output": [
                {"type": "tool_call", "name": "file_search", "arguments": "{\"query\":\"pricing\"}"},
            ]
        },
        "expected_names": ["file_search"],
        "expected_args_type": {"file_search": "dict"},
    },
    {
        "name": "function_call_nested",
        "dump": {
            "output": [
                {"type": "function_call", "function": {"name": "code_interpreter", "arguments": {"code": "print(1)"}}},
            ]
        },
        "expected_names": ["code_interpreter"],
        "expected_args_type": {"code_interpreter": "dict"},
    },
    {
        "name": "call_wrapper_string_args",
        "dump": {
            "output": [
                {"type": "tool", "call": {"name": "web_search", "arguments": "{\"q\":\"openai\"}"}},
            ]
        },
        "expected_names": ["web_search"],
        "expected_args_type": {"web_search": "dict"},
    },
    {
        "name": "tool_name_with_input",
        "dump": {
            "output": [
                {"type": "file_search_call", "tool_name": "file_search", "input": {"query": "refund"}},
            ]
        },
        "expected_names": ["file_search"],
        "expected_args_type": {"file_search": "dict"},
    },
    {
        "name": "code_interpreter_call_raw_string",
        "dump": {
            "output": [
                {"type": "code_interpreter_call", "name": "code_interpreter", "arguments": "non-json-args"},
            ]
        },
        "expected_names": ["code_interpreter"],
        "expected_args_type": {"code_interpreter": "str"},
    },
    {
        "name": "dedupe_exact_duplicate",
        "dump": {
            "output": [
                {"type": "tool_call", "name": "file_search", "arguments": "{\"query\":\"pricing\"}"},
                {"type": "tool_call", "name": "file_search", "arguments": "{\"query\":\"pricing\"}"},
            ]
        },
        "expected_names": ["file_search"],
        "expected_args_type": {"file_search": "dict"},
    },
]
