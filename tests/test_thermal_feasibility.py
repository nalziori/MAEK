import math

import numpy as np
import pytest

from maek.thermal_feasibility import (
    apparent_temperature,
    controlled_case,
    surface_temperature,
)


def example():
    return {'bulk_c': 85., 'ambient_c': 25., 'outer_diameter_mm': 114.3, 'wall_mm': 6.,
            'insulation_mm': 0., 'wall_k': 45., 'insulation_k': .045,
            'h_inner': 50., 'h_outer': 15.}


def test_known_series_resistances_and_energy_balance():
    # Independent hand solution: each of four resistances exactly 1 K m/W.
    result = surface_temperature(bulk_c=100, ambient_c=10, outer_diameter_mm=100,
        wall_mm=25, insulation_mm=50, wall_k=math.log(2)/(2*math.pi),
        insulation_k=math.log(2)/(2*math.pi), h_inner=1/(2*math.pi*.025),
        h_outer=1/(2*math.pi*.1))
    assert list(result['resistances'].values()) == pytest.approx([1, 1, 1, 1])
    assert result['heat_w_per_m'] == pytest.approx(22.5)
    assert result['surface_c'] == pytest.approx(32.5)


def test_isothermal_wall_loss_has_no_heat_signature():
    result = surface_temperature(**{**example(), 'bulk_c': 25., 'wall_mm': [6., 3., 1.]})
    np.testing.assert_allclose(result['surface_c'], 25.)
    np.testing.assert_allclose(result['heat_w_per_m'], 0.)


def test_hot_and_cold_sign_and_bounded_surface():
    hot = surface_temperature(**example())
    cold = surface_temperature(**{**example(), 'bulk_c': -35.})
    assert 25 < hot['surface_c'] < 85
    assert -35 < cold['surface_c'] < 25
    assert hot['heat_w_per_m'] == pytest.approx(-cold['heat_w_per_m'])


def test_insulation_reduces_surface_response_in_this_fixed_case():
    def change(ins):
        a = surface_temperature(**{**example(), 'insulation_mm': ins})['surface_c']
        b = surface_temperature(**{**example(), 'insulation_mm': ins,
                                   'wall_mm': 2.4})['surface_c']
        return abs(b - a)
    assert 0 < change(50.) < change(0.)


@pytest.mark.parametrize('field,value', [('wall_mm', 0), ('wall_mm', 100),
    ('h_inner', 0), ('h_outer', -1), ('wall_k', 0), ('insulation_mm', -1),
    ('bulk_c', -274), ('ambient_c', float('nan'))])
def test_invalid_physics_rejected(field, value):
    with pytest.raises(ValueError):
        surface_temperature(**{**example(), field: value})


def test_correct_camera_settings_recover_true_temperature():
    temperatures = np.array([5., 25., 85.])
    np.testing.assert_allclose(apparent_temperature(temperatures, .08, 10, .08, 10),
                               temperatures, atol=1e-10)
    assert apparent_temperature(85., 1., 10., 1., 10.) == pytest.approx(85.)


def test_controlled_pairs_keep_unmodelled_crack_out_of_image():
    params = {**example(), 'loss_fraction': .6, 'emissivity': .3,
              'noise_sigma_apparent_c': .1, 'reflected_c': 10.,
              'camera_emissivity': .95}
    a = controlled_case(params, seed=41)
    b = controlled_case(params, seed=41)
    np.testing.assert_array_equal(a['temperature_c'], b['temperature_c'])
    np.testing.assert_array_equal(a['temperature_c'][0], a['temperature_c'][3])
    assert a['peak_wall_loss_delta_apparent_c'] > 0
    assert a['peak_reflection_delta_apparent_c'] > 0
    assert a['temperature_c'].dtype == np.float32
    assert np.isfinite(a['temperature_c']).all()
    # Outside the physical perturbation's pipe, all variant inputs coincide.
    np.testing.assert_array_equal(a['temperature_c'][0, :24],
                                  a['temperature_c'][1, :24])
