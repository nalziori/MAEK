"""Generate controlled thermal observability probes; NEVER a crack-training dataset."""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import platform
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maek.thermal_feasibility import controlled_case

VARIANTS = ['intact', 'internal_wall_loss_approximation',
            'reflection_without_wall_loss', 'unmodelled_crack_counterfactual']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate(out, seed):
    if out.exists():
        raise FileExistsError(f'Use a fresh output directory: {out}')
    out.mkdir(parents=True)
    rows, records, images, clean, supports, walls = [], [], [], [], [], []
    # Scenario grid, not a sample of actual steelworks conditions or prevalence.
    grid = itertools.product((0., 5., 30., 60.), (0., 50.), (.08, .8),
                             (10., 100.), (16., 45.))
    for group_index, (delta, insulation, emissivity, hi, kw) in enumerate(grid):
        for loss in (.1, .3, .6):
            params = {'bulk_c': 25. + delta, 'ambient_c': 25.,
                      'outer_diameter_mm': 114.3, 'wall_mm': 6.,
                      'insulation_mm': insulation, 'wall_k': kw,
                      'insulation_k': .045, 'h_inner': hi, 'h_outer': 15.,
                      'loss_fraction': loss, 'emissivity': emissivity,
                      'noise_sigma_apparent_c': .1, 'reflected_c': 10.,
                      'camera_emissivity': .95}
            result = controlled_case(params, seed=seed + group_index)
            case_id = f'probe{len(rows):04d}'
            row = {'case_id': case_id, 'base_scene_id': f'scene{group_index:03d}',
                   'bulk_minus_ambient_c': delta, **params,
                   **{k: v for k, v in result.items() if not isinstance(v, np.ndarray)}}
            for sigma in (.03, .1, .3):
                ratio = result['peak_wall_loss_delta_apparent_c'] / (2 ** .5 * sigma)
                row[f'noise_proxy_sigma_{sigma:g}'] = ratio
                row[f'proxy_ge_3sigma_{sigma:g}'] = ratio >= 3
            rows.append(row)
            records.append({'case_id': case_id, 'base_scene_id': row['base_scene_id'],
                'parameters': params, 'split_role': 'feasibility_only',
                'training_eligible': False, 'ndt_outcome': None,
                'variants': VARIANTS,
                'crack_physics': 'not_modelled; last variant copies intact exactly',
                'mask_semantics': 'perturbation_support, not visible-defect ground truth'})
            images.append(result['temperature_c'])
            clean.append(result['noiseless_temperature_c'])
            supports.append(result['perturbation_support'])
            walls.append(result['wall_mm_by_column'])
    with (out / 'cases.csv').open('x', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (out / 'lineage.jsonl').open('x', encoding='utf-8') as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
    np.savez_compressed(out / 'probes.npz', temperature_c=np.stack(images),
                        noiseless_temperature_c=np.stack(clean),
                        perturbation_support=np.stack(supports),
                        wall_mm_by_column=np.stack(walls),
                        case_ids=np.array([r['case_id'] for r in rows]),
                        variants=np.array(VARIANTS))
    ratios = np.array([r['noise_proxy_sigma_0.1'] for r in rows])
    summary = {
        'dataset_status': 'physics_sensitivity_prototype_not_training_ready',
        'training_eligible': False, 'purpose': 'audit signal observability before learning',
        'seed': seed, 'groups': group_index + 1, 'cases': len(rows),
        'images': len(rows) * len(VARIANTS), 'image_shape': [96, 128],
        'image_dtype': 'float32', 'image_unit': 'apparent Celsius',
        'variants': VARIANTS, 'shared_noise_within_group': True,
        'equal_temperature_cases': sum(r['bulk_minus_ambient_c'] == 0 for r in rows),
        'zero_wall_loss_signature_cases': sum(r['peak_wall_loss_delta_apparent_c'] == 0
                                            for r in rows),
        'identical_unmodelled_crack_controls': sum(r['counterfactual_crack_identical']
                                                 for r in rows),
        'delta_over_independent_noise_proxy_sigma_0.1': {
            'min': float(ratios.min()), 'median': float(np.median(ratios)),
            'max': float(ratios.max()), 'ge_3_count': int((ratios >= 3).sum())},
        'subgroups': {},
        'limits': [
            'Internal metal loss at fixed OD only; not external corrosion or cracks.',
            'Steady independent radial columns; no lateral spreading or transient mechanics.',
            'Assumed effective heat-transfer coefficients; no validated gas flow model.',
            'Broadband gray-body approximation; not spectral OGI or field-calibrated sensor.',
            'Synthetic reflection changes are controls, not a calibrated scene generator.',
            'Noise ratios are sensitivity proxies, NOT POD, classifier accuracy or sensor NETD.',
            'Same-noise pairs and repeated intact frames are intentional controls; no random split.',
            'No field data, paired NDT, supervised masks, or permission to claim crack prediction.',
        ],
        'equation_source': 'https://ocw.mit.edu/courses/2-051-introduction-to-heat-transfer-fall-2015/e32f70f7e00f34953447b606cea0421f_MIT2_051F15_EqnSheet_Q2_v3.pdf',
        'environment': {'python': platform.python_version(), 'numpy': np.__version__},
        'source_hashes': {str(p): sha(p) for p in
            (Path(__file__).resolve(), Path(__file__).resolve().parents[1]
             / 'maek/thermal_feasibility.py')},
        'artifact_hashes': {name: sha(out / name) for name in
                           ('cases.csv', 'lineage.jsonl', 'probes.npz')},
    }
    for insulation in (0., 50.):
        chosen = [r for r in rows if r['insulation_mm'] == insulation]
        summary['subgroups'][f'insulation_{insulation:g}mm'] = {
            'cases': len(chosen),
            'median_peak_delta_apparent_c': float(np.median(
                [r['peak_wall_loss_delta_apparent_c'] for r in chosen])),
            'ge_3sigma_proxy_count': sum(r['proxy_ge_3sigma_0.1'] for r in chosen),
        }
    with (out / 'manifest.json').open('x', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, allow_nan=False)
    card = f'''# Thermal feasibility probes

Status: **not training-ready**. {summary['groups']} controlled groups,
{summary['cases']} cases, {summary['images']} apparent-temperature images (float32).

Variants: intact / approximate internal wall loss / reflection with no wall loss /
unmodelled crack counterfactual (exact copy of intact). Perturbation support is not
a supervised visible-defect mask. No physical-location NDT outcomes are provided.

The model includes inner film, wall, insulation and outer effective heat transfer.
It omits lateral conduction, actual gas flow, fracture, transient loading and leaks.
Parameters and noise are sensitivity assumptions, not validated site/sensor values.
No direct conversion from sensitivity ratios to detection accuracy is justified.

Equal bulk/ambient temperature cases: {summary['equal_temperature_cases']}.
Zero wall-loss signature cases: {summary['zero_wall_loss_signature_cases']}.
Identical unmodelled-crack controls: {summary['identical_unmodelled_crack_controls']}.
For the assumed 0.1 C noise, cases exceeding a 3-sigma independent-pair proxy:
{summary['delta_over_independent_noise_proxy_sigma_0.1']['ge_3_count']}/{len(rows)}.
This is a grid count, not expected field prevalence or a performance score.

Use cases.csv for sensitivities, lineage.jsonl for group/parameter identity and
probes.npz for controlled images. All variants of each base_scene_id belong together.
Do not randomly split controls into training and validation or export them as YOLO
crack labels. New data must pass calibration/observability and label-alignment review
before any gas-pipe defect learning claim.
'''
    (out / 'DATA_CARD.md').write_text(card, encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('dataset_status', 'groups', 'cases',
        'images', 'zero_wall_loss_signature_cases', 'subgroups')}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20261108)
    args = parser.parse_args()
    generate(args.out, args.seed)


if __name__ == '__main__':
    main()
