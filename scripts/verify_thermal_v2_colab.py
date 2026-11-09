"""Run delivered upload/QA/CPU-smoke/compare/download cells offline with a shim.

GPU guard is compiled, not executed. Training cells are explicitly changed to
one CPU smoke epoch; comparison remains invalid and no full training is claimed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import types
import zipfile
from pathlib import Path


def verify(kit, attempt=1):
    import cv2
    import numpy as np
    import torch
    from IPython.display import display  # noqa: F401 -- fail fast on missing local display dependency

    kit=Path(kit).resolve()
    manifest=json.loads((kit/'package_manifest.json').read_text(encoding='utf-8'))
    sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    notebook=kit/'MAEK_v2_threeway_train_compare.ipynb'
    archive=kit/manifest['bundle']
    assert sha(notebook)==manifest['notebook_sha256']
    assert sha(archive)==manifest['bundle_sha256']
    content=json.loads(notebook.read_text(encoding='utf-8'))
    codes=[''.join(c['source']) for c in content['cells'] if c['cell_type']=='code']
    assert len(codes)==7
    assert len({c['id'] for c in content['cells']})==len(content['cells'])
    for index,code in enumerate(codes):
        compile(code,f'v2-notebook-cell-{index}','exec')
    if attempt < 1:
        raise ValueError('Attempt must be positive')
    scratch=kit/('verification' if attempt == 1 else f'verification-attempt-{attempt}')
    scratch.mkdir(exist_ok=False)
    workspace=scratch/'workspace'
    downloads=[]
    google=types.ModuleType('google')
    colab=types.ModuleType('google.colab')
    colab.files=types.SimpleNamespace(upload=lambda:{archive.name:archive.read_bytes()},
                                     download=lambda value:downloads.append(value))
    google.colab=colab
    sys.modules['google']=google
    sys.modules['google.colab']=colab
    context={'sys':sys,'subprocess':subprocess,'torch':torch,'np':np,'cv2':cv2}

    def run_cell(index,source=None):
        print(f'Offline notebook cell {index} start',flush=True)
        exec(compile(source or codes[index],f'offline-cell-{index}','exec'),context)  # noqa: S102
        print(f'Offline notebook cell {index} passed',flush=True)

    upload=codes[1].replace("Path('/content/maek_v2_threeway')",f'Path({str(workspace)!r})')
    upload=upload.replace("Path('/content/MAEK_v2_threeway_bundle.zip')",f'Path({str(scratch / archive.name)!r})')
    run_cell(1,upload)
    run_cell(2)
    export=codes[6].replace("Path('/content/MAEK_v2_threeway_results.zip')",
                           f'Path({str(scratch / "incomplete-results.zip")!r})')
    run_cell(6,export)
    with zipfile.ZipFile(downloads[-1]) as z:
        assert json.loads(z.read('result_manifest.json'))['complete'] is False
    for index in (3,4,5):
        source=codes[index].replace("'--device','cuda'","'--device','cpu','--smoke'")
        assert source!=codes[index]
        run_cell(index,source)
    export=codes[6].replace("Path('/content/MAEK_v2_threeway_results.zip')",
                           f'Path({str(scratch / "smoke-results.zip")!r})')
    run_cell(6,export)
    with zipfile.ZipFile(downloads[-1]) as z:
        assert z.testzip() is None
        results=json.loads(z.read('result_manifest.json'))
        assert results['complete'] is False
        assert not any(results['training_completed'].values())
        for name,digest in results['files'].items():
            assert hashlib.sha256(z.read(name)).hexdigest()==digest
    fine=json.loads((workspace/'runs/finetune/training.json').read_text())
    scratch_report=json.loads((workspace/'runs/scratch/training.json').read_text())
    assert fine['batch_plan_sha256']==scratch_report['batch_plan_sha256']
    assert fine['optimizer_steps']==scratch_report['optimizer_steps']==1
    assert fine['initialization_sha256']==manifest.get('baseline_sha256',sha(workspace/'baseline/best.pt'))
    assert scratch_report['initialization_sha256'] is None
    assert sha(workspace/'baseline/best.pt')==json.loads((workspace/'experiment_protocol.json').read_text())['baseline']['sha256']
    compared=json.loads((workspace/'comparison/metrics.json').read_text())
    assert compared['valid_comparison'] is False and compared['automatic_deployment'] is False
    report={'status':'passed','verification_attempt':attempt,'compiled_code_cells':7,'upload_and_all_file_hashes_verified':True,
        'independent_dataset_validation_executed':True,'train_registration_audit_executed':True,
        'both_cpu_smoke_cells_executed':True,'same_optimizer_steps_and_batch_plan':True,
        'baseline_unchanged':True,'comparison_smoke_cell_executed':True,
        'partial_and_smoke_download_cells_executed':True,'download_zip_crc_and_hashes':True,
        'full_training_completed':False,'gpu_guard_executed':False,'cuda_training_executed':False,
        'real_colab_ui_executed':False,'notebook_sha256':sha(notebook),'bundle_sha256':sha(archive),
        'script_sha256':sha(Path(__file__))}
    (kit/'notebook-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit',type=Path,required=True)
    parser.add_argument('--attempt',type=int,default=1)
    args=parser.parse_args()
    verify(args.kit,args.attempt)
