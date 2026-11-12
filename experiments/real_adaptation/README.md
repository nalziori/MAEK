# 실사진 적응 실험 (2026-11-12)

합성 데이터로만 학습한 MAEK 부식·열화상 모델에 공개 실사진을 조금씩 넣어 추가 학습하면 얼마나 좋아지는지 잰 실험입니다. 웹 시연에 탑재한 모델(`maek_corrosion_real_v1`, `maek_thermal_real_v1`)도 여기서 만들었습니다.

## 결론

- 합성 데이터로만 학습한 모델은 실사진에서 거의 쓰지 못합니다(부식 교량 IoU 0.09, 열화상 검출률 6%).
- 실사진 25장만 넣어도 부식 IoU가 0.47로 오릅니다. 396장이면 0.64입니다.
- **다른 현장의 사진은 잘 옮겨 가지 않습니다.** 교량 사진 396장으로 학습해도 오스트라바 산업단지에서는 IoU 0.31이고, 오스트라바 사진 75장을 넣으면 0.70입니다.
- 타일 분할, 정상:결함 50:50, 회전·상하 뒤집기는 IoU를 시드 간 편차(±0.03) 이상으로 올리지 못했습니다. 심각도 3단계 학습은 396장으로는 부족했습니다(severe IoU 0.08).
- 합성 이미지를 섞어 학습(replay)하지 않으면 합성 이미지 성능을 잃습니다(IoU 0.87 → 0.34~0.49). 섞으면 0.82로 유지됩니다.

## 데이터

| 데이터 | 용도 | 라이선스 | 받는 곳 | 해시 |
|---|---|---|---|---|
| Corrosion Condition State Semantic Segmentation Dataset (Virginia Tech), 교량 실사진 440장 | 부식 학습 396 / 시험 44 | CC0 | https://data.lib.vt.edu/articles/dataset/Corrosion_Condition_State_Semantic_Segmentation_Dataset/16624663 | md5 `bbc9b8b8a5bb065e9ace028893dfd983` |
| Corrosion in Industrial Complexes in Ostrava (M. Frič), 산업단지 실사진 105장 | 부식 학습 75 / 시험 30 | CC BY 4.0 | https://zenodo.org/records/11235637 | md5 `e30f1f62eb85018c2faee44909e69a06` |
| thermal-leak-detection-acteabot v1 (Buildsys2022, Roboflow), 실제 배관·덕트 열화상 | 열화상 학습 원본 156 / 시험 93 | CC BY 4.0 | https://universe.roboflow.com/buildsys2022/thermal-leak-detection-acteabot/dataset/1 (YOLOv8 형식, 로그인 필요) | — |
| MAEK 합성 이미지 | 망각 방지용 600장, 합성 시험 200장 | 저장소 | `python -m maek camera-jobs/render2d` (시드 31, 32), `maek.thermal_render` (시드 51, 52) | — |

시작 가중치: `best.pt`(E4, sha256 `5c836f8a…`), `sim_pipe_yolov8s_640_S.pt`(`670fde80…`), `pv_yolov8s_640_A.pt`(`2cf6a812…`). 모두 이 저장소의 Release에 있습니다.

## 미리 정한 규칙

- 판정 기준 conf 0.25, 입력 640, 마지막 에포크 가중치 사용. 검증셋으로 모델을 고르지 않았으므로 시험셋은 조정에 쓰이지 않았습니다.
- 에포크 수는 `clip(16000 / 학습 이미지 수, 50, 150)`, 타일 조건은 20으로 고정했습니다.
- 조건마다 시드 3개(0, 1, 2)를 돌려 평균과 표준편차를 냅니다. 탑재 모델은 시드 0 한 번입니다.
- 열화상 원본 데이터셋은 같은 원본 사진이 학습·검증·시험에 겹쳐 들어간 것이 31건 있어서, 촬영 세션(파일 이름 접두어) 단위로 다시 나눴습니다. `A_*` 세션 93장을 시험에만 쓰고, 나머지 두 세션으로 학습했습니다.
- 열화상 클래스 `A_1`~`A_4`는 열점 하나로 합치고, `A_5`(보온재 없는 주름관 전체)는 뺐습니다. 클래스 설명이 원본에 없어 샘플을 보고 판단한 것입니다.
- 흑백 열화상은 시작 모델의 학습 입력과 같게 inferno 색상으로 바꿨습니다.

## 파일

| 파일 | 내용 |
|---|---|
| `setup.sh` | 인스턴스 준비: 패키지, 가중치, 데이터 다운로드 |
| `prep.py`, `run.py` | 1단계: 실사진 장수별 곡선 (부식 43회, 열화상 47회) |
| `prep2.py`, `run2.py` | 2단계: 타일·50:50·회전/뒤집기·심각도 조건 비교(16회)와 탑재 모델 2개 학습 |
| `results/results_corr.jsonl`, `results_th.jsonl` | 1단계 결과 (실행 1회당 한 줄) |
| `results/results_arms.jsonl` | 2단계 조건 비교 결과 |
| `results/results_final.json` | 탑재 모델 시험 결과 |
| `results/prep*.json`, `environment.txt` | 데이터 통계, 실행 환경 (RTX 4090, torch 2.14.1, ultralytics 8.4.211) |

스크립트는 실행한 그대로입니다. 경로가 `/workspace/exp`로 고정돼 있고, `run.py`/`run2.py`는 `--shard i/3`으로 세 개씩 병렬로 돌렸습니다. GPU 특성상 같은 시드로 다시 돌려도 소수점 아래 숫자는 달라질 수 있습니다.

## 한계

- 실사진은 교량, 산업단지, 건물 설비입니다. 제철소 현장 사진이 아닙니다.
- 실사진 시험셋에 정상(결함 없는) 사진이 없어 실사진 오경보율을 재지 못했습니다. 50:50 균형의 효과가 주로 나타나는 지표가 이것입니다.
- 시험 사진이 44장, 30장, 93장으로 적습니다.
- 열화상 검출률 49%는 현장 적용에 부족합니다.
