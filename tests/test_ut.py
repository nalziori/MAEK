import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from maek import params, ut

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cfg():
    return params.load_config(ROOT / "config" / "default.yaml")


@pytest.mark.parametrize("wall", [3.0, 4.5, 6.02, 8.18, 10.31, 12.0])
def test_clean_thickness_within_0p1(cfg, wall):
    s = ut.simulate_straight(cfg, np.random.default_rng(1), wall)
    assert s.dtype == np.float32 and len(s) == params.get(cfg, "ut.n_samples")
    assert abs(ut.estimate_thickness(cfg, s) - wall) < 0.1
    assert abs(ut.min_thickness(cfg, s) - wall) < 0.1


def test_thinner_wall_earlier_echo(cfg):
    fs = params.get(cfg, "ut.sampling_mhz") * 1e6
    g = int((params.get(cfg, "ut.interface_delay_us") + 0.5) * 1e-6 * fs)
    peaks = []
    for w in (8.0, 5.0):
        s = ut.simulate_straight(cfg, np.random.default_rng(0), w)
        peaks.append(g + int(np.argmax(ut.envelope(s)[g:])))
    assert peaks[1] < peaks[0]


def test_temperature_correction_80c(cfg):
    s = ut.simulate_straight(cfg, np.random.default_rng(2), 8.0, temp_c=80.0)
    assert abs(ut.estimate_thickness(cfg, s, temp_c=80.0) - 8.0) < 0.1


def test_pit_gives_min_thickness(cfg):
    s = ut.simulate_straight(cfg, np.random.default_rng(3), 8.0, pit_depth_mm=3.0,
                             pit_fraction=0.4)
    assert abs(ut.estimate_thickness(cfg, s) - 8.0) < 0.1
    assert abs(ut.min_thickness(cfg, s) - 5.0) < 0.15


@pytest.mark.parametrize("angle", [45, 60, 70])
def test_crack_found_and_not_found(cfg, angle):
    rng = np.random.default_rng(4)
    with_crack = ut.simulate_angle(cfg, rng, 8.0, crack_height_mm=1.5, angle_deg=angle)
    without = ut.simulate_angle(cfg, rng, 8.0, angle_deg=angle)
    assert ut.detect_crack(cfg, with_crack, 8.0, angle)["found"]
    assert not ut.detect_crack(cfg, without, 8.0, angle)["found"]


def test_larger_crack_higher_score(cfg):
    scores = [ut.detect_crack(cfg, ut.simulate_angle(cfg, np.random.default_rng(5), 8.0, h),
                              8.0)["score"] for h in (0.3, 1.0, 3.0)]
    assert scores[0] < scores[1] < scores[2]


def test_remaining_life_linear():
    years = np.arange(0, 10)
    th = 10.0 - 0.2 * years
    r = ut.remaining_life(years, th, t_min_mm=4.0, max_interval_yr=10)
    assert r["rate_mm_per_yr"] == pytest.approx(0.2)
    assert r["remaining_years"] == pytest.approx((8.2 - 4.0) / 0.2)
    assert r["next_inspection_years"] == pytest.approx(10.0)  # capped
    r2 = ut.remaining_life(years, th, t_min_mm=7.0)
    assert r2["next_inspection_years"] == pytest.approx(r2["remaining_years"] / 2)


def test_make_dataset_deterministic(cfg, tmp_path):
    a1, b1, l1 = ut.make_dataset(cfg, 8, 7, "train")
    a2, b2, l2 = ut.make_dataset(cfg, 8, 7, "train")
    assert np.array_equal(a1, a2) and np.array_equal(b1, b2) and l1.equals(l2)
    _, _, ls = ut.make_dataset(cfg, 8, 7, "shifted")
    assert (ls["coupling"] < l1["coupling"].min()).all()
    ut.save_dataset(tmp_path, a1, b1, l1)
    assert {"ut_straight.npz", "ut_angle.npz", "ut_labels.csv"} <= {p.name for p in tmp_path.iterdir()}


def test_cli_ut(tmp_path):
    r = subprocess.run([sys.executable, "-m", "maek", "ut", "--n", "5", "--out", str(tmp_path)],
                       cwd=ROOT, check=False, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "thickness MAE" in r.stdout and (tmp_path / "ut_labels.csv").exists()


# ---------------------------------------------------------------- regression: review findings
@pytest.mark.parametrize("wall", [4.0, 6.0, 8.0, 10.5, 12.0])
@pytest.mark.parametrize("pit_fraction", [0.3, 0.45, 0.6])
@pytest.mark.parametrize("depth_frac", [0.2, 0.375, 0.6])
def test_pitted_thickness_is_nominal_wall(cfg, wall, pit_fraction, depth_frac):
    s = ut.simulate_straight(cfg, np.random.default_rng(3), wall, pit_depth_mm=depth_frac * wall,
                             pit_fraction=pit_fraction)
    assert abs(ut.estimate_thickness(cfg, s) - wall) <= 0.2
    # the pit is still reported by the minimum thickness
    assert abs(ut.min_thickness(cfg, s) - (1 - depth_frac) * wall) < 0.3


def test_dataset_has_no_large_thickness_outliers(cfg):
    straight, _, lab = ut.make_dataset(cfg, 400, 0, "train")
    est = np.array([ut.estimate_thickness(cfg, s, t) for s, t in zip(straight, lab["temp_c"])])
    assert np.abs(est - lab["wall_mm"].to_numpy()).max() <= 0.5


@pytest.mark.parametrize("wall,pit", [(5.0, 5.0), (5.0, 6.0), (0.0, 0.0), (-1.0, 0.0),
                                      (5.0, -1.0)])
def test_simulate_straight_rejects_bad_geometry(cfg, wall, pit):
    with pytest.raises(ValueError):
        ut.simulate_straight(cfg, np.random.default_rng(0), wall, pit_depth_mm=pit,
                             pit_fraction=0.3)


def test_make_dataset_clips_pit_below_wall(cfg):
    import copy

    c = copy.deepcopy(cfg)
    c["ut"]["dataset"]["pit_prob"]["value"] = 1.0
    c["ut"]["dataset"]["pit_depth_frac_range"]["value"] = [1.0, 1.5]
    c["ut"]["n_samples"]["value"] = 1024
    _, _, lab = ut.make_dataset(c, 20, 0)
    assert (lab["pit_depth_mm"] < lab["wall_mm"]).all()


def test_measured_temperature_labels_and_zero_error(cfg):
    from maek import evaluate

    c = evaluate._with(cfg, "ut.n_samples", 2048)
    for key in ("train_temp_meas_error_c", "shifted_temp_meas_error_c"):
        c = evaluate._with(c, "ut.dataset." + key, 0.0)
    st, an, lab = ut.make_dataset(c, 30, 4, "shifted")
    assert np.allclose(lab["temp_meas_c"], lab["temp_c"])
    true_path = lab.drop(columns=["temp_meas_c"])  # falls back to the true temperature
    assert np.allclose(ut.analysis_temps(c, lab), ut.analysis_temps(c, true_path))
    assert ut.baseline(c, st, an, lab) == ut.baseline(c, st, an, true_path)


def test_shifted_measurement_error_reduces_accuracy_at_high_temp(cfg):
    from maek import evaluate

    base = evaluate._with(cfg, "ut.n_samples", 2048)
    zero = evaluate._with(base, "ut.dataset.shifted_temp_meas_error_c", 0.0)
    big = evaluate._with(base, "ut.dataset.shifted_temp_meas_error_c", 40.0)
    none = evaluate._with(base, "ut.temp_compensation", "none")
    mae = {k: evaluate.eval_ut(c, "shifted", 60, seed=5)["thickness_mae_valid_mm"]
           for k, c in (("zero", zero), ("big", big), ("none", none))}
    assert mae["big"] > mae["zero"]
    assert mae["none"] > mae["zero"]
    # 15 C default error sits between perfect and uncorrected
    assert evaluate.eval_ut(base, "shifted", 60, seed=5)["thickness_mae_valid_mm"] >= mae["zero"]


def test_h6_thickness_valid_and_fail_rate(cfg):
    import pandas as pd
    from maek import evaluate

    st, an, lab = ut.make_dataset(cfg, 10, 0, "train")
    b = ut.baseline(cfg, st, an, lab)
    for k in ("thickness_mae_valid_mm", "thickness_n_valid", "thickness_fail_rate",
              "min_thickness_mae_valid_mm"):
        assert k in b
    assert b["thickness_n_valid"] == 10
    assert b["thickness_fail_rate"] == 0.0
    assert b["thickness_mae_valid_mm"] >= 0

    dummy_labels = pd.DataFrame({"wall_mm": [10.0, 10.0], "t_min_mm": [10.0, 10.0],
                                 "temp_c": [20.0, 20.0], "crack": [False, False],
                                 "angle_deg": [45, 45]})
    nan_straight = [np.full(2048, np.nan), np.full(2048, np.nan)]
    dummy_angle = [np.zeros(2048), np.zeros(2048)]
    b_fail = ut.baseline(cfg, nan_straight, dummy_angle, dummy_labels)
    assert b_fail["thickness_n_valid"] == 0
    assert b_fail["thickness_fail_rate"] == 1.0
    assert np.isnan(b_fail["thickness_mae_valid_mm"])

    # Mixed case: 1 valid, 1 NaN
    mixed_straight = [st[0], np.full(2048, np.nan)]
    mixed_angle = [an[0], np.zeros(2048)]
    mixed_labels = pd.DataFrame({"wall_mm": [lab["wall_mm"].iloc[0], 10.0],
                                 "t_min_mm": [lab["t_min_mm"].iloc[0], 10.0],
                                 "temp_c": [lab["temp_c"].iloc[0], 20.0],
                                 "crack": [False, False],
                                 "angle_deg": [45, 45]})
    b_mixed = ut.baseline(cfg, mixed_straight, mixed_angle, mixed_labels)
    assert b_mixed["thickness_n_valid"] == 1
    assert b_mixed["thickness_fail_rate"] == 0.5
    assert not np.isnan(b_mixed["thickness_mae_valid_mm"])


def test_h7_pod_cell_all_hit_text():
    from maek import evaluate

    s = np.linspace(0.5, 5.0, 20)
    all_hit_summary = evaluate.pod_summary(s, np.ones(20))
    assert all_hit_summary["status"] == "all_hit"
    assert evaluate.pod_cell(all_hit_summary) == "전부 검출(a90 추정 불가)"

    all_miss_summary = evaluate.pod_summary(s, np.zeros(20))
    assert all_miss_summary["status"] == "all_miss"
    assert evaluate.pod_cell(all_miss_summary) == "전부 미검출(a90 추정 불가)"

