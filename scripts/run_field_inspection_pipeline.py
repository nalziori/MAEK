"""Run opt-in MAEK capture gating, observation, routing and reported NDT linkage."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maek.field_inspection_pipeline import attach_ndt_results, observe_pair, route_observations


def run(config_path, out):
    config_path, out = Path(config_path).resolve(), Path(out).resolve()
    if out.exists():
        raise FileExistsError('Use a fresh output path')
    config = json.loads(config_path.read_text(encoding='utf-8'))
    observations = []
    for capture in config['captures']:
        path = (config_path.parent / capture['sample_path']).resolve()
        source_error = None
        try:
            if not path.is_relative_to(config_path.parent):
                raise ValueError('Sample path must remain inside request directory')
            with np.load(path, allow_pickle=False) as arrays:
                current = arrays['current_c'] if 'current_c' in arrays.files else None
                reference = arrays['reference_c'] if 'reference_c' in arrays.files else None
        except (ValueError, OSError, TypeError, EOFError, zipfile.BadZipFile, zlib.error) as exc:
            current, reference = None, None
            source_error = type(exc).__name__
        observation = observe_pair(current, reference, capture['metadata'], config['quality_policy'],
            threshold=config['observer']['threshold_c'], min_area=config['observer']['min_area'])
        if source_error:
            observation['quality_flags'].append('source_unreadable:' + source_error)
        else:
            observation['evidence_refs'].append('sample-sha256:' + hashlib.sha256(path.read_bytes()).hexdigest())
        observations.append(observation)
    plan = route_observations(config['inventory'], observations, config['mappings'], config.get('budget'))
    try:
        ndt = attach_ndt_results(plan, config.get('ndt_results', []), requested_at=config['requested_at'],
                                as_of=config['as_of'])
    except (ValueError, TypeError) as exc:
        ndt = {'accepted': [], 'quarantined': [{'reason': 'invalid_result_batch_contract',
               'error_type': type(exc).__name__}], 'required_tasks_auto_closed': False,
               'safe_to_operate_inferred': False}
    result = {'version': 1, 'observations': observations, 'inspection_plan': plan,
              'ndt_result_linkage': ndt, 'field_validated': False, 'inspection_executed': False,
              'costs_are_supplied_estimates': True,
              'request_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
              'source_hashes': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                  ['maek/field_inspection_pipeline.py', 'maek/thermal_field_input.py',
                   'maek/inspection_routing.py', 'maek/thermal_observation_eval.py',
                   'scripts/run_field_inspection_pipeline.py']}}
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
    print(json.dumps({'output': str(out), 'observations': len(observations), 'field_validated': False}))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run(args.request, args.out)
