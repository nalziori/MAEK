"""Opt-in post-NMS class confidence sweep; no defaults or trained weights change."""
from __future__ import annotations

from itertools import product

import numpy as np

from maek.thermal_learned import semantic_from_instances

LEVELS = (.10, .25, .40)
GRID = {f'w{int(w * 100):02d}_d{int(d * 100):02d}_s{int(s * 100):02d}': (w, d, s)
        for w, d, s in product(LEVELS, repeat=3)}
BASELINE = 'w25_d25_s25'


def threshold_mask(masks, classes, scores, shape, thresholds):
    """Filter instances BEFORE overlap ownership. Strict > matches native NMS."""
    masks, classes, scores = map(np.asarray, (masks, classes, scores))
    levels = np.asarray(thresholds, dtype=np.float32)
    if levels.shape != (3,) or not np.isfinite(levels).all() or np.any((levels < .1) | (levels > 1)):
        raise ValueError('Expected three finite thresholds at or above cache floor 0.10')
    # Validate every instance, including those that would be removed.
    semantic_from_instances(masks, classes, scores, shape)
    keep = scores > levels[classes.astype(int)]
    return semantic_from_instances(masks[keep], classes[keep], scores[keep], shape)


def recoverability(truth, masks, classes, scores, baseline, floor):
    """Class-image failure mechanisms conditional on retained conf>.10 NMS output.

    These are observable proxy categories, never physical or causal diagnoses.
    Candidate union ignores cross-class ownership to separate confidence and
    overlap failures. GT is used only for offline analysis.
    """
    rows = []
    for cls in range(1, 4):
        target = truth == cls
        pixels = int(target.sum())
        if not pixels:
            continue
        same = classes == cls - 1
        union = np.any(masks[same] > .5, axis=0) if same.any() else np.zeros(truth.shape, bool)
        retained = same & (scores > np.float32(.25))
        high = np.any(masks[retained] > .5, axis=0) if retained.any() else np.zeros(truth.shape, bool)
        other = np.any(masks[~same] > .5, axis=0) if (~same).any() else np.zeros(truth.shape, bool)

        def coverage(mask, target=target, pixels=pixels):
            return float(np.count_nonzero(target & mask) / pixels)

        base_fraction = coverage(baseline == cls)
        floor_fraction = coverage(floor == cls)
        union_fraction, high_fraction, other_fraction = map(coverage, (union, high, other))
        if base_fraction >= .3:
            category = 'baseline_hit'
        elif union_fraction >= .3 and high_fraction < .3:
            category = 'matching_coverage_below_baseline_confidence'
        elif high_fraction >= .3:
            category = 'cross_class_overlap_ownership'
        elif other_fraction >= .3:
            category = 'other_class_overlap_at_cache_floor'
        elif union_fraction > 0:
            category = 'insufficient_same_class_mask_coverage'
        else:
            category = 'no_same_class_overlap_at_cache_floor'
        rows.append({'class_id': cls, 'gt_class_pixels': pixels, 'baseline_coverage': base_fraction,
                     'floor_semantic_coverage': floor_fraction, 'same_class_union_coverage': union_fraction,
                     'above_025_union_coverage': high_fraction, 'other_class_union_coverage': other_fraction,
                     'baseline_hit': base_fraction >= .3, 'category': category,
                     'same_class_instances_at_floor': int(same.sum())})
    return rows


def unique_grid_metrics(truth, masks, classes, scores):
    """Evaluate every setting; identical masks share exact one-image metrics."""
    from maek.thermal_dataset import evaluate_arrays

    metrics, predictions, seen = {}, {}, {}
    for name, levels in GRID.items():
        prediction = threshold_mask(masks, classes, scores, truth.shape, levels)
        identity = prediction.tobytes()
        if identity not in seen:
            seen[identity] = evaluate_arrays([(truth, prediction)])
        metrics[name], predictions[name] = seen[identity], prediction
    return metrics, predictions
