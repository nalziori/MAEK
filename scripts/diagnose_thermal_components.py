"""Inspect wet predictions on a development set; never reads the released shifted ZIP."""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from maek import params
from maek import thermal_render as tr
from maek.thermal_dataset import evaluate_arrays
from maek.thermal_filter import component_features
from scripts.evaluate_thermal_v3 import DR_VALUES


def samples(seed, count, condition="dr"):
    cfg = params.load_config()
    render_cfg = params.with_values(cfg, DR_VALUES) if condition == "dr" else cfg
    cond = "train" if condition == "dr" else condition
    for i, job in enumerate(tr.make_ir_jobs(render_cfg, count, seed, cond)):
        temp, truth, _ = tr._render(render_cfg, job, np.random.default_rng([seed, i]))
        raw = np.clip(np.rint((temp + 50) * 100), 0, 65535).astype(np.uint16)
        yield {"job": job, "temperature": raw.astype(np.float32) / 100 - 50,
               "mask": truth, "pipe": tr.pipe_mask(job)}


def diagnose(seed, count):
    cfg = params.load_config()
    records, counts, hard_counts = [], Counter(), defaultdict(Counter)
    for s in samples(seed, count):
        j, gt = s['job'], s['mask']
        pred = tr.detect_ir(cfg, s['temperature'], s['pipe'])
        negative = not gt.any()
        counts['images'] += 1
        counts['normal_images'] += int(negative)
        counts['normal_false_alarms'] += int(negative and pred.any())
        for hard in j['hard'] or ['none']:
            hard_counts[hard]['images'] += 1
            if negative:
                hard_counts[hard]['normal'] += 1
                hard_counts[hard]['false_alarm'] += int(pred.any())
        for y, x in tr._components(pred == 1, 1, 1):
            component = np.zeros_like(gt, bool)
            component[y, x] = True
            wet_overlap = int(np.count_nonzero(component & (gt == 1)))
            other_overlap = int(np.count_nonzero(component & (gt > 1)))
            records.append({"job_id": j['job_id'], "normal_image": bool(negative),
                            "hard": j['hard'] or ['none'], "wet_overlap_px": wet_overlap,
                            "label": 'wet_overlap' if wet_overlap else (
                                'other_overlap' if other_overlap else 'no_overlap'),
                            "features": component_features(s['temperature'], s['pipe'], component)})
    groups = defaultdict(list)
    for r in records:
        groups['normal_false_positive' if r['normal_image'] else r['label']].append(r['features'])
    summary = {}
    for name, rows in groups.items():
        summary[name] = {'n': len(rows)}
        for key in rows[0]:
            vals = [r[key] for r in rows if r[key] is not None]
            summary[name][key] = np.percentile(vals, [10, 50, 90]).tolist() if vals else None
    return {'seed': seed, 'count': count, 'role': 'development', 'counts': dict(counts),
            'hard_counts': dict(hard_counts), 'feature_percentiles_10_50_90': summary,
            'components': records}


def ablate(seed, count):
    cfg = params.load_config()
    render_cfg = params.with_values(cfg, DR_VALUES)
    jobs = tr.make_ir_jobs(render_cfg, count, seed, 'train')
    variants = {'baseline': {}, 'no_emissivity_variation': {'thermal.emissivity_variation': 0},
                'no_sensor_noise': {'thermal.netd_k': 0, 'thermal.fpn_k': 0},
                'no_explicit_distractors': {}}
    results, truth_reference = {}, []
    for name, changes in variants.items():
        current = params.with_values(render_cfg, changes)
        pairs = []
        for i, original in enumerate(jobs):
            job = copy.deepcopy(original)
            if name == 'no_explicit_distractors':
                job['distractors'] = []
            temp, truth, _ = tr._render(current, job, np.random.default_rng([seed, i]))
            if name == 'baseline':
                truth_reference.append(truth.copy())
            elif not np.array_equal(truth, truth_reference[i]):
                raise ValueError('Ablation changed the ground truth or random sequence')
            temp = np.clip(np.rint((temp + 50) * 100), 0, 65535).astype(np.float32) / 100 - 50
            pairs.append((truth, tr.detect_ir(cfg, temp, tr.pipe_mask(job))))
        results[name] = evaluate_arrays(pairs)
        print(name, results[name]['normal_false_alarms'], results[name]['normal_images'], flush=True)
    return {'seed': seed, 'count': count, 'role': 'development_ablation',
            'variants': variants, 'ground_truth_unchanged': True, 'results': results}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed', type=int, default=20261109)
    p.add_argument('--count', type=int, default=240)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--ablation', action='store_true')
    a = p.parse_args()
    if a.count <= 0:
        p.error('count must be positive')
    if a.out.exists():
        raise FileExistsError(a.out)
    d = ablate(a.seed, a.count) if a.ablation else diagnose(a.seed, a.count)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(d, indent=2, allow_nan=False), encoding='utf-8')
    if not a.ablation:
        print(json.dumps({k: v for k, v in d.items() if k != 'components'}, indent=2))


if __name__ == '__main__':
    main()
