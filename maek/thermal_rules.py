"""Opt-in steam recall candidates; existing jacket predictions are preserved."""
from __future__ import annotations

from maek import params
from maek import thermal_render as tr

STEAM_CANDIDATES = {
    "steam_mild": {"thermal.detector.z_thr": 2.5, "thermal.detector.peak_z": 4.0,
                   "thermal.detector.min_extent_px": 5},
    "steam_medium": {"thermal.detector.z_thr": 2.0, "thermal.detector.peak_z": 3.0,
                     "thermal.detector.min_extent_px": 3},
    "steam_aggressive": {"thermal.detector.z_thr": 1.5, "thermal.detector.peak_z": 3.0,
                         "thermal.detector.min_extent_px": 3, "thermal.detector.min_dt_k": 0.2},
}


def detect_ir(cfg, temperature, pipe_mask, candidate="baseline"):
    """Only add steam labels into previously unclassified pixels."""
    if candidate != "baseline" and candidate not in STEAM_CANDIDATES:
        raise ValueError(f"Unknown thermal candidate: {candidate}")
    baseline = tr.detect_ir(cfg, temperature, pipe_mask)
    if candidate == "baseline":
        return baseline
    relaxed = tr.detect_ir(params.with_values(cfg, STEAM_CANDIDATES[candidate]),
                           temperature, pipe_mask)
    result = baseline.copy()
    result[(baseline == 0) & (relaxed == 3)] = 3
    return result
