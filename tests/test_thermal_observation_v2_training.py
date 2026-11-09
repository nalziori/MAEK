"""Only toy pairs and untrained fixture baseline weights are used in these tests."""
import copy
import json
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from maek.thermal_observation_model import ARCHITECTURE, build_model
from scripts import train_thermal_observation_v2 as training


def fixture(tmp_path):
    data = tmp_path / "data"
    data.mkdir(); (data / "samples").mkdir(); (data / "quality-fixtures").mkdir()
    rows = []
    for split in ("train", "dev", "test", "stress"):
        for index in range(6 if split in ("train", "dev") else 1):
            name = f"{split}_{index}"
            relative = f"samples/{name}.npz"
            path = data / relative
            if split in ("train", "dev"):
                reference = np.full((16, 20), 20 + index, np.float32)
                current, target = reference.copy(), np.zeros((16, 20), np.uint8)
                current[2:6, 3:9] += .5
                target[2:6, 3:9] = 1; target[-1, -1] = 255
                np.savez(path, reference_c=reference, current_c=current, target=target)
            else:
                path.write_bytes(b"INVALID NPZ: heldout arrays must never be opened")
            rows.append({"sample_id": name, "base_scene_id": name, "split": split,
                         "relative_path": relative, "sha256": training.sha(path), "segmentation_eligible": True})
    quality = data / "quality-fixtures/q.npz"
    quality.write_bytes(b"INVALID NPZ: quality arrays must never be opened")
    quality_row = {"sample_id": "q", "base_scene_id": "train_0", "split": "train",
                   "relative_path": "quality-fixtures/q.npz", "sha256": training.sha(quality), "segmentation_eligible": False}
    (data / "index.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    (data / "quality-index.jsonl").write_text(json.dumps(quality_row), encoding="utf-8")
    training.write_json(data / "manifest.json", {"training_eligible_scope": training.TRAINING_SCOPE, "fixture_only": True})
    training.write_json(data / "protocol.json", {"fixture_only": True})
    training.write_json(data / "evidence-ledger.json", {"fixture_only": True})
    training.write_json(data / "validation.json", {"status": "passed", "fixture_only": True,
        "training_eligible_scope": training.TRAINING_SCOPE,
        "manifest_sha256": training.sha(data / "manifest.json"),
        "protocol_sha256": training.sha(data / "protocol.json"),
        "index_sha256": training.sha(data / "index.jsonl")})
    torch.manual_seed(711)
    baseline_model = build_model()
    baseline = tmp_path / "baseline.pt"
    torch.save({"model_state": baseline_model.state_dict(), "architecture": ARCHITECTURE,
                "scope": training.TRAINING_SCOPE, "input_transform": training.INPUT_TRANSFORM,
                "smoke_only": True, "optimizer_state": {"must_not_restore": True}}, baseline)
    protocol = {"version": 2, "scope": training.TRAINING_SCOPE, "baseline": {"sha256": training.sha(baseline)},
                "data_hashes": {name: training.sha(data / name) for name in training.DATA_FILES},
                "training": copy.deepcopy(training.TRAINING),
                "source_hashes": {name: training.sha(training.ROOT / name) for name in training.REQUIRED_SOURCES}}
    protocol_path = tmp_path / "experiment.json"
    training.write_json(protocol_path, protocol)
    return data, baseline, protocol_path, protocol, training.state_sha256(baseline_model)


def test_mode_initialization_is_correct_and_scratch_reproducible(tmp_path):
    _, baseline, _, _, baseline_state_sha = fixture(tmp_path)
    finetune = training.initialize_model("finetune", baseline, 20261119)
    scratch = training.initialize_model("scratch", baseline, 20261119)
    assert training.state_sha256(finetune) == baseline_state_sha
    assert training.state_sha256(scratch) != baseline_state_sha
    assert training.state_sha256(training.initialize_model("scratch", baseline, 20261119)) == training.state_sha256(scratch)


def test_both_smoke_modes_reset_optimizer_and_use_identical_batch_plan(tmp_path):
    data, baseline, protocol_path, protocol, _ = fixture(tmp_path)
    outputs = {}
    for mode in ("finetune", "scratch"):
        out = tmp_path / mode
        outputs[mode] = training.train(data, baseline, out, protocol_path, mode, device="cpu", smoke=True)
        report = outputs[mode]
        assert report["status"] == "smoke_passed" and not report["training_completed"]
        assert report["optimizer_state_reset"] and report["optimizer_initial_state_entries"] == 0
        assert report["scheduler_state_reset"] and report["optimizer_steps"] == 1
        assert report["sample_counts"] == {"train": 4, "dev": 4}
        assert report["sample_ids"]["train"] == [f"train_{i}" for i in range(4)]
        assert not report["holdout_arrays_loaded"] and not report["quality_index_arrays_loaded"]
        assert not report["dev_selection_quality_gate_applied"]
        assert report["data_hashes"] == protocol["data_hashes"]
        checkpoint = torch.load(out / "best.pt", weights_only=True, map_location="cpu")
        build_model().load_state_dict(checkpoint["model_state"], strict=True)
        assert checkpoint["mode"] == mode and checkpoint["smoke_only"]
        assert checkpoint["experiment_protocol_sha256"] == training.sha(protocol_path)
        assert checkpoint["input_transform"] == training.INPUT_TRANSFORM
        assert report["best_checkpoint_sha256"] == training.sha(out / "best.pt")
    assert outputs["finetune"]["batch_plan_sha256"] == outputs["scratch"]["batch_plan_sha256"]
    assert outputs["finetune"]["initial_model_state_sha256"] != outputs["scratch"]["initial_model_state_sha256"]
    assert outputs["finetune"]["initialization_sha256"] == training.sha(baseline)
    assert outputs["scratch"]["initialization_sha256"] is None
    assert training.sha(baseline) == protocol["baseline"]["sha256"]
    with pytest.raises(FileExistsError):
        training.train(data, baseline, tmp_path / "scratch", protocol_path, "scratch", "cpu", True)


@pytest.mark.parametrize("mode", ["finetune", "scratch"])
def test_bad_baseline_rejected_even_for_scratch(tmp_path, mode):
    data, baseline, protocol_path, _, _ = fixture(tmp_path)
    baseline.write_bytes(baseline.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="Baseline SHA256"):
        training.train(data, baseline, tmp_path / "out", protocol_path, mode, "cpu", True)
    assert not (tmp_path / "out").exists()


def test_metadata_source_and_protocol_guard(tmp_path):
    data, baseline, protocol_path, protocol, _ = fixture(tmp_path)
    (data / "evidence-ledger.json").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="evidence-ledger"):
        training.verify_protocol(data, baseline, protocol_path, True)
    protocol["data_hashes"]["evidence-ledger.json"] = training.sha(data / "evidence-ledger.json")
    protocol["source_hashes"][training.REQUIRED_SOURCES[0]] = "wrong"
    training.write_json(protocol_path, protocol)
    with pytest.raises(ValueError, match="Source SHA256"):
        training.verify_protocol(data, baseline, protocol_path, True)
    protocol["source_hashes"][training.REQUIRED_SOURCES[0]] = training.sha(training.ROOT / training.REQUIRED_SOURCES[0])
    protocol["training"]["learning_rate"] = .002
    training.write_json(protocol_path, protocol)
    with pytest.raises(ValueError, match="learning_rate"):
        training.verify_protocol(data, baseline, protocol_path, True)


def test_quality_index_cannot_enter_training_even_if_file_hashes_are_updated(tmp_path):
    data, baseline, protocol_path, protocol, _ = fixture(tmp_path)
    q = json.loads((data / "quality-index.jsonl").read_text())
    q["segmentation_eligible"] = True
    with (data / "index.jsonl").open("a") as handle:
        handle.write("\n" + json.dumps(q))
    protocol["data_hashes"]["index.jsonl"] = training.sha(data / "index.jsonl")
    training.write_json(protocol_path, protocol)
    with pytest.raises(ValueError, match="Quality fixture leaked"):
        training.verify_protocol(data, baseline, protocol_path, True)


def test_normal_cpu_and_cuda_unavailable_never_fall_back(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="requires CUDA"):
        training.train(tmp_path, tmp_path, tmp_path / "out", tmp_path, "scratch", "cpu")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="CUDA unavailable"):
        training.train(tmp_path, tmp_path, tmp_path / "out", tmp_path, "finetune", "cuda")
    with pytest.raises(ValueError, match="smoke requires"):
        training.train(tmp_path, tmp_path, tmp_path / "out", tmp_path, "scratch", "cuda", True)
    assert not (tmp_path / "out").exists()


def test_timeout_preserves_incomplete_checkpoint_without_claiming_completion(tmp_path, monkeypatch):
    data, baseline, protocol_path, _, _ = fixture(tmp_path)
    clock = iter([0., 1801.])
    monkeypatch.setattr(training, "time", SimpleNamespace(perf_counter=lambda: next(clock, 1801.)))
    out = tmp_path / "timeout"
    report = training.train(data, baseline, out, protocol_path, "scratch", "cpu", True)
    assert report["status"] == "incomplete" and report["stop_reason"] == "time_budget"
    assert not report["training_completed"] and report["epochs_completed"] == 0
    assert report["optimizer_steps"] == 0 and not (out / "best.pt").exists()
    checkpoint = torch.load(out / "interrupted.pt", map_location="cpu", weights_only=True)
    build_model().load_state_dict(checkpoint["model_state"])
    assert report["interrupted_checkpoint_sha256"] == training.sha(out / "interrupted.pt")


def test_runtime_error_persists_incomplete_before_reraising(tmp_path, monkeypatch):
    data, baseline, protocol_path, _, _ = fixture(tmp_path)

    def fail(*args):
        raise RuntimeError("fixture augmentation failure")

    monkeypatch.setattr(training, "augment_batch", fail)
    out = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="fixture augmentation"):
        training.train(data, baseline, out, protocol_path, "finetune", "cpu", True)
    report = json.loads((out / "training.json").read_text())
    assert report["status"] == "incomplete" and report["partial_epoch"] == 1
    assert not report["training_completed"] and report["stop_reason"] == "runtime_error"
    assert (out / "interrupted.pt").exists()


def test_cli_smoke_actual_checkpoint_on_toy_pairs_only(tmp_path):
    data, baseline, protocol_path, _, _ = fixture(tmp_path)
    out = tmp_path / "cli"
    result = subprocess.run([sys.executable, str(training.ROOT / "scripts/train_thermal_observation_v2.py"),
        "--data", str(data), "--baseline", str(baseline), "--protocol", str(protocol_path),
        "--mode", "scratch", "--out", str(out), "--device", "cpu", "--smoke"],
        capture_output=True, text=True, timeout=90, check=False)
    assert result.returncode == 0, result.stderr
    report = json.loads((out / "training.json").read_text())
    assert report["smoke_only"] and not report["training_completed"]
    assert report["epochs_completed"] == 1 and report["mode"] == "scratch"
