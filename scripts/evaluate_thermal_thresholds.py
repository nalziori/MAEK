"""Frozen 30epoch thermal YOLO: error taxonomy, 27 thresholds, separate confirmation."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[key] = '1'

import numpy as np

from maek import thermal_render as tr
from maek.thermal_dataset import CLASS_NAMES, evaluate_arrays, load_zip
from maek.thermal_error_analysis import features, summarize
from maek.thermal_learned import PREDICT, semantic_from_instances
from maek.thermal_thresholds import BASELINE, GRID, recoverability, threshold_mask
from maek.thermal_validation import paired_change
from scripts.diagnose_thermal_components import samples
from scripts.evaluate_thermal_local import SOURCES, Accumulator, read, save, sha

WEIGHTS_SHA = 'eccf47f78a4762003b8e2644e3493b6d9c0618cd5be6b2a235cf4662a86b3cf9'
SPLITS = {'diagnostic_val': [None, 188, 'val'], 'diagnostic_shifted': [None, 300, 'old_shifted'],
          'selection_shifted': [20261201, 240, 'shifted'],
          'selection_train': [20261202, 120, 'train'],
          'confirmation_shifted': [20261203, 400, 'shifted'],
          'confirmation_train': [20261204, 200, 'train']}
PHASES = {'diagnose': ['diagnostic_val', 'diagnostic_shifted'],
          'select': ['selection_shifted', 'selection_train'],
          'confirm': ['confirmation_shifted', 'confirmation_train']}


def sources():
    names = set(SOURCES) | {'maek/thermal_learned.py', 'maek/thermal_thresholds.py',
         'maek/thermal_threshold_inference.py', 'maek/thermal_error_analysis.py',
         'scripts/evaluate_thermal_thresholds.py'}
    return {n: sha(ROOT / n) for n in sorted(names)}


def freeze(args):
    from ultralytics.models.yolo.segment.predict import SegmentationPredictor
    from ultralytics.utils.nms import non_max_suppression
    if sha(args.weights) != WEIGHTS_SHA:
        raise ValueError('Expected verified 30epoch weights, never the 100epoch model')
    save(args.out / 'protocol.json', {'source_hashes': sources(), 'splits': SPLITS,
        'weights': str(args.weights.resolve()), 'weights_sha256': sha(args.weights),
        'archive': str(args.archive.resolve()), 'archive_sha256': sha(args.archive),
        'old_reference': str(args.reference.resolve()), 'predict': PREDICT,
        'old_reference_hashes': {f: sha(args.reference / f) for f in
                                ('val-predictions.npz', 'shifted-predictions.npz')},
        'runtime': {n: importlib.metadata.version(n) for n in ('numpy', 'torch', 'ultralytics')},
        'library_hashes': {str(Path(inspect.getfile(obj)).resolve()): sha(Path(inspect.getfile(obj)))
                          for obj in (SegmentationPredictor, non_max_suppression)},
        'grid': GRID, 'baseline': BASELINE, 'comparison': 'strict score > class threshold',
        'cache': 'conf>.10, class-aware NMS; recompose semantic mask after filtering',
        'quality': 'all finite frames scored; clipping flagged, no abstention introduced',
        'oracle': 'GT/pipe/scene used only in offline error analysis, not inference',
        'selection_gate': {'shifted_macro_gain': .01, 'no_lost_class_hits': True,
             'no_new_normal_alarms': True, 'train_no_lost_class_hits': True,
             'train_no_new_normal_alarms': True, 'class_fp_nonincrease_both_splits': True},
        'ranking': 'shifted macro desc, FA asc, pooled mean IoU desc, distance to baseline asc, name',
        'confirmation_gate': 'selection point gates plus paired shifted macro CI95 lower > 0',
        'fallback': 'baseline; best ranked rejected challenger also diagnostic confirmation',
        'bootstrap': {'seed': 19, 'repeats': 2000},
        'external_field_validation': False, 'no_retraining': True,
        'diagnostic_data_previously_seen': True})


def verify(out):
    p = read(out / 'protocol.json')
    if p['source_hashes'] != sources() or p['splits'] != SPLITS:
        raise ValueError('Frozen sources or splits changed; create a new experiment')
    if sha(p['weights']) != p['weights_sha256'] or sha(p['archive']) != p['archive_sha256']:
        raise ValueError('Weights or archive changed')
    if any(sha(Path(p['old_reference']) / f) != h for f, h in p['old_reference_hashes'].items()):
        raise ValueError('Verified original baseline predictions changed')
    if any(sha(Path(f)) != h for f, h in p['library_hashes'].items()):
        raise ValueError('Inference library source changed')
    return p


def stream(p, split):
    seed, _, condition = SPLITS[split]
    if condition == 'val':
        yield from load_zip(p['archive'], 'train', 'val')
    elif condition == 'old_shifted':
        for part in ('train', 'val'):
            yield from load_zip(p['archive'], 'shifted', part)
    else:
        yield from samples(seed, SPLITS[split][1], condition)


def digest(array):
    return hashlib.sha256(str((array.shape, array.dtype)).encode() + array.tobytes()).hexdigest()


def macro(row):
    return sum(r['image_recall'] for r in row['classes'].values()) / 3


def transitions(base, candidate, ids):
    result = {'new_normal_alarms': [], 'resolved_normal_alarms': [],
              'gained_hits': {c: [] for c in CLASS_NAMES[1:]},
              'lost_hits': {c: [] for c in CLASS_NAMES[1:]}}
    for old, new, sample_id in zip(base, candidate, ids, strict=True):
        if old['normal']:
            if not old['alarm'] and new['alarm']:
                result['new_normal_alarms'].append(sample_id)
            if old['alarm'] and not new['alarm']:
                result['resolved_normal_alarms'].append(sample_id)
        for c in old['hits']:
            if new['hits'][c] > old['hits'][c]:
                result['gained_hits'][c].append(sample_id)
            if new['hits'][c] < old['hits'][c]:
                result['lost_hits'][c].append(sample_id)
    return result


def gate(shifted, train, name):
    if name == BASELINE:
        return False
    for result in (shifted, train):
        baseline = result['results'][BASELINE]
        if not baseline['normal_images'] or any(c['image_denominator'] == 0 for c in baseline['classes'].values()):
            return False
        t = result['transitions'][name]
        if t['new_normal_alarms'] or any(t['lost_hits'].values()):
            return False
        if any(result['results'][name]['class_fp_per_image'][c] >
               result['results'][BASELINE]['class_fp_per_image'][c] + 1e-12
               for c in CLASS_NAMES[1:]):
            return False
    return macro(shifted['results'][name]) - macro(shifted['results'][BASELINE]) + 1e-12 >= .01


def rank(result, name):
    row = result['results'][name]
    return (-macro(row), row['normal_image_false_alarm_rate'],
            -sum(c['iou'] for c in row['classes'].values()) / 3,
            sum(abs(v - .25) for v in GRID[name]), name)


def run_split(out, p, split, names, model):
    destination = out / f'{split}.json'
    if destination.exists():
        raise FileExistsError(destination)
    cache_dir = out / 'cache' / split
    cache_dir.mkdir(parents=True, exist_ok=True)
    acc = {n: Accumulator() for n in names}
    ids, input_hashes, truth_hashes, error_rows, image_rows, cache_hashes = [], [], [], [], [], []
    guards, parity_count, sentinel_count, old_count = [], 0, 0, 0
    old_ids, old_preds = None, None
    if split.startswith('diagnostic'):
        old_split = 'val' if split.endswith('val') else 'shifted'
        with np.load(Path(p['old_reference']) / f'{old_split}-predictions.npz', allow_pickle=False) as z:
            old_ids, old_preds = z['ids'], z['trained_yolo']
    for i, sample in enumerate(stream(p, split)):
        temp, truth = sample['temperature'], sample['mask']
        sample_id = f"{split}:{sample['job']['condition']}:{sample['job']['job_id']}"
        input_sha, truth_sha = digest(temp), digest(truth)
        ids.append(sample_id)
        input_hashes.append(input_sha)
        truth_hashes.append(truth_sha)
        cache_file = cache_dir / f'{i:05d}.npz'
        if cache_file.exists():
            with np.load(cache_file, allow_pickle=False) as z:
                if str(z['input_sha']) != input_sha or str(z['protocol_sha']) != sha(out / 'protocol.json'):
                    raise ValueError('Partial cache belongs to different input/protocol')
                if not np.array_equal(z['truth'], truth):
                    raise ValueError('Cache truth mismatch')
                masks, classes, scores, native = z['masks'], z['classes'], z['scores'], z['native']
                guard = json.loads(str(z['guard']))
                sentinel = bool(z['sentinel'])
        else:
            prediction = model.infer(temp, conf=.10)
            masks, classes, scores = (prediction[k] for k in ('masks', 'classes', 'scores'))
            native_output = model.infer(temp, conf=.25)
            native = semantic_from_instances(*(native_output[k] for k in ('masks', 'classes', 'scores')), temp.shape)
            cached = threshold_mask(masks, classes, scores, temp.shape, GRID[BASELINE])
            if not np.array_equal(cached, native):
                raise ValueError(f'Native .25/cache pixel parity failed for {sample_id}')
            guard = {'floor': prediction['nms'], 'baseline': native_output['nms']}
            sentinel = i < 4
            if sentinel:
                native04 = model.infer(temp, conf=.40)
                actual04 = semantic_from_instances(*(native04[k] for k in ('masks', 'classes', 'scores')), temp.shape)
                if not np.array_equal(actual04, threshold_mask(masks, classes, scores, temp.shape, (.4,) * 3)):
                    raise ValueError('Native .40/cache parity failed')
                # Mixed class thresholds: native per-class inference then confidence ownership.
                mixed = [model.infer(temp, conf=t, classes=[c]) for c, t in enumerate((.1, .25, .4))]
                for c, level in enumerate((.1, .25, .4)):
                    keep = (classes == c) & (scores > np.float32(level))
                    if (not np.array_equal(mixed[c]['masks'], masks[keep]) or
                            not np.array_equal(mixed[c]['scores'], scores[keep])):
                        raise ValueError('Native per-class/cache instance parity failed')
            with cache_file.open('xb') as handle:
                np.savez_compressed(handle, masks=masks, classes=classes, scores=scores,
                    truth=truth, native=native, input_sha=input_sha,
                    protocol_sha=sha(out / 'protocol.json'), guard=json.dumps(guard), sentinel=sentinel)
        parity_count += 1
        sentinel_count += int(sentinel)
        guards.append(guard)
        cache_hashes.append(sha(cache_file))
        if old_ids is not None:
            old_id = f"{sample['job']['condition']}:{sample['job']['job_id']}"
            if old_ids[i] != old_id or not np.array_equal(native, old_preds[i]):
                raise ValueError(f'Existing verified 30epoch baseline differs: {old_id}')
            old_count += 1
        prediction_masks, metrics_by_bytes = {}, {}
        for name in names:
            prediction_masks[name] = threshold_mask(masks, classes, scores, temp.shape, GRID[name])
            key = prediction_masks[name].tobytes()
            if key not in metrics_by_bytes:
                metrics_by_bytes[key] = evaluate_arrays([(truth, prediction_masks[name])])
            acc[name].rows.append(metrics_by_bytes[key])
        floor = threshold_mask(masks, classes, scores, temp.shape, (.1,) * 3)
        analysis_sample = dict(sample)
        if analysis_sample.get('pipe') is None:
            analysis_sample['pipe'] = tr.pipe_mask(sample['job'])
        feature = features(analysis_sample)
        rows = recoverability(truth, masks, classes, scores, native, floor)
        for row in rows:
            c = row['class_id']
            hits = [n for n in names if acc[n].rows[-1]['sample_outcomes'][0]['hits'][CLASS_NAMES[c]]]
            row.update(sample_id=sample_id, any_grid_hit=bool(hits), hit_configurations=hits,
                       features=feature['classes'][c], scene=feature['image'])
            error_rows.append(row)
        image_rows.append({'sample_id': sample_id, 'features': feature['image'],
              'baseline_alarm': bool(native.any()), 'normal': not bool(truth.any()),
              'instance_count_at_floor': len(scores),
              'cache': str(cache_file.relative_to(out))})
        if (i + 1) % 40 == 0:
            print(split, i + 1, '/', SPLITS[split][1], flush=True)
    if len(ids) != SPLITS[split][1] or len(set(input_hashes)) != len(ids):
        raise ValueError('Wrong sample count or repeated input image')
    for previous in out.glob('*.json'):
        if previous.stem in SPLITS and set(read(previous)['input_hashes']) & set(input_hashes):
            raise ValueError('Input images overlap between splits')
    results = {name: a.result() for name, a in acc.items()}
    changes, transition = {}, {}
    for name in names:
        if name != BASELINE:
            changes[name] = paired_change(results[BASELINE]['sample_outcomes'], results[name]['sample_outcomes'])
            transition[name] = transitions(results[BASELINE]['sample_outcomes'], results[name]['sample_outcomes'], ids)
    save(destination, {'split': split, 'ids': ids, 'input_hashes': input_hashes,
        'truth_hashes': truth_hashes, 'cache_hashes': cache_hashes,
        'results': results, 'changes': changes, 'transitions': transition,
        'error_rows': error_rows, 'image_rows': image_rows, 'error_summary': summarize(error_rows),
        'parity': {'native025_all': parity_count, 'native040_and_mixed_sentinels': sentinel_count,
                   'old_verified_baseline': old_count},
        'nms_guards': guards, 'grid_count': len(names),
        'any_grid_hit_note': 'offline per-image upper bound over evaluated configurations, not one deployable detector'})


def run(args):
    p = verify(args.out)
    from maek.thermal_threshold_inference import ThresholdPredictor
    if args.stage == 'select' and not all((args.out / f'{n}.json').exists() for n in PHASES['diagnose']):
        raise ValueError('Diagnose first')
    if args.stage == 'confirm':
        selection = read(args.out / 'selection.json')
        for filename, expected in selection['evidence_hashes'].items():
            if sha(args.out / filename) != expected:
                raise ValueError('Selection evidence changed')
        compare = selection['selected'] if selection['selected'] != BASELINE else selection['challenger']
        names = list(dict.fromkeys([BASELINE, compare]))
    else:
        names = list(GRID)
    model = ThresholdPredictor(Path(p['weights']))
    for split in PHASES[args.stage]:
        if not (args.out / f'{split}.json').exists():
            run_split(args.out, p, split, names, model)
    verify(args.out)
    if args.stage == 'select':
        shifted, train = (read(args.out / f'{s}.json') for s in PHASES['select'])
        ranked = sorted((n for n in GRID if n != BASELINE), key=lambda n: rank(shifted, n))
        eligible = [n for n in ranked if gate(shifted, train, n)]
        save(args.out / 'selection.json', {'selected': eligible[0] if eligible else BASELINE,
             'challenger': ranked[0], 'eligible': eligible, 'confirmation_accessed': False,
             'evidence_hashes': {f: sha(args.out / f) for f in
                 ['protocol.json', *[s + '.json' for s in PHASES['diagnose'] + PHASES['select']]]}})
        print('Selected:', eligible[0] if eligible else BASELINE, flush=True)
    if args.stage == 'confirm':
        shifted, train = (read(args.out / f'{s}.json') for s in PHASES['confirm'])
        selected = selection['selected']
        confirmed = selected != BASELINE and gate(shifted, train, selected)
        if confirmed:
            confirmed = shifted['changes'][selected]['macro_recall_change']['ci95'][0] > 0
        save(args.out / 'decision.json', {'selected_on_selection': selected,
            'confirmed_improvement': bool(confirmed), 'recommended': selected if confirmed else BASELINE,
            'production_defaults_changed': False, 'confirmation_data_external': False,
            'decision': 'fixed candidate passed independent-seed synthetic confirmation' if confirmed
                        else 'keep baseline; no confirmed improvement under preregistered gate'})
        print('Confirmation:', confirmed, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['freeze', *PHASES])
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--weights', type=Path)
    parser.add_argument('--reference', type=Path)
    args = parser.parse_args()
    if args.stage == 'freeze':
        if any(v is None for v in (args.archive, args.weights, args.reference)):
            parser.error('freeze needs --archive --weights --reference')
        freeze(args)
    else:
        run(args)


if __name__ == '__main__':
    main()
