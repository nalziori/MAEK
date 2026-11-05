"""Extreme-value analysis (EVA) of internal pitting per corrosion circuit.

Instead of finding every pit, sample k scan windows per circuit, fit a Gumbel distribution to the
per-window maximum pit depths (ASTM G46 / Kowaka), extrapolate the maximum depth over the whole
wetted area and decide per circuit whether it must be repaired / fully inspected.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from maek import network, params

_EULER = 0.5772156649015329
_MODE_T = 1.0 / (1.0 - np.exp(-1.0))  # return period of the Gumbel mode


def circuits(cfg: dict, segments: pd.DataFrame) -> pd.DataFrame:
    """Group wet metal segments into corrosion circuits (eva.circuit_keys)."""
    g = lambda k: params.get(cfg, k)
    media = set(g("defects.internal_pitting.media"))
    keys = list(g("eva.circuit_keys"))
    band = g("eva.wetted_band_frac")
    s = segments[(segments["material"] != "pvc") & segments["medium"].isin(media)].copy()
    cols = ["circuit_id", "n_segments", "length_m", "id_mm", "wall_mm", "t_min_mm",
            "allowable_mm", "age_yr", "area_m2", *keys]
    if s.empty:
        return pd.DataFrame(columns=cols)
    s["decade"] = s["install_year"] // 10 * 10
    s["id_mm"] = s["od_mm"] - 2 * s["wall_mm"]
    s["age_yr"] = np.maximum(g("network.reference_year") - s["install_year"], 0)
    out = s.groupby(keys, sort=True).agg(
        n_segments=("segment_id", "size"), length_m=("length_m", "sum"), id_mm=("id_mm", "mean"),
        wall_mm=("wall_mm", "mean"), t_min_mm=("t_min_mm", "mean"), age_yr=("age_yr", "mean"),
    ).reset_index()
    out["allowable_mm"] = out["wall_mm"] - out["t_min_mm"]
    out["area_m2"] = np.pi * out["id_mm"] / 1000.0 * out["length_m"] * band
    out.insert(0, "circuit_id", ["|".join(str(v) for v in r) for r in out[keys].itertuples(
        index=False)])
    return out[cols]


def simulate_circuit(cfg: dict, circ, rng) -> tuple[np.ndarray, np.ndarray]:
    """Return (positions_m, depths_mm) of the pits of one circuit, sorted by position."""
    g = lambda k: params.get(cfg, k)
    lam = rng.lognormal(np.log(g("eva.pit_density_median_per_m2")), g("eva.pit_density_sigma_log"))
    n = rng.poisson(lam * float(circ["area_m2"]))
    rate = float(network._rate(cfg, rng))
    beta = (g("eva.depth_scale_factor") * rate * float(circ["age_yr"])
            * rng.uniform(*g("defects.exposure_frac_range")))
    depth = np.minimum(rng.exponential(max(beta, 1e-9), n), float(circ["wall_mm"]))
    pos = rng.uniform(0.0, float(circ["length_m"]), n)
    order = np.argsort(pos)
    return pos[order], depth[order]


def window_layout(cfg: dict, circ, k: int, rng=None):
    """Scan windows as (starts, length). Whole length is tiled if k * scan_length >= length."""
    L, w = float(circ["length_m"]), float(params.get(cfg, "eva.scan_length_m"))
    if k * w >= L:
        n = max(int(np.ceil(L / w)), 1)
        return np.arange(n) * w, w
    u = np.sort(rng.uniform(0.0, L - k * w, k))
    return u + np.arange(k) * w, w


def scanned_length(cfg: dict, circ, k: int) -> float:
    L, w = float(circ["length_m"]), float(params.get(cfg, "eva.scan_length_m"))
    n = max(int(np.ceil(L / w)), 1) if k * w >= L else k
    return min(n * w, L)


def scan_area(cfg: dict, circ, k: int) -> float:
    return float(np.pi * circ["id_mm"] / 1000.0 * scanned_length(cfg, circ, k)
                 * params.get(cfg, "eva.wetted_band_frac"))


def sample_maxima(cfg: dict, circ, pits, k: int, rng) -> np.ndarray:
    """Measured max depth per scan window (NaN where no pit reaches detect_min_mm)."""
    pos, depth = pits
    starts, w = window_layout(cfg, circ, k, rng)
    lo = np.searchsorted(pos, starts, "left")
    hi = np.searchsorted(pos, starts + w, "left")
    dmin, sd = params.get(cfg, "eva.detect_min_mm"), params.get(cfg, "eva.sizing_sd_mm")
    out = np.full(len(starts), np.nan)
    for i, (a, b) in enumerate(zip(lo, hi)):
        d = depth[a:b]
        d = d[d >= dmin]
        if d.size:
            out[i] = (d + rng.normal(0.0, sd, d.size)).max()
    return out


def _fit_batch(x: np.ndarray, max_iter: int = 500, tol: float = 1e-10):
    """Gumbel MLE for each row of x (B, m): fixed-point on sigma, then mu."""
    x = np.atleast_2d(np.asarray(x, float))
    c = x.mean(axis=1, keepdims=True)
    xs = x - c
    sig = np.maximum(xs.std(axis=1, ddof=0) * np.sqrt(6.0) / np.pi, 1e-9)
    for _ in range(max_iter):
        z = -xs / sig[:, None]
        z -= z.max(axis=1, keepdims=True)
        w = np.exp(z)
        new = np.maximum(-(xs * w).sum(axis=1) / w.sum(axis=1), 1e-9)  # mean(xs) == 0
        done = np.all(np.abs(new - sig) <= tol * np.maximum(sig, 1e-9))
        sig = new
        if done:
            break
    z = -xs / sig[:, None]
    zm = z.max(axis=1)
    lme = zm + np.log(np.exp(z - zm[:, None]).mean(axis=1))
    mu = -sig * lme + c[:, 0]
    return mu, sig


def gumbel_fit(x) -> tuple[float, float]:
    """MLE (mu, sigma) of a Gumbel (max) distribution."""
    mu, sig = _fit_batch(np.asarray(x, float)[None, :])
    return float(mu[0]), float(sig[0])


def return_level(mu, sigma, T):
    """Level exceeded once per T windows; floored at the mode (T < 1/(1-1/e))."""
    T = np.maximum(np.asarray(T, float), _MODE_T)
    return mu - sigma * np.log(-np.log(1.0 - 1.0 / T))


def predict_max(cfg: dict, maxima, area_total: float, area_scan: float, rng) -> dict:
    g = lambda k: params.get(cfg, k)
    maxima = np.asarray(maxima, float)
    vals = maxima[~np.isnan(maxima)]
    if vals.size < g("eva.min_maxima"):
        obs = float(vals.max()) if vals.size else 0.0
        # sizing-error margin on the observation; nothing below the detection limit can be excluded
        up = max(obs + g("eva.fallback_margin_sd") * g("eva.sizing_sd_mm"), g("eva.detect_min_mm"))
        return {"point": obs, "upper": up, "extrapolated": False}
    p = vals.size / maxima.size
    T = max(p * area_total / area_scan, 1.0)
    mu, sig = gumbel_fit(vals)
    point = float(return_level(mu, sig, T))
    B = int(g("eva.bootstrap"))
    u = rng.uniform(1e-12, 1.0, (B, vals.size))
    boot = mu - sig * np.log(-np.log(u))
    bm, bs = _fit_batch(boot)
    # predictive bootstrap: parameter uncertainty plus the sampling scatter of the realised max
    # (the max over T windows of a Gumbel(mu, s) is Gumbel(mu + s ln T, s))
    pred = bm + bs * np.log(max(T, 1.0)) - bs * np.log(-np.log(rng.uniform(1e-12, 1.0, B)))
    upper = float(np.quantile(pred, g("eva.upper_q")))
    return {"point": point, "upper": max(upper, point, float(vals.max())), "extrapolated": True}


def _ratio(num, den):
    return float(num / den) if den > 0 else np.nan


METRICS = ["n_circuits", "n_critical", "sensitivity", "false_alarm_rate", "coverage", "mae_mm",
           "direct_detection", "fallback_rate", "scans", "scanned_length_frac"]


def run(cfg: dict, seed: int, runs: int, total_km=None, k_values=None) -> pd.DataFrame:
    ks = list(k_values or params.get(cfg, "eva.k_values"))
    rows = []
    for i in range(runs):
        seg, _, _ = network.generate_network(cfg, seed + i, total_km=total_km)
        circ = circuits(cfg, seg)
        rng = np.random.default_rng([seed, i, 7])
        fields = [simulate_circuit(cfg, c, rng) for _, c in circ.iterrows()]
        tmax = np.array([f[1].max() if f[1].size else 0.0 for f in fields])
        has = np.array([f[1].size > 0 for f in fields])
        allow = circ["allowable_mm"].to_numpy()
        crit = tmax >= allow
        for k in ks:
            up, pt, ext, direct, scanned = [], [], [], [], 0.0
            for (_, c), pits in zip(circ.iterrows(), fields):
                m = sample_maxima(cfg, c, pits, k, rng)
                r = predict_max(cfg, m, c["area_m2"], scan_area(cfg, c, k), rng)
                up.append(r["upper"])
                pt.append(r["point"])
                ext.append(r["extrapolated"])
                direct.append(bool(np.any(m >= c["allowable_mm"])))
                scanned += scanned_length(cfg, c, k)
            up, pt, ext, direct = map(np.array, (up, pt, ext, direct))
            flag = up >= allow
            rows.append({
                "run": i, "k": k, "n_circuits": len(circ), "n_critical": int(crit.sum()),
                "sensitivity": _ratio((flag & crit).sum(), crit.sum()),
                "false_alarm_rate": _ratio((flag & ~crit).sum(), (~crit).sum()),
                "coverage": _ratio((has & (tmax <= up)).sum(), has.sum()),
                "mae_mm": float(np.abs(pt - tmax)[has].mean()) if has.any() else np.nan,
                "direct_detection": _ratio((direct & crit).sum(), crit.sum()),
                "fallback_rate": _ratio((~ext).sum(), len(circ)),
                "scans": k * len(circ),
                "scanned_length_frac": _ratio(scanned, circ["length_m"].sum()),
            })
    return pd.DataFrame(rows)


def summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for k, grp in df.groupby("k"):
        r = {"k": k}
        for m in METRICS:
            v = grp[m].to_numpy(float)
            ok = v[~np.isnan(v)]
            r[m] = float(ok.mean()) if ok.size else np.nan
            r[m + "_p05"] = float(np.quantile(ok, 0.05)) if ok.size else np.nan
            r[m + "_p95"] = float(np.quantile(ok, 0.95)) if ok.size else np.nan
        rows.append(r)
    return pd.DataFrame(rows)


LABELS = {"n_circuits": "회로 수", "n_critical": "위험 회로", "sensitivity": "회로 판정 민감도",
          "false_alarm_rate": "오경보율", "coverage": "최대 깊이 예측 포함률",
          "mae_mm": "예측 오차(mm)", "direct_detection": "직접 발견율",
          "fallback_rate": "대체 판정 비율", "scans": "스캔 수",
          "scanned_length_frac": "스캔 길이 비율"}


def to_markdown(summ: pd.DataFrame) -> str:
    head = "| 지표 | " + " | ".join(f"k={int(k)}" for k in summ["k"]) + " |"
    lines = [head, "|---|" + "---|" * len(summ)]
    for m, lab in LABELS.items():
        cells = [f"{r[m]:.3g} ({r[m + '_p05']:.3g}-{r[m + '_p95']:.3g})"
                 for _, r in summ.iterrows()]
        lines.append(f"| {lab} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
