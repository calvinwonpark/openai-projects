from typing import Any, Dict, List, Set

from jsonschema import Draft202012Validator


def _tool_metrics(expected_tools: List[str], actual_tools: List[str]) -> Dict[str, float]:
    expected: Set[str] = set(expected_tools or [])
    actual: Set[str] = set(actual_tools or [])
    if not expected and not actual:
        return {"precision": 1.0, "recall": 1.0}
    if not actual:
        return {"precision": 0.0, "recall": 0.0 if expected else 1.0}
    tp = len(expected.intersection(actual))
    precision = tp / len(actual) if actual else 1.0
    recall = tp / len(expected) if expected else 1.0
    return {"precision": round(precision, 4), "recall": round(recall, 4)}


def score_case(case: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
    expected = case.get("expected", {})
    failures: List[str] = []

    refusal_obj = response.get("refusal")
    actual_refusal = None
    if isinstance(refusal_obj, dict) and "is_refusal" in refusal_obj:
        actual_refusal = bool(refusal_obj.get("is_refusal"))
    expected_refusal = expected.get("should_refuse")
    if expected_refusal is not None:
        if actual_refusal is None:
            failures.append("refusal missing in adapter output")
        elif bool(expected_refusal) != actual_refusal:
            failures.append(f"refusal mismatch expected={bool(expected_refusal)} got={actual_refusal}")

    expected_route = expected.get("route")
    actual_route = response.get("route") or response.get("routing", {}).get("label")
    if expected_route is not None and actual_route != expected_route:
        failures.append(f"route mismatch expected={expected_route} got={actual_route}")

    expected_tools = expected.get("tools") or []
    actual_tools = response.get("tool_names") or []
    tool_metrics = _tool_metrics(expected_tools, actual_tools)
    if not actual_refusal and expected_tools and set(expected_tools) != set(actual_tools):
        failures.append(f"tool mismatch expected={sorted(expected_tools)} got={sorted(actual_tools)}")

    output_schema = case.get("response_schema") or expected.get("output_schema")
    schema_mode = (case.get("schema_validation_mode") or "strict").lower()
    if output_schema and schema_mode != "off":
        parsed_obj = response.get("parsed")
        try:
            if parsed_obj is None:
                raise ValueError("parsed structured output is null")
            validator = Draft202012Validator(output_schema)
            errs = list(validator.iter_errors(parsed_obj))
            if errs:
                failures.extend([f"output schema violation: {e.message}" for e in errs[:3]])
        except Exception as exc:
            failures.append(f"output schema parse/validation failed: {exc}")
    if output_schema and response.get("schema_valid") is False:
        failures.append("adapter marked schema_valid=false")

    tools_schema = expected.get("tools_schema")
    if tools_schema:
        actual_tool_calls = response.get("tool_calls", [])
        try:
            validator = Draft202012Validator(tools_schema)
            errs = list(validator.iter_errors(actual_tool_calls))
            if errs:
                failures.append(f"tools schema violation: {errs[0].message}")
        except Exception as exc:
            failures.append(f"tools schema parse/validation failed: {exc}")

    if expected.get("citation_grounding"):
        citations = response.get("citations") or []
        contexts = response.get("retrieved_context") or case.get("retrieved_context") or []
        joined = "\n".join(str(c) for c in contexts)
        for idx, cit in enumerate(citations):
            quote = str(cit.get("quote", "")).strip() if isinstance(cit, dict) else ""
            if not quote:
                failures.append(f"citation[{idx}] missing quote")
            elif quote not in joined:
                failures.append(f"citation[{idx}] quote not grounded in retrieved_context")

    return {
        "passed": len(failures) == 0,
        "failures": failures,
        "tool_metrics": tool_metrics,
        "actual_route": actual_route,
        "actual_refusal": actual_refusal,
        "expected_tools": expected_tools,
        "actual_tools": actual_tools,
    }
