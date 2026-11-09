import numpy as np
import pytest

from maek.thermal_filter import component_features, filter_wet_components


def test_local_contrast_and_rotation_invariance():
    pipe = np.zeros((40, 80), bool)
    pipe[10:30] = True
    component = np.zeros_like(pipe)
    component[16:24, 34:46] = True
    temperature = np.full(pipe.shape, 20, np.float32)
    temperature[component] = 23
    f = component_features(temperature, pipe, component)
    rotated = component_features(temperature.T, pipe.T, component.T)
    assert f['local_median_contrast_c'] == pytest.approx(3)
    assert f['across_pipe_fraction'] == pytest.approx(8 / 20)
    assert f['along_extent_px'] == pytest.approx(12)
    for key in f:
        assert f[key] == pytest.approx(rotated[key])


def test_empty_component_rejected():
    with pytest.raises(ValueError):
        component_features(np.zeros((5, 5)), np.ones((5, 5), bool), np.zeros((5, 5), bool))


def test_filter_removes_small_weak_but_preserves_strong_and_other_classes():
    pipe = np.zeros((50, 100), bool)
    pipe[10:40] = True
    pred = np.zeros(pipe.shape, np.uint8)
    pred[20:25, 20:25] = 1
    pred[20:25, 50:55] = 1
    pred[20:25, 70:75] = 2
    pred[2:5, 30:35] = 3
    temp = np.full(pipe.shape, 20, np.float32)
    temp[20:25, 20:25] = 21
    temp[20:25, 50:55] = 25
    old = pred.copy()
    result = filter_wet_components(temp, pipe, pred, 'wet_width12_area80')
    assert not result[20:25, 20:25].any()
    assert (result[20:25, 50:55] == 1).all()
    np.testing.assert_array_equal(result[old >= 2], old[old >= 2])
    np.testing.assert_array_equal(pred, old)


def test_filter_unknown_rejected():
    with pytest.raises(ValueError):
        filter_wet_components(np.zeros((5, 5)), np.ones((5, 5), bool),
                              np.zeros((5, 5), np.uint8), 'unknown')
