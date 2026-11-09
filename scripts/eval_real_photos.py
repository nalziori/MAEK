"""Check a synthetic-trained camera segmenter on real photos (public YOLO-format datasets).

Real photos have no re-renderable ground truth, so this reads the dataset's own labels: YOLO
boxes (`c cx cy w h`) or polygons (`c x1 y1 x2 y2 ...`, normalised). `--map` says which of the
dataset's class ids correspond to which MAEK class; other classes are ignored. A folder of clean
pipe photos (no defects) is passed with `--negatives` to measure false alarms only.

    python scripts/eval_real_photos.py --images roboflow_rust/test/images --map 0=corrosion \
        --method yolo --weights best.pt --vis 12 --out out/real_rust
    python scripts/eval_real_photos.py --images clean_pipes/test/images --negatives \
        --method yolo --weights best.pt --out out/real_clean

Per MAEK class (summary.csv): n_objects; detected = at least min_px predicted pixels of that class
inside the labelled region; coverage = mean fraction of the region predicted as the class (low for
boxes, which include background); hit = coverage >= eval.seg_hit_recall (meaningful for polygons);
image_detect / false_alarm as in eval_camera_seg. labels with boxes vs polygons are counted in
objects.csv (`shape`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval_camera_seg import hsv_predictor, yolo_predictor

from maek import params
from maek.camera import CLASSES

NAME_TO_ID = {v: k for k, v in CLASSES.items() if k}
EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
COLORS = np.array([[0, 0, 0], [230, 40, 40], [250, 210, 0], [0, 200, 230]], np.float32)


def read_labels(path: Path, w: int, h: int):
    """[(dataset_class, shape, mask)] for one image; boxes and polygons both become masks."""
    out = []
    if not path.exists():
        return out
    for line in path.read_text().split("\n"):
        v = line.split()
        if len(v) < 5:
            continue
        c, xs = int(v[0]), [float(x) for x in v[1:]]
        m = Image.new("L", (w, h))
        d = ImageDraw.Draw(m)
        if len(xs) == 4:
            cx, cy, bw, bh = xs
            d.rectangle([(cx - bw / 2) * w, (cy - bh / 2) * h, (cx + bw / 2) * w, (cy + bh / 2) * h],
                        fill=1)
            shape = "box"
        else:
            d.polygon([(xs[i] * w, xs[i + 1] * h) for i in range(0, len(xs) - 1, 2)], fill=1)
            shape = "polygon"
        out.append((c, shape, np.array(m, bool)))
    return out


def overlay(rgb, pred, gt_union):
    out = rgb.astype(np.float32)
    m = pred > 0
    out[m] = 0.45 * out[m] + 0.55 * COLORS[pred[m]]
    edge = gt_union & ~np.roll(gt_union, 1, 0) | gt_union & ~np.roll(gt_union, 1, 1)
    out[edge] = (255, 255, 255)
    return out.astype(np.uint8)


def evaluate(images: Path, cmap: dict[int, int], predict, negatives: bool, hit_rec: float,
             min_px: int, vis: int = 0, vis_dir: Path | None = None):
    labels = images.parent / "labels"
    orows, irows = [], []
    files = sorted(p for p in images.iterdir() if p.suffix.lower() in EXTS)
    if not files:
        raise SystemExit(f"no images in {images}")
    for n, p in enumerate(files):
        rgb = np.array(Image.open(p).convert("RGB"))
        h, w = rgb.shape[:2]
        pred = predict(rgb)
        objs = [] if negatives else [(cmap[c], s, m) for c, s, m in read_labels(labels / f"{p.stem}.txt", w, h)
                                     if c in cmap]
        for c, shape, m in objs:
            area = int(m.sum())
            if area == 0:
                continue
            cov = float((pred[m] == c).mean())
            orows.append({"image": p.name, "class": CLASSES[c], "shape": shape, "area_px": area,
                          "coverage": cov, "coverage_any_class": float((pred[m] > 0).mean()),
                          "detected": int((pred[m] == c).sum()) >= min_px, "hit": cov >= hit_rec})
        gt = {c for c, _, _ in objs}
        irows.append({"image": p.name, **{f"gt_{CLASSES[c]}": c in gt for c in (1, 2, 3)},
                      **{f"pred_px_{CLASSES[c]}": int((pred == c).sum()) for c in (1, 2, 3)}})
        if vis_dir is not None and n < vis:
            union = np.zeros((h, w), bool)
            for _, _, m in objs:
                union |= m
            Image.fromarray(np.hstack([rgb, overlay(rgb, pred, union)])).save(vis_dir / f"{p.stem}.jpg")
    dfo, dfi = pd.DataFrame(orows), pd.DataFrame(irows)
    rows = []
    for c in (1, 2, 3):
        name = CLASSES[c]
        sub = dfo[dfo["class"] == name] if len(dfo) else dfo
        pos, neg = dfi[dfi[f"gt_{name}"]], dfi[~dfi[f"gt_{name}"]]
        rows.append({"class": name, "n_objects": len(sub), "n_images_with": len(pos),
                     "detected": sub["detected"].mean() if len(sub) else np.nan,
                     "hit": sub["hit"].mean() if len(sub) else np.nan,
                     "coverage": sub["coverage"].mean() if len(sub) else np.nan,
                     "image_detect": (pos[f"pred_px_{name}"] >= min_px).mean() if len(pos) else np.nan,
                     "false_alarm": (neg[f"pred_px_{name}"] >= min_px).mean() if len(neg) else np.nan})
    return pd.DataFrame(rows), dfo, dfi


def parse_map(items: list[str]) -> dict[int, int]:
    """['0=corrosion', '2=leak_stain'] -> {0: 1, 2: 3}"""
    out = {}
    for s in items:
        k, v = s.split("=")
        if v not in NAME_TO_ID:
            raise SystemExit(f"--map target must be one of {list(NAME_TO_ID)}, got {v}")
        out[int(k)] = NAME_TO_ID[v]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--images", required=True, help="folder of images; labels in ../labels/")
    ap.add_argument("--map", action="append", default=[], metavar="ID=CLASS",
                    help="dataset class id -> corrosion | cui_sign | leak_stain (repeatable)")
    ap.add_argument("--negatives", action="store_true", help="defect-free photos: false alarms only")
    ap.add_argument("--method", choices=("hsv", "yolo"), required=True)
    ap.add_argument("--weights")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default=None)
    ap.add_argument("--vis", type=int, default=0, help="save image|prediction pairs for the first N")
    ap.add_argument("--config", default=str(ROOT / "config" / "default.yaml"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if not a.negatives and not a.map:
        ap.error("give --map ID=CLASS for labelled defects, or --negatives for clean photos")
    if a.method == "yolo" and not a.weights:
        ap.error("--weights is required for --method yolo")
    cfg = params.load_config(a.config, [])
    predict = hsv_predictor(cfg) if a.method == "hsv" else yolo_predictor(a.weights, a.conf, a.imgsz, a.device)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    vis_dir = out / "vis" if a.vis else None
    if vis_dir:
        vis_dir.mkdir(exist_ok=True)
    summary, dfo, dfi = evaluate(Path(a.images), parse_map(a.map), predict, a.negatives,
                                 params.get(cfg, "eval.seg_hit_recall"),
                                 params.get(cfg, "eval.seg_min_pred_px"), a.vis, vis_dir)
    summary.to_csv(out / "summary.csv", index=False)
    dfo.to_csv(out / "objects.csv", index=False)
    dfi.to_csv(out / "images.csv", index=False)
    print(f"{len(dfi)} images")
    print(summary.round(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
