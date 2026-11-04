"""Sample camera render jobs from the ground-truth network (see docs/render-jobs.md)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from maek import params

SCHEMA_VERSION = 1
CLASS_OF = {"external_corrosion": 1, "cui": 2, "flange_leak": 3}


def _visible(defects: pd.DataFrame) -> pd.DataFrame:
    """Defects a camera can see: external rust, flange leak stains, CUI with a cladding sign."""
    m = (defects["visible_external"].astype(bool)
         | ((defects["kind"] == "cui") & defects["external_sign"].astype(bool)))
    return defects[m]


def make_jobs(cfg: dict, segments: pd.DataFrame, defects: pd.DataFrame, n: int,
              seed: int, condition: str = "train") -> list[dict]:
    """Sample `n` image jobs (about `camera.negative_frac` clean negatives).

    condition="shifted" draws lighting/dust/steam/blur/noise from the harder
    `camera.shifted_*` ranges (same RNG stream layout as "train").
    """
    if condition not in ("train", "shifted"):
        raise ValueError("condition must be 'train' or 'shifted'")
    pre = "shifted_" if condition == "shifted" else ""
    env_rng = lambda k: g("camera." + pre + k)

    g = lambda k: params.get(cfg, k)
    rng = np.random.default_rng(seed)
    vis = _visible(defects)
    seg = segments.set_index("segment_id")
    vis_by_seg = {sid: grp for sid, grp in vis.groupby("segment_id", sort=False)}
    pos_ids = list(vis_by_seg)
    neg_ids = [s for s in segments["segment_id"] if s not in vis_by_seg]
    if not neg_ids:
        neg_ids = list(segments["segment_id"])
    n_neg = round(n * g("camera.negative_frac")) if pos_ids else n
    is_neg = np.zeros(n, bool)
    is_neg[rng.permutation(n)[:n_neg]] = True
    size = int(g("camera.image_size"))
    pw_lo, pw_hi = g("camera.pipe_width_frac_range")
    min_px = g("camera.min_defect_px")
    pad = g("camera.view_window_pad")

    jobs = []
    for i in range(n):
        if is_neg[i]:
            sid = neg_ids[rng.integers(len(neg_ids))]
            anchor = None
        else:
            sid = pos_ids[rng.integers(len(pos_ids))]
            grp = vis_by_seg[sid]
            anchor = grp.iloc[rng.integers(len(grp))]
        s = seg.loc[sid]
        pipe_frac = rng.uniform(pw_lo, pw_hi)
        px_per_mm = pipe_frac * size / s["od_mm"]
        tilt = float(rng.uniform(*g("camera.tilt_deg_range")))
        view_mm = size / px_per_mm
        if anchor is None:
            center_m = float(rng.uniform(0, s["length_m"]))
            view_clock = float(rng.uniform(0, 360))
        else:
            center_m = float(anchor["pos_m"]) + rng.uniform(-0.25, 0.25) * view_mm / 1000
            view_clock = float(anchor["clock_deg"]) + rng.uniform(-30, 30)
        shown = []
        if sid in vis_by_seg:
            for d in vis_by_seg[sid].itertuples(index=False):
                u = (d.pos_m - center_m) * 1000 * px_per_mm / size
                if abs(u) > 0.5 * pad:
                    continue
                phi = math.radians(d.clock_deg - view_clock)
                if math.cos(phi) < 0.25:
                    continue
                v = math.sin(phi)  # -1..1 across the visible half of the pipe
                side_mm = math.sqrt(max(d.area_cm2, 0.01)) * 10.0
                w_px = max(side_mm * px_per_mm, min_px)
                h_px = max(side_mm * px_per_mm * max(math.cos(phi), 0.3), min_px)
                shown.append({
                    "defect_id": d.defect_id, "kind": d.kind,
                    "class_id": CLASS_OF[d.kind],
                    "area_cm2": float(d.area_cm2),
                    "u": round(0.5 + u, 4), "v": round(v, 4),  # pipe frame (along, across)
                    "w": round(w_px / size, 4), "h": round(h_px / size, 4),
                })
        jobs.append({
            "job_id": f"J{i:06d}", "segment_id": sid, "image_size": size,
            "negative": len(shown) == 0,
            "pipe": {"od_mm": float(s["od_mm"]), "material": str(s["material"]),
                     "insulated": bool(s["insulated"]), "width_frac": round(pipe_frac, 4),
                     "tilt_deg": round(tilt, 2), "view_center_m": round(center_m, 3),
                     "view_clock_deg": round(view_clock % 360, 1)},
            "defects": shown, "condition": condition,
            "env": {
                "brightness": round(float(rng.uniform(*env_rng("brightness_range"))), 3),
                "dust": round(float(rng.uniform(*env_rng("dust_opacity_range"))), 3),
                "steam": round(float(rng.uniform(*env_rng("steam_opacity_range"))), 3),
                "blur_sigma": round(float(rng.uniform(*env_rng("blur_sigma_range"))), 3),
                "noise_sigma": round(float(rng.uniform(*env_rng("noise_sigma_range"))), 4),
            },
        })
    return jobs


def save_jobs(path, jobs: list[dict]) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "jobs": jobs}, indent=1),
                 encoding="utf-8")
    return p


def load_jobs(path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["jobs"]
