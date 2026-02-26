import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
EVALS_DIR = os.path.dirname(__file__)
DATASET_REL_PATH = "evals/datasets/workflow_eval.jsonl"
DATASET_PATH = os.path.join(EVALS_DIR, "datasets", "workflow_eval.jsonl")
LEGACY_DATASET_PATH = os.path.join(EVALS_DIR, "workflow_eval.jsonl")
BASELINE_PATH = os.path.join(EVALS_DIR, "baselines", "workflow_baseline.json")
OUT_RESULTS_PATH = os.path.join(EVALS_DIR, "out", "last_run_results.json")


def _is_timeout_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "timed out" in msg or "timeout" in msg


def _ensure_dirs():
    os.makedirs(os.path.join(EVALS_DIR, "baselines"), exist_ok=True)
    os.makedirs(os.path.join(EVALS_DIR, "out"), exist_ok=True)
    os.makedirs(os.path.join(EVALS_DIR, "datasets"), exist_ok=True)


def _resolve_dataset_path() -> str:
    if os.path.exists(DATASET_PATH):
        return DATASET_PATH
    return LEGACY_DATASET_PATH


def _to_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _to_int(v: Any) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except Exception:
        return None


def _estimate_cost_usd(input_tokens: int, output_tokens: int, model: Optional[str]) -> float:
    in_rate_per_million = 5.0
    out_rate_per_million = 15.0
    model_name = (model or os.getenv("OPENAI_MODEL", "gpt-4o")).lower()
    if "mini" in model_name:
        in_rate_per_million = 0.2
        out_rate_per_million = 0.6
    return round((input_tokens / 1_000_000) * in_rate_per_million + (output_tokens / 1_000_000) * out_rate_per_million, 6)


def _percentile(sorted_values: List[float], pct: float) -> Optional[float]:
    if not sorted_values:
        return None
    n = len(sorted_values)
    idx = max(0, min(n - 1, math.ceil(pct * n) - 1))
    return float(sorted_values[idx])


def _aggregate_metrics(records: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    lat = sorted([float(r["latency_ms"]) for r in records if r.get("latency_ms") is not None])
    cost = sorted([float(r["cost_estimate_usd"]) for r in records if r.get("cost_estimate_usd") is not None])
    tokens = sorted([float(r["tokens_total"]) for r in records if r.get("tokens_total") is not None])
    return {
        "count": len(records),
        "latency_ms_p50": _percentile(lat, 0.50),
        "latency_ms_p95": _percentile(lat, 0.95),
        "cost_usd_mean": round(sum(cost) / len(cost), 6) if cost else None,
        "cost_usd_p95": _percentile(cost, 0.95),
        "tokens_total_mean": round(sum(tokens) / len(tokens), 2) if tokens else None,
        "tokens_total_p95": _percentile(tokens, 0.95),
    }


def load_dataset(path: str) -> List[Dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _post_json_with_retry(url: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    attempts = 0
    max_attempts = 5
    while attempts < max_attempts:
        attempts += 1
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                return resp.status, body
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                body = json.loads(raw)
            except Exception:
                body = {"error": raw}
            if exc.code == 429 and attempts < max_attempts:
                time.sleep(1.5 * attempts)
                continue
            if exc.code == 500 and attempts < max_attempts:
                time.sleep(1.0 * attempts)
                continue
            return exc.code, body
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempts < max_attempts and _is_timeout_error(exc):
                time.sleep(1.5 * attempts)
                continue
            raise


def call_chat_text(row: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    payload = {"message": row["message"], "tenant_id": "eval-tenant"}
    if "tools" in row:
        payload["tools_override"] = row["tools"]
    return _post_json_with_retry(f"{API_BASE_URL}/chat_text", payload)


def call_workflow_failure_case(row: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    payload = {
        "message": row["message"],
        "tenant_id": "eval-tenant",
        "simulate_failure_mode": row.get("simulate_failure_mode"),
    }
    return _post_json_with_retry(f"{API_BASE_URL}/workflow/execute", payload)


def evaluate_row(row: Dict[str, Any], status: int, body: Dict[str, Any]) -> List[str]:
    failures: List[str] = []
    invalid_schema = bool(row.get("invalid_schema"))
    is_failure_injection = bool(row.get("simulate_failure_mode"))

    if invalid_schema:
        if status < 400:
            failures.append("expected schema validation failure status >= 400")
        if body.get("schema_valid", True) is not False:
            failures.append("expected schema_valid=false on invalid schema case")
        return failures

    if status >= 400:
        failures.append(f"unexpected HTTP status {status}")
        return failures

    expected_route = row["expected_route"]
    actual_route = body.get("routing", {}).get("label")
    if is_failure_injection:
        actual_route = body.get("route", {}).get("label")
    if actual_route != expected_route:
        failures.append(f"route mismatch: expected={expected_route} got={actual_route}")

    should_refuse = bool(row.get("should_refuse"))
    actual_refusal = bool(body.get("refusal", {}).get("is_refusal"))
    if should_refuse != actual_refusal:
        failures.append(f"refusal mismatch: expected={should_refuse} got={actual_refusal}")

    expected_tools = row.get("expected_tools") or []
    actual_tools = body.get("tool_names") or []
    if not should_refuse and sorted(expected_tools) != sorted(actual_tools):
        failures.append(f"tool selection mismatch: expected={sorted(expected_tools)} got={sorted(actual_tools)}")
    if should_refuse and actual_tools:
        failures.append(f"refusal case should not execute tools, got={sorted(actual_tools)}")

    if body.get("schema_valid") is not True:
        failures.append("schema_valid should be true for valid cases")

    if row.get("expect_warning") and not body.get("warning"):
        failures.append("expected warning flag but missing")

    if not should_refuse:
        if is_failure_injection:
            if body.get("tool_calls", 0) < 1:
                failures.append("expected at least one tool call in non-refusal case")
        else:
            if len(body.get("tool_names") or []) < 1:
                failures.append("expected at least one tool in non-refusal case")

    return failures


def _extract_perf_record(row: Dict[str, Any], status: int, body: Dict[str, Any]) -> Dict[str, Any]:
    is_failure_injection = bool(row.get("simulate_failure_mode"))
    route = body.get("routing", {}).get("label")
    if is_failure_injection:
        route = body.get("route", {}).get("label")
    refusal = bool(body.get("refusal", {}).get("is_refusal"))

    telemetry = body.get("telemetry", {}) if isinstance(body, dict) else {}
    usage = body.get("usage", {}) if isinstance(body, dict) else {}
    tokens_obj = body.get("tokens", {}) if isinstance(body, dict) else {}

    input_tokens = _to_int(usage.get("input_tokens"))
    output_tokens = _to_int(usage.get("output_tokens"))
    total_tokens = _to_int(usage.get("total_tokens"))
    if total_tokens is None:
        in_from_tokens = _to_int(tokens_obj.get("input"))
        out_from_tokens = _to_int(tokens_obj.get("output"))
        if in_from_tokens is not None:
            input_tokens = in_from_tokens
        if out_from_tokens is not None:
            output_tokens = out_from_tokens
        if input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens

    latency_ms = _to_float(telemetry.get("latency_ms"))
    if latency_ms is None:
        latency_ms = _to_float(body.get("latency_ms"))

    cost_usd = _to_float(telemetry.get("cost_estimate_usd"))
    if cost_usd is None:
        cost_usd = _to_float(body.get("cost_estimate_usd"))
    if cost_usd is None and input_tokens is not None and output_tokens is not None:
        cost_usd = _estimate_cost_usd(input_tokens, output_tokens, usage.get("model") or os.getenv("OPENAI_MODEL", "gpt-4o"))

    return {
        "id": row.get("id"),
        "status": status,
        "route": route,
        "is_refusal": refusal,
        "latency_ms": latency_ms,
        "tokens_total": total_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_estimate_usd": cost_usd,
    }


def _compute_aggregate_bundle(per_case_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    succeeded = [r for r in per_case_results if int(r.get("status", 500)) < 400]
    non_refusal = [r for r in succeeded if not r.get("is_refusal")]
    refusal_only = [r for r in succeeded if r.get("is_refusal")]

    by_route: Dict[str, Dict[str, Any]] = {}
    for route in ["tech", "marketing", "investor"]:
        route_rows = [r for r in non_refusal if r.get("route") == route]
        by_route[route] = _aggregate_metrics(route_rows)

    refusal_summary = {
        "count": len(refusal_only),
        "latency_ms_mean": round(sum(r["latency_ms"] for r in refusal_only if r.get("latency_ms") is not None) / len([r for r in refusal_only if r.get("latency_ms") is not None]), 2)
        if any(r.get("latency_ms") is not None for r in refusal_only)
        else None,
        "cost_usd_mean": round(sum(r["cost_estimate_usd"] for r in refusal_only if r.get("cost_estimate_usd") is not None) / len([r for r in refusal_only if r.get("cost_estimate_usd") is not None]), 6)
        if any(r.get("cost_estimate_usd") is not None for r in refusal_only)
        else None,
    }

    return {
        "non_refusal_overall": _aggregate_metrics(non_refusal),
        "non_refusal_by_route": by_route,
        "refusal_overall": refusal_summary,
    }


def _load_baseline(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, payload: Dict[str, Any]):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _get_nested(d: Dict[str, Any], keys: List[str]) -> Optional[float]:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return _to_float(cur)


def _check_regression(current: Dict[str, Any], baseline: Dict[str, Any]) -> List[str]:
    failures: List[str] = []

    def _compare(metric_path: List[str], multiplier: float, absolute_cap: Optional[float] = None):
        cur = _get_nested(current, metric_path)
        base = _get_nested(baseline, metric_path)
        name = ".".join(metric_path)
        if cur is None or base is None:
            failures.append(f"missing metric for comparison: {name}")
            return
        if absolute_cap is not None and cur > absolute_cap:
            failures.append(f"{name} regression: current={cur:.4f} exceeds absolute cap {absolute_cap}")
            return
        if base <= 0:
            failures.append(f"baseline metric invalid (<=0): {name}={base}")
            return
        if cur > base * multiplier:
            failures.append(f"{name} regression: current={cur:.4f} baseline={base:.4f} threshold={base * multiplier:.4f}")

    _compare(["non_refusal_overall", "latency_ms_p95"], 1.35, 3000.0)
    _compare(["non_refusal_overall", "cost_usd_mean"], 1.25)
    _compare(["non_refusal_overall", "cost_usd_p95"], 1.30)
    _compare(["non_refusal_overall", "tokens_total_p95"], 1.25)
    for route in ["tech", "marketing", "investor"]:
        _compare(["non_refusal_by_route", route, "latency_ms_p95"], 1.35)

    return failures


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run workflow evals with perf regression gate.")
    parser.add_argument("--update-baseline", action="store_true", help="Write current aggregate metrics to baseline file.")
    return parser.parse_args()


def main():
    args = _parse_args()
    _ensure_dirs()
    dataset_path = _resolve_dataset_path()
    rows = load_dataset(dataset_path)
    failed = 0
    details: List[Dict[str, Any]] = []
    confusion: Dict[str, Dict[str, int]] = {}
    per_case_results: List[Dict[str, Any]] = []

    for row in rows:
        row_id = row["id"]
        try:
            time.sleep(0.25)
            if row.get("simulate_failure_mode"):
                status, body = call_workflow_failure_case(row)
            else:
                status, body = call_chat_text(row)

            failures = evaluate_row(row, status, body)
            perf = _extract_perf_record(row, status, body)
            per_case_results.append(perf)

            expected_route = row.get("expected_route", "unknown")
            actual_route = perf.get("route") or "unknown"
            if not row.get("invalid_schema") and status < 400:
                confusion.setdefault(expected_route, {})
                confusion[expected_route][actual_route] = confusion[expected_route].get(actual_route, 0) + 1

            if failures:
                failed += 1
                details.append({"id": row_id, "failures": failures, "status": status, "output": body})
                print(f"[FAIL] {row_id}: {'; '.join(failures)}")
            else:
                print(f"[PASS] {row_id}")
        except urllib.error.URLError as exc:
            failed += 1
            details.append({"id": row_id, "failures": [f"request error: {exc}"]})
            per_case_results.append({"id": row_id, "status": 599, "route": None, "is_refusal": None, "latency_ms": None, "tokens_total": None, "input_tokens": None, "output_tokens": None, "cost_estimate_usd": None})
            print(f"[FAIL] {row_id}: request error: {exc}")
        except Exception as exc:
            failed += 1
            details.append({"id": row_id, "failures": [f"unexpected error: {exc}"]})
            per_case_results.append({"id": row_id, "status": 599, "route": None, "is_refusal": None, "latency_ms": None, "tokens_total": None, "input_tokens": None, "output_tokens": None, "cost_estimate_usd": None})
            print(f"[FAIL] {row_id}: unexpected error: {exc}")

    aggregate_metrics = _compute_aggregate_bundle(per_case_results)
    _write_json(
        OUT_RESULTS_PATH,
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset": DATASET_REL_PATH,
            "api_base_url": API_BASE_URL,
            "results": per_case_results,
            "metrics": aggregate_metrics,
        },
    )

    baseline_failures: List[str] = []
    non_refusal_count = int((aggregate_metrics.get("non_refusal_overall") or {}).get("count") or 0)
    if args.update_baseline:
        if failed > 0 or non_refusal_count == 0:
            print("\nRefusing to update baseline because eval run is not healthy.")
            print("Fix failing cases and ensure server is reachable, then rerun:")
            print("  python evals/run.py --update-baseline")
            sys.exit(1)
        _write_json(
            BASELINE_PATH,
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "dataset": DATASET_REL_PATH,
                "metrics": aggregate_metrics,
            },
        )
        print(f"\nBaseline updated: {BASELINE_PATH}")
    else:
        baseline = _load_baseline(BASELINE_PATH)
        if baseline is None:
            print("\nBaseline missing. Run:")
            print("  python evals/run.py --update-baseline")
            print(f"Then commit {BASELINE_PATH}")
            sys.exit(1)
        baseline_metrics = baseline.get("metrics", {})
        baseline_failures = _check_regression(aggregate_metrics, baseline_metrics)
        if baseline_failures:
            failed += len(baseline_failures)
            details.append({"id": "BASELINE_REGRESSION", "failures": baseline_failures})
            print("\n[FAIL] Baseline regression gate:")
            for f in baseline_failures:
                print(f" - {f}")
        else:
            print("\n[PASS] Baseline regression gate")

    total = len(rows)
    passed = total - (failed - len(baseline_failures))
    print(f"\nSummary: total={total} passed={passed} failed={failed - len(baseline_failures)}")
    print("\nRouting confusion matrix (expected_route x actual_route):")
    print(json.dumps(confusion, ensure_ascii=False, indent=2, sort_keys=True))
    print("\nAggregate metrics:")
    print(json.dumps(aggregate_metrics, ensure_ascii=False, indent=2, sort_keys=True))
    print(f"\nPer-case results written to: {OUT_RESULTS_PATH}")

    if failed:
        print("\nFailure details:")
        print(json.dumps(details, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
