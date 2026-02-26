from typing import Any, Dict, List, Optional


DEFAULT_THRESHOLDS = {
    "non_refusal_overall.latency_ms_p95": {"multiplier": 1.35, "absolute_cap": 3000.0},
    "non_refusal_overall.cost_usd_mean": {"multiplier": 1.25},
    "non_refusal_overall.tokens_total_p95": {"multiplier": 1.25},
    "non_refusal_by_route.tech.latency_ms_p95": {"multiplier": 1.35},
    "non_refusal_by_route.marketing.latency_ms_p95": {"multiplier": 1.35},
    "non_refusal_by_route.investor.latency_ms_p95": {"multiplier": 1.35},
}


def _get_path(data: Dict[str, Any], dotted: str) -> Optional[float]:
    cur: Any = data
    for p in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    try:
        return float(cur) if cur is not None else None
    except Exception:
        return None


def compare_metrics(current: Dict[str, Any], baseline: Dict[str, Any], thresholds: Dict[str, Dict[str, float]] = None) -> List[str]:
    rules = thresholds or DEFAULT_THRESHOLDS
    failures: List[str] = []
    for path, rule in rules.items():
        cur = _get_path(current, path)
        base = _get_path(baseline, path)
        if cur is None or base is None:
            if path.startswith("non_refusal_by_route."):
                continue
            failures.append(f"missing metric: {path}")
            continue
        if rule.get("absolute_cap") is not None and cur > float(rule["absolute_cap"]):
            failures.append(f"{path} regression: current={cur:.4f} > absolute_cap={float(rule['absolute_cap']):.4f}")
            continue
        mult = float(rule.get("multiplier", 1.0))
        if base <= 0:
            if cur <= 0:
                continue
            if rule.get("absolute_cap") is None or cur <= float(rule["absolute_cap"]):
                continue
            failures.append(f"baseline zero and current exceeds cap for {path}: current={cur:.4f}")
            continue
        if cur > base * mult:
            failures.append(f"{path} regression: current={cur:.4f} baseline={base:.4f} threshold={base * mult:.4f}")
    return failures


def build_thresholds(perf_gates: Dict[str, Any] = None) -> Dict[str, Dict[str, float]]:
    cfg = perf_gates or {}
    latency_mult = float(cfg.get("latency_p95_mult", 1.35))
    cost_mult = float(cfg.get("cost_mean_mult", 1.25))
    tokens_mult = float(cfg.get("tokens_p95_mult", 1.25))
    latency_abs = float(cfg.get("latency_p95_abs_cap_ms", 3000))
    return {
        "non_refusal_overall.latency_ms_p95": {"multiplier": latency_mult, "absolute_cap": latency_abs},
        "non_refusal_overall.cost_usd_mean": {"multiplier": cost_mult},
        "non_refusal_overall.tokens_total_p95": {"multiplier": tokens_mult},
        "non_refusal_by_route.tech.latency_ms_p95": {"multiplier": latency_mult},
        "non_refusal_by_route.marketing.latency_ms_p95": {"multiplier": latency_mult},
        "non_refusal_by_route.investor.latency_ms_p95": {"multiplier": latency_mult},
    }
