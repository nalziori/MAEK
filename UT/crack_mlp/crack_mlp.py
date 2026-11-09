"""Feature-based crack MLP. Inputs are RF and observable nominal metadata only."""
import numpy as np
import torch
from scipy.signal import hilbert
from ut_design_v2 import ca_cfar_power, matched_filter

from maek import ut

FEATURE_NAMES = [
    "log_peak_snr", "log_mean_power_snr", "log_max_cfar_ratio", "log_p95_cfar_ratio",
    "cfar_exceed_fraction", "peak_position_fraction", "energy_centroid_fraction",
    "energy_spread_fraction", "half_peak_width_us", "peak_energy_fraction",
    "log_gate_outside_energy_ratio", "nominal_wall_scaled", "observed_temperature_scaled",
    "nominal_angle_sine", "nominal_angle_cosine", "window_duration_us",
] + [f"bin{i}_{stat}" for i in range(8) for stat in ("log_mean_power_snr", "log_peak_power_snr")]


class CrackMLP(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = torch.nn.Sequential(
            torch.nn.Linear(len(FEATURE_NAMES), 32), torch.nn.ReLU(),
            torch.nn.Linear(32, 16), torch.nn.ReLU(), torch.nn.Linear(16, 1),
        )

    def forward(self, x):
        return self.layers(x).squeeze(-1)


def extract(cfg, rf, windows, nominal_wall_mm, nominal_angle_deg, observed_temp_c):
    """32 features, no defect label/depth/true velocity/source identifier input.

    Baseline-v4 windows are computed separately from nominal wall/angle and noisy T.
    Invalid signals are not silently converted to normal decisions by the caller.
    """
    rf = np.asarray(rf, np.float32)
    p = ut._p(cfg)
    if rf.ndim != 2 or rf.shape[1] != p["n"] or not np.isfinite(rf).all():
        raise ValueError("Finite RF with frozen sample count required")
    vectors = [np.asarray(x, float) for x in (nominal_wall_mm, nominal_angle_deg, observed_temp_c)]
    if any(x.shape != (len(rf),) or not np.isfinite(x).all() for x in vectors):
        raise ValueError("Aligned finite observable metadata required")
    windows = np.asarray(windows)
    if windows.shape != (len(rf), 2):
        raise ValueError("Aligned windows required")
    pulse = ut._pulse(cfg, np.arange(-64, 65) / p["fs"], 0.)
    features = np.empty((len(rf), len(FEATURE_NAMES)), np.float32)
    for i, (signal, (lo, hi)) in enumerate(zip(rf, windows)):
        lo, hi = int(lo), int(hi)
        if not 48 <= lo < hi <= p["n"]-48:
            raise ValueError("Invalid full-reference CFAR window")
        envelope = np.abs(hilbert(matched_filter(signal, pulse)))
        power = envelope**2
        found, threshold = ca_cfar_power(power)
        start = int(p["t0"]*p["fs"])
        outside = np.r_[signal[start:max(start, lo-48)], signal[min(p["n"], hi+48):]]
        noise = max(float(1.4826*np.median(np.abs(outside-np.median(outside)))), 1e-6)
        local = envelope[lo:hi]
        energy = power[lo:hi]
        scaled = energy/noise**2
        ratios = energy/np.maximum(threshold[lo:hi], 1e-30)
        peak = int(np.argmax(local))
        coordinate = np.linspace(0., 1., len(local))
        weights = energy/max(float(energy.sum()), 1e-30)
        centroid = float(coordinate@weights)
        spread = float(np.sqrt(((coordinate-centroid)**2)@weights))
        # Contiguous half-amplitude width, rather than count of all scattered peaks.
        left = right = peak
        while left > 0 and local[left-1] >= local[peak]*.5:
            left -= 1
        while right+1 < len(local) and local[right+1] >= local[peak]*.5:
            right += 1
        fraction = float(energy[max(0, peak-12):min(len(local), peak+13)].sum()/max(float(energy.sum()), 1e-30))
        outside_energy = np.r_[power[start:max(start, lo-48)], power[min(p["n"], hi+48):]]
        row = [np.log1p(local[peak]/noise), np.log1p(scaled.mean()), np.log1p(ratios.max()),
               np.log1p(np.quantile(ratios, .95)), float(found[lo:hi].mean()),
               peak/max(1, len(local)-1), centroid, spread, (right-left+1)/p["fs"]*1e6,
               fraction, np.log1p(energy.mean()/max(float(outside_energy.mean()), 1e-30)),
               vectors[0][i]/12., vectors[2][i]/175., np.sin(np.deg2rad(vectors[1][i])),
               np.cos(np.deg2rad(vectors[1][i])), (hi-lo)/p["fs"]*1e6]
        for section in np.array_split(scaled, 8):
            row.extend([np.log1p(section.mean()), np.log1p(section.max())])
        features[i] = row
    if not np.isfinite(features).all():
        raise ValueError("Nonfinite features; cannot classify")
    return features


def normalize(features, mean, scale):
    return ((features-np.asarray(mean))/np.asarray(scale)).astype(np.float32)
