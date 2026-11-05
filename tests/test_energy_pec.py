import pandas as pd
import pytest

from maek import energy, params, pec

CFG = params.load_config()


def test_napier():
    lb_h = energy.napier_kg_h(10, 3.0) / 0.453592
    assert lb_h == pytest.approx(54.0, abs=0.5)
    assert energy.napier_kg_h(10, 3.0) == pytest.approx(24.5, abs=0.3)


def test_bare_pipe_loss():
    seg = {"temp_c": 180.0, "od_mm": 114.3, "insulation_mm": 50.0, "pressure_barg": 8.0}
    d = {"kind": "insulation_damage", "length_mm": 1000.0, "circ_frac": 1.0}
    assert energy.defect_loss_kw(CFG, seg, d) == pytest.approx(1.1, abs=0.15)


def test_wet_and_zero_kinds():
    seg = {"temp_c": 120.0, "od_mm": 114.3, "insulation_mm": 50.0, "pressure_barg": 1.0}
    wet = {"kind": "wet_insulation", "length_mm": 2000.0, "moisture": 1.0, "circ_frac": 0.0}
    dry = {**wet, "moisture": 0.0}
    assert energy.defect_loss_kw(CFG, seg, wet) > 0
    assert energy.defect_loss_kw(CFG, seg, dry) == pytest.approx(0.0, abs=1e-9)
    assert energy.defect_loss_kw(CFG, seg, {"kind": "crack"}) == 0.0
    cold = {**seg, "temp_c": 5.0}
    assert energy.defect_loss_kw(CFG, cold, {**wet, "kind": "insulation_damage",
                                             "circ_frac": 1.0}) == 0.0


def test_annual_consistent():
    a = energy.annual(CFG, [1.0, 2.0])
    h = params.get(CFG, "energy.hours_per_year")
    assert a["mwh_per_yr"][0] == pytest.approx(h / 1000)
    assert a["steam_t_per_yr"][1] == pytest.approx(2 * h * 3.6 / 2650)
    assert a["cost_krw_per_yr"][0] == pytest.approx(a["steam_t_per_yr"][0] * 35000)
    assert a["co2_t_per_yr"][1] == pytest.approx(2 * a["co2_t_per_yr"][0])
    assert a["co2_t_per_yr"][0] > 0


def test_losses_table():
    from maek import network

    c = params.load_config(overlays=[params.scenario_path("steam")])
    seg, _, dfx = network.generate_network(c, seed=0, total_km=5)
    out = energy.losses(c, seg, dfx)
    assert set(out["kind"]) <= set(energy.ENERGY_KINDS)
    assert len(out) == dfx["kind"].isin(energy.ENERGY_KINDS).sum()
    assert (out["loss_kw"] >= 0).all() and out["loss_kw"].sum() > 0
    assert list(out.columns)[:4] == ["defect_id", "segment_id", "kind", "loss_kw"]
    assert isinstance(out, pd.DataFrame)


def _seg(ins=50.0, material="carbon_steel", jacket="aluminium"):
    return {"material": material, "wall_mm": 6.02, "insulation_mm": ins, "jacket": jacket}


def _d(kind="cui", depth=3.0, area=100.0, clock=180.0):
    return {"kind": kind, "depth_mm": depth, "area_cm2": area, "clock_deg": clock}


def test_pec_pit_vs_patch():
    assert pec.detect_prob(CFG, _seg(), _d("internal_pitting", 3.0, 1.0)) < 0.01
    assert pec.detect_prob(CFG, _seg(), _d("cui", 3.01, 100.0)) > 0.9


def test_pec_gates():
    assert pec.detect_prob(CFG, _seg(material="stainless"), _d()) == 0.0
    assert pec.detect_prob(CFG, _seg(), _d(clock=0.0)) == 0.0
    assert pec.detect_prob(CFG, _seg(), _d("crack")) == 0.0


def test_pec_galvanized_and_thickness():
    d = _d(depth=0.75, area=100.0)  # borderline: ~ threshold
    base = pec.detect_prob(CFG, _seg(), d)
    assert 0.05 < base < 0.95
    # borderline above threshold -> noise lowers P; below threshold -> raises it, so pick above
    d2 = d
    assert pec.detect_prob(CFG, _seg(jacket="galvanized"), d2) < pec.detect_prob(CFG, _seg(), d2)
    small = _d(depth=1.5, area=30.0)  # footprint dilution grows with insulation thickness
    assert pec.detect_prob(CFG, _seg(ins=100.0), small) < pec.detect_prob(CFG, _seg(ins=25.0), small)


def test_pec_helpers():
    assert pec.footprint_mm(CFG, 50) == 70.0
    assert pec.scan_minutes(CFG, 50) == pytest.approx(5 + 4 * 50)
