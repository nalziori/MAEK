"""Inspection strategy comparison: human+scaffold vs drone only vs drone+AI triage.

Detection uses a logistic POD curve POD(a) = 1/(1+exp(-(b0 + b1 ln a))) per sensor
(`strategy.pod.*`); all parameters are assumptions until fitted values replace them.
Defect size `a`: area_cm2 for visual sensors, depth_mm for UT.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from maek import energy, network, params, pec, thermal
from maek import pod as _pod

WALL_LOSS = ("external_corrosion", "cui", "fac_thinning", "internal_pitting")
FAC_FEATURES = ("elbow", "tee", "orifice_downstream", "valve_downstream")
COST_KEYS = ["cost_ut_point_krw", "cost_scaffold_krw", "cost_drone_per_km_krw",
             "cost_labor_hour_krw", "cost_drone_contact_ut_extra_krw",
             "cost_ai_processing_per_km_krw", "cost_insulation_opening_krw",
             "cost_lift_day_krw", "cost_pec_hour_krw"]
IR_KINDS = ("wet_insulation", "insulation_damage", "tracer_leak", "steam_leak")
TRAP_KINDS = thermal.TRAP_KINDS
FOUND_KINDS = (*energy.ENERGY_KINDS, "trap_failed_closed", "internal_pitting")
STRATEGIES = ("baseline", "drone", "ai_triage")
LABELS = {"baseline": "사람+비계", "drone": "드론", "ai_triage": "드론+AI"}
COUNT_COLS = ["ut_points", "drone_ut_points", "scaffolds", "drone_km", "ai_km",
              "labor_hours", "insulation_openings", "lift_days", "pec_hours"]
_ZERO = {"drone_ut_points": 0, "scaffolds": 0, "drone_km": 0.0, "ai_km": 0.0, "walk_km": 0.0,
         "flags": 0, "insulation_openings": 0, "lift_points": 0, "pec_zones": 0, "pec_m": 0.0,
         "pec_hours": 0.0, "trap_tests": 0, "pit_scan_points": 0}


def pod_prob(a, b0, b1):
    """Logistic POD for defect size a (>0); 0 for a <= 0 (alias of maek.pod.pod)."""
    a = np.asarray(a, float)
    ok = a > 0
    return np.where(ok, _pod.pod(np.where(ok, a, 1.0), b0, b1), 0.0)


def _s(cfg, key):
    return params.get(cfg, f"strategy.{key}")


def _pod_params(cfg, sensor):
    return _s(cfg, f"pod.{sensor}.b0"), _s(cfg, f"pod.{sensor}.b1")


def _draw(rng, p):
    return rng.random(len(p)) < p


def _mode(defects):
    """ut_mode as a clean string array; NaN/None (e.g. after a CSV round-trip) -> ""."""
    return defects["ut_mode"].fillna("").astype(str).str.strip().to_numpy()


def _ut_pod(cfg, defects, modes=("straight", "angle"), drone=None):
    """POD of a UT measurement that covers each defect (mode-specific, size = depth).

    Only defects whose ut_mode is in `modes` can be detected (others get POD 0).
    `drone` (bool per defect) selects drone-contact UT curves (worse coupling) over manual
    ones; internal pitting at straight-beam points uses the pit-depth curves
    (`ut_pit_manual` / `ut_pit_drone`) instead of the thinning curves.
    """
    mode = _mode(defects)
    kind = defects["kind"].to_numpy()
    depth = defects["depth_mm"].to_numpy(float)
    drone = np.zeros(len(defects), bool) if drone is None else np.asarray(drone, bool)
    pit = kind == "internal_pitting"
    p = np.zeros(len(defects))
    for name, m, manual, drn in (
            ("straight", (mode == "straight") & ~pit, "ut_straight", "ut_straight_drone"),
            ("straight", (mode == "straight") & pit, "ut_pit_manual", "ut_pit_drone"),
            ("angle", mode == "angle", "ut_angle", "ut_angle_drone")):
        if name not in modes:
            continue
        for sel, sensor in ((m & ~drone, manual), (m & drone, drn)):
            p[sel] = pod_prob(depth[sel], *_pod_params(cfg, sensor))
    return p


