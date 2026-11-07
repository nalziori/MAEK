"""Defect-level evaluation of a camera segmenter (HSV baseline or YOLO-seg) on a rendered dataset.

Same yardstick as `maek.evaluate.eval_camera` (defect hit = recall over the defect's own visible
pixels >= eval.seg_hit_recall), extended to all three classes, any dataset folder, and per-condition
breakdowns. Per-defect ids are re-rendered from jobs.json (render_job is deterministic for rng
[seed, i]); the images the model sees are the files on disk, so JPEG artefacts are kept.

    python scripts/eval_camera_seg.py --data release/camera/shifted --seed 101 --method hsv --out out/hsv
    python scripts/eval_camera_seg.py --data release/camera/shifted --seed 101 --method yolo \
        --weights best.pt --out out/e20

Seeds of the data-v3 release (scripts/produce_data.py --seed 1): train 1, shifted 101.
Outputs in --out: summary.csv (per class), by_condition.csv (per class x env-factor quartile),
defects.csv (one row per defect, with a contrast score), images.csv, summary.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maek import params
from maek.camera import CLASSES, composite2d, jobs, segment
from maek.evaluate import pod_summary

ENV = ("brightness", "dust", "steam", "blur_sigma", "noise_sigma")


def _g(cfg, k):
    return params.get(cfg, f"eval.{k}")


def image_path(data: Path, jid: str) -> Path:
    for ext in ("jpg", "png"):
        p = data / "images" / f"{jid}.{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(f"no image for {jid} in {data / 'images'}")


def hsv_predictor(cfg):
    args = (tuple(_g(cfg, "seg_hue_range_deg")), _g(cfg, "seg_sat_min"), _g(cfg, "seg_val_min"))

    def predict(rgb):
        return segment.segment_rust(rgb, *args).astype(np.uint8)  # class 1 only
    return predict


def yolo_predictor(weights, conf, imgsz, device):
    from ultralytics import YOLO

    model = YOLO(weights)

    def predict(rgb):
        r = model.predict(rgb[..., ::-1].copy(), conf=conf, imgsz=imgsz, device=device,
                          retina_masks=True, verbose=False)[0]
        out = np.zeros(rgb.shape[:2], np.uint8)
        if r.masks is None:
            return out
        m = r.masks.data.cpu().numpy() > 0.5
        cls = r.boxes.cls.cpu().numpy().astype(int) + 1  # yolo 0..2 -> mask classes 1..3
        for k in np.argsort(r.boxes.conf.cpu().numpy()):  # highest confidence painted last
            out[m[k]] = cls[k]
        return out
    return predict


def contrast(rgb, win, any_def, r=6):
    """Colour distance between a defect and its surrounding ring, in units of ring noise."""
    x = rgb.astype(np.float32) / 255.0
    ring = segment.dilate(win, r) & ~any_def
    if win.sum() < 4 or ring.sum() < 16:
        return float("nan")
    d = np.linalg.norm(x[win].mean(0) - x[ring].mean(0))
    return float(d / max(x[ring].std(0).mean(), 1e-3))


def evaluate(cfg, data: Path, seed: int, predict, split=None, check=3):
    js = jobs.load_jobs(data / "jobs.json")
    keep = None
    if split:
        keep = {Path(s).stem for s in (data / f"{split}.txt").read_text().split()}
    hit_rec, min_px = _g(cfg, "seg_hit_recall"), _g(cfg, "seg_min_pred_px")
    drows, irows = [], []
    inter = {c: 0 for c in (1, 2, 3)}
    union = {c: 0 for c in (1, 2, 3)}
    for i, job in enumerate(js):
        jid = job["job_id"]
        if keep is not None and jid not in keep:
            continue
        _, mask, ids = composite2d.render_job(cfg, job, np.random.default_rng([seed, i]),
                                              return_ids=True)
        mp = data / "masks" / f"{jid}.png"
        if check and mp.exists():
            if not np.array_equal(mask, np.array(Image.open(mp))):
                raise ValueError(f"re-rendered mask != {mp}: wrong --seed?")
            check -= 1
        rgb = np.array(Image.open(image_path(data, jid)).convert("RGB"))
        pred = predict(rgb)
        env = {k: job["env"][k] for k in ENV}
        any_def = mask > 0
        for c in (1, 2, 3):
            inter[c] += int(((pred == c) & (mask == c)).sum())
            union[c] += int(((pred == c) | (mask == c)).sum())
        irows.append({"job_id": jid, **env,
                      **{f"gt_{CLASSES[c]}": bool((mask == c).any()) for c in (1, 2, 3)},
                      **{f"pred_px_{CLASSES[c]}": int((pred == c).sum()) for c in (1, 2, 3)}})
        for k, d in enumerate(job["defects"]):
            win = ids == k + 1
            n = int(win.sum())
            if n < 4:  # hidden by the pipe edge / a later defect
                continue
            c = d["class_id"]
            rec = float((pred[win] == c).mean())
            drows.append({"job_id": jid, "k": k, "class": CLASSES[c], "area_cm2": d["area_cm2"],
                          "n_px": n, "recall": rec, "recall_any_class": float((pred[win] > 0).mean()),
                          "hit": rec >= hit_rec, "contrast": contrast(rgb, win, any_def), **env})
    dfd, dfi = pd.DataFrame(drows), pd.DataFrame(irows)
    rows = []
    for c in (1, 2, 3):
        name = CLASSES[c]
        sub = dfd[dfd["class"] == name]
        neg = dfi[~dfi[f"gt_{name}"]]
        pos = dfi[dfi[f"gt_{name}"]]
        ps = pod_summary(sub["area_cm2"], sub["hit"], _g(cfg, "pod_bootstrap"), 0) if len(sub) else {}
        rows.append({"class": name, "n_defects": len(sub),
                     "hit_rate": sub["hit"].mean() if len(sub) else np.nan,
                     "hit_rate_any_class": (sub["recall_any_class"] >= hit_rec).mean() if len(sub) else np.nan,
                     "image_detect": (pos[f"pred_px_{name}"] >= min_px).mean() if len(pos) else np.nan,
                     "false_alarm": (neg[f"pred_px_{name}"] >= min_px).mean() if len(neg) else np.nan,
                     "pixel_iou": inter[c] / union[c] if union[c] else np.nan,
                     "a90_cm2": ps.get("a90", np.nan), "pod_status": ps.get("status", "")})
    summary = pd.DataFrame(rows)
    by = []
    for f in ENV:
        if dfd.empty:
            break
        bins = pd.qcut(dfd[f], 4, duplicates="drop")
        g = dfd.groupby(["class", bins], observed=True)["hit"].agg(["mean", "size"]).reset_index()
        g = g.rename(columns={f: "bin", "mean": "hit_rate", "size": "n"})
        g.insert(1, "factor", f)
        g["bin"] = g["bin"].astype(str)
        by.append(g)
    by_cond = pd.concat(by, ignore_index=True) if by else pd.DataFrame()
    return summary, by_cond, dfd, dfi


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", required=True, help="dataset folder with jobs.json and images/")
    ap.add_argument("--seed", type=int, required=True, help="render seed (data-v3: train 1, shifted 101)")
    ap.add_argument("--method", choices=("hsv", "yolo"), required=True)
    ap.add_argument("--weights")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default=None)
    ap.add_argument("--split", choices=("train", "val"), default=None,
                    help="only images listed in train.txt / val.txt (default: all)")
    ap.add_argument("--config", default=str(ROOT / "config" / "default.yaml"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    cfg = params.load_config(a.config, [])
    if a.method == "yolo" and not a.weights:
        ap.error("--weights is required for --method yolo")
    predict = hsv_predictor(cfg) if a.method == "hsv" else yolo_predictor(a.weights, a.conf, a.imgsz, a.device)
    summary, by_cond, dfd, dfi = evaluate(cfg, Path(a.data), a.seed, predict, a.split)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out / "summary.csv", index=False)
    by_cond.to_csv(out / "by_condition.csv", index=False)
    dfd.to_csv(out / "defects.csv", index=False)
    dfi.to_csv(out / "images.csv", index=False)
    (out / "summary.json").write_text(json.dumps(
        {"args": vars(a), "n_images": len(dfi), "classes": summary.to_dict("records")},
        indent=1, default=float), encoding="utf-8")
    pd.set_option("display.width", 160)
    print(summary.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
