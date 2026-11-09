import copy
import hashlib
import itertools
import json

import numpy as np
import pytest

from scripts.validate_thermal_evidence_dataset import (
    IndependentCamera,
    recompute_target,
    safe_path,
    validate_arrays,
    validate_dataset,
    validate_lineage,
)


def test_target_boundaries_and_ignore_are_independent():
    reference = np.zeros((2, 3), np.float32)
    current = np.array([[0, .1, .2], [.3, 1, 2]], np.float32)
    low = np.full_like(reference, .1)
    high = np.full_like(reference, .3)
    valid = np.array([[True, True, True], [True, False, True]])
    np.testing.assert_array_equal(recompute_target(reference, current, valid, low, high),
                                  np.array([[0, 0, 255], [1, 255, 1]], np.uint8))


@pytest.fixture(scope="module")
def camera():
    return IndependentCamera([7.5, 14.0])


@pytest.fixture
def sample(camera):
    config = {"shape": [4, 5], "solver_shape": [2, 3], "quantization_c": .01,
              "camera_limits_c": [-40, 180], "camera_assumed_emissivity": .95,
              "camera_assumed_transmittance": 1., "read_noise_equiv_c_at_30": [.03, .1],
              "stress_read_noise_equiv_c_at_30": [.2, .4]}
    sigma = .03 * camera.derivative30
    row = {"mechanism": "reflection", "split": "train", "noise_seed": 19,
           "physical_parameters": {"ambient_c": 20.}, "factors": {"noise_bin": 0, "drive_bin": "low"},
           "read_noise_equiv_c_at_30": .03, "read_noise_radiance": sigma,
           "segmentation_eligible": True}
    true_reference = np.full((4, 5), 20.)
    true_current = np.full((4, 5), 21.)
    true_current[:, 0] = 20.
    ambient = camera.radiance(20.)
    radiances = [.95 * camera.radiance(a) + .05 * ambient for a in (true_reference, true_current)]
    bad = np.zeros((4, 5), bool)
    bad[0, 0] = True
    generator = np.random.default_rng(19)
    decode = lambda value: camera.decode(value, config, 20.)
    clean = [np.round(decode(a) / .01).astype(np.float64) * .01 for a in radiances]
    observed = [(np.round(decode(a + generator.normal(0, sigma, a.shape)) / .01) * .01).astype(np.float32)
                for a in radiances]
    for a in observed:
        a[bad] = 0.
    scales = [np.abs(decode(a + sigma) - decode(a - sigma)) / 2 for a in radiances]
    pair_sigma = np.hypot(*scales)
    low = np.maximum(pair_sigma, .01).astype(np.float32)
    high = np.maximum(3 * pair_sigma, .02).astype(np.float32)
    clean = [a.astype(np.float32) for a in clean]
    valid = ~bad
    target = np.ones((4, 5), np.uint8)
    target[:, 0] = 0
    target[bad] = 255
    arrays = {"reference_c": observed[0], "current_c": observed[1],
              "clean_reference_c": clean[0], "clean_current_c": clean[1],
              "target": target, "valid_mask": valid, "bad_pixel_mask": bad,
              "label_low_c": low, "label_high_c": high, "pipe_mask_audit_only": np.ones((4, 5), bool),
              "clean_sensor_radiance_reference_audit_only": radiances[0],
              "clean_sensor_radiance_current_audit_only": radiances[1]}
    for name in ("surface_reference_c_audit_only", "surface_current_c_audit_only"):
        arrays[name] = np.full((2, 3), 20, np.float32)
    for name in ("wall_reference_mm_audit_only", "wall_current_mm_audit_only"):
        arrays[name] = np.full((2, 3), 5, np.float32)
    return row, arrays, config


def test_independent_camera_roundtrip_and_sample_replay(camera, sample):
    values = np.array([-40., 0., 30., 100., 180.])
    np.testing.assert_allclose(camera.temperature(camera.radiance(values)), values, atol=1e-10)
    result = validate_arrays(*sample, camera)
    assert result["label1"] == 16 and result["ignore255"] == 1


@pytest.mark.parametrize("field", ["target", "label_low_c", "label_high_c", "valid_mask", "current_c"])
def test_tampered_arrays_rejected(camera, sample, field):
    row, arrays, config = sample
    if field == "valid_mask":
        arrays[field][0, 1] = False
    elif field == "target":
        arrays[field][0, 1] = 0
    else:
        arrays[field][0, 1] += 1
    with pytest.raises(ValueError):
        validate_arrays(row, arrays, config, camera)


def test_quality_fixtures_cannot_carry_segmentation_targets(camera, sample):
    row, arrays, config = sample
    row.update(mechanism="misregistration", segmentation_eligible=False)
    with pytest.raises(ValueError, match="quality"):
        validate_arrays(row, arrays, config, camera)
    arrays["target"].fill(255)
    assert validate_arrays(row, arrays, config, camera)["label1"] == 0


def test_noise_metadata_tamper_rejected(camera, sample):
    row, arrays, config = sample
    row["read_noise_radiance"] *= 2
    with pytest.raises(ValueError, match="noise"):
        validate_arrays(row, arrays, config, camera)


def lineage_fixture():
    mechanisms = ["stable_repeat", "wall_loss", "external_transfer", "reflection", "coating_change"]
    quality = ["misregistration", "calibration_drift"]
    cells = list(itertools.product([False, True], ["low", "high"], ["zero", "low", "high"], [0, 1]))
    rows, quality_rows = [], []
    for group, cell in enumerate(cells):
        for k, mechanism in enumerate(mechanisms + quality):
            row = {"sample_id": f"g{group}_{mechanism}", "base_scene_id": f"g{group}",
                   "group_index": group, "split": "train", "scene_seed": 1000 * group,
                   "noise_seed": 1000 * group + 100 + k, "mechanism": mechanism,
                   "segmentation_eligible": mechanism in mechanisms,
                   "quality_status": "ready" if mechanism in mechanisms else "reject",
                   "quality_reason": None if mechanism in mechanisms else mechanism,
                   "relative_path": f"{'samples' if mechanism in mechanisms else 'quality-fixtures'}/g{group}_{mechanism}.npz",
                   "factors": dict(zip(("insulated", "emissivity_bin", "drive_bin", "noise_bin"), cell)),
                   "pose": {"angle_rad": .2, "center_xy": [20, 20], "radius_px": 5., "half_length_px": 50.},
                   "patch": {"kind": group % 3, "center_xy": [.25 + group / 100, .5]},
                   "psf_sigma_px": [.4, .8, 1.2][group % 3],
                   "physical_parameters": {"outer_diameter_mm": 100., "insulation_mm": 0.,
                                           "length_m": 1., "bulk_c": 20., "ambient_c": 20.},
                   "solver_relative_residual": 1e-10, "solver_energy_error": 1e-10,
                   "external_balance_relative_error": 1e-10}
            (rows if mechanism in mechanisms else quality_rows).append(row)
    return rows, quality_rows, {"splits": {"train": 24}, "cells": cells}


def test_full24cell_lineage():
    result = validate_lineage(*lineage_fixture())
    assert result["train"]["groups"] == 24 and len(result["train"]["factorial_cells"]) == 24


@pytest.mark.parametrize("tamper", ["group_split", "geometry", "solver", "eligibility", "cell"])
def test_lineage_tamper_rejected(tamper):
    rows, quality, protocol = copy.deepcopy(lineage_fixture())
    if tamper == "group_split":
        protocol["splits"]["dev"] = 24
        rows[0]["split"] = "dev"
    elif tamper == "geometry":
        rows[0]["pose"]["radius_px"] *= 2
    elif tamper == "solver":
        rows[0]["solver_energy_error"] = .1
    elif tamper == "eligibility":
        quality[0]["segmentation_eligible"] = True
    else:
        rows[0]["factors"]["noise_bin"] = 3
    with pytest.raises(ValueError):
        validate_lineage(rows, quality, protocol)


@pytest.fixture
def metadata_fixture(tmp_path):
    root, repo = tmp_path / "data", tmp_path / "repo"
    root.mkdir(); repo.mkdir()
    (repo / "source.txt").write_text("fixture-only source", encoding="utf-8")
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    source_hashes = {"source.txt": digest(repo / "source.txt")}
    config = {"version": 2, "shape": [4, 5], "splits": {"train": 24},
              "field_validated": False, "crack_training_eligible": False, "band_um": [7.5, 14.]}
    protocol = {"version": 2, "task": "synthetic_registered_thermal_change_segmentation",
                "config": config, "shape": config["shape"], "splits": config["splits"],
                "mechanisms": ["stable_repeat", "wall_loss", "external_transfer", "reflection", "coating_change"],
                "quality_cases": ["misregistration", "calibration_drift"],
                "model_inputs": ["reference_c", "current_c"], "source_hashes": source_hashes}
    ledger = {"sources": [{"id": "FLIR-A70"}], "equation_mapping": {}, "parameters": {
        key: {"value": value, "empirical_distribution": False,
              "status": "published_band_endpoints_only" if key == "band_um" else "explicit_design_assumption",
              "source_ids": ["FLIR-A70"] if key == "band_um" else []}
        for key, value in config.items()}}
    for name, value in (("protocol.json", protocol), ("evidence-ledger.json", ledger)):
        (root / name).write_text(json.dumps(value), encoding="utf-8")
    for name in ("index.jsonl", "quality-index.jsonl"):
        (root / name).write_text("", encoding="utf-8")
    manifest = {"training_eligible_scope": protocol["task"], "field_validated": False,
                "crack_training_eligible": False, "provenance": "synthetic", "source_hashes": source_hashes,
                "index_sha256": digest(root / "index.jsonl"),
                "quality_index_sha256": digest(root / "quality-index.jsonl"),
                "protocol_sha256": digest(root / "protocol.json"),
                "evidence_ledger_sha256": digest(root / "evidence-ledger.json")}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root, repo


@pytest.mark.parametrize("name", ["index.jsonl", "quality-index.jsonl", "protocol.json", "evidence-ledger.json"])
def test_metadata_byte_tampering_fails_before_sample_audit(metadata_fixture, name):
    root, repo = metadata_fixture
    with (root / name).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="Manifest hash mismatch"):
        validate_dataset(root, repo)


def test_ledger_cannot_claim_an_empirical_distribution_even_with_updated_hash(metadata_fixture):
    root, repo = metadata_fixture
    path = root / "evidence-ledger.json"
    ledger = json.loads(path.read_text())
    ledger["parameters"]["band_um"]["empirical_distribution"] = True
    path.write_text(json.dumps(ledger))
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["evidence_ledger_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Parameter provenance"):
        validate_dataset(root, repo)


@pytest.mark.parametrize("path", ["../outside.npz", "C:/outside.npz", "..\\outside.npz"])
def test_audit_paths_cannot_escape_root(tmp_path, path):
    with pytest.raises(ValueError, match="path"):
        safe_path(tmp_path, path)
