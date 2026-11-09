"""Freeze small local-contrast hypotheses before fresh synthetic evaluation.

Every phase writes exclusively. Final data are never read by selection.
Different seeds of one simulator are not external field validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from maek import params
from maek import thermal_render as tr
from maek.thermal_dataset import CLASS_NAMES, evaluate_arrays, load_zip, wilson95
from maek.thermal_local_contrast import CANDIDATES, detect_ir
from maek.thermal_validation import paired_change, passes_gate
from scripts.diagnose_thermal_components import samples

SPLITS = {'develop': [20261121, 160, 'dr'], 'select': [20261122, 240, 'dr'],
          'final_shifted': [20261123, 400, 'shifted'],
          'final_train': [20261124, 200, 'train']}
SOURCES = ('scripts/evaluate_thermal_local.py', 'maek/thermal_local_contrast.py',
           'maek/thermal_dataset.py', 'maek/thermal_validation.py', 'maek/thermal_render.py',
           'maek/params.py', 'maek/network.py', 'maek/thermal.py', 'maek/heat.py',
           'maek/pod.py', 'maek/camera/composite2d.py', 'maek/camera/__init__.py',
           'config/default.yaml',
           'scripts/diagnose_thermal_components.py', 'scripts/evaluate_thermal_v3.py')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def source_hashes():
    return {name: sha(ROOT / name) for name in SOURCES}


def freeze(out, archive):
    save(out / 'protocol.json', {
        'source_hashes': source_hashes(), 'splits': SPLITS,
        'candidates': {k: asdict(v) for k, v in CANDIDATES.items()},
        'selection': 'select split only; development is descriptive; no tuning this run',
        'gate': {'fa_reduction_point': '>=10 percentage points OR >=50% relative',
                 'fa_reduction_ci95_lower': '>0', 'macro_recall_ci95_lower': '>=-0.02',
                 'each_recall_ci95_lower': '>=-0.05', 'frame_abstentions': 0},
        'ranking': 'lowest normal FA, then highest macro recall, then name',
        'fallback': 'baseline; best ranked challenger still evaluated, explicitly diagnostic',
        'bootstrap': {'seed': 19, 'repeats': 2000, 'unit': 'paired image'},
        'oracle_pipe': True, 'old_shifted_300': 'previously seen; diagnostic only',
        'archive': str(archive.resolve()), 'archive_sha256': sha(archive),
        'python': platform.python_version(), 'numpy': np.__version__,
        'external_validation': False, 'config': params.load_config()})


def verify(out):
    protocol = read(out / 'protocol.json')
    if protocol['source_hashes'] != source_hashes():
        raise ValueError('Frozen source changed; use a new experiment directory')
    if protocol['splits'] != SPLITS:
        raise ValueError('Frozen split changed')
    if sha(protocol['archive']) != protocol['archive_sha256']:
        raise ValueError('Archive changed')
    return protocol


class Accumulator:
    """Combine exact one-image metrics without keeping full-frame arrays in RAM."""
    def __init__(self):
        self.rows = []

    def add(self, truth, prediction):
        self.rows.append(evaluate_arrays([(truth, prediction)]))

    def result(self):
        if not self.rows:
            return evaluate_arrays([])
        result = evaluate_arrays([])
        rows = self.rows
        n = len(rows)
        confusion = sum((np.asarray(r['confusion']) for r in rows), np.zeros((4, 4), int))
        result.update(image_count=n, confusion=confusion.tolist(),
                      sample_outcomes=[r['sample_outcomes'][0] for r in rows],
                      normal_images=sum(r['normal_images'] for r in rows),
                      normal_false_alarms=sum(r['normal_false_alarms'] for r in rows),
                      legacy_fp_per_image=sum(r['legacy_fp_per_image'] for r in rows) / n,
                      class_fp_per_image={name: sum(r['class_fp_per_image'][name]
                                                   for r in rows) / n
                                          for name in CLASS_NAMES[1:]})
        normal, alarms = result['normal_images'], result['normal_false_alarms']
        result['normal_image_false_alarm_rate'] = alarms / normal if normal else None
        result['normal_image_false_alarm_ci95'] = wilson95(alarms, normal)
        for name in CLASS_NAMES[1:]:
            item = result['classes'][name]
            for key in ('image_hits', 'image_denominator', 'true_positive_pixels', 'union_pixels'):
                item[key] = sum(r['classes'][name][key] for r in rows)
            hit, den = item['image_hits'], item['image_denominator']
            item['image_recall'] = hit / den if den else None
            item['image_recall_ci95'] = wilson95(hit, den)
            item['iou'] = item['true_positive_pixels'] / item['union_pixels'] if item['union_pixels'] else None
        return result


def evaluate(stream, names, label):
    cfg = params.load_config()
    accumulators = {n: Accumulator() for n in names}
    quality = {n: {'frames': 0, 'frame_abstentions': 0, 'local_support_frames': 0,
                   'local_support_components': 0, 'local_support_pixels': 0,
                   'removed_components': 0, 'saturated_frames': 0} for n in names}
    hashes, identities = [], []
    for i, sample in enumerate(stream):
        temp, truth = sample['temperature'], sample['mask']
        pipe = sample.get('pipe')
        if pipe is None:
            pipe = tr.pipe_mask(sample['job'])
        raw = np.clip(np.rint((temp + 50) * 100), 0, 65535).astype(np.uint16)
        hashes.append(hashlib.sha256(raw.tobytes() + truth.tobytes() + pipe.tobytes()).hexdigest())
        identities.append(f"{label}:{sample['job']['job_id']}")
        # Quality is shared by all candidates; do not silently score an abstained frame as normal.
        check = detect_ir(cfg, temp, pipe, raw_uint16=raw)
        for name in names:
            result = check if name == 'baseline' else detect_ir(
                cfg, temp, pipe, name, baseline_prediction=check.mask, raw_uint16=raw)
            q, totals = result.quality, quality[name]
            totals['frames'] += 1
            totals['frame_abstentions'] += int(result.mask is None)
            totals['saturated_frames'] += int(q.saturated_pixels > 0)
            totals['local_support_frames'] += int(q.abstained_components > 0)
            totals['local_support_components'] += q.abstained_components
            totals['local_support_pixels'] += q.abstained_pixels
            totals['removed_components'] += q.removed_components
            if result.mask is not None:
                accumulators[name].add(truth, result.mask)
        if (i + 1) % 40 == 0:
            print(label, i + 1, flush=True)
    if len(hashes) != len(set(hashes)):
        raise ValueError('Duplicate data inside split')
    results = {n: a.result() for n, a in accumulators.items()}
    baseline = results['baseline']['sample_outcomes']
    changes = {n: paired_change(baseline, r['sample_outcomes'])
               for n, r in results.items() if n != 'baseline'}
    return {'label': label, 'data_hashes': hashes, 'identities': identities,
            'results': results, 'quality': quality, 'changes': changes}


def disjoint(previous, current):
    seen = {h for old in previous for h in old['data_hashes']}
    if seen.intersection(current['data_hashes']):
        raise ValueError('Data overlap between splits')


def eligible(change, baseline_fa, quality):
    if quality['frame_abstentions'] or not passes_gate(change, baseline_fa):
        return False
    checks = [(change['fa_reduction'], 0, True),
              (change['macro_recall_change'], -.02, False)]
    checks += [(r, -.05, False) for r in change['per_class_recall_change'].values()]
    return all(r['ci95'] is not None and (r['ci95'][0] > limit if strict
               else r['ci95'][0] >= limit) for r, limit, strict in checks)


def ranking(result, name):
    row = result['results'][name]
    macro = np.mean([c['image_recall'] for c in row['classes'].values()])
    return row['normal_image_false_alarm_rate'], -float(macro), name


def phase(out, stage):
    protocol = verify(out)
    if stage in ('develop', 'select'):
        previous = [] if stage == 'develop' else [read(out / 'develop.json')]
        seed, count, condition = SPLITS[stage]
        result = evaluate(samples(seed, count, condition), list(CANDIDATES), stage)
        disjoint(previous, result)
        save(out / f'{stage}.json', result)
        if stage == 'select':
            names = sorted(result['changes'], key=lambda n: ranking(result, n))
            passed = [n for n in names if eligible(result['changes'][n],
                      result['results']['baseline']['normal_image_false_alarm_rate'],
                      result['quality'][n])]
            save(out / 'selection.json', {'selected': passed[0] if passed else 'baseline',
                 'challenger': names[0], 'eligible': passed,
                 'protocol_sha256': sha(out / 'protocol.json'),
                 'development_sha256': sha(out / 'develop.json'),
                 'selection_data_sha256': sha(out / 'select.json'),
                 'final_accessed': False})
        return
    selection = read(out / 'selection.json')
    for field, file in [('protocol_sha256', 'protocol.json'),
                        ('development_sha256', 'develop.json'),
                        ('selection_data_sha256', 'select.json')]:
        if selection[field] != sha(out / file):
            raise ValueError('Selection evidence changed')
    names = list(dict.fromkeys(['baseline', selection['selected'], selection['challenger']]))
    previous = [read(out / f'{s}.json') for s in ('develop', 'select')]
    for split in ('final_shifted', 'final_train'):
        seed, count, condition = SPLITS[split]
        result = evaluate(samples(seed, count, condition), names, split)
        disjoint(previous, result)
        save(out / f'{split}.json', result)
        previous.append(result)
    old = (s for split in ('train', 'val') for s in load_zip(protocol['archive'], 'shifted', split))
    result = evaluate(old, names, 'seen_shifted300_diagnostic')
    disjoint(previous, result)
    save(out / 'seen_shifted300_diagnostic.json', result)
    print('Final complete; selection remains', selection['selected'], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['freeze', 'develop', 'select', 'final'])
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    if args.stage == 'freeze':
        if args.archive is None:
            parser.error('--archive is required for freeze')
        freeze(args.out, args.archive)
    else:
        phase(args.out, args.stage)


if __name__ == '__main__':
    main()
