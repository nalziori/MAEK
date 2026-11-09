"""Validate scenario targets and separate test expectations from sensor capability."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "unity/MAEKInspection/Assets/MAEK/Source"
EXPECTED = {"corrosion": "corrosion_candidate", "clean": "no_corrosion_candidate",
            "paint": "no_corrosion_candidate", "low_light": "quality_recheck",
            "occlusion": "not_visible", "analysis_offline": "analysis_error",
            "camera_offline": "camera_error", "ut_required": "additional_sensor_required",
            "ir_required": "additional_sensor_required"}


def validate(data: dict, catalogue: dict, extra: dict) -> None:
    ids = {p["id"] for p in catalogue["pipes"]} | {p["id"] for p in extra["lines"]}
    rows = data["scenarios"]
    assert data["version"] == 1 and len(rows) >= 9
    assert len({r["id"] for r in rows}) == len(rows), "duplicate scenario"
    for row in rows:
        assert row["pipeId"] in ids, "unknown pipe"
        assert row["mode"] in EXPECTED, "unknown sensor condition"
        assert row["expected"] == EXPECTED[row["mode"]], "unsupported diagnosis"
        assert row["title"] and row["description"] and row["capability"]
    assert set(EXPECTED) <= {r["mode"] for r in rows}, "missing negative/quality/sensor conditions"


if __name__ == "__main__":
    load = lambda n: json.loads((SOURCE / n).read_text(encoding="utf-8-sig"))
    validate(load("inspection_scenarios.json"), load("pipe_services.json"), load("supplementary_circuits.json"))
    print("PASS: scenario target IDs, positive/negative/fault cases, UT/IR availability limits")
