import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict


class HttpAppAdapter:
    name = "http_app"

    def run_case(self, case: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
        base_url = config.get("app_url") or "http://localhost:8000"
        endpoint = case.get("endpoint", "/chat_text")
        payload = case.get("request") or {"message": case.get("input", ""), "tenant_id": "evalkit"}
        req = urllib.request.Request(
            f"{base_url}{endpoint}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                telemetry = body.get("telemetry", {})
                if telemetry.get("latency_ms") is None:
                    telemetry["latency_ms"] = int((time.time() - started) * 1000)
                body["telemetry"] = telemetry
                body.setdefault("raw_text", str(body.get("answer", "")))
                body.setdefault("parsed", None)
                body.setdefault("schema_valid", True)
                body.setdefault("parse_error", None)
                body.setdefault("tool_calls", [])
                body.setdefault("route", body.get("routing", {}).get("label"))
                body.setdefault("latency_ms", telemetry.get("latency_ms"))
                body.setdefault("cost_estimate_usd", telemetry.get("cost_estimate_usd"))
                return body
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                body = json.loads(raw)
            except Exception:
                body = {"error": raw}
            body.setdefault("telemetry", {"latency_ms": int((time.time() - started) * 1000), "cost_estimate_usd": 0.0})
            body.setdefault("refusal", {"is_refusal": False, "reason": None})
            body.setdefault("routing", {"label": None})
            body.setdefault("tool_names", [])
            body.setdefault("tool_calls", [])
            body.setdefault("raw_text", "")
            body.setdefault("parsed", None)
            body.setdefault("schema_valid", False)
            body.setdefault("parse_error", body.get("error", "http_error"))
            body.setdefault("route", None)
            body.setdefault("latency_ms", body.get("telemetry", {}).get("latency_ms"))
            body.setdefault("cost_estimate_usd", body.get("telemetry", {}).get("cost_estimate_usd"))
            body.setdefault("usage", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "model": "unknown"})
            body["status_code"] = exc.code
            return body
