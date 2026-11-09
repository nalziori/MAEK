"""Exact pod_summary source snapshot from maek/evaluate.py; imports isolated."""
import numpy as np
import pod_snapshot as pod

def pod_summary(sizes, hits, n_boot=300, seed=0) -> dict:
    """a90 (logistic POD in ln size) with bootstrap a90/95; NaN if the fit is degenerate."""
    sizes, hits = np.asarray(sizes, float), np.asarray(hits, float)
    ok = sizes > 0
    sizes, hits = sizes[ok], hits[ok]
    nan = {"n": len(sizes), "hit_rate": float(hits.mean()) if len(hits) else np.nan,
           "min_size": float(sizes.min()) if len(sizes) else np.nan,
           "max_size": float(sizes.max()) if len(sizes) else np.nan, "status": "ok",
           "b0": np.nan, "b1": np.nan, "a90": np.nan, "a90_lo": np.nan, "a90_95": np.nan}
    if len(sizes) < 10:
        return {**nan, "status": "too_few"}
    if hits.min() == hits.max():  # perfectly separated: logistic fit diverges
        return {**nan, "status": "all_hit" if hits.min() else "all_miss"}
    f = pod.fit_pod(sizes, hits)
    if f["b1"] <= 0:
        return {**nan, "status": "no_trend"}
    a90 = pod.a_at(0.9, f["b0"], f["b1"])
    if a90 > 3 * sizes.max():  # POD never gets near 90% inside the tested size range
        return {**nan, "status": "beyond_range", "b0": f["b0"], "b1": f["b1"]}
    a90, lo, hi = pod.bootstrap_a90(sizes, hits, n_boot=n_boot, seed=seed)
    return {**nan, "b0": f["b0"], "b1": f["b1"], "a90": a90, "a90_lo": lo, "a90_95": hi}
