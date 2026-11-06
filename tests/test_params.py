import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from maek import params

ROOT = Path(__file__).resolve().parents[1]


def test_h4_release_manifest_and_card(tmp_path):
    cfg = yaml.safe_load((ROOT / "config/default.yaml").read_text(encoding="utf-8"))
    cfg["network"]["segment_m"]["value"] = 40
    config = tmp_path / "custom.yaml"
    config.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    out = tmp_path / "release"
    args = ["--config", str(config), "--out", str(out), "--scenario", "steam",
            "--total-km", "0.5", "--steam-km", "0.5", "--ut-train", "4",
            "--ut-shifted", "4", "--img-train", "2", "--img-shifted", "2",
            "--ir-train", "2", "--ir-shifted", "2", "--strategy-runs", "1",
            "--pit-runs", "1", "--sweep-runs", "1", "--sweep-km", "0.5",
            "--eva-runs", "1", "--workers", "1"]
    subprocess.run([sys.executable, str(ROOT / "scripts/produce_data.py"), *args], cwd=ROOT,
                   env={**os.environ, "OMP_NUM_THREADS": "1"}, check=True, capture_output=True)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    card = (out / "DATA_CARD.md").read_text(encoding="utf-8")
    assert manifest["argv"] == args
    assert manifest["arguments"]["scenario"] == ["steam"]
    assert manifest["effective_config"]["base"]["network"]["segment_m"]["value"] == 40
    assert manifest["effective_config"]["steam"]["network"]["media_mix"]["steam"]["value"] == 0.5
    assert manifest["network"]["length_km"] == 0.5
    assert manifest["camera_train"]["n"] == 2
    assert "0.5 km" in card and str(config) in card
    assert "100km 배관망" not in card


def test_config_validates():
    params.validate(params.load_config(ROOT / "config" / "default.yaml"))


def test_validate_rejects_missing_basis():
    with pytest.raises(ValueError, match="a.b"):
        params.validate({"a": {"b": {"value": 1}}})


def test_dotted_get():
    cfg = params.load_config(ROOT / "config" / "default.yaml")
    assert params.get(cfg, "ut.v_long") == 5920
    assert params.get(cfg, "network.total_km") == 100
    with pytest.raises(KeyError):
        params.get(cfg, "ut.nope")


def test_table_contains_every_leaf():
    cfg = params.load_config(ROOT / "config" / "default.yaml")
    table = params.params_table(cfg)
    for key, _ in params.iter_leaves(cfg):
        assert f"`{key}`" in table


def test_cli_params_table():
    r = subprocess.run([sys.executable, "-m", "maek", "params-table"], cwd=ROOT, check=False,
                       capture_output=True, text=True)
    assert r.returncode == 0 and "항목" in r.stdout


def test_cli_unknown_command_exits_2():
    r = subprocess.run([sys.executable, "-m", "maek", "no-such-command"], cwd=ROOT, check=False,
                       capture_output=True, text=True)
    assert r.returncode == 2


def test_cli_works_from_any_cwd(tmp_path):

    env = {**os.environ, "PYTHONPATH": str(ROOT), "OMP_NUM_THREADS": "1"}
    for args in (["params-table"], ["network", "--total-km", "1", "--out", str(tmp_path / "n")]):
        r = subprocess.run([sys.executable, "-m", "maek", *args], check=False, cwd=tmp_path, env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_default_paths_are_package_relative():
    assert params.DEFAULT_PATH.is_absolute() and params.DEFAULT_PATH.exists()
    from maek import cli

    ns = cli.build_parser().parse_args(["params-table"])
    assert ns.config is None


def test_overlay_merge_and_scenario(tmp_path):
    base = params.load_config()
    cfg = params.load_config(overlays=[{"network": {"total_km": {"value": 3, "assumption": True},
                                                    "media_mix": {"steam": {"value": 1.0,
                                                                            "assumption": True}}}}])
    assert params.get(cfg, "network.total_km") == 3
    assert params.get(cfg, "network.media_mix.steam") == 1.0
    # untouched siblings survive, and the base is not mutated
    assert params.get(cfg, "network.media_mix.oxygen") == 0.08
    assert params.get(base, "network.total_km") == 100
    y = tmp_path / "o.yaml"
    y.write_text("network:\n  segment_m: {value: 25, assumption: true}\n", encoding="utf-8")
    cfg = params.load_config(overlays=[y])
    assert params.get(cfg, "network.segment_m") == 25
    steam = params.load_config(overlays=[params.scenario_path("steam")])
    params.validate(steam)
    assert params.get(steam, "network.total_km") == 20
    assert params.get(steam, "network.media_mix.cooling_water") == 0.0


def test_scenario_path_unknown():
    with pytest.raises(ValueError, match="steam"):
        params.scenario_path("nope")


def test_with_values():
    cfg = params.load_config()
    new = params.with_values(cfg, {"network.total_km": 7, "energy.ambient_c": 5})
    assert params.get(new, "network.total_km") == 7 and params.get(cfg, "network.total_km") == 100
    assert new["energy"]["ambient_c"]["unit"] == "C" and new["energy"]["ambient_c"]["note"]
    with pytest.raises(KeyError):
        params.with_values(cfg, {"network.nope": 1})
    with pytest.raises(KeyError):
        params.with_values(cfg, {"network": 1})


def test_cli_scenario_option(tmp_path):
    from maek import cli

    ns = cli.build_parser().parse_args(["network", "--scenario", "steam"])
    assert ns.scenario == ["steam"]
    assert cli.main(["network", "--scenario", "steam", "--total-km", "1", "--seed", "1",
                     "--out", str(tmp_path)]) == 0
    import pandas as pd

    seg = pd.read_csv(tmp_path / "segments.csv")
    assert set(seg["medium"]) <= {"steam", "condensate", "traced_process"}
