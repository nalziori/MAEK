"""Comparison contract tests using toy arrays and mocked model inference only."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from maek import thermal_v2_comparison as comparison


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def frame(split, marker):
    positive = marker in (1, 3)
    reference = np.full((4, 4), marker, np.float32)
    return {"sample_id": f"{split}-{marker}", "base_scene_id": f"{split}-scene-{marker}",
            "reference": reference, "current": reference + float(positive),
            "target": np.full((4, 4), int(positive), np.uint8),
            "mechanism": "reflection" if positive else "stable_repeat",
            "input_sha256": f"fixture-{split}-{marker}"}


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    pytest.importorskip("cv2")
    data, training, out = (tmp_path / name for name in ("data", "training", "comparison"))
    data.mkdir()
    training.mkdir()
    baseline = tmp_path / "baseline.pt"
    baseline.write_bytes(b"baseline fixture, never loaded as model weights")
    repo = Path(comparison.__file__).resolve().parents[1]
    source_name = "maek/thermal_v2_comparison.py"
    source_hashes = {source_name: comparison.sha(repo / source_name)}
    quality = []
    for split in ("dev", "test", "stress"):
        for mechanism, marker in (("misregistration", 3), ("calibration_drift", 1)):
            path = data / f"{split}-{mechanism}.npz"
            np.savez(path, reference_c=np.full((4, 4), marker, np.float32),
                     current_c=np.full((4, 4), marker, np.float32),
                     target=np.full((4, 4), 255, np.uint8))
            quality.append({"sample_id": path.stem, "split": split, "mechanism": mechanism,
                            "relative_path": path.name, "sha256": comparison.sha(path)})
    (data / "quality-index.jsonl").write_text(
        "\n".join(json.dumps(row) for row in quality), encoding="utf-8")
    protocol = {"version": 2, "scope": comparison.TRAINING_SCOPE, "shape": [4, 4],
                "baseline": {"sha256": comparison.sha(baseline), "original_threshold": .825},
                "data_hashes": {"quality-index.jsonl": comparison.sha(data / "quality-index.jsonl")},
                "source_hashes": source_hashes, "registration_policy": {"fixture": True},
                "rule": {"method": "absolute_difference"},
                "acceptance": {"min_valid_coverage": .9, "min_misregistration_rejection": .95},
                "evaluate": {"dev_max_false_alarm_frames": 0, "min_component_area": 9,
                             "positive_hit_fraction": .3, "false_alarm_min_scored_pixels": 9,
                             "model_thresholds": [.5, .85, "OFF"],
                             "rule_thresholds": [.5, "OFF"],
                             "bootstrap_repeats": 20, "bootstrap_seed": 123}}
    protocol_path = tmp_path / "experiment.json"
    write(protocol_path, protocol)
    reports, checkpoints = {}, {}
    for mode in ("finetune", "scratch"):
        run = training / mode
        run.mkdir()
        (run / "best.pt").write_bytes(mode.encode())
        reports[mode] = {"mode": mode, "status": "completed", "scope": comparison.TRAINING_SCOPE,
                         "experiment_protocol_sha256": comparison.sha(protocol_path),
                         "baseline_sha256": comparison.sha(baseline),
                         "data_hashes": protocol["data_hashes"], "source_hashes": source_hashes,
                         "best_checkpoint_sha256": comparison.sha(run / "best.pt"),
                         "training_completed": True, "smoke_only": False, "epochs_completed": 30,
                         "device": "cuda", "gpu": "fixture GPU", "versions": {"torch": "fixture"},
                         "optimizer_steps": 900, "batch_plan_sha256": "shared-fixture-plan"}
        write(run / "training.json", reports[mode])
        checkpoints[mode] = {"mode": mode, "experiment_protocol_sha256": comparison.sha(protocol_path),
                             "smoke_only": False}
    events, predict_calls, gate_calls = [], [], []
    frames = {split: [frame(split, marker) for marker in range(1, 5)]
              for split in ("dev", "test", "stress")}

    def load_frames(_data, split):
        events.append(("load", split))
        assert split != "train"
        if split != "dev":
            assert (out / "selected.json").exists(), "Holdout opened before selection freeze"
        return frames[split]

    def load_model(path, _device):
        mode = "baseline" if Path(path) == baseline else Path(path).parent.name

        def predict(reference, current):
            marker = int(reference[0, 0])
            assert marker <= 2, "Rejected image reached model inference"
            predict_calls.append((mode, marker))
            is_dev = not any(event == ("load", "test") for event in events)
            score = {"baseline": .8, "finetune": .9 if is_dev else .1,
                     "scratch": .6 if is_dev else .99}[mode]
            return np.full(reference.shape, score if np.any(current != reference) else 0, np.float32)

        return predict, checkpoints.get(mode, {})

    def gate(reference, current, policy):
        assert isinstance(reference, np.ndarray) and isinstance(current, np.ndarray)
        assert policy == protocol["registration_policy"]
        gate_calls.append(int(reference[0, 0]))
        return {"can_infer": bool(reference[0, 0] <= 2), "assessment_status": "fixture"}

    original_sweep = comparison.sweep

    def sweep(selected_frames, scores, method, grid, settings):
        assert all(f["sample_id"].startswith("dev-") for f in selected_frames)
        assert not any(event == ("load", "test") for event in events)
        events.append(("sweep", method))
        return original_sweep(selected_frames, scores, method, grid, settings)

    monkeypatch.setattr(comparison, "load_frames", load_frames)
    monkeypatch.setattr(comparison, "load_model", load_model)
    monkeypatch.setattr(comparison, "assess_registration", gate)
    monkeypatch.setattr(comparison, "sweep", sweep)

    def run(smoke=False):
        return comparison.run_comparison(data, baseline, training, out, protocol_path,
                                         device="cpu", smoke=smoke)

    return SimpleNamespace(**locals())


def test_common_gate_abstains_for_every_method_and_retains_whole_input_denominator(experiment):
    e = experiment
    result = e.run()
    assert len(e.gate_calls) == 12 + 6  # Once per input, plus separate quality fixtures.
    for mode in comparison.MODELS:
        assert [marker for called_mode, marker in e.predict_calls if called_mode == mode] == [1, 2] * 3
    for split in ("dev", "test", "stress"):
        for method in (*comparison.MODELS, "rule", "baseline_original_point"):
            scored = result["results"][split]["methods"][method]
            whole = scored["whole_input"]
            assert scored["frames"] == 2 and scored["no_change_frame"] == 1
            assert whole["input_frames"] == 4 and whole["accepted_frames"] == 2
            assert whole["coverage"] == .5 and whole["abstained_frames"] == 2
            assert whole["all_positive_frames"] == 2 and whole["rejected_positive_frames"] == 1
            assert whole["rejected_are_negative"] is False
            assert whole["end_to_end_frame_hit_recall"] == scored["hit"] / 2
        with np.load(e.out / f"predictions-{split}.npz", allow_pickle=False) as predictions:
            assert predictions["sample_ids"].tolist() == [f"{split}-1", f"{split}-2"]
    assert result["common_quality_gate"] and not result["improvement_supported"]
    assert result["registration_summary"]["test"]["misregistration_rejected"] == 1


def test_dev_thresholds_and_challenger_are_frozen_before_holdout(experiment):
    e = experiment
    result = e.run()
    selected = json.loads((e.out / "selected.json").read_text())
    assert selected["selected"]["baseline"]["threshold"] == .5
    assert selected["selected"]["finetune"]["threshold"] == .85
    assert selected["selected"]["scratch"]["threshold"] == .5
    assert selected["dev_selected_challenger"] == "finetune"
    assert result["dev_selected_challenger"] == "finetune"  # Scratch wins holdout, cannot replace it.
    assert result["results"]["test"]["methods"]["finetune"]["hit"] == 0
    assert result["results"]["test"]["methods"]["scratch"]["hit"] == 1
    assert result["results"]["test"]["methods"]["baseline_original_point"]["hit"] == 0
    assert result["selected_json_sha256"] == comparison.sha(e.out / "selected.json")
    assert not result["holdout_used_for_selection"]
    assert [item for item in e.events if item[0] == "sweep"] == [
        ("sweep", method) for method in (*comparison.MODELS, "rule")]


@pytest.mark.parametrize("markers", [[], [1, 3], [2, 4], [3, 4]])
def test_missing_accepted_dev_support_selects_off_and_no_challenger(experiment, markers):
    e = experiment
    e.frames["dev"] = [frame("dev", marker) for marker in markers]
    result = e.run()
    selected = json.loads((e.out / "selected.json").read_text())["selected"]
    assert all(row["threshold"] == "OFF" and not row["selection_available"] for row in selected.values())
    assert result["dev_selected_challenger"] is None and not result["improvement_supported"]


def test_smoke_results_cannot_establish_valid_comparison(experiment):
    result = experiment.run(smoke=True)
    assert result["smoke_only"] and not result["valid_comparison"]
    assert not result["improvement_supported"]


def test_off_wins_when_every_finite_threshold_has_false_alarms():
    common = {"method": "baseline", "positive_frame": 2, "no_change_frame": 2,
              "frame_hit_recall": 1., "pixel_iou": .8, "pixel_recall": 1.}
    finite = [{**common, "threshold": threshold, "false_alarm": 1} for threshold in (.5, .85)]
    off = {**common, "threshold": "OFF", "false_alarm": 0,
           "frame_hit_recall": 0., "pixel_iou": 0., "pixel_recall": 0.}
    chosen = comparison.choose_threshold([*finite, off])
    assert chosen["threshold"] == "OFF" and chosen["off_selected"]
    assert chosen["selection_available"]  # Support exists; no finite operating point passed.


def test_changed_selection_is_detected_before_next_holdout(experiment, monkeypatch):
    e = experiment
    original_load = comparison.load_frames

    def load_and_corrupt_selection(data, split):
        frames = original_load(data, split)
        if split == "test":
            selected = json.loads((e.out / "selected.json").read_text())
            selected["selected"]["baseline"]["threshold"] = .99
            write(e.out / "selected.json", selected)
        return frames

    monkeypatch.setattr(comparison, "load_frames", load_and_corrupt_selection)
    with pytest.raises(ValueError, match="Selection mutated"):
        e.run()
    assert ("load", "stress") not in e.events


@pytest.mark.parametrize("markers", [[], [3, 4]])
def test_empty_or_rejected_holdout_cannot_claim_improvement(experiment, markers):
    e = experiment
    e.frames["test"] = [frame("test", marker) for marker in markers]
    result = e.run()
    for summary in result["results"]["test"]["methods"].values():
        assert summary["frames"] == 0 and summary["no_change_frame"] == 0
        assert summary["frame_hit_recall"] is None
        assert summary["whole_input"]["coverage"] == (0 if markers else None)
        assert summary["whole_input"]["end_to_end_frame_hit_recall"] == (0 if markers else None)
        assert summary["whole_input"]["abstained_frames"] == len(markers)
    assert not result["improvement_supported"]


def test_existing_output_is_preserved(experiment):
    e = experiment
    e.out.mkdir()
    sentinel = e.out / "preserve.txt"
    sentinel.write_text("existing result")
    with pytest.raises(ValueError, match="fresh comparison"):
        e.run()
    assert sentinel.read_text() == "existing result" and not e.events


@pytest.mark.parametrize(("key", "value", "message"), [
    ("mode", "scratch", "mode/protocol"),
    ("experiment_protocol_sha256", "wrong", "mode/protocol"),
    ("baseline_sha256", "wrong", "baseline"),
    ("data_hashes", {}, "data"),
    ("best_checkpoint_sha256", "wrong", "checkpoint hash"),
    ("training_completed", False, "complete"),
    ("smoke_only", True, "complete"),
    ("epochs_completed", 29, "complete"),
    ("device", "cpu", "CUDA"),
    ("gpu", "other", "Unequal"),
    ("versions", {}, "Unequal"),
    ("optimizer_steps", 899, "Unequal"),
    ("batch_plan_sha256", "other", "Unequal"),
])
def test_training_report_guards_fail_before_opening_frames(experiment, key, value, message):
    e = experiment
    e.reports["finetune"][key] = value
    write(e.training / "finetune" / "training.json", e.reports["finetune"])
    with pytest.raises(ValueError, match=message):
        e.run()
    assert not e.events


@pytest.mark.parametrize(("key", "value"), [
    ("mode", "scratch"), ("experiment_protocol_sha256", "wrong"), ("smoke_only", True),
])
def test_checkpoint_mode_protocol_and_smoke_guards(experiment, key, value):
    e = experiment
    e.checkpoints["finetune"][key] = value
    with pytest.raises(ValueError, match="Checkpoint experiment|Smoke checkpoint"):
        e.run()
    assert not e.events


def test_baseline_hash_guard_precedes_any_inference(experiment):
    e = experiment
    e.baseline.write_bytes(b"changed baseline")
    with pytest.raises(ValueError, match="Baseline hash mismatch"):
        e.run()
    assert not e.predict_calls and not e.events


@pytest.mark.parametrize(("key", "value"), [
    ("status", "incomplete"), ("scope", "unrelated_scope"), ("source_hashes", {}),
])
def test_incomplete_or_missing_training_provenance_is_rejected(experiment, key, value):
    e = experiment
    e.reports["finetune"][key] = value
    write(e.training / "finetune" / "training.json", e.reports["finetune"])
    with pytest.raises(ValueError):
        e.run()
    assert not e.events
