import copy
import json
import zipfile

import numpy as np
import pytest

from maek.field_inspection_pipeline import attach_ndt_results, observe_pair, route_observations


def policy():
    return {'valid_min_c': -40., 'valid_max_c': 180., 'max_invalid_fraction': .01,
            'max_saturation_fraction': .01, 'max_occluded_fraction': .1,
            'max_registration_error_px': .5, 'max_reference_age_seconds': 86400,
            'allowed_sensor_ids': ['fixture-ir'], 'max_frame_pixels': 1000000,
            'allow_synthetic_only': True}


def metadata():
    return {'frame_id': 'f1', 'timestamp': '2026-11-08T10:00:00+00:00',
            'reference_frame_id': 'ref1', 'reference_timestamp': '2026-11-08T09:00:00+00:00',
            'unit': 'degC', 'sensor_id': 'fixture-ir', 'reference_sensor_id': 'fixture-ir',
            'calibration_id': 'synthetic-cal', 'reference_calibration_id': 'synthetic-cal',
            'operating_state': 'steady', 'reference_operating_state': 'steady',
            'registration': {'verified': True, 'error_px': 0., 'evidence_ref': 'fixture-registration'},
            'capture_domain': 'synthetic_fixture',
            'quality': {'occluded_fraction': 0., 'blur_verified': True, 'evidence_ref': 'fixture-quality'}}


def test_missing_reference_never_calls_observer_or_turns_into_negative():
    def fail(*args):
        pytest.fail('Unsupported data reached observer')
    result = observe_pair(np.full((24, 32), 25., np.float32), None, metadata(), policy(), observer=fail)
    assert result['assessment_status'] == 'unsupported_domain'
    assert result['temporal_change'] is None
    assert result['anomaly_regions'] is None


def test_field_domain_cannot_be_enabled_by_synthetic_permission():
    meta = metadata()
    meta['capture_domain'] = 'field'
    a = np.full((24, 32), 25., np.float32)
    assert observe_pair(a, a, meta, policy())['assessment_status'] == 'unsupported_domain'


def test_actual_pixels_and_evidence_output_no_ground_truth_access():
    a = np.full((24, 32), 25., np.float32)
    b = a.copy()
    b[8:16, 10:20] += 4.
    meta = metadata()
    meta['future_ndt_outcome'] = 'no_reportable_indication'
    positive = observe_pair(b, a, meta, policy())
    assert positive['assessment_status'] == 'anomaly_observed'
    assert positive['anomaly_regions'] and positive['input_sha256']
    assert positive['asset_id'] is None and positive['location_status'] == 'unmapped'
    assert 'safe_to_operate' not in positive and 'crack_probability' not in positive
    meta['future_ndt_outcome'] = 'requires_action'
    assert observe_pair(b, a, meta, policy()) == positive
    negative = observe_pair(a, a, meta, policy())
    assert negative['assessment_status'] == 'no_anomaly_observed'
    assert negative['temporal_change']['peak_absolute_apparent_c'] == 0


def test_malformed_prediction_abstains_instead_of_healthy():
    a = np.full((24, 32), 25., np.float32)
    result = observe_pair(a, a, metadata(), policy(), observer=lambda *x: np.full(a.shape, np.nan))
    assert result['assessment_status'] == 'indeterminate'
    assert result['anomaly_regions'] is None


def test_missing_frame_id_keeps_required_inspection_and_unassigned_followup():
    a = np.full((24, 32), 25., np.float32)
    meta = metadata()
    del meta['frame_id']
    observation = observe_pair(a, a, meta, policy())
    inventory = [{'asset_id': 'A', 'segment_id': 'S', 'mandatory': True, 'high_risk': False,
                  'risk_priority': 1., 'estimated_cost': 100., 'inspection_plan_ref': 'PLAN'}]
    result = route_observations(inventory, [observation], [], 0.)
    assert result['required_preserved'] and len(result['scheduled']) == 1
    assert result['summary']['required_budget_shortfall'] == 100.
    assert result['followups'][0]['asset_id'] is None


def plan():
    return {'scheduled': [{'task_id': 't1', 'asset_id': 'A', 'segment_id': 'S',
                           'status': 'pending_execution'}], 'deferred': []}


def ndt():
    return {'result_id': 'r1', 'task_id': 't1', 'asset_id': 'A', 'segment_id': 'S',
            'performed_at': '2026-11-08T11:00:00+00:00', 'method': 'reported UT procedure',
            'procedure_ref': 'PROC-1', 'coverage_ref': 'COVERAGE-1', 'limitations': 'documented coverage only',
            'reviewer': 'fixture-reviewer', 'report_ref': 'NDT-REPORT-1',
            'outcome': 'no_reportable_indication'}


def attach(rows):
    return attach_ndt_results(plan(), rows, requested_at='2026-11-08T10:00:00+00:00',
                              as_of='2026-11-08T12:00:00+00:00')


def test_ndt_link_preserves_plan_and_limited_negative():
    p = plan()
    before = copy.deepcopy(p)
    result = attach_ndt_results(p, [ndt()], requested_at='2026-11-08T10:00:00+00:00',
                               as_of='2026-11-08T12:00:00+00:00')
    assert len(result['accepted']) == 1 and p == before
    assert result['accepted'][0]['review_status'] == 'qualified_review_pending'
    assert result['safe_to_operate_inferred'] is False


@pytest.mark.parametrize(('key', 'value'), [('asset_id', 'other'), ('task_id', 'unknown'),
    ('performed_at', '2026-11-08T08:00:00+00:00'), ('performed_at', '2026-11-08T13:00:00+00:00'),
    ('performed_at', '2026-11-08T11:00:00'), ('coverage_ref', ''), ('limitations', '')])
def test_mismatched_or_unbounded_ndt_result_is_quarantined(key, value):
    row = ndt()
    row[key] = value
    result = attach([row])
    assert not result['accepted'] and len(result['quarantined']) == 1


def test_result_ids_are_idempotent_but_conflicts_quarantine_both():
    row = ndt()
    assert len(attach([row, row])['accepted']) == 1
    changed = {**row, 'outcome': 'requires_action'}
    result = attach([row, changed])
    assert not result['accepted'] and len(result['quarantined']) == 2


def test_duplicate_result_checks_complete_payload_not_only_required_fields():
    result = attach([{**ndt(), 'reported_measurement_mm': 3.},
                     {**ndt(), 'reported_measurement_mm': 4.}])
    assert not result['accepted'] and len(result['quarantined']) == 2


@pytest.mark.parametrize('kind', ['npy_instead_of_npz', 'corrupt_zip_crc'])
def test_broken_capture_decoding_preserves_required_inspection(tmp_path, kind):
    from scripts.run_field_inspection_pipeline import run

    path = tmp_path / 'capture.npz'
    a = np.full((24, 32), 25., np.float32)
    if kind == 'npy_instead_of_npz':
        with path.open('wb') as stream:
            np.save(stream, a)
    else:
        np.savez(path, current_c=a, reference_c=a)
        with zipfile.ZipFile(path) as z:
            info = z.infolist()[0]
            payload = bytearray(path.read_bytes())
            offset = info.header_offset + 30 + len(info.filename.encode())
            extra_length = int.from_bytes(payload[info.header_offset + 28:info.header_offset + 30], 'little')
            payload[offset + extra_length + info.compress_size - 1] ^= 1
        path.write_bytes(payload)
    config = {'captures': [{'sample_path': path.name, 'metadata': metadata()}],
              'quality_policy': policy(), 'observer': {'threshold_c': .5, 'min_area': 9},
              'inventory': [{'asset_id': 'A', 'segment_id': 'S', 'mandatory': True,
                             'high_risk': False, 'risk_priority': 1., 'estimated_cost': 100.,
                             'inspection_plan_ref': 'PLAN'}],
              'mappings': [], 'budget': 0., 'requested_at': '2026-11-08T10:00:00+00:00',
              'as_of': '2026-11-08T12:00:00+00:00'}
    request = tmp_path / 'request.json'
    request.write_text(json.dumps(config), encoding='utf-8')
    result = run(request, tmp_path / 'result.json')
    assert result['inspection_plan']['required_preserved']
    assert len(result['inspection_plan']['scheduled']) == 1
    assert any(f.startswith('source_unreadable:') for f in result['observations'][0]['quality_flags'])
