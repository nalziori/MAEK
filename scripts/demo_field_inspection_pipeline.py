"""Create and run deterministic integration fixtures; no real defect labels/scores."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maek.field_inspection_pipeline import attach_ndt_results, route_observations
from scripts.run_field_inspection_pipeline import run


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def demo(out):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    policy = {'valid_min_c': -40., 'valid_max_c': 180., 'max_invalid_fraction': .01,
              'max_saturation_fraction': .01, 'max_occluded_fraction': .1,
              'max_registration_error_px': .5, 'max_reference_age_seconds': 86400,
              'allowed_sensor_ids': ['fixture-ir'], 'max_frame_pixels': 1000000,
              'allow_synthetic_only': True}
    base_meta = {'timestamp': '2026-11-08T10:00:00+00:00', 'reference_frame_id': 'fixture-ref',
        'reference_timestamp': '2026-11-08T09:00:00+00:00', 'unit': 'degC',
        'sensor_id': 'fixture-ir', 'reference_sensor_id': 'fixture-ir',
        'calibration_id': 'fixture-cal', 'reference_calibration_id': 'fixture-cal',
        'operating_state': 'steady', 'reference_operating_state': 'steady',
        'registration': {'verified': True, 'error_px': 0., 'evidence_ref': 'fixture-exact-registration'},
        'capture_domain': 'synthetic_fixture',
        'quality': {'occluded_fraction': 0., 'blur_verified': True, 'evidence_ref': 'fixture-quality'}}
    baseline = np.full((48, 64), 25., np.float32)
    changed = baseline.copy()
    changed[16:32, 24:40] += 4.
    captures = []
    cases = ['required_negative', 'high_risk_missing_reference', 'additional_anomaly',
             'same_segment_second_view', 'unmapped_anomaly', 'ambiguous_location',
             'field_unsupported', 'poor_registration', 'missing_frame_id', 'missing_file']
    for name in cases:
        metadata = copy.deepcopy(base_meta)
        metadata['frame_id'] = name
        if name == 'field_unsupported':
            metadata['capture_domain'] = 'field'
        if name == 'poor_registration':
            metadata['registration']['verified'] = False
        if name == 'missing_frame_id':
            del metadata['frame_id']
        current = baseline if name == 'required_negative' else changed
        arrays = {'current_c': current}
        if name != 'high_risk_missing_reference':
            arrays['reference_c'] = baseline
        if name != 'missing_file':
            np.savez_compressed(out / f'{name}.npz', **arrays)
        captures.append({'sample_path': f'{name}.npz', 'metadata': metadata})
    inventory = [
        {'asset_id': 'pipe-A', 'segment_id': 'required', 'mandatory': True, 'high_risk': False,
         'risk_priority': 5., 'inspection_plan_ref': 'PLAN-required', 'estimated_cost': 100.},
        {'asset_id': 'pipe-A', 'segment_id': 'high-risk', 'mandatory': False, 'high_risk': True,
         'risk_priority': 10., 'inspection_plan_ref': 'PLAN-high-risk', 'estimated_cost': 150.},
        {'asset_id': 'pipe-A', 'segment_id': 'candidate', 'mandatory': False, 'high_risk': False,
         'risk_priority': 2., 'inspection_plan_ref': None, 'estimated_cost': 80.},
    ]
    mappings = []
    locations = {'required_negative': 'required', 'high_risk_missing_reference': 'high-risk',
                 'additional_anomaly': 'candidate', 'same_segment_second_view': 'candidate',
                 'field_unsupported': 'required', 'poor_registration': 'candidate'}
    for frame, segment in locations.items():
        mappings.append({'frame_id': frame, 'asset_id': 'pipe-A', 'segment_id': segment,
                         'verified': True, 'evidence_ref': 'fixture-map:' + frame})
    for segment in ['required', 'candidate']:
        mappings.append({'frame_id': 'ambiguous_location', 'asset_id': 'pipe-A', 'segment_id': segment,
                         'verified': True, 'evidence_ref': 'conflicting-fixture-map:' + segment})
    config = {'fixture_only': True, 'quality_policy': policy,
              'observer': {'threshold_c': .5, 'min_area': 9}, 'captures': captures,
              'inventory': inventory, 'mappings': mappings, 'budget': 200.,
              'requested_at': '2026-11-08T10:00:00+00:00', 'as_of': '2026-11-08T12:00:00+00:00'}
    save(out / 'request.json', config)
    result = run(out / 'request.json', out / 'result.json')
    observations, plan = result['observations'], result['inspection_plan']
    assert plan['required_preserved']
    assert {t['segment_id'] for t in plan['scheduled']} == {'required', 'high-risk'}
    assert len(plan['deferred']) == 1 and plan['deferred'][0]['segment_id'] == 'candidate'
    assert plan['summary']['required_budget_shortfall'] == 50.
    by_frame = {o['frame_id']: o for o in observations}
    assert by_frame['required_negative']['assessment_status'] == 'no_anomaly_observed'
    assert by_frame['high_risk_missing_reference']['temporal_change'] is None
    assert by_frame['field_unsupported']['assessment_status'] == 'unsupported_domain'
    assert by_frame['poor_registration']['assessment_status'] == 'indeterminate'
    assert by_frame['missing_file']['assessment_status'] == 'unsupported_domain'
    assert all(r['location_status'] == 'unmapped' for r in plan['mapping_records']
               if r.get('frame_id') in ('unmapped_anomaly', 'ambiguous_location', None))
    assert any(t['action'] == 'restore_capture_identity_before_mapping' and t['asset_id'] is None
               for t in plan['followups'])
    assert {'additional_anomaly', 'same_segment_second_view'} <= set(plan['deferred'][0]['frame_ids'])
    funded = route_observations(inventory, observations, mappings, 400.)
    assert len(funded['scheduled']) == 3 and not funded['deferred']
    zero = route_observations(inventory, observations, mappings, 0.)
    assert zero['summary']['required_budget_shortfall'] == 250. and zero['required_preserved']
    save(out / 'plan-funded.json', funded)
    save(out / 'plan-zero-budget.json', zero)
    task = next(t for t in plan['scheduled'] if t['segment_id'] == 'required')
    reported = {'result_id': 'fixture-result-1', 'task_id': task['task_id'], 'asset_id': 'pipe-A',
        'segment_id': 'required', 'performed_at': '2026-11-08T11:00:00+00:00',
        'method': 'fixture-reported-method', 'procedure_ref': 'fixture-procedure',
        'coverage_ref': 'fixture-coverage', 'limitations': 'Fixture only; bounded coverage; no safety clearance',
        'reviewer': 'fixture-reviewer', 'report_ref': 'fixture-report', 'outcome': 'no_reportable_indication'}
    bad = {**reported, 'result_id': 'fixture-result-wrong-location', 'segment_id': 'candidate'}
    config['ndt_results'] = [reported, reported, bad]
    save(out / 'request-with-ndt.json', config)
    with_ndt = run(out / 'request-with-ndt.json', out / 'result-with-ndt.json')
    linked = with_ndt['ndt_result_linkage']
    assert len(linked['accepted']) == 1 and len(linked['quarantined']) == 1
    assert linked['accepted'][0]['duplicate_receipts'] == 1
    assert with_ndt['inspection_plan']['scheduled'] == plan['scheduled']
    conflicting = attach_ndt_results(plan, [reported, {**reported, 'outcome': 'requires_action'}],
                                     requested_at=config['requested_at'], as_of=config['as_of'])
    assert not conflicting['accepted'] and len(conflicting['quarantined']) == 2
    save(out / 'ndt-conflict.json', conflicting)
    checks = ['thermal_negative_required_preserved', 'missing_reference_not_normal',
              'field_cannot_bypass_synthetic_gate', 'registration_failure_abstains',
              'missing_identity_unassigned_followup', 'unreadable_source_preserves_required',
              'unknown_and_ambiguous_mapping_not_assigned', 'repeat_observations_deduplicated',
              'required_budget_shortfall_explicit', 'zero_budget_preserves_required',
              'funded_additional_review', 'reported_ndt_link_and_idempotence',
              'wrong_location_quarantined', 'conflicting_result_id_quarantined',
              'no_reportable_indication_does_not_close_required']
    summary = {'status': 'passed', 'fixture_only': True, 'capture_cases': len(captures), 'checks': checks,
        'field_validated': False, 'actual_ndt_performed': False, 'actual_cost_reduction_measured': False,
        'plan_summary': plan['summary'],
        'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}}
    save(out / 'validation.json', summary)
    print(json.dumps({'status': 'passed', 'checks': len(checks), 'captures': len(captures)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    demo(parser.parse_args().out)
