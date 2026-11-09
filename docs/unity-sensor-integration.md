# 안전·작업자 초음파·드론 열화상 통합 소스

이 문서는 `feature/drone-thermal-dashboard` 브랜치에 함께 들어가는 Unity 소스와 실행 방법을 설명한다. GitHub 원격 푸시나 PR 병합을 수행했다는 의미는 아니다.

## 포함 범위

- 안전 게이트와 사고 대응: 검사 중단, 대체 착륙 지점, 점유 구역 회피, 지상 재승인.
- 작업자 초음파: 기준 확인 → 이동 → 표면 준비 → 접촉매질 도포 → 접촉 → 합성 A-scan 분석 및 기록.
- 드론 열화상: 기존 배관 선택 → 충돌 검사 이동 → 정지 → 대상 표면 촬영 → 합성 온도 분석.
- 메인 대시보드: 기존 RGB·부식 / 열화상 구조, 사진 확대, 사진 아래 간단한 온도 요약, 같은 배관의 UT 기록.

기존 작업자 모델·프리팹·기본 장면과 경로는 저장소에 이미 있으므로 중복 모델을 추가하지 않았다. 물리 설비와 기존 247개 배관 목록을 옮기거나 삭제하지 않는다. 안전 기능은 별도 통합 장면의 컴포넌트가 있을 때 적용되며, 원래 RGB·CFD 장면은 유지한다.

## 최초 실행

1. 저장소 루트에서 의존성을 설치한다. CUDA 환경에서는 팀 UT 안내에 따라 해당 플랫폼의 PyTorch를 먼저 설치한다.

   ```powershell
   python -m pip install -r requirements.txt -r UT/requirements.txt
   ```

2. 서비스 전용 실행을 시작하고 터미널을 열어 둔다.

   ```powershell
   python scripts/run_unity_sensor_demo.py --services-only
   ```

   RGB는 `127.0.0.1:8765`, UT는 `127.0.0.1:8766`, 대시보드·열화상은 `127.0.0.1:8894`를 사용한다. 이미 실행 중인 서비스는 호환성을 확인한 뒤 재사용하며, 종료 시 이 명령이 시작한 프로세스만 종료한다. 다른 모델이 UT 포트를 사용하면 자동으로 덮어쓰지 않고 오류를 표시한다.

3. Unity 6000.3.12f1에서 `unity/MAEKInspection` 프로젝트를 연다.

4. 메뉴 **MAEK → Thermal → Create and open integrated sensor demo**를 선택한다. 기존 `MAEKInspectionDemo.unity`에서 안전·UT·열화상 장면을 재생성한다. 생성 장면과 빌드 결과는 Git에 포함하지 않는다.

5. Unity Play에서 오른쪽 안전 패널의 정상 조건을 설정하고 지상 재승인한다. 초음파는 작업자, 열화상은 드론이 수행한다. 기본 확인 배관은 `BF1-Q005`이다.

6. Windows 실행본이 필요하면 서비스가 켜진 상태에서 **MAEK → Thermal → Verify and build thermal V6**를 실행한다. 결과는 `unity/MAEKInspection/ThermalOutput/Player/MAEK_Player.exe`에 생성된다.

7. 서비스 전용 터미널을 종료한 후 저장소 루트의 `Start_Unity_Sensors.cmd`를 실행하거나 다음 명령을 사용한다. `.cmd`는 저장소의 `.venv`를 우선 사용하고, 없으면 Windows Python Launcher를 사용한다.

   ```powershell
   python scripts/run_unity_sensor_demo.py
   ```

메인 화면: <http://127.0.0.1:8894/index.html?tab=home&pipe=BF1-Q005>

열화상 자료는 기본적으로 `data/unity_thermal/`, 서비스 로그는 `data/unity_sensor_logs/`에 저장한다. 외부의 개인 작업 폴더나 특정 사용자 Python 경로에 의존하지 않는다. 초음파 모델·예제는 저장소의 `UT/`를 사용한다.

## 구성 파일

| 영역 | 파일 |
| --- | --- |
| 안전 판단·동작 | `MAEKSafetyGate.cs`, `MAEKSafetyResponse.cs`, `MAEKSafetyDemo.cs` |
| 작업자·장비 | `MAEKWorkerUT.cs`, `MAEKUTEquipment.cs`, 기존 `MAEKInspectorVisual.cs` |
| 열화상 | `MAEKThermalDemo.cs`, `scripts/thermal_scene.py`, `config/thermal_pipe_profiles.json` |
| 장면 생성·검사 | `BuildSafetyDemo.cs`, `BuildWorkerUTDemo.cs`, `BuildThermalDemo.cs` |
| UT 분석 서비스 | `scripts/serve_worker_ut.py`, 기존 `UT/` 모델 및 예제 |
| 통합 시작 | `scripts/run_unity_sensor_demo.py`, `Start_Unity_Sensors.cmd` |

위 C# 파일은 `unity/MAEKInspection/Assets/MAEK/Scripts/` 또는 `Editor/`에 있다. 안전 게이트가 우회되지 않도록 기존 검사 시작·재개·대시보드 명령·추가 계통 선택 경로도 함께 연결했다. `.meta` 파일을 함께 유지해야 한다.

## 이번 소스 통합에서 확인한 내용

- 통합 대상의 런타임 C# 소스 31개와 Editor 소스 22개를 Unity 6000.3.12f1의 Roslyn 및 실제 Unity 참조 어셈블리로 컴파일했다. 두 어셈블리 모두 오류 0건이다. 이는 대상 소스의 컴파일 검사이며, 새 체크아웃 전체를 Unity Editor에서 다시 열어 수행한 Play-mode 검사와는 다르다.
- 기존 작업본에서 검증된 런타임 소스와 통합본의 일치, 기존 작업자 모델·프리팹·기본 장면·촬영 경로 및 Unity 패키지 목록의 동일성을 확인했다.
- 저장소의 실제 UT 패키지 무결성 검사 및 정상·피팅 예제 2개의 추론을 확인했다. 응답의 배관 ID·요청 ID·4096개 파형·원본 해시와 작업허가 미판정 상태를 확인했다.
- 대시보드/열화상/UT 연결 검사와 실행기의 서비스 재사용·다른 모델 거부·실패 시 정리 검사를 수행한다.

재현용 검사:

```powershell
python -m unittest discover -s tests -p "*adapter.py" -q
python -m unittest discover -s tests -p "test_unity_sensor_launcher.py" -q
node dashboard/verify-thermal-unit.mjs
node dashboard/verify-ut-unit.mjs
```

기존 작업본의 Unity 통합 검사와 실행본 시연은 과거 증거이며, 이번 체크아웃의 새 Play-mode 통과 결과로 바꿔 표시하지 않는다. 전체 RGB 247개/771회와 추가 계통의 완주 하네스는 현재 환경의 프로세스 조회 권한 제한으로 재수행하지 못했다. 팀 환경에서는 `scripts/run_inspection_harness.ps1 -Unity <설치된 Unity 경로>` 및 관련 Unity 검사 메뉴를 실행해야 한다.

## 해석 범위

초음파는 팀의 동결된 합성 파형 예제를 가상 작업자 위치에서 분석하는 시연이며, 이 Unity 배관의 실제 두께 측정이 아니다. 열화상은 기존 운전 온도 가정과 표면 모델에서 생성한 합성 영상이며 현장 실측 또는 학습된 열화상 AI 검증이 아니다. 온도 이상 후보는 CUI 확정이나 작업허가가 아니다. 안전 로직과 대체 착륙도 모의시험 범위이며 실제 드론의 물리적 사고 예방 성능을 보장하지 않는다.
