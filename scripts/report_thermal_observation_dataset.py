"""Build data card and portable source/data archive after successful validation."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root):
    root = root.resolve()
    validation = json.loads((root / 'validation.json').read_text(encoding='utf-8'))
    smoke = json.loads((root / 'cpu-training-smoke.json').read_text(encoding='utf-8'))
    if validation['status'] != 'passed' or smoke['status'] != 'passed':
        raise ValueError('Independent validation and training compatibility must pass')
    for name in ('manifest', 'protocol', 'index'):
        suffix = 'jsonl' if name == 'index' else 'json'
        if sha(root / f'{name}.{suffix}') != validation[f'{name}_sha256']:
            raise ValueError('Stale validation')
    if sha(root / 'validation.json') != smoke['validation_sha256']:
        raise ValueError('Stale training smoke')
    support = validation['support_by_split_and_mechanism']
    lines = ['# MAEK 열 관측 변화 합성데이터 v1', '',
        '2026-11-08 생성. **검증된 합성 관측 변화 학습 과제용**이며 가스 배관 균열 판정용 정답은 아니다.', '',
        '- `training_eligible_scope`: `synthetic_registered_thermal_change_segmentation`',
        '- `field_validated=false`, `crack_training_eligible=false`',
        '- 독립 장면 224개, 기준/현재 영상 1,120쌍(입력 온도 영상 2,240개), 각 128×160 float32 °C.',
        '- 각 장면에 5개 조건. 같은 장면의 변형을 분할 경계에 걸치지 않는다.',
        '- 보온 유무·방사율·온도 구동력·잡음의 16조합을 모든 분할에서 교차.',
        '- 독립 센서 잡음, 고정 온도 단위, 잡음 없는 영상에서 관측 정답 계산.', '',
        '| 분할 | 장면 | 쌍 | 변화 양성 픽셀 | 판단 보류 픽셀 | 유효 센서 픽셀 |',
        '|---|---:|---:|---:|---:|---:|']
    for split, count in [('train', 128), ('dev', 32), ('test', 32), ('stress', 32)]:
        s = support[split]
        lines.append(f'| {split} | {count} | {s["samples"]} | {s["label1"]:,} | {s["ignore255"]:,} | {s["valid_fraction"]:.3%} |')
    lines += ['', '센서 유효성은 불량·포화 픽셀을 제외한 비율이다. 유효하더라도 약한 변화는 판단 보류다.', '',
        '## 원인별 실제 관측 양성 포함 쌍', '',
        '**탐지율이 아닌 정답 분포**다. 변화가 없는 라벨을 건강한 배관이라는 뜻으로 쓰지 않는다.', '',
        '| 합성 조건 | train | dev | test | stress |', '|---|---:|---:|---:|---:|']
    for mechanism in ['stable_repeat', 'wall_loss', 'external_transfer', 'reflection', 'emissivity_change']:
        values = [f'{support[f"{split}/{mechanism}"]["frames_with_positive"]}/{support[f"{split}/{mechanism}"]["samples"]}'
                  for split in ['train', 'dev', 'test', 'stress']]
        lines.append(f'| {mechanism} | ' + ' | '.join(values) + ' |')
    lines += ['', '## 실제 검증 결과', '',
        '- 입력 파일 SHA256·장면 분할·중복·원인/조건 교차 검사 통과.',
        '- 전체 저장 온도에서 0/1/255 라벨과 유효성 마스크 독립 재계산 일치.',
        '- 모든 잡음 시드를 재실행해 관측-깨끗한 영상 차이가 양자화 오차 범위에 드는지 확인.',
        f'- 최대 열해석 상대 잔차 {validation["solver_max_relative_residual"]:.3e}, 상대 에너지 오차 {validation["solver_max_relative_energy_error"]:.3e}.',
        f'- CPU 학습 입력 {smoke["input_shape"]}, 유한 손실 {smoke["loss_before"]:.6f}, 역전파 및 Adam 1회 갱신 통과.',
        '- 한 번의 역전파는 학습 완료·정확도·탑재 속도 측정이 아니다. 가중치는 저장하지 않았다.', '',
        '## 쉬운 합성 과제인지 확인한 개발 세트 규칙 기준선', '',
        '| 규칙 | 관측 변화 IoU | 변화 재현율 | 반복 촬영 쌍에서 픽셀 하나라도 오경보 |',
        '|---|---:|---:|---:|']
    for name, s in validation['dev_only_baselines'].items():
        lines.append(f'| {name} | {s["pixel_iou"]:.2%} | {s["pixel_recall"]:.2%} | {s["stable_frames_with_any_positive_pixel"]}/{s["stable_frames"]} |')
    lines += ['', '규칙에는 합성 카메라의 참 잡음 임계값이 제공된다. 영상만 보는 학습 모델과 공정한 성능 비교가 아니며 현장 성능도 아니다. 픽셀 하나라도 경보로 세는 진단은 실제 연결요소/검사 경보 정책과 다르다.', '',
        '**단순 평활 규칙도 높은 점수를 얻는 초기 과제다. 이 데이터만으로 신경망 채택이나 MAEK 완성을 주장하지 않는다.** test/stress의 예측 성능은 평가하지 않았다.', '',
        '## 학습 입력 및 정답', '',
        '`samples/*.npz`의 `reference_c`, `current_c`만 모델 입력으로 사용한다. 3채널은 기준 온도·현재 온도·두 영상 차이의 고정 asinh 변환이다. 제공 로더는 깨끗한 온도·원인·물성·두께를 입력으로 반환하지 않는다.', '',
        '`target`: 0=해상 가능한 변화 없음, 1=관측 변화, 255=약신호/포화/불량 픽셀. `CrossEntropyLoss(ignore_index=255)`를 사용한다. 반사·방사율 변화도 관측 변화이며 곧 결함이라는 뜻이 아니다.', '',
        '기준/현재 영상은 완벽하게 정합되고 공통 카메라 보정·안정된 운전 조건을 가진다고 가정한다. 기준 영상이 없으면 이 모델의 지원 범위 밖이다.', '',
        '## 생성 가정과 남은 검증', '',
        '- 정상상태 얇은 셸 근사, 원통 열저항+면내 전도, 펼친 직사각형 배관 표면.',
        '- 가정한 회색체 방사 모델과 온도 공간 PSF. 실제 센서 파장/거리/대기/3D 투영 보정 없음.',
        '- 방사율 변화는 관측 방사량만 바꾸며 열평형에 되먹임하지 않는다.',
        '- 감육은 내부 반경 변화의 근사. 균열 성장·응력·실제 누출·OGI 물리 없음.',
        '- 현장 빈도·재질·가스·카메라를 대표하는 통계 표본이 아닌 균형 실험 설계.',
        '- 미정합·운전 변화·센서 보정 드리프트 내성 미검증.',
        '- `inspection_path_fixtures.json`은 필수 검사 보존 요구사항이며 실제 통합 경로 검사 결과가 아니다.', '',
        '다음에는 dev에서 규칙과 작은 모델을 같은 입력·오경보 예산으로 비교한다. 다른 생성 모델과 영상 정합 오차를 추가할 때는 관측 불확실성을 함께 라벨링해야 한다. 이후 제어 시편 실험과 동일 위치 UT/두께/균열 결과를 확보해 위험정보+RGB 대비 열화상의 검사비 절감 효과를 검증해야 한다.', '',
        '## 재현 및 Colab 준비', '',
        'ZIP에는 data/와 필요한 maek/·scripts/ 소스를 함께 넣는다. Colab에서 ZIP을 풀고 같은 최상위 폴더에서 다음을 실행할 수 있다. 본격 학습은 이번에 실행하지 않았다.', '',
        '```bash', 'python scripts/validate_thermal_observation_dataset.py --root data',
        'python scripts/smoke_thermal_observation_training.py --data data --out fresh-smoke.json', '```', '',
        '필요 패키지는 numpy, torch, matplotlib(미리보기)이며 실제 검사 환경 버전은 cpu-training-smoke.json에 있다. 원본 데이터 재검증은 validation.json을 다시 작성하므로 기존 smoke의 검증 해시가 바뀔 수 있다. 새 smoke 보고서를 저장한다.', '',
        '생성 재현: `python scripts/generate_thermal_observation_dataset.py --out NEW_DIRECTORY --seed 20261108`. 같은 환경에서는 수치 재현을 확인할 수 있으나 압축 컨테이너 타임스탬프/라이브러리 버전 때문에 파일 바이트까지 동일하다고 보장하지 않는다.', '',
        '[검증 결과](validation.json) · [CPU 학습 경로 검사](cpu-training-smoke.json) · [프로토콜](protocol.json) · [미리보기](preview.png)', '',
        '![개발용 같은 장면의 5가지 관측 변화](preview.png)', '']
    (root / 'DATA_CARD.md').write_text('\n'.join(lines), encoding='utf-8')
    archive = root.parent / f'{root.name}-colab.zip'
    sources = ['maek/__init__.py', 'maek/thermal_feasibility.py', 'maek/thermal_surface_solver.py',
        'maek/thermal_observation_synth.py', 'maek/thermal_observation_data.py',
        'scripts/generate_thermal_observation_dataset.py', 'scripts/validate_thermal_observation_dataset.py',
        'scripts/smoke_thermal_observation_training.py', 'scripts/preview_thermal_observation_dataset.py',
        'docs/thermal-observation-training.md']
    files = [(p, 'data/' + p.relative_to(root).as_posix()) for p in sorted(root.rglob('*')) if p.is_file()]
    files += [(REPO / p, p) for p in sources]
    contents = {name: sha(path) for path, name in files}
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for path, name in files:
            z.write(path, name)
        z.writestr('package-files.json', json.dumps(contents, indent=2))
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError('Archive CRC failure')
        for name, expected in contents.items():
            if hashlib.sha256(z.read(name)).hexdigest() != expected:
                raise ValueError(f'Archive content mismatch: {name}')
    result = {'status': 'passed', 'archive': str(archive), 'bytes': archive.stat().st_size,
              'sha256': sha(archive), 'entries': len(contents) + 1, 'crc_verified': True,
              'all_entry_sha256_verified': True, 'data_card_sha256': sha(root / 'DATA_CARD.md')}
    (root.parent / f'{root.name}-package.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    build(parser.parse_args().root)
