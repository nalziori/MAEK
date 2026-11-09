# 열화상 v2 합성: 센서 근거와 가정의 경계

확인일: 2026-11-08. 이 문서는 공식 문헌·제조사 자료와 현재 v1 생성기 읽기 검토를 연결한다. 센서 실측, 현장 보정, v2 구현 검증, 모델 학습 결과는 포함하지 않는다.

**문헌이 뒷받침하는 것은 측정 과정에서 구분해야 할 영향 요인이다. 공개 사양만으로 실제 카메라의 잡음 분포·시간 상관·고정 패턴·온도 드리프트를 복원할 수는 없다.** v2는 문헌을 참고한 일반 센서 시뮬레이터로 표시하고, 현장 입력의 `unsupported_domain` 상태와 균열·감육 정답 부재를 유지한다.

## 1. 확인한 1차 출처 원장

| ID | 정확한 URL·판본 | 직접 확인한 근거 | 적용 한계 |
|---|---|---|---|
| S1 | [NIST 공식 서지](https://www.nist.gov/publications/calibration-and-measurement-procedures-high-magnification-thermal-camera), DOI `10.6028/NIST.IR.8098` | Brandon M. Lane, Eric P. Whitenton, *Calibration and Measurement Procedures for a High Magnification Thermal Camera*. NIST 게시일 2016-01-08. 픽셀별 비선형성·흑체 보정, PSF, 방사율 측정 과정을 다룬다. | 특정 장치의 보정 절차이며 MAEK 센서의 보정값이나 잡음 분포가 아니다. |
| S1-PDF | [미국 정부 GovInfo 원문 PDF](https://www.govinfo.gov/content/pkg/GOVPUB-C13-6f8cf82afef921249448cee1b0ff0f06/pdf/GOVPUB-C13-6f8cf82afef921249448cee1b0ff0f06.pdf) | 표지 December 2015. 초록·목차와 본문 pp.1–5를 확인했다. p.1은 완전한 불확도 계산 결과를 제시하는 보고서가 아님을 명시한다. 예시는 고배율 NIR 장치이며 p.2에 고온 >500°C 맥락이 있다. | NIR 장치의 예시 수치를 실온 부근 LWIR 배관 촬영에 이전하지 않는다. [NIST 원본 PDF 경로](https://nvlpubs.nist.gov/nistpubs/ir/2016/NIST.IR.8098.pdf)는 검색에서 확인했지만 직접 본문 요청은 시간 초과여서 정부 미러를 읽었다. |
| S2 | [FLIR A70 Thermal Core 29° 공식 사양](https://support.flir.com/dsdownload/assets/89929-0101-en-us.html), P/N `89929-0101`, Rev. `93980`, Last modified `2023-11-01` | 아래 표의 파장대·NETD·해상도·광학계·온도 범위와 조건부 정확도. | 정확한 SKU와 판본의 수치다. A50/A70 전체 제품군이나 다른 렌즈의 값을 합쳐 사용하지 않는다. |
| S3 | [FLIR OEM: Choosing the Right Thermal Imager](https://www.oem.flir.com/learn/discover/choosing-the-right-thermal-imager-for-your-integrated-project/) — “What Sensitivity Do I Need?”, “Do I Need Radiometry…” | NEDT는 온도 변화 신호와 시간 잡음 사이의 감도 지표다. 시험 온도에 따라 비교가 달라지며, 방사온도 측정에는 반사·광학·대기·방사율 보정이 필요하다. | 분포의 형태, 픽셀 간 독립성, 모든 온도에서 동일한 잡음 크기를 보장하지 않는다. |
| S4 | [FLIR 공식 매뉴얼 §12 Thermographic measurement techniques](https://support.flir.com/docdownload/assets/web/2p5q/en-us/T505000.xml.html) | 방사율·반사 겉보기 온도·거리·습도·대기 온도가 측정에 영향을 준다. 방사율은 표면 처리에 따라 달라지며, 반사 겉보기 온도는 단순 접촉 온도와 구분한다. | 재질 이름만으로 현장 방사율을 확정하거나 반사 온도를 항상 외기 온도와 같게 두는 근거가 아니다. |
| S5 | [FLIR A40/A50/A70 Camera placement guidelines](https://docs.flir.com/T810684/en-US/latest/s05.html), 문서 `T810684 - AA - en-US` | 이 설치 지침은 정격 측정 정확도에 대해 최소 3×3 센서 픽셀을 채우는 표적, 올바른 방사율과 초점을 전제로 한다. 거리·시야각·표적 크기를 함께 고려한다. | 3×3 표적 점유 조건은 임의의 9픽셀 연결성분 제거 규칙과 다르다. MAEK 후처리의 보편적 합격 기준으로 전용하지 않는다. |

FLIR 고객지원 NETD FAQ는 검색 결과만 표시되고 본문이 접근 확인 페이지로 이동했다. 이 문서의 정의 근거는 실제 본문을 읽은 S3이며, 접근하지 못한 FAQ 내용을 확인한 것처럼 인용하지 않았다.

## 2. 문헌에 적힌 숫자와 합성에 넣는 숫자

S2에서 확인한 **A70 Thermal Core 29° 한 SKU의 예시 사양**이다. 특정 장비 구매·선정을 권고하거나 해당 장비를 복제했다고 주장하는 표가 아니다.

| 항목 | 공식 사양의 값·조건 | v2에서 가능한 사용 |
|---|---|---|
| 센서·파장대 | Uncooled microbolometer, **7.5–14 µm** | 대표 LWIR 적분 구간의 출처로 기록 |
| NETD | **35 mK**; 이 SKU 표에는 `<` 기호가 없음 | 감도 규모 참고. `Gaussian sigma=0.035°C`라는 측정 결과로 바꾸지 않음 |
| 해상도·주파수 | **640×480**, **30 Hz** | 센서 예시 메타데이터. 128×160 합성 결과와 동일시하지 않음 |
| 렌즈 | **29°×22°**, **f/1.4**, IFOV **0.84 mrad/pixel**, 최소 초점 거리 **0.25 m** | 광학 설정을 추적해야 한다는 근거. 문서에 없는 PSF 폭은 추정하지 않음 |
| 예시 선택 범위 | **−20…175°C** | 선택 가능한 범위의 하나. 기존 −40…180°C 클리핑은 이 사양과 일치하지 않음 |
| 정확도 | 위 범위에서 주변 온도 **15…35°C** 조건: 대상 **−20…100°C에 ±2°C**, **100…175°C에 ±2%** | 조건부 정확도 사양. 1σ, 95% 구간, 매 프레임 독립 오차의 분포로 해석하지 않음 |

출처: [S2 공식 SKU 사양](https://support.flir.com/dsdownload/assets/89929-0101-en-us.html). 제품군 소개 페이지의 요약값보다 이 표의 SKU·조건·판본을 우선한다.

| 합성 파라미터 | 근거 분류 | 반드시 붙일 설명 |
|---|---|---|
| 적분 구간 7.5–14 µm | 제조사 사양을 참고한 구간 | 실제 상대 분광 응답 곡선은 확보하지 못함 |
| 구간 내 평탄한 응답 | **공학 가정** | 이상적 flat/top-hat 응답이며 A70 응답 측정값이 아님 |
| 128×160 일반 센서·binning | **공학 가정** | 계산용 격자·축소 모델. 실제 센서 해상도·binning 동작을 재현했다는 뜻이 아님 |
| 30°C 기준 등가 Gaussian read noise | **공학 가정** | 기준 온도를 명시한 합성 잡음 계수. NETD를 fitting하거나 실측 분포를 얻은 것이 아님 |
| 고정 패턴·gain/offset·행/열 잡음·시간 드리프트 | 영향 요인 분리 제안, **수치·분포는 공학 가정** | 크기·상관·시간상수는 미측정. 제조사 정확도를 임의 분포의 σ로 사용하지 않음 |
| PSF 모양·폭, 흐림 변화 | 영향 요인은 S1·S5, **수치는 공학 가정** | 실제 렌즈·초점·거리에서 측정한 PSF가 아님 |
| 방사율·반사 온도 범위와 공간 패턴 | 영향 요인은 S4, **구체 범위·분포는 공학 가정** | polished/painted 등 표면 상태별 측정값이나 현장 빈도 분포가 아님 |
| 양자화 간격·불량 픽셀 비율·클리핑·정합 오차 | **공학 가정** | 제조사 문서나 측정으로 확인하지 않은 수치를 하드웨어 사양이라고 표시하지 않음 |

## 3. NETD·정확도·두 프레임 차이에서 지켜야 할 구분

S3의 NETD 설명은 제한된 시험 조건에서 시간 잡음에 대한 신호 감도를 다룬다. 이것만으로 전체 온도 구간의 동일 분산, Gaussian 꼬리, 공간적 독립성, 프레임 간 독립성 또는 보정 불확도가 정해지지 않는다. 따라서 `NETD=모든 픽셀의 σ`나 `정확도 ±2°C=매 프레임 N(0,2²)`는 근거 없는 변환이다. [S3](https://www.oem.flir.com/learn/discover/choosing-the-right-thermal-imager-for-your-integrated-project/)

아래는 두 측정 차이에 대한 수학적 관계이며, MAEK가 측정한 분포가 아니다.

`Var(current-reference) = Var(current) + Var(reference) - 2 Cov(current,reference)`

`sqrt(2)*sigma`는 두 오차의 분산이 같고 공분산이 0일 때의 특수한 경우다. 공통 offset은 차분에서 상쇄될 수 있지만, 프레임 간 보정·주변 환경·정합 변화는 상쇄되지 않는다. v2의 계수는 “합성 등가 잡음”, “가정한 공통 offset”, “가정한 프레임 차이 drift”처럼 역할과 공유 범위를 나눠 기록한다. 숫자의 확률분포를 선택하면 그 선택 자체도 가정으로 원장에 남긴다.

방사율과 반사 온도는 같은 상태 변수로 묶지 않는다. FLIR 매뉴얼의 표면 측정 절차는 별도의 방사율·반사 온도 확인을 요구하며, 낮은 방사율에서 반사의 영향을 특히 주의하도록 설명한다. 따라서 현재 코드의 `camera_emissivity=.95`, `camera_reflected_c=ambient`는 편의를 위한 설정값이다. [S4](https://support.flir.com/docdownload/assets/web/2p5q/en-us/T505000.xml.html)

## 4. 현재 v1 생성기의 강한 편향과 우선 수정

아래 사실은 [thermal_observation_synth.py](../maek/thermal_observation_synth.py), [thermal_feasibility.py](../maek/thermal_feasibility.py), [thermal_surface_solver.py](../maek/thermal_surface_solver.py), [생성 스크립트](../scripts/generate_thermal_observation_dataset.py)를 읽어 확인했다. 모델이 실제로 해당 단서를 사용했다는 실험 결과는 아니며, 그 가능성과 개선 우선순위는 코드에서 도출한 판단이다.

| 우선순위 | 확인한 구현 | 위험과 수정 방향 |
|---|---|---|
| P0: 요인 결합 제거 | `insulated`가 `group_index % 16`의 bit0이며, 비-stress blur도 인덱스 홀짝으로 `.5`/`1.`이 됨 | 보온이면 항상 blur .5, 비보온이면 항상 1.이다. 센서 흐림이 물리 상태를 대신 나타낼 수 있다. pose·blur·patch를 물리 요인과 별도 난수 흐름으로 뽑고 교차표로 독립 설계를 검사한다. |
| P0: 위치 단서 분리 | `patch_quadrant=(group_index//16+cell)%4`; `cell`의 하위 비트가 보온·방사율과 연결됨 | 패치 위치가 조건 정보와 구조적으로 연결된다. 2개 방향 직사각형 배관·하나의 Gaussian 패치도 형상 다양성을 제한한다. 위치와 크기를 독립화하고, 다른 형상·배경 계열을 별도 확인 세트로 둔다. |
| P0: 관측 없는 경우 | 구동 온도 차이는 절댓값 2…10°C 또는 35…75°C이며 반대 부호 조건도 존재하지만 정확한 0 구동 조건은 없음 | 열적 구동이 없는 감육과 센서 변동을 분리해 검증할 수 없다. 0/low/high의 구동 조건을 명시한다. 열적 단서 부재를 무결함 정답으로 바꾸지 않는다. |
| P0: 잡음·품질 책임 분리 | 독립 동일 분산 Gaussian noise, 공통 정합·보정·PSF; σ `.03/.1`, stress `.3/.45`; 정답 경계에 알려진 σ를 사용 | 정상 반복을 단순 독립 잡음 제거 문제로 좁힌다. 공통/프레임별 오차와 정합·보정 실패 fixture를 분리한다. sigma를 쓰는 정답은 합성 가시성 규칙이지 실측 결함 라벨이 아니다. |
| P1: 복사·광학 순서 | `apparent_temperature`는 광대역 `T⁴` 회색체 혼합, 이후 온도 공간에서 Gaussian blur | 실제 제한 대역 센서의 응답·광학 혼합을 복제하지 않는다. 제안한 대역 복사 proxy에서 광학 PSF를 적용한 뒤 가정한 센서 응답·보정 역변환을 수행한다. flat response라는 한계는 유지한다. |
| P1: 반사·방사율 다양성 | 매 프레임의 카메라 설정은 .95/ambient, 표면 방사율에 고정 sinusoid, 반사장은 `ambient+8*cos(...)`, 각 개입은 같은 단일 patch | 패턴 종류와 설정 오차가 제한된다. 표면 상태·공간 반사장·카메라 설정 오차를 분리하되 임의 합성 분포를 현장 빈도라고 부르지 않는다. |
| P1: 불량 픽셀 정보 | 불량 비율 `.0005`, 관측값은 0°C로 채움; 정답은 ignore 처리하지만 기존 3채널 입력은 해당 mask를 직접 받지 않음 | 0°C 자체는 불량 표시가 아니다. 실제 센서가 제공한 유효성 정보와 합성 정답용 mask를 구분하고 출력 제외 계약을 검증한다. clean/GT mask를 일반 추론 입력으로 몰래 제공하지 않는다. |
| P1: 시험 범위 | stress에서 직경 219 mm, blur 2.2, noise .3/.45가 함께 바뀜. 모든 split은 같은 생성기 계열 | 복합 실패의 원인을 분리하기 어렵고 외부 일반화 증거가 아니다. 단일 요인 stress와 조합 stress를 구분하고, 설비·장면·센서 세션 그룹을 분할 경계에서 보존한다. |

중요한 라벨 구분: v1의 reflection/emissivity 변화가 양성인 것은 **겉보기 열 변화 관측**이라는 현재 과제 정의와 맞는다. 이를 곧바로 “오경보”나 “결함”으로 다시 이름 붙이지 않는다. v2에서는 장면의 겉보기 변화, 센서 자체 오차, 판독 불가 상태, 잠재 물리 결함을 서로 다른 필드로 관리해야 한다.

## 5. v2에 반영하기로 한 설계와 검증 조건

다음은 구현 담당과 합의한 설계 방향이다. 이 문서 작성 시점에는 완성 코드·출력의 검증을 의미하지 않는다.

1. **24개 조건:** 보온 2 × 방사율 2 × 열적 구동 3(0/low/high) × 잡음 2. pose·blur·patch는 독립 난수로 설정한다. 균등 셀은 실험 설계이며 현장 발생률이 아니다.
2. **일반 LWIR 센서:** 7.5–14 µm 구간은 S2를 참고하고, 이상적 평탄 응답과 128×160 계산 격자는 공학 가정으로 표시한다. 실제 A70 복제·보정이라고 부르지 않는다.
3. **잡음 성분 분리:** 30°C에서 정의한 합성 등가 read-noise 계수, bounded fixed-pattern/gain/offset, 정합·drift 품질 fixture를 분리한다. 각 계수의 값·단위·분포·장면/센서/프레임 공유 범위를 manifest에 기록한다. NETD fitting이라는 표현을 쓰지 않는다.
4. **라벨 경계 보존:** 실제 입력은 관측 reference/current만 사용한다. clean signal은 합성 관측 정답 생성·검증에만 사용한다. 정합 실패나 보정 불일치가 정상 음성으로 들어가지 않도록 품질 경로에서 보류한다.
5. **수치·구조 시험:** 같은 장면·같은 이상적 센서이면 clean 차이가 0인지, 고정 패턴과 frame drift의 공유 방식이 의도와 맞는지, band response가 온도에 대해 단조인지, 포화·불량 mask가 손실/지표에서 일관되게 제외되는지 검사한다. PSF는 표준편차 숫자만 바꾸는 대신 실제 적용 공간과 순서를 확인한다.
6. **재현성과 한계:** 생성기·파라미터·출처 원장 해시를 동결한다. train/dev/test의 장면·센서 그룹 누수를 검사한다. 합성 시험 개선은 현장 성능·NDT 결함 발견·사고 예방의 증거로 확대하지 않는다.

후속 실측이 가능해지면 균일 흑체의 여러 온도·카메라 안정화 시간·반복 프레임, 공간 잔차, 실제 렌즈의 edge/spot 응답, 표면 방사율·반사 조건을 기록해 가정을 갱신한다. 이것은 향후 필요한 측정 제안이며, 현재 확보한 자료가 아니다. S1의 고배율 장비 절차를 현장 LWIR에 그대로 적용한다는 뜻도 아니다.

## 6. 이번 코드 검토의 고정 지점

| 파일 | SHA256 |
|---|---|
| `maek/thermal_observation_synth.py` | `64eeae793f8412287e0ada94d26939403c407bc667bf7ab5a0f3c4bf068634c2` |
| `maek/thermal_feasibility.py` | `18c67a75deacc9331ea12d5365f7b4d1ffb28b015205d1a062dc8e412ecbd195` |
| `maek/thermal_surface_solver.py` | `2fe8f5c1d430f1cf91298a91f0904f52108ee8f066e32bac67c41697cb079891` |
| `scripts/generate_thermal_observation_dataset.py` | `ca78a310b5b949ca005369fd4444909a58ced0c9ac8867158f17138973e931f2` |

문헌의 확인 범위, 공식 사양의 조건, 코드에서 관찰한 사실, 아직 검증하지 않은 v2 설계를 구분했다. 이번 작업은 문서 작성만 수행했으며 생성기 변경·새 데이터 생성·학습·현장 측정은 수행하지 않았다.
