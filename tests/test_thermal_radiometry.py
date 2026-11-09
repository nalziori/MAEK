import math
from decimal import Decimal, localcontext

import numpy as np
import pytest

from maek.thermal_radiometry import (
    C_LIGHT,
    H_PLANCK,
    K_BOLTZMANN,
    SIGMA_SB,
    BandRadiometry,
    gaussian_psf_radiance,
    planck_band_radiance,
    planck_spectral_radiance,
)


@pytest.fixture(scope="module")
def camera():
    return BandRadiometry()


def independent_band_frequency_integral(temperature_c):
    """Independent B_nu integration in Hz using Gauss-Legendre nodes, no B_lambda call."""
    nodes, weights = np.polynomial.legendre.leggauss(128)
    nu_low, nu_high = 299792458. / 14e-6, 299792458. / 8e-6
    frequency = (nu_low + nu_high) / 2 + nodes * (nu_high - nu_low) / 2
    values = 2 * 6.62607015e-34 * frequency ** 3 / 299792458. ** 2
    values /= np.expm1(6.62607015e-34 * frequency / (1.380649e-23 * (temperature_c + 273.15)))
    return float(np.sum(values * weights) * (nu_high - nu_low) / 2)


def test_si_constants_and_independent_decimal_monochromatic_reference():
    assert (H_PLANCK, C_LIGHT, K_BOLTZMANN) == (6.62607015e-34, 299792458., 1.380649e-23)
    with localcontext() as context:
        context.prec = 50
        h, c, k, wavelength, temperature = map(Decimal, ("6.62607015e-34", "299792458", "1.380649e-23", ".00001", "300"))
        expected = 2 * h * c * c / wavelength ** 5 / ((h * c / (wavelength * k * temperature)).exp() - 1) * Decimal(".000001")
    actual = planck_spectral_radiance(10., 26.85)
    assert actual == pytest.approx(float(expected), rel=2e-14)
    assert actual == pytest.approx(9.9240333300707, rel=1e-12)
    assert SIGMA_SB == pytest.approx(5.670374419184429e-8, rel=2e-15)


@pytest.mark.parametrize("temperature", [-80., -40., 26.85, 200., 600.])
def test_band_quadrature_matches_independent_frequency_integration(temperature, camera):
    expected = independent_band_frequency_integral(temperature)
    direct = planck_band_radiance(temperature)
    assert direct == pytest.approx(expected, rel=1.5e-5)
    assert camera.radiance(temperature) == pytest.approx(expected, rel=1.5e-5)
    if -80 < temperature < 600:
        # Independent radiance, rather than a self-roundtrip through the same LUT.
        assert camera.temperature(expected) == pytest.approx(temperature, abs=.003)


def test_full_spectrum_stefan_boltzmann_limit_and_band_is_not_exitance():
    wavelength = np.geomspace(.01, 10000, 30001)
    spectral = planck_spectral_radiance(wavelength, 26.85)
    integrated = np.sum((spectral[:-1] + spectral[1:]) * .5 * np.diff(wavelength))
    assert integrated == pytest.approx(SIGMA_SB * 300 ** 4 / math.pi, rel=2e-6)
    assert 0 < planck_band_radiance(26.85) < integrated


def test_monotone_lookup_roundtrip_and_no_out_of_range_clamp(camera):
    temperatures = np.linspace(-80, 600, 401).reshape(401, 1)
    radiance = camera.radiance(temperatures)
    assert np.all(np.diff(radiance.ravel()) > 0)
    np.testing.assert_allclose(camera.temperature(radiance), temperatures, atol=2e-13, rtol=0)
    for temperature in (-80.000001, 600.000001):
        with pytest.raises(ValueError, match="supported range"):
            camera.radiance(temperature)
    for value in (0., np.nextafter(camera.radiance_range[0], -math.inf),
                  np.nextafter(camera.radiance_range[1], math.inf)):
        with pytest.raises(ValueError, match="supported range"):
            camera.temperature(value)


def test_blackbody_and_matching_gray_compensation_broadcast(camera):
    surface = np.array([[-40., 25., 100.], [0., 30., 250.]])
    np.testing.assert_allclose(camera.mix(surface, 1, 20, 1, 15), camera.radiance(surface), rtol=0, atol=0)
    recovered = camera.compensate(camera.radiance(surface), 1, 1, 20, 15)
    np.testing.assert_allclose(recovered, surface, atol=2e-13)
    eps = np.array([[.15, .5, .95]])
    tau = np.array([[.6], [.9]])
    measured = camera.mix(surface, eps, 18., tau, 12.)
    expected = tau * (eps * camera.radiance(surface) + (1 - eps) * camera.radiance(18.)) + (1 - tau) * camera.radiance(12.)
    np.testing.assert_allclose(measured, expected, rtol=2e-15)
    np.testing.assert_allclose(camera.compensate(measured, eps, tau, 18., 12.), surface, atol=2e-12)


def test_reflection_tau_zero_and_isothermal_limits(camera):
    assert camera.mix(100, 0, 20, 1, 5) == camera.radiance(20)
    assert camera.mix(100, .8, 20, 0, 5) == camera.radiance(5)
    assert camera.mix(35, .17, 35, .63, 35) == camera.radiance(35)
    # Wrong reflected-temperature compensation changes apparent temperature.
    low_eps = camera.mix(70, .2, 40, 1, 20)
    wrong = camera.compensate(low_eps, .2, 1, 20, 20)
    assert wrong > 70
    with pytest.raises(ValueError, match="assumed_transmittance"):
        camera.compensate(low_eps, .2, 0, 20, 20)
    with pytest.raises(ValueError, match="assumed_emissivity"):
        camera.compensate(low_eps, 0, 1, 20, 20)


def test_psf_blurs_radiance_not_temperature_and_constant_is_preserved(camera):
    temperature = np.full((31, 31), 20.)
    temperature[:, 16:] = 180.
    blurred_radiance = gaussian_psf_radiance(camera.radiance(temperature), 1.3)
    brightness = camera.temperature(blurred_radiance)
    wrong_temperature_blur = gaussian_psf_radiance(temperature, 1.3)
    assert brightness[15, 15] - wrong_temperature_blur[15, 15] > 5
    assert np.all((brightness >= 20 - 1e-12) & (brightness <= 180 + 1e-12))
    constant = np.full((8, 9), camera.radiance(20))
    np.testing.assert_allclose(gaussian_psf_radiance(constant, 2), constant, atol=2e-13)
    copied = gaussian_psf_radiance(constant, 0)
    assert np.array_equal(copied, constant) and not np.shares_memory(copied, constant)


def test_configurable_band_and_explicit_supported_range():
    shorter = BandRadiometry(band_um=(3., 5.), temperature_range_c=(0., 400.), temperature_samples=1025)
    assert shorter.band_um == (3., 5.) and shorter.temperature_range_c == (0., 400.)
    assert shorter.temperature(shorter.radiance(220)) == pytest.approx(220)
    assert shorter.radiance(25) < planck_band_radiance(25, (8, 14))
    with pytest.raises(ValueError, match="supported range"):
        shorter.radiance(-1)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "25", [], complex(25, 1)])
def test_invalid_scalar_array_values_rejected(camera, bad):
    with pytest.raises(ValueError):
        camera.radiance(bad)
    with pytest.raises(ValueError):
        camera.temperature(bad)


def test_invalid_physics_and_shape_rejected(camera):
    for temperature in (-273.15, -300.):
        with pytest.raises(ValueError, match="absolute zero"):
            planck_band_radiance(temperature)
    for eps, tau in ((-1, .5), (1.1, .5), (.5, -.1), (.5, 1.1)):
        with pytest.raises(ValueError):
            camera.mix(25, eps, 20, tau, 20)
    with pytest.raises(ValueError):
        camera.mix(np.zeros((2, 3)), np.ones(5), 20, 1, 20)
    with pytest.raises(ValueError, match="supported range"):
        camera.compensate(camera.radiance(0), .01, 1, 200, 20)
    for sigma in (-1, math.nan, [1, 2], 1e10):
        with pytest.raises(ValueError):
            gaussian_psf_radiance(np.ones((3, 3)), sigma)
    with pytest.raises(ValueError):
        gaussian_psf_radiance(np.array([[-1.]]), 1)
    for kwargs in ({"band_um": (14, 8)}, {"temperature_range_c": (0, 0)},
                   {"wavelength_samples": 2}, {"temperature_samples": True}):
        with pytest.raises(ValueError):
            BandRadiometry(**kwargs)
