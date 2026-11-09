"""Generate a NEW v2 dataset and source/parameter ledger, preserving all v1 data."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maek.thermal_evidence_synth import CELLS, MECHANISMS, QUALITY_CASES, generate_evidence_scene
from maek.thermal_radiometry import BandRadiometry

SCOPE = 'synthetic_registered_thermal_change_segmentation'
SOURCES = ['maek/thermal_evidence_synth.py', 'maek/thermal_radiative_surface.py',
           'maek/thermal_radiometry.py', 'maek/thermal_surface_solver.py',
           'maek/thermal_feasibility.py', 'maek/thermal_observation_synth.py',
           'scripts/generate_thermal_evidence_dataset.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def evidence_ledger(config, source_path):
    ledger = json.loads(source_path.read_text(encoding='utf-8'))
    ledger['parameters'] = {key: {'value': value,
        'status': 'published_band_endpoints_only' if key == 'band_um' else 'explicit_design_assumption',
        'source_ids': ['FLIR-A70'] if key == 'band_um' else [],
        'empirical_distribution': False,
        'applicability': 'generic synthetic camera/scenario, not measured field statistics'}
        for key, value in config.items()}
    ledger['equation_mapping'] = {
        'cylindrical_resistance': ['MIT-CYLINDER'], 'surface_radiation': ['MIT-RADIATION', 'NIST-SI'],
        'band_planck_radiance': ['NIST-PLANCK', 'NIST-SI'], 'camera_mixing': ['FLIR-FORMULA'],
        'calibration_and_psf_requirement': ['NIST-8098'],
        'passive_active_scope_boundary': ['NASA-ACTIVE', 'TWI-PASSIVE-ACTIVE']}
    ledger['formula_implementation_assumptions'] = [
        'Ideal flat7.5–14um spectral response; gray opaque surface; scalar band transmittance',
        'Thin shell + local radial insulation, no insulation lateral conduction',
        'Air equals isothermal enclosing-radiation temperature; no solar load',
        'Direction-dependent reflection perturbation is an isolated radiometric sensitivity test, not a solved BRDF/view-factor scene',
        'Orthographic camera, pipe axis in image plane, no endcaps/perspective or self-occlusion',
        'Independent Gaussian read noise in radiance; constant gain/offset/fixed pattern in valid pairs',
        'No measured sensor response, NETD distribution, material morphology or field prevalence']
    return ledger


def generate(out, config_path=ROOT / 'config/thermal-evidence-v2.json',
             source_path=ROOT / 'config/thermal-evidence-sources.json'):
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    if any(count < 24 or count % 24 for count in config['splits'].values()):
        raise ValueError('Each split needs a positive multiple of24 complete factorial groups')
    if out.exists():
        raise FileExistsError('Use a fresh output directory; never overwrite frozen evidence')
    out.mkdir(parents=True)
    (out / 'samples').mkdir()
    (out / 'quality-fixtures').mkdir()
    protocol = {'version': 2, 'task': SCOPE, 'config': config, 'cells': CELLS,
        'mechanisms': MECHANISMS, 'quality_cases': QUALITY_CASES, 'shape': config['shape'],
        'splits': config['splits'], 'source_hashes': {name: sha(ROOT / name) for name in SOURCES},
        'labels': {'0':'no resolved apparent change; NOT healthy',
                '1':'resolved apparent change; cause UNKNOWN',
                '255':'uncertain/saturated/invalid; exclude from segmentation'},
        'quality_separation': 'quality fixtures excluded from training index; all255 labels',
        'model_inputs': ['reference_c','current_c'],
        'audit_only': ['clean fields','latent wall thickness','pipe mask','cause','true noise','thresholds'],
        'target_definition': 'abs(clean_current-clean_reference)<=label_low:0; >=label_high:1; else255; invalid255',
        'frozen_gates': ['sample hashes/shapes/labels', 'full24cells per split',
                      'physical groups never cross splits', 'stable_repeat and zero-drive wall_loss have no positives',
                      'quality fixtures all255 and excluded', 'linear residual<=1e-8; energy<=1e-7; radiation<=1e-7',
                      'each split >50% valid pixels, positive support, stable-repeat support'],
        'limitations': ['synthetic only; no field validation', 'no calibrated defect or safety labels',
                     'steady reduced shell and generic camera; engineering distributions',
                     'same generator across splits; stress is not external validation'],
        'evaluation_policy': 'dev-only future tuning; test/stress integrity and support audit only'}
    write_json(out / 'protocol.json', protocol)
    write_json(out / 'evidence-ledger.json', evidence_ledger(config, Path(source_path)))
    rows, quality_rows, group_index = [], [], 0
    camera = BandRadiometry(band_um=tuple(config['band_um']))
    for split, count in config['splits'].items():
        for _ in range(count):
            group = f'evidence_scene_{group_index:04d}'
            for row, arrays in generate_evidence_scene(group_index, split, config, camera):
                eligible = row['segmentation_eligible']
                sample_id = f'{group}_{row["mechanism"]}'
                relative = f'{"samples" if eligible else "quality-fixtures"}/{sample_id}.npz'
                np.savez_compressed(out / relative, **arrays)
                item = dict(sample_id=sample_id, base_scene_id=group, split=split,
                            relative_path=relative, sha256=sha(out / relative), **row)
                (rows if eligible else quality_rows).append(item)
            group_index += 1
        print(f'{split}: {count} scenes, {count * 5} observation pairs, {count * 2} quality fixtures', flush=True)
    for name, data in [('index.jsonl', rows), ('quality-index.jsonl', quality_rows)]:
        (out / name).write_text(''.join(json.dumps(r) + '\n' for r in data), encoding='utf-8')
    write_json(out / 'manifest.json', {'training_eligible_scope': SCOPE,
        'field_validated': False, 'crack_training_eligible': False, 'provenance': 'synthetic',
        'sample_count': len(rows), 'quality_fixture_count': len(quality_rows), 'group_count': group_index,
        'source_hashes': protocol['source_hashes'], 'index_sha256': sha(out / 'index.jsonl'),
        'quality_index_sha256': sha(out / 'quality-index.jsonl'), 'protocol_sha256': sha(out / 'protocol.json'),
        'evidence_ledger_sha256': sha(out / 'evidence-ledger.json'), 'validation_required': True,
        'eligibility': 'synthetic observation task only, after independent validation passes'})
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/thermal-evidence-v2.json')
    args = parser.parse_args()
    generate(args.out, args.config)
