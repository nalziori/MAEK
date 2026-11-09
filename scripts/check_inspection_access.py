"""Exact access accounting for site-first tours; geometry is verified by Unity sweeps."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from itertools import pairwise
from pathlib import Path

DEFERRED = {"blocked_clearance", "occluded", "no_route"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def indexed(rows, key, label):
    require(isinstance(rows, list), f"Invalid {label} rows")
    require(all(isinstance(row, dict) and isinstance(row.get(key), str) and row[key]
                for row in rows), f"Invalid {label} identifier")
    result = {row[key]: row for row in rows}
    require(len(result) == len(rows), f"Duplicate {label} identifier")
    return result


def vector(value):
    return (isinstance(value, dict) and set(value) == {"x", "y", "z"}
            and all(type(v) in (int, float) and math.isfinite(v) for v in value.values()))


def count(value):
    return type(value) is int and value >= 0


def envelope(value, radius_key="radius"):
    for name, expected in (("bodyRadius", .24), ("clearanceMargin", .10), (radius_key, .34)):
        number = value.get(name)
        require(type(number) in (int, float) and math.isfinite(number)
                and abs(number - expected) <= 1e-6, f"Invalid site-first {name}")


def validate_site_plan(plan: dict, legacy: dict, pipe_ids: list[str]) -> list[str]:
    """Every frozen required sample is either scheduled once or explicitly deferred."""
    require(plan.get("siteFirst") is True, "Expected a site-first plan")
    envelope(plan)
    catalogue = set(pipe_ids)
    require(len(catalogue) == len(pipe_ids) and len(plan.get("pipeIds", [])) == len(catalogue)
            and set(plan["pipeIds"]) == catalogue == set(legacy["pipeIds"]), "Site pipe catalogue mismatch")
    required = indexed([p for p in legacy["points"] if p.get("pipeId")], "sampleId", "legacy sample")
    access = indexed(plan.get("access"), "sampleId", "access sample")
    require(set(access) == set(required), "Access ledger must contain every exact legacy required sample")
    require(count(plan.get("requiredCaptures")) and plan["requiredCaptures"] == len(required)
            == legacy["expectedCaptures"], "Required capture total differs from frozen legacy samples")
    for sid, row in access.items():
        require(row.get("pipeId") == required[sid]["pipeId"] and row["pipeId"] in catalogue,
                "Access sample assigned to wrong pipe")
        status = row.get("status")
        require(status in DEFERRED | {"accessible"} and type(row.get("accessible")) is bool
                and row["accessible"] == (status == "accessible"), "Invalid access status/accessible flag")
        require(isinstance(row.get("reason"), str) and row["reason"].strip(), "Access decision needs a reason")
        require(vector(row.get("position")) and vector(row.get("target")), "Nonfinite access pose")
        require(type(row.get("sourceIndex")) is int and row["sourceIndex"] == required[sid].get("sourceIndex", -1), "Invalid access sourceIndex")
    points = plan.get("points")
    require(isinstance(points, list) and points, "Site route needs a starting pose")
    require(all(isinstance(p, dict) and vector(p.get("position")) and vector(p.get("target"))
                for p in points), "Nonfinite site route pose")
    scheduled = indexed([p for p in points if p.get("pipeId")], "sampleId", "scheduled sample")
    accessible = {sid for sid, row in access.items() if row["accessible"]}
    require(set(scheduled) == accessible, "Scheduled captures must biject exactly with accessible samples")
    require(count(plan.get("expectedCaptures")) and plan["expectedCaptures"] == len(scheduled),
            "Scheduled capture count mismatch")
    for sid, point in scheduled.items():
        row = access[sid]
        require(point.get("pipeId") == row["pipeId"] == point.get("routePipeId")
                and point.get("phase") == "inspection" and point.get("sourceIndex", -1) == row["sourceIndex"], "Wrong-pipe scheduled capture")
        require(all(abs(point[field][axis] - row[field][axis]) <= 1e-4
                    for field in ("position", "target") for axis in "xyz"), "Scheduled capture pose differs from access decision")
    visits = indexed(plan.get("visits"), "pipeId", "site visit")
    require(set(visits) == catalogue, "Every catalogue pipe needs an access visit row")
    required_counts = Counter(row["pipeId"] for row in access.values())
    scheduled_counts = Counter(row["pipeId"] for row in scheduled.values())
    intervals = []
    for pid, visit in visits.items():
        total, available = required_counts[pid], scheduled_counts[pid]
        require(count(visit.get("captures")) and visit["captures"] == available
                and count(visit.get("requiredCaptures")) and visit["requiredCaptures"] == total,
                "Visit required/scheduled capture count mismatch")
        expected_status = "deferred" if available == 0 else "accessible" if available == total else "partial"
        reasons = visit.get("accessReasons")
        require(visit.get("accessStatus") == expected_status and isinstance(reasons, list)
                and all(isinstance(r, str) and r.strip() for r in reasons)
                and (available == total or bool(reasons)), "Visit hides deferred access")
        first, last = visit.get("firstLeg"), visit.get("lastLeg")
        require(type(first) is int and type(last) is int, "Invalid visit leg indices")
        if not available:
            require(first == last == -1, "Deferred visit must not claim a flight/capture span")
            continue
        require(1 <= first <= last < len(points), "Invalid scheduled visit span")
        section = [p for p in points[first:last + 1] if p.get("pipeId")]
        require(len(section) == available and all(p["pipeId"] == pid for p in section), "Visit span misses or includes another pipe capture")
        intervals.append((first, last))
    intervals.sort()
    require(all(a[1] < b[0] for a, b in pairwise(intervals)), "Overlapping site visit spans")
    return [p["sampleId"] for p in points if p.get("pipeId")]


def access_counts(plan: dict) -> dict:
    visits = plan["visits"]
    return {
        "cataloguePipes": len(plan["pipeIds"]),
        "requiredCaptures": plan["requiredCaptures"],
        "scheduledCaptures": plan["expectedCaptures"],
        "deferredCaptures": plan["requiredCaptures"] - plan["expectedCaptures"],
        "accessiblePipes": sum(v["captures"] == v["requiredCaptures"] for v in visits),
        "partialPipes": sum(0 < v["captures"] < v["requiredCaptures"] for v in visits),
        "deferredPipes": sum(v["captures"] == 0 for v in visits),
    }


def validate_access_report(report: dict, plan: dict):
    """Bind fixed-layout proof and every access decision to the current plan."""
    before, after = report.get("layoutBefore"), report.get("layoutAfter")
    require(report.get("status") == "PASS" and report.get("layoutUnchanged") is True
            and isinstance(report.get("scope"), str) and bool(report["scope"].strip())
            and isinstance(before, str) and len(before) == 64
            and all(c in "0123456789abcdef" for c in before.lower()) and before == after,
            "Routing changed layout or lacks matching physical-layout hashes")
    envelope(report, "queryRadius")
    for name, expected in access_counts(plan).items():
        require(type(report.get(name)) is int and report[name] == expected, f"Access report {name} mismatch")
    rows = indexed(report.get("rows"), "sampleId", "reported access sample")
    expected = indexed(plan["access"], "sampleId", "planned access sample")
    require(rows == expected and all(type(r.get("accessible")) is bool
                                    and type(r.get("sourceIndex")) is int for r in rows.values()),
            "Access report decisions differ from exact plan samples")


def validate_sweep_report(report: dict, plan: dict):
    """Check Unity's endpoint/sphere sweeps and target sightlines, by exact leg/sample IDs."""
    require(report.get("status") == "PASS" and report.get("siteFirst") is True
            and report.get("layoutFirst") is True and report.get("accessStatisticsAvailable") is True,
            "Final collider audit must certify the current site-first route")
    envelope(report)
    totals = access_counts(plan)
    expected = {
        "segments": len(plan["points"]) - 1, "views": plan["expectedCaptures"],
        "pipeCount": len(plan["pipeIds"]), "requiredCaptures": plan["requiredCaptures"],
        "scheduledCaptures": plan["expectedCaptures"], "accessibleSamples": plan["expectedCaptures"],
        "deferredSamples": totals["deferredCaptures"], "accessiblePipes": totals["accessiblePipes"],
        "partialPipes": totals["partialPipes"], "deferredPipes": totals["deferredPipes"],
    }
    for name, value in expected.items():
        require(type(report.get(name)) is int and report[name] == value, f"Collider audit {name} mismatch")
    checks = report.get("checks")
    require(isinstance(checks, list) and bool(checks) and all(isinstance(c, dict) and c.get("pass") is True
                                           for c in checks), "Collider sweep/visibility check failed")
    require(all(any(c.get("name") == name for c in checks) for name in
                ("positive flight envelope", "body plus clearance envelope")), "Missing physical-envelope checks")
    required_groups = {
        "flight ": {f"flight {i}" for i in range(1, len(plan["points"]))},
        "capture ": {"capture " + r["sampleId"] for r in plan["access"] if r["accessible"]},
        "scheduled reachable capture ": {"scheduled reachable capture " + r["sampleId"]
                                          for r in plan["access"] if r["accessible"]},
    }
    for prefix, names in required_groups.items():
        actual = [c.get("name") for c in checks if isinstance(c.get("name"), str) and c["name"].startswith(prefix)]
        require(len(actual) == len(set(actual)) and set(actual) == names,
                "Collider report must prove every exact adjacent leg and accessible sample")


def valid_signature(value):
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value.lower()))


def validate_layout_report(report: dict, legacy: dict, legacy_hash: str):
    """Exterior-stage diagnostics precede interior nesting; they are not flight certification."""
    require(report.get("status") == "LAYOUT_CHECKED" and report.get("layoutFirst") is True
            and report.get("routeSha256") == legacy_hash
            and valid_signature(report.get("layoutSignature"))
            and report.get("processPipes") == len(legacy["pipeIds"])
            and report.get("checkedSegments") == len(legacy["points"]) - 1
            and report.get("checkedViews") == legacy["expectedCaptures"]
            and all(report.get(name) is True for name in (
                "originalCollidersPreserved", "originalMeshesPreserved", "originalProcessSourcesPreserved")),
            "Realism layout/hash/preservation checks did not pass")


def validate_interior_report(build: dict, final_audit: dict):
    require(build.get("status") == "LAYOUT_CHECKED" and build.get("layoutFirst") is True
            and valid_signature(build.get("layoutSignature"))
            and build["layoutSignature"] == final_audit.get("layoutSignature")
            and final_audit.get("status") == "PASS" and final_audit.get("siteFirst") is True
            and final_audit.get("layoutFirst") is True,
            "Interior layout stage does not match the final physical audit")


def validate_site_report(report: dict, plan: dict, executed=True):
    """A complete scheduled route never means all required inspections were observed."""
    totals = access_counts(plan)
    scheduled_pipes = totals["accessiblePipes"] + totals["partialPipes"]
    expected = {name: totals[name] for name in (
        "cataloguePipes", "requiredCaptures", "deferredCaptures", "deferredPipes", "partialPipes")}
    expected.update(scheduledPipes=scheduled_pipes, expectedCaptures=plan["expectedCaptures"],
                    captures=plan["expectedCaptures"] if executed else 0,
                    coveredPipes=scheduled_pipes if executed else 0)
    require(report.get("status") == "PASS" and report.get("siteFirst") is True, "Expected site-first PASS report")
    for name, value in expected.items():
        require(type(report.get(name)) is int and report[name] == value, f"Site report {name} mismatch")
    if not executed:
        checks = report.get("checks", [])
        require(any(c.get("name") == "equipment placement independent of route" and c.get("pass") is True
                    for c in checks) and all(c.get("pass") is True for c in checks),
                "Missing independent equipment-placement rebuild proof")


def validate_site_session(session: Path, plan: dict, samples: list[str]) -> int:
    def load(name):
        return json.loads((session / name).read_text(encoding="utf-8-sig"))

    captures = indexed([json.loads(p.read_text(encoding="utf-8-sig")) for p in session.glob("*.capture.json")],
                       "sampleId", "captured sample")
    scheduled = {p["sampleId"]: p for p in plan["points"] if p.get("pipeId")}
    require(set(captures) == set(samples) == set(scheduled), "Missing or fabricated site captures")
    by_request = indexed(list(captures.values()), "requestId", "capture request")
    for sid, cap in captures.items():
        require(cap.get("pipeId") == scheduled[sid]["pipeId"] and type(cap.get("visibleTargetSamples")) is int
                and cap["visibleTargetSamples"] > 0, "Wrong-pipe or occluded site capture")
        request = cap["requestId"]
        require(Path(request).name == request and "/" not in request and "\\" not in request, "Invalid evidence request ID")
        result = load(request + ".analysis.json")
        require(hashlib.sha256((session / (request + ".png")).read_bytes()).hexdigest()
                == cap["imageSha256"] == result.get("imageSha256") and request == result.get("requestId")
                and result.get("status") == "ok" and cap["width"] == result.get("width")
                and cap["height"] == result.get("height"), "Site evidence provenance mismatch")
    require({p.name for p in session.glob("*.png")} == {rid + ".png" for rid in by_request},
            "Image fabricated for an uncaptured/deferred sample")
    require({p.name for p in session.glob("*.analysis.json")} == {rid + ".analysis.json" for rid in by_request},
            "Analysis fabricated for an uncaptured/deferred sample")
    progress = load("inspection_progress.json")
    outcomes = progress.get("outcomes", [])
    require([o.get("sampleId") for o in outcomes] == samples and not progress.get("errors")
            and all(o.get("status") in ("candidate", "no_candidate") for o in outcomes), "Incomplete/out-of-order accessible outcomes")
    for outcome in outcomes:
        cap = captures[outcome["sampleId"]]
        require(outcome.get("pipeId") == cap["pipeId"] and outcome.get("requestId") == cap["requestId"]
                and type(outcome.get("visibleTargetSamples")) is int and outcome["visibleTargetSamples"] > 0,
                "Outcome fabricated without its matching visible capture")
    observed_pipes = {o["pipeId"] for o in outcomes}
    required_counts = Counter(r["pipeId"] for r in plan["access"])
    observed_counts = Counter(o["pipeId"] for o in outcomes)
    incomplete_pipes = {pid for pid in plan["pipeIds"] if observed_counts[pid] < required_counts[pid]}
    require(set(progress.get("analysedPipes", [])) == observed_pipes
            and set(progress.get("missingPipes", [])) == incomplete_pipes
            and set(progress.get("unobservedPipes", [])) == set(plan["pipeIds"]) - observed_pipes
            and set(progress.get("plannedPipes", [])) == set(plan["pipeIds"])
            and progress.get("routeComplete") is True
            and progress.get("requiredCaptures") == plan["requiredCaptures"]
            and progress.get("expectedCaptures") == len(samples) and progress.get("captures") == len(samples),
            "Site progress hides partial/unobserved catalogue pipes")
    unobserved = indexed(progress.get("unobservedCaptures"), "sampleId", "unobserved sample")
    deferred = {r["sampleId"]: r for r in plan["access"] if not r["accessible"]}
    require(set(unobserved) == set(deferred) and all(
        row.get("pipeId") == deferred[sid]["pipeId"] and row.get("status") == deferred[sid]["status"]
        and row.get("accessible") is False and row.get("reason") for sid, row in unobserved.items()
    ), "Progress lost or fabricated deferred required samples")
    pipe_progress = indexed(progress.get("pipes"), "pipeId", "pipe progress")
    require(set(pipe_progress) == set(plan["pipeIds"]), "Progress pipe catalogue mismatch")
    follow = indexed(load("follow_up.json")["rows"], "pipeId", "follow-up pipe")
    require(set(follow) == set(plan["pipeIds"]), "Follow-up catalogue coverage mismatch")
    required = Counter(r["pipeId"] for r in plan["access"])
    available = Counter(r["pipeId"] for r in plan["access"] if r["accessible"])
    for pid, row in follow.items():
        actual = [o for o in outcomes if o["pipeId"] == pid]
        candidate = any(o["status"] == "candidate" for o in actual)
        observation = "unobserved" if not actual else "observed" if len(actual) == required[pid] else "partial"
        status = ("inspection_deferred" if not actual else "candidate_incomplete" if candidate and observation == "partial"
                  else "inspection_partial" if observation == "partial" else "candidate" if candidate else "no_rgb_candidate")
        inspection = "deferred" if observation == "unobserved" else "partial" if observation == "partial" else "completed"
        coverage = pipe_progress[pid]
        for field, value in (("plannedImages", required[pid]), ("scheduledImages", available[pid]),
                             ("deferredImages", required[pid] - available[pid]), ("analysedImages", len(actual)),
                             ("observationStatus", observation), ("inspectionStatus", inspection)):
            require(coverage.get(field) == value, "Pipe progress claims false observation completeness")
        ids = row.get("evidenceRequestIds", [])
        require(row.get("plannedImages") == required[pid] and row.get("scheduledImages") == available[pid]
                and row.get("deferredImages") == required[pid] - available[pid]
                and row.get("analysedImages") == len(actual) and row.get("observationStatus") == observation
                and row.get("status") == status and row.get("inspectionStatus") == inspection and len(ids) == len(actual)
                and set(ids) == {o["requestId"] for o in actual} and row.get("action")
                and row.get("workPermissionStatus") == "not_assessed" and row.get("syntheticAsset") is True
                and row.get("workerContext") and row.get("inspectionLimit"), "Follow-up hides deferred/partial observation or fabricates evidence")
    findings = load("findings.json")["findings"]
    for finding in findings:
        cap = by_request.get(finding.get("requestId"))
        require(cap is not None and cap["pipeId"] == finding.get("pipeId")
                and cap["imageSha256"] == finding.get("imageSha256")
                and type(finding.get("mappedSamples")) is int and finding["mappedSamples"] >= 2
                and any(o["requestId"] == finding["requestId"] and o["status"] == "candidate" for o in outcomes),
                "Finding fabricated for an unobserved/deferred pipe")
    candidate_pipes = {o["pipeId"] for o in outcomes if o["status"] == "candidate"}
    require({f["pipeId"] for f in findings} == candidate_pipes, "Candidate outcomes/findings disagree")
    return len(captures)
