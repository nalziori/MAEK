import copy

import numpy as np

from maek import network, params, strategy

KM = 5.0


def _cfg(perfect=False):
    cfg = copy.deepcopy(params.load_config())
    if perfect:
        for s in ("human", "human_video", "camera", "ut_straight", "ut_angle",
                  "ut_straight_drone", "ut_angle_drone", "ut_pit_manual", "ut_pit_drone"):
            cfg["strategy"]["pod"][s]["b0"]["value"] = 60.0
        cfg["strategy"]["human_elevated_factor"]["value"] = 1.0
        cfg["strategy"]["camera_false_flag_prob"]["value"] = 0.0
    return cfg


def test_pod_prob_monotone_and_bounded():
    p = strategy.pod_prob(np.array([0.1, 1, 10]), -1.0, 1.5)
    assert np.all(np.diff(p) > 0) and np.all((p >= 0) & (p <= 1))
    assert strategy.pod_prob(0.0, 0, 1) == 0


def test_perfect_detectors_ai_beats_baseline():
    cfg = _cfg(True)
    res = strategy._run_all(cfg, 1, 4, KM)
    b, a = res["baseline"], res["ai_triage"]
    assert a["detection_rate"].mean() >= b["detection_rate"].mean()
    assert (a["ut_points"] < b["ut_points"]).all()


def test_deterministic_and_bounded():
    cfg = _cfg()
    one = strategy.compare(cfg, 3, 3, KM)
    two = strategy.compare(cfg, 3, 3, KM)
    assert one.equals(two)
    det = one[one["metric"].str.startswith("detection_rate")]
    for c in ("baseline_mean", "drone_mean", "ai_triage_mean"):
        v = det[c].dropna()
        assert ((v >= 0) & (v <= 1)).all()


def test_single_run_metrics():
    cfg = _cfg()
    seg, feat, dfx = network.generate_network(cfg, 0, total_km=KM)
    for fn in (strategy.run_baseline, strategy.run_drone, strategy.run_ai_triage):
        m = fn(cfg, seg, feat, dfx, np.random.default_rng(0))
        assert 0 <= m["detection_rate"] <= 1 and m["cost_krw"] > 0
        assert m["labor_hours"] > 0 and m["elapsed_days"] > 0


def test_sensitivity_rows():
    df = strategy.sensitivity(_cfg(), 0, 2, KM)
    assert set(df["cost_key"]) == set(strategy.COST_KEYS)
    assert len(df) == 2 * len(strategy.COST_KEYS)
    for c in ("cost_ratio_drone", "cost_ratio_ai_triage", "time_ratio_drone",
              "time_ratio_ai_triage"):
        assert (df[c] > 0).all()


def test_risk_ranked_crack_ut_finds_at_least_as_many_as_random():
    found = {}
    for mode in ("random", "risk_ranked"):
        cfg = _cfg(True)
        cfg["strategy"]["crack_ut_mode"]["value"] = mode
        res = strategy._run_all(cfg, 5, 3, 30.0)
        ai = res["ai_triage"]
        found[mode] = float(ai["detection_rate_crack"].fillna(0).sum())
        assert (ai["ut_points"] < res["baseline"]["ut_points"]).all()
    assert found["risk_ranked"] >= found["random"] and found["risk_ranked"] > 0


def _net(seed=0, km=30.0):
    return network.generate_network(_cfg(), seed, total_km=km)


def test_baseline_cannot_detect_cracks():
    cfg = _cfg(True)
    res = strategy.run_all(cfg, 0, 3, 30.0)
    assert res["baseline"]["detection_rate_crack"].fillna(0).sum() == 0
    assert res["ai_triage"]["detection_rate_crack"].fillna(0).sum() > 0


def test_baseline_walkdown_sees_cui_external_sign():
    cfg = _cfg(True)
    seg, feat, dfx = _net(0)
    sign = (dfx["kind"] == "cui") & dfx["external_sign"].astype(bool)
    seg_el = seg.set_index("segment_id")["elevated"].astype(bool)
    target = sign & ~dfx["segment_id"].map(seg_el).astype(bool)
    assert target.sum() > 0
    # no UT: isolate the walkdown by dropping all CMLs
    cfg["strategy"]["cml_per_segment"]["value"] = 0
    d = dfx[target].copy()
    d["critical"] = True
    m = strategy.run_baseline(cfg, seg, feat, d, np.random.default_rng(0))
    assert m["detection_rate"] == 1.0


def test_nan_ut_mode_after_csv_roundtrip(tmp_path):
    import pandas as pd
    cfg = _cfg()
    seg, feat, dfx = _net(2)
    assert (dfx["ut_mode"] == "").any()
    f = tmp_path / "d.csv"
    dfx.to_csv(f, index=False)
    rt = pd.read_csv(f)
    assert rt["ut_mode"].isna().any()
    for fn in (strategy.run_baseline, strategy.run_drone, strategy.run_ai_triage):
        a = fn(cfg, seg, feat, dfx, np.random.default_rng(1))
        b = fn(cfg, seg, feat, rt, np.random.default_rng(1))
        assert a == b


def test_compare_and_sensitivity_share_runs():
    cfg = _cfg()
    c, s = strategy.compare_and_sensitivity(cfg, 1, 2, KM)
    assert c.equals(strategy.compare(cfg, 1, 2, KM))
    assert s.equals(strategy.sensitivity(cfg, 1, 2, KM))
    runs = strategy.run_all(cfg, 1, 2, KM)
    assert s.equals(strategy.sensitivity(cfg, runs_df=runs))


def test_crack_strategy_baseline_computed_once():
    from maek import evaluate
    out = evaluate.crack_strategy(_cfg(), 0, 2, KM)
    assert out["baseline"] == 0.0 or np.isnan(out["baseline"])


def test_three_strategies_deterministic():
    cfg = _cfg()
    one = strategy.run_all(cfg, 2, 2, KM)
    two = strategy.run_all(cfg, 2, 2, KM)
    assert list(one) == ["baseline", "drone", "ai_triage"]
    for k in one:
        assert one[k].equals(two[k])
    two_only = strategy.run_all(cfg, 2, 2, KM, ("baseline", "ai_triage"))
    assert two_only["baseline"].equals(one["baseline"])
    assert two_only["ai_triage"].equals(one["ai_triage"])


def test_drone_no_scaffolds_same_cml_as_baseline():
    res = strategy.run_all(_cfg(), 3, 3, 20.0)
    b, d = res["baseline"], res["drone"]
    assert (d["scaffolds"] == 0).all() and (b["scaffolds"] > 0).all()
    assert (d["ut_points"] == b["ut_points"]).all()
    assert (d["drone_ut_points"] > 0).all()
    assert (d["elapsed_days"] < b["elapsed_days"]).all()


def test_ai_triage_ut_points_within_baseline_and_positive_resources():
    res = strategy.run_all(_cfg(), 4, 3, 20.0)
    assert (res["ai_triage"]["ut_points"] <= res["baseline"]["ut_points"]).all()
    for df in res.values():
        assert (df["cost_krw"] > 0).all() and (df["labor_hours"] > 0).all()
        assert (df["elapsed_days"] > 0).all()
        assert ((df["empty_ut_rate"] >= 0) & (df["empty_ut_rate"] <= 1)).all()


def test_pit_area_scans_find_internal_pitting_with_perfect_pod():
    cfg = _cfg(True)
    res = strategy.run_all(cfg, 2, 3, 60.0, ("ai_triage",))
    assert res["ai_triage"]["pit_scan_points"].sum() > 0
    on = res["ai_triage"]["detection_rate_internal_pitting"].fillna(0).sum()
    cfg["strategy"]["pit_scan_budget_frac"]["value"] = 0.0
    off = strategy.run_all(cfg, 2, 3, 60.0, ("ai_triage",))["ai_triage"]
    assert on > 0
    assert off["pit_scan_points"].sum() == 0
    assert on > off["detection_rate_internal_pitting"].fillna(0).sum()


def test_compare_columns_and_markdown():
    c = strategy.compare(_cfg(), 1, 2, KM)
    for col in ("baseline_mean", "drone_p5", "ai_triage_p95", "ratio_drone_over_baseline",
                "ratio_ai_triage_over_baseline"):
        assert col in c.columns
    md = strategy.to_markdown(c)
    assert "사람+비계" in md and "드론+AI" in md
