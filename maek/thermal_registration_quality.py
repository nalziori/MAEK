"""Measured-image translation quality check; never a field-calibrated quality label.

Median filtering suppresses isolated detector spikes. Independent quadrant ECC
fits, initialized by phase correlation, must agree in at least three quadrants.
This rejects the aperture problem, poor overlap and unreliable estimates rather
than interpreting failure as zero motion. No image, label or metadata is returned
as a corrected/registered observation. Local temperature changes may cause a
conservative rejection. Brightness offset is intentionally not a calibration test.

Algorithm references (thresholds below are development assumptions):
https://docs.opencv.org/4.10.0/dc/d6b/group__video__track.html
https://docs.opencv.org/3.4.19/d7/df3/group__imgproc__motion.html
"""
from __future__ import annotations

from collections.abc import Mapping
from itertools import combinations
from numbers import Real
from types import MappingProxyType

import cv2
import numpy as np

DEFAULT_POLICY = MappingProxyType({
    'version': 1,
    'max_error_px': .5,
    'min_side_px': 64,
    'min_texture_std_c': .15,
    'min_gradient_eigen_ratio': .01,
    'min_phase_response': .08,
    'min_ecc': .90,
    'max_search_px': 8.,
    'max_consensus_spread_px': .25,
    'min_agreeing_tiles': 3,
    'periodic_correlation_limit': .98,
})


def _policy(value):
    result = dict(DEFAULT_POLICY)
    if not isinstance(value, Mapping):
        raise TypeError('policy must be a mapping of known numerical options')
    if set(value) - set(result):
        raise ValueError('Unknown registration policy option')
    result.update(value)
    for key, number in result.items():
        if isinstance(number, bool) or not isinstance(number, Real):
            raise TypeError(f'Invalid policy option: {key}')
        try:
            finite = np.isfinite(float(number))
        except (ValueError, TypeError) as exc:
            raise ValueError(f'Invalid policy option: {key}') from exc
        if not finite or number <= 0:
            raise ValueError(f'Invalid policy option: {key}')
    if result['version'] != 1 or result['min_agreeing_tiles'] not in (3, 4):
        raise ValueError('Unsupported version or consensus size')
    result['min_agreeing_tiles'] = int(result['min_agreeing_tiles'])
    if result['min_side_px'] < 64 or int(result['min_side_px']) != result['min_side_px']:
        raise ValueError('min_side_px must be an integer >=64')
    for key in ('min_gradient_eigen_ratio', 'min_phase_response', 'min_ecc',
                'periodic_correlation_limit'):
        if result[key] > 1:
            raise ValueError(f'{key} must be <=1')
    if result['max_error_px'] >= result['max_search_px']:
        raise ValueError('Search range must exceed accepted residual translation')
    return result


def _texture(image, policy):
    centered = image - np.mean(image)
    std = float(np.std(centered))
    if std < policy['min_texture_std_c']:
        return False
    gy, gx = np.gradient(image.astype(np.float64))
    gradients = np.stack((gx[2:-2, 2:-2].ravel(), gy[2:-2, 2:-2].ravel()))
    eig = np.linalg.eigvalsh(gradients @ gradients.T / gradients.shape[1])
    return bool(eig[0] > 0 and eig[0] / max(eig[1], 1e-20)
                >= policy['min_gradient_eigen_ratio'])


def _periodic(image, policy):
    """Exact/near-periodic textures cannot identify translation uniquely."""
    high = image - cv2.GaussianBlur(image, (0, 0), 4)
    for axis in (0, 1):
        for lag in range(6, min(25, image.shape[axis] // 3), 2):
            first = np.take(high, range(lag, image.shape[axis]), axis=axis).ravel()
            second = np.take(high, range(image.shape[axis] - lag), axis=axis).ravel()
            first, second = first - first.mean(), second - second.mean()
            denominator = np.linalg.norm(first) * np.linalg.norm(second)
            if denominator > 0 and np.dot(first, second) / denominator > \
                    policy['periodic_correlation_limit']:
                return True
    return False


def _tile_fit(reference, current, policy):
    if not _texture(reference, policy) or not _texture(current, policy):
        return None
    ref = np.ascontiguousarray((reference - reference.mean()) / reference.std())
    cur = np.ascontiguousarray((current - current.mean()) / current.std())
    window = cv2.createHanningWindow((ref.shape[1], ref.shape[0]), cv2.CV_32F)
    try:
        # phaseCorrelate can modify its arrays when applying a window.
        initial, response = cv2.phaseCorrelate(ref.copy(), cur.copy(), window)
        if not np.isfinite(initial).all() or not np.isfinite(response) or \
                response < policy['min_phase_response']:
            return None
        if np.linalg.norm(initial) > policy['max_search_px']:
            return None
        warp = np.eye(2, 3, dtype=np.float32)
        warp[:, 2] = initial
        score, warp = cv2.findTransformECC(
            ref, cur, warp, cv2.MOTION_TRANSLATION,
            (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 60, 1e-5), None, 5)
    except cv2.error:
        return None
    shift = warp[:, 2].astype(np.float64)
    if not np.isfinite(shift).all() or not np.isfinite(score) or score < policy['min_ecc']:
        return None
    if np.linalg.norm(shift) > policy['max_search_px']:
        return None
    return shift, float(response), float(score)


def assess_registration(reference, current, policy=DEFAULT_POLICY):
    """Check residual *current relative to reference* translation, [dx, dy].

    Both inputs are measured Celsius HxW arrays. Invalid arrays fail closed;
    Invalid policy raises TypeError/ValueError so configuration mistakes cannot
    be hidden. ``response`` is a raw phase-correlation response, not a calibrated
    confidence probability. ``estimated_shift_px`` uses [dx, dy] order and the
    acceptance threshold is Euclidean displacement, not per-axis displacement.
    ``ready`` is only permission from this translation check, not a complete
    quality/safety gate. Other gates must still establish calibration, operating
    condition, reference identity, domain, saturation and physical mapping.
    """
    policy = _policy(policy)
    result = {'status': 'indeterminate', 'can_infer': False, 'reason': 'invalid_input',
              'estimated_shift_px': None, 'response': None, 'policy': policy,
              'field_calibrated': False, 'accepted_tiles': 0, 'agreeing_tiles': 0}
    try:
        arrays = [np.asarray(a) for a in (reference, current)]
        if any(a.ndim != 2 or a.dtype.kind not in 'fiu' for a in arrays) or \
                arrays[0].shape != arrays[1].shape or \
                min(arrays[0].shape) < policy['min_side_px'] or \
                not all(np.isfinite(a).all() for a in arrays):
            return result
        arrays = [np.array(a, dtype=np.float32, copy=True) for a in arrays]
        if not all(np.isfinite(a).all() for a in arrays):
            return result
    except (ValueError, TypeError, OverflowError):
        return result
    arrays = [cv2.GaussianBlur(cv2.medianBlur(a, 3), (0, 0), 1.) for a in arrays]
    if not all(_texture(a, policy) for a in arrays):
        result['reason'] = 'insufficient_two_dimensional_texture'
        return result
    if any(_periodic(a, policy) for a in arrays):
        result['reason'] = 'ambiguous_periodic_texture'
        return result
    height, width = arrays[0].shape
    fits = []
    for y0, y1 in ((0, height // 2), (height // 2, height)):
        for x0, x1 in ((0, width // 2), (width // 2, width)):
            fit = _tile_fit(*(a[y0:y1, x0:x1].copy() for a in arrays), policy)
            if fit is not None:
                fits.append(fit)
    result['accepted_tiles'] = len(fits)
    if len(fits) < policy['min_agreeing_tiles']:
        result['reason'] = 'insufficient_reliable_tiles'
        return result
    shifts = np.array([fit[0] for fit in fits])
    distances = np.linalg.norm(shifts[:, None] - shifts[None, :], axis=2)
    # A clique, not a chain of mutually incompatible displacement estimates.
    consensus = []
    for size in range(len(fits), policy['min_agreeing_tiles'] - 1, -1):
        for ids in combinations(range(len(fits)), size):
            if distances[np.ix_(ids, ids)].max() <= policy['max_consensus_spread_px']:
                consensus.append(ids)
        if consensus:
            break
    if not consensus:
        result['reason'] = 'inconsistent_tile_motion'
        return result
    estimates = np.array([np.median(shifts[list(ids)], axis=0) for ids in consensus])
    if np.max(np.linalg.norm(estimates - estimates[0], axis=1)) > \
            policy['max_consensus_spread_px']:
        result['reason'] = 'ambiguous_tile_consensus'
        return result
    ids = consensus[0]
    shift = np.median(shifts[list(ids)], axis=0)
    result.update(estimated_shift_px=shift.tolist(),
                  response=float(np.median([fits[i][1] for i in ids])),
                  agreeing_tiles=len(ids),
                  ecc=float(np.median([fits[i][2] for i in ids])))
    if np.linalg.norm(shift) > policy['max_error_px']:
        result['reason'] = 'excess_residual_translation'
        return result
    result.update(status='ready', can_infer=True, reason='translation_within_policy')
    return result
