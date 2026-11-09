"""Opt-in sensitivity model, NOT a validated gas-pipe defect training simulator.

Steady radial resistance per metre: inner film + wall + insulation + outer film.
Internal metal loss increases inner radius at fixed outer diameter. Independent
radial columns omit lateral conduction, transient stress/crack and leak physics.
Coefficients are assumed effective values, not inferred material/flow properties.
"""
from __future__ import annotations

import math

import numpy as np


def surface_temperature(*, bulk_c, ambient_c, outer_diameter_mm, wall_mm,
                        insulation_mm, wall_k, insulation_k, h_inner, h_outer):
    """Return outer exposed/jacket surface temperature and resistance components.

R units K m/W; q is W/m. Supports broadcast-compatible scalar/array inputs.
The outer coefficient is an assumed linearized effective heat-transfer value.
"""
    values = np.broadcast_arrays(*[np.asarray(v, dtype=np.float64) for v in
        (bulk_c, ambient_c, outer_diameter_mm, wall_mm, insulation_mm,
         wall_k, insulation_k, h_inner, h_outer)])
    if not all(np.isfinite(v).all() for v in values):
        raise ValueError('All heat-transfer inputs must be finite')
    bulk, ambient, diameter, wall, insulation, kw, ki, hi, ho = values
    if (np.any(bulk <= -273.15) or np.any(ambient <= -273.15)
            or np.any(diameter <= 0) or np.any(wall <= 0)
            or np.any(wall * 2 >= diameter) or np.any(insulation < 0)
            or any(np.any(v <= 0) for v in (kw, ki, hi, ho))):
        raise ValueError('Invalid temperatures, radii, thickness, or coefficients')
    ro = diameter / 2000
    ri = ro - wall / 1000
    rj = ro + insulation / 1000
    resistances = {
        'inner_film': 1 / (hi * 2 * math.pi * ri),
        'wall': np.log(ro / ri) / (2 * math.pi * kw),
        'insulation': np.log(rj / ro) / (2 * math.pi * ki),
        'outer_film': 1 / (ho * 2 * math.pi * rj),
    }
    total = sum(resistances.values())
    q = (bulk - ambient) / total
    surface = ambient + q * resistances['outer_film']
    return {'surface_c': surface, 'heat_w_per_m': q, 'resistances': resistances}


def apparent_temperature(surface_c, emissivity, reflected_c, camera_emissivity,
                         camera_reflected_c):
    """Broadband gray-body approximation; not a spectral OGI or sensor calibration."""
    ts, eps, tr, es, trs = np.broadcast_arrays(*[np.asarray(v, dtype=np.float64)
        for v in (surface_c, emissivity, reflected_c, camera_emissivity,
                  camera_reflected_c)])
    if (not all(np.isfinite(v).all() for v in (ts, eps, tr, es, trs))
            or any(np.any(v <= -273.15) for v in (ts, tr, trs))
            or np.any((eps <= 0) | (eps > 1)) or np.any((es <= 0) | (es > 1))):
        raise ValueError('Invalid gray-body inputs')
    kelvin4 = (eps * (ts + 273.15) ** 4 + (1 - eps) * (tr + 273.15) ** 4
               - (1 - es) * (trs + 273.15) ** 4) / es
    if np.any(kelvin4 <= 0):
        raise ValueError('Camera setting gives non-positive inferred radiance')
    return kelvin4 ** .25 - 273.15


def controlled_case(parameters, seed=0, shape=(96, 128)):
    """Four controlled probe images. Shared noise isolates simulated changes.

The crack counterfactual is deliberately unchanged and unmodelled, not evidence
that actual cracks are always thermally invisible. These arrays are not labeled
supervised-training masks. Support masks identify where assumptions were varied.
"""
    p = dict(parameters)
    loss = float(p.pop('loss_fraction'))
    eps = float(p.pop('emissivity'))
    sigma = float(p.pop('noise_sigma_apparent_c'))
    reflected = float(p.pop('reflected_c'))
    camera_eps = float(p.pop('camera_emissivity'))
    if not 0 < loss < 1 or not np.isfinite(sigma) or sigma <= 0:
        raise ValueError('Loss must be in (0,1), noise sigma positive and finite')
    if len(shape) != 2 or min(shape) < 16:
        raise ValueError('Probe shape must be H,W >= 16')
    baseline = surface_temperature(**p)
    rng = np.random.default_rng(seed)
    height, width = shape
    yy, xx = np.indices(shape)
    center = int(rng.integers(width // 3, 2 * width // 3))
    band = np.exp(-.5 * ((np.arange(width) - center) / (width / 12)) ** 2)
    # A smooth axial band of internal thinning, uniform around circumference.
    wall = p['wall_mm'] * (1 - loss * band)
    damaged = surface_temperature(**{**p, 'wall_mm': wall})
    pipe = (yy >= height // 4) & (yy < 3 * height // 4)
    support = pipe & (band[None, :] > .5)
    baseline_app = apparent_temperature(baseline['surface_c'], eps, reflected,
                                       camera_eps, p['ambient_c'])
    damaged_app = apparent_temperature(damaged['surface_c'], eps, reflected,
                                      camera_eps, p['ambient_c'])
    # Reflection variation only: wall and true surface temperature unchanged.
    reflection_app = apparent_temperature(baseline['surface_c'], eps,
        reflected + 15 * band, camera_eps, p['ambient_c'])
    background = p['ambient_c'] + .5 * np.sin(xx / 11)
    clean = np.stack([
        np.where(pipe, baseline_app, background),
        np.where(pipe, damaged_app[None, :], background),
        np.where(pipe, reflection_app[None, :], background),
        np.where(pipe, baseline_app, background),
    ]).astype(np.float32)
    shared_noise = rng.normal(0, sigma, shape).astype(np.float32)
    images = clean + shared_noise[None, :, :]
    delta = float(np.max(np.abs(clean[1] - clean[0])))
    return {
        'temperature_c': images,
        'noiseless_temperature_c': clean,
        'perturbation_support': support,
        'wall_mm_by_column': wall.astype(np.float32),
        'peak_wall_loss_delta_apparent_c': delta,
        'peak_reflection_delta_apparent_c': float(np.max(np.abs(clean[2] - clean[0]))),
        'delta_over_independent_pair_noise': delta / (math.sqrt(2) * sigma),
        'counterfactual_crack_identical': bool(np.array_equal(images[0], images[3])),
        'true_surface_intact_c': float(baseline['surface_c']),
        'true_surface_wall_loss_peak_c': float(damaged['surface_c'][center]),
    }
