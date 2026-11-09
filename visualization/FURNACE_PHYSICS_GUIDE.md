# MAEK 고로 반응·용선 유동 시뮬레이션

## 실행
- Unity: `Assets/MAEK/Scenes/MAEKFurnacePhysics.unity`를 열고 Play. 고로 단면 모드로 시작합니다.
- P: 고로 단면 / 기존 보행·드론 모드. 1 / 2: 고로 선택. Space: 일시정지.
- 단면에서 마우스 오른쪽 버튼을 누르고 드래그하면 회전, 휠로 확대·축소합니다. 단면을 가리는 컨베이어·크레인은 이 모드에서만 시각적으로 숨기며 Collider는 유지합니다.
- 화면 버튼으로 출선구 개폐, 슬라이더로 송풍 산소 비율·온도·광석/코크스 공급량·시간 배율을 바꿉니다.
- 기본 자동 시나리오: 30초 출선 시작, 400초 폐쇄. 출선 버튼을 누르면 수동 모드가 됩니다.
- Blender: `maek_furnace_physics.blend`. 1~1441프레임, 24 fps. 계산 시간 600초를 60초에 재생하는 10배속 캐시입니다. 입력을 바꿔 다시 계산하려면 Unity를 사용합니다.

## 계산 범위
실시간 **집중정수 반응·열수지 + 단일 액상 출선 + 1차원 자유수면 수로** 모델입니다. 불꽃이나 입자만 재생하는 연출이 아니라, 수치 계산으로 얻은 온도·용선 높이·출선량·수로 깊이·유속을 화면에 연결합니다.

반응은 3개의 총괄 반응으로 축약합니다. 기체와 반응물은 유효 반응 용적 안에서 혼합되어 있다고 가정합니다. Fe2O3/CO/C/O2/CO2/N2와 고체·액체 Fe의 재고를 kmol 단위로 추적합니다. 이 구현은 Fe3O4/FeO 중간상, H2 환원, 슬래그, 용선의 탄소·규소·황 성분, 입자별 하강, 다상 CFD 및 실제 노내 공간 온도장을 풀지 않습니다. 단면의 상부 색띠는 반응 지시용 도식이며 구역별 해석 결과가 아닙니다.

| 총괄 반응 | 반응 진행량 1 kmol당 열 방출 |
|---|---:|
| 2 C + O2 → 2 CO | +221.060 MJ |
| Fe2O3 + 3 CO → 2 Fe + 3 CO2 | +23.4368 MJ |
| Fe2O3 + 3 C → 2 Fe + 3 CO | −493.9132 MJ |

철광석의 CO 및 C 환원식은 [ISIJ International의 반응·열수지 연구](https://www.jstage.jst.go.jp/article/isijinternational/54/7/54_1546/_html/-char/en)를 참고했습니다. 반응 속도와 CO 구동력의 계수는 시연용 가정이며 현장 실험으로 식별한 값이 아닙니다.

반응열은 298.15 K 표준 생성엔탈피의 화학양론 합으로 계산합니다. 사용값은 Fe2O3 −825.5032, CO −110.53, CO2 −393.51 MJ/kmol입니다. 출처: [NIST Fe2O3](https://webbook.nist.gov/cgi/cbook.cgi?ID=C1317608&Units=SI&Mask=2), [NIST CO](https://webbook.nist.gov/cgi/cbook.cgi?ID=C630080&Mask=1), [NIST CO2](https://webbook.nist.gov/cgi/cbook.cgi?ID=C124389&Units=SI&Mask=1).

## 열과 상변화
`dE = 반응열 + 유입 현열 − 배출 가스 현열 − 출선 엔탈피 − 외벽 열손실`로 적분합니다. 물질별 일정 비열과 유효 내화물 열용량을 사용하며, 상변화는 엔탈피법으로 처리합니다. 철을 **순철 대용 물성**으로 취급하여 용융점 1809 K, 잠열 247 kJ/kg를 사용합니다. 실제 탄소 함유 용선의 액상선과 조성 의존성을 재현하는 값이 아닙니다. 순철 물성의 근거: [NIST iron condensed-phase thermochemistry](https://webbook.nist.gov/cgi/cbook.cgi?ID=C7439896&Units=SI&Mask=2).

## 출선과 수로
노저 수위는 `액체 질량 / (밀도 × 단면적 × 공극률)`입니다. 출선구 입구가 잠겨 있을 때만 유동을 허용하며, 구동 압력은 `노내 게이지압 + 정수압`입니다. Darcy–Weisbach 관 마찰과 국부 저항으로 유속을 계산하고 개구율·점도·길이·직경을 반영합니다. 노내 압력 및 노저/출선구 저항의 역할은 [Shao & Saxén의 출선 연구](https://www.jstage.jst.go.jp/article/isijinternational/53/10/53_1756/_article)를 참고했습니다. 해당 논문의 두 액상 모델을 구현하거나 그 현장 검증을 승계한 것은 아닙니다.

수로는 Saint-Venant 방정식의 깊이·운동량을 Rusanov 유한체적법으로 풉니다. 단위 폭 유량 q에 대해 `∂h/∂t + ∂q/∂x = 0`, `∂q/∂t + ∂(q²/h + gh²/2)/∂x = ghS − Manning 마찰`을 사용합니다. 수로 길이 24 m, 폭 1.2 m, 48셀, 바닥 경사 0.015가 기본값입니다. CFL 제한과 유출 가능 체적 제한으로 음의 수심을 방지합니다. 수로 말단의 낙하 궤적은 계산 유속과 중력으로 표시하며, 배출 체적은 수용 용기에 누적합니다.

기본 밀도 7000 kg/m³, 기준 점도 0.006 Pa·s, 출선구 직경 0.06 m, 길이 2 m, 노내 게이지압 150 kPa를 비롯한 형상·운전값은 가상 시연 입력입니다. 운영·설계용 검증값으로 사용하지 않습니다. 설정 파일은 Unity `Assets/MAEK/Source/furnace_config.json`입니다.

## 결과와 재현
- `furnace_tests.log`: 동일 C# 계산 코드를 실행한 수치 시험 결과.
- `furnace_physics_report.json`: Unity 계산·장면 통합·기존 드론 경로 유지 검사.
- `furnace_physics_trace.csv`: 600초 시나리오, 1초 간격 상태와 각 수로 셀의 수심·유속. Blender 캐시도 이 파일을 사용합니다.
- `furnace_physics_verification.png`: 계산 시계열과 질량 전달 그래프.
- `unity_furnace_physics.png`, `furnace_physics_section.png`: 엔진에서 생성한 장면 확인 이미지.

보존 시험은 구현과 수치 해법의 검증입니다. 실제 고로 운전 데이터와 비교한 산업 모델 검증은 아닙니다. 원래의 배관 연결·Collider·가상 드론 기능은 유지하고, 단면은 외피를 시각적으로 절개하는 관찰 모드로 제공합니다.
