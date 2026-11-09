"""Steady shell with convection AND gray radiation to an isothermal enclosure.

The enclosure temperature equals ambient air temperature. This is an explicit
boundary assumption, not a steelworks environment reconstruction. Spectral and
total emissivities need not agree; the caller must state its gray assumption.
No changes to the frozen v1 solver. Units SI except Celsius and millimetres.
"""
from __future__ import annotations

import numpy as np

from maek.thermal_surface_solver import solve_surface

SIGMA_SB = 2 * np.pi**5 * (1.380649e-23)**4 / (15 * (6.62607015e-34)**3 * 299792458**2)


def solve_radiative_surface(*, emissivity_total, h_convection, max_iterations=80,
                            tolerance_c=1e-6, **parameters):
    """Iterate exact factored T^4 boundary with no radiation double-counting.

    h_convection excludes radiation. Existing solver's h_outer receives the
    combined coefficient, updated from the jacket temperature. Non-convergence
    fails rather than returning a training sample. Lateral shell approximation
    and insulated-jacket omissions remain those of solve_surface.
    """
    if 'h_outer' in parameters:
        raise ValueError('Provide h_convection, not an effective h_outer')
    shape = np.asarray(parameters['wall_mm']).shape
    eps = np.asarray(emissivity_total, dtype=float)
    hc = np.asarray(h_convection, dtype=float)
    for name, value in [('emissivity_total', eps), ('h_convection', hc)]:
        if value.ndim != 0 and value.shape != shape:
            raise ValueError(f'{name} must be scalar or match wall_mm')
        if not np.isfinite(value).all() or np.any(value <= 0):
            raise ValueError(f'{name} must be finite and positive')
    if np.any(eps > 1):
        raise ValueError('emissivity_total must be <=1')
    if (not isinstance(max_iterations, int) or max_iterations < 1
            or not np.isfinite(tolerance_c) or tolerance_c <= 0):
        raise ValueError('Invalid iteration budget/tolerance')
    ambient = float(parameters['ambient_c'])
    enclosure_k = ambient + 273.15
    estimate = np.full(shape, ambient)
    for iteration in range(1, max_iterations + 1):
        surface_k = estimate + 273.15
        hr = eps * SIGMA_SB * (surface_k + enclosure_k) * (
            surface_k**2 + enclosure_k**2)
        result = solve_surface(**parameters, h_outer=hc + hr)
        surface = result['jacket_surface_c']
        new_k = surface + 273.15
        # Factored difference avoids cancellation for nearly isothermal scenes.
        true_hr = eps * SIGMA_SB * (new_k + enclosure_k) * (new_k**2 + enclosure_k**2)
        q_physical = (hc + true_hr) * (surface - ambient)
        q_solved = (hc + hr) * (surface - ambient)
        relative = float(np.max(np.abs(q_physical - q_solved)) / max(
            1., float(np.max(np.abs(q_physical)))))
        if np.max(np.abs(surface - estimate)) <= tolerance_c and relative <= 1e-7:
            return {**result, 'radiation_iterations': iteration,
                    'external_balance_relative_error': relative,
                    'radiation_coefficient_w_m2_k': true_hr}
        estimate = .5 * estimate + .5 * surface
    raise RuntimeError('Nonlinear radiation boundary did not converge')
