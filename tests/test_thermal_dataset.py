import json

import numpy as np
import pytest
from PIL import Image

from maek.thermal_dataset import evaluate_arrays, load_split


def test_load_split_preserves_temperature(tmp_path):
    root = tmp_path / "train"
    for name in ("images", "masks"):
        (root / name).mkdir(parents=True)
    Image.fromarray(np.array([[5000, 5123], [4000, 6000]], dtype=np.uint16)).save(
        root / "images" / "ir00000.png"
    )
    Image.fromarray(np.array([[0, 1], [0, 0]], dtype=np.uint8)).save(
        root / "masks" / "ir00000.png"
    )
    (root / "jobs.json").write_text(
        json.dumps([{"job_id": "ir00000", "condition": "train"}]), encoding="utf-8"
    )
    (root / "val.txt").write_text("./images/ir00000.png\n", encoding="utf-8")
    sample = next(iter(load_split(root, "val")))
    assert sample["job"]["job_id"] == "ir00000"
    assert sample["temperature"].dtype == np.float32
    assert sample["temperature"][0, 1] == pytest.approx(1.23, abs=0.01)
    assert sample["mask"][0, 1] == 1


def test_metrics_distinguish_wrong_class_and_empty_predictions():
    truth = np.array([[0, 1, 1], [0, 2, 2]], dtype=np.uint8)
    perfect = evaluate_arrays([(truth, truth)])
    assert perfect["classes"]["wet_insulation"]["iou"] == 1
    assert perfect["classes"]["wet_insulation"]["image_recall"] == 1
    wrong = np.where(truth == 1, 2, 0).astype(np.uint8)
    result = evaluate_arrays([(truth, wrong), (np.zeros_like(truth), wrong)])
    assert result["classes"]["wet_insulation"]["image_recall"] == 0
    assert result["confusion"][1][2] == 2
    assert result["normal_image_false_alarm_rate"] == 1
    assert result["classes"]["wet_insulation"]["image_denominator"] == 1


def test_wrong_class_component_counts_class_fp():
    gt = np.ones((9, 9), dtype=np.uint8)
    pred = np.full((9, 9), 2, dtype=np.uint8)
    m = evaluate_arrays([(gt, pred)])
    assert m['legacy_fp_per_image'] == 0
    assert m['class_fp_per_image']['insulation_damage'] == 1


def test_wilson_boundaries():
    from maek.thermal_dataset import wilson95

    assert wilson95(0, 0) is None
    assert wilson95(0, 10)[1] == pytest.approx(0.2775328, abs=1e-6)
    assert wilson95(10, 10)[0] == pytest.approx(0.7224672, abs=1e-6)
    with pytest.raises(ValueError):
        wilson95(11, 10)


def test_thirty_percent_boundary():
    gt = np.ones((2, 5), dtype=np.uint8)
    pred = np.zeros_like(gt)
    pred.flat[:3] = 1
    assert evaluate_arrays([(gt, pred)])['classes']['wet_insulation']['image_recall'] == 1
    pred.flat[2] = 0
    assert evaluate_arrays([(gt, pred)])['classes']['wet_insulation']['image_recall'] == 0


@pytest.mark.parametrize('pred', [np.zeros((1, 1)), np.full((2, 5), 4)])
def test_invalid_prediction_rejected(pred):
    with pytest.raises(ValueError):
        evaluate_arrays([(np.ones((2, 5)), pred)])
