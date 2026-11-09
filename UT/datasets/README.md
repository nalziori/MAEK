# 데이터 위치와 사용 범위

`registry.json`은 사용자가 추가한 `find_info/data`의 모든 파일을 등록합니다. 같은 파일을 로컬 `C:/MAEK/UT/data`에서 SHA-256으로 대조했습니다. 약 1GB의 원시 자료를 Git 저장소에 중복 업로드하지 않습니다.

| 로컬 폴더 | 용도 | 최신 성능 표와의 관계 |
|---|---|---|
| `data/crack/synthetic_angle_v3` | 이전 균열 합성 평가 | 최신 MLP의 9,600개 평가와 다름 |
| `data/crack/geometry_stress_v1` | 각도·온도·지연 오차 진단 | 과거 실패 분석 |
| `data/crack/measured_auxiliary` | 실측 노치 크기 추정 결과·설정 | 균열 탐지률/FAR 평가가 아님 |
| `data/pit/synthetic_normal_v2` | 피팅 MLP 합성 원본·평가 | 노트북의 최신 피팅 CNN 평가셋과 다름 |
| `data/public_candidates` | NDT_ML_Flaw 자료와 출처 확인 | 최종 균열 MLP 학습에 사용하지 않음 |

NDT_ML_Flaw 원본 출처: https://github.com/koomas/NDT_ML_Flaw (기록된 commit `3bb780951752bee4207b3f974b43de4669467117`). 다운로드 URL·라이선스는 로컬 `data/public_candidates/audit/`와 `NDT_ML_Flaw/LICENSE`에 있습니다. 공개 데이터의 증강 샘플 수를 독립 결함 수로 계산하지 않습니다.

최신 균열 MLP의 전체 파형은 별도로 로컬 `UT/crack_mlp/run/fresh_*_inputs.npz`, 원 학습·보정 파형은 `UT/crack_cnn/crack_retraining_v4/run`에 보존했습니다. GitHub에는 동결 설정·가중치·개별 판정 CSV와 작은 재현 예제를 제공합니다. 전체 재학습/감사는 큰 로컬 파일도 필요합니다.

파일 전체 검사는 로컬에서 `python UT/verify_data.py`로 수행합니다. GitHub만 복제한 경우 데이터 원본이 없는 것은 의도된 상태이며, `python UT/verify_final.py`가 제공 파일의 무결성과 작은 추론 예제를 검사합니다.
