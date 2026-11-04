"""Command line interface: python -m maek <cmd>."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from maek import params

STUBS = ["network", "camera-jobs", "render2d", "strategy"]


def _params_table(args) -> int:
    cfg = params.load_config(args.config)
    params.validate(cfg)
    table = params.params_table(cfg)
    print(table)
    if args.write:
        out = Path(__file__).resolve().parents[1] / "docs" / "params.md"
        out.write_text("# 파라미터 표\n\n`python -m maek params-table --write`로 생성됨.\n\n"
                       + table, encoding="utf-8")
    return 0


def _ut(args) -> int:
    from maek import ut

    cfg = params.load_config(args.config)
    params.validate(cfg)
    straight, angle, labels = ut.make_dataset(cfg, args.n, args.seed, args.condition)
    ut.save_dataset(args.out, straight, angle, labels)
    m = ut.baseline(cfg, straight, angle, labels)
    print(f"ut: n={args.n} condition={args.condition} seed={args.seed} -> {args.out}")
    print(f"  thickness MAE      {m['thickness_mae_mm']:.3f} mm")
    print(f"  min-thickness MAE  {m['min_thickness_mae_mm']:.3f} mm")
    print(f"  crack detection    {m['crack_detection_rate']:.3f}")
    print(f"  false alarms       {m['false_alarm_rate']:.3f}")
    return 0


def _stub(args) -> int:
    print(f"{args.cmd}: not implemented yet")
    return 2


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default="config/default.yaml")
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
    for name in STUBS:
        sub.add_parser(name, parents=[common]).set_defaults(func=_stub)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
