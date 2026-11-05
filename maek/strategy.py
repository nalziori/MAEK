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


def _by_seg(d):
    """segment_id -> (defect positions, defect feature ids) for wasted-measurement checks.

    Only UT-relevant defects (ut_mode straight / angle) count: insulation, steam, tracer and
    trap defects cannot be seen by UT, so they must not make a UT point non-empty.
    """
    out = {}
    d = d[np.isin(_mode(d), ("straight", "angle"))]
    for sid, g in d.groupby("segment_id", sort=False):
        out[sid] = (g["pos_m"].to_numpy(float), g["feature_id"].fillna("").to_numpy())
    return out


def _empty_count(by_seg, seg_ids, pos, half, fids=None):
    """Number of UT points with no defect within +-half m (or tied to the point's feature)."""
    n = 0
    for i, (sid, x) in enumerate(zip(seg_ids, pos)):
        hit = by_seg.get(sid)
        ok = hit is not None and bool((np.abs(hit[0] - x) <= half).any())
        if not ok and fids is not None and hit is not None and fids[i]:
            ok = bool((hit[1] == fids[i]).any())
        n += not ok
    return n


def _metrics(cfg, defects, found, counts, en):
    """Detection + energy metrics (NaN where nothing to detect) + resource counts."""
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
    out.update(_energy_metrics(defects, found, en))
    out.update({k: float(v) for k, v in counts.items()})
    out["empty_ut_rate"] = (float(counts["empty_ut_points"] / counts["ut_points"])
                            if counts["ut_points"] else np.nan)
    out.update(cost_breakdown(cfg, counts))
    km = counts["km"]
    out["cost_krw_per_km"] = out["cost_krw"] / km if km else np.nan
    out["labor_hours_per_km"] = float(counts["labor_hours"] / km) if km else np.nan
    return out


def _energy_metrics(d, found, en):
    """Energy-loss totals found (loss-weighted), found rates per kind (count based), traps."""
    kind = d["kind"].to_numpy()
    idx = pd.Index(d["defect_id"]).get_indexer(en["defect_id"]) if len(en) else np.zeros(0, int)
    ok = idx >= 0
    fnd = np.zeros(len(en), bool)
    fnd[ok] = found[idx[ok]]
    tot = float(en["mwh_per_yr"].sum())
    out = {"energy_loss_mwh": tot,
           "energy_found_mwh": float(en.loc[fnd, "mwh_per_yr"].sum()),
           "energy_found_krw_per_yr": float(en.loc[fnd, "cost_krw_per_yr"].sum()),
           "energy_found_co2_t": float(en.loc[fnd, "co2_t_per_yr"].sum())}
    out["energy_found_frac"] = out["energy_found_mwh"] / tot if tot > 0 else np.nan
    for k in FOUND_KINDS:
        m = kind == k
        out[f"found_rate_{k}"] = float(found[m].sum() / m.sum()) if m.any() else np.nan
    failed = np.isin(kind, TRAP_KINDS)
    out["traps_failed"] = float(failed.sum())
    out["traps_found"] = float((found & failed).sum())
    return out


def _media(cfg):
    return [k for k in cfg["network"]["media_mix"]]


def cost_breakdown(cfg, counts, unit=None):
    """Total cost (KRW) from resource counts; every priced count has its own unit cost."""
    unit = unit or {k: _s(cfg, k) for k in COST_KEYS}
    g = counts.get
    ut = counts["ut_points"] * unit["cost_ut_point_krw"]
    ut += counts["drone_ut_points"] * unit["cost_drone_contact_ut_extra_krw"]
    ut += g("insulation_openings", 0.0) * unit["cost_insulation_opening_krw"]
    sc = counts["scaffolds"] * unit["cost_scaffold_krw"]
    sc += g("lift_days", 0.0) * unit["cost_lift_day_krw"]
    dr = counts["drone_km"] * unit["cost_drone_per_km_krw"]
    ai = g("ai_km", 0.0) * unit["cost_ai_processing_per_km_krw"]
    pc = g("pec_hours", 0.0) * unit["cost_pec_hour_krw"]
    lab = counts["labor_hours"] * unit["cost_labor_hour_krw"]
    return {"cost_krw": float(ut + sc + dr + ai + pc + lab)}


def _prepare(cfg, segments, defects):
    seg = segments.set_index("segment_id")
    d = defects.copy()
    d["ut_mode"] = d["ut_mode"].fillna("").astype(str).str.strip()
    d["medium"] = d["segment_id"].map(seg["medium"])
    d["elevated"] = d["segment_id"].map(seg["elevated"]).astype(bool)
    d["insulated"] = d["segment_id"].map(seg["insulated"]).fillna(False).astype(bool)
    d["consequence"] = d["medium"].map(lambda m: network.consequence(m, cfg))
    return d.reset_index(drop=True)


def _effort(cfg, *, km_walk=0.0, km_flight=0.0, n_segments=0, manual_pts=0, drone_pts=0,
            scaffolds=0, review_km=0.0, flags=0, openings=0, pec_h=0.0, trap_tests=0,
            lift_pts=0, ir_review_km=0.0):
    """Labour hours (by activity) and elapsed calendar days (phases run one after another).

    Human crews: walkdown, scaffolds / lift positioning, insulation openings, manual UT, PEC
    scanning, trap tests. Drone teams: flights (+ setup per batch of segments) and drone contact
    UT. Reviewers: video / IR review and AI-flag verification. Lift hire days = ceil(lift hours
    / work hours per day).
    """
    walk = km_walk / _s(cfg, "walk_km_per_h")
    batches = int(np.ceil(n_segments / _s(cfg, "drone_batch_segments"))) if km_flight else 0
    flight = km_flight / _s(cfg, "drone_km_per_h") + batches * _s(cfg, "drone_setup_h_per_batch")
    scaf = scaffolds * _s(cfg, "scaffold_hours")
    ut_man = manual_pts * _s(cfg, "ut_manual_min_per_point") / 60.0
    ut_drn = drone_pts * _s(cfg, "ut_drone_min_per_point") / 60.0
    opening = openings * _s(cfg, "insulation_opening_min") / 60.0
    trap = trap_tests * _s(cfg, "trap_test_min") / 60.0
    lift = lift_pts * _s(cfg, "lift_min_per_point") / 60.0
    review = (review_km * _s(cfg, "video_review_min_per_km")
              + ir_review_km * _s(cfg, "ir_review_min_per_km")
              + flags * _s(cfg, "ai_verify_min_per_flag")) / 60.0
    day = _s(cfg, "work_hours_per_day")
    crew = walk + scaf + ut_man + opening + pec_h + trap + lift
    days = (crew / (_s(cfg, "crews") * day)
            + (flight + ut_drn) / (_s(cfg, "drones") * day)
            + review / (_s(cfg, "reviewers") * day))
    return {"hours_walk": walk, "hours_flight": flight, "hours_scaffold": scaf,
            "hours_ut": ut_man + ut_drn, "hours_opening": opening, "hours_pec": pec_h,
            "hours_trap": trap, "hours_lift": lift, "hours_review": review,
            "lift_days": float(np.ceil(lift / day - 1e-9)) if lift > 0 else 0.0,
            "labor_hours": crew + flight + ut_drn + review, "elapsed_days": days}


def _resources(cfg, seg_idx, sids, drone_ok, zone_sids=()):
    """Access and opening counts for UT points (segment ids) and PEC zones (segment ids).

    A point is a drone contact point only on an elevated, uninsulated segment (and only if
    `drone_ok`); every other point is done by people. People on elevated pipe need a scaffold
    (once per elevated segment with any human activity: UT, PEC, opening) or, in `lift` mode,
    lift time per point. Every human point on an insulated segment needs an insulation opening.
    """
    sids = np.asarray(list(sids), object)
    zs = np.asarray(list(zone_sids), object)

    def attr(col, ids):
        if not len(ids):
            return np.zeros(0, bool)
        return seg_idx[col].reindex(ids).fillna(False).astype(bool).to_numpy()

    elev, ins = attr("elevated", sids), attr("insulated", sids)
    drone = elev & ~ins & bool(drone_ok)
    human_el = elev & ~drone
    zel = attr("elevated", zs)
    n_human_el = int(human_el.sum() + zel.sum())
    lift = _s(cfg, "human_elevated_access") == "lift"
    scaffolds = 0 if lift else len(set(sids[human_el]) | set(zs[zel]))
    return {"ut_points": len(sids), "drone_ut_points": int(drone.sum()),
            "insulation_openings": int(ins.sum()), "scaffolds": scaffolds,
            "lift_points": n_human_el if lift else 0}


def _drone_def(d, drone_ok):
    """Per defect: measured by drone contact UT (elevated, uninsulated segment); None if off."""
    if not drone_ok:
        return None
    return (d["elevated"] & ~d["insulated"]).to_numpy(bool)


def _fixed_ut(cfg, segments, d, rng, drone_elevated):
    """Fixed CMLs (straight-beam) at every metal segment: (hit, counts).

    Elevated uninsulated segments get drone contact UT if `drone_elevated`; all other points
    are manual (scaffold / lift on elevated pipe, insulation opening on insulated pipe).
    CMLs cannot detect cracks (angle-beam).
    """
    n = len(d)
    seg_idx = segments.set_index("segment_id")
    metal = (segments["material"] != "pvc").to_numpy()
    k = int(_s(cfg, "cml_per_segment"))
    foot = _s(cfg, "probe_footprint_m")
    cml_seg = segments.loc[metal]
    cml = {sid: (np.arange(k) + 0.5) / k * L
           for sid, L in zip(cml_seg["segment_id"], cml_seg["length_m"])}
    near = np.zeros(n, bool)
    for i, (sid, pos) in enumerate(zip(d["segment_id"], d["pos_m"])):
        pts = cml.get(sid)
        near[i] = pts is not None and bool((np.abs(pts - pos) <= foot).any())
    drone = _drone_def(d, drone_elevated)
    hit = near & _draw(rng, _ut_pod(cfg, d, ("straight",), drone)) if n else near
    by_seg = _by_seg(d)
    ids = [sid for sid in cml for _ in range(k)]
    pos = [x for sid in cml for x in cml[sid]]
    res = _resources(cfg, seg_idx, ids, drone_elevated)
    res["empty_ut_points"] = _empty_count(by_seg, ids, pos, foot)
    return hit, res


def _trap_test_all(cfg, d, features, rng):
    """Every steam trap tested by people: (found mask over d, number of tests)."""
    n_traps = int((features["kind"] == "steam_trap").sum())
    failed = np.isin(d["kind"].to_numpy(), TRAP_KINDS)
    p = np.where(failed, _s(cfg, "trap_test_pod"), 0.0)
    return failed & _draw(rng, p), n_traps


def _ir_hits(cfg, seg_dict, d, rng, reviewer):
    """Bernoulli IR detections of jacket / leak defects (thermal.detect_prob, ir_condition)."""
    n = len(d)
    p = np.zeros(n)
    cond = _s(cfg, "ir_condition")
    for i in np.flatnonzero(np.isin(d["kind"].to_numpy(), IR_KINDS)):
        row = d.iloc[i].to_dict()
        p[i] = thermal.detect_prob(cfg, seg_dict[row["segment_id"]], row, cond, reviewer)
    return _draw(rng, p)


def _seg_dict(segments):
    return segments.set_index("segment_id").to_dict("index")


def run_baseline(cfg, segments, features, defects, rng, en=None):
    """Human walkdown + fixed CMLs per segment + a trap test of every steam trap.

    Elevated pipe needs scaffolds (or a lift), insulated points need an insulation opening.
    """
    en = energy.losses(cfg, segments, defects) if en is None else en
    d = _prepare(cfg, segments, defects)
    n = len(d)
    km = segments["length_m"].sum() / 1000.0

    # human visual: visible external defects and CUI cladding stains; harder on elevated pipe
    hb0, hb1 = _pod_params(cfg, "human")
    p = pod_prob(d["area_cm2"], hb0, hb1)
    p = np.where(d["elevated"], p * _s(cfg, "human_elevated_factor"), p)
    sees = _visible(d)
    seen = _draw(rng, np.where(sees, p, 0.0)) if n else np.zeros(0, bool)

    ut_hit, fx = _fixed_ut(cfg, segments, d, rng, drone_elevated=False)
    trap_hit, n_tests = _trap_test_all(cfg, d, features, rng)
    counts = {**_ZERO, **fx, "walk_km": km, "km": km, "trap_tests": n_tests,
              **_effort(cfg, km_walk=km, manual_pts=fx["ut_points"], scaffolds=fx["scaffolds"],
                        openings=fx["insulation_openings"], trap_tests=n_tests,
                        lift_pts=fx["lift_points"])}
    return _metrics(cfg, d, seen | ut_hit | trap_hit, counts, en)


def _visible(d):
    """Defects with an external sign: visible rust / leak stain / plume / bare insulation gap,
    or CUI and wet insulation with a cladding sign."""
    sign = d["external_sign"].fillna(False).astype(bool)
    return (d["visible_external"].to_numpy(bool)
            | (d["kind"].isin(("cui", "wet_insulation")) & sign).to_numpy())


def run_drone(cfg, segments, features, defects, rng, en=None):
    """Drone video (visual + IR) of every segment reviewed by people; same fixed CMLs.

    Drone contact UT only on elevated uninsulated pipe; elevated insulated points still need
    scaffolds / lift and an opening. All traps are tested by people.
    """
    en = energy.losses(cfg, segments, defects) if en is None else en
    d = _prepare(cfg, segments, defects)
    n = len(d)
    km = segments["length_m"].sum() / 1000.0
    p = np.where(_visible(d), pod_prob(d["area_cm2"], *_pod_params(cfg, "human_video")), 0.0)
    seen = _draw(rng, p) if n else np.zeros(0, bool)
    ir = _ir_hits(cfg, _seg_dict(segments), d, rng, "human")

    ut_hit, fx = _fixed_ut(cfg, segments, d, rng, drone_elevated=True)
    trap_hit, n_tests = _trap_test_all(cfg, d, features, rng)
    counts = {**_ZERO, **fx, "drone_km": km, "km": km, "trap_tests": n_tests,
              **_effort(cfg, km_flight=km, n_segments=len(segments),
                        manual_pts=fx["ut_points"] - fx["drone_ut_points"],
                        drone_pts=fx["drone_ut_points"], review_km=km, ir_review_km=km,
                        scaffolds=fx["scaffolds"], openings=fx["insulation_openings"],
                        trap_tests=n_tests, lift_pts=fx["lift_points"])}
    return _metrics(cfg, d, seen | ut_hit | ir | trap_hit, counts, en)


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
    ins_cs = cs & s["insulated"].to_numpy(bool)
    return set(ids[thin]), set(ids[crack]), set(ids[cui]), f.assign(
        thin=thin, crack=crack, cui=cui, ins_cs=ins_cs, low_point=(kind == "low_point") & ins_cs)


def _rank_pit_segments(cfg, segments):
    """Segments ordered by internal-pitting risk (most pitting-prone first).

    network.py places internal pitting on metal segments of `defects.internal_pitting.media`
    with an expected count ~ rate x km x f, f = (age/age_ref)^exp x (1 + gain (c-1)/4)
    (uniform along the pipe, not tied to features). Score = f x consequence, so an
    age/consequence-weighted ranking over exactly the candidate segments.
    """
    media = set(params.get(cfg, "defects.internal_pitting.media"))
    age = np.maximum(params.get(cfg, "network.reference_year")
                     - segments["install_year"].to_numpy(), 0)
    cons = segments["medium"].map(lambda m: network.consequence(m, cfg)).to_numpy()
    f = (age / params.get(cfg, "defects.age_ref_years")) ** params.get(
        cfg, "defects.age_exponent") * (1 + params.get(cfg, "defects.consequence_gain")
                                       * (cons - 1) / 4)
    cand = (segments["material"] != "pvc").to_numpy() & segments["medium"].isin(media).to_numpy()
    score = np.where(cand, f * cons, -1.0)
    order = np.argsort(-score, kind="stable")
    return order[score[order] > 0]


def _pit_scans(cfg, segments, budget_pts, rng, features=None):
    """Risk-ranked straight-beam area scans: list of (segment_id, centre_m, length_m).

    `pit_scan_target` wet_spot centres the window on a randomly chosen wet-spot feature of the
    segment (low point / dead leg: at the feature; steam trap: 1 m upstream, where condensate
    pools); segments without such a feature, and the `random` target, use a random window.
    """
    k = max(int(_s(cfg, "pit_scan_k")), 1)
    n_scans = max(int(budget_pts) // k, 0)
    fp = _s(cfg, "pit_scan_footprint_m")
    order = _rank_pit_segments(cfg, segments)[:n_scans]
    spots = {}
    if features is not None and _s(cfg, "pit_scan_target") == "wet_spot":
        wf = features[features["kind"].isin(("low_point", "dead_leg", "steam_trap"))]
        for sid, g in wf.groupby("segment_id", sort=False):
            spots[sid] = (g["pos_m"].to_numpy(float) - np.where(g["kind"] == "steam_trap", 1.0, 0.0))
    out = []
    for i in order:
        sid = segments["segment_id"].iat[i]
        L = float(segments["length_m"].iat[i])
        w = min(fp, L)
        if sid in spots:
            c = float(np.clip(spots[sid][rng.integers(len(spots[sid]))], w / 2, L - w / 2))
        else:
            c = float(rng.uniform(w / 2, L - w / 2))
        out.append((sid, c, w))
    return out


def _merge_zones(rows):
    """[(sid, lo, hi)] -> merged, sorted, non-overlapping zones per segment."""
    out = []
    for sid, lo, hi in sorted(rows, key=lambda r: (r[0], r[1])):
        if out and out[-1][0] == sid and lo <= out[-1][2]:
            out[-1] = (sid, out[-1][1], max(out[-1][2], hi))
        else:
            out.append((sid, lo, hi))
    return out


def _pec_stage(cfg, seg_dict, d, zones, rng, ut_p):
    """PEC scans of `zones` [(sid, lo, hi)]: (found mask, counts, confirm sids, false sids).

    A defect of pec.PEC_KINDS inside a zone (+- half the PEC footprint) is reported with
    pec.detect_prob; a report is confirmed by one manual straight-beam UT point (with an
    insulation opening) with the manual UT POD. A zone without any report triggers an extra
    (empty) UT confirmation with `pec_false_call_prob` (x factor on galvanized jackets).
    """
    n = len(d)
    by_seg = {}
    for j, (sid, lo, hi) in enumerate(zones):
        by_seg.setdefault(sid, []).append((j, lo, hi))
    p = np.zeros(n)
    zone_of = np.full(n, -1)
    kind, sid_a, pos = d["kind"].to_numpy(), d["segment_id"].to_numpy(), d["pos_m"].to_numpy(float)
    for i in np.flatnonzero(np.isin(kind, pec.PEC_KINDS)):
        zl = by_seg.get(sid_a[i])
        if not zl:
            continue
        seg = seg_dict[sid_a[i]]
        half = pec.footprint_mm(cfg, seg["insulation_mm"]) / 2000.0
        for j, lo, hi in zl:
            if lo - half <= pos[i] <= hi + half:
                zone_of[i] = j
                p[i] = pec.detect_prob(cfg, seg, d.iloc[i].to_dict())
                break
    hit = _draw(rng, p)
    found = hit & _draw(rng, ut_p)
    has_hit = np.zeros(len(zones), bool)
    has_hit[zone_of[hit]] = True
    fc_p = np.array([_s(cfg, "pec_false_call_prob")
                     * (_s(cfg, "pec_false_call_galvanized_factor")
                        if seg_dict[z[0]]["jacket"] == "galvanized" else 1.0)
                     for z in zones])
    false_call = (~has_hit) & (rng.random(len(zones)) < fc_p)
    length = np.array([hi - lo for _, lo, hi in zones])
    hours = float(sum(pec.scan_minutes(cfg, ln) for ln in length)) / 60.0
    counts = {"pec_zones": len(zones), "pec_m": float(length.sum()), "pec_hours": hours}
    return (found, counts, list(sid_a[hit]), [zones[j][0] for j in np.flatnonzero(false_call)])


def _trap_stage_ai(cfg, seg_dict, d, features, rng):
    """AI trap triage: IR rule flags traps, people test flagged + a sample of the rest.

    Returns (found mask over d, traps tested, IR trap flags). `ai_trap_mode: full` tests all.
    """
    if _s(cfg, "ai_trap_mode") == "full":
        hit, n_tests = _trap_test_all(cfg, d, features, rng)
        return hit, n_tests, 0
    cond = _s(cfg, "ir_condition")
    n_traps = int((features["kind"] == "steam_trap").sum())
    fi = np.flatnonzero(np.isin(d["kind"].to_numpy(), TRAP_KINDS))
    nf = len(fi)
    p_flag = np.array([thermal.detect_prob(cfg, seg_dict[d["segment_id"].iat[i]],
                                           d.iloc[i].to_dict(), cond, "ai") for i in fi])
    flag = rng.random(nf) < p_flag
    tested = flag | (rng.random(nf) < _s(cfg, "trap_sample_frac"))
    ok = tested & (rng.random(nf) < _s(cfg, "trap_test_pod"))
    n_norm = max(n_traps - nf, 0)
    fa = int(rng.binomial(n_norm, cfg["thermal"]["trap"][cond]["false_alarm"]["value"]))
    sample = int(rng.binomial(n_norm - fa, _s(cfg, "trap_sample_frac")))
    found = np.zeros(len(d), bool)
    found[fi[ok]] = True
    return found, int(tested.sum()) + fa + sample, int(flag.sum()) + fa


def run_ai_triage(cfg, segments, features, defects, rng, en=None):
    """Camera + IR sweep of every segment, then UT / PEC at flagged spots + risk features +
    pit scans, and IR-triaged steam-trap tests."""
    en = energy.losses(cfg, segments, defects) if en is None else en
    d = _prepare(cfg, segments, defects)
    n = len(d)
    km = segments["length_m"].sum() / 1000.0
    seg_idx = segments.set_index("segment_id")
    seg_dict = _seg_dict(segments)
    drone_el = _s(cfg, "elevated_ut_mode") != "scaffold"
    drone_def = _drone_def(d, drone_el)

    cb0, cb1 = _pod_params(cfg, "camera")
    cam = _draw(rng, np.where(_visible(d), pod_prob(d["area_cm2"], cb0, cb1), 0.0)) \
        if n else np.zeros(0, bool)
    ir = _ir_hits(cfg, seg_dict, d, rng, "ai")

    # UT confirmation at each camera-flagged defect (flange leaks, energy defects need no UT)
    has_ut = (d["ut_mode"] != "").to_numpy()  # normalised in _prepare
    confirm = cam & has_ut
    conf_hit = confirm & _draw(rng, _ut_pod(cfg, d, drone=drone_def)) if n else confirm
    cam_found = cam & ~has_ut | conf_hit

    # false flags: extra UT points on defect-free segments
    defect_segs = set(d["segment_id"])
    clean = [s for s in segments["segment_id"] if s not in defect_segs]
    n_false = int((rng.random(len(clean)) < _s(cfg, "camera_false_flag_prob")).sum())
    false_seg = list(rng.choice(clean, n_false, replace=False)) if n_false else []

    # risk-based features: insulated carbon steel gets PEC (wall loss) instead of UT
    ff = _risk_features(cfg, segments, features, rng)[3]
    wall = ff["thin"] | ff["cui"]
    ut_wall = ff[wall & ~ff["ins_cs"]]
    pec_feat = ff[(wall & ff["ins_cs"]) | ff["low_point"]]
    crack_f = ff[ff["crack"]]
    fid = d["feature_id"].fillna("").to_numpy()
    kind = d["kind"].to_numpy()
    cover = (np.isin(fid, ut_wall.loc[ut_wall["thin"], "feature_id"].to_numpy())
             & np.isin(kind, ("fac_thinning", "internal_pitting"))) \
        | (np.isin(fid, ut_wall.loc[ut_wall["cui"], "feature_id"].to_numpy()) & (kind == "cui")) \
        | (np.isin(fid, crack_f["feature_id"].to_numpy()) & (kind == "crack"))
    feat_hit = cover & _draw(rng, _ut_pod(cfg, d, drone=drone_def)) if n else cover
    fpts = pd.concat([ut_wall, crack_f])  # one UT point per role

    # PEC zones: wet insulation found by camera / IR, and the risk features above
    half = _s(cfg, "pec_feature_zone_m") / 2.0
    length = seg_idx["length_m"]
    cs = seg_idx["material"] == "carbon_steel"
    rows = [(s, max(x - half, 0.0), min(x + half, length[s]))
            for s, x in zip(pec_feat["segment_id"], pec_feat["pos_m"])]
    seen_wet = (cam | ir) & (kind == "wet_insulation")
    for s, x, ln in zip(d["segment_id"][seen_wet], d["pos_m"][seen_wet],
                        d["length_mm"][seen_wet] / 1000.0):
        if cs[s] and seg_idx.at[s, "insulated"]:
            rows.append((s, max(x - ln / 2, 0.0), min(x + ln / 2, length[s])))
    zones = _merge_zones(rows)
    pec_found, pec_counts, pec_conf, pec_false = _pec_stage(
        cfg, seg_dict, d, zones, rng, _ut_pod(cfg, d, ("straight",), None) if n else np.zeros(0))

    trap_found, n_trap_tests, trap_flags = _trap_stage_ai(cfg, seg_dict, d, features, rng)

    base_pts = (list(ut_wall["segment_id"]) + list(crack_f["segment_id"])
                + list(d["segment_id"][confirm]) + false_seg + pec_conf + pec_false)

    # risk-ranked straight-beam area scans for internal pitting (no external sign):
    # budget in UT points, capped so the total stays within the baseline's fixed UT points
    k = max(int(_s(cfg, "pit_scan_k")), 1)
    n_base = int(_s(cfg, "cml_per_segment")) * int((segments["material"] != "pvc").sum())
    budget = min(int(_s(cfg, "pit_scan_budget_frac") * n_base), max(n_base - len(base_pts), 0))
    scans = _pit_scans(cfg, segments, budget, rng, features)
    scan_hit = np.zeros(n, bool)
    if scans and n:
        pos = d["pos_m"].to_numpy(float)
        sid = d["segment_id"].to_numpy()
        inside = np.zeros(n, bool)
        for s_id, c, w in scans:
            inside |= (sid == s_id) & (np.abs(pos - c) <= w / 2)
        inside &= (d["ut_mode"] == "straight").to_numpy()
        scan_hit = inside & _draw(rng, _ut_pod(cfg, d, ("straight",), drone_def))
    scan_sids = [s_id for s_id, _, _ in scans for _ in range(k)]

    # wasted measurements: points with no UT-visible defect within the footprint
    by_seg = _by_seg(d)
    foot = _s(cfg, "probe_footprint_m")
    empty = _empty_count(by_seg, fpts["segment_id"], fpts["pos_m"], foot,
                         fpts["feature_id"].to_numpy())
    empty += len(false_seg) + len(pec_false)
    for s_id, c, w in scans:
        cells = c - w / 2 + (np.arange(k) + 0.5) * w / k
        empty += _empty_count(by_seg, [s_id] * k, cells, w / (2 * k))

    res = _resources(cfg, seg_idx, base_pts + scan_sids, drone_el, [z[0] for z in zones])
    flags = int((cam | ir).sum()) + n_false + trap_flags
    counts = {**_ZERO, **res, "drone_km": km, "ai_km": km, "km": km, "flags": flags,
              "empty_ut_points": empty, "pit_scan_points": len(scan_sids),
              "trap_tests": n_trap_tests, **pec_counts,
              **_effort(cfg, km_flight=km, n_segments=len(segments),
                        manual_pts=res["ut_points"] - res["drone_ut_points"],
                        drone_pts=res["drone_ut_points"], scaffolds=res["scaffolds"],
                        flags=flags, openings=res["insulation_openings"],
                        pec_h=pec_counts["pec_hours"], trap_tests=n_trap_tests,
                        lift_pts=res["lift_points"])}
    found = cam_found | feat_hit | scan_hit | pec_found | ir | trap_found
    return _metrics(cfg, d, found, counts, en)


_RUNNERS = {"baseline": (run_baseline, 0), "drone": (run_drone, 2),
            "ai_triage": (run_ai_triage, 1)}


def run_all(cfg, seed, runs, total_km=None, strategies=STRATEGIES):
    """Monte Carlo runs: {strategy: runs_df} (one row per run).

    Energy losses are computed once per generated network and shared by the strategies.
    """
    unknown = set(strategies) - set(_RUNNERS)
    if unknown:
        raise ValueError(f"unknown strategies: {sorted(unknown)}")
    res = {k: [] for k in strategies}
    for i in range(runs):
        seg, feat, dfx = network.generate_network(cfg, seed + i, total_km=total_km)
        en = energy.losses(cfg, seg, dfx)
        for name in strategies:
            fn, stream = _RUNNERS[name]
            res[name].append(fn(cfg, seg, feat, dfx, np.random.default_rng([seed, i, stream]),
                                en))
    return {k: pd.DataFrame(v) for k, v in res.items()}


_run_all = run_all  # backward-compatible name


def compare(cfg, seed=0, runs=20, total_km=None, runs_df=None) -> pd.DataFrame:
    """Per metric: mean and 5-95% range per strategy, and ratios vs baseline."""
    if runs_df is None:
        runs_df = run_all(cfg, seed, runs, total_km)
    names = list(runs_df)
    cols = list(dict.fromkeys(c for df in runs_df.values() for c in df.columns))
    out = []
    for col in cols:
        row = {"metric": col}
        for name in names:
            df = runs_df[name]
            v = df[col].to_numpy(float) if col in df else np.full(len(df), np.nan)
            ok = v[~np.isnan(v)]
            m, lo, hi = ((float(ok.mean()), float(np.percentile(ok, 5)),
                          float(np.percentile(ok, 95))) if len(ok) else (np.nan,) * 3)
            row.update({f"{name}_mean": m, f"{name}_p5": lo, f"{name}_p95": hi})
        b = row.get("baseline_mean", np.nan)
        for name in names:
            if name != "baseline":
                a = row[f"{name}_mean"]
                row[f"ratio_{name}_over_baseline"] = (
                    a / b if b and not np.isnan(b) and not np.isnan(a) else np.nan)
        out.append(row)
    return pd.DataFrame(out)


def compare_and_sensitivity(cfg, seed=0, runs=20, total_km=None, factors=(0.5, 1.5)):
    """(compare table, sensitivity table) from a single Monte Carlo run."""
    runs_df = run_all(cfg, seed, runs, total_km)
    return (compare(cfg, runs_df=runs_df),
            sensitivity(cfg, factors=factors, runs_df=runs_df))


def sensitivity(cfg, seed=0, runs=20, total_km=None, factors=(0.5, 1.5),
                runs_df=None) -> pd.DataFrame:
    """Scale each unit cost by factors; mean cost per strategy, cost and time ratios vs baseline.

    Elapsed days do not depend on unit costs, so the time ratios repeat on every row.
    """
    if runs_df is None:
        runs_df = run_all(cfg, seed, runs, total_km)
    base = {k: _s(cfg, k) for k in COST_KEYS}
    names = list(runs_df)

    def mean_cost(df, unit):
        return float(np.mean([cost_breakdown(cfg, r, unit)["cost_krw"]
                              for r in df[COUNT_COLS].to_dict("records")]))

    days = {n: float(runs_df[n]["elapsed_days"].mean()) for n in names}
    rows = []
    for key in COST_KEYS:
        for f in factors:
            unit = dict(base)
            unit[key] = base[key] * f
            cost = {n: mean_cost(runs_df[n], unit) for n in names}
            row = {"cost_key": key, "factor": f}
            row.update({f"{n}_cost_krw": cost[n] for n in names})
            for n in names:
                if n != "baseline":
                    row[f"cost_ratio_{n}"] = cost[n] / cost["baseline"] if cost["baseline"] \
                        else np.nan
                    row[f"time_ratio_{n}"] = days[n] / days["baseline"] if days["baseline"] \
                        else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


# (metric, Korean label, format) rows of the readable 3-column table
_TABLE = [
    ("detection_rate", "위험 결함 발견율", "{:.3f}"),
    ("detection_rate_external_corrosion", "  외부 부식", "{:.3f}"),
    ("detection_rate_cui", "  CUI", "{:.3f}"),
    ("detection_rate_fac_thinning", "  유동가속부식 감육", "{:.3f}"),
    ("detection_rate_crack", "  균열", "{:.3f}"),
    ("detection_rate_internal_pitting", "  내부 피팅", "{:.3f}"),
    ("missed_high_consequence_critical", "놓친 고피해 위험 결함 (개)", "{:.1f}"),
    ("ut_points", "UT 측정 지점", "{:,.0f}"),
    ("empty_ut_rate", "헛측정 비율", "{:.3f}"),
    ("scaffolds", "비계 설치", "{:,.0f}"),
    ("insulation_openings", "보온재 해체 (개소)", "{:,.0f}"),
    ("pec_zones", "PEC 구간", "{:,.0f}"),
    ("traps_found", "고장 트랩 발견", "{:,.1f}"),
    ("energy_found_frac", "에너지 손실 발견 비율", "{:.3f}"),
    ("energy_found_krw_per_yr", "발견 에너지 손실 (억 원/년)", "{:,.2f}"),
    ("labor_hours", "작업 시간 (인시)", "{:,.0f}"),
    ("elapsed_days", "소요 일수 (일)", "{:.1f}"),
    ("cost_krw", "비용 (백만 원)", "{:,.1f}"),
    ("cost_krw_per_km", "km당 비용 (만 원/km)", "{:,.1f}"),
]
_SCALE = {"cost_krw": 1e-6, "cost_krw_per_km": 1e-4, "energy_found_krw_per_yr": 1e-8}
_RATIO_ROWS = ("ut_points", "labor_hours", "elapsed_days", "cost_krw", "cost_krw_per_km",
               "insulation_openings")


def _cell(r, name, fmt, scale=1.0, ratio=True):
    m = r.get(f"{name}_mean", np.nan)
    if np.isnan(m):
        return "-"
    lo, hi = r[f"{name}_p5"], r[f"{name}_p95"]
    txt = f"{fmt.format(m * scale)} ({fmt.format(lo * scale)}~{fmt.format(hi * scale)})"
    q = r.get(f"ratio_{name}_over_baseline", np.nan)
    if ratio and name != "baseline" and not np.isnan(q):
        txt += f" x{q:.2f}"
    return txt


def _table(df):
    names = [n for n in STRATEGIES if f"{n}_mean" in df.columns]
    rows = df.set_index("metric").to_dict("index")
    lines = ["| 지표 | " + " | ".join(LABELS[n] for n in names) + " |",
             "|---|" + "---|" * len(names)]
    for key, label, fmt in _TABLE:
        if key not in rows:
            continue
        scale = _SCALE.get(key, 1.0)
        r = dict(rows[key])
        for n in names:  # ratio columns are keyed by strategy; map per cell
            r[f"ratio_{n}_over_baseline"] = rows[key].get(f"ratio_{n}_over_baseline", np.nan)
        lines.append(f"| {label} | " + " | ".join(
            _cell(r, n, fmt, scale, ratio=key in _RATIO_ROWS) for n in names) + " |")
    return "\n".join(lines) + "\n\n평균 (5~95% 범위); x는 사람+비계 대비 비율"


def to_markdown(df: pd.DataFrame, floatfmt="{:.3f}") -> str:
    """Compare table -> readable 3-strategy table; any other frame -> generic table."""
    if "metric" in df.columns and "baseline_mean" in df.columns:
        return _table(df)
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df.itertuples(index=False):
        lines.append("| " + " | ".join(
            (f"{v:,.0f}" if abs(v) >= 1e6 else floatfmt.format(v)) if isinstance(v, float)
            else str(v) for v in r) + " |")
    return "\n".join(lines)


def pit_prior_sensitivity(cfg, seed=0, runs=10, total_km=None, shares=(0.0, 0.3, 0.6, 0.9)):
    """What if the wet-spot prior is wrong? AI strategy only, area scans centred on wet spots
    vs random windows, for several true shares of pits that sit at wet spots.

    `pit_detection_*` = share of all internal pits found (count based, any criticality);
    the planner's prior is the config's `strategy.pit_scan_target`; the true share is
    `defects.internal_pitting.wet_spot_share`.
    """
    rows = []
    for share in shares:
        c0 = params.with_values(cfg, {"defects.internal_pitting.wet_spot_share": share})
        nets = [network.generate_network(c0, seed + i, total_km=total_km) for i in range(runs)]
        ens = [energy.losses(c0, seg, dfx) for seg, _, dfx in nets]
        for target in ("wet_spot", "random"):
            c = params.with_values(c0, {"strategy.pit_scan_target": target})
            df = pd.DataFrame([
                run_ai_triage(c, seg, feat, dfx, np.random.default_rng([seed, i, 1]), ens[i])
                for i, (seg, feat, dfx) in enumerate(nets)])
            v = df["found_rate_internal_pitting"].to_numpy(float)
            v = v[~np.isnan(v)]
            m, lo, hi = ((float(v.mean()), float(np.percentile(v, 5)),
                          float(np.percentile(v, 95))) if len(v) else (np.nan,) * 3)
            crit = df["detection_rate_internal_pitting"].dropna()
            rows.append({"true_share": share, "target": target, "pit_detection_mean": m,
                         "pit_detection_p5": lo, "pit_detection_p95": hi,
                         "pit_critical_detection_mean": float(crit.mean()) if len(crit)
                         else np.nan,
                         "pit_scan_points": float(df["pit_scan_points"].mean())})
    return pd.DataFrame(rows)


class X(float):
    """Override value meaning "current config value times this factor" (for `sweep`)."""


def default_variations():
    rates = ("external_corrosion", "cui", "fac", "internal_pitting", "crack")
    return {
        "base": {},
        "insulated_low": {"network.insulated_fraction": 0.25},
        "insulated_high": {"network.insulated_fraction": 0.65},
        "elevated_low": {"network.elevated_fraction": 0.4},
        "elevated_high": {"network.elevated_fraction": 0.8},
        "defects_half": {f"defects.{k}.rate_per_km": X(0.5) for k in rates},
        "defects_double": {f"defects.{k}.rate_per_km": X(2.0) for k in rates},
        "old_plant": {"network.install_year_min": 1970, "network.install_year_max": 2000},
        "new_plant": {"network.install_year_min": 1990, "network.install_year_max": 2020},
        "steam_low": {"network.media_mix.steam": 0.10},
        "steam_high": {"network.media_mix.steam": 0.35},
        "lift": {"strategy.human_elevated_access": "lift"},
        "scaffold_cheap": {"strategy.cost_scaffold_krw": X(0.25)},
        "ir_shifted": {"strategy.ir_condition": "shifted"},
        "cui_dry": {"defects.cui.in_wet_zone_prob": 0.2},
    }


def sweep(cfg, seed=0, runs=5, total_km=None, variations=None) -> pd.DataFrame:
    """Robustness sweep: re-run the 3 strategies under changed network / cost assumptions.

    One row per variation (name -> {dotted key: value or X(factor)}): mean detection rate,
    cost per km and found energy fraction per strategy, ratios vs baseline, and `ai_better`
    (AI detects more AND costs less per km than the baseline).
    """
    variations = default_variations() if variations is None else variations
    rows = []
    for name, over in variations.items():
        vals = {k: (params.get(cfg, k) * float(v) if isinstance(v, X) else v)
                for k, v in over.items()}
        res = run_all(params.with_values(cfg, vals), seed, runs, total_km)

        def mean(name_, col, res=res):
            return float(res[name_][col].mean())

        row = {"variation": name}
        for n in STRATEGIES:
            row[f"detection_rate_{n}"] = mean(n, "detection_rate")
        det_b = row["detection_rate_baseline"]
        row["ratio_ai_over_baseline_detection"] = (
            row["detection_rate_ai_triage"] / det_b if det_b else np.nan)
        cost = {n: mean(n, "cost_krw_per_km") for n in STRATEGIES}
        days = {n: mean(n, "elapsed_days") for n in STRATEGIES}
        for n in STRATEGIES:
            row[f"cost_krw_per_km_{n}"] = cost[n]
        for n in ("drone", "ai_triage"):
            row[f"cost_ratio_{n}"] = cost[n] / cost["baseline"] if cost["baseline"] else np.nan
            row[f"time_ratio_{n}"] = days[n] / days["baseline"] if days["baseline"] else np.nan
        for n in STRATEGIES:
            row[f"energy_found_frac_{n}"] = mean(n, "energy_found_frac")
        row["ai_better"] = bool(row["detection_rate_ai_triage"] > det_b
                                and cost["ai_triage"] < cost["baseline"])
        rows.append(row)
    return pd.DataFrame(rows)
