"""Single bounded CUDA training run, selected by dev loss, with untouched holdouts.

Normal runs require a frozen comparison protocol and all 30 epochs for completion.
--smoke permits one CPU epoch on four train/four dev samples for compatibility;
it never sets training_completed. Existing output directories are refused.
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

from maek.thermal_observation_data import TRAINING_SCOPE, ThermalObservationDataset

LEARNING_RATE = 0.001
WEIGHT_DECAY = 0.0001


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def cache_splits(root, limit=None):
    """Only train/dev arrays; the validated loader checks global index metadata."""
    caches = {}
    for split in ("train", "dev"):
        dataset = ThermalObservationDataset(root, split)
        size = min(len(dataset), limit) if limit is not None else len(dataset)
        samples = [dataset[i] for i in range(size)]
        if not samples:
            raise ValueError(f"Empty {split} split")
        caches[split] = {
            "inputs": np.stack([sample["input"] for sample in samples]),
            "targets": np.stack([sample["target"] for sample in samples]),
            "sample_ids": [sample["sample_id"] for sample in samples],
            "base_scene_ids": [sample["base_scene_id"] for sample in samples],
        }
    return caches


def train_class_weights(targets):
    counts = {str(label): int(np.count_nonzero(targets == label)) for label in (0, 1, 255)}
    if counts["0"] == 0 or counts["1"] == 0:
        raise ValueError("Training requires both resolved target classes")
    return np.array([1, min(10, counts["0"] / counts["1"])], dtype=np.float32), counts


def augment_batch(inputs, targets, generator):
    """Shared horizontal/vertical flips only; never mutate cached tensors."""
    import torch

    inputs, targets = inputs.clone(), targets.clone()
    flips = torch.rand((len(inputs), 2), generator=generator) < 0.5
    for i in range(len(inputs)):
        dims = tuple(axis for axis, flag in zip((-1, -2), flips[i]) if flag)
        if dims:
            inputs[i] = torch.flip(inputs[i], dims)
            targets[i] = torch.flip(targets[i], dims)
    return inputs, targets


def weighted_ce_parts(logits, targets, weights):
    """Numerator/denominator of standard weighted CE, with ignored pixels omitted."""
    from torch.nn import functional

    numerator = functional.cross_entropy(logits, targets, weight=weights,
                                         ignore_index=255, reduction="sum")
    valid = targets != 255
    denominator = weights[targets[valid]].sum()
    return numerator, denominator


def _check_protocol(args):
    protocol_path = getattr(args, "protocol", None)
    if protocol_path is None:
        if args.smoke:
            return None
        raise ValueError("Normal training requires --protocol frozen comparison JSON")
    protocol_path = Path(protocol_path).resolve()
    protocol = json.loads(protocol_path.read_text(encoding="utf-8-sig"))
    expected = protocol.get("training", {})
    for key in ("epochs", "batch_size", "seed", "device", "max_seconds"):
        if expected.get(key) != getattr(args, key):
            raise ValueError(f"Comparison protocol training.{key} does not match arguments")
    for key, value in (("learning_rate", LEARNING_RATE), ("weight_decay", WEIGHT_DECAY)):
        if key in expected and expected[key] != value:
            raise ValueError(f"Comparison protocol training.{key} does not match fixed optimizer")
    frozen_hashes = protocol.get("data_hashes", {})
    for name in ("manifest.json", "protocol.json", "index.jsonl", "validation.json"):
        if frozen_hashes.get(name) != sha(Path(args.data) / name):
            raise ValueError(f"Comparison protocol data SHA256 mismatch: {name}")
    return {"path": str(protocol_path), "sha256": sha(protocol_path)}


def _save_checkpoint(path, model, epoch, dev_loss, weights, comparison, smoke):
    import torch

    from maek.thermal_observation_model import ARCHITECTURE

    temporary = path.with_suffix(".tmp")
    torch.save({"model_state": {name: value.detach().cpu()
                                for name, value in model.state_dict().items()},
                "architecture": ARCHITECTURE, "scope": TRAINING_SCOPE,
                "epoch": epoch, "dev_loss": dev_loss, "class_weights": weights.tolist(),
                "comparison_protocol_sha256": comparison["sha256"] if comparison else None,
                "smoke_only": smoke, "input_channels": ["reference", "current", "difference"],
                "input_transform": "asinh((reference-25)/50),asinh((current-25)/50),asinh((current-reference)/2)"},
               temporary)
    temporary.replace(path)


def train(args):
    import torch

    from maek.thermal_observation_model import ARCHITECTURE, build_model

    out = Path(args.out).resolve()
    if out.exists():
        raise FileExistsError(f"Refusing to overwrite training output: {out}")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; CPU fallback is prohibited")
    if args.device not in ("cpu", "cuda"):
        raise ValueError("Device must be cpu or cuda")
    if not args.smoke and (args.device != "cuda" or args.epochs != 30):
        raise ValueError("Normal training requires CUDA and exactly 30 epochs")
    if args.smoke and args.epochs != 1:
        raise ValueError("Smoke runs require --epochs 1")
    if args.batch_size < 1 or args.max_seconds <= 0:
        raise ValueError("Batch size and time budget must be positive")
    comparison = _check_protocol(args)
    data = Path(args.data).resolve()
    provenance = {name: sha(data / name) for name in
                  ("protocol.json", "manifest.json", "index.jsonl", "validation.json")}
    started = time.perf_counter()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    torch.set_num_threads(1)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    # Bilinear CUDA backward may not be bitwise deterministic; seeds are fixed,
    # but cross-device/version exact numerical reproducibility is not claimed.
    caches = cache_splits(data, limit=4 if args.smoke else None)
    weights_np, counts = train_class_weights(caches["train"]["targets"])
    weights = torch.from_numpy(weights_np).to(args.device)
    model = build_model().to(args.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    rng = torch.Generator().manual_seed(args.seed + 1)
    out.mkdir(parents=True, exist_ok=False)
    history_path = out / "history.csv"
    history_fields = ("epoch", "train_loss", "dev_loss", "learning_rate", "seconds")
    with history_path.open("x", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=history_fields).writeheader()
    best_loss, best_epoch, epochs_completed, optimizer_steps = float("inf"), None, 0, 0
    partial_epoch, reason = None, None

    def expired():
        return time.perf_counter() - started >= args.max_seconds

    def run_epoch(split, do_train):
        nonlocal optimizer_steps
        cache = caches[split]
        count = len(cache["targets"])
        order = torch.randperm(count, generator=rng).numpy() if do_train else np.arange(count)
        total_numerator, total_denominator = 0.0, 0.0
        model.train(do_train)
        for offset in range(0, count, args.batch_size):
            if expired():
                return None
            indices = order[offset:offset + args.batch_size]
            inputs = torch.from_numpy(cache["inputs"][indices])
            targets = torch.from_numpy(cache["targets"][indices].astype(np.int64))
            if do_train:
                inputs, targets = augment_batch(inputs, targets, rng)
            inputs, targets = inputs.to(args.device), targets.to(args.device)
            with torch.set_grad_enabled(do_train):
                logits = model(inputs)
                numerator, denominator = weighted_ce_parts(logits, targets, weights)
                if denominator.item() == 0:
                    continue
                loss = numerator / denominator
                if not torch.isfinite(loss).item():
                    raise FloatingPointError(f"Nonfinite {split} loss")
                if do_train:
                    optimizer.zero_grad(set_to_none=True)
                    loss.backward()
                    if not all(p.grad is not None and torch.isfinite(p.grad).all().item()
                               for p in model.parameters()):
                        raise FloatingPointError("Nonfinite or missing training gradient")
                    optimizer.step()
                    optimizer_steps += 1
            total_numerator += float(numerator.detach())
            total_denominator += float(denominator.detach())
        if total_denominator == 0:
            raise ValueError(f"No supervised pixels in {split}")
        return total_numerator / total_denominator

    failure = None
    try:
        for epoch in range(1, args.epochs + 1):
            if expired():
                reason = "time_budget"
                break
            partial_epoch = epoch
            learning_rate = optimizer.param_groups[0]["lr"]
            train_loss = run_epoch("train", True)
            dev_loss = run_epoch("dev", False) if train_loss is not None else None
            if train_loss is None or dev_loss is None:
                reason = "time_budget"
                break
            epochs_completed = epoch
            partial_epoch = None
            if dev_loss < best_loss:
                best_loss, best_epoch = dev_loss, epoch
                _save_checkpoint(out / "best.pt", model, epoch, dev_loss, weights_np,
                                 comparison, args.smoke)
            row = {"epoch": epoch, "train_loss": train_loss, "dev_loss": dev_loss,
                   "learning_rate": learning_rate, "seconds": time.perf_counter() - started}
            with history_path.open("a", newline="", encoding="utf-8") as stream:
                csv.DictWriter(stream, fieldnames=history_fields).writerow(row)
            print(json.dumps(row), flush=True)
            scheduler.step()
    except (KeyboardInterrupt, Exception) as exc:  # noqa: BLE001 - persist and re-raise below
        reason = "interrupted" if isinstance(exc, KeyboardInterrupt) else "runtime_error"
        failure = exc
    complete = epochs_completed == args.epochs and reason is None
    if not complete:
        _save_checkpoint(out / "interrupted.pt", model, epochs_completed, None,
                         weights_np, comparison, args.smoke)
    status = "smoke_passed" if complete and args.smoke else "completed" if complete else "incomplete"
    report = {
        "status": status, "scope": TRAINING_SCOPE,
        "training_completed": complete and not args.smoke and epochs_completed == 30,
        "smoke_only": args.smoke, "epochs_requested": args.epochs,
        "epochs_completed": epochs_completed, "partial_epoch": partial_epoch,
        "stop_reason": reason, "error_type": type(failure).__name__ if failure else None,
        "best_epoch": best_epoch, "best_dev_loss": best_loss if best_epoch else None,
        "selection": "minimum dev weighted CE; weights from train only; first epoch wins ties",
        "optimizer_steps": optimizer_steps, "seed": args.seed, "batch_size": args.batch_size,
        "optimizer": {"name": "AdamW", "learning_rate": LEARNING_RATE, "weight_decay": WEIGHT_DECAY},
        "scheduler": {"name": "CosineAnnealingLR", "T_max": args.epochs},
        "class_weights": weights_np.tolist(), "train_target_counts": counts,
        "loss_normalization": "sum weighted CE / sum target class weights over nonignored pixels",
        "augmentation": "shared horizontal and vertical flips, training only",
        "architecture": ARCHITECTURE, "parameter_count": sum(p.numel() for p in model.parameters()),
        "initialization": "random; no pretrained or legacy three-class weights",
        "data_splits_loaded": ["train", "dev"], "holdout_arrays_loaded": False,
        "sample_counts": {split: len(cache["targets"]) for split, cache in caches.items()},
        "sample_ids": {split: cache["sample_ids"] for split, cache in caches.items()},
        "device": args.device, "torch_num_threads": torch.get_num_threads(),
        "cuda_device_index": torch.cuda.current_device() if args.device == "cuda" else None,
        "gpu": torch.cuda.get_device_name(torch.cuda.current_device()) if args.device == "cuda" else None,
        "versions": {"torch": str(torch.__version__), "cuda": torch.version.cuda,
                     "cudnn": torch.backends.cudnn.version(), "numpy": np.__version__,
                     "python": platform.python_version()},
        "determinism": {"seeds_fixed": True, "cudnn_deterministic": True,
                        "cudnn_benchmark": False,
                        "strict_deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
                        "bitwise_cross_platform_guarantee": False},
        "max_seconds": args.max_seconds, "elapsed_seconds": time.perf_counter() - started,
        "budget_scope": "cache, model initialization, training and dev; checked between batches",
        "data_hashes": provenance, "comparison_protocol": comparison,
        "source_hashes": {name: sha(ROOT / name) for name in
                          ("maek/thermal_observation_model.py", "maek/thermal_observation_data.py",
                           "scripts/train_thermal_observation.py")},
        "best_checkpoint_sha256": sha(out / "best.pt") if (out / "best.pt").exists() else None,
        "interrupted_checkpoint_sha256": sha(out / "interrupted.pt") if not complete else None,
        "history_sha256": sha(history_path),
        "field_validated": False, "crack_training_eligible": False,
        "resume_supported": False,
    }
    _write_json(out / "training.json", report)
    if failure is not None:
        raise failure
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20261109)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--max-seconds", type=float, default=1800)
    parser.add_argument("--smoke", action="store_true")
    report = train(parser.parse_args())
    print(json.dumps({key: report[key] for key in
                      ("status", "training_completed", "epochs_completed", "best_epoch")}), flush=True)
    if report["status"] == "incomplete":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
