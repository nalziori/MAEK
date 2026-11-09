# 열화상 오경보 필터 실험

2026-11-07 실험은 작은 약한 wet 예측 영역을 제거하는 후처리를 검증했다. 새 shifted 600장에서 정상 오경보 115/210→36/210, wet 이미지 재현율 72/188→65/188이었다. 점추정 기준은 통과했지만 재현율 보존의 신뢰구간 기준은 실패했다. 기본 탐지기는 유지한다.

## 명시적으로 후보 사용

```python
from maek.thermal_filter import detect_ir

# temperature: Celsius 2D array; pipe_mask: boolean array, same shape.
prediction = detect_ir(cfg, temperature, pipe_mask,
                       candidate="wet_width14_area100")
```

`candidate`를 생략하면 기존 baseline이다. 후보는 wet 영역의 배관 가로 폭 <14px 또는 면적 <100px이면 제거하되 주변 배관보다 온도 중앙값이 4°C 이상 높은 영역을 보존한다. damage/steam 예측은 그대로 둔다. 이 픽셀 기준은 320×256 합성 영상에서만 검증했다. 배관 위치는 알려졌다고 가정한다.

## 단계별 실행

저장소 루트에서 PowerShell로 실행한다. 아래 명령은 새로운 결과 폴더에서 개발→선택→시험을 수행한다. 기존 결과를 덮어쓰지 않으며 코드·설정·프로토콜이 중간에 바뀌면 실패한다.

```powershell
$resultDir = '../outputs/maek-c/fp-followup-reproduction'
New-Item -ItemType Directory -Path $resultDir -ErrorAction Stop
Copy-Item '../outputs/maek-c/fp-followup-20261107-verified/protocol.md' "$resultDir/protocol.md"
& ./.venv/Scripts/python.exe scripts/evaluate_thermal_filter.py --stage develop --out $resultDir
& ./.venv/Scripts/python.exe scripts/evaluate_thermal_filter.py --stage select --out $resultDir
& ./.venv/Scripts/python.exe scripts/evaluate_thermal_filter.py --stage test --out $resultDir
```

이는 같은 시드의 재현 실행이며 새로운 미공개 시험이 아니다. 실험을 변경할 때는 별도 사전 기준과 아직 보지 않은 시험 표본을 준비한다. 원인 분석 실행기는 `scripts/diagnose_thermal_components.py --seed 20261109 --count 240 --out <새 JSON 경로>`이며 `--ablation`을 추가하면 요인 제거 실험을 수행한다.

```powershell
& ./.venv/Scripts/python.exe -m pytest tests/test_thermal_filter.py tests/test_thermal_validation.py tests/test_thermal_dataset.py tests/test_thermal_rules.py -q
```

관련 18개 테스트 통과. 정확한 분모·95% 구간·한계는 [실험 보고서](../../outputs/maek-c/fp-followup-20261107-verified/report.md), [성능표](../../outputs/maek-c/fp-followup-20261107-verified/performance.csv)에 있다. 로컬 CPU로 실행하며 코랩은 필요하지 않다.
