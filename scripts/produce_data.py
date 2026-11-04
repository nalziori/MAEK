"""Produce the full MAEK synthetic dataset in one go.

Usage (from the repo root):
    OMP_NUM_THREADS=1 python scripts/produce_data.py --out data/release --workers 4

Outputs:
    network/    segments.csv, features.csv, defects.csv  (100 km, ground truth)
    ut/train/   ut_straight.npz, ut_angle.npz, ut_labels.csv  (float16 A-scans)
    ut/shifted/ same, harder conditions
    camera/train/, camera/shifted/  images/*.jpg, masks/*.png, labels/*.txt (YOLO-seg),
                                     train.txt, val.txt, dataset.yaml, jobs.json
    strategy/   compare.csv, sensitivity.csv
    DATA_CARD.md
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maek import network, params, strategy, ut
from maek.camera import composite2d, jobs

_CFG = None


def _init(cfg_path: str) -> None:
    global _CFG
    _CFG = params.load_config(cfg_path)


def _render_one(task: tuple[int, int, dict, str]) -> str:
    from PIL import Image

    seed, i, job, out = task
    out_dir = Path(out)
    rgb, mask = composite2d.render_job(_CFG, job, np.random.default_rng([seed, i]))
    jid = job["job_id"]
    Image.fromarray(rgb).save(out_dir / "images" / f"{jid}.jpg", quality=92)
    Image.fromarray(mask).save(out_dir / "masks" / f"{jid}.png", compress_level=6)
    lines = composite2d.yolo_lines(mask) if mask.any() else []
    (out_dir / "labels" / f"{jid}.txt").write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return jid


def render_set(cfg_path, js, out_dir: Path, seed: int, workers: int) -> None:
    for sub in ("images", "masks", "labels"):
        (out_dir / sub).mkdir(parents=True, exist_ok=True)
    jobs.save_jobs(out_dir / "jobs.json", js)
    tasks = [(seed, i, j, str(out_dir)) for i, j in enumerate(js)]
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(cfg_path,)) as ex:
        names = list(ex.map(_render_one, tasks, chunksize=8))
    val = {j for k, j in enumerate(names) if k % 5 == 4}
    (out_dir / "train.txt").write_text("".join(f"./images/{j}.jpg\n" for j in names if j not in val))
    (out_dir / "val.txt").write_text("".join(f"./images/{j}.jpg\n" for j in names if j in val))
    cls = "".join(f"  {c - 1}: {composite2d.CLASSES[c]}\n" for c in composite2d.CLASSES if c)
    (out_dir / "dataset.yaml").write_text(
        f"path: .\ntrain: train.txt\nval: val.txt\nnames:\n{cls}", encoding="utf-8")


def save_ut(out_dir: Path, straight, angle, labels) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_dir / "ut_straight.npz", signals=straight.astype(np.float16))
    np.savez_compressed(out_dir / "ut_angle.npz", signals=angle.astype(np.float16))
    labels.to_csv(out_dir / "ut_labels.csv", index=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config" / "default.yaml"))
    ap.add_argument("--out", default=str(ROOT / "data" / "release"))
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--ut-train", type=int, default=10000)
    ap.add_argument("--ut-shifted", type=int, default=3000)
    ap.add_argument("--img-train", type=int, default=2000)
    ap.add_argument("--img-shifted", type=int, default=400)
    ap.add_argument("--strategy-runs", type=int, default=20)
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    out = Path(a.out)
    cfg = params.load_config(a.config)
    params.validate(cfg)
    log = {}
    t0 = time.perf_counter()

    seg, feat, dfx = network.generate_network(cfg, a.seed)
    network.save_network(out / "network", seg, feat, dfx)
    log["network"] = {"segments": len(seg), "features": len(feat), "defects": len(dfx),
                      "critical": int(dfx["critical"].sum())}

    for cond, n, s in (("train", a.ut_train, a.seed), ("shifted", a.ut_shifted, a.seed + 100)):
        st, an, lab = ut.make_dataset(cfg, n, s, cond)
        save_ut(out / "ut" / cond, st, an, lab)
        log[f"ut_{cond}"] = {"n": n, "seed": s, "baseline": ut.baseline(cfg, st, an, lab)}

    for cond, n, s in (("train", a.img_train, a.seed), ("shifted", a.img_shifted, a.seed + 100)):
        js = jobs.make_jobs(cfg, seg, dfx, n, s, condition=cond)
        render_set(a.config, js, out / "camera" / cond, s, a.workers)
        log[f"camera_{cond}"] = {"n": len(js), "seed": s,
                                 "negatives": int(sum(j["negative"] for j in js))}

    st_dir = out / "strategy"
    st_dir.mkdir(parents=True, exist_ok=True)
    comp = strategy.compare(cfg, a.seed, a.strategy_runs)
    comp.to_csv(st_dir / "compare.csv", index=False)
    strategy.sensitivity(cfg, a.seed, max(3, a.strategy_runs // 4)).to_csv(
        st_dir / "sensitivity.csv", index=False)

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], check=False, cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    log["elapsed_s"] = round(time.perf_counter() - t0, 1)
    (out / "manifest.json").write_text(json.dumps(log, indent=2, default=float), encoding="utf-8")
    (out / "DATA_CARD.md").write_text(_card(a, commit, log), encoding="utf-8")
    print(json.dumps(log, indent=2, default=float))
    return 0


def _card(a, commit: str, log: dict) -> str:
    nw = log["network"]
    return f"""# MAEK 합성 데이터셋 카드

가상 제철소 배관망 시뮬레이션으로 만든 합성 데이터입니다. 실제 점검 데이터가 아닙니다.

- 생성 코드: nalziori/MAEK 커밋 `{commit}`, 설정 `config/default.yaml`
- 재생성: `OMP_NUM_THREADS=1 python scripts/produce_data.py --seed {a.seed}`
- 생성 시간: {log['elapsed_s']}초

| 묶음 | 내용 | 규모 |
|---|---|---|
| network | 100km 배관망 구간·특징·결함 정답 | 구간 {nw['segments']}, 결함 {nw['defects']} (위험 {nw['critical']}) |
| ut/train, ut/shifted | ② 균열(사각 탐촉자)·③ 두께(수직 탐촉자) A-scan, float16 | {a.ut_train} / {a.ut_shifted} |
| camera/train, camera/shifted | ① 부식 이미지(JPEG)·마스크·YOLO-seg 라벨 | {a.img_train} / {a.img_shifted} |
| strategy | 기존 방식 vs AI 선별 방식 비교, 단가 민감도 | {a.strategy_runs}회 |

`shifted`는 학습에 쓰지 않은 어려운 조건(잡음, 극단 온도, 접촉 불량, 조명·분진·증기)입니다. 평가에만 쓰세요.
파라미터와 출처는 저장소 `docs/params.md`, 기준 성능은 `docs/results.md`에 있습니다.
"""


if __name__ == "__main__":
    raise SystemExit(main())
