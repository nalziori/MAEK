"""A repeated pipe or a skipped transfer must never satisfy full-network coverage."""
import copy
import hashlib
import json

import pytest

from scripts.check_inspection_harness import validate_plan, validate_realism_baseline


def test_realism_rejects_silent_route_or_pipe_edits(tmp_path):
    source = tmp_path / "source"
    baseline = tmp_path / "baseline"
    source.mkdir()
    baseline.mkdir()
    names = ("inspection_tour.json", "pipe_services.json")
    hashes = {}
    for name in names:
        (source / name).write_bytes(b'{"unchanged": true}')
        hashes[name] = hashlib.sha256((source / name).read_bytes()).hexdigest()
    (baseline / "source_hashes.json").write_text(json.dumps(hashes))
    validate_realism_baseline(source, baseline)
    for name in names:
        (source / name).write_bytes(b'{"unchanged": false}')
        with pytest.raises(ValueError, match="Frozen realism baseline changed"):
            validate_realism_baseline(source, baseline)
        (source / name).write_bytes(b'{"unchanged": true}')


def fixture():
    points = [{"position": {"x": 0, "y": 3, "z": 0}, "pipeId": ""}]
    visits, transfers, routes = [], [], []
    previous, last = "OVERVIEW", 0
    for i, name in enumerate(("A", "B", "C")):
        points.append({"pipeId": ""})
        first = len(points)
        waypoints = []
        for j in range(2):
            pos = [i * 10 + j, 3, 0]
            points.append({"position": dict(zip("xyz", pos)), "pipeId": name,
                           "routePipeId": name, "phase": "inspection", "sourceIndex": j,
                           "sampleId": f"{name}/{j}"})
            waypoints.append({"position": pos})
        transfers.append({"fromPipe": previous, "toPipe": name, "firstLeg": last,
                          "lastLeg": first - 1})
        visits.append({"pipeId": name, "firstLeg": first, "lastLeg": len(points) - 1,
                       "captures": 2, "reversed": False})
        routes.append({"id": name, "waypoints": waypoints})
        previous, last = name, len(points) - 1
    return {"pipeIds": ["A", "B", "C"], "points": points, "visits": visits,
            "transfers": transfers, "expectedCaptures": 6, "radius": .119999997}, routes


def test_complete_route_and_float32_radius():
    plan, routes = fixture()
    assert len(validate_plan(plan, ["A", "B", "C"], routes)) == 6


@pytest.mark.parametrize("mutation", ["duplicate_pipe", "missing_transfer", "cut",
                                     "skip_waypoint", "duplicate_capture", "wrong_pipe"])
def test_false_coverage_rejected(mutation):
    plan, routes = fixture()
    plan = copy.deepcopy(plan)
    if mutation == "duplicate_pipe":
        plan["visits"][2]["pipeId"] = "A"
    elif mutation == "missing_transfer":
        plan["transfers"].pop()
    elif mutation == "cut":
        plan["transfers"][1]["firstLeg"] += 1
    elif mutation == "skip_waypoint":
        plan["points"][2]["position"]["x"] += 1
    elif mutation == "duplicate_capture":
        plan["points"][3]["sampleId"] = plan["points"][2]["sampleId"]
    else:
        plan["points"][3]["pipeId"] = "B"
    with pytest.raises(ValueError):
        validate_plan(plan, ["A", "B", "C"], routes)
