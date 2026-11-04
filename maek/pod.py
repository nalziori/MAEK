"""Probability of detection (hit/miss) logistic model in ln(size), shared by all sensors.

POD(a) = 1 / (1 + exp(-(b0 + b1 ln a))), fitted by Newton-Raphson (IRLS) in numpy.
"""

from __future__ import annotations

import numpy as np


def pod(a, b0: float, b1: float):
    a = np.asarray(a, float)
    return 1.0 / (1.0 + np.exp(-(b0 + b1 * np.log(a))))


def a_at(p: float, b0: float, b1: float) -> float:
    """Size at which POD == p (a90 = a_at(0.9, ...)); a_at(0.5) == exp(-b0/b1)."""
    return float(np.exp((np.log(p / (1.0 - p)) - b0) / b1))


def fit_pod(sizes, hits, max_iter: int = 100, tol: float = 1e-9) -> dict:
    """Maximum-likelihood fit of (b0, b1) from sizes (>0) and 0/1 hits."""
    x = np.log(np.asarray(sizes, float))
    y = np.asarray(hits, float)
    X = np.column_stack([np.ones_like(x), x])
    beta = np.zeros(2)
    ridge = 1e-8 * np.eye(2)  # keeps the Hessian invertible under (near-)separation
    for _ in range(max_iter):
        p = 1.0 / (1.0 + np.exp(-np.clip(X @ beta, -35, 35)))
        grad = X.T @ (y - p)
        hess = (X * (p * (1 - p))[:, None]).T @ X + ridge
        step = np.linalg.solve(hess, grad)
        step = np.clip(step, -5, 5)  # damp wild steps on near-separated data
        beta = beta + step
        if np.max(np.abs(step)) < tol:
            break
    return {"b0": float(beta[0]), "b1": float(beta[1])}


def bootstrap_a90(sizes, hits, n_boot: int = 500, seed: int = 0):
    """Return (a90, lo95, hi95): point estimate and the 5th / 95th bootstrap percentiles.

    hi95 (one-sided 95% upper bound of a90) is the a90/95 approximation.
    """
    sizes, hits = np.asarray(sizes, float), np.asarray(hits, float)
    f = fit_pod(sizes, hits)
    a90 = a_at(0.9, f["b0"], f["b1"])
    rng = np.random.default_rng(seed)
    n = len(sizes)
    vals = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        b = fit_pod(sizes[i], hits[i])
        if b["b1"] > 0 and np.isfinite(b["b0"]):
            vals.append(a_at(0.9, b["b0"], b["b1"]))
    if not vals:
        return a90, float("nan"), float("nan")
    lo, hi = np.percentile(vals, [5, 95])
    return a90, float(lo), float(hi)
