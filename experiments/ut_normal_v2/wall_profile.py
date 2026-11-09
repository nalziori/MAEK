"""Conditional normal-wall timing fit. No ground-truth geometry inputs."""

import numpy as np
from scipy.optimize import minimize_scalar


def estimate(cfg, rf, nominal_mm, temp_observed, ut, params):
    p = ut._p(cfg)
    v = ut.velocity_long(cfg, temp_observed)
    center = 2 * nominal_mm * 1e-3 / v
    half = 2 * max(0.5, 0.1 * nominal_mm) * 1e-3 / v
    n = len(rf)
    # Fixed windows derive from the independent nominal record, not true thickness.
    indices = []
    orders = []
    radius = int(np.ceil((4 * p["sigma"] + 4 * half) * p["fs"]))
    for k in [1, 2, 3, 4]:
        mid = round((p["t0"] + k * center) * p["fs"])
        lo = max(0, mid - radius)
        hi = min(n, mid + radius + 1)
        if hi > lo:
            indices.append(np.arange(lo, hi))
            orders.append(k)
    if not indices:
        return float("nan")
    # Joint train with four positive amplitudes, not separately overlapping windows.
    idx = np.unique(np.concatenate(indices))
    t = idx / p["fs"]
    x = np.asarray(rf, dtype=float)[idx]
    orders = np.asarray(orders)

    def loss(lag):
        dt = t[:, None] - (p["t0"] + orders * lag)[None, :]
        h = np.exp(-0.5 * (dt / p["sigma"]) ** 2) * np.cos(2 * np.pi * p["f0"] * dt)
        # Include interface pulse as a nuisance regressor if the window reaches it.
        di = t - p["t0"]
        hi = np.exp(-0.5 * (di / p["sigma"]) ** 2) * np.cos(2 * np.pi * p["f0"] * di)
        if np.linalg.norm(hi) > 1e-8:
            h = np.c_[h, hi]
        amplitude = np.maximum(np.linalg.lstsq(h, x, rcond=None)[0], 0.0)
        residual = x - h @ amplitude
        return float(residual @ residual)

    grid = np.linspace(max(center - half, 1e-8), center + half, 101)
    values = np.array([loss(g) for g in grid])
    j = int(values.argmin())
    lo = grid[max(0, j - 1)]
    hi = grid[min(len(grid) - 1, j + 1)]
    if hi <= lo:
        return float("nan")
    # Scale to nanoseconds for a numerically meaningful bounded optimizer tolerance.
    fit = minimize_scalar(
        lambda q: loss(q * 1e-9),
        bounds=(lo * 1e9, hi * 1e9),
        method="bounded",
        options={"xatol": 1e-4, "maxiter": 40},
    )
    return float(fit.x * 1e-9 * v * 1e3 / 2) if fit.success else float("nan")
