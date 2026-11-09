"""Opt-in pipe-local wet-label filters; defaults and classes 2/3 are unchanged.

Local center/surround contrast is only a generic paper-inspired idea, not an
implementation or validation of Xie et al. (2014) for pipe thermography. These
fixed hypotheses require held-out evaluation. All dimensions are pixels and all
temperature differences are degrees C. Relative contrast divides by absolute
local temperature in kelvin, so its threshold does not depend on the C offset.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np

from maek import thermal_render as tr


@dataclass(frozen=True)
class Candidate:
    name: str
    radius: int = 7
    inner_radius: int = 2
    min_neighbors: int = 24
    min_valid_fraction: float = .8
    min_contrast_c: float = .35
    min_relative: float = .0015
    mad_z: float = 0.
    median3: bool = False


CANDIDATES = MappingProxyType({c.name: c for c in (
    Candidate('baseline'),
    Candidate('wet_local_relative'),
    Candidate('wet_local_mad', mad_z=2.5),
    Candidate('wet_local_median3_mad', mad_z=2.5, median3=True),
)})


@dataclass(frozen=True)
class Quality:
    status: str
    reasons: tuple[str, ...] = ()
    pipe_pixels: int = 0
    finite: bool = True
    saturation_checked: bool = False
    saturated_pixels: int = 0
    boundary_pixels: int = 0
    abstained_components: int = 0
    abstained_pixels: int = 0
    removed_components: int = 0


@dataclass(frozen=True)
class DetectionResult:
    candidate: Candidate
    mask: np.ndarray | None
    quality: Quality


def _local_stats(values, valid, rows, cols, radius, inner_radius, min_neighbors):
    """Bounded 512-point gathers; no full-frame window tensor or edge padding.

    A Chebyshev annulus excludes the center and inner square. Only in-frame,
    valid samples contribute. Unsupported medians/MADs are NaN, never zero.
    """
    dy, dx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    use = np.maximum(np.abs(dy), np.abs(dx)) > inner_radius
    dy, dx = dy[use], dx[use]
    med = np.full(len(rows), np.nan)
    sigma = np.full(len(rows), np.nan)
    supported = np.zeros(len(rows), bool)
    height, width = values.shape
    for start in range(0, len(rows), 512):
        stop = min(start + 512, len(rows))
        yy = rows[start:stop, None] + dy
        xx = cols[start:stop, None] + dx
        inside = (yy >= 0) & (yy < height) & (xx >= 0) & (xx < width)
        yy, xx = yy.clip(0, height - 1), xx.clip(0, width - 1)
        good = inside & valid[yy, xx]
        samples = np.where(good, values[yy, xx], np.nan)
        enough = good.sum(axis=1) >= min_neighbors
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            center = np.nanmedian(samples, axis=1)
            scale = 1.4826 * np.nanmedian(np.abs(samples - center[:, None]), axis=1)
        med[start:stop] = np.where(enough, center, np.nan)
        sigma[start:stop] = np.where(enough, scale, np.nan)
        supported[start:stop] = enough
    return med, sigma, supported


def _masked_median3(temperature, pipe):
    """Median of available pipe-only 3x3 samples, center included, on a copy."""
    rows, cols = np.nonzero(pipe)
    med, _, _ = _local_stats(temperature, pipe, rows, cols, 1, -1, 1)
    result = temperature.copy()
    result[rows, cols] = med
    return result


def detect_ir(cfg, temperature, pipe_mask, candidate='baseline', *,
              baseline_prediction=None, raw_uint16=None):
    """Return candidate, mask, and quality; callers must count abstentions.

    Invalid frames have mask=None, never a normal prediction. Saturation means
    literal raw uint16 0/65535 and is checked only when raw_uint16 is supplied.
    All-frame finiteness is required because the baseline also uses background.
    Pipe masks are oracle geometry in simulator studies, not estimated masks.
    Local support failures retain the baseline component and are counted in
    quality. Other classes, outside-pipe wet labels, and inputs are untouched.

    Filtering removes a whole wet component only if at least 80% of its pixels
    have >=24 usable annular pipe neighbors and its 90th-percentile contrast
    margin is negative. All baseline wet pixels are excluded from neighborhoods.
    This component-level policy is intended to avoid shaving small targets; it
    does not guarantee measured recall preservation.
    """
    if candidate not in CANDIDATES:
        raise ValueError(f'Unknown local contrast candidate: {candidate}')
    settings = CANDIDATES[candidate]
    temp = np.asarray(temperature)
    pipe = np.asarray(pipe_mask)
    if temp.ndim != 2 or pipe.shape != temp.shape or pipe.dtype != np.bool_:
        raise ValueError('Expected a 2D temperature image and equal-shape boolean pipe mask')
    if not np.issubdtype(temp.dtype, np.number) or np.iscomplexobj(temp):
        raise ValueError('Expected real numeric temperature values')
    pipe_pixels = int(pipe.sum())
    finite = bool(np.isfinite(temp).all())
    saturated = 0
    if raw_uint16 is not None:
        raw = np.asarray(raw_uint16)
        if raw.shape != temp.shape or raw.dtype != np.uint16:
            raise ValueError('raw_uint16 must be an equal-shape uint16 image')
        saturated = int(((raw == 0) | (raw == 65535)).sum())
    reasons = []
    if not finite:
        reasons.append('nonfinite_temperature')
    if pipe_pixels < 200:
        reasons.append('too_few_pipe_pixels')
    if saturated:
        reasons.append('raw_uint16_boundary_saturation')
    common = {'pipe_pixels': pipe_pixels, 'finite': finite,
              'saturation_checked': raw_uint16 is not None, 'saturated_pixels': saturated}
    if reasons:
        return DetectionResult(settings, None, Quality('abstain', tuple(reasons), **common))
    if baseline_prediction is None:
        baseline_prediction = tr.detect_ir(cfg, temp, pipe)
    baseline = np.asarray(baseline_prediction)
    if (baseline.shape != temp.shape or not np.issubdtype(baseline.dtype, np.integer)
            or not np.isin(baseline, (0, 1, 2, 3)).all()):
        raise ValueError('Expected equal-shape integer baseline labels in 0..3')
    result = baseline.astype(np.uint8, copy=True)
    if candidate == 'baseline':
        return DetectionResult(settings, result, Quality('ok', **common))

    source = temp.astype(np.float64, copy=True)
    if settings.median3:
        source = _masked_median3(source, pipe)
    wet = baseline == 1
    eligible = wet & pipe
    rows, cols = np.nonzero(eligible)
    local, sigma, supported = _local_stats(
        source, pipe & ~wet, rows, cols, settings.radius,
        settings.inner_radius, settings.min_neighbors)
    kelvin = local + 273.15
    supported &= kelvin > 0
    threshold = np.maximum(settings.min_contrast_c, settings.min_relative * kelvin)
    if settings.mad_z:
        threshold = np.maximum(threshold, settings.mad_z * np.maximum(sigma, .02))
    margin = source[rows, cols] - local - threshold
    margins = np.full(temp.shape, np.nan)
    margins[rows[supported], cols[supported]] = margin[supported]
    radius = settings.radius
    boundary = int(((rows < radius) | (rows >= temp.shape[0] - radius)
                    | (cols < radius) | (cols >= temp.shape[1] - radius)).sum())
    abstained_components = abstained_pixels = removed_components = 0
    # Use complete wet components so a partly outside-pipe component is preserved.
    for ry, rx in tr._components(wet, 1, 1):
        values = margins[ry, rx]
        good = np.isfinite(values)
        if (not pipe[ry, rx].all() or good.mean() < settings.min_valid_fraction):
            abstained_components += 1
            abstained_pixels += len(ry)
        elif np.percentile(values[good], 90) < 0:
            result[ry, rx] = 0
            removed_components += 1
    quality = Quality('ok', boundary_pixels=boundary,
                      abstained_components=abstained_components,
                      abstained_pixels=abstained_pixels,
                      removed_components=removed_components, **common)
    return DetectionResult(settings, result, quality)
