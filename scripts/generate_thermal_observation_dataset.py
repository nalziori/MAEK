"""Generate a fresh, auditable synthetic thermal-change training dataset."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maek.thermal_observation_synth import MECHANISMS, generate_scene


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def generate(out, seed=20261108):
    if out.exists():
        raise FileExistsError('Use a fresh dataset directory; never overwrite an evaluated dataset')
    out.mkdir(parents=True)
    (out / 'samples').mkdir()
    protocol = {'version': 1, 'task': 'synthetic_registered_thermal_change_segmentation', 'seed': seed,
        'splits': {'train': 128, 'dev': 32, 'test': 32, 'stress': 32}, 'mechanisms': MECHANISMS, 'shape': [128, 160],
        'labels': {'0': 'no resolved change, NOT healthy', '1': 'resolved apparent-temperature change',
                '255': 'uncertain, saturated or invalid: ignore'},
        'thresholds': 'low=max(sqrt(2)*noise_sigma_c,quantization_c); high=max(3*sqrt(2)*noise_sigma_c,2*quantization_c); delta<=low:0; delta>=high:1; else255',
        'prerequisites': ['registered reference/current pair', 'shared calibration and stable operating condition'],
        'limitations': ['assumed synthetic factors, no field prevalence', 'steady thin-shell approximate heat transfer',
                     'gray-body, not spectral OGI', 'unwrapped strip, no 3D scene projection',
                     'no transient crack growth or leakage physics', 'no registration/drift robustness claim'],
        'gates': ['independent label recomputation', 'hashes and scene split separation',
               '16 factorial cells in each split, all five interventions each scene',
               'stable_repeat zero positive labels', 'positive support and >50% valid pixels each split',
               'solver residual<=1e-8 and energy error<=1e-7'],
        'evaluation_policy': 'dev-only fixed baselines; test/stress integrity/support audit only; no tuning',
        'source_hashes': {name: sha(ROOT / name) for name in [
            'maek/thermal_feasibility.py', 'maek/thermal_surface_solver.py',
            'maek/thermal_observation_synth.py', 'scripts/generate_thermal_observation_dataset.py']}}
    write_json(out / 'protocol.json', protocol)  # Freeze before producing samples.
    rows, group_index = [], 0
    for split, count in protocol['splits'].items():
        for _ in range(count):
            for row, arrays in generate_scene(group_index, split, seed=seed):
                group = f'scene_{group_index:04d}'
                sample_id = f'{group}_{row["mechanism"]}'
                relative = f'samples/{sample_id}.npz'
                np.savez_compressed(out / relative, **arrays)
                rows.append(dict(sample_id=sample_id, base_scene_id=group, split=split,
                                 relative_path=relative, sha256=sha(out / relative), **row))
            group_index += 1
        print(f'{split}: {count} scenes / {count * len(MECHANISMS)} pairs generated', flush=True)
    (out / 'index.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    write_json(out / 'manifest.json', {'training_eligible_scope': protocol['task'],
        'field_validated': False, 'crack_training_eligible': False, 'sample_count': len(rows),
        'group_count': group_index, 'source_hashes': protocol['source_hashes'],
        'index_sha256': sha(out / 'index.jsonl'), 'protocol_sha256': sha(out / 'protocol.json'),
        'validation_required': True, 'eligibility': 'only after independent validation.json status passed'})
    write_json(out / 'inspection_path_fixtures.json', {'scope': 'requirements fixtures, NOT model training labels',
        'cases': [{'thermal': 'no_anomaly_observed', 'latent_defect': 'assumed present',
                    'required': 'preserve mandatory/high-risk NDT; thermal absence must not mark safe'},
               {'thermal': 'anomaly_observed', 'latent_defect': 'unknown',
                    'required': 'localize evidence; use risk/RGB/NDT to investigate cause'},
               {'thermal': 'missing_reference', 'latent_defect': 'unknown',
                    'required': 'unsupported for this paired model; preserve inspection path'}]})
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=20261108)
    args = parser.parse_args()
    generate(args.out, args.seed)
