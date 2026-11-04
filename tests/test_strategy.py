import copy

import numpy as np

from maek import network, params, strategy

KM = 5.0


def _cfg(perfect=False):
    cfg = copy.deepcopy(params.load_config())
    if perfect:
        for s in ("human", "camera", "ut_straight", "ut_angle"):
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
    for c in ("baseline_mean", "ai_mean"):
        v = det[c].dropna()
        assert ((v >= 0) & (v <= 1)).all()


def test_single_run_metrics():
    cfg = _cfg()
    seg, feat, dfx = network.generate_network(cfg, 0, total_km=KM)
    for fn in (strategy.run_baseline, strategy.run_ai_triage):
        m = fn(cfg, seg, feat, dfx, np.random.default_rng(0))
        assert 0 <= m["detection_rate"] <= 1 and m["cost_krw"] > 0


def test_sensitivity_rows():
    df = strategy.sensitivity(_cfg(), 0, 2, KM)
    assert set(df["cost_key"]) == set(strategy.COST_KEYS)
    assert len(df) == 2 * len(strategy.COST_KEYS)


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
    for fn in (strategy.run_baseline, strategy.run_ai_triage):
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
