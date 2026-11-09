"""Oracle GT/pipe features for OFFLINE DIAGNOSTICS ONLY.

Never use these features for inference, candidate selection, or a deployment gate.
Associations describe observations, not causes. Local rings use Chebyshev radius
5, exclude every GT defect class, and stay in the pipe (wet/damage) or outside it
(steam). Missing pipe geometry means unknown local contrast.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

import numpy as np

SCENE_NUMBERS = ('eps_jacket', 'eps_set', 'wind_mps', 'sun_k', 'sky_offset_k')
SIZE_BINS = ('<128', '128..511', '>=512')
CLIP_BINS = ('0', '(0,.1]', '>.1')
HARD_BINS = ('none', 'reflection', 'seam', 'streak', 'clamp', 'hot_bg', 'other')
JACKETS = ('aluminium', 'galvanized', 'stainless', 'unknown', 'other')
# Fixed before looking at outcomes; [lower, upper) except the unbounded ends.
SCENE_BINS = {
    'eps_jacket': ((.1, .3), ('<.1', '[.1,.3)', '>=.3')),
    'eps_set': ((.1, .3), ('<.1', '[.1,.3)', '>=.3')),
    'wind_mps': ((2., 5.), ('<2', '[2,5)', '>=5')),
    'sun_k': ((5., 15.), ('<5', '[5,15)', '>=15')),
    'sky_offset_k': ((-25., -10.), ('<-25', '[-25,-10)', '>=-10')),
}


def _number(value, name):
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
        raise TypeError(f'{name} must be a finite number or None')
    if not np.isfinite(value):
        raise ValueError(f'{name} must be finite')
    return float(value)


def _size_bin(n):
    return SIZE_BINS[0 if n < 128 else 1 if n < 512 else 2]


def _clip_bin(fraction):
    return CLIP_BINS[0 if fraction == 0 else 1 if fraction <= .1 else 2]


def _hard_tags(value):
    if value is None:
        return []
    if not isinstance(value, (list, tuple)) or any(not isinstance(v, str) for v in value):
        raise ValueError('hard must be a list of strings')
    return sorted(set(value))


def _dilate5(mask):
    padded = np.pad(mask, 5)
    out = np.zeros_like(mask)
    height, width = mask.shape
    for dy in range(11):
        for dx in range(11):
            out |= padded[dy:dy + height, dx:dx + width]
    return out


def features(sample):
    """Return JSON-safe ``{image: dict, classes: {GT_class_id: dict}}``.

    Only present GT classes appear; normal images have an empty classes mapping.
    uint16 boundary counts reconstruct round((temperature + 50) * 100) without
    clipping, so ordinary out-of-range temperatures are not invented saturation.
    """
    temperature = np.asarray(sample['temperature'], dtype=np.float64)
    truth = np.asarray(sample['mask'])
    if (temperature.ndim != 2 or temperature.size == 0 or truth.shape != temperature.shape
            or not np.isfinite(temperature).all() or not np.isin(truth, (0, 1, 2, 3)).all()):
        raise ValueError('Expected nonempty finite 2D temperatures and aligned class mask')
    pipe = sample.get('pipe')
    if pipe is not None:
        pipe = np.asarray(pipe)
        if pipe.shape != truth.shape or not np.isin(pipe, (0, 1)).all():
            raise ValueError('pipe must be an aligned finite binary mask')
        pipe = pipe.astype(bool)
    job = sample.get('job', {})
    if not isinstance(job, Mapping):
        raise TypeError('job must be a mapping')
    scene, segment = job.get('scene', {}), job.get('seg', {})
    if not isinstance(scene, Mapping) or not isinstance(segment, Mapping):
        raise TypeError('scene and seg must be mappings')
    jacket = segment.get('jacket', scene.get('jacket'))
    if jacket is not None and not isinstance(jacket, str):
        raise ValueError('jacket must be a string or None')
    clipping = (temperature < -40) | (temperature > 200)
    # Avoid overflow for valid but extreme finite float inputs.
    near_uint16_range = (temperature >= -50.01) & (temperature <= 605.36)
    raw = np.rint((temperature[near_uint16_range] + 50) * 100)
    image = {
        'temp_min_c': float(temperature.min()), 'temp_max_c': float(temperature.max()),
        'input_clip_fraction': float(clipping.mean()),
        'raw_uint16_boundary_count': int(np.count_nonzero((raw == 0) | (raw == 65535))),
        'hard': _hard_tags(job.get('hard', [])), 'jacket': jacket,
        **{key: _number(scene.get(key), key) for key in SCENE_NUMBERS},
    }
    classes = {}
    for class_id in (1, 2, 3):
        gt = truth == class_id
        pixels = int(gt.sum())
        if not pixels:
            continue
        ring = np.zeros_like(gt)
        if pipe is not None:
            domain = ~pipe if class_id == 3 else pipe
            ring = _dilate5(gt) & (truth == 0) & domain
        median = float(np.median(temperature[gt]))
        ring_pixels = int(ring.sum())
        ring_median = float(np.median(temperature[ring])) if ring_pixels else None
        if not np.isfinite(median) or (ring_median is not None and not np.isfinite(ring_median)):
            raise ValueError('Derived temperature medians are not finite')
        fraction = float(clipping[gt].mean())
        contrast = median - ring_median if ring_median is not None else None
        if contrast is not None and not np.isfinite(contrast):
            raise ValueError('Local temperature contrast is not finite')
        classes[class_id] = {
            'class_id': class_id, 'gt_pixels': pixels, 'size_bin': _size_bin(pixels),
            'gt_median_c': median, 'ring_pixels': ring_pixels, 'ring_median_c': ring_median,
            'local_contrast_c': contrast, 'gt_clip_fraction': fraction,
            'clip_bin': _clip_bin(fraction),
        }
    return {'image': image, 'classes': classes}


def _validate_finite(value):
    if isinstance(value, Mapping):
        for item in value.values():
            _validate_finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_finite(item)
    elif isinstance(value, (float, np.number)) and not np.isfinite(value):
        raise ValueError('Summary features must be finite')


def _keys(row):
    feature, scene = row['features'], row['scene']
    size, clip = feature.get('size_bin'), feature.get('clip_bin')
    if size not in SIZE_BINS or clip not in CLIP_BINS:
        raise ValueError('Expected fixed size_bin and clip_bin from features()')
    keys = [('all', 'all'), ('class', str(row['class_id'])), ('size', size), ('clip', clip)]
    # Class-stratified bins prevent class composition from hiding associations.
    keys += [(f'class_{row["class_id"]}_size', size),
             (f'class_{row["class_id"]}_clip', clip)]
    hard = _hard_tags(scene.get('hard', [])) or ['none']
    keys += [('hard', tag) for tag in sorted({x if x in HARD_BINS else 'other' for x in hard})]
    jacket = scene.get('jacket') or 'unknown'
    keys.append(('jacket', jacket if jacket in JACKETS else 'other'))
    for key, (cuts, labels) in SCENE_BINS.items():
        value = _number(scene.get(key), key)
        label = 'unknown' if value is None else labels[int(value >= cuts[0]) + int(value >= cuts[1])]
        keys.append((key, label))
    return keys


def summarize(rows):
    """Aggregate GT-class rows into fixed explanatory bins, including empty bins.

    Rows: class_id (semantic 1..3), category (one descriptive string),
    baseline_hit/any_grid_hit (binary), features (class dict), scene (image dict).
    Denominators count image-class rows, not distinct images. Hard-tag bins can
    overlap. any_grid_hit is an oracle diagnostic and MUST NOT select thresholds.
    """
    bins = {'all': ('all',), 'class': ('1', '2', '3'), 'size': SIZE_BINS,
            'clip': CLIP_BINS, 'hard': HARD_BINS, 'jacket': JACKETS}
    for class_id in (1, 2, 3):
        bins[f'class_{class_id}_size'] = SIZE_BINS
        bins[f'class_{class_id}_clip'] = CLIP_BINS
    bins.update({key: (*labels, 'unknown') for key, (_, labels) in SCENE_BINS.items()})
    groups = {
        (scope, label): {'scope': scope, 'bin': label, 'n': 0, 'baseline_hits': 0,
                         'baseline_denominator': 0, 'any_grid_hits': 0,
                         'any_grid_denominator': 0, 'categories': Counter(),
                         'low_denominator': True}
        for scope, labels in bins.items() for label in labels
    }
    count = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError('Each summary row must be a mapping')
        _validate_finite(row)
        class_id = row.get('class_id')
        baseline, any_grid = row.get('baseline_hit'), row.get('any_grid_hit')
        category = row.get('category')
        if (isinstance(class_id, (bool, np.bool_))
                or not isinstance(class_id, (int, np.integer)) or class_id not in (1, 2, 3)
                or baseline not in (0, 1) or any_grid not in (0, 1)
                or (baseline and not any_grid)
                or not isinstance(category, str) or not category
                or not isinstance(row.get('features'), Mapping)
                or not isinstance(row.get('scene'), Mapping)):
            raise ValueError('Invalid GT-class summary row')
        for key in _keys(row):
            group = groups[key]
            group['n'] += 1
            group['baseline_hits'] += int(baseline)
            group['any_grid_hits'] += int(any_grid)
            group['categories'][category] += 1
        count += 1
    for group in groups.values():
        group['baseline_denominator'] = group['any_grid_denominator'] = group['n']
        group['low_denominator'] = group['n'] < 20
        group['categories'] = dict(sorted(group['categories'].items()))
    return {'total_rows': count, 'groups': list(groups.values())}
