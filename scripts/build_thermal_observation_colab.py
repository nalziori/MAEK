"""Build a self-contained manual Colab workflow without accessing a browser."""
from __future__ import annotations

import argparse
import hashlib
import json
import textwrap
import zipfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')


def freeze_protocol(data, out):
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'comparison_protocol.json'
    protocol = {
        'version': 1, 'scope': 'synthetic_registered_thermal_change_segmentation',
        'field_validated': False, 'crack_prediction': False,
        'data_hashes': {name: sha(data / name) for name in ['manifest.json', 'index.jsonl', 'protocol.json', 'validation.json']},
        'input_contract': 'Measured reference_c/current_c only; rules use Celsius arrays and model fixed invertible asinh channels. No true noise, clean images, geometry, mechanism or latent defect metadata.',
        'training': {'architecture': 'TinyUNet16_32_64', 'runs': 1, 'epochs': 30,
            'batch_size': 16, 'seed': 20261109, 'device': 'cuda', 'max_seconds': 1800,
            'learning_rate': .001, 'weight_decay': .0001, 'optimizer': 'AdamW',
            'scheduler': 'CosineAnnealingLR', 'class_weight_positive_cap': 10,
            'augmentation': 'shared horizontal/vertical flips, train only',
            'checkpoint_selection': 'minimum dev weighted CE; weights derived from train only',
            'retries': 'Infrastructure failures only; preserve failed outputs; no score-driven reruns'},
        'evaluate': {'min_component_area': 9, 'false_alarm_min_scored_pixels': 9,
            'connectivity': 8, 'score_comparator': '>', 'dev_max_false_alarm_frames': 0,
            'positive_hit_fraction': .3,
            'rule_thresholds': [*map(float, np.geomspace(.02, 8., 41)), 'OFF'],
            'model_thresholds': [*map(float, np.linspace(.05, .95, 37)), .99, .999, 'OFF'],
            'bootstrap_repeats': 2000, 'bootstrap_seed': 20261110,
            'rules': ['absolute_difference', 'smoothed_signed_difference_3x3'],
            'selection_rank': ['frame_hit_recall', 'pixel_iou', 'pixel_recall', 'higher_threshold'],
            'rule_tie_preference': 'smoothed_signed_difference_3x3',
            'no_change_definition': 'zero GT1 pixels and at least one GT0 pixel; not a healthy-pipe label',
            'false_alarm_definition': 'at least 9 total retained predicted GT0 pixels on a no-change frame',
            'ignore_definition': '255 ignored for scoring only; components formed without GT/validity masks',
            'holdout_policy': 'write selected.json before loading test/stress NPZ; thresholds never retuned on holdout',
            'ci_unit': 'base_scene_id groups; frame Wilson intervals nominal and do not correct clustering'},
        'acceptance': 'No automatic deployment. Report selected learned model and selected rule separately. Improvement supported only if test and stress have no extra FA frames, positive frame recall nondecreasing, and stress paired IoU difference 95% CI lower bound >0. One seed and synthetic labels are not field validation.',
    }
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != protocol:
            raise ValueError('Existing frozen protocol differs; use a new output directory')
    else:
        write_json(path, protocol)
    return path


def cell(kind, source):
    value = {'cell_type': kind, 'metadata': {}, 'source': textwrap.dedent(source).strip().splitlines(True)}
    if kind == 'code':
        value.update(execution_count=None, outputs=[])
    return value


def build(data, out, protocol_only=False, reuse_bundle=False):
    data, out = data.resolve(), out.resolve()
    protocol = freeze_protocol(data, out)
    if protocol_only:
        print(str(protocol))
        return
    sources = [
        'maek/__init__.py', 'maek/thermal_observation_data.py', 'maek/thermal_observation_model.py',
        'maek/thermal_observation_eval.py', 'maek/thermal_feasibility.py', 'maek/thermal_surface_solver.py',
        'maek/thermal_observation_synth.py', 'scripts/generate_thermal_observation_dataset.py',
        'scripts/validate_thermal_observation_dataset.py', 'scripts/train_thermal_observation.py',
        'scripts/compare_thermal_observation.py', 'docs/thermal-observation-training.md',
        'docs/thermal-observation-colab.md',
    ]
    bundle = out / 'MAEK_thermal_observation_training_bundle.zip'
    paths = [(REPO / name, name) for name in sources]
    paths += [(p, 'data/' + p.relative_to(data).as_posix()) for p in sorted(data.rglob('*')) if p.is_file()]
    paths += [(protocol, 'comparison_protocol.json')]
    hashes = {name: sha(path) for path, name in paths}
    if reuse_bundle:
        with zipfile.ZipFile(bundle) as z:
            if json.loads(z.read('package-files.json')) != hashes:
                raise ValueError('Existing bundle does not match current sources/data')
    else:
        with zipfile.ZipFile(bundle, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
            for path, name in paths:
                z.write(path, name)
            z.writestr('package-files.json', json.dumps(hashes, indent=2))
    bundle_sha = sha(bundle)
    upload_code = '''
        import hashlib, json, sys, zipfile
        from pathlib import Path
        from google.colab import files
        EXPECTED_SHA256 = "BUNDLE_SHA"
        EXPECTED_NAME = "MAEK_thermal_observation_training_bundle.zip"
        ROOT = Path('/content/maek_observation_run')
        if ROOT.exists():
            raise RuntimeError('작업 폴더가 이미 있습니다. 기존 결과를 먼저 다운로드하세요. 재학습하려면 새 런타임을 사용하세요.')
        uploaded = files.upload()
        matches = [(name, payload) for name, payload in uploaded.items()
                   if hashlib.sha256(payload).hexdigest() == EXPECTED_SHA256]
        if len(matches) != 1:
            raise RuntimeError('제공된 새 training_bundle.zip 한 개를 업로드하세요. 이전 colab.zip은 사용할 수 없습니다.')
        name, payload = matches[0]
        archive = Path('/content') / EXPECTED_NAME
        archive.write_bytes(payload)
        with zipfile.ZipFile(archive) as z:
            expected = json.loads(z.read('package-files.json'))
            assert set(z.namelist()) == set(expected) | {'package-files.json'}
            for entry, digest in expected.items():
                destination = (ROOT / entry).resolve()
                if not destination.is_relative_to(ROOT.resolve()):
                    raise ValueError('Unsafe archive path')
                content = z.read(entry)
                if hashlib.sha256(content).hexdigest() != digest:
                    raise ValueError('Bundle checksum mismatch: ' + entry)
            ROOT.mkdir()
            z.extractall(ROOT)
        del uploaded, matches, payload
        sys.path.insert(0, str(ROOT))
        print('1단계 완료: ZIP 및 전체 파일 해시 확인')
    '''.replace('BUNDLE_SHA', bundle_sha)
    cells = [
        cell('markdown', '''
        # MAEK 열 관측 변화: GPU 학습과 공정한 규칙 비교
        새 합성데이터 1,120쌍. **정합된 기준·현재 영상의 열 변화** 과제이며 균열·안전 판정이 아닙니다.

        먼저 **런타임 → 런타임 유형 변경 → T4 GPU(또는 사용 가능한 GPU)**를 선택하세요.
        아래 셀을 위에서부터 한 번씩 실행합니다. 업로드에는 이 노트북과 함께 제공된
        `MAEK_thermal_observation_training_bundle.zip`을 사용하세요.
        30epoch 한 번을 실행합니다. GPU를 못 받으면 조용히 CPU 학습으로 바뀌지 않고 중단합니다.
        ''') ,
        cell('code', '''
        import importlib.util, subprocess, sys
        # Colab의 CUDA 지원 torch는 유지합니다. 없으면 기본 GPU 런타임으로 다시 연결하세요.
        if importlib.util.find_spec('torch') is None:
            raise RuntimeError('PyTorch가 있는 Colab GPU 런타임이 필요합니다.')
        for module, package in [('numpy', 'numpy'), ('cv2', 'opencv-python-headless')]:
            if importlib.util.find_spec(module) is None:
                subprocess.run([sys.executable, '-m', 'pip', 'install', package], check=True)
        import torch, numpy as np, cv2
        if not torch.cuda.is_available():
            raise RuntimeError('GPU가 없습니다. 런타임 유형에서 GPU를 선택하고 다시 연결하세요.')
        print('GPU:', torch.cuda.get_device_name(0))
        print('torch:', torch.__version__, 'numpy:', np.__version__, 'opencv:', cv2.__version__)
        ''') ,
        cell('markdown', '## 1. 데이터·코드 ZIP 업로드 및 검사\n파일 선택 창에서 새 training_bundle.zip을 선택합니다. 업로드가 끝날 때까지 기다리세요.'),
        cell('code', upload_code),
        cell('code', '''
        import subprocess, sys, json, hashlib
        protocol = json.loads((ROOT / 'comparison_protocol.json').read_text())
        for name, expected in protocol['data_hashes'].items():
            assert hashlib.sha256((ROOT / 'data' / name).read_bytes()).hexdigest() == expected, name
        from maek.thermal_observation_data import ThermalObservationDataset
        # 메타데이터 검증만 수행. 시험 영상은 학습 단계에서 열지 않습니다.
        for split, count in [('train', 640), ('dev', 160), ('test', 160), ('stress', 160)]:
            assert len(ThermalObservationDataset(ROOT / 'data', split)) == count
        print('데이터 검증 및 분할 확인 완료: train640/dev160/test160/stress160')
        print('입력: 기준/현재 온도 영상만. 실제 잡음 크기·정답 위치·원인은 추론 입력에서 제외.')
        ''') ,
        cell('markdown', '''
        ## 2. Tiny U-Net 30epoch 학습
        학습용 640쌍으로 학습하고 개발용 160쌍의 손실로 best.pt를 선택합니다.
        시험·악조건 세트로 학습하거나 체크포인트를 고르지 않습니다.
        epoch 진행 상황이 출력됩니다. 30분 제한에 걸리면 불완전 결과로 남고 최종 비교를 막습니다.
        오류·시간 초과가 나도 마지막 다운로드 셀에서 가능한 결과를 먼저 저장할 수 있습니다.
        ''') ,
        cell('code', '''
        command = [sys.executable, '-u', str(ROOT / 'scripts/train_thermal_observation.py'),
                   '--data', str(ROOT / 'data'), '--out', str(ROOT / 'training'),
                   '--protocol', str(ROOT / 'comparison_protocol.json'), '--epochs', '30',
                   '--batch-size', '16', '--seed', '20261109', '--device', 'cuda',
                   '--max-seconds', '1800']
        subprocess.run(command, cwd=ROOT, check=True)
        training = json.loads((ROOT / 'training/training.json').read_text())
        if not training.get('training_completed'):
            raise RuntimeError('30epoch 학습이 완료되지 않았습니다. 결과 ZIP을 받아 원인을 확인하세요.')
        print('2단계 완료:', {k: training.get(k) for k in
              ['status', 'epochs_completed', 'best_epoch', 'best_dev_loss', 'gpu', 'elapsed_seconds']})
        ''') ,
        cell('markdown', '''
        ## 3. 동일 입력·오경보 기준으로 비교
        기준선은 단순 절대 온도차와 3×3 평활 후 절대 온도차입니다. 참 잡음 크기는 제공하지 않습니다.
        모든 방법에 같은 8연결·9픽셀 영역 필터를 적용한 뒤 255 정답은 점수 계산에서만 제외합니다.
        양성 정답이 없는 영상에서 GT0 픽셀을 총9개 이상 잘못 표시하면 오경보입니다.
        개발 세트 오경보0건을 만족하는 설정 중 관측 변화 영상 재현율(정답 영역30% 검출), IoU 순으로 고릅니다.
        선택을 파일에 먼저 저장한 뒤 시험·악조건 세트를 한 번 평가합니다. 시험 오경보가 늘어도 임계값을 다시 맞추지 않습니다.
        'OFF'가 선택되면 무검출 결과이며 성공으로 해석하지 않습니다.
        ''') ,
        cell('code', '''
        subprocess.run([sys.executable, '-u', str(ROOT / 'scripts/compare_thermal_observation.py'),
                        '--data', str(ROOT / 'data'), '--run', str(ROOT / 'training'),
                        '--out', str(ROOT / 'comparison'), '--protocol', str(ROOT / 'comparison_protocol.json'),
                        '--device', 'cuda'], cwd=ROOT, check=True)
        import csv, html
        from IPython.display import display, HTML
        columns = ['split', 'candidate', 'threshold', 'frame_hit_recall', 'pixel_iou',
                   'no_change_frame', 'false_alarm', 'false_alarm_rate']
        with (ROOT / 'comparison/summary.csv').open(newline='') as stream:
            records = list(csv.DictReader(stream))
        rows = [['분할', '방법', '임계값', '영상 재현율', '픽셀 IoU', '오경보 분모', '오경보 수', '오경보율']]
        for record in records:
            row = []
            for key in columns:
                value = record[key]
                if value and key in ['frame_hit_recall', 'pixel_iou', 'false_alarm_rate']:
                    value = f'{float(value):.2%}'
                row.append(value)
            rows.append(row)
        display(HTML('<table>' + ''.join('<tr>' + ''.join('<td>' + html.escape(v) + '</td>'
                     for v in row) + '</tr>' for row in rows) + '</table>'))
        print('3단계 완료. comparison 폴더의 지표·선택 설정·예측을 결과 ZIP에 포함합니다.')
        metrics = json.loads((ROOT / 'comparison/metrics.json').read_text())
        print('동결된 합성 개선 기준 충족:', metrics['improvement_supported'])
        print('현장 균열 탐지 성능 또는 자동 배포 승인으로 해석하지 않습니다.')
        ''') ,
        cell('markdown', '''
        ## 4. 결과 다운로드
        마지막 셀은 학습·비교 결과와 실행 코드, 프로토콜, 해시를 ZIP으로 저장하고 다운로드합니다.
        브라우저가 자동 다운로드를 막으면 왼쪽 **파일** 패널에서 `/content/MAEK_observation_results.zip`을 찾아
        **⋮ → 다운로드**를 누르세요. 전체 데이터는 결과 ZIP에 중복으로 넣지 않습니다.
        ZIP을 이 대화에 전달하거나 로컬 저장 경로를 알려주시면 결과를 검증할 수 있습니다.
        이 셀은 오류 이후에도 실행할 수 있으며, 미완료 결과는 `complete=false`로 표시됩니다.
        ''') ,
        cell('code', '''
        import hashlib, json, platform, zipfile
        from pathlib import Path
        from google.colab import files
        if 'ROOT' not in globals() or not ROOT.is_dir():
            raise RuntimeError('업로드·압축 해제를 먼저 완료하세요.')
        artifacts = []
        for folder in ['training', 'comparison', 'maek', 'scripts']:
            if (ROOT / folder).is_dir():
                artifacts += [p for p in (ROOT / folder).rglob('*')
                              if p.is_file() and '__pycache__' not in p.parts]
        artifacts += [ROOT / 'comparison_protocol.json']
        artifacts += [ROOT / 'data' / p for p in ['manifest.json', 'index.jsonl', 'protocol.json', 'validation.json']]
        training_path = ROOT / 'training/training.json'
        def optional_json(path):
            if not path.exists():
                return {}
            try:
                return json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                return {'read_error': str(exc)}
        trained = optional_json(training_path)
        metrics_path = ROOT / 'comparison/metrics.json'
        metrics = optional_json(metrics_path)
        complete = (bool(trained.get('training_completed')) and metrics.get('status') == 'completed'
                    and metrics.get('valid_comparison') is True)
        summary = {'complete': complete, 'training_completed': bool(trained.get('training_completed')),
                   'python': platform.python_version(), 'torch': str(torch.__version__),
                   'numpy': np.__version__, 'opencv': cv2.__version__,
                   'files': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}}
        archive = Path('/content/MAEK_observation_results.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in artifacts:
                z.write(path, path.relative_to(ROOT).as_posix())
            z.writestr('result_manifest.json', json.dumps(summary, indent=2))
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
        print('complete =', complete, 'bytes =', archive.stat().st_size)
        print('SHA256 =', hashlib.sha256(archive.read_bytes()).hexdigest())
        print('저장 위치:', archive)
        files.download(str(archive))
        ''') ,
    ]
    notebook = {'nbformat': 4, 'nbformat_minor': 5, 'metadata': {
        'colab': {'name': 'MAEK_thermal_observation_train_compare.ipynb', 'provenance': []},
        'kernelspec': {'display_name': 'Python 3', 'name': 'python3'},
        'language_info': {'name': 'python'}, 'accelerator': 'GPU'}, 'cells': cells}
    for i, c in enumerate(cells):
        c['id'] = f'maek-{i:02d}'
        if c['cell_type'] == 'code':
            compile(''.join(c['source']), f'cell_{i}', 'exec')
    write_json(out / 'MAEK_thermal_observation_train_compare.ipynb', notebook)
    (out / '실행안내.md').write_bytes((REPO / 'docs/thermal-observation-colab.md').read_bytes())
    with zipfile.ZipFile(bundle) as z:
        if z.testzip() is not None:
            raise ValueError('Bundle CRC error')
        for name, expected in hashes.items():
            if hashlib.sha256(z.read(name)).hexdigest() != expected:
                raise ValueError('Bundle content error: ' + name)
    write_json(out / 'package_manifest.json', {'bundle': bundle.name, 'bundle_sha256': bundle_sha,
        'bytes': bundle.stat().st_size, 'entries': len(hashes) + 1,
        'notebook_sha256': sha(out / 'MAEK_thermal_observation_train_compare.ipynb'),
        'protocol_sha256': sha(protocol), 'crc_and_all_file_hashes_verified': True,
        'gpu_training_executed_locally': False})
    print(json.dumps({'bundle': str(bundle), 'sha256': bundle_sha, 'bytes': bundle.stat().st_size}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--protocol-only', action='store_true')
    parser.add_argument('--reuse-bundle', action='store_true', help='Verify an existing unchanged bundle and rebuild notebook only')
    args = parser.parse_args()
    build(args.data, args.out, args.protocol_only, args.reuse_bundle)
