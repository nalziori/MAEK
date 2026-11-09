"""One fixed v1 model/rule transfer diagnostic on v2 DEV only; no tuning or training.

Reject fixtures are only counted for raw candidate emission; their all-ignore
targets cannot yield accuracy/false-alarm scores. This is not deployment approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maek.thermal_observation_eval import (
    evaluate_scores,
    load_frames,
    load_predictor,
    postprocess,
    rule_score,
    sha,
    summarize,
    write_csv,
    write_json,
)


def run(received, data, out):
    import cv2
    import torch

    received, data, out = map(Path, (received, data, out))
    if out.exists():
        raise FileExistsError('Use a fresh transfer audit directory')
    selected = json.loads((received / 'comparison/selected.json').read_text(encoding='utf-8'))
    original = json.loads((received / 'comparison_protocol.json').read_text(encoding='utf-8'))
    manifest = json.loads((data / 'manifest.json').read_text(encoding='utf-8'))
    validation = json.loads((data / 'validation.json').read_text(encoding='utf-8'))
    protocol = json.loads((data / 'protocol.json').read_text(encoding='utf-8'))
    if protocol['version'] != 2 or manifest['field_validated'] or validation['status'] != 'passed':
        raise ValueError('Requires independently validated synthetic v2 data')
    if not selected['valid_comparison'] or selected['smoke_only']:
        raise ValueError('Requires completed original comparison')
    frozen = {'purpose':'v1 to v2 development transfer diagnostic, not a new tuned comparison',
        'split':'dev', 'runs':1, 'new_training_runs':0, 'threshold_search':False,
        'rule':{k:selected['selected_rule'][k] for k in ('method','threshold')},
        'model_threshold':selected['selected_model']['threshold'], 'evaluate':original['evaluate'],
        'source_checkpoint_sha256':sha(received / 'training/best.pt'),
        'source_selected_sha256':sha(received / 'comparison/selected.json'),
        'source_comparison_protocol_sha256':sha(received / 'comparison_protocol.json'),
        'data_hashes':{name:sha(data / name) for name in (
            'manifest.json','protocol.json','index.jsonl','quality-index.jsonl','validation.json')},
        'field_validated':False, 'crack_prediction_eligible':False,
        'test_or_stress_arrays_loaded':False,
        'source_hashes':{name:sha(ROOT / name) for name in (
            'scripts/audit_thermal_observation_transfer.py','maek/thermal_observation_eval.py',
            'maek/thermal_observation_data.py','maek/thermal_observation_model.py')}}
    out.mkdir(parents=True)
    write_json(out / 'protocol.json', frozen)  # Freeze before reading dev arrays.
    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    predict, _, _, _ = load_predictor(received / 'training', 'cpu',
        frozen['source_comparison_protocol_sha256'], False)
    frames = load_frames(data, 'dev')
    results, counts, masks = {}, [], {}
    for method in ('rule','model'):
        scores = [(predict(f['reference'],f['current']) if method == 'model' else
            rule_score(f['reference'],f['current'],frozen['rule']['method'])) for f in frames]
        threshold = frozen['model_threshold'] if method == 'model' else frozen['rule']['threshold']
        result, records, predictions = evaluate_scores(frames, scores, threshold, frozen['evaluate'])
        result['by_mechanism'] = {name:summarize([r for r in records if r['mechanism']==name])
            for name in sorted({r['mechanism'] for r in records})}
        results[method] = result
        counts.extend({'method':method,**r} for r in records)
        masks[method] = np.stack(predictions).astype(np.uint8)
    np.savez_compressed(out / 'predictions-dev.npz', sample_ids=np.array([f['sample_id'] for f in frames]),
                        target=np.stack([f['target'] for f in frames]), **masks)
    write_csv(out / 'per-frame.csv', counts)
    quality = [json.loads(line) for line in (data / 'quality-index.jsonl').read_text().splitlines()]
    quality = [r for r in quality if r['split']=='dev']
    quality_counts = []
    for row in quality:
        path = (data / row['relative_path']).resolve()
        if not path.is_relative_to(data.resolve()) or sha(path)!=row['sha256']:
            raise ValueError('Unsafe or mismatched quality sample')
        with np.load(path, allow_pickle=False) as a:
            reference,current,target = (a[k] for k in ('reference_c','current_c','target'))
        if np.any(target!=255):
            raise ValueError('Quality targets must be all ignored')
        for method in ('rule','model'):
            score = predict(reference,current) if method=='model' else rule_score(
                reference,current,frozen['rule']['method'])
            threshold = frozen['model_threshold'] if method=='model' else frozen['rule']['threshold']
            prediction = postprocess(score,threshold,frozen['evaluate']['min_component_area'])
            quality_counts.append({'sample_id':row['sample_id'], 'mechanism':row['mechanism'],
                'method':method, 'raw_candidate_pixels':int(prediction.sum()),
                'candidate_emitted':bool(prediction.any()), 'required_gate_decision':'reject',
                'accuracy_scored':False, 'input_sha256':row['sha256']})
    write_csv(out / 'quality-raw-candidates.csv', quality_counts)
    quality_summary = {method:{mechanism:{'frames':sum(r['method']==method and r['mechanism']==mechanism
         for r in quality_counts), 'raw_candidate_frames':sum(r['method']==method and
         r['mechanism']==mechanism and r['candidate_emitted'] for r in quality_counts)}
         for mechanism in ('misregistration','calibration_drift')} for method in ('rule','model')}
    output = {'status':'completed','scope':'v2_dev_diagnostic_only', 'thresholds_retuned':False,
        'new_training_runs':0, 'results':results, 'quality_raw_candidate_counts':quality_summary,
        'quality_accuracy':None, 'quality_gate_implemented_by_this_model':False,
        'direct_adoption_supported':False, 'field_validated':False,
        'wall_loss_positive_support':results['model']['by_mechanism']['wall_loss']['positive_frame'],
        'v2_dev_zero_false_alarm_gate':results['model']['false_alarm']==0,
        'test_or_stress_arrays_loaded':False,
        'versions':{'torch':torch.__version__,'numpy':np.__version__,'opencv':cv2.__version__},
        'artifact_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir()},
        'limits':['Development-only transfer diagnostic; no held-out confirmation or threshold search',
                  'V1 training is not V2 training; original scores cannot transfer to V2',
                  'Quality candidate counts are not false-alarm rates or quality classification accuracy',
                  'No real location mapping, NDT outcome, inspection-cost or defect validation']}
    write_json(out / 'metrics.json', output)
    print(json.dumps({'status':output['status'], 'results':{k:{x:v[x] for x in (
        'pixel_iou','hit','positive_frame','false_alarm','no_change_frame')} for k,v in results.items()},
        'quality':quality_summary}))
    return output


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--received',type=Path,required=True)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    run(args.received,args.data,args.out)
