# app/metrics.py
from __future__ import annotations
import time
import math
from typing import Dict, List, Optional
from collections import deque, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
import statistics

@dataclass
class Event:
    ts_ms: int
    latency_ms: Optional[float]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    model: Optional[str]
    error: bool

class MetricsTracker:
    """
    In-memory metrics with rolling window and simple aggregations.
    NOTE: For multi-instance deployments, back this with Redis/DB.
    """
    def __init__(self, max_events: int = 5000):
        self.max_events = max_events
        self.events: deque[Event] = deque(maxlen=max_events)

    # --- recording ---

    def record_request(
        self,
        latency_ms: Optional[float],
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        model: Optional[str] = None,
        error: bool = False,
        ts_ms: Optional[int] = None,
    ):
        e = Event(
            ts_ms = ts_ms if ts_ms is not None else int(time.time() * 1000),
            latency_ms = latency_ms,
            input_tokens = input_tokens,
            output_tokens = output_tokens,
            total_tokens = total_tokens,
            model = model,
            error = error,
        )
        self.events.append(e)

    # --- helpers ---

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _iter_window(self, days: int = 14):
        """Yield events within the last N days."""
        cutoff = self._now() - timedelta(days=days)
        cutoff_ms = int(cutoff.timestamp() * 1000)
        for e in self.events:
            if e.ts_ms >= cutoff_ms:
                yield e

    # --- aggregations ---

    def _aggregate(self, granularity: str = "hour", days: int = 14):
        """
        Return list of buckets for last N days, grouped by hour/day.
        Each item: { bucket_start_iso, req, err, input_tokens, output_tokens, total_tokens, avg_latency_ms }
        """
        assert granularity in ("hour", "day")
        buckets = defaultdict(list)

        def floor_dt(dt: datetime):
            if granularity == "hour":
                return dt.replace(minute=0, second=0, microsecond=0)
            return dt.replace(hour=0, minute=0, second=0, microsecond=0)

        for e in self._iter_window(days=days):
            dt = datetime.fromtimestamp(e.ts_ms / 1000.0, tz=timezone.utc)
            key = floor_dt(dt)
            buckets[key].append(e)

        out = []
        # Ensure continuous timeline (fill gaps) for chart niceness
        start = floor_dt(self._now() - timedelta(days=days))
        end = floor_dt(self._now())
        step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
        current = start
        while current <= end:
            evs = buckets.get(current, [])
            req = len(evs)
            err = sum(1 for x in evs if x.error)
            lat_list = [x.latency_ms for x in evs if x.latency_ms is not None]
            avg_lat = round(statistics.mean(lat_list), 2) if lat_list else None
            it = sum(x.input_tokens or 0 for x in evs)
            ot = sum(x.output_tokens or 0 for x in evs)
            tt = sum(x.total_tokens or 0 for x in evs)
            out.append({
                "bucket_start_iso": current.isoformat(),
                "req": req,
                "err": err,
                "avg_latency_ms": avg_lat,
                "input_tokens": it,
                "output_tokens": ot,
                "total_tokens": tt,
            })
            current += step
        return out

    def _totals(self, days: int = 14):
        evs = list(self._iter_window(days=days))
        req = len(evs)
        err = sum(1 for x in evs if x.error)
        lat_list = [x.latency_ms for x in evs if x.latency_ms is not None]
        tokens_it = sum(x.input_tokens or 0 for x in evs)
        tokens_ot = sum(x.output_tokens or 0 for x in evs)
        tokens_tt = sum(x.total_tokens or 0 for x in evs)

        # latency stats
        avg = round(statistics.mean(lat_list), 2) if lat_list else None
        p50 = round(statistics.median(lat_list), 2) if lat_list else None
        p95 = round(self._percentile(lat_list, 95), 2) if lat_list else None

        return {
            "window_days": days,
            "requests": req,
            "errors": err,
            "error_rate": round((err / req) * 100, 2) if req else 0.0,
            "latency_ms": {"avg": avg, "p50": p50, "p95": p95},
            "tokens": {"input": tokens_it, "output": tokens_ot, "total": tokens_tt},
        }

    def _percentile(self, data: List[float], pct: float) -> float:
        if not data:
            return math.nan
        data_sorted = sorted(data)
        k = (len(data_sorted)-1) * (pct/100.0)
        f = math.floor(k); c = math.ceil(k)
        if f == c:
            return data_sorted[int(k)]
        d0 = data_sorted[int(f)] * (c - k)
        d1 = data_sorted[int(c)] * (k - f)
        return d0 + d1

    # --- public API ---

    def get_stats(self) -> Dict:
        return {
            "totals": self._totals(days=14),
            "hourly": self._aggregate(granularity="hour", days=2),   # last 48 hours
            "daily": self._aggregate(granularity="day", days=14),    # last 14 days
        }

    def reset(self):
        self.events.clear()

# Global instance
metrics = MetricsTracker()

