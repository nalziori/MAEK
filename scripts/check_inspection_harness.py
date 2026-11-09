"""Check MAEK demo contracts and reject stale integration evidence after source drift."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "unity/MAEKInspection/Assets/MAEK"
OUT = ROOT / "visualization/inspection_demo"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources() -> list[Path]:
    paths = [ROOT / "maek/inspection_bridge.py", ROOT / "maek/camera/segment.py",
             ROOT / "scripts/check_inspection_harness.py",
             ROOT / "scripts/run_inspection_harness.ps1",
             ROOT / "scripts/start_inspection_bridge.ps1",
             ROOT / "tests/test_inspection_bridge.py",
             ROOT / "tests/test_inspection_harness.py",
             ROOT / "tests/test_worker_safety_context.py",
             ROOT / "tests/test_supplementary_circuits.py",
             ROOT / "scripts/check_supplementary_circuits.py",
             ROOT / "scripts/encode_inspection_video.py",
             ASSETS / "Editor/BuildInspectionTour.cs",
             ASSETS / "Editor/BuildSupplementaryCircuits.cs",
             ASSETS / "Editor/BuildStandaloneTeam.cs",
             ASSETS / "Editor/EnhanceSteelworks.cs",
             ASSETS / "Editor/EnhanceInteriors.cs",
             ASSETS / "Editor/AuditEnhancedColliders.cs",
             ASSETS / "Editor/CaptureInteriorPhotos.cs",
             ASSETS / "Editor/CaptureFactoryPhotos.cs",
             ROOT / "visualization/realism/baseline/source_hashes.json",
             ASSETS / "Editor/VerifyInspectionPlayMode.cs",
             ASSETS / "Scenes/MAEKInspectionDemo.unity",
             ROOT / "unity/MAEKInspection/ProjectSettings/QualitySettings.asset",
             ROOT / "unity/MAEKInspection/ProjectSettings/GraphicsSettings.asset",
             ROOT / "unity/MAEKInspection/ProjectSettings/ProjectSettings.asset",
             ROOT / "unity/MAEKInspection/Packages/manifest.json"]
    paths.extend((ASSETS / "Scripts").glob("*.cs"))
    paths.extend((ASSETS / "Scripts").glob("*.shader"))
    paths.extend((ROOT / "visualization/realism/baseline").glob("*.json"))
    for name in ("inspection_tour.json", "pipe_services.json", "service_drone_routes.json",
                 "maek_manifest.json", "maek_geometry.bytes", "collision_network.json",
                 "interior_rooms.json", "process_context.json", "hydraulic_results.json", "worker_safety_context.json", "supplementary_circuits.json", "supplementary_tour.json"):
        paths.append(ASSETS / "Source" / name)
    for suffix in ("*.asset", "*.mat"):
        paths.extend((ASSETS / "Generated").rglob(suffix))
    return sorted(set(paths))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def validate_worker_safety(data: dict, catalogue: dict) -> None:
    """Reject accident identity substitutions and automated work approval."""
    expected = {p["id"] for p in catalogue["pipes"]}
    services = {p["serviceCode"] for p in catalogue["pipes"]}
    profiles = data.get("profiles", [])
    if (data.get("version") != 1 or len(profiles) != len(services)
            or {p["serviceCode"] for p in profiles} != services
            or any(p.get("permissionStatus") != "not_assessed"
                   or not p.get("workerContext") or not p.get("inspectionLimit")
                   for p in profiles)):
        raise ValueError("Invalid worker safety service profiles")
    cases = data.get("cases", [])
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate worker accident case")
    for case in cases:
        if not case.get("limit") or not case.get("maekContribution"):
            raise ValueError("Missing accident inspection limit")
        if case["kind"] == "reported_accident":
            if (case.get("modelStatus") != "not_modelled" or case.get("pipeIds") != []
                    or not case.get("source", "").startswith("https://")):
                raise ValueError("Reported accident incorrectly mapped to synthetic pipe")
        elif (case["kind"] != "synthetic_example"
              or case.get("modelStatus") != "modelled_synthetic"
              or not case.get("pipeIds") or not set(case["pipeIds"]).issubset(expected)):
            raise ValueError("Unknown synthetic example pipe")
    if sum(c["kind"] == "reported_accident" for c in cases) != 4:
        raise ValueError("Expected four distinct source accident contexts")


def validate_realism_baseline(source_dir: Path, baseline: Path) -> None:
    """Reject visual enrichment that silently changes the process graph or flight plan."""
    for name, expected in load(baseline / "source_hashes.json").items():
        if digest(source_dir / name) != expected:
            raise ValueError(f"Frozen realism baseline changed: {name}")


def validate_plan(plan: dict, pipe_ids: list[str], routes: list[dict]) -> list[str]:
    """Check exact pipe/waypoint/transfer coverage, not just an aggregate count."""
    expected = set(pipe_ids)
    points = plan["points"]
    if (len(expected) != len(pipe_ids) or len(plan["pipeIds"]) != len(expected)
            or set(plan["pipeIds"]) != expected):
        raise ValueError("Pipe catalogue mismatch")
    visits, transfers = plan["visits"], plan["transfers"]
    if len(visits) != len(expected) or {v["pipeId"] for v in visits} != expected:
        raise ValueError("Missing or repeated pipe visit")
    if len(transfers) != len(visits):
        raise ValueError("Missing inter-pipe transfer")
    original = {r["id"]: r["waypoints"] for r in routes}
    samples = [p["sampleId"] for p in points if p["pipeId"]]
    if len(samples) != plan["expectedCaptures"] or len(set(samples)) != len(samples):
        raise ValueError("Duplicate or missing capture sample")
    last_leg = 0
    previous = "OVERVIEW"
    for visit, transfer in zip(visits, transfers):
        pipe_id = visit["pipeId"]
        first, last = visit["firstLeg"], visit["lastLeg"]
        if not (transfer["fromPipe"] == previous and transfer["toPipe"] == pipe_id
                and transfer["firstLeg"] == last_leg
                and transfer["lastLeg"] == first - 1 and last >= first):
            raise ValueError("Broken inter-pipe continuity")
        section = points[first:last + 1]
        reference = original[pipe_id][::-1] if visit["reversed"] else original[pipe_id]
        original_section = [p for p in section if p.get("sourceIndex", -1) >= 0]
        if (len(original_section) != len(reference)
                or [p["sourceIndex"] for p in original_section] != list(range(len(reference)))):
            raise ValueError("Original inspection route truncated")
        for point, source in zip(original_section, reference):
            if point["routePipeId"] != pipe_id or point["phase"] != "inspection":
                raise ValueError("Inspection route assigned to wrong pipe")
            if any(abs(point["position"][axis] - value) > 1e-4
                   for axis, value in zip("xyz", source["position"])):
                raise ValueError("Original pipe waypoint skipped or changed")
        captures = [p for p in section if p["pipeId"]]
        if not captures or len(captures) != visit["captures"]:
            raise ValueError("Unphotographed pipe")
        if any(p["pipeId"] != pipe_id for p in captures):
            raise ValueError("Wrong capture pipe")
        previous, last_leg = pipe_id, last
    if last_leg != len(points) - 1 or plan["radius"] < .12 - 1e-6:
        raise ValueError("Invalid route ending or collision clearance")
    return samples


def validate_session(session: Path, plan: dict, samples: list[str]) -> int:
    captures = list(session.glob("*.capture.json"))
    if len(captures) != len(samples):
        raise ValueError("Missing actual camera captures")
    seen = set()
    planned = {p["sampleId"]: p["pipeId"] for p in plan["points"] if p["pipeId"]}
    for path in captures:
        cap = load(path)
        image = session / (cap["requestId"] + ".png")
        result = load(session / (cap["requestId"] + ".analysis.json"))
        if (cap["sampleId"] in seen or planned.get(cap["sampleId"]) != cap["pipeId"]
                or cap.get("visibleTargetSamples", 0) < 1):
            raise ValueError("Duplicate, wrong-pipe or occluded capture")
        seen.add(cap["sampleId"])
        if not (digest(image) == cap["imageSha256"] == result["imageSha256"]
                and cap["requestId"] == result["requestId"] and result["status"] == "ok"
                and cap["width"] == result["width"] and cap["height"] == result["height"]):
            raise ValueError(f"Evidence provenance mismatch: {path}")
    progress = load(session / "inspection_progress.json")
    if (progress["missingPipes"] or progress["errors"]
            or set(progress["analysedPipes"]) != set(plan["pipeIds"])
            or [o["sampleId"] for o in progress["outcomes"]] != samples
            or any(o["status"] not in ("candidate", "no_candidate")
                   for o in progress["outcomes"])):
        raise ValueError("Incomplete or out-of-order inspection outcomes")
    follow = load(session / "follow_up.json")["rows"]
    if len(follow) != 247 or {r["pipeId"] for r in follow} != set(plan["pipeIds"]):
        raise ValueError("Follow-up catalogue coverage mismatch")
    for row in follow:
        observed = [o for o in progress["outcomes"] if o["pipeId"] == row["pipeId"]]
        candidate = any(o["status"] == "candidate" for o in observed)
        if (row["status"] != ("candidate" if candidate else "no_rgb_candidate")
                or set(row["evidenceRequestIds"]) != {o["requestId"] for o in observed}
                or row["analysedImages"] != len(observed) or not row["action"]
                or row.get("workPermissionStatus") != "not_assessed"
                or row.get("syntheticAsset") is not True
                or not row.get("workerContext") or not row.get("inspectionLimit")):
            raise ValueError("Follow-up does not match captured evidence")
    findings = load(session / "findings.json")["findings"]
    if not any(f["pipeId"] == "BF1-W002" and f["mappedSamples"] >= 2 for f in findings):
        raise ValueError("No image-derived finding on inspection reference pipe")
    return len(captures)


def check(evidence: bool = False, seal: bool = False) -> dict:
    required = [ROOT / "unity/AGENTS.md", ROOT / "docs/inspection-demo.md",
                ROOT / "docs/failures/inspection-demo.md", ROOT / "scripts/run_inspection_harness.ps1",
                ROOT / "tests/test_inspection_bridge.py"]
    for path in required + sources():
        if not path.is_file():
            raise ValueError(f"Missing harness input: {path}")
    plan = load(ASSETS / "Source/inspection_tour.json")
    validate_realism_baseline(ASSETS / "Source", ROOT / "visualization/realism/baseline")
    pipes = load(ASSETS / "Source/pipe_services.json")["pipes"]
    validate_worker_safety(load(ASSETS / "Source/worker_safety_context.json"), {"pipes": pipes})
    from check_supplementary_circuits import validate as validate_supplementary
    validate_supplementary(load(ASSETS / "Source/supplementary_circuits.json"))
    if len(pipes) != 247:
        raise ValueError("Expected the complete 247-pipe scene catalogue")
    samples = validate_plan(plan, [p["id"] for p in pipes],
                            load(ASSETS / "Source/service_drone_routes.json")["routes"])
    hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in sources()}
    if evidence or seal:
        extra_path = ROOT / "visualization/supplementary_circuits/connections_colliders.json"
        extra = load(extra_path)
        if extra["status"] != "PASS" or extra["lines"] != 17 or extra["views"] != 17 or not all(c["pass"] for c in extra["checks"]):
            raise ValueError("Supplementary circuit connections/colliders/views failed")
        interior_dir = ROOT / "visualization/interior_detail"
        interior_build = load(interior_dir / "build_report.json")
        interior_audit = load(interior_dir / "after-interior-colliders.json")
        access_gate = load(interior_dir / "before-interior-colliders.json")
        if (interior_build["status"] != "PASS" or interior_build["rooms"] != 5
                or interior_build["stations"] < 8 or interior_build["closedSpools"] < 6
                or any(r["status"] != "PASS" or not all(c["pass"] for c in r["checks"])
                       for r in (interior_audit, access_gate))
                or interior_audit["segments"] != len(plan["points"]) - 1
                or interior_audit["views"] != len(samples)
                or interior_audit["pipeCount"] != 247):
            raise ValueError("Interior collider/access/closed-spool verification failed")
        geometry_path = ROOT / "visualization/realism/geometry_audit.json"
        geometry = load(geometry_path)
        if (geometry["status"] != "PASS" or geometry["processPipes"] != 247
                or geometry["checkedSegments"] != len(plan["points"]) - 1
                or geometry["checkedViews"] != len(samples)
                or not geometry["originalCollidersPreserved"]
                or not geometry["originalMeshesPreserved"]
                or not geometry["originalProcessSourcesPreserved"]):
            raise ValueError("Realism geometry preservation checks did not pass")
        report = load(OUT / "integration_report.json")
        if (report["status"] != "PASS" or not all(c["pass"] for c in report["checks"])
                or report.get("coveredPipes") != 247 or report["captures"] != len(samples)):
            raise ValueError("Integration checks did not pass")
        live = load(OUT / "play_mode_report.json")
        if (live["status"] != "PASS" or live["captures"] != len(samples)
                or live.get("coveredPipes") != 247 or not live["completed"]
                or live.get("recordedFrames", 0) < 24):
            raise ValueError("Real Play-mode HTTP/coroutine integration did not pass")
        session = Path((OUT / "latest_verification.txt").read_text(encoding="utf-8-sig"))
        validate_session(session, plan, samples)
        validate_session(Path(live["session"]), plan, samples)
        report_hashes = {name: digest(OUT / name) for name in (
            "build_report.json", "integration_report.json", "play_mode_report.json")}
        report_hashes["realism/geometry_audit.json"] = digest(geometry_path)
        report_hashes["supplementary_circuits/connections_colliders.json"] = digest(extra_path)
        for name in ("build_report.json", "after-interior-colliders.json",
                     "before-interior-colliders.json"):
            report_hashes["interior_detail/" + name] = digest(interior_dir / name)
        if seal:
            report_time = (OUT / "integration_report.json").stat().st_mtime
            if any(p.stat().st_mtime > report_time for p in sources()):
                raise ValueError("Sources changed after verification; rerun Unity integration")
            (OUT / "evidence_seal.json").write_text(json.dumps({
                "sources": hashes, "reports": report_hashes,
                "session": str(session),
            }, indent=2), encoding="utf-8")
            outcomes = load(session / "inspection_progress.json")["outcomes"]
            findings = load(session / "findings.json")["findings"]
            with (OUT / "pipe_inspection_summary.csv").open("w", encoding="utf-8-sig",
                                                          newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["pipe_id", "planned_images", "analysed_images", "result",
                                 "mapped_findings", "scope"])
                for visit in plan["visits"]:
                    rows = [o for o in outcomes if o["pipeId"] == visit["pipeId"]]
                    count = sum(f["pipeId"] == visit["pipeId"] for f in findings)
                    state = "candidate" if any(o["status"] == "candidate" for o in rows) \
                        else "no_rgb_candidate_not_integrity_proof"
                    writer.writerow([visit["pipeId"], visit["captures"], len(rows), state,
                                     count, "sampled_synthetic_RGB_not_full_surface"])
        else:
            saved = load(OUT / "evidence_seal.json")
            if saved["sources"] != hashes:
                raise ValueError("STALE: demo source/scene changed; rerun run_inspection_harness.ps1")
            if saved.get("reports") != report_hashes:
                raise ValueError("Integration report changed without a new seal")
    return {"status": "PASS", "source_files": len(hashes), "pipes": len(pipes),
            "capture_stops": len(samples), "transfers": len(plan["transfers"]),
            "evidence_checked": evidence or seal}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", action="store_true")
    parser.add_argument("--seal", action="store_true")
    args = parser.parse_args()
    print(json.dumps(check(args.evidence, args.seal), indent=2))
