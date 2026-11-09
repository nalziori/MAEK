"""Independent non-wrapping procedural fixtures, no generator truth as input."""
import cv2
import numpy as np
import pytest

from maek.thermal_registration_quality import DEFAULT_POLICY, assess_registration


def texture(seed=45, shape=(128, 160)):
    rng = np.random.default_rng(seed)
    image = cv2.GaussianBlur(rng.normal(size=shape).astype(np.float32), (0, 0), 2)
    return (25 + image / image.std() * 3).astype(np.float32)


def translated(image, dx, dy):
    return cv2.warpAffine(image, np.array([[1, 0, dx], [0, 1, dy]], np.float32),
                          (image.shape[1], image.shape[0]), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


@pytest.mark.parametrize('shift', [(0, 0), (.2, -.2), (-.25, .15)])
def test_aligned_and_small_subpixel_motion_allowed(shift):
    ref = texture()
    got = assess_registration(ref, translated(ref, *shift))
    assert got['can_infer'], got
    assert np.linalg.norm(np.array(got['estimated_shift_px']) - shift) < .15


@pytest.mark.parametrize('shift', [(1, 0), (-1, 0), (0, 1), (0, -1), (.8, -.6),
                                  (-.8, .6), (3, 3), (-3, -3)])
def test_nonwrapping_translation_rejected_with_correct_direction(shift):
    ref = texture()
    got = assess_registration(ref, translated(ref, *shift))
    assert not got['can_infer'], got
    assert got['reason'] == 'excess_residual_translation', got
    assert np.linalg.norm(np.array(got['estimated_shift_px']) - shift) < .25


@pytest.mark.parametrize('shift', [(0, 0), (1.2, -.7)])
def test_local_thermal_change_brightness_noise_and_shared_bad_pixels(shift):
    rng = np.random.default_rng(73)
    ref = texture(19)
    cur = translated(ref, *shift) + 2.5
    yy, xx = np.indices(ref.shape)
    cur += 8 * np.exp(-((xx - 26)**2 + (yy - 22)**2) / 160)
    ref += rng.normal(0, .08, ref.shape).astype(np.float32)
    cur += rng.normal(0, .08, cur.shape).astype(np.float32)
    ref[10::25, 10::30] = 0
    cur[10::25, 10::30] = 0
    got = assess_registration(ref, cur)
    assert got['can_infer'] == (shift == (0, 0)), got
    assert got['estimated_shift_px'] is not None, got
    assert np.linalg.norm(np.array(got['estimated_shift_px']) - shift) < .25


def test_brightness_change_is_not_claimed_as_calibration_validation():
    ref = texture()
    got = assess_registration(ref, ref + 7)
    assert got['can_infer']
    assert got['field_calibrated'] is False


@pytest.mark.parametrize('kind', ['flat', 'noisy_flat', 'straight_edge', 'periodic'])
def test_ambiguous_content_is_not_zero_motion_evidence(kind):
    yy, xx = np.indices((128, 160))
    image = np.full((128, 160), 25, np.float32)
    if kind == 'noisy_flat':
        image += np.random.default_rng(5).normal(0, .1, image.shape).astype(np.float32)
    elif kind == 'straight_edge':
        image += (xx > 80) * 5
    elif kind == 'periodic':
        image += (3 * np.sin(xx * np.pi / 8) + 3 * np.cos(yy * np.pi / 8)).astype(np.float32)
    got = assess_registration(image, image.copy())
    assert not got['can_infer'], got
    assert got['estimated_shift_px'] is None


def test_inconsistent_local_motions_rejected():
    ref = texture()
    cur = ref.copy()
    cur[:64] = translated(ref, 2, 0)[:64]
    cur[64:] = translated(ref, -2, 0)[64:]
    got = assess_registration(ref, cur)
    assert not got['can_infer'], got
    assert got['reason'] == 'inconsistent_tile_motion'


def test_diagonal_threshold_is_euclidean_not_per_axis():
    ref = texture()
    got = assess_registration(ref, translated(ref, .45, .45))
    assert got['reason'] == 'excess_residual_translation', got


def test_unrelated_views_fail_closed():
    assert not assess_registration(texture(21), texture(93))['can_infer']


def test_backend_nonconvergence_is_indeterminate(monkeypatch):
    def fail(*args, **kwargs):
        raise cv2.error('deliberate nonconvergence fixture')

    monkeypatch.setattr(cv2, 'findTransformECC', fail)
    got = assess_registration(texture(), texture())
    assert got['reason'] == 'insufficient_reliable_tiles'
    assert not got['can_infer']


@pytest.mark.parametrize('bad', [np.zeros((4, 4)), np.zeros((128, 160, 3)),
                                np.full((128, 160), np.nan),
                                np.full((128, 160), np.inf), None])
def test_bad_input_fails_closed(bad):
    got = assess_registration(texture(), bad)
    assert not got['can_infer']
    assert got['reason'] == 'invalid_input'


def test_does_not_mutate_inputs_or_defaults():
    ref, cur = texture(), texture() + 1
    ref_before, cur_before = ref.copy(), cur.copy()
    got = assess_registration(ref, cur)
    np.testing.assert_array_equal(ref, ref_before)
    np.testing.assert_array_equal(cur, cur_before)
    got['policy']['max_error_px'] = 999
    assert DEFAULT_POLICY['max_error_px'] == .5


@pytest.mark.parametrize('policy', [{'max_error_px': float('nan')}, {'max_error_px': -1},
                                   {'min_agreeing_tiles': 1}, {'true_shift': 0}])
def test_invalid_policy_is_not_hidden(policy):
    with pytest.raises(ValueError):
        assess_registration(texture(), texture(), policy)


@pytest.mark.parametrize('policy', [None, {'max_error_px': '.5'}, {'min_ecc': True}])
def test_mistyped_policy_is_not_hidden(policy):
    with pytest.raises(TypeError):
        assess_registration(texture(), texture(), policy)
