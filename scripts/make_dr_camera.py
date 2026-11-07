"""Domain-randomised (DR) camera dataset: wider lighting/dust/steam/blur/noise + rare-class oversampling.

Renders a YOLO-seg dataset like the data-v3 release but with environment ranges wider than the
train condition and more images showing cui_sign / leak_stain. Use one seed for a DR training set
and a different seed for a DR validation set (model selection); keep data-v3 `shifted` as the
untouched final test.

    python scripts/make_dr_camera.py --out dr_train --n 3000 --seed 11 --workers 2
    python scripts/make_dr_camera.py --out dr_val   --n 600  --seed 12 --workers 2
    python scripts/eval_camera_seg.py --data dr_val --seed 12 --method yolo --weights best.pt --out out/dr_val

The default ranges are a superset of both train and shifted ranges in config/default.yaml. Report
that the training ranges cover the test ranges (the shifted set itself is never used for training).
--seed is both the network seed and the render seed, so it is also the --seed for eval_camera_seg.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maek import network, params  # noqa: E402
from maek.camera import composite2d, jobs  # noqa: E402

WIDE = {"brightness_range": [0.2, 1.6], "dust_opacity_range": [0.0, 0.8],
        "steam_opacity_range": [0.0, 0.9], "blur_sigma_range": [0.0, 4.0],
        "noise_sigma_range": [0.0, 0.1]}
SHORT = {"brightness": "brightness_range", "dust": "dust_opacity_range",
         "steam": "steam_opacity_range", "blur": "blur_sigma_range", "noise": "noise_sigma_range"}


def dr_config(cfg: dict, ranges: dict) -> dict:
    c = copy.deepcopy(cfg)
    for k, v in ranges.items():
        c["camera"][k]["value"] = list(v)
    return c


def oversample(js: list[dict], n: int, weights: dict[int, float], seed: int) -> list[dict]:
    """Pick n of js without replacement; a job's weight is the max weight of its defect classes."""
    w = np.array([max([1.0] + [weights.get(d["class_id"], 1.0) for d in j["defects"]]) for j in js])
    rng = np.random.default_rng([seed, 202])
    idx = np.sort(rng.choice(len(js), size=n, replace=False, p=w / w.sum()))
    out = []
    for new_i, i in enumerate(idx):
        j = dict(js[i])
        j["job_id"] = f"J{new_i:06d}"
        j["condition"] = "dr"
        out.append(j)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--seed", type=int, required=True, help="network + render seed (data-v3 used 1 / 101)")
    ap.add_argument("--pool", type=float, default=3.0, help="candidate jobs = pool * n before oversampling")
    ap.add_argument("--cui-weight", type=float, default=3.0)
    ap.add_argument("--leak-weight", type=float, default=4.0)
    ap.add_argument("--set", action="append", default=[], metavar="NAME=LO,HI",
                    help="override a range: brightness, dust, steam, blur, noise (e.g. dust=0,0.6)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--config", default=str(ROOT / "config" / "default.yaml"))
    a = ap.parse_args(argv)
    if a.seed in (1, 101):
        ap.error("seeds 1 and 101 are the data-v3 train/shifted seeds; use another seed")
    ranges = dict(WIDE)
    for s in a.set:
        name, val = s.split("=")
        lo, hi = (float(x) for x in val.split(","))
        ranges[SHORT[name]] = [lo, hi]
    cfg = dr_config(params.load_config(a.config, []), ranges)
    seg, _, dfx = network.generate_network(cfg, a.seed)
    pool = jobs.make_jobs(cfg, seg, dfx, int(a.pool * a.n), a.seed, condition="train")
    js = oversample(pool, a.n, {2: a.cui_weight, 3: a.leak_weight}, a.seed)
    out = Path(a.out)
    composite2d.render_all(cfg, js, out, a.seed, image_format="jpg", jpg_quality=92,
                           workers=a.workers, relative_yaml=True)
    jobs.save_jobs(out / "jobs.json", js)
    counts = {c: sum(d["class_id"] == c for j in js for d in j["defects"]) for c in (1, 2, 3)}
    meta = {"args": vars(a), "ranges": ranges, "n_images": len(js),
            "negatives": sum(j["negative"] for j in js), "defects_by_class": counts}
    (out / "dr_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
