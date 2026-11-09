"""Turn a Roboflow YOLOv8 export into a MAEK fine-tuning set: every class -> corrosion (0).

Writes OUT/{train,valid,test}/{images,labels} (images symlinked, copied if links are not allowed),
train subsets (random.Random(seed)) plus the full train split, and ds_<n>.yaml with the MAEK class
names, validating on the export's valid split. The test split is for the final check only:

    python scripts/prep_real_finetune.py --src Corrosion-Instance-Segmentation-3 --out rc
    python scripts/eval_real_photos.py --images rc/test/images --map 0=corrosion ...
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
from pathlib import Path

import yaml

NAMES = {0: "corrosion", 1: "cui_sign", 2: "leak_stain"}


def link(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    try:
        os.symlink(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", required=True, help="Roboflow YOLOv8 export (train/valid/test)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sizes", default="50,200", help="train subset sizes; the full split is always added")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    src, dst = Path(a.src).resolve(), Path(a.out).resolve()
    for s in ("train", "valid", "test"):
        if not (src / s / "images").is_dir():
            continue
        (dst / s / "images").mkdir(parents=True, exist_ok=True)
        (dst / s / "labels").mkdir(parents=True, exist_ok=True)
        for im in (src / s / "images").iterdir():
            link(im, dst / s / "images" / im.name)
            lab = src / s / "labels" / f"{im.stem}.txt"
            rows = [r.split() for r in lab.read_text().splitlines()] if lab.exists() else []
            (dst / s / "labels" / f"{im.stem}.txt").write_text(
                "".join("0 " + " ".join(r[1:]) + "\n" for r in rows if len(r) >= 5))
    train = sorted(str(p) for p in (dst / "train" / "images").iterdir())
    valid = sorted(str(p) for p in (dst / "valid" / "images").iterdir())
    (dst / "valid.txt").write_text("\n".join(valid) + "\n")
    rng = random.Random(a.seed)
    for n in [int(x) for x in a.sizes.split(",") if int(x) < len(train)] + [len(train)]:
        tag = "all" if n == len(train) else str(n)
        (dst / f"train_{tag}.txt").write_text("\n".join(sorted(rng.sample(train, n))) + "\n")
        with open(dst / f"ds_{tag}.yaml", "w", encoding="utf-8") as f:
            yaml.safe_dump({"path": str(dst), "train": f"train_{tag}.txt", "val": "valid.txt", "names": NAMES},
                           f, sort_keys=False)
    print(f"{len(train)} train / {len(valid)} valid -> {sorted(p.name for p in dst.glob('ds_*.yaml'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
