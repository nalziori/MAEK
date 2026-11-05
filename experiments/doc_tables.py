"""Print Markdown tables for the docs from a produce_data release directory."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, "/home/user/maek-int")
from maek import eva, params, strategy  # noqa: E402

R = Path(sys.argv[1])
cfg = params.load_config()
S = R / "strategy"
NAMES = ("baseline", "drone", "ai_triage")


def section(t):
    print(f"\n##### {t}\n")


for f in ("compare.csv", "compare_steam.csv"):
    if (S / f).exists():
        section(f)
        print(strategy.to_markdown(pd.read_csv(S / f)))

# cost breakdown (means of counts) for base and steam
unit = {k: params.get(cfg, f"strategy.{k}") for k in strategy.COST_KEYS}
for f in ("compare.csv", "compare_steam.csv"):
    if not (S / f).exists():
        continue
    df = pd.read_csv(S / f).set_index("metric")
    section(f"cost breakdown {f} (억 원)")
    rows = {
        "초음파 1점 비용": lambda n: df.at["ut_points", f"{n}_mean"] * unit["cost_ut_point_krw"],
        "드론 접촉 초음파 추가": lambda n: df.at["drone_ut_points", f"{n}_mean"] * unit["cost_drone_contact_ut_extra_krw"],
        "보온재 해체·복구": lambda n: df.at["insulation_openings", f"{n}_mean"] * unit["cost_insulation_opening_krw"],
        "비계 자재": lambda n: df.at["scaffolds", f"{n}_mean"] * unit["cost_scaffold_krw"],
        "고소작업차": lambda n: df.at["lift_days", f"{n}_mean"] * unit["cost_lift_day_krw"],
        "드론 촬영": lambda n: df.at["drone_km", f"{n}_mean"] * unit["cost_drone_per_km_krw"],
        "AI 처리": lambda n: df.at["ai_km", f"{n}_mean"] * unit["cost_ai_processing_per_km_krw"],
        "PEC 장비": lambda n: df.at["pec_hours", f"{n}_mean"] * unit["cost_pec_hour_krw"],
        "인건비": lambda n: df.at["labor_hours", f"{n}_mean"] * unit["cost_labor_hour_krw"],
    }
    print("| 항목 | " + " | ".join(strategy.LABELS[n] for n in NAMES) + " |")
    print("|---|" + "---|" * 3)
    tot = {n: 0.0 for n in NAMES}
    for k, fn in rows.items():
        vals = {n: fn(n) for n in NAMES}
        for n in NAMES:
            tot[n] += vals[n]
        print(f"| {k} | " + " | ".join(f"{vals[n] / 1e8:.2f}" for n in NAMES) + " |")
    print("| 합계 | " + " | ".join(f"{tot[n] / 1e8:.2f}" for n in NAMES) + " |")
    hours = [h for h in df.index if h.startswith("hours_")]
    print("\nhours:", {h: [round(df.at[h, f"{n}_mean"]) for n in NAMES] for h in hours})
    for c in ("scaffolds", "insulation_openings", "lift_days", "pec_hours", "drone_ut_points", "ut_points"):
        if c in df.index:
            print(c, [round(df.at[c, f"{n}_mean"], 1) for n in NAMES])

if (S / "sensitivity.csv").exists():
    sens = pd.read_csv(S / "sensitivity.csv")
    section("sensitivity ranges")
    for n in ("drone", "ai_triage"):
        c = sens[f"cost_ratio_{n}"]
        print(n, f"cost ratio {c.min():.2f}~{c.max():.2f}")
    print(sens[["cost_key", "factor", "cost_ratio_drone", "cost_ratio_ai_triage"]].round(3).to_string())

for f in ("pit_prior.csv", "sweep.csv"):
    if (S / f).exists():
        section(f)
        print(pd.read_csv(S / f).round(3).to_string())

E = R / "eva" / "eva_summary.csv"
if E.exists():
    section("eva")
    print(eva.to_markdown(pd.read_csv(E)))
