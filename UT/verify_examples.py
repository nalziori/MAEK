"""Replay fixed examples for both models, without training or threshold selection."""
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np
from package_utils import verify_package

ROOT = Path(__file__).resolve().parent


def main():
    files = verify_package()
    subprocess.run([sys.executable, str(ROOT / "predict_ascan.py"), "--verify-example"],
                   check=True, cwd=ROOT)
    sys.path.insert(0, str(ROOT / "crack_cnn"))
    import torch
    from angle_crack_runtime import FrozenCrackRuntime

    torch.set_num_threads(1)
    model = FrozenCrackRuntime()
    with np.load(ROOT / "examples/crack_ascan.npz", allow_pickle=False) as data:
        if int(data["n_avg"]) != 16:
            raise ValueError("Crack model requires the frozen 16-shot acquisition setting")
        result = model.predict(
            data["RF"], nominal_wall_mm=data["nominal_wall_mm"],
            nominal_probe_angle_deg=data["nominal_probe_angle_deg"],
            measured_temp_c=data["measured_temp_c"], sampling_hz=float(data["sampling_hz"]),
            probe_frequency_hz=float(data["probe_frequency_hz"]), origin=str(data["origin"]),
            material_profile=str(data["material_profile"]),
        )
    expected = json.loads((ROOT / "examples/crack_expected.json").read_text(encoding="utf-8"))
    difference = float(np.max(np.abs(result["logits"] - expected["logits"])))
    if (difference > 2e-5 or result["gate"].tolist() != expected["gate"]
            or result["indication"].tolist() != expected["indication"]
            or not result["supported"].all()):
        raise ValueError(f"Crack example replay mismatch: {difference}")
    checked = {"passed": True, "files_checked": files, "pit_examples": 32,
               "crack_examples": len(expected["logits"]), "crack_max_logit_difference": difference,
               "new_training": False, "scope": "portability replay, not a new performance test"}
    (ROOT / "outputs").mkdir(exist_ok=True)
    (ROOT / "outputs/example_verification.json").write_text(json.dumps(checked, indent=2),
                                                           encoding="utf-8")
    print(json.dumps(checked))


if __name__ == "__main__":
    main()
