"""Steady radial heat transfer for (insulated) pipes and saturated-steam helpers.

Shared by the energy-loss model (maek.energy) and the infrared model (maek.thermal).
Pipe wall and inner film resistances are neglected (small next to insulation + outer film).
"""

from __future__ import annotations

import numpy as np

# Antoine equation for water, log10(P[mmHg]) = A - B / (C + T[C]); (t_lo, t_hi, A, B, C)
_ANTOINE = ((1.0, 100.0, 8.07131, 1730.63, 233.426),
            (99.0, 374.0, 8.14019, 1810.94, 244.485))
_MMHG_TO_BAR = 0.00133322
ATM_BAR = 1.01325


def _resist(od_mm, ins_mm, k_w_mk, h_out_w_m2k):
    """(R per metre [K m/W], outer radius [m]) of insulation + outer film."""
    r1 = np.asarray(od_mm, float) / 2000.0
    ins = np.maximum(np.asarray(ins_mm, float), 0.0) / 1000.0
    r2 = r1 + ins
    k = np.asarray(k_w_mk, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        r_ins = np.where(ins > 0, np.log(r2 / r1) / (2 * np.pi * k), 0.0)
    r_out = 1.0 / (np.asarray(h_out_w_m2k, float) * 2 * np.pi * r2)
    return r_ins + r_out, r2


def heat_loss_w_per_m(t_in_c, t_amb_c, od_mm, ins_mm, k_w_mk, h_out_w_m2k):
    """Heat loss per metre of pipe (W/m). ins_mm <= 0 means a bare pipe."""
    r, _ = _resist(od_mm, ins_mm, k_w_mk, h_out_w_m2k)
    return (np.asarray(t_in_c, float) - np.asarray(t_amb_c, float)) / r


def surface_temp_c(t_in_c, t_amb_c, od_mm, ins_mm, k_w_mk, h_out_w_m2k):
    """Outer (jacket or bare-metal) surface temperature in C."""
    r, r2 = _resist(od_mm, ins_mm, k_w_mk, h_out_w_m2k)
    q = (np.asarray(t_in_c, float) - np.asarray(t_amb_c, float)) / r
    return np.asarray(t_amb_c, float) + q / (np.asarray(h_out_w_m2k, float) * 2 * np.pi * r2)


def sat_pressure_bar_abs(t_c):
    """Saturation pressure of water (bar absolute), Antoine equation, 1 to 374 C."""
    t = np.asarray(t_c, float)
    lo, hi = _ANTOINE
    a, b, c = np.where(t < lo[1], lo[2], hi[2]), np.where(t < lo[1], lo[3], hi[3]), \
        np.where(t < lo[1], lo[4], hi[4])
    return 10.0 ** (a - b / (c + t)) * _MMHG_TO_BAR


def sat_temp_c(p_bar_abs):
    """Saturation temperature of water (C) for an absolute pressure in bar."""
    p = np.asarray(p_bar_abs, float) / _MMHG_TO_BAR
    lo, hi = _ANTOINE
    t_hi = hi[3] / (hi[2] - np.log10(p)) - hi[4]
    t_lo = lo[3] / (lo[2] - np.log10(p)) - lo[4]
    return np.where(t_hi >= 100.0, t_hi, t_lo)
