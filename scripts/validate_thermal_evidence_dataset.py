"""Independent v2 data/label audit; no synthesis, solver or radiometry imports.

Reconstructs the declared ideal Planck lookup with direct expm1/trapezoidal
integration, then independently checks inversion, noise replay and label scales.
This validates numerical consistency, not field calibration or physical truth.
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

REPO = Path(__file__).resolve().parents[1]
SCOPE = "synthetic_registered_thermal_change_segmentation"
MECHANISMS = {"stable_repeat", "wall_loss", "external_transfer", "reflection", "coating_change"}
QUALITY = {"misregistration", "calibration_drift"}
FACTOR_KEYS = ("insulated", "emissivity_bin", "drive_bin", "noise_bin")
CELLS = set(itertools.product((False, True), ("low", "high"), ("zero", "low", "high"), (0, 1)))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_path(root, relative):
    require(isinstance(relative, str) and bool(relative) and "\\" not in relative,
            "Invalid relative path")
    require(not PurePosixPath(relative).is_absolute() and not PureWindowsPath(relative).drive
            and ".." not in PurePosixPath(relative).parts, "Unsafe relative path")
    path = (root / relative).resolve()
    require(path.is_relative_to(root), "Path escapes audit root")
    return path


class IndependentCamera:
    """Independent SI Planck implementation; declared production LUT grid only.

    Uses wavelength in metres and direct expm1, instead of the producer's log
    spectral function. The shared grid is an audited numerical contract, not a
    shared implementation. No measured FLIR spectral response is implied.
    """

    def __init__(self, band_um):
        low, high = map(float, band_um)
        require(0 < low < high and math.isfinite(high), "Invalid spectral band")
        wavelength = np.linspace(low * 1e-6, high * 1e-6, 257)
        self.temperatures = np.linspace(-80., 600., 8193)
        self.radiances = np.empty_like(self.temperatures)
        h, c, k = 6.62607015e-34, 299792458., 1.380649e-23
        spacing = (wavelength[-1] - wavelength[0]) / 256
        for offset in range(0, len(self.temperatures), 256):
            kelvin = self.temperatures[offset:offset + 256, None] + 273.15
            spectrum = 2 * h * c**2 / (wavelength**5 * np.expm1(h * c / (wavelength * k * kelvin)))
            self.radiances[offset:offset + 256] = np.sum(
                (spectrum[:, :-1] + spectrum[:, 1:]) * (spacing / 2), axis=1)
        require(np.all(np.diff(self.radiances) > 0), "Independent LUT is not monotone")
        self.derivative30 = float((self.radiance(30.01) - self.radiance(29.99)) / .02)

    def radiance(self, temperature):
        value = np.asarray(temperature, dtype=np.float64)
        require(np.isfinite(value).all() and np.all((value >= -80) & (value <= 600)),
                "Temperature outside independent LUT")
        return np.interp(value, self.temperatures, self.radiances)

    def temperature(self, radiance):
        value = np.asarray(radiance, dtype=np.float64)
        require(np.isfinite(value).all() and np.all((value >= self.radiances[0])
                                                  & (value <= self.radiances[-1])),
                "Radiance outside independent LUT")
        return np.interp(value, self.radiances, self.temperatures)

    def decode(self, received, config, ambient_c):
        emissivity = float(config["camera_assumed_emissivity"])
        transmission = float(config["camera_assumed_transmittance"])
        require(0 < emissivity <= 1 and 0 < transmission <= 1, "Invalid camera inverse settings")
        ambient = self.radiance(ambient_c)
        object_radiance = (np.asarray(received) - (1 - transmission) * ambient
                          - transmission * (1 - emissivity) * ambient) / (transmission * emissivity)
        return self.temperature(object_radiance)


def recompute_target(reference, current, valid, low, high):
    delta = np.abs(current.astype(np.float64) - reference.astype(np.float64))
    target = np.full(reference.shape, 255, np.uint8)
    target[valid & (delta <= low)] = 0
    target[valid & (delta >= high)] = 1
    return target


def _quantization_check(stored, unquantized, config):
    q = float(config["quantization_c"])
    lo, hi = config["camera_limits_c"]
    # Allow only quantization and float32 rounding, including half-bin ties.
    expected = np.clip(unquantized, lo, hi)
    bound = q / 2 + 2 * float(np.max(np.abs(np.spacing(stored)))) + 1e-8
    deviation = float(np.max(np.abs(stored.astype(float) - expected))) if stored.size else 0.
    require(deviation <= bound, "Camera inversion/noise replay exceeds quantization bound")
    interior = (stored > lo) & (stored < hi)
    grid_error = np.abs(stored[interior].astype(float) - np.round(stored[interior] / q) * q)
    require(np.all(grid_error < 3e-5), "Stored Celsius values violate quantization grid")
    return deviation


def validate_arrays(row, arrays, config, camera):
    shape, solver_shape = tuple(config["shape"]), tuple(config["solver_shape"])
    float_fields = ("reference_c", "current_c", "clean_reference_c", "clean_current_c",
                    "label_low_c", "label_high_c")
    for name in float_fields:
        require(name in arrays and arrays[name].shape == shape and arrays[name].dtype == np.float32,
                f"Bad float32 image schema: {name}")
        require(np.isfinite(arrays[name]).all(), f"Nonfinite image: {name}")
    for name in ("valid_mask", "bad_pixel_mask", "pipe_mask_audit_only"):
        require(name in arrays and arrays[name].shape == shape and arrays[name].dtype == np.bool_,
                f"Bad Boolean mask schema: {name}")
    for name in ("surface_reference_c_audit_only", "surface_current_c_audit_only",
                 "wall_reference_mm_audit_only", "wall_current_mm_audit_only"):
        require(name in arrays and arrays[name].shape == solver_shape
                and arrays[name].dtype == np.float32 and np.isfinite(arrays[name]).all(),
                f"Bad surface audit schema: {name}")
    target = arrays["target"]
    require(target.shape == shape and target.dtype == np.uint8 and np.isin(target, [0, 1, 255]).all(),
            "Invalid target schema")
    require(np.all(arrays["wall_reference_mm_audit_only"] > 0)
            and np.all(arrays["wall_current_mm_audit_only"] > 0), "Nonpositive wall audit values")
    q = float(config["quantization_c"])
    require(math.isfinite(q) and q > 0, "Invalid quantization")
    minimum, maximum = map(float, config["camera_limits_c"])
    require(math.isfinite(minimum) and math.isfinite(maximum) and minimum < maximum,
            "Invalid camera bounds")
    bad = arrays["bad_pixel_mask"]
    valid = ~bad.copy()
    for name in float_fields[:4]:
        valid &= (arrays[name] > minimum) & (arrays[name] < maximum)
    require(np.array_equal(valid, arrays["valid_mask"]), "Stored valid_mask differs from recomputation")
    require(np.all(arrays["label_high_c"] > arrays["label_low_c"])
            and np.all(arrays["label_low_c"] > 0), "Invalid ordered label thresholds")
    noise_values = config["stress_read_noise_equiv_c_at_30" if row["split"] == "stress"
                          else "read_noise_equiv_c_at_30"]
    equivalent = float(noise_values[row["factors"]["noise_bin"]])
    sigma = equivalent * camera.derivative30
    require(math.isclose(float(row["read_noise_equiv_c_at_30"]), equivalent, rel_tol=1e-12)
            and math.isclose(float(row["read_noise_radiance"]), sigma, rel_tol=1e-8),
            "Declared noise scale does not match independent Planck derivative")
    require(sigma > 0 and math.isfinite(sigma), "Invalid independent noise scale")
    ambient = float(row["physical_parameters"]["ambient_c"])
    generator = np.random.default_rng(row["noise_seed"])
    scales, radiances, deviations = [], [], []
    for variant in ("reference", "current"):
        name = f"clean_sensor_radiance_{variant}_audit_only"
        require(name in arrays and arrays[name].shape == shape and arrays[name].dtype == np.float64
                and np.isfinite(arrays[name]).all(), f"Bad radiance audit field: {name}")
        radiance = arrays[name]
        radiances.append(radiance)
        decode = lambda value: camera.decode(value, config, ambient)
        deviations.append(_quantization_check(arrays[f"clean_{variant}_c"], decode(radiance), config))
        noisy = decode(radiance + generator.normal(0, sigma, shape))
        require(np.all(arrays[f"{variant}_c"][bad] == 0), "Bad-pixel encoding mismatch")
        deviations.append(_quantization_check(arrays[f"{variant}_c"][~bad], noisy[~bad], config))
        scales.append(np.abs(decode(radiance + sigma) - decode(radiance - sigma)) / 2)
    combined = np.sqrt(scales[0]**2 + scales[1]**2)
    expected_low = np.maximum(combined, q).astype(np.float32)
    expected_high = np.maximum(3 * combined, 2 * q).astype(np.float32)
    require(np.allclose(arrays["label_low_c"], expected_low, atol=1e-6, rtol=1e-5)
            and np.allclose(arrays["label_high_c"], expected_high, atol=1e-6, rtol=1e-5),
            "Stored thresholds differ from independent Planck/noise reconstruction")
    if row["segmentation_eligible"]:
        expected_target = recompute_target(arrays["clean_reference_c"], arrays["clean_current_c"],
                                           valid, arrays["label_low_c"], arrays["label_high_c"])
        require(np.array_equal(target, expected_target), "Target differs from independent recomputation")
    else:
        require(np.all(target == 255), "Rejected quality fixture contains segmentation targets")
    zero_wall = row["mechanism"] == "wall_loss" and row["factors"]["drive_bin"] == "zero"
    if row["mechanism"] == "stable_repeat" or zero_wall:
        require(not np.any(target == 1), "Stable/zero-drive wall-loss sample has positive targets")
        require(np.allclose(radiances[0], radiances[1], rtol=1e-12, atol=1e-10),
                "Stable/zero-drive wall-loss clean radiance is not unchanged")
    return {"pixels": target.size, "label0": int(np.count_nonzero(target == 0)),
            "label1": int(np.count_nonzero(target == 1)), "ignore255": int(np.count_nonzero(target == 255)),
            "sensor_valid_pixels": int(valid.sum()), "max_quantization_deviation_c": max(deviations),
            "max_threshold_error_c": float(max(np.max(np.abs(expected_low - arrays["label_low_c"])),
                                                np.max(np.abs(expected_high - arrays["label_high_c"]))))}


def validate_lineage(rows, quality_rows, protocol):
    groups, identifiers, paths, noise_seeds, scene_seeds, group_indices = {}, set(), set(), set(), {}, {}
    require(set(map(tuple, protocol["cells"])) == CELLS, "Protocol factorial differs from24 cells")
    for row, eligible in itertools.chain(((r, True) for r in rows), ((r, False) for r in quality_rows)):
        require(row["sample_id"] not in identifiers and row["relative_path"] not in paths,
                "Duplicate sample identifier or path")
        identifiers.add(row["sample_id"]); paths.add(row["relative_path"])
        require(row["segmentation_eligible"] is eligible, "Index eligibility mismatch")
        require(row["mechanism"] in (MECHANISMS if eligible else QUALITY), "Wrong mechanism/index")
        require(row["quality_status"] == ("ready" if eligible else "reject")
                and row["quality_reason"] == (None if eligible else row["mechanism"]),
                "Quality status/index mismatch")
        expected_directory = "samples" if eligible else "quality-fixtures"
        require(PurePosixPath(row["relative_path"]).parts[0] == expected_directory, "Wrong sample directory")
        group, split = row["base_scene_id"], row["split"]
        require(split in protocol["splits"], "Unexpected split")
        bucket = groups.setdefault(group, {"split": split, "rows": []})
        require(bucket["split"] == split, "Parent scene crosses splits")
        bucket["rows"].append(row)
        for key, used in (("scene_seed", scene_seeds), ("group_index", group_indices)):
            require(row[key] not in used or used[row[key]] == group, f"Reused {key} across groups")
            used[row[key]] = group
        require(row["noise_seed"] not in noise_seeds, "Noise seed reused")
        noise_seeds.add(row["noise_seed"])
        cell = tuple(row["factors"][key] for key in FACTOR_KEYS)
        require(cell in CELLS, "Unexpected factorial cell")
        physical, pose = row["physical_parameters"], row["pose"]
        radius = float(physical["outer_diameter_mm"]) / 2000 + float(physical["insulation_mm"]) / 1000
        length = float(physical["length_m"])
        require(radius > 0 and length > 0 and pose["radius_px"] > 0 and pose["half_length_px"] > 0,
                "Invalid cylinder geometry")
        require(math.isclose(pose["half_length_px"] / pose["radius_px"], length / (2 * radius),
                             rel_tol=1e-10, abs_tol=1e-10), "Projected geometry ratio mismatch")
        for key, maximum in (("solver_relative_residual", 1e-8), ("solver_energy_error", 1e-7),
                             ("external_balance_relative_error", 1e-7)):
            value = float(row[key])
            require(math.isfinite(value) and 0 <= value <= maximum, f"Solver diagnostic gate failed: {key}")
        if row["factors"]["drive_bin"] == "zero":
            require(physical["bulk_c"] == physical["ambient_c"], "Zero-drive metadata is not isothermal")
    result = {}
    for split, expected_count in protocol["splits"].items():
        selected = [group for group in groups.values() if group["split"] == split]
        require(len(selected) == expected_count and expected_count > 0 and expected_count % 24 == 0,
                "Incorrect split group count")
        cells, patch_kinds, blur = Counter(), Counter(), defaultdict(Counter)
        centers = []
        for group in selected:
            rr = group["rows"]
            require(len(rr) == 7 and {r["mechanism"] for r in rr} == MECHANISMS | QUALITY,
                    "Each scene must contain five observation and two quality cases")
            for key in ("factors", "pose", "patch", "physical_parameters", "scene_seed", "psf_sigma_px"):
                require(all(r[key] == rr[0][key] for r in rr), f"Parent scene metadata differs: {key}")
            row = rr[0]
            cells[tuple(row["factors"][key] for key in FACTOR_KEYS)] += 1
            patch_kinds[str(row["patch"]["kind"])] += 1
            centers.append(row["patch"]["center_xy"])
            blur[str(row["factors"]["insulated"])][str(row["psf_sigma_px"])] += 1
        require(set(cells) == CELLS and len(set(cells.values())) == 1, "Unbalanced24-cell factorial")
        centers = np.asarray(centers, dtype=float)
        require(centers.shape == (expected_count, 2) and np.isfinite(centers).all()
                and np.all((centers >= 0) & (centers <= 1)), "Invalid patch center metadata")
        result[split] = {"groups": expected_count, "factorial_cells": {str(k): v for k, v in cells.items()},
                         "blur_by_insulation": {key: dict(value) for key, value in blur.items()},
                         "patch_kinds": dict(patch_kinds),
                         "patch_center_min_xy": centers.min(axis=0).tolist(),
                         "patch_center_max_xy": centers.max(axis=0).tolist()}
    return result


def validate_dataset(root, repo_root=REPO):
    root, repo_root = Path(root).resolve(), Path(repo_root).resolve()
    read = lambda name: json.loads(safe_path(root, name).read_text(encoding="utf-8-sig"))
    protocol, manifest, ledger = read("protocol.json"), read("manifest.json"), read("evidence-ledger.json")
    require(protocol["task"] == manifest["training_eligible_scope"] == SCOPE, "Wrong task scope")
    require(manifest["field_validated"] is False and manifest["crack_training_eligible"] is False
            and manifest["provenance"] == "synthetic", "Invalid field/defect eligibility claim")
    bindings = {"index_sha256": "index.jsonl", "quality_index_sha256": "quality-index.jsonl",
                "protocol_sha256": "protocol.json", "evidence_ledger_sha256": "evidence-ledger.json"}
    for key, name in bindings.items():
        require(manifest[key] == sha(root / name), f"Manifest hash mismatch: {name}")
    require(protocol["version"] == protocol["config"]["version"] == 2, "Wrong dataset version")
    config = protocol["config"]
    require(protocol["shape"] == config["shape"] and protocol["splits"] == config["splits"],
            "Protocol/config shape or split mismatch")
    require(set(protocol["mechanisms"]) == MECHANISMS and set(protocol["quality_cases"]) == QUALITY,
            "Protocol mechanism mismatch")
    require(protocol["model_inputs"] == ["reference_c", "current_c"], "Audit fields leaked to input contract")
    require(config["field_validated"] is False and config["crack_training_eligible"] is False,
            "Config claims field/defect eligibility")
    require(manifest["source_hashes"] == protocol["source_hashes"] and bool(protocol["source_hashes"]),
            "Source provenance mismatch")
    for path, digest in protocol["source_hashes"].items():
        require(sha(safe_path(repo_root, path)) == digest, f"Frozen source hash mismatch: {path}")
    require(set(ledger["parameters"]) == set(config), "Incomplete parameter evidence ledger")
    source_ids = {source["id"] for source in ledger["sources"]}
    require(len(source_ids) == len(ledger["sources"]), "Duplicate literature source IDs")
    for name, value in config.items():
        entry = ledger["parameters"][name]
        require(entry["value"] == value and entry["empirical_distribution"] is False,
                f"Parameter provenance mismatch: {name}")
        expected = "published_band_endpoints_only" if name == "band_um" else "explicit_design_assumption"
        require(entry["status"] == expected and set(entry["source_ids"]) <= source_ids,
                f"Parameter evidence status mismatch: {name}")
    require(ledger["parameters"]["band_um"]["source_ids"] == ["FLIR-A70"], "Missing band source binding")
    for references in ledger["equation_mapping"].values():
        require(set(references) <= source_ids, "Unknown equation source reference")
    rows, quality_rows = [
        [json.loads(line) for line in (root / name).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
        for name in ("index.jsonl", "quality-index.jsonl")]
    require(len(rows) == manifest["sample_count"] and len(quality_rows) == manifest["quality_fixture_count"],
            "Manifest sample count mismatch")
    require(manifest["group_count"] == sum(protocol["splits"].values()), "Manifest group count mismatch")
    require(len(rows) + len(quality_rows) <= 20000 and np.prod(config["shape"]) <= 1_000_000,
            "Audit exceeds bounded size")
    lineage = validate_lineage(rows, quality_rows, protocol)
    camera = IndependentCamera(config["band_um"])
    statistics = defaultdict(lambda: Counter(samples=0, pixels=0, label0=0, label1=0, ignore255=0,
                                              sensor_valid_pixels=0, positive_frames=0))
    pair_hashes, reference_hashes = {}, {}
    duplicate_within_split = 0
    max_threshold_error, max_quantization_deviation = 0., 0.
    for number, row in enumerate(rows + quality_rows, 1):
        path = safe_path(root, row["relative_path"])
        require(path.suffix == ".npz" and sha(path) == row["sha256"], f"Sample SHA256 mismatch: {row['sample_id']}")
        with np.load(path, allow_pickle=False) as data:
            arrays = {key: data[key] for key in data.files}
        result = validate_arrays(row, arrays, config, camera)
        max_threshold_error = max(max_threshold_error, result.pop("max_threshold_error_c"))
        max_quantization_deviation = max(max_quantization_deviation, result.pop("max_quantization_deviation_c"))
        key = f"{row['split']}/{row['mechanism']}"
        statistics[key].update(result)
        statistics[key]["samples"] += 1
        statistics[key]["positive_frames"] += int(result["label1"] > 0)
        digest = hashlib.sha256(arrays["reference_c"].tobytes() + arrays["current_c"].tobytes()).hexdigest()
        previous = pair_hashes.get(digest)
        require(previous is None or previous == row["split"], "Measured input pair duplicated across splits")
        duplicate_within_split += int(previous is not None)
        pair_hashes[digest] = row["split"]
        clean_reference = hashlib.sha256(arrays["clean_sensor_radiance_reference_audit_only"].tobytes()).hexdigest()
        group = row["base_scene_id"]
        require(group not in reference_hashes or reference_hashes[group] == clean_reference,
                "Reference radiance differs inside physical scene")
        reference_hashes[group] = clean_reference
        if number % 100 == 0:
            print(f"Audited {number}/{len(rows) + len(quality_rows)} pairs", flush=True)
    support = {}
    for split in protocol["splits"]:
        selected = [statistics[f"{split}/{kind}"] for kind in MECHANISMS]
        total = sum(item["pixels"] for item in selected)
        scored = sum(item["label0"] + item["label1"] for item in selected)
        positive = sum(item["label1"] for item in selected)
        require(total > 0 and scored / total > .5 and positive > 0, "Insufficient split target support")
        require(statistics[f"{split}/stable_repeat"]["samples"] > 0, "Missing stable-repeat support")
        support[split] = {"pixels": total, "scored_pixels": scored,
                          "scored_fraction": scored / total, "positive_pixels": positive}
    return {"status": "passed", "training_eligible_scope": SCOPE,
            "field_validated": False, "crack_training_eligible": False,
            "manifest_sha256": sha(root / "manifest.json"), "protocol_sha256": sha(root / "protocol.json"),
            "index_sha256": sha(root / "index.jsonl"), "quality_index_sha256": sha(root / "quality-index.jsonl"),
            "evidence_ledger_sha256": sha(root / "evidence-ledger.json"), "validator_sha256": sha(__file__),
            "sample_count": len(rows), "quality_fixture_count": len(quality_rows),
            "lineage_and_factorial": lineage, "support_by_split_and_mechanism": dict(statistics),
            "segmentation_support": support, "duplicate_measured_pairs_across_splits": 0,
            "duplicate_measured_pairs_within_split": duplicate_within_split,
            "independent_uncertainty_reconstruction": {"method": "SI Planck expm1;257 wavelengths;8193 temperatures;-80..600C; independent camera inverse/noise seed replay",
                "threshold_atol_c": 1e-6, "threshold_rtol": 1e-5,
                "max_threshold_error_c": max_threshold_error,
                "max_quantization_deviation_c": max_quantization_deviation},
            "solver_diagnostic_maxima": {key: max(row[key] for row in rows + quality_rows) for key in
                                          ("solver_relative_residual", "solver_energy_error", "external_balance_relative_error")},
            "limitations": ["Integrity and internal numerical consistency, not physical or field validation",
                            "Solver diagnostics checked; PDE not independently re-solved",
                            "Exact measured-pair hashes do not detect all near-duplicates",
                            "Factor summaries do not prove statistical independence or field prevalence",
                            "No model fitting, threshold selection or performance tuning"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", "--root", "--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    destination = args.out or args.data / "validation.json"
    try:
        report = validate_dataset(args.data)
    except (ValueError, KeyError, OSError) as exc:
        report = {"status": "failed", "training_eligible_scope": SCOPE, "field_validated": False,
                  "error_type": type(exc).__name__, "error": str(exc), "validator_sha256": sha(__file__)}
        destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        raise
    destination.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "sample_count": report["sample_count"],
                      "quality_fixture_count": report["quality_fixture_count"], "out": str(destination)}), flush=True)


if __name__ == "__main__":
    main()
