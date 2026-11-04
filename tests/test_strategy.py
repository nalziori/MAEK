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
