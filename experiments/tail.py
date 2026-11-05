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


def _pit_scans(cfg, segments, budget_pts, rng):
    """Risk-ranked straight-beam area scans: list of (segment_id, centre_m, length_m)."""
    k = max(int(_s(cfg, "pit_scan_k")), 1)
    n_scans = max(int(budget_pts) // k, 0)
    fp = _s(cfg, "pit_scan_footprint_m")
    order = _rank_pit_segments(cfg, segments)[:n_scans]
    out = []
    for i in order:
        L = float(segments["length_m"].iat[i])
        w = min(fp, L)
        out.append((segments["segment_id"].iat[i], float(rng.uniform(w / 2, L - w / 2)), w))
    return out


def run_ai_triage(cfg, segments, features, defects, rng):
    """Camera sweep of every segment, then UT at flagged spots + risk features + pit scans."""
    d = _prepare(cfg, segments, defects)
    n = len(d)
    km = segments["length_m"].sum() / 1000.0
    drone_el = _s(cfg, "elevated_ut_mode") != "scaffold"
    drone_def = d["elevated"].to_numpy(bool) if drone_el else None

    cb0, cb1 = _pod_params(cfg, "camera")
    cam = _draw(rng, np.where(_visible(d), pod_prob(d["area_cm2"], cb0, cb1), 0.0)) \
        if n else np.zeros(0, bool)

    # UT confirmation at each camera-flagged defect (flange leaks need no UT)
    has_ut = (d["ut_mode"] != "").to_numpy()  # normalised in _prepare
    confirm = cam & has_ut
    conf_hit = confirm & _draw(rng, _ut_pod(cfg, d, drone=drone_def)) if n else confirm
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
    feat_hit = cover & _draw(rng, _ut_pod(cfg, d, drone=drone_def)) if n else cover

    thin_cui = ff["thin"] | ff["cui"]
    fpts = pd.concat([ff[thin_cui], ff[ff["crack"]]])  # one UT point per role
    base_pts = pd.concat([
        pd.DataFrame({"segment_id": ff.loc[thin_cui, "segment_id"]}),
        pd.DataFrame({"segment_id": ff.loc[ff["crack"], "segment_id"]}),
        pd.DataFrame({"segment_id": d["segment_id"][confirm]}),
        pd.DataFrame({"segment_id": false_seg}, dtype=object)], ignore_index=True)

    # risk-ranked straight-beam area scans for internal pitting (no external sign):
    # budget in UT points, capped so the total stays within the baseline's fixed UT points
    k = max(int(_s(cfg, "pit_scan_k")), 1)
    n_base = int(_s(cfg, "cml_per_segment")) * int((segments["material"] != "pvc").sum())
    budget = min(int(_s(cfg, "pit_scan_budget_frac") * n_base), max(n_base - len(base_pts), 0))
    scans = _pit_scans(cfg, segments, budget, rng)
    scan_hit = np.zeros(n, bool)
    if scans and n:
        pos = d["pos_m"].to_numpy(float)
        sid = d["segment_id"].to_numpy()
        inside = np.zeros(n, bool)
        for s_id, c, w in scans:
            inside |= (sid == s_id) & (np.abs(pos - c) <= w / 2)
        inside &= (d["ut_mode"] == "straight").to_numpy()
        scan_hit = inside & _draw(rng, _ut_pod(cfg, d, ("straight",), drone_def))
    scan_pts = pd.DataFrame({"segment_id": [s_id for s_id, _, _ in scans for _ in range(k)]},
                            dtype=object)
    pts = pd.concat([base_pts, scan_pts], ignore_index=True)

    # wasted measurements: points with no defect within the footprint
    by_seg = _by_seg(d)
    foot = _s(cfg, "probe_footprint_m")
    empty = _empty_count(by_seg, fpts["segment_id"], fpts["pos_m"], foot,
                         fpts["feature_id"].to_numpy())
    empty += len(false_seg)
    for s_id, c, w in scans:
        cells = c - w / 2 + (np.arange(k) + 0.5) * w / k
        empty += _empty_count(by_seg, [s_id] * k, cells, w / (2 * k))

    seg_elev = segments.set_index("segment_id")["elevated"]
    elev = pts["segment_id"].map(seg_elev).fillna(False).astype(bool)
    n_pts = len(pts)
    if not drone_el:
        scaffolds, drone_pts = int(pts.loc[elev, "segment_id"].nunique()), 0
    else:
        scaffolds, drone_pts = 0, int(elev.sum())
    flags = int(cam.sum()) + n_false
    counts = {"ut_points": n_pts, "drone_ut_points": drone_pts, "scaffolds": scaffolds,
              "drone_km": km, "ai_km": km, "walk_km": 0.0, "flags": flags,
              "empty_ut_points": empty, "pit_scan_points": len(scan_pts),
              **_effort(cfg, km_flight=km, n_segments=len(segments),
                        manual_pts=n_pts - drone_pts, drone_pts=drone_pts,
                        scaffolds=scaffolds, flags=flags)}
    return _metrics(cfg, d, cam_found | feat_hit | scan_hit, counts)


_RUNNERS = {"baseline": (run_baseline, 0), "drone": (run_drone, 2),
            "ai_triage": (run_ai_triage, 1)}


def run_all(cfg, seed, runs, total_km=None, strategies=STRATEGIES):
    """Monte Carlo runs: {strategy: runs_df} (one row per run)."""
    unknown = set(strategies) - set(_RUNNERS)
    if unknown:
        raise ValueError(f"unknown strategies: {sorted(unknown)}")
    res = {k: [] for k in strategies}
    for i in range(runs):
        seg, feat, dfx = network.generate_network(cfg, seed + i, total_km=total_km)
        for name in strategies:
            fn, stream = _RUNNERS[name]
            res[name].append(fn(cfg, seg, feat, dfx, np.random.default_rng([seed, i, stream])))
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
    ("labor_hours", "작업 시간 (인시)", "{:,.0f}"),
    ("elapsed_days", "소요 일수 (일)", "{:.1f}"),
    ("cost_krw", "비용 (백만 원)", "{:,.1f}"),
]


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
        scale = 1e-6 if key == "cost_krw" else 1.0
        r = dict(rows[key])
        for n in names:  # ratio columns are keyed by strategy; map per cell
            r[f"ratio_{n}_over_baseline"] = rows[key].get(f"ratio_{n}_over_baseline", np.nan)
        lines.append(f"| {label} | " + " | ".join(
            _cell(r, n, fmt, scale, ratio=key in ("ut_points", "labor_hours", "elapsed_days",
                                                  "cost_krw")) for n in names) + " |")
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
