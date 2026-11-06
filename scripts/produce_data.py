"""Produce the full MAEK synthetic dataset in one go.

Usage (from the repo root):
    OMP_NUM_THREADS=1 python scripts/produce_data.py --out data/release --workers 4

Outputs:
    network/    segments.csv, features.csv, defects.csv  (100 km, ground truth)
    ut/train/   ut_straight.npz, ut_angle.npz, ut_labels.csv  (float16 A-scans)
    ut/shifted/ same, harder conditions
    camera/train/, camera/shifted/  images/*.jpg, masks/*.png, labels/*.txt (YOLO-seg),
                                     train.txt, val.txt, dataset.yaml, jobs.json
                                     (train/val split by segment; dataset.yaml has `path: .`,
                                     train_yolo_seg.py resolves it to the YAML's folder, so the
                                     unzipped release trains from anywhere)
    strategy/   compare.csv, sensitivity.csv (base config), compare_steam.csv,
                sensitivity_steam.csv (steam scenario), pit_prior.csv, sweep.csv
    eva/        eva_summary.csv  (extreme-value pitting circuit analysis)
    thermal/train, thermal/shifted  IR images/*.png (16-bit), masks, labels, dataset.yaml
    DATA_CARD.md
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maek import eva, network, params, strategy, ut
from maek import thermal_render as tr
from maek.camera import composite2d, jobs


def render_set(cfg, js, out_dir: Path, seed: int, workers: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    composite2d.render_all(cfg, js, out_dir, seed, image_format="jpg", jpg_quality=92,
                           workers=workers, relative_yaml=True)
    jobs.save_jobs(out_dir / "jobs.json", js)


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
    ap.add_argument("--ir-train", type=int, default=1000)
    ap.add_argument("--ir-shifted", type=int, default=300)
    ap.add_argument("--strategy-runs", type=int, default=20)
    ap.add_argument("--pit-runs", type=int, default=10)
    ap.add_argument("--sweep-runs", type=int, default=5)
    ap.add_argument("--sweep-km", type=float, default=20.0)
    ap.add_argument("--eva-runs", type=int, default=10)
    ap.add_argument("--total-km", type=float, default=None,
                    help="network / base strategy length (default: network.total_km)")
    ap.add_argument("--steam-km", type=float, default=None,
                    help="steam scenario strategy length (default: the scenario's total_km)")
    ap.add_argument("--scenario", action="append", default=None, metavar="NAME",
                    help="overlay config/scenarios/NAME.yaml on the base dataset (repeatable)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    out = Path(a.out)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {out}; choose a new directory")
    overlays = [params.scenario_path(n) for n in (a.scenario or [])]
    cfg = params.load_config(a.config, overlays)
    params.validate(cfg)
    cfg_steam = params.load_config(a.config, [*overlays, params.scenario_path("steam")])
    params.validate(cfg_steam)
    log = {"argv": sys.argv[1:], "arguments": vars(a),
           "effective_config": {"base": cfg, "steam": cfg_steam}}
    t0 = time.perf_counter()

    seg, feat, dfx = network.generate_network(cfg, a.seed, total_km=a.total_km)
    network.save_network(out / "network", seg, feat, dfx)
    log["network"] = {"length_km": float(seg["length_m"].sum() / 1000),
                      "segments": len(seg), "features": len(feat), "defects": len(dfx),
                      "critical": int(dfx["critical"].sum())}

    for cond, n, s in (("train", a.ut_train, a.seed), ("shifted", a.ut_shifted, a.seed + 100)):
        st, an, lab = ut.make_dataset(cfg, n, s, cond)
        save_ut(out / "ut" / cond, st, an, lab)
        log[f"ut_{cond}"] = {"n": len(lab), "seed": s, "baseline": ut.baseline(cfg, st, an, lab)}

    for cond, n, s in (("train", a.img_train, a.seed), ("shifted", a.img_shifted, a.seed + 100)):
        js = jobs.make_jobs(cfg, seg, dfx, n, s, condition=cond)
        render_set(cfg, js, out / "camera" / cond, s, a.workers)
        log[f"camera_{cond}"] = {"n": len(js), "seed": s,
                                 "negatives": int(sum(j["negative"] for j in js))}

    st_dir = out / "strategy"
    st_dir.mkdir(parents=True, exist_ok=True)
    comp, sens = strategy.compare_and_sensitivity(cfg, a.seed, a.strategy_runs, a.total_km)
    comp.to_csv(st_dir / "compare.csv", index=False)
    sens.to_csv(st_dir / "sensitivity.csv", index=False)
    comp_s, sens_s = strategy.compare_and_sensitivity(cfg_steam, a.seed, a.strategy_runs,
                                                      a.steam_km)
    comp_s.to_csv(st_dir / "compare_steam.csv", index=False)
    sens_s.to_csv(st_dir / "sensitivity_steam.csv", index=False)
    strategy.pit_prior_sensitivity(cfg, a.seed, a.pit_runs, a.total_km).to_csv(
        st_dir / "pit_prior.csv", index=False)
    sw = strategy.sweep(cfg, a.seed, a.sweep_runs, a.sweep_km)
    sw.to_csv(st_dir / "sweep.csv", index=False)
    log["sweep_ai_better"] = f"{int(sw['ai_better'].sum())}/{len(sw)}"

    (out / "eva").mkdir(parents=True, exist_ok=True)
    eva.summary(eva.run(cfg, a.seed, a.eva_runs, a.total_km)).to_csv(
        out / "eva" / "eva_summary.csv", index=False)

    for cond, n, s in (("train", a.ir_train, a.seed), ("shifted", a.ir_shifted, a.seed + 100)):
        ir_jobs = tr.make_ir_jobs(cfg, n, s, cond)
        tr.render_all_ir(cfg, ir_jobs, out / "thermal" / cond, s, workers=a.workers)
        log[f"thermal_{cond}"] = {"n": len(ir_jobs), "seed": s}

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], check=False, cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    log["git_commit"] = commit or None
    log["strategy"] = {"runs": a.strategy_runs, "base_km": a.total_km if a.total_km is not None
                       else params.get(cfg, "network.total_km"),
                       "steam_km": a.steam_km if a.steam_km is not None
                       else params.get(cfg_steam, "network.total_km"),
                       "pit_runs": a.pit_runs, "sweep_runs": a.sweep_runs,
                       "sweep_km": a.sweep_km, "eva_runs": a.eva_runs}
    log["elapsed_s"] = round(time.perf_counter() - t0, 1)
    (out / "manifest.json").write_text(json.dumps(log, indent=2, default=float), encoding="utf-8")
    (out / "DATA_CARD.md").write_text(_card(log), encoding="utf-8")
    print(f"Wrote dataset and manifest to {out}")
    return 0


def _card(log: dict) -> str:
    nw = log["network"]
    st = log["strategy"]
    command = shlex.join(["python", "scripts/produce_data.py", *log["argv"]])
    return f"""# MAEK 합성 데이터셋 카드

가상 제철소 배관망 시뮬레이션으로 만든 합성 데이터입니다. 실제 점검 데이터가 아닙니다.

- 생성 코드: nalziori/MAEK 커밋 `{log['git_commit']}`
- 실행 명령: `OMP_NUM_THREADS=1 {command}`
- 실행 인자와 병합된 기본·증기 설정의 내용은 `manifest.json`에 보존됩니다. 재생성 시 동일한 설정 내용과 코드를 사용하세요.
- 생성 시간: {log['elapsed_s']}초

| 묶음 | 내용 | 규모 |
|---|---|---|
| network | 배관망 구간·특징·결함 정답 | {nw['length_km']:g} km, 구간 {nw['segments']}, 결함 {nw['defects']} (위험 {nw['critical']}) |
| ut/train, ut/shifted | 초음파 A-scan | {log['ut_train']['n']} / {log['ut_shifted']['n']} |
| camera/train, camera/shifted | 부식 이미지·마스크·YOLO-seg 라벨 | {log['camera_train']['n']} / {log['camera_shifted']['n']} |
| strategy | 점검 방식과 민감도 비교 | {st['runs']}회, 기본 {st['base_km']:g} km / 증기 {st['steam_km']:g} km (pit {st['pit_runs']}, sweep {st['sweep_runs']}회 x {st['sweep_km']:g} km) |
| eva | 극값 내부 피팅 회로 분석 | {st['eva_runs']}회 |
| thermal/train, thermal/shifted | 열화상·마스크·YOLO-seg 라벨 | {log['thermal_train']['n']} / {log['thermal_shifted']['n']} |

`shifted`는 학습에 쓰지 않은 어려운 조건(잡음, 극단 온도, 접촉 불량, 조명·분진·증기, 열화상은 맑은 낮·강풍·방사율 설정 오차)입니다. 평가에만 쓰세요.
strategy의 비용·시간·고장 트랩 점검 시간 등은 모두 가정값이며, 증기 시나리오는 `config/scenarios/steam.yaml`을 덮어쓴 결과입니다.
파라미터와 출처는 저장소 `docs/params.md`, 기준 성능은 `docs/results.md`에 있습니다.
"""


if __name__ == "__main__":
    raise SystemExit(main())
