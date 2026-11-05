"""Command line interface: python -m maek <cmd>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from maek import params

STUBS: list[str] = []


def _cfg(args) -> dict:
    """Load --config, apply --scenario overlays in order, validate."""
    overlays = [params.scenario_path(n) for n in (getattr(args, "scenario", None) or [])]
    cfg = params.load_config(args.config, overlays)
    params.validate(cfg)
    return cfg


def _params_table(args) -> int:
    cfg = _cfg(args)
    table = params.params_table(cfg)
    print(table)
    if args.write:
        out = Path(__file__).resolve().parents[1] / "docs" / "params.md"
        out.write_text("# 파라미터 표\n\n`python -m maek params-table --write`로 생성됨.\n\n"
                       + table, encoding="utf-8")
    return 0


def _ut(args) -> int:
    from maek import ut

    cfg = _cfg(args)
    straight, angle, labels = ut.make_dataset(cfg, args.n, args.seed, args.condition)
    ut.save_dataset(args.out, straight, angle, labels)
    m = ut.baseline(cfg, straight, angle, labels)
    print(f"ut: n={args.n} condition={args.condition} seed={args.seed} -> {args.out}")
    print(f"  thickness MAE      {m['thickness_mae_mm']:.3f} mm")
    print(f"  min-thickness MAE  {m['min_thickness_mae_mm']:.3f} mm")
    print(f"  crack detection    {m['crack_detection_rate']:.3f}")
    print(f"  false alarms       {m['false_alarm_rate']:.3f}")
    return 0


def _strategy(args) -> int:
    from maek import strategy

    cfg = _cfg(args)
    cmp_df, sens = strategy.compare_and_sensitivity(cfg, args.seed, args.runs, args.total_km)
    out = Path(args.out) / "strategy"
    out.mkdir(parents=True, exist_ok=True)
    cmp_df.to_csv(out / "compare.csv", index=False, encoding="utf-8")
    sens.to_csv(out / "sensitivity.csv", index=False, encoding="utf-8")
    print(strategy.to_markdown(cmp_df))
    print()
    print(strategy.to_markdown(sens, "{:.3f}"))
    print(f"wrote: {out / 'compare.csv'}, {out / 'sensitivity.csv'}")
    return 0


def _network(args) -> int:
    from maek import network

    cfg = _cfg(args)
    seg, feat, dfx = network.generate_network(cfg, args.seed, total_km=args.total_km)
    paths = network.save_network(args.out, seg, feat, dfx)
    print(network.summary(seg, feat, dfx))
    print("wrote: " + ", ".join(str(p) for p in paths))
    return 0


def _eva(args) -> int:
    from maek import eva

    cfg = _cfg(args)
    df = eva.run(cfg, args.seed, args.runs, args.total_km)
    summ = eva.summary(df)
    out = Path(args.out) / "eva"
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "eva_runs.csv", index=False, encoding="utf-8")
    summ.to_csv(out / "eva_summary.csv", index=False, encoding="utf-8")
    print(eva.to_markdown(summ))
    print(f"wrote: {out / 'eva_runs.csv'}, {out / 'eva_summary.csv'}")
    return 0


def _camera_jobs(args) -> int:
    from maek import network
    from maek.camera import jobs

    cfg = _cfg(args)
    seg, _, dfx = network.generate_network(cfg, args.seed)
    js = jobs.make_jobs(cfg, seg, dfx, args.n, args.seed)
    path = jobs.save_jobs(Path(args.out) / "camera" / "jobs.json", js)
    print(f"wrote {len(js)} jobs ({sum(j['negative'] for j in js)} negative) -> {path}")
    return 0


def _render2d(args) -> int:
    import time

    from maek.camera import composite2d, jobs

    cfg = _cfg(args)
    cam = Path(args.out) / "camera"
    js = jobs.load_jobs(cam / "jobs.json")
    t0 = time.perf_counter()
    ds = composite2d.render_all(cfg, js, cam, args.seed)
    dt = time.perf_counter() - t0
    print(f"rendered {len(js)} images in {dt:.1f}s ({len(js) / dt:.1f} img/s) -> {ds}")
    return 0


def _evaluate(args) -> int:
    from maek import evaluate

    cfg = _cfg(args)
    res = evaluate.run_all(cfg, args.out, args.seed, args.n_camera, args.n_ut,
                           args.strategy_runs)
    print(evaluate.tables_markdown(res))
    print(f"wrote: {args.out}/camera_metrics.csv, ut_metrics.csv, pod.csv, results_tables.md")
    return 0


def _onboard(args) -> int:
    from maek import onboard

    cfg = _cfg(args)
    df = onboard.run_all(cfg, args.out, seed=args.seed, n_images=args.n_images, n_ut=args.n_ut,
                         config_label=args.config or str(params.DEFAULT_PATH))
    print(onboard.to_markdown(df))
    print(f"wrote: {args.out}/onboard.csv")
    return 0


def _thermal(args) -> int:
    import time

    from maek import thermal_render as tr

    cfg = _cfg(args)
    out = Path(args.out) / "thermal"
    jobs = tr.make_ir_jobs(cfg, args.n, args.seed, args.condition)
    t0 = time.perf_counter()
    ds = tr.render_all_ir(cfg, jobs, out, args.seed)
    dt = time.perf_counter() - t0
    print(f"rendered {len(jobs)} IR images in {dt:.1f}s ({len(jobs) / dt:.1f} img/s incl. PNG) -> {ds}")
    met, df = tr.evaluate_ir(cfg, args.n, args.seed, args.condition, jobs=jobs)
    print(tr.metrics_markdown({args.condition: met}))
    print(f"detector {met['detect_img_per_s']:.1f} img/s, render {met['render_img_per_s']:.1f} img/s")
    df.to_csv(out / "hitmiss.csv", index=False, encoding="utf-8")
    return 0


def _thermal_pod(args) -> int:
    from maek import thermal
    from maek import thermal_render as tr

    cfg = _cfg(args)
    for cond in ("train", "shifted"):
        met, df = tr.evaluate_ir(cfg, args.n, args.seed, cond)
        fit = tr.fit_ir_pod(cfg, df=df)
        trap = thermal.trap_pods(cfg, cond, 4000, args.seed)
        print(f"## {cond} (n={args.n}, FP/img {met['fp_per_image']:.2f})")
        print("| class | b0 | b1 | n | hit rate |\n|---|---|---|---|---|")
        for k, f in fit.items():
            print(f"| {k} | {f['b0']:.2f} | {f['b1']:.2f} | {f['n']} | {f['hit_rate']:.2f} |")
        print("trap: " + ", ".join(f"{k}={v:.3f}" for k, v in trap.items()) + "\n")
    return 0


def _stub(args) -> int:
    print(f"{args.cmd}: not implemented yet")
    return 2


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=None,
                        help="config YAML (default: the packaged config/default.yaml)")
    common.add_argument("--scenario", action="append", default=None, metavar="NAME",
                        help="overlay config/scenarios/NAME.yaml (repeatable)")
    common.add_argument("--seed", type=int, default=0)
    common.add_argument("--out", default="data/")
    p = argparse.ArgumentParser(prog="maek")
    sub = p.add_subparsers(dest="cmd", required=True)
    pt = sub.add_parser("params-table", parents=[common], help="print parameter table")
    pt.add_argument("--write", action="store_true", help="write docs/params.md")
    pt.set_defaults(func=_params_table)
    u = sub.add_parser("ut", parents=[common], help="UT A-scan dataset + baseline")
    u.add_argument("--n", type=int, default=2000)
    u.add_argument("--condition", choices=["train", "shifted"], default="train")
    u.set_defaults(func=_ut)
    nw = sub.add_parser("network", parents=[common], help="generate pipe network + defects")
    nw.add_argument("--total-km", type=float, default=None, help="override network.total_km")
    nw.set_defaults(func=_network)
    ea = sub.add_parser("eva", parents=[common], help="extreme-value (Gumbel) pitting circuit analysis")
    ea.add_argument("--runs", type=int, default=10)
    ea.add_argument("--total-km", type=float, default=None, help="override network.total_km")
    ea.set_defaults(func=_eva)
    cj = sub.add_parser("camera-jobs", parents=[common], help="sample camera render jobs")
    cj.add_argument("--n", type=int, default=300)
    cj.set_defaults(func=_camera_jobs)
    th = sub.add_parser("thermal", parents=[common], help="IR images + detector metrics")
    th.add_argument("--n", type=int, default=300)
    th.add_argument("--condition", choices=["train", "shifted"], default="train")
    th.set_defaults(func=_thermal)
    tp = sub.add_parser("thermal-pod", parents=[common], help="fit IR POD params from simulator")
    tp.add_argument("--n", type=int, default=600)
    tp.set_defaults(func=_thermal_pod)
    sub.add_parser("render2d", parents=[common], help="render jobs.json (2D)"
                   ).set_defaults(func=_render2d)
    st = sub.add_parser("strategy", parents=[common], help="human+scaffold vs drone vs drone+AI comparison")
    st.add_argument("--runs", type=int, default=20)
    st.add_argument("--total-km", type=float, default=None, help="override network.total_km")
    st.set_defaults(func=_strategy)
    ev = sub.add_parser("evaluate", parents=[common], help="evaluate 3 functions (train/shifted)")
    ev.add_argument("--n-camera", type=int, default=None, help="images per condition")
    ev.add_argument("--n-ut", type=int, default=None, help="UT samples per condition")
    ev.add_argument("--strategy-runs", type=int, default=10)
    ev.set_defaults(func=_evaluate)
    ob = sub.add_parser("onboard", parents=[common], help="CPU latency/memory approximation")
    ob.add_argument("--n-images", type=int, default=None)
    ob.add_argument("--n-ut", type=int, default=None)
    ob.set_defaults(func=_onboard)
    for name in STUBS:
        sub.add_parser(name, parents=[common]).set_defaults(func=_stub)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
