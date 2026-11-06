from __future__ import annotations

import json
import math
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


def _text_key(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value)).casefold()
    kept = "".join(ch if ch.isalnum() else " " for ch in text)
    return " ".join(kept.split())


def _same_scalar(got: Any, want: Any) -> bool:
    if isinstance(want, bool) or isinstance(got, bool):
        return bool(got) == bool(want) and isinstance(got, bool) == isinstance(want, bool)
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
    got_rows = sorted((tuple(_text_key(c) if isinstance(c, str) else c for c in row) for row in got["rows"]), key=str)
    want_rows = sorted((tuple(_text_key(c) if isinstance(c, str) else c for c in row) for row in want["rows"]), key=str)
    return all(_same_list(list(g), list(w)) for g, w in zip(got_rows, want_rows))


def is_correct(submitted: dict[str, Any], truth: dict[str, Any]) -> bool:
    if submitted.get("type") != truth.get("type"):
        return False
    kind = truth["type"]
    if kind == "unanswerable":
        return True
    got, want = submitted.get("answer"), truth.get("answer")
    aliases = truth.get("alias") or []
    candidates = [want, *aliases]
    if kind == "list":
        return any(_same_list(got, c) for c in candidates)
    if kind == "table":
        return any(_same_table(got, c) for c in candidates)
    return any(_same_scalar(got, c) for c in candidates)


def score(submission_path: Path | str, truth_path: Path | str) -> dict[str, Any]:
    truth = {json.loads(l)["id"]: json.loads(l) for l in Path(truth_path).read_text(encoding="utf-8").splitlines() if l.strip()}
    submitted = {json.loads(l)["id"]: json.loads(l) for l in Path(submission_path).read_text(encoding="utf-8").splitlines() if l.strip()}
    right = wrong = blank = 0
    per_type: dict[str, Counter[str]] = {}
    wrong_ids: list[tuple[str, Any, Any]] = []
    for qid, want in truth.items():
        bucket = per_type.setdefault(want["type"], Counter())
        line = submitted.get(qid)
        if line is None or line.get("type") == "abstain":
            blank += 1
            bucket["blank"] += 1
            continue
        if is_correct(line, want):
            right += 1
            bucket["right"] += 1
        else:
            wrong += 1
            bucket["wrong"] += 1
            wrong_ids.append((qid, line.get("answer", line.get("type")), want.get("answer", want.get("type"))))
    answered = right + wrong
    return {
        "n": len(truth),
        "score": right - wrong,
        "right": right,
        "wrong": wrong,
        "blank": blank,
        "accuracy": round(right / answered, 4) if answered else 0.0,
        "coverage": round(answered / len(truth), 4) if truth else 0.0,
        "per_type": {k: dict(v) for k, v in sorted(per_type.items())},
        "wrong_ids": wrong_ids,
    }


def main() -> int:
    if len(sys.argv) != 3:
        raise ValueError("usage: score.py <submission.jsonl> <truth.jsonl>")
    report = score(sys.argv[1], sys.argv[2])
    wrong_ids = report.pop("wrong_ids")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nsai {len(wrong_ids)} câu:")
    for qid, got, want in wrong_ids[:40]:
        print(f"  {qid}  nộp={got!r}  đúng={want!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
