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
