"""Jetson benchmark helpers. Importing this module never loads CUDA or a model."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

from maek.onboard_models import summarize


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def array_hash(array):
    """Include shape and dtype so an identical byte stream cannot hide reshaping."""
    header = json.dumps([list(array.shape), str(array.dtype)]).encode()
    return hashlib.sha256(header + array.tobytes(order="C")).hexdigest()


def read_optional(path):
    try:
        return Path(path).read_text().strip().replace("\x00", "")
    except (OSError, UnicodeError):
        return None


def command_record(argv):
    if not shutil.which(argv[0]):
        return {"command": argv, "status": "unavailable"}
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15, check=False)
        return {"command": argv, "returncode": result.returncode,
                "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": argv, "error": str(exc)}


def is_target_jetson(system, machine, model, l4t):
    return (system == "Linux" and machine in {"aarch64", "arm64"}
            and "jetson orin nano" in (model or "").lower() and bool(l4t))


def probe():
    model = read_optional("/proc/device-tree/model")
    l4t = read_optional("/etc/nv_tegra_release")
    system, machine = platform.system(), platform.machine()
    versions = {}
    for name in ("torch", "torchvision", "ultralytics", "numpy", "psutil", "tensorrt"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    result = {"system": system, "machine": machine, "platform": platform.platform(),
              "python": platform.python_version(), "device_tree_model": model, "l4t": l4t,
              "target_jetson_detected": is_target_jetson(system, machine, model, l4t),
              "versions": versions,
              "nvpmodel": command_record(["nvpmodel", "-q", "--verbose"]),
              "clocks": command_record(["jetson_clocks", "--show"]),
              "jetpack_packages": command_record(["dpkg-query", "-W", "nvidia-jetpack",
                                                  "nvidia-l4t-core", "libnvinfer*"]),
              "tegrastats_path": shutil.which("tegrastats")}
    try:
        import psutil
        result["system_memory"] = {"total_mib": psutil.virtual_memory().total / 2**20,
                                   "available_mib": psutil.virtual_memory().available / 2**20,
                                   "swap_total_mib": psutil.swap_memory().total / 2**20}
    except ImportError:
        result["system_memory"] = None
    try:
        import torch
        result["torch_runtime"] = {
            "cuda_available": torch.cuda.is_available(), "cuda_build": torch.version.cuda,
            "cudnn": torch.backends.cudnn.version(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "capability": list(torch.cuda.get_device_capability(0))
            if torch.cuda.is_available() else None,
        }
    except (ImportError, OSError, RuntimeError) as exc:
        result["torch_runtime"] = {"error": str(exc)}
    try:
        import tensorrt
        result["tensorrt_runtime"] = {"version": tensorrt.__version__}
    except (ImportError, OSError, RuntimeError) as exc:
        result["tensorrt_runtime"] = {"error": str(exc)}
    return result


def validate_engine_environment(exported, current):
    """A matching manifest is necessary, not proof that an engine is portable."""
    if not exported.get("target_jetson_detected") or not current.get("target_jetson_detected"):
        raise ValueError("TensorRT export and inference must both identify a Jetson Orin Nano")
    signatures = []
    for environment in (exported, current):
        signatures.append({
            **{key: environment.get(key) for key in ("machine", "device_tree_model", "l4t")},
            "tensorrt": environment.get("tensorrt_runtime", {}).get("version"),
            "cuda_build": environment.get("torch_runtime", {}).get("cuda_build"),
            "gpu": environment.get("torch_runtime", {}).get("gpu"),
            "capability": environment.get("torch_runtime", {}).get("capability"),
        })
    missing = [key for key, value in signatures[0].items()
               if value is None or signatures[1][key] is None]
    different = [key for key in signatures[0] if signatures[0][key] != signatures[1][key]]
    if missing or different:
        raise ValueError(f"Engine build/runtime environment mismatch or unknown: {missing + different}; "
                         "rebuild on the target Jetson and save a fresh manifest")
    return {"status": "matched", "fields": signatures[0],
            "note": "Manifest match is not a portability guarantee; actual load/output checks still required"}


def timed_calls(fn, synchronize, repeats, clock=time.perf_counter):
    """CUDA completion is inside every sample, including the final inference."""
    latencies = []
    synchronize()
    start = clock()
    for i in range(repeats):
        synchronize()
        before = clock()
        fn(i)
        synchronize()
        latencies.append((clock() - before) * 1000)
    elapsed = clock() - start
    return latencies, elapsed


def measure(fn, synchronize, warmup, repeats):
    import psutil
    for i in range(warmup):
        fn(i)
        synchronize()
    process = psutil.Process()
    stop = threading.Event()
    rss, available, errors = [], [], []

    def sample_once():
        try:
            rss.append(process.memory_info().rss)
            available.append(psutil.virtual_memory().available)
        except (psutil.Error, OSError) as exc:
            errors.append(str(exc))

    def sample():
        while not stop.wait(0.01):
            sample_once()

    sample_once()
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    try:
        latencies, elapsed = timed_calls(fn, synchronize, repeats)
    finally:
        sample_once()
        stop.set()
        sampler.join()
    peak = max(rss) / 2**20 if rss and not errors else None
    stats = summarize(latencies, elapsed, peak)
    # RSS is not all shared Jetson DRAM, TensorRT allocations or system memory.
    stats.pop("pass_memory_2gib")
    return {**stats, "process_peak_rss_mib": peak,
            "system_min_available_mib": min(available) / 2**20 if available else None,
            "memory_sampling_ms": 10, "memory_errors": errors}


def segmentation_snapshot(result):
    """CPU copy of semantic mask union; no detection-order matching assumption."""
    import numpy as np
    boxes = result.boxes.data.detach().float().cpu().numpy()
    masks = None if result.masks is None else result.masks.data.detach().float().cpu().numpy()
    if not np.isfinite(boxes).all() or (masks is not None and not np.isfinite(masks).all()):
        raise RuntimeError("Nonfinite segmentation output")
    if len(boxes) and (masks is None or len(masks) != len(boxes)):
        raise RuntimeError("Boxes and segmentation masks disagree")
    unions = {}
    for index, box in enumerate(boxes):
        cls = int(box[-1])
        mask = masks[index] > 0.5
        unions[cls] = mask if cls not in unions else unions[cls] | mask
    return {"boxes": boxes, "unions": unions}


def compare_segmentations(reference, candidate):
    import numpy as np
    scores = {}
    for cls in sorted(set(reference["unions"]) | set(candidate["unions"])):
        a, b = reference["unions"].get(cls), candidate["unions"].get(cls)
        if a is None or b is None:
            scores[str(cls)] = 0.0
        elif a.shape != b.shape:
            raise ValueError("Mask shapes differ; comparison preprocessing is inconsistent")
        else:
            union = np.count_nonzero(a | b)
            scores[str(cls)] = float(np.count_nonzero(a & b) / union) if union else 1.0
    return {"reference_detections": len(reference["boxes"]),
            "candidate_detections": len(candidate["boxes"]), "class_union_iou": scores,
            "both_empty": not len(reference["boxes"]) and not len(candidate["boxes"])}


def validate_collection(rows):
    """Reject mixed input/protocol runs and incomplete three-process comparisons."""
    if not rows:
        raise ValueError("No worker JSON files found")
    groups = {}
    for row in rows:
        if row.get("schema") != "maek-jetson-v1" or not row["environment"]["target_jetson_detected"]:
            raise ValueError("Only genuine Jetson worker results may be collected")
        key = (row["model"], row["backend"], row["device"], row["precision"], row["size"])
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        if sorted(r["run"] for r in group) != [1, 2, 3]:
            raise ValueError("Each configuration requires exactly runs 1, 2, 3")
        identities = {json.dumps({key: row[key] for key in
                      ("input_hashes", "archive_sha256", "weights_sha256", "engine_sha256",
                       "protocol", "code_sha256")}, sort_keys=True) for row in group}
        if len(identities) != 1:
            raise ValueError("Input, weights, source or protocol drift between fresh processes")
        environments = {json.dumps({
            "runtime": {key: row["environment"].get(key) for key in
                        ("versions", "torch_runtime", "tensorrt_runtime", "device_tree_model",
                         "l4t", "nvpmodel")},
            "conditions": {key: row.get(key) for key in
                           ("cooling", "power_supply", "actual_torch_threads", "input_tensors")}
        }, sort_keys=True) for row in group}
        if len(environments) != 1:
            raise ValueError("Runtime, power mode or measurement conditions drift between runs")
        for row in group:
            for scope in ("model_only", "end_to_end"):
                stats = row[scope]
                recomputed = summarize(stats["latencies_ms"], stats["elapsed_s"], None)
                for key in ("p50_ms", "p95_ms", "throughput_per_s"):
                    if abs(recomputed[key] - stats[key]) > 1e-8:
                        raise ValueError("Saved timing summary does not match raw samples")
                if len(stats["latencies_ms"]) != row["protocol"]["repeats"]:
                    raise ValueError("Sample count does not match protocol")
    return groups
