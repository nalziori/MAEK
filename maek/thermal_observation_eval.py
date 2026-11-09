"""Frozen-dev comparison of paired thermal change observers, never defect inference."""
from __future__ import annotations

import csv
import hashlib
import importlib
import io
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from maek.thermal_observation_data import (
    TRAINING_SCOPE,
    ThermalObservationDataset,
    encode_pair,
)

RULES = ("absolute_difference", "smoothed_signed_difference_3x3")
COUNT_KEYS = ("tp", "fp", "fn", "tn", "positive_frame", "hit", "no_change_frame",
              "false_alarm", "all_ignored", "stable_repeat")
ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def write_csv(path, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        writer.writeheader()
        writer.writerows(rows)


def rule_score(reference, current, method):
    """Measured arrays only; no target, noise metadata, clean image or pipe mask."""
    reference, current = np.asarray(reference), np.asarray(current)
    require(reference.ndim == 2 and reference.shape == current.shape,
            "Expected matching 2D measured arrays")
    require(np.isfinite(reference).all() and np.isfinite(current).all(), "Nonfinite measured arrays")
    difference = current.astype(np.float64) - reference.astype(np.float64)
    if method == "absolute_difference":
        return np.abs(difference)
    require(method == "smoothed_signed_difference_3x3", "Unknown rule")
    h, w = difference.shape
    padded = np.pad(difference, 1, mode="edge")
    smoothed = sum(padded[y:y + h, x:x + w] for y in range(3) for x in range(3)) / 9
    return np.abs(smoothed)


def postprocess(score, threshold, min_area=9):
    """Strict score > threshold, then 8-connected area filter without GT access."""
    import cv2

    score = np.asarray(score)
    require(score.ndim == 2 and np.isfinite(score).all(), "Invalid score map")
    require(isinstance(min_area, int) and min_area > 0, "Invalid component area")
    if threshold == "OFF":
        return np.zeros(score.shape, dtype=bool)
    require(isinstance(threshold, (int, float)) and math.isfinite(threshold), "Invalid threshold")
    # Preserve the frozen JSON threshold rather than weak-scalar float32 rounding.
    binary = (score.astype(np.float64) > float(threshold)).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    keep = stats[:, cv2.CC_STAT_AREA] >= min_area
    keep[0] = False
    return keep[labels]


def score_frame(target, prediction, *, hit_fraction=.3, fa_min_pixels=9):
    target, prediction = np.asarray(target), np.asarray(prediction)
    require(target.shape == prediction.shape and target.ndim == 2, "Mismatched scoring shapes")
    require(np.isin(target, (0, 1, 255)).all(), "Invalid target values")
    require(prediction.dtype == bool, "Prediction must be boolean")
    require(0 < hit_fraction <= 1 and fa_min_pixels > 0, "Invalid scoring parameters")
    positive, stable = target == 1, target == 0
    tp = int(np.sum(prediction & positive)); fp = int(np.sum(prediction & stable))
    n_positive, n_stable = int(positive.sum()), int(stable.sum())
    no_change = n_positive == 0 and n_stable > 0
    return {"tp": tp, "fp": fp, "fn": n_positive - tp, "tn": n_stable - fp,
            "positive_frame": int(n_positive > 0),
            "hit": int(n_positive > 0 and tp / n_positive >= hit_fraction),
            "no_change_frame": int(no_change),
            "false_alarm": int(no_change and fp >= fa_min_pixels),
            "all_ignored": int(n_positive + n_stable == 0)}


def wilson95(successes, count):
    require(0 <= successes <= count, "Invalid Wilson counts")
    if count == 0:
        return None
    z = 1.959963984540054
    p = successes / count
    denominator = 1 + z * z / count
    center = (p + z * z / (2 * count)) / denominator
    half = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count * count)) / denominator
    return [max(0., center - half), min(1., center + half)]


def summarize(records):
    totals = {key: sum(int(row.get(key, 0)) for row in records) for key in COUNT_KEYS}
    tp, fp, fn = (totals[key] for key in ("tp", "fp", "fn"))
    total_positive, total_normal = totals["positive_frame"], totals["no_change_frame"]
    stable = [r for r in records if r.get("stable_repeat") and r["no_change_frame"]]
    return {**totals, "frames": len(records),
            "pixel_iou": tp / (tp + fp + fn) if tp + fp + fn else None,
            "pixel_precision": tp / (tp + fp) if tp + fp else None,
            "pixel_recall": tp / (tp + fn) if tp + fn else None,
            "frame_hit_recall": totals["hit"] / total_positive if total_positive else None,
            "false_alarm_rate": totals["false_alarm"] / total_normal if total_normal else None,
            "false_alarm_wilson95_nominal": wilson95(totals["false_alarm"], total_normal),
            "false_alarm_sample_ids": [r["sample_id"] for r in records if r["false_alarm"]],
            "stable_repeat_no_change_frames": len(stable),
            "stable_repeat_false_alarms": sum(r["false_alarm"] for r in stable),
            "stable_repeat_false_alarm_wilson95_nominal": wilson95(sum(r["false_alarm"] for r in stable), len(stable))}


def evaluate_scores(frames, scores, threshold, settings):
    require(len(frames) == len(scores), "Frame/score length mismatch")
    records, masks = [], []
    for frame, score in zip(frames, scores):
        prediction = postprocess(score, threshold, settings["min_component_area"])
        counts = score_frame(frame["target"], prediction, hit_fraction=settings["positive_hit_fraction"],
                             fa_min_pixels=settings["false_alarm_min_scored_pixels"])
        records.append({"sample_id": frame["sample_id"], "base_scene_id": frame["base_scene_id"],
                        "mechanism": frame["mechanism"], "input_sha256": frame["input_sha256"],
                        **counts, "stable_repeat": int(frame["mechanism"] == "stable_repeat")})
        masks.append(prediction)
    return summarize(records), records, masks


def selection_rank(candidate):
    def number(key):
        return candidate[key] if candidate[key] is not None else -1.
    threshold = math.inf if candidate["threshold"] == "OFF" else candidate["threshold"]
    return (number("frame_hit_recall"), number("pixel_iou"), number("pixel_recall"), threshold,
            int(candidate["method"] == "smoothed_signed_difference_3x3"))


def select_candidate(candidates, max_false_alarm_frames=0):
    require(bool(candidates), "Empty dev sweep")
    require(all(c["positive_frame"] > 0 and c["no_change_frame"] > 0 for c in candidates),
            "Dev must contain both positive and scored no-change frames")
    eligible = [c for c in candidates if c["false_alarm"] <= max_false_alarm_frames]
    require(bool(eligible), "No feasible candidate; OFF fallback missing")
    chosen = dict(max(eligible, key=selection_rank))
    chosen["off_selected"] = chosen["threshold"] == "OFF"
    chosen["finite_candidates_passing_gate"] = sum(c["threshold"] != "OFF" for c in eligible)
    return chosen


def sweep(frames, scores, method, thresholds, settings):
    rows = []
    require("OFF" in thresholds, "Threshold grid must include OFF")
    for threshold in thresholds:
        summary, _, _ = evaluate_scores(frames, scores, threshold, settings)
        rows.append({"method": method, "threshold": threshold,
                     **{k: summary[k] for k in ("tp", "fp", "fn", "tn", "positive_frame", "hit", "no_change_frame", "false_alarm", "all_ignored", "frame_hit_recall", "pixel_iou", "pixel_recall")},
                     "eligible": summary["false_alarm"] <= settings["dev_max_false_alarm_frames"]})
    return rows


def paired_group_bootstrap(rule_records, model_records, repeats=2000, seed=20261110):
    """Paired resampling of whole parent scenes, preserving all frame variants."""
    require(repeats > 0, "Bootstrap repetitions must be positive")
    require(len(rule_records) == len(model_records) and len(rule_records) > 0, "Invalid paired records")
    for before, after in zip(rule_records, model_records):
        require((before["sample_id"], before["base_scene_id"], before["positive_frame"], before["no_change_frame"])
                == (after["sample_id"], after["base_scene_id"], after["positive_frame"], after["no_change_frame"]),
                "Unaligned paired sample identity or target support")
        require(before["tp"] + before["fn"] == after["tp"] + after["fn"], "Unaligned GT pixel count")
    groups = sorted({r["base_scene_id"] for r in rule_records})
    group_index = {name: i for i, name in enumerate(groups)}
    arrays = []
    for records in (rule_records, model_records):
        values = np.zeros((len(groups), 5), dtype=np.float64)
        for row in records:
            values[group_index[row["base_scene_id"]]] += [row[k] for k in ("tp", "fp", "fn", "hit", "positive_frame")]
        arrays.append(values)
    draws = np.random.default_rng(seed).integers(0, len(groups), size=(repeats, len(groups)))
    totals = [array[draws].sum(axis=1) for array in arrays]

    def ratio(values, metric):
        numerator = values[..., 0] if metric == "pixel_iou" else values[..., 3]
        denominator = values[..., :3].sum(axis=-1) if metric == "pixel_iou" else values[..., 4]
        return np.divide(numerator, denominator, out=np.full_like(numerator, np.nan, dtype=float), where=denominator > 0)

    result = {"unit": "base_scene_id", "groups": len(groups), "repeats": repeats, "seed": seed, "direction": "model minus selected rule"}
    for metric in ("pixel_iou", "frame_hit_recall"):
        differences = ratio(totals[1], metric) - ratio(totals[0], metric)
        finite = differences[np.isfinite(differences)]
        point = float(ratio(arrays[1].sum(axis=0), metric) - ratio(arrays[0].sum(axis=0), metric))
        result[metric] = {"difference": point if math.isfinite(point) else None,
                          "ci95": np.quantile(finite, [.025, .975]).tolist() if len(finite) else None,
                          "valid_replicates": len(finite)}
    return result


def load_frames(data, split):
    """The dataset constructor reads metadata only; this opens only the requested split."""
    dataset = ThermalObservationDataset(data, split)
    frames = []
    for row in dataset._rows:
        payload = dataset._path(row["relative_path"]).read_bytes()
        require(hashlib.sha256(payload).hexdigest() == row["sha256"], "Sample SHA256 mismatch")
        with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
            reference, current, target = (archive[name] for name in ("reference_c", "current_c", "target"))
        require(reference.dtype == current.dtype == np.float32, "Measured input dtype must be float32")
        require(reference.ndim == 2 and reference.shape == current.shape == target.shape, "Invalid sample shape")
        require(target.dtype == np.uint8 and np.isin(target, (0, 1, 255)).all(), "Invalid target")
        require(np.isfinite(reference).all() and np.isfinite(current).all(), "Nonfinite measured input")
        frames.append({"sample_id": row["sample_id"], "base_scene_id": row["base_scene_id"],
                       "mechanism": row["mechanism"], "reference": reference, "current": current,
                       "target": target, "input_sha256": row["sha256"]})
    return frames


def load_predictor(run, device, protocol_hash, smoke):
    import torch

    model_source = importlib.import_module("maek.thermal_observation_model")
    run = Path(run)
    training = json.loads((run / "training.json").read_text(encoding="utf-8"))
    if not smoke:
        require(training.get("status") == "completed" and training.get("training_completed") is True,
                "Full completed training required; use --smoke only for an invalid fixture comparison")
        require(training.get("smoke_only") is False, "Smoke checkpoint cannot establish a valid comparison")
    require(training.get("scope") == TRAINING_SCOPE, "Training scope mismatch")
    require(training.get("comparison_protocol", {}).get("sha256") == protocol_hash, "Training comparison protocol mismatch")
    weights = run / "best.pt"
    require(training.get("best_checkpoint_sha256") == sha(weights), "Checkpoint hash mismatch")
    for name, digest in training.get("source_hashes", {}).items():
        require(sha(ROOT / name) == digest, f"Training source hash mismatch: {name}")
    require(bool(training.get("source_hashes")), "Missing training source provenance")
    if device == "cuda":
        require(torch.cuda.is_available(), "CUDA requested but unavailable")
    else:
        require(device == "cpu", "Device must be cpu or cuda")
        torch.set_num_threads(1)
    checkpoint = torch.load(weights, map_location="cpu", weights_only=True)
    require(checkpoint.get("comparison_protocol_sha256") == protocol_hash, "Checkpoint protocol mismatch")
    require(checkpoint.get("scope") == TRAINING_SCOPE, "Checkpoint scope mismatch")
    require(checkpoint.get("architecture") == model_source.ARCHITECTURE,
            "Checkpoint architecture mismatch")
    require(smoke or checkpoint.get("smoke_only") is False, "Smoke checkpoint not allowed")
    model = model_source.build_model()
    model.load_state_dict(checkpoint["model_state"], strict=True)
    model = model.to(device).eval()

    def predict(reference, current):
        inputs = torch.from_numpy(encode_pair(reference, current)[None]).to(device)
        with torch.inference_mode():
            logits = model(inputs)
            require(tuple(logits.shape) == (1, 2, *reference.shape), "Unexpected model output shape")
            require(bool(torch.isfinite(logits).all()), "Nonfinite logits")
            return torch.softmax(logits, dim=1)[0, 1].cpu().numpy()

    return predict, training, str(Path(model_source.__file__).resolve()), str(torch.__version__)


def check_protocol(protocol, data):
    require(protocol["scope"] == TRAINING_SCOPE, "Comparison protocol scope mismatch")
    required_data = {"manifest.json", "index.jsonl", "protocol.json", "validation.json"}
    require(set(protocol["data_hashes"]) == required_data, "Incomplete protocol data binding")
    for name, digest in protocol["data_hashes"].items():
        require(sha(Path(data) / name) == digest, f"Protocol data hash mismatch: {name}")
    settings = protocol["evaluate"]
    require(settings["score_comparator"] == ">" and settings["connectivity"] == 8,
            "Comparator/connectivity contract mismatch")
    require(settings["min_component_area"] == 9 and settings["false_alarm_min_scored_pixels"] == 9,
            "Area/alarm unit contract mismatch")
    require(settings["dev_max_false_alarm_frames"] == 0 and settings["positive_hit_fraction"] == .3,
            "FA/hit contract mismatch")
    require(tuple(settings["rules"]) == RULES, "Unexpected rule candidates")
    require(settings["rule_tie_preference"] == RULES[1], "Unexpected rule tie preference")
    require(settings["selection_rank"] == ["frame_hit_recall", "pixel_iou", "pixel_recall", "higher_threshold"], "Unexpected selection rank")
    for key in ("rule_thresholds", "model_thresholds"):
        values = settings[key]
        require(values.count("OFF") == 1 and all(v == "OFF" or isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in values), "Invalid threshold grid")
        require(len(values) == len(set(values)), "Duplicate threshold candidates")
    return settings


def run_comparison(data, run, out, protocol_path, *, device="cpu", smoke=False):
    import cv2

    data, run, out, protocol_path = map(Path, (data, run, out, protocol_path))
    require(not out.exists(), "Use a fresh output directory; never overwrite an evaluated comparison")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    settings = check_protocol(protocol, data)
    protocol_hash = sha(protocol_path)
    predict, training, model_source, torch_version = load_predictor(run, device, protocol_hash, smoke)
    require(training.get("data_hashes") == protocol["data_hashes"], "Training and comparison data provenance mismatch")
    if not smoke:
        require(training.get("epochs_completed") == protocol["training"]["epochs"] == 30,
                "Frozen 30-epoch training has not completed")
        require(training.get("device") == protocol["training"]["device"] == "cuda",
                "Completed CUDA training is required for the frozen comparison")
        require(training.get("holdout_arrays_loaded") is False
                and training.get("data_splits_loaded") == ["train", "dev"], "Training holdout separation not established")
    cv2.setNumThreads(1)
    sources = [Path(__file__), Path(__file__).with_name("thermal_observation_data.py"), Path(model_source), ROOT / "scripts/compare_thermal_observation.py"]
    provenance = {"comparison_protocol_sha256": protocol_hash, "data_hashes": protocol["data_hashes"],
                  "checkpoint_sha256": sha(run / "best.pt"), "training_json_sha256": sha(run / "training.json"),
                  "source_hashes": {str(path.resolve()): sha(path) for path in sources},
                  "environment": {"numpy": np.__version__, "torch": torch_version, "opencv": cv2.__version__, "device": device}}
    out.mkdir(parents=True)
    dev = load_frames(data, "dev")
    dev_scores = {name: [rule_score(f["reference"], f["current"], name) for f in dev] for name in RULES}
    dev_scores["model"] = [predict(f["reference"], f["current"]) for f in dev]
    candidates = []
    for method, scores in dev_scores.items():
        grid = settings["model_thresholds"] if method == "model" else settings["rule_thresholds"]
        candidates.extend(sweep(dev, scores, method, grid, settings))
    selected_rule = select_candidate([c for c in candidates if c["method"] in RULES])
    selected_model = select_candidate([c for c in candidates if c["method"] == "model"])
    selection = {"selection_split": "dev", "frozen_before_holdout_loading": True,
                 "created_at_utc": datetime.now(UTC).isoformat(), "valid_comparison": not smoke,
                 "smoke_only": bool(smoke), "selected_rule": selected_rule, "selected_model": selected_model,
                 "dev_sample_ids": [f["sample_id"] for f in dev], "provenance": provenance,
                 "alarm_definition": "GT1 absent, GT0 present, >=9 total retained predicted GT0 pixels; not an any-pixel alarm",
                 "prediction_order": "score > threshold then 8-connected min-area-9 components WITHOUT GT; ignore255 only during scoring"}
    write_csv(out / "dev-sweep.csv", candidates)
    write_json(out / "selected.json", selection)
    selection_hash = sha(out / "selected.json")
    # No test/stress NPZ is opened before this point.
    results, all_counts, table = {}, [], []
    for split in ("dev", "test", "stress"):
        require(sha(out / "selected.json") == selection_hash, "Selection changed after freezing")
        frames = dev if split == "dev" else load_frames(data, split)
        rule_method = selected_rule["method"]
        score_maps = {"rule": dev_scores[rule_method] if split == "dev" else [rule_score(f["reference"], f["current"], rule_method) for f in frames],
                      "model": dev_scores["model"] if split == "dev" else [predict(f["reference"], f["current"]) for f in frames]}
        split_results, split_records, saved_masks = {}, {}, {}
        for method, selected in (("rule", selected_rule), ("model", selected_model)):
            summary, records, masks = evaluate_scores(frames, score_maps[method], selected["threshold"], settings)
            summary["by_mechanism"] = {mechanism: summarize([r for r in records if r["mechanism"] == mechanism]) for mechanism in sorted({r["mechanism"] for r in records})}
            split_results[method] = summary; split_records[method] = records
            saved_masks[method] = np.stack(masks).astype(np.uint8)
            all_counts.extend({"split": split, "method": method, **r} for r in records)
            table.append({"split": split, "method": method, "candidate": selected["method"], "threshold": selected["threshold"],
                          **{key: summary[key] for key in ("frames", "positive_frame", "hit", "frame_hit_recall", "pixel_iou", "pixel_recall", "no_change_frame", "false_alarm", "false_alarm_rate", "stable_repeat_no_change_frames", "stable_repeat_false_alarms", "all_ignored")}, "valid_comparison": not smoke})
        np.savez_compressed(out / f"predictions-{split}.npz", sample_ids=np.array([f["sample_id"] for f in frames]),
                            target=np.stack([f["target"] for f in frames]), **saved_masks)
        if split != "dev":
            split_results["paired_group_bootstrap"] = paired_group_bootstrap(split_records["rule"], split_records["model"], settings["bootstrap_repeats"], settings["bootstrap_seed"])
        new_false_alarms = sorted(set(split_results["model"]["false_alarm_sample_ids"]) - set(split_results["rule"]["false_alarm_sample_ids"]))
        split_results["model_new_false_alarm_sample_ids"] = new_false_alarms
        results[split] = split_results
    checks = {}
    for split in ("test", "stress"):
        rule_result, model_result = results[split]["rule"], results[split]["model"]
        checks[f"{split}_no_extra_false_alarm_count"] = model_result["false_alarm"] <= rule_result["false_alarm"]
        checks[f"{split}_no_new_false_alarm_frames"] = not results[split]["model_new_false_alarm_sample_ids"]
        recalls = [model_result["frame_hit_recall"], rule_result["frame_hit_recall"]]
        checks[f"{split}_frame_recall_nondecreasing"] = all(v is not None for v in recalls) and recalls[0] >= recalls[1]
    stress_ci = results["stress"]["paired_group_bootstrap"]["pixel_iou"]["ci95"]
    checks["stress_paired_iou_ci_lower_gt_zero"] = stress_ci is not None and stress_ci[0] > 0
    final = {"status": "completed", "valid_comparison": not smoke, "smoke_only": bool(smoke),
             "scope": TRAINING_SCOPE, "field_validated": False, "crack_training_eligible": False,
             "selected_json_sha256": selection_hash, "provenance": provenance,
             "results": results, "acceptance_checks": checks,
             "improvement_supported": not smoke and all(checks.values()), "automatic_deployment": False,
             "limitations": ["One seed and synthetic labels do not validate field accuracy or defect inference.",
                             "No-change includes unresolved physical changes; it does not mean healthy pipe.",
                             "Zero observed dev FA is not proof of zero population FA.",
                             "Wilson intervals are nominal per-frame; bootstrap resamples parent scenes.",
                             "Dev was used for checkpoint/threshold selection; final test/stress thresholds were not retuned.",
                             "Rules and CNN receive measured pair information only; model uses fixed invertible asinh channels.",
                             "Smoke mode uses fixture/untrained weights and cannot support a comparison claim." if smoke else "The acceptance decision does not authorize automatic deployment."]}
    write_csv(out / "per-frame.csv", all_counts)
    write_csv(out / "summary.csv", table)
    final["artifact_hashes"] = {path.name: sha(path) for path in out.iterdir() if path.is_file()}
    write_json(out / "metrics.json", final)
    return final
