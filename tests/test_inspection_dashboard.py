"""Exercise the dashboard contract over real loopback HTTP."""
import base64
import hashlib
import io
import json
import os
import subprocess
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pytest
from PIL import Image

from maek.inspection_bridge import MODEL, InspectionServer
from maek.inspection_dashboard import DashboardState


def png(colour=120):
    out = io.BytesIO()
    Image.fromarray(np.full((32, 48, 3), colour, dtype=np.uint8)).save(out, format="PNG")
    return out.getvalue()


def telemetry(session="session-a", sequence=1, frame="live1", raw=None):
    data = {
        "sessionId": session, "sequence": sequence, "source": "unity_virtual",
        "scenarioId": "rust", "scenarioRunId": "run1", "frameId": frame,
        "scenarios": [{"id": "rust", "title": "부식", "description": "RGB 후보",
                       "capability": "rgb_rust_baseline"}],
    }
    if raw is not None:
        data["imageBase64"] = base64.b64encode(raw).decode()
    return data


@pytest.fixture
def http(tmp_path):
    server = InspectionServer(("127.0.0.1", 0), dashboard_root=tmp_path)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    def request(path, data=None):
        body = None if data is None else json.dumps(data).encode()
        req = Request(f"http://127.0.0.1:{server.server_port}" + path, data=body,
                      headers={"Content-Type": "application/json"})
        try:
            response = urlopen(req, timeout=3)
        except HTTPError as exc:
            response = exc
        with response:
            request.last_headers = response.headers
            raw = response.read()
            value = json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw
            return response.status, value

    request.server = server
    yield request, server.dashboard
    server.shutdown()
    server.server_close()
    worker.join(timeout=3)


def test_health_and_initial_state(http):
    call, _ = http
    code, health = call("/health")
    assert code == 200
    assert health["model"] == MODEL == "maek.camera.segment.segment_rust / HSV baseline"
    assert health["capabilities"] == ["dashboard_v1", "scenarios_v1"]
    _, state = call("/api/state")
    assert set(state) == {"version", "serverTimeMs", "sessionId", "connected", "ageSeconds",
                          "telemetry", "preview", "analyses", "evaluations", "scenarios", "lastCommand"}
    assert state["connected"] is False and state["telemetry"] is None
    assert call("/api/control", {"command": "pause"})[0] == 409
    assert call("/api/frame/missing")[0] == 404
    assert call("/unknown")[0] == 404


def test_live_and_analysed_frames_have_exact_provenance(http):
    call, _ = http
    raw = png()
    assert call("/api/telemetry", telemetry(raw=raw))[0] == 200
    req = {"requestId": "capture1", "sessionId": "session-a", "pipeId": "247",
           "sampleId": "sample1", "scenarioId": "rust", "scenarioRunId": "run1",
           "imageBase64": base64.b64encode(raw).decode()}
    code, analysis = call("/analyse", req)
    assert code == 200 and analysis["quality"]["canInfer"] is True
    _, state = call("/api/state")
    preview = state["preview"]
    still = state["analyses"][0]
    assert preview["imageSha256"] == still["imageSha256"] == hashlib.sha256(raw).hexdigest()
    assert call(preview["url"])[1] == call(still["frameUrl"])[1] == raw
    assert still["frameUrl"] != preview["url"]
    assert all(still[k] == req[k] for k in ("sessionId", "pipeId", "sampleId", "scenarioId", "scenarioRunId"))
    assert "imageBase64" not in state["telemetry"]
    newer = png(180)
    assert call("/api/telemetry", telemetry(sequence=2, frame="live2", raw=newer))[0] == 200
    _, state = call("/api/state")
    assert call(state["preview"]["url"])[1] == newer
    assert call(state["analyses"][0]["frameUrl"])[1] == raw
    assert call("/api/telemetry", telemetry(sequence=3, frame="live3"))[0] == 200
    assert call("/api/state")[1]["preview"] is None


def test_frame_bounds_and_immutable_ids(http):
    call, state = http
    state.max_frames = 2
    raw = png()
    for i in range(3):
        assert call("/api/telemetry", telemetry(sequence=i, frame=f"f{i}", raw=raw))[0] == 200
    assert call("/api/frame/f0")[0] == 404
    assert call("/api/frame/f1")[1] == raw
    assert call("/api/telemetry", telemetry(sequence=3, frame="f2", raw=png(140)))[0] == 409
    assert call("/api/state")[1]["telemetry"]["sequence"] == 2
    assert state.frame_bytes <= state.max_frame_bytes
    state.max_frame_bytes = len(raw)
    assert call("/api/telemetry", telemetry(sequence=4, frame="f4", raw=raw))[0] == 200
    assert len(state.frames) == 1
    assert call("/api/frame/f2")[0] == 404


def test_sequences_retired_sessions_and_stale_analysis(http):
    call, _ = http
    assert call("/api/telemetry", telemetry())[0] == 200
    assert call("/api/telemetry", telemetry())[0] == 409
    assert call("/api/telemetry", telemetry(sequence=0))[0] == 409
    queued = call("/api/control", {"command": "pause"})[1]
    call("/api/control?sessionId=session-a")
    assert call("/api/telemetry", telemetry(session="session-b"))[0] == 200
    assert call("/api/telemetry", telemetry(sequence=9))[0] == 409
    assert call("/api/control?sessionId=session-a")[0] == 409
    assert call("/api/control?sessionId=session-b")[1] == {"commands": []}
    assert call("/api/ack", {"sessionId": "session-b", "commandId": queued["commandId"],
                             "status": "applied", "message": ""})[0] == 409
    req = {"requestId": "old", "sessionId": "session-a", "imageBase64": base64.b64encode(png()).decode()}
    assert call("/analyse", req)[0] == 200
    assert call("/api/state")[1]["analyses"] == []


def test_control_drain_ack_and_overflow(http):
    call, state = http
    call("/api/telemetry", telemetry())
    assert call("/api/control", {"command": "fly"})[0] == 400
    assert call("/api/control", {"command": "scenario", "scenarioId": "unknown"})[0] == 400
    assert call("/api/control", {"command": "scenario"})[0] == 400
    state.max_commands = 1
    _, queued = call("/api/control", {"command": "scenario", "scenarioId": "rust"})
    ack = {"sessionId": "session-a", "commandId": queued["commandId"], "status": "applied", "message": "완료"}
    assert call("/api/ack", ack)[0] == 409
    assert call("/api/control", {"command": "pause"})[0] == 409
    _, drained = call("/api/control?sessionId=session-a")
    assert drained == {"commands": [{"commandId": queued["commandId"], "command": "scenario", "scenarioId": "rust"}]}
    assert call("/api/control?sessionId=session-a")[1] == drained
    assert call("/api/control", {"command": "pause"})[0] == 409
    assert call("/api/ack", ack)[0] == 200
    assert call("/api/ack", ack)[0] == 200
    assert call("/api/control?sessionId=session-a")[1] == {"commands": []}
    assert call("/api/state")[1]["lastCommand"]["status"] == "applied"
    assert call("/api/control", {"command": "pause"})[0] == 200


def test_evaluation_never_changes_pixel_inference(http):
    call, _ = http
    call("/api/telemetry", telemetry())
    req = {"requestId": "pixels", "sessionId": "session-a", "imageBase64": base64.b64encode(png()).decode()}
    before = call("/analyse", req)[1]
    evaluation = {"sessionId": "session-a", "runId": "run1", "scenarioId": "rust", "title": "평가",
                  "pipeId": "247", "expected": {"rust": True}, "observed": "no_candidate",
                  "classification": "warning", "guardPass": True, "detectionPass": False,
                  "detectionApplicable": True, "findings": 0, "captures": 1,
                  "errors": [], "workPermissionStatus": "not_assessed"}
    assert call("/api/evaluation", evaluation)[0] == 200
    assert call("/analyse", req)[1] == before
    state = call("/api/state")[1]
    assert state["evaluations"] == [evaluation]
    assert state["evaluations"][0]["guardPass"] is True
    assert state["evaluations"][0]["detectionPass"] is False
    for field in ("detectionPass", "detectionApplicable"):
        assert call("/api/evaluation", {**evaluation, field: "true"})[0] == 400
    assert "expected" not in state["analyses"][0]
    assert "not proof" in before["negativeMeaning"]
    assert call("/api/evaluation", {**evaluation, "workPermissionStatus": "approved"})[0] == 400
    assert call("/api/evaluation", {**evaluation, "sessionId": "old"})[0] == 409


@pytest.mark.parametrize("change", [
    {"sequence": True}, {"source": "real_drone"}, {"sequence": -1},
    {"position": {"x": float("nan"), "y": 0, "z": 0}}, {"yaw": float("inf")},
    {"frameId": "../secret"}, {"blocked": "false"}, {"captures": -1},
    {"scenarios": [None]}, {"imageBase64": "!!!"}, {"truth": "rust"},
])
def test_invalid_telemetry_rejected_without_state_mutation(http, change):
    call, _ = http
    assert call("/api/telemetry", {**telemetry(), **change})[0] == 400
    assert call("/api/state")[1]["sessionId"] is None


def test_expiry_and_snapshot_isolation(http):
    call, state = http
    now = [100.0]
    state.clock = lambda: now[0]
    call("/api/telemetry", telemetry())
    snapshot = state.snapshot()
    snapshot["scenarios"][0]["title"] = "mutated"
    assert state.snapshot()["scenarios"][0]["title"] == "부식"
    now[0] += 11
    assert call("/api/state")[1]["connected"] is False
    assert call("/api/control", {"command": "pause"})[0] == 409
    assert call("/api/control?sessionId=session-a")[0] == 409


@pytest.mark.parametrize("route", ["/", "/dashboard", "/dashboard/", "/index.html"])
def test_missing_existing_root_never_serves_prototype(http, monkeypatch, tmp_path, route):
    import maek.inspection_bridge as bridge
    call, _ = http
    monkeypatch.setattr(bridge, "__file__", str(tmp_path / "inspection_bridge.py"))
    call.server.dashboard_root = None
    web = tmp_path / "web"
    web.mkdir()
    prototype = web / "dashboard.html"
    original = "<html>프로토타입 · 제공 금지</html>".encode()
    prototype.write_bytes(original)
    code, result = call(route)
    assert code == 503
    assert result["status"] == "error"
    assert "--dashboard-root" in result["message"]
    assert prototype.read_bytes() == original


def test_only_loopback_binding():
    with pytest.raises(ValueError, match="127.0.0.1"):
        InspectionServer(("0.0.0.0", 0))


def test_capacity_too_small_rejects_without_state_change(http):
    call, state = http
    state.max_frame_bytes = 1
    assert call("/api/telemetry", telemetry(raw=png()))[0] == 413
    assert call("/api/state")[1]["sessionId"] is None


def test_analysis_finishing_after_session_switch_is_ignored():
    state = DashboardState()
    state.telemetry_update(telemetry())
    state.telemetry_update(telemetry(session="session-b"))
    state.record_analysis({"requestId": "old"}, png(), {"sessionId": "session-a"})
    assert state.snapshot()["analyses"] == []


def test_evicted_frame_id_cannot_be_reused(http):
    call, state = http
    state.max_frames = 1
    call("/api/telemetry", telemetry(raw=png()))
    call("/api/telemetry", telemetry(sequence=2, frame="live2", raw=png()))
    assert call("/api/telemetry", telemetry(sequence=3, raw=png(50)))[0] == 409
    assert call("/api/frame/live1")[0] == 404


def test_expired_commands_do_not_run_on_reconnect(http):
    call, state = http
    now = [100.0]
    state.clock = lambda: now[0]
    call("/api/telemetry", telemetry())
    queued = call("/api/control", {"command": "pause"})[1]
    now[0] += 11
    assert call("/api/telemetry", telemetry(sequence=2))[0] == 200
    assert call("/api/control?sessionId=session-a")[1] == {"commands": []}
    assert call("/api/ack", {"sessionId": "session-a", "commandId": queued["commandId"],
                             "status": "applied"})[0] == 409
    assert call("/api/state")[1]["lastCommand"]["status"] == "error"


@pytest.mark.parametrize("data", [[], None, "text", {"command": "scenario", "scenarioId": []}])
def test_invalid_control_json_is_client_error(http, data):
    call, _ = http
    # None means GET in the helper, so send a non-object JSON value explicitly via a list.
    if data is None:
        data = [None]
    assert call("/api/control", data)[0] == 400


def mapped_telemetry():
    return {
        **telemetry(raw=png()), "cameraAvailable": True,
        "mappedFindings": [{"pipeId": "247", "requestId": "req1", "imageSha256": "a" * 64,
                            "kind": "surface_corrosion_candidate", "position": {"x": 1, "y": 2, "z": 3},
                            "recommendation": "추가 확인"}],
        "outcomes": [{"requestId": "req1", "pipeId": "247", "sampleId": "sample1", "status": "candidate",
                      "visibleTargetSamples": 10, "newFindings": 1}],
    }


def test_mapped_results_are_separate_from_inference_and_camera_loss_clears_preview(http):
    call, _ = http
    data = mapped_telemetry()
    assert call("/api/telemetry", data)[0] == 200
    state = call("/api/state")[1]
    assert state["telemetry"]["outcomes"] == data["outcomes"]
    assert state["telemetry"]["mappedFindings"] == data["mappedFindings"]
    assert state["analyses"] == []
    assert state["preview"] is not None
    assert call("/api/telemetry", {**data, "sequence": 2, "cameraAvailable": False})[0] == 200
    assert call("/api/state")[1]["preview"] is None
    assert call("/api/telemetry", telemetry(session="session-b", frame="new"))[0] == 200
    assert call("/api/state")[1]["preview"] is None


@pytest.mark.parametrize("field", ["mappedFindings", "outcomes"])
def test_mapping_arrays_bounded_to_forty(http, field):
    call, _ = http
    data = mapped_telemetry()
    item = data[field][0]
    assert call("/api/telemetry", {**data, field: [item] * 41})[0] == 400
    assert call("/api/telemetry", {**data, field: [item] * 40})[0] == 200


@pytest.mark.parametrize("field,change", [
    ("mappedFindings", {"position": {"x": float("inf"), "y": 0, "z": 0}}),
    ("mappedFindings", {"imageSha256": "invalid"}),
    ("mappedFindings", {"expected": "rust"}),
    ("outcomes", {"visibleTargetSamples": -1}),
    ("outcomes", {"newFindings": True}),
])
def test_mapping_rejects_nonfinite_or_invalid_fields(http, field, change):
    call, _ = http
    data = mapped_telemetry()
    data[field] = [{**data[field][0], **change}]
    assert call("/api/telemetry", data)[0] == 400


def test_eleven_opaque_scenarios_and_sensor_guidance_are_metadata_only(http):
    call, _ = http
    registered = [{"id": f"S{i:02}", "title": f"시나리오 {i}",
                   "description": "가상 점검", "capability": "rgb_rust_baseline"}
                  for i in range(1, 12)]
    data = {**telemetry(), "scenarios": registered, "scenarioId": "S10",
            "sensorRequirement": "UT", "optionalGuidance": "UT 센서 필요",
            "guidance": "실제 UT 측정값 없음"}
    assert call("/api/telemetry", data)[0] == 200
    snapshot = call("/api/state")[1]
    assert len(snapshot["scenarios"]) == 11
    assert snapshot["telemetry"]["sensorRequirement"] == "UT"
    req = {"requestId": "sensor-check", "sessionId": "session-a", "scenarioId": "S10",
           "imageBase64": base64.b64encode(png()).decode()}
    result = call("/analyse", req)[1]
    for field in ("optionalGuidance", "guidance", "sensorRequirement"):
        assert field not in result
        assert field not in call("/api/state")[1]["analyses"][0]
    queued = call("/api/control", {"command": "scenario", "scenarioId": "S11"})[1]
    drained = call("/api/control?sessionId=session-a")[1]
    assert drained["commands"][0]["scenarioId"] == "S11"
    assert call("/api/ack", {"sessionId": "session-a", "commandId": queued["commandId"],
                             "status": "applied", "message": "새 세션 시작"})[0] == 200
    assert call("/api/telemetry", {**data, "sessionId": "session-b", "sequence": 0,
                                   "scenarioId": "S11", "sensorRequirement": "IR",
                                   "guidance": "실제 IR 측정값 없음"})[0] == 200
    for sequence in (0, 1, 999):
        assert call("/api/telemetry", {**data, "sequence": sequence})[0] == 409
    assert call("/api/state")[1]["sessionId"] == "session-b"
    assert call("/api/state")[1]["telemetry"]["sensorRequirement"] == "IR"


@pytest.mark.parametrize("field", ["optionalGuidance", "guidance", "sensorRequirement"])
@pytest.mark.parametrize("value", [123, {"expected": "rust"}, "x" * 4097])
def test_guidance_requires_bounded_strings(http, field, value):
    call, _ = http
    assert call("/api/telemetry", {**telemetry(), field: value})[0] == 400
    assert call("/api/state")[1]["sessionId"] is None


def test_evaluation_history_survives_all_eleven_case_sessions(http):
    call, state = http
    evaluations = []
    previous_session = None
    for case in range(1, 12):
        sid = f"S{case:02}"
        session = f"case-session-{case}"
        data = {**telemetry(session=session, frame=f"case-{case}"), "scenarioId": sid,
                "scenarioRunId": f"run-{case}"}
        assert call("/api/telemetry", data)[0] == 200
        snapshot = call("/api/state")[1]
        assert snapshot["evaluations"] == list(reversed(evaluations))
        assert snapshot["analyses"] == [] and snapshot["preview"] is None
        assert snapshot["lastCommand"] is None
        assert call(f"/api/control?sessionId={session}")[1] == {"commands": []}
        if previous_session is not None:
            assert call("/api/evaluation", {**evaluations[-1], "sessionId": previous_session})[0] == 200
        evaluation = {"sessionId": session, "runId": f"run-{case}", "scenarioId": sid,
                      "title": f"평가 {case}", "pipeId": "247", "expected": "evaluation only",
                      "observed": "no_candidate", "classification": "warning", "guardPass": True,
                      "detectionPass": False, "detectionApplicable": True, "findings": 0,
                      "captures": 1, "errors": [], "workPermissionStatus": "not_assessed"}
        assert call("/api/evaluation", evaluation) == (200, {"status": "ok"})
        evaluations.append(evaluation)
        req = {"requestId": f"capture-{case}", "sessionId": session,
               "imageBase64": base64.b64encode(png()).decode()}
        assert call("/analyse", req)[0] == 200
        assert call("/api/control", {"command": "pause"})[0] == 200
        previous_session = session
    snapshot = call("/api/state")[1]
    assert snapshot["evaluations"] == list(reversed(evaluations))
    assert len(snapshot["analyses"]) == 1
    assert len(state.evaluations) == 11 and state.evaluations.maxlen == 128
    for number in range(129):
        state.evaluation({**evaluations[-1], "runId": f"bounded-{number}"})
    assert len(state.snapshot()["evaluations"]) == 128
    assert state.snapshot()["evaluations"][0]["runId"] == "bounded-128"
    assert state.snapshot()["evaluations"][-1]["runId"] == "bounded-1"


def test_full_inspection_finding_known_extra_fields(http):
    call, _ = http
    data = mapped_telemetry()
    data["mappedFindings"][0].update(normal={"x": 0, "y": 1, "z": 0},
                                     model=MODEL, pixelCount=100, mappedSamples=64)
    assert call("/api/telemetry", data)[0] == 200
    assert call("/api/state")[1]["telemetry"]["mappedFindings"] == data["mappedFindings"]
    assert call("/api/state")[1]["analyses"] == []


@pytest.mark.parametrize("change", [
    {"normal": {"x": float("nan"), "y": 0, "z": 0}}, {"normal": [0, 1, 0]},
    {"model": 123}, {"model": "x" * 4097}, {"pixelCount": -1},
    {"pixelCount": 1280 * 720 + 1}, {"mappedSamples": True}, {"mappedSamples": []},
    {"expected": "rust"},
])
def test_full_finding_extras_are_known_bounded_and_finite(http, change):
    call, _ = http
    data = mapped_telemetry()
    data["mappedFindings"][0].update(change)
    assert call("/api/telemetry", data)[0] == 400
    assert call("/api/state")[1]["sessionId"] is None


@pytest.mark.parametrize("view", ["fpv", "chase"])
@pytest.mark.parametrize("encoded", [None, ""])
def test_unity_view_strings_and_empty_optional_image(http, view, encoded):
    call, _ = http
    assert call("/api/telemetry", {**telemetry(), "droneView": view,
                                  "imageBase64": encoded})[0] == 200
    state = call("/api/state")[1]
    assert state["telemetry"]["droneView"] == view
    assert "imageBase64" not in state["telemetry"]
    assert state["preview"] is None


@pytest.mark.parametrize("view", [True, False, None, "", "scene", 1, []])
def test_drone_view_rejects_non_enum_values(http, view):
    call, _ = http
    assert call("/api/telemetry", {**telemetry(), "droneView": view})[0] == 400


@pytest.mark.parametrize("encoded", [" ", "!!!", "not-base64", 0, False, [], {}])
def test_nonempty_malformed_image_still_rejected(http, encoded):
    call, _ = http
    assert call("/api/telemetry", {**telemetry(), "imageBase64": encoded})[0] == 400


@pytest.mark.parametrize("active,paused", [(True, False), (True, True), (False, False), (False, True)])
def test_optional_tour_flags_preserve_actual_unity_state(http, active, paused):
    call, _ = http
    assert call("/api/telemetry", {**telemetry(), "active": active, "paused": paused})[0] == 200
    state = call("/api/state")[1]["telemetry"]
    assert state["active"] is active
    assert state["paused"] is paused


@pytest.mark.parametrize("field", ["active", "paused"])
@pytest.mark.parametrize("value", [0, 1, "true", "false", None, []])
def test_optional_tour_flags_require_boolean(http, field, value):
    call, _ = http
    assert call("/api/telemetry", {**telemetry(), field: value})[0] == 400
    assert call("/api/state")[1]["sessionId"] is None


@pytest.mark.parametrize("route", ["/", "/dashboard", "/dashboard/", "/index.html"])
def test_existing_dashboard_injected_without_changing_source(http, monkeypatch, tmp_path, route):
    import maek.inspection_bridge as bridge
    call, _ = http
    root = tmp_path / "existing"
    root.mkdir()
    index = root / "index.html"
    original = b"<html><HEAD><title>Existing UI</title></HEAD><BODY>existing</BODY></html>"
    index.write_bytes(original)
    web = tmp_path / "web"
    web.mkdir()
    (web / "existing-dashboard-adapter.css").write_text("body {color: red}", encoding="utf-8")
    (web / "existing-dashboard-adapter.js").write_text("window.test = 1;", encoding="utf-8")
    monkeypatch.setattr(bridge, "__file__", str(tmp_path / "inspection_bridge.py"))
    call.server.dashboard_root = root
    code, html = call(route)
    assert code == 200
    assert call.last_headers.get_content_type() == "text/html"
    assert b"<script src='/api/existing-dashboard-adapter.js' defer></script></BODY>" in html
    assert b"<link rel='stylesheet' href='/api/existing-dashboard-adapter.css'></HEAD>" in html
    assert index.read_bytes() == original
    assert call("/api/existing-dashboard-adapter.js")[1] == b"window.test = 1;"
    assert call.last_headers.get_content_type() == "text/javascript"
    assert call("/api/existing-dashboard-adapter.css")[1] == b"body {color: red}"
    assert call.last_headers.get_content_type() == "text/css"
    index.write_text("<body>updated</body>", encoding="utf-8")
    assert b"updated<script" in call(route)[1]


@pytest.mark.parametrize("asset,body,mime", [
    ("style.css", b"body{}", "text/css"), ("app.js", b"let a=1;", "text/javascript"),
    ("assets/image.png", b"png-bytes", "image/png"), ("assets/font.woff2", b"font", "font/woff2"),
    ("assets/config.json", b'{"key":1}', "application/json"),
])
def test_existing_static_assets_have_mime_and_are_read_only(http, tmp_path, asset, body, mime):
    call, _ = http
    call.server.dashboard_root = tmp_path
    target = tmp_path / asset
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    for prefix in ("/", "/dashboard/"):
        assert call(prefix + asset + "?v=1") == (200, json.loads(body) if mime == "application/json" else body)
        assert call.last_headers.get_content_type() == mime
        assert call.last_headers["X-Content-Type-Options"] == "nosniff"
    assert call("/" + asset, {"overwrite": True})[0] == 404
    assert target.read_bytes() == body


@pytest.mark.parametrize("route", [
    "/../outside.js", "/%2e%2e/outside.js", "/%252e%252e/outside.js",
    "/assets/%2e%2e/outside.js", "/assets%5c..%5coutside.js", "/C:%5coutside.js",
    "/.hidden.js", "/.secret/app.js", "/app.js%3asecret", "/app.js%00",
    "/assets/../app.js", "/app.js%20", "/file.py", "/assets/",
])
def test_existing_static_rejects_traversal_hidden_and_disallowed_assets(http, tmp_path, route):
    call, _ = http
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside.js").write_text("outside", encoding="utf-8")
    for name in (".hidden.js", "app.js", "file.py"):
        (root / name).write_text("private", encoding="utf-8")
    hidden = root / ".secret"
    hidden.mkdir()
    (hidden / "app.js").write_text("private", encoding="utf-8")
    call.server.dashboard_root = root
    assert call(route)[0] == 404


def test_existing_static_rejects_symlink_escape(http, tmp_path):
    call, _ = http
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.js"
    outside.write_text("outside", encoding="utf-8")
    try:
        (root / "escape.js").symlink_to(outside)
    except OSError as exc:
        if os.name != "nt":
            pytest.skip(f"Symbolic links unavailable: {exc}")
        outside_dir = tmp_path / "outside-dir"
        outside_dir.mkdir()
        (outside_dir / "outside.js").write_text("outside", encoding="utf-8")
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(root / "escape"), str(outside_dir)],
            capture_output=True, check=False,
        )
        if result.returncode:
            pytest.skip("Symbolic links and Windows junctions unavailable")
        call.server.dashboard_root = root
        assert call("/escape/outside.js")[0] == 404
        return
    call.server.dashboard_root = root
    assert call("/escape.js")[0] == 404


def test_default_static_root_source_then_packaged(http, monkeypatch, tmp_path):
    import maek.inspection_bridge as bridge
    module = tmp_path / "repo" / "maek" / "inspection_bridge.py"
    module.parent.mkdir(parents=True)
    monkeypatch.setattr(bridge, "__file__", str(module))
    assert bridge.default_dashboard_root() is None
    packaged = module.parent / "dashboard"
    packaged.mkdir()
    assert bridge.default_dashboard_root() == packaged
    source = module.parent.parent / "dashboard"
    source.mkdir()
    assert bridge.default_dashboard_root() == source
    server = bridge.BridgeServer(("127.0.0.1", 0), dashboard_root=packaged)
    try:
        assert server.dashboard_root == packaged.resolve()
    finally:
        server.server_close()


def test_missing_configured_static_root_does_not_replace_existing_ui(http, tmp_path):
    call, _ = http
    call.server.dashboard_root = tmp_path / "absent"
    code, result = call("/")
    assert code == 503
    assert "--dashboard-root" in result["message"]


def test_dashboard_root_cli_option(monkeypatch, tmp_path):
    import maek.inspection_bridge as bridge
    received = {}

    class FakeServer:
        def __init__(self, address, *, dashboard_root):
            received.update(address=address, dashboard_root=dashboard_root)

        def serve_forever(self):
            received["started"] = True

    monkeypatch.setattr(bridge, "BridgeServer", FakeServer)
    monkeypatch.setattr("sys.argv", ["inspection_bridge", "--port", "18224", "--dashboard-root", str(tmp_path)])
    bridge.main()
    assert received == {"address": ("127.0.0.1", 18224), "dashboard_root": tmp_path, "started": True}


def test_existing_dashboard_injects_script_when_optional_css_absent(http, monkeypatch, tmp_path):
    import maek.inspection_bridge as bridge
    call, _ = http
    root = tmp_path / "existing"
    root.mkdir()
    (root / "index.html").write_text("<head></head><body>original</body>", encoding="utf-8")
    call.server.dashboard_root = root
    monkeypatch.setattr(bridge, "__file__", str(tmp_path / "inspection_bridge.py"))
    html = call("/")[1]
    assert b"existing-dashboard-adapter.js" in html
    assert b"existing-dashboard-adapter.css" not in html


@pytest.mark.skipif(os.name != "nt", reason="Windows hidden file attributes")
def test_existing_static_rejects_windows_hidden_file(http, tmp_path):
    import ctypes
    call, _ = http
    target = tmp_path / "hidden.js"
    target.write_text("private", encoding="utf-8")
    assert ctypes.windll.kernel32.SetFileAttributesW(str(target), 2)
    call.server.dashboard_root = tmp_path
    try:
        assert call("/hidden.js")[0] == 404
    finally:
        ctypes.windll.kernel32.SetFileAttributesW(str(target), 128)


def evaluation_row(session="session-a", run="run1"):
    return {"sessionId": session, "runId": run, "scenarioId": "rust", "title": "지연 평가",
            "pipeId": "247", "expected": {"rust": True}, "observed": "no_candidate",
            "classification": "false_negative", "guardPass": True, "detectionPass": False,
            "detectionApplicable": True, "findings": 0, "captures": 1,
            "errors": [], "workPermissionStatus": "not_assessed"}


def test_lifecycle_delayed_retired_evaluation_does_not_change_current_session(http):
    call, _ = http
    call("/api/telemetry", telemetry())
    call("/api/telemetry", telemetry(session="session-b", frame="b", raw=png()))
    call("/api/control", {"command": "pause"})
    before = call("/api/state")[1]
    row = evaluation_row()
    assert call("/api/evaluation", row) == (200, {"status": "ok"})
    assert call("/api/evaluation", dict(reversed(list(row.items())))) == (200, {"status": "ok"})
    after = call("/api/state")[1]
    assert after["evaluations"] == [row]
    for field in ("sessionId", "telemetry", "preview", "analyses", "lastCommand", "scenarios"):
        assert after[field] == before[field]
    assert call("/api/telemetry", telemetry(sequence=99))[0] == 409
    assert call("/api/control?sessionId=session-a")[0] == 409
    assert call("/api/evaluation", evaluation_row("unknown"))[0] == 409


@pytest.mark.parametrize("change", [{"findings": 1}, {"expected": {"rust": False}}, {"guardPass": False}])
def test_lifecycle_evaluation_conflicting_retry_is_409(http, change):
    call, _ = http
    call("/api/telemetry", telemetry())
    row = evaluation_row()
    assert call("/api/evaluation", row)[0] == 200
    assert call("/api/evaluation", {**row, **change})[0] == 409
    assert call("/api/state")[1]["evaluations"] == [row]


def test_lifecycle_evaluation_retry_survives_history_eviction_and_offline(http):
    call, state = http
    now = [100.0]
    state.clock = lambda: now[0]
    call("/api/telemetry", telemetry())
    row = evaluation_row()
    call("/api/evaluation", row)
    for i in range(128):
        state.evaluation(evaluation_row(run=f"new-{i}"))
    before = state.snapshot()["evaluations"]
    now[0] += 11
    assert call("/api/evaluation", row)[0] == 200
    assert state.snapshot()["evaluations"] == before
    assert call("/api/evaluation", {**row, "findings": 1})[0] == 409
    assert call("/api/evaluation", evaluation_row(run="offline-result"))[0] == 200
    assert state.snapshot()["connected"] is False


def test_lifecycle_concurrent_evaluation_retry_stores_once(http):
    from concurrent.futures import ThreadPoolExecutor
    call, _ = http
    call("/api/telemetry", telemetry())
    row = evaluation_row()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: call("/api/evaluation", row)[0], range(8)))
    assert results == [200] * 8
    assert call("/api/state")[1]["evaluations"] == [row]


def test_lifecycle_unacked_commands_redeliver_until_ack(http):
    call, _ = http
    call("/api/telemetry", telemetry())
    first = call("/api/control", {"command": "pause"})[1]
    second = call("/api/control", {"command": "resume"})[1]
    delivered = call("/api/control?sessionId=session-a")[1]
    assert call("/api/control?sessionId=session-a")[1] == delivered
    assert [c["commandId"] for c in delivered["commands"]] == [first["commandId"], second["commandId"]]
    ack = {"sessionId": "session-a", "commandId": first["commandId"], "status": "applied"}
    assert call("/api/ack", ack)[0] == 200
    assert call("/api/control?sessionId=session-a")[1] == {"commands": [delivered["commands"][1]]}
    assert call("/api/ack", {**ack, "message": ""})[0] == 200
    assert call("/api/state")[1]["lastCommand"]["commandId"] == second["commandId"]
    assert call("/api/ack", {**ack, "status": "error"})[0] == 409
    assert call("/api/ack", {**ack, "message": "different"})[0] == 409
    assert call("/api/ack", {**ack, "commandId": second["commandId"]})[0] == 200
    assert call("/api/control?sessionId=session-a")[1] == {"commands": []}


@pytest.mark.parametrize("ack_before_switch", [True, False])
def test_lifecycle_closed_session_ack_retry_never_resurrects_session(http, ack_before_switch):
    call, _ = http
    call("/api/telemetry", telemetry())
    command = call("/api/control", {"command": "scenario", "scenarioId": "rust"})[1]
    call("/api/control?sessionId=session-a")
    ack = {"sessionId": "session-a", "commandId": command["commandId"], "status": "applied", "message": "새 세션 시작"}
    if ack_before_switch:
        assert call("/api/ack", ack)[0] == 200
    call("/api/telemetry", telemetry(session="session-b", frame="b", raw=png()))
    call("/api/control", {"command": "pause"})
    before = call("/api/state")[1]
    assert call("/api/ack", ack) == (200, {"status": "ok"})
    assert call("/api/ack", ack) == (200, {"status": "ok"})
    after = call("/api/state")[1]
    for field in ("sessionId", "telemetry", "preview", "analyses", "lastCommand", "scenarios"):
        assert after[field] == before[field]
    assert call("/api/ack", {**ack, "sessionId": "session-b"})[0] == 409
    assert call("/api/ack", {**ack, "message": "conflicting"})[0] == 409
    assert call("/api/control?sessionId=session-a")[0] == 409
    assert len(call("/api/control?sessionId=session-b")[1]["commands"]) == 1
    assert call("/api/telemetry", telemetry(sequence=999))[0] == 409


def test_lifecycle_undelivered_closed_session_command_cannot_be_acked(http):
    call, _ = http
    call("/api/telemetry", telemetry())
    command = call("/api/control", {"command": "pause"})[1]
    call("/api/telemetry", telemetry(session="session-b"))
    assert call("/api/ack", {"sessionId": "session-a", "commandId": command["commandId"],
                             "status": "applied"})[0] == 409
    assert call("/api/control?sessionId=session-b")[1] == {"commands": []}


def test_lifecycle_receipt_ids_are_bounded(http):
    call, state = http
    state.max_receipts = 3
    call("/api/telemetry", telemetry())
    commands = []
    for i in range(8):
        state.evaluation(evaluation_row(run=f"run-{i}"))
        command = call("/api/control", {"command": "pause"})[1]
        commands.append(command)
        call("/api/control?sessionId=session-a")
        assert call("/api/ack", {"sessionId": "session-a", "commandId": command["commandId"],
                                 "status": "applied"})[0] == 200
        assert len(state.command_receipts) <= 3
        assert len(state.evaluation_receipts) <= 3
    assert len(state.command_receipts) == len(state.evaluation_receipts) == 3
    assert [key[1] for key in state.evaluation_receipts] == ["run-5", "run-6", "run-7"]
    assert call("/api/ack", {"sessionId": "session-a", "commandId": commands[0]["commandId"],
                             "status": "applied"})[0] == 409


def test_lifecycle_active_delivered_command_survives_receipt_eviction(http):
    call, state = http
    state.max_receipts = 1
    call("/api/telemetry", telemetry())
    first = call("/api/control", {"command": "pause"})[1]
    second = call("/api/control", {"command": "resume"})[1]
    call("/api/control?sessionId=session-a")
    assert len(state.command_receipts) == 1
    for command in (first, second):
        assert call("/api/ack", {"sessionId": "session-a", "commandId": command["commandId"],
                                 "status": "applied"})[0] == 200
    assert call("/api/control?sessionId=session-a")[1] == {"commands": []}


def test_lifecycle_concurrent_ack_retry_has_one_effect(http):
    from concurrent.futures import ThreadPoolExecutor
    call, state = http
    call("/api/telemetry", telemetry())
    command = call("/api/control", {"command": "pause"})[1]
    call("/api/control?sessionId=session-a")
    ack = {"sessionId": "session-a", "commandId": command["commandId"], "status": "applied"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(lambda _: call("/api/ack", ack)[0], range(8)))
    assert statuses == [200] * 8
    assert not state.pending
    assert call("/api/control?sessionId=session-a")[1] == {"commands": []}
    assert call("/api/state")[1]["lastCommand"]["status"] == "applied"


def test_lifecycle_closed_receipts_remain_bounded_across_sessions():
    from maek.inspection_dashboard import APIError
    state = DashboardState(max_receipts=3)
    acknowledgements = []
    for i in range(8):
        session = f"receipt-session-{i}"
        state.telemetry_update(telemetry(session=session, frame=f"receipt-frame-{i}"))
        command = state.control({"command": "pause"})
        state.drain(session)
        ack = {"sessionId": session, "commandId": command["commandId"], "status": "applied"}
        state.ack(ack)
        acknowledgements.append(ack)
        assert len(state.command_receipts) <= 3
    before = state.snapshot()
    assert state.ack(acknowledgements[-2]) == {"status": "ok"}
    assert state.snapshot()["telemetry"] == before["telemetry"]
    assert state.snapshot()["lastCommand"] == before["lastCommand"]
    with pytest.raises(APIError) as error:
        state.ack(acknowledgements[0])
    assert error.value.status == 409


def access_row(pipe="P0", *, planned=3, scheduled=3, analysed=0):
    geometry = "accessible" if scheduled == planned else "partial" if scheduled else "deferred"
    observation = "unobserved" if not analysed else "observed" if analysed == planned else "partial"
    inspection = "deferred" if not analysed else "completed" if analysed == planned else "partial"
    status = {"deferred": "inspection_deferred", "partial": "inspection_partial",
              "completed": "no_rgb_candidate"}[inspection]
    return {"pipeId": pipe, "plannedImages": planned, "scheduledImages": scheduled,
            "deferredImages": planned - scheduled, "analysedImages": analysed,
            "status": status, "observationStatus": observation, "inspectionStatus": inspection,
            "accessStatus": geometry,
            "accessReasons": [] if geometry == "accessible" else ["blocked_clearance: 통로 폭 부족"]}


def test_access_all_247_preserved_and_coverage_derived_over_http(http):
    call, _ = http
    rows = [access_row(f"PIPE-{i:03d}") for i in range(247)]
    rows[1] = access_row("PIPE-001", scheduled=0)
    rows[2] = access_row("PIPE-002", scheduled=2, analysed=1)
    rows[3] = access_row("PIPE-003", analysed=3)
    payload = {**telemetry(), "plannedPipes": 247, "access": rows, "complete": True}
    assert call("/api/telemetry", payload)[0] == 200
    actual = call("/api/state")[1]["telemetry"]
    assert actual["access"] == rows
    assert actual["coverage"] == {
        "totalPipes": 247, "scheduledPipes": 246, "observedPipes": 1,
        "deferredPipes": 245, "partialPipes": 1,
        "requiredCaptures": 741, "scheduledCaptures": 737, "deferredCaptures": 4,
    }
    # Route completion and geometrically accessible plans never turn zero observations healthy.
    assert actual["access"][0]["status"] == "inspection_deferred"
    assert actual["access"][0]["accessStatus"] == "accessible"
    assert actual["access"][0]["observationStatus"] == "unobserved"


def test_access_maximum_300_rows_and_legacy_optional_compatibility():
    state = DashboardState()
    state.telemetry_update(telemetry())
    assert "access" not in state.snapshot()["telemetry"]
    assert "coverage" not in state.snapshot()["telemetry"]
    rows = [access_row(f"P{i}") for i in range(300)]
    state.telemetry_update({**telemetry(sequence=2), "access": rows})
    assert state.snapshot()["telemetry"]["coverage"]["totalPipes"] == 300
    with pytest.raises(ValueError):
        state.telemetry_update({**telemetry(sequence=3), "access": rows + [access_row("P300")]})


@pytest.mark.parametrize("change", [
    {"plannedImages": 0}, {"plannedImages": True}, {"plannedImages": 3.0},
    {"scheduledImages": -1}, {"scheduledImages": 4}, {"deferredImages": 1},
    {"analysedImages": 4}, {"analysedImages": False}, {"status": "healthy"},
    {"status": "no_rgb_candidate"}, {"status": "candidate"},
    {"observationStatus": "observed"}, {"observationStatus": "partial"},
    {"inspectionStatus": "completed"}, {"inspectionStatus": "partial"},
    {"accessStatus": "safe"}, {"accessStatus": "deferred"},
    {"accessReasons": [12]}, {"accessReasons": [""]},
    {"accessReasons": ["x" * 513]}, {"accessReasons": ["blocked"] * 17},
    {"expected": "clean"}, {"position": {"x": 1, "y": 2, "z": 3}},
])
def test_access_rejects_malformed_or_false_zero_observation_completion(change):
    state = DashboardState()
    state.telemetry_update(telemetry())
    before = state.snapshot()
    with pytest.raises(ValueError):
        state.telemetry_update({**telemetry(sequence=2), "access": [{**access_row(), **change}]})
    assert state.snapshot()["telemetry"] == before["telemetry"]


@pytest.mark.parametrize("rows", [None, {}, [None], [access_row(), access_row()],
    [{key: value for key, value in access_row().items() if key != "accessReasons"}],
    [{**access_row(scheduled=0), "accessReasons": []}],
    [{**access_row(scheduled=2, analysed=1), "status": "no_rgb_candidate"}],
    [{**access_row(analysed=3), "observationStatus": "partial"}],
])
def test_access_requires_unique_exact_provenance_rows(rows):
    state = DashboardState()
    with pytest.raises(ValueError):
        state.telemetry_update({**telemetry(), "access": rows})


def test_access_declared_coverage_matches_rows_and_never_stands_alone():
    state = DashboardState()
    row = access_row(scheduled=0)
    expected = {"totalPipes": 1, "scheduledPipes": 0, "observedPipes": 0,
                "deferredPipes": 1, "partialPipes": 0,
                "requiredCaptures": 3, "scheduledCaptures": 0, "deferredCaptures": 3}
    state.telemetry_update({**telemetry(), "access": [row], "coverage": expected})
    assert state.snapshot()["telemetry"]["coverage"] == expected
    for coverage in ({**expected, "observedPipes": 1}, {**expected, "totalPipes": True},
                     {**expected, "expected": "clean"}, {}, None):
        with pytest.raises(ValueError):
            state.telemetry_update({**telemetry(sequence=2), "access": [row], "coverage": coverage})
    with pytest.raises(ValueError):
        state.telemetry_update({**telemetry(sequence=2), "coverage": expected})
    with pytest.raises(ValueError):
        state.telemetry_update({**telemetry(sequence=2), "access": [row], "plannedPipes": 247})


def test_access_does_not_raise_unrelated_metadata_list_limit():
    state = DashboardState()
    with pytest.raises(ValueError):
        state.telemetry_update({**telemetry(), "outcomes": [None] * 257})


def test_access_successful_and_incomplete_candidates_remain_distinct():
    state = DashboardState()
    rows = [{**access_row("P1", analysed=3), "status": "candidate"},
            {**access_row("P2", scheduled=2, analysed=1), "status": "candidate_incomplete"}]
    state.telemetry_update({**telemetry(), "access": rows})
    result = state.snapshot()["telemetry"]
    assert result["coverage"]["observedPipes"] == 1
    assert result["coverage"]["partialPipes"] == 1
    assert result["access"] == rows


def coverage_evaluation(**changes):
    return {**evaluation_row(), "captures": 3, "observationStatus": "observed",
            "inspectionStatus": "completed", "accessStatus": "accessible", "accessReasons": [],
            "requiredCaptures": 3, "scheduledCaptures": 3, **changes}


@pytest.mark.parametrize("partial", [False, True])
def test_coverage_evaluation_deferred_negative_is_nonapplicable_over_http(http, partial):
    call, _ = http
    row = access_row("247", scheduled=2 if partial else 0, analysed=1 if partial else 0)
    assert call("/api/telemetry", {**telemetry(), "access": [row]})[0] == 200
    payload = coverage_evaluation(
        captures=1 if partial else 0, observationStatus="partial" if partial else "unobserved",
        inspectionStatus="partial" if partial else "deferred", accessStatus=row["accessStatus"],
        accessReasons=row["accessReasons"], scheduledCaptures=row["scheduledImages"],
        observed="inspection_deferred", classification="inspection_deferred",
        detectionApplicable=False, detectionPass=False,
    )
    before = call("/api/state")[1]
    assert call("/api/evaluation", payload) == (200, {"status": "ok"})
    assert call("/api/evaluation", dict(reversed(list(payload.items()))))[0] == 200
    after = call("/api/state")[1]
    assert after["evaluations"] == [payload]
    for field in ("sessionId", "telemetry", "preview", "analyses", "lastCommand"):
        assert after[field] == before[field]


@pytest.mark.parametrize("field", ["observationStatus", "inspectionStatus", "accessStatus",
                                   "accessReasons", "requiredCaptures", "scheduledCaptures"])
def test_coverage_evaluation_group_is_all_or_absent(field):
    state = DashboardState()
    state.telemetry_update(telemetry())
    payload = coverage_evaluation()
    del payload[field]
    with pytest.raises(ValueError):
        state.evaluation(payload)
    assert state.evaluation(evaluation_row()) == {"status": "ok"}


@pytest.mark.parametrize("change", [
    {"observationStatus": "safe"}, {"inspectionStatus": "healthy"}, {"accessStatus": "safe"},
    {"requiredCaptures": 0}, {"requiredCaptures": True}, {"scheduledCaptures": 3.0},
    {"scheduledCaptures": -1}, {"scheduledCaptures": 4}, {"captures": 4}, {"captures": 0},
    {"accessReasons": None}, {"accessReasons": ["reason"] * 17},
    {"accessReasons": ["x" * 513]}, {"accessReasons": [2]}, {"accessReasons": [""]},
    {"observationStatus": "unobserved"}, {"inspectionStatus": "partial"},
    {"accessStatus": "deferred"}, {"scheduledCaptures": 2},
])
def test_coverage_evaluation_rejects_incoherent_counts_and_enums(change):
    state = DashboardState()
    state.telemetry_update(telemetry())
    with pytest.raises(ValueError):
        state.evaluation({**coverage_evaluation(), **change})
    assert state.snapshot()["evaluations"] == []


@pytest.mark.parametrize("change", [
    {"detectionApplicable": True}, {"detectionPass": True}, {"findings": 1},
    {"classification": "true_negative"}, {"classification": "false_negative"},
])
def test_coverage_evaluation_zero_observations_cannot_be_detection_result(change):
    state = DashboardState()
    state.telemetry_update(telemetry())
    payload = coverage_evaluation(captures=0, scheduledCaptures=0, observationStatus="unobserved",
        inspectionStatus="deferred", accessStatus="deferred", accessReasons=["no_route"],
        classification="inspection_deferred", observed="inspection_deferred",
        detectionApplicable=False, detectionPass=False)
    with pytest.raises(ValueError):
        state.evaluation({**payload, **change})


def test_coverage_evaluation_correlates_source_plan_and_survives_retired_session():
    state = DashboardState()
    row = access_row("247", analysed=3)
    state.telemetry_update({**telemetry(), "access": [row]})
    # The current session must not supply the plan/provenance for a delayed older evaluation.
    state.telemetry_update({**telemetry(session="session-b", frame="new"),
                            "access": [access_row("other", scheduled=0)]})
    payload = coverage_evaluation()
    assert state.evaluation(payload) == {"status": "ok"}
    assert state.evaluation(payload) == {"status": "ok"}
    assert state.snapshot()["sessionId"] == "session-b"
    for change in ({"runId": "other-run"}, {"pipeId": "other"},
                   {"requiredCaptures": 4, "scheduledCaptures": 4, "captures": 4}):
        with pytest.raises(ValueError):
            state.evaluation({**payload, **change})


def test_coverage_evaluation_new_group_does_not_change_pixel_inference(http):
    call, _ = http
    call("/api/telemetry", telemetry())
    request = {"requestId": "unchanged", "sessionId": "session-a",
               "imageBase64": base64.b64encode(png()).decode()}
    before = call("/analyse", request)[1]
    assert call("/api/evaluation", coverage_evaluation())[0] == 200
    assert call("/analyse", request)[1] == before
    assert "observationStatus" not in call("/api/state")[1]["analyses"][0]
