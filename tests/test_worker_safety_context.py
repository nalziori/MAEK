"""Accident pipe identity and work permission must not be inferred from RGB evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.check_inspection_harness import validate_worker_safety

SOURCE = Path(__file__).resolve().parents[1] / "unity/MAEKInspection/Assets/MAEK/Source"


def fixture():
    load = lambda name: json.loads((SOURCE / name).read_text(encoding="utf-8-sig"))
    return load("worker_safety_context.json"), load("pipe_services.json")


def test_current_accident_contexts_preserve_unmodelled_identity():
    data, catalogue = fixture()
    validate_worker_safety(data, catalogue)


@pytest.mark.parametrize("accident", [0, 1, 2, 3])
def test_actual_accident_cannot_be_relabelled_as_existing_pipe(accident):
    data, catalogue = fixture()
    data["cases"][accident]["pipeIds"] = ["BF1-G004"]
    data["cases"][accident]["modelStatus"] = "modelled_synthetic"
    with pytest.raises(ValueError, match="Reported accident"):
        validate_worker_safety(data, catalogue)


def test_rgb_inspection_cannot_grant_work_permission():
    data, catalogue = fixture()
    data["profiles"][0]["permissionStatus"] = "approved"
    with pytest.raises(ValueError, match="service profiles"):
        validate_worker_safety(data, catalogue)


def test_missing_medium_profile_and_unknown_scene_pipe_rejected():
    data, catalogue = fixture()
    altered = copy.deepcopy(data)
    altered["profiles"].pop()
    with pytest.raises(ValueError, match="service profiles"):
        validate_worker_safety(altered, catalogue)
    data["cases"][-1]["pipeIds"] = ["NONEXISTENT-OXYGEN"]
    with pytest.raises(ValueError, match="Unknown synthetic"):
        validate_worker_safety(data, catalogue)
