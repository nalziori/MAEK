# Unity 정비 캐릭터

`Assets/MAEK/Scenes/MAEKInspectionDemo.unity`를 열고 Play를 누르면 정비인이
세정 슬러리 배관 BF1-Q005 주변의 대기 위치에 자동 배치된다. 기존 ShiftLink의
노란 안전모·작업복 남성 캐릭터와 PDA를 프로젝트 내부에 포함했으므로
ShiftLink 폴더나 별도 에셋 다운로드가 필요하지 않다.

바로 확인하려면 Play 중 Hierarchy에서 `MAEK maintenance inspector`를 검색하고
선택한 뒤 Scene 뷰에서 F를 누른다. Game 뷰의 드론 시점과 경로는 바뀌지 않는다.
모델만 살펴보려면 아래 프리팹을 더블클릭해 Prefab Mode에서 연다.

프리팹: `Assets/MAEK/Resources/MAEK/MaintenanceInspector.prefab`.
다른 촬영용 씬에서도 프리팹을 끌어다 배치할 수 있다. 모델 높이는 약 1.72m이며,
기본 상태는 PDA를 든 대기 자세와 작은 유휴 동작이다. 이번 추가 범위는 정비인
표현과 배치이며, NDT 결과나 작업 허가를 자동 생성하지 않는다.

자동 배치는 기존 설비를 옮기지 않는다. 지면, 작업자 캡슐과 설비 간 간섭,
기존·추가 계통의 전체 드론 경로와의 간섭을 확인한 위치만 채택한다. 반경 0.5m,
높이 1.8m의 실제 CapsuleCollider는 설비와 같은 layer 8을 사용한다. 후보 위치를
확보하지 못하면 배치를 보류하고 로그를 남긴다. 기존 배관과 경로 파일은 유지된다.

Unity 메뉴 `MAEK > Characters > Verify maintenance inspector`에서 배치, 프리팹
참조, 유휴 자세, 드론 경로 간섭, 재실행 시 중복 생성 방지와 실제 렌더를 검사한다.
검증 결과와 사진은 `visualization/maintenance_inspector/`에 저장된다.
Python 참조 검사는 `python -m pytest tests/test_maintenance_inspector.py -q`로 실행한다.

원본 모델·재질의 출처와 SHA-256은
`Assets/MAEK/Story/ShiftLinkWorker/provenance.json`에 기록했다.
