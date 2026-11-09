"""Ideal band radiometry for synthetic sensitivity work, not camera calibration.

Planck spectral radiance is integrated over a configurable ideal flat response
(default 8--14 micrometres), in vacuum (n=1). Emissivity and atmospheric
transmittance are gray within that band; the target is opaque. A reflected
temperature represents an effective blackbody surrounding. No measured camera
response, optics throughput, atmospheric spectrum, scattering, or real sensor
calibration is supplied. A Gaussian PSF is an assumed spatial kernel, not a
measured camera MTF. Apply it to received radiance BEFORE temperature inversion.

Primary sources verified 2026-11-08:
* FLIR measurement formula, terms and assumptions:
  https://support.flir.com/docdownload/assets/web/4jau/en-us/T505006.xml.html
* FLIR official manual section 13, equations (2)--(4):
  https://support.flir.com/docdownload/assets/dl/t559495-en-us%24aa.pdf
  L = tau*(eps*B(Tobj)+(1-eps)*B(Trefl)) + (1-tau)*B(Tatm).
  Its prose item 3 has an extra tau; the total equations do NOT. The implemented
  total equation preserves an isothermal scene and the tau=0 atmosphere limit.
* NIST optical-metrology course, slide 17, Planck spectral radiance (set n=1):
  https://www.nist.gov/system/files/documents/iaao/SIM-Metrology-School-Optical-Metrology-Y-Ohno-2.pdf
* Exact current SI h, c, k (not the older constants printed on the 2013 slide):
  https://www.nist.gov/pml/special-publication-330/sp-330-section-2

Temperature and radiance lookup endpoints are explicit: values outside them
raise ValueError. There is no implicit extrapolation, saturation or clamping.
"""
from __future__ import annotations

import math
from numbers import Integral

import numpy as np

H_PLANCK = 6.62607015e-34  # J s, exact SI definition
C_LIGHT = 299792458.0  # m/s, exact SI definition
K_BOLTZMANN = 1.380649e-23  # J/K, exact SI definition
SIGMA_SB = 2 * math.pi ** 5 * K_BOLTZMANN ** 4 / (15 * H_PLANCK ** 3 * C_LIGHT ** 2)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _numeric(value, name):
    try:
        raw = np.asarray(value)
        _require(raw.dtype.kind in "fiu" and raw.size > 0, f"{name} must be a nonempty real numeric value")
        result = raw.astype(np.float64)
    except (TypeError, OverflowError) as error:
        raise ValueError(f"{name} must be a finite real numeric value") from error
    _require(np.isfinite(result).all(), f"{name} must be finite")
    return result


def _result(value):
    value = np.asarray(value, dtype=np.float64)
    return float(value) if value.ndim == 0 else value


def _temperature(value, name="temperature_c"):
    result = _numeric(value, name)
    _require(np.all(result > -273.15), f"{name} must be above absolute zero")
    return result


def _fraction(value, name, *, positive=False):
    result = _numeric(value, name)
    _require(np.all((result > 0 if positive else result >= 0) & (result <= 1)),
             f"{name} must be in {'(0,1]' if positive else '[0,1]'}")
    return result


def _band(band_um):
    band = _numeric(band_um, "band_um")
    _require(band.shape == (2,) and 0 < band[0] < band[1], "band_um must be two increasing positive endpoints")
    return float(band[0]), float(band[1])


def planck_spectral_radiance(wavelength_um, temperature_c):
    """Planck B_lambda in W/(m² sr micrometre), with NumPy broadcasting.

    Wavelength is a vacuum wavelength in micrometres. Temperature is Celsius.
    Use T[...,None] with a wavelength vector for an outer spectral grid.
    """
    wavelength = _numeric(wavelength_um, "wavelength_um")
    _require(np.all(wavelength > 0), "wavelength_um must be positive")
    temperature = _temperature(temperature_c) + 273.15
    wavelength, temperature = np.broadcast_arrays(wavelength * 1e-6, temperature)
    # log(expm1(x)) = x + log(1-exp(-x)); avoids overflow for cold/shortwave cases.
    with np.errstate(over="ignore", under="ignore", divide="ignore", invalid="ignore"):
        exponent = (H_PLANCK * C_LIGHT / K_BOLTZMANN) / wavelength / temperature
        log_denominator = exponent + np.log(-np.expm1(-exponent))
        log_numerator = math.log(2 * H_PLANCK * C_LIGHT ** 2 * 1e-6) - 5 * np.log(wavelength)
        radiance = np.exp(log_numerator - log_denominator)
    _require(np.isfinite(radiance).all(), "Spectral inputs exceed floating-point radiance range")
    return _result(radiance)


def planck_band_radiance(temperature_c, band_um=(8., 14.), wavelength_samples=257):
    """Direct trapezoidal Planck integration, W/(m² sr), ideal unit band response.

    Not a band average: no division by bandwidth. Uniform wavelength quadrature
    has an explicit sample count; convergence depends on the chosen band/range.
    Processing temperatures in blocks limits the temporary spectral-array size.
    """
    temperature = _temperature(temperature_c)
    low, high = _band(band_um)
    _require(isinstance(wavelength_samples, Integral) and not isinstance(wavelength_samples, bool)
             and wavelength_samples >= 3, "wavelength_samples must be an integer >=3")
    wavelength = np.linspace(low, high, wavelength_samples)
    flat, answer = temperature.ravel(), np.empty(temperature.size, dtype=np.float64)
    weights = np.full(wavelength_samples, (high - low) / (wavelength_samples - 1))
    weights[[0, -1]] *= .5
    for start in range(0, flat.size, 512):
        spectrum = planck_spectral_radiance(wavelength, flat[start:start + 512, None])
        answer[start:start + 512] = np.sum(spectrum * weights, axis=-1)
    _require(np.isfinite(answer).all(), "Integrated radiance exceeds floating-point range")
    return _result(answer.reshape(temperature.shape))


class BandRadiometry:
    """Fast monotone forward/inverse lookup over an explicitly supported range.

    Table values use direct Planck wavelength quadrature; both directions use
    piecewise-linear interpolation on the same table. Defaults use 8193 uniform
    temperatures over -80..600°C (~0.083°C spacing) and 257 wavelengths. Lookup
    and quadrature error are numerical approximations, not calibration accuracy.
    All physical/camera parameter arrays may broadcast against the input image.
    """

    def __init__(self, band_um=(8., 14.), temperature_range_c=(-80., 600.),
                 wavelength_samples=257, temperature_samples=8193):
        self.band_um = _band(band_um)
        supported = _temperature(temperature_range_c, "temperature_range_c")
        _require(supported.shape == (2,) and supported[0] < supported[1],
                 "temperature_range_c must have two increasing endpoints")
        _require(isinstance(temperature_samples, Integral) and not isinstance(temperature_samples, bool)
                 and temperature_samples >= 2, "temperature_samples must be an integer >=2")
        self.temperature_range_c = tuple(float(v) for v in supported)
        self.wavelength_samples = wavelength_samples
        self.temperature_samples = int(temperature_samples)
        self._temperature_grid = np.linspace(*self.temperature_range_c, self.temperature_samples)
        self._radiance_grid = planck_band_radiance(self._temperature_grid, self.band_um, wavelength_samples)
        _require(np.all(np.diff(self._radiance_grid) > 0), "Lookup radiance must be strictly increasing")
        self.radiance_range = float(self._radiance_grid[0]), float(self._radiance_grid[-1])
        self._temperature_grid.setflags(write=False)
        self._radiance_grid.setflags(write=False)

    def radiance(self, temperature_c):
        """Blackbody band radiance W/(m² sr); out-of-range temperatures raise."""
        temperature = _temperature(temperature_c)
        low, high = self.temperature_range_c
        _require(np.all((temperature >= low) & (temperature <= high)),
                 f"temperature_c outside supported range [{low}, {high}]")
        result = np.interp(temperature.ravel(), self._temperature_grid, self._radiance_grid)
        return _result(result.reshape(temperature.shape))

    def temperature(self, radiance):
        """Band brightness temperature °C; out-of-table radiance raises, never clamps."""
        radiance = _numeric(radiance, "radiance")
        low, high = self.radiance_range
        _require(np.all((radiance >= low) & (radiance <= high)),
                 f"radiance outside supported range [{low}, {high}] W/(m2 sr)")
        result = np.interp(radiance.ravel(), self._radiance_grid, self._temperature_grid)
        return _result(result.reshape(radiance.shape))

    def mix(self, surface_c, emissivity, reflected_c, transmittance, atmosphere_c):
        """Opaque gray target + reflected surroundings + isothermal atmosphere.

        Forward eps and tau may include zero: eps=0 is pure reflection, tau=0
        loses all target information and returns atmospheric radiance only.
        No atmospheric attenuation is applied again to its own emission term.
        """
        eps = _fraction(emissivity, "emissivity")
        tau = _fraction(transmittance, "transmittance")
        target, reflected, atmosphere, eps, tau = np.broadcast_arrays(
            self.radiance(surface_c), self.radiance(reflected_c), self.radiance(atmosphere_c), eps, tau)
        surface_mix = reflected + eps * (target - reflected)
        surface_mix = np.where(eps == 1, target, surface_mix)
        received = atmosphere + tau * (surface_mix - atmosphere)
        received = np.where(tau == 1, surface_mix, received)
        return _result(received)

    def compensate(self, radiance, assumed_emissivity, assumed_transmittance,
                   assumed_reflected_c, assumed_atmosphere_c):
        """Invert assumed camera compensation, then lookup apparent object °C.

        Positive eps/tau are necessary to identify object radiance. Wrong camera
        assumptions can imply negative/out-of-range object radiance: that raises
        ValueError. Callers must explicitly handle invalid observations; no
        hidden repair, clipping, epsilon substitution or range extrapolation.
        Spatially varying camera assumptions broadcast, but do not undo PSF blur.
        """
        measured = _numeric(radiance, "radiance")
        _require(np.all(measured >= 0), "Measured radiance must be nonnegative")
        eps = _fraction(assumed_emissivity, "assumed_emissivity", positive=True)
        tau = _fraction(assumed_transmittance, "assumed_transmittance", positive=True)
        measured, eps, tau, reflected, atmosphere = np.broadcast_arrays(
            measured, eps, tau, self.radiance(assumed_reflected_c), self.radiance(assumed_atmosphere_c))
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            object_radiance = reflected + ((measured - atmosphere) / tau + atmosphere - reflected) / eps
        object_radiance = np.where((eps == 1) & (tau == 1), measured, object_radiance)
        return self.temperature(object_radiance)


def gaussian_psf_radiance(radiance, sigma_px, truncate=3.):
    """Separable normalized Gaussian PSF on HxW radiance, with edge replication.

    sigma=0 returns a copy. The finite kernel radius is ceil(truncate*sigma),
    capped by validation at 4096 pixels to avoid unbounded kernel allocation.
    This preserves constant radiance but does not claim global flux conservation
    across a finite cropped field of view with replicated boundaries.
    """
    radiance = _numeric(radiance, "radiance")
    _require(radiance.ndim == 2 and np.all(radiance >= 0), "PSF requires nonnegative HxW radiance")
    sigma, cutoff = _numeric(sigma_px, "sigma_px"), _numeric(truncate, "truncate")
    _require(sigma.ndim == cutoff.ndim == 0 and sigma >= 0 and cutoff > 0,
             "sigma_px must be a nonnegative scalar and truncate a positive scalar")
    if sigma == 0:
        return radiance.copy()
    radius_float = float(sigma) * float(cutoff)
    _require(math.isfinite(radius_float) and radius_float <= 4096, "PSF kernel radius exceeds supported 4096 pixels")
    radius = max(1, math.ceil(radius_float))
    coordinates = np.arange(-radius, radius + 1, dtype=np.float64)
    with np.errstate(over="ignore", under="ignore"):
        weights = np.exp(-.5 * (coordinates / float(sigma)) ** 2)
    weights /= weights.sum()
    result = radiance.copy()
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (radius, radius)
        padded = np.pad(result, pad, mode="edge")
        result = sum(weight * np.take(padded, np.arange(result.shape[axis]) + i, axis=axis)
                     for i, weight in enumerate(weights))
    return result
