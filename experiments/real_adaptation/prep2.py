"""Stage 2 data: the judges' feedback applied.

- tiles: real photos cut into 640 px tiles with 20% overlap (stride 512); each tile is 'defect' (has corrosion)
  or 'normal' (no corrosion pixel), so normal samples come from splitting, and the two can be balanced 50:50.
- severity: VT masks kept as three classes (fair / poor / severe) instead of one.
- synthetic replay + synthetic test sets, so the fine-tuned models can be checked for forgetting.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from matplotlib import colormaps

ROOT = Path("/workspace/exp")
DATA = ROOT / "data"
DS = ROOT / "ds2"
TILE, STRIDE, MAXSIDE = 640, 512, 2048
SEV = {(128, 0, 0): 0, (0, 128, 0): 1, (128, 128, 0): 2}  # fair, poor, severe (RGB)


def polygons(binary, min_area):
    cs, _ = cv2.findContours(binary.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cs:
        if cv2.contourArea(c) >= min_area:
            c = cv2.approxPolyDP(c, 1.5, True).reshape(-1, 2)
            if len(c) >= 3:
                out.append(c)
    return out


def load_pair(img, mask):
    im, m = cv2.imread(img), cv2.imread(mask)
    s = MAXSIDE / max(im.shape[:2])
    if s < 1:
        im = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    if m.shape[:2] != im.shape[:2]:
        m = cv2.resize(m, im.shape[1::-1], interpolation=cv2.INTER_NEAREST)
    return im, m


def starts(n):
    if n <= TILE:
        return [0]
    s = list(range(0, n - TILE, STRIDE)) + [n - TILE]
    return sorted(set(s))


def pairs_of(name):
    v = glob.glob(str(DATA / "vt" / "*" / "original"))[0]
    o = glob.glob(str(DATA / "ostrava" / "*"))[0]
    if name.startswith("vt"):
        s = "Train" if name == "vt_train" else "Test"
        return [(f, f"{v}/{s}/masks/{Path(f).stem}.png") for f in sorted(glob.glob(f"{v}/{s}/images/*"))]
    ss = ["train"] if name == "os_train" else ["validation", "test"]
    return [(f, f.replace("/images/", "/masks/").replace(".jpg", ".png")) for s in ss for f in sorted(glob.glob(f"{o}/{s}/images/*.jpg"))]


def tiles(name):
    d = DS / "corr" / "tiles" / name
    (d / "images").mkdir(parents=True, exist_ok=True); (d / "labels").mkdir(parents=True, exist_ok=True)
    meta = []
    for k, (img, mask) in enumerate(pairs_of(name)):
        im, m = load_pair(img, mask)
        b = m.any(axis=2)
        for y in starts(im.shape[0]):
            for x in starts(im.shape[1]):
                t, tb = im[y:y + TILE, x:x + TILE], b[y:y + TILE, x:x + TILE]
                h, w = tb.shape
                polys = polygons(tb, 100)
                if not polys and tb.any():
                    continue  # only slivers of corrosion: neither a clean normal nor a usable defect tile
                stem = f"{name}_{k:04d}_{y}_{x}"
                cv2.imwrite(str(d / "images" / (stem + ".jpg")), t, [cv2.IMWRITE_JPEG_QUALITY, 92])
                (d / "labels" / (stem + ".txt")).write_text("".join("0 " + " ".join(f"{px / w:.5f} {py / h:.5f}" for px, py in p) + "\n" for p in polys))
                meta.append({"tile": stem, "src": k, "defect": bool(polys)})
    (d / "meta.json").write_text(json.dumps(meta))
    return {"tiles": len(meta), "defect": sum(t["defect"] for t in meta), "normal": sum(not t["defect"] for t in meta)}


def full(name):
    d = DS / "corr" / "full" / name
    (d / "images").mkdir(parents=True, exist_ok=True); (d / "masks").mkdir(parents=True, exist_ok=True)
    ps = pairs_of(name)
    for k, (img, mask) in enumerate(ps):
        im, m = load_pair(img, mask)
        cv2.imwrite(str(d / "images" / f"{name}_{k:04d}.jpg"), im, [cv2.IMWRITE_JPEG_QUALITY, 95])
        cv2.imwrite(str(d / "masks" / f"{name}_{k:04d}.png"), m.any(axis=2).astype(np.uint8) * 255)
    return len(ps)


def severity(split):
    v = glob.glob(str(DATA / "vt" / "*" / "512x512"))[0]
    d = DS / "corr" / "sev" / split.lower()
    for s in ("images", "labels", "masks"):
        (d / s).mkdir(parents=True, exist_ok=True)
    px = np.zeros(3, np.int64)
    fs = sorted(glob.glob(f"{v}/{split}/images_512/*.jpeg"))
    for k, f in enumerate(fs):
        m = cv2.imread(f.replace("images_512", "mask_512").replace(".jpeg", ".png"))[..., ::-1]
        idx = np.zeros(m.shape[:2], np.uint8)
        lines = []
        for rgb, c in SEV.items():
            b = (m == np.array(rgb, np.uint8)).all(axis=2)
            idx[b] = c + 1; px[c] += int(b.sum())
            for p in polygons(b, 50):
                lines.append(f"{c} " + " ".join(f"{x / 512:.5f} {y / 512:.5f}" for x, y in p))
        shutil.copy(f, d / "images" / f"sev_{k:04d}.jpg")
        cv2.imwrite(str(d / "masks" / f"sev_{k:04d}.png"), idx)
        (d / "labels" / f"sev_{k:04d}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
    return {"images": len(fs), "pixels_fair_poor_severe": px.tolist()}


def synthetic_corrosion(name, n, seed):
    out = DS / "syn_corr" / name
    env = dict(os.environ, OMP_NUM_THREADS="1")
    for cmd in (["camera-jobs", "--n", str(n)], ["render2d"]):
        subprocess.run([sys.executable, "-m", "maek", *cmd, "--seed", str(seed), "--out", str(out)], cwd=ROOT / "MAEK", env=env, check=True, stdout=subprocess.DEVNULL)
    return len(glob.glob(str(out / "**" / "images" / "**" / "*.*"), recursive=True))


def synthetic_thermal(name, n, seed):
    """Same conversion as make_sim_yolo.py (the script that made sim_pipe_S's training set), new seeds."""
    from scipy import ndimage as ndi
    sys.path.insert(0, str(ROOT / "MAEK"))
    from maek import thermal_render as tr
    from maek.params import load_config
    cfg, cmap = load_config(), colormaps["inferno"]
    d = DS / "syn_th" / name
    (d / "images").mkdir(parents=True, exist_ok=True); (d / "labels").mkdir(parents=True, exist_ok=True)
    for i, job in enumerate(tr.make_ir_jobs(cfg, n, seed, "train")):
        temp, mask = tr.render_ir(cfg, job, np.random.default_rng([seed, i]))
        lo, hi = np.percentile(temp, [1, 99.5])
        rgb = (cmap(np.clip((temp - lo) / max(hi - lo, 1e-3), 0, 1))[..., :3] * 255).astype(np.uint8)
        H, W = mask.shape
        cv2.imwrite(str(d / "images" / f"{name}_{i:04d}.jpg"), rgb[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 95])
        lab, _ = ndi.label(mask > 0, np.ones((3, 3), bool))
        lines = [f"0 {(s[1].start + s[1].stop) / 2 / W:.6f} {(s[0].start + s[0].stop) / 2 / H:.6f} {(s[1].stop - s[1].start) / W:.6f} {(s[0].stop - s[0].start) / H:.6f}"
                 for s in ndi.find_objects(lab)]
        (d / "labels" / f"{name}_{i:04d}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
    return n


if __name__ == "__main__":
    shutil.rmtree(DS, ignore_errors=True)
    out = {"tiles": {n: tiles(n) for n in ("vt_train", "os_train")},
           "full_test": {n: full(n) for n in ("vt_test", "os_test")},
           "severity": {s: severity(s) for s in ("Train", "Test")},
           "syn_corr": {"replay": synthetic_corrosion("replay", 600, 31), "test": synthetic_corrosion("test", 200, 32)},
           "syn_th": {"replay": synthetic_thermal("replay", 600, 51), "test": synthetic_thermal("test", 200, 52)}}
    (ROOT / "prep2.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
