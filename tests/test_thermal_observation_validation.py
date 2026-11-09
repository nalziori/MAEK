import copy
import json

import numpy as np
import pytest

from scripts.validate_thermal_observation_dataset import (
    MECHANISMS,
    SCOPE,
    check_noise_lineage,
    recompute_target,
    recompute_valid,
    safe_path,
    sha,
    thresholds,
    validate_dataset,
    validate_lineage,
)


def test_target_exact_boundaries_ignore_and_float64_difference():
    before = np.zeros((2, 3), np.float32)
    after = np.array([[0, 1, 2], [3, 4, 5]], np.float32)
    valid = np.ones((2, 3), bool)
    valid[1, 2] = False
    assert recompute_target(before, after, valid, 1, 3).tolist() == [[0, 0, 255], [1, 1, 255]]
    maximum = np.finfo(np.float32).max
    assert recompute_target(np.array([[maximum]], np.float32), np.array([[-maximum]], np.float32),
                            np.ones((1, 1), bool), 1, 3).item() == 1
    with pytest.raises(ValueError, match="threshold"):
        recompute_target(before, after, valid, 3, 1)


def test_thresholds_noise_and_quantization_limits():
    assert thresholds(.01, 1.) == (1., 2.)
    lo, hi = thresholds(1., .01)
    assert lo == pytest.approx(2 ** .5) and hi == pytest.approx(3 * 2 ** .5)
    with pytest.raises(ValueError, match="sigma"):
        thresholds(0, .01)


def test_saturation_and_bad_pixels_recomputed_from_both_frames():
    arrays = {k: np.ones((1, 5), np.float32) for k in
              ("reference_c", "current_c", "clean_reference_c", "clean_current_c")}
    arrays["bad_pixel_mask"] = np.array([[False, False, False, True, False]])
    arrays["reference_c"][0, 0] = -40
    arrays["clean_current_c"][0, 1] = 180
    arrays["current_c"][0, 2] = 181
    assert recompute_valid(arrays, -40, 180).tolist() == [[False, False, False, False, True]]


@pytest.mark.parametrize("path", ["../x.npz", "C:/x.npz", "/x.npz", "samples\\x.npz"])
def test_unsafe_sample_path_rejected(tmp_path, path):
    with pytest.raises(ValueError, match="Unsafe"):
        safe_path(tmp_path, path)


def index_rows(split="train", offset=0):
    rows = []
    for i in range(16):
        for k, mechanism in enumerate(sorted(MECHANISMS)):
            group = offset + i
            rows.append({"sample_id": f"g{group}_{mechanism}", "base_scene_id": f"g{group}",
                         "relative_path": f"samples/g{group}_{mechanism}.npz", "split": split,
                         "mechanism": mechanism, "scene_seed": group * 100,
                         "noise_seed_reference": group * 100 + 2 * k + 1,
                         "noise_seed_current": group * 100 + 2 * k + 2,
                         "factors": {"insulated": bool(i & 1), "emissivity_bin": "high" if i & 2 else "low",
                                     "drive_bin": "high" if i & 4 else "low", "noise_bin": "high" if i & 8 else "low",
                                     "orientation": "vertical" if i % 2 else "horizontal", "patch_quadrant": i % 4}})
    return rows


def test_scene_split_seed_and_factorial_guards():
    original = index_rows()
    assert validate_lineage(original, {"train": 16})["train"]["groups"] == 16
    modified = copy.deepcopy(original)
    modified[1]["split"] = "dev"
    with pytest.raises(ValueError, match="crosses"):
        validate_lineage(modified, {"train": 16, "dev": 16})
    modified = copy.deepcopy(original)
    modified[1]["noise_seed_current"] = modified[0]["noise_seed_current"]
    with pytest.raises(ValueError, match="noise seed"):
        validate_lineage(modified, {"train": 16})
    modified = copy.deepcopy(original)
    for row in modified:
        row["factors"]["insulated"] = False
    with pytest.raises(ValueError, match="factorial"):
        validate_lineage(modified, {"train": 16})


def mini_dataset(root):
    root.mkdir(exist_ok=True)
    (root / "samples").mkdir()
    source = root / "fixture_source.py"
    source.write_text("# independently authored test fixture\n", encoding="utf-8")
    source_hashes = {str(source): sha(source)}
    rows = []
    shape = (8, 8)
    for j, split in enumerate(("train", "dev", "test", "stress")):
        for row in index_rows(split, j * 16):
            i = int(row["base_scene_id"][1:])
            sigma = (.45 if row["factors"]["noise_bin"] == "high" else .3) if split == "stress" else (.1 if row["factors"]["noise_bin"] == "high" else .03)
            lo, hi = thresholds(sigma, .01)
            row.update(noise_sigma_c=sigma, quantization_c=.01, camera_min_c=-40., camera_max_c=180.,
                       low_threshold_c=lo, high_threshold_c=hi, blur_sigma_px=2.2 if split == "stress" else (.5 if i % 2 else 1.),
                       outer_diameter_mm=219. if split == "stress" else (114.3 if i % 2 else 168.3),
                       solver_relative_residual=1e-10, solver_energy_error=1e-10)
            clean_ref = np.full(shape, 20 + i / 10, np.float32)
            clean_cur = clean_ref.copy()
            target = np.zeros(shape, np.uint8)
            if row["mechanism"] != "stable_repeat":
                clean_cur[2:6, 2:6] += 2
                target[2:6, 2:6] = 1
            arrays = {"clean_reference_c": clean_ref, "clean_current_c": clean_cur,
                      "valid_mask": np.ones(shape, bool), "bad_pixel_mask": np.zeros(shape, bool), "target": target}
            for variant, seed_key in (("reference", "noise_seed_reference"), ("current", "noise_seed_current")):
                noise = np.random.default_rng(row[seed_key]).normal(0, sigma, shape)
                arrays[f"{variant}_c"] = (np.round((arrays[f"clean_{variant}_c"].astype(float) + noise) / .01) * .01).astype(np.float32)
            path = root / row["relative_path"]
            np.savez(path, **arrays)
            row["sha256"] = sha(path)
            rows.append(row)
    protocol = {"task": SCOPE, "splits": {s: 16 for s in ("train", "dev", "test", "stress")},
                "mechanisms": sorted(MECHANISMS), "shape": list(shape), "source_hashes": source_hashes}
    (root / "protocol.json").write_text(json.dumps(protocol), encoding="utf-8")
    (root / "index.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    manifest = {"training_eligible_scope": SCOPE, "field_validated": False, "crack_training_eligible": False,
                "index_sha256": sha(root / "index.jsonl"), "protocol_sha256": sha(root / "protocol.json"),
                "sample_count": len(rows), "source_hashes": source_hashes}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return rows, manifest


def test_full_saved_fixture_and_tamper_rejection(tmp_path):
    rows, manifest = mini_dataset(tmp_path)
    result = validate_dataset(tmp_path)
    assert result["status"] == "passed" and result["sample_count"] == 320
    assert result["training_eligible_scope"] == SCOPE
    assert result["dev_only_baselines"]["train_spatial_prior"]["stable_frames"] == 16
    sample = tmp_path / rows[0]["relative_path"]
    original = sample.read_bytes()
    sample.write_bytes(original + b"tamper")
    with pytest.raises(ValueError, match="Sample hash"):
        validate_dataset(tmp_path)
    sample.write_bytes(original)
    with np.load(sample) as z:
        arrays = {key: z[key] for key in z.files}
    arrays["target"][0, 0] = 1
    np.savez(sample, **arrays)
    rows[0]["sha256"] = sha(sample)
    (tmp_path / "index.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    manifest["index_sha256"] = sha(tmp_path / "index.jsonl")
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="independent post-camera"):
        validate_dataset(tmp_path)


def test_independent_noise_seed_guard(tmp_path):
    rows, _ = mini_dataset(tmp_path)
    row = rows[0]
    with np.load(tmp_path / row["relative_path"]) as z:
        arrays = {k: z[k] for k in z.files}
    check_noise_lineage(arrays, row, arrays["valid_mask"])
    row["noise_seed_current"] += 9999
    with pytest.raises(ValueError, match="noise seed"):
        check_noise_lineage(arrays, row, arrays["valid_mask"])
