from __future__ import annotations

import json
import math
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import Field

from ..models.config import FrozenModel


class ScoreReport(FrozenModel):
    """Ba số luôn đi cùng nhau: điểm, accuracy, coverage; kèm id câu sai."""

    n: int
    score: int
    right: int
    wrong: int
    blank: int
    accuracy: float
    coverage: float
    per_type: dict[str, dict[str, int]] = Field(default_factory=dict)
    wrong_ids: tuple[str, ...] = ()


def score_submission(submission: Path, truth: Path) -> ScoreReport:
    wanted = _by_id(truth)
    submitted = _by_id(submission)
    right = wrong = blank = 0
    per_type: dict[str, Counter[str]] = {}
    wrong_ids: list[str] = []
    for qid, want in wanted.items():
        bucket = per_type.setdefault(str(want["type"]), Counter())
        line = submitted.get(qid)
        if line is None or line.get("type") == "abstain":
            blank += 1
            bucket["blank"] += 1
        elif is_correct(line, want):
            right += 1
            bucket["right"] += 1
        else:
            wrong += 1
            bucket["wrong"] += 1
            wrong_ids.append(qid)
    answered = right + wrong
    return ScoreReport(
        n=len(wanted),
        score=right - wrong,
        right=right,
        wrong=wrong,
        blank=blank,
        accuracy=round(right / answered, 4) if answered else 0.0,
        coverage=round(answered / len(wanted), 4) if wanted else 0.0,
        per_type={kind: dict(counts) for kind, counts in sorted(per_type.items())},
        wrong_ids=tuple(wrong_ids),
    )


def is_correct(submitted: dict[str, Any], truth: dict[str, Any]) -> bool:
    if submitted.get("type") != truth.get("type"):
        return False
    kind = truth["type"]
    if kind == "unanswerable":
        return True
    got = submitted.get("answer")
    candidates = [truth.get("answer"), *(truth.get("alias") or [])]
    if kind == "list":
        return any(_same_list(got, c) for c in candidates)
    if kind == "table":
        return any(_same_table(got, c) for c in candidates)
    return any(_same_scalar(got, c) for c in candidates)


def _by_id(path: Path) -> dict[str, dict[str, Any]]:
    rows = (json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip())
    return {row["id"]: row for row in rows}


def _text_key(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value)).casefold()
    kept = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(kept.split())


def _same_scalar(got: Any, want: Any) -> bool:
    if isinstance(want, bool) or isinstance(got, bool):
        return isinstance(got, bool) and isinstance(want, bool) and got == want
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        return math.isclose(float(got), float(want), rel_tol=0.0, abs_tol=1e-6)
    if isinstance(want, str) and isinstance(got, str):
        return _text_key(got) == _text_key(want)
    return got == want


def _same_list(got: Any, want: Any) -> bool:
    if not isinstance(got, list) or not isinstance(want, list) or len(got) != len(want):
        return False
    return all(_same_scalar(g, w) for g, w in zip(got, want))


def _same_table(got: Any, want: Any) -> bool:
    if not isinstance(got, dict) or not isinstance(want, dict):
        return False
    if set(got) != {"columns", "rows"} or set(want) != {"columns", "rows"}:
        return False
    if len(got["columns"]) != len(want["columns"]) or len(got["rows"]) != len(want["rows"]):
        return False

    def key(rows: list[list[Any]]) -> list[tuple[Any, ...]]:
        return sorted((tuple(_text_key(c) if isinstance(c, str) else c for c in row) for row in rows), key=str)

    return all(_same_list(list(g), list(w)) for g, w in zip(key(got["rows"]), key(want["rows"])))
