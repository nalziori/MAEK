"""Pulsed eddy current (PEC) through-insulation wall-loss model (carbon steel only).

PEC averages wall loss over a footprint that grows with insulation thickness (lift-off), so a
small pit is diluted below the threshold while a large patch is still seen.
"""

from __future__ import annotations

import math

from maek import params

PEC_KINDS = ("external_corrosion", "cui", "fac_thinning", "internal_pitting")


def applicable(seg) -> bool:
    return seg["material"] == "carbon_steel"


def footprint_mm(cfg: dict, liftoff_mm: float) -> float:
    return (params.get(cfg, "pec.footprint_base_mm")
            + params.get(cfg, "pec.footprint_per_liftoff") * float(liftoff_mm))


def averaged_loss(cfg: dict, wall_mm: float, depth_mm: float, area_cm2: float,
                  liftoff_mm: float, offset_mm: float = 0.0) -> float:
    """Relative wall loss seen by PEC: depth/wall x min(1, area/footprint) x Gaussian offset."""
    f = footprint_mm(cfg, liftoff_mm)
    a_fp = math.pi * (f / 2.0) ** 2 / 100.0  # cm2
    s = f / 2.355
    gauss = math.exp(-(offset_mm ** 2) / (2 * s * s))
    return depth_mm / wall_mm * min(1.0, area_cm2 / a_fp) * gauss


def detect_prob(cfg: dict, seg, d) -> float:
    """Probability that one PEC scan reports `d` (0 outside the scanned 6 o'clock band)."""
    g = lambda key: params.get(cfg, key)
    if not applicable(seg) or d["kind"] not in PEC_KINDS:
        return 0.0
    if abs(float(d["clock_deg"]) % 360.0 - 180.0) > g("pec.band_deg"):
        return 0.0
    loss = averaged_loss(cfg, seg["wall_mm"], d["depth_mm"], d["area_cm2"],
                         seg["insulation_mm"], g("pec.grid_spacing_mm") / 4.0)
    sigma = g("pec.noise_rel") * (g("pec.galvanized_noise_factor")
                                  if seg["jacket"] == "galvanized" else 1.0)
    return 0.5 * (1.0 + math.erf((loss - g("pec.threshold_rel")) / (sigma * math.sqrt(2.0))))


def scan_minutes(cfg: dict, length_m: float) -> float:
    return params.get(cfg, "pec.setup_min") + params.get(cfg, "pec.lines") * float(length_m) \
        / params.get(cfg, "pec.scan_m_per_min")
