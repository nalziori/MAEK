# MAEK 합성 데이터 (v1)

`main` 브랜치의 `scripts/produce_data.py`로 만든 합성 데이터입니다. 실제 점검 데이터가 아닙니다.
자세한 내용은 `maek-network-strategy.zip` 안의 `DATA_CARD.md`를 보세요.

## 받기와 풀기

```bash
git clone --branch data --single-branch https://github.com/nalziori/MAEK.git maek-data
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
