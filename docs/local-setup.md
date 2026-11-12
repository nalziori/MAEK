# MAEK AI 모델 직접 실행 안내

2026-11-12 기준. Windows PC 한 대에서 MAEK의 AI 모델 세 개(부식, 열화상, 초음파 피팅)를 직접 돌려 보는 방법입니다.

## 요약

따로 받으셔야 할 `.env`나 비공개 `yaml` 파일은 없습니다. API 키를 쓰지 않고, 설정 파일은 모두 저장소에 들어 있습니다. 모델 가중치는 용량 때문에 git 대신 GitHub Release에 올려 두었으므로, 아래 순서대로 내려받으면 됩니다.

| 모델 | 하는 일 | 가중치 | 처리 시간(CPU) |
| --- | --- | --- | --- |
| 부식 YOLOv8n-seg (E4) | 배관 사진에서 부식·CUI 흔적·누설 얼룩 영역 분할 | Release `best.pt` | 이미지당 약 0.12초 |
| 열화상 YOLOv8s (sim_pipe_S) | 배관 열화상에서 증기 누설 열점 검출 | Release `sim_pipe_yolov8s_640_S.pt` | 이미지당 약 0.14초 |
| 초음파 피팅 1D-CNN (cnn_dr) | 초음파 A-scan 파형에서 내부 피팅 판정 | 저장소에 포함(ONNX) | 32건에 약 0.5초 |

아래 순서는 2026-11-12에 실제로 실행해 확인했습니다. GPU는 필요 없습니다.

## 준비물

| 항목 | 권장 | 비고 |
| --- | --- | --- |
| OS | Windows 10/11 64비트 | CPU로 실행 |
| Python | 3.10 | [python.org](https://www.python.org/downloads/release/python-31011/)에서 설치. "Add python.exe to PATH" 체크 |
| Git | 최신 | [git-scm.com](https://git-scm.com/download/win). 없으면 [저장소](https://github.com/nalziori/MAEK)에서 Code → Download ZIP |
| 디스크 | 약 3GB | PyTorch, ultralytics, 가중치 |
| 인터넷 | 설치할 때만 | 설치 후에는 오프라인으로 실행 |

사내망 프록시 때문에 `pip install`이나 다운로드가 막히면 사내 IT에 프록시 주소를 받아야 합니다.

## 1. 설치 (처음 한 번)

PowerShell을 열고 차례로 실행합니다.

```powershell
git clone https://github.com/nalziori/MAEK.git
cd MAEK
py -3.10 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements-train.txt -r UT/requirements.txt onnxruntime
```

- `activate`는 새 창을 열 때마다 다시 실행합니다. 프롬프트 앞에 `(.venv)`가 보이면 정상입니다.
- `activate`가 "스크립트를 실행할 수 없습니다"로 막히면 먼저 `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`를 실행합니다.
- 설치는 네트워크에 따라 10~20분 걸립니다.

## 2. 모델 가중치 받기 (처음 한 번)

```powershell
mkdir models
$b = "https://github.com/nalziori/MAEK/releases/download"
Invoke-WebRequest "$b/e4-20261109/best.pt" -OutFile models/best.pt
Invoke-WebRequest "$b/models-20261110/sim_pipe_yolov8s_640_S.pt" -OutFile models/sim_pipe_yolov8s_640_S.pt
Get-FileHash models\*.pt
```

마지막 줄의 해시가 아래와 같으면 파일이 온전히 받아진 것입니다.

| 파일 | SHA-256 |
| --- | --- |
| `best.pt` | `5c836f8af95c1fbee2b7478e25536dd12a20c36cb03b297f3bbd12f7d74cd63a` |
| `sim_pipe_yolov8s_640_S.pt` | `670fde808c69fc7b4ad9c97f6e5f6c4448c725e34ecf282f43c63a77c8f0de56` |

초음파 피팅 CNN은 ONNX로 변환한 파일(`site/sim/data/pitting_cnn.onnx`)이 저장소에 들어 있어서 따로 받지 않습니다.

## 3. 모델 실행

아래 명령은 모두 `MAEK` 폴더에서 `(.venv)`가 켜진 상태로 실행합니다. 먼저 이 두 줄을 실행해 둡니다.

```powershell
$env:OMP_NUM_THREADS = "1"   # 결과 재현용 스레드 고정
$env:PYTHONUTF8 = "1"        # 한글 출력 깨짐 방지
```

### 3-1. 부식 모델

```powershell
yolo segment predict model=models/best.pt source=site/sim/data/rgb_input.jpg
```

결과 이미지는 `runs\segment\predict\` 폴더에 저장되며, 찾은 영역이 색으로 칠해지고 클래스와 확신도가 표시됩니다. 샘플 이미지 대신 다른 이미지나 폴더를 `source=`에 넣어도 됩니다.

여러 장으로 시험하려면 학습 데이터와 같은 생성기로 정답이 있는 이미지를 만들어 돌립니다.

```powershell
python -m maek camera-jobs --n 12 --seed 7 --out data/samples
python -m maek render2d --seed 7 --out data/samples
yolo segment predict model=models/best.pt source=data/samples/camera/images
```

12장(결함 7장, 정상 5장)이 10초 안에 만들어집니다. 정답은 `data\samples\camera\labels\`에 있습니다(빈 파일은 정상, 0=부식, 1=CUI 흔적, 2=누설 얼룩). 2026-11-12 실행에서는 12장 모두 정답과 일치했습니다. `--seed` 값을 바꾸면 다른 이미지가 나옵니다.

### 3-2. 열화상 모델

```powershell
yolo detect predict model=models/sim_pipe_yolov8s_640_S.pt source=site/sim/data/ir_input.png
```

결과는 `runs\detect\predict\`에 저장됩니다. 샘플에서는 열점(hot_spot) 1건을 찾습니다.

### 3-3. 초음파 피팅 CNN

```powershell
python scripts/predict_pitting.py
```

예제 A-scan 32건(`UT/examples/ascan.npz`)에 대해 건별 피팅 확률과 판정을 출력합니다. 2026-11-12 실행 결과는 14건이 피팅으로 판정됐고, 기존 MLP 앙상블의 판정과 31/32건이 일치했습니다. 다른 파일은 `python scripts/predict_pitting.py 파일.npz`로 실행하며, `RF` 배열이 (건수, 4096) 형태이고 100MHz로 샘플링된 파형이어야 합니다.

## 입력에 관한 참고

세 모델 모두 MAEK 합성 데이터로 학습했습니다. 그래서 실제 현장 사진을 넣으면 결과가 학습 데이터 때보다 떨어질 수 있습니다.

- 부식 모델: 일반 RGB 사진을 그대로 넣으면 됩니다.
- 열화상 모델: 온도를 inferno 색상표(검정-보라-주황-노랑)로 칠한 이미지를 기준으로 학습했습니다. 다른 색상표의 열화상 카메라 이미지는 인식률이 떨어질 수 있습니다.
- 피팅 CNN: 100MHz, 4096 샘플 A-scan 형식에 맞춘 데이터만 받습니다.

## 설정 바꾸기

| 바꾸려는 것 | 위치 | 방법 |
| --- | --- | --- |
| 검출 기준(확신도) | 명령 뒤 | `conf=0.5`처럼 추가(기본 0.25) |
| 합성 데이터 파라미터 | `config/default.yaml` | 파일을 고치거나 명령 뒤에 `--set 키=값` 추가 |
| 현장 시나리오(광양·포항·증기) | `config/scenarios/*.yaml` | 명령 뒤에 `--scenario 이름` 추가 |

## 자주 막히는 곳

| 증상 | 해결 |
| --- | --- |
| `py`를 찾을 수 없음 | `python -m venv .venv`로 대신합니다(`python --version`이 3.10인지 확인) |
| `yolo`를 찾을 수 없음 | `(.venv)`가 켜져 있지 않은 상태입니다. `.venv\Scripts\activate`를 다시 실행합니다 |
| `pip install`이나 `Invoke-WebRequest`가 연결 오류 | 사내 프록시 문제. 사내 IT에 문의 |
| 해시가 표와 다름 | 다운로드가 중간에 끊긴 것입니다. 파일을 지우고 다시 받습니다 |
| 한글이 깨져 출력됨 | `$env:PYTHONUTF8 = "1"` 실행 후 다시 실행 |
| 결과 폴더가 `predict2`, `predict3`…로 늘어남 | 실행할 때마다 새 폴더가 생기는 것이 정상입니다 |
