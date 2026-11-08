"""Why does drone+AI cost more than the human method with boom lifts in a scenario?

Runs the strategies for a reference network (default config) and a scenario, splits each cost
into its priced items, and then swaps one resource count at a time (scenario -> reference) to see
which item brings the drone+AI / human cost ratio back down. Run it with the boom-lift access mode
that shows the reversal (x1.01 base network -> x1.26 Pohang/Gwangyang).

    python scripts/cost_reversal.py                                  # pohang_base, 100 km x 3
    python scripts/cost_reversal.py --scenario gwangyang_base --runs 10 --out data/cost_reversal

The swap is an accounting check (counts replaced after the run, labor hours are not re-derived),
so it shows which item matters, not an exact what-if. Simulated numbers, not field-verified.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from maek import strategy
from maek.cli import _cfg

ITEMS = {  # label -> (count column, unit cost key)
    "초음파 점 장비": ("ut_points", "cost_ut_point_krw"),
    "드론 접촉 초음파 추가": ("drone_ut_points", "cost_drone_contact_ut_extra_krw"),
    "보온재 해체": ("insulation_openings", "cost_insulation_opening_krw"),
    "비계": ("scaffolds", "cost_scaffold_krw"),
    "고소작업차": ("lift_days", "cost_lift_day_krw"),
    "드론 촬영": ("drone_km", "cost_drone_per_km_krw"),
    "AI 처리": ("ai_km", "cost_ai_processing_per_km_krw"),
    "PEC 장비": ("pec_hours", "cost_pec_hour_krw"),
    "인건비": ("labor_hours", "cost_labor_hour_krw"),
}


def run(scenarios, args):
    sets = [f"strategy.human_elevated_access={args.access}"] + (args.set or [])
    cfg = _cfg(argparse.Namespace(config=args.config, scenario=scenarios, set=sets))
    res = strategy.run_all(cfg, args.seed, args.runs, args.total_km,
                           strategies=("baseline", "ai_triage"))
    unit = {k: strategy._s(cfg, k) for _, k in ITEMS.values()}
    counts = {n: df.mean(numeric_only=True) for n, df in res.items()}
    return counts, unit


def cost(counts, unit):
    return {lab: float(counts[col]) * unit[key] for lab, (col, key) in ITEMS.items()}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--config", default=None)
    p.add_argument("--scenario", default="pohang_base", help="scenario that shows the reversal")
    p.add_argument("--set", action="append", default=None, metavar="KEY=VALUE")
    p.add_argument("--access", default="lift", choices=["lift", "scaffold"])
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--total-km", type=float, default=100.0)
    p.add_argument("--out", default="data/cost_reversal")
    args = p.parse_args(argv)

    ref_c, ref_u = run(None, args)
    sc_c, sc_u = run([args.scenario], args)
    rows = {}
    for tag, c, u in (("기본망", ref_c, ref_u), (args.scenario, sc_c, sc_u)):
        for n, lab in (("baseline", "사람"), ("ai_triage", "드론+AI")):
            rows[f"{tag} {lab}"] = {k: v / 1e8 for k, v in cost(c[n], u).items()}
    br = pd.DataFrame(rows)
    br.loc["합계"] = br.sum()
    br.loc["드론+AI / 사람"] = float("nan")
    for t in ("기본망", args.scenario):
        br.loc["드론+AI / 사람", f"{t} 드론+AI"] = br.loc["합계", f"{t} 드론+AI"] / br.loc["합계", f"{t} 사람"]
    counts = pd.DataFrame({
        f"{t} {lab}": {c: float(cc[n][c]) for _, (c, _) in ITEMS.items()}
        for t, cc in (("기본망", ref_c), (args.scenario, sc_c))
        for n, lab in (("baseline", "사람"), ("ai_triage", "드론+AI"))})

    human = sum(cost(sc_c["baseline"], sc_u).values())
    ai_now = sum(cost(sc_c["ai_triage"], sc_u).values())
    swap = [{"바꾼 항목": "(없음, 현재)", "드론+AI/사람 비용 비율": ai_now / human}]
    for lab, (col, _) in ITEMS.items():
        c2 = sc_c["ai_triage"].copy()
        c2[col] = ref_c["ai_triage"][col]
        swap.append({"바꾼 항목": f"{lab} 개수를 기본망 값으로",
                     "드론+AI/사람 비용 비율": sum(cost(c2, sc_u).values()) / human})
    swap = pd.DataFrame(swap)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    br.to_csv(out / "cost_breakdown_100m_won_unit_eok.csv", encoding="utf-8-sig")
    counts.to_csv(out / "resource_counts.csv", encoding="utf-8-sig")
    swap.to_csv(out / "swap_test.csv", index=False, encoding="utf-8-sig")
    pd.options.display.float_format = "{:,.2f}".format
    print(f"\n[비용 항목별, 억 원] 접근={args.access}, {args.total_km:g} km x {args.runs}회")
    print(br.to_string())
    print("\n[자원 개수]")
    print(counts.to_string())
    print("\n[하나씩 바꿔 보기: 시나리오의 드론+AI 항목을 기본망 개수로 바꾸면]")
    print(swap.to_string(index=False))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
