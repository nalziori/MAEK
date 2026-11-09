# 포스코 사진을 참고한 MAEK 외관 보강

## 기준과 범위
- 사용자 제공 고로 사진 3장의 철골, 층별 외장, 컨베이어, 주상·열풍로·부대 건물을 참고했다.
- 실제 포스코 배관 도면이나 현장 자산 스캔은 사용하지 않았다. 사진 자체를 텍스처에 붙이지 않았다.
- Unity `MAEKInspectionDemo.unity`가 이번 보강 대상이다. 기존 Blender 파일과 원래 수리·CFD 장면 파일은 재작성하지 않았다.
- 분석 대상은 원래 247개 배관이다. 추가 외관용 순환 배관은 수리 계산/MAEK 분석 대상이 아니다.

## 재생성
프로젝트 루트에서 `./scripts/run_inspection_harness.ps1` 실행.
`BuildInspectionTour`가 기존 원본 장면으로 같은 경로를 만든 뒤 `EnhanceSteelworks`를 적용한다.
`baseline`의 해시와 경로는 보강 전 상태이므로 외관 수정에 맞춰 갱신하지 않는다.

## 검증 산출물
- `geometry_audit.json`: 원본 메시/Collider 보존, 고정 경로와 촬영 시야, 추가/제외 부품.
- `../inspection_demo/integration_report.json`: 모든 촬영·HTTP 분석·표면 투영과 장애물 주입 검사.
- `../inspection_demo/play_mode_report.json`: 실제 Play 모드 전체 경로와 런타임 녹화.
- `../inspection_demo/evidence_seal.json`: 검증한 소스/에셋/장면/보고서 해시.
- `../factory_photos/latest_capture.txt`: 최근 1920×1080 전경·고로·검사 구역 렌더 위치.

보강 이전 비교 사진: `../factory_photos/20261108-185454/`.
합성 장면의 RGB 부식 후보이며 균열 예측이나 현장 판독 정확도 검증이 아니다.
