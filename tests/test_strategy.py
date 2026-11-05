import copy

import numpy as np
import pytest

from maek import cli, network, params, strategy, thermal

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
    # drone contact UT replaces scaffolds on uninsulated pipe only; elevated insulated points
    # still need human access, so the drone strategy keeps some scaffolds (fewer than baseline)
    assert (d["scaffolds"] < b["scaffolds"]).all() and (b["scaffolds"] > 0).all()
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


def _steam_cfg(**over):
    cfg = params.load_config(overlays=[params.scenario_path("steam")])
    return params.with_values(cfg, over) if over else cfg


def test_no_drone_ut_on_insulated_and_openings_counted():
    cfg = _cfg()
    seg, feat, dfx = network.generate_network(cfg, 1, total_km=10.0)
    ins = seg["insulated"].to_numpy(bool)
    metal = (seg["material"] != "pvc").to_numpy()
    elev_unins = (seg["elevated"].to_numpy(bool) & ~ins & metal).sum()
    k = int(params.get(cfg, "strategy.cml_per_segment"))
    for fn in (strategy.run_drone, strategy.run_ai_triage):
        m = fn(cfg, seg, feat, dfx, np.random.default_rng(0))
        if fn is strategy.run_drone:  # fixed CMLs: drone UT only on elevated uninsulated pipe
            assert m["drone_ut_points"] == elev_unins * k
            assert m["insulation_openings"] == (ins & metal).sum() * k
        else:
            assert m["drone_ut_points"] <= elev_unins * k + 3 * 5  # + false flags / scans
        assert m["insulation_openings"] > 0
    b = strategy.run_baseline(cfg, seg, feat, dfx, np.random.default_rng(0))
    assert b["insulation_openings"] == (ins & metal).sum() * k


def test_lift_mode_replaces_scaffolds():
    base = strategy.run_all(_cfg(), 2, 2, 8.0)
    lift = strategy.run_all(params.with_values(_cfg(), {"strategy.human_elevated_access": "lift"}),
                            2, 2, 8.0)
    for name in strategy.STRATEGIES:
        assert (lift[name]["scaffolds"] == 0).all() and (lift[name]["lift_days"] > 0).all()
        assert (base[name]["lift_days"] == 0).all() and (base[name]["scaffolds"] > 0).all()
        assert not np.allclose(lift[name]["cost_krw"], base[name]["cost_krw"])


def test_empty_ut_ignores_non_ut_defects():
    cfg = _cfg()
    seg, feat, dfx = _net(0, 10.0)
    only_energy = dfx[~dfx["ut_mode"].isin(("straight", "angle"))]
    assert len(only_energy) > 0
    assert strategy._by_seg(only_energy.assign(ut_mode=only_energy["ut_mode"].fillna(""))) == {}
    m = strategy.run_baseline(cfg, seg, feat, only_energy, np.random.default_rng(0))
    assert m["empty_ut_rate"] == 1.0


def test_per_km_metrics_and_cost_terms_reach_cost():
    cfg = _cfg()
    res = strategy.run_all(cfg, 3, 2, KM)
    for df in res.values():
        assert np.allclose(df["cost_krw_per_km"] * df["km"], df["cost_krw"])
        assert np.allclose(df["labor_hours_per_km"] * df["km"], df["labor_hours"])
    unit = {k: params.get(cfg, f"strategy.{k}") for k in strategy.COST_KEYS}
    counts = res["ai_triage"].iloc[0].to_dict()
    base = strategy.cost_breakdown(cfg, counts)["cost_krw"]
    assert np.isclose(base, counts["cost_krw"])
    for key, col in (("cost_insulation_opening_krw", "insulation_openings"),
                     ("cost_lift_day_krw", "lift_days"), ("cost_pec_hour_krw", "pec_hours")):
        assert col in strategy.COUNT_COLS and key in strategy.COST_KEYS
        bumped = dict(unit, **{key: unit[key] * 2})
        extra = strategy.cost_breakdown(cfg, dict(counts, **{col: counts[col] + 3}), bumped)
        assert extra["cost_krw"] > strategy.cost_breakdown(cfg, counts, bumped)["cost_krw"]


def test_energy_loss_same_across_strategies_and_ai_finds_more_with_perfect_ir(monkeypatch):
    cfg = _steam_cfg(**{"strategy.trap_test_pod": 1.0})
    monkeypatch.setattr(thermal, "detect_prob", lambda *a, **k: 1.0)
    res = strategy.run_all(cfg, 1, 3, KM)
    tot = [res[n]["energy_loss_mwh"].to_numpy() for n in strategy.STRATEGIES]
    assert tot[0].min() > 0 and np.allclose(tot[0], tot[1]) and np.allclose(tot[0], tot[2])
    assert (res["ai_triage"]["energy_found_frac"] >= res["baseline"]["energy_found_frac"] - 1e-9
            ).all()
    assert (res["drone"]["energy_found_frac"] >= res["baseline"]["energy_found_frac"] - 1e-9).all()


def test_steam_scenario_pec_helps_cui():
    cfg = _steam_cfg()
    res = strategy.run_all(cfg, 1, 3, KM)
    ai, base = res["ai_triage"], res["baseline"]
    assert (ai["pec_zones"] > 0).all() and (base["pec_zones"] == 0).all()
    assert (ai["pec_hours"] > 0).all()
    assert ai["detection_rate_cui"].mean() >= base["detection_rate_cui"].mean()
    for col in ("traps_failed", "traps_found", "energy_found_frac", "found_rate_steam_leak"):
        assert col in ai.columns


def test_pit_prior_wet_spot_target_pays_only_if_prior_is_right():
    # perfect UT, 10x pits and a bigger scan budget give enough statistics on 10 km
    cfg = _cfg(True)
    cfg = params.with_values(cfg, {
        "defects.internal_pitting.rate_per_km":
            10 * params.get(cfg, "defects.internal_pitting.rate_per_km"),
        "strategy.pit_scan_budget_frac": 0.5})
    df = strategy.pit_prior_sensitivity(cfg, 1, 3, 10.0, shares=(0.0, 0.9))
    assert list(df.columns)[:5] == ["true_share", "target", "pit_detection_mean",
                                    "pit_detection_p5", "pit_detection_p95"]
    assert len(df) == 4 and "pit_scan_points" in df.columns

    def get(share, target):
        r = df[(df["true_share"] == share) & (df["target"] == target)].iloc[0]
        return r["pit_detection_mean"]

    assert get(0.9, "wet_spot") > get(0.9, "random")
    assert abs(get(0.0, "wet_spot") - get(0.0, "random")) < 0.06


def test_sweep_one_row_per_variation():
    cfg = _cfg()
    var = {"base": {}, "lift": {"strategy.human_elevated_access": "lift"},
           "cheap": {"strategy.cost_scaffold_krw": strategy.X(0.25)},
           "dry": {"defects.cui.in_wet_zone_prob": 0.2}}
    df = strategy.sweep(cfg, 1, 2, 5.0, var)
    assert list(df["variation"]) == list(var)
    for c in ("ratio_ai_over_baseline_detection", "cost_ratio_drone", "cost_ratio_ai_triage",
              "time_ratio_drone", "time_ratio_ai_triage", "cost_krw_per_km_baseline"):
        assert np.isfinite(df[c]).all()
    assert df["ai_better"].dtype == bool
    assert set(strategy.default_variations()) >= {"base", "old_plant", "ir_shifted", "cui_dry"}


def test_cli_set_parsing_and_cfg():
    sets = cli.parse_sets(["strategy.ir_condition=shifted", "strategy.trap_test_pod=0.5",
                           "strategy.crews=[1]"])
    assert sets == {"strategy.ir_condition": "shifted", "strategy.trap_test_pod": 0.5,
                    "strategy.crews": [1]}
    with pytest.raises(ValueError):
        cli.parse_sets(["novalue"])
    args = cli.build_parser().parse_args(
        ["strategy", "--scenario", "steam", "--set", "strategy.trap_test_pod=0.5",
         "--set", "strategy.ir_condition=shifted"])
    cfg = cli._cfg(args)
    assert params.get(cfg, "strategy.trap_test_pod") == 0.5
    assert params.get(cfg, "strategy.ir_condition") == "shifted"
    assert params.get(cfg, "network.media_mix.steam") == 0.5  # scenario applied first
    with pytest.raises(KeyError):
        cli._cfg(cli.build_parser().parse_args(["strategy", "--set", "strategy.nope=1"]))


def test_resources_drone_never_on_insulated_and_scaffold_once_per_segment():
    import pandas as pd
    seg = pd.DataFrame({"segment_id": ["A", "B", "C"], "elevated": [True, True, False],
                        "insulated": [False, True, True]}).set_index("segment_id")
    cfg = _cfg()
    r = strategy._resources(cfg, seg, ["A", "A", "B", "B", "C"], True, zone_sids=["B", "A"])
    assert r["drone_ut_points"] == 2 and r["insulation_openings"] == 3
    assert r["scaffolds"] == 2 and r["lift_points"] == 0  # A (zone) and B, once each
    lift = params.with_values(cfg, {"strategy.human_elevated_access": "lift"})
    r = strategy._resources(lift, seg, ["A", "A", "B", "B", "C"], True, zone_sids=["B", "A"])
    assert r["scaffolds"] == 0 and r["lift_points"] == 4  # 2 elevated insulated + 2 PEC zones
    assert strategy._resources(cfg, seg, ["A"], False)["drone_ut_points"] == 0
