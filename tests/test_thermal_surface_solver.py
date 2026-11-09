"""Physical checks for the reduced surface solver, not field validation."""
import math

import numpy as np
import pytest

from maek.thermal_surface_solver import solve_surface


def parameters(shape=(16, 24)):
    return {
        'bulk_c': 85., 'ambient_c': 25., 'outer_diameter_mm': 114.3,
        'wall_mm': np.full(shape, 6.), 'insulation_mm': 0., 'wall_k': 45.,
        'insulation_k': .045, 'h_inner': 50., 'h_outer': 15., 'length_m': 1.,
    }


def independent_radial(p):
    # Independent per-metre series-resistance calculation for test references.
    ro = p['outer_diameter_mm'] / 2000
    ri = ro - p['wall_mm'] / 1000
    rj = ro + np.asarray(p['insulation_mm']) / 1000
    rin = 1 / (p['h_inner'] * 2 * math.pi * ri)
    rw = np.log(ro / ri) / (2 * math.pi * p['wall_k'])
    rins = np.log(rj / ro) / (2 * math.pi * p['insulation_k'])
    rout = 1 / (p['h_outer'] * 2 * math.pi * rj)
    q = (p['bulk_c'] - p['ambient_c']) / (rin + rw + rins + rout)
    return p['ambient_c'] + q * (rins + rout), p['ambient_c'] + q * rout


@pytest.mark.parametrize('insulation', [0., 50.])
def test_uniform_surface_matches_analytic_cylinder(insulation):
    p = {**parameters(), 'insulation_mm': insulation}
    result = solve_surface(**p)
    wall, jacket = independent_radial(p)
    np.testing.assert_allclose(result['wall_surface_c'], wall, rtol=0, atol=1e-8)
    np.testing.assert_allclose(result['jacket_surface_c'], jacket, rtol=0, atol=1e-8)
    assert result['residual_relative'] < 1e-9
    assert result['energy_relative_error'] < 1e-9


def test_isothermal_irregular_wall_has_no_signal():
    p = parameters()
    p['wall_mm'][:, 7:14] = 2.4
    p['bulk_c'] = p['ambient_c']
    result = solve_surface(**p)
    np.testing.assert_array_equal(result['wall_surface_c'], np.full((16, 24), 25.))
    np.testing.assert_array_equal(result['jacket_surface_c'], np.full((16, 24), 25.))
    assert result['iterations'] == 0
    assert result['energy_relative_error'] == 0


@pytest.mark.parametrize('bulk', [-35., 85.])
def test_maximum_principle_and_conservation_with_variable_coefficients(bulk):
    p = parameters()
    p['bulk_c'] = bulk
    p['wall_mm'][3:11, 7:18] = 2.
    p['insulation_mm'] = np.zeros((16, 24))
    p['insulation_mm'][4:13, 10:20] = 30.
    result = solve_surface(**p)
    for key in ('wall_surface_c', 'jacket_surface_c'):
        assert np.all(result[key] >= min(bulk, p['ambient_c']) - 1e-8)
        assert np.all(result[key] <= max(bulk, p['ambient_c']) + 1e-8)
    assert result['energy_relative_error'] < 1e-8
    assert result['residual_relative'] < 1e-9


def test_lateral_diffusion_reduces_local_peak_and_spreads_response():
    p = parameters((24, 36))
    base = solve_surface(**p)['wall_surface_c']
    p['wall_mm'][10:14, 16:20] = 2.4
    radial, _ = independent_radial(p)
    result = solve_surface(**p)['wall_surface_c']
    assert 0 < np.max(result - base) < np.max(radial - base)
    assert result[10, 15] > base[10, 15] + 1e-6


@pytest.mark.parametrize('bulk', [-35., 85.])
def test_local_external_transfer_respects_balance_and_bounds(bulk):
    p = {**parameters(), 'bulk_c': bulk}
    base = solve_surface(**p)['wall_surface_c']
    p['h_outer'] = np.full((16, 24), 15.)
    p['h_outer'][4:12, 8:16] = 60.
    result = solve_surface(**p)
    surface = result['wall_surface_c']
    assert np.all(surface >= min(bulk, p['ambient_c']) - 1e-8)
    assert np.all(surface <= max(bulk, p['ambient_c']) + 1e-8)
    assert abs(surface[8, 12] - p['ambient_c']) < abs(base[8, 12] - p['ambient_c'])
    assert result['energy_relative_error'] < 1e-8
    assert result['residual_relative'] < 1e-9


def smooth_solution(shape):
    h, w = shape
    p = parameters(shape)
    x = (np.arange(w) + .5) / w
    y = (np.arange(h) + .5) / h
    p['wall_mm'] = 4 + 1.5 * np.cos(2 * np.pi * x)[None, :] * np.cos(np.pi * y)[:, None]
    return solve_surface(**p)['wall_surface_c']


def restrict_four(image):
    h, w = image.shape
    return image.reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3))


def test_smooth_case_converges_under_mesh_refinement():
    coarse = smooth_solution((8, 12))
    medium = smooth_solution((16, 24))
    fine = smooth_solution((32, 48))
    first = np.sqrt(np.mean((coarse - restrict_four(medium)) ** 2))
    second = np.sqrt(np.mean((medium - restrict_four(fine)) ** 2))
    assert second < first * .7
    assert second < .01


@pytest.mark.parametrize('field,value', [
    ('wall_mm', np.zeros((4, 5))), ('wall_mm', np.ones(5)),
    ('wall_mm', np.full((4, 5), 60.)), ('wall_mm', np.full((4, 5), np.nan)),
    ('insulation_mm', -1.), ('insulation_mm', np.ones((3, 4))),
    ('length_m', 0.), ('length_m', float('inf')), ('h_inner', 0.),
    ('wall_k', -1.), ('circumferential_span_rad', 0.),
    ('h_outer', np.ones((3, 4))), ('h_outer', np.zeros((16, 24))),
])
def test_invalid_inputs_are_rejected(field, value):
    with pytest.raises(ValueError):
        solve_surface(**{**parameters(), field: value})
