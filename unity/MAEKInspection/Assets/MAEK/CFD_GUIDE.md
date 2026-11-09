# MAEK 3차원 다상 CFD 시연

**실제 수치 해석 결과를 재생하는 연구·시연용 프로토타입입니다.** 기존 축약 모델과 별도 장면으로 제공하며, 포스코 현장 도면·운전 데이터로 검증된 모델이 아닙니다. 노저부와 상부 반응층은 **서로 독립된 해석 영역**입니다. 전 고로의 반응·용융·유동을 양방향으로 결합한 산업용 모델이라고 해석하면 안 됩니다.

## 실행

- Unity 프로젝트: `unity/MAEKInspection`, 장면 `Assets/MAEK/Scenes/MAEKFurnaceCFD.unity` → Play.
- 별도 프로젝트: `MAEK_Furnace_CFD.unitypackage`를 가져온 뒤 위 장면 실행. 패키지는 이 폴더에 있습니다.
- H: 노저부 확대, S: 상부 반응층, P: 기존 보행·드론으로 복귀, 1/2: 고로 선택, Space: 일시정지.
- 오른쪽 마우스 드래그와 휠: 카메라 회전·확대. 시간 슬라이더: 계산된 상태 선택.
- Temperature / CO / Reduction: 상부의 온도·CO 몰분율·광석 환원율. 단면 슬라이더로 다른 깊이의 계산 셀을 확인합니다.
- 주황색: 용선, 갈색: 슬래그, 청록색 화살표: 계산 액상 유속 × 10초. 화살표는 입자 궤적이 아닙니다. 가스는 빈 공간으로 표현하며 실제 상분율은 해석 파일에 저장됩니다.
- BF1/BF2는 **동일한 기준 해석의 두 배치**입니다. 별도 운전 조건의 두 고로를 계산했다고 표시하지 않습니다.
- Blender: `maek_furnace_cfd.blend`. 1~289프레임, 24fps. 노저부 0~12초, 상부 0~120초를 같은 재생 길이에 배치했습니다. 두 시간은 별개입니다. 내부 `CFD_COMPUTED_FIELDS.json.zlib.base64` 텍스트에 원본 표면·공간장이 압축되어 들어 있습니다. 검토용 렌더는 단면만 표시하며 전체 제철소 환경은 뷰포트에 유지합니다.
- Unity/Blender는 사전 계산 결과를 재생합니다. 운전 입력 변경은 `config.json`을 수정한 후 다시 해석해야 합니다. 즉석 수치 계산은 기존 `MAEKFurnacePhysics.unity`의 축약 모델에서 제공합니다.

## 실제로 계산하는 것

| 영역 | 구현 | 계산 범위 |
|---|---|---|
| 노저부 | OpenFOAM Foundation 14 `incompressibleMultiphaseVoF` | 3차원 비압축성 Navier–Stokes, PIMPLE 압력–속도 결합, MULES VOF 수송, 중력·표면장력 |
| 세 유체 | 용선 / 슬래그 / 가스 | 상분율별 밀도·점도, 공통 속도장, 움직이는 경계면 |
| 코크스 데드맨 | `porosityForce` / Darcy–Forchheimer | 중앙 다공성 영역의 운동량 저항. 입자를 직접 해석하거나 코크스 고체 부피를 유체 저장체적에서 빼지는 않음 |
| 상부 충전층 | Python/SciPy 3D 유한체적 Darcy 모델 | 8개 비대칭 CO 혼합가스 유입, 층별 저항, 공간 압력·유속, CO/CO2/N2 수송 |
| 상부 반응·열 | Fe2O3 + 3CO → 2Fe + 3CO2 | 셀별 반응·반응열·유효 열전도·가스 열수송, 고체 산화철/철 재고 및 원소수지 |
| 시각화 | 계산 상분율의 0.5 등가면 | 임의의 파도·입자 연출 없이 실제 격자 결과에서 표면과 화살표 생성 |

노저부는 반경 5m, 높이 4m인 계단식 원통 근사입니다. 0.5m/2,528셀과 0.25m/20,224셀을 비교했습니다. 초기 용선 높이 1.75m, 슬래그 두께 0.75m이며, 경계면에 0.08m 비대칭 교란을 주어 과도 응답을 계산했습니다. 이는 현장 관측 파형이 아닙니다.

노저부 밀도는 용선 7000, 슬래그 2800, 가스 1 kg/m³, 동점도는 각각 8.5714e-7, 1.4286e-4, 6e-5 m²/s입니다. 상간 표면장력은 용선–슬래그 1.2, 용선–가스 1.6, 슬래그–가스 0.5 N/m입니다. 모두 시연 설정이며 조성·온도 의존 물성으로 보정하지 않았습니다.

출선 경계는 0.5m²의 격자 패치입니다. 실제 60mm 출선구를 이 크기로 확대 설계한 것이 아니라 **미해상 출선구의 유량 경계**입니다. 기존 축약 모델의 180초 값 77.7024051748993 kg/s를 밀도 7000으로 나눈 0.0111003435964142 m³/s를 일정하게 부과합니다. CFD 압력이 출선구 유량을 다시 바꾸지는 않습니다. 기존 외부 1차원 수로를 3차원으로 바꾼 것은 아닙니다.

상부는 1m 격자 1,496셀, 120초입니다. 유입은 레이스웨이에서 이미 생성된 것으로 가정한 CO/N2 혼합가스이며 **송풍 산소·코크스 연소를 직접 계산하지 않습니다**. 고체는 움직이지 않고 가스 총 몰농도는 고정입니다. CO 환원으로 가스 총 몰수는 보존되지만 조성 변화에 따른 밀도·열팽창은 압력장에 피드백하지 않습니다. 생성 철은 셀에 재고로 남으며 노저부로 이송·용융시키지 않습니다. 반응 속도는 시연용이며 Fe3O4/FeO 중간상, H2, 조성 평형, 광석 입자 확산은 없습니다.

## 검증과 현재 한계

- `test_cfd.py`: 압력 유량 수지, 불활성 스칼라 보존, 반응물 부재, 원소·열수지, 시간 간격 변화, 3차원 격자 등 7개 시험.
- `verification.json`: 두 격자, 원본 CFD 셀 순서, 저장된 상분율 범위·합, 배출 유량과 상별 체적, 정지 용선 시험, 상부 수지 결과.
- `unity_cfd_report.json`: 원본 계산 프레임과 장면, 좌표·카메라, 기존 Collider와 240개 드론 경로 검사.
- `blender_cfd_report.json`: 원본 데이터 해시와 프레임별 노출 상태. 별도 저장 후 재열기 검사도 수행합니다.

**격자 독립성은 확보되지 않았습니다.** 두 격자의 용선 유속 RMS 차이가 약 0.0070 m/s이며 비교한 정밀 격자 유속 RMS 약 0.0065 m/s와 비슷한 크기입니다. 따라서 국소 유속을 정량 예측값으로 쓰면 안 됩니다. 용선 배출 체적 수지 오차는 약 1.42e-4m³로 초기 재고의 약 1.03e-6, 부과한 12초 배출량의 약 0.107%입니다. 이는 수치 보존 검사이며 실제 설비 정확도가 아닙니다.

정지 액상 시험에서 용선 최대 속도는 약 5.3e-6 m/s였으나, 가스·계면에는 최대 약 0.043 m/s의 수치적 잔류 유동이 남았습니다. 더 높은 밀도비 안정화, 경계면 해상도, 시간 간격 검토가 필요합니다.

노저부는 **등온·층류 모델**이며 열·반응과 결합하지 않았습니다. 난류 모델, 접촉각/젖음, 용해·응고, 슬래그 화학, 탄소 함량, 코크스 입자 운동, 내화물 공액 열전달, 수 cm 출선구 및 외부 3차원 수로는 포함하지 않습니다. 현장 재현에는 실제 형상·운전 경계조건·물성·검증 자료, 격자/시간 수렴 연구가 추가로 필요합니다.

## 재실행

Windows Python 3.12: NumPy, SciPy, scikit-image, matplotlib 필요. WSL Ubuntu에 OpenFOAM Foundation 14가 설치되어 있습니다. 이번 작업에서 사용한 패키지는 `openfoam14 20261008`입니다. OpenFOAM은 GPLv3이며 Unity 패키지에 OpenFOAM 바이너리를 포함하지 않습니다.

1. 이 폴더에서 `python test_cfd.py`, `python reactive_shaft.py` 실행.
2. `python build_case.py`, `python build_case.py --name hearth_fine --cell 0.25` 실행.
3. WSL에서 `export HWLOC_COMPONENTS=-gl; source /opt/openfoam14/etc/bashrc` 후 각 case에서 `blockMesh`, `checkMesh`, `foamRun`, `foamPostProcess -func writeCellCentres -time 0` 실행. 출력은 각 `log.*`에 보관합니다.
4. 정지 상태 케이스는 `run_cfd.ps1`이 생성·실행합니다. 전체 재실행도 이 스크립트를 사용합니다.
5. `python export_results.py`가 검증과 Unity용 `Source/cfd_playback.json`을 갱신합니다. `python plot_results.py`로 검사 그림을 갱신합니다.
6. Unity 메뉴 `MAEK > Build and verify 3D CFD playback`. Blender는 `blender -b --python build_blender.py` 실행.

원본 OpenFOAM 케이스는 `hearth`, `hearth_fine`, `hearth_equilibrium` 폴더입니다. `hearth_fine/hearth.foam`을 ParaView에서 열면 저장된 압력·속도·세 상분율의 전체 3차원장을 확인할 수 있습니다.

## 참고 근거

- [OpenFOAM 14 공식 배포·설치](https://openfoam.org/download/14-ubuntu/): 사용한 네이티브 해석 환경.
- [공식 다상 VOF 예제](https://github.com/OpenFOAM/OpenFOAM-14/tree/master/tutorials/incompressibleMultiphaseVoF/damBreak4phase): 해당 버전의 설정 형식 확인.
- [Huang et al., 2008: 고로 노저부 CFD와 다공성 저항](https://www.jstage.jst.go.jp/article/isijinternational/48/9/48_9_1182/_pdf): 공간 유동과 코크스층 저항을 구분하는 모델 구성 참고. 논문의 검증 정확도를 승계하지 않음.
- [2025 고로 용선·슬래그·가스 계면 연구](https://doi.org/10.1016/j.ijheatmasstransfer.2025.127085): 다상 계면·점도·코크스 크기를 별도로 다루는 연구 범위 참고. 해당 연구 모델의 복제는 아님.
- [ISIJ 반응·열수지 연구](https://www.jstage.jst.go.jp/article/isijinternational/54/7/54_1546/_html/-char/en), [NIST Fe2O3](https://webbook.nist.gov/cgi/cbook.cgi?ID=C1317608&Units=SI&Mask=2): 기존 순철 대용 총괄 반응식·반응열을 재사용. 실제 공정 속도 상수의 근거는 아님.


