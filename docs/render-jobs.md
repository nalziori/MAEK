# Camera 렌더 잡(render job) 스키마

`python -m maek camera-jobs --n 300`이 `data/camera/jobs.json`을 만든다. 이 JSON이 렌더러(현재 2D
절차적 `maek/camera/composite2d.py`, 이후 Unity/Blender)와의 계약이다. 렌더러는 잡 하나당
이미지 1장과 클래스 마스크 1장을 만든다.

```json
{"schema_version": 1, "jobs": [ <job>, ... ]}
```

## job

| 필드 | 설명 |
|---|---|
| `job_id` | `J000000` 형식 고유 ID (파일명으로 사용) |
| `segment_id` | 네트워크 구간 ID (`segments.csv`) |
| `image_size` | 정사각 이미지 한 변 px (`camera.image_size`) |
| `negative` | 보이는 결함이 없으면 true (마스크는 비어 있어야 함) |
| `pipe.od_mm` / `material` / `insulated` | 배관 외경, 재질(`carbon_steel`/`stainless`/`pvc`), 보온(클래딩) 여부 |
| `pipe.width_frac` | 이미지 크기 대비 배관 외경 폭 (0~1) |
| `pipe.tilt_deg` | 배관 축의 이미지 기울기(시점) |
| `pipe.view_center_m` | 이미지 중심의 구간 내 위치(m) |
| `pipe.view_clock_deg` | 카메라가 바라보는 원주 방향(시계 각도, 0=상단) |
| `defects[]` | 이미지에 보이는 결함 (아래) |
| `env.brightness` | 조명 배율 |
| `env.dust` / `env.steam` | 분진 / 증기 불투명도 (0~1) |
| `env.blur_sigma` | 가우시안 블러 σ (px) |
| `env.noise_sigma` | 센서 노이즈 σ (0~1 스케일) |

## defects[]

| 필드 | 설명 |
|---|---|
| `defect_id` | `defects.csv`의 ID |
| `kind` | `external_corrosion` / `cui`(외관 징후 있는 것만) / `flange_leak` |
| `class_id` | 마스크 클래스: 1 corrosion, 2 cui_sign, 3 leak_stain (0은 배경/배관) |
| `area_cm2` | 실제 면적 (ground truth) |
| `u` | 배관 축 방향 위치, 이미지 폭 대비 (0.5 = 중심) |
| `v` | 배관 폭 방향 위치, -1~1 (0 = 배관 중심선, ±1 = 가장자리) |
| `w`, `h` | 결함 축방향/원주방향 크기, 이미지 크기 대비. 크기는 `sqrt(area_cm2)*10 mm`에 `px/mm = width_frac*image_size/od_mm`를 곱해 구하고 원주 방향은 시점에 따라 cos로 줄임 |

좌표계는 배관 프레임이다. 이미지 좌표는 `pipe.tilt_deg`만큼 회전해 얻는다:
`x = S/2 + (u-0.5)*S*cos t - v*hw*sin t`, `y = S/2 + (u-0.5)*S*sin t + v*hw*cos t`
(`S`=image_size, `hw`=width_frac*S/2, `t`=tilt).

## 출력 (`python -m maek render2d`, `scripts/produce_data.py`)

`images/*.png` 또는 `images/*.jpg`, `masks/*.png`(값=클래스 ID), `labels/*.txt`(YOLO-seg: `class x1 y1 x2 y2 ...`,
정규화 좌표, 클래스는 0부터이므로 mask 값-1), `train.txt`, `val.txt`, `dataset.yaml`.

- `render2d` CLI 기본값은 PNG이고 `dataset.yaml`의 `path:`가 출력 폴더 절대 경로다. 릴리스(`produce_data.py`)는
  JPEG(품질 92)이고 `path: .`다. 둘 다 `composite2d.render_all(image_format="png"|"jpg", workers=N,
  relative_yaml=...)`로 만든다. 이미지별 시드가 `[seed, i]`라 workers 수와 무관하게 결과가 같다.
- `train.txt`/`val.txt`는 항상 `./images/<id>.<ext>` 상대 경로다. 학습/검증은 `segment_id` 기준 해시로 나뉘어
  (약 80/20) 같은 구간(같은 실제 결함)이 train과 val에 동시에 들어가지 않는다. 음성 이미지도 구간 단위로 묶인다.
- Ultralytics는 상대 `path:`를 YAML 폴더가 아니라 자신의 DATASETS_DIR 기준으로 해석한다. 그래서 릴리스를 어디에
  풀어도 `python scripts/train_yolo_seg.py train|val --data <압축 푼 곳>/dataset.yaml`을 쓰면 실행 시점에
  `path:`를 YAML의 절대 폴더로 바꾼 임시 YAML을 만들어 넘긴다. `ultralytics`를 직접 호출할 때는 `path:`를 직접
  절대 경로로 고쳐야 한다.
