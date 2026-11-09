"""Verify the final UT handoff; replay frozen examples without training."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def verify_manifest():
    manifest = json.loads((ROOT / 'final_manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError(f'Missing or invalid package file: {name}')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f'Package file changed: {name}')
    return len(manifest['files'])


def replay_crack():
    import numpy as np
    import torch

    sys.path.insert(0, str(ROOT / 'crack_mlp'))
    from predict_mlp import FrozenMLP

    torch.set_num_threads(1)
    model = FrozenMLP()
    with np.load(ROOT / 'examples/crack_mlp_ascan.npz', allow_pickle=False) as data:
        result = model.predict(
            data['rf'], data['nominal_wall_mm'], data['nominal_angle_deg'],
            data['observed_temp_c'], sampling_mhz=100, probe_mhz=5,
            n_avg=16, origin='synthetic',
        )
        try:
            model.predict(
                data['rf'][:1], data['nominal_wall_mm'][:1], data['nominal_angle_deg'][:1],
                data['observed_temp_c'][:1], sampling_mhz=100, probe_mhz=5,
                n_avg=1, origin='synthetic',
            )
        except ValueError:
            pass
        else:
            raise AssertionError('Unsupported averaging was accepted')
    expected = json.loads((ROOT / 'examples/crack_mlp_expected.json').read_text())
    np.testing.assert_allclose(result['logits'], expected['logits'], rtol=3e-5, atol=3e-5)
    for key in ('gate', 'indication'):
        np.testing.assert_array_equal(result[key], expected[key])
    return {'count': len(expected['logits']),
            'max_logit_difference': float(np.max(np.abs(result['logits'] - expected['logits']))),
            'unsupported_averaging_rejected': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-only', action='store_true')
    args = parser.parse_args()
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
    os.environ.setdefault('MKL_NUM_THREADS', '1')
    report = {'files_checked': verify_manifest(), 'new_training': False}
    if not args.manifest_only:
        # Different runtime snapshots must not share the same maek module cache.
        subprocess.run([sys.executable, str(ROOT / 'predict_ascan.py'), '--verify-example'],
                       check=True, cwd=ROOT)
        report['pit_mlp_examples'] = 32
        report['crack_mlp'] = replay_crack()
        report['pit_notebook'] = 'saved_output_only_not_replayed'
    report['passed'] = True
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
