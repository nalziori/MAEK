"""Prepare/probe or run isolated benchmarks on an actual Jetson Orin Nano."""
from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maek.jetson_benchmark import (
    array_hash,
    compare_segmentations,
    measure,
    probe,
    segmentation_snapshot,
    sha256,
    validate_collection,
    validate_engine_environment,
)


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def state_dict_sha256(state):
    """Hash actual CPU FP32 state before precision/device conversion, not its seed."""
    digest = hashlib.sha256(b"MAEK_STATE_DICT_V1\x00")
    for name in sorted(state):
        array = state[name].detach().cpu().contiguous().numpy()
        header = json.dumps({"name": name, "shape": list(array.shape), "dtype": array.dtype.str},
                            sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        payload = array.tobytes(order="C")
        for part in (header, payload):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


def load_inputs(args):
    import numpy as np
    from PIL import Image
    archive = args.data / ("maek-ut.zip" if args.model == "ut" else "maek-camera.zip")
    with ZipFile(archive) as zipped:
        if args.model == "ut":
            with np.load(io.BytesIO(zipped.read("ut/train/ut_angle.npz"))) as data:
                arrays = list(data["signals"][:12].astype(np.float32))
            if len(arrays) != 12 or any(x.shape != (4096,) for x in arrays):
                raise ValueError("Expected first 12 UT signals of length 4096")
            members = [f"ut/train/ut_angle.npz:signals[{i}]" for i in range(12)]
        else:
            entries = sorted(set(zipped.read("camera/train/train.txt").decode().splitlines()))[:12]
            arrays, members = [], []
            for entry in entries:
                relative = PurePosixPath(entry)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Unsafe archive image member")
                member = str(PurePosixPath("camera/train") / relative)
                with Image.open(io.BytesIO(zipped.read(member))) as image:
                    # Ultralytics numpy input is BGR. Preserve original resolution.
                    arrays.append(np.asarray(image.convert("RGB"))[:, :, ::-1].copy())
                members.append(member)
            if len(arrays) != 12:
                raise ValueError("Expected 12 camera images")
    if any(not np.isfinite(x).all() for x in arrays):
        raise ValueError("Nonfinite input")
    return arrays, {"archive_sha256": sha256(archive), "input_members": members,
                    "input_hashes": [array_hash(x) for x in arrays]}


def tensor_info(tensor):
    return {"shape": list(tensor.shape), "dtype": str(tensor.dtype),
            "device": str(tensor.device)}


def check_outputs(output, torch):
    found = []

    def visit(value):
        if isinstance(value, torch.Tensor):
            if not bool(torch.isfinite(value).all()):
                raise RuntimeError("Nonfinite model output")
            found.append(tensor_info(value))
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
    visit(output)
    if not found:
        raise RuntimeError("Backend returned no inspectable tensors")
    return found


def worker(args):
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = str(args.threads)
    environment = probe()
    if not environment["target_jetson_detected"]:
        raise RuntimeError("Not a detected Jetson Orin Nano: use --probe; no PC benchmark emitted")
    import psutil
    import torch

    from maek.onboard_models import make_ut_model

    device = torch.device(args.device)
    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Requested CUDA is unavailable; CPU fallback is forbidden")
    if args.precision == "fp16" and device.type != "cuda":
        raise ValueError("FP16 is only enabled for CUDA")
    if args.engine and (args.model != "yolo" or device.type != "cuda"):
        raise ValueError("TensorRT engine requires YOLO and CUDA")
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    dtype = torch.float16 if args.precision == "fp16" else torch.float32
    synchronize = (lambda: torch.cuda.synchronize(device)) if device.type == "cuda" else lambda: None
    arrays, inputs = load_inputs(args)
    weights = args.ut_weights if args.model == "ut" else args.weights
    if weights and not weights.is_file():
        raise FileNotFoundError(weights)
    weights_hash = sha256(weights) if weights else None
    precision_comparison = None
    engine_manifest = None
    engine_environment_check = None
    model_state_hash = None
    if args.model == "ut":
        model = make_ut_model()
        if weights:
            model.load_state_dict(torch.load(weights, map_location="cpu", weights_only=True),
                                  strict=True)
        model_state_hash = state_dict_sha256(model.state_dict())
        cpu_tensors = [torch.from_numpy(x).reshape(1, 1, 4096) for x in arrays]
        with torch.inference_mode():
            reference = [model(x).numpy().copy() for x in cpu_tensors]
        model = model.to(device=device, dtype=dtype).eval()
        tensors = [x.to(device=device, dtype=dtype) for x in cpu_tensors]

        def model_only(index):
            return model(tensors[index % 12])

        @torch.inference_mode()
        def end_to_end(index):
            x = torch.from_numpy(arrays[index % 12].copy()).reshape(1, 1, 4096)
            return model(x.to(device=device, dtype=dtype)).float().cpu().numpy()

        import numpy as np
        candidate = [end_to_end(i) for i in range(12)]
        precision_comparison = {
            "reference": "same weights CPU FP32 logits", "samples": 12,
            "max_abs_error": float(np.max(np.abs(np.array(reference) - np.array(candidate)))),
            "allclose_rtol_1e2_atol_1e3": bool(np.allclose(reference, candidate,
                                                         rtol=1e-2, atol=1e-3))}
        metadata = {"model_name": "Tiny1DCNN", "backend_class": type(model).__name__,
                    "weights_status": args.weights_provenance if weights else
                    "fixed random seed0; cost only; no learned defect accuracy",
                    "batchnorm_modules": 0, "fused": False}
    else:
        from ultralytics import YOLO
        if not weights:
            raise ValueError("YOLO requires an existing local --weights .pt; no downloads")
        if weights.suffix != ".pt" or (args.engine and args.engine.suffix != ".engine"):
            raise ValueError("Expected .pt source weights and optional .engine TensorRT artifact")
        predict_options = {"imgsz": args.size, "device": args.device, "verbose": False,
                           "save": False, "rect": False, "conf": 0.25, "iou": 0.7,
                           "max_det": 300, "retina_masks": True}
        # Reference is evaluated outside measured scopes and released before timing.
        reference_model = YOLO(str(weights), task="segment")
        reference = [segmentation_snapshot(reference_model.predict(x, half=False,
                     **predict_options)[0]) for x in arrays]
        del reference_model
        gc.collect()
        if device.type == "cuda":
            torch.cuda.empty_cache()
        if args.engine:
            if not args.engine_manifest:
                raise ValueError("--engine requires --engine-manifest")
            engine_manifest = json.loads(args.engine_manifest.read_text(encoding="utf-8"))
            expected = {"source_weights_sha256": weights_hash,
                        "engine_sha256": sha256(args.engine), "precision": args.precision,
                        "imgsz": args.size, "batch": 1, "nms": False, "dynamic": False}
            if any(engine_manifest.get(k) != v for k, v in expected.items()):
                raise ValueError("Engine manifest does not match weights/engine/protocol")
            engine_environment_check = validate_engine_environment(
                engine_manifest.get("export_environment", {}), environment)
        yolo = YOLO(str(args.engine or weights), task="segment")

        def end_to_end(index):
            result = yolo.predict(arrays[index % 12], half=args.precision == "fp16",
                                  **predict_options)[0]
            # Include output device-to-host copies; disk I/O/acquisition remains excluded.
            return result.cpu()

        end_to_end(0)
        backend = yolo.predictor.model
        actual_format = getattr(backend, "format", None)
        is_engine = actual_format == "engine" or getattr(backend, "engine", False) is True
        if bool(args.engine) != bool(is_engine):
            raise RuntimeError("Actual backend does not match requested TensorRT/PyTorch")
        if not args.engine and not (actual_format == "pt" or getattr(backend, "pt", False)):
            raise RuntimeError("Actual backend is not PyTorch")
        if bool(backend.fp16) != (args.precision == "fp16"):
            raise RuntimeError("Actual backend precision differs from requested precision")
        tensors = [yolo.predictor.preprocess([x]) for x in arrays]
        if any(x.dtype != dtype or x.device.type != device.type or
               tuple(x.shape) != (1, 3, args.size, args.size) for x in tensors):
            raise RuntimeError("Actual predictor tensor shape/device/precision mismatch")

        def model_only(index):
            return backend(tensors[index % 12])

        comparisons = [compare_segmentations(reference[i], segmentation_snapshot(end_to_end(i)))
                       for i in range(12)]
        precision_comparison = {"reference": "same .pt weights FP32 predictor on same device",
                                "samples": comparisons,
                                "note": "conversion sanity only, not labeled accuracy; empty pairs uninformative"}
        del reference
        underlying = getattr(backend, "model", None)
        parameters = list(underlying.parameters()) if isinstance(underlying, torch.nn.Module) else []
        batchnorm_count = sum(isinstance(m, torch.nn.modules.batchnorm._BatchNorm)
                              for m in underlying.modules()) if parameters else None
        if parameters and any(p.device.type != device.type or p.dtype != dtype for p in parameters):
            raise RuntimeError("Actual model parameters do not match requested device/precision")
        metadata = {"model_name": weights.stem, "weights_status": args.weights_provenance,
                    "backend_class": type(backend).__name__, "backend_format": actual_format,
                    "backend_model_class": type(underlying).__name__,
                    "batchnorm_modules": batchnorm_count,
                    "fused": batchnorm_count == 0 if parameters else None,
                    "parameter_dtypes": sorted({str(p.dtype) for p in parameters}),
                    "precision_note": "engine I/O dtype verified; internal layer precision not inferred"}
        if parameters and batchnorm_count:
            raise RuntimeError("Expected fused YOLO predictor, found BatchNorm modules")
        # Ultralytics may reset CPU threads during predictor setup.
        torch.set_num_threads(args.threads)
    with torch.inference_mode():
        output_info = check_outputs(model_only(0), torch)
        synchronize()
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        measured = {}
        for scope, fn in (("model_only", model_only), ("end_to_end", end_to_end)):
            measured[scope] = measure(fn, synchronize, args.warmup, args.repeats)
            if torch.get_num_threads() != args.threads:
                raise RuntimeError("Actual CPU thread count changed")
    return {"schema": "maek-jetson-v1", "run": args.run, "pid": os.getpid(),
            "utc_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "environment": environment, "cooling": args.cooling, "power_supply": args.power_supply,
            "model": args.model, "backend": "tensorrt" if args.engine else "pytorch",
            "device": args.device, "precision": args.precision, "size": args.size,
            "weights_sha256": weights_hash, "engine_sha256": sha256(args.engine) if args.engine else None,
            "model_state_sha256": model_state_hash,
            "engine_manifest": engine_manifest, "engine_environment_check": engine_environment_check,
            **inputs, **metadata, **measured,
            "input_tensors": [tensor_info(x) for x in tensors], "output_tensors": output_info,
            "actual_torch_threads": torch.get_num_threads(),
            "code_sha256": {str(p.relative_to(ROOT)): sha256(p) for p in
                            (Path(__file__), ROOT / "maek/jetson_benchmark.py",
                             ROOT / "maek/onboard_models.py")},
            "protocol": {"warmup": args.warmup, "repeats": args.repeats, "batch": 1,
                         "model_state_sha256": model_state_hash,
                         "threads": args.threads, "tf32": False, "cudnn_benchmark": False,
                         "model_only": "predictor backend; resident device tensor; no postprocess/D2H",
                         "end_to_end": "host BGR/float32 array through preprocessing/H2D/model/postprocess/D2H",
                         "file_io_included": False, "camera_acquisition_included": False,
                         "camera_preprocessing": "Ultralytics rect=False square letterbox; conf=.25 iou=.7 max_det=300 retina_masks=True",
                         "ut_preprocessing": "float32 raw amplitude; no normalization; 1x1x4096",
                         "gpu_timing": "wall clock with synchronize before and after every sample"},
            "precision_comparison": precision_comparison,
            "process_rss_at_end_mib": psutil.Process().memory_info().rss / 2**20,
            "torch_cuda_peak_allocated_mib": torch.cuda.max_memory_allocated(device) / 2**20
            if device.type == "cuda" else None,
            "torch_cuda_peak_reserved_mib": torch.cuda.max_memory_reserved(device) / 2**20
            if device.type == "cuda" else None,
            "memory_note": "RSS sampled working set; excludes some GPU/runtime allocations. CUDA allocator counters exclude TensorRT. Shared DRAM values must not be added."}


def collect(directory):
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(directory.glob("run-*.json"))]
    groups = validate_collection(rows)
    telemetry = [{"run": row["run"], "path": f"tegrastats-{row['run']}.log",
                  "nonempty": (directory / f"tegrastats-{row['run']}.log").is_file() and
                  (directory / f"tegrastats-{row['run']}.log").stat().st_size > 0}
                 for row in rows]
    flat = []
    for row in rows:
        for scope in ("model_only", "end_to_end"):
            flat.append({**{k: row[k] for k in ("model", "backend", "device", "precision", "size", "run")},
                         "scope": scope, **{k: v for k, v in row[scope].items()
                                            if k not in ("latencies_ms", "memory_errors")}})
    # Collection is reproducible; exclusive creation prevents overwriting an earlier summary.
    write_json(directory / "collected.json", rows)
    write_json(directory / "collection-status.json", {
        "tegrastats": telemetry,
        "telemetry_review_required": True,
        "note": "A nonempty log is not proof of valid telemetry or absence of throttling. Inspect raw logs."})
    with (directory / "latency.csv").open("x", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)
    return {"runs": len(rows), "configurations": len(groups),
            "output": str(directory / "latency.csv")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="read-only environment JSON; no benchmark")
    parser.add_argument("--collect", type=Path, help="validate existing worker JSON and write JSON/CSV")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--weights-provenance", default="COCO pretrained; not MAEK defect-trained")
    parser.add_argument("--ut-weights", type=Path, help="optional Tiny1DCNN state_dict checkpoint")
    parser.add_argument("--engine", type=Path, help="existing engine; never exported during benchmark")
    parser.add_argument("--engine-manifest", type=Path)
    parser.add_argument("--model", choices=("yolo", "ut"), default="yolo")
    parser.add_argument("--device", choices=("cpu", "cuda:0"), default="cpu")
    parser.add_argument("--precision", choices=("fp32", "fp16"), default="fp32")
    parser.add_argument("--size", type=positive, default=320)
    parser.add_argument("--threads", type=positive, default=1)
    parser.add_argument("--warmup", type=positive, default=10)
    parser.add_argument("--repeats", type=positive, default=100)
    parser.add_argument("--cooling", default="unspecified")
    parser.add_argument("--power-supply", default="unspecified")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run", type=positive, default=1, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.probe:
        print(json.dumps(probe(), indent=2, ensure_ascii=False))
        return
    if args.collect:
        print(json.dumps(collect(args.collect), indent=2))
        return
    if not args.data or not args.output:
        parser.error("benchmark requires --data and --output")
    if args.model == "ut":
        args.size = 4096
        if args.ut_weights and args.weights_provenance == "COCO pretrained; not MAEK defect-trained":
            parser.error("UT checkpoint requires an explicit --weights-provenance")
    elif args.size % 32:
        parser.error("YOLO --size must be divisible by 32")
    if args.worker:
        write_json(args.output / f"run-{args.run}.json", worker(args))
        return
    environment = probe()
    if not environment["target_jetson_detected"]:
        parser.error("No Jetson Orin Nano detected; only --probe/--collect are allowed on this host")
    if args.cooling == "unspecified" or args.power_supply == "unspecified":
        parser.error("record actual --cooling and --power-supply before measurement")
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "probe.json", environment)
    # Every run is a fresh process, sequentially; no concurrent model workloads.
    base = [sys.executable, str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])]
    for run in (1, 2, 3):
        log_path = args.output / f"tegrastats-{run}.log"
        with log_path.open("x", encoding="utf-8") as telemetry:
            monitor = subprocess.Popen([environment["tegrastats_path"], "--interval", "100"],
                                       stdout=telemetry, stderr=subprocess.STDOUT) if environment["tegrastats_path"] else None
            try:
                result = subprocess.run([*base, "--worker", "--run", str(run)],
                                        capture_output=True, text=True, check=False)
            finally:
                if monitor:
                    monitor.terminate()
                    try:
                        monitor.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        monitor.kill()
                        monitor.wait()
            (args.output / f"worker-{run}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            if result.returncode:
                raise RuntimeError(f"Worker {run} failed; inspect worker-{run}.log")
        print(f"Completed fresh process {run}/3", flush=True)
    print(json.dumps(collect(args.output), indent=2))


if __name__ == "__main__":
    main()
