# 산소 공급·소결 2차 집진 증설 및 팀원용 Windows 배포

## 구현 범위

최신 프로젝트 계획서(제출 2026-11-09)를 먼저 확인했다. MAEK는 가스 배관 전용이 아니라
여러 매질에서 센서 관측과 후속 검사 검토를 연결하는 도구다. 이번 증설은 두 매질의
검사 사례를 추가하며, 기존 247개 배관의 분류·ID·연결·경로를 대체하지 않는다.

- 산소: 공급 경계 → 입구 차단 → 필터 → 출구 차단 → 계량 → 제어 → 소비처 인입 경계,
  7개 검사 스팬. 필터 하우징은 연결된 설비 구간으로 모델링했다.
- 소결: 선별·이송 지점 포집 후드 2개 → 합류 덕트 → 백필터 → 유인 송풍기 → 배기 굴뚝,
  10개 검사 스팬. 백필터와 송풍기 내부 연결을 나타내는 설비 스팬 2개가 포함된다.
- 소결 주배가스 계통, MEROS, 고로 BFG와 이차 집진을 혼합하지 않는다.
- 산소 소비처 인입 경계 이후의 풍구 부화·질량 유량·고로 CFD 결합은 미구현이다.
- 두 신규 계통의 실제 압력·유량·팬 곡선·집진 효율은 미계산/미보정이다.
  기존 공통 수치 계산 결과를 산소 운전값으로 전용하지 않는다.

공개 원문의 구성 요소와 일반 원리를 조합한 가상 구획이다. 포스코 실제 P&ID,
사고 현장, 시공 설계, 산소 안전 적합성 검증을 재현한 결과가 아니다.
원문 위치·권리·적용 판단은 `docs/references/oxygen-sinter/2026-11-09/`에 기록했다.

## 검사 흐름

원래 카탈로그/검사 경로와 새 방향 그래프/검사 경로를 분리했다. E 키로 새 구획의
전경부터 17구간을 연속 촬영한다. T 키는 원래 247개 검사로 돌아가 재시작한다.
전환은 별도 검사 세션의 시작이며 두 구획 사이를 연속 비행한다고 소개하지 않는다.
원래 경로 내부의 모든 이동은 유지된다. 추가 경로의 모든 이동도 0.12m swept sphere로 검사한다.

동일한 `MAEKInspectionTour`가 원본 RGB 촬영 → 로컬 HTTP 분석 → 요청 ID/이미지 해시
검사 → 대상 표면 Raycast → 위치 핀 → 세션별 후속 검사 목록을 처리한다.
합성 결함 라벨은 추론 입력으로 보내지 않는다. 결과표는 추가 계통의 모든 17구간도 표시한다.
촬영은 구간당 대표 시야 1개로 전 표면 검사가 아니다.

현재 Unity의 라이브 분석은 HSV 부식 색상 규칙 기준선이다. UT/IR/PEC나 학습 모델을
새로 통합했다고 주장하지 않는다. 무검출은 건전성 보장이 아니며, 후속 목록은
`workPermissionStatus=not_assessed`를 유지한다. 산소 누출·청정도·내부 균열·구조 하중 및
운전/작업 허가 판단은 수행하지 않는다. 사고 사례는 동일 종류의 참고 증설과 실제 사고 현장의
동일성을 구별한다.

## 검증과 배포

최종 검증을 완료했다. 근거 파일:

- `visualization/supplementary_circuits/connections_colliders.json`
- `visualization/interior_detail/after-interior-colliders.json`
- `visualization/inspection_demo/integration_report.json`
- `visualization/inspection_demo/play_mode_report.json`
- `visualization/inspection_demo/evidence_seal.json`
- `visualization/standalone_release/20261109_oxygen_sinter/frozen_bridge_test.json`
- `visualization/standalone_release/20261109_oxygen_sinter/delivery_report.json`

EXE는 Unity 플레이어와 독립 Python 런타임·로컬 분석 서버를 하나의 ZIP에 묶는다.
외부 Unity/Python 설치나 인터넷 모델 다운로드 없이 실행한다. ZIP 전체를 해제하고
`MAEK/MAEK.exe`를 실행한다. EXE만 따로 복사하지 않는다.
R 녹화는 PNG/JSONL 프레임 저장이며 MP4 직접 인코딩을 내장하지 않았다.


### 최종 결과

- Python 계약/회귀 테스트 23개와 신규 Python 파일 Ruff 검사 통과.
- 기존 장면 Collider/통로/시야 검사 13,396개 통과.
- 추가 17스팬/19노드/61 Collider, 34개 이동 구간과 17개 촬영 시야 등 221개 검사 통과.
- Editor 통합 검증 800개 통과: 247개 배관, 771회 촬영·분석.
- 실제 Play 모드 통과: 247/771, 24 녹화 프레임, 20,832회 이동 충돌 확인.
- 네이티브 EXE 통과: 247/771 + 추가 17/17, 추가 결과 표면 매핑, 후속 목록 모두 작업 허가
  미판정, 24 녹화 프레임. 이동 충돌 확인은 원래 20,828회와 추가 348회다.
- EXE 시험의 PATH는 Windows/System32로 제한했고 별도 Unity/Python 실행 경로를 사용하지 않았다.
  종료 후 자체 분석 서버 포트가 닫혔으며 네이티브 player.log의 런타임 예외가 없음을 확인했다.
- 빌드 후 검증 봉인에 포함한 소스 569개는 해시 변경이 없었다.
- ZIP CRC와 전체 262개 배포 파일의 해시를 검사했다. 실제 시험한 Player 파일과 묶인 파일도 비교했다.

중간 검증에서 발견된 바닥 관통 2건과 가림 1건은 형상/시점을 수정한 뒤 재검사로 해소했다.
봉인 쓰기 전 중복 실행한 별도 근거 검사는 이전 봉인을 읽어 STALE을 표시했으나, 이후
새 봉인과 전체 근거 검사가 모두 통과했다. Play 시작 시의 UnityEditor.Search.SearchDatabase
인덱스 예외는 기존 편집기 초기화 경고와 같았고 MAEK 하니스 및 네이티브 검증은 정상 통과했다.

배포 ZIP: `MAEK_Windows_Oxygen_Sinter_20261109.zip`

크기: 104,314,581 bytes

SHA-256: `57a639b5f32d9f5c62067868385973fea1df5f46e3987213a1c313023b222d0e`
