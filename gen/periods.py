"""Periods of a question as inclusive [start, end] dates, resolved against as_of and the rules (week start, Tết).

A period spec is a dict with 'kind':
  day(date) | today | yesterday | month(y, m) | this_month | quarter(y, q) | this_week | last_week | last_n_days(n)
  | ytd | range(start, end) | tet(year) | year(y) | upto(date) (from the start of the data)
  | season(name, year) (window named in a split rulebook: Rules.seasons)
Months/quarters without a year are resolved by the question generator (rulebook §2), never here.
"""
from __future__ import annotations

import calendar as _cal
import datetime as dt
from functools import lru_cache
from pathlib import Path

import pandas as pd

CALENDAR = Path(__file__).resolve().parents[1] / 'data' / 'train' / 'calendar.csv'


@lru_cache(maxsize=1)
def lunar_table():
    c = pd.read_csv(CALENDAR, parse_dates=['date'])
    return c


def solar_of_lunar(lunar_year, lunar_month, lunar_day):
    c = lunar_table()
    hit = c[(c.lunar_year == lunar_year) & (c.lunar_month == lunar_month) & (c.lunar_day == lunar_day) & ~c.lunar_leap]
    if hit.empty:
        raise ValueError(f'lunar {lunar_day}/{lunar_month}/{lunar_year} not in calendar')
    return hit.date.iloc[0].date()


def month_end(y, m):
    return dt.date(y, m, _cal.monthrange(y, m)[1])


def add_months(y, m, k):
    i = y * 12 + (m - 1) + k
    return i // 12, i % 12 + 1


def bounds(spec, as_of: dt.date, rules) -> tuple[dt.date, dt.date]:
    k = spec['kind']
    if k == 'day':
        d = spec['date']
        return d, d
    if k == 'today':
        return as_of, as_of
    if k == 'yesterday':
        d = as_of - dt.timedelta(days=1)
        return d, d
    if k == 'month':
        return dt.date(spec['y'], spec['m'], 1), month_end(spec['y'], spec['m'])
    if k == 'this_month':
        return as_of.replace(day=1), as_of
    if k == 'quarter':
        m0 = 3 * (spec['q'] - 1) + 1
        return dt.date(spec['y'], m0, 1), month_end(spec['y'], m0 + 2)
    if k == 'year':
        return dt.date(spec['y'], 1, 1), dt.date(spec['y'], 12, 31)
    if k in ('this_week', 'last_week'):
        start = as_of - dt.timedelta(days=(as_of.weekday() - rules.week_start) % 7)
        if k == 'this_week':
            return start, as_of
        return start - dt.timedelta(days=7), start - dt.timedelta(days=1)
    if k == 'last_n_days':
        if not getattr(rules, 'last_n_include_today', True):          # split rulebook: N full days before today
            return as_of - dt.timedelta(days=spec['n']), as_of - dt.timedelta(days=1)
        return as_of - dt.timedelta(days=spec['n'] - 1), as_of
    if k == 'ytd':
        return as_of.replace(month=1, day=1), as_of
    if k == 'range':
        return spec['start'], spec['end']
    if k == 'upto':
        return dt.date(1900, 1, 1), spec['date']
    if k == 'tet':
        y = spec['year']
        (m1, d1), (m2, d2) = rules.tet_start, rules.tet_end
        return solar_of_lunar(y - 1 if m1 > m2 else y, m1, d1), solar_of_lunar(y, m2, d2)
    if k == 'season':                         # a named window the split rulebook defines (vụ Đông Xuân, mùa tựu trường)
        y = spec['year']
        for key, _label, (m1, d1), (m2, d2) in getattr(rules, 'seasons', ()):
            if key == spec['name']:
                return dt.date(y - 1 if (m1, d1) > (m2, d2) else y, m1, d1), dt.date(y, m2, d2)
        raise ValueError(f"season {spec['name']} not in the rulebook")
    raise ValueError(k)


def previous(spec, as_of, rules, same_days=None):
    """The comparison period of 'thay đổi so với kỳ trước' (rulebook §1, §2). same_days: the question's own words fix
    the window of 'tháng này' vs the previous month (True: 'cùng kỳ', 'cùng số ngày'; False: 'cả tháng trước'), over
    the rulebook (§ intro: the question wins when it says otherwise)."""
    k = spec['kind']
    if k == 'month':
        y, m = add_months(spec['y'], spec['m'], -1)
        return {'kind': 'month', 'y': y, 'm': m}
    if k == 'quarter':
        q, y = spec['q'] - 1, spec['y']
        if q == 0:
            q, y = 4, y - 1
        return {'kind': 'quarter', 'y': y, 'q': q}
    if k == 'this_month':                     # same number of days of the previous month (clamped to its end)
        y, m = add_months(as_of.year, as_of.month, -1)
        same = rules.this_month_same_days if same_days is None else same_days
        end = min(as_of.day, _cal.monthrange(y, m)[1]) if same else _cal.monthrange(y, m)[1]
        return {'kind': 'range', 'start': dt.date(y, m, 1), 'end': dt.date(y, m, end)}
    if k == 'tet':
        return {'kind': 'tet', 'year': spec['year'] - 1}
    if k == 'season':
        return {**spec, 'year': spec['year'] - 1}
    if k in ('day', 'today', 'yesterday', 'last_week', 'this_week', 'last_n_days', 'range'):
        s, e = bounds(spec, as_of, rules)
        n = (e - s).days + 1
        if k == 'this_week':
            n = 7
            s2 = s - dt.timedelta(days=7)
            return {'kind': 'range', 'start': s2, 'end': s2 + dt.timedelta(days=(e - s).days)}
        return {'kind': 'range', 'start': s - dt.timedelta(days=n), 'end': s - dt.timedelta(days=1)}
    raise ValueError(k)


def before_tet(spec, as_of, rules, days=None):
    """'So với trước Tết' = the same number of days right before 23 tháng Chạp; `days` when the question names the
    number ('17 ngày trước Tết')."""
    s, e = bounds(spec, as_of, rules)
    n = days or (e - s).days + 1
    return {'kind': 'range', 'start': s - dt.timedelta(days=n), 'end': s - dt.timedelta(days=1)}
