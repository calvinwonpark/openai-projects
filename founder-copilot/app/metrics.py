"""
Metrics tracking for token usage and latency.
"""
import time
from typing import Dict, List, Optional
from collections import deque
import statistics


class MetricsTracker:
    def __init__(self, max_samples: int = 1000):
        self.max_samples = max_samples
        self.latencies: deque = deque(maxlen=max_samples)
        self.token_usages: List[Dict] = []
        self.request_count = 0
        self.error_count = 0
        
    def record_request(
        self,
        latency_ms: float,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        error: bool = False
    ):
        """Record a request with latency and token usage."""
        self.request_count += 1
        if error:
            self.error_count += 1
        else:
            self.latencies.append(latency_ms)
            if total_tokens is not None or input_tokens is not None or output_tokens is not None:
                self.token_usages.append({
                    "input_tokens": input_tokens or 0,
                    "output_tokens": output_tokens or 0,
                    "total_tokens": total_tokens or (input_tokens or 0) + (output_tokens or 0),
                    "timestamp": time.time()
                })
                # Keep only recent token usages
                if len(self.token_usages) > self.max_samples:
                    self.token_usages = self.token_usages[-self.max_samples:]
    
    def get_stats(self) -> Dict:
        """Get aggregated statistics."""
        if not self.latencies:
            return {
                "request_count": self.request_count,
                "error_count": self.error_count,
                "success_count": self.request_count - self.error_count,
                "latency": {
                    "p50": None,
                    "p95": None,
                    "p99": None,
                    "avg": None,
                    "min": None,
                    "max": None,
                    "count": 0
                },
                "tokens": {
                    "total_input": 0,
                    "total_output": 0,
                    "total": 0,
                    "avg_input": 0,
                    "avg_output": 0,
                    "avg_total": 0,
                    "count": 0
                }
            }
        
        sorted_latencies = sorted(self.latencies)
        n = len(sorted_latencies)
        
        latency_stats = {
            "p50": sorted_latencies[int(n * 0.50)] if n > 0 else None,
            "p95": sorted_latencies[int(n * 0.95)] if n > 0 else None,
            "p99": sorted_latencies[int(n * 0.99)] if n > 0 else None,
            "avg": statistics.mean(sorted_latencies),
            "min": min(sorted_latencies),
            "max": max(sorted_latencies),
            "count": n
        }
        
        # Token statistics
        if self.token_usages:
            total_input = sum(u["input_tokens"] for u in self.token_usages)
            total_output = sum(u["output_tokens"] for u in self.token_usages)
            total = sum(u["total_tokens"] for u in self.token_usages)
            count = len(self.token_usages)
            
            token_stats = {
                "total_input": total_input,
                "total_output": total_output,
                "total": total,
                "avg_input": total_input / count if count > 0 else 0,
                "avg_output": total_output / count if count > 0 else 0,
                "avg_total": total / count if count > 0 else 0,
                "count": count
            }
        else:
            token_stats = {
                "total_input": 0,
                "total_output": 0,
                "total": 0,
                "avg_input": 0,
                "avg_output": 0,
                "avg_total": 0,
                "count": 0
            }
        
        return {
            "request_count": self.request_count,
            "error_count": self.error_count,
            "success_count": self.request_count - self.error_count,
            "latency": latency_stats,
            "tokens": token_stats
        }
    
    def reset(self):
        """Reset all metrics."""
        self.latencies.clear()
        self.token_usages.clear()
        self.request_count = 0
        self.error_count = 0


# Global metrics tracker instance
metrics = MetricsTracker()

