# MAEK 합성 데이터 (v2)

v2는 코드 리뷰 15건 수정(두께 추정, 학습·검증 분할, YOLO 경로 등)을 반영한 데이터입니다. `data` 브랜치의 v1은 쓰지 마세요.

`main` 브랜치의 `scripts/produce_data.py`로 만든 합성 데이터입니다. 실제 점검 데이터가 아닙니다.
자세한 내용은 `maek-network-strategy.zip` 안의 `DATA_CARD.md`를 보세요.

## 받기와 풀기

```bash
git clone --branch data-v2 --single-branch https://github.com/nalziori/MAEK.git maek-data
cd maek-data
sha256sum -c SHA256SUMS
cat maek-ut.zip.part* > maek-ut.zip
cat maek-camera.zip.part* > maek-camera.zip
unzip maek-network-strategy.zip -d release
unzip maek-ut.zip -d release
unzip maek-camera.zip -d release
```

Windows PowerShell에서 조각 합치기:

```powershell
cmd /c copy /b maek-ut.zip.part00+maek-ut.zip.part01+maek-ut.zip.part02 maek-ut.zip
cmd /c copy /b maek-camera.zip.part00+maek-camera.zip.part01+maek-camera.zip.part02 maek-camera.zip
```

같은 데이터를 직접 만들려면 `main`에서 `OMP_NUM_THREADS=1 python scripts/produce_data.py --seed 1`을 실행하세요.

YOLO-seg 학습은 `main`의 스크립트로 하세요. 압축을 푼 위치와 상관없이 경로를 자동으로 맞춥니다.

```bash
python scripts/train_yolo_seg.py train --data release/camera/train/dataset.yaml --epochs 50 --imgsz 640
python scripts/train_yolo_seg.py val --data release/camera/shifted/dataset.yaml --weights runs/segment/maek/weights/best.pt
```

학습·검증 분할은 배관 구간 단위라 같은 결함이 양쪽에 들어가지 않습니다.
