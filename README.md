# MAEK 합성 데이터 (v3)

v3는 증기·응축수·스팀 트레이싱 대표 시나리오, 열화상·PEC 단계, 보온재 해체 비용, 피팅 극치통계를 반영한 데이터입니다. `data`(v1)와 `data-v2` 브랜치는 이전 모델의 데이터라 쓰지 마세요.

`main` 브랜치의 `scripts/produce_data.py`로 만든 합성 데이터입니다. 실제 점검 데이터가 아닙니다.
자세한 내용은 `maek-network-strategy.zip` 안의 `DATA_CARD.md`를 보세요.

| 파일 | 내용 |
|---|---|
| `maek-network-strategy.zip` | 배관망 정답(100 km), 점검 전략 비교(기본망·증기 시나리오), 단가·피팅·환경 가정 민감도, 피팅 극치통계 요약, 데이터 카드 |
| `maek-ut.zip.part*` | ②③ 초음파 A-scan (학습 10,000개, 어려운 조건 3,000개) |
| `maek-camera.zip.part*` | ① 카메라 이미지·마스크·YOLO-seg 라벨 (학습 2,000장, 어려운 조건 400장) |
| `maek-thermal.zip.part*` | 열화상 16비트 온도 PNG·마스크·YOLO-seg 라벨 (학습 1,000장, 어려운 조건 300장) |

## 받기와 풀기

```bash
git clone --branch data-v3 --single-branch https://github.com/nalziori/MAEK.git maek-data
cd maek-data
sha256sum -c SHA256SUMS
cat maek-ut.zip.part* > maek-ut.zip
cat maek-camera.zip.part* > maek-camera.zip
cat maek-thermal.zip.part* > maek-thermal.zip
unzip maek-network-strategy.zip -d release
unzip maek-ut.zip -d release
unzip maek-camera.zip -d release
unzip maek-thermal.zip -d release
```

Windows PowerShell에서 조각 합치기:

```powershell
cmd /c copy /b maek-ut.zip.part00+maek-ut.zip.part01+maek-ut.zip.part02 maek-ut.zip
cmd /c copy /b maek-camera.zip.part00+maek-camera.zip.part01+maek-camera.zip.part02 maek-camera.zip
cmd /c copy /b maek-thermal.zip.part00+maek-thermal.zip.part01 maek-thermal.zip
```

열화상 이미지는 16비트 PNG이고 픽셀 값은 (온도 ℃ + 50) × 100입니다. 온도로 되돌리려면 `값 / 100 - 50`을 계산하세요.

같은 데이터를 직접 만들려면 `main`에서 `OMP_NUM_THREADS=1 python scripts/produce_data.py --seed 1`을 실행하세요(4코어 약 15분).

YOLO-seg 학습은 `main`의 스크립트로 하세요. 압축을 푼 위치와 상관없이 경로를 자동으로 맞춥니다.

```bash
python scripts/train_yolo_seg.py train --data release/camera/train/dataset.yaml --epochs 50 --imgsz 640
python scripts/train_yolo_seg.py val --data release/camera/shifted/dataset.yaml --weights runs/segment/maek/weights/best.pt
```

학습·검증 분할은 배관 구간 단위라 같은 결함이 양쪽에 들어가지 않습니다.
