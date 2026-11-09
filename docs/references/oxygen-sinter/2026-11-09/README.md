# 산소 공급·소결 2차 집진 원문 근거 기록

기록일: 2026-11-09. 작성 범위: `docs/references/oxygen-sinter/2026-11-09/`.

이 문서는 공개 1차 자료에서 확인한 사실, 자료를 조합한 개념 구성, MAEK 적용 판단을 구분한다. **실제 고로 P&ID가 아니며, 좌표·치수·운전 조건은 미보정이다. 사고현장 복제도 아니다.** 이 문서는 원문 근거 검토 기록이며, 구현 범위와 실행 검증은 [증설·배포 검토](../../../reviews/oxygen-sinter-delivery-20261109.md)에 따로 기록한다. 문서의 화살표는 개념상의 흐름이며 설계·시공·운전 지시가 아니다.

## 1. 근거와 확인 수준

| 출처 ID | 확인한 사실 | 원문 위치 | 적용 한계 |
| --- | --- | --- | --- |
| EIGA-DOC13-20 | 산소 필터의 차단 구성, 공급 배관에 연계한 계량·제어 기능 | [EIGA Doc 13/20](https://www.eiga.eu/uploads/documents/DOC013.pdf) §5.4.3, §8.1–8.2 | 일반 기체 산소 배관 지침. 특정 고로 도면이 아님 |
| CP-TATA-SINTER-SECONDARY | Tata Port Talbot 소결공장 기존 secondary 계통에 bag filtration 및 연결 덕트 설치 | [C&P 사례](https://www.cpengineering.co.uk/case_study/tata-steel-filtration-plant/), 제목 아래 첫 문단 및 external ductwork 문단 | 시공 참여사의 실제 사례 설명. 후드별 배치·fan 위치·전체 P&ID 미제공 |
| PRIMETALS-SDS | 일반 2차 집진 구성과 소결/펠릿 room dedusting 적용 범주 | [Primetals SDS](https://www.primetals.com/en/portfolio/solutions/environmental-solutions/secondary-dedusting-systems/), Enhance… 본문과 Applications | 여러 공정의 일반 설명. Tata 현장의 상세 구성 증거가 아님 |
| PRIMETALS-MEROS | 소결 공정 배가스의 별도 처리 문맥 | [Primetals MEROS](https://www.primetals.com/en/portfolio/solutions/environmental-solutions/meros-gas-cleaning-plant/), Advanced Off-Gas Cleaning… 첫 세 문단 | secondary 집진의 설치 사례나 Tata의 MEROS 채택 증거가 아님 |

HTML은 제목·문단 시작어로 다시 찾을 수 있게 `sources.json`에 기록했다. 웹 도구의 임시 줄 번호는 영구 원문 위치로 쓰지 않았다. 페이지 게시일과 현 시점 설비 운전 상태는 확인하지 않았다.

## 2. 산소 공급: 소비처 인입경계까지

```text
supply pipeline
  -> inlet block valve -> filter -> outlet block valve
  -> meter/control station functions
  -> consumer inlet boundary [이 문서의 모델 범위 끝]

filter 후단 ~ outlet block 전단: vent 분기 근거 있음
```

**원문 사실:** §5.4.3.6은 청소를 위한 필터 입·출구 차단밸브와 위 vent 위치를 설명한다. 공급 중단이 불가능한 경우의 병렬 필터도 다룬다. §5.4.3은 역류·차압·재료 관련 위험을 함께 설명하므로 단순 필터 외형만으로 안전성이 입증되지 않는다. §8.1은 공급 배관과 연계된 gas control/metering 기능을, §8.2는 고객·현장 조건, P&ID를 포함한 설계기준과 위험 검토를 다룬다. §8.2.2–8.2.4에는 인입 필터, 계량, 유량·압력 제어 기능이 있다.

**프로젝트 해석:** 위 순서는 해당 구성요소를 조합한 단순 개념안이다. `meter/control` 내부의 고정 순서나 실제 밸브·계기 사양을 원문이 보증하는 것은 아니다. 새로 만드는 oxygen 공급계통의 범위는 **소비처 인입경계까지**이며 **실제 BF 풍구 연결은 미구현**으로 명시한다. 이 문서에서 구현 유무를 코드로 재검증한 것은 아니며, 후속 구현이 지켜야 할 범위 선언이다.

원문 위치: 로컬 PDF **29–30쪽 = 인쇄 25–26쪽**(§5.4.3, 다음 쪽으로 이어짐), **47–49쪽 = 인쇄 43–45쪽**(§8.1–8.2 전체). PDF 1–2쪽에서 `Doc 13/20`, `Revision of Doc 13/12`, 2020-08-26 오탈자 정정을 확인했다. PDF 5쪽/인쇄 1쪽의 §2는 기체 산소 배관의 적용 범위 및 완전한 설계 편람·의무 코드가 아니라는 한계를 명시한다. 최신판 여부와 현장 적용 적합성은 별도 확인 대상이다.

## 3. 소결: secondary 집진만의 개념 흐름

```text
secondary collection hoods
  -> merging duct -> bagfilter -> induced fan -> clean stack
```

**현장 사실과 일반 원리의 구분:** C&P는 Tata Port Talbot의 실제 소결 secondary bag filtration 사례를 확인해 준다. Primetals SDS는 후드·덕트·필터·ID fan·stack 구성과 소결 room dedusting 적용 범주를 설명한다. 위 전체 흐름, 특히 필터 후단 fan 배치는 이를 바탕으로 선택한 **프로젝트 개념 구성**이다. 실제 Tata 현장의 접속 순서·배관도·장치 위치를 복제하거나 검증한 결과로 표기하지 않는다.

소결 **primary process off-gas와 secondary room dedusting는 별도 계통**으로 취급한다. MEROS 원문은 소결 공정 배가스 처리 문맥을 보완할 뿐, 이 secondary 흐름에 MEROS를 추가할 근거가 아니다. SDS 본문 중 EAF/AOD의 primary 가스 혼합 예시를 소결 계통에 옮기지 않는다.

SDS 사진 캡션의 `LD converter (BOF)` 및 `Dillinger Hüttenwerke, Germany`는 BOF 사례다. **BOF 사진을 sinter 사진으로 사용하지 않는다.** 공정이 특정되지 않은 일반 bagfilter 사진도 소결 실설비의 증거로 재명명하지 않는다. 이 작업에서는 웹 사진을 다운로드하거나 복제하지 않았다.

## 4. MAEK 관측과 의사결정의 경계

계획서는 상위 작업에서 Google Drive 원문을 조회해 확인했다. 제출일 **2026-11-09**, revision:

```text
AHj4eMSMkDcF8Q6MWzoFzKATf2t2hqmYY7y9ZbfvHZ3Ex7XGjYZc-2G9jm2Gdm_TdT56MkcgIYf81jb7N_VBGkh8iwLqwucD_j4wk7VbJzM
```

상위 작업에서 Google Drive로 [최신 계획서 원문](https://docs.google.com/document/d/1FfAsoZOnLjI0hc3uvzqAkWLmLkO8IS1IBK8JXm9SqAg/edit?tab=t.0)을 조회한 뒤 아래의 목표 정합성을 확인했다. 이 원문 근거 문서 자체는 실행 검증 보고서와 구별한다.

| 단계 | 문서에서 허용하는 해석 | 완료로 주장하지 않는 사항 |
| --- | --- | --- |
| sensor AI 구상: RGB / UT / IR | 센서별 관측 증거를 구별해 취합하는 계획 | 세 센서의 통합 학습·실증 완료 |
| RGB 외관 후보 | 현재 RGB는 **HSV baseline only**. 외관 이상 후보와 위치를 추가검사 입력으로 사용 | 부식 깊이·잔존 두께·누설·파열 또는 내부 결함 확정 |
| UT 추가검사 | RGB 후보에 대해 UT 두께 등 추가 증거를 확보하는 후속 검사 경로 | 실제 UT 측정 완료, 자동 합격 판정 또는 현장 접근 가능성 평가 |
| IR 관측 | 열적 관측 증거를 별도로 취급 | 표면 온도 이상만으로 벽 두께나 구조 건전성 확정 |
| 의사결정 | **안전 / 품질 / 공정 영향**을 분리 평가하고 **예산 기반 우선순위**와 구분해 연결 | HSV 점수를 안전등급으로 직접 치환, 예산 순위를 안전 승인으로 간주 |
| 작업허가 | **not_assessed** | 작업허가 적합성·발급·운전 지속 승인 |

산소·집진의 공개 공정 자료는 관측 대상을 설명하는 근거다. RGB→UT 검사 경로의 현장 성능이나 센서별 판정 임계값을 검증하는 실험 근거는 아니다. 어떤 부위가 보이는지, UT 접근과 검사법이 적합한지, 안전·품질·공정 영향 점수 및 비용 가중치는 현장 근거 없이 보정하지 않았다.

## 5. 공개 접근과 저작권

공개 URL에 로그인 없이 접근할 수 있다는 사실과 원문·사진을 재배포할 권한은 구분한다.

- EIGA PDF 2쪽: EIGA 2020 저작권 및 **EIGA를 출처로 명시하는 조건의 publication 복제 허용**을 확인했다. 조건 없는 자유 라이선스로 표시하지 않는다. 로컬 사본은 검토용으로 보관하며, 원문 동봉 배포 시 허가 조건을 확인·준수해야 한다. 해당 조건을 넘는 변경물·제3자 자료 이용 권한은 미확인이다.
- C&P·Primetals: 공개 본문 접근을 확인했지만 사진·본문의 별도 재사용 허가나 자유 라이선스는 확인하지 않았다. 원문 링크와 제한적인 자체 요약만 기록했다.
- **무단 재배포 금지. 권한이 불확실한 원문·이미지는 배포물에 포함하지 않는다.** 이 문서는 법적 권리 판단을 완료했다는 선언이 아니다.

`originals/EIGA-DOC013.pdf`는 공식 URL에서 받은 원본 바이트다. SHA-256·파일 크기·쪽수·권한 확인 위치는 `sources.json`에 기록했다. 공개 저장소 커밋·업로드·외부 배포는 이 작업에서 하지 않았다.

## 6. 확인 결과와 남은 한계

원문 PDF 식별자·관련 절의 연속 페이지, 공식 HTML의 공정 식별 및 사진 캡션을 확인했다. 산소·소결 사실은 `sources.json`의 claim/source ID로 연결했다. JSON 파싱, 출처 참조, 로컬 PDF 해시·쪽수, 필수 경계 문구를 최종 검증 대상으로 삼았다.

확정한 문서 결정은 산소 소비처 인입경계, 소결 primary/secondary 분리, BOF 사진 전용 금지, RGB 외관 후보→UT 추가검사 및 작업허가 미평가다. 현장 P&ID·치수·좌표·운전 보정, 실제 BF 연결, 센서 실증, 계획서의 독립 재열람, 최신 규격 확인, 미확인 자료의 재사용 권한은 해결하지 않았다. 실제 하위 에이전트 실행 도구가 제공되지 않아 병렬 위임은 수행하지 못했고, 독립 원문 조회 후 단일 작성자가 통합했다.
