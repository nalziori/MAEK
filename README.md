# MAEK (맥)

**파이프의 맥을 읽는다.** POSCO AI Hackathon 2026 안전 주제 프로젝트입니다.

## 한 줄 소개

카메라로 낡은 배관의 부식을 먼저 찾고, 의심 지점만 초음파로 재서 점검 순서를 정합니다.

## 핵심 기능

| 기능 | 장비 | 찾는 것 |
|---|---|---|
| ① 부식 탐지 | 카메라 (드론, 로봇, CCTV) | 외부 부식, 보온재 아래 부식(CUI)의 겉 징후 |
| ② 내부 균열 탐지 | 초음파 사각 탐촉자 | 겉에서 안 보이는 균열, 파열 |
| ③ 두께 측정 | 초음파 수직 탐촉자 | 감육, 피팅, 남은 수명 |

## 동작 구조

1. 카메라로 1차 선별합니다. 부식, 보온재 손상, 누출 흔적을 찾습니다.
2. 고른 곳과 고위험 위치만 초음파로 봅니다. 두께를 재고 균열을 확인합니다.
3. 위험도로 점검 순서를 정합니다. 흐르는 물질(산소, 불산, CO), 사람 통행, 설치 연식을 씁니다.

## 설치와 실행

```bash
pip install -r requirements.txt
```

결과를 재현할 때는 스레드를 1개로 고정합니다. `OMP_NUM_THREADS=1`을 붙여 실행하세요.

| 명령 | 하는 일 | 예시 |
|---|---|---|
| `params-table` | 파라미터 표를 출력합니다. `--write`를 붙이면 `docs/params.md`를 갱신합니다. | `python -m maek params-table --write` |
| `network` | 가상 배관망, 구간, 결함을 만듭니다. | `python -m maek network --seed 0 --out data/network` |
| `ut` | 초음파 A-scan 데이터를 만들고 기준 성능을 출력합니다. | `OMP_NUM_THREADS=1 python -m maek ut --n 2000 --condition shifted --out data/ut` |
| `camera-jobs` | 카메라 촬영 작업(JSON)을 만듭니다. | `python -m maek camera-jobs --n 300 --seed 1 --out data/` |
| `render2d` | 촬영 작업을 이미지·마스크·YOLO-seg 라벨로 렌더링합니다. | `OMP_NUM_THREADS=1 python -m maek render2d --seed 1 --out data/` |
| `strategy` | 기존 방식과 AI 선별 방식을 비교합니다. | `python -m maek strategy --runs 20 --seed 0` |
| `evaluate` | 세 기능을 한 번에 평가합니다. | `python -m maek evaluate --out data/eval` |
| `onboard` | 탑재 장비의 연산 시간과 메모리를 측정합니다. | `python -m maek onboard --out data/eval` |

전체 데이터는 `scripts/produce_data.py`로 한 번에 만듭니다.

```bash
OMP_NUM_THREADS=1 python scripts/produce_data.py
```

`--out`의 기본값은 `data/release`, `--seed`의 기본값은 1입니다. 규모는 `--ut-train`, `--img-train` 등으로 바꿀 수 있습니다.

## 결과 요약

아래 수치는 합성 데이터로 만든 기준선(규칙 기반 베이스라인)입니다. 실제 현장 성능이 아닙니다.
`train`은 학습 조건, `shifted`는 조명, 온도, 노이즈 등을 바꾼 학습에 없던 조건입니다.
자세한 내용은 [결과 문서](docs/results.md)에 있습니다.

| 기능 | 지표 | train | shifted |
|---|---|---|---|
| ① 부식 | 픽셀 IoU | 0.823 | 0.262 |
| ① 부식 | 결함 단위 hit율 | 0.991 | 0.311 |
| ② 균열 | 검출률 | 1.000 | 0.912 |
| ③ 두께 | 두께 MAE (mm) | 0.117 | 1.074 |
| ③ 두께 | 피트 검출률 | 0.925 | 0.045 |

점검 전략 비교 (치명 균열 검출률, 평균 UT 점 수):

| 전략 | 검출률 | UT 점 수 |
|---|---|---|
| 기준 (고정 CML) | 0.043 | 3821 |
| AI 트리아지, 무작위 순서 | 0.027 | 2389 |
| AI 트리아지, 위험도 순서 | 0.149 | 3031 |

탑재 장비 측정 (개발 PC CPU 1코어, 근사값):

- 부식 분할 640x640: 중앙값 66 ms. 5 fps 예산(200 ms) 안에 들어가지만 여유가 약 3배입니다. 보드가 3배 이상 느리면 못 맞춥니다.
- 부식 분할 320x320: 중앙값 15 ms.
- 균열, 두께 추정 (UT): 한 번에 1 ms 미만입니다.
- 메모리: 최대 약 157 MB (기준선만 측정). 학습 모델은 아직 측정하지 않았습니다.

## 데이터 받기

합성 데이터 v1(약 450MB)은 이 저장소의 `data` 브랜치에 있습니다. 받는 방법과 조각 합치는 방법은 [data 브랜치 README](https://github.com/nalziori/MAEK/tree/data)에 있습니다.

| 묶음 | 규모 |
|---|---|
| 배관망 정답 | 100km, 구간 2,000개, 특징 25,018개, 결함 885개(위험 200개) |
| ②③ 초음파 A-scan | 학습 10,000개, 어려운 조건 3,000개 |
| ① 카메라 이미지 | 학습 2,000장, 어려운 조건 400장 (마스크, YOLO-seg 라벨 포함) |
| 점검 전략 비교 | 20회 반복, 단가 민감도 |

데이터 카드와 결과 표는 [구글 드라이브 MAEK 폴더](https://drive.google.com/drive/folders/1CSW6ENnyRrK0J1tF6CnAKn7gXxHfBkVz)에도 있습니다.

## 문서

- [배관 AI 비파괴검사 주제 검토](docs/posco-pipe-ndt-review.md): 포스코 현행 점검, 사고별 효과, 시뮬레이션 전략, 준비 일정, 예상 질문
- [포스코 제철소 안전사고 아카이브](docs/posco-safety-accidents.md): 2018~2026년 사고 22건과 출처
- [파라미터 표](docs/params.md): 가상 배관망과 센서 파라미터, 근거 구분 (가정 여부)
- [결과](docs/results.md): 세 기능의 기준 성능, POD a90, 점검 전략 비교, YOLO-seg 학습 방법
- [탑재 리소스](docs/onboard-resources.md): 드론·로봇 탑재 시 지연·메모리 측정
- [렌더 작업 형식](docs/render-jobs.md): Unity·Blender 렌더러와 주고받는 JSON 형식

## 한계

- 모든 데이터는 합성입니다. 실제 점검 데이터로 검증하지 않았습니다.
- 탑재 장비 수치는 개발 PC CPU에서 잰 근사값입니다. 실제 보드 수치가 아닙니다.
- 비용 파라미터는 가정값입니다. 근거 자료가 없는 값은 `docs/params.md`에서 가정으로 표시합니다.
