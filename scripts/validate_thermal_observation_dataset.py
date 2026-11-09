"""Independent integrity and target-consistency gate for synthetic paired change.

Does not import the generator, the shell solver, or the training loader. Test and
stress arrays are checked for integrity/support only; baseline scores use dev.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath, PureWindowsPath

import numpy as np

SCOPE = "synthetic_registered_thermal_change_segmentation"
MECHANISMS = {"stable_repeat", "wall_loss", "external_transfer", "reflection", "emissivity_change"}
FACTOR_KEYS = ("insulated", "emissivity_bin", "drive_bin", "noise_bin")
REPO = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_path(root, relative):
    require(isinstance(relative, str) and bool(relative), "Missing relative path")
    p = PurePosixPath(relative)
    require(not p.is_absolute() and not PureWindowsPath(relative).drive
            and "\\" not in relative and ".." not in p.parts, "Unsafe sample path")
    result = (root / relative).resolve()
    require(result.is_relative_to(root.resolve()), "Sample path escapes dataset root")
    return result


def thresholds(sigma, quantization):
    require(math.isfinite(sigma) and sigma > 0 and math.isfinite(quantization)
            and quantization > 0, "Invalid sigma or quantization")
    return max(math.sqrt(2) * sigma, quantization), max(3 * math.sqrt(2) * sigma, 2 * quantization)


def recompute_target(reference, current, valid, low, high):
    require(reference.shape == current.shape == valid.shape, "Target input shapes differ")
    require(valid.dtype == bool, "valid_mask must be bool")
    require(np.isfinite(reference).all() and np.isfinite(current).all(), "Nonfinite clean images")
    require(math.isfinite(low) and math.isfinite(high) and 0 <= low < high,
            "Invalid uncertainty thresholds")
    delta = np.abs(current.astype(np.float64) - reference.astype(np.float64))
    result = np.full(reference.shape, 255, dtype=np.uint8)
    result[valid & (delta <= low)] = 0
    result[valid & (delta >= high)] = 1
    return result


def recompute_valid(arrays, minimum, maximum):
    require(math.isfinite(minimum) and math.isfinite(maximum) and minimum < maximum,
            "Invalid camera window")
    valid = ~arrays["bad_pixel_mask"]
    for name in ("reference_c", "current_c", "clean_reference_c", "clean_current_c"):
        valid = valid & (arrays[name] > minimum) & (arrays[name] < maximum)
    return valid


def check_noise_lineage(arrays, row, valid):
    """Quantization allows <= one step between observed-clean and declared noise."""
    largest_error = 0.
    for variant, seed_key in (("reference", "noise_seed_reference"),
                              ("current", "noise_seed_current")):
        measured, clean = arrays[f"{variant}_c"], arrays[f"clean_{variant}_c"]
        noise = np.random.default_rng(row[seed_key]).normal(0, row["noise_sigma_c"], clean.shape)
        error = np.abs(measured.astype(float) - clean.astype(float) - noise)[valid]
        bound = row["quantization_c"] + 2 * float(np.max(np.abs(np.spacing(measured))))
        require(bool(np.all(error <= bound)), "Stored pair inconsistent with declared noise seed")
        largest_error = max(largest_error, float(error.max()))
    return largest_error


def validate_lineage(rows, split_groups):
    groups, noise_seeds, ids, paths, scene_seeds = {}, set(), set(), set(), {}
    for row in rows:
        require(row["sample_id"] not in ids, "Duplicate sample_id")
        require(row["relative_path"] not in paths, "Duplicate sample path")
        ids.add(row["sample_id"]); paths.add(row["relative_path"])
        group, split = row["base_scene_id"], row["split"]
        require(split in split_groups, "Unexpected split")
        if group not in groups:
            groups[group] = {"split": split, "rows": []}
        require(groups[group]["split"] == split, "Parent scene crosses splits")
        groups[group]["rows"].append(row)
        scene_seed = row["scene_seed"]
        require(scene_seed not in scene_seeds or scene_seeds[scene_seed] == group,
                "Scene seed reused across parent groups")
        scene_seeds[scene_seed] = group
        for name in ("noise_seed_reference", "noise_seed_current"):
            require(row[name] not in noise_seeds, "Sensor noise seed reused")
            noise_seeds.add(row[name])
    expected_cells = set(itertools.product((False, True), ("low", "high"),
                                         ("low", "high"), ("low", "high")))
    result = {}
    for split, count in split_groups.items():
        selected = [g for g in groups.values() if g["split"] == split]
        require(len(selected) == count, f"Incorrect group count: {split}")
        cells, orientation, quadrant = Counter(), Counter(), Counter()
        for g in selected:
            rr = g["rows"]
            require(len(rr) == 5 and {r["mechanism"] for r in rr} == MECHANISMS,
                    "Each group must contain all five mechanisms exactly once")
            require(all(r["factors"] == rr[0]["factors"] for r in rr),
                    "Nuisance factors differ within parent group")
            require(len({r["scene_seed"] for r in rr}) == 1, "Scene seed differs within group")
            f = rr[0]["factors"]
            cells[tuple(f[k] for k in FACTOR_KEYS)] += 1
            orientation[str(f["orientation"])] += 1
            quadrant[str(f["patch_quadrant"])] += 1
        require(set(cells) == expected_cells and len(set(cells.values())) == 1,
                f"Incomplete or unbalanced 16-cell nuisance factorial: {split}")
        require(len(orientation) == 2 and len(quadrant) == 4,
                f"Missing orientation or quadrant support: {split}")
        result[split] = {"groups": count, "factorial_cells": {str(k): v for k, v in cells.items()},
                         "orientation_groups": dict(orientation), "quadrant_groups": dict(quadrant)}
    return result


def confusion(target, prediction):
    valid = target != 255
    return np.bincount((2 * target[valid].astype(int) + prediction[valid].astype(int)),
                       minlength=4).reshape(2, 2)


def metrics(matrix):
    tn, fp, fn, tp = map(int, matrix.ravel())
    return {"confusion_actual_rows": matrix.tolist(),
            "pixel_precision": tp / (tp + fp) if tp + fp else None,
            "pixel_recall": tp / (tp + fn) if tp + fn else None,
            "pixel_iou": tp / (tp + fp + fn) if tp + fp + fn else None,
            "stable_pixel_false_positive_rate": fp / (tn + fp) if tn + fp else None}


def smooth3(array):
    padded = np.pad(array.astype(float), 1, mode="edge")
    h, w = array.shape
    return sum(padded[y:y + h, x:x + w] for y in range(3) for x in range(3)) / 9


def validate_dataset(root):
    root = Path(root).resolve()
    protocol = json.loads((root / "protocol.json").read_text(encoding="utf-8-sig"))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8-sig"))
    rows = [json.loads(s) for s in (root / "index.jsonl").read_text(encoding="utf-8-sig").splitlines() if s.strip()]
    require(protocol["task"] == manifest["training_eligible_scope"] == SCOPE, "Wrong task scope")
    require(manifest["field_validated"] is False and manifest["crack_training_eligible"] is False,
            "Synthetic data cannot claim field/crack eligibility")
    require(manifest["index_sha256"] == sha(root / "index.jsonl"), "Index hash mismatch")
    require(manifest["protocol_sha256"] == sha(root / "protocol.json"), "Protocol hash mismatch")
    require(manifest["sample_count"] == len(rows), "Manifest sample count mismatch")
    require(set(protocol["mechanisms"]) == MECHANISMS, "Protocol mechanism mismatch")
    require(bool(manifest["source_hashes"]), "Missing source provenance")
    require(manifest["source_hashes"] == protocol["source_hashes"], "Source provenance differs from frozen protocol")
    for path, digest in manifest["source_hashes"].items():
        require(sha(REPO / path) == digest, f"Source hash mismatch: {Path(path).name}")
    lineage = validate_lineage(rows, protocol["splits"])
    shape = tuple(protocol["shape"])
    require(len(shape) == 2 and min(shape) > 0, "Invalid image shape")
    statistics = defaultdict(lambda: {"samples": 0, "valid_pixels": 0, "pixels": 0,
                                     "label0": 0, "label1": 0, "ignore255": 0,
                                     "frames_with_positive": 0, "stable_repeat_frames": 0})
    hashes_by_pair, clean_hashes_by_pair = {}, {}
    clean_by_group = {}
    residual_correlations, noise_scales = [], []
    train_positive, train_valid = np.zeros(shape, dtype=np.int64), np.zeros(shape, dtype=np.int64)
    dev = []
    max_solver_residual = max_energy_error = 0.
    max_noise_seed_error = 0.
    sensor_values = defaultdict(lambda: defaultdict(set))
    for row in rows:
        path = safe_path(root, row["relative_path"])
        require(sha(path) == row["sha256"], f"Sample hash mismatch: {row['sample_id']}")
        with np.load(path, allow_pickle=False) as z:
            names = ("reference_c", "current_c", "clean_reference_c", "clean_current_c",
                     "valid_mask", "bad_pixel_mask", "target")
            require(set(names) <= set(z.files), "Missing sample arrays")
            a = {name: z[name] for name in names}
        for name, value in a.items():
            require(value.shape == shape, f"Array shape mismatch: {name}")
            expected_type = bool if name.endswith("mask") else (np.uint8 if name == "target" else np.float32)
            require(value.dtype == expected_type, f"Array dtype mismatch: {name}")
            require(np.isfinite(value).all(), f"Nonfinite array: {name}")
        low, high = thresholds(float(row["noise_sigma_c"]), float(row["quantization_c"]))
        require(math.isclose(row["low_threshold_c"], low, rel_tol=1e-12)
                and math.isclose(row["high_threshold_c"], high, rel_tol=1e-12), "Threshold rule mismatch")
        valid = recompute_valid(a, row["camera_min_c"], row["camera_max_c"])
        require(np.array_equal(valid, a["valid_mask"]), "Validity does not match saturation/bad pixels")
        expected = recompute_target(a["clean_reference_c"], a["clean_current_c"], valid, low, high)
        require(np.array_equal(a["target"], expected), "Target differs from independent post-camera recomputation")
        require(float(valid.mean()) > .5, "Insufficient valid fraction in sample")
        for key in ("reference_c", "current_c", "clean_reference_c", "clean_current_c"):
            require(np.all((a[key] >= row["camera_min_c"]) & (a[key] <= row["camera_max_c"])), "Temperature outside camera window")
            requantized = (np.rint(a[key].astype(float) / row["quantization_c"]) * row["quantization_c"]).astype(np.float32)
            require(np.array_equal(a[key], requantized), "Sample not on declared quantization grid")
        max_noise_seed_error = max(max_noise_seed_error, check_noise_lineage(a, row, valid))
        if row["mechanism"] == "stable_repeat":
            require(np.array_equal(a["clean_reference_c"], a["clean_current_c"]), "Stable control clean images differ")
            require(not np.any(a["target"] == 1), "Stable repeat has positive target")
        for prefix, seen in (("", hashes_by_pair), ("clean_", clean_hashes_by_pair)):
            digest = hashlib.sha256(a[f"{prefix}reference_c"].tobytes() + a[f"{prefix}current_c"].tobytes()).hexdigest()
            require(digest not in seen or seen[digest] == row["split"], "Exact image pair leaks across splits")
            seen[digest] = row["split"]
        group = row["base_scene_id"]
        reference_digest = hashlib.sha256(a["clean_reference_c"].tobytes()).hexdigest()
        if group in clean_by_group:
            require(clean_by_group[group] == reference_digest, "Clean reference changes within scene group")
        clean_by_group[group] = reference_digest
        for key, limit in (("solver_relative_residual", 1e-8), ("solver_energy_error", 1e-7)):
            require(math.isfinite(row[key]) and 0 <= row[key] <= limit, f"Solver tolerance failed: {key}")
        max_solver_residual = max(max_solver_residual, row["solver_relative_residual"])
        max_energy_error = max(max_energy_error, row["solver_energy_error"])
        for key in ("noise_sigma_c", "blur_sigma_px", "outer_diameter_mm"):
            sensor_values[row["split"]][key].add(row[key])
        residual_ref = (a["reference_c"].astype(float) - a["clean_reference_c"])[valid]
        residual_cur = (a["current_c"].astype(float) - a["clean_current_c"])[valid]
        require(not np.array_equal(residual_ref, residual_cur), "Identical pair-noise residuals")
        if residual_ref.std() > 0 and residual_cur.std() > 0:
            residual_correlations.append(float(np.corrcoef(residual_ref, residual_cur)[0, 1]))
        noise_scales.extend([float(residual_ref.std() / row["noise_sigma_c"]),
                             float(residual_cur.std() / row["noise_sigma_c"])])
        for key in (row["split"], f"{row['split']}/{row['mechanism']}"):
            stat = statistics[key]
            stat["samples"] += 1; stat["pixels"] += int(valid.size)
            stat["valid_pixels"] += int(valid.sum())
            stat["label0"] += int(np.sum(expected == 0)); stat["label1"] += int(np.sum(expected == 1))
            stat["ignore255"] += int(np.sum(expected == 255))
            stat["frames_with_positive"] += int(np.any(expected == 1))
            stat["stable_repeat_frames"] += int(row["mechanism"] == "stable_repeat")
        if row["split"] == "train":
            train_positive += expected == 1; train_valid += expected != 255
        elif row["split"] == "dev":
            dev.append((row, a))
    for split in protocol["splits"]:
        require(statistics[split]["label1"] > 0 and statistics[split]["label0"] > 0,
                f"Missing realized positive/stable labels: {split}")
        require(statistics[split]["valid_pixels"] / statistics[split]["pixels"] > .5,
                f"Insufficient split validity: {split}")
    if "stress" in sensor_values:
        expected_stress = {"noise_sigma_c": {.3, .45}, "blur_sigma_px": {2.2}, "outer_diameter_mm": {219.}}
        expected_regular = {"noise_sigma_c": {.03, .1}, "blur_sigma_px": {.5, 1.}, "outer_diameter_mm": {114.3, 168.3}}
        for key, expected in expected_stress.items():
            require(sensor_values["stress"][key] == expected, f"Stress regime mismatch: {key}")
            for split in ("train", "dev", "test"):
                require(sensor_values[split][key] == expected_regular[key], f"Regular regime mismatch: {split}/{key}")
    prior = np.divide(train_positive, train_valid, out=np.zeros(shape, dtype=float), where=train_valid > 0) >= .5
    baseline = {name: np.zeros((2, 2), dtype=np.int64) for name in ("absolute_difference", "smoothed_signed_difference_3x3", "train_spatial_prior")}
    stable_alarms = {name: 0 for name in baseline}
    stable_dev = 0
    for row, a in dev:
        difference = a["current_c"].astype(float) - a["reference_c"].astype(float)
        predictions = {"absolute_difference": np.abs(difference) >= row["high_threshold_c"],
                       "smoothed_signed_difference_3x3": np.abs(smooth3(difference)) >= row["high_threshold_c"],
                       "train_spatial_prior": prior}
        for name, prediction in predictions.items():
            baseline[name] += confusion(a["target"], prediction)
            if row["mechanism"] == "stable_repeat":
                stable_alarms[name] += int(np.any(prediction & (a["target"] == 0)))
        stable_dev += int(row["mechanism"] == "stable_repeat")
    summaries = {key: {**value, "valid_fraction": value["valid_pixels"] / value["pixels"]}
                 for key, value in statistics.items()}
    return {"status": "passed", "training_eligible_scope": SCOPE, "field_validated": False,
            "crack_training_eligible": False, "manifest_sha256": sha(root / "manifest.json"),
            "index_sha256": sha(root / "index.jsonl"), "protocol_sha256": sha(root / "protocol.json"),
            "validator_sha256": sha(__file__), "sample_count": len(rows), "lineage_and_factorial": lineage,
            "support_by_split_and_mechanism": summaries,
            "solver_max_relative_residual": max_solver_residual, "solver_max_relative_energy_error": max_energy_error,
            "sensor_regimes": {s: {k: sorted(v) for k, v in values.items()} for s, values in sensor_values.items()},
            "noise_residual_diagnostics": {"pair_correlation_min_median_max": [min(residual_correlations), float(np.median(residual_correlations)), max(residual_correlations)],
                                           "max_declared_noise_reconstruction_error_c": max_noise_seed_error,
                                           "residual_std_over_declared_sigma_min_median_max": [min(noise_scales), float(np.median(noise_scales)), max(noise_scales)]},
            "dev_only_baselines": {name: {**metrics(value), "stable_frames_with_any_positive_pixel": stable_alarms[name], "stable_frames": stable_dev} for name, value in baseline.items()},
            "limits": ["All evidence is synthetic; no field accuracy or crack/remaining-wall inference established.",
                       "Labels represent registered observable thermal change, regardless of physical cause; below-threshold is not a healthy-pipe label.",
                       "Target independently recomputed from saved post-camera clean images; this does not independently reconstruct the shell solver or PSF itself.",
                       "Perturbation support is not ground truth; ignore pixels include saturation/bad pixels and the uncertainty band.",
                       "Test/stress inspected only for integrity and label support, not prediction performance; future tuning on them destroys that separation.",
                       "Dev any-pixel alarm is a pixel multiplicity diagnostic, not a deployed component alarm policy.",
                       "Difference-rule baselines receive known synthetic noise thresholds; this is not a fair comparison to image-only learned models or a deployable sensor calibration.",
                       "Registered pair and matched calibration are prerequisites; the dataset does not solve registration or calibration."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_dataset(args.root)
    except (ValueError, KeyError, OSError, TypeError) as error:
        result = {"status": "failed", "error": str(error), "training_eligible_scope": None}
        (args.root / "validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        raise
    (args.root / "validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "sample_count": result["sample_count"],
                      "dev_only_baselines": result["dev_only_baselines"]}))


if __name__ == "__main__":
    main()
