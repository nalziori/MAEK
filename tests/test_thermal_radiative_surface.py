"""Independent radial root, energy and limiting-case checks; not field validation."""
from __future__ import annotations

import math

import numpy as np
import pytest

from maek.thermal_radiative_surface import solve_radiative_surface


def parameters():
    return {'bulk_c': 85., 'ambient_c': 25., 'outer_diameter_mm': 114.3,
            'wall_mm': np.full((8, 12), 6.), 'insulation_mm': 0., 'wall_k': 45.,
            'insulation_k': .045, 'h_inner': 50., 'length_m': 1.}


@pytest.mark.parametrize('insulation', [0., 40.])
@pytest.mark.parametrize('bulk', [-5., 85.])
def test_uniform_matches_independent_nonlinear_radial_root(insulation, bulk):
    p = {**parameters(), 'bulk_c': bulk, 'insulation_mm': insulation}
    ro, ri = .1143 / 2, .1143 / 2 - .006
    rj = ro + insulation / 1000
    resistance = (1 / (50 * 2 * math.pi * ri) + math.log(ro / ri) / (2 * math.pi * 45)
                  + math.log(rj / ro) / (2 * math.pi * .045))
    lo, hi = sorted([bulk, 25.])
    for _ in range(90):
        t = (lo + hi) / 2
        residual = ((bulk - t) / resistance - 2 * math.pi * rj * (
            10 * (t - 25) + .8 * 5.670374419e-8 * ((t + 273.15)**4 - 298.15**4)))
        if residual > 0:
            lo = t
        else:
            hi = t
    actual = solve_radiative_surface(**p, emissivity_total=.8, h_convection=10.)
    np.testing.assert_allclose(actual['jacket_surface_c'], (lo + hi) / 2, atol=1e-6)
    assert actual['external_balance_relative_error'] < 1e-7
    assert actual['energy_relative_error'] < 1e-8


def test_zero_drive_and_irregular_wall_gives_no_thermal_signal():
    p = {**parameters(), 'bulk_c': 25.}
    p['wall_mm'][2:6, 4:8] = 2.
    result = solve_radiative_surface(**p, emissivity_total=.2, h_convection=2.)
    np.testing.assert_array_equal(result['jacket_surface_c'], np.full((8, 12), 25.))


def test_emissivity_changes_actual_energy_balance():
    low = solve_radiative_surface(**parameters(), emissivity_total=.1, h_convection=5.)
    high = solve_radiative_surface(**parameters(), emissivity_total=.95, h_convection=5.)
    assert np.all(high['jacket_surface_c'] < low['jacket_surface_c'])


def test_nonconvergence_and_double_counting_rejected():
    with pytest.raises(RuntimeError, match='converge'):
        solve_radiative_surface(**parameters(), emissivity_total=.8, h_convection=10.,
                                max_iterations=1)
    with pytest.raises(ValueError, match='effective'):
        solve_radiative_surface(**parameters(), emissivity_total=.8, h_convection=10., h_outer=15)


@pytest.mark.parametrize('key,value', [('emissivity_total', 1.1), ('emissivity_total', 0),
                                      ('h_convection', -1), ('h_convection', float('nan'))])
def test_invalid_inputs(key, value):
    kwargs = {'emissivity_total': .8, 'h_convection': 10.}
    kwargs[key] = value
    with pytest.raises(ValueError):
        solve_radiative_surface(**parameters(), **kwargs)


def nonuniform_case(shape=(16, 24), insulation=0., bulk=85.):
    """One fixed physical domain sampled at cell centres on each grid."""
    height, width = shape
    x = (np.arange(width) + .5) / width
    y = (np.arange(height) + .5) / height
    smooth = np.cos(2 * np.pi * x)[None, :] * np.cos(np.pi * y)[:, None]
    p = {**parameters(), 'wall_mm': 4 + 1.5 * smooth,
         'insulation_mm': insulation, 'bulk_c': bulk}
    eps = .6 + .2 * smooth
    hc = 10 + 4 * np.cos(np.pi * x)[None, :] * np.cos(np.pi * y)[:, None]
    return p, eps, hc


def independent_heat_totals(p, eps, hc, result):
    """Reconstruct physical W on the represented half-cylinder, not solver hr.

    Internal heat crosses inner film + metal wall. External heat leaves the
    jacket via the direct nonlinear T**4 law on its OWN, larger surface area.
    Lateral no-flux edges contribute zero net heat to the whole strip.
    """
    height, width = p['wall_mm'].shape
    ro = p['outer_diameter_mm'] / 2000
    ri = ro - p['wall_mm'] / 1000
    rj = ro + p['insulation_mm'] / 1000
    dx, dtheta = p['length_m'] / width, math.pi / height
    r_inner_per_m = (1 / (p['h_inner'] * 2 * math.pi * ri)
                     + np.log(ro / ri) / (2 * math.pi * p['wall_k']))
    inward = float(np.sum((p['bulk_c'] - result['wall_surface_c']) / r_inner_per_m)
                   * dx * dtheta / (2 * math.pi))
    jacket = result['jacket_surface_c']
    convection = hc * (jacket - p['ambient_c'])
    radiation = eps * 5.670374419e-8 * (
        (jacket + 273.15)**4 - (p['ambient_c'] + 273.15)**4)
    outward = float(np.sum(convection + radiation) * rj * dx * dtheta)
    return inward, outward


@pytest.mark.parametrize('insulation', [0., 40.])
@pytest.mark.parametrize('bulk', [-5., 85.])
def test_nonuniform_actual_nonlinear_heat_balance(insulation, bulk, record_property):
    p, eps, hc = nonuniform_case(insulation=insulation, bulk=bulk)
    result = solve_radiative_surface(**p, emissivity_total=eps, h_convection=hc)
    inward, outward = independent_heat_totals(p, eps, hc, result)
    relative_gap = abs(inward - outward) / max(abs(inward), abs(outward))
    record_property('inward_w', inward)
    record_property('outward_w', outward)
    record_property('independent_energy_relative_gap', relative_gap)
    assert np.ptp(result['jacket_surface_c']) > .01  # genuinely nonuniform test
    assert inward * (bulk - p['ambient_c']) > 0
    assert outward * (bulk - p['ambient_c']) > 0
    assert relative_gap < 1e-7


def test_two_grid_smooth_nonuniform_agreement(record_property):
    """Two-level agreement check; neither an order proof nor field calibration."""
    surfaces = []
    for shape in ((16, 24), (32, 48)):
        p, eps, hc = nonuniform_case(shape)
        result = solve_radiative_surface(**p, emissivity_total=eps, h_convection=hc)
        surfaces.append(result['jacket_surface_c'])
    fine_to_coarse = surfaces[1].reshape(16, 2, 24, 2).mean(axis=(1, 3))
    difference = surfaces[0] - fine_to_coarse
    rms = float(np.sqrt(np.mean(difference**2)))
    maximum = float(np.max(np.abs(difference)))
    variation = float(np.ptp(surfaces[1]))
    record_property('two_grid_rms_difference_c', rms)
    record_property('two_grid_max_difference_c', maximum)
    record_property('fine_surface_range_c', variation)
    # Numerical regression bounds relative to this case's temperature variation.
    assert rms < .002 * variation
    assert maximum < .005 * variation
