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


def fit_pod_firth(sizes, hits, max_iter=200, tol=1e-9) -> dict:
    """Firth-penalised logistic POD fit (ln size): finite even when every defect is hit.

    Maximises log L + 0.5 log det I (Jeffreys prior); close to `maek.pod.fit_pod` when the
    data are not separated. Used to hand usable (b0, b1) to the strategy model when the
    plain fit diverges (all hit).
    """
    sizes, hits = np.asarray(sizes, float), np.asarray(hits, float)
    ok = sizes > 0
    if ok.sum() < 2:
        return {"b0": float("nan"), "b1": float("nan")}
    X = np.column_stack([np.ones(ok.sum()), np.log(sizes[ok])])
    y = hits[ok]
    beta = np.zeros(2)
    for _ in range(max_iter):
        p = 1 / (1 + np.exp(-np.clip(X @ beta, -35, 35)))
        w = p * (1 - p)
        info = (X * w[:, None]).T @ X + 1e-10 * np.eye(2)
        inv = np.linalg.inv(info)
        h = w * np.einsum("ij,jk,ik->i", X, inv, X)  # hat-matrix diagonal
        step = inv @ (X.T @ (y - p + h * (0.5 - p)))
        step = np.clip(step, -2, 2)
        beta = beta + step
        if np.max(np.abs(step)) < tol:
            break
    return {"b0": float(beta[0]), "b1": float(beta[1])}


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
def _pit_metrics(lab, found, depth_est, nb, seed) -> dict:
    """Pit detection / false-alarm rates, POD in depth and depth error of one detector."""
    pit_mask = lab["pit_depth_mm"].to_numpy() > 0
    found = np.asarray(found, bool)
    depth = lab["pit_depth_mm"].to_numpy()
    err = np.abs(np.asarray(depth_est, float) - depth)[pit_mask & found]
    nan = float("nan")
    return {
        "pit_detection_rate": float(found[pit_mask].mean()) if pit_mask.any() else nan,
        "pit_false_alarm_rate": float(found[~pit_mask].mean()) if (~pit_mask).any() else nan,
        "pit_depth_mae_mm": float(err.mean()) if len(err) else nan,
        "pit_pod": pod_summary(depth[pit_mask], found[pit_mask], nb, seed),
        "pit_sizes": depth[pit_mask].tolist(), "pit_hits": found[pit_mask].tolist(),
    }


def eval_ut(cfg, condition, n, seed=0) -> dict:
    """Crack, thickness and pit metrics on one condition (straight beam: `ut.n_avg` shots).

    Pit detection uses the default detector `ut.detect_pit` (`ut.pit.method`).
    """
    straight, angle, lab = ut.make_dataset(cfg, n, seed, condition)
    rows = list(lab.itertuples())
    temps = ut.analysis_temps(cfg, lab)  # measured (not true) temperature, or 20 C
    th = np.array([ut.estimate_thickness(cfg, s, t) for s, t in zip(straight, temps)])
    det = np.array([ut.detect_crack(cfg, s, r.wall_mm, r.angle_deg, t)["found"]
                    for s, r, t in zip(angle, rows, temps)])
    pits = [ut.detect_pit(cfg, s, w, t) for s, w, t in zip(straight, lab["wall_mm"], temps)]
    crack = lab["crack"].to_numpy(bool)
    err = np.abs(th - lab["wall_mm"].to_numpy())
    err = np.where(np.isnan(err), np.inf, err)  # a failed estimate counts as a miss
    t1, t2 = _g(cfg, "thickness_tol_mm")
    nb = _g(cfg, "pod_bootstrap")
    return {
        "condition": condition, "n": n, "n_crack": int(crack.sum()),
        "n_pit": int((lab["pit_depth_mm"] > 0).sum()),
        "n_avg": int(params.get(cfg, "ut.n_avg")), "pit_method": params.get(cfg, "ut.pit.method"),
        "crack_detection_rate": float(det[crack].mean()),
        "crack_false_alarm_rate": float(det[~crack].mean()),
        "crack_pod": pod_summary(lab["crack_height_mm"][crack], det[crack], nb, seed),
        "thickness_mae_mm": float(np.mean(err[np.isfinite(err)])),
        "thickness_within_t1": float((err <= t1).mean()),
        "thickness_within_t2": float((err <= t2).mean()),
        **_pit_metrics(lab, [r["found"] for r in pits], [r["depth_est_mm"] for r in pits], nb,
                       seed),
        "crack_sizes": lab["crack_height_mm"][crack].tolist(), "crack_hits": det[crack].tolist(),
    }


# ------------------------------------------------------------------ pit ablation / diagnosis
PIT_FACTORS = (("train", ()), ("noise", ("noise",)), ("coupling", ("coupling",)),
               ("temperature", ("temperature",)), ("noise+coupling", ("noise", "coupling")),
               ("shifted", ("noise", "coupling", "temperature")))


def factor_cfg(cfg, factors):
    """Config whose 'shifted' condition changes only `factors` (others at train values).

    noise: x`shifted_noise_scale`; coupling: `shifted_coupling_range`; temperature:
    `shifted_temp_range_c` and `shifted_temp_meas_error_c` (hot pipe, poor reading).
    """
    d = "ut.dataset."
    g = params.get
    c = cfg
    if "noise" not in factors:
        c = _with(c, d + "shifted_noise_scale", 1.0)
    if "coupling" not in factors:
        c = _with(c, d + "shifted_coupling_range", g(cfg, d + "train_coupling_range"))
    if "temperature" not in factors:
        c = _with(c, d + "shifted_temp_range_c", g(cfg, d + "train_temp_range_c"))
        c = _with(c, d + "shifted_temp_meas_error_c", g(cfg, d + "train_temp_meas_error_c"))
    return c


def pit_detections(cfg, straight, lab, methods, models=None) -> dict:
    """{method: (found [n], depth_est [n])} for every method on the same A-scans."""
    from maek import pit

    models = models or {}
    temps = ut.analysis_temps(cfg, lab)
    out = {m: ([], []) for m in methods}
    for s, w, t, na in zip(straight, lab["wall_mm"], temps, lab["n_avg"]):
        a = pit.analyse(cfg, s, w, t)
        for m in methods:
            r = pit.detect_pit(cfg, s, w, t, m, model=models.get(m), a=a, n_avg=na)
            out[m][0].append(r["found"])
            out[m][1].append(r["depth_est_mm"])
    return {m: (np.array(f, bool), np.array(d, float)) for m, (f, d) in out.items()}


def _pit_models(cfg, methods) -> dict:
    from maek import pit

    return {m: pit.get_model(cfg, shadow=m == "learned_shadow") for m in methods
            if m.startswith("learned")}


def pit_ablation(cfg, n, seed=0, methods=None, n_avgs=None) -> list[dict]:
    """Every pit method x n_avg (1 and `ut.n_avg`) x condition, same geometry and seed."""
    from maek import pit

    methods = methods or pit.METHODS
    n_avgs = n_avgs or sorted({1, int(params.get(cfg, "ut.n_avg"))})
    models = _pit_models(cfg, methods)
    nb = _g(cfg, "pod_bootstrap")
    rows = []
    for c in CONDITIONS:
        for na in n_avgs:
            straight, _, lab = ut.make_dataset(cfg, n, seed, c, n_avg=na)
            hits = pit_detections(cfg, straight, lab, methods, models)
            for m in methods:
                rows.append({"method": m, "n_avg": na, "condition": c,
                             "extra_time_s": ut.averaging_time_s(cfg, na),
                             **_pit_metrics(lab, *hits[m], nb, seed)})
    return rows


def pit_dr_validation(cfg, n, methods=None, n_avgs=None) -> list[dict]:
    """Method selection set: held-out domain-randomised A-scans (not train, not shifted).

    Same `ut.pit.dr_*` ranges as the classifier's training data but its own seed
    (`ut.pit.dr_seed` + 100), one set per n_avg. The default detector is chosen on this
    table; the shifted set stays a pure test set.
    """
    from maek import pit

    methods = methods or pit.METHODS
    n_avgs = n_avgs or sorted({1, int(params.get(cfg, "ut.n_avg"))})
    models = _pit_models(cfg, methods)
    rows = []
    for na in n_avgs:
        c = _with(cfg, "ut.pit.dr_n_avg_choices", [na])
        sig, lab = pit.make_dr_dataset(c, n, int(params.get(cfg, "ut.pit.dr_seed")) + 100)
        lab = lab.assign(n_avg=na)
        hits = pit_detections(cfg, sig, lab, methods, models)
        for m in methods:
            r = _pit_metrics(lab, *hits[m], 0, 0)
            rows.append({"method": m, "n_avg": na, "n": n,
                         **{k: r[k] for k in ("pit_detection_rate", "pit_false_alarm_rate",
                                              "pit_depth_mae_mm")}})
    return rows


def pit_dr_coverage(cfg, n, seed=0, n_avgs=None) -> list[dict]:
    """Shifted test with a classifier trained on DR ranges that do / do not cover shifted.

    'default' uses `ut.pit.dr_*`; 'narrow' replaces them by `eval.pit_narrow_dr` (noise,
    coupling, temperature ranges below shifted). Each with and without the CFAR gate.
    """
    from maek import pit

    narrow = cfg
    for k, v in _g(cfg, "pit_narrow_dr").items():
        narrow = _with(narrow, "ut.pit." + k, v)
    models = {"default": pit.get_model(cfg), "narrow": pit.get_model(narrow)}
    n_avgs = n_avgs or sorted({1, int(params.get(cfg, "ut.n_avg"))})
    rows = []
    for na in n_avgs:
        straight, _, lab = ut.make_dataset(cfg, n, seed, "shifted", n_avg=na)
        temps = ut.analysis_temps(cfg, lab)
        res = {(m, g): [] for m in models for g in (True, False)}
        for s, w, t in zip(straight, lab["wall_mm"], temps):
            a = pit.analyse(cfg, s, w, t)
            for (m, g), out in res.items():
                out.append(pit.detect_learned(cfg, a, models[m], na, gate=g)["found"])
        pm = lab["pit_depth_mm"].to_numpy() > 0
        for (m, g), f in res.items():
            f = np.array(f)
            rows.append({"dr_ranges": m, "gate": g, "n_avg": na, "n": n,
                         "pit_detection_rate": float(f[pm].mean()),
                         "pit_false_alarm_rate": float(f[~pm].mean())})
    return rows


def pit_factors(cfg, n, seed=0, detectors=None) -> list[dict]:
    """Pit detection with one shifted factor at a time (per-factor diagnosis).

    detectors: (label, method, n_avg); default old baseline, mf_cfar and the default
    detector, each at 1 shot and at `ut.n_avg`.
    """
    na = int(params.get(cfg, "ut.n_avg"))
    dflt = params.get(cfg, "ut.pit.method")
    detectors = detectors or [("baseline", "baseline", 1), (dflt, dflt, 1),
                              ("baseline", "baseline", na), (dflt, dflt, na)]
    methods = sorted({m for _, m, _ in detectors})
    models = _pit_models(cfg, methods)
    rows = []
    for name, factors in PIT_FACTORS:
        c = factor_cfg(cfg, factors)
        cond = "train" if not factors else "shifted"
        for k in sorted({a for _, _, a in detectors}):
            straight, _, lab = ut.make_dataset(c, n, seed, cond, n_avg=k)
            hits = pit_detections(c, straight, lab, methods, models)
            for label, m, a in detectors:
                if a != k:
                    continue
                r = _pit_metrics(lab, *hits[m], 0, seed)
                rows.append({"factor": name, "method": label, "n_avg": a, "n": n,
                             "pit_detection_rate": r["pit_detection_rate"],
                             "pit_false_alarm_rate": r["pit_false_alarm_rate"]})
    return rows


# ------------------------------------------------------------------ strategy crack numbers
def crack_strategy(cfg, seed=0, runs=10, total_km=None) -> dict:
    """Crack detection rate of baseline / AI (old random mode / risk-ranked) triage."""
    from maek import strategy

    out = {}
    # baseline does not depend on crack_ut_mode: run it once, with the first mode only
    for name, mode in (("ai_random", "random"), ("ai_risk_ranked", "risk_ranked")):
        which = ("baseline", "ai_triage") if "baseline" not in out else ("ai_triage",)
        res = strategy.run_all(_with(cfg, "strategy.crack_ut_mode", mode), seed, runs,
                               total_km, which)
        out[name] = float(res["ai_triage"]["detection_rate_crack"].mean())
        out[name + "_ut_points"] = float(res["ai_triage"]["ut_points"].mean())
        if "baseline" in res:
            out["baseline"] = float(res["baseline"]["detection_rate_crack"].mean())
            out["baseline_ut_points"] = float(res["baseline"]["ut_points"].mean())
    return out


# ------------------------------------------------------------------ driver / reporting
def run_all(cfg, out_dir, seed=0, n_camera=None, n_ut=None, strategy_runs=10,
            n_ut_factor=None) -> dict:
    n_camera = n_camera or _g(cfg, "n_camera")
    n_ut = n_ut or _g(cfg, "n_ut")
    n_ut_factor = n_ut_factor or min(_g(cfg, "n_ut_factor"), n_ut)
    res = {"camera": {}, "ut": {}}
    for c in CONDITIONS:
        res["camera"][c] = eval_camera(cfg, c, n_camera, seed, _g(cfg, "camera_image_size"))
        res["ut"][c] = eval_ut(cfg, c, n_ut, seed)
    res["pit_ablation"] = pit_ablation(cfg, n_ut, seed)
    res["pit_factors"] = pit_factors(cfg, n_ut_factor, seed)
    res["pit_dr_validation"] = pit_dr_validation(cfg, _g(cfg, "n_pit_dr_val"))
    res["pit_dr_coverage"] = pit_dr_coverage(cfg, n_ut, seed)
    res["strategy_crack"] = crack_strategy(cfg, seed, strategy_runs)
    res["meta"] = {"seed": seed, "n_camera": n_camera, "n_ut": n_ut,
                   "n_ut_factor": n_ut_factor, "strategy_runs": strategy_runs,
                   "n_avg": int(params.get(cfg, "ut.n_avg")),
                   "pit_method": params.get(cfg, "ut.pit.method"),
                   "avg_extra_time_s": float(params.get(cfg, "ut.avg_extra_time_s"))}
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
    if "pit_ablation" in res:
        pit_ablation_frame(res).to_csv(out / "pit_ablation.csv", index=False)
        pit_pod_frame(res).to_csv(out / "pit_pod.csv", index=False)
    for k in ("pit_factors", "pit_dr_validation", "pit_dr_coverage"):
        if k in res:
            pd.DataFrame(res[k]).to_csv(out / f"{k}.csv", index=False)
    pd.DataFrame([res["strategy_crack"]]).to_csv(out / "strategy_crack.csv", index=False)
    (out / "results_tables.md").write_text(tables_markdown(res), encoding="utf-8")


def pit_ablation_frame(res) -> pd.DataFrame:
    rows = []
    for r in res["pit_ablation"]:
        p = r["pit_pod"]
        rows.append({k: v for k, v in r.items() if not isinstance(v, (dict, list))}
                    | {f"pod_{k}": p[k] for k in ("status", "b0", "b1", "a90", "a90_95")})
    return pd.DataFrame(rows)


def pit_pod_frame(res) -> pd.DataFrame:
    """Fitted POD (ln depth_mm) of the default pit detector, train and shifted."""
    m = res["meta"]
    rows = []
    for c in CONDITIONS:
        u = res["ut"][c]
        p = u["pit_pod"]
        fi = fit_pod_firth(u["pit_sizes"], u["pit_hits"])
        rows.append({"condition": c, "method": u["pit_method"], "n_avg": u["n_avg"],
                     "extra_time_s": m.get("avg_extra_time_s", float("nan")),
                     "size_unit": "mm (pit depth)", "detection_rate": u["pit_detection_rate"],
                     "false_alarm_rate": u["pit_false_alarm_rate"],
                     **{k: p[k] for k in ("n", "status", "b0", "b1", "a90", "a90_lo",
                                          "a90_95", "min_size", "max_size")},
                     "b0_firth": fi["b0"], "b1_firth": fi["b1"]})
    return pd.DataFrame(rows)


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
    if p["status"] == "no_trend":
        return f"깊이 추세 없음(hit율 {fmt(p['hit_rate'], 2)})"
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
    thk = tab(f"③ 두께 (직진 UT 에코 간격 / 피트: {u['train']['pit_method']}, "
              f"평균 {u['train']['n_avg']}회)", [
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
    parts = [cam, crk, thk, "\n".join(st)]
    if "pit_ablation" in res:
        parts += pit_tables_markdown(res)
    return "\n\n".join(parts) + "\n"


PIT_LABELS = {"baseline": "기존 규칙(min_thickness)", "mf": "정합 필터 + 기존 규칙",
              "cfar": "저면 에코 차감 + CFAR (정합 필터 없음)",
              "mf_cfar": "정합 필터 + 저면 에코 차감 + CFAR",
              "rel_amp": "정합 필터 + 저면 대비 상대 진폭(고정 0.1)",
              "shadow": "저면 에코 그늘(계면 에코 기준, 시뮬레이터 전용)",
              "learned": "학습 MLP (1~4 특징) + CFAR 게이트",
              "learned_shadow": "학습 MLP + 그늘 특징 + CFAR 게이트"}


def pit_tables_markdown(res) -> list[str]:
    """Pit ablation, per-factor diagnosis and fitted POD tables."""
    out = []
    ab = {(r["method"], r["n_avg"], r["condition"]): r for r in res["pit_ablation"]}
    keys = sorted({(m, a) for m, a, _ in ab}, key=lambda k: (k[1], list(PIT_LABELS).index(k[0])))
    head = ("| 방법 | 평균 횟수 | train 검출 | train 오경보 | train a90 | shifted 검출 "
            "| shifted 오경보 | shifted a90 | 깊이 오차 mm (train / shifted) |")
    t = ["**③ 피트 검출 방법 비교 (같은 시드·형상; 검출률 / 오경보율 / a90 [a90/95] 깊이 mm)**", "",
         head, "|---|---|---|---|---|---|---|---|---|"]
    for m, a in keys:
        tr, sh = ab[(m, a, "train")], ab[(m, a, "shifted")]
        t.append(f"| {PIT_LABELS.get(m, m)} | {a} | {fmt(tr['pit_detection_rate'])} | "
                 f"{fmt(tr['pit_false_alarm_rate'])} | {pod_cell(tr['pit_pod'])} | "
                 f"{fmt(sh['pit_detection_rate'])} | {fmt(sh['pit_false_alarm_rate'])} | "
                 f"{pod_cell(sh['pit_pod'])} | {fmt(tr['pit_depth_mae_mm'], 2)} / "
                 f"{fmt(sh['pit_depth_mae_mm'], 2)} |")
    out.append("\n".join(t))
    if "pit_factors" in res:
        fac = res["pit_factors"]
        dets = list(dict.fromkeys((r["method"], r["n_avg"]) for r in fac))
        t = ["**③ 요인 분리: shifted 요인 하나씩만 적용한 피트 검출률 (오경보율)**", "",
             "| 조건 | " + " | ".join(f"{PIT_LABELS.get(m, m)}, 평균 {a}회" for m, a in dets) + " |",
             "|---|" + "---|" * len(dets)]
        names = {"train": "train", "noise": "노이즈 3배만", "coupling": "접촉 0.3~0.7만",
                 "temperature": "고온 100~175 C + 측정 오차 15 C만",
                 "noise+coupling": "노이즈 + 접촉", "shifted": "shifted 전체"}
        for f in dict.fromkeys(r["factor"] for r in fac):
            cells = []
            for m, a in dets:
                r = next(x for x in fac if x["factor"] == f and x["method"] == m
                         and x["n_avg"] == a)
                cells.append(f"{fmt(r['pit_detection_rate'])} ({fmt(r['pit_false_alarm_rate'])})")
            t.append(f"| {names.get(f, f)} | " + " | ".join(cells) + " |")
        out.append("\n".join(t))
    if "pit_dr_validation" in res:
        dv = {(r["method"], r["n_avg"]): r for r in res["pit_dr_validation"]}
        navg = sorted({a for _, a in dv})
        t = ["**③ 방법 선택용 DR 검증 세트 (별도 시드, shifted 아님; 검출률 / 오경보율)**", "",
             "| 방법 | " + " | ".join(f"평균 {a}회" for a in navg) + " |",
             "|---|" + "---|" * len(navg)]
        for m in dict.fromkeys(m for m, _ in dv):
            t.append(f"| {PIT_LABELS.get(m, m)} | " + " | ".join(
                f"{fmt(dv[(m, a)]['pit_detection_rate'])} / "
                f"{fmt(dv[(m, a)]['pit_false_alarm_rate'])}" for a in navg) + " |")
        out.append("\n".join(t))
    if "pit_dr_coverage" in res:
        t = ["**③ 학습 분류기 외삽 점검: DR 학습 범위가 shifted를 덮지 않을 때 (shifted 검출률 / 오경보율)**",
             "", "| DR 학습 범위 | CFAR 게이트 | 평균 횟수 | 검출률 | 오경보율 |",
             "|---|---|---|---|---|"]
        for r in res["pit_dr_coverage"]:
            rng = "기본(shifted 포함)" if r["dr_ranges"] == "default" else "좁음(shifted 밖)"
            t.append(f"| {rng} | {'있음' if r['gate'] else '없음'} | {r['n_avg']} | "
                     f"{fmt(r['pit_detection_rate'])} | {fmt(r['pit_false_alarm_rate'])} |")
        out.append("\n".join(t))
    pp = pit_pod_frame(res)
    t = ["**③ 기본 피트 검출기 POD 로지스틱 계수 (POD = 1/(1+exp(-(b0 + b1 ln 깊이 mm))))**", "",
         "| 조건 | 방법 | 평균 횟수 | b0 | b1 | b0 (Firth) | b1 (Firth) | a90 [a90/95] | 상태 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in pp.to_dict("records"):
        t.append(f"| {r['condition']} | {r['method']} | {r['n_avg']} | {fmt(r['b0'])} | "
                 f"{fmt(r['b1'])} | {fmt(r['b0_firth'])} | {fmt(r['b1_firth'])} | "
                 f"{pod_cell(res['ut'][r['condition']]['pit_pod'])} | {r['status']} |")
    out.append("\n".join(t))
    return out
