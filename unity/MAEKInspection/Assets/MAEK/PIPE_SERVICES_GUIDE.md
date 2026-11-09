# MAEK 배관 계통·용도 적용

Unity 시작 장면: `Assets/MAEK/Scenes/MAEKPipeServices.unity`.
Blender 파일: `maek_pipe_services.blend`.

기존 배관 240개의 중심선·유체·차단 상태를 보존하고 용도 정보를 추가했습니다.
별도 정비 시험 구역에 질소 배관 4개와 계장공기 배관 3개를 추가하여 총 247개입니다.
실제 포스코 P&ID가 없는 가상 설계이며, 현장 배관을 특정하거나 설계 적합성을 입증하지 않습니다.

## 14개 용도

| 용도 | 개수 | 연결 목적 |
|---|---:|---|
| 미정제 고로가스 | 6 | 고로 상부 → 집진기 |
| 1차 집진 고로가스 | 2 | 집진기 → 세정기 |
| 정제 고로가스 | 18 | 세정기 → TRT → 연료 사용 설비 |
| 냉풍 공기 | 12 | 송풍기 → 열풍로 |
| 열풍 공기 | 60 | 열풍로 → 환상관 → 고로 풍구 |
| 연소용 공기 | 12 | 연소공기 송풍기 → 열풍로 버너 |
| 연소 배기가스 | 14 | 열풍로·보일러 → 굴뚝 |
| 냉각수 공급 | 52 | 냉각기·펌프 → 냉각판 |
| 냉각수 환수 | 50 | 냉각판 → 냉각기 |
| 가스 세정수 | 6 | 순환수·보충수 → 세정기 |
| 세정 슬러리 | 4 | 세정기 → 침전·슬러지 처리 |
| 검사 훈련용 물 순환 | 4 | 독립 훈련 펌프·시험 코일 |
| 질소 불활성화 시험 | 4 | 공급 → 감압 → 차단 → 챔버 → 회수 용기 |
| 계장용 압축공기 | 3 | 공기 공급 → 건조·조압 → 밸브 액추에이터 |

질소·계장공기는 별도 가상 정비 시험 모듈입니다. 실제 고로 공정에 접속한 배관으로 해석하면 안 됩니다.
계장공기는 질소 차단밸브의 공압 액추에이터로 연결되며 질소 유로와 섞이지 않습니다.
제어 관계는 메타데이터이며 공압 구동은 계산하지 않습니다. 질소 밸브는 기본 차단 상태입니다.
시험 챔버와 회수 용기는 시연 형상이며 실제 질소 퍼지 장치의 안전 설계도가 아닙니다.

## Unity 사용

1. 장면을 열고 Play합니다. 외관 검사 시점으로 시작합니다.
2. 오른쪽에서 계통을 선택하고 이전·다음 배관으로 원하는 ID를 고릅니다.
3. 용도, 시작·끝 노드, 상태, 검사 참고 항목을 읽습니다.
4. `이 배관으로 검사 카메라 이동`을 누르면 해당 배관의 검사 경로 첫 지점에서 일시정지합니다.

- E: 화면 중앙으로 조준한 배관 선택.
- L: 시연용 계통 색상 / 원래 재질 전환.
- M: 정보 패널 표시·숨김.
- F: 보행 / 드론. 화살표: 이전·다음 검사 경로. Space: 비행 재개·일시정지.
- 보행: WASD, 클릭으로 시점 고정, Esc로 해제. 패널을 누를 때는 Esc를 먼저 누릅니다.
- P: 기존 고로 CFD 화면 전환. CFD 화면의 H/S, 1/2 선택은 기존과 동일합니다.

색상은 용도 구분을 위한 임의 팔레트이며 국내외 배관 식별 표준이나 포스코 도장 규정이 아닙니다.
한글 표시는 운영체제의 맑은 고딕 등을 사용합니다. 폰트는 패키지에 재배포하지 않습니다.
배관 반경은 외형 제작값입니다. 실제 DN, 설계 압력, 재질 등급은 미확보 상태로 표시합니다.
시작·끝은 연결 그래프의 기준 방향이며 측정·계산된 유량 방향이 아닙니다.
환상관의 분배 유량과 방향은 미해석이고, 차단 구간에는 유동을 표시하지 않습니다.
검사 참고 항목은 용도별 설명이며 새로운 AI 진단·위험도 계산이나 가스 농도 감지 기능이 아닙니다.

기존 노저부 다상 CFD와 상부 반응 모델은 보존됩니다. 계통 선택은 CFD 입력이나 계산 결과를 바꾸지 않습니다.
CFD의 해석 범위와 한계는 기존 `CFD_GUIDE.md`를 참조하세요.

## Blender 사용

배관 객체 Custom Properties의 `line_id`, `service_code`, `fluid`, `purpose_ko`,
`from_node`, `to_node`, `normal_state`, `flow_basis`, `inspection_context`를 확인합니다.
Scene Custom Properties의 `pipe_service_colors`를 0으로 하면 기존 재질, 1이면 용도 색상을 봅니다.
Material Preview 또는 Rendered 보기에서 확인하세요.
`16_Pipe_services_and_utilities` 컬렉션은 새 질소·계장공기 시험 구역입니다.
기존 240개 드론 카메라를 보존했습니다. 새 7개 검사 경로는 Unity에 추가했습니다.

CFD 캐시와 애니메이션을 유지하고 외관 보기로 저장했습니다.
CFD 단면을 보려면 `12_Original_shells__toggle_for_exterior`를 숨기고,
`13_Physics_section_shells`, `15_3D_CFD_computed_fields`를 표시한 뒤 기존 CFD 카메라를 사용합니다.
`14_Calculated_reactions_and_molten_flow`는 이전 축약 모델이므로 CFD 보기에서는 숨겨 둡니다.

## 데이터·검증

- `pipe_services.json`: Unity·Blender 공통 용도/형상 데이터.
- `services_network.json`: 기존 배관망을 복사하고 용도·시험 계통을 추가한 연결 그래프.
- `line_service_list.csv`: 배관 ID별 용도·연결점·상태 목록(Excel용 UTF-8 BOM).
- `test_services.py`: 기존 형상 보존, 계통 분류, 유체 분리, 밸브 차단, 설비 포트 검사.
- `unity_service_report.json`: Unity Collider를 사용한 신규 배관 간섭·247개 검사 경로 검사.
- `blender_service_report.json`: 저장 파일 재열기와 메타데이터·CFD 캐시 보존 확인.

247개 비행 경로는 개별 배관 검사 경로입니다. 배관 간 이동은 카메라 컷이며 연속 비행 검증 대상이 아닙니다.
검증은 가상 장면의 형상과 데이터에 대한 것으로 실제 플랜트의 공정 안전 검증은 아닙니다.

## 참고 근거

일반적인 설비 역할을 참고한 자료입니다. 이 모델의 위치·치수·계통별 개수를 입증하지 않습니다.

- Paul Wurth, Stove and Blast Furnace Valve Technology: https://www.paulwurth.com/wp-content/uploads/2020/08/Brochure-Stove-and-Blast-Furnace-Valve-Technology-en.pdf
- Linde, Drying, Inerting, Blanketing and Purging: https://www.linde-gas.com/products-and-services/industrial-service-solutions/drying-inerting-blanketing-purging
- Primetals, Blast Furnace Gas Cleaning Plant: https://www.primetals.com/en/portfolio/solutions/ironmaking/blast-furnace/gas-cleaning-plant/

공개 자료의 일반 공정 역할을 가상 장면에 대응시킨 것이며 포스코의 실제 배관 도면을 복제한 것이 아닙니다.
