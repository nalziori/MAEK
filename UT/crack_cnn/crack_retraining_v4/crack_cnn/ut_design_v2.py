"""B UT design candidates. No trained weights or field-performance claims.

Active input is angle-beam shear-wave pulse-echo RF, not normal-beam or low-frequency guided waves.
The existing shared maek detectors remain unchanged for paired comparison.
"""
from dataclasses import dataclass

import numpy as np
import torch
from scipy.optimize import minimize_scalar
from scipy.signal import correlate, hilbert


def coherent_average(shots, *, aligned, shot_ids, expected_shots=16):
    """Average genuine, trigger-aligned RF repeats of the same position.

    Registration and shot provenance must be verified upstream. Repeating one stored
    waveform 16 times is not acquisition averaging and supplies no noise reduction evidence.
    """
    shots = np.asarray(shots, dtype=float)
    if shots.ndim != 2 or len(shots) != expected_shots or not aligned:
        raise ValueError("Require 16 aligned RF shots from the same position")
    if len(shot_ids) != expected_shots or len(set(shot_ids)) != expected_shots:
        raise ValueError("Require distinct shot provenance IDs")
    if not np.isfinite(shots).all():
        raise ValueError("Non-finite RF shots")
    return shots.mean(axis=0)


def matched_filter(signal, reference_pulse):
    x, pulse = np.asarray(signal, float), np.asarray(reference_pulse, float)
    if x.ndim != 1 or pulse.ndim != 1 or len(pulse) % 2 != 1:
        raise ValueError("Require 1D RF and odd-length calibrated reference pulse")
    energy = float(pulse @ pulse)
    if energy <= 0 or not np.isfinite(x).all() or not np.isfinite(pulse).all():
        raise ValueError("Invalid RF/reference pulse")
    return correlate(x, pulse, mode="same", method="fft") / energy


def ca_cfar_power(power, *, reference_each_side=32, guard_each_side=16, cell_pfa=1e-3):
    """Literal two-sided cell-averaging CFAR on nonnegative power.

    alpha = N(Pfa^(-1/N)-1) assumes independent exponential reference/CUT powers.
    Matched RF samples are correlated; final scene FAR must be separately calibrated.
    Edges without full reference windows are unavailable, never zero-padded noise cells.
    """
    power = np.asarray(power, dtype=float)
    r, g = int(reference_each_side), int(guard_each_side)
    if power.ndim != 1 or not np.isfinite(power).all() or (power < 0).any():
        raise ValueError("Require finite nonnegative power")
    if r < 1 or g < 0 or not 0 < cell_pfa < 1:
        raise ValueError("Invalid CFAR parameters")
    threshold = np.full(len(power), np.nan)
    margin = r + g
    index = np.arange(margin, len(power)-margin)
    cumulative = np.r_[0.0, np.cumsum(power)]
    left = cumulative[index-g] - cumulative[index-g-r]
    right = cumulative[index+g+r+1] - cumulative[index+g+1]
    n = 2*r
    alpha = n * (cell_pfa**(-1/n)-1)
    threshold[index] = alpha * (left+right)/n
    return power > threshold, threshold


PIT_FEATURES = ("log_first_snr", "log_second_first_peak", "log_second_first_energy",
                "first_spread_us", "second_spread_us", "first_tail_fraction",
                "second_tail_fraction", "echo_gap_us")


def echo_features(signal, sampling_hz, first_gate, second_gate, noise_gate):
    """Relative attenuation and energy-weighted temporal spread; preserve gain ratios.

    Gates are supplied by calibrated timing, never pit/depth ground truth. They must be
    fixed for a probe/material protocol before test inspection. No per-trace max scaling.
    """
    x = np.asarray(signal, float)
    if x.ndim != 1 or not np.isfinite(x).all() or sampling_hz <= 0:
        raise ValueError("Invalid RF/sampling rate")
    for lo, hi in (first_gate, second_gate, noise_gate):
        if not 0 <= lo < hi <= len(x) or hi-lo < 4:
            raise ValueError("Invalid echo/noise gate")
    if not first_gate[1] <= second_gate[0]:
        raise ValueError("Echo gates must be ordered and disjoint")
    for gate in (first_gate, second_gate):
        if max(gate[0], noise_gate[0]) < min(gate[1], noise_gate[1]):
            raise ValueError("Noise gate overlaps an echo gate")
    noise = x[slice(*noise_gate)]
    x = x - np.median(noise)
    sigma = 1.4826*np.median(np.abs(noise-np.median(noise)))
    if sigma <= np.finfo(float).tiny:
        raise ValueError("Noise scale unidentifiable")
    envelope = np.abs(hilbert(x))
    stats = []
    for lo, hi in (first_gate, second_gate):
        e = envelope[lo:hi]
        energy = e*e
        total = float(energy.sum())
        if total <= 0:
            raise ValueError("Echo energy unidentifiable")
        t = np.arange(lo, hi)/sampling_hz*1e6
        center = float(t @ energy/total)
        spread = float(np.sqrt(((t-center)**2) @ energy/total))
        tail = float(energy[t > center+spread].sum()/total)
        stats.append((float(e.max()), total, spread, tail, center))
    a, b = stats
    return np.asarray([np.log(a[0]/sigma), np.log(max(b[0], 1e-30)/max(a[0], 1e-30)),
                       np.log(b[1]/a[1]), a[2], b[2], a[3], b[3], b[4]-a[4]])


class PitSmallMLP(torch.nn.Module):
    """Train-only standardized features -> 16 -> 8 -> pit logit."""
    def __init__(self):
        super().__init__()
        self.layers = torch.nn.Sequential(torch.nn.Linear(len(PIT_FEATURES), 16), torch.nn.ReLU(),
                                          torch.nn.Linear(16, 8), torch.nn.ReLU(), torch.nn.Linear(8, 1))

    def forward(self, features):
        return self.layers(features).squeeze(-1)


class SmallWaveCNN(torch.nn.Module):
    """Separate instances for pit/crack; calibrated RF + envelope + gate mask.

    Noise normalization/scale parameters are fitted on training only. Masked mean and max
    retain both distributed waveform spreading and a localized echo response.
    """
    def __init__(self):
        super().__init__()
        self.body = torch.nn.Sequential(torch.nn.Conv1d(3, 16, 17, stride=4, padding=8), torch.nn.ReLU(),
                                         torch.nn.Conv1d(16, 24, 9, stride=2, padding=4), torch.nn.ReLU(),
                                         torch.nn.Conv1d(24, 32, 9, stride=2, padding=4), torch.nn.ReLU())
        self.head = torch.nn.Sequential(torch.nn.Linear(64, 16), torch.nn.ReLU(), torch.nn.Linear(16, 1))

    def forward(self, channels):
        h = self.body(channels)
        mask = torch.nn.functional.adaptive_max_pool1d(channels[:, 2:3], h.shape[-1]) > 0
        count = mask.sum(dim=-1).clamp(min=1)
        mean = (h*mask).sum(dim=-1)/count
        maximum = h.masked_fill(~mask, -1e4).amax(dim=-1)
        logit = self.head(torch.cat([mean, maximum], dim=1)).squeeze(-1)
        return torch.where(mask.any(dim=(1, 2)), logit, torch.full_like(logit, -1e4))


@dataclass(frozen=True)
class FrozenOperatingPoint:
    """Parameters selected on validation and calibrated on normal calibration units only."""
    threshold: float
    mlp_weight: float
    model_sha256: str
    calibration_manifest_sha256: str

    def __post_init__(self):
        if not np.isfinite(self.threshold) or not 0 <= self.mlp_weight <= 1:
            raise ValueError("Invalid operating point")
        for digest in (self.model_sha256, self.calibration_manifest_sha256):
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Require frozen model/calibration hashes")


def pit_decision(mlp_logit, cnn_logit, gate_pass, operating_point):
    z = operating_point.mlp_weight*np.asarray(mlp_logit) + (1-operating_point.mlp_weight)*np.asarray(cnn_logit)
    return (z > operating_point.threshold) & np.asarray(gate_pass, bool)


def temperature_velocity(reference_velocity_mps, coefficient_mps_per_c, measured_temp_c, reference_temp_c=20):
    values = np.asarray([reference_velocity_mps, coefficient_mps_per_c, measured_temp_c, reference_temp_c])
    if not np.isfinite(values).all():
        raise ValueError("Uncalibrated temperature/velocity")
    velocity = reference_velocity_mps + coefficient_mps_per_c*(measured_temp_c-reference_temp_c)
    if velocity <= 0:
        raise ValueError("Nonphysical velocity")
    return float(velocity)


def angle_echo_time_profile_mle(signal, reference_pulse, sampling_hz, coarse_arrival_sample,
                                *, halfwidth_samples=2.0):
    """Local single-echo ML timing candidate, conditional on a calibrated reference pulse.

    Echo amplitude and DC offset are nuisance parameters; minimize profiled SSE under
    iid Gaussian residuals. Colored grain noise and overlapping echoes violate the model.
    A detected candidate on a known ray path is required; this does not create a reflector.
    """
    x, pulse = np.asarray(signal, float), np.asarray(reference_pulse, float)
    if x.ndim != 1 or pulse.ndim != 1 or len(pulse) % 2 != 1 or not np.isfinite(x).all() or not np.isfinite(pulse).all():
        raise ValueError("Invalid RF/reference pulse")
    if pulse @ pulse <= 0:
        raise ValueError("Zero reference pulse energy")
    if not np.isfinite([sampling_hz, coarse_arrival_sample, halfwidth_samples]).all() or min(sampling_hz, halfwidth_samples) <= 0:
        raise ValueError("Invalid calibrated timing")
    half = (len(pulse)-1)/2
    start = int(np.floor(coarse_arrival_sample-half-halfwidth_samples-2))
    stop = int(np.ceil(coarse_arrival_sample+half+halfwidth_samples+3))
    if start < 0 or stop > len(x):
        return {"status": "insufficient_echo_coverage", "arrival_time_s": None}
    axis = np.arange(start, stop)
    pulse_axis = np.arange(len(pulse))-half
    y = x[start:stop]

    def objective(arrival):
        column = np.interp(axis-arrival, pulse_axis, pulse, left=0, right=0)
        matrix = np.column_stack([column, np.ones(len(axis))])
        coef = np.linalg.lstsq(matrix, y, rcond=None)[0]
        return float(np.square(y-matrix@coef).sum())

    grid = np.linspace(coarse_arrival_sample-halfwidth_samples, coarse_arrival_sample+halfwidth_samples, 41)
    losses = np.asarray([objective(value) for value in grid])
    best = int(losses.argmin())
    if best in (0, len(grid)-1):
        return {"status": "search_boundary", "arrival_time_s": None}
    fit = minimize_scalar(objective, bounds=(grid[best-1], grid[best+1]), method="bounded", options={"xatol": 1e-6})
    if not fit.success or not np.isfinite(fit.fun):
        return {"status": "optimization_failed", "arrival_time_s": None}
    return {"status": "candidate_only_quality_not_validated", "arrival_sample": float(fit.x),
            "arrival_time_s": float(fit.x/sampling_hz), "residual_sse": float(fit.fun),
            "likelihood_assumption": "iid Gaussian residual, fixed reference pulse, isolated echo"}


def angle_thickness_if_identifiable(arrival_time_s, *, shear_velocity_mps, refracted_angle_deg,
                                    wedge_delay_s, verified_path, wall_traversals=2,
                                    echo_path_confirmed=False):
    """Convert a verified oblique ray path to wall thickness, otherwise abstain.

    d = Vs * (ToF - wedge_delay) * cos(theta) / wall_traversals.
    theta is the refracted STEEL angle from the surface normal, not the wedge angle.
    The existing simulator's ID-corner round-trip uses wall_traversals=2. A generic
    monostatic angle-beam scan does not supply a normal-incidence backwall echo train.
    Known geometry and echo identification are prerequisites, never inferred from truth.
    """
    if not echo_path_confirmed or verified_path != "id_corner_round_trip" or wall_traversals != 2:
        return {"status": "not_identifiable_path", "thickness_mm": None}
    if arrival_time_s is None:
        return {"status": "no_identified_echo", "thickness_mm": None}
    values = np.asarray([arrival_time_s, shear_velocity_mps, refracted_angle_deg, wedge_delay_s], float)
    if not np.isfinite(values).all() or shear_velocity_mps <= 0 or not 0 < refracted_angle_deg < 80 or wedge_delay_s < 0:
        return {"status": "unsupported_calibration", "thickness_mm": None}
    material_time = arrival_time_s-wedge_delay_s
    if material_time <= 0:
        return {"status": "nonphysical_time", "thickness_mm": None}
    thickness = shear_velocity_mps*material_time*np.cos(np.deg2rad(refracted_angle_deg))/wall_traversals*1e3
    return {"status": "conditional_geometry_estimate", "thickness_mm": float(thickness),
            "caution": "requires independently verified ID-corner geometry, mode and wedge calibration"}


def angle_error_contribution_mm(thickness_mm, angle_deg, angle_error_deg):
    """First-order magnitude of angle-only thickness error, not total uncertainty/MAE."""
    return float(abs(thickness_mm*np.tan(np.deg2rad(angle_deg))*np.deg2rad(angle_error_deg)))


def validate_angle_manifest(manifest, *, require_measured=False):
    """Refuse other modalities before they enter the active B model training cohort."""
    required = ("dataset_id", "specimen_id", "modality", "origin", "sampling_hz", "probe_center_hz",
                "material_grade", "refracted_angle_deg", "measured_temp_c", "wedge_delay_s")
    missing = [key for key in required if manifest.get(key) is None]
    if missing:
        return {"eligible": False, "reason": "missing_metadata", "fields": missing}
    if manifest["modality"] != "angle_beam_shear_pulse_echo":
        return {"eligible": False, "reason": "modality_mismatch"}
    if manifest["origin"] not in ("measured", "synthetic"):
        return {"eligible": False, "reason": "unknown_origin"}
    if require_measured and manifest["origin"] != "measured":
        return {"eligible": False, "reason": "measured_cohort_required"}
    if str(manifest["material_grade"]).lower() in ("unknown", "aluminum", "steel_unspecified"):
        return {"eligible": False, "reason": "material_not_qualified"}
    try:
        numeric = np.asarray([manifest[key] for key in ("probe_center_hz", "sampling_hz", "refracted_angle_deg",
                                                       "measured_temp_c", "wedge_delay_s")], dtype=float)
    except (TypeError, ValueError):
        return {"eligible": False, "reason": "invalid_numeric_metadata"}
    if not np.isfinite(numeric).all():
        return {"eligible": False, "reason": "nonfinite_metadata"}
    if not (0 < manifest["probe_center_hz"] < manifest["sampling_hz"]/2 and
            0 < manifest["refracted_angle_deg"] < 80 and manifest["wedge_delay_s"] >= 0):
        return {"eligible": False, "reason": "unsupported_sampling_or_geometry"}
    return {"eligible": True, "reason": "metadata_eligible_not_performance_validated"}


def thickness_metrics(predicted_mm, truth_mm, tolerance_mm=.1):
    predicted, truth = np.asarray(predicted_mm, float), np.asarray(truth_mm, float)
    if predicted.shape != truth.shape or predicted.ndim != 1 or not len(truth) or not np.isfinite(truth).all():
        raise ValueError("Require aligned finite ground truth")
    valid = np.isfinite(predicted)
    error = np.abs(predicted-truth)
    within = valid & (error <= tolerance_mm)
    return {"total": len(truth), "valid": int(valid.sum()), "failed": int((~valid).sum()),
            "mae_valid_mm": float(error[valid].mean()) if valid.any() else None,
            "within_tolerance_count": int(within.sum()), "within_tolerance_all": float(within.mean()),
            "tolerance_mm": tolerance_mm}
