"""Internal-pit detection (maek.pit): averaging, matched filter, CFAR, learned classifier."""

from pathlib import Path

import numpy as np
import pytest

from maek import evaluate, params, pit, ut

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg():
    return params.load_config(ROOT / "config" / "default.yaml")


@pytest.fixture(scope="module")
def small(cfg):
    """2048-sample traces and a tiny DR training budget, for speed."""
    c = evaluate._with(cfg, "ut.n_samples", 2048)
    for k, v in (("dr_n_train", 120), ("dr_n_calib", 120), ("mlp_iters", 300)):
        c = evaluate._with(c, "ut.pit." + k, v)
    return c


# ---------------------------------------------------------------- acquisition / averaging
def test_n_avg_1_reproduces_previous_signals(cfg):
    # digests of the simulator before n_avg existed (same call, same seed)
    s = ut.simulate_straight(cfg, np.random.default_rng(5), 7.3, 2.0, 0.35, 120.0, 0.55, 3.0)
    assert float(s.astype(np.float64).sum()) == pytest.approx(5.32321315059653, rel=1e-5)
    assert float(np.abs(s).astype(np.float64).sum()) == pytest.approx(221.67490817290218,
                                                                      rel=1e-6)
    assert np.allclose(s[[100, 1000, 2500]], [0.7768642902, -0.0422182195, -0.0644756109],
                       atol=1e-6)
    s1 = ut.simulate_straight(cfg, np.random.default_rng(5), 7.3, 2.0, 0.35, 120.0, 0.55, 3.0,
                              n_avg=1, avg_rng=np.random.default_rng(99))
    assert np.array_equal(s, s1)
    st, _, _ = ut.make_dataset(cfg, 6, 3, "shifted", n_avg=1)
    assert float(np.abs(st).astype(np.float64).sum()) == pytest.approx(1281.42209557731, rel=1e-6)


def test_averaging_reduces_only_electronic_noise(cfg):
    args = (cfg, 6.0, 0.0, 0.0, 20.0, 0.8, 2.0)
    s1 = ut.simulate_straight(args[0], np.random.default_rng(0), *args[1:])
    s16 = ut.simulate_straight(args[0], np.random.default_rng(0), *args[1:], n_avg=16,
                               avg_rng=np.random.default_rng(1))
    pre = slice(0, 60)  # before the interface echo: electronic noise only
    ratio = np.std(s1[pre]) / np.std(s16[pre])
    assert 2.5 < ratio < 6.0  # ~ sqrt(16)
    # grain backscatter is shared: more averaging converges to the same grain pattern,
    # another probe position (seed) gives an unrelated one
    late = slice(3000, 4000)  # echo train has decayed: grain + electronic noise only
    s256 = ut.simulate_straight(args[0], np.random.default_rng(0), *args[1:], n_avg=256,
                                avg_rng=np.random.default_rng(2))
    other = ut.simulate_straight(args[0], np.random.default_rng(1), *args[1:], n_avg=256,
                                 avg_rng=np.random.default_rng(3))
    assert np.corrcoef(s16[late], s256[late])[0, 1] > 0.7
    assert abs(np.corrcoef(s256[late], other[late])[0, 1]) < 0.2
    with pytest.raises(ValueError):
        ut.simulate_straight(cfg, np.random.default_rng(0), 6.0, n_avg=0)


def test_make_dataset_n_avg_keeps_geometry(cfg):
    a1, b1, l1 = ut.make_dataset(cfg, 8, 4, "shifted", n_avg=1)
    a16, b16, l16 = ut.make_dataset(cfg, 8, 4, "shifted", n_avg=16)
    assert np.array_equal(b1, b16)  # angle beam untouched
    assert l1.drop(columns="n_avg").equals(l16.drop(columns="n_avg"))
    assert (l16["n_avg"] == 16).all() and not np.array_equal(a1, a16)
    _, _, ld = ut.make_dataset(cfg, 2, 4)
    assert (ld["n_avg"] == params.get(cfg, "ut.n_avg")).all()


def test_avg_extra_time_matches_config(cfg):
    n, prf = params.get(cfg, "ut.n_avg"), params.get(cfg, "ut.prf_hz")
    assert ut.averaging_time_s(cfg) == pytest.approx((n - 1) / prf)
    assert params.get(cfg, "ut.avg_extra_time_s") == pytest.approx(ut.averaging_time_s(cfg))
    assert ut.averaging_time_s(cfg, 1) == 0.0


# ---------------------------------------------------------------- signal processing
def test_matched_filter_amplitude_and_noise_gain(cfg):
    p = ut._p(cfg)
    t = ut._time(cfg)
    x = 0.7 * ut._pulse(cfg, t, 12.34e-6)
    z = pit.analytic(cfg, x)
    assert np.abs(z).max() == pytest.approx(0.7, rel=0.01)
    assert abs(np.argmax(np.abs(z)) / p["fs"] - 12.34e-6) < 2 / p["fs"]
    noise = np.random.default_rng(0).standard_normal(p["n"])
    gain = np.std(noise) / np.std(pit.analytic(cfg, noise).real)
    assert 2.3 < gain < 3.0  # sqrt(pulse energy in samples) ~ 2.66
    # the analytic response model matches the filtered pulse
    i = np.arange(1200, 1300)
    R = pit.echo_response(cfg, i / p["fs"] - 12.34e-6)
    assert np.max(np.abs(z[i] - 0.7 * R)) < 0.01


def test_cfar_sigma_follows_noise(cfg):
    rng = np.random.default_rng(3)
    sig = [np.mean([pit.noise_sigma(cfg, pit.analytic(cfg, k * rng.standard_normal(4096)))
                    for _ in range(10)]) for k in (0.02, 0.04)]
    assert sig[1] / sig[0] == pytest.approx(2.0, rel=0.1)
    assert sig[0] == pytest.approx(0.02 / np.sqrt(7.1), rel=0.1)  # white noise / sqrt(E)
    # with an A-scan: coupling scales echoes and grain alike, sigma follows it
    s = [pit.noise_sigma(cfg, pit.analytic(cfg, ut.simulate_straight(
        cfg, np.random.default_rng(4), 5.0, coupling=c, n_avg=64)), 5.0) for c in (1.0, 0.4)]
    assert s[1] / s[0] == pytest.approx(0.4, rel=0.2)
    assert pit.cfar_k(cfg, 50) > pit.cfar_k(cfg, 5) > 3.0


@pytest.mark.parametrize("method", [None, "mf_cfar"])
@pytest.mark.parametrize("wall,depth,frac", [(8.0, 3.0, 0.3), (6.0, 0.5, 0.4), (4.0, 2.2, 0.2)])
def test_detector_finds_pit_and_depth(cfg, wall, depth, frac, method):
    s = ut.simulate_straight(cfg, np.random.default_rng(11), wall, depth, frac, n_avg=16)
    r = ut.detect_pit(cfg, s, wall, method=method)
    assert set(r) == {"found", "score", "depth_est_mm"}
    assert r["found"] and r["score"] > 1
    assert r["depth_est_mm"] == pytest.approx(depth, abs=0.1)  # 0.5 mm overlaps the back wall
    clean = ut.simulate_straight(cfg, np.random.default_rng(11), wall, n_avg=16)
    assert not ut.detect_pit(cfg, clean, wall, method=method)["found"]


def test_shipped_model_matches_default_config(cfg):
    shipped = pit.load_shipped()["learned"]
    assert shipped["fingerprint"] == pit._fingerprint(cfg)  # else: python -m maek.pit --write
    assert pit.get_model(cfg) is pit._MODELS[(pit._fingerprint(cfg), False)]
    assert pit.get_model(cfg)["W1"] == shipped["W1"]
    assert params.get(cfg, "ut.pit.method") in pit.METHODS


def test_each_method_runs_on_tiny_inputs(small):
    rng = np.random.default_rng(0)
    sigs = [ut.simulate_straight(small, rng, 6.0, 2.0, 0.4, 30.0, 0.9),
            ut.simulate_straight(small, rng, 6.0, 0.0, 0.0, 30.0, 0.9)]
    models = {m: pit.train_classifier(small, shadow=m == "learned_shadow")
              for m in ("learned", "learned_shadow")}
    for m in pit.METHODS:
        out = [pit.detect_pit(small, s, 6.0, 30.0, m, model=models.get(m), n_avg=1)
               for s in sigs]
        for r in out:
            assert isinstance(r["found"], bool) and np.isfinite(r["score"])
            assert np.isfinite(r["depth_est_mm"]) and r["depth_est_mm"] >= 0
        if m not in ("rel_amp",):
            assert out[0]["found"] and not out[1]["found"], m
    with pytest.raises(ValueError):
        pit.detect_pit(small, sigs[0], 6.0, method="nope")


def test_learned_classifier_deterministic_for_seed(small):
    pit._dr_features.cache_clear()
    a = pit.train_classifier(small, seed=5)
    pit._dr_features.cache_clear()
    b = pit.train_classifier(small, seed=5)
    c = pit.train_classifier(small, seed=6)
    assert a == b
    assert a["W1"] != c["W1"]
    assert a["fingerprint"] == pit._fingerprint(small)
    assert len(a["thresholds"]) == len(a["n_avg_choices"])
    X = np.random.default_rng(0).standard_normal((50, 3))
    y = X[:, 0] + 0.3 * X[:, 1] > 0
    m1, m2 = pit.fit_mlp(X, y, seed=1, iters=200), pit.fit_mlp(X, y, seed=1, iters=200)
    assert m1 == m2
    assert ((pit.predict_proba(m1, X) > 0.5) == y).mean() > 0.9
    lr = pit.fit_mlp(X, y, hidden=0, iters=300)  # logistic regression
    assert ((pit.predict_proba(lr, X) > 0.5) == y).mean() > 0.9


# ---------------------------------------------------------------- performance (fixed seed)
def test_new_detector_beats_old_on_small_shifted_sample(cfg):
    st1, _, lab = ut.make_dataset(cfg, 160, 21, "shifted", n_avg=1)
    st16, _, _ = ut.make_dataset(cfg, 160, 21, "shifted", n_avg=16)
    pitm = lab["pit_depth_mm"].to_numpy() > 0
    temps = ut.analysis_temps(cfg, lab)
    rows = list(zip(lab["wall_mm"], temps))

    def rate(st, method, n_avg):
        f = np.array([pit.detect_pit(cfg, s, w, t, method, n_avg=n_avg)["found"]
                      for s, (w, t) in zip(st, rows)])
        return f[pitm].mean(), f[~pitm].mean()

    old, old_fa = rate(st1, "baseline", 1)
    same_shot, fa1 = rate(st1, "mf_cfar", 1)
    learned1, fal = rate(st1, "learned", 1)
    new, fa16 = rate(st16, params.get(cfg, "ut.pit.method"), 16)
    assert old < 0.15
    assert same_shot > old + 0.25 and learned1 > old + 0.25  # processing alone, 1 shot
    assert new > 0.75 and new > old + 0.5  # default detector on averaged A-scans
    assert max(old_fa, fa1, fal, fa16) <= 0.02


def test_false_alarms_bounded_on_pit_free_signals(cfg):
    c = evaluate._with(cfg, "ut.n_samples", 2048)
    sig, lab = pit.make_dr_dataset(c, 250, 8, pit_prob=0.0)
    for m in (None, "mf_cfar"):  # default (learned, retrained for 2048 samples) and the rule
        found = [pit.detect_pit(c, s, w, t, m, n_avg=na)["found"]
                 for s, w, t, na in zip(sig, lab["wall_mm"], lab["temp_meas_c"], lab["n_avg"])]
        assert np.mean(found) <= 0.02, m


# ---------------------------------------------------------------- evaluation helpers
def test_factor_cfg_changes_only_listed_factor(cfg):
    _, _, lt = ut.make_dataset(cfg, 30, 2, "train")
    _, _, ln = ut.make_dataset(evaluate.factor_cfg(cfg, ("noise",)), 30, 2, "shifted")
    _, _, lc = ut.make_dataset(evaluate.factor_cfg(cfg, ("coupling",)), 30, 2, "shifted")
    assert (ln["noise_scale"] == 3.0).all() and np.allclose(ln["coupling"], lt["coupling"])
    assert np.allclose(ln["temp_c"], lt["temp_c"])
    assert (lc["noise_scale"] == 1.0).all() and (lc["coupling"] <= 0.7).all()


def test_pit_ablation_and_tables_tiny(small):
    rows = evaluate.pit_ablation(small, 24, seed=1, methods=("baseline", "mf_cfar"))
    assert {(r["method"], r["n_avg"], r["condition"]) for r in rows} == {
        (m, a, c) for m in ("baseline", "mf_cfar") for a in (1, 16) for c in ("train", "shifted")}
    for r in rows:
        assert 0 <= r["pit_false_alarm_rate"] <= 1 and "pit_pod" in r
        assert r["extra_time_s"] == pytest.approx(ut.averaging_time_s(small, r["n_avg"]))
    fac = evaluate.pit_factors(small, 16, seed=1, detectors=[("baseline", "baseline", 1)])
    assert [r["factor"] for r in fac] == [f for f, _ in evaluate.PIT_FACTORS]
    cov = evaluate.pit_dr_coverage(small, 12, seed=1, n_avgs=[16])
    assert {(r["dr_ranges"], r["gate"]) for r in cov} == {
        (m, g) for m in ("default", "narrow") for g in (True, False)}
    dv = evaluate.pit_dr_validation(small, 20, methods=("mf_cfar",))
    assert [(r["method"], r["n_avg"]) for r in dv] == [("mf_cfar", 1), ("mf_cfar", 16)]
    res = {"ut": {c: evaluate.eval_ut(small, c, 24, seed=1) for c in evaluate.CONDITIONS},
           "pit_ablation": rows, "pit_factors": fac, "pit_dr_validation": dv,
           "pit_dr_coverage": cov,
           "meta": {"avg_extra_time_s": 0.15}}
    pp = evaluate.pit_pod_frame(res)
    assert list(pp["condition"]) == ["train", "shifted"]
    assert {"b0", "b1", "b0_firth", "b1_firth", "status", "extra_time_s"} <= set(pp.columns)
    md = "\n".join(evaluate.pit_tables_markdown(res))
    assert "요인 분리" in md and "POD 로지스틱 계수" in md and "DR 검증" in md and "외삽" in md


def test_firth_pod_finite_when_all_hit():
    s = np.linspace(0.3, 7.0, 200)
    f = evaluate.fit_pod_firth(s, np.ones_like(s))
    assert np.isfinite(f["b0"]) and np.isfinite(f["b1"])
    assert evaluate.pod.pod(0.3, f["b0"], f["b1"]) > 0.95
    rng = np.random.default_rng(0)
    h = rng.random(400) < evaluate.pod.pod(np.repeat(s, 2), 0.5, 2.5)
    ml = evaluate.pod.fit_pod(np.repeat(s, 2), h)
    fi = evaluate.fit_pod_firth(np.repeat(s, 2), h)
    assert fi["b1"] == pytest.approx(ml["b1"], rel=0.1)


def test_cfar_gate_bounds_false_alarms_of_any_classifier(cfg):
    # a classifier that always says "pit": the CFAR gate alone must keep false alarms low
    m = dict(pit.get_model(cfg))
    m["thresholds"] = [[-1.0] * len(t) for t in m["thresholds"]]
    sig, lab = pit.make_dr_dataset(cfg, 300, 12, pit_prob=0.0)
    found = []
    for s, w, t, na in zip(sig, lab["wall_mm"], lab["temp_meas_c"], lab["n_avg"]):
        a = pit.analyse(cfg, s, w, t)
        found.append(pit.detect_learned(cfg, a, m, na)["found"])
        assert pit.detect_learned(cfg, a, m, na, gate=False)["found"]
    assert np.mean(found) <= 0.03
