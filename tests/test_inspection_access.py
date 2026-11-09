"""Site-first access must partition exact legacy samples, never invent observations."""
import copy
import hashlib
import json

import pytest

from scripts.check_inspection_access import (
    access_counts,
    validate_access_report,
    validate_interior_report,
    validate_layout_report,
    validate_site_plan,
    validate_site_report,
    validate_site_session,
    validate_sweep_report,
)
from scripts.check_inspection_harness import validate_plan, validate_session


def pose(x):
    return {"x": x, "y": 2.0, "z": 0.0}


def plans():
    ids = ["A", "B", "C"]
    required = []
    for i, pid in enumerate(ids):
        for j in range(2):
            required.append({"pipeId": pid, "routePipeId": pid, "sampleId": f"{pid}/{j}",
                             "position": pose(2 * i + j + 1), "target": pose(2 * i + j + 11),
                             "phase": "inspection", "sourceIndex": -1})
    legacy = {"pipeIds": ids, "points": required, "expectedCaptures": 6}
    access = []
    for i, point in enumerate(required):
        status = "accessible" if i < 3 else ["blocked_clearance", "occluded", "no_route"][i - 3]
        access.append({k: copy.deepcopy(point[k]) for k in ("pipeId", "sampleId", "position", "target", "sourceIndex")})
        access[-1].update(status=status, accessible=status == "accessible", reason=status)
    plan = {"siteFirst": True, "bodyRadius": .24, "clearanceMargin": .10, "radius": .34,
            "pipeIds": ids, "requiredCaptures": 6, "expectedCaptures": 3, "access": access,
            "points": [{"pipeId": "", "position": pose(0), "target": pose(10)}] + copy.deepcopy(required[:3]),
            "transfers": [], "visits": [
                {"pipeId": "A", "captures": 2, "requiredCaptures": 2, "accessStatus": "accessible", "accessReasons": [], "firstLeg": 1, "lastLeg": 2},
                {"pipeId": "B", "captures": 1, "requiredCaptures": 2, "accessStatus": "partial", "accessReasons": ["blocked_clearance"], "firstLeg": 3, "lastLeg": 3},
                {"pipeId": "C", "captures": 0, "requiredCaptures": 2, "accessStatus": "deferred", "accessReasons": ["occluded", "no_route"], "firstLeg": -1, "lastLeg": -1},
            ]}
    return plan, legacy


def audit(plan):
    return {"status": "PASS", "scope": "fixed physical layout", "layoutBefore": "a" * 64,
            "layoutAfter": "a" * 64, "layoutUnchanged": True, "bodyRadius": .24,
            "clearanceMargin": .10, "queryRadius": .34, **access_counts(plan),
            "rows": copy.deepcopy(plan["access"])}


def sweep_report(plan):
    totals = access_counts(plan)
    checks = [{"name": f"flight {i}", "pass": True} for i in range(1, len(plan["points"]))]
    checks.extend({"name": name, "pass": True} for name in
                  ("positive flight envelope", "body plus clearance envelope"))
    for row in plan["access"]:
        if row["accessible"]:
            checks.extend({"name": prefix + row["sampleId"], "pass": True}
                          for prefix in ("capture ", "scheduled reachable capture "))
    return {"status": "PASS", "siteFirst": True, "layoutFirst": True, "accessStatisticsAvailable": True,
            "bodyRadius": .24, "clearanceMargin": .10, "radius": .34,
            "segments": len(plan["points"]) - 1, "views": plan["expectedCaptures"],
            "pipeCount": len(plan["pipeIds"]), "requiredCaptures": plan["requiredCaptures"],
            "scheduledCaptures": plan["expectedCaptures"], "accessibleSamples": plan["expectedCaptures"],
            "deferredSamples": totals["deferredCaptures"], "accessiblePipes": totals["accessiblePipes"],
            "partialPipes": totals["partialPipes"], "deferredPipes": totals["deferredPipes"], "checks": checks}


def report(plan, executed=True):
    result = {"status": "PASS", "siteFirst": True, **access_counts(plan)}
    result["checks"] = [{"name": "equipment placement independent of route", "pass": True}]
    result.update(expectedCaptures=plan["expectedCaptures"], scheduledPipes=2,
                  coveredPipes=2 if executed else 0, captures=plan["expectedCaptures"] if executed else 0)
    return result


def write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def make_session(tmp_path, plan, candidate=False):
    scheduled = [p for p in plan["points"] if p.get("pipeId")]
    outcomes, caps, findings = [], {}, []
    for i, point in enumerate(scheduled):
        rid = f"request-{i}"
        raw = b"unit-test-capture-" + rid.encode()
        sha = hashlib.sha256(raw).hexdigest()
        cap = {"requestId": rid, "pipeId": point["pipeId"], "sampleId": point["sampleId"],
               "visibleTargetSamples": 5, "imageSha256": sha, "width": 64, "height": 36}
        (tmp_path / (rid + ".png")).write_bytes(raw)
        write(tmp_path / (rid + ".capture.json"), cap)
        write(tmp_path / (rid + ".analysis.json"), {"status": "ok", "requestId": rid,
              "imageSha256": sha, "width": 64, "height": 36})
        is_candidate = candidate and point["pipeId"] == "B"
        outcomes.append({"requestId": rid, "pipeId": point["pipeId"], "sampleId": point["sampleId"],
                         "visibleTargetSamples": 5, "status": "candidate" if is_candidate else "no_candidate"})
        caps[point["sampleId"]] = cap
        if is_candidate:
            findings.append({"requestId": rid, "pipeId": point["pipeId"], "imageSha256": sha, "mappedSamples": 4})
    rows, coverage = [], []
    for visit in plan["visits"]:
        pid = visit["pipeId"]
        actual = [o for o in outcomes if o["pipeId"] == pid]
        n, required = len(actual), visit["requiredCaptures"]
        observation = "unobserved" if not n else "partial" if n < required else "observed"
        inspection = "deferred" if not n else "partial" if n < required else "completed"
        detected = any(o["status"] == "candidate" for o in actual)
        status = "inspection_deferred" if not n else "candidate_incomplete" if detected and n < required else "inspection_partial" if n < required else "candidate" if detected else "no_rgb_candidate"
        base = {"pipeId": pid, "plannedImages": required, "scheduledImages": visit["captures"],
                "deferredImages": required - visit["captures"], "analysedImages": n,
                "observationStatus": observation, "inspectionStatus": inspection}
        coverage.append(base)
        rows.append({**base, "status": status, "evidenceRequestIds": [o["requestId"] for o in actual],
                     "action": "검사 보류 포함 · 후속 점검", "workPermissionStatus": "not_assessed",
                     "syntheticAsset": True, "workerContext": "합성 배관", "inspectionLimit": "RGB만 사용"})
    progress = {"plannedPipes": plan["pipeIds"], "analysedPipes": sorted({o["pipeId"] for o in outcomes}),
                "missingPipes": [r["pipeId"] for r in coverage if r["inspectionStatus"] != "completed"],
                "unobservedPipes": [r["pipeId"] for r in coverage if r["observationStatus"] == "unobserved"],
                "unobservedCaptures": [r for r in plan["access"] if not r["accessible"]],
                "requiredCaptures": plan["requiredCaptures"], "expectedCaptures": plan["expectedCaptures"],
                "captures": len(caps), "routeComplete": True, "pipes": coverage,
                "outcomes": outcomes, "errors": []}
    write(tmp_path / "inspection_progress.json", progress)
    write(tmp_path / "follow_up.json", {"rows": rows})
    write(tmp_path / "findings.json", {"findings": findings})
    return progress, rows


def test_site_plan_exact_partition_and_legacy_dispatch():
    plan, legacy = plans()
    assert validate_site_plan(plan, legacy, legacy["pipeIds"]) == ["A/0", "A/1", "B/0"]
    assert validate_plan(plan, legacy["pipeIds"], [], legacy) == ["A/0", "A/1", "B/0"]
    validate_access_report(audit(plan), plan)
    validate_sweep_report(sweep_report(plan), plan)
    validate_site_report(report(plan), plan)
    validate_site_report(report(plan, False), plan, executed=False)


@pytest.mark.parametrize("mutation", ["missing_id", "duplicate_id", "wrong_pipe", "flag", "no_reason", "nan_pose",
                                     "capture_deferred", "missing_visit", "false_complete", "radius", "required", "span"])
def test_site_plan_rejects_false_coverage(mutation):
    plan, legacy = plans()
    if mutation == "missing_id": plan["access"].pop()
    elif mutation == "duplicate_id": plan["access"][-1]["sampleId"] = "A/0"
    elif mutation == "wrong_pipe": plan["access"][0]["pipeId"] = "B"
    elif mutation == "flag": plan["access"][0]["accessible"] = False
    elif mutation == "no_reason": plan["access"][-1]["reason"] = ""
    elif mutation == "nan_pose": plan["access"][0]["position"]["x"] = float("nan")
    elif mutation == "capture_deferred": plan["points"][-1]["sampleId"] = "B/1"
    elif mutation == "missing_visit": plan["visits"].pop()
    elif mutation == "false_complete": plan["visits"][1]["accessStatus"] = "accessible"
    elif mutation == "radius": plan["radius"] = .12
    elif mutation == "required": plan["requiredCaptures"] = 3
    else: plan["visits"][-1]["firstLeg"] = 0
    with pytest.raises(ValueError): validate_site_plan(plan, legacy, legacy["pipeIds"])


@pytest.mark.parametrize("mutation", ["layout", "flag", "count", "row_id", "row_pose", "scope"])
def test_site_audit_rejects_layout_or_partition_changes(mutation):
    plan, _ = plans()
    proof = audit(plan)
    if mutation == "layout": proof["layoutAfter"] = "b" * 64
    elif mutation == "flag": proof["layoutUnchanged"] = False
    elif mutation == "count": proof["deferredCaptures"] -= 1
    elif mutation == "row_id": proof["rows"][-1]["sampleId"] = "C/9"
    elif mutation == "scope": proof["scope"] = ""
    else: proof["rows"][0]["position"]["x"] += 1
    with pytest.raises(ValueError): validate_access_report(proof, plan)


@pytest.mark.parametrize("mutation", ["skip", "duplicate", "blocked", "missing_view", "fake_view", "radius"])
def test_sweep_proof_requires_every_exact_leg_and_sample(mutation):
    plan, _ = plans()
    proof = sweep_report(plan)
    if mutation == "skip": proof["checks"][0]["name"] = "flight 999"
    elif mutation == "duplicate": proof["checks"].append(proof["checks"][0])
    elif mutation == "blocked": proof["checks"][0]["pass"] = False
    elif mutation == "missing_view": proof["checks"].pop()
    elif mutation == "fake_view": proof["checks"].append({"name": "capture C/0", "pass": True})
    else: proof["radius"] = .12
    with pytest.raises(ValueError): validate_sweep_report(proof, plan)


@pytest.mark.parametrize("candidate", [False, True])
def test_site_session_preserves_partial_and_deferred_not_healthy(tmp_path, candidate):
    plan, legacy = plans()
    samples = validate_site_plan(plan, legacy, legacy["pipeIds"])
    make_session(tmp_path, plan, candidate)
    assert validate_site_session(tmp_path, plan, samples) == 3
    assert validate_session(tmp_path, plan, samples) == 3


@pytest.mark.parametrize("mutation", ["partial_healthy", "deferred_healthy", "false_complete", "hide_missing",
                                     "hide_deferred", "wrong_request", "fake_finding", "fake_analysis", "image_hash"])
def test_site_session_rejects_fabricated_observations(tmp_path, mutation):
    plan, _ = plans()
    progress, follow = make_session(tmp_path, plan)
    if mutation == "partial_healthy": follow[1]["status"] = "no_rgb_candidate"
    elif mutation == "deferred_healthy": follow[2]["status"] = "no_rgb_candidate"
    elif mutation == "false_complete": follow[1]["inspectionStatus"] = "completed"
    elif mutation == "hide_missing": progress["missingPipes"] = ["C"]
    elif mutation == "hide_deferred": progress["unobservedCaptures"].pop()
    elif mutation == "wrong_request": progress["outcomes"][0]["requestId"] = "request-1"
    elif mutation == "fake_finding": write(tmp_path / "findings.json", {"findings": [{"pipeId": "C", "requestId": "unobserved"}]})
    elif mutation == "fake_analysis": write(tmp_path / "unobserved.analysis.json", {"status": "ok"})
    else: (tmp_path / "request-0.png").write_bytes(b"different pixels")
    write(tmp_path / "inspection_progress.json", progress)
    write(tmp_path / "follow_up.json", {"rows": follow})
    with pytest.raises(ValueError): validate_site_session(tmp_path, plan, ["A/0", "A/1", "B/0"])


def test_all_deferred_remains_an_explicit_valid_unobserved_catalogue(tmp_path):
    plan, legacy = plans()
    for row in plan["access"]: row.update(accessible=False, status="no_route", reason="no swept path")
    plan["points"] = plan["points"][:1]
    plan["expectedCaptures"] = 0
    for visit in plan["visits"]:
        visit.update(captures=0, accessStatus="deferred", accessReasons=["no_route"], firstLeg=-1, lastLeg=-1)
    assert validate_site_plan(plan, legacy, legacy["pipeIds"]) == []
    make_session(tmp_path, plan)
    assert validate_site_session(tmp_path, plan, []) == 0
    validate_access_report(audit(plan), plan)
    validate_sweep_report(sweep_report(plan), plan)


@pytest.mark.parametrize("field", ["cataloguePipes", "scheduledPipes", "requiredCaptures", "deferredCaptures",
                                   "deferredPipes", "partialPipes", "coveredPipes", "captures"])
def test_completion_report_cannot_turn_scheduled_counts_into_full_coverage(field):
    plan, _ = plans()
    proof = report(plan)
    proof[field] += 1
    with pytest.raises(ValueError): validate_site_report(proof, plan)


def test_layout_diagnostics_accept_blocked_legacy_but_require_preservation():
    _, legacy = plans()
    geometry = {"status": "LAYOUT_CHECKED", "layoutFirst": True, "routeSha256": "legacy-hash",
                "layoutSignature": "a" * 64, "processPipes": 3,
                "checkedSegments": 5, "checkedViews": 6,
                "blockedSegments": 4, "occludedViews": 3,
                "originalCollidersPreserved": True, "originalMeshesPreserved": True,
                "originalProcessSourcesPreserved": True}
    validate_layout_report(geometry, legacy, "legacy-hash")
    for field, value in (("layoutFirst", False), ("routeSha256", "changed"),
                         ("originalCollidersPreserved", False), ("originalMeshesPreserved", False),
                         ("originalProcessSourcesPreserved", False), ("status", "PASS")):
        with pytest.raises(ValueError):
            validate_layout_report({**geometry, field: value}, legacy, "legacy-hash")


def test_source_index_is_legacy_waypoint_index_not_new_global_point_index():
    plan, legacy = plans()
    plan["access"][0]["sourceIndex"] = 1
    with pytest.raises(ValueError, match="sourceIndex"):
        validate_site_plan(plan, legacy, legacy["pipeIds"])


def test_layout_signatures_are_stage_specific_but_final_interior_must_match():
    _, legacy = plans()
    exterior = {"status": "LAYOUT_CHECKED", "layoutFirst": True, "routeSha256": "legacy-hash",
                "layoutSignature": "a" * 64, "processPipes": 3, "checkedSegments": 5,
                "checkedViews": 6, "originalCollidersPreserved": True,
                "originalMeshesPreserved": True, "originalProcessSourcesPreserved": True}
    interior = {"status": "LAYOUT_CHECKED", "layoutFirst": True, "layoutSignature": "b" * 64}
    audit = {"status": "PASS", "siteFirst": True, "layoutFirst": True, "layoutSignature": "b" * 64}
    validate_layout_report(exterior, legacy, "legacy-hash")
    validate_interior_report(interior, audit)
    for changed in ({**audit, "layoutSignature": "c" * 64}, {**audit, "status": "LAYOUT_CHECKED"}):
        with pytest.raises(ValueError):
            validate_interior_report(interior, changed)
    with pytest.raises(ValueError):
        validate_layout_report({**exterior, "layoutSignature": "invalid"}, legacy, "legacy-hash")


def test_build_report_requires_actual_independent_layout_rebuild_check():
    plan, _ = plans()
    build = report(plan, False)
    for checks in ([], [{"name": "equipment placement independent of route", "pass": False}]):
        with pytest.raises(ValueError, match="independent equipment-placement"):
            validate_site_report({**build, "checks": checks}, plan, executed=False)
