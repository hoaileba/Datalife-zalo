# DataMate v4

Zalo AI Challenge 2026, DataMate: Vietnamese questions over a shop's spreadsheets, answered by a code agent
(Gemma 12B via vLLM writes one pandas program; a sandbox runs it; the host checks and submits).

- Rules for working here: `CLAUDE.md`, `AGENTS.md`. Code map: `MAP.md`.
- Setup: Python 3.12, `pip install -e .` (pandas 2.2.3, numpy 1.26.4 pinned: the idioms the model writes); `.env` with `VLLM_BASE_URL` (and `VLLM_API_KEY`).
- Data: `data/train`, `data/public_test` (not in git).

| Command | What |
|---|---|
| `make test` | all tests, synthetic data, no model calls (< 30 s) |
| `make dev SPLIT=train N=5` | 5 questions end to end; prints aggregates (health, PA) |
| `make replay RUN=outputs/runs/<run> SPLIT=train` | re-run logged programs with current host code |
| `make predict DATA=/data RESULT=/result` | submission run: `/result/submission.jsonl` + `/result/logs/` |
| `make view` | trace viewer for `outputs/runs` (http://localhost:8765) |
| `python -m gen.teacher ...` | teacher (DeepSeek) runs for training data, one detailed JSON per question; stats: `gen.teacher_stats`; prompt review: `scripts/prompt_md.py` (guide: `docs/TEACHER_GEN.md`) |

Outputs of a run: `submission.jsonl` (one line per question, written as each finishes), `logs/<id>.json` (answer,
seconds, model outputs, code, stdout, errors), `summary.json` (health and, when answers exist, local PA).

Model: `google/gemma-4-12B-it` (12B parameters), temperature 0, seed 0, thinking off.
