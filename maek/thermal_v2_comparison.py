"""Frozen three-way v2 comparison with a common image-only registration gate.

Inference never receives targets, latent geometry, known shifts or mechanism.
Rejected observations are abstentions, not healthy/negative classifications.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np

from maek.thermal_observation_data import TRAINING_SCOPE, encode_pair
from maek.thermal_observation_eval import (
    evaluate_scores,
    load_frames,
    paired_group_bootstrap,
    selection_rank,
    sha,
    summarize,
    sweep,
    write_csv,
    write_json,
)
from maek.thermal_registration_quality import assess_registration

MODELS = ('baseline', 'finetune', 'scratch')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_experiment(data, baseline, protocol_path, repo):
    protocol = json.loads(Path(protocol_path).read_text(encoding='utf-8'))
    require(protocol['version'] == 2 and protocol['scope'] == TRAINING_SCOPE, 'Wrong scope/version')
    require(sha(baseline) == protocol['baseline']['sha256'], 'Baseline hash mismatch')
    for name, digest in protocol['data_hashes'].items():
        require(sha(Path(data) / name) == digest, f'Frozen data mismatch: {name}')
    for name, digest in protocol['source_hashes'].items():
        path = (Path(repo) / name).resolve()
        require(path.is_relative_to(Path(repo).resolve()), 'Unsafe source path')
        require(sha(path) == digest, f'Frozen source mismatch: {name}')
    require(protocol['evaluate']['dev_max_false_alarm_frames'] == 0, 'Expected zero-dev-FA gate')
    return protocol


def load_model(path, device):
    import torch

    from maek.thermal_observation_model import ARCHITECTURE, build_model

    checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    require(checkpoint['architecture'] == ARCHITECTURE and checkpoint['scope'] == TRAINING_SCOPE,
            'Checkpoint architecture/scope mismatch')
    model = build_model()
    model.load_state_dict(checkpoint['model_state'], strict=True)
    model.to(device).eval()

    def predict(reference, current):
        inputs = torch.from_numpy(encode_pair(reference, current)[None]).to(device)
        with torch.inference_mode():
            logits = model(inputs)
            require(tuple(logits.shape) == (1, 2, *reference.shape)
                    and bool(torch.isfinite(logits).all()), 'Invalid model output')
            return torch.softmax(logits, dim=1)[0, 1].cpu().numpy()

    return predict, checkpoint


def choose_threshold(candidates):
    """Explicit unavailable selection for empty positive/no-change dev support."""
    if not candidates or not candidates[0]['positive_frame'] or not candidates[0]['no_change_frame']:
        return {'threshold':'OFF', 'off_selected':True, 'selection_available':False,
                'reason':'insufficient_accepted_dev_support'}
    eligible = [r for r in candidates if r['false_alarm'] == 0]
    require(bool(eligible), 'Missing OFF fallback')
    chosen = dict(max(eligible, key=selection_rank))
    chosen.update(off_selected=chosen['threshold'] == 'OFF', selection_available=True)
    return chosen


def _gate_frames(frames, policy):
    decisions, accepted = [], []
    for frame in frames:
        result = assess_registration(frame['reference'], frame['current'], policy)
        decisions.append({'sample_id':frame['sample_id'], 'base_scene_id':frame['base_scene_id'], **result})
        if result['can_infer']:
            accepted.append(frame)
    return accepted, decisions


def _whole_input_summary(frames, accepted, scored):
    positive = sum(bool(np.any(f['target'] == 1)) for f in frames)
    no_change = sum(not np.any(f['target'] == 1) and np.any(f['target'] == 0) for f in frames)
    return {'input_frames':len(frames), 'accepted_frames':len(accepted),
            'abstained_frames':len(frames)-len(accepted),
            'coverage':len(accepted)/len(frames) if frames else None,
            'all_positive_frames':positive, 'all_no_change_frames':int(no_change),
            'rejected_positive_frames':positive-scored['positive_frame'],
            'end_to_end_frame_hit_recall':scored['hit']/positive if positive else None,
            'rejected_are_negative':False}


def run_comparison(data, baseline, training_root, out, protocol_path, *, device='cuda', smoke=False):
    import cv2
    import torch

    from maek.thermal_observation_eval import rule_score

    data, baseline, training_root, out, protocol_path = map(Path, (
        data, baseline, training_root, out, protocol_path))
    repo = Path(__file__).resolve().parents[1]
    protocol = check_experiment(data, baseline, protocol_path, repo)
    require(not out.exists(), 'Use a fresh comparison output')
    require(device in ('cpu','cuda'), 'Invalid device')
    require(device != 'cuda' or torch.cuda.is_available(), 'CUDA unavailable')
    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    protocol_hash = sha(protocol_path)
    reports, predictors = {}, {}
    predictors['baseline'], _ = load_model(baseline, device)
    for mode in ('finetune','scratch'):
        run = training_root / mode
        report = json.loads((run / 'training.json').read_text(encoding='utf-8'))
        require(report['mode'] == mode and report['experiment_protocol_sha256'] == protocol_hash,
                'Training mode/protocol mismatch')
        require(report['baseline_sha256'] == sha(baseline), 'Training baseline mismatch')
        require(report['data_hashes'] == protocol['data_hashes'], 'Training data mismatch')
        require(report.get('scope') == TRAINING_SCOPE, 'Training scope mismatch')
        require(bool(report.get('source_hashes')), 'Missing training source provenance')
        require(sha(run / 'best.pt') == report['best_checkpoint_sha256'], 'Trained checkpoint hash mismatch')
        for name, digest in report['source_hashes'].items():
            require(sha(repo / name) == digest, 'Training source mismatch')
        if not smoke:
            require(report.get('status') == 'completed' and report['training_completed'] and not report['smoke_only']
                    and report['epochs_completed'] == 30 and report['device'] == 'cuda',
                    'Both full 30-epoch CUDA runs must complete')
        predict, checkpoint = load_model(run / 'best.pt', device)
        require(checkpoint['mode'] == mode and checkpoint['experiment_protocol_sha256'] == protocol_hash,
                'Checkpoint experiment mismatch')
        require(smoke or not checkpoint['smoke_only'], 'Smoke checkpoint cannot be compared as complete')
        reports[mode], predictors[mode] = report, predict
    for key in ('device','gpu','versions','optimizer_steps','batch_plan_sha256'):
        require(reports['finetune'][key] == reports['scratch'][key], f'Unequal experiment condition: {key}')
    settings = protocol['evaluate']
    out.mkdir(parents=True)
    # Gate depends only on measured images; all methods share one accepted set.
    dev = load_frames(data, 'dev')
    if smoke:
        dev = dev[:8]
    accepted, decisions = _gate_frames(dev, protocol['registration_policy'])
    write_json(out / 'registration-dev.json', decisions)
    dev_scores = {name:[predictors[name](f['reference'],f['current']) for f in accepted] for name in MODELS}
    rule_method = protocol['rule']['method']
    dev_scores['rule'] = [rule_score(f['reference'],f['current'],rule_method) for f in accepted]
    candidates, selected = [], {}
    for name, scores in dev_scores.items():
        grid = settings['rule_thresholds'] if name == 'rule' else settings['model_thresholds']
        trials = sweep(accepted, scores, name, grid, settings)
        candidates.extend(trials)
        selected[name] = choose_threshold(trials)
    # Select one challenger using DEV only. Holdout cannot select a new winner.
    eligible = [mode for mode in ('finetune','scratch') if not selected[mode]['off_selected']]
    challenger = max(eligible, key=lambda mode: (
        selection_rank(selected[mode])[:3], mode == 'finetune')) if eligible else None
    selection = {'selected':selected,'dev_selected_challenger':challenger,
        'selection_split':'dev','frozen_before_holdout':True,
        'baseline_weights_changed':False,'baseline_original_threshold':protocol['baseline']['original_threshold'],
        'experiment_protocol_sha256':protocol_hash,'smoke_only':smoke,
        'checkpoints':{'baseline':sha(baseline), **{mode:reports[mode]['best_checkpoint_sha256'] for mode in reports}}}
    write_json(out / 'selected.json', selection)
    write_csv(out / 'dev-sweep.csv', candidates)
    selection_sha = sha(out / 'selected.json')
    all_results, records_csv, table = {}, [], []
    for split in ('dev','test','stress'):
        require(sha(out / 'selected.json') == selection_sha, 'Selection mutated after freeze')
        frames = dev if split == 'dev' else load_frames(data, split)
        if smoke:
            frames = frames[:8]
        if split == 'dev':
            good, gate, scores = accepted, decisions, dev_scores
        else:
            good, gate = _gate_frames(frames, protocol['registration_policy'])
            scores = {name:[predictors[name](f['reference'],f['current']) for f in good] for name in MODELS}
            scores['rule'] = [rule_score(f['reference'],f['current'],rule_method) for f in good]
            write_json(out / f'registration-{split}.json', gate)
        results, records_by_method, masks = {}, {}, {}
        for name in (*MODELS,'rule','baseline_original_point'):
            threshold = (protocol['baseline']['original_threshold'] if name == 'baseline_original_point'
                         else selected[name]['threshold'])
            summary, records, predictions = evaluate_scores(good, scores['baseline' if name == 'baseline_original_point' else name], threshold, settings)
            summary['by_mechanism'] = {m:summarize([r for r in records if r['mechanism']==m])
                for m in sorted({r['mechanism'] for r in records})}
            summary['whole_input'] = _whole_input_summary(frames, good, summary)
            results[name], records_by_method[name] = summary, records
            masks[name] = (np.stack(predictions).astype(np.uint8) if predictions else
                           np.empty((0,*protocol['shape']),np.uint8))
            records_csv.extend({'split':split,'method':name,**r} for r in records)
            table.append({'split':split,'method':name,'threshold':threshold,
                **{k:summary[k] for k in ('frames','pixel_iou','hit','positive_frame','frame_hit_recall',
                    'false_alarm','no_change_frame','false_alarm_rate')}, **summary['whole_input'],
                'valid_comparison':not smoke})
        np.savez_compressed(out / f'predictions-{split}.npz',
            sample_ids=np.array([f['sample_id'] for f in good],dtype=str),
            target=np.stack([f['target'] for f in good]) if good else np.empty((0,*protocol['shape']),np.uint8),
            **masks)
        comparisons = {}
        for mode in ('finetune','scratch'):
            if good:
                comparisons[mode] = paired_group_bootstrap(records_by_method['baseline'],records_by_method[mode],
                    repeats=50 if smoke else settings['bootstrap_repeats'],seed=settings['bootstrap_seed'])
                comparisons[mode]['direction'] = f'{mode} minus recalibrated baseline'
            else:
                comparisons[mode] = None
        all_results[split] = {'methods':results,'paired_vs_baseline':comparisons}
    # Quality fixtures never supply validity to the image-only gate itself.
    quality_rows = [json.loads(line) for line in (data / 'quality-index.jsonl').read_text().splitlines()]
    quality_records = []
    for split in ('dev','test','stress'):
        rows = [r for r in quality_rows if r['split']==split]
        if smoke:
            rows = rows[:4]
        for row in rows:
            path = (data / row['relative_path']).resolve()
            require(path.is_relative_to(data.resolve()) and sha(path)==row['sha256'], 'Bad quality source')
            with np.load(io.BytesIO(path.read_bytes()),allow_pickle=False) as a:
                reference,current = a['reference_c'],a['current_c']
                require(np.all(a['target']==255), 'Quality fixture contains scored target')
            decision = assess_registration(reference,current,protocol['registration_policy'])
            quality_records.append({'split':split,'sample_id':row['sample_id'],
                'mechanism_audit_only':row['mechanism'], **decision})
    write_json(out / 'registration-quality-fixtures.json',quality_records)
    # Explicit adoption gates; comparing all requested models does not select on test.
    checks = {}
    if challenger:
        for split in ('test','stress'):
            b = all_results[split]['methods']['baseline']
            c = all_results[split]['methods'][challenger]
            checks[split+'_coverage_at_least_90pct'] = (c['whole_input']['coverage'] is not None
                and c['whole_input']['coverage'] >= protocol['acceptance']['min_valid_coverage'])
            checks[split+'_zero_false_alarms'] = c['false_alarm'] == 0
            checks[split+'_no_new_false_alarm_frames'] = not set(c['false_alarm_sample_ids'])-set(b['false_alarm_sample_ids'])
            checks[split+'_nondecreasing_frame_recall'] = (c['frame_hit_recall'] is not None
                and b['frame_hit_recall'] is not None and c['frame_hit_recall']>=b['frame_hit_recall'])
            boot=all_results[split]['paired_vs_baseline'][challenger]
            checks[split+'_positive_iou_gain_ci'] = bool(boot and boot['pixel_iou']['ci95']
                and boot['pixel_iou']['ci95'][0] > 0)
    gate_summary={split:{'valid_frames':len([r for r in (decisions if split=='dev' else json.loads((out/f'registration-{split}.json').read_text()))]),
        'misregistration_total':sum(r['split']==split and r['mechanism_audit_only']=='misregistration' for r in quality_records),
        'misregistration_rejected':sum(r['split']==split and r['mechanism_audit_only']=='misregistration' and not r['can_infer'] for r in quality_records),
        'calibration_drift_total':sum(r['split']==split and r['mechanism_audit_only']=='calibration_drift' for r in quality_records),
        'calibration_drift_abstained':sum(r['split']==split and r['mechanism_audit_only']=='calibration_drift' and not r['can_infer'] for r in quality_records)}
        for split in ('dev','test','stress')}
    for split in ('test','stress'):
        g=gate_summary[split]
        checks[split+'_misregistration_rejection_at_least_95pct'] = (g['misregistration_total']>0
            and g['misregistration_rejected']/g['misregistration_total']>=protocol['acceptance']['min_misregistration_rejection'])
    write_csv(out/'per-frame.csv',records_csv)
    write_csv(out/'summary.csv',table)
    result={'status':'completed','valid_comparison':not smoke,'smoke_only':smoke,
        'scope':TRAINING_SCOPE,'experiment_protocol_sha256':protocol_hash,
        'selected_json_sha256':selection_sha,'results':all_results,'registration_summary':gate_summary,
        'dev_selected_challenger':challenger,'acceptance_checks':checks,
        'improvement_supported':bool(not smoke and challenger and all(checks.values())),
        'baseline_preserved':True,'automatic_deployment':False,'field_validated':False,
        'defect_performance_validated':False,'common_quality_gate':True,
        'holdout_used_for_selection':False,'device':device,
        'versions':{'torch':str(torch.__version__),'opencv':cv2.__version__,'numpy':np.__version__},
        'limitations':['One seed; synthetic observation masks, not confirmed cracks',
            'Finetune has prior v1 training; equal ADDITIONAL epochs, not equal total compute',
            'Baseline weights unchanged; its primary operating point is calibrated on v2 dev like both new models',
            'Registration checker is limited to supported residual image translations; field validation absent',
            'Calibration drift requires separate metadata/calibration checks; absence of translation is not full input validity',
            'Abstentions require review and cannot cancel mandatory/high-risk NDT'],
        'artifact_hashes':{p.name:sha(p) for p in out.iterdir() if p.is_file()}}
    write_json(out/'metrics.json',result)
    return result
