# 박성훈 UT 최종 공유 패키지

배관 균열·피팅을 **가상 초음파 파형**으로 평가한 코드, 동결 가중치와 결과 근거를 정리했습니다. 실제 배관 검사 성능이나 Jetson 실측 속도를 나타내지 않습니다.

## 무엇을 실행할 수 있나요?

| 구분 | 설계 | 제공 상태 |
|---|---|---|
| 최신 균열 | 사각빔 정합필터 + CA-CFAR + 32개 특징 MLP | 코드·가중치·문턱값·개별 판정·작은 파형 재생 제공 |
| 피팅 MLP | 수직 UT 보정·신호처리 + 소형 MLP 3개 앙상블 | 기존 PR #35·#36의 모델과 실행 의존성·예제 제공 |
| 피팅 노트북 | 수직 UT 1D-CNN, 저오경보 기준 | `notebooks/UT.ipynb` 원본과 저장 출력 제공. 최신 가중치·외부 스크립트가 없어 전체 재실행은 미완료 |

균열 MLP와 피팅 MLP는 입력 특징과 가중치가 다릅니다. 피팅 노트북 결과를 MLP 결과라고 부르지 않습니다.

## 시작하기

Python 3.10 이상을 사용합니다. CUDA/Jetson에서는 플랫폼에 맞는 PyTorch를 먼저 설치하세요.

```powershell
python -m pip install -r UT/requirements.txt
$env:OMP_NUM_THREADS='1'
python UT/verify_final.py
```

`verify_final.py`는 파일 SHA-256과 피팅 MLP 32개·균열 MLP 작은 예제의 점수·판정을 확인합니다. 새로운 학습이나 최종 성능 재평가가 아닙니다. 균열 예제에는 보관된 미탐·오경보 사례를 포함하므로 이 예제만으로 탐지률을 계산하지 않습니다.

과학 계산 의존성 없이 파일만 검사: `python UT/verify_final.py --manifest-only`.

균열 입력은 `rf(N,4096)`, `nominal_wall_mm(N)`, `nominal_angle_deg(N)`, `observed_temp_c(N)`입니다. 5 MHz 탐촉자, 100 MHz 샘플링, 16회 평균, 공칭 3~12 mm·45/60/70도 합성 조건을 사용합니다.

```powershell
python UT/crack_mlp/predict_mlp.py --input UT/examples/crack_mlp_ascan.npz --output crack_mlp_predictions.json --sampling-mhz 100 --probe-mhz 5 --n-avg 16
python UT/predict_ascan.py --verify-example
```

기존 출력은 덮어쓰지 않습니다. 품질·검사창 문제로 `followup_required`가 나온 결과는 정상으로 처리하지 않습니다.

## 최종 결과를 읽는 순서

1. [최종 결과와 검증 범위](docs/최종_균열_피팅_결과와한계.md)
2. [최신 균열 MLP](crack_mlp/README.md), `crack_mlp/run/results.json`, `audit.json`
3. [피팅 노트북 설명](notebooks/README.md), `reports/pit_notebook_saved_results.json`
4. [데이터 목록과 적용 범위](datasets/README.md), `datasets/registry.json`

균열 최종 평가: 조건별 균열 1,200개·정상 1,200개, 총 9,600개. 기본 악조건 탐지률 **1,195/1,200 = 99.583%**, 오경보 **0/1,200 = 0%**. 온도·굴절각·형상 오차 조건에서는 **1,191/1,200 = 99.25%**, 오경보 **1/1,200 = 0.083%**입니다. 모두 같은 생성기의 독립 시드 평가입니다.

피팅 노트북의 최신 저오경보 모델 저장 출력: shifted 탐지률 **95.475%**, 오경보 **2/4,000 = 0.05%**. 원시 개별 판정으로 재집계한 값이 아니며, 최신 피팅 가중치로 재생한 결과도 아닙니다.

## 파일 구성

| 경로 | 내용 |
|---|---|
| `crack_mlp/` | 최신 균열 MLP 학습·추론·감사 코드, 선택 가중치 5101과 다른 시드, 설정·결과 |
| `crack_cnn/crack_retraining_v4/` | MLP가 재사용하는 전처리·검사창·CFAR와 생성기 스냅샷. 최신 균열 판정기는 MLP |
| `normal_ut_reviewed_v1/`, `normal_ut_repair_v2/` | 피팅 MLP 가중치·정규화·보정·동결 문턱값·프로토콜 |
| `runtime/` | 피팅 재생에 필요한 MAEK 의존 코드·설정 스냅샷 |
| `notebooks/` | 사용자가 추가한 피팅 Colab 노트북 원본 |
| `examples/` | 작은 고정 파형과 기대 판정 |
| `datasets/` | 추가 데이터 전체 목록·해시·용도 |
| `reports/`, `docs/` | 결과 근거, 완료·미완료 설명 |
| `final_manifest.json` | 이번 GitHub 패키지 파일의 바이트 단위 SHA-256 |

## 보존과 재현

대용량 원본은 로컬 `C:/MAEK/UT/data`, `crack_mlp/run`, `crack_cnn/crack_retraining_v4/run`에 보존하며 Git에 중복 업로드하지 않습니다. 원시 데이터가 없는 GitHub 복제본에서는 작은 추론 예제를 실행할 수 있습니다. 전체 재학습·9,600개 재감사에는 원 학습/평가 NPZ가 추가로 필요합니다.

`train_mlp_gpu.py`는 당시 학습 코드입니다. 전체 데이터가 있는 별도 복사본에서 `--baseline`을 지정하고 `--smoke` 후 실행합니다. 기존 `run`과 `smoke_v2`를 덮어쓰지 않도록 새 폴더가 필요합니다. CUDA 없는 환경에서는 학습을 거절합니다.

`manifest.json`은 기존 피팅/이전 균열 예제 검증기가 읽는 호환용 목록으로 이번 포함 파일에 맞춰 갱신했습니다. 이전 목록은 `reports/legacy_package_manifest.json`에 보존했습니다. 이번 최종 공유 범위는 `final_manifest.json`으로 확인합니다. `.gitattributes`에서 UT 바이트를 보존해 Windows/Linux 줄바꿈 때문에 동결 해시가 바뀌지 않도록 합니다.

`ruff.toml`은 해시가 고정된 실험 스냅샷의 import 정렬·dict 표기 규칙만 파일별로 제외합니다. 원본 노트북은 반복 실행 셀을 가진 보관 자료라 실행 코드 lint에서 제외하고, 파일 해시·저장 결과와 재현 한계는 별도 테스트로 검사합니다. 그 외 Python 오류 검사는 유지합니다.
