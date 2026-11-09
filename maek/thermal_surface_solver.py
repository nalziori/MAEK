"""Steady reduced thin-shell thermal sensitivity model using only NumPy.

The outer metal surface is a rectangular axial/arc-length strip. Independent
radial inner-film/wall paths feed it; insulation/outer-film paths remove heat.
In-plane sheet conductance is k_wall * wall thickness. All four represented
strip edges have zero lateral flux, including the front-half circumference edges.
These are assumed boundaries, not a reconstruction of the pipe's hidden half.

This approximation omits through-wall temperature variation in lateral transport,
insulation lateral conduction, transients, fluid flow, cracks, leaks, spectral gas
imaging and 3-D geometry. It is not a field- or FEM-validated defect simulator.
"""
from __future__ import annotations

import math

import numpy as np

from maek.thermal_feasibility import surface_temperature


def _positive_scalar(value, name):
    value = np.asarray(value, dtype=np.float64)
    if value.ndim != 0 or not np.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be a finite positive scalar')
    return float(value)


def _pcg(apply, diagonal, rhs, initial):
    """Jacobi-preconditioned CG; verify the true residual before accepting."""
    norm_rhs = float(np.linalg.norm(rhs))
    if norm_rhs == 0:
        return np.zeros_like(rhs), 0., 0
    tolerance = 1e-10 * norm_rhs
    solution = initial.copy()
    residual = rhs - apply(solution)
    if np.linalg.norm(residual) <= tolerance:
        return solution, float(np.linalg.norm(residual) / norm_rhs), 0
    z = residual / diagonal
    direction = z.copy()
    rz = float(np.sum(residual * z))
    for iteration in range(1, max(1000, 10 * rhs.size) + 1):
        applied = apply(direction)
        denominator = float(np.sum(direction * applied))
        if not np.isfinite(denominator) or denominator <= 0 or not np.isfinite(rz):
            raise RuntimeError('Thermal PCG breakdown: non-positive or non-finite curvature')
        alpha = rz / denominator
        solution += alpha * direction
        residual -= alpha * applied
        if np.linalg.norm(residual) <= tolerance:
            true_residual = rhs - apply(solution)
            norm_true = float(np.linalg.norm(true_residual))
            if norm_true <= tolerance:
                return solution, norm_true / norm_rhs, iteration
            # Restart if accumulated rounding makes the recursive residual optimistic.
            residual = true_residual
            z = residual / diagonal
            direction = z.copy()
            rz = float(np.sum(residual * z))
            continue
        z = residual / diagonal
        next_rz = float(np.sum(residual * z))
        direction = z + (next_rz / rz) * direction
        rz = next_rz
    raise RuntimeError('Thermal PCG did not converge to relative residual 1e-10')


def solve_surface(*, bulk_c, ambient_c, outer_diameter_mm, wall_mm,
                  insulation_mm, wall_k, insulation_k, h_inner, h_outer,
                  length_m, circumferential_span_rad=math.pi):
    """Solve a cell-centred finite-volume thin-shell heat balance.

wall_mm is H x W (H,W >= 2); insulation_mm and h_outer are scalar or the same
H x W. All other inputs are scalars. Conductivities are W/(m K), film coefficients
W/(m² K), length metres, temperatures Celsius, span radians. x is axial;
y is arc length on the fixed outer metal radius. Grid spacings are length/W
and outer_radius*span/H. Harmonic face sheet conductance conserves flux.

Returns float64 wall_surface_c/jacket_surface_c arrays and solver diagnostics.
residual_relative uses the ambient-subtracted equation. energy_relative_error
is |total inward - total outward heat| / max(|inward|, |outward|), zero when
both vanish. Nonconvergence or invalid/non-finite coefficients raises.
"""
    wall = np.asarray(wall_mm, dtype=np.float64)
    insulation = np.asarray(insulation_mm, dtype=np.float64)
    if wall.ndim != 2 or min(wall.shape) < 2:
        raise ValueError('wall_mm must be an H x W array with H,W >= 2')
    if insulation.ndim != 0 and insulation.shape != wall.shape:
        raise ValueError('insulation_mm must be scalar or match wall_mm shape')
    length = _positive_scalar(length_m, 'length_m')
    span = _positive_scalar(circumferential_span_rad, 'circumferential_span_rad')
    if span > 2 * math.pi:
        raise ValueError('circumferential_span_rad must be <= 2*pi')
    diameter = _positive_scalar(outer_diameter_mm, 'outer_diameter_mm')
    kw = _positive_scalar(wall_k, 'wall_k')
    ki = _positive_scalar(insulation_k, 'insulation_k')
    hi = _positive_scalar(h_inner, 'h_inner')
    ho = np.asarray(h_outer, dtype=np.float64)
    if (ho.ndim != 0 and ho.shape != wall.shape) or not np.isfinite(ho).all() \
            or np.any(ho <= 0):
        raise ValueError('h_outer must be finite, positive, and scalar or match wall_mm shape')
    temperatures = np.asarray([bulk_c, ambient_c], dtype=np.float64)
    if temperatures.shape != (2,):
        raise ValueError('bulk_c and ambient_c must be scalars')
    bulk, ambient = temperatures
    radial = surface_temperature(
        bulk_c=bulk, ambient_c=ambient, outer_diameter_mm=diameter,
        wall_mm=wall, insulation_mm=insulation, wall_k=kw, insulation_k=ki,
        h_inner=hi, h_outer=ho)['resistances']
    ro = diameter / 2000
    dx = length / wall.shape[1]
    dy = ro * span / wall.shape[0]
    gin = 1 / (2 * math.pi * ro * (radial['inner_film'] + radial['wall']))
    gout = 1 / (2 * math.pi * ro * (radial['insulation'] + radial['outer_film']))
    reaction = gin + gout
    sheet = kw * wall / 1000  # W/K, per metre transverse width of sheet.
    face_x = 2 / (1 / sheet[:, :-1] + 1 / sheet[:, 1:]) / dx ** 2
    face_y = 2 / (1 / sheet[:-1, :] + 1 / sheet[1:, :]) / dy ** 2
    diagonal = reaction.copy()
    diagonal[:, :-1] += face_x
    diagonal[:, 1:] += face_x
    diagonal[:-1, :] += face_y
    diagonal[1:, :] += face_y
    if (not all(np.isfinite(v).all() for v in (gin, gout, face_x, face_y, diagonal))
            or np.any(gin <= 0) or np.any(gout <= 0) or np.any(diagonal <= 0)):
        raise ValueError('Derived conductances must be finite and positive')

    def apply(excess):
        result = reaction * excess
        flux_x = face_x * (excess[:, :-1] - excess[:, 1:])
        result[:, :-1] += flux_x
        result[:, 1:] -= flux_x
        flux_y = face_y * (excess[:-1, :] - excess[1:, :])
        result[:-1, :] += flux_y
        result[1:, :] -= flux_y
        return result

    rhs = gin * (bulk - ambient)
    if not np.isfinite(rhs).all():
        raise ValueError('Derived heat input must be finite')
    excess, residual, iterations = _pcg(apply, diagonal, rhs, rhs / reaction)
    wall_surface = ambient + excess
    jacket_surface = ambient + excess * radial['outer_film'] / (
        radial['insulation'] + radial['outer_film'])
    inward = float(np.sum(gin * (bulk - wall_surface)) * dx * dy)
    outward = float(np.sum(gout * excess) * dx * dy)
    scale = max(abs(inward), abs(outward))
    energy_error = abs(inward - outward) / scale if scale else 0.
    if not (np.isfinite(wall_surface).all() and np.isfinite(jacket_surface).all()
            and np.isfinite(energy_error)):
        raise RuntimeError('Non-finite thermal solution')
    return {
        'wall_surface_c': wall_surface, 'jacket_surface_c': jacket_surface,
        'residual_relative': residual, 'energy_relative_error': energy_error,
        'iterations': iterations,
    }
