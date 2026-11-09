"""Conservative input/provenance gate; no sensor, blur or registration validation.

Field captures remain unsupported until a separate measured calibration process
exists. A ready synthetic pair is eligible for the synthetic observer only; it
does not establish pipe health or compute temporal change.
"""
from __future__ import annotations

import math
from datetime import datetime
from numbers import Real

import numpy as np


def _number(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def _text(value):
    return value if isinstance(value, str) and value.strip() else None


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        return None
    return result if result.tzinfo is not None and result.utcoffset() is not None else None


def assess_pair(current: np.ndarray | None, reference: np.ndarray | None,
                metadata: dict, policy: dict) -> dict:
    """Return JSON-compatible checks without changing or returning input arrays.

    Threshold equality is allowed for fractions, registration error and age.
    Finite temperatures at/beyond the configured bounds count as saturated and
    must be excluded downstream, even when their fraction is tolerated. Any
    nonfinite value blocks inference regardless of the configured fraction.
    """
    flags, blockers, unsupported = [], [], []

    def flag(name, kind="indeterminate"):
        if name not in flags:
            flags.append(name)
        if kind == "unsupported":
            unsupported.append(name)
        elif kind == "indeterminate":
            blockers.append(name)

    if not isinstance(metadata, dict):
        flag("metadata_invalid")
        metadata = {}
    if not isinstance(policy, dict):
        flag("policy_invalid")
        policy = {}
    parsed = {}
    policy_errors_before = len(blockers)
    numeric_keys = ("valid_min_c", "valid_max_c", "max_invalid_fraction",
                    "max_saturation_fraction", "max_occluded_fraction",
                    "max_registration_error_px", "max_reference_age_seconds")
    for key in numeric_keys:
        value = _number(policy.get(key))
        invalid = value is None
        if value is not None:
            invalid |= key.startswith("max_") and value < 0
            invalid |= key.endswith("fraction") and value > 1
        if invalid:
            flag(f"policy_{key}_invalid")
            value = None
        parsed[key] = value
    limits_valid = (parsed["valid_min_c"] is not None and parsed["valid_max_c"] is not None
                    and parsed["valid_min_c"] < parsed["valid_max_c"])
    if not limits_valid:
        flag("policy_temperature_bounds_invalid")
    max_pixels = _number(policy.get("max_frame_pixels", policy.get("maxframepixels")))
    if max_pixels is None or max_pixels < 1 or not max_pixels.is_integer():
        flag("policy_max_frame_pixels_invalid")
        max_pixels = None
    if ("max_frame_pixels" in policy and "maxframepixels" in policy
            and _number(policy["max_frame_pixels"]) != _number(policy["maxframepixels"])):
        flag("policy_max_frame_pixels_conflict")
    parsed["max_frame_pixels"] = int(max_pixels) if max_pixels is not None else None
    sensors = policy.get("allowed_sensor_ids")
    if not isinstance(sensors, list) or any(_text(value) is None for value in sensors):
        flag("policy_allowed_sensor_ids_invalid")
        sensors = None
    parsed["allowed_sensor_ids"] = list(sensors) if sensors is not None else None
    allow_synthetic = policy.get("allow_synthetic_only")
    if not isinstance(allow_synthetic, bool):
        flag("policy_allow_synthetic_only_invalid")
    parsed["allow_synthetic_only"] = allow_synthetic if isinstance(allow_synthetic, bool) else None
    checks = {
        "policy_valid": len(blockers) == policy_errors_before and "policy_invalid" not in flags,
        "policy": parsed, "verification_source": "caller_provided_evidence_only",
        "automatic_registration_performed": False, "automatic_blur_detection_performed": False,
        "field_calibration_validated": False,
    }

    domain = _text(metadata.get("capture_domain"))
    if domain == "field":
        flag("field_domain_unvalidated", "unsupported")
    elif domain == "synthetic_fixture":
        if allow_synthetic is False:
            flag("synthetic_domain_disabled", "unsupported")
    elif _text(domain) is None:
        flag("capture_domain_missing")
    else:
        flag("capture_domain_unsupported", "unsupported")
    if reference is None:
        flag("reference_missing", "unsupported")

    def inspect_array(value, name):
        summary = {"present": value is not None, "analysis_performed": False,
                   "shape": None, "dtype": None, "pixel_count": None,
                   "invalid_count": None, "invalid_fraction": None,
                   "saturation_count": None, "saturation_fraction": None,
                   "out_of_range_count": None, "valid_pixel_count": None}
        if value is None:
            if name != "reference":
                flag(f"{name}_missing")
            return summary
        if not isinstance(value, np.ndarray):
            flag(f"{name}_not_numpy_array")
            return summary
        summary.update(shape=list(value.shape), dtype=str(value.dtype), pixel_count=int(value.size))
        if value.ndim != 2 or value.size == 0:
            flag(f"{name}_shape_invalid")
            return summary
        if value.dtype.kind != "f":
            flag(f"{name}_not_float_temperature")
            return summary
        if max_pixels is None or value.size > max_pixels:
            flag(f"{name}_pixel_limit_exceeded")
            return summary
        finite = np.isfinite(value)
        nonfinite = int(np.count_nonzero(~finite))
        invalid_fraction = nonfinite / value.size
        summary.update(analysis_performed=True, invalid_count=nonfinite,
                       invalid_fraction=invalid_fraction)
        if nonfinite:
            flag(f"{name}_nonfinite")
        if (parsed["max_invalid_fraction"] is not None
                and invalid_fraction > parsed["max_invalid_fraction"]):
            flag(f"{name}_invalid_fraction_exceeded")
        finite_values = value[finite]
        summary["finite_min_c"] = _number(finite_values.min()) if finite_values.size else None
        summary["finite_max_c"] = _number(finite_values.max()) if finite_values.size else None
        if limits_valid:
            low, high = parsed["valid_min_c"], parsed["valid_max_c"]
            saturation = int(np.count_nonzero(finite & ((value <= low) | (value >= high))))
            summary.update(saturation_count=saturation, saturation_fraction=saturation / value.size,
                           valid_pixel_count=int(value.size) - nonfinite - saturation,
                           out_of_range_count=int(np.count_nonzero(finite & ((value < low) | (value > high)))))
            if saturation:
                flag(f"{name}_saturation_present", "info")
            if (parsed["max_saturation_fraction"] is not None
                    and summary["saturation_fraction"] > parsed["max_saturation_fraction"]):
                flag(f"{name}_saturation_fraction_exceeded")
        return summary

    checks["current"] = inspect_array(current, "current")
    checks["reference"] = inspect_array(reference, "reference")
    same_shape = (isinstance(current, np.ndarray) and isinstance(reference, np.ndarray)
                  and current.shape == reference.shape)
    if isinstance(current, np.ndarray) and isinstance(reference, np.ndarray) and not same_shape:
        flag("pair_shape_mismatch")
    checks["same_shape"] = same_shape
    checks["output_exclusion_required"] = any(
        bool(checks[name][key]) for name in ("current", "reference")
        for key in ("invalid_count", "saturation_count"))
    checks["pair_valid_pixel_count"] = None
    if same_shape and limits_valid and all(checks[name]["analysis_performed"]
                                           for name in ("current", "reference")):
        low, high = parsed["valid_min_c"], parsed["valid_max_c"]
        valid = (np.isfinite(current) & np.isfinite(reference)
                 & (current > low) & (current < high) & (reference > low) & (reference < high))
        checks["pair_valid_pixel_count"] = int(np.count_nonzero(valid))
        if not checks["pair_valid_pixel_count"]:
            flag("no_valid_pair_pixels")

    required = ("frame_id", "reference_frame_id", "sensor_id", "reference_sensor_id",
                "calibration_id", "reference_calibration_id", "operating_state",
                "reference_operating_state")
    strings = {key: _text(metadata.get(key)) for key in required}
    for key, value in strings.items():
        if value is None:
            flag(f"{key}_missing")
    checks["unit_degC"] = _text(metadata.get("unit")) == "degC"
    if not checks["unit_degC"]:
        flag("unit_not_degC")
    for key in ("sensor_id", "calibration_id", "operating_state"):
        matched = strings[key] is not None and strings[key] == strings[f"reference_{key}"]
        checks[f"matching_{key}"] = matched
        if not matched:
            flag(f"reference_{key}_mismatch")
    if sensors is not None:
        for key in ("sensor_id", "reference_sensor_id"):
            if strings[key] is not None and strings[key] not in sensors:
                flag(f"{key}_not_allowed", "unsupported")
    current_time = _timestamp(metadata.get("timestamp"))
    reference_time = _timestamp(metadata.get("reference_timestamp"))
    for key, value in (("timestamp", current_time), ("reference_timestamp", reference_time)):
        if value is None:
            flag(f"{key}_invalid_or_timezone_missing")
    age = (current_time - reference_time).total_seconds() if current_time and reference_time else None
    checks["reference_age_seconds"] = age
    if age is not None:
        if age < 0:
            flag("reference_timestamp_in_future")
        elif (parsed["max_reference_age_seconds"] is not None
              and age > parsed["max_reference_age_seconds"]):
            flag("reference_too_old")

    registration = metadata.get("registration")
    registration = registration if isinstance(registration, dict) else {}
    error = _number(registration.get("error_px"))
    evidence = _text(registration.get("evidence_ref"))
    verified = registration.get("verified") is True
    if not verified:
        flag("registration_unverified")
    if error is None or error < 0:
        flag("registration_error_invalid")
    elif (parsed["max_registration_error_px"] is not None
          and error > parsed["max_registration_error_px"]):
        flag("registration_error_exceeded")
    if evidence is None:
        flag("registration_evidence_missing")
    checks["registration"] = {"verification_provided": verified, "reported_error_px": error,
                              "evidence_ref": evidence, "measured_by_this_module": False}
    quality = metadata.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    occluded = _number(quality.get("occluded_fraction"))
    blur_verified = quality.get("blur_verified") is True
    evidence = _text(quality.get("evidence_ref"))
    if occluded is None or not 0 <= occluded <= 1:
        flag("occluded_fraction_invalid")
    elif parsed["max_occluded_fraction"] is not None and occluded > parsed["max_occluded_fraction"]:
        flag("occluded_fraction_exceeded")
    if not blur_verified:
        flag("blur_unverified")
    if evidence is None:
        flag("quality_evidence_missing")
    checks["quality"] = {"reported_occluded_fraction": occluded,
                         "blur_verification_provided": blur_verified,
                         "evidence_ref": evidence, "measured_by_this_module": False}
    status = "unsupported_domain" if unsupported else "indeterminate" if blockers else "ready"
    return {
        "assessment_status": status, "quality_flags": flags, "temporal_change": None,
        "reference_frame_id": strings["reference_frame_id"], "frame_id": strings["frame_id"],
        "timestamp": _text(metadata.get("timestamp")),
        "support_status": "synthetic_only" if domain == "synthetic_fixture" else "unvalidated",
        "can_infer": status == "ready", "checks": checks,
    }
