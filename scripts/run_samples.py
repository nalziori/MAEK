"""Run the three deployed models on the web page's samples and compare with the recorded results.

The web page (site/try), the offline ZIP and this script use the same ONNX files and the same
site/try/data/samples.json, so all three must agree. No weight download is needed.

    python scripts/run_samples.py

Pass criteria (fixed): same number of detections, same top class, confidence within 0.02,
pitting logit within 1e-3. Needs ultralytics and onnxruntime (see docs/local-setup.md).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "try" / "data"


def sha12(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:12]


def main() -> int:
    import onnxruntime as ort
    from ultralytics import YOLO
    d = json.loads((DATA / "samples.json").read_text(encoding="utf-8"))
    pit = DATA / d["ultrasonic"]["model"]["file"]
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip() or "?"
    print(f"build {commit} · models {sha12(DATA / 'corrosion.onnx')[:6]} / {sha12(DATA / 'thermal.onnx')[:6]} / {sha12(pit)[:6]}")
    bad = 0
    for kind, task in (("corrosion", "segment"), ("thermal", "detect")):
        model = YOLO(str(DATA / d[kind]["model"]["file"]), task=task)
        for s in d[kind]["samples"]:
            r = model.predict(str(DATA / s["image"]), imgsz=640, conf=d["conf"], verbose=False)[0]
            ref, n = s["reference"], len(r.boxes)
            got = f"{n} det" + (f", {model.names[int(r.boxes.cls[0])]} {float(r.boxes.conf[0]):.3f}" if n else "")
            ok = n == ref["detections"] and (not n or (abs(float(r.boxes.conf[0]) - ref["confidence"]) <= 0.02
                                                      and ref.get("class", model.names[int(r.boxes.cls[0])]) == model.names[int(r.boxes.cls[0])]))
            bad += not ok
            print(f"{'OK  ' if ok else 'DIFF'} {kind:10s} {s['id']:16s} {'real' if s.get('source') == 'real' else 'synthetic':9s} truth={s['truth']:18s} {got}")
    u = d["ultrasonic"]
    sess = ort.InferenceSession(str(pit))
    for s in u["samples"]:
        x = ((np.asarray(s["rf"], np.float32) - u["rf_mean"]) / u["rf_std"]).astype(np.float32)[None, None]
        z = float(np.asarray(sess.run(None, {"rf": x})[0]).ravel()[0])
        ok = abs(z - s["reference"]["logit"]) <= 1e-3
        bad += not ok
        print(f"{'OK  ' if ok else 'DIFF'} ultrasonic {s['id']:16s} synthetic truth={s['truth']:18s} logit {z:.3f} -> {'pitting' if z > u['threshold_logit'] else 'normal'}")
    total = sum(len(d[k]["samples"]) for k in ("corrosion", "thermal", "ultrasonic"))
    print(f"{total - bad}/{total} samples match the recorded results")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
