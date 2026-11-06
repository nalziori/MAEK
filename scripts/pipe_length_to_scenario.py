"""Convert synthetic site pipe-length estimates to MAEK scenario overlays."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "posco_pipe_length_scenario_2026-11-06.json"
OUTPUT = ROOT / "config" / "scenarios"


def make_scenario(site, scenario, data, steam_fraction=0.7, acid_fraction=0.1,
                  source_name=SOURCE.name):
    """Map rounded source lengths to normalized medium probabilities."""
    if not all(math.isfinite(x) and 0 <= x <= 1 for x in (steam_fraction, acid_fraction)):
        raise ValueError("split fractions must be between 0 and 1")
    lengths = data["length_km"]
    total = data["total_km"]
    if not math.isfinite(total) or total <= 0 or any(
        not math.isfinite(v) or v < 0 for v in lengths.values()
    ):
        raise ValueError("lengths must be finite and nonnegative, with positive total")
    # Eleven source entries are rounded independently to 0.001 km.
    source_sum = sum(lengths.values())
    if abs(source_sum - total) > 0.0055 + 1e-9:
        raise ValueError("source lengths do not sum to total within rounding tolerance")
    steam = lengths["steam_and_condensate"]
    mixed = lengths["compressed_air_hydraulic_and_chemicals"]
    groups = {
        "cooling_water": (lengths["cooling_and_industrial_water"]
                          + lengths["wastewater_and_treated_water"], "냉각·공업용수 + 폐수·처리수"),
        "steam": (steam * steam_fraction, f"증기·응축수 중 증기 {steam_fraction:g}"),
        "byproduct_gas_co": (sum(lengths[k] for k in ("bfg", "cog", "ldg", "hydrogen",
                                                        "natural_gas")),
                             "BFG·COG·LDG·수소·천연가스를 피해등급 5 가스로 묶음"),
        "oxygen": (lengths["oxygen"], "산소"),
        "nitrogen": (lengths["nitrogen_argon"], "질소·아르곤을 질소로 묶음"),
        "pickling_acid_hf": (mixed * acid_fraction, f"압축공기·유압·화학물 중 산세액 {acid_fraction:g}"),
        "compressed_air": (mixed * (1 - acid_fraction), f"압축공기·유압·화학물의 나머지 {1-acid_fraction:g}"),
        "condensate": (steam * (1 - steam_fraction), f"증기·응축수 중 응축수 {1-steam_fraction:g}"),
        "traced_process": (0.0, "원본에 별도 항목 없음"),
    }
    note = f"{source_name}: {site}/{scenario}; 합성 가정, 실제 설비 목록 아님"
    mix = {key: {"value": km / source_sum, "assumption": True,
                 "note": f"{note}; {reason}; 반올림 합계로 정규화"}
           for key, (km, reason) in groups.items()}
    return {"network": {"total_km": {"value": total, "unit": "km", "assumption": True,
                                    "note": note}, "media_mix": mix}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, default=OUTPUT)
    parser.add_argument("--steam-fraction", type=float, default=0.7)
    parser.add_argument("--acid-fraction", type=float, default=0.1)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    scenarios = [(site["site"], name, make_scenario(site["site"], name, entry,
                  args.steam_fraction, args.acid_fraction, args.input.name))
                 for site in data["sites"] for name, entry in site["scenarios"].items()]
    args.out.mkdir(parents=True, exist_ok=True)
    for site, name, cfg in scenarios:
        path = args.out / f"{site}_{name}.yaml"
        path.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
