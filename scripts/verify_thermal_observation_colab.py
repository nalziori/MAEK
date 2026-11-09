"""Offline check of delivered notebook upload/metadata/download cells.

Uses a local upload/download shim and redirects /content to a fresh workspace.
It does not execute the GPU guard, full training, or real holdout predictions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import types
import zipfile
from pathlib import Path


def verify(kit, attempt=1):
    import cv2
    import numpy as np
    import torch

    kit = kit.resolve()
    notebook_path = kit / 'MAEK_thermal_observation_train_compare.ipynb'
    notebook = json.loads(notebook_path.read_text(encoding='utf-8'))
    package = json.loads((kit / 'package_manifest.json').read_text(encoding='utf-8'))
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    assert sha(notebook_path) == package['notebook_sha256']
    archive = kit / package['bundle']
    assert sha(archive) == package['bundle_sha256']
    codes = [''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code']
    for i, source in enumerate(codes):
        compile(source, f'cell_{i}', 'exec')
    assert len(codes) == 6 and len({c['id'] for c in notebook['cells']}) == len(notebook['cells'])
    if attempt < 1:
        raise ValueError('Attempt must be positive')
    scratch = kit / 'verification' / f'notebook-cells-{attempt}'
    scratch.mkdir(parents=True, exist_ok=False)
    workspace = scratch / 'portable-workspace'
    downloads = []
    files = types.SimpleNamespace(upload=lambda: {archive.name: archive.read_bytes()},
                                  download=lambda path: downloads.append(str(path)))
    google = types.ModuleType('google')
    colab = types.ModuleType('google.colab')
    colab.files = files
    google.colab = colab
    sys.modules['google'] = google
    sys.modules['google.colab'] = colab
    context = {'torch': torch, 'np': np, 'cv2': cv2}
    upload = codes[1].replace("Path('/content/maek_observation_run')", f'Path({str(workspace)!r})')
    upload = upload.replace("Path('/content')", f'Path({str(scratch)!r})')
    exec(compile(upload, 'upload-cell-local-path', 'exec'), context)  # noqa: S102 - own hash-checked notebook
    exec(compile(codes[2], 'metadata-cell', 'exec'), context)  # noqa: S102 - own hash-checked notebook
    download = codes[5].replace("Path('/content/MAEK_observation_results.zip')",
                                f'Path({str(scratch / "incomplete-results-fixture.zip")!r})')
    exec(compile(download, 'download-cell-local-path', 'exec'), context)  # noqa: S102 - own hash-checked notebook
    assert len(downloads) == 1
    with zipfile.ZipFile(downloads[0]) as z:
        assert z.testzip() is None
        result = json.loads(z.read('result_manifest.json'))
        assert result['complete'] is False and result['training_completed'] is False
        for name, expected in result['files'].items():
            assert hashlib.sha256(z.read(name)).hexdigest() == expected
    # Imported loader must come from the extracted delivery, not the repository.
    import maek.thermal_observation_data as loader

    assert Path(loader.__file__).resolve().is_relative_to(workspace)
    result = {'status': 'passed', 'code_cells_compiled': len(codes),
              'upload_hash_verification_and_extraction': True, 'portable_loader_metadata_checks': True,
              'incomplete_result_download_cell_executed': True, 'result_zip_crc_and_hashes': True,
              'gpu_guard_executed': False, 'gpu_training_executed': False,
              'real_holdout_prediction_executed': False,
              'limitations': 'Colab upload/download APIs locally simulated; CUDA/full training not executed.',
              'notebook_sha256': sha(notebook_path), 'bundle_sha256': sha(archive)}
    (kit / 'notebook-verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--attempt', type=int, default=1)
    args = parser.parse_args()
    verify(args.kit, args.attempt)
