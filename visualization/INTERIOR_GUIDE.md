# MAEK 내부 공간 버전
Unity 프로젝트: D:/obsd/Projects/hackerton/MAEK/unity/MAEKInspection
장면: Assets/MAEK/Scenes/MAEKInterior.unity
환경 프리팹: Assets/MAEK/Generated/MAEKInteriorEnvironment.prefab
Blender: visualization/maek_interior_ready.blend

출선장 2개, 원료동 2개, 후면 설비동 3개의 내부를 구성했습니다.
건물의 채워진 외관용 박스를 바닥·벽·출입구로 분리했습니다.
중앙 통로, 양쪽 출입구, 기둥, 천장 보, 실내 조명, 작업대와 공구 보관대를 배치했습니다.
출선장에는 크레인·시연용 비가동 트로프·검사 작업대·냉각수 검사 연습용 폐회로를 추가했습니다.
기존 배관 236개에 실내 배관 4개가 추가되어 240개입니다.

Play 후 WASD로 출선장 앞에서 내부로 이동합니다. 클릭하면 마우스 시점 제어, Esc로 해제합니다.
이전 외부 검사대와 계단, 이동형 UT 검사기 설정도 유지했습니다.

실제 제철소 내부 도면은 확보되지 않았으므로 내부 배치와 검사 연습 장비는 가상 설계입니다.
고로 내부의 반응·용선 생산·크레인 가동을 계산하는 공정 시뮬레이터는 아닙니다.

검사:
- interior_overlap_report.json: 실내·외 메시 관통 및 등록 접속부 검사
- interior_connectivity_report.json: 배관 연결·계통 경로 검사
- unity_interior_report.json: 기존 물리 검사 + 건물별 출입구/중앙 통로 검사 + 실제 캐릭터 진입
- interior_rooms.json: 건물 위치와 크기

Blender 제작: visualization/build_interiors.py
Unity 재생성: MAEK > Build and verify collision environment
Unity 패키지: visualization/MAEK_Interior_Ready.unitypackage
내보낸 Unity 재질은 Blender 절차적 질감의 기본색·금속성·거칠기를 사용합니다.
