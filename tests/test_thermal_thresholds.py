import copy

import numpy as np
import pytest

from maek.thermal_thresholds import (
    BASELINE,
    GRID,
    recoverability,
    threshold_mask,
    unique_grid_metrics,
)


def test_grid_exactly_27_includes_current_baseline():
    assert len(GRID) == len(set(GRID.values())) == 27
    assert GRID[BASELINE] == (.25, .25, .25)


def test_strict_threshold_and_overlap_recomposed_not_pixel_erased():
    masks = np.ones((2, 1, 2), np.uint8)
    pred = threshold_mask(masks, np.array([0, 2]), np.array([.4, .25], np.float32), (1, 2), (.4, .25, .1))
    assert np.all(pred == 3)
    assert not threshold_mask(masks, np.array([0, 2]), np.array([.4, .25], np.float32),
                              (1, 2), (.4, .25, .25)).any()


def test_empty_and_bad_instances_are_not_silently_normal():
    assert not threshold_mask(np.empty((0, 2, 3)), np.array([]), np.array([]), (2, 3), (.1,) * 3).any()
    with pytest.raises(ValueError):
        threshold_mask(np.ones((1, 2, 3)), np.array([5]), np.array([.2]), (2, 3), (.25,) * 3)
    with pytest.raises(ValueError):
        threshold_mask(np.ones((1, 2, 3)), np.array([0]), np.array([.2]), (2, 3), (.05,) * 3)


def test_error_categories_disentangle_threshold_and_ownership():
    gt = np.ones((2, 3), np.uint8)
    masks = np.ones((2, 2, 3), np.uint8)
    classes = np.array([0, 2])
    for scores, expected in [(np.array([.2, .15]), 'matching_coverage_below_baseline_confidence'),
                             (np.array([.3, .4]), 'cross_class_overlap_ownership')]:
        base = threshold_mask(masks, classes, scores, gt.shape, (.25,) * 3)
        floor = threshold_mask(masks, classes, scores, gt.shape, (.1,) * 3)
        assert recoverability(gt, masks, classes, scores, base, floor)[0]['category'] == expected


def test_all27_metrics_match_prediction_and_inputs_unchanged():
    gt = np.array([[1, 1, 0], [0, 0, 3]], np.uint8)
    masks = np.array([[[1, 1, 0], [0, 0, 0]], [[0, 0, 0], [0, 0, 1]]], np.uint8)
    original = masks.copy()
    scores, classes = np.array([.2, .7]), np.array([0, 2])
    metrics, preds = unique_grid_metrics(gt, masks, classes, scores)
    assert len(metrics) == len(preds) == 27
    assert metrics[BASELINE]['classes']['wet_insulation']['image_hits'] == 0
    assert metrics['w10_d25_s25']['classes']['wet_insulation']['image_hits'] == 1
    np.testing.assert_array_equal(masks, original)


@pytest.mark.parametrize('failure', ['none', 'no_normals', 'missing_class', 'new_alarm', 'lost_hit', 'class_fp'])
def test_selection_rejects_unsafe_or_unassessable_candidates(failure):
    from scripts.evaluate_thermal_thresholds import gate
    names = ['wet_insulation', 'insulation_damage', 'steam_leak']
    baseline = {'normal_images': 10, 'class_fp_per_image': dict.fromkeys(names, 0.),
                'classes': {c: {'image_recall': .5, 'image_denominator': 10} for c in names}}
    candidate = copy.deepcopy(baseline)
    candidate['classes'][names[0]]['image_recall'] = .6
    row = {'results': {BASELINE: baseline, 'candidate': candidate},
           'transitions': {'candidate': {'new_normal_alarms': [], 'lost_hits': {c: [] for c in names}}}}
    if failure == 'no_normals':
        baseline['normal_images'] = 0
    elif failure == 'missing_class':
        baseline['classes'][names[0]]['image_denominator'] = 0
    elif failure == 'new_alarm':
        row['transitions']['candidate']['new_normal_alarms'] = ['image']
    elif failure == 'lost_hit':
        row['transitions']['candidate']['lost_hits'][names[0]] = ['image']
    elif failure == 'class_fp':
        candidate['class_fp_per_image'][names[0]] = .1
    assert gate(row, row, 'candidate') == (failure == 'none')
