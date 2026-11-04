import subprocess
import sys
from pathlib import Path

import pytest

from maek import params

ROOT = Path(__file__).resolve().parents[1]


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


def test_cli_stub_exits_2():
    r = subprocess.run([sys.executable, "-m", "maek", "strategy"], cwd=ROOT, check=False,
                       capture_output=True, text=True)
    assert r.returncode == 2
