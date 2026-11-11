"""Column typing from content: text, bool, date, number, quantity, and the sandbox dtype of each kind.

In:  the raw cells of one column (all its partitions), their sources, the header label.
Out: `type_column` -> (kind, parsed values, units); `to_series` -> pandas Series.
Per column, from its own cells: the decimal mark ("1,250" is 1.25 in a column that also has "0,5"; thousands when
nothing shows otherwise) and the date order (m/d/y only when a second part above 12 proves it). Never guesses beyond
the text: a cell that does not parse is blank and its column keeps the original text (data.py, `__raw`).
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter

import numpy as np
import pandas as pd

from .values import decimal_mark, fold, nfc, parse_datetime, parse_number, parse_qty, year_hint

PARSE_SHARE = 0.98          # share of non-empty cells that must parse before a column is typed
LEADING_ZERO = re.compile(r'0\d+')
DATE_HEADER = re.compile(r'\b(ngay|date|thoi gian|thoi diem|time)\b')     # the only header hint (Excel serials): first word
SHORT_DATE = re.compile(r'\s*\d{1,2}[/\-.]\d{1,2}\s*')
DM_TEXT = re.compile(r'\s*(\d{1,2})[/\-.](\d{1,2})(?:[/\-.]\d{2,4})?(?:[ ,t].*)?', re.I)


def date_order(values):
    """'md' when some text date has a second part above 12 and none a first part above 12 (an m/d/y export), else 'dm'
    (Vietnamese order, also when no cell proves either)."""
    parts = [(int(m[1]), int(m[2])) for v in values if isinstance(v, str) and (m := DM_TEXT.fullmatch(v))]
    return 'md' if any(b > 12 for _, b in parts) and not any(a > 12 for a, _ in parts) else 'dm'


def money(values):
    """Numbers mostly round to the hundred: amounts ("Giá ngày lễ" 45000), never Excel serial dates (45722, 45723...)."""
    nums = [x for v in values if not isinstance(v, bool) and (x := parse_number(v)) is not None]
    return len(nums) * 2 > len(values) and sum(float(v) % 100 == 0 for v in nums) >= 0.8 * len(nums)


def _share(values, ok):
    return sum(map(ok, values)) / len(values) if values else 0.0


def _explicit_date(v):
    return isinstance(v, (dt.date, dt.datetime)) or (isinstance(v, str) and (
        parse_datetime(v, None, serial_ok=False) is not None
        or (DM_TEXT.fullmatch(v) is not None and parse_datetime(v, None, serial_ok=False, dayfirst=False) is not None)))


def parse_dates(values, sources, dayfirst=True, serials=(36500, 47500)):
    """Dates incl. Excel serials; 'd/m' takes the year of the closest full date above it in the same source."""
    out, last_year = [], {}
    for v, src in zip(values, sources):
        d = None if v is None or isinstance(v, bool) else parse_datetime(v, None, True, dayfirst, serials)
        if d is None and isinstance(v, str) and SHORT_DATE.fullmatch(v):
            d = parse_datetime(v, last_year.get(src) or year_hint(src), serial_ok=False, dayfirst=dayfirst)
        elif d is not None:
            last_year[src] = d.year
        out.append(d)
    return out


def type_column(values, sources, label=''):
    """Content-first typing: (kind, parsed values, units or None); kind in text/bool/date/number/quantity."""
    present = [v for v in values if v is not None]
    as_text = [None if v is None else nfc(str(v)) for v in values]
    if not present:
        return 'text', as_text, None
    if all(isinstance(v, bool) for v in present) or all(isinstance(v, str) and v.strip().lower() in ('true', 'false') for v in present):
        return 'bool', [v if v is None or isinstance(v, bool) else v.strip().lower() == 'true' for v in values], None
    if any(isinstance(v, str) and LEADING_ZERO.fullmatch(v.strip()) for v in present):
        return 'text', as_text, None                                   # codes such as 0012
    if all(isinstance(v, (dt.date, dt.datetime)) for v in present):
        return 'date', [None if v is None else parse_datetime(v) for v in values], None
    header = DATE_HEADER.match(fold(re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', label))) and not money(present)   # "Ngày bán", not "Giá ngày lễ"
    if header or any(_explicit_date(v) for v in dict.fromkeys(present)):
        dates = parse_dates(values, sources, date_order(present) == 'dm', (18000, 73050) if header else (36500, 47500))   # 1949-2099: never a count of days
        if sum(d is not None for d in dates) >= PARSE_SHARE * len(present):
            return 'date', dates, None
    mark = decimal_mark(present)
    if _share(present, lambda v: not isinstance(v, bool) and parse_number(v, mark) is not None) >= PARSE_SHARE:
        return 'number', [None if v is None or isinstance(v, bool) else parse_number(v, mark) for v in values], None
    if _share(present, lambda v: isinstance(v, str) and '=' in v) >= 0.5:
        return 'text', as_text, None                     # unit rules "1 thùng = 6 bịch": text, read with dm.factors
    qty = [parse_qty(v, mark) if v is not None else (None, None) for v in values]
    if _share(present, lambda v: parse_qty(v, mark)[0] is not None) >= PARSE_SHARE and any(u for _, u in qty):
        return 'quantity', [n for n, _ in qty], [u for _, u in qty]
    return 'text', as_text, None


def to_series(kind, values):
    """Sandbox dtype: int64 (whole, no blanks), float64, datetime64, str, bool (no blanks), else object."""
    present = [v for v in values if v is not None]
    if kind in ('number', 'quantity'):
        if len(present) == len(values) and all(float(v).is_integer() and abs(v) < 2 ** 53 for v in present):
            return pd.Series([int(v) for v in values], dtype=np.int64)
        return pd.Series([np.nan if v is None else float(v) for v in values], dtype=np.float64)
    if kind == 'date':
        return pd.Series(pd.to_datetime([pd.NaT if v is None else v for v in values]), dtype='datetime64[ns]')
    if kind == 'bool' and len(present) == len(values):
        return pd.Series(values, dtype=bool)
    if present and all(isinstance(v, str) for v in present):
        return pd.Series(values, dtype='str')
    return pd.Series(values, dtype=object)
