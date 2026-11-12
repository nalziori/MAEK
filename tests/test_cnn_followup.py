"""Small CPU checks; no training or large synthetic dataset generation."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("scipy")
MODULE = Path(__file__).resolve().parents[1] / "UT/cnn_followup.py"
spec = importlib.util.spec_from_file_location("cnn_followup", MODULE)
cnn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cnn)


def test_auc_ties_and_direction():
    assert cnn.auc([0, 1, 0, 1], [0, 1, 0, 1]) == 1
    assert cnn.auc([0, 1], [1, 0]) == 0
    assert cnn.auc([0, 1], [2, 2]) == .5


def test_threshold_bound_and_strict_ties():
    scores = np.linspace(-5, 5, 6000)
    result = cnn.select_threshold(scores, confidence=.975)
    assert result["upper"] <= .007
    assert np.count_nonzero(scores > result["threshold"]) == result["allowed"]
    tied = cnn.select_threshold(np.ones(6000), confidence=.975)
    assert tied["observed_fp"] == 0
    with pytest.raises(ValueError, match="Insufficient"):
        cnn.select_threshold(np.arange(10))


def test_model_logits_and_immutable_record(tmp_path):
    torch.set_num_threads(1)
    model = cnn.PitCNN().eval()
    assert sum(p.numel() for p in model.parameters()) == 145281
    scores = cnn.logits(model, np.zeros((3, 4096), np.float32), {"rf_mean": 0., "rf_std": 1.})
    assert scores.shape == (3,)
    assert np.isfinite(scores).all()
    target = tmp_path / "record.json"
    cnn.write_once(target, {"seed": 1})
    cnn.write_once(target, {"seed": 1})
    with pytest.raises(ValueError, match="differs"):
        cnn.write_once(target, {"seed": 2})


def test_generator_independent_domains_and_resume(tmp_path):
    from maek import params

    cfg = params.load_config(MODULE.parents[1] / "config/default.yaml")
    protocol = cnn.protocol()
    protocol["counts"] = {k: 8 for k in protocol["counts"]}
    assert len(set(protocol["seeds"].values())) == len(protocol["seeds"])
    normal = cnn.generate("calibration_shifted", tmp_path, cfg, protocol)
    assert normal["RF"].shape == (8, 4096)
    assert not normal["y"].any()
    assert (normal["domain"] == 1).all()
    assert np.isfinite(normal["RF"]).all()
    again = cnn.generate("calibration_shifted", tmp_path, cfg, protocol)
    np.testing.assert_array_equal(normal["RF"], again["RF"])
    test = cnn.generate("final_shifted", tmp_path, cfg, protocol)
    assert test["y"].sum() == 4
    assert not np.array_equal(normal["RF"], test["RF"])


def test_summary_counts():
    result = cnn.summary("test", "ordinary", [0, 0, 1, 1], [.1, .7, .8, .4], .5)
    assert result["far_count"] == 1
    assert result["recall_count"] == 1
    assert result["far"] == .5
    assert result["recall"] == .5


def test_read_only_second_averaging_setting(tmp_path):
    data = np.arange(2 * 5 * 16, dtype=np.float32).reshape(2, 5, 16)
    path = tmp_path / "data.npz"
    np.savez_compressed(path, RF=data)
    np.testing.assert_array_equal(cnn.averaged_array(path, "RF"), data[1])


def test_interrupted_save_does_not_publish_final_file(tmp_path, monkeypatch):
    target = tmp_path / "train.npz"

    def interrupted(stream, **kwargs):
        stream.write(b"unfinished")
        raise OSError("simulated interrupted write")

    monkeypatch.setattr(cnn.np, "savez_compressed", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        cnn.save_dataset(target, {}, "train", cnn.protocol())
    assert not target.exists()
    assert target.with_suffix(".npz.partial").read_bytes() == b"unfinished"


def test_recovery_keeps_corrupt_source_and_reuses_valid(tmp_path):
    from maek import params

    source, destination = tmp_path / "old", tmp_path / "new"
    source.mkdir()
    destination.mkdir()
    protocol = cnn.protocol()
    protocol["counts"] = {k: 8 for k in protocol["counts"]}
    cnn.write_once(source / "protocol.json", protocol)
    cnn.write_once(source / "inputs.json", {
        "script_sha256": "70f673cf23e4798100d8e661e33e82548656ae6dfd477c839fa947a710c604f4",
        "example": "unchanged",
    })
    cnn.write_once(destination / "inputs.json", {"script_sha256": "new", "example": "unchanged"})
    cfg = params.load_config(MODULE.parents[1] / "config/default.yaml")
    valid = cnn.generate("train", source, cfg, protocol)
    (source / "validation.npz").write_bytes(b"incomplete zip")
    cnn.recover_data(source, destination, protocol)
    assert (source / "validation.npz").read_bytes() == b"incomplete zip"
    assert not (destination / "validation.npz").exists()
    restored = cnn.load_dataset(destination / "train.npz", "train", protocol)
    np.testing.assert_array_equal(restored["RF"], valid["RF"])
