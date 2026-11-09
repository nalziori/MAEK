"""One CPU optimizer step to check data compatibility, not model performance.

Requires a hash-bound, independently validated synthetic observation dataset.
Only training samples are loaded; no weights, predictions or accuracy are saved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261108


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_smoke(data):
    # Optional training dependency stays out of module import and --help.
    import numpy as np
    import torch

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from maek.thermal_observation_data import TRAINING_SCOPE, ThermalObservationDataset

    torch.set_num_threads(1)
    torch.manual_seed(SEED)
    dataset = ThermalObservationDataset(data, "train")
    positive, stable = [], []
    scanned = []
    for sample in dataset:
        scanned.append(sample["sample_id"])
        target = sample["target"]
        if np.any(target == 1):
            if len(positive) < 2:
                positive.append(sample)
        elif np.any(target == 0) and len(stable) < 2:
            stable.append(sample)
        if len(positive) == len(stable) == 2:
            break
    if len(positive) != 2 or len(stable) != 2:
        raise ValueError("Smoke batch requires two positive and two no-resolved-change train samples")
    samples = [stable[0], positive[0], stable[1], positive[1]]
    inputs = torch.from_numpy(np.stack([s["input"] for s in samples])).to("cpu")
    targets = torch.from_numpy(np.stack([s["target"] for s in samples]).astype(np.int64)).to("cpu")
    assert inputs.ndim == 4 and inputs.shape[:2] == (4, 3)
    assert targets.shape == (4, *inputs.shape[2:])
    assert torch.isfinite(inputs).all().item()
    model = torch.nn.Sequential(
        torch.nn.Conv2d(3, 8, kernel_size=3, padding=1),
        torch.nn.ReLU(),
        torch.nn.Conv2d(8, 2, kernel_size=1),
    ).to("cpu")
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    criterion = torch.nn.CrossEntropyLoss(ignore_index=255)
    before = [parameter.detach().clone() for parameter in model.parameters()]
    model.train()
    optimizer.zero_grad(set_to_none=True)
    logits = model(inputs)
    loss = criterion(logits, targets)
    assert torch.isfinite(loss).item(), "Nonfinite smoke loss"
    loss_before = float(loss.detach())
    loss.backward()
    parameters = list(model.parameters())
    assert all(p.grad is not None and torch.isfinite(p.grad).all().item() for p in parameters)
    assert any(torch.count_nonzero(p.grad).item() for p in parameters)
    optimizer.step()
    assert all(torch.isfinite(p).all().item() for p in parameters)
    changed = sum(not torch.equal(old, new.detach()) for old, new in zip(before, parameters))
    assert changed > 0, "Optimizer did not update any parameter tensors"
    root = Path(data).resolve()
    return {
        "status": "passed", "purpose": "data_pipeline_compatibility_only",
        "scope": TRAINING_SCOPE, "data_split": "train", "seed": SEED,
        "device": "cpu", "torch_num_threads": torch.get_num_threads(),
        "batch_selection": "First two with target1 and first two with target0 but no target1; target-only selection in index order",
        "sample_ids": [s["sample_id"] for s in samples],
        "base_scene_ids": [s["base_scene_id"] for s in samples],
        "train_samples_scanned": scanned,
        "input_shape": list(inputs.shape), "target_shape": list(targets.shape),
        "logits_shape": list(logits.shape), "input_dtype": str(inputs.dtype),
        "target_counts": {str(k): int((targets == k).sum()) for k in (0, 1, 255)},
        "loss_before": loss_before, "loss": "CrossEntropyLoss(ignore_index=255)",
        "model": "Conv2d(3,8,3,padding=1),ReLU,Conv2d(8,2,1)",
        "optimizer": "Adam(lr=0.001)", "step_count": 1,
        "parameter_tensors_updated": changed, "finite_gradients": True,
        "training_completed": False, "accuracy_evaluated": False,
        "holdout_samples_loaded": 0, "weights_saved": False,
        "manifest_sha256": sha(root / "manifest.json"),
        "protocol_sha256": sha(root / "protocol.json"),
        "index_sha256": sha(root / "index.jsonl"),
        "validation_sha256": sha(root / "validation.json"),
        "script_sha256": sha(__file__),
        "versions": {"torch": torch.__version__, "numpy": np.__version__,
                     "python": platform.python_version()},
        "limitations": ["One random tiny network optimizer step is not a trained model",
                        "No accuracy, runtime benchmark or field validation",
                        "No-resolved-change targets do not imply healthy pipe",
                        "No crack, wall-loss or operational safety claim"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New JSON compatibility report")
    args = parser.parse_args()
    destination = args.out.resolve()
    if destination.suffix.lower() != ".json":
        parser.error("--out must be a new JSON file")
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}")
    report = run_smoke(args.data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"status": report["status"], "step_count": 1,
                      "training_completed": False, "output": str(destination)}))


if __name__ == "__main__":
    main()
