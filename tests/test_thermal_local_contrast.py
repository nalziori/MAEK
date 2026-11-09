"""Behavioral contracts for opt-in thermal local contrast candidates."""
import numpy as np
import pytest

from maek import thermal_local_contrast as lc


def scene():
    pipe = np.zeros((40, 60), bool)
    pipe[5:35] = True
    temp = np.full(pipe.shape, 20., np.float32)
    pred = np.zeros(pipe.shape, np.uint8)
    pred[15:18, 15:18] = 1
    pred[15:18, 35:38] = 1
    temp[15:18, 15:18] = 20.1
    temp[15:18, 35:38] = 24
    pred[23:26, 20:23] = 2
    pred[1:3, 30:33] = 3
    return temp, pipe, pred


@pytest.mark.parametrize('candidate', lc.CANDIDATES)
def test_class_preservation_input_immutable_and_supplied_baseline(candidate, monkeypatch):
    temp, pipe, pred = scene()
    originals = [a.copy() for a in (temp, pipe, pred)]
    monkeypatch.setattr(lc.tr, 'detect_ir', lambda *a: pytest.fail('recomputed baseline'))
    result = lc.detect_ir({}, temp, pipe, candidate, baseline_prediction=pred)
    assert result.quality.status == 'ok'
    np.testing.assert_array_equal(result.mask[pred != 1], pred[pred != 1])
    for actual, original in zip((temp, pipe, pred), originals):
        np.testing.assert_array_equal(actual, original)
    assert not np.shares_memory(result.mask, pred)


@pytest.mark.parametrize('candidate', [x for x in lc.CANDIDATES if x != 'baseline'])
def test_weak_blob_removed_small_hot_blob_retained(candidate):
    temp, pipe, pred = scene()
    result = lc.detect_ir({}, temp, pipe, candidate, baseline_prediction=pred)
    assert not result.mask[15:18, 15:18].any()
    assert (result.mask[15:18, 35:38] == 1).all()


@pytest.mark.parametrize('candidate', lc.CANDIDATES)
def test_masked_background_invariance(candidate):
    temp, pipe, pred = scene()
    changed = temp.copy()
    changed[~pipe] = np.arange((~pipe).sum()) * 1000.
    before = lc.detect_ir({}, temp, pipe, candidate, baseline_prediction=pred)
    after = lc.detect_ir({}, changed, pipe, candidate, baseline_prediction=pred)
    np.testing.assert_array_equal(before.mask, after.mask)


@pytest.mark.parametrize('fault', ['nan', 'inf', 'small_pipe', 'empty_pipe', 'saturation'])
def test_bad_frame_abstains_instead_of_normal(fault):
    temp, pipe, pred = scene()
    raw = None
    if fault == 'nan':
        temp[0, 0] = np.nan
    elif fault == 'inf':
        temp[0, 0] = np.inf
    elif fault in ('small_pipe', 'empty_pipe'):
        pipe[:] = False
        if fault == 'small_pipe':
            pipe[0, :10] = True
    else:
        raw = np.full(temp.shape, 7000, np.uint16)
        raw[0, 0] = 65535
    result = lc.detect_ir({}, temp, pipe, 'wet_local_relative',
                          baseline_prediction=pred, raw_uint16=raw)
    assert result.mask is None
    assert result.quality.status == 'abstain'
    assert result.quality.reasons


def test_boundary_and_insufficient_neighbors_preserve_component():
    temp = np.full((20, 20), 20., np.float32)
    pipe = np.ones(temp.shape, bool)
    pred = np.ones(temp.shape, np.uint8)
    result = lc.detect_ir({}, temp, pipe, 'wet_local_relative', baseline_prediction=pred)
    np.testing.assert_array_equal(result.mask, pred)
    assert result.quality.abstained_components == 1
    assert result.quality.abstained_pixels == 400
    assert result.quality.boundary_pixels > 0


def test_saturation_not_inferred_from_float_temperature_extrema():
    temp, pipe, pred = scene()
    temp[0, 0] = -50
    temp[0, 1] = 605.35
    result = lc.detect_ir({}, temp, pipe, baseline_prediction=pred)
    assert result.quality.saturation_checked is False
    assert result.quality.status == 'ok'


def test_shape_and_raw_contracts():
    temp, pipe, pred = scene()
    with pytest.raises(ValueError):
        lc.detect_ir({}, temp, pipe[:, :-1], baseline_prediction=pred)
    with pytest.raises(ValueError):
        lc.detect_ir({}, temp, pipe, 'unknown', baseline_prediction=pred)
    with pytest.raises(ValueError):
        lc.detect_ir({}, temp, pipe, raw_uint16=temp, baseline_prediction=pred)
    with pytest.raises(ValueError):
        lc.detect_ir({}, temp, pipe, baseline_prediction=pred + 4)


def test_registry_is_frozen():
    from dataclasses import FrozenInstanceError
    with pytest.raises(TypeError):
        lc.CANDIDATES['new'] = lc.CANDIDATES['baseline']
    with pytest.raises(FrozenInstanceError):
        lc.CANDIDATES['baseline'].radius = 2


def test_baseline_called_once_and_no_wet_is_identity(monkeypatch):
    temp, pipe, pred = scene()
    pred[pred == 1] = 0
    calls = []

    def baseline(*args):
        calls.append(args)
        return pred

    monkeypatch.setattr(lc.tr, 'detect_ir', baseline)
    result = lc.detect_ir({}, temp, pipe, 'wet_local_mad')
    assert len(calls) == 1
    np.testing.assert_array_equal(result.mask, pred)
    assert result.quality.abstained_components == 0


def test_single_pixel_effect_of_optional_median_is_explicit():
    temp, pipe, pred = scene()
    pred[pred == 1] = 0
    temp[:] = 20
    pred[20, 30] = 1
    temp[20, 30] = 25
    raw = lc.detect_ir({}, temp, pipe, 'wet_local_relative', baseline_prediction=pred)
    smooth = lc.detect_ir({}, temp, pipe, 'wet_local_median3_mad', baseline_prediction=pred)
    assert raw.mask[20, 30] == 1
    assert smooth.mask[20, 30] == 0  # Known loss mechanism, not a recall claim.


def test_optional_mad_rejects_low_signal_against_textured_pipe():
    temp, pipe, pred = scene()
    pred[:] = 0
    yy, xx = np.indices(temp.shape)
    temp[:] = 20 + ((xx + yy) % 2) * 4
    pred[18:21, 28:31] = 1
    temp[18:21, 28:31] = 25
    relative = lc.detect_ir({}, temp, pipe, 'wet_local_relative', baseline_prediction=pred)
    mad = lc.detect_ir({}, temp, pipe, 'wet_local_mad', baseline_prediction=pred)
    assert (relative.mask[18:21, 28:31] == 1).all()
    assert not mad.mask[18:21, 28:31].any()


def test_chunked_support_and_image_boundary_are_deterministic():
    temp = np.full((40, 60), 20., np.float32)
    pipe = np.ones(temp.shape, bool)
    pred = np.zeros(temp.shape, np.uint8)
    pred[::2, ::2] = 1  # 600 sparse points, crossing the 512-point chunk.
    a = lc.detect_ir({}, temp, pipe, 'wet_local_relative', baseline_prediction=pred)
    b = lc.detect_ir({}, temp, pipe, 'wet_local_relative', baseline_prediction=pred)
    np.testing.assert_array_equal(a.mask, b.mask)
    assert not a.mask.any()
    assert a.quality.boundary_pixels > 0
    assert a.quality == b.quality


def test_low_raw_boundary_and_outside_pipe_component():
    temp, pipe, pred = scene()
    pred[0:2, 1:3] = 1
    result = lc.detect_ir({}, temp, pipe, 'wet_local_relative', baseline_prediction=pred)
    assert (result.mask[0:2, 1:3] == 1).all()
    assert result.quality.abstained_components == 1
    raw = np.full(temp.shape, 7000, np.uint16)
    raw[0, 0] = 0
    result = lc.detect_ir({}, temp, pipe, baseline_prediction=pred, raw_uint16=raw)
    assert result.mask is None
    assert result.quality.saturated_pixels == 1
