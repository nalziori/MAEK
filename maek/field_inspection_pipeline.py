"""Opt-in observation-to-inspection contracts, not field-validated diagnosis.

The existing strategy simulator uses defect truth/POD. This path consumes only
measured arrays and declared capture/asset records. No inspection is executed.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime

import numpy as np

from maek.inspection_routing import plan_inspections
from maek.thermal_field_input import assess_pair
from maek.thermal_observation_eval import postprocess, rule_score


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _array_digest(value):
    if value is None:
        return None
    value = np.asarray(value)
    if value.dtype.hasobject:
        return None
    return hashlib.sha256(str((value.shape, value.dtype.str)).encode() + value.tobytes()).hexdigest()


def observe_pair(current, reference, metadata, policy, *, observer=None,
                 observer_version='synthetic_smooth_change_rule_v1', threshold=.5, min_area=9):
    """Gate first, then image-only observer. Default threshold is a demo assumption.

    Custom observers receive (reference, current) only and return an HxW score.
    Changing an observer/threshold requires new validation; field remains blocked.
    """
    import cv2

    if not np.isfinite(threshold) or threshold < 0 or not isinstance(min_area, int) or min_area < 1:
        raise ValueError('Invalid observer threshold or area')
    quality = assess_pair(current, reference, metadata, policy)
    hashes = {'reference': _array_digest(reference), 'current': _array_digest(current)}
    model = {'version': observer_version, 'threshold': threshold, 'min_area': min_area,
             'calibrated': False, 'purpose': 'synthetic integration fixture'}
    identity = {'frame_id': quality.get('frame_id'), 'timestamp': quality.get('timestamp'),
                'reference_frame_id': quality.get('reference_frame_id'), 'hashes': hashes, 'model': model}
    out = {**quality, 'observation_id': 'obs-' + _digest(identity)[:24], 'model_version': observer_version,
           'observer_config': model, 'input_sha256': hashes, 'policy_sha256': _digest(policy),
           'asset_id': None, 'segment_id': None, 'feature_id': None, 'location_status': 'unmapped',
           'observation_type': 'registered_pair_thermal_change', 'anomaly_regions': None,
           'evidence_score': None, 'evidence_refs': [], 'temporal_change': None,
           'field_validated': False, 'negative_meaning': 'No observed change does not establish pipe integrity'}
    out['evidence_refs'] = [out['observation_id'], 'sha256:' + str(hashes['current'])]
    if not quality['can_infer']:
        return out
    try:
        score = (rule_score(reference, current, 'smoothed_signed_difference_3x3') if observer is None
                 else np.asarray(observer(reference, current)))
        if score.shape != current.shape or not np.isfinite(score).all() or np.any(score < 0):
            raise ValueError('Invalid observer output')
        # Saturated pixels and their 3x3 neighbourhood cannot support evidence.
        valid = ((reference > policy['valid_min_c']) & (reference < policy['valid_max_c'])
                 & (current > policy['valid_min_c']) & (current < policy['valid_max_c']))
        contaminated = cv2.dilate((~valid).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        score = np.where(contaminated, 0., score)
        mask = postprocess(score, threshold, min_area)
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        if count > 129:
            raise ValueError('Too many regions for bounded evidence output')
        delta = current.astype(float) - reference.astype(float)
        regions = []
        for label in range(1, count):
            x, y, w, h, area = map(int, stats[label])
            selected = labels == label
            regions.append({'region_id': f'{out["observation_id"]}:{label}',
                'coordinate_space': 'current_frame_pixels', 'bbox_xyxy': [x, y, x + w, y + h],
                'area_pixels': area, 'centroid_xy': centroids[label].tolist(),
                'peak_absolute_apparent_delta_c': float(np.max(np.abs(delta[selected]))),
                'mean_signed_apparent_delta_c': float(np.mean(delta[selected]))})
        usable = ~contaminated
        if not usable.any():
            raise ValueError('No valid neighbourhoods remain')
        out.update(assessment_status='anomaly_observed' if regions else 'no_anomaly_observed',
                   anomaly_regions=regions,
                   temporal_change={'reference_frame_id': quality['reference_frame_id'],
                                    'peak_absolute_apparent_c': float(np.max(np.abs(delta[usable]))),
                                    'valid_pixel_count': int(usable.sum())})
    except (ValueError, RuntimeError, TypeError) as exc:
        out.update(assessment_status='indeterminate', can_infer=False)
        out['quality_flags'] = [*out['quality_flags'], 'observer_failed:' + type(exc).__name__]
    return out


def _time(value):
    if not isinstance(value, str):
        raise TypeError('Timestamp must be a timezone-aware ISO string')
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError('Timestamp timezone is required')
    return result


def route_observations(inventory, observations, mappings, budget=None):
    """Keep malformed capture identities out of mapping without losing required work."""
    routable, missing_identity = [], []
    for observation in observations:
        frame_id = observation.get('frame_id')
        (routable if isinstance(frame_id, str) and frame_id.strip() else missing_identity).append(observation)
    plan = plan_inspections(inventory, routable, mappings, budget)
    for observation in missing_identity:
        plan['followups'].append({'task_id': 'capture-review:' + observation['observation_id'],
            'task_kind': 'followup_capture_review', 'status': 'pending_review',
            'action': 'restore_capture_identity_before_mapping', 'asset_id': None, 'segment_id': None,
            'reasons': ['missing_frame_identity'], 'observation_ids': [observation['observation_id']],
            'frame_ids': [], 'evidence_refs': observation['evidence_refs'],
            'quality_flags': observation['quality_flags']})
        plan['mapping_records'].append({'observation_id': observation['observation_id'], 'frame_id': None,
            'location_status': 'unmapped', 'asset_id': None, 'segment_id': None, 'reason': 'missing_frame_identity'})
    plan['summary']['followup_tasks'] = len(plan['followups'])
    plan['summary']['unmapped_observations'] += len(missing_identity)
    plan['summary']['observations'] = len(observations)
    return plan


def attach_ndt_results(plan, results, *, requested_at, as_of):
    """Associate reported NDT records for review; never clear required tasks.

    Identical result IDs/payloads are idempotent within this batch. Conflicting
    IDs are quarantined together. No reported outcome grants operating clearance.
    """
    start, end = _time(requested_at), _time(as_of)
    if end < start:
        raise ValueError('as_of precedes inspection request')
    tasks = {}
    for task in plan['scheduled']:
        if task['task_id'] in tasks:
            raise ValueError('Duplicate task ID in plan')
        tasks[task['task_id']] = task
    required = ('result_id', 'task_id', 'asset_id', 'segment_id', 'performed_at', 'method',
                'procedure_ref', 'coverage_ref', 'limitations', 'reviewer', 'report_ref', 'outcome')
    groups, rejected, accepted = defaultdict(list), [], []
    for i, row in enumerate(results):
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in required):
            rejected.append({'row': i, 'reason': 'missing_required_result_fields'})
            continue
        record = {key: row[key] for key in required}
        try:
            payload_hash = _digest(row)
        except (ValueError, TypeError):
            rejected.append({'row': i, 'reason': 'invalid_result_payload'})
            continue
        groups[record['result_id']].append((i, record, payload_hash))
    for result_id, entries in sorted(groups.items()):
        unique = {payload_hash for _, _, payload_hash in entries}
        if len(unique) != 1:
            rejected.extend({'row': i, 'result_id': result_id, 'reason': 'conflicting_result_id'} for i, _, _ in entries)
            continue
        i, record, _ = entries[0]
        task = tasks.get(record['task_id'])
        reason = None
        if task is None:
            reason = 'unknown_or_unscheduled_task'
        elif (record['asset_id'], record['segment_id']) != (task['asset_id'], task['segment_id']):
            reason = 'location_mismatch'
        elif record['outcome'] not in ('requires_action', 'no_reportable_indication', 'inconclusive', 'unknown'):
            reason = 'unsupported_outcome'
        else:
            try:
                performed = _time(record['performed_at'])
                if not start <= performed <= end:
                    reason = 'result_outside_request_time_window'
            except ValueError:
                reason = 'invalid_result_timestamp'
        if reason:
            rejected.append({'row': i, 'result_id': result_id, 'reason': reason})
        else:
            accepted.append({**record, 'record_sha256': next(iter(unique)),
                'review_status': 'qualified_review_pending', 'duplicate_receipts': len(entries) - 1,
                'scope': 'Reported inspection coverage only; not independent measurement verification'})
    return {'accepted': accepted, 'quarantined': rejected, 'request_timestamp': requested_at,
            'as_of': as_of, 'required_tasks_auto_closed': False, 'safe_to_operate_inferred': False,
            'field_validated': False}
