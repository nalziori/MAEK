# GEMINI.md — MAEK (Antigravity 작업 지침)

POSCO AI Hackathon 2026 안전 주제 출품작. 제철소 배관 이상 탐지 및 점검 전략 평가를 위한 디지털 트윈 시뮬레이터.
드론 카메라·열화상 1차 선별 → 의심 지점 초음파(UT)·펄스 와전류(PEC) 정밀 검사 → 위험도 기반 정비 우선순위 도출.
합성 배관망에서 몬테카를로 시뮬레이션으로 사람+비계 / 드론 / 드론+AI 세 방식을 비교 평가합니다. 모든 수치는 합성 데이터이며 현장 실측치가 아닙니다.

## 주요 구조 및 파일

- `maek/network.py`: 가상 배관망 및 결함 주입 (세그먼트, 형상 특성, 결함 모델링).
- `maek/strategy.py`: 3가지 점검 전략 비교 시뮬레이션, 민감도 분석, `sweep`, `pit_prior`.
- `maek/ut.py`, `pit.py`: 초음파 A-scan 파형 생성, 균열/두께/피팅 신호 처리 및 검출.
- `maek/thermal*.py`, `pec.py`, `heat.py`, `energy.py`, `eva.py`: 열화상 모델, PEC 검사, 열전달·에너지 손실 계산, 극치통계 분석.
- `maek/camera/`: 2D 합성 렌더러 (이미지, 마스크, YOLO-seg 라벨).
- `maek/cli.py`: CLI 진입점 (`python -m maek <command>`).
- `config/default.yaml`: 기본 파라미터 정의 (`value`, `unit`, `assumption`, `note`).
- `config/scenarios/*.yaml`: 시나리오 오버레이 (예: `--scenario steam`). CLI 인라인 오버라이드는 `--set key=value`.
- `scripts/produce_data.py`: 전체 데이터셋 생성 스크립트 (`data-v3` 브랜치 기준).
- `posco_pipe_length_scenario_2026-11-06.json`: 포항·광양 배관 길이 시나리오 (11개 매질 분류, 3개 스케일링 케이스).

## 실행 및 테스트 명령

- 기본 검사: `ruff check .` 및 `pytest -q tests/test_<대상>.py`
  - *Windows 환경 주의:* `maek/onboard.py`가 Unix 전용 `resource` 모듈을 참조하므로, Windows 로컬 실행 시 `test_eval_onboard.py`를 제외하거나 특정 테스트 파일을 지정해 실행합니다 (`pytest -q tests/test_docs.py`, `pytest -q tests/test_network.py` 등). CI는 Python 3.12 (Linux)에서 동작합니다.
- 재현성 보장: 실행 전 단일 스레드 설정 필수
  - PowerShell: `$env:OMP_NUM_THREADS='1'`
  - Bash: `OMP_NUM_THREADS=1`
- 빠른 전략 실행 확인:
  `python -m maek strategy --runs 2 --seed 1 --total-km 20`
- 파라미터 문서 동기화:
  `python -m maek params-table --write` (수정 후 `tests/test_docs.py` 통과 확인)

## 작업 원칙 및 주의사항

1. **데이터 성격 명시**: 모든 결과는 가상 배관망 시뮬레이션 기반의 합성 데이터입니다. "비용 절감"보다는 "동일 비용 투입 시 고위험 결함 탐지율 대폭 향상" 논리를 유지합니다.
2. **파라미터 추적성**: 새 파라미터 추가 시 `config/default.yaml`에 출처 또는 `assumption: true`를 필수로 기재하고, `docs/params.md`를 갱신합니다.
3. **데이터 브랜치**: 대용량 합성 데이터는 `data-v3` 브랜치를 사용하며, 작업 트리 내 `data/` 경로를 임의로 커밋하지 않습니다.
4. **다중 에이전트 협업 (Reason Network)**:
   - `maek-claude` (Claude Code, `CLAUDE.md`)
   - `maek-codex-6` (Codex, `AGENTS.md`)
   - `maek-antigravity` (Antigravity, `GEMINI.md`)
   - 동일 저장소 및 작업 디렉터리를 공유하므로 다른 에이전트가 작업 중인 파일을 동시에 수정하지 않으며, 작업 분담은 메시지로 조율합니다.
   - 요청 없이 임의 커밋을 수행하지 않습니다.
