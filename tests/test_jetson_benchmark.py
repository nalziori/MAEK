import copy
import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from maek.jetson_benchmark import (
    array_hash,
    compare_segmentations,
    is_target_jetson,
    timed_calls,
    validate_collection,
    validate_engine_environment,
)
from maek.onboard_models import summarize


def test_hardware_guard_requires_linux_arm_orin_and_l4t():
    assert is_target_jetson("Linux", "aarch64", "NVIDIA Jetson Orin Nano Developer Kit", "R36")
    assert not is_target_jetson("Windows", "AMD64", "NVIDIA Jetson Orin Nano", "R36")
    assert not is_target_jetson("Linux", "aarch64", "NVIDIA Jetson Orin Nano", None)
    assert not is_target_jetson("Linux", "aarch64", "NVIDIA Jetson AGX Orin", "R36")


def test_hash_captures_shape_dtype_and_pixels():
    a = np.arange(12, dtype=np.uint8)
    assert array_hash(a) == array_hash(a.copy())
    assert array_hash(a) != array_hash(a.reshape(3, 4))
    assert array_hash(a) != array_hash(a.view(np.int8))
    b = a.copy()
    b[0] = 100
    assert array_hash(a) != array_hash(b)


def test_timer_waits_for_gpu_completion_inside_each_sample():
    events = []
    values = iter([0, 0.001, 0.004, 0.005, 0.010, 0.011])
    times, elapsed = timed_calls(lambda i: events.append(("call", i)),
                                lambda: events.append("sync"), 2, lambda: next(values))
    assert times == pytest.approx([3, 5])
    assert elapsed == pytest.approx(0.011)
    assert events == ["sync", "sync", ("call", 0), "sync", "sync", ("call", 1), "sync"]


def test_conversion_comparison_does_not_match_by_detection_order():
    a = {"boxes": np.zeros((2, 6)), "unions": {0: np.array([[1, 0]], bool)}}
    b = {"boxes": np.zeros((1, 6)), "unions": {0: np.array([[1, 1]], bool)}}
    result = compare_segmentations(a, b)
    assert result["class_union_iou"] == {"0": 0.5}
    assert result["reference_detections"] == 2
    assert result["candidate_detections"] == 1
    empty = {"boxes": np.zeros((0, 6)), "unions": {}}
    assert compare_segmentations(empty, empty)["both_empty"]
    assert compare_segmentations(empty, a)["class_union_iou"] == {"0": 0.0}


def sample_rows():
    stats = summarize([1.0, 2.0], 0.003, None)
    base = {"schema": "maek-jetson-v1", "environment": {"target_jetson_detected": True},
            "model": "ut", "backend": "pytorch", "device": "cpu", "precision": "fp32",
            "size": 4096, "input_hashes": ["abc"], "archive_sha256": "data",
            "weights_sha256": None, "engine_sha256": None, "protocol": {"repeats": 2},
            "code_sha256": {"script": "code"}, "model_only": stats, "end_to_end": stats}
    return [dict(copy.deepcopy(base), run=run) for run in (1, 2, 3)]


def test_collection_accepts_complete_same_protocol_and_recomputes_timing():
    assert len(validate_collection(sample_rows())) == 1


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "input", "source", "pc", "timing", "runtime"])
def test_collection_rejects_incomplete_or_mixed_or_corrupt_results(mutation):
    rows = sample_rows()
    if mutation == "missing":
        rows.pop()
    elif mutation == "duplicate":
        rows[-1]["run"] = 2
    elif mutation == "input":
        rows[-1]["input_hashes"] = ["different"]
    elif mutation == "source":
        rows[-1]["code_sha256"] = {"script": "changed"}
    elif mutation == "pc":
        rows[-1]["environment"]["target_jetson_detected"] = False
    elif mutation == "timing":
        rows[-1]["model_only"]["p95_ms"] = 123
    elif mutation == "runtime":
        rows[-1]["environment"]["versions"] = {"torch": "different"}
    with pytest.raises(ValueError):
        validate_collection(rows)


def load_cli():
    script = Path(__file__).resolve().parents[1] / "scripts/benchmark_jetson.py"
    spec = importlib.util.spec_from_file_location("jetson_cli_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_rejects_pc_before_output_creation(tmp_path, monkeypatch):
    module = load_cli()
    monkeypatch.setattr(module, "probe", lambda: {"target_jetson_detected": False})
    output = tmp_path / "must-not-exist"
    with pytest.raises(SystemExit) as exc:
        module.main(["--data", str(tmp_path), "--output", str(output)])
    assert exc.value.code == 2
    assert not output.exists()


def test_collect_writes_six_scope_rows_without_loading_models(tmp_path):
    module = load_cli()
    for row in sample_rows():
        module.write_json(tmp_path / f"run-{row['run']}.json", row)
    result = module.collect(tmp_path)
    assert result["runs"] == 3 and result["configurations"] == 1
    with (tmp_path / "latency.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 6
    assert {row["scope"] for row in rows} == {"model_only", "end_to_end"}
    telemetry = json.loads((tmp_path / "collection-status.json").read_text())
    assert all(not item["nonempty"] for item in telemetry["tegrastats"])
    with pytest.raises(FileExistsError):
        module.collect(tmp_path)


def test_engine_rejects_unknown_or_changed_build_environment():
    environment = {"target_jetson_detected": True, "machine": "aarch64",
                   "device_tree_model": "NVIDIA Jetson Orin Nano", "l4t": "test-release",
                   "torch_runtime": {"cuda_build": "test-cuda", "gpu": "Orin", "capability": [8, 7]},
                   "tensorrt_runtime": {"version": "test-trt"}}
    assert validate_engine_environment(environment, copy.deepcopy(environment))["status"] == "matched"
    for key in ("l4t", "device_tree_model", "tensorrt_runtime"):
        changed = copy.deepcopy(environment)
        changed[key] = {"version": "different"} if key == "tensorrt_runtime" else "different"
        with pytest.raises(ValueError, match="rebuild on the target Jetson"):
            validate_engine_environment(environment, changed)
    unknown = copy.deepcopy(environment)
    unknown["tensorrt_runtime"] = {"error": "unavailable"}
    with pytest.raises(ValueError, match="unknown"):
        validate_engine_environment(environment, unknown)
    with pytest.raises(ValueError, match="both identify"):
        validate_engine_environment({}, environment)


class ArrayTensor:
    """Minimal tensor interface to test byte hashing without importing PyTorch."""

    def __init__(self, values):
        self.values = np.asarray(values)

    def detach(self):
        return self

    def cpu(self):
        return self

    def contiguous(self):
        return ArrayTensor(np.ascontiguousarray(self.values))

    def numpy(self):
        return self.values


def test_model_state_hash_is_order_independent_and_captures_tensor_identity():
    function = load_cli().state_dict_sha256
    values = np.arange(6, dtype=np.float32).reshape(2, 3)
    first = {"weight": ArrayTensor(values), "bias": ArrayTensor(np.zeros(2, np.float32))}
    expected = function(first)
    reverse = {"bias": first["bias"], "weight": ArrayTensor(np.asfortranarray(values))}
    assert function(reverse) == expected
    assert len(expected) == 64
    alternatives = [values.reshape(3, 2), values.astype(np.float64), values + 1]
    for array in alternatives:
        assert function({**first, "weight": ArrayTensor(array)}) != expected
    assert function({"renamed_weight": first["weight"], "bias": first["bias"]}) != expected


def test_collection_rejects_model_state_hash_drift_via_protocol():
    rows = sample_rows()
    for row in rows:
        row["protocol"]["model_state_sha256"] = "first-state"
    rows[-1]["protocol"]["model_state_sha256"] = "different-state"
    with pytest.raises(ValueError, match="protocol drift"):
        validate_collection(rows)
