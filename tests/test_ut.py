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
