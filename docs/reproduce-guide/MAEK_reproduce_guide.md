# MAEK 재현 방법

**저장소의 yaml 설정으로 그대로 실행하기**

2026년 11월 12일 · MAEK 팀

## 요약

> **저장소의 yaml은 config/default.yaml 하나와 시나리오 7개이고, python -m maek <명령> 한 줄로 그대로 돌아갑니다. 모델 가중치, GPU, 따로 받을 파일은 필요 없습니다.**
>
> GitHub main(0b83f5e)을 새로 받아 requirements.txt의 4개 패키지만 설치한 Python 3.10에서 13개 명령을 모두 실행해 확인했습니다.

웹 시연은 학습된 AI 모델 3개의 판정을 보여 주고, 이 경로는 그 바탕이 된 **가상 배관망 시뮬레이터**(합성 데이터 생성, 규칙 기반 기준 성능, 점검 전략 비교)를 돌립니다.

## 1. yaml 파일

| 파일 | 내용 |
|---|---|
| config/default.yaml | 전체 파라미터(배관망, 결함, 초음파, 카메라, 열화상, 비용·전략). 값마다 출처 URL 또는 assumption: true가 붙어 있습니다 |
| config/scenarios/steam.yaml | 증기·응축수·트레이싱 배관 20 km |
| config/scenarios/pohang_*.yaml, gwangyang_*.yaml | 포항·광양 배관 길이 추정(667~1,370 km) 6개. 공개 자료로 만든 가정이며 실제 설비 목록이 아닙니다 |

시나리오 파일은 default.yaml 위에 바뀌는 값만 덮어씁니다. UT/ 아래의 default.yaml 두 개는 초음파 패키지용 고정 사본이라 직접 지정할 일이 없습니다.

## 2. 설치

PowerShell에서 차례로 실행합니다.

```powershell
git clone https://github.com/nalziori/MAEK.git
cd MAEK
py -3.10 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:OMP_NUM_THREADS = "1"; $env:PYTHONUTF8 = "1"
```

## 3. 실행 명령

걸린 시간은 노트북 한 대에서 스레드 1개로 잰 값입니다.

| 명령 | 하는 일 | 시간 |
|---|---|---|
| python -m maek params-table | yaml의 모든 값·단위·근거를 표로 출력 | 1초 |
| python -m maek network --seed 0 --out data/network | 100 km 가상 배관망과 결함 생성(CSV 3개) | 4초 |
| python -m maek strategy --runs 20 --seed 1 | 사람+비계, 드론, 드론+AI 비교 | 107초 |
| python -m maek strategy --scenario steam --runs 20 --seed 1 | 같은 비교를 증기 시나리오로 | 76초 |
| python -m maek ut --n 2000 --condition shifted --out data/ut | 초음파 A-scan 생성과 기준 성능 | 63초 |
| python -m maek camera-jobs --n 300 --seed 1 --out data/ | 카메라 촬영 작업 목록 생성 | 14초 |
| python -m maek render2d --seed 1 --out data/ | 위 작업을 이미지·마스크·라벨로 렌더링 | 117초 |
| python -m maek thermal --n 300 --condition train --out data/ | 합성 열화상 생성과 기본 탐지기 평가 | 20초 |
| python -m maek thermal-pod --n 600 | 열화상 발견 확률 곡선 적합 | 61초 |
| python -m maek eva --runs 10 --total-km 100 | 내부 피팅 극치통계 판정 | 77초 |
| python -m maek onboard --out data/eval | 연산 시간·메모리 측정 | 32초 |
| python -m maek pit-prior --runs 10 | 피팅 스캔 위치 가정 민감도 | 축소 실행(2회, 20 km) 8초 |
| python -m maek sweep --runs 5 --total-km 20 | 환경 가정 15가지 변경 | 축소 실행(1회) 16초 |
| python -m maek evaluate --out data/eval | 세 기능 종합 평가 | 734초(약 12분) |

결과는 화면에 표로 나오고, --out 폴더(기본 data/)에 CSV로 저장됩니다.

## 4. 설정 바꾸는 방법

모든 명령에 공통으로 붙고, 적용 순서는 --config → --scenario → --set입니다.

| 옵션 | 예시 |
|---|---|
| --scenario 이름 | python -m maek strategy --scenario pohang_base --runs 10 --seed 1 --total-km 100 |
| --set 키=값 | python -m maek strategy --set strategy.human_elevated_access=lift |
| --config 파일 | default.yaml을 복사해 고친 파일을 지정 |

- **포항·광양 시나리오에는 --total-km 100을 붙이세요.** 그대로 돌리면 770~1,370 km 전체를 계산해 오래 걸립니다. 전체 길이 실행은 확인하지 않았습니다.
- 없는 시나리오 이름을 넣으면 사용 가능한 7개 이름을 알려 주고 멈춥니다.
- 값에 출처나 assumption 표시가 없으면 실행 전에 오류로 알려 줍니다.

## 5. 확인된 결과

- **기본망 전략 비교:** README 표와 같습니다. 위험 결함 발견율 0.192 / 0.270 / 0.587, 비용 35.3억 / 24.7억 / 19.2억입니다.
- **증기 시나리오:** README 표와 같습니다. 발견율 0.146 / 0.209 / 0.593, 비용 9.0억 / 8.7억 / 7.5억입니다.
- **열화상:** 기본 탐지기 hit율 0.78 / 0.93 / 0.59로 README와 같고, thermal-pod가 낸 계수도 yaml에 적힌 값과 같습니다.
- **종합 평가(evaluate):** README의 결과 요약 표와 같습니다. 부식 픽셀 IoU 0.823 / 0.262, 균열 검출률 1.000 / 0.912, 두께 오차 0.002 / 0.020 mm, 피트 검출률 1.000 / 0.889입니다(학습 조건 / 어려운 조건).
- **확인하지 않은 것:** 전체 데이터를 한 번에 만드는 python scripts/produce_data.py는 돌리지 않았습니다. README에는 4코어에서 약 15분으로 적혀 있습니다.

*이 수치는 모두 합성 데이터와 가정한 단가로 낸 값입니다.*

