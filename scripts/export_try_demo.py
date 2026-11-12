"""Build the "try the models" page data (site/try/data/).

Exports the released YOLO weights to ONNX, renders fixed-seed samples with the
same generators the models were trained on, runs the reference prediction
with the exported ONNX (what the browser runs) on each, and keeps only samples whose prediction matches the truth.
The browser re-runs the ONNX models on these samples; verify-site.mjs checks
the browser result against the reference recorded here.

    python scripts/export_try_demo.py --weights models

Needs ultralytics, onnx, onnxruntime (see docs/local-setup.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "site" / "try" / "data"
PIT = ROOT / "site" / "sim" / "data"  # pitting CNN ONNX + normalisation, shared with the sim
CONF = 0.25

# How many samples of each truth label to keep, in display order.
CORROSION_PLAN = [("corrosion", 3), ("cui_sign", 2), ("leak_stain", 1), ("normal", 2)]
THERMAL_PLAN = [("steam_leak", 2), ("wet_insulation", 2), ("insulation_damage", 1), ("normal", 2)]
UT_PLAN = [("pitting", 4), ("normal", 4)]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def export_onnx(weights: Path, name: str) -> dict:
    from ultralytics import YOLO
    with tempfile.TemporaryDirectory() as tmp:
        pt = Path(tmp) / weights.name
        shutil.copy(weights, pt)
        onnx = Path(YOLO(str(pt)).export(format="onnx", imgsz=640, opset=17, simplify=True, verbose=False))
        shutil.copy(onnx, OUT / f"{name}.onnx")
    return {"file": f"{name}.onnx", "weights": weights.name, "weights_sha256": sha(weights),
            "onnx_sha256": sha(OUT / f"{name}.onnx"), "mb": round((OUT / f"{name}.onnx").stat().st_size / 1e6, 1)}


def outline(mask: np.ndarray) -> Image.Image:
    from scipy import ndimage as ndi
    edge = mask & ~ndi.binary_erosion(mask, iterations=2)
    rgba = np.zeros((*mask.shape, 4), np.uint8)
    rgba[edge] = (255, 255, 255, 255)
    return Image.fromarray(rgba)


def corrosion(cfg, onnx: Path, seed=101) -> list[dict]:
    from ultralytics import YOLO

    from maek import network
    from maek.camera import composite2d, jobs
    model = YOLO(str(onnx), task="segment")  # the exact file the browser runs (square 640 letterbox)
    names = model.names  # {0: corrosion, 1: cui_sign, 2: leak_stain}; job class_id = model id + 1
    need = dict(CORROSION_PLAN)
    got: dict[str, list] = {k: [] for k in need}
    seg, _, dfx = network.generate_network(cfg, seed)
    for i, job in enumerate(jobs.make_jobs(cfg, seg, dfx, 400, seed, condition="train")):
        ids = [d["class_id"] for d in job["defects"]]
        if len(ids) > 1:
            continue
        truth = names[ids[0] - 1] if ids else "normal"
        if len(got[truth]) >= need[truth]:
            continue
        rgb, mask = composite2d.render_job(cfg, job, np.random.default_rng([seed, i]))
        r = model.predict(rgb[..., ::-1].copy(), imgsz=640, conf=CONF, verbose=False)[0]
        n = len(r.boxes)
        if truth == "normal":
            if n:
                continue
            ref = {"detections": 0}
        else:
            if n != 1 or names[int(r.boxes.cls[0])] != truth:
                continue
            pred = r.masks.data[0].cpu().numpy() > 0.5
            pred = np.array(Image.fromarray(pred).resize(mask.shape[::-1], Image.NEAREST))
            t = mask == ids[0]
            iou = float((pred & t).sum() / max((pred | t).sum(), 1))
            if iou < 0.5:
                continue
            ref = {"detections": 1, "class": truth, "confidence": round(float(r.boxes.conf[0]), 4),
                   "box_xyxy_norm": [round(v, 4) for v in r.boxes.xyxyn[0].tolist()], "mask_iou_vs_truth": round(iou, 3)}
            outline(t).save(OUT / "corrosion" / f"c{i:03d}_truth.png")
        Image.fromarray(rgb).save(OUT / "corrosion" / f"c{i:03d}.jpg", quality=92)
        got[truth].append({"id": f"c{i:03d}", "image": f"corrosion/c{i:03d}.jpg",
                           "truth_overlay": f"corrosion/c{i:03d}_truth.png" if truth != "normal" else None,
                           "truth": truth, "job_id": job["job_id"], "reference": ref})
        if all(len(got[k]) >= v for k, v in need.items()):
            return [s for k, _ in CORROSION_PLAN for s in got[k]]
    raise SystemExit(f"corrosion: not enough matching samples {[(k, len(v)) for k, v in got.items()]}")


def thermal(cfg, onnx: Path, seed=111) -> list[dict]:
    from matplotlib import colormaps
    from scipy import ndimage as ndi
    from ultralytics import YOLO

    from maek import thermal_render as tr
    model = YOLO(str(onnx), task="detect")
    cmap = colormaps["inferno"]
    need = dict(THERMAL_PLAN)
    got: dict[str, list] = {k: [] for k in need}
    for i, job in enumerate(tr.make_ir_jobs(cfg, 400, seed, "train")):
        kinds = [d["kind"] for d in job["defects"]]
        if len(kinds) > 1:
            continue
        truth = {"tracer_leak": "wet_insulation"}.get(kinds[0], kinds[0]) if kinds else "normal"
        if len(got[truth]) >= need[truth]:
            continue
        temp, mask = tr.render_ir(cfg, job, np.random.default_rng([seed, i]))
        lo, hi = np.percentile(temp, [1, 99.5])  # same stretch + palette as the training set
        rgb = (cmap(np.clip((temp - lo) / max(hi - lo, 1e-3), 0, 1))[..., :3] * 255).astype(np.uint8)
        r = model.predict(rgb[..., ::-1].copy(), imgsz=640, conf=CONF, verbose=False)[0]
        H, W = mask.shape
        boxes = []
        if truth != "normal":
            lab, _ = ndi.label(mask > 0, np.ones((3, 3), bool))
            boxes = [[sl[1].start / W, sl[0].start / H, sl[1].stop / W, sl[0].stop / H] for sl in ndi.find_objects(lab)]
        n = len(r.boxes)
        if truth == "normal":
            if n:
                continue
            ref = {"detections": 0}
        else:
            if n != 1:
                continue
            box = r.boxes.xyxyn[0].tolist()
            iou = max(box_iou(box, b) for b in boxes)
            if iou < 0.3:
                continue
            ref = {"detections": 1, "confidence": round(float(r.boxes.conf[0]), 4),
                   "box_xyxy_norm": [round(v, 4) for v in box], "box_iou_vs_truth": round(iou, 3)}
        Image.fromarray(rgb).save(OUT / "thermal" / f"t{i:03d}.png")
        got[truth].append({"id": f"t{i:03d}", "image": f"thermal/t{i:03d}.png", "truth": truth,
                           "distractors": job["hard"],
                           "truth_boxes_norm": [[round(v, 4) for v in b] for b in boxes],
                           "temp_range_c": [round(float(lo), 1), round(float(hi), 1)],
                           "job_id": job["job_id"], "reference": ref})
        if all(len(got[k]) >= v for k, v in need.items()):
            return [s for k, _ in THERMAL_PLAN for s in got[k]]
    raise SystemExit(f"thermal: not enough matching samples {[(k, len(v)) for k, v in got.items()]}")


def box_iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = lambda q: (q[2] - q[0]) * (q[3] - q[1])
    return ix / (area(a) + area(b) - ix)


def ultrasonic(cfg, seed=121) -> list[dict]:
    """A-scans from the cnn_dr training generator (ordinary domain), scored with the shared ONNX."""
    import onnxruntime as ort

    from maek import params, ut
    meta = json.loads((PIT / "ascan.json").read_text(encoding="utf-8"))
    sess = ort.InferenceSession(str(PIT / "pitting_cnn.onnx"))
    need = dict(UT_PLAN)
    got: dict[str, list] = {k: [] for k in need}
    rng = np.random.default_rng(seed)
    for i in range(400):
        pit = i % 2 == 0
        truth = "pitting" if pit else "normal"
        wall = rng.uniform(3, 16)
        depth = wall * rng.uniform(.1, .6) if pit else 0.
        area = rng.uniform(.1, .5) if pit else 0.
        temperature, coupling = rng.uniform(10, 80), rng.uniform(.7, 1)
        varied = params.with_values(cfg, {
            "ut.v_long": params.get(cfg, "ut.v_long") + rng.uniform(-70, 70),
            "ut.probe_freq_mhz": params.get(cfg, "ut.probe_freq_mhz") * rng.uniform(.9, 1.1),
            "ut.pulse_sigma_us": params.get(cfg, "ut.pulse_sigma_us") * rng.uniform(.85, 1.15),
            "ut.interface_delay_us": params.get(cfg, "ut.interface_delay_us") + rng.uniform(-.03, .03)})
        rf = ut.simulate_straight(varied, rng, wall, depth, area, temperature, coupling, 1, 16)
        rf = rf.astype(np.float16).astype(np.float32)
        if len(got[truth]) >= need[truth]:
            continue
        x = ((rf - meta["rf_mean"]) / meta["rf_std"]).astype(np.float32)[None, None]
        z = float(np.asarray(sess.run(None, {"rf": x})[0]).ravel()[0])
        if (z > meta["threshold_logit"]) != pit:
            continue
        got[truth].append({"id": f"u{i:03d}", "truth": truth, "wall_mm": round(wall, 2),
                           "pit_depth_mm": round(depth, 2), "pit_area_fraction": round(area, 3),
                           "temperature_c": round(temperature, 1),
                           "rf": [round(float(v), 5) for v in rf], "reference": {"logit": round(z, 4)}})
        if all(len(got[k]) >= v for k, v in need.items()):
            order = [s for k, _ in UT_PLAN for s in got[k]]
            return order[::4] + order[1::4] + order[2::4] + order[3::4]  # interleave pitting / normal
    raise SystemExit(f"ultrasonic: not enough matching samples {[(k, len(v)) for k, v in got.items()]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--weights", type=Path, required=True)
    a = ap.parse_args()
    from maek.params import load_config
    cfg = load_config()
    shutil.rmtree(OUT, ignore_errors=True)
    for sub in ("corrosion", "thermal"):
        (OUT / sub).mkdir(parents=True)
    e4, ir = a.weights / "best.pt", a.weights / "sim_pipe_yolov8s_640_S.pt"
    meta = json.loads((PIT / "ascan.json").read_text(encoding="utf-8"))
    result = {
        "conf": CONF,
        "corrosion": {"model": export_onnx(e4, "corrosion"), "classes": ["corrosion", "cui_sign", "leak_stain"],
                      "samples": corrosion(cfg, OUT / "corrosion.onnx")},
        "thermal": {"model": export_onnx(ir, "thermal"), "classes": ["hot_spot"], "samples": thermal(cfg, OUT / "thermal.onnx")},
        "ultrasonic": {"model": {"file": "../../sim/data/pitting_cnn.onnx", "onnx_sha256": sha(PIT / "pitting_cnn.onnx"),
                                 "mb": round((PIT / "pitting_cnn.onnx").stat().st_size / 1e6, 1)},
                       "rf_mean": meta["rf_mean"], "rf_std": meta["rf_std"], "threshold_logit": meta["threshold_logit"],
                       "sampling_mhz": 100, "samples": ultrasonic(cfg)},
    }
    (OUT / "samples.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    for k in ("corrosion", "thermal", "ultrasonic"):
        print(k, result[k]["model"].get("mb"), "MB,", [s["truth"] for s in result[k]["samples"]])


if __name__ == "__main__":
    main()
