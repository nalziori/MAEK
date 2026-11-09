"""Offline explanatory features; no model inference or selection."""
import json

import numpy as np
import pytest

from maek.thermal_error_analysis import features, summarize


def sample(shape=(15, 15)):
    return {'temperature': np.full(shape, 20.), 'mask': np.zeros(shape, dtype=np.uint8),
            'pipe': np.ones(shape, dtype=bool),
            'job': {'scene': {'eps_jacket': .1, 'eps_set': .12, 'wind_mps': 2.,
                              'sun_k': 5., 'sky_offset_k': -25.},
                    'seg': {'jacket': 'aluminium'}, 'hard': ['reflection']}}


def test_normal_features_are_json_safe_and_do_not_invent_gt():
    result = features(sample())
    assert result['classes'] == {}
    assert result['image']['temp_min_c'] == result['image']['temp_max_c'] == 20
    assert result['image']['hard'] == ['reflection']
    assert result['image']['jacket'] == 'aluminium'
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize('class_id', [1, 2, 3])
def test_local_ring_excludes_other_gt_and_respects_pipe_domain(class_id):
    s = sample()
    s['mask'][7, 7] = class_id
    s['temperature'][7, 7] = 30
    s['pipe'][:, 8:] = False
    if class_id == 3:
        s['pipe'] = ~s['pipe']
    s['temperature'][:, 8:] = 100
    s['mask'][6, 7] = 2 if class_id != 2 else 1
    s['temperature'][6, 7] = 150
    out = features(s)['classes'][class_id]
    assert out['ring_pixels'] == 64  # 11 rows * 6 columns minus two GT pixels.
    assert out['ring_median_c'] == 20
    assert out['local_contrast_c'] == 10


@pytest.mark.parametrize('pixels,expected', [(127, '<128'), (128, '128..511'),
                                              (511, '128..511'), (512, '>=512')])
def test_size_bin_boundaries(pixels, expected):
    s = sample((1, pixels))
    s['mask'][:] = 1
    out = features(s)['classes'][1]
    assert out['size_bin'] == expected
    assert out['ring_pixels'] == 0
    assert out['ring_median_c'] is None


@pytest.mark.parametrize('clipped,expected', [(0, '0'), (1, '(0,.1]'), (2, '>.1')])
def test_clip_boundaries_and_raw_uint16_reconstruction(clipped, expected):
    s = sample((1, 10))
    s['mask'][:] = 1
    s['temperature'][0, :clipped] = -50
    out = features(s)
    assert out['classes'][1]['clip_bin'] == expected
    assert out['image']['raw_uint16_boundary_count'] == clipped
    s['temperature'][0, :2] = [-40, 200]
    assert features(s)['classes'][1]['gt_clip_fraction'] == 0
    s['temperature'][0, :2] = [-50, 605.35]
    assert features(s)['image']['raw_uint16_boundary_count'] == 2


def test_missing_pipe_means_unknown_local_contrast():
    s = sample()
    s.pop('pipe')
    s['mask'][0, 0] = 3
    out = features(s)['classes'][3]
    assert out['ring_pixels'] == 0
    assert out['ring_median_c'] is out['local_contrast_c'] is None


def test_hot_bg_hard_tag_is_preserved_and_grouped():
    s = sample()
    s['job']['hard'] = ['hot_bg', 'hot_bg']
    assert features(s)['image']['hard'] == ['hot_bg']
    r = row()
    r['scene'] = features(s)['image']
    groups = {(g['scope'], g['bin']): g for g in summarize([r])['groups']}
    assert groups['hard', 'hot_bg']['n'] == 1
    assert groups['hard', 'other']['n'] == 0


@pytest.mark.parametrize('change', [
    {'temperature': np.empty((0, 2)), 'mask': np.empty((0, 2))},
    {'temperature': np.full((15, 15), np.nan)},
    {'temperature': np.full((15, 15), np.inf)},
    {'mask': np.full((15, 15), 4)}, {'mask': np.zeros((2, 2))},
    {'pipe': np.full((15, 15), np.nan)}, {'pipe': np.zeros((2, 2))},
    {'job': {'scene': {'wind_mps': np.nan}}},
])
def test_invalid_input_is_rejected(change):
    s = sample()
    s.update(change)
    with pytest.raises(ValueError):
        features(s)


def row(baseline=False, any_grid=True, category='low_score'):
    s = sample()
    s['mask'][7, 7] = 1
    f = features(s)
    return {'class_id': 1, 'category': category, 'baseline_hit': baseline,
            'any_grid_hit': any_grid, 'features': f['classes'][1], 'scene': f['image']}


def test_summary_counts_fixed_bins_and_low_denominator_without_dropping_empty_bins():
    out = summarize([row()] * 19 + [row(True, True, 'hit')])
    groups = {(g['scope'], g['bin']): g for g in out['groups']}
    total = groups['all', 'all']
    assert total['n'] == total['baseline_denominator'] == total['any_grid_denominator'] == 20
    assert total['baseline_hits'] == 1 and total['any_grid_hits'] == 20
    assert not total['low_denominator']
    assert total['categories'] == {'hit': 1, 'low_score': 19}
    assert groups['size', '>=512']['n'] == 0
    assert groups['size', '>=512']['low_denominator']
    assert groups['hard', 'reflection']['n'] == 20
    assert summarize([row()])['groups'][0]['low_denominator']
    empty = summarize([])
    assert empty['total_rows'] == 0 and empty['groups'][0]['n'] == 0
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize('change', [
    {'class_id': 0}, {'class_id': 1.0}, {'baseline_hit': np.nan}, {'any_grid_hit': 2},
    {'baseline_hit': True, 'any_grid_hit': False}, {'category': ''},
    {'features': {'gt_pixels': np.nan}}, {'scene': {'wind_mps': np.inf}},
])
def test_invalid_summary_rows_fail(change):
    r = row()
    r.update(change)
    with pytest.raises(ValueError):
        summarize([r])
