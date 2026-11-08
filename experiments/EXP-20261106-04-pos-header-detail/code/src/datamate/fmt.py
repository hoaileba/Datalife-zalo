from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .norm import round2, round_money

ANSWER_TYPES = frozenset({"number", "percent", "date", "boolean", "string", "list", "table", "unanswerable", "abstain"})


def money(value: float | int) -> int:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError("money value must be finite")
    return round_money(float(value))


def count(value: float | int) -> int:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError("count value must be finite")
    rounded = round_money(float(value))
    if abs(float(value) - rounded) > 1e-9:
        raise ValueError(f"count is not integral: {value}")
    return rounded


def quantity(value: float | int) -> int | float:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError("quantity value must be finite")
    as_float = float(value)
    if abs(as_float - round(as_float)) < 1e-9:
        return int(round(as_float))
    return round2(as_float)


def percent(value: float | int) -> float:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError("percent value must be finite")
    return round2(float(value))


def average(value: float | int) -> float:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError("average value must be finite")
    return round2(float(value))


def day_answer(value: date | datetime | str) -> str:
    if isinstance(value, str):
        return date.fromisoformat(value).isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def month_answer(value: date | datetime | str | tuple[int, int]) -> str:
    if isinstance(value, tuple):
        year, month = value
        return f"{year:04d}-{month:02d}"
    if isinstance(value, str):
        parts = value.split("-")
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}"
    return f"{value.year:04d}-{value.month:02d}"


def table(*, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> dict[str, Any]:
    if not columns:
        raise ValueError("table needs at least one column")
    width = len(columns)
    out_rows: list[list[Any]] = []
    for row in rows:
        if len(row) != width:
            raise ValueError(f"table row width {len(row)} != {width}")
        out_rows.append(list(row))
    return {"columns": [str(c) for c in columns], "rows": out_rows}


def _check_scalar_number(value: Any, *, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a JSON number, got {type(value).__name__}")
    if not math.isfinite(float(value)):
        raise ValueError(f"{field} must be finite")


def plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, bytes)):
        return value
    if getattr(value, "shape", None) == () and callable(getattr(value, "item", None)):
        return value.item()
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    return value


def answer_line(question_id: str, answer_type: str, answer: Any = None, *, reason: str | None = None) -> dict[str, Any]:
    if answer_type not in ANSWER_TYPES:
        raise ValueError(f"unsupported answer type: {answer_type}")
    answer = plain(answer)
    if answer_type == "abstain":
        return {"id": question_id, "type": "abstain"}
    if answer_type == "unanswerable":
        line: dict[str, Any] = {"id": question_id, "type": "unanswerable", "answer": None}
        if reason is not None:
            if not isinstance(reason, str):
                raise ValueError("reason must be a string")
            line["reason"] = reason
        return line
    if answer_type == "number":
        _check_scalar_number(answer, field="number answer")
    elif answer_type == "percent":
        _check_scalar_number(answer, field="percent answer")
    elif answer_type == "boolean":
        if not isinstance(answer, bool):
            raise ValueError(f"boolean answer must be true/false, got {answer!r}")
    elif answer_type == "string":
        if not isinstance(answer, str) or answer.strip() == "":
            raise ValueError(f"string answer must be a non-empty string, got {answer!r}")
    elif answer_type == "date":
        if not isinstance(answer, str):
            raise ValueError(f"date answer must be a string, got {answer!r}")
        if len(answer) == 7:
            year, month = answer.split("-")
            if len(year) != 4 or len(month) != 2 or not 1 <= int(month) <= 12:
                raise ValueError(f"date answer not YYYY-MM: {answer!r}")
        else:
            date.fromisoformat(answer)
    elif answer_type == "list":
        if not isinstance(answer, list):
            raise ValueError(f"list answer must be a JSON array, got {type(answer).__name__}")
        if not answer:
            raise ValueError("list answer must not be empty")
    elif answer_type == "table":
        if not isinstance(answer, dict) or set(answer) != {"columns", "rows"}:
            raise ValueError("table answer needs exactly columns and rows")
        if not isinstance(answer["columns"], list) or not isinstance(answer["rows"], list):
            raise ValueError("table columns and rows must be arrays")
        width = len(answer["columns"])
        for row in answer["rows"]:
            if not isinstance(row, list) or len(row) != width:
                raise ValueError(f"table row does not match {width} columns: {row!r}")
    return {"id": question_id, "type": answer_type, "answer": answer}


def validate_line(line: dict[str, Any]) -> None:
    if "id" not in line or not isinstance(line["id"], str):
        raise ValueError(f"line missing string id: {line!r}")
    if "type" not in line:
        raise ValueError(f"line missing type: {line!r}")
    answer_line(line["id"], line["type"], line.get("answer"), reason=line.get("reason"))


def write_answers(path: Path | str, lines: Iterable[dict[str, Any]]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with target.open("w", encoding="utf-8") as handle:
        for line in lines:
            validate_line(line)
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
            written += 1
    return written


def load_questions(path: Path | str) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if raw:
                rows.append(json.loads(raw))
    return tuple(rows)
