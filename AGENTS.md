# MAEK — Codex 작업 지침

MAEK은 제철소 배관 결함과 점검 전략을 합성 데이터로 평가하는 Python 시뮬레이터다. 카메라·열화상 선별과 초음파·PEC 확인을 모델링한다. 결과는 현장 검증 성능이 아니며, 비용·센서·설비 구성의 가정을 실제 값으로 표현하지 않는다.

## 시작점

- 프로젝트 개요와 명령: `README.md`, `docs/project-overview.md`
- 가상 배관망과 결함: `maek/network.py`; 점검 전략: `maek/strategy.py`; 초음파: `maek/ut.py`
- 설정: `config/default.yaml`, 시나리오 덮어쓰기: `config/scenarios/steam.yaml`; CLI: `maek/cli.py`
- 평가와 한계: `docs/results.md`, `docs/steam-scenario.md`; 전체 데이터 생성: `scripts/produce_data.py`
- `posco_pipe_length_scenario_2026-11-06.json`은 합성 길이 시나리오이며 실제 설비 목록이 아니다.

## 실행 및 확인

- 의존성: `pip install -r requirements.txt`
- CLI: `python -m maek --help`; 예: `python -m maek strategy --scenario steam --runs 20 --seed 1`
- 재현 실행 전 스레드를 하나로 고정한다. PowerShell: `$env:OMP_NUM_THREADS='1'`.
- 관련 테스트: `python -m pytest -q tests/test_<대상>.py`; 전체 CI 검사: `ruff check .` 및 `python -m pytest -q` (CI는 Python 3.12).
- 전체 데이터 생성: `python scripts/produce_data.py`; 대용량 결과와 실행 시간을 고려하고 출력 경로의 기존 데이터를 보존한다.

## 작업 시 주의

- 설정의 출처·가정 표기를 유지하고 시드, 단위, train/shifted 구분을 보존한다. 결과 수치 변경 시 해당 평가와 문서를 함께 확인한다.
- `data-v3`는 최신 합성 데이터 브랜치다. `data`와 `data-v2`는 이전 버전이다.
- 공유 작업 중이므로 기존 변경을 보존하고, 요청 없이 커밋하거나 다른 에이전트의 지침 파일을 수정하지 않는다.
