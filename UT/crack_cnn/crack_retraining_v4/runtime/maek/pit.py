"""Internal-pit detection by straight-beam UT (numpy only).

Methods (compared as an ablation in `maek.evaluate.pit_ablation`; `METHODS`):

- baseline  `ut.min_thickness` (earliest envelope crossing of max(15 % of max, 6 x MAD)).
- mf        the same rule on the matched-filtered trace.
- cfar      back-wall echo subtracted + CFAR threshold, raw envelope (no matched filter).
- mf_cfar   matched filter + back-wall subtraction + CFAR threshold (`detect_rule`).
- rel_amp   coupling-normalised rule: pit echo >= `ut.pit.rel_amp_min` x first back-wall echo.
- shadow    back-wall drop relative to the front-wall echo (simulator-only coupling reference).
- learned   tiny MLP on the matched-filter / CFAR / coupling-normalised features, trained only
            on domain-randomised data (`ut.pit.dr_*`), threshold calibrated per n_avg and
            SNR band on pit-free DR data (default, `ut.pit.method`; weights shipped in
            `maek/pit_model.json`, rebuilt by `python -m maek.pit --write`).
- learned_shadow  the same plus the simulator-only shadow feature.

Coherent averaging of N shots is an acquisition setting (`ut.n_avg`,
`ut.simulate_straight(..., n_avg=N)`), so every method can run on averaged A-scans.

Matched filter: correlate with the known probe pulse and take the analytic signal. An echo
of amplitude a at tau gives z(tau) ~= a (the maximum-likelihood amplitude), and white
electronic noise drops by sqrt(pulse energy) ~ 2.7x. Grain backscatter lies in the probe band
and is not reduced by the matched filter, nor by averaging (it is fixed under the probe).

Back-wall echo time: echo-train spacing (`ut.wall_echo_lag`, robust to pits). Its echo is
removed with the known response R and every earlier sample is tested with the conditional
statistic |z(t) - R(t - tw) z(tw)| / (sigma sqrt(1 - |R|^2)), which stays ~Rayleigh up to
the back-wall echo, so shallow pits that overlap it can still be found. sigma comes from
noise-only gates (before the front-wall echo, end of the trace), so the threshold follows
noise and coupling (CFAR). Pit depth = (tw - t_pit) v / 2 from the earliest echo above it.
"""

from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path

import numpy as np

from maek import ut
from maek.params import get

METHODS = ("baseline", "mf", "cfar", "mf_cfar", "rel_amp", "shadow", "learned",
           "learned_shadow")
MODEL_PATH = Path(__file__).resolve().parent / "pit_model.json"
_LN2 = np.sqrt(2 * np.log(2))  # median of a unit Rayleigh variable
_TAIL_FRAC = 1 / 4  # late noise gate: this fraction of the trace end


def _q(cfg, k):
    return get(cfg, f"ut.pit.{k}")


def _p_cached(cfg):
    return ut._p(cfg)


# ---------------------------------------------------------------- matched filter
@functools.lru_cache(maxsize=8)
def _kernel_fft(n: int, fs: float, f0: float, sigma: float) -> np.ndarray:
    """Real spectrum of the (even) probe pulse placed circularly at t = 0, unit energy gain."""
    i = np.arange(n)
    t = np.where(i < n // 2, i, i - n) / fs
    k = np.exp(-0.5 * (t / sigma) ** 2) * np.cos(2 * np.pi * f0 * t)
    k[np.abs(t) > 6 * sigma] = 0.0
    return np.fft.fft(k).real / np.sum(k**2)


def _onesided(n: int) -> np.ndarray:
    h = np.zeros(n)
    h[0] = 1.0
    if n % 2 == 0:
        h[n // 2] = 1.0
        h[1:n // 2] = 2.0
    else:
        h[1:(n + 1) // 2] = 2.0
    return h


def analytic(cfg, signal, matched=True) -> np.ndarray:
    """Analytic signal of the A-scan, optionally after the matched filter (complex array).

    With `matched`, an echo a * pulse(t - tau) gives |z(tau)| ~= a (normalised by the pulse
    energy), so amplitudes stay comparable with the raw envelope.
    """
    p = ut._p(cfg)
    x = np.asarray(signal, dtype=float)
    n = len(x)
    X = np.fft.fft(x)
    if matched:
        X = X * _kernel_fft(n, p["fs"], p["f0"], p["sigma"])
    return np.fft.ifft(X * _onesided(n))


def echo_response(cfg, u_s, matched=True) -> np.ndarray:
    """Normalised analytic response R(u) of one echo, u = t - tau in seconds (R(0) = 1).

    Pulse: exp(-u^2 / 2 s^2) e^{i w u}; after the matched filter the envelope widens to
    exp(-u^2 / 4 s^2) (autocorrelation of a Gaussian).
    """
    p = ut._p(cfg)
    s2 = (4 if matched else 2) * p["sigma"] ** 2
    u = np.asarray(u_s, float)
    return np.exp(-u**2 / s2) * np.exp(2j * np.pi * p["f0"] * u)


def interp(cfg, z, t_s) -> complex:
    """Complex value of z at a fractional time (linear interpolation at baseband)."""
    p = ut._p(cfg)
    w = 2 * np.pi * p["f0"]
    x = t_s * p["fs"]
    i = int(np.floor(x))
    if i < 0 or i + 1 >= len(z):
        return 0j
    f = x - i
    b0 = z[i] * np.exp(-1j * w * i / p["fs"])
    b1 = z[i + 1] * np.exp(-1j * w * (i + 1) / p["fs"])
    return complex(((1 - f) * b0 + f * b1) * np.exp(1j * w * t_s))


# ---------------------------------------------------------------- noise floor (CFAR)
def noise_sigma(cfg, z, wall_mm=None, temp_c=20.0, matched=True) -> float:
    """Robust per-component noise sigma of z from noise-only reference cells (CFAR).

    Reference gate: the last 1/4 of the trace after ring-down, with back-wall echoes still
    above 0.5 % of the first one masked. It holds the same noise as the pit window
    (electronic noise + grain backscatter). The gate before the front-wall echo has no grain
    noise and only ~30 samples, so it is used only if the late gate is fully masked.
    sigma = median(|z|) / sqrt(2 ln 2) (Rayleigh envelope).
    """
    p = _p_cached(cfg)
    n = len(z)
    half = (np.sqrt(2) if matched else 1.0) * p["sigma"] * p["fs"]
    guard = int(np.ceil(6 * half))
    i0 = int(p["t0"] * p["fs"])
    tail = np.arange(n - int(n * _TAIL_FRAC), n - guard)
    if wall_mm is not None and wall_mm > 0:
        T = 2 * wall_mm * 1e-3 / ut.velocity_long(cfg, temp_c) * p["fs"]
        k = np.arange(1, int(n / T) + 2)
        rel = get(cfg, "ut.backwall_decay") ** (k - 1) * ut._atten(cfg, 2 * (k - 1) * wall_mm)
        echoes = i0 + k[rel > 0.005] * T
        if len(echoes):
            d = np.abs(tail[:, None] - echoes[None, :]).min(axis=1)
            tail = tail[d > 3 * half]
    if len(tail) < 64:
        tail = np.concatenate([np.arange(0, max(i0 - guard, 1)), tail])
    return float(np.median(np.abs(z[tail])) / _LN2) if len(tail) >= 16 else float("nan")


def cfar_k(cfg, n_cells: float, margin=None) -> float:
    """Threshold multiple of sigma for a design false-alarm probability per A-scan.

    Rayleigh envelope: P(|z| > k sigma) = exp(-k^2/2) per independent cell, so
    k = sqrt(2 ln(n_cells / Pfa)), plus a margin for the error of the sigma estimate
    (`ut.pit.cfar_k_margin` unless given).
    """
    pfa = _q(cfg, "cfar_pfa")
    margin = _q(cfg, "cfar_k_margin") if margin is None else margin
    return float(np.sqrt(2 * np.log(max(n_cells, 1.0) / pfa)) + margin)


# ---------------------------------------------------------------- echo analysis
def analyse(cfg, signal, wall_nominal_mm, temp_c=20.0, matched=True) -> dict:
    """Locate the back-wall echo, subtract it and scan earlier times for pit echoes.

    Returns the quantities used by the rule detector and the learned classifier:
    `stat` (CFAR statistic: pit-echo amplitude / noise sigma for every sample of the pit
    window), `stat2` (same at the second echo of a pit train, t0 + 2 (t - t0)), the echo
    times / amplitudes and the window length.
    """
    p = _p_cached(cfg)
    fs, t0 = p["fs"], p["t0"]
    x = np.asarray(signal, dtype=float)
    n = len(x)
    z = analytic(cfg, x, matched)
    v = ut.velocity_long(cfg, temp_c)
    # back-wall time: echo-train spacing (robust to pits), checked against the nominal wall
    lag = ut.wall_echo_lag(cfg, z.real if matched else x, temp_c)
    w_meas = lag / fs * v / 2 * 1e3
    if abs(w_meas - wall_nominal_mm) <= _q(cfg, "wall_tol_frac") * wall_nominal_mm:
        tw = t0 + lag / fs
    else:  # spacing picked a harmonic: fall back to the nominal wall
        tw = t0 + 2 * wall_nominal_mm * 1e-3 / v
    sigma = noise_sigma(cfg, z, wall_nominal_mm, temp_c, matched)
    z_if = interp(cfg, z, t0)
    a_w = interp(cfg, z, tw)
    t2w = t0 + 2 * (tw - t0)
    i_dead = int(np.ceil((t0 + _q(cfg, "dead_zone_us") * 1e-6) * fs))
    dmin = 2 * _q(cfg, "min_depth_mm") * 1e-3 / v
    i_end = int(np.floor((tw - dmin) * fs))
    out = {"tw": tw, "wall_meas_mm": float(w_meas), "wall_nominal_mm": float(wall_nominal_mm),
           "sigma": sigma, "a_if": abs(z_if), "a_w": abs(a_w),
           "a_w2": abs(interp(cfg, z, t2w)) if t2w < (n - 1) / fs else 0.0,
           "v": v, "n_win": max(i_end - i_dead + 1, 0), "matched": matched}
    if i_end < i_dead or not sigma > 0:
        out.update(stat=np.zeros(0), stat2=np.zeros(0), amp=np.zeros(0), t=np.zeros(0))
        return out
    i = np.arange(i_dead, i_end + 1)
    t = i / fs
    R_w = echo_response(cfg, t - tw, matched)
    R_if = echo_response(cfg, t - t0, matched)
    res = z[i] - R_w * a_w - R_if * z_if
    # noise of the subtracted estimate: matched -> conditional variance 1 - |R|^2,
    # raw (white) -> the subtracted sample adds its own noise, 1 + |R|^2
    var = (1 - np.abs(R_w) ** 2) if matched else (1 + np.abs(R_w) ** 2)
    amp = np.abs(res) / np.sqrt(np.maximum(var, 1e-3))  # amplitude of an echo at t
    # second echo of a pit train; masked where it would sit on a back-wall echo
    i0 = round(t0 * fs)
    i2 = i0 + 2 * (i - i0)
    half = (np.sqrt(2) if matched else 1.0) * p["sigma"] * fs
    T = (tw - t0) * fs
    near_wall = np.abs((i2 - i0) / T - np.round((i2 - i0) / T)) * T < 4 * half
    ok = (i2 < n) & ~(near_wall & (np.round((i2 - i0) / T) >= 1))
    stat2 = np.zeros(len(i))
    stat2[ok] = np.abs(z[i2[ok]]) / sigma
    out.update(stat=amp / sigma, stat2=stat2, amp=amp, t=t)
    return out


def _corr_cells(cfg, n_win, matched=True) -> float:
    """Number of roughly independent envelope cells in a window of n_win samples."""
    p = _p_cached(cfg)
    width = 2 * np.sqrt(np.pi) * (np.sqrt(2) if matched else 1.0) * p["sigma"] * p["fs"]
    return n_win / width + 1.0


def _depth_at(a, j) -> float:
    return float((a["tw"] - a["t"][j]) * a["v"] / 2 * 1e3)


def _earliest_peak(cfg, st, thr) -> int | None:
    above = np.nonzero(st > thr)[0]
    if len(above) == 0:
        return None
    p = _p_cached(cfg)
    j = above[0]
    return j + int(np.argmax(st[j:j + int(3 * p["sigma"] * p["fs"])]))  # its local peak


def detect_rule(cfg, signal, wall_nominal_mm, temp_c=20.0, matched=True, a=None) -> dict:
    """Rule detector: a pit echo above the CFAR threshold anywhere in the pit window.

    score = max(stat) / threshold (> 1 means found); depth from the earliest echo above it.
    """
    a = a or analyse(cfg, signal, wall_nominal_mm, temp_c, matched)
    st = a["stat"]
    if len(st) == 0:
        return {"found": False, "score": 0.0, "depth_est_mm": 0.0}
    thr = cfar_k(cfg, _corr_cells(cfg, a["n_win"], matched))
    j = _earliest_peak(cfg, st, thr)
    score = float(st.max() / thr)
    if j is None:
        return {"found": False, "score": score, "depth_est_mm": 0.0}
    return {"found": True, "score": score, "depth_est_mm": _depth_at(a, j)}


# ---------------------------------------------------------------- other rules
def detect_baseline(cfg, signal, wall_nominal_mm, temp_c=20.0, matched=False) -> dict:
    """Old rule: `ut.min_thickness` thinner than nominal by `ut.pit.min_depth_mm`."""
    x = analytic(cfg, signal).real if matched else signal
    tm = ut.min_thickness(cfg, x, temp_c)
    depth = wall_nominal_mm - tm if np.isfinite(tm) else 0.0
    found = bool(np.isfinite(tm) and depth >= _q(cfg, "min_depth_mm"))
    return {"found": found, "score": float(depth / _q(cfg, "min_depth_mm")),
            "depth_est_mm": float(depth) if found else 0.0}


def detect_rel_amp(cfg, a) -> dict:
    """Coupling-normalised fixed rule: an echo >= rel_amp_min x the first back-wall echo.

    The ratio does not depend on coupling, but its noise does, so this rule has no
    noise-adaptive threshold (shown in the ablation for that reason).
    """
    if len(a["amp"]) == 0 or not a["a_w"] > 0:
        return {"found": False, "score": 0.0, "depth_est_mm": 0.0}
    rel = a["amp"] / a["a_w"]
    thr = _q(cfg, "rel_amp_min")
    j = _earliest_peak(cfg, rel, thr)
    score = float(rel.max() / thr)
    if j is None:
        return {"found": False, "score": score, "depth_est_mm": 0.0}
    return {"found": True, "score": score, "depth_est_mm": _depth_at(a, j)}


def shadow_ratio(cfg, a) -> float:
    """(back-wall / front-wall amplitude) / its pit-free value; ~ 1 - pit area fraction."""
    w = a["wall_nominal_mm"]
    exp_ratio = get(cfg, "ut.backwall_amp") * ut._atten(cfg, 2 * w) / get(cfg, "ut.interface_amp")
    return float(a["a_w"] / max(a["a_if"], 1e-9) / exp_ratio)


def detect_shadow(cfg, a) -> dict:
    """Back-wall 'shadow': the first back-wall echo is weaker than expected under a pit.

    The front-wall (interface) echo is the coupling reference. In this simulator coupling
    scales both echoes alike; with a real couplant layer it does not, so treat this cue as a
    simulator upper bound. z = drop / its noise (both echo amplitudes carry sigma).
    """
    r = shadow_ratio(cfg, a)
    sd = r * np.hypot(a["sigma"] / max(a["a_w"], 1e-9), a["sigma"] / max(a["a_if"], 1e-9))
    zs = (1 - r) / max(sd, 1e-9)
    found = bool((1 - r) >= _q(cfg, "shadow_min_drop") and zs >= _q(cfg, "shadow_z"))
    depth = 0.0
    if found and len(a["stat"]):
        depth = _depth_at(a, int(np.argmax(a["stat"])))  # best guess: strongest candidate
    return {"found": found, "score": float(zs / _q(cfg, "shadow_z")), "depth_est_mm": depth}


# ---------------------------------------------------------------- learned classifier
FEATURES = ("snr_max", "snr_train", "rel_amp", "bw_snr", "train_ratio", "excess", "depth_frac")
SHADOW = "shadow"


def features(cfg, a, shadow=False) -> np.ndarray:
    """Engineered features of one analysed A-scan (see FEATURES; + `shadow` if asked).

    snr_max      max CFAR statistic in the pit window (matched filter + CFAR)
    snr_train    max sqrt(stat^2 + stat2^2): first + second echo of a pit train
    rel_amp      log(pit-echo amplitude / first back-wall amplitude) (coupling-normalised)
    bw_snr       log(back-wall amplitude / sigma)
    train_ratio  log((2nd / 1st back-wall) / expected decay): echo-train attenuation change
    excess       fraction of window samples above 3 sigma minus its Rayleigh expectation
    depth_frac   depth of the strongest candidate / nominal wall
    shadow       log((back-wall / front-wall) / expected): back-wall drop under a pit. Uses
                 the front-wall echo as a coupling reference; valid in this simulator, where
                 coupling scales both echoes alike (not with a real couplant layer).
    """
    w = a["wall_nominal_mm"]
    att = get(cfg, "ut.backwall_decay") * ut._atten(cfg, 2 * w)
    tiny = 1e-6
    st = a["stat"]
    if len(st):
        j = int(np.argmax(st))
        f = [np.log1p(st[j]), np.log1p(float(np.sqrt(st**2 + a["stat2"] ** 2).max())),
             np.log(max(a["amp"][j], tiny) / max(a["a_w"], tiny)),
             float(np.mean(st > 3.0) - np.exp(-4.5)), _depth_at(a, j) / w]
    else:
        f = [0.0, 0.0, np.log(tiny), 0.0, 0.0]
    bw = np.log(max(a["a_w"], tiny) / max(a["sigma"], tiny))
    tr = np.log(max(a["a_w2"], tiny) / max(a["a_w"], tiny) / att)
    out = [f[0], f[1], f[2], bw, tr, f[3], f[4]]
    if shadow:
        exp_ratio = get(cfg, "ut.backwall_amp") * ut._atten(cfg, 2 * w) / get(cfg, "ut.interface_amp")
        out.append(np.log(max(a["a_w"], tiny) / max(a["a_if"], tiny) / exp_ratio))
    return np.clip(np.asarray(out, float), -20, 50)


def _standardise(X):
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    return mu, sd


def fit_mlp(X, y, seed=0, hidden=16, l2=1e-3, iters=1500, lr=0.01) -> dict:
    """Tiny MLP (standardised inputs -> `hidden` tanh units -> sigmoid), full-batch Adam.

    Binary cross-entropy + L2 weight decay. Deterministic for a given seed and data.
    hidden=0 gives plain logistic regression.
    """
    X = np.asarray(X, float)
    y = np.asarray(y, float)
    mu, sd = _standardise(X)
    Z = (X - mu) / sd
    rng = np.random.default_rng([seed, 7])
    d = X.shape[1]
    w = {"b2": np.zeros(1)}
    if hidden:
        w.update(W1=rng.standard_normal((d, hidden)) / np.sqrt(d), b1=np.zeros(hidden),
                 W2=rng.standard_normal((hidden, 1)) / np.sqrt(hidden))
    else:
        w["W2"] = np.zeros((d, 1))
    m = {k: np.zeros_like(v) for k, v in w.items()}
    v2 = {k: np.zeros_like(v) for k, v in w.items()}
    b1m, b2m, eps = 0.9, 0.999, 1e-8
    n = len(Z)
    for it in range(1, int(iters) + 1):
        h = np.tanh(Z @ w["W1"] + w["b1"]) if hidden else Z
        logit = (h @ w["W2"])[:, 0] + w["b2"][0]
        pr = 1 / (1 + np.exp(-np.clip(logit, -35, 35)))
        g = ((pr - y) / n)[:, None]
        grads = {"W2": h.T @ g + l2 * w["W2"], "b2": g.sum(axis=0)}
        if hidden:
            gh = (g @ w["W2"].T) * (1 - h**2)
            grads["W1"] = Z.T @ gh + l2 * w["W1"]
            grads["b1"] = gh.sum(axis=0)
        for k, gk in grads.items():
            m[k] = b1m * m[k] + (1 - b1m) * gk
            v2[k] = b2m * v2[k] + (1 - b2m) * gk**2
            w[k] = w[k] - lr * (m[k] / (1 - b1m**it)) / (np.sqrt(v2[k] / (1 - b2m**it)) + eps)
    return {"mean": mu.tolist(), "std": sd.tolist(), "hidden": int(hidden),
            **{k: v.tolist() for k, v in w.items()}}


def predict_proba(model, X) -> np.ndarray:
    """Pit probability of feature rows X under a `fit_mlp` model."""
    Z = (np.atleast_2d(np.asarray(X, float)) - np.asarray(model["mean"])) / np.asarray(model["std"])
    h = np.tanh(Z @ np.asarray(model["W1"]) + np.asarray(model["b1"])) if model["hidden"] else Z
    logit = (h @ np.asarray(model["W2"]))[:, 0] + model["b2"][0]
    return 1 / (1 + np.exp(-np.clip(logit, -35, 35)))


_MODEL_VERSION = 1  # bump when features / training change, so shipped weights go stale
_PHYSICS = ("v_long", "temp_coeff_mps_per_c", "probe_freq_mhz", "sampling_mhz", "noise_std",
            "grain_noise_std", "n_samples", "interface_delay_us", "pulse_sigma_us",
            "interface_amp", "backwall_amp", "backwall_decay", "atten_db_per_mm")
_RULE_ONLY = ("method", "cfar_pfa", "cfar_k_margin", "gate_k_margin", "rel_amp_min",
              "shadow_min_drop", "shadow_z")


def _fingerprint(cfg) -> str:
    """Hash of every parameter that changes the training data, features or calibration."""
    u = cfg["ut"]
    keep = {"version": _MODEL_VERSION, **{k: u[k] for k in _PHYSICS},
            "pit": {k: v for k, v in u["pit"].items() if k not in _RULE_ONLY},
            "dataset": {k: u["dataset"][k] for k in
                        ("wall_range_mm", "pit_depth_frac_range", "pit_fraction_range")}}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _dataset_features(cfg, signals, labels):
    return np.array([features(cfg, analyse(cfg, s, w, t), shadow=True)
                     for s, w, t in zip(signals, labels["wall_mm"], labels["temp_meas_c"])])


@functools.lru_cache(maxsize=4)
def _dr_features(cfg_json: str, seed: int, n_train: int, n_calib: int):
    """Features (all columns, incl. shadow) of the DR training and pit-free calibration sets."""
    cfg = json.loads(cfg_json)
    sig, lab = make_dr_dataset(cfg, n_train, seed)
    X = _dataset_features(cfg, sig, lab)
    sig0, lab0 = make_dr_dataset(cfg, n_calib, seed + 1, pit_prob=0.0)
    return (X, lab["pit_depth_mm"].to_numpy() > 0, _dataset_features(cfg, sig0, lab0),
            lab0["n_avg"].to_numpy())


def train_classifier(cfg, shadow=False, seed=None, n_train=None, n_calib=None) -> dict:
    """Fit the MLP on domain-randomised data and calibrate its threshold (no test data).

    Threshold: the pit-free calibration set (own seed) is split by n_avg (known at
    acquisition) and, inside each, into `calib_strata` equal-count bands of back-wall SNR;
    each stratum gets the (1 - target_fa) quantile of its scores, so the false-alarm rate is
    held in every noise / coupling / averaging regime, not only on average (one global
    threshold let false alarms pile up at low SNR and on averaged, grain-limited scans).
    """
    seed = int(_q(cfg, "dr_seed") if seed is None else seed)
    n_train = int(n_train or _q(cfg, "dr_n_train"))
    n_calib = int(n_calib or _q(cfg, "dr_n_calib"))
    X, y, X0, navg0 = _dr_features(json.dumps(cfg, sort_keys=True, default=str), seed,
                                   n_train, n_calib)
    cols = slice(None) if shadow else slice(0, len(FEATURES))
    X, X0 = X[:, cols], X0[:, cols]
    model = fit_mlp(X, y, seed, _q(cfg, "mlp_hidden"), _q(cfg, "mlp_l2"), _q(cfg, "mlp_iters"))
    p0 = predict_proba(model, X0)
    k = int(_q(cfg, "calib_strata"))
    q = 1 - _q(cfg, "target_fa")
    choices = sorted({int(v) for v in navg0})
    edges, thr = [], []
    for na in choices:
        sel = navg0 == na
        bw = X0[sel, FEATURES.index("bw_snr")]
        e = np.quantile(bw, np.linspace(0, 1, k + 1)[1:-1]) if k > 1 else np.zeros(0)
        band = np.digitize(bw, e)
        edges.append(e.tolist())
        thr.append([float(np.quantile(p0[sel][band == b], q)) if (band == b).any() else 0.5
                    for b in range(k)])
    model.update(shadow=bool(shadow), n_avg_choices=choices, edges=edges, thresholds=thr,
                 seed=seed, n_train=n_train, n_calib=n_calib, fingerprint=_fingerprint(cfg))
    return model


_MODELS: dict = {}


def load_shipped(path=MODEL_PATH) -> dict:
    """Pre-trained models shipped with the package, {name: model} ({} if missing)."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def get_model(cfg, shadow=False) -> dict:
    """Classifier for this configuration.

    Uses the shipped weights (`maek/pit_model.json`, written by `python -m maek.pit
    --write`) when they were trained with the same parameters (fingerprint); otherwise trains
    once per process on domain-randomised data (deterministic, ~1 min).
    """
    key = (_fingerprint(cfg), bool(shadow))
    if key not in _MODELS:
        shipped = load_shipped().get("learned_shadow" if shadow else "learned")
        if shipped and shipped.get("fingerprint") == key[0]:
            _MODELS[key] = shipped
        else:
            _MODELS[key] = train_classifier(cfg, shadow)
    return _MODELS[key]


def detect_learned(cfg, a, model, n_avg=1, gate=True) -> dict:
    """Learned classifier, accepted only where an echo also passes a CFAR gate.

    Threshold: the one calibrated for the nearest n_avg and back-wall SNR band. Gate: the
    strongest pit-window echo must exceed the CFAR design threshold with margin
    `ut.pit.gate_k_margin` (default 0: the rule threshold without its sigma-estimation
    margin). The gate keeps false alarms bounded by the CFAR design when field conditions
    fall outside the DR training ranges, where the classifier alone is not calibrated.
    """
    f = features(cfg, a, model["shadow"])
    pr = float(predict_proba(model, f)[0])
    choices = np.asarray(model["n_avg_choices"])
    i = int(np.argmin(np.abs(np.log(choices) - np.log(max(int(n_avg), 1)))))
    band = int(np.digitize(f[FEATURES.index("bw_snr")], model["edges"][i]))
    thr = model["thresholds"][i][band]
    st = a["stat"]
    k = cfar_k(cfg, _corr_cells(cfg, a["n_win"]), _q(cfg, "gate_k_margin"))
    passed = bool(len(st)) and (not gate or float(st.max()) > k)
    found = bool(pr > thr and passed)
    depth = 0.0
    if found:  # depth: earliest echo above the rule threshold, else the strongest echo
        j = _earliest_peak(cfg, st, cfar_k(cfg, _corr_cells(cfg, a["n_win"])))
        depth = _depth_at(a, j if j is not None else int(np.argmax(st)))
    return {"found": found, "score": pr / max(thr, 1e-9), "depth_est_mm": depth}


# ---------------------------------------------------------------- public entry point
def detect_pit(cfg, signal, wall_nominal_mm, temp_c=20.0, method=None, model=None,
               a=None, n_avg=None) -> dict:
    """Detect an internal pit in a straight-beam A-scan.

    Returns {found, score (> 1 means found, comparable within a method), depth_est_mm}.
    `method` defaults to `ut.pit.method` (see METHODS); `temp_c` is the temperature used for
    velocity correction (measured, not true). `a` reuses an `analyse` result (matched);
    `n_avg` (default `ut.n_avg`) is the number of averaged shots of `signal` (learned only).
    """
    method = method or _q(cfg, "method")
    if method not in METHODS:
        raise ValueError(f"unknown pit method {method!r}; choose from {METHODS}")
    if method in ("baseline", "mf"):
        return detect_baseline(cfg, signal, wall_nominal_mm, temp_c, matched=method == "mf")
    if method == "cfar":
        return detect_rule(cfg, signal, wall_nominal_mm, temp_c, matched=False)
    a = a or analyse(cfg, signal, wall_nominal_mm, temp_c)
    if method == "mf_cfar":
        return detect_rule(cfg, signal, wall_nominal_mm, temp_c, a=a)
    if method == "rel_amp":
        return detect_rel_amp(cfg, a)
    if method == "shadow":
        return detect_shadow(cfg, a)
    model = model or get_model(cfg, shadow=method == "learned_shadow")
    return detect_learned(cfg, a, model, get(cfg, "ut.n_avg") if n_avg is None else n_avg)


# ---------------------------------------------------------------- domain-randomised data
def make_dr_dataset(cfg, n, seed, pit_prob=None):
    """Domain-randomised straight-beam A-scans for training / threshold calibration.

    Geometry follows `ut.dataset.*` (wall, pit depth / area fraction); acquisition
    conditions are drawn from the wider `ut.pit.dr_*` ranges (noise scale log-uniform,
    coupling, temperature, temperature-measurement error, n_avg). Uses its own seed, never
    the train/shifted evaluation sets. Returns (signals [n, N] float32, labels DataFrame).
    """
    import pandas as pd

    pit_prob = _q(cfg, "dr_pit_prob") if pit_prob is None else pit_prob
    rng = np.random.default_rng([seed, 101])
    avg_rng = np.random.default_rng([seed, 102])
    d = "ut.dataset."
    wr = get(cfg, d + "wall_range_mm")
    nlo, nhi = _q(cfg, "dr_noise_scale_range")
    navg = _q(cfg, "dr_n_avg_choices")
    rows, sig = [], np.zeros((n, int(get(cfg, "ut.n_samples"))), np.float32)
    for i in range(n):
        wall = rng.uniform(*wr)
        depth = frac = 0.0
        if rng.random() < pit_prob:
            depth = wall * min(rng.uniform(*get(cfg, d + "pit_depth_frac_range")), ut._MAX_PIT_FRAC)
            frac = rng.uniform(*get(cfg, d + "pit_fraction_range"))
        ns = float(np.exp(rng.uniform(np.log(nlo), np.log(nhi))))
        coup = rng.uniform(*_q(cfg, "dr_coupling_range"))
        temp = rng.uniform(*_q(cfg, "dr_temp_range_c"))
        err = rng.uniform(0, _q(cfg, "dr_temp_meas_error_max_c"))
        temp_meas = temp + err * rng.standard_normal()
        na = int(navg[rng.integers(len(navg))])
        sig[i] = ut.simulate_straight(cfg, rng, wall, depth, frac, temp, coup, ns, na, avg_rng)
        rows.append({"wall_mm": wall, "pit_depth_mm": depth, "pit_fraction": frac,
                     "noise_scale": ns, "coupling": coup, "temp_c": temp,
                     "temp_meas_c": temp_meas, "n_avg": na})
    return sig, pd.DataFrame(rows)


def write_shipped(cfg, path=MODEL_PATH) -> dict:
    """Train the default (no-shadow) classifier for `cfg` and store it next to the code."""
    models = {"learned": train_classifier(cfg, shadow=False)}
    Path(path).write_text(json.dumps(models, indent=1) + "\n", encoding="utf-8")
    return models


if __name__ == "__main__":  # python -m maek.pit --write [--config path]
    import argparse

    from maek import params

    ap = argparse.ArgumentParser(description="train / store the learned pit classifier")
    ap.add_argument("--config", default=None)
    ap.add_argument("--write", action="store_true", help=f"write {MODEL_PATH.name}")
    args = ap.parse_args()
    c = params.load_config(args.config)
    params.validate(c)
    m = write_shipped(c) if args.write else {"learned": train_classifier(c)}
    print(json.dumps({k: {"fingerprint": v["fingerprint"], "thresholds": v["thresholds"]}
                      for k, v in m.items()}, indent=1))
