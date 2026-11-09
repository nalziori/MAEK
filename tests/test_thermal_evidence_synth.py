"""Scene contracts, physical projection and label isolation for v2 synthesis."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from maek.thermal_evidence_synth import CELLS, generate_evidence_scene, project_cylinder
from maek.thermal_radiometry import BandRadiometry


@pytest.fixture(scope='module')
def examples():
    config = json.loads((Path(__file__).resolve().parents[1]
                        / 'config/thermal-evidence-v2.json').read_text())
    config.update(shape=[48, 64], solver_shape=[8, 12])
    camera = BandRadiometry(band_um=tuple(config['band_um']))
    return config, {i: generate_evidence_scene(i, 'train', config, camera) for i in [0, 4, 12]}


def test_full_factorial_has_no_missing_or_duplicate_cells():
    assert len(CELLS) == len(set(CELLS)) == 24
    for factor, values in enumerate([[False, True], ['low', 'high'], ['zero', 'low', 'high'], [0, 1]]):
        for value in values:
            assert sum(row[factor] == value for row in CELLS) == 24 // len(values)


def test_arc_projection_does_not_stretch_arc_linearly():
    angles = ((np.arange(100) + .5) / 100 - .5) * np.pi
    field = np.broadcast_to(angles[:, None], (100, 100))
    image, mask = project_cylinder(field, np.zeros((101, 101)), angle_rad=0,
        center_xy=[50.5, 50.5], radius_px=40, half_length_px=45)
    assert image[70, 50] == pytest.approx(np.arcsin(.5), abs=1e-4)
    assert image[50, 50] == pytest.approx(0, abs=1e-8)
    assert not mask[100, 50]


def test_aspect_ratio_matches_physical_jacket(examples):
    for scene in examples[1].values():
        row, _ = scene[0]
        p = row['physical_parameters']
        radius = p['outer_diameter_mm'] / 2000 + p['insulation_mm'] / 1000
        assert row['pose']['half_length_px'] / row['pose']['radius_px'] == pytest.approx(
            p['length_m'] / (2 * radius))


def test_latent_wall_loss_is_not_forced_positive_without_heat_drive(examples):
    for i in [0, 12]:
        row, arrays = examples[1][i][1]
        assert row['mechanism'] == 'wall_loss'
        assert np.any(arrays['wall_current_mm_audit_only'] < arrays['wall_reference_mm_audit_only'])
        assert not np.any(arrays['target'] == 1)
        np.testing.assert_array_equal(arrays['clean_reference_c'], arrays['clean_current_c'])


def test_stable_scene_has_independent_read_noise_and_no_positive_truth(examples):
    for scene in examples[1].values():
        _, arrays = scene[0]
        assert not np.any(arrays['target'] == 1)
        assert not np.array_equal(arrays['current_c'], arrays['reference_c'])


def test_quality_failures_not_training_masks(examples):
    for scene in examples[1].values():
        for row, arrays in scene[-2:]:
            assert not row['segmentation_eligible']
            assert row['quality_status'] == 'reject'
            assert np.all(arrays['target'] == 255)


def test_coating_recomputes_surface_temperature(examples):
    row, arrays = examples[1][4][4]
    assert row['mechanism'] == 'coating_change'
    assert np.max(np.abs(arrays['surface_current_c_audit_only']
                         - arrays['surface_reference_c_audit_only'])) > 0


def test_targets_match_stored_uncertainty_and_invalid_pixels(examples):
    for scene in examples[1].values():
        for row, a in scene[:5]:
            valid = a['valid_mask']
            delta = np.abs(a['clean_current_c'].astype(float) - a['clean_reference_c'])
            target = np.full(delta.shape, 255, np.uint8)
            target[valid & (delta <= a['label_low_c'])] = 0
            target[valid & (delta >= a['label_high_c'])] = 1
            np.testing.assert_array_equal(target, a['target'])
            assert not np.any(valid & a['bad_pixel_mask'])


def test_same_seed_reproduces_all_arrays(examples):
    config, scenes = examples
    for (r1, a1), (r2, a2) in zip(scenes[4], generate_evidence_scene(4, 'train', config)):
        assert r1 == r2
        for name in a1:
            np.testing.assert_array_equal(a1[name], a2[name])
