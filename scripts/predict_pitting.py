"""Run the pitting 1D-CNN (cnn_dr, ONNX export of ut_pitting_cnn_dr.pt) on UT A-scans.

Input: an .npz with "RF" shaped (N, 4096) sampled at 100 MHz, like UT/examples/ascan.npz.
Usage: python scripts/predict_pitting.py [file.npz]
"""
import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "sim" / "data"


def predict(rf):
    meta = json.loads((DATA / "ascan.json").read_text(encoding="utf-8"))
    sess = ort.InferenceSession(str(DATA / "pitting_cnn.onnx"))
    x = ((rf.astype(np.float32) - meta["rf_mean"]) / meta["rf_std"]).astype(np.float32)
    z = np.array([float(np.asarray(sess.run(None, {"rf": s[None, None]})[0]).ravel()[0]) for s in x])
    return z, z > meta["threshold_logit"]


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "UT" / "examples" / "ascan.npz"
    with np.load(path, allow_pickle=False) as a:
        rf = a["RF"]
    if rf.ndim != 2 or rf.shape[1] != 4096:
        sys.exit(f"RF must be (N, 4096) at 100 MHz, got {rf.shape}")
    z, pit = predict(rf)
    print("case  probability  result")
    for i, (zi, p) in enumerate(zip(z, pit)):
        print(f"{i:4d}  {1 / (1 + np.exp(-zi)):11.4f}  {'PITTING' if p else 'normal'}")
    print(f"{int(pit.sum())}/{len(pit)} flagged as pitting")
    if path.name == "ascan.npz":  # self-check against the logit recorded at ONNX export
        meta = json.loads((DATA / "ascan.json").read_text(encoding="utf-8"))
        assert abs(z[meta["case_index"]] - meta["expected_logit"]) < 1e-3
