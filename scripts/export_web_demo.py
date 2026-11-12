"""Build the model inputs/outputs shown in the web simulation (site/sim/data/).

Uses the released weights on images made by the same generators the models were trained on:
  E4 corrosion YOLO-seg  <- maek.camera.composite2d (train condition)
  thermal YOLO (sim_pipe_S) <- maek.thermal_render, p1-p99.5 stretch + inferno (make_sim_yolo.py)
  pitting CNN (cnn_dr)   <- UT/examples/ascan.npz, exported to ONNX for in-browser inference

    python scripts/export_web_demo.py --weights <dir with maek_corrosion_real_v1.pt, maek_thermal_real_v1.pt, ut_pitting_cnn_dr.pt>

Needs ultralytics, onnx, onnxruntime. Seeds are fixed; provenance goes to data/provenance.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "UT"))
OUT = ROOT / "site" / "sim" / "data"
CNN_THRESHOLD = 0.8280118107795715  # logit, ut_pitting_frozen_comparison.json cnn_dr.threshold


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def overlay(rgb, mask, color):
    from scipy import ndimage as ndi
    out = rgb.astype(np.float32).copy()
    out[mask] = out[mask] * 0.65 + np.array(color, np.float32) * 0.35
    edge = mask & ~ndi.binary_erosion(mask, iterations=3)
    out[edge] = color
    return out.clip(0, 255).astype(np.uint8)


def corrosion(cfg, weights, seed=31):
    from ultralytics import YOLO

    from maek import network
    from maek.camera import composite2d, jobs
    model = YOLO(str(weights))
    seg, _, dfx = network.generate_network(cfg, seed)
    pool = jobs.make_jobs(cfg, seg, dfx, 200, seed, condition="train")
    tried = 0
    for i, job in enumerate(pool):
        if [d["class_id"] for d in job["defects"]] != [1]:
            continue  # exactly one external-corrosion patch keeps the story simple
        tried += 1
        rgb, mask = composite2d.render_job(cfg, job, np.random.default_rng([seed, i]))
        r = model.predict(rgb[..., ::-1].copy(), imgsz=640, conf=0.25, verbose=False)[0]
        if r.masks is None or not len(r.boxes):
            continue
        k = int(r.boxes.conf.argmax())
        pred = r.masks.data[k].cpu().numpy() > 0.5
        pred = np.array(Image.fromarray(pred).resize(mask.shape[::-1], Image.NEAREST))
        truth = mask == 1
        iou = float((pred & truth).sum() / max((pred | truth).sum(), 1))
        if iou < 0.5:
            continue
        Image.fromarray(rgb).save(OUT / "rgb_input.jpg", quality=90)
        Image.fromarray(overlay(rgb, pred, (230, 40, 40))).save(OUT / "rgb_output.jpg", quality=90)
        return {"job_id": job["job_id"], "seed": seed, "index": i, "candidates_tried": tried,
                "class": r.names[int(r.boxes.cls[k])], "confidence": float(r.boxes.conf[k]),
                "mask_iou_vs_truth": iou, "box_xyxy_norm": (r.boxes.xyxyn[k].tolist())}
    raise SystemExit("E4 found no corrosion with IoU >= 0.5 in the candidate pool")


def thermal(cfg, weights, seed=41):
    from matplotlib import colormaps
    from scipy import ndimage as ndi
    from ultralytics import YOLO

    from maek import thermal_render as tr
    model = YOLO(str(weights))
    cmap = colormaps["inferno"]
    for i, job in enumerate(tr.make_ir_jobs(cfg, 200, seed, "train")):
        if [d["kind"] for d in job["defects"]] != ["steam_leak"]:
            continue
        temp, mask = tr.render_ir(cfg, job, np.random.default_rng([seed, i]))
        lo, hi = np.percentile(temp, [1, 99.5])
        rgb = (cmap(np.clip((temp - lo) / max(hi - lo, 1e-3), 0, 1))[..., :3] * 255).astype(np.uint8)
        r = model.predict(rgb[..., ::-1].copy(), imgsz=640, conf=0.25, verbose=False)[0]
        if not len(r.boxes):
            continue
        lab, _ = ndi.label(mask > 0, np.ones((3, 3), bool))
        sl = ndi.find_objects(lab)[0]
        H, W = mask.shape
        truth = [sl[1].start / W, sl[0].start / H, sl[1].stop / W, sl[0].stop / H]
        k = int(r.boxes.conf.argmax())
        box = r.boxes.xyxyn[k].tolist()
        ix = max(0, min(box[2], truth[2]) - max(box[0], truth[0])) * max(0, min(box[3], truth[3]) - max(box[1], truth[1]))
        area = lambda b: (b[2] - b[0]) * (b[3] - b[1])
        iou = ix / (area(box) + area(truth) - ix)
        if iou < 0.3:
            continue
        Image.fromarray(rgb).save(OUT / "ir_input.png")
        return {"job_id": job["job_id"], "seed": seed, "index": i, "confidence": float(r.boxes.conf[k]),
                "box_xyxy_norm": box, "truth_xyxy_norm": truth, "box_iou_vs_truth": iou,
                "temp_range_c": [float(lo), float(hi)], "size": [W, H]}
    raise SystemExit("thermal model found no steam leak in the candidate pool")


def pitting(weights):
    import onnxruntime as ort
    import torch
    from cnn_followup import checkpoint, logits
    net, ck = checkpoint(weights)
    prep = ck["preprocessing"]
    a = np.load(ROOT / "UT" / "examples" / "ascan.npz", allow_pickle=False)
    rf = a["RF"].astype(np.float32)
    z = logits(net, rf, prep)
    k = int(np.argmax(z))
    if z[k] <= CNN_THRESHOLD:
        raise SystemExit("no example A-scan above the cnn_dr threshold")
    onnx_path = OUT / "pitting_cnn.onnx"
    torch.onnx.export(net, torch.zeros(1, 1, rf.shape[1]), str(onnx_path), input_names=["rf"],
                      output_names=["logit"], opset_version=17, dynamo=False)
    sess = ort.InferenceSession(str(onnx_path))
    x = ((rf[k] - prep["rf_mean"]) / prep["rf_std"]).astype(np.float32)[None, None]
    onnx_logit = float(np.asarray(sess.run(None, {"rf": x})[0]).reshape(-1)[0])
    assert abs(onnx_logit - float(z[k])) < 1e-4, (onnx_logit, z[k])
    (OUT / "ascan.json").write_text(json.dumps({
        "rf": [round(float(v), 6) for v in rf[k]], "rf_mean": prep["rf_mean"], "rf_std": prep["rf_std"],
        "threshold_logit": CNN_THRESHOLD, "expected_logit": float(z[k]),
        "sampling_mhz": int(a["sampling_mhz"]), "case_index": k,
        "nominal_wall_mm": float(a["nominal_wall_mm"][k])}), encoding="utf-8")
    return {"case_index": k, "logit": float(z[k]), "onnx_logit": onnx_logit, "threshold_logit": CNN_THRESHOLD}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--weights", type=Path, required=True)
    a = ap.parse_args()
    from maek.params import load_config
    cfg = load_config()
    OUT.mkdir(parents=True, exist_ok=True)
    files = {"e4": a.weights / "maek_corrosion_real_v1.pt", "thermal": a.weights / "maek_thermal_real_v1.pt",
             "pitting": a.weights / "ut_pitting_cnn_dr.pt"}
    result = {"weights_sha256": {k: sha(v) for k, v in files.items()},
              "corrosion": corrosion(cfg, files["e4"]),
              "leak": thermal(cfg, files["thermal"]),
              "pitting": pitting(files["pitting"])}
    (OUT / "results.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
