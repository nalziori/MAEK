"""Synthetic registered-pair observation task; no crack or safety ground truth.

Thin-shell steady conduction, approximate gray-body imaging and a synthetic
camera. All temperatures Celsius. Parameters are assumed, not field calibrated.
"""
from __future__ import annotations

import math

import numpy as np

from maek.thermal_feasibility import apparent_temperature
from maek.thermal_surface_solver import solve_surface

MECHANISMS = ['stable_repeat', 'wall_loss', 'external_transfer', 'reflection',
              'emissivity_change']


def blur_float(array, sigma):
    """Separable Gaussian approximation in apparent-temperature space."""
    radius = max(1, math.ceil(3 * sigma))
    weights = np.exp(-.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    weights /= weights.sum()
    result = np.asarray(array, dtype=np.float64)
    for axis in (0, 1):
        pads = [(0, 0), (0, 0)]
        pads[axis] = (radius, radius)
        padded = np.pad(result, pads, mode='reflect')
        result = sum(w * np.take(padded, np.arange(result.shape[axis]) + i,
                                 axis=axis) for i, w in enumerate(weights))
    return result


def resize_float(array, shape):
    """Bilinear grid interpolation without integer-image conversion."""
    old_y, old_x = array.shape
    rows = np.array([np.interp(np.linspace(0, old_x - 1, shape[1]),
                              np.arange(old_x), row) for row in array])
    return np.array([np.interp(np.linspace(0, old_y - 1, shape[0]),
                              np.arange(old_y), col) for col in rows.T]).T


def camera_pair(reference, current, *, sigma, quantization, blur_sigma,
                seed_reference, seed_current, bad_pixel_mask, limits=(-40., 180.)):
    """Independent read noise; common registration, calibration and fixed PSF."""
    lo, hi = limits

    def quantize(a):
        return np.clip(np.round(a / quantization) * quantization, lo, hi).astype(np.float32)

    clean = [quantize(blur_float(a, blur_sigma)) for a in (reference, current)]
    # Noise added before quantization, not to the already quantized clean data.
    observed = [quantize(blur_float(a, blur_sigma) + np.random.default_rng(seed).normal(
        0, sigma, a.shape)) for a, seed in zip((reference, current),
                                             (seed_reference, seed_current))]
    valid = ~bad_pixel_mask.copy()
    for a in clean + observed:
        valid &= (a > lo) & (a < hi)
    for a in observed:
        a[bad_pixel_mask] = 0.  # Sensor validity is explicit; these pixels ignored.
    low, high = max(math.sqrt(2) * sigma, quantization), max(3 * math.sqrt(2) * sigma,
                                                                         2 * quantization)
    delta = np.abs(clean[1].astype(np.float64) - clean[0])
    target = np.full(reference.shape, 255, np.uint8)
    target[valid & (delta <= low)] = 0
    target[valid & (delta >= high)] = 1
    return {'reference_c': observed[0], 'current_c': observed[1],
            'clean_reference_c': clean[0], 'clean_current_c': clean[1],
            'valid_mask': valid, 'bad_pixel_mask': bad_pixel_mask, 'target': target}, low, high


def generate_scene(group_index, split, *, seed=20261108, shape=(128, 160)):
    """Five paired interventions on one scene; entire scene assigned one split."""
    scene_seed = seed + group_index * 100
    rng = np.random.default_rng(scene_seed)
    cell = group_index % 16
    insulated, low_eps, high_drive, high_noise = (bool(cell & (1 << i)) for i in range(4))
    stress = split == 'stress'
    ambient = float(rng.uniform(10, 35))
    drive = float(rng.uniform(2, 10) if not high_drive else rng.uniform(35, 75))
    if (group_index // 16) % 2:
        drive = -min(drive, 35.)
    eps = float(rng.uniform(.12, .35) if low_eps else rng.uniform(.75, .95))
    noise = (.45 if high_noise else .3) if stress else (.1 if high_noise else .03)
    blur = 2.2 if stress else (.5 if group_index % 2 else 1.)
    diameter = 219. if stress else float(rng.choice([114.3, 168.3]))
    wall = float(rng.uniform(4, 8))
    insulation = float(rng.uniform(25, 60)) if insulated else 0.
    sy, sx = np.mgrid[0:1:32j, 0:1:48j]
    quadrant = (group_index // 16 + cell) % 4
    cx = rng.uniform(.18, .42) if quadrant % 2 == 0 else rng.uniform(.58, .82)
    cy = rng.uniform(.18, .42) if quadrant // 2 == 0 else rng.uniform(.58, .82)
    patch = np.exp(-.5 * (((sx - cx) / rng.uniform(.07, .2)) ** 2
                          + ((sy - cy) / rng.uniform(.1, .3)) ** 2))
    parameters = {'bulk_c': ambient + drive, 'ambient_c': ambient,
                      'outer_diameter_mm': diameter, 'wall_mm': np.full((32, 48), wall),
                      'insulation_mm': insulation, 'wall_k': float(rng.choice([16., 45.])),
                      'insulation_k': .045, 'h_inner': float(rng.choice([10., 100.])),
                      'h_outer': 15., 'length_m': float(rng.uniform(.5, 1.5))}
    baseline = solve_surface(**parameters)
    loss_fraction = float(rng.uniform(.1, .6))
    loss = solve_surface(**{**parameters, 'wall_mm': wall * (1 - loss_fraction * patch)})
    transfer = solve_surface(**{**parameters, 'h_outer': 15 * (1 + 3 * patch)})
    # Static coating/reflection textures appear in BOTH frames and every mechanism.
    eps_field = np.clip(eps + .025 * np.sin(7 * sx + 3 * sy), .08, .98)
    reflection = ambient + 8 * np.cos(5 * sy + 2 * sx)
    surfaces = [baseline, loss, transfer, baseline, baseline]
    reflection_change = float(rng.choice([-1., 1.]) * rng.uniform(10, 45))
    emissivity_change = (.2 if eps < .5 else -.3) * patch
    pipe_apps = []
    for mechanism, solution in zip(MECHANISMS, surfaces):
        pipe_apps.append(apparent_temperature(
            solution['jacket_surface_c'],
            np.clip(eps_field + (emissivity_change if mechanism == 'emissivity_change' else 0), .05, .99),
            reflection + (reflection_change * patch if mechanism == 'reflection' else 0),
            .95, ambient))
    # Vary image pose; this is a rectangular unwrapped strip, not a calibrated projection.
    vertical = bool(rng.integers(2))
    height, width = shape
    yy, xx = np.indices(shape)
    background = ambient + 2 * np.sin(xx / 23 + rng.uniform(0, 6)) + np.cos(yy / 19)
    thickness = int(rng.uniform(.35, .65) * (width if vertical else height))
    start = int(rng.uniform(.12, .3) * (width if vertical else height))
    region = (slice(8, height - 8), slice(start, min(width - 4, start + thickness))) if vertical else (
        slice(start, min(height - 4, start + thickness)), slice(8, width - 8))
    canvases = []
    for app in pipe_apps:
        canvas = background.copy()
        canvas[region] = resize_float(app.T if vertical else app, canvas[region].shape)
        canvases.append(canvas)
    bad = rng.random(shape) < .0005
    result = []
    for k, (mechanism, current, solution) in enumerate(zip(MECHANISMS, canvases, surfaces)):
        noise_ref, noise_cur = scene_seed + 1 + k * 2, scene_seed + 2 + k * 2
        arrays, low, high = camera_pair(canvases[0], current, sigma=noise, quantization=.01,
            blur_sigma=blur, seed_reference=noise_ref, seed_current=noise_cur, bad_pixel_mask=bad)
        row = {'mechanism': mechanism, 'scene_seed': scene_seed,
                   'noise_seed_reference': noise_ref, 'noise_seed_current': noise_cur,
                   'noise_sigma_c': noise, 'quantization_c': .01, 'blur_sigma_px': blur,
                   'outer_diameter_mm': diameter, 'camera_min_c': -40., 'camera_max_c': 180.,
                   'low_threshold_c': low, 'high_threshold_c': high,
                   'factors': {'insulated': insulated, 'emissivity_bin': 'low' if low_eps else 'high',
                       'drive_bin': 'high' if high_drive else 'low', 'noise_bin': 'high' if high_noise else 'low',
                       'orientation': 'vertical' if vertical else 'horizontal', 'patch_quadrant': int(quadrant)},
                   'solver_relative_residual': max(baseline['residual_relative'], solution['residual_relative']),
                   'solver_energy_error': max(baseline['energy_relative_error'], solution['energy_relative_error']),
                   'physical_parameters': {'ambient_c': ambient, 'bulk_c': ambient + drive,
                       'emissivity': eps, 'wall_mm': wall, 'insulation_mm': insulation,
                       'wall_k': parameters['wall_k'], 'h_inner': parameters['h_inner'],
                       'length_m': parameters['length_m'], 'loss_fraction': loss_fraction,
                       'reflection_change_c': reflection_change, 'patch_center': [float(cx), float(cy)]}}
        result.append((row, arrays))
    return result
