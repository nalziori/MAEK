"""Synthetic radiometric IR images of insulated pipes + baseline detector + POD fitting.

Image = apparent temperature in C (float32), as read by a camera whose emissivity setting is
`eps_set`. Mask classes: 0 background/pipe, 1 wet_insulation, 2 insulation_damage, 3 steam_leak.
Pipe pixels follow the gray-body model of maek.thermal; the background is given directly in
apparent temperature (sky gradient + clutter).
"""

from __future__ import annotations

import json
import math
import time
import warnings
from pathlib import Path

import numpy as np

from maek import pod, thermal
from maek.camera.composite2d import (
    _blur,
    _interp_matrix,
    _noise,
    label_components,
    split_val,
    yolo_lines,
)

IR_CLASSES = {0: "background", 1: "wet_insulation", 2: "insulation_damage", 3: "steam_leak"}
KIND_CLASS = {"wet_insulation": 1, "tracer_leak": 1, "insulation_damage": 2, "steam_leak": 3}
HARD_NEGATIVES = ("reflection", "seam", "streak", "clamp", "hot_bg")
PNG_OFFSET_C, PNG_SCALE = 50.0, 100.0
CAM_MIN_C = -40.0   # lower end of the camera calibration range (negative radiance saturates)
_MEDIUMS = ("steam", "condensate", "traced")


def _sc(cfg, key):
    return cfg["thermal"]["scene"][key]["value"]


def _cond_index(condition: str) -> int:
    return {"train": 0, "shifted": 1}[condition]


# ------------------------------------------------------------------------------ jobs
def make_ir_jobs(cfg: dict, n: int, seed: int = 0, condition: str = "train") -> list[dict]:
    """Sample `n` render jobs: scene parameters + defects in image coordinates."""
    th = cfg["thermal"]
    cond = thermal._cond(cfg, condition)
    rng = np.random.default_rng([seed, 101, _cond_index(condition)])
    W, H = int(th["image_w"]["value"]), int(th["image_h"]["value"])
    err = th["eps_set_error"][condition]["value"]
    neg_frac = _sc(cfg, "negative_frac")
    jobs = []
    for i in range(n):
        medium = str(rng.choice(_MEDIUMS, p=[0.4, 0.3, 0.3]))
        t_c = float(rng.uniform(*_sc(cfg, f"{medium}_temp_c")))
        p_barg = (float(np.clip(thermal.heat.sat_pressure_bar_abs(t_c) - 1.013, 0, 25))
                  if medium == "steam" else (float(rng.uniform(1, 3)) if medium == "condensate"
                                             else 0.0))
        jacket = str(rng.choice(["aluminium", "galvanized", "stainless"], p=[0.5, 0.25, 0.25]))
        e_lo, e_hi = th["emissivity_by_jacket"][jacket]["value"]
        seg = {"medium": medium, "material": "carbon_steel", "temp_c": t_c,
               "od_mm": float(rng.choice(_sc(cfg, "od_mm"))), "insulated": True,
               "insulation_mm": float(rng.uniform(*_sc(cfg, "insulation_mm"))),
               "jacket": jacket, "pressure_barg": p_barg, "traced": medium == "traced"}
        negative = bool(rng.random() < neg_frac)
        hard = []
        sc = {"ambient_c": float(rng.uniform(*th["ambient_c"]["value"])),
              "sky_offset_k": float(rng.uniform(*cond["sky_offset_k"])),
              "wind_mps": float(rng.uniform(*cond["wind_mps"])),
              "sun_k": float(rng.uniform(*cond["sun_k"])),
              "eps_jacket": float(rng.uniform(e_lo, e_hi)),
              "eps_set": float(0.5 * (e_lo + e_hi) * (1 + rng.normal(0, err))),
              "hw_px": float(rng.uniform(*_sc(cfg, "pipe_halfwidth_px"))),
              "tilt_deg": float(rng.uniform(*_sc(cfg, "tilt_deg_range"))),
              "cy_px": float(H / 2 + rng.uniform(-0.1, 0.1) * H),
              "blur_sigma": float(rng.uniform(*th["blur_sigma_range"]["value"])),
              "bare_eps": float(rng.uniform(*th["bare_metal_emissivity"]["value"]))}
        if negative:
            kind = str(rng.choice(["none", *HARD_NEGATIVES], p=[0.3, 0.14, 0.14, 0.14, 0.14, 0.14]))
            if kind != "none":
                hard.append(kind)
        elif rng.random() < 0.25:
            hard.append(str(rng.choice(["seam", "streak", "clamp"])))
        if "reflection" in hard:       # shiny jacket under a clear sky
            sc["eps_jacket"] = float(rng.uniform(0.05, 0.10))
            sc["sky_offset_k"] = min(sc["sky_offset_k"], -25.0)
        job = {"job_id": f"ir{i:05d}", "segment_id": f"IRS{i:05d}", "condition": condition,
               "image_w": W, "image_h": H, "negative": negative, "seg": seg, "scene": sc,
               "hard": hard, "distractors": _distractors(hard, sc, W, rng), "defects": []}
        if not negative:
            job["defects"] = _sample_defects(cfg, job, rng)
        jobs.append(job)
    return jobs


def _distractors(hard, sc, W, rng):
    out = []
    for kind in hard:
        if kind == "seam":
            out.append({"type": "seam", "period": float(rng.uniform(60, 140)),
                        "phase": float(rng.uniform(0, 140)), "width": float(rng.uniform(1.5, 3)),
                        "d_eps": float(rng.uniform(0.06, 0.15))})
        elif kind == "streak":
            out.append({"type": "streak", "v": float(rng.uniform(-0.8, 0.8)) * sc["hw_px"],
                        "thick": float(rng.uniform(2, 4.5)), "u0": float(rng.uniform(-W / 3, W / 6)),
                        "length": float(rng.uniform(60, 160)),
                        "d_eps": float(rng.choice([-1, 1]) * rng.uniform(0.06, 0.15))})
        elif kind == "clamp":
            out.append({"type": "clamp", "u": float(rng.uniform(-W / 3, W / 3)),
                        "width": float(rng.uniform(3, 5)), "eps": float(rng.uniform(0.6, 0.85)),
                        "cold_frac": float(rng.uniform(0.0, 0.5))})
        elif kind == "hot_bg":
            out.append({"type": "hot_bg", "u": float(rng.uniform(-W / 3, W / 3)),
                        "side": float(rng.choice([-1, 1])), "dist": float(rng.uniform(5, 40)),
                        "radius": float(rng.uniform(7, 14)), "dt": float(rng.uniform(2.5, 7))})
    return out


def _sample_defects(cfg, job, rng):
    sc, seg, W = job["scene"], job["seg"], job["image_w"]
    hw = sc["hw_px"]
    n_def = 1 + int(rng.random() < 0.25)
    lo, hi = _sc(cfg, "defect_length_px")
    out, used = [], []
    for _ in range(n_def):
        medium = seg["medium"]
        kind = str(rng.choice(["wet_insulation", "insulation_damage", "steam_leak"],
                              p=[0.4, 0.3, 0.3]))
        if kind == "wet_insulation" and medium == "traced" and rng.random() < 0.5:
            kind = "tracer_leak"
        a = float(np.exp(rng.uniform(np.log(lo), np.log(hi))) / 2)    # half-length (px)
        for _try in range(30):
            u = float(rng.uniform(-0.36, 0.36) * W)
            if all(abs(u - u2) > 2 * (a + a2) + 24 for u2, a2 in used):
                break
        else:
            continue
        used.append((u, a if kind != "steam_leak" else 18.0))
        d = {"kind": kind, "class_id": KIND_CLASS[kind], "u": u, "a_px": a}
        if kind in ("wet_insulation", "tracer_leak"):
            b = float(rng.uniform(0.3, 0.7) * hw)
            vc = float(rng.uniform(0.15, 0.55) * hw)
            b = min(b, hw - vc - 1.0)
            d.update(v=vc, b_px=b, moisture=(0.8 if kind == "tracer_leak"
                                             else float(rng.uniform(0.03, 1.0))),
                     soft=0.35, length_mm=0.0, circ_frac=0.0, orifice_mm=0.0, clock_deg=180.0)
        elif kind == "insulation_damage":
            cf = float(rng.uniform(0.2, 1.0))
            vc = float(rng.uniform(-0.5, 0.5) * hw)
            b = float(np.clip(cf * hw * 0.8, 3.0, hw - abs(vc) - 1.0))
            d.update(v=vc, b_px=b, moisture=0.0, soft=0.07, circ_frac=cf, orifice_mm=0.0,
                     length_mm=0.0, clock_deg=float(180 + 90 * vc / hw))
        else:
            o = float(np.exp(rng.uniform(np.log(_sc(cfg, "orifice_mm")[0]),
                                         np.log(_sc(cfg, "orifice_mm")[1]))))
            d.update(orifice_mm=o, r_px=float(3.0 + 0.5 * o), side=-1.0 if rng.random() < 0.8 else 1.0,
                     drift=float(rng.uniform(-0.5, 0.5)), moisture=0.0)
        d["true_dt_k"] = (0.0 if kind == "steam_leak" else float(
            thermal.contrast_k(cfg, seg, d, sc["wind_mps"], sc["ambient_c"])))
        out.append(d)
    return out


# ------------------------------------------------------------------------------ rendering
def _frame(job):
    sc = job["scene"]
    t = math.radians(sc["tilt_deg"])
    return math.cos(t), math.sin(t), W2(job), sc["cy_px"], sc["hw_px"]


def W2(job):
    return job["image_w"] / 2.0


def _uv(job):
    H, W = job["image_h"], job["image_w"]
    ct, st, cx0, cy0, _hw = _frame(job)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dx, dy = xx - cx0, yy - cy0
    return xx, yy, dx * ct + dy * st, -dx * st + dy * ct


def pipe_mask(job: dict) -> np.ndarray:
    """Boolean pipe-band mask of a job (what the detector is told about the pipe)."""
    _, _, _, v = _uv(job)
    return np.abs(v) < job["scene"]["hw_px"]


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def _smooth_noise_z(rng, h, w, cell):
    n = _noise(rng, h, w, cell, 3)
    return (n - n.mean()) / (n.std() + 1e-6)


def _plume(job, d, rng, xx, yy):
    """Plume field in [0, ~1.3] (before amplitude) for one leak defect."""
    ct, st, cx0, cy0, hw = _frame(job)
    u, side, r = d["u"], d["side"], d["r_px"]
    sx = cx0 + u * ct - side * hw * st
    sy = cy0 + u * st + side * hw * ct
    ang = d["drift"]
    dxn, dyn = math.sin(ang), side * math.cos(ang)
    ex, ey = xx - sx, yy - sy
    al = ex * dxn + ey * dyn
    pe = -ex * dyn + ey * dxn
    lp = 2.6 * r
    wp = 0.65 * r * (1.0 + 0.5 * np.clip(al, 0, None) / lp)
    q = ((al - lp) / lp) ** 2 + (pe / wp) ** 2
    f = np.exp(-q)
    nz = _noise(rng, f.shape[0], f.shape[1], max(r, 4.0), 3)
    return (f * (0.65 + 0.7 * nz)).astype(np.float32)


def _render(cfg: dict, job: dict, rng):
    """(temp_app float32 HxW, mask uint8, ids uint8) -- ids[k] marks defect index k + 1."""
    th = cfg["thermal"]
    H, W = job["image_h"], job["image_w"]
    sc, seg = job["scene"], job["seg"]
    xx, yy, u, v = _uv(job)
    hw = sc["hw_px"]
    inside = np.abs(v) < hw
    n_up = -np.clip(v / hw, -1, 1)
    amb, wind = sc["ambient_c"], sc["wind_mps"]
    tj = thermal.jacket_temp_c(cfg, seg, wind, ambient_c=amb)
    t_bare = thermal.jacket_temp_c(cfg, seg, wind, bare=True, ambient_c=amb)

    # emissivity field: spatial variation + longitudinal streaks
    ev = th["emissivity_variation"]["value"]
    wy, wx = _interp_matrix(H, 4.0), _interp_matrix(W, 60.0)
    gx = rng.random((wy.shape[1], wx.shape[1]), dtype=np.float32)
    streak_n = wy @ gx @ wx.T
    streak_n = (streak_n - streak_n.mean()) / (streak_n.std() + 1e-6)
    eps = (sc["eps_jacket"] + ev * (0.7 * _smooth_noise_z(rng, H, W, 30) + 0.7 * streak_n)
           ).astype(np.float32)
    ts = np.full((H, W), tj, np.float32) + np.float32(sc["sun_k"]) * eps * np.clip(n_up, 0, 1)
    ts_bare = t_bare + sc["sun_k"] * sc["bare_eps"] * np.clip(n_up, 0, 1)

    # distractors (hard negatives)
    for dis in job["distractors"]:
        if dis["type"] == "seam":
            ph = ((u + dis["phase"]) % dis["period"]) - dis["period"] / 2
            eps = eps + dis["d_eps"] * (np.abs(ph) < dis["width"] / 2)
        elif dis["type"] == "streak":
            m = (np.abs(v - dis["v"]) < dis["thick"] / 2) & (u > dis["u0"]) & \
                (u < dis["u0"] + dis["length"])
            eps = eps + dis["d_eps"] * m
        elif dis["type"] == "clamp":
            m = (np.abs(u - dis["u"]) < dis["width"] / 2) & (np.abs(v) < hw * 1.05)
            eps = np.where(m, dis["eps"], eps)
            ts = np.where(m, amb + dis["cold_frac"] * (tj - amb), ts)
    eps = np.clip(eps, 0.03, 0.98)

    mask = np.zeros((H, W), np.uint8)
    ids = np.zeros((H, W), np.uint8)
    plume = np.zeros((H, W), np.float32)
    order = sorted(range(len(job["defects"])), key=lambda k: job["defects"][k]["class_id"])
    for k in order:
        d = job["defects"][k]
        if d["kind"] == "steam_leak":
            f = _plume(job, d, rng, xx, yy)
            amp = ((seg["temp_c"] - amb) * 0.35 * (1.0 - math.exp(-(d["orifice_mm"] / 12.0) ** 1.5))
                   / (1.0 + 0.15 * wind))
            plume += np.float32(amp) * f
            region = (f > 0.3) & ~inside & (mask == 0)
            mask[region] = 3
            ids[region] = k + 1
            continue
        a, b = d["a_px"], d["b_px"]
        nz = _noise(rng, H, W, max(min(a, b) * 0.7, 3.0), 2)
        r = np.sqrt(((u - d["u"]) / a) ** 2 + ((v - d["v"]) / b) ** 2) * (1.0 + 0.3 * (0.5 - nz))
        w = _sigmoid((1.0 - r) / d["soft"]).astype(np.float32)
        w[r > 2.5] = 0
        if d["class_id"] == 1:
            t_wet = thermal.jacket_temp_c(cfg, seg, wind, moisture=d["moisture"], ambient_c=amb)
            ts = ts + w * np.float32(t_wet - tj) * (0.85 + 0.3 * nz)
        else:
            ts = ts * (1 - w) + ts_bare * w
            eps = eps * (1 - w) + sc["bare_eps"] * w
        region = (w > 0.5) & inside
        mask[region] = d["class_id"]
        ids[region] = k + 1

    refl = thermal.reflected_temp_c(amb, sc["sky_offset_k"], n_up)
    t_pipe = thermal.apparent_temp_c(ts, eps, refl, sc["eps_set"], amb).astype(np.float32)

    # background in apparent temperature: sky gradient, clutter, hot object
    sky_g = np.clip(1.0 - yy / (0.6 * H), 0, 1)
    bg = amb + 0.5 * sc["sky_offset_k"] * sky_g + 6.0 * (_noise(rng, H, W, 50, 3) - 0.5)
    for dis in job["distractors"]:
        if dis["type"] == "hot_bg":
            ct, st, cx0, cy0, _ = _frame(job)
            vv = dis["side"] * (hw + dis["dist"] + dis["radius"])
            hx, hy = cx0 + dis["u"] * ct - vv * st, cy0 + dis["u"] * st + vv * ct
            bg = bg + dis["dt"] * np.exp(-(((xx - hx) ** 2 + (yy - hy) ** 2) / (2 * (dis["radius"] / 1.6) ** 2)))
    img = np.where(inside, np.maximum(t_pipe, CAM_MIN_C), bg + plume).astype(np.float32)
    img = _blur(img, sc["blur_sigma"])

    # detector noise: NETD + fixed-pattern (per-pixel, uncorrected residual), expressed in radiance -> 1/eps_set on the pipe
    t0 = 293.15
    gain = (t0 / (img + thermal.KELVIN)) ** 3
    gain = gain * np.where(inside, 1.0 / max(sc["eps_set"], 0.03), 1.0)
    sig = math.hypot(th["netd_k"]["value"], th["fpn_k"]["value"])   # NETD + static per-pixel FPN
    noise = sig * rng.standard_normal((H, W), dtype=np.float32)
    return (img + gain * noise).astype(np.float32), mask, ids


def render_ir(cfg: dict, job: dict, rng) -> tuple[np.ndarray, np.ndarray]:
    """Render one job -> (temp_app float32 C, mask uint8 with classes 0..3)."""
    t, m, _ = _render(cfg, job, rng)
    return t, m


# ------------------------------------------------------------------------------ detector
def _box3(a):
    p = np.pad(a, 1, mode="edge")
    return sum(p[i:i + a.shape[0], j:j + a.shape[1]] for i in range(3) for j in range(3)) / 9.0


def _dilate(m, r):
    pad = np.pad(m, r)
    h, w = m.shape
    out = np.zeros_like(m)
    for i in range(2 * r + 1):
        for j in range(2 * r + 1):
            out |= pad[i:i + h, j:j + w]
    return out


def _mad_sigma(x):
    m = np.median(x)
    return float(1.4826 * np.median(np.abs(x - m)))


def _components(m, min_area, min_extent):
    """Yield (rows, cols) index arrays of 8-connected components passing area / extent tests."""
    lab, n = label_components(m)
    for k in range(1, n + 1):
        ys, xs = np.nonzero(lab == k)
        if len(ys) < min_area:
            continue
        if min(ys.max() - ys.min() + 1, xs.max() - xs.min() + 1) < min_extent:
            continue
        yield ys, xs


def _longest_run(flags):
    """Indices of the longest contiguous run of True in a 1-D boolean array."""
    d = np.diff(np.concatenate(([0], flags.astype(np.int8), [0])))
    st, en = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    if len(st) == 0:
        return np.zeros(0, int)
    k = int(np.argmax(en - st))
    return np.arange(st[k], en[k])


def _bg_median_u(g, win, stride=4):
    """Running median of each row of g (nv, nu) along u over `win` px (subsampled, interpolated)."""
    from numpy.lib.stride_tricks import sliding_window_view

    nu = g.shape[1]
    win = min(win, nu if nu % 2 else nu - 1)
    pad = win // 2
    gp = np.pad(g, ((0, 0), (pad, pad)), mode="reflect")
    idx = np.unique(np.append(np.arange(0, nu, stride), nu - 1))
    med = np.median(sliding_window_view(gp, win, axis=1)[:, idx], axis=2)
    j = np.clip(np.searchsorted(idx, np.arange(nu), side="right") - 1, 0, len(idx) - 2)
    t = (np.arange(nu) - idx[j]) / (idx[j + 1] - idx[j])
    return med[:, j] * (1 - t) + med[:, j + 1] * t


def detect_ir(cfg: dict, temp_app: np.ndarray, pipe_mask_: np.ndarray) -> np.ndarray:
    """Baseline detector -> class mask (uint8, 0..3). See module docstring for the method."""
    det = cfg["thermal"]["detector"]
    z_thr, min_dt = det["z_thr"]["value"], det["min_dt_k"]["value"]
    min_area, min_ext = det["min_area_px"]["value"], det["min_extent_px"]["value"]
    win, dmg_dt = int(det["bg_window_px"]["value"]), det["damage_dt_k"]["value"]
    peak_z, dmg_edge = det["peak_z"]["value"], det["damage_edge_px"]["value"]
    H, W = temp_app.shape
    out = np.zeros((H, W), np.uint8)
    ys, xs = np.nonzero(pipe_mask_)
    if len(xs) < 200:
        return out
    cx, cy = xs.mean(), ys.mean()
    th = 0.5 * math.atan2(2 * ((xs - cx) * (ys - cy)).mean(),
                          ((xs - cx) ** 2).mean() - ((ys - cy) ** 2).mean())
    ct, st = math.cos(th), math.sin(th)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    u = (xx - cx) * ct + (yy - cy) * st
    v = -(xx - cx) * st + (yy - cy) * ct
    pu, pv = u[pipe_mask_], v[pipe_mask_]
    v_lo, v_hi = pv.min(), pv.max()

    # ---- jacket: wet / damaged zones as warm residual against the along-axis running median
    vs = np.arange(math.ceil(v_lo) + 2, math.floor(v_hi) - 1)
    us = np.arange(math.ceil(pu.min()), math.floor(pu.max()) + 1)
    if len(vs) >= 4 and len(us) >= 8:
        gx = np.rint(cx + us[None, :] * ct - vs[:, None] * st).astype(int)
        gy = np.rint(cy + us[None, :] * st + vs[:, None] * ct).astype(int)
        ok = (gx >= 0) & (gx < W) & (gy >= 0) & (gy < H)
        gxc, gyc = np.clip(gx, 0, W - 1), np.clip(gy, 0, H - 1)
        ok &= pipe_mask_[gyc, gxc]
        cols = _longest_run(ok.all(axis=0))
        if len(cols) >= 16:
            us_k = us[cols]
            g = temp_app[gyc[:, cols], gxc[:, cols]]
            res = _box3(g - _bg_median_u(g, win))
            sig = max(_mad_sigma(res), 0.02)
            cand = (res >= z_thr * sig) & (res >= min_dt)
            grad = np.hypot(*np.gradient(res))
            cpred = np.zeros(cand.shape, np.uint8)
            for ry, rx in _components(cand, min_area, min_ext):
                vals = res[ry, rx]
                if vals.max() < peak_z * sig:        # hysteresis: weak blobs are noise/clutter
                    continue
                keep = vals >= 0.5 * np.percentile(vals, 95)      # half-maximum outline
                ky, kx = ry[keep], rx[keep]
                if (len(ky) < min_area or min(np.ptp(ky), np.ptp(kx)) + 1 < min_ext):
                    continue
                # bare metal = hot AND sharp-edged; a strongly wet zone is hot but soft-edged
                edge_w = vals.max() / (grad[ry, rx].max() + 1e-6)
                cpred[ky, kx] = 2 if (vals.max() >= dmg_dt and edge_w <= dmg_edge) else 1
            iv = np.rint(v - vs[0]).astype(int)
            iu = np.rint(u - us_k[0]).astype(int)
            ok2 = pipe_mask_ & (iv >= 0) & (iv < cpred.shape[0]) & (iu >= 0) & (iu < cpred.shape[1])
            out[ok2] = cpred[iv[ok2], iu[ok2]]

    # ---- leak: warm blob outside the band vs the per-row background of the non-pipe pixels
    outside = (v > v_hi + 3) | (v < v_lo - 3)
    cnt = outside.sum(axis=1)
    tm = np.where(outside, temp_app, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        bgrow = np.nanmedian(tm, axis=1)
    good = cnt >= 20
    if good.sum() >= 8:
        bgrow = np.interp(np.arange(H), np.flatnonzero(good), bgrow[good])
        res2 = _box3(temp_app - bgrow[:, None])
        sig2 = max(_mad_sigma(res2[outside]), 0.02)
        cand = outside & (res2 >= z_thr * sig2) & (res2 >= min_dt)
        near = np.abs(v) <= max(abs(v_lo), abs(v_hi)) + 10
        for ry, rx in _components(cand, min_area, min_ext):
            if near[ry, rx].any() and res2[ry, rx].max() >= peak_z * sig2:
                out[ry, rx] = 3
    return out


# ------------------------------------------------------------------------------ evaluation
def evaluate_ir(cfg: dict, n: int = 300, seed: int = 0, condition: str = "train", jobs=None):
    """Render + detect `n` jobs -> (metrics dict, hit/miss DataFrame[class, a, hit, ...])."""
    import pandas as pd

    jobs = make_ir_jobs(cfg, n, seed, condition) if jobs is None else jobs
    inter = np.zeros(4)
    union = np.zeros(4)
    rows, fp = [], 0
    t_render = t_det = 0.0
    for i, job in enumerate(jobs):
        t0 = time.perf_counter()
        temp, mask, ids = _render(cfg, job, np.random.default_rng([seed, i]))
        t1 = time.perf_counter()
        pred = detect_ir(cfg, temp, pipe_mask(job))
        t_render += t1 - t0
        t_det += time.perf_counter() - t1
        for c in (1, 2, 3):
            g, p = mask == c, pred == c
            inter[c] += (g & p).sum()
            union[c] += (g | p).sum()
            if p.any():       # group fragments: components of the 5x5-dilated prediction
                lab, m = label_components(_dilate(p, 2))
                for k in range(1, m + 1):
                    if not mask[lab == k].any():
                        fp += 1
        for k, d in enumerate(job["defects"]):
            pix = ids == k + 1
            if not pix.any():
                continue
            frac = float((pred[pix] == d["class_id"]).mean())
            a = d["orifice_mm"] if d["kind"] == "steam_leak" else abs(d["true_dt_k"])
            rows.append({"class": IR_CLASSES[d["class_id"]], "a": float(a), "hit": frac >= 0.3,
                         "frac": frac, "kind": d["kind"], "jacket": job["seg"]["jacket"],
                         "job_id": job["job_id"]})
    df = pd.DataFrame(rows, columns=["class", "a", "hit", "frac", "kind", "jacket", "job_id"])
    iou = {IR_CLASSES[c]: float(inter[c] / union[c]) if union[c] > 0 else float("nan")
           for c in (1, 2, 3)}
    hit = {name: float(df.loc[df["class"] == name, "hit"].mean()) if (df["class"] == name).any()
           else float("nan") for name in list(IR_CLASSES.values())[1:]}
    met = {"n_images": len(jobs), "condition": condition, "iou": iou,
           "miou": float(np.nanmean(list(iou.values()))), "hit_rate": hit,
           "hit_rate_all": float(df["hit"].mean()) if len(df) else float("nan"),
           "fp_per_image": fp / max(len(jobs), 1),
           "render_img_per_s": len(jobs) / max(t_render, 1e-9),
           "detect_img_per_s": len(jobs) / max(t_det, 1e-9)}
    return met, df


def _fit_one(a, hit):
    """Hit/miss logistic fit; Firth fallback if separated; b1 >= 0 (POD must not fall with size)."""
    a, hit = np.asarray(a, float), np.asarray(hit, float)
    ok = a > 0
    a, hit = a[ok], hit[ok]
    if len(a) < 5:
        return {"b0": float("nan"), "b1": float("nan")}
    f = pod.fit_pod(a, hit)
    if (not np.isfinite(f["b0"]) or abs(f["b0"]) > 20 or abs(f["b1"]) > 15
            or hit.min() == hit.max()):
        from maek.evaluate import fit_pod_firth

        f = fit_pod_firth(a, hit)
    if f["b1"] < 0:
        r = float(np.clip(hit.mean(), 0.02, 0.98))
        f = {"b0": math.log(r / (1 - r)), "b1": 0.0}
    return f


def fit_ir_pod(cfg: dict, n: int = 600, seed: int = 0, condition: str = "train", df=None) -> dict:
    """POD (b0, b1) per class from the simulator: a = |true dT| (K) or orifice (mm)."""
    if df is None:
        _, df = evaluate_ir(cfg, n, seed, condition)
    out = {}
    for name in list(IR_CLASSES.values())[1:]:
        sub = df[df["class"] == name]
        f = _fit_one(sub["a"], sub["hit"])
        out[name] = {"b0": round(f["b0"], 2), "b1": round(f["b1"], 2), "n": len(sub),
                     "hit_rate": float(sub["hit"].mean()) if len(sub) else float("nan")}
    return out


# ------------------------------------------------------------------------------ dataset output
_CFG = None


def _init_worker(cfg):
    global _CFG
    _CFG = cfg


def _render_one(task):
    from PIL import Image

    seed, i, job, out = task
    out = Path(out)
    temp, mask = render_ir(_CFG, job, np.random.default_rng([seed, i]))
    jid = job["job_id"]
    arr = np.clip(np.rint((temp + PNG_OFFSET_C) * PNG_SCALE), 0, 65535).astype(np.uint16)
    Image.fromarray(arr).save(out / "images" / f"{jid}.png", compress_level=1)
    Image.fromarray(mask).save(out / "masks" / f"{jid}.png", compress_level=1)
    lines = yolo_lines(mask, IR_CLASSES) if mask.any() else []
    (out / "labels" / f"{jid}.txt").write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return jid


def render_all_ir(cfg: dict, jobs: list[dict], out_dir, seed: int = 0, val_frac: float = 0.2,
                  workers: int = 1) -> Path:
    """Write images/ (16-bit PNG, (T_app_C + 50) x 100), masks/, labels/ (YOLO-seg), train.txt,
    val.txt, dataset.yaml and jobs.json (with the true dT / orifice per defect)."""
    out = Path(out_dir)
    if any((out / name).exists() for name in ("dataset.yaml", "train.txt", "val.txt")) or any(
        p.is_dir() and any(p.iterdir()) for p in (out / s for s in ("images", "masks", "labels"))
    ):
        raise FileExistsError(f"Dataset already exists in {out}; choose a new output directory")
    for sub in ("images", "masks", "labels"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    tasks = [(seed, i, job, str(out)) for i, job in enumerate(jobs)]
    if workers > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(cfg,)) as ex:
            names = list(ex.map(_render_one, tasks, chunksize=8))
    else:
        _init_worker(cfg)
        names = [_render_one(t) for t in tasks]
    val = split_val(jobs, val_frac)
    (out / "train.txt").write_text("".join(f"./images/{j}.png\n" for j in names if j not in val))
    (out / "val.txt").write_text("".join(f"./images/{j}.png\n" for j in names if j in val))
    cls_lines = "".join(f"  {c - 1}: {IR_CLASSES[c]}\n" for c in IR_CLASSES if c)
    (out / "dataset.yaml").write_text(
        f"path: {out.resolve()}\ntrain: train.txt\nval: val.txt\nnames:\n{cls_lines}",
        encoding="utf-8")
    (out / "jobs.json").write_text(json.dumps(jobs, indent=1), encoding="utf-8")
    return out / "dataset.yaml"


def metrics_markdown(met_by_cond: dict) -> str:
    rows = ["| condition | IoU wet | IoU damage | IoU leak | hit wet | hit damage | hit leak | FP/img |",
            "|---|---|---|---|---|---|---|---|"]
    for cond, m in met_by_cond.items():
        i, h = m["iou"], m["hit_rate"]
        rows.append(f"| {cond} | {i['wet_insulation']:.2f} | {i['insulation_damage']:.2f} | "
                    f"{i['steam_leak']:.2f} | {h['wet_insulation']:.2f} | "
                    f"{h['insulation_damage']:.2f} | {h['steam_leak']:.2f} | "
                    f"{m['fp_per_image']:.2f} |")
    return "\n".join(rows) + "\n"
