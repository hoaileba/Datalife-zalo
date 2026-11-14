from __future__ import annotations

import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pandas as pd

from datamate.norm import parse_datetime, parse_number


def _norm_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = unicodedata.normalize("NFD", str(value)).replace("đ", "d").replace("Đ", "D")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.casefold().split())


def norm(value: Any) -> Any:
    """Chuỗi bỏ dấu, chữ thường, gộp khoảng trắng; nhận một giá trị hoặc một cột."""
    if isinstance(value, pd.Series):
        return value.map(_norm_text)
    if isinstance(value, pd.Index):
        return pd.Index([_norm_text(item) for item in value])
    return _norm_text(value)


def values(df: pd.DataFrame, col: str) -> pd.Series:
    """Các giá trị của một cột kèm số dòng, nhiều nhất trước."""
    return df[col].value_counts(dropna=False)


def to_num(values_: Any) -> Any:
    if isinstance(values_, pd.Series):
        return values_.map(lambda value: parse_number(value))
    return parse_number(values_)


def to_date(values_: Any, dayfirst: bool = True) -> Any:
    if isinstance(values_, pd.Series):
        return pd.to_datetime(values_.map(lambda value: parse_datetime(value)), errors="coerce")
    moment = parse_datetime(values_)
    return pd.NaT if moment is None else pd.Timestamp(moment)


def _day(ref: Any) -> pd.Timestamp:
    return pd.Timestamp(ref).normalize()


def _cap(start: pd.Timestamp, end: pd.Timestamp, until: Any) -> tuple[pd.Timestamp, pd.Timestamp]:
    return (start, min(end, _day(until))) if until is not None else (start, end)


def day_range(ref: Any, offset: int = 0, until: Any = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    day = _day(ref) + pd.Timedelta(days=offset)
    return _cap(day, day, until)


def month_range(ref: Any, offset: int = 0, until: Any = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = (_day(ref).replace(day=1) + pd.DateOffset(months=offset)).normalize()
    return _cap(start, (start + pd.offsets.MonthEnd(0)).normalize(), until)


def quarter_range(ref: Any, offset: int = 0, until: Any = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    day = _day(ref)
    start = (pd.Timestamp(day.year, 3 * ((day.month - 1) // 3) + 1, 1) + pd.DateOffset(months=3 * offset)).normalize()
    return _cap(start, (start + pd.DateOffset(months=3) - pd.Timedelta(days=1)).normalize(), until)


def year_range(ref: Any, offset: int = 0, until: Any = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(_day(ref).year + offset, 1, 1)
    return _cap(start, pd.Timestamp(start.year, 12, 31), until)


def week_range(ref: Any, week_start: int, offset: int = 0, until: Any = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    day = _day(ref)
    start = day - pd.Timedelta(days=(day.weekday() - week_start) % 7) + pd.Timedelta(weeks=offset)
    return _cap(start, start + pd.Timedelta(days=6), until)


def days_back(ref: Any, n: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    end = _day(ref)
    return end - pd.Timedelta(days=n - 1), end


def between(df: pd.DataFrame, col: str, start: Any, end: Any) -> pd.DataFrame:
    """Các dòng có ngày của cột (bỏ giờ) nằm trong [start, end], cả hai đầu."""
    days = pd.to_datetime(df[col], errors="coerce").dt.normalize()
    return df[(days >= _day(start)) & (days <= _day(end))]


def drop_groups(df: pd.DataFrame, group_col: str, mask: Any) -> pd.DataFrame:
    """Bỏ mọi dòng của nhóm có ít nhất một dòng thoả mask."""
    flagged = set(df.loc[pd.Series(mask, index=df.index).fillna(False).astype(bool), group_col].dropna())
    return df[~df[group_col].isin(flagged)]


def dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Bỏ các dòng giống hệt nhau ở mọi ô, giữ dòng đầu."""
    return df.drop_duplicates()


def top(data: Any, by: str | None = None, k: int = 1, ascending: bool = False, tie: str | None = None) -> Any:
    """k phần tử đầu theo giá trị; bằng nhau thì theo mã (index hoặc cột tie) tăng dần."""
    if isinstance(data, pd.Series):
        frame = pd.DataFrame({"value": data.values, "key": data.index.astype(str)}, index=data.index)
        ordered = frame.sort_values(["value", "key"], ascending=[ascending, True], kind="mergesort")
        return data.loc[ordered.index[:k]]
    if by is None:
        raise ValueError("dm.top on a DataFrame needs by=<column>")
    keys = [by] + ([tie] if tie else [])
    return data.sort_values(keys, ascending=[ascending] + ([True] if tie else []), kind="mergesort").head(k)


def round_decimal(value: Any, digits: int = 0) -> Any:
    """Làm tròn nửa lên như trên giấy, không theo kiểu banker của round()."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    quantum = Decimal(1).scaleb(-digits)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(rounded) if digits == 0 else float(rounded)
