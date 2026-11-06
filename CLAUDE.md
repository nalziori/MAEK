# CLAUDE.md — MAEK

POSCO AI Hackathon 2026 safety entry. Synthetic digital-twin simulator for steel-mill piping inspection:
drone camera/thermal screening → targeted UT/PEC → risk-ranked inspection order.
Compares 사람+비계 / 드론 / 드론+AI by Monte Carlo on a generated pipe network. All data is synthetic.

## Layout
- `maek/network.py` — pipe network + defect injection (segments, features, defects). Driven by `network.*` in config.
- `maek/strategy.py` — three-strategy comparison, sensitivity, `sweep`, `pit_prior`.
- `maek/ut.py`, `pit.py` (UT A-scan, crack/thickness/pit), `thermal*.py`, `pec.py`, `heat.py`, `energy.py`, `eva.py` (extreme-value pitting), `camera/` (2D renderer), `evaluate.py`, `onboard.py`, `pod.py`.
- `maek/cli.py` — all subcommands (`python -m maek <cmd>`). `scripts/produce_data.py` — full data release.
- `config/default.yaml` — every parameter with `value`, `unit`, `assumption`, `note`. `config/scenarios/*.yaml` overlay it (`--scenario steam`). One-off override: `--set key=value`.
- `docs/` — results, params (generated: `python -m maek params-table --write`), cost model, robustness, overview.
- `posco_pipe_length_scenario_2026-11-06.json` — Pohang/Gwangyang pipe-length scenarios (11 media classes, 3 scaling cases). Not yet wired into config.

## Commands
- Test: `pytest -q`; lint: `ruff check .` (CI runs both on PRs).
- Reproducible runs: prefix `OMP_NUM_THREADS=1`.
- Quick check: `python -m maek strategy --runs 2 --seed 1 --total-km 20`.

## Rules
- Every new parameter goes in YAML with source or `assumption: true`; regenerate `docs/params.md`; `tests/test_docs.py` checks docs.
- Never present synthetic numbers as POSCO field data. Claim "같은 돈으로 더 많이 찾는다", not "싸다".
- Data branches: use `data-v3` only. Don't commit data under `data/`.
- Branch off `main` for PRs; this checkout is `docs/initial-research`.

## Multi-agent setup
- Peers on Reason Network: `maek-codex-6` (Codex, AGENTS.md), `maek-antigravity` (Antigravity, GEMINI.md). Same repo/branch, same working tree — don't edit a file another agent is editing; coordinate by message.
- Shared memory / large data: Google Drive `/MAEK/agents-shared` (folder id `1ZkOAIczN7VxxhG-Ue4Ih3b_yJLRKjBPg`). Rules in its README.md. Name files `YYYY-MM-DD_claude_<topic>`. Claude reaches it via the claude.ai Google Drive connector.
