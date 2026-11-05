# MAEK 합성 데이터셋 카드

가상 제철소 배관망 시뮬레이션으로 만든 합성 데이터입니다. 실제 점검 데이터가 아닙니다.

- 생성 코드: nalziori/MAEK 커밋 `1909610`, 설정 `config/default.yaml`
- 재생성: `OMP_NUM_THREADS=1 python scripts/produce_data.py --seed 1`
- 생성 시간: 19.9초

| 묶음 | 내용 | 규모 |
|---|---|---|
| network | 100km 배관망 구간·특징·결함 정답 | 구간 2000, 결함 885 (위험 200) |
| ut/train, ut/shifted | ② 균열(사각 탐촉자)·③ 두께(수직 탐촉자) A-scan, float16 | 100 / 50 |
| camera/train, camera/shifted | ① 부식 이미지(JPEG)·마스크·YOLO-seg 라벨 | 30 / 10 |
| strategy | 기존 방식 vs AI 선별 방식 비교, 단가 민감도 | 2회 |

`shifted`는 학습에 쓰지 않은 어려운 조건(잡음, 극단 온도, 접촉 불량, 조명·분진·증기)입니다. 평가에만 쓰세요.
파라미터와 출처는 저장소 `docs/params.md`, 기준 성능은 `docs/results.md`에 있습니다.
