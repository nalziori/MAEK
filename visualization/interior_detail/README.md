# MAEK 주상·정비동 내부 보강

사용자 지정 순서: 보강된 장면 Collider 재검사 → 통과 확인 → 주상/정비동 내부 보강.

## 대상과 보존
- 주상: BF1.CASTHOUSE, BF2.CASTHOUSE.
- 정비동: SERVICE.-97, SERVICE.0, SERVICE.99.
- 기존 247개 분석 배관, 원본 메시/Collider, 원본 경로 및 최종 비행 계획을 유지한다.
- 추가 냉간 검사 스풀은 훈련용 모형이다. 추가 수리 계산 회로나 MAEK 분석 대상으로 등록하지 않는다.
- 기존 주상 검사 루프는 원래 드론 경로와 MAEK 분석 연결에 그대로 포함된다.

## 현재 구성
- 작업대 16개: UT/PEC 준비, 모형 계측기와 케이블, 하부 선반 및 받침.
- 닫힌 검사 스풀 12개: 곡관, 플랜지, 펌프 몸체, 지지대와 게이지.
- 공구함, 통로 도색, 작업 구역, 가드레일, 천장에 부착된 조명.
- 실내 신규 물리 Collider 940개. 도색과 인쇄 글자만 물리 두께가 없는 평면이다.
- 글자는 벽/장비의 깊이 판정에 따르며, 과도하게 겹치던 실내 조명의 범위를 줄였다.

## 검증 자료
- initial-collider-failures.json: 최초 실패 3건 원본. 통로 기둥 2곳과 중앙 시선의 접합부 판정.
- before-interior-colliders.json: 수정 후 내부 작업 시작 전 PASS, 10,133개 검사.
- build_report.json: 내부 조립체 배치 수와 제외 내역.
- after-interior-colliders.json: 최신 저장 장면 Collider·통로·촬영 시야·작업대·스풀 이음 검사.
- latest_photos.txt: 최신 내부 1920×1080 사진 폴더.
- ../inspection_demo/: 전체 에디터/Play 비행·RGB 분석 보고서와 최신 증거 해시 봉인.

재생성 및 전체 검증은 프로젝트 루트에서 `./scripts/run_inspection_harness.ps1`.
저장된 장면만 다시 검사하려면 Unity batch execute method `MAEK.Editor.AuditEnhancedColliders.Run`.
수치/모델의 현장 정확도나 실제 구조물의 시공 적합성을 검증하는 자료는 아니다.
