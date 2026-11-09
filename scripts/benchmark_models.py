"""Measure CPU models on v3 inputs in a fresh process per model, size and run."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maek.onboard_models import summarize


def positive_int(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def sha256(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def measure(fn, warmup, repeats, process):
    import psutil
    for i in range(warmup):
        fn(i)
    stop = threading.Event()
    samples, errors = [], []

    def read_rss():
        try:
            value = process.memory_info().rss
            if value <= 0:
                raise ValueError("Invalid RSS")
            samples.append(value)
        except (psutil.Error, OSError, ValueError) as exc:
            errors.append(str(exc))

    def sample():
        while not stop.wait(0.005):
            read_rss()

    read_rss()
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    latencies = []
    start = time.perf_counter()
    try:
        for i in range(repeats):
            before = time.perf_counter()
            fn(i)
            latencies.append((time.perf_counter() - before) * 1000)
    finally:
        elapsed = time.perf_counter() - start
        read_rss()
        stop.set()
        sampler.join()
    peak = None if errors or not samples else max(samples) / 2**20
    return {**summarize(latencies, elapsed, peak), "peak_rss_mb": peak, "rss_errors": errors}


def worker(args):
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = str(args.threads)
    import numpy as np
    import psutil
    import torch
    from PIL import Image

    from maek.onboard_models import make_ut_model

    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    process = psutil.Process()
    if args.model == "ut":
        archive = args.data / "maek-ut.zip"
        with ZipFile(archive) as z, np.load(io.BytesIO(z.read("ut/train/ut_angle.npz"))) as data:
            signals = data["signals"][:12].astype(np.float32)
        if signals.shape != (12, 4096) or not np.isfinite(signals).all():
            raise ValueError("Expected 12 finite A-scans of length 4096")
        model = make_ut_model()
        tensors = [torch.from_numpy(s).reshape(1, 1, 4096) for s in signals]

        def model_only(i):
            with torch.inference_mode():
                return model(tensors[i % len(tensors)])

        def end_to_end(i):
            with torch.inference_mode():
                x = torch.from_numpy(signals[i % len(signals)].copy()).reshape(1, 1, 4096)
                return model(x).numpy()

        result = model_only(0)
        if result.shape != (1, 2) or not torch.isfinite(result).all():
            raise RuntimeError("Invalid UT output")
        metadata = {"model": "Tiny1DCNN", "weights_status": "fixed random seed0; cost only",
                    "input": "v3 ut_angle float32 1x1x4096; first12; no normalization",
                    "weights_sha256": None, "weights_mb": None, "ultralytics_version": None,
                    "input_members": "ut/train/ut_angle.npz:signals[0:12]"}
    else:
        from ultralytics import YOLO
        from ultralytics import __version__ as ultralytics_version
        archive = args.data / "maek-camera.zip"
        images, members = [], []
        with ZipFile(archive) as z:
            entries = sorted(set(z.read("camera/train/train.txt").decode().splitlines()))[:12]
            for entry in entries:
                rel = PurePosixPath(entry)
                if rel.is_absolute() or ".." in rel.parts:
                    raise ValueError("Unsafe image path")
                member = str(PurePosixPath("camera/train") / rel)
                with Image.open(io.BytesIO(z.read(member))) as im:
                    images.append(im.convert("RGB").copy())
                members.append(member)
        if not args.weights.is_file():
            raise FileNotFoundError(args.weights)
        # Official Python API: https://docs.ultralytics.com/usage/python/
        yolo = YOLO(str(args.weights), task="segment")
        model = yolo.model.cpu().float().eval()
        tensors = [torch.from_numpy(np.asarray(im.resize((args.size, args.size))).copy()
                                   .transpose(2, 0, 1)).unsqueeze(0).float() / 255 for im in images]

        def model_only(i):
            with torch.inference_mode():
                return model(tensors[i % len(tensors)])

        def end_to_end(i):
            return yolo.predict(images[i % len(images)], imgsz=args.size, device="cpu",
                                verbose=False, save=False)

        # Initialize/fuse the predictor before either measured scope for comparable state.
        end_to_end(0)
        # Ultralytics select_device resets CPU threads; restore the requested count after init.
        torch.set_num_threads(args.threads)
        model = yolo.model.cpu().float().eval()
        with torch.inference_mode():
            output = model(tensors[0])
        tensors_out = []

        def collect(value):
            if isinstance(value, torch.Tensor):
                tensors_out.append(value)
            elif isinstance(value, (tuple, list)):
                for item in value:
                    collect(item)
            elif isinstance(value, dict):
                for item in value.values():
                    collect(item)

        collect(output)
        if not tensors_out or not all(bool(torch.isfinite(t).all()) for t in tensors_out):
            raise RuntimeError("Invalid YOLO output")

        metadata = {"model": "YOLOv8n-seg", "weights_status": "COCO pretrained; not MAEK trained",
                    "input": f"v3 RGB first12; {args.size}; model-only square PIL resize",
                    "weights_sha256": sha256(args.weights),
                    "weights_mb": args.weights.stat().st_size / 2**20,
                    "ultralytics_version": ultralytics_version, "input_members": members}
    loaded_rss = process.memory_info().rss / 2**20
    if loaded_rss <= 0:
        loaded_rss = None
    model_stats = measure(model_only, args.warmup, args.repeats, process)
    if torch.get_num_threads() != args.threads:
        raise RuntimeError("Model inference changed the requested CPU thread count")
    full_stats = measure(end_to_end, args.warmup, args.repeats, process)
    if torch.get_num_threads() != args.threads:
        raise RuntimeError("Predictor changed the requested CPU thread count")
    return {**metadata, "run": args.run, "threads": args.threads, "size": args.size,
            "parameters": sum(p.numel() for p in model.parameters()),
            "warmup": args.warmup, "repeats": args.repeats, "batch": 1,
            "device": "cpu", "dtype": "float32", "loaded_rss_mb": loaded_rss,
            "actual_torch_threads": torch.get_num_threads(),
            "model_only": model_stats, "end_to_end": full_stats,
            "rss_sampling_ms": 5, "rss_note": "Working set; short peaks may be missed",
            "file_io_included": False, "data_sha256": sha256(archive),
            "python": platform.python_version(), "torch": torch.__version__,
            "numpy": np.__version__, "psutil": psutil.__version__,
            "platform": str(sys.getwindowsversion()) if sys.platform == "win32" else sys.platform,
            "processor": os.environ.get("PROCESSOR_IDENTIFIER")}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--weights", type=Path, required=True)
    p.add_argument("--threads", type=positive_int, default=1)
    p.add_argument("--warmup", type=positive_int, default=10)
    p.add_argument("--repeats", type=positive_int, default=100)
    p.add_argument("--runs", type=positive_int, default=3)
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--model", choices=("ut", "yolo"), help=argparse.SUPPRESS)
    p.add_argument("--size", type=int, default=320, help=argparse.SUPPRESS)
    p.add_argument("--run", type=int, default=1, help=argparse.SUPPRESS)
    a = p.parse_args()
    if a.worker:
        if a.model is None:
            p.error("--worker requires --model")
        print(json.dumps(worker(a), allow_nan=False))
        return
    a.output.mkdir(parents=True, exist_ok=True)
    if (a.output / "runs.json").exists():
        raise FileExistsError("Choose a new output directory")
    rows = []
    for model, size in (("yolo", 320), ("yolo", 640), ("ut", 4096)):
        for run in range(1, a.runs + 1):
            cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", "--model", model,
                   "--size", str(size), "--run", str(run), "--threads", str(a.threads),
                   "--warmup", str(a.warmup), "--repeats", str(a.repeats),
                   "--weights", str(a.weights.resolve()), "--data", str(a.data.resolve()),
                   "--output", str(a.output.resolve())]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode:
                raise RuntimeError(result.stderr + result.stdout)
            row = json.loads(result.stdout.strip().splitlines()[-1])
            rows.append(row)
            (a.output / f"{model}-{size}-{run}.json").write_text(
                json.dumps(row, indent=2, allow_nan=False), encoding="utf-8")
            print(model, size, run, row["end_to_end"]["p50_ms"], flush=True)
    (a.output / "runs.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    flat = []
    for row in rows:
        base = {k: v for k, v in row.items() if k not in ("model_only", "end_to_end")}
        for scope in ("model_only", "end_to_end"):
            stats = {k: v for k, v in row[scope].items() if k != "latencies_ms"}
            flat.append({**base, "scope": scope, **stats})
    with (a.output / "onboard-speed.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)


if __name__ == "__main__":
    main()
