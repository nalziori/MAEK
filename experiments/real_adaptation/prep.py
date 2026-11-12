"""Build YOLO datasets for the real-photo adaptation experiments.

corrosion: VT bridge (CC0) and Ostrava industrial (CC BY 4.0) masks -> YOLO-seg polygons, one class.
thermal:   Roboflow thermal-leak-detection-acteabot (CC BY 4.0) -> one class hot_spot (A_1..A_4),
           A_5 (uninsulated hose) dropped, grayscale -> inferno (the palette sim_pipe_S was trained on),
           split by capture session so no source image is shared between train and test.
"""
import collections
import glob
import json
import os
import re
import shutil
from pathlib import Path

import cv2
import numpy as np
from matplotlib import colormaps

ROOT = Path("/workspace/exp")
DATA = ROOT / "data"
DS = ROOT / "ds"


def polygons(binary, min_area=64, eps=1.5):
    cs, _ = cv2.findContours(binary.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cs:
        if cv2.contourArea(c) < min_area:
            continue
        c = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        if len(c) >= 3:
            out.append(c)
    return out


def corrosion_set(name, pairs):
    d = DS / "corr" / name
    for s in ("images", "labels", "masks"):
        (d / s).mkdir(parents=True, exist_ok=True)
    n_inst = 0
    for k, (img, mask) in enumerate(sorted(pairs)):
        m = cv2.imread(mask, cv2.IMREAD_COLOR).any(axis=2)
        h, w = m.shape
        stem = f"{name}_{k:04d}"
        shutil.copy(img, d / "images" / (stem + Path(img).suffix.replace(".jpeg", ".jpg")))
        cv2.imwrite(str(d / "masks" / (stem + ".png")), m.astype(np.uint8) * 255)
        lines = []
        for p in polygons(m, min_area=max(64, h * w * 2e-4)):
            lines.append("0 " + " ".join(f"{x / w:.5f} {y / h:.5f}" for x, y in p))
        n_inst += len(lines)
        (d / "labels" / (stem + ".txt")).write_text("\n".join(lines) + ("\n" if lines else ""))
    return {"images": len(pairs), "instances": n_inst}


def corrosion():
    v = glob.glob(str(DATA / "vt" / "*" / "512x512"))[0]
    o = glob.glob(str(DATA / "ostrava" / "*"))[0]
    vt = lambda s: [(f, f.replace("images_512", "mask_512").replace(".jpeg", ".png")) for f in glob.glob(f"{v}/{s}/images_512/*.jpeg")]  # noqa: E731
    os_ = lambda ss: [(f, f.replace("/images/", "/masks/").replace(".jpg", ".png")) for s in ss for f in glob.glob(f"{o}/{s}/images/*.jpg")]  # noqa: E731
    return {"vt_train": corrosion_set("vt_train", vt("Train")), "vt_test": corrosion_set("vt_test", vt("Test")),
            "os_train": corrosion_set("os_train", os_(["train"])), "os_test": corrosion_set("os_test", os_(["validation", "test"]))}


def thermal():
    cmap = colormaps["inferno"]
    src = DATA / "rf"
    items = collections.defaultdict(list)  # original id -> [(split, image path, kept boxes)]
    for sp in ("train", "valid", "test"):
        for lab in glob.glob(str(src / sp / "labels" / "*.txt")):
            base = os.path.basename(lab)[:-4]
            boxes = [l.split() for l in open(lab) if l.strip()]
            kept = [b[1:] for b in boxes if b[0] != "4"]
            items[base.split(".rf.")[0]].append((sp, str(src / sp / "images" / (base + ".jpg")), kept))
    stats = collections.Counter()
    manifest = {"pool": {}, "test": {}}
    for part in ("pool", "test"):
        for s in ("images", "labels"):
            (DS / "th" / part / s).mkdir(parents=True, exist_ok=True)
    for orig, vers in sorted(items.items()):
        if not any(v[2] for v in vers):
            stats["dropped_A5_only"] += 1
            continue
        session = re.match(r"[A-Za-z]+", orig).group(0)
        clean = [v for v in vers if v[0] != "train"]  # Roboflow augments only its train split
        if session == "A":  # held-out capture session: evaluate on un-augmented frames only
            if not clean:
                stats["A_only_augmented_unused"] += 1
                continue
            part, use = "test", clean[:1]
        else:
            part, use = "pool", vers
        files = []
        for k, (sp, img, kept) in enumerate(use):
            g = cv2.imread(img, cv2.IMREAD_GRAYSCALE)
            rgb = (cmap(g.astype(np.float32) / 255.0)[..., :3] * 255).astype(np.uint8)
            stem = f"{orig}__{k}"
            cv2.imwrite(str(DS / "th" / part / "images" / (stem + ".jpg")), rgb[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 95])
            (DS / "th" / part / "labels" / (stem + ".txt")).write_text("".join("0 " + " ".join(b) + "\n" for b in kept))
            files.append(stem)
        manifest[part][orig] = files
        stats[f"{part}_originals_{session}"] += 1
        stats[f"{part}_images"] += len(files)
    (DS / "th" / "manifest.json").write_text(json.dumps(manifest))
    return dict(stats)


if __name__ == "__main__":
    shutil.rmtree(DS, ignore_errors=True)
    out = {"corrosion": corrosion(), "thermal": thermal()}
    (ROOT / "prep.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
