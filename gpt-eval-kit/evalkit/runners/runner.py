import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from evalkit.adapters.http_app import HttpAppAdapter
from evalkit.adapters.offline import OfflineAdapter
from evalkit.adapters.openai_responses import OpenAIResponsesAdapter
from evalkit.reporting.diffing import build_thresholds, compare_metrics
from evalkit.reporting.reporter import make_diff_markdown, make_markdown_report
from evalkit.scoring.deterministic import score_case
from evalkit.scoring.metrics import aggregate_perf, mean
from evalkit.scoring.rubric_judge import maybe_rubric_score
from evalkit.scoring.schemas import ROUTING_SCHEMA


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_json(path: str, payload: Dict[str, Any]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _append_jsonl(path: str, row: Dict[str, Any]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _adapter(mode: str):
    if mode == "offline":
        return OfflineAdapter()
    if mode == "http_app":
        return HttpAppAdapter()
    if mode == "openai":
        return OpenAIResponsesAdapter()
    raise ValueError(f"unsupported mode: {mode}")


def _suite_name_from_path(suite_path: str) -> str:
    return Path(suite_path).stem


def _load_suite_defaults(suite_path: str) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {}
    sidecar = f"{suite_path}.config.json"
    if os.path.exists(sidecar):
        with open(sidecar, "r", encoding="utf-8") as f:
            loaded = json.load(f)
            if isinstance(loaded, dict):
                defaults.update(loaded)
    return defaults


def _load_cases_with_defaults(suite_path: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    suite_defaults = _load_suite_defaults(suite_path)
    rows = _read_jsonl(suite_path)
    cases: List[Dict[str, Any]] = []
    for row in rows:
        if "_suite_config" in row and isinstance(row["_suite_config"], dict):
            suite_defaults.update(row["_suite_config"])
            continue

        case = dict(row)
        expected = dict(suite_defaults.get("expected", {}))
        expected.update(case.get("expected", {}))
        if case.get("expected_route") is not None:
            expected["route"] = case.get("expected_route")
        if case.get("expected_tools") is not None:
            expected["tools"] = case.get("expected_tools")
        if case.get("should_refuse") is not None:
            expected["should_refuse"] = case.get("should_refuse")
        case["expected"] = expected

        for k in ("tools", "model", "temperature", "requires_structured_output", "response_schema", "perf_gates"):
            if case.get(k) is None and suite_defaults.get(k) is not None:
                case[k] = suite_defaults.get(k)

        schema_mode = case.get("schema_validation_mode") or suite_defaults.get("schema_validation_mode")
        case["schema_validation_mode"] = schema_mode or "strict"
        cases.append(case)
    return suite_defaults, cases


def _prepare_case_for_mode(case: Dict[str, Any], mode: str) -> Dict[str, Any]:
    prepared = dict(case)
    expected = prepared.get("expected", {})
    if mode == "openai":
        has_route_or_refusal_checks = expected.get("route") is not None or expected.get("should_refuse") is not None
        if has_route_or_refusal_checks and prepared.get("requires_structured_output") is None:
            prepared["requires_structured_output"] = True
        if prepared.get("requires_structured_output") and not prepared.get("response_schema"):
            prepared["response_schema"] = ROUTING_SCHEMA
    return prepared


def _build_metrics(scored: List[Dict[str, Any]]) -> Dict[str, Any]:
    perf_rows = [s for s in scored if not s.get("is_refusal") and not s.get("is_failure_injection")]
    refusal = [s for s in scored if s.get("is_refusal") and not s.get("is_failure_injection")]
    by_route: Dict[str, List[Dict[str, Any]]] = {"tech": [], "marketing": [], "investor": []}
    confusion: Dict[str, Dict[str, int]] = {}
    for row in perf_rows:
        r = row.get("actual_route")
        if r in by_route:
            by_route[r].append(row)
    for row in scored:
        exp = row.get("expected_route")
        act = row.get("actual_route")
        if exp is not None and act is not None:
            confusion.setdefault(exp, {})
            confusion[exp][act] = confusion[exp].get(act, 0) + 1

    refusal_latency = [float(r["latency_ms"]) for r in refusal if r.get("latency_ms") is not None]
    refusal_cost = [float(r["cost_estimate_usd"]) for r in refusal if r.get("cost_estimate_usd") is not None]
    return {
        "non_refusal_overall": aggregate_perf(perf_rows),
        "non_refusal_by_route": {k: aggregate_perf(v) for k, v in by_route.items()},
        "refusal_overall": {
            "count": len(refusal),
            "latency_ms_mean": round(mean(refusal_latency), 2) if mean(refusal_latency) is not None else None,
            "cost_usd_mean": round(mean(refusal_cost), 6) if mean(refusal_cost) is not None else None,
        },
        "confusion_matrix": confusion,
    }


def run_suite(
    suite_path: str,
    mode: str,
    app_url: str = None,
    model: str = None,
    baseline_dir: str = None,
    update_baseline: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = os.path.join("runs", run_id)
    os.makedirs(run_dir, exist_ok=True)
    adapter = _adapter(mode)
    suite_defaults, cases = _load_cases_with_defaults(suite_path)
    suite_name = _suite_name_from_path(suite_path)
    baseline_dir = baseline_dir or os.path.join("baselines", suite_name)

    manifest = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "suite_path": suite_path,
        "suite_name": suite_name,
        "mode": mode,
        "adapter": getattr(adapter, "name", mode),
        "baseline_dir": baseline_dir,
    }
    _write_json(os.path.join(run_dir, "manifest.json"), manifest)

    scored_rows: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    schema_errors: List[str] = []
    tool_mismatches: List[Dict[str, Any]] = []
    results_path = os.path.join(run_dir, "results.jsonl")
    if os.path.exists(results_path):
        os.remove(results_path)

    for case in cases:
        prepared_case = _prepare_case_for_mode(case, mode)
        started = time.time()
        result = adapter.run_case(prepared_case, {"app_url": app_url, "model": model})
        latency = result.get("latency_ms") or result.get("telemetry", {}).get("latency_ms")
        if latency is None:
            latency = int((time.time() - started) * 1000)
        result.setdefault("telemetry", {})["latency_ms"] = latency
        if result.get("cost_estimate_usd") is None:
            result["cost_estimate_usd"] = result.get("telemetry", {}).get("cost_estimate_usd")

        scored = score_case(prepared_case, result)
        usage = result.get("usage", {})
        row = {
            "id": prepared_case.get("id"),
            "input": prepared_case.get("input"),
            "expected_route": prepared_case.get("expected", {}).get("route"),
            "actual_route": scored.get("actual_route"),
            "is_refusal": scored.get("actual_refusal"),
            "is_failure_injection": bool(prepared_case.get("simulate_failure_mode")),
            "latency_ms": result.get("telemetry", {}).get("latency_ms"),
            "cost_estimate_usd": result.get("telemetry", {}).get("cost_estimate_usd") or result.get("cost_estimate_usd"),
            "tokens_total": usage.get("total_tokens"),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "tool_names": result.get("tool_names", []),
            "tool_calls": result.get("tool_calls", []),
            "tool_precision": scored.get("tool_metrics", {}).get("precision"),
            "tool_recall": scored.get("tool_metrics", {}).get("recall"),
            "schema_valid": result.get("schema_valid", True),
            "parse_error": result.get("parse_error"),
            "rubric": maybe_rubric_score(result.get("answer", ""), prepared_case.get("rubric_path")),
            "passed": scored.get("passed"),
            "failures": scored.get("failures"),
            "expected_tools": scored.get("expected_tools", []),
            "actual_tools": scored.get("actual_tools", []),
        }
        scored_rows.append(row)
        _append_jsonl(results_path, row)
        if not row["passed"]:
            failures.append(
                {
                    "id": row["id"],
                    "failures": row["failures"],
                    "schema_errors": (result.get("schema_errors") or [])[:3],
                    "parse_error": result.get("parse_error"),
                }
            )
            for msg in row["failures"]:
                if "schema" in str(msg).lower():
                    schema_errors.append(str(msg))
        if row.get("expected_tools") != row.get("actual_tools"):
            tool_mismatches.append(
                {"id": row["id"], "expected_tools": row.get("expected_tools", []), "actual_tools": row.get("actual_tools", [])}
            )

    metrics = _build_metrics(scored_rows)
    tool_precision_values = [float(r["tool_precision"]) for r in scored_rows if r.get("tool_precision") is not None]
    tool_recall_values = [float(r["tool_recall"]) for r in scored_rows if r.get("tool_recall") is not None]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": suite_path,
        "suite_name": suite_name,
        "total_cases": len(scored_rows),
        "passed_cases": len([r for r in scored_rows if r.get("passed")]),
        "failed_cases": len([r for r in scored_rows if not r.get("passed")]),
        "metrics": metrics,
        "tool_summary": {
            "precision_mean": round(mean(tool_precision_values), 4) if mean(tool_precision_values) is not None else None,
            "recall_mean": round(mean(tool_recall_values), 4) if mean(tool_recall_values) is not None else None,
            "top_mismatches": tool_mismatches[:10],
        },
        "schema_errors": schema_errors[:3],
    }
    _write_json(os.path.join(run_dir, "summary.json"), summary)

    report_md = make_markdown_report(manifest, summary, failures)
    with open(os.path.join(run_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(report_md)

    baseline_path = os.path.join(baseline_dir, "summary.json")
    regressions: List[str] = []
    thresholds = build_thresholds((suite_defaults.get("perf_gates") or {}))
    if update_baseline:
        os.makedirs(baseline_dir, exist_ok=True)
        _write_json(baseline_path, {"generated_at": datetime.now(timezone.utc).isoformat(), "dataset": suite_path, "suite_name": suite_name, "metrics": metrics})
    else:
        if not os.path.exists(baseline_path):
            regressions = [f"baseline missing at {baseline_path}. Run with --update-baseline."]
        else:
            with open(baseline_path, "r", encoding="utf-8") as f:
                baseline = json.load(f)
            regressions = compare_metrics(metrics, baseline.get("metrics", {}), thresholds=thresholds)

    diff_md = make_diff_markdown(run_id, baseline_path, regressions, failures=failures)
    with open(os.path.join(run_dir, "diff.md"), "w", encoding="utf-8") as f:
        f.write(diff_md)

    return run_dir, {"summary": summary, "regressions": regressions, "failures": failures}
