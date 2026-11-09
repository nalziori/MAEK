# 열화상 v3 평가와 CPU 모델 측정

2026-11-07 구현. 원본 데이터 ZIP은 수정하지 않으며 학습·성능 측정은 분리한다.

## 현재 상태

저장된 온도 PNG를 직접 평가하는 로더, 클래스별 이미지 재현율·IoU·혼동행렬·오경보·Wilson 95% 구간, 독립 DR 선택과 최종 shifted 평가, YOLO/1D-CNN CPU 계측을 추가했다. 증기 후보는 기존 배경 픽셀에만 class 3을 추가하는 opt-in 규칙이며 기존 기본 탐지기는 바꾸지 않았다.

첫 배경 창/임계값 실험과 이후 증기 후보 모두 사전 선택 기준에 미달했다. 후보는 실험용이며 개선 성공·현장 적용 검증 완료로 해석하지 않는다. 두 번째 DR의 기준선 평균 이미지 재현율 0.6881/정상 오경보 0.3902에 비해 mild 후보는 0.7171/0.4634로, 오경보가 더 늘었다. 따라서 최종 선택은 baseline이다.

## 열화상 평가

프로젝트 루트에서 실행한다. output은 새 폴더여야 하며, select와 final 사이 코드·설정·데이터 해시가 바뀌면 final을 거부한다.

```powershell
.venv/Scripts/python.exe scripts/evaluate_thermal_v3.py --stage select --zip "../data/data-v3 (합성 데이터 최신)/maek-thermal.zip" --output "../outputs/maek-c/new-thermal-run"
.venv/Scripts/python.exe scripts/evaluate_thermal_v3.py --stage final --zip "../data/data-v3 (합성 데이터 최신)/maek-thermal.zip" --output "../outputs/maek-c/new-thermal-run"
```

- 선택: 별도 생성 DR 120장(seed 20261108), 기본 조건 val 188장으로 회귀 확인. 이 188장은 방법 선택에 사용된 회귀 검증셋이며 순수 최종 holdout이 아니다.
- 최종: 기본 val 188장과 shifted 전체 300장. shifted는 후보·임계값 선택에 사용하지 않는다. 이미 본 최종 결과로 다시 조정하면 새 독립 시험 데이터가 필요하다.
- hit: 클래스 정답 픽셀의 30% 이상을 같은 클래스로 예측한 이미지. 저장 데이터에 인스턴스 ID가 없어 **개별 결함 hit율이 아니다**. 클래스별 분모를 함께 기록한다.
- 배관 위치 마스크는 합성 job 정답으로 제공한다. 실제 영상에서 배관 위치 추정 성능은 포함하지 않는다.
- 기존 FP/img는 5×5 팽창한 예측 연결영역이 어떤 GT와도 겹치지 않을 때 센다. 클래스별 FP/img는 같은 클래스 GT와 겹치는지로 판단한다. 객체 매칭 precision은 아니다.
- Wilson 구간은 각 비율의 구간이며 전후 차이의 쌍체 신뢰구간은 아니다.
- `selection.json`, `final.json`, `thermal-performance.csv`에 설정·해시·원시 지표·분모·이미지별 hit 결과를 저장한다.

## CPU 모델 측정

기존 환경과 분리한 Python 3.12 환경을 사용했다. 정확한 직접 의존성은 `requirements-benchmark.txt`, 전체 실제 버전은 실행 산출물의 `benchmark-environment.txt`에 있다.

```powershell
py -3.12 -m venv .venv-benchmark
.venv-benchmark/Scripts/python.exe -m pip install torch==2.15.0+cpu torchvision==0.29.2+cpu --index-url https://download.pytorch.org/whl/cpu
.venv-benchmark/Scripts/python.exe -m pip install -r requirements-benchmark.txt
.venv-benchmark/Scripts/python.exe scripts/benchmark_models.py --data "../data/data-v3 (합성 데이터 최신)" --weights "../outputs/maek-c/models/yolov8n-seg.pt" --output "../outputs/maek-c/new-benchmark-run" --runs 3 --warmup 10 --repeats 100
```

가중치는 공식 Ultralytics `YOLO('yolov8n-seg.pt')` 다운로드 기능으로 준비한다. 결과에 파일 SHA-256을 기록한다. [Ultralytics Python API](https://docs.ultralytics.com/usage/python/)와 [segmentation 문서](https://docs.ultralytics.com/tasks/segment/)를 따른다.

- YOLOv8n-seg: COCO 사전학습 가중치. v3 카메라의 정렬된 첫 12개 RGB 이미지 순환. 320/640 입력. 열화상 정확도나 MAEK 학습 모델 결과가 아니다.
- Tiny1DCNN: Conv1d 1→16→32→64, global average pooling, 2출력. seed0 난수 가중치로 구조 비용만 측정한다. v3 UT angle 첫 12개, 길이 4096, float16→float32, 별도 정규화 없음.
- CPU float32, batch1, 1스레드. 모델·크기별 3개 독립 프로세스, 워밍업 10회, 측정 100회. 모델 연산만/전후처리 포함 경로를 구분한다. 두 경로 모두 ZIP 읽기·이미지 디코딩은 제외한다.
- 모델만 경로는 리사이즈된 텐서, YOLO 전체 경로는 PIL RGB를 predict에 전달한다. predictor 초기화·fusion은 측정 전에 끝낸다.
- Ultralytics가 CPU 초기화 중 스레드 수를 재설정하므로 초기 predict 후 요청한 스레드로 복원한다. 두 측정 후 실제 스레드 수를 검증하고 JSON의 `actual_torch_threads`에 남긴다. 초기 구현에서 이 복원이 없던 결과는 최종 표에서 제외했다.
- 처리량은 반복 횟수/실제 총시간이며 1000/p50 근사치와 별도 기록한다.
- 메모리는 Python·런타임·입력을 포함한 Windows working set(RSS)이다. 5ms 샘플링이므로 짧은 피크를 놓칠 수 있다. 2GiB/5fps는 가정 예산이며 실제 보드 성능을 보장하지 않는다.
- 실행별 JSON에는 전체 지연 샘플과 메모리 오류를 보존하고, `onboard-speed.csv`에 각 실행/측정 범위를 기록한다. 중간 실패 시 완료된 개별 JSON은 남긴다.

## 검증

```powershell
.venv/Scripts/python.exe -m pytest tests/test_thermal_dataset.py tests/test_thermal_rules.py tests/test_model_benchmark.py -q
.venv/Scripts/python.exe -m pytest tests/test_thermal.py tests/test_eval_onboard.py -q
.venv/Scripts/python.exe -m ruff check maek/thermal_dataset.py maek/thermal_rules.py maek/onboard_models.py scripts/evaluate_thermal_v3.py scripts/benchmark_models.py tests/test_thermal_dataset.py tests/test_thermal_rules.py tests/test_model_benchmark.py
```

새 모듈 부재 상태의 RED를 확인한 뒤 구현했다. 온도 복원/잘못된 클래스/30% 경계/빈 분모/오경보 구분/Wilson 경계/기존 라벨 보존/계측값 검증을 테스트한다. 모델 출력 구조 검사 실패는 중첩 텐서를 재귀 검사하도록 수정했고 실제 YOLO 출력을 확인했다.

현재 코랩은 필요하지 않다. YOLO 추가 학습을 수행할 때 GPU 환경을 검토하고, 그 가중치의 CPU 속도는 다시 로컬에서 측정한다. 실제 배관 데이터·탑재 보드·1D-CNN 정확도·성공한 열화상 개선안은 아직 검증되지 않았다.
