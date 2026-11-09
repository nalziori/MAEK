import hashlib
import json
from argparse import Namespace
from typing import ClassVar

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from maek.thermal_observation_model import build_model
from scripts import train_thermal_observation as training


@pytest.mark.parametrize("shape", [(2, 3, 32, 40), (1, 3, 31, 37)])
def test_unet_forward_backward_and_ignore(shape):
    torch.set_num_threads(1)
    model = build_model()
    inputs = torch.randn(shape)
    logits = model(inputs)
    assert logits.shape == (shape[0], 2, shape[2], shape[3])
    assert sum(p.numel() for p in model.parameters()) < 500_000
    logits.retain_grad()
    target = torch.zeros((shape[0], shape[2], shape[3]), dtype=torch.long)
    target[:, :3, :3] = 1
    target[:, -1, -1] = 255
    numerator, denominator = training.weighted_ce_parts(logits, target, torch.tensor([1., 3.]))
    loss = numerator / denominator
    expected = torch.nn.functional.cross_entropy(logits, target, weight=torch.tensor([1., 3.]),
                                                 ignore_index=255)
    torch.testing.assert_close(loss, expected)
    loss.backward()
    assert torch.count_nonzero(logits.grad[:, :, -1, -1]) == 0
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())


def test_train_class_weights_cap_and_ignore():
    target = np.zeros((2, 20, 20), dtype=np.uint8)
    target[0, 0, 0] = 1
    target[1, 0, :] = 255
    weights, counts = training.train_class_weights(target)
    np.testing.assert_array_equal(weights, np.array([1, 10], dtype=np.float32))
    assert counts == {"0": 779, "1": 1, "255": 20}
    with pytest.raises(ValueError):
        training.train_class_weights(np.zeros((1, 4, 4), dtype=np.uint8))


def test_shared_flips_preserve_alignment_and_cache():
    targets = torch.arange(24).reshape(2, 3, 4)
    inputs = targets[:, None].repeat(1, 3, 1, 1).float()
    original = inputs.clone()
    augmented, labels = training.augment_batch(inputs, targets, torch.Generator().manual_seed(19))
    torch.testing.assert_close(augmented[:, 0], labels.float())
    torch.testing.assert_close(augmented[:, 1], labels.float())
    torch.testing.assert_close(inputs, original)


class FakeDataset:
    accessed: ClassVar[list] = []

    def __init__(self, root, split):
        assert split in ("train", "dev"), "Holdout access forbidden"
        self.split = split

    def __len__(self):
        return 5

    def __getitem__(self, index):
        if index >= len(self):
            raise IndexError(index)
        self.accessed.append((self.split, index))
        target = np.zeros((16, 20), dtype=np.uint8)
        target[2:4, 3:7] = 1
        target[-1, -1] = 255
        return {"input": np.zeros((3, 16, 20), dtype=np.float32), "target": target,
                "sample_id": f"{self.split}_{index}", "base_scene_id": f"{self.split}_g{index}"}


def test_cache_reads_only_train_dev_and_smoke_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(training, "ThermalObservationDataset", FakeDataset)
    FakeDataset.accessed = []
    caches = training.cache_splits(tmp_path, limit=4)
    assert list(caches) == ["train", "dev"]
    assert all(cache["inputs"].shape == (4, 3, 16, 20) for cache in caches.values())
    assert FakeDataset.accessed == [(s, i) for s in ("train", "dev") for i in range(4)]


def test_cuda_unavailable_never_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    with pytest.raises(RuntimeError, match="CUDA"):
        training.train(Namespace(data=tmp_path, out=tmp_path / "out", epochs=30, batch_size=16,
                                 seed=20261109, device="cuda", max_seconds=1800, smoke=False))
    assert not (tmp_path / "out").exists()


def test_smoke_run_reports_scope_and_checkpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(training, "ThermalObservationDataset", FakeDataset)
    for name in ("protocol.json", "manifest.json", "index.jsonl", "validation.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    out = tmp_path / "out"
    report = training.train(Namespace(data=tmp_path, out=out, epochs=1, batch_size=4,
                                      seed=20261109, device="cpu", max_seconds=30, smoke=True))
    assert report["status"] == "smoke_passed" and not report["training_completed"]
    assert report["epochs_completed"] == 1 and report["best_epoch"] == 1
    assert report["data_splits_loaded"] == ["train", "dev"]
    checkpoint = torch.load(out / "best.pt", map_location="cpu", weights_only=True)
    model = build_model()
    model.load_state_dict(checkpoint["model_state"])
    assert json.loads((out / "training.json").read_text())["best_checkpoint_sha256"]
    with pytest.raises(FileExistsError):
        training.train(Namespace(data=tmp_path, out=out, epochs=1, batch_size=4,
                                 seed=20261109, device="cpu", max_seconds=30, smoke=True))


def test_timeout_preserves_checkpoint_and_incomplete_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(training, "ThermalObservationDataset", FakeDataset)
    for name in ("protocol.json", "manifest.json", "index.jsonl", "validation.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")
    out = tmp_path / "timeout"
    report = training.train(Namespace(data=tmp_path, out=out, epochs=1, batch_size=4,
                                      seed=20261109, device="cpu", max_seconds=1e-9, smoke=True))
    assert report["status"] == "incomplete" and not report["training_completed"]
    assert report["epochs_completed"] == 0 and report["stop_reason"] == "time_budget"
    assert report["best_epoch"] is None and not (out / "best.pt").exists()
    checkpoint = torch.load(out / "interrupted.pt", map_location="cpu", weights_only=True)
    build_model().load_state_dict(checkpoint["model_state"])
    assert report["interrupted_checkpoint_sha256"]


def test_protocol_argument_and_data_digest_binding(tmp_path):
    names = ("protocol.json", "manifest.json", "index.jsonl", "validation.json")
    for name in names:
        (tmp_path / name).write_text("{}", encoding="utf-8")
    args = Namespace(data=tmp_path, epochs=30, batch_size=16, seed=20261109,
                     device="cuda", max_seconds=1800, smoke=False)
    with pytest.raises(ValueError, match="--protocol"):
        training._check_protocol(args)
    protocol = {"training": {key: getattr(args, key) for key in
                             ("epochs", "batch_size", "seed", "device", "max_seconds")},
                "data_hashes": {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
                                for name in names}}
    args.protocol = tmp_path / "comparison.json"
    args.protocol.write_text(json.dumps(protocol), encoding="utf-8")
    assert training._check_protocol(args)["sha256"] == training.sha(args.protocol)
    args.seed = 2
    with pytest.raises(ValueError, match="training.seed"):
        training._check_protocol(args)
    args.seed = 20261109
    (tmp_path / "index.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="data SHA256"):
        training._check_protocol(args)


def test_all_ignored_pixels_have_zero_weight():
    logits = torch.randn(1, 2, 3, 4)
    targets = torch.full((1, 3, 4), 255, dtype=torch.long)
    numerator, denominator = training.weighted_ce_parts(logits, targets, torch.tensor([1., 10.]))
    assert numerator.item() == 0 and denominator.item() == 0


def test_runtime_error_preserves_metadata_before_reraising(monkeypatch, tmp_path):
    monkeypatch.setattr(training, "ThermalObservationDataset", FakeDataset)
    for name in ("protocol.json", "manifest.json", "index.jsonl", "validation.json"):
        (tmp_path / name).write_text("{}", encoding="utf-8")

    def fail_augmentation(*args):
        raise RuntimeError("fixture runtime failure")

    monkeypatch.setattr(training, "augment_batch", fail_augmentation)
    out = tmp_path / "runtime_error"
    with pytest.raises(RuntimeError, match="fixture runtime failure"):
        training.train(Namespace(data=tmp_path, out=out, epochs=1, batch_size=4,
                                 seed=20261109, device="cpu", max_seconds=30, smoke=True))
    report = json.loads((out / "training.json").read_text())
    assert report["status"] == "incomplete" and report["stop_reason"] == "runtime_error"
    assert report["error_type"] == "RuntimeError" and report["partial_epoch"] == 1
    assert not report["training_completed"] and (out / "interrupted.pt").is_file()
