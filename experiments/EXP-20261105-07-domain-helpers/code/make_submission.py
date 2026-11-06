from __future__ import annotations

import collections
import json
import math
import re
import sys
from pathlib import Path

DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
NO_DATA_REASON = "dữ liệu phát hành không đủ để trả lời"
STRUCTURED_TEXT = re.compile(r"^\s*[\[{]")


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def format_problem(row: dict) -> str | None:
    kind, answer = row["type"], row.get("answer")
    if kind in ("number", "percent") and not is_number(answer):
        return f"{kind} is not a number"
    if kind == "date" and not (isinstance(answer, str) and DATE.match(answer)):
        return "date format"
    if kind == "boolean" and not isinstance(answer, bool):
        return "boolean format"
    if kind == "string" and (not isinstance(answer, str) or not answer.strip() or STRUCTURED_TEXT.match(answer)):
        return "string format"
    if kind == "list" and (not isinstance(answer, list) or not answer or any(cell is None or isinstance(cell, (list, dict)) for cell in answer)):
        return "list format"
    if kind == "table":
        if not isinstance(answer, dict) or set(answer) != {"columns", "rows"} or not answer["rows"]:
            return "table format"
        if any(not isinstance(cells, list) or len(cells) != len(answer["columns"]) or any(cell is None for cell in cells) for cells in answer["rows"]):
            return "table cells"
    if kind not in ("number", "percent", "date", "boolean", "string", "list", "table", "unanswerable"):
        return f"unknown type {kind}"
    return None


def main() -> int:
    answers_path, questions_path, out_path = map(Path, sys.argv[1:4])
    answers = {json.loads(line)["id"]: json.loads(line) for line in answers_path.read_text(encoding="utf-8").splitlines() if line.strip()}
    ids = [json.loads(line)["id"] for line in questions_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    changes: collections.Counter[str] = collections.Counter()
    rows = []
    for question_id in ids:
        row = answers.get(question_id) or {"id": question_id, "type": None, "answer": None}
        if row.get("type") in (None, "abstain"):
            changes["blank to abstain"] += 1
            rows.append({"id": question_id, "type": "abstain"})
            continue
        problem = format_problem(row)
        if problem is not None:
            changes[f"abstain: {problem}"] += 1
            print(question_id, problem, json.dumps(row.get("answer"), ensure_ascii=False)[:90])
            rows.append({"id": question_id, "type": "abstain"})
            continue
        if row["type"] == "unanswerable":
            rows.append({"id": question_id, "type": "unanswerable", "reason": NO_DATA_REASON})
            continue
        answer = row["answer"]
        if row["type"] == "percent" and round(answer, 2) != answer:
            changes["percent rounded"] += 1
            answer = round(answer, 2)
        if row["type"] == "number" and isinstance(answer, float) and answer.is_integer():
            answer = int(answer)
        rows.append({"id": question_id, "type": row["type"], "answer": answer})
    out_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print("rows", len(rows), "types", collections.Counter(row["type"] for row in rows).most_common())
    print("changes", dict(changes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
