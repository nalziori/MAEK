"""Two-mode v2 training: fresh optimizer/data RNG; fine-tuning has extra prior compute.

Normal runs require the frozen v2 protocol and 30 CUDA epochs. Explicit --smoke
--device cpu runs one epoch on four train/four dev fixtures and is never training
completion. No quality-index arrays, test arrays, or stress arrays are loaded.
The frozen v1 trainer/model/loader are imported, not modified.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import random
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maek.thermal_observation_data import TRAINING_SCOPE
from scripts.train_thermal_observation import (
    augment_batch,
    cache_splits,
    train_class_weights,
    weighted_ce_parts,
)

BASELINE_SHA256 = "9d6a84170f4012f5fbe187e169ca0235466ee2170c5019d381353bd8cd4dba5f"
INPUT_TRANSFORM = "asinh((reference-25)/50),asinh((current-25)/50),asinh((current-reference)/2)"
DATA_FILES = ("manifest.json", "protocol.json", "index.jsonl", "quality-index.jsonl", "validation.json", "evidence-ledger.json")
REQUIRED_SOURCES = ("maek/thermal_observation_model.py", "maek/thermal_observation_data.py",
                    "scripts/train_thermal_observation.py", "scripts/train_thermal_observation_v2.py")
TRAINING = {"epochs": 30, "batch_size": 16, "seed": 20261119,
            "learning_rate": .001, "weight_decay": .0001, "max_seconds": 1800, "device": "cuda"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def verify_protocol(data, baseline, protocol_path, smoke):
    protocol = json.loads(Path(protocol_path).read_text(encoding="utf-8-sig"))
    require(protocol.get("version") == 2 and protocol.get("scope") == TRAINING_SCOPE, "Expected v2 training scope")
    for key, value in TRAINING.items():
        require(protocol.get("training", {}).get(key) == value, f"Frozen training.{key} mismatch")
    require(set(protocol.get("data_hashes", {})) == set(DATA_FILES), "All six v2 metadata hashes are required")
    for name in DATA_FILES:
        require(sha(Path(data) / name) == protocol["data_hashes"][name], f"Data SHA256 mismatch: {name}")
    sources = protocol.get("source_hashes", {})
    require(set(REQUIRED_SOURCES) <= set(sources), "Missing training source provenance")
    for name, digest in sources.items():
        path = (ROOT / name).resolve()
        require(not Path(name).is_absolute() and path.is_relative_to(ROOT), "Source hashes require repository-relative paths")
        require(sha(path) == digest, f"Source SHA256 mismatch: {name}")
    baseline_sha = sha(baseline)
    require(baseline_sha == protocol.get("baseline", {}).get("sha256"), "Baseline SHA256 mismatch")
    require(smoke or baseline_sha == BASELINE_SHA256, "Normal runs require the pinned v1 baseline")
    index, quality = read_jsonl(Path(data) / "index.jsonl"), read_jsonl(Path(data) / "quality-index.jsonl")
    ids = [row["sample_id"] for row in index]
    require(len(ids) == len(set(ids)), "Duplicate main-index sample ID")
    require(not set(ids) & {row["sample_id"] for row in quality}, "Quality fixture leaked into main index")
    require(all(row.get("segmentation_eligible") is True for row in index), "Main index contains a non-segmentation-eligible sample")
    return protocol, baseline_sha, index, len(quality)


def state_sha256(model):
    digest = hashlib.sha256()
    for name, value in sorted(model.state_dict().items()):
        tensor = value.detach().cpu().contiguous()
        digest.update(json.dumps([name, str(tensor.dtype), list(tensor.shape)]).encode())
        digest.update(tensor.numpy().tobytes())
    return digest.hexdigest()


def initialize_model(mode, baseline, seed):
    """Load only model_state for fine-tuning; no optimizer/scheduler state survives."""
    import torch

    from maek.thermal_observation_model import ARCHITECTURE, build_model

    require(mode in ("finetune", "scratch"), "Mode must be finetune or scratch")
    checkpoint = torch.load(baseline, map_location="cpu", weights_only=True)
    require(checkpoint.get("architecture") == ARCHITECTURE, "Baseline architecture mismatch")
    require(checkpoint.get("scope") == TRAINING_SCOPE, "Baseline scope mismatch")
    require(checkpoint.get("input_transform") == INPUT_TRANSFORM, "Baseline input transform mismatch")
    torch.manual_seed(seed)
    model = build_model()
    if mode == "finetune":
        model.load_state_dict(checkpoint["model_state"], strict=True)
    require(all(torch.isfinite(value).all().item() for value in model.state_dict().values()), "Nonfinite initial model")
    return model


def save_checkpoint(path, model, *, epoch, dev_loss, weights, mode, protocol_sha, baseline_sha, smoke):
    import torch

    from maek.thermal_observation_model import ARCHITECTURE

    temporary = path.with_suffix(".tmp")
    torch.save({"model_state": {key: value.detach().cpu() for key, value in model.state_dict().items()},
                "architecture": ARCHITECTURE, "scope": TRAINING_SCOPE, "mode": mode,
                "epoch": epoch, "dev_loss": dev_loss, "class_weights": weights.tolist(),
                "experiment_protocol_sha256": protocol_sha, "baseline_sha256": baseline_sha,
                "initialization_sha256": baseline_sha if mode == "finetune" else None,
                "smoke_only": smoke, "input_channels": ["reference", "current", "difference"],
                "input_transform": INPUT_TRANSFORM}, temporary)
    temporary.replace(path)


def train(data, baseline, out, protocol_path, mode, device="cuda", smoke=False):
    import torch

    from maek.thermal_observation_model import ARCHITECTURE

    data, baseline, out, protocol_path = (Path(p).resolve() for p in (data, baseline, out, protocol_path))
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite training output: {out}")
    require(mode in ("finetune", "scratch"), "Mode must be finetune or scratch")
    require(device in ("cpu", "cuda"), "Device must be cpu or cuda")
    require((smoke and device == "cpu") or (not smoke and device == "cuda"),
            "Normal training requires CUDA; smoke requires explicit --device cpu")
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; CPU fallback is prohibited")
    protocol, baseline_sha, index, quality_count = verify_protocol(data, baseline, protocol_path, smoke)
    protocol_sha = sha(protocol_path)
    config = protocol["training"]
    epochs, batch_size, seed = (1 if smoke else config["epochs"]), config["batch_size"], config["seed"]
    started = time.perf_counter()
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.set_num_threads(1)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    caches = cache_splits(data, limit=4 if smoke else None)
    for split in ("train", "dev"):
        expected_ids = [row["sample_id"] for row in index if row["split"] == split]
        if smoke:
            expected_ids = expected_ids[:4]
        require(caches[split]["sample_ids"] == expected_ids, f"Cached {split} samples differ from the main index")
    weights_np, counts = train_class_weights(caches["train"]["targets"])
    weights = torch.from_numpy(weights_np).to(device)
    model = initialize_model(mode, baseline, seed).to(device)
    initial_state_sha = state_sha256(model)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"])
    optimizer_initial_states = len(optimizer.state)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    rng = torch.Generator().manual_seed(seed + 1)
    batch_digest, batch_count = hashlib.sha256(), 0
    out.mkdir(parents=True, exist_ok=False)
    history_path = out / "history.csv"
    history_fields = ("epoch", "train_loss", "dev_loss", "learning_rate", "seconds")
    with history_path.open("x", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=history_fields).writeheader()
    best_loss, best_epoch, epochs_completed, optimizer_steps = float("inf"), None, 0, 0
    partial_epoch, reason, failure = None, None, None

    def expired():
        return time.perf_counter() - started >= config["max_seconds"]

    def checkpoint(path, epoch, loss):
        save_checkpoint(path, model, epoch=epoch, dev_loss=loss, weights=weights_np, mode=mode,
                        protocol_sha=protocol_sha, baseline_sha=baseline_sha, smoke=smoke)

    def run_epoch(split, do_train, epoch):
        nonlocal optimizer_steps, batch_count
        cache = caches[split]
        count = len(cache["targets"])
        order = torch.randperm(count, generator=rng).numpy() if do_train else np.arange(count)
        total_numerator = total_denominator = 0.
        model.train(do_train)
        for offset in range(0, count, batch_size):
            if expired():
                return None
            indices = order[offset:offset + batch_size]
            inputs = torch.from_numpy(cache["inputs"][indices])
            targets = torch.from_numpy(cache["targets"][indices].astype(np.int64))
            if do_train:
                preview = torch.Generator()
                preview.set_state(rng.get_state())
                flips = (torch.rand((len(indices), 2), generator=preview) < .5).numpy().astype(np.uint8)
                batch_digest.update(json.dumps([epoch, offset, indices.tolist(), flips.tolist()], separators=(",", ":")).encode())
                batch_count += 1
                inputs, targets = augment_batch(inputs, targets, rng)
            inputs, targets = inputs.to(device), targets.to(device)
            with torch.set_grad_enabled(do_train):
                numerator, denominator = weighted_ce_parts(model(inputs), targets, weights)
                if denominator.item() == 0:
                    continue
                loss = numerator / denominator
                if not torch.isfinite(loss).item():
                    raise FloatingPointError(f"Nonfinite {split} loss")
                if do_train:
                    optimizer.zero_grad(set_to_none=True)
                    loss.backward()
                    if not all(p.grad is not None and torch.isfinite(p.grad).all().item() for p in model.parameters()):
                        raise FloatingPointError("Nonfinite or missing training gradient")
                    optimizer.step(); optimizer_steps += 1
            total_numerator += float(numerator.detach()); total_denominator += float(denominator.detach())
            if expired():
                return None
        require(total_denominator > 0, f"No supervised pixels in {split}")
        return total_numerator / total_denominator

    try:
        for epoch in range(1, epochs + 1):
            if expired():
                reason = "time_budget"; break
            partial_epoch = epoch
            learning_rate = optimizer.param_groups[0]["lr"]
            train_loss = run_epoch("train", True, epoch)
            dev_loss = run_epoch("dev", False, epoch) if train_loss is not None else None
            if train_loss is None or dev_loss is None:
                reason = "time_budget"; break
            epochs_completed, partial_epoch = epoch, None
            if dev_loss < best_loss:
                best_loss, best_epoch = dev_loss, epoch
                checkpoint(out / "best.pt", epoch, dev_loss)
            row = {"epoch": epoch, "train_loss": train_loss, "dev_loss": dev_loss,
                   "learning_rate": learning_rate, "seconds": time.perf_counter() - started}
            with history_path.open("a", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=history_fields).writerow(row)
            print(json.dumps(row), flush=True)
            scheduler.step()
        if reason is None and expired():
            reason = "time_budget"
    except (KeyboardInterrupt, Exception) as error:  # noqa: BLE001 - persist and re-raise below
        reason = "interrupted" if isinstance(error, KeyboardInterrupt) else "runtime_error"
        failure = error
    complete = epochs_completed == epochs and reason is None
    if not complete:
        checkpoint(out / "interrupted.pt", epochs_completed, None)
    require(sha(baseline) == baseline_sha, "Baseline changed during training")
    report = {"status": "smoke_passed" if complete and smoke else "completed" if complete else "incomplete",
              "training_completed": bool(complete and not smoke and epochs_completed == 30 and device == "cuda"),
              "smoke_only": bool(smoke), "scope": TRAINING_SCOPE, "mode": mode,
              "epochs_requested": epochs, "epochs_completed": epochs_completed, "partial_epoch": partial_epoch,
              "stop_reason": reason, "error_type": type(failure).__name__ if failure else None,
              "best_epoch": best_epoch, "best_dev_loss": best_loss if best_epoch else None,
              "optimizer_steps": optimizer_steps, "optimizer_state_reset": True,
              "optimizer_initial_state_entries": optimizer_initial_states, "scheduler_state_reset": True,
              "optimizer": {"name": "AdamW", "learning_rate": config["learning_rate"], "weight_decay": config["weight_decay"]},
              "scheduler": {"name": "CosineAnnealingLR", "T_max": epochs},
              "seed": seed, "batch_size": batch_size, "batch_plan_sha256": batch_digest.hexdigest(),
              "batch_plan_batches": batch_count,
              "batch_plan_definition": "Attempted train batches: epoch, offset, shuffled indices, previewed horizontal/vertical flip decisions from the independent generator; no model RNG used",
              "architecture": ARCHITECTURE, "class_weights": weights_np.tolist(), "train_target_counts": counts,
              "input_transform": INPUT_TRANSFORM, "baseline_sha256": baseline_sha,
              "baseline_unchanged": True, "initialization_sha256": baseline_sha if mode == "finetune" else None,
              "initial_model_state_sha256": initial_state_sha,
              "experiment_protocol_sha256": protocol_sha, "source_hashes": protocol["source_hashes"], "data_hashes": protocol["data_hashes"],
              "selection": "minimum dev weighted CE before quality gating; train-only class weights; first epoch wins ties",
              "dev_selection_quality_gate_applied": False, "data_splits_loaded": ["train", "dev"],
              "quality_index_arrays_loaded": False, "quality_index_fixture_count_excluded": quality_count,
              "holdout_arrays_loaded": False, "sample_ids": {s: c["sample_ids"] for s, c in caches.items()},
              "sample_counts": {s: len(c["targets"]) for s, c in caches.items()},
              "device": device, "gpu": torch.cuda.get_device_name(torch.cuda.current_device()) if device == "cuda" else None,
              "versions": {"torch": str(torch.__version__), "cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version(),
                           "numpy": np.__version__, "python": platform.python_version()},
              "determinism": {"seeded_data_order_and_flips": True, "cudnn_deterministic": True,
                              "bitwise_cross_platform_guarantee": False},
              "max_seconds": config["max_seconds"], "elapsed_seconds": time.perf_counter() - started,
              "budget_scope": "cache, initialization, train/dev and checkpoints; checked at batch/epoch boundaries, cannot preempt a running kernel",
              "comparison_compute_note": "Fine-tune design: existing v1 30 epochs plus v2 30 epochs; scratch design: v2 30 epochs. Additional training budgets match; total prior compute does not.",
              "smoke_note": "Smoke uses fixture weights and one CPU epoch; it does not establish full training or comparative performance." if smoke else None,
              "best_checkpoint_sha256": sha(out / "best.pt") if (out / "best.pt").exists() else None,
              "interrupted_checkpoint_sha256": sha(out / "interrupted.pt") if not complete else None,
              "history_sha256": sha(history_path), "field_validated": False, "crack_training_eligible": False,
              "resume_supported": False}
    write_json(out / "training.json", report)
    if failure:
        raise failure
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--mode", choices=("finetune", "scratch"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    report = train(args.data, args.baseline, args.out, args.protocol, args.mode, args.device, args.smoke)
    print(json.dumps({key: report[key] for key in ("mode", "status", "training_completed", "epochs_completed", "batch_plan_sha256")}))
    if report["status"] == "incomplete":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
