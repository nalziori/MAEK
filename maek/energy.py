"""Energy loss of insulation / steam defects and its annual cost and CO2.

Heat flows use maek.heat (steady radial conduction + outer film); steam escaping through an
orifice uses the Napier (choked-flow) rule of thumb from the Clemson IAC leak sheet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from maek import heat, params

ENERGY_KINDS = ("insulation_damage", "wet_insulation", "steam_leak", "tracer_leak",
                "trap_failed_open")
_LB_TO_KG = 0.453592
_BAR_TO_PSI = 14.5038


def napier_kg_h(p_barg, orifice_mm, const: float = 24.24):
    """Steam mass flow (kg/h) through an orifice: lb/h = const x P(psia) x D(in)^2."""
    psia = (np.asarray(p_barg, float) + heat.ATM_BAR) * _BAR_TO_PSI
    d_in = np.asarray(orifice_mm, float) / 25.4
    return const * psia * d_in ** 2 * _LB_TO_KG


def _q_w_per_m(cfg, seg, k, insulated: bool) -> float:
    g = lambda key: params.get(cfg, key)
    ins = float(seg["insulation_mm"]) if insulated else 0.0
    h = g("energy.h_jacket_w_m2k") if insulated else g("energy.h_bare_w_m2k")
    q = heat.heat_loss_w_per_m(seg["temp_c"], g("energy.ambient_c"), seg["od_mm"], ins, k, h)
    return max(float(q), 0.0)


def defect_loss_kw(cfg: dict, seg, d) -> float:
    """Continuous energy loss (kW) caused by defect `d` on segment `seg`."""
    kind = d["kind"]
    if kind not in ENERGY_KINDS:
        return 0.0
    if kind in ("steam_leak", "tracer_leak", "trap_failed_open"):
        kg_h = napier_kg_h(seg["pressure_barg"], d["orifice_mm"],
                           params.get(cfg, "energy.napier_const"))
        return float(kg_h) * params.get(cfg, "energy.steam_enthalpy_kj_kg") / 3600.0
    length_m = float(d["length_mm"]) / 1000.0
    k = params.get(cfg, "energy.k_insulation_w_mk")
    if kind == "insulation_damage":
        dq = _q_w_per_m(cfg, seg, k, False) - _q_w_per_m(cfg, seg, k, True)
        return max(dq, 0.0) * length_m * float(d["circ_frac"]) / 1000.0
    mult = params.get(cfg, "energy.wet_k_multiplier")
    k_wet = k * (1 + (mult - 1) * float(d["moisture"]))
    dq = _q_w_per_m(cfg, seg, k_wet, True) - _q_w_per_m(cfg, seg, k, True)
    return max(dq, 0.0) * length_m / 1000.0


def annual(cfg: dict, kw) -> dict:
    """Annual energy, steam, cost and CO2 of a continuous loss `kw` (scalar or array)."""
    g = lambda key: params.get(cfg, key)
    kwh = np.asarray(kw, float) * g("energy.hours_per_year")
    mwh = kwh / 1000.0
    steam_t = kwh * 3.6 / g("energy.steam_enthalpy_kj_kg")
    fuel_gj = mwh * 3.6 / g("energy.boiler_eff")
    mix = cfg["energy"]["fuel_mix"]
    ef = sum(v["value"] * cfg["energy"]["ef_t_per_tj"][k]["value"] for k, v in mix.items())
    return {"mwh_per_yr": mwh, "steam_t_per_yr": steam_t,
            "cost_krw_per_yr": steam_t * g("energy.steam_cost_krw_per_t"),
            "co2_t_per_yr": fuel_gj * ef / 1000.0}


def losses(cfg: dict, segments: pd.DataFrame, defects: pd.DataFrame) -> pd.DataFrame:
    """Per-defect energy loss table for the energy-relevant defect kinds."""
    cols = ["defect_id", "segment_id", "kind", "loss_kw", "mwh_per_yr", "steam_t_per_yr",
            "cost_krw_per_yr", "co2_t_per_yr"]
    sel = defects[defects["kind"].isin(ENERGY_KINDS)]
    seg = segments.set_index("segment_id")
    kw = np.array([defect_loss_kw(cfg, seg.loc[r.segment_id], r._asdict())
                   for r in sel.itertuples(index=False)], float)
    out = pd.DataFrame({"defect_id": sel["defect_id"].to_numpy(),
                        "segment_id": sel["segment_id"].to_numpy(),
                        "kind": sel["kind"].to_numpy(), "loss_kw": kw})
    for k, v in annual(cfg, kw).items():
        out[k] = v
    return out[cols]
