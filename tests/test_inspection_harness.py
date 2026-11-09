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


@pytest.fixture
def ui_evidence(tmp_path, monkeypatch):
    from scripts import check_inspection_harness as harness
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    names = harness.UI_REFRESH_SOURCES | {
        "maek/inspection_bridge.py",
        "unity/MAEKInspection/Assets/MAEK/Scripts/MAEKDashboardLink.cs",
    }
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original", encoding="utf-8")
    hashes = {name: harness.digest(tmp_path / name) for name in names}
    reports = {"integration_report.json": "a" * 64, "play_mode_report.json": "b" * 64}
    session = tmp_path / "full-verification-session"
    saved = {"sources": dict(hashes), "reports": dict(reports), "session": str(session)}
    report = {"status": "PASS", "sourceHashes": {name: hashes[name] for name in harness.UI_SOURCES},
              "checks": dict(harness.UI_CHECKS)}
    browser = tmp_path / "browser-qa.json"
    browser.write_text(json.dumps(report), encoding="utf-8")
    return harness, saved, hashes, reports, session, browser, report


def test_ui_seal_refresh_accepts_only_frontend_and_gate_edits(ui_evidence):
    harness, saved, hashes, reports, session, browser, report = ui_evidence
    before = copy.deepcopy(saved)
    for name in ("dashboard/operations.js", "scripts/check_inspection_harness.py",
                 "tests/test_inspection_harness.py"):
        (harness.ROOT / name).write_text("UI-only update", encoding="utf-8")
        hashes[name] = harness.digest(harness.ROOT / name)
    report["sourceHashes"] = {name: hashes[name] for name in harness.UI_SOURCES}
    browser.write_text(json.dumps(report), encoding="utf-8")
    refreshed = harness.refresh_ui_seal(saved, hashes, reports, session, browser)
    assert saved == before
    assert refreshed["sources"] == hashes
    assert refreshed["reports"] == before["reports"]
    assert refreshed["session"] == before["session"]
    binding = refreshed["dashboardVerification"]
    assert binding == {"path": "browser-qa.json", "hash": harness.digest(browser),
                       "sourceHashes": report["sourceHashes"]}
    harness.validate_bound_dashboard(binding, hashes)


@pytest.mark.parametrize("name", [
    "maek/inspection_bridge.py", "maek/inspection_dashboard.py",
    "unity/MAEKInspection/Assets/MAEK/Scripts/MAEKDashboardLink.cs",
    "unity/MAEKInspection/Assets/MAEK/Scripts/NewEngine.cs",
])
def test_ui_seal_rejects_api_engine_changes_and_additions(ui_evidence, name):
    harness, saved, hashes, reports, session, browser, _ = ui_evidence
    before = copy.deepcopy(saved)
    hashes[name] = "changed"
    with pytest.raises(ValueError, match="Non-UI source changes"):
        harness.refresh_ui_seal(saved, hashes, reports, session, browser)
    assert saved == before


def test_ui_seal_rejects_removed_engine_source(ui_evidence):
    harness, saved, hashes, reports, session, browser, _ = ui_evidence
    del hashes["maek/inspection_bridge.py"]
    with pytest.raises(ValueError, match="Non-UI source changes"):
        harness.refresh_ui_seal(saved, hashes, reports, session, browser)


@pytest.mark.parametrize("mutation", ["changed", "removed", "added"])
def test_ui_seal_rejects_changed_full_report_hashes(ui_evidence, mutation):
    harness, saved, hashes, reports, session, browser, _ = ui_evidence
    before = copy.deepcopy(saved)
    if mutation == "changed":
        reports["integration_report.json"] = "c" * 64
    elif mutation == "removed":
        reports.pop("play_mode_report.json")
    else:
        reports["new_report.json"] = "c" * 64
    with pytest.raises(ValueError, match="Full integration reports changed"):
        harness.refresh_ui_seal(saved, hashes, reports, session, browser)
    assert saved == before


def test_ui_seal_rejects_changed_session_anchor(ui_evidence):
    harness, saved, hashes, reports, session, browser, _ = ui_evidence
    with pytest.raises(ValueError, match="Sealed verification session changed"):
        harness.refresh_ui_seal(saved, hashes, reports, session.parent / "different", browser)


@pytest.mark.parametrize("mutation", ["stale", "missing", "extra"])
def test_ui_qa_requires_exactly_seven_current_source_hashes(ui_evidence, mutation):
    harness, saved, hashes, reports, session, browser, report = ui_evidence
    name = "dashboard/operations.js"
    if mutation == "stale":
        report["sourceHashes"][name] = "f" * 64
    elif mutation == "missing":
        del report["sourceHashes"][name]
    else:
        report["sourceHashes"]["maek/inspection_bridge.py"] = hashes["maek/inspection_bridge.py"]
    browser.write_text(json.dumps(report), encoding="utf-8")
    before = copy.deepcopy(saved)
    with pytest.raises(ValueError, match="exactly seven current UI files"):
        harness.refresh_ui_seal(saved, hashes, reports, session, browser)
    assert saved == before


@pytest.mark.parametrize("name,value", [
    ("scenarioControlsAbsent", False), ("scenarioEvaluationAbsent", False),
    ("storedModePreserved", False), ("desktopOverflow", True), ("mobileOverflow", True),
    ("javascriptExceptions", 1), ("javascriptExceptions", False),
    ("scenarioControlsAbsent", 1),
])
def test_ui_qa_rejects_failed_or_wrong_type_checks(ui_evidence, name, value):
    harness, saved, hashes, reports, session, browser, report = ui_evidence
    report["checks"][name] = value
    browser.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="Dashboard QA checks did not pass"):
        harness.refresh_ui_seal(saved, hashes, reports, session, browser)
    assert "dashboardVerification" not in saved


def test_ui_qa_rejects_nonpass_status(ui_evidence):
    harness, saved, hashes, reports, session, browser, report = ui_evidence
    report["status"] = "FAIL"
    browser.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="Dashboard QA sourceHashes"):
        harness.refresh_ui_seal(saved, hashes, reports, session, browser)


def test_bound_ui_qa_rejects_report_rewrite_even_if_checks_still_pass(ui_evidence):
    harness, _, hashes, _, _, browser, report = ui_evidence
    binding = harness.validate_dashboard_report(browser, hashes)
    report["extra"] = "edited after sealing"
    browser.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="report changed without a new UI seal"):
        harness.validate_bound_dashboard(binding, hashes)


def test_ui_seal_requires_existing_full_seal(ui_evidence):
    harness, _, hashes, reports, session, browser, _ = ui_evidence
    with pytest.raises(ValueError, match="existing full evidence seal"):
        harness.refresh_ui_seal({}, hashes, reports, session, browser)


def test_source_inventory_allows_bootstrap_before_generated_site_json(tmp_path, monkeypatch):
    from scripts import check_inspection_harness as harness
    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(harness, "ASSETS", tmp_path / "Assets")
    generated = harness.ASSETS / "Source/site_inspection_tour.json"
    assert generated not in harness.sources()
    generated.parent.mkdir(parents=True)
    generated.write_text("{}", encoding="utf-8")
    assert generated in harness.sources()


def test_source_only_bootstrap_requires_site_plan_before_any_evidence(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from scripts import check_inspection_harness as harness

    monkeypatch.setattr(harness, "ROOT", tmp_path)
    monkeypatch.setattr(harness, "ASSETS", tmp_path / "Assets")
    monkeypatch.setattr(harness, "sources", list)
    for name in ("unity/AGENTS.md", "docs/inspection-demo.md", "docs/failures/inspection-demo.md",
                 "scripts/run_inspection_harness.ps1", "tests/test_inspection_bridge.py"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    catalogue = [{"id": str(i)} for i in range(247)]
    data = {"pipe_services.json": {"pipes": catalogue}, "service_drone_routes.json": {"routes": []}}
    monkeypatch.setattr(harness, "load", lambda path: data.get(path.name, {}))
    for name in ("validate_realism_baseline", "validate_worker_safety"):
        monkeypatch.setattr(harness, name, lambda *args: None)
    monkeypatch.setattr(harness, "validate_plan", lambda *args: list(range(771)))
    for name in ("check_supplementary_circuits", "check_inspection_scenarios"):
        monkeypatch.setitem(sys.modules, name, SimpleNamespace(validate=lambda *args: None))
    result = harness.check()
    assert result["site_build_pending"] is True
    assert result["plan_mode"] == "legacy_baseline_only"
    assert result["required_captures"] == 771
    assert result["evidence_checked"] is False
    for options in ({"evidence": True}, {"seal": True}, {"seal_ui": tmp_path / "qa.json"}):
        with pytest.raises(ValueError, match="Missing generated site_inspection_tour.json"):
            harness.check(**options)


@pytest.fixture
def freshness_context(tmp_path, monkeypatch):
    import os

    from scripts import check_inspection_harness as harness

    monkeypatch.setattr(harness, "ROOT", tmp_path)
    names = ["scripts/check_inspection_harness.py", "tests/test_inspection_harness.py",
             "unity/MAEKInspection/Assets/MAEK/Editor/VerifyInspectionScenarios.cs",
             "unity/MAEKInspection/Assets/MAEK/Scripts/MAEKInspectionTour.cs",
             "unity/MAEKInspection/Assets/MAEK/Editor/BuildInspectionTour.cs",
             "unity/MAEKInspection/Assets/MAEK/Editor/VerifyInspectionPlayMode.cs",
             "unity/MAEKInspection/Assets/MAEK/Scenes/MAEKInspectionDemo.unity",
             "maek/inspection_bridge.py", "scripts/check_inspection_access.py"]
    paths = []
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source", encoding="utf-8")
        os.utime(path, ns=(100_000_000_000, 100_000_000_000))
        paths.append(path)
    reports = []
    for name, time in (("editor.json", 200), ("play.json", 150), ("scenario.json", 300)):
        path = tmp_path / name
        path.write_text("report", encoding="utf-8")
        os.utime(path, ns=(time * 1_000_000_000, time * 1_000_000_000))
        reports.append(path)
    return harness, paths, reports


def test_fresh_case_driver_can_use_its_new_scenario_report(freshness_context):
    import os

    harness, paths, reports = freshness_context
    for path in paths[:2]:
        os.utime(path, (400, 400))
    os.utime(paths[2], (250, 250))
    harness.validate_source_freshness(paths, *reports)


@pytest.mark.parametrize("index", [3, 4, 5, 6, 7, 8])
def test_fresh_case_report_cannot_revalidate_changed_core_source(freshness_context, index):
    import os

    harness, paths, reports = freshness_context
    # Later than Play, earlier than Editor: min(Editor, Play) must reject this.
    os.utime(paths[index], (175, 175))
    with pytest.raises(ValueError, match="Source changed after Editor/Play integration"):
        harness.validate_source_freshness(paths, *reports)


def test_case_driver_rejects_old_matching_scenario_report(freshness_context):
    import os

    harness, paths, reports = freshness_context
    os.utime(paths[2], (350, 350))
    with pytest.raises(ValueError, match="Source changed after scenario verification"):
        harness.validate_source_freshness(paths, *reports)


def test_same_timestamp_is_fresh_but_gate_exemption_is_exact_path(freshness_context):
    import os

    harness, paths, reports = freshness_context
    os.utime(paths[3], (150, 150))
    harness.validate_source_freshness(paths, *reports)
    other = harness.ROOT / "other/check_inspection_harness.py"
    other.parent.mkdir()
    other.write_text("not the executing checker", encoding="utf-8")
    os.utime(other, (400, 400))
    with pytest.raises(ValueError, match="Source changed after Editor/Play integration"):
        harness.validate_source_freshness([*paths, other], *reports)
