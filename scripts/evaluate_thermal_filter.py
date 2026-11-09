"""Develop, freeze, select and test wet-component filters on disjoint synthetic sets."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maek import params
from maek import thermal_render as tr
from maek.thermal_dataset import evaluate_arrays
from maek.thermal_filter import FILTERS, RESCUE_CONTRAST_C, filter_wet_components
from maek.thermal_validation import paired_change, passes_gate
from scripts.diagnose_thermal_components import samples

SPLITS = {'develop': (20261109, 240, 'dr'), 'select': (20261110, 400, 'dr'),
          'shifted_new': (20261111, 600, 'shifted'), 'train_new': (20261112, 400, 'train')}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    names = ['maek/thermal_filter.py', 'maek/thermal_validation.py', 'maek/thermal_render.py',
             'maek/thermal_dataset.py', 'config/default.yaml', 'scripts/evaluate_thermal_filter.py',
             'scripts/diagnose_thermal_components.py', 'scripts/evaluate_thermal_v3.py']
    return {name: sha(ROOT / name) for name in names}


def save(path, data):
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')


def compare(split, methods):
    seed, count, condition = SPLITS[split]
    cfg = params.load_config()
    pairs = {name: [] for name in methods}
    identifiers, hashes = [], []
    for s in samples(seed, count, condition):
        baseline = tr.detect_ir(cfg, s['temperature'], s['pipe'])
        identifiers.append(f"{condition}:{seed}:{s['job']['job_id']}")
        hashes.append(hashlib.sha256(s['temperature'].tobytes() + s['mask'].tobytes()).hexdigest())
        for name in methods:
            pred = baseline if name == 'baseline' else filter_wet_components(
                s['temperature'], s['pipe'], baseline, name)
            pairs[name].append((s['mask'], pred))
    metrics = {name: evaluate_arrays(items) for name, items in pairs.items()}
    base = metrics['baseline']
    changes = {}
    for name, m in metrics.items():
        if name == 'baseline':
            continue
        changes[name] = paired_change(base['sample_outcomes'], m['sample_outcomes'])
        changes[name]['point_gate_pass'] = passes_gate(
            changes[name], base['normal_image_false_alarm_rate'])
        print(split, name, 'FA', m['normal_image_false_alarm_rate'],
              'macro delta', changes[name]['macro_recall_change']['change'],
              'gate', changes[name]['point_gate_pass'], flush=True)
    return {'split': split, 'seed': seed, 'count': count, 'condition': condition,
            'sample_ids': identifiers, 'data_hashes': hashes, 'metrics': metrics, 'changes': changes}


def verify_frozen(out):
    frozen = json.loads((out / 'frozen.json').read_text())
    if frozen['source_hashes'] != source_hashes():
        raise ValueError('Code or configuration changed since candidates were frozen')
    if frozen['filters'] != FILTERS or frozen['splits'] != {k: list(v) for k, v in SPLITS.items()}:
        raise ValueError('Candidate or split changed')
    if frozen['protocol_sha256'] != sha(out / 'protocol.md'):
        raise ValueError('Preregistered protocol changed')
    return frozen


def assert_disjoint(previous, current):
    old = {h for result in previous for h in result['data_hashes']}
    if old.intersection(current['data_hashes']):
        raise ValueError('Data overlap across development/selection/test')
    if len(current['data_hashes']) != len(set(current['data_hashes'])):
        raise ValueError('Duplicate samples within split')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage', required=True, choices=['develop', 'select', 'test'])
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    methods = ['baseline', *FILTERS]
    if a.stage == 'develop':
        if (a.out / 'frozen.json').exists() or (a.out / 'develop.json').exists():
            raise FileExistsError('Development run already exists')
        result = compare('develop', methods)
        assert_disjoint([], result)
        save(a.out / 'develop.json', result)
        save(a.out / 'frozen.json', {'source_hashes': source_hashes(), 'filters': FILTERS,
                                    'rescue_contrast_c': RESCUE_CONTRAST_C, 'splits': SPLITS,
                                    'protocol_sha256': sha(a.out / 'protocol.md'),
                                    'metric': 'class-image recall, not individual defect hit',
                                    'pipe_mask': 'known synthetic geometry'})
        return
    verify_frozen(a.out)
    dev = json.loads((a.out / 'develop.json').read_text())
    if a.stage == 'select':
        if (a.out / 'selection.json').exists():
            raise FileExistsError('Selection already exists')
        result = compare('select', methods)
        assert_disjoint([dev], result)
        eligible = [n for n in FILTERS if result['changes'][n]['point_gate_pass']]
        result['selected'] = min(eligible, key=lambda n: (
            result['metrics'][n]['normal_image_false_alarm_rate'],
            -result['changes'][n]['macro_recall_change']['change'])) if eligible else 'baseline'
        save(a.out / 'selection.json', result)
        print('SELECTED', result['selected'], flush=True)
        return
    if (a.out / 'final.json').exists():
        raise FileExistsError('Final test already exists')
    selection = json.loads((a.out / 'selection.json').read_text())
    name = selection['selected']
    methods = list(dict.fromkeys(['baseline', name]))
    shifted = compare('shifted_new', methods)
    assert_disjoint([dev, selection], shifted)
    train = compare('train_new', methods)
    assert_disjoint([dev, selection, shifted], train)
    if name == 'baseline':
        passed = False
    else:
        change = train['changes'][name]
        passed = (shifted['changes'][name]['point_gate_pass']
                  and change['fa_reduction']['change'] >= -1e-12
                  and change['macro_recall_change']['change'] >= -.02 - 1e-12
                  and all(x['change'] >= -.05 - 1e-12
                          for x in change['per_class_recall_change'].values()))
    save(a.out / 'final.json', {'selected': name, 'point_success': passed,
                              'frozen_sha256': sha(a.out / 'frozen.json'),
                              'selection_sha256': sha(a.out / 'selection.json'),
                              'shifted_new': shifted, 'train_new': train})
    rows = []
    for result in [shifted, train]:
        for method, m in result['metrics'].items():
            for cls, values in m['classes'].items():
                rows.append({'split': result['split'], 'seed': result['seed'], 'method': method,
                             'class': cls, **values, 'normal_images': m['normal_images'],
                             'normal_false_alarms': m['normal_false_alarms'],
                             'normal_fa': m['normal_image_false_alarm_rate'],
                             'class_fp_per_image': m['class_fp_per_image'][cls]})
    with (a.out / 'performance.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print('FINAL_POINT_SUCCESS', passed, flush=True)


if __name__ == '__main__':
    main()
