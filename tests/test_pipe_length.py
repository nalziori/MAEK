import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from maek import network, params
from scripts.pipe_length_to_scenario import make_scenario

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "posco_pipe_length_scenario_2026-11-06.json"


def test_generated_scenarios_match_source():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    for site in data["sites"]:
        for name, entry in site["scenarios"].items():
            lengths, total = entry["length_km"], entry["total_km"]
            assert sum(lengths.values()) == pytest.approx(total, abs=0.0055)
            scenario = yaml.safe_load((ROOT / "config/scenarios" / f"{site['site']}_{name}.yaml")
                                      .read_text(encoding="utf-8"))
            assert scenario == make_scenario(site["site"], name, entry)
            assert scenario["network"]["total_km"]["value"] == total
            mix = scenario["network"]["media_mix"]
            assert len(mix) == 9
            assert sum(x["value"] for x in mix.values()) == pytest.approx(1)
            expected = {
                "byproduct_gas_co": sum(lengths[k] for k in
                                        ("bfg", "cog", "ldg", "hydrogen", "natural_gas")),
                "oxygen": lengths["oxygen"], "nitrogen": lengths["nitrogen_argon"],
                "cooling_water": lengths["cooling_and_industrial_water"]
                                 + lengths["wastewater_and_treated_water"],
                "steam": lengths["steam_and_condensate"] * 0.7,
                "condensate": lengths["steam_and_condensate"] * 0.3,
                "pickling_acid_hf": lengths["compressed_air_hydraulic_and_chemicals"] * 0.1,
                "compressed_air": lengths["compressed_air_hydraulic_and_chemicals"] * 0.9,
                "traced_process": 0,
            }
            for key, km in expected.items():
                assert mix[key]["value"] * total == pytest.approx(km, abs=0.0055)
                assert mix[key]["assumption"] is True and mix[key]["note"]


def test_sensitivity_and_invalid_fractions(tmp_path):
    subprocess.run([sys.executable, str(ROOT / "scripts/pipe_length_to_scenario.py"),
                    "--out", str(tmp_path), "--steam-fraction", "0.4", "--acid-fraction", "0.2"],
                   check=True, capture_output=True)
    mix = yaml.safe_load((tmp_path / "pohang_base.yaml").read_text(encoding="utf-8"))["network"]["media_mix"]
    assert mix["steam"]["value"] / (mix["steam"]["value"] + mix["condensate"]["value"]) \
        == pytest.approx(0.4)
    assert mix["pickling_acid_hf"]["value"] / (mix["pickling_acid_hf"]["value"]
           + mix["compressed_air"]["value"]) == pytest.approx(0.2)
    entry = json.loads(SOURCE.read_text(encoding="utf-8"))["sites"][0]["scenarios"]["base"]
    with pytest.raises(ValueError):
        make_scenario("pohang", "base", entry, steam_fraction=1.1)


def test_load_scenario_and_mix_error():
    cfg = params.load_config(overlays=[params.scenario_path("pohang_base")])
    params.validate(cfg)
    seg, _, _ = network.generate_network(cfg, seed=7, total_km=1)
    report = network.mix_error(seg, cfg)
    assert sum(row["actual"] for row in report.values()) == pytest.approx(1)
    for key, row in report.items():
        assert row["target"] == cfg["network"]["media_mix"][key]["value"]
        assert row["actual"] == pytest.approx(seg.loc[seg.medium == key, "length_m"].sum() / 1000)
        assert row["difference"] == pytest.approx(row["actual"] - row["target"])
    result = subprocess.run([sys.executable, "-m", "maek", "params-table", "--scenario", "pohang_base"],
                            cwd=ROOT, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
