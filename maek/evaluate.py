"""Baseline evaluation of the three functions on train vs shifted conditions.

(1) corrosion image segmentation (HSV threshold), (2) UT crack detection (angle beam),
(3) UT thickness / pit-depth detection (straight beam). Every number comes from simulated
data with fixed seeds; see docs/results.md for the commands and caveats.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

from maek import network, params, pod, ut
from maek.camera import composite2d, jobs, segment

CONDITIONS = ("train", "shifted")


def _g(cfg, k):
    return params.get(cfg, f"eval.{k}")


# ------------------------------------------------------------------ POD helpers
def pod_summary(sizes, hits, n_boot=300, seed=0) -> dict:
    """a90 (logistic POD in ln size) with bootstrap a90/95; NaN if the fit is degenerate."""
    sizes, hits = np.asarray(sizes, float), np.asarray(hits, float)
    ok = sizes > 0
    sizes, hits = sizes[ok], hits[ok]
    nan = {"n": len(sizes), "hit_rate": float(hits.mean()) if len(hits) else np.nan,
           "min_size": float(sizes.min()) if len(sizes) else np.nan,
           "max_size": float(sizes.max()) if len(sizes) else np.nan, "status": "ok",
           "b0": np.nan, "b1": np.nan, "a90": np.nan, "a90_lo": np.nan, "a90_95": np.nan}
    if len(sizes) < 10:
        return {**nan, "status": "too_few"}
    if hits.min() == hits.max():  # perfectly separated: logistic fit diverges
        return {**nan, "status": "all_hit" if hits.min() else "all_miss"}
    f = pod.fit_pod(sizes, hits)
    if f["b1"] <= 0:
        return {**nan, "status": "no_trend"}
    a90 = pod.a_at(0.9, f["b0"], f["b1"])
    if a90 > 3 * sizes.max():  # POD never gets near 90% inside the tested size range
        return {**nan, "status": "beyond_range", "b0": f["b0"], "b1": f["b1"]}
    a90, lo, hi = pod.bootstrap_a90(sizes, hits, n_boot=n_boot, seed=seed)
    return {**nan, "b0": f["b0"], "b1": f["b1"], "a90": a90, "a90_lo": lo, "a90_95": hi}


# ------------------------------------------------------------------ (1) corrosion images
def _defect_center_radius(job, d):
    """Pixel centre and search radius of a job defect (same geometry as the renderer)."""
    S = job["image_size"]
    cx, cy = composite2d.defect_center(job, d)
    r = 1.2 * max(d["w"], d["h"]) * S / 2 + 3
    return cx, cy, r


def eval_camera_image(cfg, job, rgb, mask) -> dict:
    """Metrics of the rust segmenter on one rendered image."""
    pred = segment.segment_rust(rgb, tuple(_g(cfg, "seg_hue_range_deg")), _g(cfg, "seg_sat_min"),
                                _g(cfg, "seg_val_min"))
    gt = mask == 1
    S = mask.shape[0]
    yy, xx = np.mgrid[0:S, 0:S]
    defects = []
    for d in job["defects"]:
        if d["class_id"] != 1:
            continue
        cx, cy, r = _defect_center_radius(job, d)
        win = ((xx - cx) ** 2 + (yy - cy) ** 2 <= r * r) & gt
        n = int(win.sum())
        if n < 4:  # hidden by the pipe edge / other class: no ground-truth pixels to hit
            continue
        rec = float((pred & win).sum() / n)
        defects.append({"area_cm2": d["area_cm2"], "hit": rec >= _g(cfg, "seg_hit_recall")})
    return {"inter": int((pred & gt).sum()), "union": int((pred | gt).sum()),
            "gt_pos": bool(gt.any()), "pred_px": int(pred.sum()), "defects": defects}


def eval_camera(cfg, condition, n, seed=0, size=None) -> dict:
    """Render n images in `condition` and evaluate the segmenter."""
    if size is not None:
        cfg = _with(cfg, "camera.image_size", size)
    seg, _, dfx = network.generate_network(cfg, seed)
    js = jobs.make_jobs(cfg, seg, dfx, n, seed, condition)
    inter = union = 0
    det, gt_pos, rows = [], [], []
    min_px = _g(cfg, "seg_min_pred_px")
    for i, job in enumerate(js):
        rgb, mask = composite2d.render_job(cfg, job, np.random.default_rng([seed, 7, i]))
        r = eval_camera_image(cfg, job, rgb, mask)
        inter += r["inter"]
        union += r["union"]
        gt_pos.append(r["gt_pos"])
        det.append(r["pred_px"] >= min_px)
        rows += r["defects"]
    det, gt_pos = np.array(det), np.array(gt_pos)
    area = [r["area_cm2"] for r in rows]
    hit = [r["hit"] for r in rows]
    return {
        "condition": condition, "n_images": n, "n_positive": int(gt_pos.sum()),
        "pixel_iou": inter / union if union else float("nan"),
        "detection_rate": float(det[gt_pos].mean()) if gt_pos.any() else float("nan"),
        "false_alarm_rate": float(det[~gt_pos].mean()) if (~gt_pos).any() else float("nan"),
        "pod": pod_summary(area, hit, _g(cfg, "pod_bootstrap"), seed),
        "defect_sizes": area, "defect_hits": hit,
    }


def _with(cfg, dotted, value):
    import copy

    c = copy.deepcopy(cfg)
    node = c
    for part in dotted.split("."):
        node = node[part]
    node["value"] = value
    return c


# ------------------------------------------------------------------ (2)(3) UT
def eval_ut(cfg, condition, n, seed=0) -> dict:
    straight, angle, lab = ut.make_dataset(cfg, n, seed, condition)
    rows = list(lab.itertuples())
    th = np.array([ut.estimate_thickness(cfg, s, r.temp_c) for s, r in zip(straight, rows)])
    tm = np.array([ut.min_thickness(cfg, s, r.temp_c) for s, r in zip(straight, rows)])
    det = np.array([ut.detect_crack(cfg, s, r.wall_mm, r.angle_deg, r.temp_c)["found"]
                    for s, r in zip(angle, rows)])
    crack = lab["crack"].to_numpy(bool)
    err = np.abs(th - lab["wall_mm"].to_numpy())
    err = np.where(np.isnan(err), np.inf, err)  # a failed estimate counts as a miss
    t1, t2 = _g(cfg, "thickness_tol_mm")
    pit = lab["pit_depth_mm"].to_numpy() > 0
    pit_hit = np.nan_to_num(tm, nan=1e9) <= lab["wall_mm"].to_numpy() - _g(cfg, "pit_margin_mm")
    nb = _g(cfg, "pod_bootstrap")
    return {
        "condition": condition, "n": n, "n_crack": int(crack.sum()), "n_pit": int(pit.sum()),
        "crack_detection_rate": float(det[crack].mean()),
        "crack_false_alarm_rate": float(det[~crack].mean()),
        "crack_pod": pod_summary(lab["crack_height_mm"][crack], det[crack], nb, seed),
        "thickness_mae_mm": float(np.mean(err[np.isfinite(err)])),
        "thickness_within_t1": float((err <= t1).mean()),
        "thickness_within_t2": float((err <= t2).mean()),
        "pit_detection_rate": float(pit_hit[pit].mean()) if pit.any() else float("nan"),
        "pit_false_alarm_rate": float(pit_hit[~pit].mean()) if (~pit).any() else float("nan"),
        "pit_pod": pod_summary(lab["pit_depth_mm"][pit], pit_hit[pit], nb, seed),
        "crack_sizes": lab["crack_height_mm"][crack].tolist(), "crack_hits": det[crack].tolist(),
        "pit_sizes": lab["pit_depth_mm"][pit].tolist(), "pit_hits": pit_hit[pit].tolist(),
    }


# ------------------------------------------------------------------ strategy crack numbers
def crack_strategy(cfg, seed=0, runs=10, total_km=None) -> dict:
    """Crack detection rate of baseline / AI (old random mode / risk-ranked) triage."""
    from maek import strategy

    out = {}
    for name, mode in (("ai_random", "random"), ("ai_risk_ranked", "risk_ranked")):
        res = strategy._run_all(_with(cfg, "strategy.crack_ut_mode", mode), seed, runs, total_km)
        out[name] = float(res["ai_triage"]["detection_rate_crack"].mean())
        out[name + "_ut_points"] = float(res["ai_triage"]["ut_points"].mean())
        out["baseline"] = float(res["baseline"]["detection_rate_crack"].mean())
        out["baseline_ut_points"] = float(res["baseline"]["ut_points"].mean())
    return out


# ------------------------------------------------------------------ driver / reporting
def run_all(cfg, out_dir, seed=0, n_camera=None, n_ut=None, strategy_runs=10) -> dict:
    n_camera = n_camera or _g(cfg, "n_camera")
    n_ut = n_ut or _g(cfg, "n_ut")
    res = {"camera": {}, "ut": {}}
    for c in CONDITIONS:
        res["camera"][c] = eval_camera(cfg, c, n_camera, seed, _g(cfg, "camera_image_size"))
        res["ut"][c] = eval_ut(cfg, c, n_ut, seed)
    res["strategy_crack"] = crack_strategy(cfg, seed, strategy_runs)
    res["meta"] = {"seed": seed, "n_camera": n_camera, "n_ut": n_ut,
                   "strategy_runs": strategy_runs}
    write_outputs(res, out_dir)
    return res


def _flat_pod(res) -> pd.DataFrame:
    rows = []
    for c in CONDITIONS:
        for fn, p, unit in (("corrosion", res["camera"][c]["pod"], "cm2"),
                            ("crack", res["ut"][c]["crack_pod"], "mm"),
                            ("thickness_pit", res["ut"][c]["pit_pod"], "mm")):
            rows.append({"function": fn, "condition": c, "size_unit": unit, **p})
    return pd.DataFrame(rows)


def write_outputs(res, out_dir) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    cam = pd.DataFrame([{k: v for k, v in res["camera"][c].items() if k != "pod"
                         and not k.startswith("defect_")} for c in CONDITIONS])
    utd = pd.DataFrame([{k: v for k, v in res["ut"][c].items()
                         if not isinstance(v, (dict, list))} for c in CONDITIONS])
    cam.to_csv(out / "camera_metrics.csv", index=False)
    utd.to_csv(out / "ut_metrics.csv", index=False)
    _flat_pod(res).to_csv(out / "pod.csv", index=False)
    pd.DataFrame([res["strategy_crack"]]).to_csv(out / "strategy_crack.csv", index=False)
    (out / "results_tables.md").write_text(tables_markdown(res), encoding="utf-8")


def fmt(v, nd=3):
    return "-" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.{nd}f}"


def pod_cell(p) -> str:
    """a90 [a90/95] text, or why it is undefined."""
    if p["status"] == "ok":
        return f"{fmt(p['a90'], 2)} [{fmt(p['a90_95'], 2)}]"
    if p["status"] == "all_hit":
        return f"전부 검출(a90 < {fmt(p['min_size'], 2)})"
    if p["status"] == "beyond_range":
        return f"도달 못함(a90 > 시험 범위 최대 {fmt(p['max_size'], 1)})"
    if p["status"] == "all_miss":
        return "전부 미검출(a90 > 범위)"
    return p["status"]


def tables_markdown(res) -> str:
    """Markdown tables of all headline numbers (pasted into docs/results.md)."""
    c, u = res["camera"], res["ut"]

    def tab(title, rows):
        out = [f"**{title}**", "", "| 지표 | train | shifted |", "|---|---|---|"]
        for name, f, k in rows:
            out.append(f"| {name} | {f(k[0])} | {f(k[1])} |")
        return "\n".join(out)

    def pair(d, key, sub=None):
        return tuple(d[x][key] if sub is None else d[x][key][sub] for x in CONDITIONS)

    n3 = fmt
    cam = tab("① 부식 (HSV 임계값 분할)", [
        ("픽셀 IoU", n3, pair(c, "pixel_iou")),
        ("이미지 검출률", n3, pair(c, "detection_rate")),
        ("오경보율", n3, pair(c, "false_alarm_rate")),
        ("결함 단위 hit율", n3, pair(c, "pod", "hit_rate")),
        ("a90 [a90/95] (cm2)", pod_cell, pair(c, "pod"))])
    crk = tab("② 균열 (사각 UT 게이트 검출)", [
        ("검출률", n3, pair(u, "crack_detection_rate")),
        ("오경보율", n3, pair(u, "crack_false_alarm_rate")),
        ("a90 [a90/95] (균열 높이 mm)", pod_cell, pair(u, "crack_pod"))])
    thk = tab("③ 두께 (직진 UT 에코 간격 / 피트 최소 두께)", [
        ("MAE (mm)", n3, pair(u, "thickness_mae_mm")),
        ("+-0.1 mm 이내 비율", n3, pair(u, "thickness_within_t1")),
        ("+-0.5 mm 이내 비율", n3, pair(u, "thickness_within_t2")),
        ("피트 검출률", n3, pair(u, "pit_detection_rate")),
        ("피트 오경보율", n3, pair(u, "pit_false_alarm_rate")),
        ("피트 a90 [a90/95] (깊이 mm)", pod_cell, pair(u, "pit_pod"))])
    sc = res["strategy_crack"]
    st = ["**전략 비교: 치명 균열 검출률**", "", "| 전략 | 검출률 | 평균 UT 점 수 |", "|---|---|---|"]
    for name, k in (("기준(고정 CML)", "baseline"), ("AI 트리아지, 기존(random)", "ai_random"),
                    ("AI 트리아지, 위험순위(risk_ranked)", "ai_risk_ranked")):
        pts = sc["baseline_ut_points"] if k == "baseline" else sc[k + "_ut_points"]
        st.append(f"| {name} | {fmt(sc[k])} | {fmt(pts, 0)} |")
    return "\n\n".join((cam, crk, thk, "\n".join(st))) + "\n"
