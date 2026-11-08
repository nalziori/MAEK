"""POD sweep: "if the AI's detection rate is X, how do the inspection strategies compare?"

Sweeps the mean detection rate (POD) of one AI at a time, re-runs the strategy simulation, and
writes a CSV plus curve PNGs (ratio vs the human method, 1x line = break-even).

    python scripts/pod_sweep.py                       # 100 km x 20 runs, both access modes
    python scripts/pod_sweep.py --total-km 20 --runs 3 --out out/pod_quick   # quick check
    python scripts/pod_sweep.py --targets 0.2 0.4 0.6 0.8 --sensors camera

Sensors (the AI whose detection rate is swept; only the drone+AI strategy changes, the human and
plain-drone methods keep the current assumptions):
  camera  A's corrosion AI       strategy.pod.camera                       size = defect area
  crack   B's crack classifier   strategy.pod.ut_angle + ut_angle_drone    size = crack depth
  pit     B's pit classifier     strategy.pod.ut_pit_manual + ut_pit_drone size = pit depth
  wall    wall-thinning UT read  strategy.pod.ut_straight + ut_straight_drone (not an AI task)
The x axis is the *mean* POD over the simulated defects (what A/B report as a detection rate),
converted to the logistic intercept b0 here. Assumption for crack/pit: the AI reads every UT
signal of the drone+AI strategy, whether the probe is on a drone or in a person's hand.
All numbers are simulated, not field-verified.
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

# sensor -> (strategy.pod keys moved together, defect rows that give the sizes, per-kind column)
SENSORS = {
    "camera": (("camera",), "camera", "external_corrosion"),
    "crack": (("ut_angle", "ut_angle_drone"), "crack", "crack"),
    "pit": (("ut_pit_manual", "ut_pit_drone"), "pit", "internal_pitting"),
    "wall": (("ut_straight", "ut_straight_drone"), "wall", "fac_thinning"),
}


def _sample(cfg, seed, total_km):
    """Defect sizes of one generated network, used to turn b0 <-> mean POD."""
    d = network.generate_network(cfg, seed, total_km=total_km)[2]
    mode = strategy._mode(d)
    kind = d["kind"].to_numpy()
    depth = d["depth_mm"].to_numpy(float)
    area = d.loc[strategy._visible(d), "area_cm2"].to_numpy(float)
    sizes = {
        "camera": area,
        "crack": depth[(mode == "angle") & (kind == "crack")],
        "pit": depth[(mode == "straight") & (kind == "internal_pitting")],
        "wall": depth[(mode == "straight") & (kind != "internal_pitting")],
    }
    return {k: v[v > 0] for k, v in sizes.items()}


def _b(cfg, key):
    return (strategy._s(cfg, f"pod.{key}.b0"), strategy._s(cfg, f"pod.{key}.b1"))


def b0_for_mean_pod(sizes, b1, target):
    lo, hi = -40.0, 40.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if pod(sizes, mid, b1).mean() < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def summarize(res):
    out = {}
    for n, df in res.items():
        out[n] = {"det": float(df["detection_rate"].mean()),
                  "missed": float(df["missed_high_consequence_critical"].mean()),
                  "cost": float(df["cost_krw"].mean()),
                  "days": float(df["elapsed_days"].mean())}
        for col in df.columns:
            if col.startswith("detection_rate_"):
                out[n][col] = float(df[col].mean())
    return out


def run(args):
    cfg0 = _cfg(argparse.Namespace(config=args.config, scenario=args.scenario, set=args.set))
    sizes = _sample(cfg0, args.seed, max(args.total_km, 100.0))
    for s in args.sensors:
        print(f"[{s}] {len(sizes[SENSORS[s][1]])} defects used for the mean-POD conversion")
    rows = []
    for access in args.access:
        cfg_a = params.with_values(cfg0, {"strategy.human_elevated_access": access})
        s0 = summarize(strategy.run_all(cfg_a, args.seed, args.runs, args.total_km,
                                        strategies=("baseline", "drone")))
        base, dr = s0["baseline"], s0["drone"]
        print(f"[{access}] baseline: det {base['det']:.3f}, cost {base['cost'] / 1e6:,.0f} M KRW")
        for sensor in args.sensors:
            keys, size_key, kind = SENSORS[sensor]
            sz = sizes[size_key]
            now = float(np.mean([pod(sz, *_b(cfg_a, k)).mean() for k in keys]))
            points = [("current", now, None)] + [(f"{t:.2f}", t, t) for t in args.targets]
            for label, mean_pod, target in points:
                cfg = cfg_a if target is None else params.with_values(cfg_a, {
                    f"strategy.pod.{k}.b0": b0_for_mean_pod(sz, _b(cfg_a, k)[1], target)
                    for k in keys})
                ai = summarize(strategy.run_all(cfg, args.seed, args.runs, args.total_km,
                                                strategies=("ai_triage",)))["ai_triage"]
                kcol = f"detection_rate_{kind}"
                rows.append({
                    "sensor": sensor, "access": access, "point": label, "mean_pod": mean_pod,
                    "det_baseline": base["det"], "det_drone": dr["det"], "det_ai": ai["det"],
                    "det_ratio_ai": ai["det"] / base["det"] if base["det"] else np.nan,
                    "kind": kind, "kind_det_baseline": base.get(kcol, np.nan),
                    "kind_det_ai": ai.get(kcol, np.nan),
                    "missed_baseline": base["missed"], "missed_ai": ai["missed"],
                    "missed_ratio_ai": ai["missed"] / base["missed"] if base["missed"] else np.nan,
                    "cost_ratio_drone": dr["cost"] / base["cost"],
                    "cost_ratio_ai": ai["cost"] / base["cost"],
                    "days_ratio_ai": ai["days"] / base["days"],
                })
                r = rows[-1]
                print(f"  {sensor:6s} {label:>7s} pod={mean_pod:.2f}  det x{r['det_ratio_ai']:.2f}"
                      f"  {kind} {r['kind_det_baseline']:.2f}->{r['kind_det_ai']:.2f}"
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

    names = {"camera": t("카메라 AI", "camera AI"), "crack": t("균열 AI", "crack AI"),
             "pit": t("피팅 AI", "pit AI"), "wall": t("두께(감육) 초음파", "wall-thinning UT")}
    kinds = {"external_corrosion": t("외부 부식", "external corrosion"),
             "crack": t("균열", "crack"), "internal_pitting": t("내부 피팅", "internal pitting"),
             "fac_thinning": t("유동가속부식 감육", "FAC thinning")}
    for sensor, g in df.groupby("sensor", sort=False):
        fig, axes = plt.subplots(1, 4, figsize=(17, 4))
        kind = kinds[g["kind"].iloc[0]]
        panels = (("det_ratio_ai", t("위험 결함 발견율 (사람 대비 배)", "risk-defect detection (x human)")),
                  ("kind_det_ai", t(f"{kind} 발견율 (드론+AI, 절대값)", f"{kind} detection (drone+AI)")),
                  ("missed_ratio_ai", t("놓친 고피해 결함 (사람 대비 배)", "missed high-damage (x human)")),
                  ("cost_ratio_ai", t("비용 (사람 대비 배)", "cost (x human)")))
        for ax, (col, title) in zip(axes, panels):
            for access, ga in g.groupby("access"):
                ga = ga.sort_values("mean_pod")
                ax.plot(ga["mean_pod"], ga[col], marker="o", label=ACCESS[access] if ko else access)
                cur = ga[ga["point"] == "current"]
                ax.scatter(cur["mean_pod"], cur[col], s=130, facecolors="none", edgecolors="k")
            if col != "kind_det_ai":
                ax.axhline(1.0, color="gray", ls="--", lw=1)
            ax.set_xlabel(t(f"{names[sensor]} 평균 탐지률", f"{names[sensor]} mean detection rate"))
            ax.set_title(title, fontsize=9)
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
    p.add_argument("--sensors", nargs="+", choices=list(SENSORS), default=["camera", "crack", "pit"])
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
