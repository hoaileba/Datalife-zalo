# AGENTS: how to work on DataMate v4

Read first: `CLAUDE.md` (rules, public test), `MAP.md` (code), `DECISIONS.md` (history).

## Loop
1. Read `MAP.md`, then only the modules you change.
2. Change one thing. Add or update a test in `tests/` for it (synthetic data, no model calls).
3. `make test` (< 30 s) must pass, including `tests/test_structure.py` (size limits, dependencies, MAP coverage).
4. Host-side change (data, sandbox, shape, answer)? `make replay RUN=outputs/runs/<run>` first: 0 model calls.
5. Model-side change (prompt, schema)? `make dev SPLIT=train` then `make dev SPLIT=public`: 5 questions each,
   aggregates only. Compare `health` with the previous run; one question of difference is noise (the gateway is
   not deterministic at temperature 0).
6. Commit with the numbers in the message; add one line to `DECISIONS.md`.

## Rules
- Never edit `src/` while a measurement runs.
- At most 6 questions per dev run; more needs the user's explicit approval (`--allow-large`).
- Public test: never read its questions, answers, data or logs; never tune on it; print aggregates only.
- General solutions only: nothing specific to a question, shop, column name or label.
- Keep the limits: `src/` ≤ 3500 lines, file ≤ 300, function ≤ 60. Split a module rather than raise them.
- One flow, one implementation per step. No feature flags or variants; try alternatives on a git branch.
- Every failure of one question becomes an abstain for that question, never a crashed run.
