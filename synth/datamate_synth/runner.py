from __future__ import annotations

import ast
import contextlib
import datetime
import io
import json
import math
import pickle
import sys
import traceback
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from . import dm

MARKER = "\n<<<RUNNER_RESULT>>>\n"
FORBIDDEN = (ast.Import, ast.ImportFrom, ast.For, ast.While, ast.If, ast.FunctionDef, ast.AsyncFunctionDef, ast.Try, ast.With, ast.ClassDef)
VALUE_LIMIT = 300


class LenientFrame(pd.DataFrame):
    """DataFrame nhận tên cột viết khác dấu hoặc hoa thường, như prompt hứa với model."""

    @property
    def _constructor(self) -> type:
        return LenientFrame

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str) and key not in self.columns:
            matches = [column for column in self.columns if dm.norm(column) == dm.norm(key)]
            if len(matches) == 1:
                key = matches[0]
        return super().__getitem__(key)


class LenientTables(dict):
    """Bảng theo tên, nhận tên viết khác dấu hoặc hoa thường."""

    def __missing__(self, key: str) -> Any:
        matches = [name for name in self if dm.norm(name) == dm.norm(key)]
        if len(matches) == 1:
            return self[matches[0]]
        raise KeyError(f"no table {key!r}, tables are {sorted(self)}")


def _plain(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return {"columns": [str(column) for column in value.columns], "rows": [[_plain(cell) for cell in row] for row in value.itertuples(index=False)]}
    if isinstance(value, (pd.Series, pd.Index, np.ndarray)):
        return [_plain(item) for item in list(value)]
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _show(value: Any) -> str:
    if isinstance(value, pd.DataFrame):
        return f"DataFrame shape={value.shape} columns={list(value.columns)[:20]}\n{value.head(5).to_string()[:VALUE_LIMIT]}"
    if isinstance(value, pd.Series):
        return f"Series len={len(value)} name={value.name!r}\n{value.head(5).to_string()[:VALUE_LIMIT]}"
    return repr(value)[:VALUE_LIMIT]


def _issues(result: Any) -> list[str]:
    plain = _plain(result)
    flat = plain["rows"] if isinstance(plain, dict) else plain if isinstance(plain, list) else [plain]
    cells = [cell for row in flat for cell in (row if isinstance(row, list) else [row])]
    if not cells or all(cell is None for cell in cells):
        return ["result is empty: check the filters"]
    numbers = [cell for cell in cells if isinstance(cell, (int, float)) and not isinstance(cell, bool)]
    if numbers and len(numbers) == len(cells) and all(cell == 0 for cell in numbers):
        return ["every value is 0: cannot be confirmed, fix the filters or abstain"]
    return []


def run(code: str, *, tables: dict[str, pd.DataFrame], as_of: str) -> dict[str, Any]:
    stdout = io.StringIO()
    try:
        tree = ast.parse(code, filename="<agent>")
    except SyntaxError as error:
        return {"ok": False, "stdout": "", "error": {"type": "SyntaxError", "message": str(error.msg), "line": error.lineno, "source": (error.text or "").strip()}}
    banned = next((node for node in ast.walk(tree) if isinstance(node, FORBIDDEN)), None)
    if banned is not None:
        line = code.splitlines()[banned.lineno - 1].strip()
        return {"ok": False, "stdout": "", "error": {"type": "ForbiddenSyntax", "message": f"{type(banned).__name__} is not allowed: no imports, loops, if, def, try or with blocks", "line": banned.lineno, "source": line}}
    lenient = LenientTables({name: LenientFrame(frame) for name, frame in tables.items()})
    namespace: dict[str, Any] = {"pd": pd, "np": np, "dm": dm, "datetime": datetime, "math": math, "Decimal": Decimal, "round_decimal": dm.round_decimal, "tables": lenient, "as_of": pd.Timestamp(as_of), **lenient}
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stdout):
            exec(compile(tree, "<agent>", "exec"), namespace)
    except Exception as error:
        frames = [frame for frame in traceback.extract_tb(error.__traceback__) if frame.filename == "<agent>"]
        line = frames[-1].lineno if frames else None
        source = code.splitlines()[line - 1].strip() if line else None
        names = {node.id for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Name)} if source and _parses(source) else set()
        shown = {name: _show(namespace[name]) for name in sorted(names) if name in namespace and name not in {"pd", "np", "dm", "tables", "datetime", "math", "Decimal", "round_decimal"} and not isinstance(namespace[name], type(dm))}
        return {"ok": False, "stdout": stdout.getvalue(), "error": {"type": type(error).__name__, "message": str(error)[:500], "line": line, "source": source}, "variables": shown}
    if "result" not in namespace:
        return {"ok": False, "stdout": stdout.getvalue(), "error": {"type": "NoResult", "message": "The program ran but never assigned result: the last line must be result = <value to submit>", "line": None, "source": None}}
    result = namespace["result"]
    return {"ok": True, "stdout": stdout.getvalue(), "result": _plain(result), "issues": _issues(result)}


def _parses(source: str) -> bool:
    try:
        ast.parse(source)
    except SyntaxError:
        return False
    return True


def main() -> int:
    tables_path, as_of = sys.argv[1], sys.argv[2]
    with open(tables_path, "rb") as handle:
        tables = pickle.load(handle)
    outcome = run(sys.stdin.read(), tables=tables, as_of=as_of)
    sys.stdout.write(MARKER + json.dumps(outcome, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
