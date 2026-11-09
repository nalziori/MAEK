"""Thread-safe, bounded state for the loopback Unity inspection dashboard."""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import math
import threading
import time
import uuid
from collections import OrderedDict, deque

from PIL import Image

MAX_IMAGE_BYTES = 8_000_000
COMMANDS = frozenset({
    "scenario", "run_all", "start_original", "start_extra", "pause", "resume",
    "stop", "record_toggle", "view_toggle",
})
META = ("sessionId", "pipeId", "sampleId", "scenarioId", "scenarioRunId")
TELEMETRY = {
    "sessionId", "sequence", "source", "scenarioId", "scenarioRunId", "phase",
    "activePipe", "position", "yaw", "leg", "plannedPipes", "analysedPipes",
    "captures", "expectedCaptures", "collisionSteps", "blocked", "waiting",
    "complete", "recording", "droneView", "status", "frameId", "scenarios",
    "mappedFindings", "outcomes", "cameraAvailable", "active", "paused",
    "optionalGuidance", "guidance", "sensorRequirement", "access", "coverage",
}


class APIError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def identifier(value, name="identifier") -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 100:
        raise APIError(f"{name}: 1..100자 문자열이 필요합니다")
    return value


def bounded_json(payload, *, allow_access=False) -> None:
    """Reject nonfinite numbers, deep containers and oversized untrusted text."""
    def check(value, depth=0, list_limit=256):
        if depth > 8:
            raise APIError("중첩 깊이 초과")
        if isinstance(value, float) and not math.isfinite(value):
            raise APIError("유한한 숫자가 필요합니다")
        if isinstance(value, str) and len(value) > 4096:
            raise APIError("문자열 크기 초과")
        if isinstance(value, dict):
            if len(value) > 128:
                raise APIError("필드 수 초과")
            for key, item in value.items():
                check(key, depth + 1)
                limit = 300 if allow_access and depth == 0 and key == "access" else 256
                check(item, depth + 1, limit)
        if isinstance(value, list):
            if len(value) > list_limit:
                raise APIError("목록 크기 초과")
            for item in value:
                check(item, depth + 1)
    if not isinstance(payload, dict):
        raise APIError("JSON 객체가 필요합니다")
    check(payload)
    if len(json.dumps(payload, ensure_ascii=False)) > 128_000:
        raise APIError("메타데이터 크기 초과")


def decode_image(encoded, *, png_only=False):
    if not isinstance(encoded, str) or len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 4:
        raise APIError("이미지 크기 또는 형식 오류")
    raw = base64.b64decode(encoded, validate=True)
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise APIError("이미지 크기 초과")
    with Image.open(io.BytesIO(raw)) as source:
        if source.width > 1280 or source.height > 720:
            raise APIError("Capture must be at most 1280x720")
        if png_only and source.format != "PNG":
            raise APIError("PNG 이미지가 필요합니다")
        rgb = source.convert("RGB")
        rgb.load()
    return raw, rgb


def position(value):
    if not isinstance(value, dict) or set(value) != {"x", "y", "z"} or any(
        type(v) not in (int, float) or not math.isfinite(v) for v in value.values()
    ):
        raise APIError("position 형식 오류")


def mapped_results(data):
    for key, fields in (
        ("mappedFindings", {"pipeId", "requestId", "imageSha256", "kind", "position", "recommendation"}),
        ("outcomes", {"requestId", "pipeId", "sampleId", "status", "visibleTargetSamples", "newFindings"}),
    ):
        items = data.get(key, [])
        if not isinstance(items, list) or len(items) > 40:
            raise APIError(f"{key}: 최대 40개까지 허용됩니다")
        for item in items:
            extras = {"normal", "model", "pixelCount", "mappedSamples"} if key == "mappedFindings" else set()
            if not isinstance(item, dict) or not fields <= set(item) or set(item) - fields - extras:
                raise APIError(f"{key}: 필드 형식 오류")
            for field in ("requestId", "pipeId"):
                identifier(item[field], field)
            if key == "mappedFindings":
                digest = item["imageSha256"]
                if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                    raise APIError("imageSha256 형식 오류")
                position(item["position"])
                if "normal" in item:
                    position(item["normal"])
                if "model" in item and not isinstance(item["model"], str):
                    raise APIError("model 문자열 형식 오류")
                for field in ("pixelCount", "mappedSamples"):
                    if field in item and (type(item[field]) is not int or not 0 <= item[field] <= 1280 * 720):
                        raise APIError(f"{field}: 픽셀 개수 범위 오류")
                if any(not isinstance(item[field], str) for field in ("kind", "recommendation")):
                    raise APIError("매핑 결과 문자열 형식 오류")
            else:
                identifier(item["sampleId"], "sampleId")
                if not isinstance(item["status"], str):
                    raise APIError("outcome status 형식 오류")
                for field in ("visibleTargetSamples", "newFindings"):
                    if type(item[field]) is not int or item[field] < 0:
                        raise APIError("outcome 개수 형식 오류")


def access_coverage(data):
    """Keep planned geometry separate from actual observation/completion evidence."""
    if "access" not in data:
        if "coverage" in data:
            raise APIError("coverage에는 원본 access 행이 필요합니다")
        return
    rows = data["access"]
    fields = {"pipeId", "plannedImages", "scheduledImages", "deferredImages", "analysedImages",
              "status", "observationStatus", "inspectionStatus", "accessStatus", "accessReasons"}
    if not isinstance(rows, list) or len(rows) > 300:
        raise APIError("access: 최대 300개 행이 필요합니다")
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != fields:
            raise APIError("access: 허용된 10개 필드만 필요합니다")
        pipe_id = identifier(row["pipeId"], "pipeId")
        if pipe_id in ids:
            raise APIError("access: 배관 ID가 중복되었습니다")
        ids.add(pipe_id)
        for field in ("plannedImages", "scheduledImages", "deferredImages", "analysedImages"):
            if type(row[field]) is not int or row[field] < 0:
                raise APIError(f"access.{field}: 0 이상의 정수가 필요합니다")
        required, scheduled = row["plannedImages"], row["scheduledImages"]
        deferred, analysed = row["deferredImages"], row["analysedImages"]
        if required < 1 or scheduled > required or analysed > scheduled or deferred != required - scheduled:
            raise APIError("access: 필수·계획·유예·분석 촬영 수가 일치하지 않습니다")
        geometry = "accessible" if scheduled == required else "partial" if scheduled else "deferred"
        if row["accessStatus"] != geometry:
            raise APIError("accessStatus가 촬영 접근 계획과 다릅니다")
        reasons = row["accessReasons"]
        if (not isinstance(reasons, list) or len(reasons) > 16
                or any(not isinstance(r, str) or not r.strip() or len(r) > 512 for r in reasons)
                or geometry != "accessible" and not reasons):
            raise APIError("accessReasons: 최대 16개, 각 1..512자 사유가 필요합니다")
        observation, inspection, status = (
            row["observationStatus"], row["inspectionStatus"], row["status"]
        )
        if analysed == 0:
            valid = (observation == "unobserved" and inspection == "deferred"
                     and status == "inspection_deferred")
        elif inspection == "completed":
            valid = (observation == "observed" and analysed == required and deferred == 0
                     and status in ("candidate", "no_rgb_candidate"))
        else:
            valid = (inspection == "partial" and observation == "partial"
                     and status in ("inspection_partial", "candidate_incomplete"))
        if not valid:
            raise APIError("access: 미관측·부분 관측은 완료 또는 무후보 판정이 될 수 없습니다")
    if "plannedPipes" in data and data["plannedPipes"] != len(rows):
        raise APIError("access는 계획된 모든 배관 행을 포함해야 합니다")
    coverage = {
        "totalPipes": len(rows),
        "scheduledPipes": sum(r["scheduledImages"] > 0 for r in rows),
        "observedPipes": sum(r["observationStatus"] == "observed" for r in rows),
        "deferredPipes": sum(r["inspectionStatus"] == "deferred" for r in rows),
        "partialPipes": sum(r["inspectionStatus"] == "partial" for r in rows),
        "requiredCaptures": sum(r["plannedImages"] for r in rows),
        "scheduledCaptures": sum(r["scheduledImages"] for r in rows),
        "deferredCaptures": sum(r["deferredImages"] for r in rows),
    }
    if "coverage" in data:
        given = data["coverage"]
        if (not isinstance(given, dict) or set(given) != set(coverage)
                or any(type(v) is not int or v < 0 for v in given.values()) or given != coverage):
            raise APIError("coverage는 access 행의 실제 집계와 일치해야 합니다")
    data["coverage"] = coverage


EVALUATION_COVERAGE = {
    "observationStatus", "inspectionStatus", "accessStatus", "accessReasons",
    "requiredCaptures", "scheduledCaptures",
}


def evaluation_coverage(payload):
    required, scheduled = payload["requiredCaptures"], payload["scheduledCaptures"]
    if (type(required) is not int or type(scheduled) is not int
            or not 1 <= required <= 2_147_483_647 or not 0 <= scheduled <= required
            or payload["captures"] > scheduled):
        raise APIError("평가 필수·계획·실제 촬영 수가 일치하지 않습니다")
    geometry = "accessible" if scheduled == required else "partial" if scheduled else "deferred"
    reasons = payload["accessReasons"]
    if (payload["accessStatus"] != geometry or not isinstance(reasons, list) or len(reasons) > 16
            or any(not isinstance(r, str) or not r.strip() or len(r) > 512 for r in reasons)
            or geometry != "accessible" and not reasons):
        raise APIError("평가 접근 상태·사유 형식 오류")
    observation, inspection = payload["observationStatus"], payload["inspectionStatus"]
    if observation == "unobserved":
        valid = (inspection == "deferred" and payload["findings"] == 0
                 and not payload["detectionApplicable"] and not payload["detectionPass"])
    elif observation == "partial":
        valid = inspection == "partial" and payload["captures"] > 0
    elif observation == "observed":
        valid = inspection == "completed" and scheduled == required == payload["captures"]
    else:
        valid = False
    classification = payload["classification"]
    if (not valid or payload["detectionPass"] and not payload["detectionApplicable"]
            or inspection != "completed" and classification in ("true_negative", "false_negative")
            or observation == "unobserved" and classification in ("true_positive", "false_positive")):
        raise APIError("미관측·부분 검사 평가는 완료/음성 검출 평가로 바꿀 수 없습니다")


def metadata(payload):
    result = {key: identifier(payload[key], key) for key in META if key in payload}
    return result


class DashboardState:
    def __init__(self, *, max_frames=64, max_frame_bytes=64_000_000,
                 max_commands=64, connected_seconds=10, clock=time.time, max_receipts=1024):
        self.lock = threading.RLock()
        self.clock = clock
        self.max_frames = max_frames
        self.max_frame_bytes = max_frame_bytes
        self.max_commands = max_commands
        if type(max_receipts) is not int or max_receipts < 1:
            raise ValueError("max_receipts must be a positive integer")
        self.max_receipts = max_receipts
        # Replay guarantees cover the most recent max_receipts IDs in each cache.
        self.command_receipts = OrderedDict()
        self.evaluation_receipts = OrderedDict()
        # Preserve immutable plan correlation for delayed evaluations across up to 64 runs.
        self.evaluation_sources = OrderedDict()
        self.connected_seconds = connected_seconds
        self.session = None
        self.retired = set()
        self.telemetry = None
        self.updated = None
        self.preview = None
        self.frames = OrderedDict()
        self.frame_ids = set()
        self.frame_bytes = 0
        self.analyses = deque(maxlen=128)
        self.evaluations = deque(maxlen=128)
        self.scenarios = []
        self.commands = deque()
        self.pending = {}
        self.last_command = None

    def _connected(self):
        return self.updated is not None and self.clock() - self.updated <= self.connected_seconds

    def _session(self, session):
        if session != self.session or not self._connected():
            raise APIError("현재 연결된 세션이 아닙니다", 409)

    def _frame(self, frame_id, raw):
        digest = hashlib.sha256(raw).hexdigest()
        if frame_id in self.frames:
            if self.frames[frame_id] != raw:
                raise APIError("frameId는 다른 이미지에 재사용할 수 없습니다", 409)
        else:
            if frame_id in self.frame_ids:
                raise APIError("퇴거된 frameId는 재사용할 수 없습니다", 409)
            if len(self.frame_ids) >= 65_536:
                raise APIError("프레임 ID 한도 초과: 서버를 재시작하세요", 409)
            if len(raw) > self.max_frame_bytes:
                raise APIError("프레임 보관 용량 초과", 413)
            self.frame_ids.add(frame_id)
            self.frames[frame_id] = raw
            self.frame_bytes += len(raw)
            while len(self.frames) > self.max_frames or self.frame_bytes > self.max_frame_bytes:
                _, evicted = self.frames.popitem(last=False)
                self.frame_bytes -= len(evicted)
        return {"frameId": frame_id, "imageSha256": digest,
                "url": f"/api/frame/{frame_id}"}

    def telemetry_update(self, payload):
        data = {key: value for key, value in payload.items() if key != "imageBase64"}
        bounded_json(data, allow_access=True)
        if set(data) - TELEMETRY:
            raise APIError("알 수 없는 텔레메트리 필드")
        session = identifier(data.get("sessionId"), "sessionId")
        sequence = data.get("sequence")
        if type(sequence) is not int or sequence < 0:
            raise APIError("sequence는 0 이상의 정수여야 합니다")
        if data.get("source") != "unity_virtual":
            raise APIError("Unity 가상 드론만 지원합니다")
        for key in ("scenarioId", "scenarioRunId", "frameId"):
            identifier(data.get(key), key)
        # Frame ids are URL path segments, never filesystem paths.
        if any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in data["frameId"]):
            raise APIError("frameId 형식 오류")
        for key in ("blocked", "waiting", "complete", "recording", "cameraAvailable", "active", "paused"):
            if key in data and type(data[key]) is not bool:
                raise APIError(f"{key}: boolean이 필요합니다")
        if "droneView" in data and data["droneView"] not in ("fpv", "chase"):
            raise APIError("droneView는 fpv 또는 chase여야 합니다")
        for key in ("leg", "plannedPipes", "analysedPipes", "captures", "expectedCaptures", "collisionSteps"):
            if key in data and (type(data[key]) is not int or data[key] < 0):
                raise APIError(f"{key}: 0 이상의 정수가 필요합니다")
        if "position" in data:
            position(data["position"])
        mapped_results(data)
        access_coverage(data)
        if "yaw" in data and type(data["yaw"]) not in (int, float):
            raise APIError("yaw 형식 오류")
        for key in ("phase", "activePipe", "status", "optionalGuidance", "guidance", "sensorRequirement"):
            if key in data and not isinstance(data[key], str):
                raise APIError(f"{key}: 문자열이 필요합니다")
        scenarios = data.get("scenarios", [])
        if not isinstance(scenarios, list) or len(scenarios) > 64:
            raise APIError("scenarios 형식 오류")
        ids = set()
        for scenario in scenarios:
            if not isinstance(scenario, dict) or set(scenario) != {"id", "title", "description", "capability"}:
                raise APIError("시나리오 설명 형식 오류")
            sid = identifier(scenario["id"])
            if sid in ids or any(not isinstance(v, str) for v in scenario.values()):
                raise APIError("시나리오 중복 또는 형식 오류")
            ids.add(sid)
        encoded = payload.get("imageBase64")
        raw = None if encoded is None or encoded == "" else decode_image(encoded, png_only=True)[0]
        with self.lock:
            if session in self.retired:
                raise APIError("종료된 세션입니다", 409)
            if session == self.session and sequence <= self.telemetry["sequence"]:
                raise APIError("sequence가 증가해야 합니다", 409)
            if session != self.session and self.session and len(self.retired) >= 1024:
                raise APIError("세션 한도 초과: 서버를 재시작하세요", 409)
            # Validate frame conflicts before changing any session state.
            preview = self._frame(data["frameId"], raw) if raw is not None else None
            if session != self.session:
                if self.session:
                    self.retired.add(self.session)
                self.commands.clear()
                self.pending.clear()
                self.last_command = None
                self.analyses.clear()
                self.preview = None
                self.scenarios = []
            if not self._connected():
                self.commands.clear()
                self.pending.clear()
                if self.last_command:
                    self.last_command.update(status="error", message="연결 만료로 명령이 취소되었습니다")
            self.session = session
            self.telemetry = copy.deepcopy(data)
            source_key = (session, data["scenarioRunId"], data["scenarioId"])
            if source_key not in self.evaluation_sources or "access" in data:
                self.evaluation_sources[source_key] = None if "access" not in data else {
                    row["pipeId"]: {"requiredCaptures": row["plannedImages"],
                                    "scheduledCaptures": row["scheduledImages"],
                                    "accessStatus": row["accessStatus"]}
                    for row in data["access"]
                }
            self.evaluation_sources.move_to_end(source_key)
            while len(self.evaluation_sources) > 64:
                self.evaluation_sources.popitem(last=False)
            self.updated = self.clock()
            if "scenarios" in data:
                self.scenarios = copy.deepcopy(scenarios)
            # Never associate the prior image with a new telemetry frame id.
            self.preview = preview or (self.preview if self.preview and self.preview["frameId"] == data["frameId"] else None)
            if data.get("cameraAvailable") is False:
                self.preview = None
        return {"status": "ok"}

    def snapshot(self):
        with self.lock:
            return copy.deepcopy({
                "version": 1, "serverTimeMs": int(self.clock() * 1000),
                "sessionId": self.session, "connected": self._connected(),
                "ageSeconds": None if self.updated is None else max(0, self.clock() - self.updated),
                "telemetry": self.telemetry, "preview": self.preview if self._connected() else None,
                "analyses": list(self.analyses), "evaluations": list(self.evaluations),
                "scenarios": self.scenarios, "lastCommand": self.last_command,
            })

    def frame(self, frame_id):
        with self.lock:
            if frame_id not in self.frames:
                raise APIError("프레임이 없거나 보관 기한이 지났습니다", 404)
            return self.frames[frame_id]

    def record_analysis(self, result, raw, meta):
        with self.lock:
            if meta.get("sessionId") != self.session or not self._connected():
                return
            frame = self._frame("analysis_" + uuid.uuid4().hex, raw)
            self.analyses.appendleft(copy.deepcopy({
                **result, **{key: meta.get(key) for key in META}, "frameUrl": frame["url"],
                "receivedAtMs": int(self.clock() * 1000),
            }))

    def control(self, payload):
        bounded_json(payload)
        command = payload.get("command")
        if not isinstance(command, str) or command not in COMMANDS or set(payload) - {"command", "scenarioId"}:
            raise APIError("지원하지 않는 명령입니다")
        sid = payload.get("scenarioId")
        if sid is not None:
            identifier(sid, "scenarioId")
        with self.lock:
            self._session(self.session)
            if (command == "scenario" or sid is not None) and sid not in {s["id"] for s in self.scenarios}:
                raise APIError("등록되지 않은 시나리오입니다")
            if len(self.pending) >= self.max_commands:
                raise APIError("명령 대기열이 가득 찼습니다", 409)
            item = {"commandId": uuid.uuid4().hex, "command": command}
            if sid is not None:
                item["scenarioId"] = sid
            self.commands.append(item)
            self.pending[item["commandId"]] = {**item, "delivered": False}
            self.last_command = {**item, "scenarioId": sid, "status": "queued", "message": ""}
            return {"commandId": item["commandId"], "status": "queued"}

    def _trim_receipts(self, receipts):
        while len(receipts) > self.max_receipts:
            receipts.popitem(last=False)

    def drain(self, session):
        with self.lock:
            self._session(session)
            items = list(self.commands)
            for item in items:
                self.pending[item["commandId"]]["delivered"] = True
                self.command_receipts.setdefault((session, item["commandId"]), {"ack": None})
            self._trim_receipts(self.command_receipts)
            # Unity deduplicates commandId because delivery is at least once.
            return {"commands": copy.deepcopy(items)}

    def ack(self, payload):
        bounded_json(payload)
        session = identifier(payload.get("sessionId"), "sessionId")
        cid = identifier(payload.get("commandId"), "commandId")
        if payload.get("status") not in ("applied", "error") or not isinstance(payload.get("message", ""), str):
            raise APIError("명령 결과 형식 오류")
        result = {"status": payload["status"], "message": payload.get("message", "")}
        with self.lock:
            key = (session, cid)
            receipt = self.command_receipts.get(key)
            if receipt is None:
                item = self.pending.get(cid) if session == self.session else None
                if not item or not item["delivered"]:
                    raise APIError("전달되지 않았거나 만료된 명령입니다", 409)
                receipt = {"ack": None}
                self.command_receipts[key] = receipt
            if receipt["ack"] is not None:
                if receipt["ack"] != result:
                    raise APIError("이미 확정된 명령 결과와 다릅니다", 409)
                return {"status": "ok"}
            receipt["ack"] = result
            self._trim_receipts(self.command_receipts)
            # Receipt-only ACKs for retired sessions cannot mutate the current session.
            if session == self.session:
                self.pending.pop(cid, None)
                self.commands = deque(item for item in self.commands if item["commandId"] != cid)
                if self.last_command and self.last_command["commandId"] == cid:
                    self.last_command.update(result)
        return {"status": "ok"}

    def evaluation(self, payload):
        bounded_json(payload)
        fields = {"sessionId", "runId", "scenarioId", "title", "pipeId", "expected", "observed", "classification", "guardPass", "detectionPass", "detectionApplicable", "findings", "captures", "errors", "workPermissionStatus"}
        extended = set(payload) == fields | EVALUATION_COVERAGE
        if (set(payload) != fields and not extended
                or payload.get("workPermissionStatus") != "not_assessed"):
            raise APIError("평가 필드 형식 오류")
        for key in ("sessionId", "runId", "scenarioId", "pipeId"):
            identifier(payload[key], key)
        if any(type(payload[key]) is not bool for key in ("guardPass", "detectionPass", "detectionApplicable")) or not isinstance(payload["errors"], list):
            raise APIError("평가 결과 형식 오류")
        for key in ("findings", "captures"):
            if type(payload[key]) is not int or payload[key] < 0:
                raise APIError("평가 개수 형식 오류")
        for key in ("title", "classification"):
            if not isinstance(payload[key], str):
                raise APIError("평가 문자열 형식 오류")
        if extended:
            evaluation_coverage(payload)
        key = tuple(payload[field] for field in ("sessionId", "runId", "scenarioId", "pipeId"))
        digest = hashlib.sha256(json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")).hexdigest()
        with self.lock:
            if payload["sessionId"] != self.session and payload["sessionId"] not in self.retired:
                raise APIError("알 수 없는 평가 세션입니다", 409)
            previous = self.evaluation_receipts.get(key)
            if previous is not None:
                if previous != digest:
                    raise APIError("동일 평가 식별자의 결과가 다릅니다", 409)
                return {"status": "ok"}
            if extended:
                source_key = (payload["sessionId"], payload["runId"], payload["scenarioId"])
                if (source_key not in self.evaluation_sources and any(
                        k[0] == payload["sessionId"] for k in self.evaluation_sources)):
                    raise APIError("평가 실행 출처가 텔레메트리와 다릅니다", 409)
                source = self.evaluation_sources.get(source_key)
                if source is not None:
                    row = source.get(payload["pipeId"])
                    if row is None or any(payload[field] != value for field, value in row.items()):
                        raise APIError("평가 배관·촬영 계획이 원본 텔레메트리와 다릅니다", 409)
            self.evaluation_receipts[key] = digest
            self._trim_receipts(self.evaluation_receipts)
            self.evaluations.appendleft(copy.deepcopy(payload))
        return {"status": "ok"}
