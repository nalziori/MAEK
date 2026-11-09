# E4 부식 모델 재현

공식 결과는 **공개한 E4 가중치와 data-v3 평가셋**을 기준으로 합니다.
공개 가중치의 재평가와 처음부터의 재학습은 서로 다른 재현 작업입니다.

## 가중치와 기준 결과

- [E4 Release](https://github.com/nalziori/MAEK/releases/tag/e4-20261109)
- [best.pt 다운로드](https://github.com/nalziori/MAEK/releases/download/e4-20261109/best.pt) (7,040,692 bytes)
- SHA256: `5c836f8af95c1fbee2b7478e25536dd12a20c36cb03b297f3bbd12f7d74cd63a`
- YOLOv8n-seg, 입력 640, 클래스 `0=corrosion`, `1=cui_sign`, `2=leak_stain`.
- Release에 학습 인자, 원래 평가 요약, 패키지 버전, 체크섬과 재현 검증 결과를 함께 제공합니다.
- 체크포인트에 명시된 라이선스는 AGPL-3.0입니다. 원본 Ultralytics 출처와 라이선스를 유지합니다.

기준 결과는 data-v3 `camera/shifted` 400장, 렌더 seed 101, confidence 0.25, 전처리 없음입니다.
결함 영역의 30% 이상을 같은 클래스로 예측하면 hit입니다. **0.987은 mAP가 아닌 결함 단위 hit율**입니다.

| 클래스 | 결함 수 | hit율 | 오경보율 |
|---|---:|---:|---:|
| corrosion | 155 | 0.9870967742 | 0.0000000000 |
| cui_sign | 73 | 0.8356164384 | 0.0428134557 |
| leak_stain | 12 | 0.4166666667 | 0.0000000000 |

공식 평가 원본은 `e4-final-shifted-summary.csv/json`입니다. 원본 JSON의 `NaN`은 산출되지 않은 POD 값으로,
표준 JSON만 지원하는 도구에서는 CSV를 사용하세요. 원본의 과거 실행 경로는 현재 경로로 바꿔 실행합니다.
데이터 기준 커밋은 `data-v3`의 `f6a5b050923cb2c4eba0874d3a2ae39a2e3e7cfb`입니다.

## 실행 환경

완전한 과거 환경의 `pip freeze`는 확보하지 못했습니다. 확인된 근거를 구분합니다.

| 근거 | 확인된 값 |
|---|---|
| E4 시작 로그 | Python 3.13.16, Ultralytics 8.4.204, torch 2.14.1+cu130, Tesla T4 |
| 최종 체크포인트 | Ultralytics 8.4.208, 저장 시각 2026-11-09T01:45:38.765235+00:00 |
| 최종 학습 인자 | 50 epochs, 640 입력, batch 16, seed 0, deterministic=true, last.pt에서 resume |
| 고정 재현 패키지 | Ultralytics 8.4.208, torch 2.14.1, torchvision 0.29.1 |

`requirements-train.txt`는 핵심 AI 패키지를 고정한 실행 기준입니다. torchvision은 호환 재현용 버전이며
당시 버전이라고 주장하지 않습니다. 간접 의존성·드라이버·CUDA까지 복원하는 lockfile은 아닙니다.
시작 환경과 최종 저장 버전이 다르므로 이를 당시 모든 실행의 환경이라고 해석하지 않습니다.

새 가상환경에서 설치합니다. 아래는 CPU 예시입니다. GPU 학습은 할당된 외부 GPU 환경에서 실행하고,
CUDA wheel은 해당 환경에 맞게 선택하되 핵심 패키지 버전을 유지하고 실제 설치 버전을 기록합니다.

```bash
python3.13 -m venv .venv-train
source .venv-train/bin/activate
python -m pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-train.txt
python -m pip freeze > environment-evaluation.txt
```

Windows에서는 `py -3.13 -m venv .venv-train`과 `.venv-train\Scripts\Activate.ps1`을 사용합니다.
Jetson용 wheel과 TensorRT 변환은 별도 환경이며 위 설치 명령을 그대로 적용하지 않습니다.

## 공개 가중치로 평가하기

저장소 루트에서 실행합니다. 아래는 Bash 예시이며 GPU 없이도 평가할 수 있습니다.

```bash
mkdir -p data/e4
gh release download e4-20261109 --repo nalziori/MAEK --dir data/e4
(cd data/e4 && sha256sum -c SHA256SUMS)
git clone --branch data-v3 --single-branch https://github.com/nalziori/MAEK.git data/maek-data-v3
git -C data/maek-data-v3 checkout f6a5b050923cb2c4eba0874d3a2ae39a2e3e7cfb
(cd data/maek-data-v3 && sha256sum -c SHA256SUMS && cat maek-camera.zip.part* > maek-camera.zip)
python -m zipfile -e data/maek-data-v3/maek-camera.zip data/release
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 python scripts/eval_camera_seg.py \
  --data data/release/camera/shifted --seed 101 --method yolo \
  --weights data/e4/best.pt --conf 0.25 --imgsz 640 --pre none --device cpu \
  --out data/test-artifacts/e4-reproduction
```

PowerShell의 체크섬 확인은 `Get-FileHash data/e4/best.pt -Algorithm SHA256`을 사용합니다.
단일 스레드는 `$env:OMP_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'; $env:OPENBLAS_NUM_THREADS='1'`로 설정합니다.
평가 스크립트가 저장 마스크와 재생성 마스크의 일치를 확인하므로 seed나 데이터 버전이 다르면 실패합니다.
결과 CSV를 위 기준과 비교하고 차이가 있으면 환경·데이터·가중치 해시를 함께 보고합니다.
일치하도록 confidence나 전처리를 평가셋에 맞춰 재조정하지 않습니다.
Release의 `environment-evaluation-cpu.txt`는 이번 Windows CPU 검증 환경의 전체 패키지 목록으로,
원래 Colab 학습 환경의 기록과 구분합니다.

## 재학습의 한계

E4는 21 epoch 부근에 런타임을 바꿔 이어서 학습했다는 팀 기록이 있고, 최종 인자에도 resume 경로가 남아 있습니다.
공개 `best.pt`는 추론용 체크포인트로 epoch=-1이며, optimizer 상태를 포함한 완전한 재개 지점이 아닙니다.
처음부터 학습하는 명령은 [결과 문서](results.md)를 참고하되 당시 중단·재개 과정의 비트 단위 복원은 아닙니다.

GPU 종류(T4/RTX 4090), 라이브러리 버전, 학습 재개 이력에 따라 재학습 결과는 달라질 수 있습니다.
seed와 deterministic 옵션을 고정해도 서로 다른 플랫폼·버전 간 완전한 재현은 보장되지 않습니다.
[PyTorch 재현성 문서](https://docs.pytorch.org/docs/2.15/notes/randomness.html)도 이 한계를 설명합니다.
재학습 변동 폭은 반복 학습 전에는 수치로 약속하지 않습니다. 공식 표는 첨부 가중치의 원래 평가 결과입니다.

## 실제 사진 데이터 받기

사용한 외부 데이터는 **Failure의 Corrosion Instance Segmentation, version 3**입니다.

1. [프로젝트 페이지](https://universe.roboflow.com/failure-sjoo6/corrosion-instance-segmentation-sfcpc-1yuxj)에서
   Dataset의 **version 3**을 선택합니다. 최신 버전으로 임의 변경하지 않습니다.
2. 필요한 경우 Roboflow 계정으로 로그인하고 **YOLOv8 instance segmentation** 형식으로 내려받습니다.
   API 방식은 화면의 version 3 다운로드 코드를 사용하되 API key를 저장소·발표 자료에 넣지 않습니다.
3. 원본 `train/valid/test` 분할을 유지합니다. 이 실험의 학습은 1,442장, 최종 test는 205장입니다.
   개수가 다르면 데이터 버전·내보내기 조건을 확인합니다.
4. `python scripts/prep_real_finetune.py --src Corrosion-Instance-Segmentation-3 --out data/rc --seed 0`으로
   클래스들을 `corrosion=0`으로 통합하고 50장·200장·전체 학습 목록을 만듭니다. test는 학습에 넣지 않습니다.

공식 페이지의 라이선스는 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)입니다.
출처: Failure, *Corrosion Instance Segmentation Dataset*, Roboflow Universe, version 3.
원본 이미지 재배포는 이번 Release에 포함하지 않습니다. 재배포 시 원저자·원본 URL·라이선스를 표시하고,
클래스 통합·부분집합 구성 등 변경 사항도 표시합니다. 외부 서비스의 삭제·접근 정책 변경 가능성은 남습니다.

실사 미세조정은 조건당 1회입니다. 50장 조건의 약 +0.09 차이는 잠정 관측이며,
여러 시드에서 반복 검증한 개선 폭이나 통계적으로 확정된 우위가 아닙니다.
