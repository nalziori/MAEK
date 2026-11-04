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

from maek import params

FEATURE_KINDS = ["elbow", "tee", "orifice_downstream", "valve_downstream", "support",
                 "nozzle", "dead_leg", "flange", "weld"]
DEFECT_KINDS = ["external_corrosion", "cui", "fac_thinning", "internal_pitting", "crack",
                "flange_leak"]
UT_MODE = {"external_corrosion": "straight", "cui": "straight", "fac_thinning": "straight",
           "internal_pitting": "straight", "crack": "angle", "flange_leak": ""}
# config location_weight key -> feature kind
FAC_KIND = {"elbow": "elbow", "tee": "tee", "orifice": "orifice_downstream",
            "valve": "valve_downstream"}

SEGMENT_COLS = ["segment_id", "area", "medium", "material", "nps", "od_mm", "wall_mm",
                "t_min_mm", "install_year", "insulated", "temp_c", "elevated", "traffic",
                "length_m"]
FEATURE_COLS = ["feature_id", "segment_id", "kind", "pos_m"]
DEFECT_COLS = ["defect_id", "segment_id", "feature_id", "kind", "pos_m", "clock_deg",
               "depth_mm", "area_cm2", "length_mm", "growth_mm_per_yr", "visible_external",
               "external_sign", "ut_mode", "remaining_wall_mm", "critical"]


def _sub(cfg: dict, dotted: str) -> dict:
    node = cfg
    for part in dotted.split("."):
        node = node[part]
    return {k: v["value"] for k, v in node.items()}


def consequence(medium: str, cfg: dict | None = None) -> int:
    """Consequence score 1..5 of a leak of `medium` (risk.consequence.*)."""
    cfg = cfg or params.load_config()
    return int(params.get(cfg, f"risk.consequence.{medium}"))


def _segments(cfg: dict, rng, total_km: float) -> pd.DataFrame:
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

    p_ins = np.where(medium == "steam", g("network.insulated_prob_steam"),
                     g("network.insulated_fraction"))
    insulated = (rng.random(n) < p_ins) & (material != "pvc")
    elevated = rng.random(n) < g("network.elevated_fraction")
    traffic = rng.choice(np.asarray(g("network.traffic_levels"), int), size=n)
    year = rng.integers(g("network.install_year_min"), g("network.install_year_max") + 1, n)

    return pd.DataFrame({
        "segment_id": [f"S{i:05d}" for i in range(n)],
        "area": areas, "medium": medium, "material": material,
        "nps": [int(k.split("_")[1]) for k in nps_key], "od_mm": od, "wall_mm": wall,
        "t_min_mm": np.round(wall * g("network.t_min_frac"), 3),
        "install_year": year.astype(int), "insulated": insulated, "temp_c": temp,
        "elevated": elevated, "traffic": traffic.astype(int), "length_m": lengths,
    }, columns=SEGMENT_COLS)


def _features(cfg: dict, rng, seg: pd.DataFrame) -> pd.DataFrame:
    dens = _sub(cfg, "network.features_per_km")
    rows = []
    for sid, L in zip(seg["segment_id"], seg["length_m"]):
        for kind in FEATURE_KINDS:
            k = rng.poisson(dens[kind] * L / 1000.0)
            for p in np.sort(rng.uniform(0, L, k)):
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
    seg = _segments(cfg, rng, g("network.total_km") if total_km is None else total_km)
    feat = _features(cfg, rng, seg)
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

    rows = []

    def add(s, kind, fid, pos, clock, depth, area, length, growth, sign=False):
        wall = s.wall_mm
        rem = wall if kind in ("crack", "flange_leak") else wall - depth
        crit = depth > crit_frac * wall if kind == "crack" else rem < s.t_min_mm
        rows.append((s.segment_id, fid, kind, round(float(min(max(pos, 0), s.length_m)), 3),
                     round(float(clock) % 360, 1), round(float(depth), 3),
                     round(float(area), 2), round(float(length), 1),
                     round(float(growth), 4), kind in ("external_corrosion", "flange_leak"),
                     bool(sign), UT_MODE[kind], round(float(rem), 3), bool(crit)))

    def wall_loss(s, age, factor=1.0):
        r = float(_rate(cfg, rng)) * factor
        depth = min(r * age * rng.uniform(*exp_rng), 0.9 * s.wall_mm)
        return depth, r

    def place(s, fs, weights, n):
        """Yield (feature_id|None, pos) for n defects split by location weights."""
        kinds = [k for k in weights if k == "straight" or (fs["kind"] == k).any()]
        w = np.array([weights[k] for k in kinds], float)
        for k in rng.choice(kinds, size=n, p=w / w.sum()):
            if k == "straight":
                yield None, rng.uniform(0, s.length_m)
            else:
                cand = fs[fs["kind"] == k]
                j = rng.integers(len(cand))
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
            for _ in range(rng.poisson(g("defects.internal_pitting.rate_per_km") * km * f)):
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

    df = pd.DataFrame(rows, columns=DEFECT_COLS[1:])
    df.insert(0, "defect_id", [f"D{i:06d}" for i in range(len(df))])
    df["feature_id"] = df["feature_id"].astype(object).where(df["feature_id"].notna(), None)
    return seg, feat, df[DEFECT_COLS]


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
