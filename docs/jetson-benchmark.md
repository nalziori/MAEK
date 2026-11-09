# Jetson Orin Nano Super 8GB 벤치마크 실행 준비

2026-11-07: Jetson에 접근할 수 없어 **실측하지 않았다**. 이 문서는 실행 도구와 재현 절차다. Windows PC 수치를 Jetson 수치로 옮기거나 TOPS로 FPS를 환산하지 않는다. 기존 CPU 벤치마크, 모델, 결과 파일은 변경하지 않는다.

| 모델 / 실행 경로 | Jetson 지연·메모리 |
|---|---|
| 카메라 YOLO-seg PyTorch CPU FP32 | 미측정 |
| 카메라 YOLO-seg PyTorch CUDA FP32 / FP16 | 미측정 |
| 카메라 YOLO-seg TensorRT FP32 / FP16 | 미측정 |
| Tiny1DCNN CPU FP32 / CUDA FP32·FP16 | 미측정 |

기본 카메라 가중치는 `../outputs/maek-c/models/yolov8n-seg.pt`이며 COCO 사전학습 모델이다. MAEK 녹·결함 분할 학습 모델이 아니므로 이 측정으로 결함 정확도를 주장할 수 없다. Tiny1DCNN은 `maek.onboard_models.make_ut_model()`과 같은 구조·seed 0 임의 가중치이며 계산 비용만 측정한다. 실제 학습 checkpoint를 사용하는 경우 `--ut-weights`에 순수 `state_dict`를 주고 `--weights-provenance`에 학습 출처를 명시한다. 열화상 YOLO 입력 전처리는 이 카메라 벤치마크에 포함되지 않는다.

Tiny1DCNN은 실제 CPU FP32 `state_dict`의 텐서 이름을 정렬하고 각 이름·shape·dtype·연속 bytes를 길이와 함께 SHA256에 넣은 `model_state_sha256`를 기록한다. seed만 같고 실제 값이 달라지는 경우도 식별하며, FP16/device 변환 전에 계산하므로 정밀도 간 동일 가중치를 대조할 수 있다. 이 값은 `protocol`에도 포함하여 3회 run 간 동일성을 검증한다. checkpoint 파일의 `weights_sha256`와 구분한다. 임의 가중치는 파일 해시가 `null`이어도 실제 state 해시는 존재한다. YOLO는 원본 파일 해시를 사용하고 `model_state_sha256`는 `null`이다.

## 1. 장치와 환경 확인

```bash
python scripts/benchmark_jetson.py --probe > jetson-probe.json
cat /proc/device-tree/model
cat /etc/nv_tegra_release
sudo nvpmodel -q --verbose
sudo jetson_clocks --show
```

`--probe`는 읽기 전용이며 PC에서도 사용할 수 있다. Jetson Orin Nano·Linux ARM64·L4T 확인이 없으면 실제 벤치마크 실행은 거절한다. 이 식별만으로 8GB SKU와 Super 모드까지 인증하지는 않는다. 장치 라벨, 출력된 DRAM 용량, JetPack/L4T, 전력 모드를 사람이 확인해야 한다. 모드 번호는 JetPack과 보드 구성에 따라 다르므로 `nvpmodel -m 0` 같은 명령을 자동 실행하지 않는다. 전력 설정을 변경한다면 해당 릴리스의 NVIDIA 문서를 따라 설정하고, 재부팅 요구 여부를 확인한 뒤 probe를 다시 저장한다. 팬·히트싱크, 실내 온도, 전원 어댑터, 헤드리스/GUI 여부, 백그라운드 부하를 기록한다. `--cooling`, `--power-supply`는 실제 설명을 입력해야 한다.

도구는 Python/package 버전, CUDA build, cuDNN, GPU 이름·compute capability, L4T, dpkg의 JetPack/TensorRT 버전, `nvpmodel`, `jetson_clocks --show` 출력을 저장한다. 읽기 권한 부족은 오류 문자열로 남는다. 그러면 위 `sudo` 조회 결과를 별도 보관한다. 벤치마크가 전력·클록을 바꾸지는 않는다.

## 2. JetPack에 맞는 설치

먼저 대상 장치의 JetPack/L4T와 Python 버전을 확인한다. NVIDIA가 해당 조합에 배포하는 PyTorch wheel 또는 컨테이너를 사용하고 대응 torchvision, CUDA, cuDNN, TensorRT 조합을 유지한다. 이 PC의 CPU 전용 가상환경이나 `requirements-benchmark.txt`를 그대로 설치하지 않는다. PyPI의 일반 torch로 NVIDIA wheel을 덮어쓰지 않는다. wheel 설치 전에 NVIDIA 문서의 버전별 사전 의존성을 확인한다. 모든 JetPack에 통하는 고정 설치 명령은 제공하지 않는다.

NVIDIA PyTorch 설치 후 Ultralytics/Pillow/NumPy/psutil을 설치하되, 기존 torch·torchvision·numpy 버전을 constraints에 고정하여 먼저 `pip install --dry-run`으로 교체 여부를 확인한다. TensorRT Python 패키지는 대상 JetPack의 설치 경로가 사용되는지 확인한다. 검증한 버전은 `pip freeze`로 보관한다. 현재 코드는 PC의 Ultralytics 8.4.204 API 구조를 참고했으며 Jetson runtime 통합 실행은 아직 검증되지 않았다. 기존 predictor API와 다른 릴리스면 오류를 해결하고 별도 출력 경로로 다시 측정한다.

```bash
python -c 'import torch, torchvision; print(torch.__version__, torchvision.__version__, torch.version.cuda, torch.cuda.is_available()); print(torch.cuda.get_device_name(0))'
python -c 'import tensorrt; print(tensorrt.__version__)'  # TensorRT를 사용할 때
python -m pytest tests/test_jetson_benchmark.py -q
```

공식 근거: [NVIDIA PyTorch for Jetson 설치](https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform/index.html), [NVIDIA Jetson Linux r36.4.4 전력·성능](https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/SD/PlatformPowerAndPerformance/JetsonOrinNanoSeriesJetsonOrinNxSeriesAndJetsonAgxOrinSeries.html). 실제 L4T가 다르면 해당 릴리스 문서를 선택한다.

## 3. 동일 입력과 측정 범위

대상 장치에 `maek-camera.zip`, `maek-ut.zip`, 모델, 이 저장소를 복사한다. ZIP 전체 SHA256 및 실제 선택 입력의 dtype·shape·bytes SHA256를 각 run에 저장한다. 카메라는 `camera/train/train.txt` 정렬 후 첫 12장, UT는 `ut/train/ut_angle.npz`의 `signals[0:12]`를 사용한다. 이전 CPU 도구와 입력 선택은 같지만 카메라 model-only가 기존 PIL square resize에서 **실제 predictor의 square letterbox**로 바뀌었으므로 이전 model-only 시간과 완전히 같은 프로토콜로 취급하지 않는다.

- 공통: batch 1, 기본 CPU thread 1, scope별 warmup 10회 후 100회, 설정마다 서로 다른 Python process로 3회 순차 실행. TF32와 cuDNN autotune 비활성화. 동시 학습·벤치마크 금지.
- model-only: 실제 초기화·fusion된 predictor backend에 이미 device에 있는 tensor를 입력. 모델 출력 생성까지; 전후처리와 host 복사 제외.
- end-to-end: RAM의 원본 BGR 이미지/float32 신호에서 시작하여 전처리, H2D, 모델, YOLO 후처리, 결과 D2H까지. 파일 읽기·카메라 취득·로봇 통신 제외. UT는 raw amplitude, 정규화 없음.
- CUDA는 각 sample 앞뒤 `torch.cuda.synchronize()`를 호출하여 GPU 완료까지 wall time으로 측정. FP16은 CUDA에서만 허용하고 실제 backend·입력·PyTorch parameter dtype/device를 확인. YOLO BatchNorm 잔여 수를 검사하여 fusion 상태를 기록한다.
- 모든 raw latency와 p50/p95, 실제 wall time throughput을 저장한다. 단순 `1000 / p50`은 별도 참고값이며 지속 처리율과 같지 않다. 3회 중 최악 p95와 각 회 분산을 함께 보고한다.
- 10ms 주기의 process RSS와 system available RAM을 분리한다. CUDA allocator allocated/reserved는 PyTorch 범위이며 TensorRT 전체 사용량이 아니다. Jetson은 공유 DRAM이므로 RSS+CUDA+시스템 사용량을 더하지 않는다. 샘플 사이 짧은 peak는 누락 가능하다. 메모리 2GiB 판정을 자동으로 만들지 않는다.

각 worker가 실행되는 동안 parent가 `tegrastats --interval 100` 원문을 저장한다. RAM/SWAP, 온도, GR3D/CPU clock, 전력을 확인하고 지속 부하에서 클록 하락·열/전력 제한 징후를 별도 검토한다. 도구 부재, 권한 오류 또는 빈 로그를 정상 측정으로 간주하지 않는다. `collection-status.json`은 로그 유무만 확인하며 throttling 부재를 인증하지 않는다. 공식 옵션과 필드 정의는 [NVIDIA tegrastats](https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegrastatsUtility.html)를 따른다.

## 4. 실행 예시

아래 `DATA`, `WEIGHTS`, 냉각·전원 설명을 대상 장치의 실제 값으로 바꾼다. 출력 폴더는 새 경로여야 한다.

```bash
DATA='/path/to/data-v3 (합성 데이터 최신)'
WEIGHTS='/path/to/yolov8n-seg.pt'
python scripts/benchmark_jetson.py --data "$DATA" --weights "$WEIGHTS" --model yolo --size 320 --device cpu --precision fp32 --cooling 'actual fan/heatsink/ambient' --power-supply 'actual adapter' --output runs/yolo320-cpu-fp32
python scripts/benchmark_jetson.py --data "$DATA" --weights "$WEIGHTS" --model yolo --size 320 --device cuda:0 --precision fp32 --cooling 'actual fan/heatsink/ambient' --power-supply 'actual adapter' --output runs/yolo320-cuda-fp32
python scripts/benchmark_jetson.py --data "$DATA" --weights "$WEIGHTS" --model yolo --size 320 --device cuda:0 --precision fp16 --cooling 'actual fan/heatsink/ambient' --power-supply 'actual adapter' --output runs/yolo320-cuda-fp16
python scripts/benchmark_jetson.py --data "$DATA" --model ut --device cpu --precision fp32 --cooling 'actual fan/heatsink/ambient' --power-supply 'actual adapter' --output runs/ut-cpu-fp32
```

YOLO는 `--size 640`도 같은 방식으로 별도 경로에 반복한다. UT는 CUDA FP32/FP16도 각각 수행하며 입력 길이는 항상 4096이다. 기본 100회는 짧은 지연 표본이므로 지속 5FPS 운용·열평형을 검증하려면 `--repeats`를 충분히 늘린 별도 장시간 실험이 필요하다. 실제 반복 시간을 보고하고, 짧은 실험 통과를 현장 안정성 보장으로 쓰지 않는다.

## 5. TensorRT는 먼저 변환하고 나중에 측정

엔진은 하드웨어/runtime에 의존한다. **대상 Jetson에서**, 측정과 분리된 작업으로 만들고 export 로그를 보관한다. CPU PC에서 만든 엔진을 Jetson 실측 준비 완료로 간주하지 않는다. 자동 설치를 유발하는 Ultralytics export 의존성은 미리 설치·확인한다. 충분한 여유 메모리가 없으면 workspace를 조정하고 기록한다. 다음은 한 FP16/320 엔진 예시다.

```python
# 저장소 루트에서 별도 실행. 모델 사본이 든 준비 폴더를 사용한다.
from pathlib import Path
import json
import time
from ultralytics import YOLO
from maek.jetson_benchmark import probe, sha256

weights = Path('/path/to/engine-preparation/yolov8n-seg.pt')
expected_engine = weights.with_suffix('.engine')
manifest_path = expected_engine.with_suffix('.manifest.json')
# Ultralytics may also export an intermediate ONNX beside the model.
for target in (expected_engine, manifest_path, weights.with_suffix('.onnx')):
    if target.exists():
        raise FileExistsError(f'Use a fresh preparation directory: {target}')
export_started = time.perf_counter()
engine = Path(YOLO(str(weights), task='segment').export(
    format='engine', imgsz=320, batch=1, half=True, device=0,
    dynamic=False, nms=False, workspace=1))
export_elapsed_s = time.perf_counter() - export_started
if engine.resolve() != expected_engine.resolve() or not engine.is_file():
    raise RuntimeError('Unexpected or missing engine output; inspect export log')
manifest = dict(source_weights_sha256=sha256(weights), engine_sha256=sha256(engine),
                precision='fp16', imgsz=320, batch=1, nms=False, dynamic=False,
                workspace_gib=1, export_elapsed_s=export_elapsed_s,
                export_environment=probe())
with manifest_path.open('x', encoding='utf-8') as stream:
    json.dump(manifest, stream, indent=2, allow_nan=False)
```

```bash
python scripts/benchmark_jetson.py --data "$DATA" --weights "$WEIGHTS" --model yolo --size 320 --device cuda:0 --precision fp16 --engine /path/to/yolov8n-seg.engine --engine-manifest /path/to/yolov8n-seg.manifest.json --cooling 'actual fan/heatsink/ambient' --power-supply 'actual adapter' --output runs/yolo320-trt-fp16
```

FP32 엔진은 다른 준비 폴더에서 `half=False`, manifest `precision='fp32'`로 만든다. 640 엔진도 별도 생성한다. 기존 engine·manifest·중간 ONNX가 있으면 예시는 중단하며, 다른 export 작업을 같은 폴더에서 동시에 실행하지 않는다. `export_elapsed_s`는 모델 로드부터 export 완료까지의 전체 준비 시간이며 추론 지연과 분리한다. manifest는 원본 가중치/engine SHA256, 크기, batch, precision, dynamic/NMS 옵션이 요청과 맞아야 한다. build 당시와 실행 시의 장치 종류, L4T, CUDA build, GPU capability, 실제 import한 TensorRT 버전이 다르거나 누락되면 worker가 거절한다. manifest 일치만으로 다른 보드에 대한 engine 이식성을 보장하지 않으며, 대상 Jetson에서 새로 생성하고 실제 로드·출력을 검사한다. 실제 engine backend와 I/O tensor dtype을 검사하되 내부 layer 모두의 precision을 I/O dtype만으로 추정하지 않는다. TensorRT 버전에 따라 export FP32 내부 TF32 사용 여부도 별도로 확인해야 하며 PyTorch TF32 설정이 engine build까지 지배한다고 간주하지 않는다.

측정 전에 같은 12입력을 원본 `.pt` FP32와 후보 backend로 추론하여 유한 출력, box/mask 대응, class별 mask union IoU와 검출 수를 기록한다. 빈 출력끼리는 변환 정확도를 입증하지 않는다. NMS threshold 경계에서 검출 수가 달라질 수 있으므로 차이를 검토한다. 이는 **변환 sanity**이며 라벨 기반 정확도 평가나 MAEK 분할 성능 보장이 아니다. UT는 FP32 logits 대비 최대 절대오차와 `rtol=1e-2, atol=1e-3` allclose를 기록한다. 차이를 검토하지 않은 엔진은 배포하지 않는다. 공식 export/inference API: [Ultralytics TensorRT](https://docs.ultralytics.com/integrations/tensorrt/).

## 6. 결과 회수와 검증

성공한 실행 폴더에는 `probe.json`, `run-1..3.json`, `worker-1..3.log`, `tegrastats-1..3.log`, `collected.json`, `collection-status.json`, `latency.csv`가 생긴다. 폴더 전체를 PC로 복사한다. raw JSON만 회수했다면 새 폴더에서 다음 명령으로 검증·수집한다. 이미 summary가 있는 폴더는 덮어쓰지 않고 실패하므로 기존 결과를 그대로 연다.

```bash
python scripts/benchmark_jetson.py --collect /path/to/new-raw-results-folder
```

수집기는 3회 누락·중복, 입력/가중치/프로토콜/소스 drift, raw latency와 p50/p95 불일치, 비Jetson 결과를 거절한다. PC에서 수집 가능하며 모델을 실행하지 않는다. 다른 device/precision 폴더를 비교할 때 입력·가중치 해시, 설치 버전, 전력·냉각 조건, preprocessing 규약을 다시 대조한다. 정확도는 기존 별도 데이터 평가, 실행 속도는 이 표로 구분한다. 실제 Jetson 준비가 끝나기 전까지 결과 표의 수치는 모두 미측정이다.
