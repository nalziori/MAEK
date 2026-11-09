# 균열 MLP v1

가상 사각빔 파형의 정합필터 + CA-CFAR + 특징 MLP 후보입니다. 선택 가중치는 `run/mlp_seed5101.pt`입니다.

보고서: [최종 결과와 검증 범위](../docs/최종_균열_피팅_결과와한계.md).

입력 NPZ의 필수 배열은 `rf`(N,4096), `nominal_wall_mm`, `nominal_angle_deg`, `observed_temp_c`(각 N)입니다. 실제 균열 정답은 입력하지 않습니다.

저장소 루트에서 추론 예:

```powershell
$env:OMP_NUM_THREADS='1'
python UT/crack_mlp/predict_mlp.py --input UT/examples/crack_mlp_ascan.npz --output crack_mlp_predictions.json --sampling-mhz 100 --probe-mhz 5 --n-avg 16
```

기존 출력은 덮어쓰지 않습니다. 가상5MHz/100MHz/16회 평균, 공칭 두께3~12mm·45/60/70도 범위만 지원합니다. 부분 검사창 또는 품질 문제가 있는 음성 결과는 추가 확인 대상으로 표시합니다.

의존성은 UT/requirements.txt와 같습니다. 공통 처리와 원 학습 자료가 있는 `UT/crack_cnn/crack_retraining_v4`를 함께 보관하세요. Python3.12·PyTorch2.14.1 서버에서 학습했으며 Jetson 속도 검증은 수행하지 않았습니다.

동결 결과는 run/에 있습니다. GitHub에는 큰 파형 NPZ를 제외했으므로, 전체 재학습·감사에는 로컬에 보관한 원 학습·보정·평가 파형이 필요합니다. 작은 예제는 실행 호환성 확인용이며 표본 탐지률을 계산하는 자료가 아닙니다.

재학습은 코드를 별도 새 폴더에 복사하고 `--baseline`으로 v4 폴더를 지정하여 `--smoke` 성공 후 실행합니다. 기존 run/와 smoke_v2/는 덮어쓰지 않습니다. v4 폴더명의 CNN은 전처리·생성기를 가져온 과거 실험명이며 여기서 실제 판정하는 모델은 MLP입니다.
