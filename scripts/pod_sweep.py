"""POD sweep: "if the AI's detection rate is X, how do the inspection strategies compare?"

Sweeps the mean detection rate (POD) of one sensor at a time, re-runs the strategy simulation,
and writes a CSV plus curve PNGs (ratio vs the human method, 1x line = break-even).

    python scripts/pod_sweep.py                       # 100 km x 20 runs, both access modes
    python scripts/pod_sweep.py --total-km 20 --runs 3 --out out/pod_quick   # quick check
    python scripts/pod_sweep.py --targets 0.2 0.4 0.6 0.8 --sensors camera

Sensors: `camera` (strategy.pod.camera, defect area) and `ut` (drone-contact ultrasound,
strategy.pod.ut_straight_drone / ut_angle_drone, defect depth). The x axis is the *mean* POD over
the simulated defects (what A/B report as a detection rate), converted to the logistic intercept
b0 here. Human-method sensors are not changed. All numbers are simulated, not field-verified.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from maek import network, params, strategy
from maek.cli import _cfg
from maek.pod import pod

ACCESS = {"scaffold": "비계", "lift": "고소작업차"}


def _sample(cfg, seed, total_km):
    """Defects of one generated network, used to turn b0 <-> mean POD."""
    d = network.generate_network(cfg, seed, total_km=total_km)[2]
    vis = strategy._visible(d)
    area = d.loc[vis, "area_cm2"].to_numpy(float)
    mode = strategy._mode(d)
    kind = d["kind"].to_numpy()
    depth = d["depth_mm"].to_numpy(float)[(mode == "straight") & (kind != "internal_pitting")]
    return {"camera": area[area > 0], "ut": depth[depth > 0]}


SENSORS = {"camera": "camera", "ut": "ut_straight_drone"}  # sensor -> main strategy.pod key


def _b(cfg, sensor):
    return (strategy._s(cfg, f"pod.{sensor}.b0"), strategy._s(cfg, f"pod.{sensor}.b1"))


def b0_for_mean_pod(sizes, b1, target):
    lo, hi = -40.0, 40.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if pod(sizes, mid, b1).mean() < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def overrides(cfg, sensor, b0):
    """Config overrides that put `b0` on the sensor (angle UT keeps its offset to straight UT)."""
    if sensor == "camera":
        return {"strategy.pod.camera.b0": b0}
    off = _b(cfg, "ut_angle_drone")[0] - _b(cfg, "ut_straight_drone")[0]
    return {"strategy.pod.ut_straight_drone.b0": b0, "strategy.pod.ut_angle_drone.b0": b0 + off}


def summarize(res):
    return {n: {"det": float(df["detection_rate"].mean()),
                "missed": float(df["missed_high_consequence_critical"].mean()),
                "cost": float(df["cost_krw"].mean()),
                "days": float(df["elapsed_days"].mean())} for n, df in res.items()}


def run(args):
    cfg0 = _cfg(argparse.Namespace(config=args.config, scenario=args.scenario, set=args.set))
    sizes = _sample(cfg0, args.seed, args.total_km)
    rows = []
    for access in args.access:
        cfg_a = params.with_values(cfg0, {"strategy.human_elevated_access": access})
        base = summarize(strategy.run_all(cfg_a, args.seed, args.runs, args.total_km,
                                          strategies=("baseline",)))["baseline"]
        print(f"[{access}] baseline: det {base['det']:.3f}, cost {base['cost'] / 1e6:,.0f} M KRW")
        for sensor in args.sensors:
            main = SENSORS[sensor]
            b0_now, b1 = _b(cfg_a, main)
            points = [("current", float(pod(sizes[sensor], b0_now, b1).mean()), None)]
            points += [(f"{t:.2f}", t, b0_for_mean_pod(sizes[sensor], b1, t)) for t in args.targets]
            for label, mean_pod, b0 in points:
                cfg = cfg_a if b0 is None else params.with_values(
                    cfg_a, overrides(cfg_a, sensor, b0))
                s = summarize(strategy.run_all(cfg, args.seed, args.runs, args.total_km,
                                               strategies=("drone", "ai_triage")))
                ai, dr = s["ai_triage"], s["drone"]
                rows.append({
                    "sensor": sensor, "access": access, "point": label,
                    "mean_pod": mean_pod, "b0": b0_now if b0 is None else b0,
                    "det_baseline": base["det"], "det_drone": dr["det"], "det_ai": ai["det"],
                    "det_ratio_ai": ai["det"] / base["det"] if base["det"] else np.nan,
                    "missed_baseline": base["missed"], "missed_ai": ai["missed"],
                    "missed_ratio_ai": ai["missed"] / base["missed"] if base["missed"] else np.nan,
                    "cost_ratio_drone": dr["cost"] / base["cost"],
                    "cost_ratio_ai": ai["cost"] / base["cost"],
                    "days_ratio_ai": ai["days"] / base["days"],
                })
                r = rows[-1]
                print(f"  {sensor:6s} {label:>7s} pod={mean_pod:.2f}  det x{r['det_ratio_ai']:.2f}"
                      f"  missed x{r['missed_ratio_ai']:.2f}  cost x{r['cost_ratio_ai']:.2f}")
    return pd.DataFrame(rows)


def plot(df, out, total_km, runs):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    korean = [f for f in ("Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR")
              if f in {x.name for x in font_manager.fontManager.ttflist}]
    ko = bool(korean)
    if ko:
        plt.rcParams["font.family"] = korean[0]
    plt.rcParams["axes.unicode_minus"] = False

    def t(k, e):
        return k if ko else e

    names = {"camera": t("카메라 AI", "camera AI"), "ut": t("드론 초음파 AI", "drone UT AI")}
    for sensor, g in df.groupby("sensor"):
        fig, axes = plt.subplots(1, 3, figsize=(13, 4))
        panels = (("det_ratio_ai", t("위험 결함 발견율 (사람 대비 배)", "risk-defect detection (x human)")),
                  ("missed_ratio_ai", t("놓친 고피해 결함 (사람 대비 배)", "missed high-damage (x human)")),
                  ("cost_ratio_ai", t("비용 (사람 대비 배)", "cost (x human)")))
        for ax, (col, title) in zip(axes, panels):
            for access, ga in g.groupby("access"):
                ga = ga.sort_values("mean_pod")
                ax.plot(ga["mean_pod"], ga[col], marker="o", label=ACCESS[access] if ko else access)
                cur = ga[ga["point"] == "current"]
                ax.scatter(cur["mean_pod"], cur[col], s=130, facecolors="none", edgecolors="k")
            ax.axhline(1.0, color="gray", ls="--", lw=1)
            ax.set_xlabel(t(f"{names[sensor]} 평균 탐지률", f"{names[sensor]} mean detection rate"))
            ax.set_title(title, fontsize=10)
            ax.set_ylim(bottom=0)
            ax.grid(alpha=0.3)
        axes[0].legend(title=t("사람 방식의 높은 곳 접근", "human-method access"), fontsize=8)
        fig.suptitle(t(f"{names[sensor]} 탐지률에 따른 드론+AI 결과 — 가상 시뮬레이션, 현장 미검증 "
                       f"(원=현재 가정값, 점선=사람과 같음, {total_km:g} km x {runs}회)",
                       f"Drone+AI vs human by {names[sensor]} rate - simulated, not field-verified "
                       f"(circle = current assumption, dashed = same as human, {total_km:g} km x {runs})"),
                     fontsize=10)
        fig.tight_layout()
        path = out / f"pod_sweep_{sensor}.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        print(f"wrote {path}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--config", default=None)
    p.add_argument("--scenario", action="append", default=None, metavar="NAME")
    p.add_argument("--set", action="append", default=None, metavar="KEY=VALUE")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--runs", type=int, default=20)
    p.add_argument("--total-km", type=float, default=100.0)
    p.add_argument("--targets", type=float, nargs="+", default=[0.3, 0.5, 0.7, 0.9],
                   help="mean detection rates to sweep (the current assumption is always added)")
    p.add_argument("--sensors", nargs="+", choices=list(SENSORS), default=list(SENSORS))
    p.add_argument("--access", nargs="+", choices=list(ACCESS), default=list(ACCESS),
                   help="how the human method reaches high places")
    p.add_argument("--out", default="data/pod_sweep")
    args = p.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df = run(args)
    df.to_csv(out / "pod_sweep.csv", index=False, encoding="utf-8-sig")
    print(f"wrote {out / 'pod_sweep.csv'}")
    plot(df, out, args.total_km, args.runs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
