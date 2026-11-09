# Unity 제철소 검사 시뮬레이터

이 PR은 최신 main 기준의 독립된 시뮬레이터 변경이다. 다른 연구/학습 브랜치를 먼저
병합할 필요가 없다. 기존 247개 배관과 771회 촬영 경로, 산소 공급 7스팬과 소결 2차
집진 10스팬의 별도 검사 경로를 포함한다. 집진 10스팬 중 2개는 필터/팬의 설비 내부
연결을 표현한다. 원래 경로와 추가 경로 사이의 전환은 별도 세션의 시작이다.

## Unity에서 실행

1. Git LFS를 설치하고 저장소 루트에서 `git lfs install`, `git lfs pull`을 실행한다.
   대형 장면·메시·필수 CFD/배관 입력은 LFS에 저장한다. .meta GUID를 유지한다.
2. Python 가상환경 `.venv`를 만들고 `pip install -r requirements.txt`를 실행한다.
   영상 인코딩/Windows 패키징이 필요하면 `pip install -r requirements-demo.txt`도 실행한다.
3. `./scripts/start_inspection_bridge.ps1`로 로컬 RGB 분석 서버를 시작한다.
4. Unity 6000.3.12f1로 `unity/MAEKInspection`을 열고
   `Assets/MAEK/Scenes/MAEKInspectionDemo.unity`에서 Play를 누른다.
5. E: 산소·소결 17스팬 / T: 기존 247개 검사로 복귀 / Space: 일시 정지 /
   P: 공정·사고 맥락 안내 / R: PNG+JSONL 녹화 프레임 저장.

전체 재생성·Collider·Editor·실제 Play·HTTP·근거 봉인 검증:

```powershell
./scripts/run_inspection_harness.ps1 -Unity 'C:/설치경로/Editor/Unity.exe'
```

기본 Unity 경로는 개발 PC의 값이며 `-Unity`로 바꿀 수 있다. 캐시·개인 설정·녹화·ZIP·EXE와
근거 봉인은 커밋하지 않는다. 저장된 검사 보고서는 이전 검증의 참고이며, 현재 체크아웃의
근거 봉인은 전체 하니스를 실행해 새로 생성한다. Python 계약 검증은 `pytest -q`,
`python scripts/check_supplementary_circuits.py`, `python scripts/check_inspection_harness.py`로 실행한다.

## Windows EXE 재생성

Windows에서 Windows Build Support (Mono)를 설치한 Unity와 위 Python 환경이 필요하다.
완성된 배포 ZIP을 받는 팀원은 Unity/Python 설치가 필요 없다. 아래 작업은 저장소 루트에서 한다.

```powershell
$release = 'visualization/standalone_release/20261109_oxygen_sinter'
python -m PyInstaller --noconfirm --onedir --windowed --name MAEK --paths . --distpath "$release/dist" --workpath "$release/build" --specpath "$release" scripts/maek_standalone_launcher.py
& 'C:/설치경로/Editor/Unity.exe' -batchmode -projectPath "$PWD/unity/MAEKInspection" -executeMethod MAEK.Editor.BuildStandaloneTeam.Run -logFile "$PWD/$release/unity_build.log"
python scripts/verify_windows_standalone.py $release
python scripts/package_standalone.py $release
```

Unity 빌드 프로세스가 정상 종료된 뒤 다음 명령을 실행한다. 네이티브 검증은 외부 Python/Unity
PATH를 제거한 상태에서 기존 247/771 및 추가 17/17을 모두 촬영·분석하고, 표면 투영·후속 목록·
녹화 24프레임·분석 서버 종료를 검사한다. 패키징은 검증 이후 바뀐 Player 파일과 압축 오류를 거부한다.
생성된 ZIP 전체를 압축 해제해 `MAEK/MAEK.exe`를 실행하며 `_internal`, `Player`를 함께 유지한다.
R 녹화는 PNG/JSONL 저장이며 MP4 직접 인코딩을 내장하지 않는다. ZIP과 EXE는 PR에 넣지 않는다.

## 해석 범위

공개 자료를 참고한 가상 배치이며 실제 POSCO P&ID/사고 현장의 복제가 아니다. 산소는 소비처
인입 경계까지이며 풍구 산소 부화/기존 CFD와의 결합은 미구현이다. 소결은 이송·선별 2차 집진이며
소결 주배가스나 고로 BFG 계통이 아니다. 새 계통의 실제 압력·유량·집진 효율은 미계산이다.
라이브 분석은 렌더 RGB에서 부식 색상 후보를 찾는 HSV 기준선으로, UT/IR/PEC 통합이나 내부
균열 확진·구조 하중/작업 허가 판단은 수행하지 않는다. 작업 허가 상태는 항상 미판정이다.

기존 Blender/CFD 생성 코드와 수치 실험은 `visualization/`에 있다. 이 코드는 별도 Blender/수치
런타임을 사용하며 일반 패키지 CI와 분리한다. CFD 선택 의존성은 `visualization/cfd/requirements-cfd.txt`에 있다.
