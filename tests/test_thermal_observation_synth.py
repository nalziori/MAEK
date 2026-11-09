import numpy as np

from maek.thermal_observation_synth import camera_pair, generate_scene


def test_stable_pair_independent_noise_and_no_false_ground_truth():
    a = np.full((32, 40), 25.)
    arrays, low, high = camera_pair(a, a, sigma=.1, quantization=.01, blur_sigma=.7,
        seed_reference=1, seed_current=2, bad_pixel_mask=np.zeros(a.shape, bool))
    assert not arrays['target'].any()
    assert not np.array_equal(arrays['reference_c'], arrays['current_c'])
    assert low < high


def test_target_uses_post_psf_change_and_ignores_saturation():
    a = np.full((32, 40), 25.)
    b = a.copy()
    b[16, 20] += 20
    a[0:8] = b[0:8] = 300
    arrays, _low, high = camera_pair(a, b, sigma=.03, quantization=.01, blur_sigma=1.,
        seed_reference=3, seed_current=4, bad_pixel_mask=np.zeros(a.shape, bool))
    delta = np.abs(arrays['clean_current_c'].astype(float) - arrays['clean_reference_c'])
    assert np.all(arrays['target'][delta >= high] == 1)
    assert np.all(arrays['target'][0:4] == 255)
    assert np.sum(arrays['target'] == 1) > 1  # optical spread, not latent patch mask


def test_scene_all_mechanisms_same_factors_reproducible():
    first = generate_scene(1, 'train', shape=(40, 48))
    second = generate_scene(1, 'train', shape=(40, 48))
    assert len(first) == 5
    assert len({str(row['factors']) for row, _ in first}) == 1
    for (row, arrays), (row2, arrays2) in zip(first, second):
        assert row == row2
        for name in arrays:
            np.testing.assert_array_equal(arrays[name], arrays2[name])
        assert row['solver_relative_residual'] < 1e-8
        assert row['solver_energy_error'] < 1e-7
