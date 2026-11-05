import copy

import numpy as np
import pandas as pd
import pytest

from maek import network, params

KM = 5.0


@pytest.fixture(scope="module")
def cfg():
    c = copy.deepcopy(params.load_config())
    c["network"]["total_km"]["value"] = KM
    return c


@pytest.fixture(scope="module")
def net(cfg):
    return network.generate_network(cfg, seed=7)


def test_deterministic(cfg, net):
    again = network.generate_network(cfg, seed=7)
    for a, b in zip(net, again):
        pd.testing.assert_frame_equal(a, b)
    other = network.generate_network(cfg, seed=8)
    assert not other[2].equals(net[2])


def test_columns(net):
    seg, feat, dfx = net
    assert list(seg.columns) == network.SEGMENT_COLS
    assert list(feat.columns) == network.FEATURE_COLS
    assert list(dfx.columns) == network.DEFECT_COLS
    assert set(dfx["kind"]) <= set(network.DEFECT_KINDS)
    assert set(feat["kind"]) <= set(network.FEATURE_KINDS)


def test_total_length(cfg):
    seg, _, _ = network.generate_network(cfg, seed=1, total_km=1.23)
    assert seg["length_m"].sum() == pytest.approx(1230.0)
    seg, _, _ = network.generate_network(cfg, seed=1)
    assert seg["length_m"].sum() == pytest.approx(KM * 1000)


def test_segment_rules(net):
    seg = net[0]
    assert not (seg["insulated"] & (seg["material"] == "pvc")).any()
    assert (seg["t_min_mm"] < seg["wall_mm"]).all()
    assert seg["traffic"].between(0, 2).all()


def test_cui_only_on_insulated_carbon_steel(cfg, net):
    seg, _, dfx = net
    m = dfx[dfx["kind"] == "cui"].merge(seg, on="segment_id")
    assert len(m) > 0
    assert m["insulated"].all() and (m["material"] == "carbon_steel").all()
    lo, hi = params.get(cfg, "defects.cui.temp_min_c"), params.get(cfg, "defects.cui.temp_max_c")
    assert m["temp_c"].between(lo, hi).all()
    ext = dfx[dfx["kind"] == "external_corrosion"].merge(seg, on="segment_id")
    assert (~ext["insulated"]).all() and (ext["material"] == "carbon_steel").all()


def test_visible_external_and_ut_mode(net):
    dfx = net[2]
    dfx = dfx[~dfx["kind"].isin(network.DEFECT_KINDS[6:])]
    ext_kinds = {"external_corrosion", "flange_leak"}
    assert (dfx["visible_external"] == dfx["kind"].isin(ext_kinds)).all()
    assert not dfx.loc[dfx["kind"] != "cui", "external_sign"].any()
    assert (dfx.loc[dfx["kind"] == "crack", "ut_mode"] == "angle").all()
    for kind, mode in network.UT_MODE.items():
        assert (dfx.loc[dfx["kind"] == kind, "ut_mode"] == mode).all()


def test_referential_integrity(net):
    seg, feat, dfx = net
    assert dfx["segment_id"].isin(seg["segment_id"]).all()
    assert feat["segment_id"].isin(seg["segment_id"]).all()
    fid = dfx["feature_id"].dropna()
    assert fid.isin(feat["feature_id"]).all()


def test_critical_definition(cfg, net):
    seg, _, dfx = net
    m = dfx.merge(seg, on="segment_id")
    wl = m[m["ut_mode"] == "straight"]
    assert (wl["critical"] == (wl["remaining_wall_mm"] < wl["t_min_mm"])).all()
    assert (np.isclose(wl["remaining_wall_mm"] + wl["depth_mm"], wl["wall_mm"], atol=2e-3)).all()


def test_fac_density_elbow_vs_straight(cfg):
    seg, feat, dfx = network.generate_network(cfg, seed=3, total_km=20)
    elig = seg[(seg["material"] == "carbon_steel")
               & seg["medium"].isin(params.get(cfg, "defects.fac.media"))]
    fac = dfx[dfx["kind"] == "fac_thinning"]
    fkind = fac["feature_id"].map(feat.set_index("feature_id")["kind"])
    n_elbows = (feat["kind"] == "elbow")[feat["segment_id"].isin(elig["segment_id"])].sum()
    per_elbow = (fkind == "elbow").sum() / n_elbows
    per_m_straight = fac["feature_id"].isna().sum() / elig["length_m"].sum()
    # one elbow attracts more FAC than a metre of straight pipe by a wide margin
    assert per_elbow > 20 * per_m_straight


def test_consequence(cfg):
    assert network.consequence("oxygen", cfg) == 5
    assert network.consequence("pickling_acid_hf", cfg) >= 4
    assert network.consequence("byproduct_gas_co", cfg) >= 4
    assert network.consequence("cooling_water", cfg) < network.consequence("oxygen", cfg)


def test_save_and_cli(tmp_path, cfg, net):
    paths = network.save_network(tmp_path, *net)
    assert [p.name for p in paths] == ["segments.csv", "features.csv", "defects.csv"]
    back = pd.read_csv(tmp_path / "defects.csv")
    assert len(back) == len(net[2])
    from maek import cli
    assert cli.main(["network", "--seed", "1", "--total-km", "1", "--out", str(tmp_path / "c")]) == 0
    assert (tmp_path / "c" / "segments.csv").exists()


# --- regression: base network (default config) must not change when new features are added ---
BASE_REF = {  # kind -> (count, depth_mm sum), seed 3, total_km 5, recorded before the steam work
    "cui": (15, 31.009), "external_corrosion": (12, 17.956), "fac_thinning": (10, 22.249),
    "internal_pitting": (9, 10.018), "crack": (1, 1.131), "flange_leak": (1, 0.0),
}


def test_base_network_regression(cfg):
    _, _, dfx = network.generate_network(cfg, seed=3)
    for kind, (n, depth) in BASE_REF.items():
        sub = dfx[dfx["kind"] == kind]
        assert len(sub) == n, kind
        assert sub["depth_mm"].sum() == pytest.approx(depth, abs=2e-3), kind


@pytest.fixture(scope="module")
def steam_net():
    c = params.load_config(overlays=[params.scenario_path("steam")])
    return c, network.generate_network(c, seed=0)


def test_steam_scenario_content(steam_net):
    _c, (seg, feat, dfx) = steam_net
    assert set(seg["medium"]) == {"steam", "condensate", "traced_process"}
    assert (seg["traced"] == (seg["medium"] == "traced_process")).all()
    assert (seg.loc[seg["traced"], "insulated"]).all()
    assert (seg.loc[~seg["insulated"], "insulation_mm"] == 0).all()
    assert (seg.loc[seg["insulated"], "jacket"] != "").all()
    st = seg[seg["medium"] == "steam"]
    assert (st["pressure_barg"] > 0).all()
    assert {"steam_trap", "low_point"} <= set(feat["kind"])
    assert feat["feature_id"].is_unique and dfx["defect_id"].is_unique
    for k in network.DEFECT_KINDS[6:]:
        assert (dfx.loc[dfx["kind"] == k, "ut_mode"] == "").all()
        sub = dfx[dfx["kind"] == k]
        assert len(sub) > 0 or k == "steam_leak"
        assert (sub["depth_mm"] == 0).all() and not sub["critical"].any()
    assert dfx["feature_id"].dropna().isin(feat["feature_id"]).all()
    zk = dfx.set_index("defect_id")["kind"]
    zone = dfx.dropna(subset=["zone_id"])
    assert set(zone.loc[zone["kind"] == "cui", "zone_id"].map(zk)) == {"wet_insulation"}
    assert set(zone.loc[zone["kind"] == "wet_insulation", "zone_id"].map(zk)) == {"tracer_leak"}
    cui_z = dfx[(dfx["kind"] == "cui") & dfx["zone_id"].notna()]
    assert len(cui_z) > 0
    assert (dfx["segment_id"].isin(seg["segment_id"])).all()
    assert dfx["pos_m"].between(0, 50).all()


def test_camera_ignores_new_kinds(steam_net):
    from maek.camera import jobs

    _, (_, _, dfx) = steam_net
    assert set(jobs._visible(dfx)["kind"]) <= set(jobs.CLASS_OF)
