"""Ultrasonic testing (UT) A-scan simulator and baseline analysis (numpy only).

Function (2): internal crack detection by angle-beam shear wave (corner-trap echo).
Function (3): wall thickness by straight-beam pulse-echo longitudinal wave; internal pits by
`detect_pit` (matched filter + back-wall subtraction + CFAR features, see `maek.pit`).

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
                      coupling=1.0, noise_scale=1.0, n_avg=1, avg_rng=None) -> np.ndarray:
    """Pulse-echo A-scan (longitudinal wave, normal incidence).

    `n_avg` > 1 returns the coherent average of n_avg shots at the same probe position:
    coupling and grain backscatter (fixed by the microstructure under the probe) are shared,
    electronic noise is independent per shot, so it drops by sqrt(n_avg). Extra shots draw
    from `avg_rng` (default `rng`); n_avg=1 consumes exactly the same random numbers as before.
    """
    n_avg = int(n_avg)
    if n_avg < 1:
        raise ValueError(f"n_avg must be >= 1, got {n_avg}")
    if not wall_mm > 0:
        raise ValueError(f"wall_mm must be > 0, got {wall_mm}")
    if pit_depth_mm < 0 or pit_depth_mm >= wall_mm:
        raise ValueError(f"pit_depth_mm must be in [0, wall_mm); got {pit_depth_mm} "
                         f"for wall {wall_mm}")
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
        if T <= 0:
            continue
        k = 1
        while p["t0"] + k * T < t[-1] and amp > 0:
            s += amp * decay ** (k - 1) * _atten(cfg, 2 * k * thick) * _pulse(cfg, t, p["t0"] + k * T)
            k += 1
    s += _grain_noise(cfg, rng, p["t0"] + 3 * p["sigma"], noise_scale)
    s *= coupling
    noise = rng.standard_normal(p["n"])
    if n_avg > 1:
        extra = (avg_rng if avg_rng is not None else rng).standard_normal((n_avg - 1, p["n"]))
        noise = (noise + extra.sum(axis=0)) / n_avg
    s += get(cfg, "ut.noise_std") * noise_scale * noise
    return s.astype(np.float32)


_MAX_PIT_FRAC = 0.95  # dataset pits never consume the whole wall
_COMB_K = 4  # echoes summed by the echo-comb score
_COMB_REL = 0.4  # peak must reach this fraction of the best comb score
_COMB_MID = 0.3  # penalty weight for echo energy midway between comb teeth
_COMB_SNR = 8.0  # ... and this many robust sigmas of the comb score


def _gate_start(cfg) -> int:
    p = _p(cfg)
    return int((p["t0"] + 5 * p["sigma"]) * p["fs"])


def _echo_train_lag(cfg, signal, temp_c) -> int:
    """Coarse back-wall echo spacing [samples] from an echo-comb score on the envelope.

    score(L) = sum_k env(t0 + k L) - w sum_k env(t0 + (k - 1/2) L) over the first echoes.
    Pits add a second, shorter echo train (and wall-pit cross terms at the pit depth) that
    can beat the wall train on plain autocorrelation. A comb scores only true echo trains
    (the midpoint term suppresses harmonics), so the wall spacing is the longest comb peak
    that stands clear of the noise floor.
    """
    p = _p(cfg)
    v = velocity_long(cfg, temp_c)
    env = envelope(np.asarray(signal, dtype=float))
    n = len(env)
    w = 3
    pad = np.pad(env, (w, w), mode="edge")
    env_max = np.lib.stride_tricks.sliding_window_view(pad, 2 * w + 1).max(axis=1)
    ref = round(p["t0"] * p["fs"])
    lag_min = int(2 * 1.5e-3 / v * p["fs"])  # 1.5 mm
    lag_max = min((n - 1 - ref) // _COMB_K, int(2 * 25e-3 / v * p["fs"]))  # 25 mm
    lags = np.arange(lag_min, lag_max)
    hits = sum(env_max[ref + k * lags] for k in range(1, _COMB_K + 1))
    # echoes midway between comb teeth mean L is a harmonic (or sub-harmonic) of the train
    mid = sum(env_max[ref + ((2 * k - 1) * lags) // 2] for k in range(1, _COMB_K + 1))
    score = hits - _COMB_MID * mid
    score = score - np.median(score)
    top = score.max()
    mad = 1.4826 * np.median(np.abs(score))
    peaks = np.nonzero((score[1:-1] >= score[:-2]) & (score[1:-1] > score[2:]))[0] + 1
    peaks = peaks[score[peaks] >= max(_COMB_REL * top, _COMB_SNR * mad)]
    best = int(peaks[np.argmax(lags[peaks])]) if len(peaks) else int(np.argmax(score))
    return int(lags[best])


def wall_echo_lag(cfg, signal, temp_c=20.0) -> float:
    """Back-wall echo spacing [samples, fractional] (see `estimate_thickness`)."""
    p = _p(cfg)
    x = np.asarray(signal, dtype=float)[_gate_start(cfg):]
    x = x - x.mean()
    n = len(x)
    X = np.fft.rfft(x, 2 * n)
    ac = np.fft.irfft(X * np.conj(X))[:n]
    i = _echo_train_lag(cfg, signal, temp_c)
    half = int(p["fs"] / p["f0"] / 2)
    lo, hi = max(1, i - half), min(n - 2, i + half)
    j = lo + int(np.argmax(ac[lo:hi + 1]))
    return _parabolic(ac, j)


def estimate_thickness(cfg, signal, temp_c=20.0) -> float:
    """Wall thickness [mm] from the spacing of successive back-wall echoes.

    Coarse spacing from an echo-comb score (robust to pits: returns the nominal wall, the
    longest echo train, not the pit depth; see `min_thickness` for the pit), refined on the
    RF autocorrelation of the gated trace with parabolic interpolation.
    """
    lag = wall_echo_lag(cfg, signal, temp_c) / _p(cfg)["fs"]
    return float(lag * velocity_long(cfg, temp_c) / 2 * 1e3)


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


def averaging_time_s(cfg, n_avg=None) -> float:
    """Extra acquisition time per UT point for coherent averaging: (n_avg - 1) / PRF [s]."""
    n_avg = get(cfg, "ut.n_avg") if n_avg is None else n_avg
    return float((int(n_avg) - 1) / get(cfg, "ut.prf_hz"))


def detect_pit(cfg, signal, wall_nominal_mm, temp_c=20.0, method=None) -> dict:
    """Default internal-pit detector -> {found, score, depth_est_mm} (see `maek.pit`).

    `ut.pit.method` (default learned: MLP on matched-filter + back-wall subtraction + CFAR
    features; mf_cfar is the training-free rule); `temp_c` is the measured temperature used
    for velocity correction. The signal is assumed to average `ut.n_avg` shots.
    """
    from maek import pit

    return pit.detect_pit(cfg, signal, wall_nominal_mm, temp_c, method)


# ---------------------------------------------------------------- angle beam
def corner_trap_time(cfg, wall_mm, angle_deg=60, temp_c=20.0) -> float:
    """Arrival time [s] of the ID corner-trap echo (half-skip, round trip)."""
    path = 2 * wall_mm * 1e-3 / np.cos(np.radians(angle_deg))
    return _p(cfg)["t0"] + path / velocity_shear(cfg, temp_c)


def _crack_amp(cfg, height_mm):
    return get(cfg, "ut.crack_amp_max") * (1 - np.exp(-height_mm / get(cfg, "ut.crack_h0_mm")))


def simulate_angle(cfg, rng, wall_mm, crack_height_mm=0.0, angle_deg=60, temp_c=20.0,
                   coupling=1.0, noise_scale=1.0, n_avg=1, avg_rng=None) -> np.ndarray:
    """Angle-beam shear wave; averaging shares grain/clutter and reduces electronics only.

    The default consumes the original random stream unchanged. Extra shots may use an
    independent ``avg_rng``, as for ``simulate_straight``.
    """
    if int(n_avg) != n_avg or n_avg < 1:
        raise ValueError("n_avg must be a positive integer")
    n_avg = int(n_avg)
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
    noise = rng.standard_normal(p["n"])
    if n_avg > 1:
        extra = (avg_rng if avg_rng is not None else rng).standard_normal((n_avg - 1, p["n"]))
        noise = (noise + extra.sum(axis=0)) / n_avg
    s += get(cfg, "ut.noise_std") * noise_scale * noise
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
def acquisition_counts(cfg, n_avg=None, angle_n_avg=None) -> tuple[int, int]:
    """Resolve dataset shot counts; a null/missing angle count follows the straight count."""
    n_avg = get(cfg, "ut.n_avg") if n_avg is None else n_avg
    if angle_n_avg is None:
        angle_n_avg = cfg["ut"].get("angle_n_avg", {}).get("value")
    angle_n_avg = n_avg if angle_n_avg is None else angle_n_avg
    for name, value in (("n_avg", n_avg), ("angle_n_avg", angle_n_avg)):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    return int(n_avg), int(angle_n_avg)


def make_dataset(cfg, n, seed, condition="train", n_avg=None, angle_n_avg=None):
    """Random UT cases. Returns (straight [n, N], angle [n, N], labels DataFrame).

    Both beams use `n_avg` shots (default `ut.n_avg`) unless `angle_n_avg` or
    `ut.angle_n_avg` overrides the angle beam. Use angle_n_avg=1 for legacy datasets.
    Each beam's extra shots use a separate random stream: geometry, truth and the
    other beam are unchanged when only one beam's count changes. Only independent
    electronic noise is averaged; coupling and grain backscatter are shared.
    """
    if condition not in ("train", "shifted"):
        raise ValueError("condition must be 'train' or 'shifted'")
    n_avg, angle_n_avg = acquisition_counts(cfg, n_avg, angle_n_avg)
    rng = np.random.default_rng(seed)
    avg_rng = np.random.default_rng([seed, 13])
    angle_avg_rng = np.random.default_rng([seed, 14])
    d = "ut.dataset."
    shifted = condition == "shifted"
    temp_rng = get(cfg, d + ("shifted_temp_range_c" if shifted else "train_temp_range_c"))
    coup_rng = get(cfg, d + ("shifted_coupling_range" if shifted else "train_coupling_range"))
    noise_scale = get(cfg, d + "shifted_noise_scale") if shifted else 1.0
    angles = get(cfg, "ut.angle_beam_angles_deg")
    meas_err = get(cfg, d + ("shifted_temp_meas_error_c" if shifted else "train_temp_meas_error_c"))
    err_rng = np.random.default_rng([seed, 11])  # own stream: other draws stay unchanged
    wr = get(cfg, d + "wall_range_mm")
    n_s = int(get(cfg, "ut.n_samples"))
    straight = np.zeros((n, n_s), np.float32)
    angle = np.zeros((n, n_s), np.float32)
    rows = []
    for i in range(n):
        wall = rng.uniform(*wr)
        pit_depth = pit_frac = 0.0
        if rng.random() < get(cfg, d + "pit_prob"):
            lo_f, hi_f = get(cfg, d + "pit_depth_frac_range")
            pit_depth = wall * min(rng.uniform(lo_f, hi_f), _MAX_PIT_FRAC)
            pit_frac = rng.uniform(*get(cfg, d + "pit_fraction_range"))
        crack_h = 0.0
        if rng.random() < get(cfg, d + "crack_prob"):
            crack_h = wall * rng.uniform(*get(cfg, d + "crack_height_frac_range"))
        temp = rng.uniform(*temp_rng)
        temp_meas = temp + meas_err * err_rng.standard_normal()
        coup = rng.uniform(*coup_rng)
        ang = float(angles[rng.integers(len(angles))])
        straight[i] = simulate_straight(cfg, rng, wall, pit_depth, pit_frac, temp, coup,
                                        noise_scale, n_avg, avg_rng)
        angle[i] = simulate_angle(cfg, rng, wall, crack_h, ang, temp, coup, noise_scale,
                                  angle_n_avg, angle_avg_rng)
        rows.append({"wall_mm": wall, "pit_depth_mm": pit_depth, "pit_fraction": pit_frac,
                     "t_min_mm": wall - pit_depth, "crack": crack_h > 0,
                     "crack_height_mm": crack_h, "angle_deg": ang, "temp_c": temp,
                     "temp_meas_c": temp_meas,
                     "coupling": coup, "noise_scale": noise_scale, "n_avg": n_avg,
                     "angle_n_avg": angle_n_avg, "condition": condition})
    return straight, angle, pd.DataFrame(rows)


def save_dataset(out_dir, straight, angle, labels) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "ut_straight.npz", signals=straight)
    np.savez_compressed(out / "ut_angle.npz", signals=angle)
    labels.to_csv(out / "ut_labels.csv", index=False)


def analysis_temps(cfg, labels) -> np.ndarray:
    """Temperature [C] the analysis software uses for velocity correction.

    `ut.temp_compensation` = "measured": the (noisy) measured temperature `temp_meas_c`
    (true temperature when the label table has no such column); "none": assume 20 C, i.e.
    no correction (shows the cost of ignoring a hot pipe).
    """
    mode = get(cfg, "ut.temp_compensation")
    if mode == "none":
        return np.full(len(labels), 20.0)
    if mode != "measured":
        raise ValueError("ut.temp_compensation must be 'measured' or 'none'")
    col = "temp_meas_c" if "temp_meas_c" in labels.columns else "temp_c"
    return labels[col].to_numpy(float)


def baseline(cfg, straight, angle, labels) -> dict:
    """Rule-based baseline: thickness MAE, min-thickness MAE, crack POD / false alarms.

    Velocity correction uses the measured temperature (see `analysis_temps`), not the truth.
    """
    temps = analysis_temps(cfg, labels)
    rows = list(labels.itertuples())
    th = np.array([estimate_thickness(cfg, s, t) for s, t in zip(straight, temps)])
    tm = np.array([min_thickness(cfg, s, t) for s, t in zip(straight, temps)])
    det = np.array([detect_crack(cfg, s, r.wall_mm, r.angle_deg, t)["found"]
                    for s, r, t in zip(angle, rows, temps)])
    crack = labels["crack"].to_numpy(bool)
    err_th = np.abs(th - labels["wall_mm"].to_numpy())
    valid_th = np.isfinite(err_th)
    n_valid = int(valid_th.sum())
    fail_rate = float(1.0 - (n_valid / len(th))) if len(th) > 0 else float("nan")
    mae_th = float(np.mean(err_th[valid_th])) if n_valid > 0 else float("nan")
    err_tm = np.abs(tm - labels["t_min_mm"].to_numpy())
    valid_tm = np.isfinite(err_tm)
    mae_tm = float(np.mean(err_tm[valid_tm])) if valid_tm.any() else float("nan")
    return {
        "thickness_mae_valid_mm": mae_th,
        "thickness_n_valid": n_valid,
        "thickness_fail_rate": fail_rate,
        "min_thickness_mae_valid_mm": mae_tm,
        "crack_detection_rate": float(det[crack].mean()) if crack.any() else float("nan"),
        "false_alarm_rate": float(det[~crack].mean()) if (~crack).any() else float("nan"),
    }
