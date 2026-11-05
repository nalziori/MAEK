import numpy as np

from maek import eva, params


def _cfg(**over):
    cfg = params.load_config()
    for k, v in over.items():
        cfg["eva"][k]["value"] = v
    return cfg


def test_gumbel_fit_recovers_parameters():
    rng = np.random.default_rng(1)
    x = 2.0 - 0.7 * np.log(-np.log(rng.uniform(size=2000)))
    mu, sig = eva.gumbel_fit(x)
    assert abs(mu - 2.0) / 2.0 < 0.05
    assert abs(sig - 0.7) / 0.7 < 0.05


def test_return_level_closed_form():
    mu, s, T = 3.0, 0.5, 100.0
    assert np.isclose(eva.return_level(mu, s, T), mu - s * np.log(-np.log(0.99)))
    # CDF at the return level is 1 - 1/T
    z = eva.return_level(mu, s, T)
    assert np.isclose(np.exp(-np.exp(-(z - mu) / s)), 0.99)


def test_run_small_network():
    # widespread pitting (many pits per scan window): the regime the Gumbel method assumes
    cfg = _cfg(bootstrap=50, pit_density_median_per_m2=20.0)
    df = eva.run(cfg, 0, 3, total_km=10, k_values=[16])
    assert len(df) == 3
    assert df["n_circuits"].min() > 0
    # nominal 95 % upper bound covers ~0.7-0.75 here (fallback circuits with < 3 maxima and
    # sizing noise); docs/pitting-strategy.md reports the gap, so only guard against collapse
    assert df["coverage"].mean() >= 0.7
    assert df["sensitivity"].mean() >= df["direct_detection"].mean()
    again = eva.run(cfg, 0, 3, total_km=10, k_values=[16])
    assert df.equals(again)
    assert set(eva.summary(df)["k"]) == {16}


def test_fallback_with_few_maxima():
    cfg = _cfg()
    rng = np.random.default_rng(0)
    r = eva.predict_max(cfg, np.array([np.nan, 1.2, np.nan, 0.8]), 100.0, 10.0, rng)
    assert r["point"] == 1.2 and not r["extrapolated"]
    assert np.isclose(r["upper"], 1.2 + 2.0 * 0.2)
    r = eva.predict_max(cfg, np.array([np.nan, np.nan]), 100.0, 10.0, rng)
    assert r["point"] == 0.0 and not r["extrapolated"] and r["upper"] >= 0.3
    r = eva.predict_max(cfg, np.array([1.0, 1.5, 0.9, 1.1]), 100.0, 10.0, rng)
    assert r["extrapolated"] and r["upper"] >= r["point"] > 1.0


def test_circuits_and_sampling():
    from maek import network

    cfg = _cfg()
    seg, _, _ = network.generate_network(cfg, 0, total_km=10)
    c = eva.circuits(cfg, seg)
    assert (c["allowable_mm"] > 0).all() and (c["area_m2"] > 0).all()
    row = c.iloc[0]
    rng = np.random.default_rng(0)
    pits = eva.simulate_circuit(cfg, row, rng)
    m = eva.sample_maxima(cfg, row, pits, 4, rng)
    assert len(m) == (4 if 4 * 5 < row["length_m"] else int(np.ceil(row["length_m"] / 5)))
