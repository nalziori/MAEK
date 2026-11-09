"""Evidence-traceable synthetic observations, not validated defect ground truth.

See docs/thermal-evidence-synthesis.md for sources, assumptions and exclusions.
Five valid paired interventions plus two acquisition rejection fixtures/scene.
The physical cause is audit metadata only, never an image classifier target.
"""
from __future__ import annotations

import itertools

import numpy as np

from maek.thermal_observation_synth import resize_float
from maek.thermal_radiative_surface import solve_radiative_surface
from maek.thermal_radiometry import BandRadiometry, gaussian_psf_radiance

MECHANISMS = ['stable_repeat', 'wall_loss', 'external_transfer', 'reflection', 'coating_change']
QUALITY_CASES = ['misregistration', 'calibration_drift']
CELLS = list(itertools.product([False, True], ['low', 'high'], ['zero', 'low', 'high'], [0, 1]))


def _uniform(rng, interval):
    return float(rng.uniform(*interval))


def _texture(rng, shape, scale=1.):
    return resize_float(rng.normal(0, scale, (5, 7)), shape)


def project_cylinder(field, background, *, angle_rad, center_xy, radius_px, half_length_px):
    """Orthographic side view, axis in image plane; no endcaps/perspective/BRDF.

    Field rows are equally spaced arc cells on front pi radians. Image-plane
    transverse coordinate is radius*sin(theta), not a flat stretched strip.
    Bilinear interpolation clamps ONLY half-cell edge extrapolation.
    """
    field, background = np.asarray(field, float), np.asarray(background, float)
    if field.ndim != 2 or background.ndim != 2 or min(field.shape) < 2:
        raise ValueError('Fields must be 2D; surface grid at least 2x2')
    if radius_px <= 0 or half_length_px <= 0:
        raise ValueError('Positive projected dimensions required')
    yy, xx = np.indices(background.shape, dtype=float)
    x, y = xx + .5 - center_xy[0], yy + .5 - center_xy[1]
    axial = (x * np.cos(angle_rad) + y * np.sin(angle_rad)) / half_length_px
    transverse = (-x * np.sin(angle_rad) + y * np.cos(angle_rad)) / radius_px
    mask = (np.abs(axial) <= 1) & (np.abs(transverse) <= 1)
    u = np.clip((axial + 1) * field.shape[1] / 2 - .5, 0, field.shape[1] - 1)
    v = np.clip((np.arcsin(np.clip(transverse, -1, 1)) / np.pi + .5) * field.shape[0]
                - .5, 0, field.shape[0] - 1)
    x0, y0 = u.astype(int), v.astype(int)
    x1, y1 = np.minimum(x0 + 1, field.shape[1] - 1), np.minimum(y0 + 1, field.shape[0] - 1)
    wx, wy = u - x0, v - y0
    sampled = ((1 - wy) * ((1 - wx) * field[y0, x0] + wx * field[y0, x1])
               + wy * ((1 - wx) * field[y1, x0] + wx * field[y1, x1]))
    return np.where(mask, sampled, background), mask


def _patch(rng, shape):
    yy, xx = np.mgrid[0:1:complex(shape[0]), 0:1:complex(shape[1])]
    cx, cy = rng.uniform(.18, .82, 2)
    kind = int(rng.integers(3))
    sx, sy = rng.uniform(.07, .2), rng.uniform(.08, .25)
    angle = rng.uniform(0, np.pi)
    x = (xx - cx) * np.cos(angle) + (yy - cy) * np.sin(angle)
    y = -(xx - cx) * np.sin(angle) + (yy - cy) * np.cos(angle)
    patch = np.exp(-.5 * ((x / sx)**2 + (y / sy)**2))
    if kind == 1:
        patch = np.maximum(patch, .8 * np.exp(-.5 * (((x - .15) / sx)**2 + (y / sy)**2)))
    elif kind == 2:
        patch = np.exp(-.5 * ((x / (sx * .6))**4 + (y / (sy * 1.3))**4))
    return patch, {'kind': kind, 'center_xy': [float(cx), float(cy)],
                   'scales_xy': [float(sx), float(sy)], 'angle_rad': float(angle)}


def _camera_pair(ref, cur, *, camera, config, rng, sigma_l, fixed, gain, offset,
                 assumed_reflected_c, bad, quality=None):
    def decode(radiance):
        return camera.compensate(radiance, assumed_emissivity=config['camera_assumed_emissivity'],
            assumed_transmittance=config['camera_assumed_transmittance'],
            assumed_reflected_c=assumed_reflected_c, assumed_atmosphere_c=assumed_reflected_c)

    q = config['quantization_c']
    lo, hi = config['camera_limits_c']
    clean_l = [a * (1 + gain) + fixed + offset for a in (ref, cur)]
    if quality == 'calibration_drift':
        derivative = float((camera.radiance(30.01) - camera.radiance(29.99)) / .02)
        clean_l[1] = clean_l[1] + config['quality_drift_equiv_c_at_30'] * derivative
    clean_unclipped = [decode(a) for a in clean_l]
    observed_unclipped = [decode(a + rng.normal(0, sigma_l, a.shape)) for a in clean_l]
    clean = [np.clip(np.round(a / q) * q, lo, hi).astype(np.float32) for a in clean_unclipped]
    observed = [np.clip(np.round(a / q) * q, lo, hi).astype(np.float32)
                for a in observed_unclipped]
    valid = ~bad.copy()
    for a in clean + observed:
        valid &= (a > lo) & (a < hi)
    # A per-pixel uncertainty scale from finite radiance perturbation through
    # the SAME assumed camera inverse. Gaussian read noise is an assumption.
    sigmas = [np.abs(decode(a + sigma_l) - decode(a - sigma_l)) / 2 for a in clean_l]
    sigma_pair = np.hypot(*sigmas)
    low = np.maximum(sigma_pair, q).astype(np.float32)
    high = np.maximum(3 * sigma_pair, 2 * q).astype(np.float32)
    delta = np.abs(clean[1].astype(float) - clean[0])
    target = np.full(ref.shape, 255, np.uint8)
    if quality is None:
        target[valid & (delta <= low)] = 0
        target[valid & (delta >= high)] = 1
    for image in observed:
        image[bad] = 0
    return {'reference_c': observed[0], 'current_c': observed[1], 'clean_reference_c': clean[0],
                'clean_current_c': clean[1], 'target': target, 'valid_mask': valid, 'bad_pixel_mask': bad,
                'label_low_c': low, 'label_high_c': high,
                'clean_sensor_radiance_reference_audit_only': clean_l[0],
                'clean_sensor_radiance_current_audit_only': clean_l[1]}


def generate_evidence_scene(group_index, split, config, camera=None):
    """Return rows/arrays; all variants of a physical scene stay in one split."""
    seed = config['seed'] + group_index * 1000
    rng = np.random.default_rng(seed)
    camera = camera or BandRadiometry(band_um=tuple(config['band_um']))
    insulated, eps_bin, drive_bin, noise_bin = CELLS[group_index % len(CELLS)]
    stress = split == 'stress'
    shape, grid = tuple(config['shape']), tuple(config['solver_shape'])
    ambient = _uniform(rng, config['ambient_c'])
    drive = 0. if drive_bin == 'zero' else _uniform(rng, config[f'drive_{drive_bin}_c'])
    if rng.random() < .5:
        drive = -min(drive, 35.)
    eps_mean = _uniform(rng, config[f'emissivity_{eps_bin}'])
    eps = np.clip(eps_mean + _texture(rng, grid, .015), .05, .99)
    wall = _uniform(rng, config['wall_mm'])
    patch, patch_info = _patch(rng, grid)
    loss = _uniform(rng, config['loss_fraction'])
    hc = _uniform(rng, config['h_convection_w_m2_k'])
    parameters = {'bulk_c': ambient + drive, 'ambient_c': ambient,
        'outer_diameter_mm': float(rng.choice(config['stress_diameter_mm' if stress else 'diameter_mm'])),
        'wall_mm': np.full(grid, wall), 'insulation_mm': _uniform(rng, config['insulation_mm']) if insulated else 0.,
        'wall_k': float(rng.choice(config['wall_k_w_m_k'])),
        'insulation_k': _uniform(rng, config['insulation_k_w_m_k']),
        'h_inner': _uniform(rng, config['h_inner_w_m2_k']), 'length_m': _uniform(rng, config['length_m'])}
    transfer_multiplier = _uniform(rng, config['external_transfer_multiplier'])
    eps_coating = np.clip(eps + (.25 if eps_mean < .5 else -.25) * patch, .05, .99)
    # Total and band emissivity equality is an explicit gray-surface assumption.
    baseline = solve_radiative_surface(**parameters, emissivity_total=eps, h_convection=hc)
    solutions = [baseline,
        solve_radiative_surface(**{**parameters, 'wall_mm': wall * (1 - loss * patch)},
                                emissivity_total=eps, h_convection=hc),
        solve_radiative_surface(**parameters, emissivity_total=eps,
                                h_convection=hc * (1 + (transfer_multiplier - 1) * patch)),
        baseline,
        solve_radiative_surface(**parameters, emissivity_total=eps_coating, h_convection=hc)]
    tau = _uniform(rng, config['stress_transmittance' if stress else 'transmittance'])
    reflection = ambient + _texture(rng, grid, 7.)
    reflection_delta = _uniform(rng, config['reflection_change_c']) * rng.choice([-1, 1])
    scale = config['supersample']
    big_shape = tuple(s * scale for s in shape)
    bg_temp = ambient + _texture(rng, big_shape, 4.)
    background = camera.mix(bg_temp, .9, ambient, tau, ambient)
    pixels_per_m = max(shape) * scale * rng.uniform(.9, 1.5) / parameters['length_m']
    jacket_radius_m = parameters['outer_diameter_mm'] / 2000 + parameters['insulation_mm'] / 1000
    pose = {'angle_rad': float(rng.uniform(-np.pi / 2, np.pi / 2)),
                'center_xy': [float(shape[1] * scale * rng.uniform(.4, .6)),
                           float(shape[0] * scale * rng.uniform(.4, .6))],
                'radius_px': float(jacket_radius_m * pixels_per_m),
                'half_length_px': float(parameters['length_m'] * pixels_per_m / 2)}
    psf = float(rng.choice(config['stress_psf_sigma_px' if stress else 'psf_sigma_px']))
    radiances, pipe_mask = [], None
    for mechanism, solution in zip(MECHANISMS, solutions):
        radiance = camera.mix(solution['jacket_surface_c'],
            eps_coating if mechanism == 'coating_change' else eps,
            reflection + (reflection_delta * patch if mechanism == 'reflection' else 0.), tau, ambient)
        projected, big_mask = project_cylinder(radiance, background, **pose)
        blurred = gaussian_psf_radiance(projected, psf * scale)
        radiances.append(blurred.reshape(shape[0], scale, shape[1], scale).mean(axis=(1, 3)))
        pipe_mask = big_mask.reshape(shape[0], scale, shape[1], scale).mean(axis=(1, 3)) > .5
    dldt = float((camera.radiance(30.01) - camera.radiance(29.99)) / .02)
    equiv = config['stress_read_noise_equiv_c_at_30' if stress else 'read_noise_equiv_c_at_30'][noise_bin]
    sigma_l = equiv * dldt
    fixed = rng.normal(0, config['fixed_pattern_equiv_c_at_30'] * dldt, shape)
    fixed += rng.normal(0, .5 * config['fixed_pattern_equiv_c_at_30'] * dldt, (shape[0], 1))
    gain = _uniform(rng, config['calibration_gain_fraction'])
    offset = _uniform(rng, config['calibration_offset_equiv_c_at_30']) * dldt
    bad = rng.random(shape) < config['bad_pixel_probability']
    rows = []
    for k, mechanism in enumerate(MECHANISMS + QUALITY_CASES):
        quality = mechanism if mechanism in QUALITY_CASES else None
        current = radiances[k] if quality is None else radiances[0].copy()
        shift = [0, 0]
        if mechanism == 'misregistration':
            shift = [int(rng.choice(config['quality_registration_shift_px'])),
                     int(rng.choice(config['quality_registration_shift_px']))]
            # Edge-pad translation, never wrap the opposite image edge.
            padded = np.pad(current, ((shift[0], 0), (shift[1], 0)), mode='edge')
            current = padded[:shape[0], :shape[1]]
        noise_seed = seed + 100 + k
        arrays = _camera_pair(radiances[0], current, camera=camera, config=config,
            rng=np.random.default_rng(noise_seed), sigma_l=sigma_l, fixed=fixed, gain=gain,
            offset=offset, assumed_reflected_c=ambient, bad=bad, quality=quality)
        arrays['pipe_mask_audit_only'] = pipe_mask
        current_solution = solutions[k] if quality is None else baseline
        arrays['surface_reference_c_audit_only'] = baseline['jacket_surface_c'].astype(np.float32)
        arrays['surface_current_c_audit_only'] = current_solution['jacket_surface_c'].astype(np.float32)
        arrays['wall_reference_mm_audit_only'] = np.full(grid, wall, np.float32)
        arrays['wall_current_mm_audit_only'] = (wall * (1 - loss * patch)
            if mechanism == 'wall_loss' else np.full(grid, wall)).astype(np.float32)
        row = {'mechanism': mechanism, 'group_index': group_index, 'scene_seed': seed,
            'noise_seed': noise_seed, 'quality_status': 'ready' if quality is None else 'reject',
            'quality_reason': quality, 'segmentation_eligible': quality is None,
            'factors': {'insulated': insulated, 'emissivity_bin': eps_bin, 'drive_bin': drive_bin,
                         'noise_bin': noise_bin}, 'psf_sigma_px': psf, 'pose': pose, 'patch': patch_info,
            'physical_parameters': {key: value for key, value in parameters.items() if key != 'wall_mm'},
            'wall_mm': wall, 'loss_fraction': loss, 'emissivity_mean': eps_mean,
            'h_convection_w_m2_k': hc, 'transfer_multiplier': transfer_multiplier,
            'actual_transmittance': tau, 'reflection_change_c': float(reflection_delta),
            'read_noise_equiv_c_at_30': equiv, 'read_noise_radiance': sigma_l,
            'calibration_gain_fraction': gain, 'calibration_offset_radiance': offset,
            'registration_shift_px': shift, 'solver_relative_residual': max(s['residual_relative'] for s in solutions),
            'solver_energy_error': max(s['energy_relative_error'] for s in solutions),
            'external_balance_relative_error': max(s['external_balance_relative_error'] for s in solutions)}
        rows.append((row, arrays))
    return rows
