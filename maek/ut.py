"""Ultrasonic testing (UT) A-scan simulator and baseline analysis (numpy only).

Function (2): internal crack detection by angle-beam shear wave (corner-trap echo).
Function (3): wall thickness by straight-beam pulse-echo longitudinal wave.

Amplitudes are normalised (first back-wall echo of a clean, well coupled probe ~ 1.0).
Time axis: t = i / fs, with fs = ut.sampling_mhz. The interface (initial) echo sits at
ut.interface_delay_us; back-wall echoes follow at multiples of 2*wall/v.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from maek.params import get


# ---------------------------------------------------------------- helpers
def _p(cfg):
    """Frequently used parameters in SI-ish units (s, m/s, Hz)."""
    return {
        "fs": get(cfg, "ut.sampling_mhz") * 1e6,
        "f0": get(cfg, "ut.probe_freq_mhz") * 1e6,
        "n": int(get(cfg, "ut.n_samples")),
        "t0": get(cfg, "ut.interface_delay_us") * 1e-6,
        "sigma": get(cfg, "ut.pulse_sigma_us") * 1e-6,
    }


def velocity_long(cfg, temp_c: float) -> float:
    return get(cfg, "ut.v_long") + get(cfg, "ut.temp_coeff_mps_per_c") * (temp_c - 20.0)


def velocity_shear(cfg, temp_c: float) -> float:
    return get(cfg, "ut.v_shear") + get(cfg, "ut.temp_coeff_shear_mps_per_c") * (temp_c - 20.0)


def _time(cfg) -> np.ndarray:
    p = _p(cfg)
    return np.arange(p["n"]) / p["fs"]


def _pulse(cfg, t: np.ndarray, tc: float) -> np.ndarray:
    """Gaussian-modulated sinusoid centred at tc."""
    p = _p(cfg)
    dt = t - tc
    return np.exp(-0.5 * (dt / p["sigma"]) ** 2) * np.cos(2 * np.pi * p["f0"] * dt)


def _atten(cfg, path_mm: float) -> float:
    return 10 ** (-get(cfg, "ut.atten_db_per_mm") * path_mm / 20.0)


def _grain_noise(cfg, rng, start: float, scale: float) -> np.ndarray:
    """Band-limited (probe band) backscatter starting at `start` seconds."""
    p = _p(cfg)
    t = _time(cfg)
    white = rng.standard_normal(p["n"])
    k = _pulse(cfg, np.arange(-64, 65) / p["fs"], 0.0)
    k /= np.sqrt(np.sum(k**2))
    g = np.convolve(white, k, mode="same")
    g[t < start] = 0.0
    return get(cfg, "ut.grain_noise_std") * scale * g


def envelope(x: np.ndarray) -> np.ndarray:
    """Magnitude of the analytic signal (FFT Hilbert transform)."""
    n = len(x)
    X = np.fft.fft(x)
    h = np.zeros(n)
    h[0] = 1.0
    if n % 2 == 0:
        h[n // 2] = 1.0
        h[1:n // 2] = 2.0
    else:
        h[1:(n + 1) // 2] = 2.0
    return np.abs(np.fft.ifft(X * h))


def _parabolic(y: np.ndarray, i: int) -> float:
    if i <= 0 or i >= len(y) - 1:
        return float(i)
    a, b, c = y[i - 1], y[i], y[i + 1]
    d = a - 2 * b + c
    return float(i) if d == 0 else i + 0.5 * (a - c) / d


# ---------------------------------------------------------------- straight beam
def simulate_straight(cfg, rng, wall_mm, pit_depth_mm=0.0, pit_fraction=0.0, temp_c=20.0,
                      coupling=1.0, noise_scale=1.0) -> np.ndarray:
    """Pulse-echo A-scan (longitudinal wave, normal incidence)."""
    p = _p(cfg)
    t = _time(cfg)
    v = velocity_long(cfg, temp_c)
    a1 = get(cfg, "ut.backwall_amp")
    decay = get(cfg, "ut.backwall_decay")
    s = get(cfg, "ut.interface_amp") * _pulse(cfg, t, p["t0"])
    pit_fraction = float(np.clip(pit_fraction, 0.0, 1.0)) if pit_depth_mm > 0 else 0.0
    trains = [(wall_mm, a1 * (1.0 - pit_fraction))]
    if pit_fraction > 0:
        trains.append((wall_mm - pit_depth_mm, a1 * pit_fraction))
    for thick, amp in trains:
        T = 2 * thick * 1e-3 / v
        k = 1
        while p["t0"] + k * T < t[-1] and amp > 0:
            s += amp * decay ** (k - 1) * _atten(cfg, 2 * k * thick) * _pulse(cfg, t, p["t0"] + k * T)
            k += 1
    s += _grain_noise(cfg, rng, p["t0"] + 3 * p["sigma"], noise_scale)
    s *= coupling
    s += get(cfg, "ut.noise_std") * noise_scale * rng.standard_normal(p["n"])
    return s.astype(np.float32)


def _gate_start(cfg) -> int:
    p = _p(cfg)
    return int((p["t0"] + 5 * p["sigma"]) * p["fs"])


def estimate_thickness(cfg, signal, temp_c=20.0) -> float:
    """Wall thickness [mm] from the spacing of successive back-wall echoes.

    The interface echo is gated out; the autocorrelation of the remaining RF trace peaks
    at the echo spacing. Coarse lag from the autocorrelation envelope, refined on the RF
    autocorrelation with parabolic interpolation.
    """
    p = _p(cfg)
    x = np.asarray(signal, dtype=float)[_gate_start(cfg):]
    x = x - x.mean()
    n = len(x)
    X = np.fft.rfft(x, 2 * n)
    ac = np.fft.irfft(X * np.conj(X))[:n]
    v = velocity_long(cfg, temp_c)
    lag_min = int(2 * 1.5e-3 / v * p["fs"])  # 1.5 mm
    lag_max = min(n - 1, int(2 * 25e-3 / v * p["fs"]))  # 25 mm
    env = envelope(ac)
    i = lag_min + int(np.argmax(env[lag_min:lag_max]))
    half = int(p["fs"] / p["f0"] / 2)
    lo, hi = max(1, i - half), min(n - 2, i + half)
    j = lo + int(np.argmax(ac[lo:hi + 1]))
    lag = _parabolic(ac, j) / p["fs"]
    return float(lag * v / 2 * 1e3)


def min_thickness(cfg, signal, temp_c=20.0, rel_threshold=0.15, snr=6.0) -> float:
    """Remaining thickness [mm] from the earliest significant echo after the interface."""
    p = _p(cfg)
    g0 = _gate_start(cfg)
    x = np.asarray(signal, dtype=float)
    env = envelope(x)[g0:]
    noise = 1.4826 * np.median(np.abs(x[-len(x) // 8:] - np.median(x[-len(x) // 8:])))
    thr = max(rel_threshold * env.max(), snr * noise)
    above = np.nonzero(env > thr)[0]
    if len(above) == 0:
        return float("nan")
    w = int(3 * p["sigma"] * p["fs"])
    a = above[0]
    i = a + int(np.argmax(env[a:a + w]))
    tpk = (g0 + _parabolic(env, i)) / p["fs"]
    return float((tpk - p["t0"]) * velocity_long(cfg, temp_c) / 2 * 1e3)


# ---------------------------------------------------------------- angle beam
def corner_trap_time(cfg, wall_mm, angle_deg=60, temp_c=20.0) -> float:
    """Arrival time [s] of the ID corner-trap echo (half-skip, round trip)."""
    path = 2 * wall_mm * 1e-3 / np.cos(np.radians(angle_deg))
    return _p(cfg)["t0"] + path / velocity_shear(cfg, temp_c)


def _crack_amp(cfg, height_mm):
    return get(cfg, "ut.crack_amp_max") * (1 - np.exp(-height_mm / get(cfg, "ut.crack_h0_mm")))


def simulate_angle(cfg, rng, wall_mm, crack_height_mm=0.0, angle_deg=60, temp_c=20.0,
                   coupling=1.0, noise_scale=1.0) -> np.ndarray:
    """Angle-beam shear-wave A-scan; inner-surface crack gives a corner-trap echo."""
    p = _p(cfg)
    t = _time(cfg)
    s = np.zeros(p["n"])
    path_mm = 2 * wall_mm / np.cos(np.radians(angle_deg))
    if crack_height_mm > 0:
        tc = corner_trap_time(cfg, wall_mm, angle_deg, temp_c)
        s += _crack_amp(cfg, crack_height_mm) * _atten(cfg, path_mm) * _pulse(cfg, t, tc)
    for _ in range(rng.integers(0, 4)):  # weak geometric clutter (root, ID roughness)
        tc = rng.uniform(p["t0"], t[-1])
        s += rng.uniform(0, get(cfg, "ut.clutter_amp")) * _pulse(cfg, t, tc)
    s += _grain_noise(cfg, rng, p["t0"], noise_scale)
    s *= coupling
    s += get(cfg, "ut.noise_std") * noise_scale * rng.standard_normal(p["n"])
    return s.astype(np.float32)


def detect_crack(cfg, signal, wall_mm, angle_deg=60, temp_c=20.0) -> dict:
    """Gate the envelope around the expected corner-trap time.

    Threshold = max(fixed amplitude, SNR x robust noise floor measured outside the gate).
    """
    p = _p(cfg)
    tc = corner_trap_time(cfg, wall_mm, angle_deg, temp_c)
    half = get(cfg, "ut.gate_halfwidth_us") * 1e-6 + 0.03 * (tc - p["t0"])
    lo = max(0, int((tc - half) * p["fs"]))
    hi = min(len(signal), int((tc + half) * p["fs"]) + 1)
    x = np.asarray(signal, dtype=float)
    env = envelope(x)
    score = float(env[lo:hi].max()) if hi > lo else 0.0
    outside = np.concatenate([x[int(p["t0"] * p["fs"]):lo], x[hi:]])
    noise = 1.4826 * np.median(np.abs(outside - np.median(outside))) if len(outside) else 0.0
    thr = max(get(cfg, "ut.crack_threshold"), get(cfg, "ut.crack_snr") * noise)
    found = score > thr
    height = 0.0
    if found:
        path_mm = 2 * wall_mm / np.cos(np.radians(angle_deg))
        r = min(score / (get(cfg, "ut.crack_amp_max") * _atten(cfg, path_mm)), 0.99)
        height = float(-get(cfg, "ut.crack_h0_mm") * np.log(1 - r))
    return {"found": bool(found), "score": score, "height_est_mm": height}


# ---------------------------------------------------------------- remaining life
def remaining_life(years, thickness_mm, t_min_mm, max_interval_yr=10.0) -> dict:
    """Linear corrosion-rate fit; next inspection at half remaining life (API 570)."""
    years = np.asarray(years, dtype=float)
    th = np.asarray(thickness_mm, dtype=float)
    slope, icpt = np.polyfit(years, th, 1)
    rate = float(-slope)
    t_now = slope * years.max() + icpt
    if rate <= 0:
        remaining = float("inf")
    else:
        remaining = float(max(t_now - t_min_mm, 0.0) / rate)
    nxt = float(min(remaining / 2.0, max_interval_yr))
    return {"rate_mm_per_yr": rate, "remaining_years": remaining, "next_inspection_years": nxt}


# ---------------------------------------------------------------- dataset
def make_dataset(cfg, n, seed, condition="train"):
    """Random UT cases. Returns (straight [n, N], angle [n, N], labels DataFrame)."""
    if condition not in ("train", "shifted"):
        raise ValueError("condition must be 'train' or 'shifted'")
    rng = np.random.default_rng(seed)
    d = "ut.dataset."
    shifted = condition == "shifted"
    temp_rng = get(cfg, d + ("shifted_temp_range_c" if shifted else "train_temp_range_c"))
    coup_rng = get(cfg, d + ("shifted_coupling_range" if shifted else "train_coupling_range"))
    noise_scale = get(cfg, d + "shifted_noise_scale") if shifted else 1.0
    angles = get(cfg, "ut.angle_beam_angles_deg")
    wr = get(cfg, d + "wall_range_mm")
    n_s = int(get(cfg, "ut.n_samples"))
    straight = np.zeros((n, n_s), np.float32)
    angle = np.zeros((n, n_s), np.float32)
    rows = []
    for i in range(n):
        wall = rng.uniform(*wr)
        pit_depth = pit_frac = 0.0
        if rng.random() < get(cfg, d + "pit_prob"):
            pit_depth = wall * rng.uniform(*get(cfg, d + "pit_depth_frac_range"))
            pit_frac = rng.uniform(*get(cfg, d + "pit_fraction_range"))
        crack_h = 0.0
        if rng.random() < get(cfg, d + "crack_prob"):
            crack_h = wall * rng.uniform(*get(cfg, d + "crack_height_frac_range"))
        temp = rng.uniform(*temp_rng)
        coup = rng.uniform(*coup_rng)
        ang = float(angles[rng.integers(len(angles))])
        straight[i] = simulate_straight(cfg, rng, wall, pit_depth, pit_frac, temp, coup,
                                        noise_scale)
        angle[i] = simulate_angle(cfg, rng, wall, crack_h, ang, temp, coup, noise_scale)
        rows.append({"wall_mm": wall, "pit_depth_mm": pit_depth, "pit_fraction": pit_frac,
                     "t_min_mm": wall - pit_depth, "crack": crack_h > 0,
                     "crack_height_mm": crack_h, "angle_deg": ang, "temp_c": temp,
                     "coupling": coup, "noise_scale": noise_scale, "condition": condition})
    return straight, angle, pd.DataFrame(rows)


def save_dataset(out_dir, straight, angle, labels) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "ut_straight.npz", signals=straight)
    np.savez_compressed(out / "ut_angle.npz", signals=angle)
    labels.to_csv(out / "ut_labels.csv", index=False)


def baseline(cfg, straight, angle, labels) -> dict:
    """Rule-based baseline: thickness MAE, min-thickness MAE, crack POD / false alarms."""
    th = np.array([estimate_thickness(cfg, s, r.temp_c) for s, r in zip(straight, labels.itertuples())])
    tm = np.array([min_thickness(cfg, s, r.temp_c) for s, r in zip(straight, labels.itertuples())])
    det = np.array([detect_crack(cfg, s, r.wall_mm, r.angle_deg, r.temp_c)["found"]
                    for s, r in zip(angle, labels.itertuples())])
    crack = labels["crack"].to_numpy(bool)
    return {
        "thickness_mae_mm": float(np.nanmean(np.abs(th - labels["wall_mm"]))),
        "min_thickness_mae_mm": float(np.nanmean(np.abs(tm - labels["t_min_mm"]))),
        "crack_detection_rate": float(det[crack].mean()) if crack.any() else float("nan"),
        "false_alarm_rate": float(det[~crack].mean()) if (~crack).any() else float("nan"),
    }
