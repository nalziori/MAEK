"""Freeze and package the v2 baseline/finetune/scratch Colab experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import textwrap
import zipfile
from pathlib import Path

import numpy as np

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
from maek.thermal_registration_quality import DEFAULT_POLICY

DATA_NAMES=('manifest.json','protocol.json','index.jsonl','quality-index.jsonl','validation.json','evidence-ledger.json')
NEW_SOURCES=['maek/__init__.py','maek/thermal_observation_data.py','maek/thermal_observation_model.py',
    'maek/thermal_observation_eval.py','maek/thermal_registration_quality.py','maek/thermal_v2_comparison.py',
    'scripts/train_thermal_observation.py','scripts/train_thermal_observation_v2.py',
    'scripts/compare_thermal_observation_v2.py','scripts/audit_registration_quality_v2.py',
    'scripts/validate_thermal_evidence_dataset.py','scripts/build_thermal_v2_colab.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def cell(kind,source,index):
    value={'cell_type':kind,'id':f'maek-v2-{index:02d}','metadata':{},
           'source':textwrap.dedent(source).strip().splitlines(True)}
    if kind=='code':
        value.update(execution_count=None,outputs=[])
    return value


def freeze(data,baseline,out):
    manifest=json.loads((data/'manifest.json').read_text(encoding='utf-8'))
    validation=json.loads((data/'validation.json').read_text(encoding='utf-8'))
    if validation['status']!='passed' or manifest['field_validated']:
        raise ValueError('Requires validated synthetic v2')
    if sha(baseline)!='9d6a84170f4012f5fbe187e169ca0235466ee2170c5019d381353bd8cd4dba5f':
        raise ValueError('Expected verified user v1 baseline')
    sources=sorted(set(NEW_SOURCES)|set(manifest['source_hashes']))
    for name,digest in manifest['source_hashes'].items():
        if sha(REPO/name)!=digest:
            raise ValueError('Frozen dataset generator changed')
    protocol={'version':2,'scope':'synthetic_registered_thermal_change_segmentation','shape':[128,160],
        'baseline':{'sha256':sha(baseline),'original_threshold':.825,'original_training_epochs':30,
                    'policy':'preserve weights; recalibrate primary threshold on v2 dev; original point also reported'},
        'data_hashes':{name:sha(data/name) for name in DATA_NAMES},
        'source_hashes':{name:sha(REPO/name) for name in sources},
        'training':{'epochs':30,'batch_size':16,'seed':20261119,'learning_rate':.001,
                    'weight_decay':.0001,'max_seconds':1800,'device':'cuda'},
        'training_runs':2,'modes':['finetune','scratch'],
        'budget_meaning':'equal additional 30epochs; finetune has prior v1 training; no equal-total-compute claim',
        'registration_policy':dict(DEFAULT_POLICY),
        'registration_design_data':'procedural fixtures and v2 train only; no dev/test/stress tuning',
        'rule':{'method':'smoothed_signed_difference_3x3'},
        'evaluate':{'min_component_area':9,'false_alarm_min_scored_pixels':9,'connectivity':8,
            'score_comparator':'>','positive_hit_fraction':.3,'dev_max_false_alarm_frames':0,
            'model_thresholds':[float(x) for x in np.linspace(.05,.95,37)]+[.99,.999,'OFF'],
            'rule_thresholds':[float(x) for x in np.geomspace(.02,8,41)]+['OFF'],
            'selection_rank':['frame_hit_recall','pixel_iou','pixel_recall','higher_threshold'],
            'bootstrap_repeats':2000,'bootstrap_seed':20261120},
        'acceptance':{'min_valid_coverage':.9,'min_misregistration_rejection':.95,
            'zero_test_stress_false_alarms':True,'no_new_false_alarm_frames':True,
            'nondecreasing_frame_recall':True,'positive_iou_gain_ci_test_and_stress':True},
        'model_inputs':'measured registered pair only; asinh3channels; no audit fields',
        'holdout_policy':'freeze all operating points and one dev challenger before test/stress loads',
        'field_validated':False,'defect_training_eligible':False,'automatic_deployment':False,
        'retries':'Infrastructure failures only; fresh output; preserve failed artifacts; no score-driven retry'}
    out.mkdir(parents=True,exist_ok=True)
    path=out/'experiment_protocol.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=protocol:
        raise ValueError('Existing protocol differs; use a fresh output folder')
    save(path,protocol)
    return path,sources


def build(data,baseline,out,protocol_only=False):
    data,baseline,out=(Path(p).resolve() for p in (data,baseline,out))
    protocol,sources=freeze(data,baseline,out)
    if protocol_only:
        print(protocol)
        return
    paths=[(REPO/name,name) for name in sources]
    paths += [(p,'data/'+p.relative_to(data).as_posix()) for p in sorted(data.rglob('*')) if p.is_file()]
    paths += [(baseline,'baseline/best.pt'),(protocol,'experiment_protocol.json')]
    for name in ('training.json','history.csv'):
        paths.append((baseline.parent/name,'baseline/'+name))
    for name in ('thermal-role-contract.md','thermal-evidence-synthesis.md','thermal-v2-colab.md',
                 'field-inspection-development-plan.md'):
        paths.append((REPO/'docs'/name,'docs/'+name))
    bundle=out/'MAEK_v2_threeway_bundle.zip'
    hashes={name:sha(path) for path,name in paths}
    with zipfile.ZipFile(bundle,'x',allowZip64=True) as z:
        for path,name in paths:
            z.write(path,name,compress_type=zipfile.ZIP_STORED if path.suffix=='.npz' else zipfile.ZIP_DEFLATED)
        z.writestr('package-files.json',json.dumps(hashes,indent=2),compress_type=zipfile.ZIP_DEFLATED)
    bundle_sha=sha(bundle)
    entries=[]
    def add(kind,text):
        entries.append(cell(kind,text,len(entries)))
    add('markdown','''
    # MAEK v2: 기준선 보존 · 추가 학습 · 처음부터 학습
    합성 열적 관측 비교입니다. 균열/감육 확정이나 현장 검증이 아닙니다.
    GPU(T4 등) 런타임에서 위에서 아래로 실행합니다. 새 ZIP 한 개를 업로드하세요.
    기존 가중치 보존, 추가 학습30epoch, 처음 학습30epoch. dev 오경보0건 문턱을 고정한 뒤 test/stress를 평가합니다.
    정합 품질 검사는 모든 모델에 동일하게 선행합니다. 보류는 정상 판정이 아닙니다.
    ''')
    add('code','''
    import sys, subprocess, importlib.util
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('런타임 > 런타임 유형 변경 > GPU를 선택하고 다시 시작하세요. CPU 본학습은 금지합니다.')
    if importlib.util.find_spec('cv2') is None:
        subprocess.run([sys.executable,'-m','pip','install','opencv-python-headless==4.12.0.88'],check=True)
    import numpy as np, cv2
    print('GPU:',torch.cuda.get_device_name(0),'Torch:',torch.__version__,'NumPy:',np.__version__,'OpenCV:',cv2.__version__)
    ''')
    add('markdown','## 1. 새 v2 번들 업로드\n`MAEK_v2_threeway_bundle.zip`을 선택합니다. 기존 v1 ZIP과 결과 ZIP은 입력 파일이 아닙니다.')
    add('code',f'''
    import hashlib, json, zipfile, stat
    from pathlib import Path, PurePosixPath, PureWindowsPath
    from google.colab import files
    ROOT=Path('/content/maek_v2_threeway')
    if ROOT.exists():
        raise RuntimeError('기존 작업 폴더가 있습니다. 결과를 먼저 다운로드하고 새 런타임을 사용하세요.')
    uploaded=files.upload()
    matches=[(name,payload) for name,payload in uploaded.items() if hashlib.sha256(payload).hexdigest()=='{bundle_sha}']
    if len(matches)!=1:
        raise RuntimeError('제공된 v2 번들의 SHA256과 일치하는 파일 한 개가 필요합니다.')
    archive=Path('/content/MAEK_v2_threeway_bundle.zip')
    archive.write_bytes(matches[0][1])
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or z.testzip() is not None:
            raise RuntimeError('중복 경로나 손상된 ZIP입니다.')
        expected=json.loads(z.read('package-files.json'))
        if set(names)!=set(expected)|{{'package-files.json'}}:
            raise RuntimeError('번들 목록이 일치하지 않습니다.')
        for info in z.infolist():
            name=info.filename; part=PurePosixPath(name)
            if part.is_absolute() or '..' in part.parts or chr(92) in name or PureWindowsPath(name).drive or stat.S_ISLNK(info.external_attr>>16):
                raise RuntimeError('허용하지 않는 ZIP 경로입니다.')
            payload=z.read(name)
            if name in expected and hashlib.sha256(payload).hexdigest()!=expected[name]:
                raise RuntimeError('파일 해시가 일치하지 않습니다: '+name)
            dest=ROOT/name; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(payload)
    del uploaded,matches,payload
    sys.path.insert(0,str(ROOT))
    print('업로드·파일 해시 검사 완료:',ROOT)
    ''')
    add('markdown','## 2. 데이터 독립 검증 · 정합 품질 검사\n학습 세트로만 검사 동작과 보류율을 확인합니다. 정합 실패를 임의로 정상 입력으로 변경하지 마세요. 드리프트 검증은 별도 교정 정보가 필요합니다.')
    add('code','''
    def run_script(name,*args):
        subprocess.run([sys.executable,str(ROOT/'scripts'/name),*map(str,args)],cwd=ROOT,check=True)
    frozen=json.loads((ROOT/'experiment_protocol.json').read_text())
    for name,digest in frozen['data_hashes'].items():
        assert hashlib.sha256((ROOT/'data'/name).read_bytes()).hexdigest()==digest,name
    (ROOT/'quality').mkdir(exist_ok=True)
    run_script('validate_thermal_evidence_dataset.py','--dataset',ROOT/'data','--out',ROOT/'quality/data-validation-replay.json')
    run_script('audit_registration_quality_v2.py','--data',ROOT/'data','--protocol',ROOT/'experiment_protocol.json','--out',ROOT/'quality/train-registration.json')
    quality=json.loads((ROOT/'quality/train-registration.json').read_text())
    print('유효 입력 통과율:',quality['valid_pair_coverage'],'정합 오류 보류율:',quality['misregistration_rejection'])
    if quality['valid_pair_coverage'] < frozen['acceptance']['min_valid_coverage']:
        print('주의: 유효 입력 통과율 목표 미달입니다. 연구 비교는 계속하지만 현장 적용 준비가 완료된 것으로 해석할 수 없습니다.')
    print('보류 입력은 재촬영/검토 대상이며 필수 정밀검사를 삭제하지 않습니다.')
    ''')
    add('markdown','## 3. 기존 가중치에서 추가 학습30epoch\n기존 파일을 덮어쓰지 않습니다. 옵티마이저는 새로 시작합니다.')
    add('code','''
    run_script('train_thermal_observation_v2.py','--data',ROOT/'data','--baseline',ROOT/'baseline/best.pt',
        '--protocol',ROOT/'experiment_protocol.json','--mode','finetune','--out',ROOT/'runs/finetune','--device','cuda')
    ''')
    add('markdown','## 4. 무작위 초기화에서 학습30epoch\n추가 학습과 동일한 데이터·난수·배치·학습 설정입니다. 기존 모델의 과거 학습 비용은 별도입니다.')
    add('code','''
    run_script('train_thermal_observation_v2.py','--data',ROOT/'data','--baseline',ROOT/'baseline/best.pt',
        '--protocol',ROOT/'experiment_protocol.json','--mode','scratch','--out',ROOT/'runs/scratch','--device','cuda')
    ''')
    add('markdown','## 5. 동일 오경보 기준 비교\n세 모델 모두 동일 정합 검사와 dev 문턱 선택을 적용합니다. 기존0.825 문턱도 별도 행으로 보존합니다. test/stress에서 문턱을 다시 조정하지 않습니다.')
    add('code','''
    run_script('compare_thermal_observation_v2.py','--data',ROOT/'data','--baseline',ROOT/'baseline/best.pt',
        '--training-root',ROOT/'runs','--protocol',ROOT/'experiment_protocol.json','--out',ROOT/'comparison','--device','cuda')
    import csv
    from IPython.display import display
    rows=list(csv.DictReader((ROOT/'comparison/summary.csv').open()))
    try:
        import pandas as pd
        display(pd.DataFrame(rows))
    except ImportError:
        for row in rows: print(row)
    result=json.loads((ROOT/'comparison/metrics.json').read_text())
    print('dev에서 선택한 비교후보:',result['dev_selected_challenger'])
    print('기준선 대비 개선 조건 충족:',result['improvement_supported'])
    print('정합 검사:',result['registration_summary'])
    print('실측 균열 검출·현장 배치 승인이 아닙니다.')
    ''')
    add('markdown','''
    ## 6. 결과 다운로드 — 오류·시간초과가 났어도 이 셀 실행
    `MAEK_v2_threeway_results.zip`에 기준선, 두 가중치/학습 기록, 품질 검사, 비교 결과, 소스/프로토콜을 담습니다.
    complete=false는 미완료이며 성공 결과로 사용하면 안 됩니다. 자동 다운로드가 막히면 왼쪽 파일 패널의
    `/content/MAEK_v2_threeway_results.zip`을 우클릭해 다운로드하세요. 파일을 로컬에 저장한 뒤 경로를 알려주세요.
    ''')
    add('code','''
    import platform
    if 'ROOT' not in globals() or not ROOT.exists():
        raise RuntimeError('번들 업로드·압축 해제를 먼저 완료하세요.')
    def optional_json(path):
        try: return json.loads(path.read_text())
        except (OSError,ValueError): return {}
    training={mode:optional_json(ROOT/'runs'/mode/'training.json') for mode in ['finetune','scratch']}
    comparison=optional_json(ROOT/'comparison/metrics.json')
    artifacts=[]
    for folder in ['baseline','runs','comparison','quality','maek','scripts','docs']:
        if (ROOT/folder).exists():
            artifacts.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    artifacts.append(ROOT/'experiment_protocol.json')
    artifacts.extend(ROOT/'data'/name for name in ['manifest.json','protocol.json','index.jsonl','quality-index.jsonl','validation.json','evidence-ledger.json'])
    complete=all(r.get('training_completed') and not r.get('smoke_only') for r in training.values()) and comparison.get('valid_comparison') is True and comparison.get('status')=='completed'
    manifest={'complete':bool(complete),'training_completed':{m:bool(r.get('training_completed')) for m,r in training.items()},
        'comparison_completed':comparison.get('status')=='completed','python':platform.python_version(),
        'files':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}}
    result_zip=Path('/content/MAEK_v2_threeway_results.zip')
    with zipfile.ZipFile(result_zip,'w',zipfile.ZIP_DEFLATED) as z:
        for p in artifacts: z.write(p,p.relative_to(ROOT).as_posix())
        z.writestr('result_manifest.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(result_zip) as z: assert z.testzip() is None
    print('complete:',manifest['complete'],'ZIP:',result_zip,'SHA256:',hashlib.sha256(result_zip.read_bytes()).hexdigest())
    files.download(str(result_zip))
    ''')
    notebook=out/'MAEK_v2_threeway_train_compare.ipynb'
    save(notebook,{'nbformat':4,'nbformat_minor':5,'metadata':{
        'accelerator':'GPU','kernelspec':{'display_name':'Python3','language':'python','name':'python3'},
        'colab':{'name':notebook.name,'provenance':[]}},'cells':entries})
    with zipfile.ZipFile(bundle) as z:
        if z.testzip() is not None: raise ValueError('Bundle CRC failed')
        for name,digest in hashes.items():
            if hashlib.sha256(z.read(name)).hexdigest()!=digest: raise ValueError(name)
    save(out/'package_manifest.json',{'bundle':bundle.name,'bundle_sha256':bundle_sha,
        'bundle_bytes':bundle.stat().st_size,'file_count':len(hashes)+1,
        'notebook_sha256':sha(notebook),'protocol_sha256':sha(protocol),'crc_all_hashes_passed':True,
        'actual_training_performed':False,'field_validated':False})
    print(json.dumps({'notebook':str(notebook),'bundle':str(bundle),'bytes':bundle.stat().st_size}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('data','baseline','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--protocol-only',action='store_true')
    args=parser.parse_args()
    build(args.data,args.baseline,args.out,args.protocol_only)
