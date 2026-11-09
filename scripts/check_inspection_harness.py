"""Check MAEK demo contracts and reject stale integration evidence after source drift."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

if __package__:
    from .check_inspection_access import (
        validate_access_report,
        validate_interior_report,
        validate_layout_report,
        validate_site_plan,
        validate_site_report,
        validate_site_session,
        validate_sweep_report,
    )
else:
    from check_inspection_access import (
        validate_access_report,
        validate_interior_report,
        validate_layout_report,
        validate_site_plan,
        validate_site_report,
        validate_site_session,
        validate_sweep_report,
    )

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "unity/MAEKInspection/Assets/MAEK"
OUT = ROOT / "visualization/inspection_demo"
UI_SOURCES = frozenset({
    "maek/web/existing-dashboard-adapter.js", "maek/web/existing-dashboard-adapter.css",
    "dashboard/index.html", "dashboard/operations.js", "dashboard/operations.css",
    "dashboard/operations-data.js", "dashboard/inspection-evidence.js",
})
UI_REFRESH_SOURCES = UI_SOURCES | {
    "scripts/check_inspection_harness.py", "tests/test_inspection_harness.py",
}
UI_CHECKS = {
    "scenarioControlsAbsent": True, "scenarioEvaluationAbsent": True,
    "storedModePreserved": True, "desktopOverflow": False,
    "mobileOverflow": False, "javascriptExceptions": 0,
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources() -> list[Path]:
    paths = [ROOT / "maek/inspection_bridge.py", ROOT / "maek/inspection_dashboard.py", ROOT / "maek/camera/segment.py",
             ROOT / "tests/test_inspection_dashboard.py", ROOT / "tests/test_inspection_scenarios.py", ROOT / "scripts/check_inspection_scenarios.py",
             ROOT / "scripts/check_inspection_harness.py",
             ROOT / "scripts/check_inspection_access.py", ROOT / "tests/test_inspection_access.py",
             ROOT / "scripts/run_inspection_harness.ps1",
             ROOT / "scripts/start_inspection_bridge.ps1",
             ROOT / "tests/test_inspection_bridge.py",
             ROOT / "tests/test_inspection_harness.py",
             ROOT / "tests/test_worker_safety_context.py",
             ROOT / "tests/test_supplementary_circuits.py",
             ROOT / "scripts/check_supplementary_circuits.py",
             ROOT / "scripts/encode_inspection_video.py",
             ASSETS / "Editor/BuildInspectionTour.cs", ASSETS / "Editor/SiteInspectionPlanner.cs",
             ASSETS / "Editor/BuildSupplementaryCircuits.cs",
             ASSETS / "Editor/BuildStandaloneTeam.cs",
             ASSETS / "Editor/VerifyInspectionScenarios.cs",
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
    paths.extend((ROOT / "maek/web").glob("existing-dashboard-adapter.*"))
    for name in ("index.html", "operations.js", "operations.css", "operations-data.js",
                 "inspection-evidence.js"):
        paths.append(ROOT / "dashboard" / name)
    paths.extend((ASSETS / "Scripts").glob("*.shader"))
    paths.extend((ROOT / "visualization/realism/baseline").glob("*.json"))
    for name in ("inspection_tour.json", "pipe_services.json", "service_drone_routes.json",
                 "maek_manifest.json", "maek_geometry.bytes", "collision_network.json",
                 "interior_rooms.json", "process_context.json", "hydraulic_results.json", "worker_safety_context.json", "supplementary_circuits.json", "supplementary_tour.json", "inspection_scenarios.json"):
        paths.append(ASSETS / "Source" / name)
    site_plan = ASSETS / "Source/site_inspection_tour.json"
    if site_plan.is_file():
        paths.append(site_plan)
    optional_site = ASSETS / "Source/site_supplementary_tour.json"
    if optional_site.is_file():
        paths.append(optional_site)
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


def validate_plan(plan: dict, pipe_ids: list[str], routes: list[dict],
                  legacy_plan: dict | None = None) -> list[str]:
    """Keep frozen legacy validation; site tours account for every required sample."""
    if plan.get("siteFirst") is True:
        if legacy_plan is None:
            raise ValueError("Site-first validation requires the frozen legacy plan")
        return validate_site_plan(plan, legacy_plan, pipe_ids)
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
    if plan.get("siteFirst") is True:
        return validate_site_session(session, plan, samples)
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


def validate_dashboard_report(path: Path, hashes: dict) -> dict:
    """Bind browser QA to exactly the current seven frontend files."""
    path = path if path.is_absolute() else ROOT / path
    path = path.resolve()
    raw = path.read_bytes()
    report = json.loads(raw.decode("utf-8-sig"))
    if not UI_SOURCES.issubset(hashes):
        raise ValueError("Missing dashboard QA source files")
    expected = {name: hashes[name] for name in sorted(UI_SOURCES)}
    if (not isinstance(report, dict) or report.get("status") != "PASS"
            or report.get("sourceHashes") != expected):
        raise ValueError("Dashboard QA sourceHashes must match exactly seven current UI files")
    checks = report.get("checks")
    if not isinstance(checks, dict) or any(
        type(checks.get(name)) is not type(value) or checks[name] != value
        for name, value in UI_CHECKS.items()
    ):
        raise ValueError("Dashboard QA checks did not pass")
    stored_path = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
    return {"path": stored_path, "hash": hashlib.sha256(raw).hexdigest(),
            "sourceHashes": expected}


def validate_bound_dashboard(binding: dict, hashes: dict) -> None:
    if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
        raise TypeError("Invalid bound dashboard verification")
    actual = validate_dashboard_report(Path(binding["path"]), hashes)
    if actual["hash"] != binding.get("hash") or actual["sourceHashes"] != binding.get("sourceHashes"):
        raise ValueError("Bound dashboard QA report changed without a new UI seal")


def refresh_ui_seal(saved: dict, hashes: dict, reports: dict,
                    session: Path, browser_report: Path) -> dict:
    """Only frontend and gate-code drift may reuse validated, unchanged full evidence."""
    if not isinstance(saved.get("sources"), dict) or not saved["sources"]:
        raise ValueError("An existing full evidence seal is required for UI refresh")
    if not reports or saved.get("reports") != reports:
        raise ValueError("Full integration reports changed; UI-only refresh rejected")
    if saved.get("session") != str(session):
        raise ValueError("Sealed verification session changed; UI-only refresh rejected")
    changed = {name for name in saved["sources"].keys() | hashes.keys()
               if saved["sources"].get(name) != hashes.get(name)}
    forbidden = changed - UI_REFRESH_SOURCES
    if forbidden:
        raise ValueError("Non-UI source changes require full verification: " + ", ".join(sorted(forbidden)))
    binding = validate_dashboard_report(browser_report, hashes)
    return {**saved, "sources": dict(hashes), "dashboardVerification": binding}


def validate_source_freshness(paths: list[Path], integration: Path,
                              play: Path, scenarios: Path) -> None:
    """Match each source to its verifier; only the two currently executed gate files are exempt."""
    core_time = min(integration.stat().st_mtime_ns, play.stat().st_mtime_ns)
    scenario_time = scenarios.stat().st_mtime_ns
    gate_files = {"scripts/check_inspection_harness.py", "tests/test_inspection_harness.py"}
    case_driver = "unity/MAEKInspection/Assets/MAEK/Editor/VerifyInspectionScenarios.cs"
    for path in paths:
        name = path.relative_to(ROOT).as_posix()
        if name in gate_files:
            continue
        verified_at = scenario_time if name == case_driver else core_time
        if path.stat().st_mtime_ns > verified_at:
            verifier = "scenario verification" if name == case_driver else "Editor/Play integration"
            raise ValueError(f"Source changed after {verifier}: {name}; rerun its verifier")


def check(evidence: bool = False, seal: bool = False, seal_ui: Path | None = None) -> dict:
    if seal and seal_ui is not None:
        raise ValueError("--seal and --seal-ui cannot be combined")
    required = [ROOT / "unity/AGENTS.md", ROOT / "docs/inspection-demo.md",
                ROOT / "docs/failures/inspection-demo.md", ROOT / "scripts/run_inspection_harness.ps1",
                ROOT / "tests/test_inspection_bridge.py"]
    for path in required + sources():
        if not path.is_file():
            raise ValueError(f"Missing harness input: {path}")
    legacy_plan = load(ASSETS / "Source/inspection_tour.json")
    plan_path = ASSETS / "Source/site_inspection_tour.json"
    validate_realism_baseline(ASSETS / "Source", ROOT / "visualization/realism/baseline")
    pipes = load(ASSETS / "Source/pipe_services.json")["pipes"]
    validate_worker_safety(load(ASSETS / "Source/worker_safety_context.json"), {"pipes": pipes})
    from check_supplementary_circuits import validate as validate_supplementary
    validate_supplementary(load(ASSETS / "Source/supplementary_circuits.json"))
    from check_inspection_scenarios import validate as validate_scenarios
    validate_scenarios(load(ASSETS / "Source/inspection_scenarios.json"), {"pipes": pipes}, load(ASSETS / "Source/supplementary_circuits.json"))
    if len(pipes) != 247:
        raise ValueError("Expected the complete 247-pipe scene catalogue")
    pipe_ids = [p["id"] for p in pipes]
    routes = load(ASSETS / "Source/service_drone_routes.json")["routes"]
    legacy_samples = validate_plan(legacy_plan, pipe_ids, routes)
    if len(legacy_samples) != 771:
        raise ValueError("Expected all 771 frozen legacy required samples")
    if not plan_path.is_file():
        if evidence or seal or seal_ui is not None:
            raise ValueError("Missing generated site_inspection_tour.json; run the site-first Unity Build")
        return {"status": "PASS", "plan_mode": "legacy_baseline_only", "site_build_pending": True,
                "pipes": len(pipes), "required_captures": len(legacy_samples), "evidence_checked": False}
    plan = load(plan_path)
    if plan.get("siteFirst") is not True:
        raise ValueError("Default site_inspection_tour.json must be siteFirst")
    samples = validate_plan(plan, pipe_ids, routes, legacy_plan)
    observed_pipes = {p["pipeId"] for p in plan["points"] if p.get("pipeId")}
    extra_plan_path = ASSETS / "Source/site_supplementary_tour.json"
    extra_plan = load(extra_plan_path) if extra_plan_path.is_file() else None
    if extra_plan is not None:
        extra_legacy = load(ASSETS / "Source/supplementary_tour.json")
        validate_site_plan(extra_plan, extra_legacy, extra_legacy["pipeIds"])
    hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in sources()}
    if evidence or seal or seal_ui is not None:
        access_path = OUT / "site_access_audit.json"
        validate_access_report(load(access_path), plan)
        validate_site_report(load(OUT / "build_report.json"), plan, executed=False)
        scenario_path = ROOT / "visualization/inspection_scenarios/verification.json"
        scenario_report = load(scenario_path)
        if (scenario_report["status"] != "PASS" or scenario_report["scenarios"] != 11
                or scenario_report.get("controlChecks", 0) < 5
                or not all(r["guardPass"] for r in scenario_report["evaluations"])):
            raise ValueError("Virtual drone/scenario evidence verification failed")
        extra_path = ROOT / "visualization/supplementary_circuits/connections_colliders.json"
        extra = load(extra_path)
        if extra["status"] != "PASS" or extra["lines"] != 17 or extra["views"] != (extra_plan["expectedCaptures"] if extra_plan is not None else 17) or not all(c["pass"] for c in extra["checks"]):
            raise ValueError("Supplementary circuit connections/colliders/views failed")
        if extra_plan is not None and (extra.get("requiredViews") != 17
                                       or extra.get("deferredViews") != 17 - extra_plan["expectedCaptures"]):
            raise ValueError("Supplementary deferred visibility accounting mismatch")
        interior_dir = ROOT / "visualization/interior_detail"
        interior_build = load(interior_dir / "build_report.json")
        interior_audit = load(interior_dir / "after-interior-colliders.json")
        if (interior_build["rooms"] != 5
                or interior_build["stations"] < 8 or interior_build["closedSpools"] < 6
                or any(r["status"] != "PASS" or not all(c["pass"] for c in r["checks"])
                       for r in (interior_audit,))
                or interior_audit["segments"] != len(plan["points"]) - 1
                or interior_audit["views"] != len(samples)
                or interior_audit["pipeCount"] != 247):
            raise ValueError("Interior collider/access/closed-spool verification failed")
        validate_interior_report(interior_build, interior_audit)
        validate_sweep_report(interior_audit, plan)
        geometry_path = ROOT / "visualization/realism/geometry_audit.json"
        geometry = load(geometry_path)
        validate_layout_report(geometry, legacy_plan, digest(ASSETS / "Source/inspection_tour.json"))
        report = load(OUT / "integration_report.json")
        validate_site_report(report, plan)
        if (report["status"] != "PASS" or not all(c["pass"] for c in report["checks"])
                or report.get("coveredPipes") != len(observed_pipes) or report["captures"] != len(samples)):
            raise ValueError("Integration checks did not pass")
        live = load(OUT / "play_mode_report.json")
        validate_site_report(live, plan)
        if (live["status"] != "PASS" or live["captures"] != len(samples)
                or live.get("coveredPipes") != len(observed_pipes) or not live["completed"]
                or live.get("recordedFrames", 0) < 24
                or live.get("runtimeScenarios", 0) != 11
                or live.get("evaluationAcks", 0) != 11
                or live.get("unsentEvaluations", -1) != 0):
            raise ValueError("Real Play-mode HTTP/coroutine integration did not pass")
        session = Path((OUT / "latest_verification.txt").read_text(encoding="utf-8-sig"))
        validate_session(session, plan, samples)
        validate_session(Path(live["session"]), plan, samples)
        report_hashes = {name: digest(OUT / name) for name in (
            "build_report.json", "integration_report.json", "play_mode_report.json")}
        report_hashes["site_access_audit.json"] = digest(access_path)
        report_hashes["realism/geometry_audit.json"] = digest(geometry_path)
        report_hashes["supplementary_circuits/connections_colliders.json"] = digest(extra_path)
        report_hashes["inspection_scenarios/verification.json"] = digest(scenario_path)
        for name in ("build_report.json", "after-interior-colliders.json"):
            report_hashes["interior_detail/" + name] = digest(interior_dir / name)
        if seal:
            validate_source_freshness(sources(), OUT / "integration_report.json",
                                      OUT / "play_mode_report.json", scenario_path)
            (OUT / "evidence_seal.json").write_text(json.dumps({
                "sources": hashes, "reports": report_hashes,
                "session": str(session),
            }, indent=2), encoding="utf-8")
            outcomes = load(session / "inspection_progress.json")["outcomes"]
            findings = load(session / "findings.json")["findings"]
            with (OUT / "pipe_inspection_summary.csv").open("w", encoding="utf-8-sig",
                                                          newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["pipe_id", "planned_images", "scheduled_images", "deferred_images",
                                 "analysed_images", "observation_status", "result", "mapped_findings", "scope"])
                follow_rows = {r["pipeId"]: r for r in load(session / "follow_up.json")["rows"]}
                for visit in plan["visits"]:
                    rows = [o for o in outcomes if o["pipeId"] == visit["pipeId"]]
                    count = sum(f["pipeId"] == visit["pipeId"] for f in findings)
                    follow_row = follow_rows[visit["pipeId"]]
                    writer.writerow([visit["pipeId"], visit["requiredCaptures"], visit["captures"],
                                     visit["requiredCaptures"] - visit["captures"], len(rows),
                                     follow_row["observationStatus"], follow_row["status"], count,
                                     "sampled_synthetic_RGB_not_full_surface"])
        elif seal_ui is not None:
            seal_path = OUT / "evidence_seal.json"
            updated = refresh_ui_seal(load(seal_path), hashes, report_hashes, session, seal_ui)
            if {p.relative_to(ROOT).as_posix(): digest(p) for p in sources()} != hashes:
                raise ValueError("Sources changed during UI verification; retry after edits finish")
            validate_bound_dashboard(updated["dashboardVerification"], hashes)
            seal_path.write_text(json.dumps(updated, indent=2), encoding="utf-8")
        else:
            saved = load(OUT / "evidence_seal.json")
            if saved["sources"] != hashes:
                raise ValueError("STALE: demo source/scene changed; rerun run_inspection_harness.ps1")
            if saved.get("reports") != report_hashes:
                raise ValueError("Integration report changed without a new seal")
            if "dashboardVerification" in saved:
                validate_bound_dashboard(saved["dashboardVerification"], hashes)
    return {"status": "PASS", "source_files": len(hashes), "pipes": len(pipes),
            "capture_stops": len(samples), "required_captures": plan["requiredCaptures"],
            "deferred_captures": plan["requiredCaptures"] - len(samples),
            "transfers": len(plan["transfers"]),
            "evidence_checked": evidence or seal or seal_ui is not None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", action="store_true")
    sealing = parser.add_mutually_exclusive_group()
    sealing.add_argument("--seal", action="store_true")
    sealing.add_argument("--seal-ui", type=Path, metavar="PATH")
    args = parser.parse_args()
    print(json.dumps(check(args.evidence, args.seal, args.seal_ui), indent=2))
