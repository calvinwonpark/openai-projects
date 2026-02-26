import math
from typing import Any, Dict, List, Optional


def percentile(values: List[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    idx = max(0, min(len(ordered) - 1, math.ceil(pct * len(ordered)) - 1))
    return float(ordered[idx])


def mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return float(sum(values) / len(values))


def estimate_cost_usd(input_tokens: int, output_tokens: int, model: str) -> float:
    in_rate_per_million = 5.0
    out_rate_per_million = 15.0
    model_name = (model or "gpt-4o").lower()
    if "mini" in model_name:
        in_rate_per_million = 0.2
        out_rate_per_million = 0.6
    return round((input_tokens / 1_000_000) * in_rate_per_million + (output_tokens / 1_000_000) * out_rate_per_million, 6)


def aggregate_perf(records: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    lat = [float(r["latency_ms"]) for r in records if r.get("latency_ms") is not None]
    cost = [float(r["cost_estimate_usd"]) for r in records if r.get("cost_estimate_usd") is not None]
    tok = [float(r["tokens_total"]) for r in records if r.get("tokens_total") is not None]
    return {
        "count": len(records),
        "latency_ms_p50": percentile(lat, 0.50),
        "latency_ms_p95": percentile(lat, 0.95),
        "cost_usd_mean": round(mean(cost), 6) if mean(cost) is not None else None,
        "cost_usd_p95": percentile(cost, 0.95),
        "tokens_total_mean": round(mean(tok), 2) if mean(tok) is not None else None,
        "tokens_total_p95": percentile(tok, 0.95),
    }
