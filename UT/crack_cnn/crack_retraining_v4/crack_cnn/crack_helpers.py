"""Exact window helpers extracted from scripts/ut_cnn.py for standalone inference."""
import numpy as np

from maek import params, ut


def crack_windows(cfg, walls, angles, temps) -> np.ndarray:
    """[lo, hi) sample range of the corner-trap gate, identical to `ut.detect_crack`."""
    p = ut._p(cfg)
    out = np.zeros((len(walls), 2), int)
    for i, (w, a, t) in enumerate(zip(walls, angles, temps)):
        tc = ut.corner_trap_time(cfg, w, a, t)
        half = params.get(cfg, "ut.gate_halfwidth_us") * 1e-6 + 0.03 * (tc - p["t0"])
        out[i] = max(0, int((tc - half) * p["fs"])), min(p["n"], int((tc + half) * p["fs"]) + 1)
    return out

def window_mask(win: np.ndarray, n: int) -> np.ndarray:
    idx = np.arange(n)[None, :]
    return (idx >= win[:, :1]) & (idx < win[:, 1:])
