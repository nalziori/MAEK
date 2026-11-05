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


