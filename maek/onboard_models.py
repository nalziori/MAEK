"""CPU benchmark helpers and an untrained cost-only UT A-scan model."""
from __future__ import annotations

import math
import statistics


def summarize(latencies_ms, elapsed_s, peak_rss_mb):
    if (not latencies_ms or not math.isfinite(elapsed_s) or elapsed_s <= 0
            or any(not math.isfinite(x) or x <= 0 for x in latencies_ms)):
        raise ValueError("latencies and elapsed time must be positive and finite")
    if peak_rss_mb is not None and (not math.isfinite(peak_rss_mb) or peak_rss_mb <= 0):
        raise ValueError("peak RSS must be positive and finite, or None")
    values = sorted(latencies_ms)
    pos = 0.95 * (len(values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    p95 = values[lo] + (values[hi] - values[lo]) * (pos - lo)
    p50 = statistics.median(values)
    return {"p50_ms": p50, "p95_ms": p95,
            "throughput_per_s": len(values) / elapsed_s, "fps_from_p50": 1000 / p50,
            "pass_p95_200ms": p95 <= 200,
            "pass_memory_2gib": None if peak_rss_mb is None else peak_rss_mb <= 2048,
            "latencies_ms": list(latencies_ms), "elapsed_s": elapsed_s}


def make_ut_model():
    """Fixed random weights measure cost, not defect classification accuracy."""
    import torch

    torch.manual_seed(0)
    return torch.nn.Sequential(
        torch.nn.Conv1d(1, 16, 9, stride=2, padding=4), torch.nn.ReLU(),
        torch.nn.Conv1d(16, 32, 7, stride=2, padding=3), torch.nn.ReLU(),
        torch.nn.Conv1d(32, 64, 5, stride=2, padding=2), torch.nn.ReLU(),
        torch.nn.AdaptiveAvgPool1d(1), torch.nn.Flatten(), torch.nn.Linear(64, 2),
    ).cpu().float().eval()
