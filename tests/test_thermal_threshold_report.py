"""Pure formatting checks; no model, image data, or inference dependencies."""
import csv
import itertools
import json
import tempfile
import unittest
from pathlib import Path

from scripts import report_thermal_thresholds as report


class ReportTests(unittest.TestCase):
    def test_end_to_end_format_and_exclusive_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            grid = {f'w{int(w*100):02d}_d{int(d*100):02d}_s{int(s*100):02d}': [w, d, s]
                    for w, d, s in itertools.product((.1, .25, .4), repeat=3)}
            base, challenger = 'w25_d25_s25', 'w10_d10_s10'
            protocol = {'baseline': base, 'grid': grid,
                        'splits': {name: [i, 1, 'train'] for i, name in enumerate(report.SPLITS)},
                        'weights_sha256': 'weights', 'archive_sha256': 'archive',
                        'runtime': {'python': 'test'}, 'archive': 'archive.zip',
                        'weights': 'best.pt', 'old_reference': 'reference'}
            def save(name, value):
                (out / name).write_text(json.dumps(value), encoding='utf-8')
            save('protocol.json', protocol)
            metric = {'image_count': 1, 'normal_images': 1, 'normal_false_alarms': 0,
                      'sample_outcomes': [{'normal': True, 'alarm': False}],
                      'normal_image_false_alarm_rate': 0,
                      'normal_image_false_alarm_ci95': [0, .79],
                      'class_fp_per_image': {c: 0 for c in report.CLASSES},
                      'classes': {c: {'image_recall': 1, 'iou': 1, 'image_hits': 1,
                                      'image_denominator': 1, 'true_positive_pixels': 1,
                                      'union_pixels': 1} for c in report.CLASSES}}
            for split in report.SPLITS:
                names = [base, challenger] if split.startswith('confirmation') else grid
                transitions = {n: {'new_normal_alarms': [], 'resolved_normal_alarms': [],
                                   'gained_hits': {c: [] for c in report.CLASSES},
                                   'lost_hits': {c: [] for c in report.CLASSES}}
                               for n in names if n != base}
                change = {'change': 0, 'ci95': [0, 0], 'bootstrap_valid': 2000}
                rows = [{'sample_id': split, 'class_id': c, 'category': 'baseline_hit',
                         'baseline_hit': True, 'any_grid_hit': True,
                         'features': {'local_contrast_c': float(c), 'gt_pixels': 10,
                                      'gt_clip_fraction': 0}, 'scene': {}}
                        for c in (1, 2, 3)]
                data = {'ids': [split], 'input_hashes': [split],
                        'image_rows': [{'sample_id': split, 'normal': True,
                                        'features': {'hard': [], 'jacket': None,
                                                     'input_clip_fraction': 0}}],
                        'results': {n: metric for n in names}, 'grid_count': len(names),
                        'changes': {n: {'macro_recall_change': change} for n in names if n != base},
                        'transitions': transitions, 'error_rows': rows,
                        'error_summary': {'groups': []},
                        'parity': {'native025_all': 1, 'native040_and_mixed_sentinels': 1,
                                   'old_verified_baseline': int(split.startswith('diagnostic'))}}
                save(f'{split}.json', data)
            save('selection.json', {'selected': base, 'challenger': challenger, 'eligible': [],
                                    'evidence_hashes': {'protocol.json': report.sha(out / 'protocol.json')}})
            save('decision.json', {'selected_on_selection': base, 'recommended': base,
                                   'confirmed_improvement': False})
            (out / 'review67').mkdir()
            (out / 'review67' / '07-judge.md').write_text(
                '| rank | score |\n|---|---|\n' + ''.join(f'| {i} | 9/9/9 |\n' for i in range(6)) +
                '\n## 가져온 부분 장부\n\n- six proposals\n', encoding='utf-8')
            result = report.generate(out)
            self.assertEqual(result['comparison_rows'], 112)
            self.assertEqual(result['error_rows'], 18)
            self.assertEqual(result['normal_error_groups'], 112 * 4)
            with (out / 'threshold-comparison.csv').open(encoding='utf-8-sig', newline='') as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 112)
            text = (out / 'report.md').read_text(encoding='utf-8')
            self.assertLess(text.index('| rank'), text.index('## 통합 실험 결과'))
            self.assertIn('자동 테스트 통과를 주장하지 않는다', text)
            self.assertIn('원시 제안 부재를 증명하지 않는다', text)
            self.assertIn('signed local contrast', text)
            self.assertIn('## 가져온 부분 장부', text)
            self.assertIn('## 정상 이미지의 오경보 오류', text)
            with (out / 'normal-error-groups.csv').open(encoding='utf-8-sig', newline='') as stream:
                normal_rows = list(csv.DictReader(stream))
            self.assertEqual(len(normal_rows), 112 * 4)
            self.assertTrue(any(r['scope'] == 'hard' and r['bin'] == 'none' for r in normal_rows))
            with self.assertRaises(FileExistsError):
                report.generate(out)

    def test_transition_rows_preserve_sample_identifiers(self):
        data = {'error_rows': [], 'error_summary': {'groups': []},
                'transitions': {'candidate': {'new_normal_alarms': ['id:007'],
                                              'resolved_normal_alarms': [],
                                              'gained_hits': {'steam_leak': ['id:008']},
                                              'lost_hits': {'wet_insulation': ['id:009']}}}}
        _, ledger, _ = report.detail_rows({'selection_shifted': data})
        self.assertEqual([r['sample_id'] for r in ledger], ['id:007', 'id:008', 'id:009'])

    def test_normal_groups_overlap_tags_and_alignment(self):
        images = [
            {'sample_id': 'id:01', 'normal': True, 'features': {'hard': ['reflection', 'streak', 'streak'], 'jacket': 'aluminium', 'input_clip_fraction': .05}},
            {'sample_id': 'id:02', 'normal': True, 'features': {'hard': [], 'jacket': None, 'input_clip_fraction': 0}},
            {'sample_id': 'id:03', 'normal': False, 'features': {}},
        ]
        base = [{'normal': True, 'alarm': False}, {'normal': True, 'alarm': True}, {'normal': False, 'alarm': True}]
        candidate = [{'normal': True, 'alarm': True}, {'normal': True, 'alarm': False}, {'normal': False, 'alarm': True}]
        data = {'ids': [r['sample_id'] for r in images], 'image_rows': images,
                'results': {name: {'sample_outcomes': outcomes, 'normal_images': 2, 'normal_false_alarms': 1}
                            for name, outcomes in (('base', base), ('candidate', candidate))}}
        rows = report.normal_groups({'split': data}, 'base')
        values = {(r['scope'], r['bin']): r for r in rows if r['configuration'] == 'candidate'}
        self.assertEqual(values[('all', 'all')]['new_normal_alarm_ids'], ['id:01'])
        self.assertEqual(values[('all', 'all')]['resolved_normal_alarm_ids'], ['id:02'])
        self.assertEqual(values[('all', 'all')]['normal_images'], 2)
        self.assertEqual(values[('hard', 'streak')]['normal_images'], 1)
        self.assertEqual(values[('hard', 'reflection')]['alarms'], 1)
        self.assertEqual(values[('hard', 'none')]['alarms'], 0)
        self.assertEqual(values[('input_clip_fraction', '(0,.1]')]['input_clip_fraction_median'], .05)
        data['ids'][0] = 'wrong-id'
        with self.assertRaisesRegex(ValueError, 'alignment'):
            report.normal_groups({'split': data}, 'base')


if __name__ == '__main__':
    unittest.main()
