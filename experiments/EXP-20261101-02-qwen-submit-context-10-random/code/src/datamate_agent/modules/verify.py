from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from datamate.fmt import validate_line

from ..models import VerifyResult
from .executor import Executor
from .paths import WorkLayout

PROBLEM_LIMIT = 20


class Verifier:
    """Cổng nhận đáp án: harness tự chạy script, script phải ghi đủ id, đúng format, đúng chính sách abstain."""

    def __init__(
        self,
        *,
        question_ids: Mapping[str, frozenset[str]],
        layout: WorkLayout,
        executor: Executor,
        allow_abstain: bool,
    ) -> None:
        self._question_ids = question_ids
        self._layout = layout
        self._executor = executor
        self._allow_abstain = allow_abstain

    def check_file(self, shop: str) -> VerifyResult:
        path = self._layout.answers(shop)
        expected = self._question_ids[shop]
        if not path.exists():
            return _result(("answers file missing: " + str(path.name),), total=len(expected), lines=())
        lines, problems = _read_lines(path)
        seen: Counter[str] = Counter(line["id"] for line in lines)
        problems.extend(f"duplicate id: {qid}" for qid, n in sorted(seen.items()) if n > 1)
        problems.extend(f"missing id: {qid}" for qid in sorted(expected - set(seen)))
        problems.extend(f"id not in this shop: {qid}" for qid in sorted(set(seen) - expected))
        if not self._allow_abstain:
            problems.extend(
                f"abstain not allowed, pick the most likely answer: {line['id']}" for line in lines if line["type"] == "abstain"
            )
        return _result(tuple(problems), total=len(expected), lines=tuple(lines))

    def run_script(self, shop: str) -> VerifyResult:
        script = self._layout.script(shop)
        answers = self._layout.answers(shop)
        total = len(self._question_ids[shop])
        if not script.exists():
            return _result((f"script missing: code/shops/{shop}.py",), total=total, lines=())
        answers.unlink(missing_ok=True)
        run = self._executor.run(script)
        if run.timed_out or run.exit_code != 0:
            tail = (run.stderr or run.stdout)[-1500:]
            return _result((f"script failed (exit {run.exit_code}): {tail}",), total=total, lines=())
        if not answers.exists():
            return _result((f"script did not write out/answers/{shop}.jsonl",), total=total, lines=())
        return self.check_file(shop)


def _read_lines(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    lines: list[dict[str, Any]] = []
    problems: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except json.JSONDecodeError as error:
            problems.append(f"line {number}: not valid json: {error}")
            continue
        if not isinstance(line, dict):
            problems.append(f"line {number}: must be one JSON object per line, got {type(line).__name__}")
            continue
        try:
            validate_line(line)
        except ValueError as error:
            problems.append(f"line {number}: bad format: {error}")
            continue
        lines.append(line)
    return lines, problems


def _result(
    problems: tuple[str, ...],
    *,
    total: int,
    lines: tuple[dict[str, Any], ...],
) -> VerifyResult:
    trimmed = problems if len(problems) <= PROBLEM_LIMIT else problems[:PROBLEM_LIMIT] + (f"... {len(problems) - PROBLEM_LIMIT} more",)
    kinds = Counter(line["type"] for line in lines)
    return VerifyResult(
        ok=not problems,
        problems=trimmed,
        total=total,
        answered=sum(n for kind, n in kinds.items() if kind != "abstain"),
        abstain=kinds["abstain"],
        unanswerable=kinds["unanswerable"],
    )
