# MAEK 충돌 설정 버전

이 환경은 공개 공정도를 참고한 가상 설계이며 포스코의 실제 준공 도면이 아닙니다.

## 열기

Unity 6000.3.12f1 프로젝트:
D:/obsd/Projects/hackerton/MAEK/unity/MAEKInspection

장면:
Assets/MAEK/Scenes/MAEKInspection.unity

환경 프리팹:
Assets/MAEK/Generated/MAEKEnvironment.prefab

이동 가능한 검사기 프리팹:
Assets/MAEK/Generated/MAEKPortableUT.prefab

다른 Unity 프로젝트에 가져올 때는 visualization/MAEK_Collision_Ready.unitypackage를 사용합니다.
URP/HDRP 프로젝트에서는 재질을 해당 렌더 파이프라인으로 변환해야 합니다.
에디터 메뉴 MAEK > Build and verify collision environment는 전용 MAEK 프로젝트에서 재생성할 때 사용합니다.

Blender 원본:
visualization/maek_collision_ready.blend

## 적용한 변경

- 열풍 환상관을 고로 본체와 냉각수 배관 바깥으로 이격했습니다.
- TRT 발전기를 세정기 반대쪽으로 옮겼습니다.
- 배관 받침대 높이를 실제 관 하단에 맞췄습니다.
- 컨베이어가 출선장 지붕 위로 지나도록 높이를 조정했습니다.
- 상부 작업발판에 컨베이어 통과 개구부를 만들었습니다.
- 검사대 접근 계단과 난간 출입구를 추가하고 냉각수 회수 배관을 우회했습니다.
- 설비 접속점을 외면으로 정렬하고 송풍기 출구의 접선 방향 관통을 수정했습니다.
- 236개 배관의 ID와 설비 연결 관계를 유지했습니다.
- 원래 파일은 보존했습니다. 이 버전의 계통 데이터는 collision_network.json입니다.

## Collider 정책

| 대상 | 설정 |
|---|---|
| 고정 배관·철골·건물·설비 | 에셋 단위 비볼록 MeshCollider, Is Trigger 꺼짐, Rigidbody 없음 |
| 바닥·도로 | BoxCollider |
| 검사자 | 높이 1.8m, 반경 0.3m CharacterController |
| 이동 가능한 UT 검사기 | BoxCollider + Rigidbody, Continuous Dynamic, 보간 사용 |
| 문자·도색·화면·가는 케이블 | 장식으로 분류, 충돌체 없음 |

배관·난간·통로 전체를 커다란 BoxCollider나 Convex hull로 감싸지 않습니다.
동일한 에셋을 구성하는 부품들은 하나의 메시 충돌체로 묶되, 실제 빈 공간을 유지합니다.
게임 오브젝트의 MAEKAssetInfo에서 원본 에셋 ID와 포함된 Blender 객체를 확인할 수 있습니다.

MAEKEnvironment, MAEKPlayer, MAEKEquipment 레이어 사이 충돌을 활성화했습니다.
새 에셋을 겹쳐 놓는 에디터 작업을 자동으로 금지하는 도구는 아닙니다.
배치를 바꿀 때는 기하 검사와 물리 시험을 다시 실행해야 합니다.

## 사용

장면을 열고 Play를 누릅니다.
WASD로 이동하고 화면을 클릭하면 마우스로 시점을 바꿀 수 있습니다.
Esc로 마우스 잠금을 해제합니다.
시작 위치 앞 계단을 통해 검사대에 올라갈 수 있습니다.

MAEKPortableUT.prefab을 장면에 넣으면 중력과 충돌이 적용됩니다.
고정 환경 프리팹에는 움직이는 Rigidbody를 붙이지 않습니다.

## 검증 파일

- asset_overlap_before.json: 최초 메시 관통 후보.
- asset_overlap_after.json / asset_overlap_final.json: 수정 후 메시 검사.
- collision_connectivity_report.json: 배관 연결·밸브 상태·관끼리의 간섭 검사.
- unity_collision_report.json: 실제 Unity 6 물리 엔진 검사.
- unity_export_report.json: 내보낸 에셋과 메시 수.

기하 검사는 렌더에 보이는 서로 다른 조립체 사이의 삼각형 교차와,
닫힌 메시 안에 완전히 들어간 에셋을 검사합니다.
접속부 예외는 등록된 노즐·T 접속점·접촉 프로브의 국소 영역에 한정합니다.
한 조립체 안의 용접·볼트 결합 등은 에셋 간 관통으로 세지 않습니다.
계산 허용치는 미터 단위 0.002m입니다. 시공 간격·응력·유체 해석 검증은 아닙니다.

Unity 검사 항목:
1. 충돌 대상 에셋에 충돌체가 빠짐없이 생성됨.
2. 고정 환경에 비볼록 동적 Rigidbody나 Trigger가 없음.
3. 바닥 폭 330m로 단위가 일치함.
4. 바닥 Raycast가 맞는 높이에 적중함.
5. 이동하는 검사 장비의 SphereCast가 배관에 적중함.
6. 배관 아래 보행 통로가 열려 있음.
7. 철골 사이의 빈 공간이 충돌체로 막히지 않음.
8. 실제 CharacterController가 계단을 올라 검사대에 도착함.
9. 이동 검사기에 BoxCollider와 Continuous Dynamic이 설정됨.
10. 검사기가 낙하 후 바닥 위에 멈춤.

## 재생성

1. visualization/build_collision_ready.py를 Blender에서 실행합니다.
2. visualization/finalize_collision_model.py로 최종 검사와 렌더를 실행합니다.
3. Unity에서 MAEK > Build and verify collision environment를 실행합니다.

Unity 형상은 Blender에서 평가한 메시를 에셋별로 묶어 가져옵니다.
Blender의 절차적 노이즈 질감은 기본색·금속성·거칠기 값으로 단순화됩니다.
이 버전은 충돌과 접근성 시연을 위한 것으로, MAEK AI 판독 기능은 포함하지 않습니다.

API 참고:
- Unity Collider 종류: https://docs.unity3d.com/kr/6000.0/Manual/physics-optimization-cpu-collider-types.html
- Blender BVH 교차·레이 검사: https://docs.blender.org/api/main/mathutils.bvhtree.html
