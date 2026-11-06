from __future__ import annotations

import argparse
import json
import math
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Sequence


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


def score(*, answers: Path, reference: Path) -> tuple[Counter[str], tuple[tuple[str, dict[str, Any], dict[str, Any]], ...]]:
    golds = {row["id"]: row for row in map(json.loads, reference.read_text(encoding="utf-8").splitlines())}
    counts: Counter[str] = Counter()
    wrong = []
    for row in map(json.loads, answers.read_text(encoding="utf-8").splitlines()):
        if row.get("type") in (None, "abstain"):
            counts["blank"] += 1
        elif is_correct(row, golds[row["id"]]):
            counts["right"] += 1
        else:
            counts["wrong"] += 1
            wrong.append((row["id"], row, golds[row["id"]]))
    return counts, tuple(wrong)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chấm answers.jsonl theo đáp án tham chiếu: đúng +1, sai -1, trống 0")
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    args = parser.parse_args(argv)
    counts, wrong = score(answers=args.answers, reference=args.reference)
    answered = counts["right"] + counts["wrong"]
    total = answered + counts["blank"]
    print(f"score {counts['right'] - counts['wrong']}/{total} right {counts['right']} wrong {counts['wrong']} blank {counts['blank']} accuracy {counts['right'] / answered if answered else 0:.2f} coverage {answered / total if total else 0:.2f}")
    for question_id, row, gold in wrong:
        print(question_id, json.dumps(row.get("answer"), ensure_ascii=False)[:60], "|", json.dumps(gold.get("answer"), ensure_ascii=False)[:60], "|", row.get("type"), gold.get("type"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
