"""Data-only audit of a completed frozen thermal threshold experiment.

No model is loaded. All outcomes are audited; pixel metrics are independently
replayed only for baseline and selected (or rejected best challenger).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import itertools
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for _key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[_key] = '1'

import numpy as np

from maek.thermal_dataset import CLASS_NAMES, evaluate_arrays, load_zip, wilson95
from maek.thermal_validation import paired_change
from scripts.diagnose_thermal_components import samples

BASELINE = 'w25_d25_s25'
GRID = {f'w{int(w * 100):02d}_d{int(d * 100):02d}_s{int(s * 100):02d}': [w, d, s]
        for w, d, s in itertools.product((.10, .25, .40), repeat=3)}
SPLITS = {'diagnostic_val': [None, 188, 'val'],
          'diagnostic_shifted': [None, 300, 'old_shifted'],
          'selection_shifted': [20261201, 240, 'shifted'],
          'selection_train': [20261202, 120, 'train'],
          'confirmation_shifted': [20261203, 400, 'shifted'],
          'confirmation_train': [20261204, 200, 'train']}
NAMES = CLASS_NAMES[1:]
WEIGHTS_SHA = 'eccf47f78a4762003b8e2644e3493b6d9c0618cd5be6b2a235cf4662a86b3cf9'
SOURCE_NAMES = {
    'config/default.yaml', 'maek/camera/__init__.py', 'maek/camera/composite2d.py',
    'maek/heat.py', 'maek/network.py', 'maek/params.py', 'maek/pod.py',
    'maek/thermal.py', 'maek/thermal_dataset.py', 'maek/thermal_error_analysis.py',
    'maek/thermal_learned.py', 'maek/thermal_local_contrast.py', 'maek/thermal_render.py',
    'maek/thermal_threshold_inference.py', 'maek/thermal_thresholds.py',
    'maek/thermal_validation.py', 'scripts/diagnose_thermal_components.py',
    'scripts/evaluate_thermal_local.py', 'scripts/evaluate_thermal_thresholds.py',
    'scripts/evaluate_thermal_v3.py'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def equal(actual, expected, label):
    require(actual == expected, f'{label}: mismatch')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def digest(array):
    return hashlib.sha256(str((array.shape, array.dtype)).encode() + array.tobytes()).hexdigest()


def check_protocol(out):
    p = read(out / 'protocol.json')
    expected = {
        'splits': SPLITS, 'grid': GRID, 'baseline': BASELINE,
        'weights_sha256': WEIGHTS_SHA,
        'predict': {'imgsz': 320, 'conf': .25, 'iou': .7, 'retina_masks': True,
                    'device': 'cpu', 'verbose': False, 'save': False, 'max_det': 300},
        'comparison': 'strict score > class threshold',
        'cache': 'conf>.10, class-aware NMS; recompose semantic mask after filtering',
        'quality': 'all finite frames scored; clipping flagged, no abstention introduced',
        'oracle': 'GT/pipe/scene used only in offline error analysis, not inference',
        'selection_gate': {'shifted_macro_gain': .01, 'no_lost_class_hits': True,
                           'no_new_normal_alarms': True, 'train_no_lost_class_hits': True,
                           'train_no_new_normal_alarms': True,
                           'class_fp_nonincrease_both_splits': True},
        'ranking': 'shifted macro desc, FA asc, pooled mean IoU desc, distance to baseline asc, name',
        'confirmation_gate': 'selection point gates plus paired shifted macro CI95 lower > 0',
        'fallback': 'baseline; best ranked rejected challenger also diagnostic confirmation',
        'bootstrap': {'seed': 19, 'repeats': 2000},
        'external_field_validation': False, 'no_retraining': True,
        'diagnostic_data_previously_seen': True}
    for key, value in expected.items():
        equal(p[key], value, f'protocol.{key}')
    equal(set(p['source_hashes']), SOURCE_NAMES, 'protocol source inventory')
    for name, value in p['source_hashes'].items():
        equal(sha(ROOT / name), value, f'source {name}')
    for key in ('weights', 'archive'):
        equal(sha(p[key]), p[f'{key}_sha256'], key)
    equal(set(p['old_reference_hashes']), {'val-predictions.npz', 'shifted-predictions.npz'},
          'reference inventory')
    for name, value in p['old_reference_hashes'].items():
        equal(sha(Path(p['old_reference']) / name), value, f'reference {name}')
    equal(set(p['runtime']), {'numpy', 'torch', 'ultralytics'}, 'runtime inventory')
    for name, value in p['runtime'].items():
        equal(importlib.metadata.version(name), value, f'runtime {name}')
    equal(len(p['library_hashes']), 2, 'library count')
    equal({Path(name).name for name in p['library_hashes']}, {'predict.py', 'nms.py'},
          'library names')
    for name, value in p['library_hashes'].items():
        equal(sha(name), value, f'library {Path(name).name}')
    return p


def stream(p, split):
    seed, count, condition = SPLITS[split]
    if condition == 'val':
        yield from load_zip(p['archive'], 'train', 'val')
    elif condition == 'old_shifted':
        for part in ('train', 'val'):
            yield from load_zip(p['archive'], 'shifted', part)
    else:
        yield from samples(seed, count, condition)


def compose(masks, classes, scores, shape, levels):
    """Independent strict float32 filtering and stable pixel ownership."""
    require(masks.dtype == np.bool_ and masks.shape == (len(scores), *shape), 'mask schema')
    require(classes.dtype == np.int64 and classes.shape == scores.shape, 'class schema')
    require(scores.dtype == np.float32 and scores.ndim == 1, 'score schema')
    require(np.isin(classes, (0, 1, 2)).all(), 'class range')
    require(np.isfinite(scores).all() and ((scores > np.float32(.1)) & (scores <= 1)).all(),
            'score range/cache floor')
    require(not len(scores) or masks.reshape(len(scores), -1).any(axis=1).all(), 'empty mask')
    thresholds = np.asarray(levels, dtype=np.float32)
    result = np.zeros(shape, dtype=np.uint8)
    # Python stable sorting gives an implementation independent of numpy argsort.
    order = sorted(range(len(scores)), key=lambda i: -float(scores[i]))
    for i in order:
        if scores[i] > thresholds[classes[i]]:
            result[masks[i] & (result == 0)] = int(classes[i]) + 1
    return result


def check_guard(guard, post_count=None):
    equal(guard['class_aware'], True, 'NMS class aware')
    equal(guard['end2end'], False, 'NMS end2end')
    equal(guard['timeout'], False, 'NMS timeout')
    equal(guard['calls'], 1, 'NMS calls')
    equal(guard['max_det'], 300, 'NMS max_det')
    shape = guard['raw_shape']
    require(len(shape) == 3 and shape[0] == 1 and shape[-1] != 6, 'NMS shape')
    equal(guard['anchor_count'], shape[-1], 'NMS anchor count')
    require(0 < shape[-1] <= min(guard['max_nms'], 30000), 'NMS max_nms truncation')
    counts = guard['pre_mask_counts']
    require(len(counts) == 1 and 0 <= counts[0] < 300, 'NMS max_det saturation')
    require(0 <= guard['post_mask_count'] <= counts[0], 'NMS post mask count')
    equal(guard['empty_masks_removed'], counts[0] - guard['post_mask_count'], 'NMS empty count')
    if post_count is not None:
        equal(guard['post_mask_count'], post_count, 'NMS instance count')


def transition(base, candidate, ids):
    value = {'new_normal_alarms': [], 'resolved_normal_alarms': [],
             'gained_hits': {c: [] for c in NAMES}, 'lost_hits': {c: [] for c in NAMES}}
    for old, new, identity in zip(base, candidate, ids, strict=True):
        equal(old['normal'], new['normal'], 'transition truth normal')
        equal(set(old['hits']), set(new['hits']), 'transition truth classes')
        if old['normal'] and old['alarm'] != new['alarm']:
            key = 'new_normal_alarms' if new['alarm'] else 'resolved_normal_alarms'
            value[key].append(identity)
        for c in old['hits']:
            if old['hits'][c] != new['hits'][c]:
                value['gained_hits' if new['hits'][c] else 'lost_hits'][c].append(identity)
    return value


def check_outcomes(row, count, label):
    equal(row['image_count'], count, label + ' image count')
    equal(set(row['classes']), set(NAMES), label + ' classes')
    outcomes = row['sample_outcomes']
    equal(len(outcomes), count, label + ' outcome count')
    for outcome in outcomes:
        equal(set(outcome), {'hits', 'normal', 'alarm'}, label + ' outcome keys')
        require(type(outcome['normal']) is bool and type(outcome['alarm']) is bool,
                label + ' outcome booleans')
        require(set(outcome['hits']) <= set(NAMES), label + ' outcome class names')
        require(all(type(v) is int and v in (0, 1) for v in outcome['hits'].values()),
                label + ' binary hits')
        equal(outcome['normal'], not bool(outcome['hits']), label + ' normal GT')
    normal = sum(o['normal'] for o in outcomes)
    alarms = sum(o['normal'] and o['alarm'] for o in outcomes)
    equal(row['normal_images'], normal, label + ' normal count')
    equal(row['normal_false_alarms'], alarms, label + ' FA count')
    equal(row['normal_image_false_alarm_rate'], alarms / normal if normal else None, label + ' FA rate')
    equal(row['normal_image_false_alarm_ci95'], wilson95(alarms, normal), label + ' FA CI')
    confusion = np.asarray(row['confusion'])
    require(confusion.shape == (4, 4) and np.issubdtype(confusion.dtype, np.integer)
            and (confusion >= 0).all(), label + ' confusion schema')
    for index, c in enumerate(NAMES, 1):
        denominator = sum(c in o['hits'] for o in outcomes)
        hits = sum(o['hits'].get(c, 0) for o in outcomes)
        tp = int(confusion[index, index])
        union = int(confusion[index, :].sum() + confusion[:, index].sum() - tp)
        equal(row['classes'][c], {'iou': tp / union if union else None,
              'image_recall': hits / denominator if denominator else None,
              'image_hits': hits, 'image_denominator': denominator,
              'image_recall_ci95': wilson95(hits, denominator),
              'true_positive_pixels': tp, 'union_pixels': union}, label + ' ' + c)
    require(normal > 0 and all(v['image_denominator'] > 0 for v in row['classes'].values()),
            label + ' required denominators')
    equal(set(row['class_fp_per_image']), set(NAMES), label + ' FP names')
    for rate in [row['legacy_fp_per_image'], *row['class_fp_per_image'].values()]:
        require(np.isfinite(rate) and rate >= 0 and abs(rate * count - round(rate * count)) < 1e-8,
                label + ' FP rate/count consistency')


def macro(row):
    return sum(row['classes'][c]['image_recall'] for c in NAMES) / 3


def gate(shifted, train, name):
    if name == BASELINE:
        return False
    for result in (shifted, train):
        base, candidate = result['results'][BASELINE], result['results'][name]
        evidence = transition(base['sample_outcomes'], candidate['sample_outcomes'], result['ids'])
        if not base['normal_images'] or any(v['image_denominator'] == 0 for v in base['classes'].values()):
            return False
        if evidence['new_normal_alarms'] or any(evidence['lost_hits'].values()):
            return False
        if any(candidate['class_fp_per_image'][c] > base['class_fp_per_image'][c] + 1e-12 for c in NAMES):
            return False
    return macro(shifted['results'][name]) - macro(shifted['results'][BASELINE]) + 1e-12 >= .01


def ranking(result, name):
    row = result['results'][name]
    return (-macro(row), row['normal_image_false_alarm_rate'],
            -sum(row['classes'][c]['iou'] for c in NAMES) / 3,
            sum(abs(v - .25) for v in GRID[name]), name)


def replay_pairs(out, p, split, result, name, audit):
    """One streaming generator; no full image stack is retained."""
    old = None
    if audit and split.startswith('diagnostic'):
        old_name = 'val' if split.endswith('val') else 'shifted'
        old = np.load(Path(p['old_reference']) / f'{old_name}-predictions.npz', allow_pickle=False)
    count = 0
    try:
        for i, sample in enumerate(stream(p, split)):
            require(i < SPLITS[split][1], split + ' extra input')
            temp, truth = sample['temperature'], sample['mask']
            path = out / 'cache' / split / f'{i:05d}.npz'
            with np.load(path, allow_pickle=False) as z:
                masks, classes, scores = z['masks'], z['classes'], z['scores']
                prediction = compose(masks, classes, scores, truth.shape, GRID[name])
                if audit:
                    label = f'{split}[{i}]'
                    require(np.isfinite(temp).all(), label + ' finite input')
                    equal(sha(path), result['cache_hashes'][i], label + ' cache hash')
                    equal(digest(temp), result['input_hashes'][i], label + ' input hash')
                    equal(str(z['input_sha']), digest(temp), label + ' cache input header')
                    equal(str(z['protocol_sha']), sha(out / 'protocol.json'), label + ' protocol header')
                    equal(digest(truth), result['truth_hashes'][i], label + ' truth hash')
                    equal(digest(z['truth']), digest(truth), label + ' cache truth bytes/dtype')
                    require(np.array_equal(z['truth'], truth), label + ' cache truth')
                    old_id = f"{sample['job']['condition']}:{sample['job']['job_id']}"
                    equal(result['ids'][i], f'{split}:{old_id}', label + ' sample ID')
                    equal(result['image_rows'][i]['sample_id'], result['ids'][i], label + ' feature ID')
                    equal(result['image_rows'][i]['cache'], str(path.relative_to(out)), label + ' cache path')
                    equal(result['image_rows'][i]['normal'], not bool(truth.any()), label + ' normal')
                    equal(result['image_rows'][i]['baseline_alarm'], bool(prediction.any()), label + ' baseline alarm')
                    equal(result['image_rows'][i]['instance_count_at_floor'], len(scores), label + ' floor count')
                    equal(bool(z['sentinel']), i < 4, label + ' sentinel flag')
                    guard = json.loads(str(z['guard']))
                    equal(guard, result['nms_guards'][i], label + ' guard header')
                    equal(set(guard), {'floor', 'baseline'}, label + ' guard keys')
                    check_guard(guard['floor'], len(scores))
                    check_guard(guard['baseline'], int((scores > np.float32(.25)).sum()))
                    require(z['native'].dtype == np.uint8 and z['native'].shape == truth.shape,
                            label + ' native mask schema')
                    require(np.array_equal(prediction, z['native']), label + ' cached/native .25 parity')
                    if old is not None:
                        equal(str(old['ids'][i]), old_id, label + ' previous ID')
                        require(np.array_equal(old['trained_yolo'][i], z['native']), label + ' previous prediction')
                        require(np.array_equal(old['truth'][i], truth), label + ' previous truth')
                    present = {NAMES[c - 1] for c in (1, 2, 3) if (truth == c).any()}
                    for method, row in result['results'].items():
                        outcome = row['sample_outcomes'][i]
                        equal(set(outcome['hits']), present, label + ' ' + method + ' GT class set')
                        equal(outcome['normal'], not bool(present), label + ' ' + method + ' normal GT')
            count += 1
            yield truth, prediction
        equal(count, SPLITS[split][1], split + ' regenerated count')
        if old is not None:
            equal(len(old['ids']), count, split + ' previous count')
    finally:
        if old is not None:
            old.close()


def validate(out):
    artifact_names = ['protocol.json', 'selection.json', 'decision.json',
                      *[s + '.json' for s in SPLITS]]
    initial_hashes = {name: sha(out / name) for name in artifact_names}
    p = check_protocol(out)
    selection = read(out / 'selection.json')
    evidence_files = {'protocol.json', *[name + '.json' for name in SPLITS
                                        if not name.startswith('confirmation')]}
    equal(set(selection['evidence_hashes']), evidence_files, 'selection evidence inventory')
    for filename, expected in selection['evidence_hashes'].items():
        equal(sha(out / filename), expected, 'selection evidence ' + filename)
    equal(selection['confirmation_accessed'], False, 'selection confirmation flag')
    require(selection['selected'] in GRID and selection['challenger'] in GRID
            and selection['challenger'] != BASELINE, 'selection identities')
    compare = selection['selected'] if selection['selected'] != BASELINE else selection['challenger']
    replay_names = [BASELINE, compare]
    all_results, seen_inputs, seen_ids, summaries = {}, set(), set(), {}
    for split, (_, count, _) in SPLITS.items():
        print(f'Validating {split}: {count} images; saved outcomes first', flush=True)
        result = read(out / f'{split}.json')
        all_results[split] = result
        equal(result['split'], split, split + ' name')
        expected_names = replay_names if split.startswith('confirmation') else list(GRID)
        equal(set(result['results']), set(expected_names), split + ' method registry')
        equal(result['grid_count'], len(expected_names), split + ' grid count')
        for key in ('ids', 'input_hashes', 'truth_hashes', 'cache_hashes', 'nms_guards', 'image_rows'):
            equal(len(result[key]), count, split + ' ' + key + ' count')
        for key in ('input_hashes', 'ids'):
            equal(len(set(result[key])), count, split + ' unique ' + key)
        require(not seen_inputs.intersection(result['input_hashes']), split + ' cross-split input leakage')
        require(not seen_ids.intersection(result['ids']), split + ' cross-split ID leakage')
        seen_inputs.update(result['input_hashes'])
        seen_ids.update(result['ids'])
        equal(result['parity'], {'native025_all': count, 'native040_and_mixed_sentinels': 4,
                                'old_verified_baseline': count if split.startswith('diagnostic') else 0},
              split + ' parity counts')
        equal({f.name for f in (out / 'cache' / split).glob('*.npz')},
              {f'{i:05d}.npz' for i in range(count)}, split + ' cache file inventory')
        changes = set(expected_names) - {BASELINE}
        equal(set(result['changes']), changes, split + ' changes inventory')
        equal(set(result['transitions']), changes, split + ' transitions inventory')
        paired_cache = {}
        for name, row in result['results'].items():
            check_outcomes(row, count, split + ':' + name)
            if name != BASELINE:
                outcomes = row['sample_outcomes']
                key = json.dumps(outcomes, sort_keys=True, separators=(',', ':'))
                if key not in paired_cache:
                    paired_cache[key] = paired_change(result['results'][BASELINE]['sample_outcomes'],
                                                       outcomes, seed=19, repeats=2000)
                equal(result['changes'][name], paired_cache[key], split + ':' + name + ' paired CI')
                equal(result['transitions'][name], transition(result['results'][BASELINE]['sample_outcomes'],
                      outcomes, result['ids']), split + ':' + name + ' transitions')
        for name in replay_names:
            print(f'Replaying {split}: {name}', flush=True)
            replayed = evaluate_arrays(replay_pairs(out, p, split, result, name, name == BASELINE))
            equal(replayed, result['results'][name], split + ':' + name + ' full pixel metrics')
        summaries[split] = {'images': count, 'saved_outcome_methods_checked': len(expected_names),
                            'pixel_metrics_replayed': replay_names, 'cache_files_checked': count,
                            'coverage': 1.0, 'native025_cache_parity': count,
                            'reported_native040_mixed_sentinels': 4}
        print(f'Validated {split}: {count} images', flush=True)
    shifted, train = (all_results['selection_' + kind] for kind in ('shifted', 'train'))
    ranked = sorted((name for name in GRID if name != BASELINE), key=lambda name: ranking(shifted, name))
    eligible = [name for name in ranked if gate(shifted, train, name)]
    selected = eligible[0] if eligible else BASELINE
    equal(selection['challenger'], ranked[0], 'challenger ranking')
    equal(selection['eligible'], eligible, 'eligible list')
    equal(selection['selected'], selected, 'selected gate')
    shifted, train = (all_results['confirmation_' + kind] for kind in ('shifted', 'train'))
    confirmed = selected != BASELINE and gate(shifted, train, selected)
    if confirmed:
        confirmed = shifted['changes'][selected]['macro_recall_change']['ci95'][0] > 0
    decision = read(out / 'decision.json')
    equal(decision, {'selected_on_selection': selected, 'confirmed_improvement': bool(confirmed),
          'recommended': selected if confirmed else BASELINE, 'production_defaults_changed': False,
          'confirmation_data_external': False,
          'decision': 'fixed candidate passed independent-seed synthetic confirmation' if confirmed else
                      'keep baseline; no confirmed improvement under preregistered gate'}, 'decision replay')
    # Detect concurrent edits to immutable evidence during validation as well.
    check_protocol(out)
    for filename, expected in initial_hashes.items():
        equal(sha(out / filename), expected, 'unchanged during validation ' + filename)
    for filename, expected in selection['evidence_hashes'].items():
        equal(sha(out / filename), expected, 'final evidence ' + filename)
    return {'status': 'passed', 'protocol_sha256': sha(out / 'protocol.json'),
            'validator_sha256': sha(__file__), 'splits': summaries,
            'total_unique_inputs': len(seen_inputs), 'selected': selected,
            'confirmed_improvement': bool(confirmed), 'recommended': decision['recommended'],
            'artifact_hashes': {name: sha(out / name) for name in
                               ['selection.json', 'decision.json', *[s + '.json' for s in SPLITS]]},
            'scope': 'All saved outcomes, Wilson intervals, paired changes, transitions, gates, hashes, '
                     'regenerated inputs and cache guards checked. Baseline plus selected/best challenger '
                     'pixel metrics independently replayed on all six splits. Other grid pixel masks '
                     'were not replayed. Sentinel parity is a recorded assertion, not rerun inference. '
                     'No model inference, retraining, timing or external-field validation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    destination = args.out / 'validation.json'
    if destination.exists():
        raise FileExistsError(destination)
    try:
        result = validate(args.out)
    # Fail closed with a durable failure artifact for any validation/library error.
    except Exception as error:  # noqa: BLE001
        result = {'status': 'failed', 'reason': f'{type(error).__name__}: {error}',
                  'validator_sha256': sha(__file__)}
    with destination.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
    print(result['status'] + (': ' + result['reason'] if 'reason' in result else ''), flush=True)
    if result['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
