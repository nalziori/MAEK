"""Scientific-contract tests; all files/images/checkpoints below are toy fixtures."""
from __future__ import annotations

import csv
import json
import subprocess
import sys

import numpy as np
import pytest
import torch

from maek import thermal_observation_eval as ev
from maek.thermal_observation_model import ARCHITECTURE, build_model


def settings():
    return {"min_component_area": 9, "false_alarm_min_scored_pixels": 9,
            "connectivity": 8, "score_comparator": ">", "dev_max_false_alarm_frames": 0,
            "positive_hit_fraction": .3, "rules": list(ev.RULES),
            "rule_thresholds": np.geomspace(.02, 8, 41).tolist() + ["OFF"],
            "model_thresholds": np.linspace(.05, .95, 37).tolist() + [.99, .999, "OFF"],
            "bootstrap_repeats": 2000, "bootstrap_seed": 20261110,
            "selection_rank": ["frame_hit_recall", "pixel_iou", "pixel_recall", "higher_threshold"],
            "rule_tie_preference": ev.RULES[1]}


def test_rules_use_signed_smoothing_and_measured_arrays_only():
    reference = np.zeros((3, 3), np.float32)
    current = np.array([[1, -1, 1], [-1, 0, -1], [1, -1, 1]], np.float32)
    assert ev.rule_score(reference, current, ev.RULES[0]).sum() == 8
    assert ev.rule_score(reference, current, ev.RULES[1])[1, 1] == 0
    with pytest.raises(ValueError, match="Nonfinite"):
        ev.rule_score(reference, current * np.nan, ev.RULES[0])


def test_strict_threshold_eight_connectivity_and_component_area():
    score = np.eye(9, dtype=np.float64)
    assert ev.postprocess(score, 1).sum() == 0  # Strict >, including exact ties.
    assert ev.postprocess(score, .9).sum() == 9  # Diagonal is one 8-connected component.
    score[-1, -1] = 0
    assert ev.postprocess(score, .9).sum() == 0  # Eight pixels is below min-area 9.
    assert ev.postprocess(np.ones((5, 5)), "OFF").sum() == 0
    assert ev.postprocess(np.full((3, 3), .5, np.float32), np.nextafter(.5, 0)).sum() == 9


def test_gt_ignore_only_after_component_filter_and_area_alarm_unit():
    score = np.zeros((5, 5))
    score[:3, :3] = 1
    prediction = ev.postprocess(score, .5)
    target = np.zeros((5, 5), np.uint8)
    target[0, 0] = 255
    result = ev.score_frame(target, prediction)
    assert prediction.sum() == 9 and result["fp"] == 8 and result["false_alarm"] == 0
    target[0, 0] = 0
    assert ev.score_frame(target, prediction)["false_alarm"] == 1
    target[:] = 255
    result = ev.score_frame(target, prediction)
    assert result["all_ignored"] == 1 and result["no_change_frame"] == 0


def test_positive_hit_coverage_and_nonpositive_physical_change_labels():
    target = np.zeros((4, 4), np.uint8)
    target.ravel()[:10] = 1
    prediction = np.zeros((4, 4), bool)
    prediction.ravel()[:3] = True
    result = ev.score_frame(target, prediction)
    assert result["hit"] == 1 and result["tp"] == 3 and result["no_change_frame"] == 0
    prediction.ravel()[2] = False
    assert ev.score_frame(target, prediction)["hit"] == 0
    target[:] = 0
    assert ev.score_frame(target, prediction)["no_change_frame"] == 1


def candidate(method=ev.RULES[0], threshold=.2, fa=0, recall=.8, iou=.6):
    return {"method": method, "threshold": threshold, "false_alarm": fa,
            "positive_frame": 5, "no_change_frame": 4, "frame_hit_recall": recall,
            "pixel_iou": iou, "pixel_recall": .9}


def test_gate_ranking_smooth_tie_preference_and_explicit_off():
    bad = candidate(fa=1, recall=1)
    raw, smooth = candidate(), candidate(method=ev.RULES[1])
    assert ev.select_candidate([bad, raw, smooth])["method"] == ev.RULES[1]
    higher = candidate(threshold=.3)
    assert ev.select_candidate([raw, higher])["threshold"] == .3
    off = candidate(threshold="OFF", recall=0, iou=0)
    chosen = ev.select_candidate([bad, off])
    assert chosen["off_selected"] and chosen["finite_candidates_passing_gate"] == 0


def test_group_bootstrap_pairs_whole_scenes_and_checks_identity():
    before, after = [], []
    for group in ("a", "b"):
        for j in range(3):
            common = {"sample_id": f"{group}{j}", "base_scene_id": group,
                      "positive_frame": 1, "no_change_frame": 0, "fp": 0}
            before.append({**common, "tp": 0, "fn": 10, "hit": 0})
            after.append({**common, "tp": 10, "fn": 0, "hit": 1})
    result = ev.paired_group_bootstrap(before, after, repeats=2000)
    assert result["groups"] == 2
    assert result["pixel_iou"]["ci95"] == [1., 1.]
    assert result["frame_hit_recall"]["difference"] == 1
    after[0]["sample_id"] = "wrong"
    with pytest.raises(ValueError, match="Unaligned"):
        ev.paired_group_bootstrap(before, after)
    assert ev.wilson95(0, 32)[1] == pytest.approx(.1071791982550706)


def fixture_run(root):
    """Create toy-only bound dataset and a real, randomly initialized torch checkpoint."""
    data, run = root / "toy-data", root / "toy-run"
    data.mkdir(); run.mkdir(); (data / "samples").mkdir()
    rows = []
    for split in ("dev", "test", "stress"):
        for group in range(2):
            for changed in (False, True):
                sample_id = f"{split}_{group}_{changed}"
                reference = np.full((16, 16), group, np.float32)
                current, target = reference.copy(), np.zeros((16, 16), np.uint8)
                if changed:
                    current[5:9, 5:9] += 1
                    target[5:9, 5:9] = 1
                target[0, 0] = 255
                path = data / "samples" / f"{sample_id}.npz"
                np.savez(path, reference_c=reference, current_c=current, target=target,
                         clean_reference_c=np.full((16, 16), np.nan),
                         clean_current_c=np.full((16, 16), np.nan), noise_sigma_c=np.nan)
                rows.append({"sample_id": sample_id, "base_scene_id": f"{split}_{group}",
                             "split": split, "mechanism": "reflection" if changed else "stable_repeat",
                             "relative_path": f"samples/{sample_id}.npz", "sha256": ev.sha(path)})
    ev.write_json(data / "protocol.json", {"fixture_only": True})
    ev.write_json(data / "manifest.json", {"training_eligible_scope": ev.TRAINING_SCOPE, "fixture_only": True})
    (data / "index.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    ev.write_json(data / "validation.json", {"status": "passed", "fixture_only": True,
        "training_eligible_scope": ev.TRAINING_SCOPE,
        **{key: ev.sha(data / name) for key, name in (("manifest_sha256", "manifest.json"),
            ("protocol_sha256", "protocol.json"), ("index_sha256", "index.jsonl"))}})
    hashes = {name: ev.sha(data / name) for name in ("manifest.json", "protocol.json", "index.jsonl", "validation.json")}
    protocol = root / "comparison_protocol.json"
    ev.write_json(protocol, {"scope": ev.TRAINING_SCOPE, "data_hashes": hashes,
                             "training": {"epochs": 30, "device": "cuda"}, "evaluate": settings()})
    torch.manual_seed(123)
    model = build_model()
    torch.save({"model_state": model.state_dict(), "scope": ev.TRAINING_SCOPE,
                "architecture": ARCHITECTURE, "smoke_only": True,
                "comparison_protocol_sha256": ev.sha(protocol)}, run / "best.pt")
    ev.write_json(run / "training.json", {"status": "smoke_passed", "training_completed": False,
        "smoke_only": True, "scope": ev.TRAINING_SCOPE, "fixture_only": True,
        "epochs_completed": 0, "data_hashes": hashes, "comparison_protocol": {"sha256": ev.sha(protocol)},
        "source_hashes": {"maek/thermal_observation_model.py": ev.sha(ev.ROOT / "maek/thermal_observation_model.py")},
        "best_checkpoint_sha256": ev.sha(run / "best.pt")})
    return data, run, protocol


def test_real_checkpoint_toy_e2e_freezes_before_holdout_and_recomputable_counts(tmp_path, monkeypatch):
    data, run, protocol = fixture_run(tmp_path)
    out = tmp_path / "comparison"
    original_loader = ev.load_frames
    loaded = []

    def guarded_loader(root, split):
        if split != "dev":
            assert (out / "selected.json").is_file()
            chosen = json.loads((out / "selected.json").read_text())
            assert chosen["selection_split"] == "dev"
        loaded.append(split)
        return original_loader(root, split)

    monkeypatch.setattr(ev, "load_frames", guarded_loader)
    result = ev.run_comparison(data, run, out, protocol, smoke=True)
    assert loaded == ["dev", "test", "stress"]
    assert result["status"] == "completed" and result["valid_comparison"] is False
    assert not result["improvement_supported"]
    assert len(list(csv.DictReader((out / "summary.csv").open()))) == 6
    assert len(list(csv.DictReader((out / "per-frame.csv").open()))) == 24
    assert len(list(csv.DictReader((out / "dev-sweep.csv").open()))) == 124
    for split in ("dev", "test", "stress"):
        with np.load(out / f"predictions-{split}.npz") as z:
            for method in ("rule", "model"):
                counts = [ev.score_frame(t, p.astype(bool)) for t, p in zip(z["target"], z[method])]
                for key in ("tp", "fp", "fn", "hit", "false_alarm", "all_ignored"):
                    assert sum(c[key] for c in counts) == result["results"][split][method][key]
    assert result["selected_json_sha256"] == ev.sha(out / "selected.json")
    with pytest.raises(ValueError, match="fresh"):
        ev.run_comparison(data, run, out, protocol, smoke=True)


def test_incomplete_and_protocol_tampered_checkpoint_rejected_before_data_load(tmp_path, monkeypatch):
    data, run, protocol = fixture_run(tmp_path)
    monkeypatch.setattr(ev, "load_frames", lambda *args: pytest.fail("Must reject before reading frames"))
    with pytest.raises(ValueError, match="Full completed"):
        ev.run_comparison(data, run, tmp_path / "no-full-run", protocol)
    checkpoint = torch.load(run / "best.pt", weights_only=True)
    checkpoint["comparison_protocol_sha256"] = "wrong"
    torch.save(checkpoint, run / "best.pt")
    training = json.loads((run / "training.json").read_text())
    training["best_checkpoint_sha256"] = ev.sha(run / "best.pt")
    ev.write_json(run / "training.json", training)
    with pytest.raises(ValueError, match="Checkpoint protocol"):
        ev.run_comparison(data, run, tmp_path / "bad-bind", protocol, smoke=True)
    checkpoint["comparison_protocol_sha256"] = ev.sha(protocol)
    checkpoint["architecture"] = "wrong architecture"
    torch.save(checkpoint, run / "best.pt")
    training["best_checkpoint_sha256"] = ev.sha(run / "best.pt")
    ev.write_json(run / "training.json", training)
    with pytest.raises(ValueError, match="Checkpoint architecture"):
        ev.run_comparison(data, run, tmp_path / "bad-architecture", protocol, smoke=True)


def test_cli_smoke_is_explicit_and_only_uses_toy_files(tmp_path):
    data, run, protocol = fixture_run(tmp_path)
    out = tmp_path / "cli-smoke"
    command = [sys.executable, str(ev.ROOT / "scripts/compare_thermal_observation.py"),
               "--data", str(data), "--run", str(run), "--out", str(out), "--protocol", str(protocol),
               "--device", "cpu", "--smoke"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=90)
    assert completed.returncode == 0, completed.stderr
    result = json.loads((out / "metrics.json").read_text())
    assert result["smoke_only"] and not result["valid_comparison"]
