# 열화상 개선·Jetson 검증 문헌 근거

확인일: 2026-11-07. 이 문서는 문헌의 관찰, MAEK에 대한 제안, 아직 검증하지 않은 내용을 구분한다. 논문 수치를 MAEK의 성능으로 환산하지 않는다. 실제 Jetson, 설치된 JetPack, TensorRT 실행 여부를 확인한 문서가 아니다.

## 1. Passive multivariate thermography

Vieira de Souza, López, Maldague, **Corrosion under insulation mitigation by passive multivariate thermography**, DOI **10.1080/17686733.2024.2305917**. 온라인 공개 2024-01-22, 저널 권호 22(2), 2025.

- **직접 확인 범위:** 출판사 초록과 서지정보. 원문 실험·수식·코드는 확보하지 못했다.
- **확인 사실:** 단열재 내부 수분을 수동 열화상으로 탐지하는 연구다. 공정 변화와 외부 환경 상호작용 중 열적 거동을 다루고, PLS가 물리 현상을 분리하고 낮은 표면 방사율의 외장에서도 활용 가능성을 넓혔다고 보고한다. [출판사 초록](https://www.tandfonline.com/doi/full/10.1080/17686733.2024.2305917)
- **MAEK 제안·추론:** 환경·공정 변화와 결함의 영향을 구분한다는 방향을 채택한다. 실제 시간축 변화와 환경 변수가 있는 자료를 확보한 뒤 별도 다변량 실험을 설계한다. 독립적인 단일 스냅숏에 공간 배경 제거만 적용하고 이 논문의 재현이라고 부르지 않는다.
- **미확인:** 원문의 정확한 시계열 길이, 센서 종류, 입력 행렬, PLS 성분 수, 분할 방법 및 수치 성능. 초록만으로 특정 환경 센서 조합이나 구현식을 확정할 수 없다. 수분 위험 징후 탐지와 실제 부식량 확정도 구분한다.

## 2. Synthetic datasets 기반 배관 사례

Rezayiye, Ibarra-Castanedo, Maldague, **Methods for Corrosion Detection in Pipes Using Thermography: A Case Study on Synthetic Datasets**, DOI **10.3390/a17100439**, Algorithms 2024, 17, 439.

- **직접 확인 범위:** 논문 PDF의 §4.1–4.3, Table 4–5, 결론. MDPI 직접 접근은 제한되어 동일 출판 논문 PDF 미러로 확인했다. 이차 요약의 주장에 의존하지 않았다.
- **확인 사실:** 6개 강관, 12.7 mm 유리섬유 단열재, 0.76 mm 알루미늄 외장과 젖은 단열재를 사용했다. FLIR T650Sc 640 × 480 영상에 median filtering을 적용했으며 알려진 결함 위치로 ROI를 정의했다. FEM은 정상상태·균질 재료·관 끝 열손실 없음, 관내 Mobil Therm 603 강제대류, 외부 자연대류와 복사 조건이다. 외장 방사율은 **0.9**로 설정한다. [논문 §4 원문](https://pdfs.semanticscholar.org/2bd9/1295d8ea0ffe5a60f0f1b70b436f8fb4b4a4.pdf), [정식 DOI](https://doi.org/10.3390/a17100439)
- **보고 결과:** 실험 20장만 사용한 학습과 실험 20장 + FEM 2000장 학습을 비교한다. F1 0.89→0.90, Mean IoU 0.66→0.87을 보고한다. 이는 해당 논문의 실험이며 MAEK 결과가 아니다. [Table 5 및 §4.3](https://pdfs.semanticscholar.org/2bd9/1295d8ea0ffe5a60f0f1b70b436f8fb4b4a4.pdf)
- **MAEK 제안·추론:** 물리조건을 맞춘 합성자료와 별도 실측 검증의 근거로 활용한다. 방사율 0.9 결과를 저방사율 외장의 반사·바람·일사 변화에 일반화하지 않는다. 알려진 결함 ROI도 실제 탐지기 입력에 제공하지 않는다.
- **미확인:** MAEK 저방사율 조건에서의 효과, 현장 오경보, Jetson 지연. 이 논문에서 확인하지 않은 외부 램프 가열이나 정확한 가열온도를 추가로 단정하지 않는다.

## 3. Xie: 공간 중심–주변 대비

Xie et al., **Small target detection based on accumulated center-surround difference measure**, DOI **10.1016/j.infrared.2014.07.006**, Infrared Physics & Technology 67 (2014), 229–236.

- **직접 확인 범위:** 저자 공개 PDF §2, §3, Table 1.
- **확인 사실:** 중심 픽셀 주위 두 창에서 8방향 차이를 누적하고, 방향별 값의 최솟값으로 측정맵을 만든다. 여기서 누적은 공간 방향상의 누적이다. 시간축 누적으로 해석하면 안 된다. 구름 경계·하늘과 바다 경계 등 클러터 속 적외선 소형 표적을 대상으로 검증했다. [저자 공개 원문](https://www.kerenfu.top/sources/SDAC2014.pdf)
- **MAEK 제안·추론:** 작은 국소 이상과 긴 경계의 구분이라는 아이디어만 시험한다. 단순 box-filter 차이 또는 임의 다중 스케일 잔차는 원문 ACSDM과 같은 구현이 아니다. 새 후보라면 이름과 수식을 별도로 명시한다.
- **미확인:** 배관 수분·부식·일사 반사에 대한 검증, MAEK 오경보 감소, Jetson 속도. 원문의 픽셀 단위 ROC와 정상 이미지별 오경보율은 분모가 다르다. 원문 128 × 128 계산시간을 다른 해상도·하드웨어의 지연으로 전용하지 않는다.

## 4. Gao: 패치 저랭크·희소 분리

Gao et al., **Infrared Patch-Image Model for Small Target Detection in a Single Image**, DOI **10.1109/TIP.2013.2281420**, IEEE TIP 22(12), 4996–5009 (2013).

- **직접 확인 범위:** 저자 출판 목록, 저자 공식 저장소 README와 APG_IR.m. IEEE 원문 페이지는 로봇 확인에 막혔으므로 논문 전체를 읽었다고 표시하지 않는다. [저자 서지](https://www.cs.cmu.edu/~deyum/Publications.htm), [정식 DOI](https://doi.org/10.1109/TIP.2013.2281420)
- **확인 사실:** 공개 핵심 구현은 저랭크 성분과 희소 성분을 추정하며 반복 루프에서 SVD를 수행한다. 저장소는 분할 단계가 포함되지 않으며 응용 시 전처리·후처리와 파라미터 검토가 필요하다고 명시한다. [APG_IR.m](https://github.com/gaocq/IPI-for-small-target-detection/blob/master/APG_IR.m), [저자 README](https://github.com/gaocq/IPI-for-small-target-detection)
- **MAEK 제안·추론:** 배경과 국소 이상을 분리하는 근거로 참고하되, 반복 SVD·패치 행렬 메모리 비용이 있는 방법을 속도 개선으로 선제 도입하지 않는다. 간단한 잔차 후보를 먼저 측정한다.
- **미확인:** 원문 전체 실험조건, MAEK 배관 검증, Jetson 실시간성. 저자 코드는 비상업 연구용 무료 사용 조건이므로 코드를 제품에 그대로 복사하는 근거로 삼지 않는다.

## 5. YOLOBench: 비교 방법의 근거

Lazarevich et al., **YOLOBench: Benchmarking Efficient Object Detectors on Embedded Systems**, ICCVW 2023.

- **직접 확인 범위:** 사용자 지정 CVF PDF는 직접 열기에서 403; 검색 인덱스와 저자 arXiv 원문의 §3을 확인했다. arXiv 버전과 CVF판의 모든 문구가 동일한지 대조하지는 않았다. [CVF 원본](https://openaccess.thecvf.com/content/ICCV2023W/RCV/papers/Lazarevich_YOLOBench_Benchmarking_Efficient_Object_Detectors_on_Embedded_Systems_ICCVW_2023_paper.pdf), [저자 arXiv 원문](https://arxiv.org/pdf/2307.13901)
- **확인 사실:** 550개 이상 YOLO 기반 객체 탐지 모델과 4개 데이터셋을 비교한다. 지연 측정 플랫폼은 Jetson Nano GPU / ONNX Runtime FP32, VIM3 NPU / INT16, Raspberry Pi 4 / TFLite XNNPACK FP32, Intel i7-10875H / OpenVINO FP32다. batch 1, warmup 5회, 200회 평균이며 그래프 실행시간에서 NMS를 제외한다. VIM3는 box decoding도 제외한다. [§3](https://arxiv.org/pdf/2307.13901)
- **MAEK 제안·추론:** 모델·해상도·정밀도·런타임·batch·워밍업·측정 경계를 함께 고정·기록한다. YOLO11-seg의 마스크 후처리를 포함한 전체 파이프라인은 따로 측정한다.
- **미확인:** Orin Nano Super, YOLO11-seg, MAEK 열화상 지연. Jetson Nano 수치를 Orin Nano 수치로 바꾸거나 탐지 모델의 graph-only 평균을 분할 E2E p95로 대체할 수 없다.

## 6. NVIDIA TensorRT: 실측의 경계와 환경

**Performance Benchmarking**, NVIDIA TensorRT 공식 문서. latest URL은 변경 가능하므로 실제 사용 시 설치 버전 문서를 함께 확인한다.

- **직접 확인 범위:** warm-up, 측정 반복, wall-clock/CUDA events, 메모리, 하드웨어 환경 절.
- **확인 사실:** 워밍업 후 측정하고 wall-clock 측정에서는 비동기 GPU 실행의 완료를 동기화해야 한다. CUDA event 시간과 전체 애플리케이션 시간은 목적이 다르다. 클록·전력·온도가 결과를 바꿀 수 있으며 nvidia-smi 관련 절차는 dGPU용이고 Jetson/iGPU에는 적용되지 않는다고 명시한다. [공식 benchmarking 문서](https://docs.nvidia.com/deeplearning/tensorrt/latest/performance/benchmarking.html)
- **Jetson 보조 근거:** tegrastats는 RAM/SWAP, CPU/GPU 사용·주파수, 온도·전력 등을 보고한다. RAM은 시스템 사용량이며 해당 Python 프로세스 RSS와 동일하지 않다. 표기 필드와 사용 가능 센서는 기기·버전에 따라 확인한다. [Jetson Linux r36.4.4 tegrastats 문서](https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegrastatsUtility.html)
- **MAEK 제안:** 모델 로드·엔진 빌드는 정상 추론 지연과 분리한다. E2E는 전처리→추론→필요한 동기화→마스크·판정 후처리로 명시한다. 고정된 표본과 실행 순서를 사용하고 p50/p95, 각 실행 원자료, 프로세스 peak RSS, CUDA allocator 사용량(가능한 런타임만), 시스템 RAM을 각자 보고한다. tegrastats·전력모드·클록·냉각 상태와 JetPack/L4T/CUDA/TensorRT 버전을 함께 저장한다. p95는 실제 표본으로 계산하며 평균 FPS의 역수로 대신하지 않는다.
- **미확인:** 사용자의 설치된 JetPack/TensorRT 버전, 실제 장치 전력모드, FP16·INT8 지원 상태, 실제 지연·온도·메모리. 누락 항목은 unavailable로 남기고 결과를 만들어 채우지 않는다.

## 채택 판단

현재 단일 스냅숏 입력에는 배경 잔차와 공간 대비를 작은 비교 후보로 검토한다. 시간·환경 다변량 방식은 해당 입력을 갖춘 별도 실험으로 남긴다. 합성 shifted 결과는 조건별 진단이며 실측 현장 검증을 대신하지 않는다. 후보 채택은 동일 분할에서 결함 성능과 정상 오경보를 함께 비교하고, 별도 미공개·실측 자료와 실제 장치 측정으로 확인한다. 위 문헌 검토 자체는 성능 개선이나 탑재 성공을 증명하지 않는다.