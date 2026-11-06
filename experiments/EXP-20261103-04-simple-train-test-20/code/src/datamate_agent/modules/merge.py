from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from datamate.fmt import validate_line
from pydantic import Field

from ..models.config import FrozenModel


class MergeReport(FrozenModel):
    """Kết quả gộp đáp án các shop thành một file nộp."""

    questions: int
    answered: int
    abstain: int
    missing: tuple[str, ...]
    unverified: tuple[str, ...]
    problems: tuple[str, ...]
    per_type: dict[str, int] = Field(default_factory=dict)
    per_shop: dict[str, dict[str, int]] = Field(default_factory=dict)

    @property
    def coverage(self) -> float:
        return self.answered / self.questions if self.questions else 0.0


def merge_answers(
    *,
    questions: Sequence[Mapping[str, Any]],
    answers_dir: Path,
    submission: Path,
    accepted_shops: frozenset[str] | None = None,
) -> MergeReport:
    found, problems = _collect(answers_dir)
    lines: list[dict[str, Any]] = []
    missing: list[str] = []
    unverified: list[str] = []
    per_type: Counter[str] = Counter()
    per_shop: dict[str, Counter[str]] = {}
    for question in questions:
        qid = question["id"]
        line = found.get(qid)
        if line is not None and accepted_shops is not None and str(question["business_id"]) not in accepted_shops:
            unverified.append(qid)
            line = None
        if line is None:
            missing.append(qid)
            line = {"id": qid, "type": "abstain"}
        lines.append(line)
        per_type[line["type"]] += 1
        per_shop.setdefault(str(question["business_id"]), Counter())[line["type"]] += 1
    known = {question["id"] for question in questions}
    problems.extend(f"answer for unknown id: {qid}" for qid in sorted(set(found) - known))
    submission.parent.mkdir(parents=True, exist_ok=True)
    with submission.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return MergeReport(
        questions=len(questions),
        answered=sum(n for kind, n in per_type.items() if kind != "abstain"),
        abstain=per_type["abstain"],
        missing=tuple(missing),
        unverified=tuple(unverified),
        problems=tuple(problems),
        per_type=dict(per_type),
        per_shop={shop: dict(counts) for shop, counts in sorted(per_shop.items())},
    )


def _collect(answers_dir: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    found: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for path in sorted(answers_dir.glob("*.jsonl")):
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not raw.strip():
                continue
            try:
                line = json.loads(raw)
                validate_line(line)
            except (json.JSONDecodeError, ValueError) as error:
                problems.append(f"{path.name}:{number} {error}")
                continue
            if line["id"] in found:
                problems.append(f"{path.name}:{number} duplicate id {line['id']}")
                continue
            found[line["id"]] = line
    return found, problems
