"""Standalone Ultralytics YOLO-seg training / evaluation for the rendered MAEK dataset.

Not part of the core package and not run in CI or pytest (needs `pip install ultralytics`,
a GPU is strongly recommended). Typical use on Colab or a GPU box:

    python -m maek camera-jobs --n 2000 --out data/ && python -m maek render2d --out data/
    python scripts/train_yolo_seg.py train  --data data/camera/dataset.yaml --epochs 50
    python scripts/train_yolo_seg.py val    --data data/camera/dataset.yaml --weights runs/segment/maek/weights/best.pt
    python scripts/train_yolo_seg.py export --weights runs/segment/maek/weights/best.pt --format onnx --imgsz 320
    python scripts/train_yolo_seg.py benchmark --weights runs/segment/maek/weights/best.pt --data data/camera/dataset.yaml --imgsz 640

To measure the train -> shifted drop, render a second dataset with shifted jobs
(`maek.camera.jobs.make_jobs(..., condition="shifted")`) and pass its dataset.yaml to `val`.
dataset.yaml may hold `path: .` (released data): the train/val/benchmark commands rewrite it at
run time with `path:` set to the YAML's absolute folder, so the data trains after unzipping anywhere.
Classes (dataset.yaml): 0 corrosion, 1 cui_sign, 2 leak_stain.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

import yaml

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


def resolve_data(data: str) -> str:
    """Return a dataset yaml Ultralytics can use from anywhere.

    Ultralytics resolves a relative `path:` against its DATASETS_DIR, not the YAML's folder, so
    the released `path: .` fails. Write a temp yaml whose `path:` is the YAML's absolute folder
    (train/val lists stay relative to it) and return that temp file's path.
    """
    src = Path(data).resolve()
    cfg = yaml.safe_load(src.read_text(encoding="utf-8"))
    cfg["path"] = str(src.parent)
    tmp = Path(tempfile.mkdtemp(prefix="maek_ds_")) / "dataset.yaml"
    tmp.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(tmp)


def find_images(data: str, n: int | None = None) -> list[Path]:
    """Read the train/val image lists specified by the dataset YAML."""
    yaml_path = Path(data).resolve()
    cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    root = yaml_path.parent
    imgs = set()
    for split in ("train", "val"):
        list_path = root / cfg[split]
        for line in list_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                image = (root / line.strip()).resolve()
                if image.suffix.lower() not in IMAGE_EXTS or not image.is_file():
                    raise ValueError(f"Invalid dataset image: {image}")
                imgs.add(image)
    imgs = sorted(imgs)
    return imgs[:n] if n else imgs


def _yolo(weights: str):
    from ultralytics import YOLO  # imported lazily so `--help` works without it

    return YOLO(weights)


def cmd_train(a) -> int:
    model = _yolo(a.weights)
    model.train(data=resolve_data(a.data), epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, device=a.device,
                project=a.project, name=a.name, seed=a.seed, exist_ok=True)
    return 0


def cmd_val(a) -> int:
    m = _yolo(a.weights).val(data=resolve_data(a.data), imgsz=a.imgsz, device=a.device, split="val")
    out = {"box_map50": float(m.box.map50), "mask_map50": float(m.seg.map50),
           "mask_map50_95": float(m.seg.map), "per_class_mask_map50": [float(x) for x in m.seg.ap50]}
    print(json.dumps(out, indent=1))
    return 0


def cmd_export(a) -> int:
    path = _yolo(a.weights).export(format=a.format, imgsz=a.imgsz, half=a.half, int8=a.int8,
                                   device=a.device)
    print(f"exported: {path} ({Path(path).stat().st_size / 2**20:.1f} MB)")
    return 0


def cmd_benchmark(a) -> int:
    """Latency (median / p95 ms), params and weight size; run this ON the target board."""
    model = _yolo(a.weights)
    imgs = find_images(a.data, a.n)
    if not imgs:
        raise SystemExit("no images found next to dataset.yaml")
    kw = {"imgsz": a.imgsz, "device": a.device, "verbose": False}
    for p in imgs[:3]:
        model.predict(str(p), **kw)  # warm-up
    lat = []
    for p in imgs:
        t = time.perf_counter()
        model.predict(str(p), **kw)
        lat.append((time.perf_counter() - t) * 1e3)
    n_params = sum(p.numel() for p in model.model.parameters()) if hasattr(model, "model") \
        and hasattr(model.model, "parameters") else None
    res = {"imgsz": a.imgsz, "n_images": len(imgs), "median_ms": statistics.median(lat),
           "p95_ms": sorted(lat)[int(0.95 * (len(lat) - 1))],
           "fps": 1000.0 / statistics.median(lat), "params": n_params,
           "weights_mb": Path(a.weights).stat().st_size / 2**20}
    print(json.dumps(res, indent=1))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, weights="yolov8n-seg.pt"):
        sp.add_argument("--weights", default=weights)
        sp.add_argument("--data", default="data/camera/dataset.yaml")
        sp.add_argument("--imgsz", type=int, default=640)
        sp.add_argument("--device", default=None, help="e.g. 0, cpu (default: auto)")

    t = sub.add_parser("train")
    common(t)
    t.add_argument("--epochs", type=int, default=50)
    t.add_argument("--batch", type=int, default=16)
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--project", default="runs/segment")
    t.add_argument("--name", default="maek")
    t.set_defaults(func=cmd_train)
    v = sub.add_parser("val")
    common(v)
    v.set_defaults(func=cmd_val)
    e = sub.add_parser("export")
    common(e)
    e.add_argument("--format", default="onnx", help="onnx, tflite, ncnn, openvino, engine ...")
    e.add_argument("--half", action="store_true")
    e.add_argument("--int8", action="store_true")
    e.set_defaults(func=cmd_export)
    b = sub.add_parser("benchmark")
    common(b)
    b.add_argument("--n", type=int, default=50)
    b.set_defaults(func=cmd_benchmark)
    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
