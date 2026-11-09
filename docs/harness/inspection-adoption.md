# MAEK 검사 시연 하니스 도입 결과

## 현재: Collider 재검사 및 내부 보강

주상 2개와 정비동 3개의 내부 보강을 완료했다. 최신 검증은 [내부 보강 결과](interior-adoption.md)를 참조한다.
보강 후 Collider/접근/연결 13,396개 항목, 에디터/Play 각각 247개 배관·771장 전체 실행이 통과했다.


## 이전 검증: 포스코 사진 기반 외관 보강 (2026-11-08)

고로 층별 골강판 외벽·보강 철골·입체 상부 트러스·작업층, 주변 건물 창/처마/환기구,
보조 배관 랙과 부식·오염 재질을 추가했다. 상부 트러스는 각 28개 부품이 모두 배치될 때만 수락한다. 현재 Unity 시연 장면에 적용했으며, 실제 공장
설계도 복제가 아닌 참고 사진 기반의 가상 배치다.

| 검증 항목 | 결과 |
|---|---|
| 기존 공정 및 경로 | 247개 배관, 원본 메시/Collider 보존; 6개 원본 파일 SHA-256 불변 |
| 비행 계획 | 2,376개 경로점, 4,262.77392578125m, 최종 경로 JSON 바이트 동일 |
| 추가 외관 | Collider 3,499개, 닫힌 보조 순환 회로 30개, 풍화 재질 적용 Renderer 362개 |
| 간섭 예방 | 부품 211개 분량 배치 제외; 보조 회로는 전체 단위로 거부하여 끊어진 곡관 방지 |
| 형상 검증 | 2,375개 이동 구간 swept sphere, 771개 촬영 시야 PASS |
| 전체 통합 | 에디터/Play 각각 247개 배관·771장 촬영/HTTP 분석, 오류/미분석 0 |
| 에디터 하니스 | 798개 검사 PASS, 247개 접근/이동 구간 장애물 주입과 제거 후 재통과 PASS |
| 단면 보기 | 추가 외장 숨김/복원과 Collider 유지 PASS |
| Play 이동 | 20,832단계, 최대 1.2000035047531129m 및 6.000836372375488°/단계 |
| 표면 매핑 | 에디터 39개/Play 40개 RGB 부식 후보; 현장 정확도나 정답 수가 아님 |
| 녹화 | 현재 Play 실행에서 24프레임 생성 확인; 이번 보강의 전체 경로 MP4는 만들지 않음 |
| Python | 회귀 12개 PASS, 변경 Python 파일 Ruff PASS |

검증 명령: `./scripts/run_inspection_harness.ps1`.
원본 보존 기준과 외관 검사 결과는 `visualization/realism/`, 최신 전체 실행의 증거 봉인은
`visualization/inspection_demo/evidence_seal.json`에 있다. 현재 봉인은 532개 소스/에셋을 포함한다. 이전 486개 소스 봉인은 최신 보강을
검증한 증거로 사용하지 않는다.

Play 시작 중 Unity 자체 `UnityEditor.Search.SearchDatabase.EnumerateAll`의
`ArgumentOutOfRangeException`이 한 차례 발생했다. MAEK 스택과 관련 없는 기존 편집기
인덱스 문제이며 전체 실행은 완료됐다. MAEK 촬영/분석 오류 0과 편집기 로그 무오류는 구분한다.


## 이전 검증: 247개 전체 배관 확장 (2026-11-08)

전체 247개 배관의 원래 검사 경로를 연속 연결했다. 원본 경로점 1,938개를 모두 유지했고,
유틸리티 4개 배관의 가려진 끝점 대신 중간 촬영점을 추가했다. 실제 장면 Collider를 기준으로
이동 구간을 검증하며, 배관별 촬영·분석·표면 위치 표시와 결과표를 연결했다.

| 확인 항목 | 최종 결과 |
|---|---|
| 배관 방문/분석 | 에디터와 Play 모드 모두 247/247 |
| 실제 촬영·HTTP 분석 | 두 실행 각각 771/771, 고유 촬영점 ID와 순서 일치 |
| 경로 | 2,376개 경로점, 약 4,262.77m |
| 접근/배관 간 이동 | 최초 접근 1구간 + 배관 사이 246구간 |
| 경로·가시성 생성 검사 | 3,641개 PASS |
| 에디터 통합 검사 | 772개 PASS |
| 이동 중 장애물 회귀 | 247개 접근/이동 구간 모두 장애물 삽입 시 차단, 제거 후 통과 |
| Play 모드 이동 검사 | 20,832개 작은 이동 단계, 최대 이동 1.200004m/단계·회전 6.000837°/단계 |
| 실제 촬영 시 가림/분석 오류/미분석 배관 | 두 실행 모두 0 |
| RGB 후보 표면 위치 | 에디터 17개, Play 모드 16개; 실제 렌더 이미지 기반 규칙 후보이며 동일 정답 수를 강제하지 않음 |
| 런타임 녹화 | 24프레임 저장, 2초 MP4 인코딩·디코딩 PASS |
| 회귀 테스트 | `test_inspection_bridge.py` + `test_inspection_harness.py`: 11 passed |
| 증거 해시 | 486개 소스·장면·에셋, 양쪽 실행의 촬영 PNG/분석 응답 검증 PASS |

현재 실행한 명령:

```powershell
./scripts/run_inspection_harness.ps1
.venv/Scripts/python.exe -m pytest tests/test_inspection_bridge.py tests/test_inspection_harness.py -q
.venv/Scripts/python.exe -m ruff check scripts/check_inspection_harness.py tests/test_inspection_harness.py
```

전체 하니스 명령에서 Unity 생성 → 에디터 검증 → Play 모드 검증 → 증거 해시 기록/재확인까지 PASS.
추가로 현재 Play 모드 녹화 폴더를 `scripts/encode_inspection_video.py`로 인코딩/디코딩했다.
이 2초 녹화 샘플은 캡처 시점에 기존 검출 표식이 화면 밖에 있어 표식 포함 프레임은 0이며,
전체 247개 경로를 보여주는 완성 영상으로 제공하는 자료가 아니다. 이전 41초 영상은 과거 3개
배관 버전이다. 전체 경로 영상은 `run_inspection_harness.ps1 -Record`로 별도 생성한다.

실제 Play 검증은 여러 개의 작은 이동/충돌 단계를 프레임 사이에 실행해 가속했다. 경로점이나
촬영/분석을 생략하지 않는다. 사용자 기본 재생과 녹화는 원래 속도를 유지한다.

이번 변경 파일: `MAEKInspectionTour.cs`, `BuildInspectionTour.cs`, `VerifyInspectionPlayMode.cs`,
`check_inspection_harness.py`, `run_inspection_harness.ps1`, 새 `test_inspection_harness.py`,
생성된 `inspection_tour.json`·`MAEKInspectionDemo.unity`, `unity/AGENTS.md`, 사용 안내와 실패 기록.
분석 모델과 기존 247개 배관의 형상·Collider는 변경하지 않았다.

결과: `visualization/inspection_demo/pipe_inspection_summary.csv`는 에디터 통합 검증 세션의
247개 배관별 결과다. 각 실행의 실제 좌표는 해당 세션의 `findings.json`에 있으며,
`inspection_progress.json`에 모든 촬영점의 상태를 보존했다.
시작 중 Unity 자체 `UnityEditor.Search.SearchDatabase.EnumerateAll`에서
`ArgumentOutOfRangeException` 한 건이 기록됐다. MAEK 스택의 오류는 아니었고 전체 Play 검증이
완료됐으며, 검색 인덱스/에디터 캐시는 이번 작업에서 변경하지 않았다.

유지할 경계: 771개 시점의 합성 RGB 샘플 검사다. 배관 전체 표면·보온재 내부의 완전 검사,
균열 발생 예측, 실제 드론 공력학 또는 현장 검출 정확도를 입증하지 않는다.
Python 분석 코드 변경 시 서버를 재시작하는 수동 확인은 여전히 필요하다.

---

## 아래는 최초 3개 배관 버전의 도입 기록

검증일: 2026-11-08 (Asia/Seoul).

## 판정

**대표 배관 3개의 RGB 1차 검사 기능을 보여주는 합성 시연 환경으로 적합하다.**
전경에서 연속 이동하고, 실제 촬영 PNG를 MAEK 규칙 검출기에 전달하며, 검출 픽셀을 촬영
당시 카메라에서 역투영해 해당 배관 표면에 표시한다. 영상 출력까지 검증했다.
전체 247개 배관의 자율 검사, 드론 공력학, 열화상/UT/PEC의 실측 연결,
균열 발생 예측, 현장 정확도 검증은 완료했다고 주장하지 않는다.

## 기존 규칙과 구현을 확인한 범위

`RULES.md`, `README.md`, `pyproject.toml`, 기존 CI, camera segment/jobs 코드,
열화상 역할 명세, Unity 런타임/생성기/패키지 설정, 최신 Blender 파일을 확인했다.
기존 Python/NumPy/Pillow와 Unity 6000.3.12f1 구조를 유지했다.
기존 사용자 수정이 있는 README와 .gitignore는 이번 작업에서 수정하지 않았다.

## 추가·변경 파일

- `maek/inspection_bridge.py`: 루프백 HTTP RGB 분석, 이미지 해시와 픽셀 근거.
- `tests/test_inspection_bridge.py`: 이미지 기반 검출, 정답 입력 무시, 음성/좌표/오류 회귀 테스트.
- `unity/MAEKInspection/Assets/MAEK/Scripts/MAEKInspectionTour.cs`: 연속 카메라,
  촬영·HTTP·응답 검증·배관 표면 매핑·결과 표시.
- 같은 폴더의 `MAEKTourRecorder.cs`: 고정 간격 PNG와 결과 메타데이터 녹화.
- `unity/MAEKInspection/Assets/MAEK/Editor/BuildInspectionTour.cs`: 경로 계획·생성·통합 검사·자동 녹화.
- 같은 폴더의 `VerifyInspectionPlayMode.cs`: 실제 Play 모드 코루틴과 녹화 검사.
- 생성 산출물: `Assets/MAEK/Source/inspection_tour.json`,
  `Assets/MAEK/Scenes/MAEKInspectionDemo.unity`, Unity가 생성한 대응 `.meta` 파일.
- `ProjectSettings/EditorBuildSettings.asset`: 새 시연 장면을 시작 장면으로 지정.
- `scripts/start_inspection_bridge.ps1`, `scripts/run_inspection_harness.ps1`,
  `scripts/check_inspection_harness.py`, `scripts/encode_inspection_video.py`.
- `requirements-demo.txt`: 선택 영상 인코더 `imageio-ffmpeg==0.6.0`.
- `unity/AGENTS.md`, `docs/inspection-demo.md`, `docs/failures/inspection-demo.md`, 이 보고서.

이전 hydraulic/CFD Unity 장면과 Blender 파일은 보존했다. 현재 기능의 실행 기준은 새 Unity
장면이며, 기존 Blender의 이동 카메라 애니메이션이 복구됐다고 주장하지 않는다.

## 실제 실행한 검증 명령과 결과

프로젝트 루트 기준:

| 명령/검사 | 결과 |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests/test_inspection_bridge.py -q` | 4 passed |
| `.venv/Scripts/python.exe -m ruff check maek/inspection_bridge.py scripts/encode_inspection_video.py scripts/check_inspection_harness.py tests/test_inspection_bridge.py` | All checks passed |
| `./scripts/start_inspection_bridge.ps1` | 루프백 health 확인, 동일 서버 중복 시작 방지 |
| `./scripts/run_inspection_harness.ps1 -Record` | 최종 전체 실행 PASS |
| 위 명령의 `MAEK.Editor.BuildInspectionTour.Run` | 28개 경로점, 27개 연속 구간 및 3개 배관 대상 검사 PASS |
| `MAEK.Editor.BuildInspectionTour.Verify` | 13개 검사 PASS, 실제 촬영 3개, 표면 연결 결과 1개 |
| `MAEK.Editor.VerifyInspectionPlayMode.Run` | 실제 Play/HTTP 경로 완료, 촬영 3개, 결과 1개, 런타임 녹화 24프레임 |
| `MAEK.Editor.BuildInspectionTour.RecordDemo` | 13개 검사 PASS, 496프레임 |
| `scripts/encode_inspection_video.py <recorded-session/video> --output <session/MAEK_inspection_demo.mp4>` | 960×540, 12fps, 41.333초, 디코딩 오류 없음, 결과 표식 포함 74프레임 |
| 같은 인코더로 Play 모드 녹화 폴더 인코딩 | 640×360, 12fps, 24프레임/2초, 디코딩 오류 없음 |
| `scripts/check_inspection_harness.py --seal` / `--evidence` | 485개 소스·장면·에셋 해시 및 촬영 증거 PASS |
| digest 함수에 변경된 소스 해시를 주입한 음성 검사 | 파일을 수정하지 않고 STALE 거부 확인 |
| 배포용 MP4 복사 후 SHA-256 비교 | 원본과 동일 |

초기 환경에서는 .venv에 pip가 없어 시스템 Python의
`python -m pip --python .venv/Scripts/python.exe install -r requirements-demo.txt`로 설치했다.
하니스의 충돌 반경 검사에는 Unity float32 직렬화 오차에 대한 1e-6 허용치를 적용했다.
초기 배치 화면 캡처는 파일이 생성되지 않아 지정 카메라 렌더 방식으로 검증했다.

## 검증 증거와 실패 기억

증거는 `visualization/inspection_demo/`에 있다.
`build_report.json`, `integration_report.json`, `play_mode_report.json`, `record_report.json`,
`evidence_seal.json`, `harness_negative_checks.json`, 각 촬영/분석/영상 메타데이터를 보존했다.
이전 카메라 순간 이동·Blender 애니메이션 소실·분석 미연결 문제와 재발 방지 검사는
`docs/failures/inspection-demo.md`에 기록했다.

MP4: `visualization/inspection_demo/MAEK_inspection_demo.mp4`.
시연 영상의 시작 화면과 검출 표식을 이미지로 확인했고 전체 영상을 디코딩 검사했다.

## 다음 변경부터의 운영

장면·경로·Collider·분석 계약 변경 뒤 `./scripts/run_inspection_harness.ps1`를 실행한다.
영상 변경을 포함하면 `-Record`를 사용한다. 과거 PASS 결과만으로 완료를 보고하지 않는다.
기존 CI의 pytest는 RGB 계약 테스트를 포함하고, Unity/GPU 통합 검증은 로컬 하니스로 실행한다.
백그라운드 영구 감시나 주기 실행은 설정하지 않았다.

효과는 다음 지표로 확인한다: 경로 단절/관통 재발 0건, 요청·이미지 오연결 수 0건,
오래된 검증 증거 수용 0건, 촬영→분석→표면 표시→녹화의 매 변경 후 통과 여부.
실제 현장 도입 판단에는 별도의 현장 데이터 정확도·오탐률·미탐률 검증이 필요하다.
