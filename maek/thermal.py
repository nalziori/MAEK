"""Infrared (thermal) inspection model for insulated steam / condensate / traced lines.

Physics: jacket surface temperature from steady radial heat transfer (maek.heat), wet insulation
raises the conductivity, damaged insulation exposes bare metal. Camera: gray-body radiometry in
a total-band approximation (radiance ~ eps sigma T^4 + (1 - eps) sigma T_refl^4); the camera
inverts it with its emissivity setting, so a wrong setting or a reflective jacket shrinks and
distorts the apparent contrast. Steam traps are judged by inlet / outlet apparent temperatures.

`detect_prob` is the pure function the strategy model calls; the (b0, b1) it uses are fitted
from the image simulator (maek.thermal_render) and stored in the config under thermal.pod.
"""

from __future__ import annotations

import numpy as np

from maek import heat, pod

KELVIN = 273.15
WET_KINDS = ("wet_insulation", "tracer_leak")
TRAP_KINDS = ("trap_failed_open", "trap_failed_closed")
TRACER_MOISTURE = 0.8
TRAP_EPS_NOMINAL = 0.75


def _t(cfg: dict, key: str):
    return cfg["thermal"][key]["value"]


def _cond(cfg: dict, condition: str) -> dict:
    return {k: v["value"] for k, v in cfg["thermal"]["conditions"][condition].items()}


def _num(d, key, default=0.0) -> float:
    try:
        v = d[key]
    except (KeyError, IndexError):
        return default
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return default if np.isnan(v) else v


def h_wind(cfg: dict, wind_mps) -> np.ndarray:
    """Outer surface heat-transfer coefficient (W/m2/K), h = a + b v."""
    return _t(cfg, "h_wind_a") + _t(cfg, "h_wind_b") * np.asarray(wind_mps, float)


def jacket_temp_c(cfg: dict, seg, wind_mps: float = 1.0, moisture: float = 0.0, bare: bool = False,
                  ambient_c: float | None = None) -> float:
    """True outer surface temperature (C): intact jacket, wet zone (moisture > 0) or bare metal."""
    amb = cfg["energy"]["ambient_c"]["value"] if ambient_c is None else ambient_c
    k0 = cfg["energy"]["k_insulation_w_mk"]["value"]
    mult = cfg["energy"]["wet_k_multiplier"]["value"]
    k = k0 * (1.0 + (mult - 1.0) * moisture)
    ins = 0.0 if bare else _num(seg, "insulation_mm", 50.0)
    return float(heat.surface_temp_c(_num(seg, "temp_c"), amb, _num(seg, "od_mm", 114.3), ins, k,
                                     h_wind(cfg, wind_mps)))


def contrast_k(cfg: dict, seg, d, wind_mps: float = 1.0, ambient_c: float | None = None) -> float:
    """True surface temperature difference (K) of defect `d` vs the intact jacket.

    0 for kinds without a jacket signature (traps; steam_leak is handled by orifice size) and
    for uninsulated segments. tracer_leak behaves like a wet zone with moisture 0.8.
    """
    kind = d["kind"]
    if not bool(seg["insulated"]) or _num(seg, "insulation_mm", 1.0) <= 0:
        return 0.0
    base = jacket_temp_c(cfg, seg, wind_mps, ambient_c=ambient_c)
    if kind in WET_KINDS:
        m = TRACER_MOISTURE if kind == "tracer_leak" else _num(d, "moisture", 0.5)
        return jacket_temp_c(cfg, seg, wind_mps, moisture=float(np.clip(m, 0, 1)),
                             ambient_c=ambient_c) - base
    if kind == "insulation_damage":
        return jacket_temp_c(cfg, seg, wind_mps, bare=True, ambient_c=ambient_c) - base
    return 0.0


# ---------------------------------------------------------------- radiometric camera model
def apparent_temp_c(ts_c, eps, trefl_c, eps_set, trefl_set_c):
    """Camera reading (C) of a gray body at ts_c with emissivity eps reflecting trefl_c.

    L = eps T^4 + (1 - eps) Trefl^4 (sigma cancels); inverted with the camera's eps_set and
    reflected-temperature setting: T_app^4 = (L - (1 - eps_set) Tset^4) / eps_set.
    """
    ts, tr = np.asarray(ts_c, float) + KELVIN, np.asarray(trefl_c, float) + KELVIN
    tset = np.asarray(trefl_set_c, float) + KELVIN
    eps, es = np.asarray(eps, float), np.asarray(eps_set, float)
    rad = eps * ts ** 4 + (1.0 - eps) * tr ** 4
    t4 = (rad - (1.0 - es) * tset ** 4) / es
    return np.maximum(t4, 1.0) ** 0.25 - KELVIN


def sky_fraction(n_up):
    """Weight of the sky in the reflected temperature for a surface-normal elevation sin(n_up)."""
    return np.clip(0.5 + 0.5 * np.asarray(n_up, float), 0.0, 1.0)


def reflected_temp_c(ambient_c, sky_offset_k, n_up):
    """Reflected apparent temperature (C): sky (ambient + offset) above, ground (ambient) below."""
    s = sky_fraction(n_up)
    t4 = s * (ambient_c + sky_offset_k + KELVIN) ** 4 + (1 - s) * (ambient_c + KELVIN) ** 4
    return t4 ** 0.25 - KELVIN


# ---------------------------------------------------------------- steam traps
def trap_readings(cfg: dict, state: str, condition: str, n: int, rng, p_barg=None):
    """Apparent (inlet, outlet) temperatures (C) of `n` traps in state normal | open | closed.

    Inputs mirror the plant: trap body is bare metal (emissivity 0.6-0.9, camera set to 0.75
    +- relative error), pressure 2-10 barg. Returns (inlet_app, outlet_app, t_sat).
    """
    cond = _cond(cfg, condition)
    amb = rng.uniform(*_t(cfg, "ambient_c"), n)
    sky = rng.uniform(*cond["sky_offset_k"], n)
    wind = rng.uniform(*cond["wind_mps"], n)
    sun = rng.uniform(*cond["sun_k"], n)
    p = rng.uniform(2.0, 10.0, n) if p_barg is None else np.full(n, float(p_barg))
    tsat = heat.sat_temp_c(p + heat.ATM_BAR)
    eps = rng.uniform(*_t(cfg, "bare_metal_emissivity"), n)
    eps_set = TRAP_EPS_NOMINAL * (1 + rng.normal(0, cfg["thermal"]["eps_set_error"][condition]["value"], n))
    # body surface sits a few K below the steam; wind cools it, sun heats it by absorptivity
    cool = 1.0 + 0.4 * (h_wind(cfg, wind) - 5.7) / 20.0
    t_in = tsat - rng.uniform(2, 8, n) * cool
    if state == "normal":
        t_out = t_in - rng.uniform(20, 40, n)
    elif state == "open":                    # live steam blows through to the condensate line
        t_out = t_in - rng.uniform(0, 15, n)
    elif state == "closed":                  # condensate backs up: inlet side cooled well below Tsat
        t_in = amb + rng.uniform(0.1, 0.9, n) * (tsat - amb)
        t_out = t_in - rng.uniform(0, 8, n)
    else:
        raise ValueError(state)
    solar = sun * eps
    out = []
    for t in (t_in, t_out):
        ts = t + solar + rng.normal(0, 1.0 + 0.4 * wind, n)
        trefl = reflected_temp_c(amb, sky, 0.3)
        app = apparent_temp_c(ts, eps, trefl, eps_set, amb)
        out.append(app + rng.normal(0, 0.3, n))
    return out[0], out[1], tsat


def trap_rule(inlet_app, outlet_app, tsat, closed_drop_k=30.0, open_dt_k=10.0):
    """Boolean arrays (flag_closed, flag_open) from the apparent inlet / outlet temperatures."""
    closed = np.asarray(inlet_app) < np.asarray(tsat) - closed_drop_k
    opened = (~closed) & (np.asarray(outlet_app) > np.asarray(inlet_app) - open_dt_k)
    return closed, opened


def trap_pods(cfg: dict, condition: str = "train", n: int = 3000, seed: int = 0) -> dict:
    """Monte-Carlo pod_open, pod_closed and false_alarm of the trap rule."""
    rng = np.random.default_rng([seed, 17, 0 if condition == "train" else 1])
    res = {}
    for state in ("normal", "open", "closed"):
        i, o, ts = trap_readings(cfg, state, condition, n, rng)
        c, op = trap_rule(i, o, ts)
        res[state] = (c, op)
    return {"pod_open": float(res["open"][1].mean()),
            "pod_closed": float(res["closed"][0].mean()),
            "false_alarm": float((res["normal"][0] | res["normal"][1]).mean())}


# ---------------------------------------------------------------- detection probability
def detect_prob(cfg: dict, seg, d, condition: str = "train", reviewer: str = "ai") -> float:
    """Probability that an IR inspection flags defect `d` on segment `seg` (no randomness)."""
    kind = d["kind"]
    th = cfg["thermal"]
    table = th["pod"] if condition == "train" else th["pod_shifted"]
    if kind in TRAP_KINDS:
        t = th["trap"][condition]
        p = t["pod_open" if kind == "trap_failed_open" else "pod_closed"]["value"]
    elif kind == "steam_leak":
        b = table["steam_leak"]
        p = float(pod.pod(max(_num(d, "orifice_mm", 0.0), 1e-6), b["b0"]["value"], b["b1"]["value"]))
    elif kind in (*WET_KINDS, "insulation_damage"):
        if not bool(seg["insulated"]):
            return 0.0
        wind = float(np.mean(_cond(cfg, condition)["wind_mps"]))
        a = abs(contrast_k(cfg, seg, d, wind))
        key = "insulation_damage" if kind == "insulation_damage" else "wet_insulation"
        b = table[key]
        p = float(pod.pod(max(a, 1e-6), b["b0"]["value"], b["b1"]["value"]))
    else:
        return 0.0
    if reviewer == "human":
        p *= th["human_review_factor"]["value"]
    return float(p)
