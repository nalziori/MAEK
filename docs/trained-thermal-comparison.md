# 학습 열화상 모델의 공통 지표 비교와 CPU 측정

`scripts/compare_trained_thermal.py`는 원본 v3 PNG·정답 마스크를 읽어 기존 규칙, 오경보 필터를 붙인 규칙, Colab 학습 YOLO11n-seg를 같은 지표로 평가한다. 새로운 데이터 생성이나 추가 학습은 수행하지 않는다.

`maek/thermal_learned.py`는 학습과 동일한 고정 −40~200°C → 회색 8비트 3채널 변환을 수행한다. CPU, FP32, imgsz320, confidence0.25, IoU0.7, retina_masks=True로 추론하며 원본 마스크 크기를 검사한다. 클래스0..2는 평가 클래스1..3으로 변환하고 겹치는 인스턴스는 confidence가 높은 쪽을 남긴다. 규칙 탐지기만 알려진 합성 배관 위치를 사용한다.

평가 데이터는 기본 조건 val188장과 shifted300장이다. val은 모델 선택에 사용됐고 shifted도 이미 분석한 데이터이므로 결과는 진단 비교다. 임계값을 조정하거나 현장 일반화 성능을 검증하는 절차가 아니다.

## 실행

저장소 루트 PowerShell 기준. `.venv-benchmark`에는 CPU PyTorch, Ultralytics, NumPy, Pillow, psutil, PyYAML이 필요하다. 의존성 버전은 `requirements-benchmark.txt`에 기록했다. 먼저 새 출력 폴더에 평가 전에 정한 `protocol.md`를 둔다. 재현 실행은 기존 프로토콜을 복사할 수 있다.

```powershell
$thermalArchive = '../data/data-v3 (합성 데이터 최신)/maek-thermal.zip'
$trainedWeights = '../outputs/maek-c/colab-training-20261107/best.pt'
$comparisonOut = '../outputs/maek-c/trained-comparison-reproduction'
New-Item -ItemType Directory -Path $comparisonOut -ErrorAction Stop
Copy-Item '../outputs/maek-c/trained-comparison-20261107-verified/protocol.md' "$comparisonOut/protocol.md"
& ./.venv-benchmark/Scripts/python.exe scripts/compare_trained_thermal.py --mode evaluate --archive $thermalArchive --weights $trainedWeights --out $comparisonOut
& ./.venv-benchmark/Scripts/python.exe scripts/compare_trained_thermal.py --mode benchmark --archive $thermalArchive --weights $trainedWeights --out $comparisonOut
```

두 명령을 순서대로 실행한다. 평가 중이나 CPU 벤치마크 중에는 다른 학습·추론 작업을 병렬로 실행하지 않는다. 벤치마크는 평가와 소스·가중치·데이터·프로토콜 해시가 같은지 확인한다. 기존 결과를 덮어쓰지 않는다.

## 지표와 산출물

- 이미지 재현율: 정답 클래스 픽셀 30% 이상을 같은 클래스로 예측한 이미지 비율. 개별 결함 재현율·YOLO mAP와 다르다.
- 정상 이미지 오경보율: 정상 이미지에 예측 클래스 픽셀이 하나라도 있으면 경보로 센다.
- 픽셀 IoU: 각 클래스 전체 TP/union. 변화 구간은 이미지 단위 paired bootstrap으로 구한다.
- `comparison.json`, `thermal-performance.csv`, `val-predictions.npz`, `shifted-predictions.npz`에 원시 결과·예측 마스크를 저장한다.
- CPU는 PyTorch intra/inter-op 및 OpenCV 각각1, batch1, FP32로 새 프로세스3회 실행한다. val12+shifted12 고정 표본을 순환하고 scope마다 warmup10회·측정100회를 수행한다.
- 모델 계산만의 시간은 실제 predictor가 만든 `(1,3,256,320)` 텐서로 측정한다. 전체 시간은 온도 배열 입력부터 RGB 변환·YOLO 추론·클래스 마스크 생성까지 포함한다. 파일 I/O, 모델 로드, 최초 초기화는 제외한다.
- `cpu-run-*.json`, `cpu-runs.json`, `cpu-speed.csv`에 원시 지연값과 메모리를 저장한다. RSS는 프로세스 전체 working set이며5ms샘플 최댓값이다. Windows 생애 peak_wset은 초기화까지 포함하므로 별도로 해석한다.

현재 Ultralytics의 AutoBackend는 원래 모델과 별도의 융합된 모델을 만들 수 있다. 모델 계산만 측정할 때도 실제 `predictor.model.backend.model`을 사용하고 객체 일치·FP32·스레드를 검사한다. 초기 융합 전 모델 측정은 최종 표에서 제외했다.

[2026-11-07 결과 보고서](../../outputs/maek-c/trained-comparison-20261107-verified/report.md)
