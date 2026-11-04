"""Onboard resource approximation: latency / throughput / memory of the classical baselines.

These are CPU measurements on the dev machine with the thread count limited
(OMP_NUM_THREADS + CPU affinity). They approximate, but do not equal, a small onboard board.
"""

from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pandas as pd

from maek import params, ut
from maek.camera import composite2d, jobs, segment


def limit_threads(k: int) -> None:
    """Best-effort: restrict BLAS/OpenMP threads and (Linux) the CPU set to k cores."""
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = str(k)
    if hasattr(os, "sched_setaffinity"):
        cpus = sorted(os.sched_getaffinity(0))[:k]
        if cpus:
            os.sched_setaffinity(0, cpus)


def measure(fn, items, warmup: int = 2, repeat: int = 1) -> dict:
    """Per-item latency (ms; median, p95), throughput (items/s), tracemalloc peak (MB)."""
    for it in items[:warmup]:
        fn(it)
    lat = []
    for _ in range(repeat):
        for it in items:
            t = time.perf_counter()
            fn(it)
            lat.append((time.perf_counter() - t) * 1e3)
    tracemalloc.start()
    tracemalloc.reset_peak()
    for it in items[:max(3, len(items) // 4)]:
        fn(it)
    peak = tracemalloc.get_traced_memory()[1] / 2**20
    tracemalloc.stop()
    med = float(np.median(lat))
    return {"median_ms": med, "p95_ms": float(np.percentile(lat, 95)),
            "throughput_per_s": 1000.0 / med, "tracemalloc_peak_mb": float(peak)}


def _rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0  # Linux: KiB


def make_inputs(cfg, sizes, n_images, n_ut, seed=0) -> dict:
    from maek import network

    inputs = {"images": {}}
    for s in sizes:
        c = _with_size(cfg, s)
        seg, _, dfx = network.generate_network(c, seed, total_km=10)
        js = jobs.make_jobs(c, seg, dfx, n_images, seed)
        inputs["images"][s] = [composite2d.render_job(c, j, np.random.default_rng(i))[0]
                               for i, j in enumerate(js)]
    straight, angle, lab = ut.make_dataset(cfg, n_ut, seed)
    inputs["ut"] = list(zip(straight, angle, lab.itertuples()))
    return inputs


def _with_size(cfg, size):
    import copy

    c = copy.deepcopy(cfg)
    c["camera"]["image_size"]["value"] = int(size)
    return c


def run_benchmark(cfg, sizes=None, n_images=None, n_ut=None, seed=0) -> list[dict]:
    """Benchmark the three baselines in this process (call after limit_threads)."""
    sizes = sizes or params.get(cfg, "onboard.bench_image_sizes")
    n_images = n_images or params.get(cfg, "onboard.bench_n_images")
    n_ut = n_ut or params.get(cfg, "onboard.bench_n_ut")
    inp = make_inputs(cfg, sizes, n_images, n_ut, seed)
    rows = []
    for s in sizes:
        rows.append({"function": "corrosion_segment", "input": f"{s}x{s}px",
                     **measure(segment.segment_rust, inp["images"][s])})
    rows.append({"function": "crack_detect", "input": "A-scan 4096",
                 **measure(lambda x: ut.detect_crack(cfg, x[1], x[2].wall_mm, x[2].angle_deg,
                                                     x[2].temp_c), inp["ut"], repeat=3)})
    rows.append({"function": "thickness", "input": "A-scan 4096",
                 **measure(lambda x: (ut.estimate_thickness(cfg, x[0], x[2].temp_c),
                                      ut.min_thickness(cfg, x[0], x[2].temp_c)),
                           inp["ut"], repeat=3)})
    rss = _rss_mb()
    for r in rows:
        r["process_peak_rss_mb"] = rss
    return rows


def judge(cfg, df: pd.DataFrame) -> pd.DataFrame:
    """Add pass/fail columns against onboard.target_fps and onboard.memory_limit_gb."""
    fps = params.get(cfg, "onboard.target_fps")
    mem_mb = params.get(cfg, "onboard.memory_limit_gb") * 1024
    df = df.copy()
    df["target_fps"] = fps
    df["pass_fps"] = df["throughput_per_s"] >= fps
    df["pass_memory"] = df["process_peak_rss_mb"] <= mem_mb
    return df


def run_all(cfg, out_dir, threads=None, **kw) -> pd.DataFrame:
    """Run the worker once per thread limit (fresh process each) and collect results."""
    threads = threads or params.get(cfg, "onboard.bench_threads")
    root = Path(__file__).resolve().parents[1]
    recs = []
    for k in threads:
        env = {**os.environ, "OMP_NUM_THREADS": str(k), "OPENBLAS_NUM_THREADS": str(k),
               "MKL_NUM_THREADS": str(k), "PYTHONPATH": str(root)}
        cmd = [sys.executable, "-m", "maek.onboard", "--threads", str(k)]
        if kw.get("n_images"):
            cmd += ["--n-images", str(kw["n_images"])]
        if kw.get("n_ut"):
            cmd += ["--n-ut", str(kw["n_ut"])]
        out = subprocess.run(cmd, env=env, cwd=root, capture_output=True, text=True, check=True)
        for r in json.loads(out.stdout.strip().splitlines()[-1]):
            recs.append({"threads": k, **r})
    df = judge(cfg, pd.DataFrame(recs))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "onboard.csv", index=False)
    return df


def to_markdown(df: pd.DataFrame) -> str:
    cols = ["function", "input", "threads", "median_ms", "p95_ms", "throughput_per_s",
            "tracemalloc_peak_mb", "process_peak_rss_mb", "pass_fps", "pass_memory"]
    L = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df[cols].itertuples(index=False):
        L.append("| " + " | ".join(
            f"{v:.1f}" if isinstance(v, float) else ("통과" if v is True else
                                                     "미달" if v is False else str(v))
            for v in r) + " |")
    return "\n".join(L)


def _main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--n-images", type=int, default=None)
    ap.add_argument("--n-ut", type=int, default=None)
    a = ap.parse_args(argv)
    limit_threads(a.threads)
    cfg = params.load_config()
    print(json.dumps(run_benchmark(cfg, n_images=a.n_images, n_ut=a.n_ut)))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
