"""Observable component features for opt-in thermal false-alarm filtering."""
from __future__ import annotations

import numpy as np

from maek import thermal_render as tr

FILTERS = {
    'wet_width10': {'min_width': 10.0, 'min_area': 0},
    'wet_width12_area80': {'min_width': 12.0, 'min_area': 80},
    'wet_width14_area100': {'min_width': 14.0, 'min_area': 100},
}
RESCUE_CONTRAST_C = 4.0


def component_features(temperature, pipe_mask, component):
    if temperature.shape != pipe_mask.shape or component.shape != temperature.shape:
        raise ValueError("Temperature and masks must have the same shape")
    if temperature.ndim != 2 or not np.isfinite(temperature).all():
        raise ValueError("Expected a finite 2D temperature image")
    yy, xx = np.nonzero(component)
    py, px = np.nonzero(pipe_mask)
    if len(xx) == 0 or len(px) < 2:
        raise ValueError("Component and pipe mask must be nonempty")
    coords = np.column_stack((px, py)).astype(np.float64)
    center = coords.mean(axis=0)
    _, vectors = np.linalg.eigh(np.cov(coords - center, rowvar=False))
    axis = vectors[:, -1]
    across = np.array([-axis[1], axis[0]])
    component_xy = np.column_stack((xx, yy)).astype(np.float64) - center
    u, v = component_xy @ axis, component_xy @ across
    pipe_v = (coords - center) @ across
    width = float(np.ptp(pipe_v) + 1)
    ring = tr._dilate(component, 5) & ~component & pipe_mask
    contrast = (float(np.median(temperature[component]) - np.median(temperature[ring]))
                if ring.any() else None)
    along, cross = float(np.ptp(u) + 1), float(np.ptp(v) + 1)
    return {"area_px": len(xx), "along_extent_px": along, "across_extent_px": cross,
            "across_pipe_fraction": cross / width,
            "aspect_along_over_across": along / cross,
            "center_to_pipe_edge_fraction": max(0, width / 2 - abs(float(np.median(v))))
                                            / (width / 2),
            "local_median_contrast_c": contrast}


def filter_wet_components(temperature, pipe_mask, prediction, candidate):
    """Reject small weak wet blobs without changing damage/steam or input arrays."""
    if candidate == 'baseline':
        return prediction.copy()
    if candidate not in FILTERS:
        raise ValueError(f'Unknown wet filter: {candidate}')
    settings = FILTERS[candidate]
    result = prediction.copy()
    for rows, cols in tr._components(prediction == 1, 1, 1):
        component = np.zeros_like(pipe_mask, dtype=bool)
        component[rows, cols] = True
        f = component_features(temperature, pipe_mask, component)
        strong = (f['local_median_contrast_c'] is not None
                  and f['local_median_contrast_c'] >= RESCUE_CONTRAST_C)
        small = (f['across_extent_px'] < settings['min_width']
                 or f['area_px'] < settings['min_area'])
        if small and not strong:
            result[rows, cols] = 0
    return result


def detect_ir(cfg, temperature, pipe_mask, candidate='baseline'):
    return filter_wet_components(temperature, pipe_mask,
                                 tr.detect_ir(cfg, temperature, pipe_mask), candidate)
