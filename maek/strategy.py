"""Inspection strategy comparison: periodic human walkdown + fixed UT vs AI triage.

Detection uses a logistic POD curve POD(a) = 1/(1+exp(-(b0 + b1 ln a))) per sensor
(`strategy.pod.*`); all parameters are assumptions until fitted values replace them.
Defect size `a`: area_cm2 for visual sensors, depth_mm for UT.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from maek import network, params
from maek import pod as _pod

WALL_LOSS = ("external_corrosion", "cui", "fac_thinning", "internal_pitting")
FAC_FEATURES = ("elbow", "tee", "orifice_downstream", "valve_downstream")
COST_KEYS = ["cost_ut_point_krw", "cost_scaffold_krw", "cost_drone_per_km_krw",
             "cost_labor_hour_krw", "cost_drone_contact_ut_extra_krw"]


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


def _ut_pod(cfg, defects, modes=("straight", "angle")):
    """POD of a UT measurement that covers each defect (mode-specific, size = depth).

    Only defects whose ut_mode is in `modes` can be detected (others get POD 0).
    """
    mode = _mode(defects)
    depth = defects["depth_mm"].to_numpy(float)
    p = np.zeros(len(defects))
    for name, sensor in (("straight", "ut_straight"), ("angle", "ut_angle")):
        m = (mode == name) & (name in modes)
        p[m] = pod_prob(depth[m], *_pod_params(cfg, sensor))
    return p


def _metrics(cfg, defects, found, counts):
    """Detection metrics (NaN where no critical defect exists) + resource counts."""
    crit = defects["critical"].to_numpy(bool)
    found = np.asarray(found, bool)
    out = {"n_critical": float(crit.sum())}

    def rate(mask):
        n = (crit & mask).sum()
        return float((found & crit & mask).sum() / n) if n else np.nan

    out["detection_rate"] = rate(np.ones(len(defects), bool))
    for m in _media(cfg):
        out[f"detection_rate_{m}"] = rate((defects["medium"] == m).to_numpy())
    for k in network.DEFECT_KINDS:
        out[f"detection_rate_{k}"] = rate((defects["kind"] == k).to_numpy())
    hc = (defects["consequence"] >= _s(cfg, "high_consequence_min")).to_numpy()
    out["missed_high_consequence_critical"] = float((crit & hc & ~found).sum())
    out.update({k: float(v) for k, v in counts.items()})
    out.update(cost_breakdown(cfg, counts))
    return out


def _media(cfg):
    return [k for k in cfg["network"]["media_mix"]]


def cost_breakdown(cfg, counts, unit=None):
    unit = unit or {k: _s(cfg, k) for k in COST_KEYS}
    ut = counts["ut_points"] * unit["cost_ut_point_krw"]
    ut += counts["drone_ut_points"] * unit["cost_drone_contact_ut_extra_krw"]
    sc = counts["scaffolds"] * unit["cost_scaffold_krw"]
    dr = counts["drone_km"] * unit["cost_drone_per_km_krw"]
    lab = counts["labor_hours"] * unit["cost_labor_hour_krw"]
    return {"cost_krw": float(ut + sc + dr + lab)}


def _prepare(cfg, segments, defects):
    seg = segments.set_index("segment_id")
    d = defects.copy()
    d["ut_mode"] = d["ut_mode"].fillna("").astype(str).str.strip()
    d["medium"] = d["segment_id"].map(seg["medium"])
    d["elevated"] = d["segment_id"].map(seg["elevated"]).astype(bool)
    d["consequence"] = d["medium"].map(lambda m: network.consequence(m, cfg))
    return d.reset_index(drop=True)


def _labor(cfg, km_walk, km_drone, ut_points, scaffolds):
    return (km_walk / _s(cfg, "walk_km_per_h") + km_drone / _s(cfg, "drone_km_per_h")
            + ut_points * _s(cfg, "ut_hours_per_point")
            + scaffolds * _s(cfg, "scaffold_hours"))


def run_baseline(cfg, segments, features, defects, rng):
    """Human walkdown + fixed CMLs per segment (elevated segments need scaffold)."""
    d = _prepare(cfg, segments, defects)
    n = len(d)
    km = segments["length_m"].sum() / 1000.0

    # human visual: visible external defects and CUI cladding stains; harder on elevated pipe
    hb0, hb1 = _pod_params(cfg, "human")
    p = pod_prob(d["area_cm2"], hb0, hb1)
    p = np.where(d["elevated"], p * _s(cfg, "human_elevated_factor"), p)
    sees = d["visible_external"].to_numpy(bool) | (
        (d["kind"] == "cui") & d["external_sign"].fillna(False).astype(bool)).to_numpy()
    p = np.where(sees, p, 0.0)
    seen = _draw(rng, p) if n else np.zeros(0, bool)

    # fixed UT points (not on PVC); defect measured only if inside the footprint
    seg = segments.set_index("segment_id")
    metal = (segments["material"] != "pvc").to_numpy()
    k = int(_s(cfg, "cml_per_segment"))
    foot = _s(cfg, "probe_footprint_m")
    cml_seg = segments.loc[metal]
    ut_points = int(len(cml_seg) * k)
    cml = {sid: (np.arange(k) + 0.5) / k * L
           for sid, L in zip(cml_seg["segment_id"], cml_seg["length_m"])}
    near = np.zeros(n, bool)
    for i, (sid, pos) in enumerate(zip(d["segment_id"], d["pos_m"])):
        pts = cml.get(sid)
        near[i] = pts is not None and bool((np.abs(pts - pos) <= foot).any())
    # CMLs are straight-beam thickness points: they cannot detect cracks (angle-beam)
    ut_hit = near & _draw(rng, _ut_pod(cfg, d, ("straight",))) if n else near
    scaffolds = int(seg.loc[cml_seg["segment_id"], "elevated"].sum())

    counts = {"ut_points": ut_points, "drone_ut_points": 0, "scaffolds": scaffolds,
              "drone_km": 0.0, "walk_km": km,
              "labor_hours": _labor(cfg, km, 0.0, ut_points, scaffolds)}
    return _metrics(cfg, d, seen | ut_hit, counts)


def _rank_crack_points(cfg, segments, f, s, metal, cons, kind):
    """Angle-beam UT at the top-ranked weld/elbow locations within a fixed UT budget.

    score = (age / age_ref)^exponent x consequence x location weight (weld > elbow);
    the budget is `crack_ut_budget_frac` x the baseline's fixed UT point count.
    """
    age = np.maximum(params.get(cfg, "network.reference_year") - s["install_year"].to_numpy(), 0)
    age_f = (age / params.get(cfg, "defects.age_ref_years")) ** params.get(
        cfg, "defects.age_exponent")
    w = {k: params.get(cfg, f"defects.crack.location_weight.{k}") for k in ("weld", "elbow")}
    kw = np.where(kind == "weld", w["weld"], np.where(kind == "elbow", w["elbow"], 0.0))
    cand = metal & (kw > 0)
    score = np.where(cand, age_f * cons * kw, -1.0)
    n_base = int(_s(cfg, "cml_per_segment")) * int((segments["material"] != "pvc").sum())
    budget = int(_s(cfg, "crack_ut_budget_frac") * n_base)
    order = np.argsort(-score, kind="stable")[:budget]
    out = np.zeros(len(f), bool)
    out[order] = True
    return out & cand


def _risk_features(cfg, segments, features, rng):
    """Features chosen for risk-based UT: returns (thin_ids, crack_ids, cui_ids)."""
    seg = segments.set_index("segment_id")
    f = features[features["segment_id"].isin(seg.index)].copy()
    s = seg.loc[f["segment_id"]]
    metal = (s["material"] != "pvc").to_numpy()
    cs = (s["material"] == "carbon_steel").to_numpy()
    cons = s["medium"].map(lambda m: network.consequence(m, cfg)).to_numpy()
    kind = f["kind"].to_numpy()
    u = rng.random(len(f))
    fac_media = set(params.get(cfg, "defects.fac.media"))
    lo, hi = params.get(cfg, "defects.cui.temp_min_c"), params.get(cfg, "defects.cui.temp_max_c")
    thin = np.isin(kind, FAC_FEATURES) & cs & s["medium"].isin(fac_media).to_numpy()
    if _s(cfg, "crack_ut_mode") == "risk_ranked":
        crack = _rank_crack_points(cfg, segments, f, s, metal, cons, kind)
    else:
        crack = (metal & (cons >= _s(cfg, "risk_ut_consequence_min"))
                 & (((kind == "weld") & (u < _s(cfg, "weld_sample_frac"))) | (kind == "elbow")))
    cui = (cs & s["insulated"].to_numpy() & s["temp_c"].between(lo, hi).to_numpy()
           & (((kind == "support") & (u < _s(cfg, "support_sample_frac")))
              | np.isin(kind, ("nozzle", "dead_leg"))))
    ids = f["feature_id"].to_numpy()
    return set(ids[thin]), set(ids[crack]), set(ids[cui]), f.assign(
        thin=thin, crack=crack, cui=cui)


def run_ai_triage(cfg, segments, features, defects, rng):
    """Camera sweep of every segment, then UT at flagged spots + risk features."""
    d = _prepare(cfg, segments, defects)
    n = len(d)
    km = segments["length_m"].sum() / 1000.0

    cb0, cb1 = _pod_params(cfg, "camera")
    sees = d["visible_external"].to_numpy(bool) | (
        (d["kind"] == "cui") & d["external_sign"].to_numpy(bool)).to_numpy()
    cam = _draw(rng, np.where(sees, pod_prob(d["area_cm2"], cb0, cb1), 0.0)) \
        if n else np.zeros(0, bool)

    # UT confirmation at each camera-flagged defect (flange leaks need no UT)
    has_ut = (d["ut_mode"] != "").to_numpy()  # normalised in _prepare
    confirm = cam & has_ut
    conf_hit = confirm & _draw(rng, _ut_pod(cfg, d)) if n else confirm
    cam_found = cam & ~has_ut | conf_hit

    # false flags: extra UT points on defect-free segments
    defect_segs = set(d["segment_id"])
    clean = [s for s in segments["segment_id"] if s not in defect_segs]
    n_false = int((rng.random(len(clean)) < _s(cfg, "camera_false_flag_prob")).sum())
    false_seg = list(rng.choice(clean, n_false, replace=False)) if n_false else []

    # risk-based UT at features; a feature point measures defects tied to that feature
    thin_ids, crack_ids, cui_ids, ff = _risk_features(cfg, segments, features, rng)
    fid = d["feature_id"].fillna("").to_numpy()
    kind = d["kind"].to_numpy()
    cover = (np.isin(fid, list(thin_ids)) & np.isin(kind, ("fac_thinning", "internal_pitting"))) \
        | (np.isin(fid, list(cui_ids)) & (kind == "cui")) \
        | (np.isin(fid, list(crack_ids)) & (kind == "crack"))
    feat_hit = cover & _draw(rng, _ut_pod(cfg, d)) if n else cover

    thin_cui = ff["thin"] | ff["cui"]
    pts = pd.concat([
        pd.DataFrame({"segment_id": ff.loc[thin_cui, "segment_id"]}),
        pd.DataFrame({"segment_id": ff.loc[ff["crack"], "segment_id"]}),
        pd.DataFrame({"segment_id": d["segment_id"][confirm]}),
        pd.DataFrame({"segment_id": false_seg}, dtype=object)], ignore_index=True)
    seg_elev = segments.set_index("segment_id")["elevated"]
    elev = pts["segment_id"].map(seg_elev).fillna(False).astype(bool)
    n_pts = len(pts)
    if _s(cfg, "elevated_ut_mode") == "scaffold":
        scaffolds, drone_pts = int(pts.loc[elev, "segment_id"].nunique()), 0
    else:
        scaffolds, drone_pts = 0, int(elev.sum())
    counts = {"ut_points": n_pts, "drone_ut_points": drone_pts, "scaffolds": scaffolds,
              "drone_km": km, "walk_km": 0.0,
              "labor_hours": _labor(cfg, 0.0, km, n_pts, scaffolds)}
    return _metrics(cfg, d, cam_found | feat_hit, counts)


def run_all(cfg, seed, runs, total_km=None, strategies=("baseline", "ai_triage")):
    """Monte Carlo runs: {strategy: runs_df} (one row per run)."""
    res = {k: [] for k in strategies}
    for i in range(runs):
        seg, feat, dfx = network.generate_network(cfg, seed + i, total_km=total_km)
        if "baseline" in res:
            res["baseline"].append(run_baseline(cfg, seg, feat, dfx,
                                                np.random.default_rng([seed, i, 0])))
        if "ai_triage" in res:
            res["ai_triage"].append(run_ai_triage(cfg, seg, feat, dfx,
                                                  np.random.default_rng([seed, i, 1])))
    return {k: pd.DataFrame(v) for k, v in res.items()}


_run_all = run_all  # backward-compatible name


def compare(cfg, seed=0, runs=20, total_km=None, runs_df=None) -> pd.DataFrame:
    """Monte Carlo comparison: mean and 5-95% range per metric, plus AI/baseline ratio."""
    if runs_df is None:
        runs_df = run_all(cfg, seed, runs, total_km)
    rows = {}
    for name, df in runs_df.items():
        for col in df.columns:
            v = df[col].to_numpy(float)
            ok = v[~np.isnan(v)]
            rows.setdefault(col, {})[name] = (
                (float(ok.mean()), float(np.percentile(ok, 5)), float(np.percentile(ok, 95)))
                if len(ok) else (np.nan,) * 3)
    out = []
    for col, r in rows.items():
        b, a = r["baseline"], r["ai_triage"]
        ratio = a[0] / b[0] if b[0] and not np.isnan(b[0]) else np.nan
        out.append({"metric": col, "baseline_mean": b[0], "baseline_p5": b[1],
                    "baseline_p95": b[2], "ai_mean": a[0], "ai_p5": a[1], "ai_p95": a[2],
                    "ratio_ai_over_baseline": ratio})
    return pd.DataFrame(out)


def compare_and_sensitivity(cfg, seed=0, runs=20, total_km=None, factors=(0.5, 1.5)):
    """(compare table, sensitivity table) from a single Monte Carlo run."""
    runs_df = run_all(cfg, seed, runs, total_km)
    return (compare(cfg, runs_df=runs_df),
            sensitivity(cfg, factors=factors, runs_df=runs_df))


def sensitivity(cfg, seed=0, runs=20, total_km=None, factors=(0.5, 1.5),
                runs_df=None) -> pd.DataFrame:
    """Scale each unit cost by factors; report mean cost of each strategy and AI/baseline."""
    if runs_df is None:
        runs_df = run_all(cfg, seed, runs, total_km)
    base = {k: _s(cfg, k) for k in COST_KEYS}
    cols = ["ut_points", "drone_ut_points", "scaffolds", "drone_km", "labor_hours"]

    def mean_cost(df, unit):
        return float(np.mean([cost_breakdown(cfg, r, unit)["cost_krw"]
                              for r in df[cols].to_dict("records")]))

    rows = []
    for key in COST_KEYS:
        for f in factors:
            unit = dict(base)
            unit[key] = base[key] * f
            b, a = mean_cost(runs_df["baseline"], unit), mean_cost(runs_df["ai_triage"], unit)
            rows.append({"cost_key": key, "factor": f, "baseline_cost_krw": b,
                         "ai_cost_krw": a, "cost_ratio_ai_over_baseline": a / b if b else np.nan})
    return pd.DataFrame(rows)


def to_markdown(df: pd.DataFrame, floatfmt="{:.3f}") -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df.itertuples(index=False):
        lines.append("| " + " | ".join(
            floatfmt.format(v) if isinstance(v, float) else str(v) for v in r) + " |")
    return "\n".join(lines)
