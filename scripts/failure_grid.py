"""Grid of missed defects for slides: image | ground truth | prediction, one row per defect.

Needs an eval_camera_seg.py run with --save-pred. Use DR val (or train val) for pictures while
models are still being chosen; the shifted test set is looked at once, at the very end.

    python scripts/eval_camera_seg.py --data dr_val --seed 12 --method yolo --weights best.pt \
        --save-pred --out out/e2_drval
    python scripts/failure_grid.py --data dr_val --eval out/e2_drval --out e2_misses.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from eval_camera_seg import image_path
from PIL import Image

COLORS = np.array([[0, 0, 0], [230, 40, 40], [250, 210, 0], [0, 200, 230]], np.float32)


def overlay(rgb, mask):
    out = rgb.astype(np.float32)
    m = mask > 0
    out[m] = 0.45 * out[m] + 0.55 * COLORS[mask[m]]
    return out.astype(np.uint8)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data", required=True)
    ap.add_argument("--eval", required=True, help="eval_camera_seg --out folder (with pred/)")
    ap.add_argument("--per-class", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    data, ev = Path(a.data), Path(a.eval)
    if not (ev / "pred").is_dir():
        ap.error(f"{ev / 'pred'} missing: rerun eval_camera_seg.py with --save-pred")
    d = pd.read_csv(ev / "defects.csv")
    miss = d[~d["hit"]]
    rows = pd.concat([g.sample(min(len(g), a.per_class), random_state=a.seed)
                      for _, g in miss.groupby("class")]) if len(miss) else miss
    if rows.empty:
        print("no missed defects")
        return 0
    fig, axs = plt.subplots(len(rows), 3, figsize=(9, 3 * len(rows)), squeeze=False)
    for ax, (_, r) in zip(axs, rows.iterrows()):
        rgb = np.array(Image.open(image_path(data, r["job_id"])).convert("RGB"))
        gt = np.array(Image.open(data / "masks" / f"{r['job_id']}.png"))
        pred = np.array(Image.open(ev / "pred" / f"{r['job_id']}.png"))
        for x, im, t in zip(ax, (rgb, overlay(rgb, gt), overlay(rgb, pred)), ("", "truth", "pred")):
            x.imshow(im)
            x.set_title(t, fontsize=9)
            x.axis("off")
        ax[0].set_title(f"{r['job_id']} {r['class']} recall {r['recall']:.2f} any {r['recall_any_class']:.2f}\n"
                        f"contrast {r['contrast']:.2f} bright {r['brightness']:.2f} dust {r['dust']:.2f}",
                        fontsize=8, loc="left")
    fig.text(0.5, 0.995, "red corrosion | yellow cui_sign | cyan leak_stain", ha="center", va="top",
             fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.99))
    fig.savefig(a.out, dpi=110)
    print(f"{len(rows)} missed defects -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
