import time
from typing import Any, Dict

from evalkit.scoring.metrics import estimate_cost_usd


class OfflineAdapter:
    name = "offline"

    def run_case(self, case: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        started = time.time()
        synthetic = case.get("offline_response", {})
        answer = synthetic.get("answer", case.get("input", ""))
        route = synthetic.get("route") or case.get("expected", {}).get("route")
        refusal = bool(synthetic.get("refusal", case.get("expected", {}).get("should_refuse", False)))
        tool_names = synthetic.get("tool_names", case.get("expected", {}).get("tools", []))
        usage = synthetic.get("usage", {"input_tokens": 50, "output_tokens": 120, "total_tokens": 170, "model": "gpt-4o-mini"})
        telemetry = synthetic.get(
            "telemetry",
            {
                "latency_ms": int((time.time() - started) * 1000),
                "cost_estimate_usd": estimate_cost_usd(usage.get("input_tokens", 0), usage.get("output_tokens", 0), usage.get("model", "gpt-4o-mini")),
            },
        )
        parsed = None
        raw_text = str(answer)
        if case.get("requires_structured_output") and case.get("response_schema"):
            parsed = {
                "route": route or "unknown",
                "answer": str(answer),
                "refusal": {"is_refusal": refusal, "reason": "OFFLINE_REFUSAL" if refusal else None},
            }
            raw_text = str(parsed)
        return {
            "raw_text": raw_text,
            "parsed": parsed,
            "schema_valid": True,
            "parse_error": None,
            "tool_calls": [{"name": t, "arguments": None} for t in (tool_names or [])],
            "answer": answer,
            "route": route,
            "routing": {"label": route},
            "tool_names": tool_names or [],
            "refusal": {"is_refusal": refusal, "reason": "OFFLINE_REFUSAL" if refusal else None},
            "usage": usage,
            "latency_ms": telemetry.get("latency_ms"),
            "cost_estimate_usd": telemetry.get("cost_estimate_usd"),
            "telemetry": telemetry,
            "citations": synthetic.get("citations", []),
            "retrieved_context": synthetic.get("retrieved_context", case.get("retrieved_context", [])),
        }
