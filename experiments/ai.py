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
    thin_ids, crack_ids, cui_ids, ff = _risk_features(cfg, segments, features, rng)
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


