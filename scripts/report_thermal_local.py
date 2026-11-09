"""Validate saved thermal experiment summaries and export reviewable tables."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from maek.thermal_dataset import CLASS_NAMES, wilson95
from maek.thermal_validation import paired_change
from scripts.evaluate_thermal_local import disjoint, read, save, sha, verify

LABELS = {'baseline': 'baseline(채택)', 'wet_local_relative': '상대 대비',
          'wet_local_mad': '국소 MAD(미채택)', 'wet_local_median3_mad': 'median3+MAD'}
SPLITS = ['develop', 'select', 'final_shifted', 'final_train', 'seen_shifted300_diagnostic']


def percent(value):
    return f'{100 * value:.2f}%'


def ratio(hit, count):
    return f'{hit}/{count} ({percent(hit / count)})' if count else '분모 없음'


def interval(record):
    lo, hi = record['ci95']
    return f"{record['change'] * 100:+.2f} [{lo * 100:+.2f}, {hi * 100:+.2f}]"


def validate(result):
    for name, metrics in result['results'].items():
        q = result['quality'][name]
        outcomes = metrics['sample_outcomes']
        assert len(outcomes) == metrics['image_count'] == q['frames'] - q['frame_abstentions']
        normal = sum(o['normal'] for o in outcomes)
        alarms = sum(o['normal'] and o['alarm'] for o in outcomes)
        assert (normal, alarms) == (metrics['normal_images'], metrics['normal_false_alarms'])
        assert metrics['normal_image_false_alarm_rate'] == (alarms / normal if normal else None)
        assert metrics['normal_image_false_alarm_ci95'] == wilson95(alarms, normal)
        confusion = np.asarray(metrics['confusion'])
        for cls, label in enumerate(CLASS_NAMES[1:], 1):
            row = metrics['classes'][label]
            hits = sum(o['hits'].get(label, 0) for o in outcomes)
            den = sum(label in o['hits'] for o in outcomes)
            assert (hits, den) == (row['image_hits'], row['image_denominator'])
            assert row['image_recall'] == (hits / den if den else None)
            assert row['image_recall_ci95'] == wilson95(hits, den)
            assert row['true_positive_pixels'] == confusion[cls, cls]
            assert row['union_pixels'] == confusion[cls].sum() + confusion[:, cls].sum() - confusion[cls, cls]
            assert row['iou'] == (row['true_positive_pixels'] / row['union_pixels']
                                  if row['union_pixels'] else None)
            if name != 'baseline' and cls in (2, 3):
                assert row == result['results']['baseline']['classes'][label]
        if name != 'baseline':
            assert result['changes'][name] == paired_change(
                result['results']['baseline']['sample_outcomes'], outcomes)


def export(out):
    protocol = verify(out)
    selection = read(out / 'selection.json')
    assert selection['protocol_sha256'] == sha(out / 'protocol.json')
    assert selection['development_sha256'] == sha(out / 'develop.json')
    assert selection['selection_data_sha256'] == sha(out / 'select.json')
    previous, flat, text = [], [], []
    for split in SPLITS:
        result = read(out / f'{split}.json')
        validate(result)
        disjoint(previous, result)
        previous.append(result)
        text += [f'### {split}', '',
                 '| 방법 | 평가/전체 | 젖은 보온재 | 보온 손상 | 증기 누설 | Macro | 정상 오경보 | 영상 보류 |',
                 '|---|---:|---:|---:|---:|---:|---:|---:|']
        for name, row in result['results'].items():
            q = result['quality'][name]
            values = [row['classes'][c] for c in CLASS_NAMES[1:]]
            recalls = [ratio(r['image_hits'], r['image_denominator']) for r in values]
            macro = float(np.mean([r['image_recall'] for r in values]))
            text.append(f"| {LABELS[name]} | {row['image_count']}/{q['frames']} | " +
                        ' | '.join(recalls) + f" | {percent(macro)} | " +
                        ratio(row['normal_false_alarms'], row['normal_images']) +
                        ' | ' + ratio(q['frame_abstentions'], q['frames']) + ' |')
            for c in CLASS_NAMES[1:]:
                r = row['classes'][c]
                flat.append({'split': split, 'method': name, 'class': c, **r,
                             'class_fp_per_evaluated_image': row['class_fp_per_image'][c],
                             'evaluated_images': row['image_count'], 'total_images': q['frames'],
                             'normal_false_alarms': row['normal_false_alarms'],
                             'normal_images': row['normal_images'],
                             'normal_fa_ci95': row['normal_image_false_alarm_ci95'], **q})
        text += ['', '| 후보−baseline | 정상 FA 감소, pp [95% CI] | Wet 재현율 변화, pp [95% CI] | Macro 변화, pp [95% CI] |',
                 '|---|---:|---:|---:|']
        for name, change in result['changes'].items():
            text.append(f'| {LABELS[name]} | ' + interval(change['fa_reduction']) + ' | ' +
                        interval(change['per_class_recall_change']['wet_insulation']) + ' | ' +
                        interval(change['macro_recall_change']) + ' |')
        text += ['', '| 방법 | IoU wet / damage / steam | 클래스 불일치 FP 성분/장 wet / damage / steam | 지역 필터 보류 영상 |',
                 '|---|---|---|---|']
        for name, row in result['results'].items():
            q = result['quality'][name]
            text.append(f'| {LABELS[name]} | ' + ' / '.join(
                f"{row['classes'][c]['iou']:.4f}" for c in CLASS_NAMES[1:]) + ' | ' +
                ' / '.join(f"{row['class_fp_per_image'][c]:.4f}" for c in CLASS_NAMES[1:]) +
                f" | {q['local_support_frames']}/{row['image_count']} |")
        text.append('')
    with (out / 'thermal-performance.csv').open('x', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat[0]))
        writer.writeheader()
        writer.writerows(flat)
    with (out / 'thermal-tables.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(text))
    save(out / 'validation.json', {'status': 'passed', 'split_count': len(previous),
         'unique_images': sum(len(r['data_hashes']) for r in previous),
         'checks': ['frozen code/config/archive and selection evidence hashes',
                    'all split raw+truth+pipe tuple hashes disjoint', 'outcome denominators/hits/normal FA',
                    'Wilson CI and paired bootstrap recomputed',
                    'class2/3 exact aggregate equality', 'confusion TP and IoU union'],
         'selected': selection['selected'], 'external_validation': False,
         'protocol_sha256': sha(out / 'protocol.json'),
         'result_hashes': {split: sha(out / f'{split}.json') for split in SPLITS}})
    print(json.dumps({'validated': len(previous), 'selected': selection['selected'],
                      'protocol': protocol['splits']}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    export(parser.parse_args().out)
