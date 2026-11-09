import hashlib
import json

import numpy as np
import pytest

from maek.thermal_observation_data import ThermalObservationDataset, encode_pair

SCOPE = "synthetic_registered_thermal_change_segmentation"


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def write_index(root, rows):
    (root / "index.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    write_json(root / "validation.json", {
        "status": "passed", "training_eligible_scope": SCOPE,
        **{f"{name}_sha256": hashlib.sha256((root / filename).read_bytes()).hexdigest()
           for name, filename in (("protocol", "protocol.json"),
                                  ("manifest", "manifest.json"), ("index", "index.jsonl"))},
    })


@pytest.fixture
def dataset(tmp_path):
    write_json(tmp_path / "protocol.json", {"schema_version": 1})
    write_json(tmp_path / "manifest.json", {"training_eligible_scope": SCOPE})
    write_json(tmp_path / "validation.json", {"status": "passed"})
    reference = np.array([[25, 25.001], [30, -20]], dtype=np.float32)
    current = reference + np.array([[0, 0.003], [2, -4]], dtype=np.float32)
    target = np.array([[0, 255], [1, 1]], dtype=np.uint8)
    np.savez(tmp_path / "sample.npz", reference_c=reference, current_c=current,
             target=target, clean_reference_c=np.full((2, 2), 999))
    row = {"sample_id": "s1", "base_scene_id": "b1", "split": "train",
           "relative_path": "sample.npz",
           "sha256": hashlib.sha256((tmp_path / "sample.npz").read_bytes()).hexdigest(),
           "causative_mechanism": "never_an_input", "crack": True}
    write_index(tmp_path, [row])
    return tmp_path, row, reference, current, target


def test_temperature_precision_fixed_channels_and_no_label_leakage(dataset):
    root, _, reference, current, target = dataset
    sample = ThermalObservationDataset(root, "train")[0]
    expected = np.stack([np.arcsinh((reference.astype(float) - 25) / 50),
                         np.arcsinh((current.astype(float) - 25) / 50),
                         np.arcsinh((current.astype(float) - reference) / 2)]).astype(np.float32)
    np.testing.assert_allclose(sample["input"], expected, rtol=1e-6)
    assert sample["input"].dtype == np.float32
    assert sample["input"][2, 0, 1] != 0
    assert set(sample) == {"input", "target", "sample_id", "base_scene_id"}
    np.testing.assert_array_equal(sample["target"], target)
    assert sample["target"].dtype == np.uint8
    assert len(ThermalObservationDataset(root, "train")) == 1


@pytest.mark.parametrize("reference,current", [
    (np.zeros((2, 2)), np.zeros((1, 2))),
    (np.zeros(4), np.zeros(4)),
    (np.empty((0, 2)), np.empty((0, 2))),
    (np.full((2, 2), np.nan), np.zeros((2, 2))),
    (np.zeros((2, 2)), np.full((2, 2), np.inf)),
])
def test_encode_rejects_invalid_inputs(reference, current):
    with pytest.raises(ValueError):
        encode_pair(reference, current)


@pytest.mark.parametrize("status", [None, "failed", "unknown"])
def test_validation_required_by_default(dataset, status):
    root = dataset[0]
    if status is None:
        (root / "validation.json").unlink()
    else:
        write_json(root / "validation.json", {"status": status})
    with pytest.raises(ValueError, match="validation"):
        ThermalObservationDataset(root, "train")
    assert len(ThermalObservationDataset(root, "train", require_validated=False)) == 1


@pytest.mark.parametrize("scope", [None, "gas_crack_detection", "unknown"])
def test_unknown_or_missing_scope_rejected(dataset, scope):
    root = dataset[0]
    write_json(root / "manifest.json", {} if scope is None else {"training_eligible_scope": scope})
    with pytest.raises(ValueError, match="scope"):
        ThermalObservationDataset(root, "train")


@pytest.mark.parametrize("filename", ["protocol.json", "manifest.json", "index.jsonl"])
def test_missing_required_metadata_rejected(dataset, filename):
    root = dataset[0]
    (root / filename).unlink()
    with pytest.raises(ValueError):
        ThermalObservationDataset(root, "train")


def test_hash_tamper_detected_after_construction(dataset):
    root = dataset[0]
    loader = ThermalObservationDataset(root, "train")
    with (root / "sample.npz").open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="SHA256"):
        loader[0]
    assert ThermalObservationDataset(root, "train", verify_hashes=False)[0]["input"].shape == (3, 2, 2)


def test_split_filter_and_base_scene_disjointness(dataset):
    root, row, *_ = dataset
    second = dict(row, sample_id="s2", base_scene_id="b2", split="val", relative_path="other.npz")
    (root / "other.npz").write_bytes((root / "sample.npz").read_bytes())
    write_index(root, [row, second])
    assert ThermalObservationDataset(root, "val")[0]["sample_id"] == "s2"
    second["base_scene_id"] = "b1"
    write_index(root, [row, second])
    with pytest.raises(ValueError, match="base_scene_id"):
        ThermalObservationDataset(root, "train")


@pytest.mark.parametrize("path", ["../outside.npz", "/outside.npz", "C:/outside.npz",
                                  "..\\outside.npz", "\\\\server\\share\\x.npz"])
def test_path_traversal_rejected(dataset, path):
    root, row, *_ = dataset
    write_index(root, [dict(row, relative_path=path)])
    with pytest.raises(ValueError, match="path"):
        ThermalObservationDataset(root, "train")


def test_unknown_split_duplicate_ids_and_bad_hash_rejected(dataset):
    root, row, *_ = dataset
    with pytest.raises(ValueError, match="split"):
        ThermalObservationDataset(root, "missing")
    write_index(root, [row, row])
    with pytest.raises(ValueError, match="Duplicate"):
        ThermalObservationDataset(root, "train")
    write_index(root, [dict(row, sha256="bad")])
    with pytest.raises(ValueError, match="sha256"):
        ThermalObservationDataset(root, "train")


@pytest.mark.parametrize("field,value", [
    ("reference_c", np.zeros((2, 2), dtype=np.float64)),
    ("current_c", np.full((2, 2), np.nan, dtype=np.float32)),
    ("target", np.full((2, 2), 2, dtype=np.uint8)),
    ("target", np.zeros((1, 2), dtype=np.uint8)),
    ("target", np.zeros((2, 2), dtype=np.int64)),
])
def test_wrong_npz_schema_rejected(dataset, field, value):
    root, _, reference, current, target = dataset
    arrays = {"reference_c": reference, "current_c": current, "target": target}
    arrays[field] = value
    np.savez(root / "sample.npz", **arrays)
    with pytest.raises(ValueError):
        ThermalObservationDataset(root, "train", verify_hashes=False)[0]


@pytest.mark.parametrize("filename,content", [
    ("protocol.json", "[]"), ("protocol.json", "{"),
    ("index.jsonl", "{"), ("index.jsonl", "{}\n"), ("index.jsonl", ""),
])
def test_corrupt_metadata_rejected(dataset, filename, content):
    root = dataset[0]
    (root / filename).write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        ThermalObservationDataset(root, "train")


def test_missing_sample_arrays_and_sequence_boundaries(dataset):
    root, _, reference, current, _ = dataset
    loader = ThermalObservationDataset(root, "train")
    assert loader[-1]["sample_id"] == "s1"
    assert len(loader[:1]) == 1
    with pytest.raises(IndexError):
        _ = loader[1]
    np.savez(root / "sample.npz", reference_c=reference, current_c=current)
    with pytest.raises(ValueError, match="required"):
        ThermalObservationDataset(root, "train", verify_hashes=False)[0]


def test_duplicate_paths_and_missing_sample_rejected(dataset):
    root, row, *_ = dataset
    write_index(root, [row, dict(row, sample_id="s2")])
    with pytest.raises(ValueError, match="Duplicate sample path"):
        ThermalObservationDataset(root, "train")
    write_index(root, [dict(row, relative_path="missing.npz")])
    with pytest.raises(ValueError, match="path"):
        ThermalObservationDataset(root, "train")


@pytest.mark.parametrize("filename", ["protocol.json", "manifest.json", "index.jsonl"])
def test_stale_validation_metadata_rejected(dataset, filename):
    root = dataset[0]
    # A semantically harmless byte change still invalidates frozen validation.
    with (root / filename).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(ValueError, match="validation.*SHA256"):
        ThermalObservationDataset(root, "train")
    assert len(ThermalObservationDataset(root, "train", require_validated=False)) == 1


@pytest.mark.parametrize("key,value", [
    ("manifest_sha256", None), ("protocol_sha256", "bad"), ("index_sha256", "0" * 64),
    ("training_eligible_scope", None), ("training_eligible_scope", "gas_crack_detection"),
])
def test_missing_or_invalid_validation_bindings_rejected(dataset, key, value):
    root = dataset[0]
    path = root / "validation.json"
    validation = json.loads(path.read_text(encoding="utf-8"))
    if value is None:
        del validation[key]
    else:
        validation[key] = value
    write_json(path, validation)
    with pytest.raises(ValueError, match="validation"):
        ThermalObservationDataset(root, "train")
