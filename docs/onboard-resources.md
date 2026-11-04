# 탑재(온보드) 리소스 근사 측정

> **주의: 이 문서의 수치는 개발 머신의 CPU 근사값이며 실제 드론/보드 수치가 아닙니다.**
> 측정 머신은 4코어 x86 서버급 CPU입니다. 실제 임베디드 보드(예: ARM 계열 SBC)는 같은 코드가
> 수 배 ~ 수십 배 느릴 수 있으므로, 아래 "여유 배율"을 보드 감속 한도로 읽어야 합니다.

## 측정 방법

- 명령: `OMP_NUM_THREADS=1 python -m maek onboard --out data/eval` (결과 CSV: `data/eval/onboard.csv`)
- 스레드 수 1~4마다 새 프로세스를 띄워 `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`를 설정하고
  `os.sched_setaffinity`로 사용 CPU 코어 수도 제한함 (`maek/onboard.py`).
- 대상: 각 기능의 **고전 베이스라인**(학습 모델 아님)
  - ① 부식: `maek.camera.segment.segment_rust` (HSV 임계값 + 모폴로지), 입력 640x640 / 320x320, 렌더 이미지 12장
  - ② 균열: `maek.ut.detect_crack` (A-scan 4096 샘플, 게이트 검출), 60개 x 3회
  - ③ 두께: `maek.ut.estimate_thickness` + `min_thickness` (A-scan 4096 샘플), 60개 x 3회
- 지연: 항목 1개 처리 시간(ms)의 중앙값과 p95, 처리량 = 1000 / 중앙값.
- 메모리: `tracemalloc` 피크(항목 처리 중 파이썬 할당, MB)와 `resource.getrusage` 프로세스 최대 RSS(MB).
  RSS에는 측정용 데이터 렌더링과 pandas/numpy 로딩이 포함되어 **과대 추정(상한)** 입니다.
- 예산(config `onboard.*`, 둘 다 `assumption: true`): `target_fps` = 5 (프레임당 200 ms),
  `memory_limit_gb` = 2.

## 측정 결과 (1 코어 기준, 대표값)

| 기능 | 입력 | 중앙값 ms | p95 ms | 처리량 /s | tracemalloc 피크 MB | 프로세스 RSS MB | 5 fps | 2 GB |
|---|---|---|---|---|---|---|---|---|
| ① 부식 분할 | 640x640 | 64.4 | 71.1 | 15.5 | 22.7 | 157 | 통과 | 통과 |
| ① 부식 분할 | 320x320 | 14.8 | 16.9 | 67.6 | 5.7 | 157 | 통과 | 통과 |
| ② 균열 검출 | A-scan | 0.3 | 0.3 | 3566 | 0.3 | 157 | 통과 | 통과 |
| ③ 두께 추정 | A-scan | 1.1 | 1.3 | 925 | 0.4 | 157 | 통과 | 통과 |

스레드 2/3/4개에서도 거의 같았음(예: 640px 중앙값 65.9 / 70.7 / 66.3 ms). 이 베이스라인은
numpy 원소 단위 연산이라 사실상 단일 스레드로 돌기 때문입니다. 전체 표는 `data/eval/onboard.csv`
(스레드 x 기능 16행)에 있고 `python -m maek onboard`로 재생성됩니다.

## 예산 대비 판정

- 5 fps(프레임당 200 ms) 대비 여유 배율: 640px 약 3.0배(200 / 66), 320px 약 13.7배(200 / 14.6).
  즉 **이 CPU 기준 통과**이지만, 보드가 이 개발 머신보다 3배 이상 느리면 640px 분할 베이스라인은
  5 fps를 못 맞춥니다. 임베디드 ARM 코어는 3배 이상 느린 경우가 흔하므로 640px는 **보장되지 않는 것**으로 봅니다.
- UT 베이스라인(②③)은 A-scan 1개에 약 1 ms(두께 추정은 피팅에 강한 에코 열 방식으로 바꾸며 0.7 -> 1.1 ms)라 보드가 100배 느려도 5 fps 예산 안에 들어옵니다. 병목은 카메라입니다.
- 메모리: 측정 범위 최대 RSS 약 157 MB로 2 GB 한도의 8% 정도. 단, 이는 고전 베이스라인만의 값입니다.
  학습 모델(PyTorch/ONNX 런타임 + 가중치 + 활성값)은 훨씬 클 수 있어 별도 측정이 필요합니다.

## 학습형 YOLO-seg 모델

이 환경에서는 학습/추론할 수 없고, 모델 크기·파라미터 수·FLOPs를 인용할 수 있는 출처 URL을
확인하지 못했으므로(문서 사이트 접속 불가) **수치를 적지 않습니다.** 대신 실제 보드에서
`scripts/train_yolo_seg.py`의 `export`(ONNX/NCNN/TFLite 등)와 `benchmark` 단계로 다음을 측정해 이 문서에 채웁니다.

```bash
python scripts/train_yolo_seg.py export --weights best.pt --format onnx --imgsz 640
python scripts/train_yolo_seg.py benchmark --weights best.pt --data data/camera/dataset.yaml --imgsz 640
python scripts/train_yolo_seg.py benchmark --weights best.pt --data data/camera/dataset.yaml --imgsz 320
```

`benchmark`는 중앙값/p95 지연(ms), fps, 파라미터 수, 가중치 파일 크기를 JSON으로 출력합니다.
메모리는 보드에서 `/usr/bin/time -v`(최대 RSS)로 별도 확인합니다.

## 예산을 못 맞출 때의 대안

1. **해상도 낮추기**: 640 -> 320이면 이 베이스라인 기준 약 4.5배 빨라짐(66 -> 14.6 ms). 작은 결함의 검출 한계(a90)는 나빠질 수 있어 해상도별 POD를 함께 측정해야 합니다.
2. **더 가벼운 모델**: 가장 작은 YOLO-seg 계열(nano급) 사용, 정수 양자화(`--int8`)/반정밀(`--half`), 보드 전용 런타임(NCNN, TFLite 등) 변환.
3. **프레임 건너뛰기/관심영역 처리**: 5 fps 전 프레임이 아니라 배관이 보이는 영역만 크롭하거나 N프레임마다 추론.
4. **드론은 촬영만, 지상에서 처리**: 드론은 영상/A-scan을 저장·전송만 하고 지상 PC/GPU에서 분할·검출. 온보드 연산 예산은 사라지지만
   실시간 재촬영/즉시 UT 확인은 불가능하고 전송·저장 용량이 필요합니다.
5. **전·후처리 분리**: 가벼운 고전 필터(색상 임계값)로 후보 프레임만 고르고(트리아지) 학습 모델은 후보에만 실행.

## 한계

- 개발 머신 CPU 측정이며 보드의 클럭, 메모리 대역폭, 열 제한(스로틀링), OS 부하는 반영하지 않았습니다.
- RSS는 측정 데이터 생성 코드까지 포함한 상한입니다. 배포 시에는 렌더러/pandas 없이 훨씬 작게 만들 수 있습니다.
- GPU/NPU 가속 경로는 측정하지 않았습니다.
