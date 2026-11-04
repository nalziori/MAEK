# 3대 기능 베이스라인 평가 결과

모든 수치는 **시뮬레이터 합성 데이터**에서 고정 시드(`--seed 0`)로 얻은 값이며, 실제 현장 데이터가 아닙니다.
아래 구현은 모두 **고전(규칙 기반) 베이스라인**이고, 해커톤에서 학습 모델로 개선할 출발점입니다.

## 재현 명령

```bash
export OMP_NUM_THREADS=1
python -m maek evaluate --out data/eval            # 이 문서의 표 (이미지 300장 x 2조건, UT 3000개 x 2조건, 전략 10회)
python -m maek onboard  --out data/eval            # docs/onboard-resources.md
python -m maek params-table --write                # docs/params.md
```

- 크기 설정은 `config/default.yaml`의 `eval.*` (`n_camera=300`, `n_ut=3000`, 이미지 640 px, 모두 `assumption: true`).
- 결과 파일: `data/eval/camera_metrics.csv`, `ut_metrics.csv`, `pod.csv`, `strategy_crack.csv`, `results_tables.md`.
- 소요 시간: 약 3분 30초 (4코어 CPU, 단일 스레드 설정).

## 평가 방식

- **train / shifted**: 같은 시뮬레이터에서 조건만 다르게 만든 두 데이터셋입니다.
  - 카메라 shifted: 조명 0.25~0.6배(어두움), 분진 0.3~0.7, 증기 0.3~0.8, 블러 1.5~3.5 px, 센서 노이즈 0.03~0.08
    (train은 0.5~1.5배, 0~0.4, 0~0.5, 0~2 px, 0~0.04). `camera.shifted_*` 파라미터.
  - UT shifted: 온도 100~175 C(고온 배관), 접촉 0.3~0.7(불량 접촉), 노이즈 3배 (`ut.dataset.shifted_*`).
  - 온도 보정: 분석은 실제 온도가 아니라 **측정 온도 = 실제 + 오차**로 음속을 보정합니다. 오차 표준편차는 train 2 C, shifted 15 C
    (`ut.dataset.*_temp_meas_error_c`, 가정값). `ut.temp_compensation: none`이면 20 C로 가정해 보정하지 않습니다.
  - 베이스라인의 임계값은 두 조건 모두에서 같게 고정했으며 shifted로 재조정하지 않았습니다.
- **① 부식 분할기** (`maek/camera/segment.py`): 평균 밝기 정규화 후 HSV에서 색상 5~40도, 채도 >= 0.35, 명도 >= 0.12를
  녹으로 판정하고 3x3 침식-팽창으로 잡음 제거. 클래스는 corrosion(1)만 평가합니다.
  - 픽셀 IoU: 전체 이미지 합산(교집합 / 합집합). 이미지 검출: 예측 30 px 이상. 오경보: 정답에 부식 픽셀이 없는데 검출.
  - 결함 단위 hit: 결함 위치 주변 정답 픽셀의 30% 이상이 예측되면 hit. 크기는 결함 면적(cm2).
- **② 균열**: 사각 UT 코너트랩 에코 게이트 검출(`ut.detect_crack`). 크기는 균열 높이(mm).
- **③ 두께**: 직진 UT 뒷면 에코 열의 간격(`ut.estimate_thickness`)으로 공칭 두께를 추정해 MAE와 +-0.1/+-0.5 mm 이내 비율을 봅니다.
  피팅이 있어도 벽 두께를 읽도록 에코 열 간격을 점수화합니다(피팅 깊이는 `ut.min_thickness`가 따로 보고).
  피트 검출은 `ut.min_thickness`가 공칭 두께보다 0.3 mm(`eval.pit_margin_mm`) 이상 얇게 나오면 hit, 크기는 피트 깊이(mm).
- **POD**: `maek.pod`의 로지스틱 모델(ln 크기)을 hit/miss에 최대우도로 적합, a90 = POD 90% 크기.
  대괄호 안은 부트스트랩 300회의 95% 백분위수(a90/95 근사, 일측 상한).

## 결과

**① 부식 (HSV 임계값 분할)**

| 지표 | train | shifted |
|---|---|---|
| 픽셀 IoU | 0.823 | 0.262 |
| 이미지 검출률 | 1.000 | 0.764 |
| 오경보율 | 0.000 | 0.021 |
| 결함 단위 hit율 | 0.991 | 0.311 |
| a90 [a90/95] (cm2) | 0.61 [2.88] | 도달 못함(a90 > 시험 범위 최대 117.1) |

**② 균열 (사각 UT 게이트 검출)**

| 지표 | train | shifted |
|---|---|---|
| 검출률 | 1.000 | 0.912 |
| 오경보율 | 0.000 | 0.000 |
| a90 [a90/95] (균열 높이 mm) | 전부 검출(a90 < 0.25) | 1.22 [1.34] |

**③ 두께 (직진 UT 에코 간격 / 피트 최소 두께)**

| 지표 | train | shifted |
|---|---|---|
| MAE (mm) | 0.003 | 0.434 |
| +-0.1 mm 이내 비율 | 1.000 | 0.886 |
| +-0.5 mm 이내 비율 | 1.000 | 0.899 |
| 피트 검출률 | 0.924 | 0.045 |
| 피트 오경보율 | 0.000 | 0.000 |
| 피트 a90 [a90/95] (깊이 mm) | 1.48 [1.67] | 도달 못함(a90 > 시험 범위 최대 7.1) |

**전략 비교: 치명 균열 검출률**

| 전략 | 검출률 | 평균 UT 점 수 |
|---|---|---|
| 기준(고정 CML) | 0.000 | 3821 |
| AI 트리아지, 기존(random) | 0.027 | 2389 |
| AI 트리아지, 위험순위(risk_ranked) | 0.149 | 3031 |

POD 표기: 숫자는 a90 [a90/95]. "전부 검출"은 모든 결함을 맞혀 로지스틱 적합이 발산하므로 a90이 가장 작은 시험 크기보다 작다는 뜻만 말할 수 있고,
"도달 못함"은 시험한 크기 범위 안에서 POD가 90%에 이르지 못한다는 뜻입니다.

## 전체 점검 전략 비교

`python scripts/produce_data.py`의 `strategy/compare.csv` (100 km x 20회 평균, 시드 1).

| 지표 | 기존 방식 | AI 선별 방식 |
|---|---|---|
| 위험 결함 발견율 | 0.191 | 0.504 |
| 외부 부식 | 0.504 | 0.864 |
| CUI | 0.234 | 0.421 |
| 유동가속부식 감육 | 0.023 | 0.614 |
| 균열 | 0.000 | 0.169 |
| 내부 피팅 | 0.033 | 0.000 |
| 놓친 고위험 위험 결함 | 39.6 | 27.5 |
| 초음파 측정 지점 | 3,823 | 3,016 |
| 비계 설치 | 1,152 | 0 |
| 비용 비율 (AI / 기존) | | 0.22 (단가 x0.5~x1.5에서 0.17~0.33) |

- 사람 점검도 CUI의 보온재 외장 얼룩을 볼 수 있게 고친 뒤 기존 방식의 CUI 발견율은 0.02 -> 0.23이 됐습니다.
- 내부 피팅은 겉에 징후가 없어 AI 선별 방식이 하나도 찾지 못합니다. 고위험 위치 초음파에 피팅을 넣는 것이 다음 개선 과제입니다.
- 비용 단가는 모두 가정값입니다.

## 해석과 한계 (솔직한 메모)

- **train -> shifted 하락이 큽니다.** ① 픽셀 IoU 0.82 -> 0.26, 결함 단위 hit율 0.99 -> 0.31, 이미지 검출률 1.00 -> 0.76.
  어둡고 뿌연 영상에서 색상 임계값이 녹 색을 놓치는 전형적인 사례이며, 조건에 맞게 임계값을 다시 잡거나 학습 모델로
  개선해야 합니다. shifted에서 오경보는 2% 수준이라 놓침이 문제입니다.
- ② 균열은 train에서 전부 검출(오경보 0)이라 합성 조건이 베이스라인에 쉽다는 뜻이기도 합니다(최소 균열 높이 0.15 mm 이상).
  이 수치를 실제 성능으로 읽으면 안 됩니다. shifted에서는 검출률 0.91, a90 1.22 mm [상한 1.34 mm]로 나빠집니다.
- ③ 두께 MAE는 0.003 -> 0.43 mm로 악화. +-0.1 mm와 +-0.5 mm 이내 비율이 거의 같은 것은 오차가 "정확히 맞거나 에코 간격을 잘못 잡아 크게 틀리는"
  이중 모드이기 때문입니다. 남은 큰 오차는 주로 shifted의 피팅 샘플(노이즈 3배·저접촉)에서 나옵니다. 피트 검출은 shifted에서 거의 무너집니다(0.92 -> 0.05).
  원인 후보는 저접촉으로 인한 진폭 저하, 노이즈 3배, 측정 온도 오차(15 C)이며 각각을 분리해서 확인하지는 않았습니다.
- 모든 임계값/가정은 `assumption: true` 파라미터이며 현장 보정이 없습니다. POD 곡선도 시뮬레이터 안에서의 값입니다.
- 이 베이스라인들은 **해커톤에서 학습 모델(YOLO-seg 분할기, 1D-CNN 등)로 개선할 기준선**입니다.
  개선 여부는 위 표의 같은 지표(특히 shifted 열)로 비교합니다.

## 전략 개선: 위험 순위 기반 균열 UT

기준 전략의 고정 측정점은 두께용(수직 탐촉자)이라 균열을 찾지 못합니다(검출률 0). 기존 AI 트리아지는 용접부를 무작위(5%)로, 고피해 엘보를 모두 사각 UT로 쟀지만 치명 균열을 거의 못 찾았습니다.
새 모드(`strategy.crack_ut_mode: risk_ranked`)는 금속 배관의 용접/엘보 위치를
**점수 = (경년/기준)^지수 x 피해등급(매질) x 형상 가중치(용접 0.6 > 엘보 0.3)** 로 순위를 매겨,
기준 전략 고정 UT 점 수의 `crack_ut_budget_frac`(0.30) 만큼만 상위부터 측정합니다.
(`crack_ut_mode: random`으로 기존 동작 유지.)

| 100 km x 10회 평균 (시드 0) | 치명 균열 검출률 | 평균 UT 점 수 |
|---|---|---|
| 기준(고정 CML) | 0.000 | 3821 |
| AI 기존(random) | 0.027 | 2389 |
| AI 위험순위(risk_ranked) | 0.149 | 3031 |

AI 총 UT 점 수는 기준 전략보다 적게 유지됩니다(약 79%). 다만 절대 수준(약 15%)은 여전히 낮은데, 사각 UT POD 파라미터
(`strategy.pod.ut_angle`, 균열 깊이 mm 기준)가 가정값이고 시뮬레이션 균열이 대부분 작기 때문입니다.
예산 비율 0.2/0.3/0.4/0.5에서 검출률은 약 0.10/0.15/0.22/0.27, UT 점 수는 기준의 69/79/89/99%였습니다.
비용·정확도 균형에 맞는 비율은 현장 협의가 필요합니다(비용은 `python -m maek strategy`로 확인).

## 학습형 YOLO-seg (Colab / GPU)

`scripts/train_yolo_seg.py`는 렌더링한 `dataset.yaml`을 Ultralytics YOLO-seg로 학습/평가하는 독립 스크립트입니다
(core 의존성이 아니며 CI/pytest 대상 아님; `pip install ultralytics` 필요).

```bash
# 1) 데이터 생성 (로컬 또는 Colab)
python -m maek camera-jobs --n 2000 --out data/ && python -m maek render2d --out data/
# 2) 학습 / 검증 / 내보내기 / 보드 벤치마크
python scripts/train_yolo_seg.py train  --data data/camera/dataset.yaml --epochs 50 --imgsz 640
python scripts/train_yolo_seg.py val    --data data/camera/dataset.yaml --weights runs/segment/maek/weights/best.pt
python scripts/train_yolo_seg.py export --weights runs/segment/maek/weights/best.pt --format onnx --imgsz 320
python scripts/train_yolo_seg.py benchmark --weights runs/segment/maek/weights/best.pt --data data/camera/dataset.yaml
```

Colab에서는 런타임 유형을 GPU로 바꾸고 저장소를 `git clone`한 뒤 `pip install pyyaml pillow pandas numpy ultralytics`
후 위 명령을 실행하면 됩니다. shifted 조건 성능은 `make_jobs(..., condition="shifted")`로 별도 데이터셋을 렌더링해 `val --data`에
넘겨 측정합니다. 클래스는 0 corrosion, 1 cui_sign, 2 leak_stain입니다. 이 환경에서는 학습을 실행하지 못했으므로 학습 모델 수치는 없습니다.
탑재 자원 측정은 [onboard-resources.md](onboard-resources.md)를 참고하세요.
