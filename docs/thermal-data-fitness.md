# 열화상 데이터 적합성 현재 판정

2026-11-08 감사 결과, 현재 v3 열화상과 30/100epoch 모델은 보온·증기 합성 관측 하위 과제용이다. **가스 배관 균열·감육 최종 기능의 학습/검증 근거로는 부적합**하다. 원본 자료는 재현용으로 보존했으며 가스 배관 목표 후보에서 제외 판정을 기록했다. 생산 기본 모델은 변경하지 않았다.

- 열화상1,300장에는 균열·감육 라벨이 없고, 기존 열저항 식은 금속벽·내부 대류막을 생략한다.
- UT13,000표본에는 관련 결함 정답이 있으나 물리적 위치 ID가 없어 열화상과 연결할 수 없다.
- RGB2,400장 중 기본 학습/shifted에 같은 배관 구간·결함이 있으므로 독립 설비 평가가 아니다.
- wet 위치·경계 편향, damage 영역 전처리 클리핑 등을 전수 통계로 확인했다. 파일 무결성과 실제 학습 적합성은 별개다.

새 `maek/thermal_feasibility.py`와 `scripts/generate_thermal_feasibility.py`는 내부막·벽·보온·외부막을 포함하는 제한된 원통 열전달 민감도 도구다. 192조건768영상을 생성했지만 실제 균열/누출·측방 열확산·센서 보정을 구현한 학습 데이터가 아니다. `training_eligible=false`이며 감독학습에 자동 투입하지 않는다. `perturbation_support`는 band>0.5 중심영역이고 관측 결함 마스크가 아니다.

재현:

```powershell
.venv-benchmark/Scripts/python.exe scripts/audit_maek_v3.py --help
.venv-benchmark/Scripts/python.exe scripts/audit_thermal_bias.py --help
.venv-benchmark/Scripts/python.exe scripts/generate_thermal_feasibility.py --out ../outputs/maek-c/thermal-feasibility-new-run
.venv/Scripts/python.exe -m pytest tests/test_thermal_feasibility.py -q
```

새 생성기는 기존 폴더 덮어쓰기를 거절한다. seed/입력 가정·그룹 ID·원시 float 온도·소스/데이터 해시를 보존한다. 같은 대조군을 학습/검증에 나누지 않는다.

상세 결과: [감사·개선 보고서](../../outputs/maek-c/data-fit-audit-20261108/report.md), [모델 처리 판정](../../outputs/maek-c/data-fit-audit-20261108/model-disposition.json), [최종 대조 데이터](../../outputs/maek-c/thermal-feasibility-20261108-verified/DATA_CARD.md).

가스 배관 결함 판정용 학습은 [역할 계약](thermal-role-contract.md)의 정답·관측·위치 연결과 실제 조건 검증을 먼저 충족해야 한다. 사용자는 대응 실측 자료가 없으며 데이터/생성기 개선부터 진행하도록 답했다.

후속으로 [기준/현재 열 관측 변화 학습 과제](thermal-observation-training.md)를 분리했다. 새 생성기는 면내 열전도와 독립 센서 잡음을 포함하며, 관측 변화용 0/1/255 정답을 사용한다. 독립 검증을 통과한 새 데이터는 이 제한된 합성 하위 과제에 사용할 수 있다. 이는 기존 feasibility 데이터의 `training_eligible=false`를 변경하거나 균열 학습 적합성을 인정하는 조치가 아니다. 현재 새 Colab 학습은 실행하지 않았다.
