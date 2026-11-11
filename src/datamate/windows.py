"""Calendar windows for `dm`, whole days, both ends inclusive -> (start, end). A reference is a Timestamp/date or text
read like the data ("05/07/2025" = 5 July, ISO); an unreadable date, a week start outside 0-6 (or a day name), n < 1
or an end before the start raises with the fix instead of returning a plausible wrong window."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .values import fold, parse_datetime


def _day(ref):
    """A reference date: Timestamp/date, or text read like the data ("05/07/2025" = 5 July; ISO too)."""
    if isinstance(ref, str):
        if (d := parse_datetime(ref.strip(), None, serial_ok=False)) is None:
            raise ValueError(f'Cannot read the date {ref!r}: pass a pd.Timestamp or "YYYY-MM-DD"')
        return pd.Timestamp(d).normalize()
    if ref is None or isinstance(ref, (bool, int, float, np.integer, np.floating)):
        raise ValueError(f'A date is needed, got {ref!r}: pass a pd.Timestamp or "YYYY-MM-DD"')
    return pd.Timestamp(ref).normalize()


def _window(start, end, until=None):
    end = min(end, _day(until)) if until is not None else end
    if end < start:
        raise ValueError(f'Empty window: end {end.date()} is before start {start.date()} (check until/offset)')
    return start, end


WEEKDAYS = {fold(w): i for i, names in enumerate(
    [('monday', 'mon', 'thứ hai', 'thứ 2', 't2'), ('tuesday', 'tue', 'thứ ba', 'thứ 3', 't3'),
     ('wednesday', 'wed', 'thứ tư', 'thứ 4', 't4'), ('thursday', 'thu', 'thứ năm', 'thứ 5', 't5'),
     ('friday', 'fri', 'thứ sáu', 'thứ 6', 't6'), ('saturday', 'sat', 'thứ bảy', 'thứ 7', 't7'),
     ('sunday', 'sun', 'chủ nhật', 'cn')]) for w in names}


def day_range(ref, offset=0):
    d = _day(ref) + pd.Timedelta(days=offset)
    return d, d


def days_back(ref, n):
    """The n days ending at ref, both inclusive: 'last 7 days' including today = days_back(as_of, 7).
    Whether a window includes today is a rulebook decision: pass as_of - 1 day as ref to end yesterday."""
    if isinstance(n, bool) or not isinstance(n, (int, np.integer)) or n < 1:
        raise ValueError(f'days_back needs a whole number of days n >= 1, got {n!r}')
    end = _day(ref)
    return end - pd.Timedelta(days=int(n) - 1), end


def week_range(ref, week_start, offset=0, until=None):
    """Week containing ref shifted by `offset` weeks. week_start: 0=Monday … 6=Sunday, or a day name ('monday',
    'thứ hai', 'chủ nhật'), as the rulebook says. until: optional last date to clip the window (e.g. as_of)."""
    week_start = WEEKDAYS.get(fold(week_start), week_start) if isinstance(week_start, str) else week_start
    if isinstance(week_start, bool) or not isinstance(week_start, (int, np.integer)) or not 0 <= week_start <= 6:
        raise ValueError(f'week_start must be 0=Monday … 6=Sunday or a day name, got {week_start!r}')
    d = _day(ref)
    start = d - pd.Timedelta(days=(d.weekday() - week_start) % 7) + pd.Timedelta(weeks=offset)
    return _window(start, start + pd.Timedelta(days=6), until)


def month_range(ref, offset=0, until=None):
    start = (_day(ref).replace(day=1) + pd.DateOffset(months=offset)).normalize()
    return _window(start, (start + pd.offsets.MonthEnd(0)).normalize(), until)


def quarter_range(ref, offset=0, until=None):
    d = _day(ref)
    start = (pd.Timestamp(d.year, 3 * ((d.month - 1) // 3) + 1, 1) + pd.DateOffset(months=3 * offset)).normalize()
    return _window(start, (start + pd.DateOffset(months=3) - pd.Timedelta(days=1)).normalize(), until)


def year_range(ref, offset=0, until=None):
    start = pd.Timestamp(_day(ref).year + offset, 1, 1)
    return _window(start, pd.Timestamp(start.year, 12, 31), until)
