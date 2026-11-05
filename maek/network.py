"""Virtual steel-plant pipe network with ground-truth defects.

`generate_network(cfg, seed)` returns three DataFrames (segments, features, defects).
Every random draw comes from one `numpy.random.Generator` seeded with `seed`, so the
output is identical for a given seed and config.

Sensor physics contract (see docs/posco-pipe-ndt-review.md 6.2 item 3):
- camera sees only `visible_external` defects (external rust, flange leak stain) and
  CUI defects whose cladding shows a sign (`external_sign`);
- straight-beam UT measures wall loss (`ut_mode == "straight"`);
- angle-beam UT finds cracks (`ut_mode == "angle"`).

Assumptions (also in config/default.yaml): t_min = nominal wall x `network.t_min_frac`;
wall loss depth = corrosion rate x exposure years, exposure = age x U(defects.exposure_frac_range)
(initiation delay); crack rows keep remaining_wall_mm = nominal wall (no metal loss).
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

import numpy as np
import pandas as pd

from maek import heat, params

FEATURE_KINDS = ["elbow", "tee", "orifice_downstream", "valve_downstream", "support",
                 "nozzle", "dead_leg", "flange", "weld", "steam_trap", "low_point"]
DEFECT_KINDS = ["external_corrosion", "cui", "fac_thinning", "internal_pitting", "crack",
                "flange_leak", "insulation_damage", "wet_insulation", "steam_leak", "tracer_leak",
                "trap_failed_open", "trap_failed_closed"]
UT_MODE = {"external_corrosion": "straight", "cui": "straight", "fac_thinning": "straight",
           "internal_pitting": "straight", "crack": "angle", "flange_leak": "",
           **{k: "" for k in DEFECT_KINDS[6:]}}
# config location_weight key -> feature kind
NEW_KINDS = frozenset(DEFECT_KINDS[6:])
FAC_KIND = {"elbow": "elbow", "tee": "tee", "orifice": "orifice_downstream",
            "valve": "valve_downstream"}

SEGMENT_COLS = ["segment_id", "area", "medium", "material", "nps", "od_mm", "wall_mm",
                "t_min_mm", "install_year", "insulated", "temp_c", "elevated", "traffic",
                "length_m", "traced", "insulation_mm", "jacket", "pressure_barg"]
FEATURE_COLS = ["feature_id", "segment_id", "kind", "pos_m"]
DEFECT_COLS = ["defect_id", "segment_id", "feature_id", "kind", "pos_m", "clock_deg",
               "depth_mm", "area_cm2", "length_mm", "growth_mm_per_yr", "visible_external",
               "external_sign", "ut_mode", "remaining_wall_mm", "critical", "moisture", "circ_frac",
               "orifice_mm", "zone_id"]


def _sub(cfg: dict, dotted: str) -> dict:
    node = cfg
    for part in dotted.split("."):
        node = node[part]
    return {k: v["value"] for k, v in node.items() if "value" in v}


def consequence(medium: str, cfg: dict | None = None) -> int:
    """Consequence score 1..5 of a leak of `medium` (risk.consequence.*)."""
    cfg = cfg or params.load_config()
    return int(params.get(cfg, f"risk.consequence.{medium}"))


def _segments(cfg: dict, rng, total_km: float, rng2) -> pd.DataFrame:
    g = partial(params.get, cfg)
    seg_m = float(g("network.segment_m"))
    total_m = float(total_km) * 1000.0
    n = int(np.ceil(total_m / seg_m - 1e-9))
    lengths = np.full(n, seg_m)
    lengths[-1] = total_m - seg_m * (n - 1)

    mix = _sub(cfg, "network.media_mix")
    media = list(mix)
    pm = np.array([mix[m] for m in media], float)
    medium = rng.choice(media, size=n, p=pm / pm.sum())

    nw = _sub(cfg, "network.nps_weights")
    names = list(nw)
    pw = np.array([nw[k] for k in names], float)
    nps_key = rng.choice(names, size=n, p=pw / pw.sum())
    od = np.array([g(f"network.pipe_sizes.{k}.od_mm") for k in nps_key], float)
    wall = np.array([g(f"network.pipe_sizes.{k}.wall_mm") for k in nps_key], float)

    mat = _sub(cfg, "network.material")
    u = rng.random(n)
    material = np.where(u < mat["other_stainless"], "stainless", "carbon_steel").astype(object)
    ox = medium == "oxygen"
    material[ox] = np.where(u[ox] < mat["oxygen_stainless"], "stainless", "carbon_steel")
    ac = medium == "pickling_acid_hf"
    material[ac] = np.where(u[ac] < mat["acid_pvc"], "pvc", "stainless")

    areas = np.empty(n, dtype=object)
    temp = np.empty(n)
    for m in media:
        idx = np.flatnonzero(medium == m)
        opts = g(f"network.area_by_medium.{m}")
        areas[idx] = rng.choice(opts, size=idx.size)
        lo, hi = g(f"network.temp_c_by_medium.{m}")
        temp[idx] = np.round(rng.uniform(lo, hi, size=idx.size), 1)

    p_ins = np.full(n, float(g("network.insulated_fraction")))
    for m, prob in _sub(cfg, "network.insulated_prob_by_medium").items():
        p_ins[medium == m] = prob
    insulated = (rng.random(n) < p_ins) & (material != "pvc")
    elevated = rng.random(n) < g("network.elevated_fraction")
    traffic = rng.choice(np.asarray(g("network.traffic_levels"), int), size=n)
    year = rng.integers(g("network.install_year_min"), g("network.install_year_max") + 1, n)

    traced = medium == "traced_process"
    ins_by_nps = _sub(cfg, "network.insulation_mm_by_nps")
    ins_mm = np.where(insulated, [float(ins_by_nps[k]) for k in nps_key], 0.0)
    jm = _sub(cfg, "network.jacket_mix")
    jk = list(jm)
    jp = np.array([jm[k] for k in jk], float)
    jacket = np.full(n, "", dtype=object)
    jacket[insulated] = rng2.choice(jk, size=int(insulated.sum()), p=jp / jp.sum())
    press = np.zeros(n)
    st = medium == "steam"
    press[st] = np.round(np.maximum(heat.sat_pressure_bar_abs(temp[st]) - heat.ATM_BAR, 0.0), 2)
    for m, key in (("traced_process", "network.tracer_pressure_barg"),
                   ("condensate", "network.condensate_pressure_barg")):
        idx = np.flatnonzero(medium == m)
        press[idx] = np.round(rng2.uniform(*g(key), size=idx.size), 2)

    return pd.DataFrame({
        "segment_id": [f"S{i:05d}" for i in range(n)],
        "area": areas, "medium": medium, "material": material,
        "nps": [int(k.split("_")[1]) for k in nps_key], "od_mm": od, "wall_mm": wall,
        "t_min_mm": np.round(wall * g("network.t_min_frac"), 3),
        "install_year": year.astype(int), "insulated": insulated, "temp_c": temp,
        "elevated": elevated, "traffic": traffic.astype(int), "length_m": lengths,
        "traced": traced, "insulation_mm": ins_mm, "jacket": jacket, "pressure_barg": press,
    }, columns=SEGMENT_COLS)


def _features(cfg: dict, rng, seg: pd.DataFrame, rng2) -> pd.DataFrame:
    dens = _sub(cfg, "network.features_per_km")
    rows = []
    for sid, L in zip(seg["segment_id"], seg["length_m"]):
        for kind in FEATURE_KINDS[:9]:
            k = rng.poisson(dens[kind] * L / 1000.0)
            for p in np.sort(rng.uniform(0, L, k)):
                rows.append((sid, kind, round(float(p), 3)))
    extra = cfg["network"]["medium_features_per_km"]
    for sid, medium, L in zip(seg["segment_id"], seg["medium"], seg["length_m"]):
        for kind, leaf in extra.get(medium, {}).items():
            k = rng2.poisson(leaf["value"] * L / 1000.0)
            for p in np.sort(rng2.uniform(0, L, k)):
                rows.append((sid, kind, round(float(p), 3)))
    df = pd.DataFrame(rows, columns=["segment_id", "kind", "pos_m"])
    df.insert(0, "feature_id", [f"F{i:06d}" for i in range(len(df))])
    return df[FEATURE_COLS]


def _rate(cfg: dict, rng, size=None):
    mean = params.get(cfg, "defects.corrosion_rate.mean_mm_per_year")
    s = params.get(cfg, "defects.corrosion_rate.sigma_log")
    r = rng.lognormal(np.log(mean) - s * s / 2, s, size)
    return np.minimum(r, params.get(cfg, "defects.corrosion_rate.max_mm_per_year"))


def generate_network(cfg: dict | None = None, seed: int = 0, total_km: float | None = None):
    """Return (segments, features, defects) DataFrames; deterministic for (cfg, seed)."""
    cfg = cfg or params.load_config()
    g = partial(params.get, cfg)
    rng = np.random.default_rng(seed)
    rng2 = np.random.default_rng([seed, 1])  # all draws added after the base network
    seg = _segments(cfg, rng, g("network.total_km") if total_km is None else total_km, rng2)
    feat = _features(cfg, rng, seg, rng2)
    by_seg = {sid: grp for sid, grp in feat.groupby("segment_id", sort=False)}
    empty = feat.iloc[0:0]

    ref_year, age_ref = g("network.reference_year"), g("defects.age_ref_years")
    age_exp, gain = g("defects.age_exponent"), g("defects.consequence_gain")
    cui_lo, cui_hi = g("defects.cui.temp_min_c"), g("defects.cui.temp_max_c")
    pk_lo, pk_hi = g("defects.cui.peak_min_c"), g("defects.cui.peak_max_c")
    cui_w = _sub(cfg, "defects.cui.location_weight")
    fac_w = {FAC_KIND.get(k, k): v for k, v in _sub(cfg, "defects.fac.location_weight").items()}
    crk_w = _sub(cfg, "defects.crack.location_weight")
    fac_media = set(g("defects.fac.media"))
    pit_media = set(g("defects.internal_pitting.media"))
    cons = _sub(cfg, "risk.consequence")
    exp_rng = g("defects.exposure_frac_range")
    crit_frac = g("defects.crack.critical_height_frac")
    pit_factor = _sub(cfg, "defects.internal_pitting.rate_factor_by_medium")

    rows = []

    def add(s, kind, fid, pos, clock, depth, area, length, growth, sign=False, visible=None,
            moisture=0.0, circ=0.0, orifice=0.0, zone=None):
        wall = s.wall_mm
        new = kind in NEW_KINDS
        rem = wall if kind in ("crack", "flange_leak") or new else wall - depth
        crit = depth > crit_frac * wall if kind == "crack" else (rem < s.t_min_mm and not new)
        if visible is None:
            visible = kind in ("external_corrosion", "flange_leak")
        rows.append((s.segment_id, fid, kind, round(float(min(max(pos, 0), s.length_m)), 3),
                     round(float(clock) % 360, 1), round(float(depth), 3),
                     round(float(area), 2), round(float(length), 1),
                     round(float(growth), 4), bool(visible),
                     bool(sign), UT_MODE[kind], round(float(rem), 3), bool(crit),
                     round(float(moisture), 3), round(float(circ), 3), round(float(orifice), 3),
                     zone))
        return len(rows) - 1

    def wall_loss(s, age, factor=1.0):
        r = float(_rate(cfg, rng)) * factor
        depth = min(r * age * rng.uniform(*exp_rng), 0.9 * s.wall_mm)
        return depth, r

    def place(s, fs, weights, n, gen=rng):
        """Yield (feature_id|None, pos) for n defects split by location weights."""
        kinds = [k for k in weights if k == "straight" or (fs["kind"] == k).any()]
        w = np.array([weights[k] for k in kinds], float)
        for k in gen.choice(kinds, size=n, p=w / w.sum()):
            if k == "straight":
                yield None, gen.uniform(0, s.length_m)
            else:
                cand = fs[fs["kind"] == k]
                j = gen.integers(len(cand))
                yield cand["feature_id"].iat[j], cand["pos_m"].iat[j]

    for s in seg.itertuples(index=False):
        fs = by_seg.get(s.segment_id, empty)
        age = max(ref_year - s.install_year, 0)
        f = (age / age_ref) ** age_exp * (1 + gain * (cons[s.medium] - 1) / 4)
        km = s.length_m / 1000.0
        cs = s.material == "carbon_steel"
        metal = s.material != "pvc"

        if cs and not s.insulated:
            for _ in range(rng.poisson(g("defects.external_corrosion.rate_per_km") * km * f)):
                d, r = wall_loss(s, age)
                a = rng.lognormal(np.log(20), 0.8)
                add(s, "external_corrosion", None, rng.uniform(0, s.length_m),
                    rng.uniform(0, 360), d, a, np.sqrt(a) * 10, r)

        if cs and s.insulated and cui_lo <= s.temp_c <= cui_hi:
            tf = g("defects.cui.peak_factor") if pk_lo <= s.temp_c <= pk_hi else 1.0
            n = rng.poisson(g("defects.cui.rate_per_km") * km * f * tf)
            for fid, pos in place(s, fs, cui_w, n):
                d, r = wall_loss(s, age, tf)
                a = rng.lognormal(np.log(30), 0.8)
                add(s, "cui", fid, pos + rng.normal(0, 0.2), rng.normal(180, 40), d, a,
                    np.sqrt(a) * 10, r, rng.random() < g("defects.cui.external_sign_prob"))

        if cs and s.medium in fac_media:
            n = rng.poisson(g("defects.fac.rate_per_km") * km * f)
            for fid, pos in place(s, fs, fac_w, n):
                d, r = wall_loss(s, age, g("defects.fac.rate_factor"))
                a = rng.lognormal(np.log(15), 0.6)
                down = rng.uniform(0, 3 * s.od_mm / 1000.0) if fid is not None else 0.0
                add(s, "fac_thinning", fid, pos + down, rng.uniform(0, 360), d, a,
                    np.sqrt(a) * 10, r)

        if metal and s.medium in pit_media:
            for _ in range(rng.poisson(g("defects.internal_pitting.rate_per_km") * km * f
                                    * pit_factor.get(s.medium, 1.0))):
                d, r = wall_loss(s, age)
                a = rng.lognormal(np.log(1.0), 0.5)
                add(s, "internal_pitting", None, rng.uniform(0, s.length_m),
                    rng.normal(180, 60), d, a, np.sqrt(a) * 10, r)

        if metal:
            n = rng.poisson(g("defects.crack.rate_per_km") * km * f)
            mu = np.log(g("defects.crack.length_mean_mm"))
            ls = g("defects.crack.length_sigma_log")
            for fid, pos in place(s, fs, crk_w, n):
                frac = min(rng.lognormal(np.log(g("defects.crack.depth_frac_mean")), 0.4),
                           g("defects.crack.depth_frac_max"))
                add(s, "crack", fid, pos, rng.uniform(0, 360), frac * s.wall_mm, 0.0,
                    rng.lognormal(mu - ls * ls / 2, ls), g("defects.crack.growth_mm_per_year"))

        flanges = fs[fs["kind"] == "flange"]
        if len(flanges):
            p = min(g("defects.flange_leak.p_per_flange") * f, 1.0)
            for fid, pos in zip(flanges["feature_id"], flanges["pos_m"]):
                if rng.random() < p:
                    a = rng.lognormal(np.log(50), 0.7)
                    add(s, "flange_leak", fid, pos, rng.normal(180, 30), 0.0, a,
                        np.sqrt(a) * 10, 0.0)

    _new_kinds(cfg, rng2, seg, by_seg, empty, rows, add, place)
    df = pd.DataFrame(rows, columns=DEFECT_COLS[1:])
    df["feature_id"] = df["feature_id"].astype(object).where(df["feature_id"].notna(), None)
    df["zone_id"] = df["zone_id"].astype(object)
    _relocate(cfg, rng2, seg, feat, df)
    df.insert(0, "defect_id", [f"D{i:06d}" for i in range(len(df))])
    zid = df["zone_id"]
    df["zone_id"] = [None if pd.isna(z) else f"D{int(z):06d}" for z in zid]
    return seg, feat, df[DEFECT_COLS]


def _new_kinds(cfg, rng2, seg, by_seg, empty, rows, add, place) -> None:
    """Second pass (rng2): insulation / steam / tracer / trap defects, no depth."""
    g = partial(params.get, cfg)
    ref_year, age_ref, age_exp = g("network.reference_year"), g("defects.age_ref_years"), \
        g("defects.age_exponent")
    idm, wet, stm, trc = (_sub(cfg, f"defects.{k}") for k in
                          ("insulation_damage", "wet_insulation", "steam_leak", "tracer_leak"))
    trap = _sub(cfg, "defects.steam_trap")
    wet_w = _sub(cfg, "defects.wet_insulation.location_weight")
    stm_w = {FAC_KIND.get(k, k): v for k, v in
             _sub(cfg, "defects.steam_leak.location_weight").items()}

    def lognorm(median, sigma, lo, hi):
        return float(min(max(rng2.lognormal(np.log(median), sigma), lo), hi))

    def wet_row(s, fid, pos, moisture, length, sign, zone=None):
        area = np.pi * s.od_mm / 10 * 0.5 * length * 100
        return add(s, "wet_insulation", fid, pos, 180.0, 0.0, area, length * 1000, 0.0,
                   sign=sign, moisture=moisture, zone=zone)

    for s in seg.itertuples(index=False):
        fs = by_seg.get(s.segment_id, empty)
        age = max(ref_year - s.install_year, 0)
        fa = (age / age_ref) ** age_exp
        km = s.length_m / 1000.0
        od_cm = s.od_mm / 10.0

        if s.insulated and s.temp_c >= idm["hot_min_c"]:
            for _ in range(rng2.poisson(idm["rate_per_km"] * km * fa)):
                ln = lognorm(idm["length_median_m"], idm["length_sigma_log"], 0.1,
                             idm["length_max_m"])
                circ = rng2.uniform(*idm["circ_frac_range"])
                vis = rng2.random() < idm["visible_prob"]
                add(s, "insulation_damage", None, rng2.uniform(0, s.length_m),
                    rng2.uniform(0, 360), 0.0, np.pi * od_cm * circ * ln * 100, ln * 1000, 0.0,
                    visible=vis, circ=circ)

        if s.insulated:
            rate = wet["rate_per_km"] * (wet["traced_factor"] if s.traced else 1.0)
            for fid, pos in place(s, fs, wet_w, rng2.poisson(rate * km * fa), rng2):
                ln = lognorm(wet["length_median_m"], wet["length_sigma_log"], 0.3,
                             wet["length_max_m"])
                wet_row(s, fid, pos, rng2.uniform(*wet["moisture_range"]), ln,
                        rng2.random() < wet["external_sign_prob"])

        if s.medium == "steam":
            for fid, pos in place(s, fs, stm_w, rng2.poisson(stm["rate_per_km"] * km * fa), rng2):
                o = lognorm(stm["orifice_median_mm"], stm["orifice_sigma_log"], 0.2,
                            stm["orifice_max_mm"])
                add(s, "steam_leak", fid, pos, rng2.uniform(0, 360), 0.0, 100 * o, o, 0.0,
                    visible=o >= stm["visible_plume_mm"], orifice=o)

        if s.traced:
            for _ in range(rng2.poisson(trc["rate_per_km"] * km * fa)):
                pos = rng2.uniform(0, s.length_m)
                o = lognorm(trc["orifice_median_mm"], trc["orifice_sigma_log"], 0.2,
                            trc["orifice_max_mm"])
                idx = add(s, "tracer_leak", None, pos, rng2.uniform(0, 360), 0.0, 100 * o, o,
                          0.0, visible=False, orifice=o)
                if s.insulated and rng2.random() < trc["wet_zone_prob"]:
                    ln = lognorm(trc["length_median_m"], 0.6, 0.3, wet["length_max_m"])
                    wet_row(s, None, pos, rng2.uniform(*trc["moisture_range"]), ln,
                            rng2.random() < wet["external_sign_prob"], zone=idx)

        for tid, tpos in zip(fs.loc[fs["kind"] == "steam_trap", "feature_id"],
                             fs.loc[fs["kind"] == "steam_trap", "pos_m"]):
            if rng2.random() < trap["fail_prob"]:
                if rng2.random() < trap["fail_open_share"]:
                    o = rng2.uniform(*trap["open_orifice_mm_range"])
                    add(s, "trap_failed_open", tid, tpos, 180.0, 0.0, 100 * o, o, 0.0,
                        orifice=o)
                else:
                    add(s, "trap_failed_closed", tid, tpos, 180.0, 0.0, 0.0, 0.0, 0.0)


def _relocate(cfg, rng2, seg, feat, df: pd.DataFrame) -> None:
    """Move CUI into wet-insulation zones and pitting to wet-spot features (in place)."""
    g = partial(params.get, cfg)
    p_wet, share, win = (g("defects.cui.in_wet_zone_prob"),
                         g("defects.internal_pitting.wet_spot_share"),
                         g("defects.internal_pitting.wet_spot_window_m"))
    length = seg.set_index("segment_id")["length_m"]
    zones = df[df["kind"] == "wet_insulation"].groupby("segment_id").groups
    wet_feat = feat[feat["kind"].isin(("low_point", "steam_trap", "dead_leg"))]
    spots = {sid: grp for sid, grp in wet_feat.groupby("segment_id")}
    for i in df.index[df["kind"] == "cui"]:
        sid = df.at[i, "segment_id"]
        if sid not in zones:
            continue
        if rng2.random() < p_wet:
            z = zones[sid][rng2.integers(len(zones[sid]))]
            half = df.at[z, "length_mm"] / 2000.0
            c = df.at[z, "pos_m"]
            df.at[i, "pos_m"] = round(float(np.clip(rng2.uniform(c - half, c + half), 0,
                                                    length[sid])), 3)
            df.at[i, "zone_id"] = int(z)
            df.at[i, "feature_id"] = df.at[z, "feature_id"]
    for i in df.index[df["kind"] == "internal_pitting"]:
        sid = df.at[i, "segment_id"]
        if sid not in spots or rng2.random() >= share:
            continue
        grp = spots[sid]
        j = rng2.integers(len(grp))
        pos = grp["pos_m"].iat[j]
        if grp["kind"].iat[j] == "steam_trap":
            pos -= rng2.uniform(0, win)
        else:
            pos += rng2.uniform(-win / 2, win / 2)
        df.at[i, "pos_m"] = round(float(np.clip(pos, 0, length[sid])), 3)
        df.at[i, "feature_id"] = grp["feature_id"].iat[j]


def save_network(out_dir, segments, features, defects) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, df in (("segments", segments), ("features", features), ("defects", defects)):
        p = out / f"{name}.csv"
        df.to_csv(p, index=False, encoding="utf-8")
        paths.append(p)
    return paths


def summary(segments, features, defects) -> str:
    lines = [f"segments: {len(segments)} ({segments['length_m'].sum() / 1000:.2f} km)",
             f"features: {len(features)}", f"defects: {len(defects)}"]
    counts = defects["kind"].value_counts()
    crit = defects[defects["critical"]]["kind"].value_counts()
    for k in DEFECT_KINDS:
        lines.append(f"  {k:<20} {int(counts.get(k, 0)):>6}  critical {int(crit.get(k, 0))}")
    lines.append(f"critical total: {int(defects['critical'].sum())}")
    return "\n".join(lines)
