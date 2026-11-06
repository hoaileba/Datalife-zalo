from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from .norm import is_blank, squeeze

MAX_HEADER_SCAN = 15


def sheet_names(path: Path | str) -> tuple[str, ...]:
    return tuple(pd.ExcelFile(path).sheet_names)


def peek(path: Path | str, *, sheet: str | int = 0, rows: int = 8, cols: int = 20) -> str:
    """Dump thô những dòng đầu của một sheet hay file csv, để mắt người xác nhận header."""
    target = Path(path)
    if target.suffix.lower() == ".csv":
        raw = pd.read_csv(target, header=None, nrows=rows, dtype=str, encoding="utf-8-sig", keep_default_na=False)
    else:
        raw = pd.read_excel(target, sheet_name=sheet, header=None, nrows=rows, dtype=object)
    raw = raw.iloc[:, :cols]
    lines: list[str] = []
    for idx, row in raw.iterrows():
        cells = [("" if is_blank(v) else squeeze(v))[:28] for v in row.tolist()]
        lines.append(f"[{idx}] " + " | ".join(cells))
    return "\n".join(lines)


def detect_header_row(raw: pd.DataFrame) -> int:
    scan = min(MAX_HEADER_SCAN, len(raw))
    counts: list[int] = []
    for i in range(scan):
        counts.append(sum(1 for v in raw.iloc[i].tolist() if not is_blank(v)))
    if not counts:
        return 0
    widest = max(counts)
    for i in range(scan):
        if counts[i] < max(2, int(widest * 0.6)):
            continue
        values = [v for v in raw.iloc[i].tolist() if not is_blank(v)]
        if all(isinstance(v, str) for v in values):
            return i
    return int(max(range(scan), key=lambda i: counts[i]))


def _merge_header(raw: pd.DataFrame, header_row: int, header_rows: int) -> list[str]:
    block = raw.iloc[header_row : header_row + header_rows]
    names: list[str] = []
    for col in range(raw.shape[1]):
        parts: list[str] = []
        carried = ""
        for r in range(header_rows):
            cell = block.iloc[r, col]
            if is_blank(cell):
                continue
            parts.append(squeeze(cell))
        if header_rows > 1 and not parts:
            for back in range(col - 1, -1, -1):
                top = block.iloc[0, back]
                if not is_blank(top):
                    carried = squeeze(top)
                    break
            parts = [carried] if carried else []
        names.append(" ".join(parts).strip() or f"col_{col}")
    out: list[str] = []
    seen: dict[str, int] = {}
    for name in names:
        if name in seen:
            seen[name] += 1
            out.append(f"{name}.{seen[name]}")
        else:
            seen[name] = 0
            out.append(name)
    return out


def read_table(
    path: Path | str,
    *,
    sheet: str | int = 0,
    header_row: int | None = None,
    header_rows: int = 1,
) -> pd.DataFrame:
    """Đọc một sheet hay csv thành DataFrame, header dò được hoặc chỉ định tường minh."""
    target = Path(path)
    if target.suffix.lower() == ".csv":
        raw = pd.read_csv(target, header=None, dtype=object, encoding="utf-8-sig", keep_default_na=False, na_values=[""])
    else:
        raw = pd.read_excel(target, sheet_name=sheet, header=None, dtype=object)
    if raw.empty:
        return raw
    row = detect_header_row(raw) if header_row is None else header_row
    names = _merge_header(raw, row, header_rows)
    body = raw.iloc[row + header_rows :].reset_index(drop=True)
    body.columns = names
    body = body.dropna(axis=0, how="all")
    keep = [c for c in body.columns if not str(c).startswith("col_") or body[c].notna().any()]
    return body[keep].reset_index(drop=True)


def read_all_sheets(path: Path | str, *, header_rows: int = 1) -> dict[str, pd.DataFrame]:
    return {name: read_table(path, sheet=name, header_rows=header_rows) for name in sheet_names(path)}


def fill_group(frame: pd.DataFrame, columns: Sequence[str], *, anchor: str | None = None) -> pd.DataFrame:
    """Rulebook §8: ô trống ở dòng sau của cùng nhóm dòng mang giá trị của dòng đầu nhóm."""
    out = frame.copy()
    if anchor is None:
        for column in columns:
            out[column] = out[column].ffill()
        return out
    group_id = out[anchor].ffill()
    for column in columns:
        out[column] = out.groupby(group_id, sort=False)[column].transform(lambda s: s.ffill())
    return out


def drop_exact_duplicates(frame: pd.DataFrame, *, within: str | None = None) -> pd.DataFrame:
    """Rulebook §8: hai dòng của cùng một đơn giống nhau ở mọi ô là lỗi xuất file, tính một lần."""
    if within is None:
        return frame.drop_duplicates().reset_index(drop=True)
    kept = [frame.loc[idx].drop_duplicates() if False else group.drop_duplicates() for idx, group in frame.groupby(within, sort=False)]
    return pd.concat(kept).sort_index().reset_index(drop=True)


def sqlite_tables(path: Path | str) -> tuple[str, ...]:
    with sqlite3.connect(str(path)) as conn:
        rows = conn.execute("select name from sqlite_master where type='table' order by name").fetchall()
    return tuple(r[0] for r in rows)


def read_sqlite(path: Path | str, table: str) -> pd.DataFrame:
    with sqlite3.connect(str(path)) as conn:
        return pd.read_sql_query(f'select * from "{table}"', conn)


def column_report(frame: pd.DataFrame, *, samples: int = 3) -> str:
    lines: list[str] = []
    for column in frame.columns:
        series = frame[column]
        values = [squeeze(v) for v in series.dropna().head(samples).tolist()]
        lines.append(f"{column!r}: nonnull={int(series.notna().sum())}/{len(series)} e.g. {values}")
    return "\n".join(lines)


def drop_subtotal_rows(frame: pd.DataFrame, *, key_columns: Sequence[str]) -> pd.DataFrame:
    """Bỏ dòng tổng cộng chen giữa sheet: dòng không có giá trị ở bất kỳ cột khoá nào."""
    missing = [c for c in key_columns if c not in frame.columns]
    if missing:
        raise ValueError(f"key columns not in frame: {missing}")
    mask = frame[list(key_columns)].notna().any(axis=1)
    return frame[mask].reset_index(drop=True)


def census(frame: pd.DataFrame, *, key_columns: Sequence[str], samples: int = 5) -> str:
    """Kiểm kê dòng: bao nhiêu dòng không có cột khoá, và chúng là dòng gì."""
    mask = frame[list(key_columns)].notna().any(axis=1)
    orphans = frame[~mask]
    lines = [f"total={len(frame)} with_key={int(mask.sum())} without_key={len(orphans)}"]
    if not orphans.empty:
        for _, row in orphans.head(samples).iterrows():
            kept = {c: squeeze(v) for c, v in row.items() if not is_blank(v)}
            lines.append(f"  orphan: {kept}")
    return "\n".join(lines)


def drop_repeated_header_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Bỏ dòng header bị lặp lại giữa file: dòng có giá trị trùng chính tên cột của nó."""
    names = {str(c).strip().casefold() for c in frame.columns}
    def _is_header(row: pd.Series) -> bool:
        cells = [squeeze(v).casefold() for v in row.tolist() if not is_blank(v)]
        return len(cells) >= 2 and all(cell in names for cell in cells)
    mask = frame.apply(_is_header, axis=1)
    return frame[~mask].reset_index(drop=True)
