# MAEK 합성 데이터셋 카드

가상 제철소 배관망 시뮬레이션으로 만든 합성 데이터입니다. 실제 점검 데이터가 아닙니다.

- 생성 코드: nalziori/MAEK 커밋 `514d86a`, 설정 `config/default.yaml`
- 재생성: `OMP_NUM_THREADS=1 python scripts/produce_data.py --seed 1`
- 생성 시간: 7.5초

| 묶음 | 내용 | 규모 |
|---|---|---|
| network | 100km 배관망 구간·특징·결함 정답 | 구간 40, 결함 18 (위험 0) |
| ut/train, ut/shifted | ② 균열(사각 탐촉자)·③ 두께(수직 탐촉자) A-scan, float16 | 20 / 10 |
| camera/train, camera/shifted | ① 부식 이미지(JPEG)·마스크·YOLO-seg 라벨 | 6 / 4 |
| strategy | 3가지 점검 방식(사람+비계 / 드론 / 드론+AI) 비교(compare.csv), 단가 민감도(sensitivity.csv), 증기 시나리오(compare_steam.csv, sensitivity_steam.csv), 내부 피팅 스캔 사전지식 민감도(pit_prior.csv), 가정 변화 강건성(sweep.csv) | 1회 (pit 1, sweep 1회 x 2 km) |
| eva | 극값(Gumbel) 내부 피팅 회로 분석 요약 (eva_summary.csv) | 1회 |
| thermal/train, thermal/shifted | ④ 열화상(IR) 이미지(16비트 PNG, (온도 C + 50) x 100)·마스크·YOLO-seg 라벨. 젖은 보온재, 외장 훼손, 증기 누설 | 4 / 3 |

`shifted`는 학습에 쓰지 않은 어려운 조건(잡음, 극단 온도, 접촉 불량, 조명·분진·증기, 열화상은 맑은 낮·강풍·방사율 설정 오차)입니다. 평가에만 쓰세요.
strategy의 비용·시간·고장 트랩 점검 시간 등은 모두 가정값이며, 증기 시나리오는 `config/scenarios/steam.yaml`을 덮어쓴 결과입니다.
파라미터와 출처는 저장소 `docs/params.md`, 기준 성능은 `docs/results.md`에 있습니다.
