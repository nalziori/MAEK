import numpy as np

from maek import heat


def test_saturation_round_trip_and_known_points():
    assert abs(float(heat.sat_pressure_bar_abs(100.0)) - 1.013) < 0.01
    assert abs(float(heat.sat_pressure_bar_abs(180.0)) - 10.0) < 0.15  # steam tables 10.03
    t = np.array([60.0, 120.0, 150.0, 200.0])
    assert np.allclose(heat.sat_temp_c(heat.sat_pressure_bar_abs(t)), t, atol=0.05)


def test_insulation_cuts_loss_and_wet_insulation_warms_jacket():
    args = {"t_in_c": 180.0, "t_amb_c": 15.0, "od_mm": 114.3}
    bare = heat.heat_loss_w_per_m(**args, ins_mm=0, k_w_mk=0.045, h_out_w_m2k=20)
    ins = heat.heat_loss_w_per_m(**args, ins_mm=50, k_w_mk=0.045, h_out_w_m2k=10)
    wet = heat.heat_loss_w_per_m(**args, ins_mm=50, k_w_mk=0.045 * 5, h_out_w_m2k=10)
    assert bare > 10 * ins and ins < wet < bare
    assert 60 < float(ins) < 80  # hand calculation: 165 K / 2.37 K m/W = 69.6 W/m
    t_dry = heat.surface_temp_c(**args, ins_mm=50, k_w_mk=0.045, h_out_w_m2k=10)
    t_wet = heat.surface_temp_c(**args, ins_mm=50, k_w_mk=0.045 * 5, h_out_w_m2k=10)
    assert 15 < float(t_dry) < float(t_wet) < 180
