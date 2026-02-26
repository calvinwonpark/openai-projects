import json
import os
import time
from typing import Any, Dict, List, Optional

from jsonschema import Draft202012Validator
from openai import OpenAI

from evalkit.scoring.metrics import estimate_cost_usd
from evalkit.scoring.schemas import ROUTING_SCHEMA


def _extract_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if isinstance(text, str) and text:
        return text
    out = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            if getattr(content, "type", None) == "output_text":
                out.append(getattr(content, "text", ""))
    return "\n".join(t for t in out if t).strip()


def _response_dump(response: Any) -> Dict[str, Any]:
    if hasattr(response, "model_dump"):
        try:
            return response.model_dump()
        except Exception:
            pass
    if hasattr(response, "model_dump_json"):
        try:
            return json.loads(response.model_dump_json())
        except Exception:
            pass
    return response if isinstance(response, dict) else {}


def _usage(response: Any) -> Dict[str, Any]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "model": "unknown"}
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or (input_tokens + output_tokens))
    model = str(getattr(response, "model", "unknown"))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "model": model,
    }


def _maybe_parse_json_arg(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return value
    if not ((s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))):
        return value
    try:
        return json.loads(s)
    except Exception:
        return value


def _parse_tool_calls_from_dump(dump: Dict[str, Any]) -> List[Dict[str, Any]]:
    supported_types = {
        "tool_call",
        "function_call",
        "file_search_call",
        "web_search_call",
        "computer_call",
        "code_interpreter_call",
        "tool",
    }
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for item in dump.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", ""))
        if item_type and item_type not in supported_types and not (
            item.get("name") or item.get("tool_name") or isinstance(item.get("function"), dict) or isinstance(item.get("call"), dict)
        ):
            continue

        name = (
            item.get("name")
            or item.get("tool_name")
            or (item.get("function") or {}).get("name")
            or (item.get("call") or {}).get("name")
        )
        arguments = (
            item.get("arguments")
            if "arguments" in item
            else (item.get("function") or {}).get("arguments")
            if isinstance(item.get("function"), dict)
            else None
        )
        if arguments is None and isinstance(item.get("call"), dict):
            arguments = item["call"].get("arguments")
        if arguments is None:
            arguments = item.get("input")
        arguments = _maybe_parse_json_arg(arguments)
        if not name:
            continue

        stable_args = json.dumps(arguments, ensure_ascii=False, sort_keys=True) if isinstance(arguments, dict) else str(arguments)
        stable_key = (str(name), stable_args)
        if stable_key in seen:
            continue
        seen.add(stable_key)
        normalized.append({"name": str(name), "arguments": arguments, "raw": item})
    return normalized


def _parse_structured(raw_text: str, response_dump: Dict[str, Any]) -> Dict[str, Any]:
    # Prefer parsed payloads when available from SDK.
    for key in ("output_parsed", "parsed"):
        val = response_dump.get(key)
        if isinstance(val, dict):
            return {"parsed": val, "parse_error": None}
    try:
        parsed = json.loads(raw_text) if raw_text else None
        if isinstance(parsed, dict):
            return {"parsed": parsed, "parse_error": None}
        return {"parsed": None, "parse_error": "structured output is not a JSON object"}
    except Exception as exc:
        return {"parsed": None, "parse_error": str(exc)}


class OpenAIResponsesAdapter:
    name = "openai"

    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def run_case(self, case: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        started = time.time()
        model = case.get("model") or config.get("model") or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        req: Dict[str, Any] = {"model": model, "input": case.get("input", "")}
        if case.get("temperature") is not None:
            req["temperature"] = float(case.get("temperature"))
        if case.get("tools"):
            req["tools"] = case["tools"]

        requires_structured = bool(case.get("requires_structured_output"))
        response_schema = case.get("response_schema")
        if requires_structured and not response_schema and (
            case.get("expected", {}).get("route") is not None or case.get("expected", {}).get("should_refuse") is not None
        ):
            response_schema = ROUTING_SCHEMA

        if requires_structured and response_schema:
            req["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": str(case.get("schema_name") or f"{case.get('id', 'case')}_schema"),
                    "schema": response_schema,
                    "strict": True,
                },
            }
        elif case.get("response_format"):
            req["response_format"] = case["response_format"]

        response = self.client.responses.create(**req)
        dump = _response_dump(response)
        usage = _usage(response)
        raw_text = _extract_text(response)
        tool_calls = _parse_tool_calls_from_dump(dump)
        parsed_payload = _parse_structured(raw_text, dump) if requires_structured else {"parsed": None, "parse_error": None}
        parsed = parsed_payload.get("parsed")
        parse_error = parsed_payload.get("parse_error")
        schema_errors: List[Dict[str, str]] = []
        schema_valid = True
        if requires_structured and response_schema:
            if parsed is None:
                schema_valid = False
            else:
                validator = Draft202012Validator(response_schema)
                errs = list(validator.iter_errors(parsed))
                if errs:
                    schema_valid = False
                    for err in errs[:3]:
                        path = ".".join(str(p) for p in list(err.path)) or "$"
                        schema_errors.append({"path": path, "message": err.message})

        route: Optional[str] = None
        refusal = None
        answer = raw_text
        if isinstance(parsed, dict):
            route = parsed.get("route")
            if isinstance(parsed.get("refusal"), dict):
                refusal = {
                    "is_refusal": bool(parsed["refusal"].get("is_refusal", False)),
                    "reason": parsed["refusal"].get("reason"),
                }
            answer = str(parsed.get("answer", raw_text))
        elif requires_structured:
            refusal = {"is_refusal": False, "reason": None}
            schema_valid = False if response_schema else schema_valid

        latency_ms = int((time.time() - started) * 1000)
        cost = estimate_cost_usd(usage["input_tokens"], usage["output_tokens"], usage["model"])
        tool_names = []
        seen = set()
        for call in tool_calls:
            name = str(call.get("name", "")).strip()
            if name and name not in seen:
                seen.add(name)
                tool_names.append(name)

        return {
            "raw_text": raw_text,
            "answer": answer,
            "parsed": parsed,
            "schema_valid": schema_valid,
            "schema_errors": schema_errors[:3],
            "parse_error": parse_error,
            "response_id": dump.get("id"),
            "model": usage.get("model"),
            "tool_calls": tool_calls,
            "tool_names": tool_names,
            "route": route,
            "routing": {"label": route},
            "refusal": refusal,
            "usage": usage,
            "latency_ms": latency_ms,
            "cost_estimate_usd": cost,
            "telemetry": {"latency_ms": latency_ms, "cost_estimate_usd": cost},
            "citations": [],
            "retrieved_context": case.get("retrieved_context", []),
            "raw_response": dump,
        }
