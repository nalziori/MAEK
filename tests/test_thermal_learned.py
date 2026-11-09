import numpy as np
import pytest

from maek.thermal_learned import (
    paired_iou_change,
    semantic_from_instances,
    temperature_to_rgb,
)


def test_training_temperature_transform_and_clipping():
    t = np.array([[-100, -40, 80, 200, 300]], dtype=np.float32)
    rgb = temperature_to_rgb(t)
    assert rgb.shape == (1, 5, 3) and rgb.dtype == np.uint8
    np.testing.assert_array_equal(rgb[..., 0], [[0, 0, 128, 255, 255]])
    np.testing.assert_array_equal(rgb[..., 0], rgb[..., 2])
    with pytest.raises(ValueError):
        temperature_to_rgb(np.array([[np.nan]]))


def test_empty_instances_are_background():
    result = semantic_from_instances(np.empty((0, 256, 320)), [], [], (256, 320))
    assert result.shape == (256, 320) and not result.any()


def test_overlap_class_mapping_and_mask_threshold():
    masks = np.array([[[1, 1, 0]], [[0, 1, 1]], [[0.5, 0, 0]]])
    result = semantic_from_instances(masks, [0, 2, 1], [.6, .9, .99], (1, 3))
    np.testing.assert_array_equal(result, [[1, 3, 3]])
    tied = semantic_from_instances(np.ones((2, 1, 1)), [1, 2], [.8, .8], (1, 1))
    assert tied[0, 0] == 2


def test_invalid_shape_and_classes_fail_instead_of_silent_resize():
    with pytest.raises(ValueError, match='shape'):
        semantic_from_instances(np.ones((1, 320, 320)), [0], [.8], (256, 320))
    with pytest.raises(ValueError, match='values'):
        semantic_from_instances(np.ones((1, 1, 1)), [1.5], [.8], (1, 1))


def test_iou_bootstrap_recomputes_pooled_ratio_and_preserves_pairing():
    before = np.array([[[1, 2]] * 3, [[0, 8]] * 3])
    after = np.array([[[2, 2]] * 3, [[4, 8]] * 3])
    result = paired_iou_change(before, after, repeats=100)
    assert result == paired_iou_change(before, after, repeats=100)
    for r in result['classes'].values():
        assert r['change'] == pytest.approx(.5)
        assert r['ci95'] == pytest.approx([.5, .5])
    assert paired_iou_change(before, before)['classes']['steam_leak']['ci95'] == [0, 0]
    with pytest.raises(ValueError):
        paired_iou_change(before, after[:1])
