import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("supplementary_check", ROOT / "scripts/check_supplementary_circuits.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
DATA = json.loads((module.SOURCE / "supplementary_circuits.json").read_text(encoding="utf-8"))


def test_reference_topology():
    module.validate(DATA)


def test_oxygen_cannot_connect_to_sinter():
    broken = copy.deepcopy(DATA)
    broken["lines"][0]["to"] = "SINTER.HEADER"
    with pytest.raises(AssertionError, match="cross-medium"):
        module.validate(broken)


def test_disconnected_equipment_is_rejected():
    broken = copy.deepcopy(DATA)
    broken["lines"][4]["from"] = "O2.SUPPLY"
    with pytest.raises(AssertionError, match="dead-ended"):
        module.validate(broken)


def test_duplicate_line_is_rejected():
    broken = copy.deepcopy(DATA)
    broken["lines"][-1]["id"] = broken["lines"][0]["id"]
    with pytest.raises(AssertionError):
        module.validate(broken)
