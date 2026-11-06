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
    """Cổng nhận đáp án: đủ id, đúng format, đúng chính sách abstain, và script sinh lại đúng file đó."""

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

    def verify(self, shop: str) -> VerifyResult:
        script = self._layout.script(shop)
        answers = self._layout.answers(shop)
        problems: list[str] = []
        if not script.exists():
            problems.append(f"script missing: code/shops/{shop}.py")
        if not self._layout.notes(shop).exists():
            problems.append(f"notes missing: logs/{shop}-notes.md")
        if not answers.exists():
            problems.append(f"answers file missing: out/answers/{shop}.jsonl")
        if problems:
            return _result(tuple(problems), total=len(self._question_ids[shop]), lines=())
        before = answers.read_text(encoding="utf-8")
        run = self._executor.run(script)
        if run.timed_out or run.exit_code != 0:
            tail = (run.stderr or run.stdout)[-1500:]
            return _result((f"script failed on rerun (exit {run.exit_code}): {tail}",), total=len(self._question_ids[shop]), lines=())
        after = answers.read_text(encoding="utf-8")
        changed = _changed_ids(before, after)
        if changed:
            problems.append(
                f"rerunning the script produced a different answers file for {len(changed)} ids, e.g. {', '.join(changed[:5])}; "
                "the answers file must come from the script only"
            )
        checked = self.check_file(shop)
        return _result(tuple(problems) + checked.problems, total=checked.total, lines=None, counts=checked)


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
        try:
            validate_line(line)
        except ValueError as error:
            problems.append(f"line {number}: bad format: {error}")
            continue
        lines.append(line)
    return lines, problems


def _changed_ids(before: str, after: str) -> list[str]:
    def by_id(text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for raw in text.splitlines():
            if raw.strip():
                try:
                    line = json.loads(raw)
                except json.JSONDecodeError:
                    out[f"<bad json {len(out)}>"] = raw
                    continue
                out[str(line.get("id"))] = json.dumps(line, ensure_ascii=False, sort_keys=True)
        return out

    old, new = by_id(before), by_id(after)
    return sorted(qid for qid in set(old) | set(new) if old.get(qid) != new.get(qid))


def _result(
    problems: tuple[str, ...],
    *,
    total: int,
    lines: tuple[dict[str, Any], ...] | None,
    counts: VerifyResult | None = None,
) -> VerifyResult:
    trimmed = problems if len(problems) <= PROBLEM_LIMIT else problems[:PROBLEM_LIMIT] + (f"... {len(problems) - PROBLEM_LIMIT} more",)
    if counts is not None:
        return VerifyResult(ok=not problems, problems=trimmed, total=total, answered=counts.answered, abstain=counts.abstain, unanswerable=counts.unanswerable)
    kinds = Counter(line["type"] for line in lines or ())
    return VerifyResult(
        ok=not problems,
        problems=trimmed,
        total=total,
        answered=sum(n for kind, n in kinds.items() if kind != "abstain"),
        abstain=kinds["abstain"],
        unanswerable=kinds["unanswerable"],
    )
