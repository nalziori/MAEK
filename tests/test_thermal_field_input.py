import copy
import json

import numpy as np
import pytest

from maek.thermal_field_input import assess_pair


@pytest.fixture
def pair():
    current = np.full((10, 12), 25, dtype=np.float32)
    reference = np.full_like(current, 24.5)
    metadata = {
        "frame_id": "frame-current", "timestamp": "2026-11-08T10:00:00+09:00",
        "reference_frame_id": "frame-reference",
        "reference_timestamp": "2026-11-08T09:00:00+09:00", "unit": "degC",
        "sensor_id": "SIM-01", "reference_sensor_id": "SIM-01",
        "calibration_id": "CAL-01", "reference_calibration_id": "CAL-01",
        "operating_state": "steady", "reference_operating_state": "steady",
        "capture_domain": "synthetic_fixture",
        "registration": {"verified": True, "error_px": 0.1, "evidence_ref": "fixture/reg.json"},
        "quality": {"occluded_fraction": 0., "blur_verified": True,
                    "evidence_ref": "fixture/quality.json"},
    }
    policy = {
        "valid_min_c": -40., "valid_max_c": 180., "max_invalid_fraction": .01,
        "max_saturation_fraction": .01, "max_occluded_fraction": .1,
        "max_registration_error_px": .5, "max_reference_age_seconds": 86400,
        "allowed_sensor_ids": ["SIM-01"], "max_frame_pixels": 1_000_000,
        "allow_synthetic_only": True,
    }
    return current, reference, metadata, policy


def test_ready_synthetic_pair_is_not_temporal_or_field_validation(pair):
    result = assess_pair(*pair)
    assert result["assessment_status"] == "ready" and result["can_infer"]
    assert result["support_status"] == "synthetic_only"
    assert result["temporal_change"] is None
    assert result["reference_frame_id"] == "frame-reference"
    assert result["checks"]["verification_source"] == "caller_provided_evidence_only"
    assert result["checks"]["reference_age_seconds"] == 3600
    assert result["checks"]["current"]["pixel_count"] == 120
    json.dumps(result, allow_nan=False)


def test_field_never_becomes_validated_and_retains_quality_failures(pair):
    current, reference, metadata, policy = pair
    metadata.update(capture_domain="field", field_validated=True)
    current[0, 0] = np.nan
    metadata["registration"]["verified"] = False
    result = assess_pair(current, reference, metadata, policy)
    assert result["assessment_status"] == "unsupported_domain" and not result["can_infer"]
    assert result["support_status"] == "unvalidated"
    assert "field_domain_unvalidated" in result["quality_flags"]
    assert "current_nonfinite" in result["quality_flags"]
    assert "registration_unverified" in result["quality_flags"]
    json.dumps(result, allow_nan=False)


def test_missing_reference_is_unsupported(pair):
    current, _, metadata, policy = pair
    result = assess_pair(current, None, metadata, policy)
    assert result["assessment_status"] == "unsupported_domain"
    assert not result["can_infer"] and result["temporal_change"] is None
    assert "reference_missing" in result["quality_flags"]


@pytest.mark.parametrize("replacement", [None, np.zeros((10, 12, 3)),
                                         np.zeros((10, 12), dtype=np.uint16),
                                         np.empty((0, 12)), [[25.]]])
def test_malformed_current_arrays_are_indeterminate(pair, replacement):
    _, reference, metadata, policy = pair
    result = assess_pair(replacement, reference, metadata, policy)
    assert result["assessment_status"] == "indeterminate" and not result["can_infer"]


def test_shape_mismatch_and_size_limit(pair):
    current, reference, metadata, policy = pair
    result = assess_pair(current, reference[:, :-1], metadata, policy)
    assert "pair_shape_mismatch" in result["quality_flags"]
    assert not result["can_infer"]
    policy["max_frame_pixels"] = 100
    assert not assess_pair(current, reference, metadata, policy)["can_infer"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_any_nonfinite_blocks_even_below_fraction_threshold(pair, value):
    _, _, metadata, policy = pair
    current = np.full((100, 100), 25., dtype=np.float64)
    reference = current.copy()
    current[0, 0] = value
    result = assess_pair(current, reference, metadata, policy)
    assert result["checks"]["current"]["invalid_fraction"] < policy["max_invalid_fraction"]
    assert result["assessment_status"] == "indeterminate" and not result["can_infer"]


def test_saturation_threshold_and_exclusion_counts(pair):
    _, _, metadata, policy = pair
    current = np.full((100, 100), 25., dtype=np.float32)
    reference = current.copy()
    current[0, 0] = policy["valid_max_c"]
    result = assess_pair(current, reference, metadata, policy)
    assert result["can_infer"]
    assert result["checks"]["current"]["saturation_count"] == 1
    assert result["checks"]["current"]["valid_pixel_count"] == 9999
    assert result["checks"]["output_exclusion_required"]
    current[:2] = 200.
    assert not assess_pair(current, reference, metadata, policy)["can_infer"]


@pytest.mark.parametrize("key,value", [
    ("timestamp", "2026-11-08T10:00:00"), ("timestamp", "bad"),
    ("reference_timestamp", "2026-11-09T09:00:00+09:00"),
    ("reference_timestamp", "2026-11-01T09:00:00+09:00"),
    ("reference_calibration_id", "different"), ("reference_sensor_id", "different"),
    ("reference_operating_state", "startup"), ("unit", "uint16_counts"),
    ("frame_id", None), ("reference_frame_id", ""), ("calibration_id", None),
])
def test_bad_provenance_blocks_inference(pair, key, value):
    current, reference, metadata, policy = pair
    metadata[key] = value
    result = assess_pair(current, reference, metadata, policy)
    assert not result["can_infer"]
    assert result["assessment_status"] in ("indeterminate", "unsupported_domain")


@pytest.mark.parametrize("section,key,value", [
    ("registration", "verified", False), ("registration", "verified", None),
    ("registration", "error_px", .6), ("registration", "error_px", float("nan")),
    ("registration", "evidence_ref", ""), ("quality", "blur_verified", False),
    ("quality", "blur_verified", None), ("quality", "evidence_ref", ""),
    ("quality", "occluded_fraction", .2), ("quality", "occluded_fraction", -1),
])
def test_registration_and_quality_are_required(pair, section, key, value):
    current, reference, metadata, policy = pair
    metadata[section][key] = value
    result = assess_pair(current, reference, metadata, policy)
    assert result["assessment_status"] == "indeterminate" and not result["can_infer"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("key,value", [("max_invalid_fraction", -1),
                                      ("valid_max_c", float("inf")),
                                      ("allowed_sensor_ids", "SIM-01"),
                                      ("max_frame_pixels", 0)])
def test_invalid_policy_blocks_without_nonjson_values(pair, key, value):
    current, reference, metadata, policy = pair
    policy[key] = value
    result = assess_pair(current, reference, metadata, policy)
    assert not result["can_infer"] and not result["checks"]["policy_valid"]
    json.dumps(result, allow_nan=False)


def test_input_and_metadata_are_not_mutated(pair):
    current, reference, metadata, policy = pair
    before_current, before_reference = current.copy(), reference.copy()
    before_metadata, before_policy = copy.deepcopy(metadata), copy.deepcopy(policy)
    assess_pair(*pair)
    np.testing.assert_array_equal(current, before_current)
    np.testing.assert_array_equal(reference, before_reference)
    assert metadata == before_metadata and policy == before_policy


def test_sensor_domain_allowlist_and_max_pixels_alias(pair):
    current, reference, metadata, policy = pair
    policy["maxframepixels"] = policy.pop("max_frame_pixels")
    assert assess_pair(current, reference, metadata, policy)["can_infer"]
    policy["allowed_sensor_ids"] = []
    result = assess_pair(current, reference, metadata, policy)
    assert result["assessment_status"] == "unsupported_domain" and not result["can_infer"]


@pytest.mark.parametrize("key", ["unit", "capture_domain"])
def test_nonscalar_metadata_is_rejected_without_crashing(pair, key):
    current, reference, metadata, policy = pair
    metadata[key] = np.array(["field", "degC"])
    result = assess_pair(current, reference, metadata, policy)
    assert not result["can_infer"]
    json.dumps(result, allow_nan=False)


def test_non_scalar_policy_alias_is_rejected(pair):
    current, reference, metadata, policy = pair
    policy["maxframepixels"] = np.array([2, 3])
    result = assess_pair(current, reference, metadata, policy)
    assert not result["can_infer"]
    json.dumps(result, allow_nan=False)


def test_exact_policy_boundaries_are_allowed_and_excluded_pixels_reported(pair):
    _, _, metadata, policy = pair
    current = np.full((100, 100), 25., dtype=np.float32)
    reference = current.copy()
    current[0] = policy["valid_min_c"]
    metadata["registration"]["error_px"] = policy["max_registration_error_px"]
    metadata["quality"]["occluded_fraction"] = policy["max_occluded_fraction"]
    metadata["reference_timestamp"] = "2026-11-07T10:00:00+09:00"
    result = assess_pair(current, reference, metadata, policy)
    assert result["can_infer"]
    assert result["checks"]["pair_valid_pixel_count"] == 9900


@pytest.mark.parametrize("section", ["registration", "quality"])
def test_missing_verification_section_blocks(pair, section):
    current, reference, metadata, policy = pair
    metadata.pop(section)
    assert assess_pair(current, reference, metadata, policy)["assessment_status"] == "indeterminate"


def test_malformed_top_level_objects_block_without_raising(pair):
    current, reference, _, policy = pair
    result = assess_pair(current, reference, None, policy)
    assert not result["can_infer"]
    json.dumps(result, allow_nan=False)
    result = assess_pair(current, reference, {}, None)
    assert not result["can_infer"] and not result["checks"]["policy_valid"]
    json.dumps(result, allow_nan=False)


def test_unknown_or_disabled_domain_is_unsupported(pair):
    current, reference, metadata, policy = pair
    metadata["capture_domain"] = "unrecognized"
    assert assess_pair(current, reference, metadata, policy)["assessment_status"] == "unsupported_domain"
    metadata["capture_domain"] = "synthetic_fixture"
    policy["allow_synthetic_only"] = False
    assert assess_pair(current, reference, metadata, policy)["assessment_status"] == "unsupported_domain"
