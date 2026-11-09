# MAEK 연속 드론 검사 시연

이 환경은 합성 제철소를 촬영하고 실제 MAEK RGB 부식 규칙 검출기를 실행하는 기능 시연이다.
학습 모델의 현장 정확도, 균열 발생 예측, 실제 드론 비행 역학을 입증하는 환경은 아니다.
기존 압력·유량·CFD 장면을 보존하고 별도 `MAEKInspectionDemo.unity`를 생성한다.

## 포스코 사진 기반 외관 보강

`EnhanceSteelworks.Apply`와 `EnhanceInteriors.Apply`가 설비·외장·배관 랙·내부 작업 설비를
먼저 배치한다. 드론 경로·촬영 시야·전경 사진을 보존하기 위해 설비를 제외하는 조건은
제거했다. 공정 배관의 물리적 연결과 사람의 통로는 계속 보호한다. 포스코 사진과 공개
계통을 참고한 가상 배치이며 실제 현장 설계도·실측 배치의 복제가 아니다.

그 뒤 `SiteInspectionPlanner`가 기존 요구 촬영점마다 기체·여유 공간 간섭, 대상 표면 가림,
현재 위치에서의 연속 이동 경로를 검사한다. 반경 0.24m 가상 기체와 여유 0.10m를 합한
0.34m로 이동을 검사한다. 경로 탐색은 제한된 격자·노드 예산을 사용하므로 `no_route`는
그 설정에서 경로 미확보를 뜻한다. 실제 비행 불가·작업 허가 판정을 뜻하지 않는다.
[근거와 가정](references/drone-access-layout-20261109.md)을 참조한다.

기존 247개 배관과 771개 요구 관측은 유지하지만, 모두 촬영하도록 강제하지 않는다.
새 경로 `Source/site_inspection_tour.json`은 접근 가능한 관측만 예약한다. 추가 계통은
`site_supplementary_tour.json`을 사용한다. 원래 `inspection_tour.json`과 6개 동결 입력은
과거 기준으로 보존하며 새 환경의 실제 비행 경로로 소개하지 않는다.

`site_access_audit.json`은 배관·관측점별 접근 판정과 사유, 계획 전후 고정 설비 해시를 남긴다.
서로 다른 가짜 경로를 입력해도 외장 배치 해시가 같은지 재생성으로 확인한다. 새 경로는
설비를 이동·삭제하지 않으며 이동·시선 검사는 예약된 관측에만 수행한다. 요구 관측은
`accessible` 또는 `blocked_clearance`·`occluded`·`no_route`로 빠짐없이 분류한다.

관측이 없는 배관은 `미관측·검사보류`, 일부만 유효하게 관측한 배관은 `부분 관측·검사보류`다.
후보가 있는 일부 관측도 `candidate_incomplete`로 보류를 유지한다. 경로 완료와 배관 전체
검사 완료를 구분하며, 미관측 구간의 RGB 이미지·분석 결과를 만들어 채우지 않는다.
고정 현장 배치와 기하학적 접근성 검증이며 비행 역학·전파·온도·풍속·현장 허가는 미검증이다.

## 제선 공정과 검사 역할 안내

`Source/process_context.json`과 `MAEKProcessContext`가 고로 제선 흐름, 선택 배관의 계통 흐름,
검사 역할과 후속 확인 항목을 표시한다. P 키로 안내 패널을 접을 수 있다.
주요 검사 후보는 냉각수·고로가스·세정수·슬러리 138개이며, 결과표는 이를 기본 표시하고
버튼으로 전체 247개로 전환한다. 전체 관리 대상은 247개이며 실제 촬영·분석은 접근 가능한 예약 관측에 한정한다.
훈련 루프 4개와 독립 질소·계장공기 7개는 실제 고로 공급 계통과 구별한다.

압력 패널과 녹화 메타데이터에는 현장 미보정 가정 계산임을 표시한다. 송풍기 압력 상승
3.0 kPa, 공통 내경/외경 비, 냉각수 등온 가정은 실제 고로 운전값으로 보정한 결과가 아니다.
질소 퍼지/실링·산소 부화·PCI·풍구별 상세 냉각 계통은 현재 시연 범위 밖임을 표시한다.
확인되지 않은 운전값으로 계산 결과를 바꾸거나 미연결 계통을 연결 완료로 소개하지 않는다.

각 세션의 `follow_up.json`은 247개 배관별 촬영 수·관측 상태·요청 ID와 후속 확인 안내를
저장한다. RGB 후보가 있어도 요구 관측이 부족하면 `candidate_incomplete`, 유효 관측이 없으면
`inspection_deferred`, 일부만 관측되면 `inspection_partial`로 남긴다. 훈련/독립 시험대 표시는 후속 안내에도 유지한다.
이는 증거 기반 후속 확인 목록이며 실제 결함 확정이나 MAEK 위험 순위 최적화 결과가 아니다.
녹화 프레임에는 `processContext`와 `numericalScope`가 포함되어 인코딩 영상에도 반영된다.

## 사고 계통과 작업자 위험 확인

공정 안내(P)의 사고 배관 확인 탭은 실제 사고 보도의 산소 공급관·소결 집진/배기 덕트·
화학물질 관련 사고·스팀 작업 구역을 구분한다. 현재 장면에는 해당 사고 회로가 없으며
냉각수/BFG/열풍 등 기존 가상 배관을 실제 사고 위치로 표시하지 않는다.
14개 계통의 작업 위험 맥락과 검사 한계를 표시하고, 기본 결과표는 전체 247개를 보여준다.
`follow_up.json`의 `workPermissionStatus`는 항상 `not_assessed`다.
관측 결과·밸브 닫힘·유량 0은 가스 없음·잔여 강도·작업 허가의 근거가 아니다.
[사고 계통 확인과 수정 기록](reviews/worker-accident-pipe-correction-20261109.md)을 참조한다.

## 실행

### 기존 대시보드와 Unity 가상 드론 연결

프로젝트 루트에서 `./scripts/start_inspection_bridge.ps1`을 실행하고
<http://127.0.0.1:8765/dashboard>를 연다. 서버는 기존 `dashboard/` 파일을 제공하고
응답에만 라이브 어댑터를 삽입한다. 기존 화면·저장 검사 자료·NDT 로컬 등록은 보존된다.
다른 경로를 사용할 때는 `.venv/Scripts/python.exe -m maek.inspection_bridge --port 8765 --dashboard-root PATH`로 실행한다.

Unity 6000.3.12f1에서 `MAEKInspectionDemo.unity`를 열고 Play를 누르면 가상 드론의
위치·원본 RGB 영상·분석 기록이 연결된다. 기본 라이브 미리보기는 초당 2회 갱신되는 PNG이며
영상 통신 프로토콜이나 실물 드론 연결은 아니다.
`MAEKDashboardLink.Initialize`가 `Application.runInBackground=true`를 설정해 대시보드로
전환했을 때도 Unity의 백그라운드 실행을 허용한다. 이 추가 수정은 Unity 6000.3의 C# 컴파일러와
프로젝트 참조 설정으로 런타임 어셈블리 컴파일을 통과했다. 대화형 Play 재검증은 사용자의
PR만 진행 요청에 따라 중단했다.
`V`로 추적 시점을 전환해도 분석 카메라는
원래 FPV 촬영 포즈를 유지한다. 가상 드론 외형과 Collider는 기체 반경 0.24m 안에 있으며,
이동 경로는 여유 0.10m를 더한 반경 0.34m로 검사한다.

대시보드의 `실시간 RGB`와 `저장 자료`는 별도 관측이다. 저장된 열화상/NDT를 라이브 RGB와
동시 측정한 센서 결과로 취급하지 않는다. 분석 상자는 요청 ID·원본 SHA-256·크기를 확인한
정지 영상에만 표시한다. 움직이는 원본 영상에는 이전 프레임의 상자를 붙이지 않는다.
연결이 끊기거나 카메라를 사용할 수 없으면 라이브 영상과 제어를 보류한다.
추가 O2/SINTER 배관에 대응하는 저장 자료가 없으면 다른 배관의 자료를 대신 표시하지 않는다.

시나리오는 **Unity 게임 화면 우측 하단의 `검사 시나리오` 버튼**에서 선택·적용한다.
열린 목록에서 11개 사례 또는 전체 순차 시험을 실행한다. 대시보드에서는 시나리오 선택·
실행 및 평가 정답 패널을 제공하지 않는다. 대시보드는 관측 영상·배관 위치·분석 근거를
확인하고 일시정지·재개·녹화·시점 전환을 제어한다. 검사 범위 전환은 Unity의 T/E 버튼을 쓴다.

Unity 시나리오 선택으로 냉각수·산소·소결 RGB 부식 후보, 정상 색상 대조, 주황색 도장 오탐,
저조도, 가림, 분석 서버 장애, 카메라 장애, UT 추가 필요, IR 추가 필요를 시험한다.
정답은 별도 평가 API로만 전달하며 RGB 검출기에 주지 않는다. UT/IR 시나리오는 추가 센서가
필요함을 보이는 절차 시험이다. 내부 균열·감육·열 이상을 측정하거나 확진하지 않는다.
전체 시나리오 실행은 각 사례를 별도 세션에서 시작하므로 사례 사이의 연속 비행을 뜻하지 않는다.
기존 247개 경로와 별도 산소·소결 17스팬 경로는 각각 유지된다.

시나리오별 실제 결과는 세션의 `scenario_evaluation.json`, 통합 검증은
`visualization/inspection_scenarios/verification.json`에 기록한다. 제어 명령은 Unity의
적용 응답을 받아 상태를 표시하며, 평가가 통과해도 현장 정확도나 작업 허가를 입증하지 않는다.
Unity의 기존 녹화 기능 및 대시보드 추가 제어의 녹화 전환은 PNG 프레임과 메타데이터를 저장한다.
이 소스 변경이 과거 EXE ZIP에 자동으로 반영되지는 않는다.

### Unity와 대시보드의 실제 연동 재검증

로컬 서버와 Unity Play 실행이 모두 켜진 상태에서 다음 검증을 실행한다.
Windows의 Microsoft Edge와 Python `playwright` 패키지가 필요하다.

```powershell
./.venv/Scripts/python.exe -m pip install playwright
./.venv/Scripts/python.exe scripts/verify_live_dashboard.py
```

전체 배관 검사 모드의 실제 Unity 영상·분석·배관 매핑이 들어올 때까지 기다린 뒤,
데스크톱·모바일 화면의 분석 이미지 SHA-256과 표시 상태를 검사한다. 브라우저의
일시정지·재개 버튼을 눌러 Unity의 적용 ACK와 실제 비행 위치 변경을 확인한다.
247개 접근·관측 행, 요구/예약/보류 집계와 제공 중인 대시보드 파일 해시도 남긴다.
가짜 텔레메트리나 저장 영상 재생으로 실시간 연결을 대신하지 않는다.

자동 전체 Play 실행은 기존 `MAEK.Editor.VerifyInspectionPlayMode.Run`을 사용한다.
실행 중 다른 터미널에서 위 브라우저 검증을 함께 실행한다. 기본 대기 시간은 20분이며,
서버 주소는 `--base`, 결과 폴더는 `--output`, 대기 시간은 `--timeout`으로 지정한다.
캐시가 있는 다른 Unity 프로젝트를 사용할 때는 `--unity-project 경로`로 실행 소스·장면·
경로가 이 체크아웃과 일치하는지도 확인한다. 결과는
`visualization/inspection_scenarios/dashboard/live-날짜-시각/report.json`과 화면 PNG로 남는다.
실제 실행 실패·해시 불일치·명령 미적용·화면 오류는 종료 코드 1로 처리한다.

2026-11-09 실제 연동 세션 `20261109-175022-060`은 브라우저 4개 화면의 원본 해시와
정지·재개 ACK/위치 갱신을 통과했다. 요약은
`visualization/inspection_demo/dashboard_live_report.json`에 보존한다. 같은 세션의
`play_mode_report.json`은 664개 촬영, 24프레임 녹화, 11개 평가 ACK·미전송 0건으로 PASS다.
브라우저 보고서의 관측 집계는 촬영 중 스냅샷이며 최종 관측 집계와 구별한다.

### 주상·정비동 내부

주상 `BF1.CASTHOUSE`, `BF2.CASTHOUSE`와 정비동 `SERVICE.-97`, `SERVICE.0`,
`SERVICE.99`에 작업대, 공구함, 계측 장비 모형, 모의 검사 스풀, 조명과 통로 표시를 추가했다.
주상의 기존 검사 루프 네 개는 원래 247개 배관 목록과 비행 경로에 그대로 포함된다.
정비동의 추가 스풀은 닫힌 **냉간 훈련용 모형**이며 MAEK 분석 대상이나 압력·유량 계산
배관에 추가하지 않았다. 새 장비의 화면/게이지는 실측 결과를 표시하는 장치가 아니다.

`MAEK.Editor.AuditEnhancedColliders.Run`은 저장된 장면을 읽어 드론 이동, 실제 촬영 방식과
동일한 5×5 시선 샘플, 추가 구조물/공정 배관 간섭, 출입 통로와 작업대 접근을 검사한다.
보행 접근은 반경 0.3m·높이 1.7m 캡슐의 연속 이동으로 검사한다. 접합부에서는 중앙 광선이
옆 배관을 맞힐 수 있으므로 주변 시선까지 검사하되, 대상 배관에 실제로 닿는 시선이 있어야 한다.
`EnhanceInteriors.Apply`가 생성하는 작업대와 검사 스풀은 조립체 전체 단위로 수락/거부한다.
스풀의 모든 이음점은 저장된 Collider 변환을 사용해 다시 검증한다.

빌드 단계는 `visualization/interior_detail/after-interior-colliders.json`을 만들고 내부 사진을
자동 촬영한다. `latest_photos.txt`가 사진 폴더를 가리킨다. 바닥 도색과 인쇄된 글자만 Collider가
없는 평면이며, 바닥·표지판·계측기 본체에는 Collider가 남아 있다. CFD 단면 보기에서는 기존
외장과 함께 내부 추가 렌더러를 숨겼다가 복원한다.

프로젝트 루트에서 다음 명령으로 로컬 분석 서버를 시작한다.

```powershell
./scripts/start_inspection_bridge.ps1
```

Unity에서 `Assets/MAEK/Scenes/MAEKInspectionDemo.unity`를 열고 Play를 누른다.
전경에서 시작해 고정 설비 안에서 접근 가능한 촬영점들을 연속 방문한다. 전체 247개 배관의
요구 관측을 관리하되, 접근 가능한 시작·중간·끝 시점과 긴 구간의 추가 시점에서 촬영한다.
배관 사이도 연결 경로를 따라 이동하며 순간 이동하지 않는다. 정확한 순서·촬영 수·거리는
`Assets/MAEK/Source/site_inspection_tour.json`과 `visualization/inspection_demo/site_access_audit.json`에 기록된다.
`Space`: 일시 정지, `R`: 프레임 녹화 시작/종료, `T`: 시연 종료/시작.
전체 영상을 녹화하려면 시작 후 일시 정지, 녹화 시작, 재생 순서로 사용하거나 아래 자동 녹화를 쓴다.
기존 자유 보행과 배관별 카메라는 시연을 종료하면 복원된다.
상단에 전체 배관 분석 진행률과 촬영 수가 표시되며, `결과표`에서 배관별 대기·가림·부식 의심·
RGB 후보 없음 상태를 확인할 수 있다. `inspection_progress.json`에는 미분석 배관과 촬영별
결과가 저장된다. 샘플 촬영이며 배관 표면 전체나 보온재 내부의 검사 완료를 뜻하지 않는다.
하니스 완료 후 `visualization/inspection_demo/pipe_inspection_summary.csv`에서 에디터 통합
검증 세션의 배관별 결과를 볼 수 있다. 실제 Play 실행의 결과는 해당 실행 폴더에 별도로 저장된다.

분석 서버는 `127.0.0.1:8765`에만 바인딩하며, Unity와 같은 컴퓨터에서 실행한다.
서버가 없으면 “분석 보류”를 표시한다. 서버 시작 스크립트는 PID와 로그 위치를 출력한다.
실행을 마친 뒤 서버를 종료하려면 기록된 PID가 MAEK 서버인지 확인하고 해당 프로세스만 종료한다.
`maek/inspection_bridge.py` 또는 `maek/camera/segment.py`를 수정한 경우에는 실행 중인 분석
서버를 먼저 재시작한 뒤 하니스를 실행한다. Python 서버는 이미 import한 코드를 자동 갱신하지 않는다.

## 실제 연결 구조

1. 247개 배관 목록과 원본 검사 경로의 ID가 정확히 일치하는지 검사한다.
2. 각 배관의 모든 원본 경로점을 유지하고, 배관 간 이동은 3D 경로 계획 후 swept-sphere로 검사한다.
3. 대상 배관이 첫 표면으로 보이는 시점에서만 촬영하도록 정하고, 실제 촬영 시에도 가림을 검사한다.
4. 각 정지점에서 640×360 PNG와 촬영 위치·방향·화각·배관 ID·고유 촬영점 ID를 저장한다.
5. PNG만 로컬 Python 서버로 보내 `maek.camera.segment.segment_rust`를 실행한다.
6. 분석 응답의 요청 ID·이미지 SHA-256·크기를 확인한다. 같은 응답의 중복 적용을 거부한다.
7. 검출 픽셀을 촬영 당시 카메라에서 역투영한다. 첫 충돌 표면이 대상 배관인 결과만 표시한다.
8. 해당 표면에 부식 의심 표식과 후속 UT/PEC 검사 안내를 표시한다.

검출기에 배관 ID, 결함 정답, 예상 결과는 입력하지 않는다. 결과는 HSV 색상 기반 부식 후보이며
주황색 도장 등에 오탐할 수 있다. 무검출은 “새 RGB 후보 없음 · 건전성 보장 아님”으로 표시한다.
열화상 센서·학습 모델·UT/PEC 실측은 이 시연에 연결하지 않았다.
점검 순위 최적화나 균열 발생/성장 계산도 이번 연결의 범위가 아니다.

## 녹화

`R` 녹화는 1280×720, 24fps의 고정 시뮬레이션 간격으로 PNG와 `frames.jsonl`을 저장한다.
렌더링이 느리면 실제 녹화 시간은 길어져도 시뮬레이션 프레임은 건너뛰지 않는다.
저장 위치는 화면 하단 및 Unity 로그의 `MAEK recording saved`에 표시한다.
GUI는 녹화 후 인코더가 프레임별 실제 결과 좌표로 합성한다. 분석 입력에는 표식이 포함되지 않는다.

```powershell
# 설치 환경에 맞는 pip/uv로 선택 의존성 설치
python -m pip --python .venv/Scripts/python.exe install -r requirements-demo.txt
# FOLDER는 recording.json, frames.jsonl, 000000.png 등이 있는 폴더
.venv/Scripts/python.exe scripts/encode_inspection_video.py FOLDER --output OUTPUT.mp4
```

자동 시연 녹화는 아래 하니스의 `-Record` 옵션이다. 자동 검증 영상은 960×540, 12fps로
GPU 부담을 낮춘다. PNG 원본·촬영 메타데이터·분석 JSON·표면 좌표를 함께 보존한다.
이제 `-Record`는 247개 전체 경로를 녹화하므로 기존 3개 배관 영상보다 시간·디스크 공간이 많이
필요하다. 기존 `MAEK_inspection_demo.mp4`는 3개 배관 버전의 과거 영상이며 전체 247개 검증 증거가 아니다.

## 반복 검증

```powershell
.venv/Scripts/python.exe -m pytest tests/test_inspection_bridge.py tests/test_inspection_harness.py -q
./scripts/run_inspection_harness.ps1
./scripts/run_inspection_harness.ps1 -Record
.venv/Scripts/python.exe scripts/check_inspection_harness.py --evidence
```

실행 중인 같은 Unity 프로젝트를 닫고 하니스를 실행한다. 다른 작업을 강제 종료하지 않는다.
하니스는 Python 계약 테스트 → Unity 재생성 → 실제 RGB/HTTP/표면 매핑 통합 검증 →
소스 해시 기록 순서로 실행한다. `-Record`는 전체 경로 프레임 생성과 MP4 인코딩·디코딩도 검사한다.
별도의 Play 모드 검사는 실제 Update·코루틴·HTTP 요청으로 경로를 끝까지 실행하고,
런타임 녹화기가 결과 표시 시점에서 최소 24프레임을 저장하는지도 확인한다.
전체 Play 모드 검증은 프레임 사이에서 여러 개의 작은 이동·충돌 검사 단계를 실행해 가속한다.
경로점·촬영·분석은 생략하지 않으며 기본 사용자 재생/녹화 속도는 변경하지 않는다.
핵심 검증: 연속 위치·회전, 배관 사이 연결, 장애물 정지, 247개 배관 ID의 정확한 방문/분석 일치,
모든 계획 촬영점의 실제 PNG/분석 응답과 순서 일치, 대상 가시성, 부식 패치 검출,
첫 표면/배관 ID 일치, 촬영 포즈 사용, 잘못된 해시 거부, 서버 실패를 정상으로 오인하지 않기.

이 검증의 통과는 기능 연결을 뜻한다. 현장 검출률·오탐률을 뜻하지 않는다.
로컬 장면·서버·GPU가 필요한 통합 검증은 로컬 스크립트로 수행하고,
기존 CI의 pytest는 RGB 계약 회귀 테스트를 실행한다.

Unity·추론·장면을 바꾸지 않고 대시보드만 수정한 경우에는 전체 검증 봉인을 기준으로
새 브라우저 QA의 화면·JavaScript 검사와 7개 프런트엔드 파일 해시를 확인한다.
`scripts/check_inspection_harness.py --seal-ui QA_REPORT.json` 후 `--evidence`로 확인한다.
원래 통합 보고서·검증 세션이나 Unity/추론 소스가 달라지면 이 갱신은 거부되며 전체 하니스를
다시 실행해야 한다. 화면 변경을 이유로 이전 엔진 검증을 임의로 최신 처리하지 않는다.

카메라 캡처 구현은 Unity 공식 [Camera.Render 문서](https://docs.unity3d.com/cn/6000.0/ScriptReference/Camera.Render.html)의
RenderTexture/ReadPixels 방식을 사용한다. 에디터 배치 실행에서 화면 캡처가 저장되지 않는 경우를
피하기 위해 녹화는 지정 카메라를 직접 렌더한다.


## 산소·소결 공개 참고 계통 증설 (2026-11-09)

기존 247개 배관·6개 동결 원본·전체 드론 경로는 보존한다. E 키 또는 우측 상단 버튼으로
별도 산소 7구간과 소결 2차 집진 10구간의 연속 검사 경로를 시작한다. 전환 시 기존 검사는
종료·보존되고 별도 세션이 만들어지며 카메라는 추가 계통 전경에서 시작한다. T 키는
원래 247개 경로로 복귀·재시작한다. 두 경로 사이의 비행 연결은 주장하지 않는다.

추가 계통은 `supplementary_circuits.json`의 방향 그래프와 동일한 물리 포트에 연결한다.
소결 10구간에는 백필터·송풍기의 내부 연결을 나타내는 설비 스팬 2개가 포함된다.
추가 태그는 `MAEKSupplementaryLine`이며 원래 서비스 카탈로그와 계통 해석을 대체하지 않는다.
소결 덕트는 원료 이송·선별의 secondary 계통이며 소결 strand primary 배가스나 고로 BFG가 아니다.
산소는 공급/소비처 인입 경계까지이며 실제 풍구 산소 부화·기존 CFD 결합은 구현하지 않았다.
새 계통의 운전 압력·유량·집진 효율은 미계산이며 기존 공통 가정값을 전용하지 않는다.

촬영·HTTP RGB 분석·픽셀 해시/요청 ID·실제 표면 투영·결과 핀·후속 목록·R 프레임 녹화는
기존 `MAEKInspectionTour`를 재사용한다. 부식 후보는 실제 렌더 이미지에서 규칙으로 추출한다.
후속 검사 목록은 `workPermissionStatus=not_assessed`를 유지한다. UT/IR/PEC 측정은 새로 통합되지 않았다.
공개 원문 근거와 한계는 `docs/references/oxygen-sinter/2026-11-09/README.md`를 참조한다.

검증: `scripts/check_supplementary_circuits.py`, `tests/test_supplementary_circuits.py`,
Unity `BuildSupplementaryCircuits.Audit`, 전체 `scripts/run_inspection_harness.ps1`.
Windows 네이티브 검증은 `MAEK.exe --verify`로 247/771 이후 추가 17/17을 실제 로컬 HTTP로
실행하고 추가 경로의 표면 매핑과 프레임 녹화까지 검사한다.
