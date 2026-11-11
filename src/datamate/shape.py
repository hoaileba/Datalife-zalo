"""Turn the program's `result` into a plain, JSON-safe value (runs inside the sandbox worker).

In:  any Python/pandas/numpy object assigned to `result`.
Out: scalar | list | {'columns': [...], 'rows': [[...]]}; dates as {'$date': 'YYYY-MM-DD'} (or '$datetime'),
     Decimal as {'$decimal': '1.50'}. Raises ShapeError with guidance when the shape is ambiguous.
Unambiguous conversions only: DataFrame (also subclasses; group keys in the index become columns), Series (group
keys -> two-column table, else its values), ndarray/Index -> list, list of same-key dicts -> table,
dict of equal-length columns -> table. Nothing is guessed.
"""
from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal

MAX_ITEMS = 10000


class ShapeError(Exception):
    pass


def _is_frame(v):
    return all(hasattr(v, a) for a in ('columns', 'itertuples', 'index', 'dtypes'))


def _is_series(v):
    return not _is_frame(v) and all(hasattr(v, a) for a in ('index', 'to_frame', 'tolist'))


def _meaningful_index(index):
    """An index carrying data (group keys, names), not a row position left over from filtering."""
    if getattr(index, 'nlevels', 1) > 1 or any(n is not None for n in index.names):
        return True
    return str(getattr(index, 'dtype', '')) not in ('int64', 'int32', 'uint64')


def _table(columns, rows):
    columns = [str(c) for c in columns]
    repeated = sorted({c for c in columns if columns.count(c) > 1})
    if repeated:
        raise ShapeError(f'Table columns must be unique; repeated: {repeated}. Columns: {columns}')
    if len(rows) > MAX_ITEMS:
        raise ShapeError(f'Result has {len(rows)} rows; keep only what the question asks for')
    return {'columns': columns, 'rows': [[cell(v) for v in r] for r in rows]}


def cell(v):
    """One JSON-safe value."""
    if v is None:
        return None
    if type(v).__name__ in ('NAType', 'NaTType'):
        return None
    if type(v).__name__ in ('datetime64', 'timedelta64'):
        v = v.astype('datetime64[us]').item() if type(v).__name__ == 'datetime64' else v.astype('timedelta64[us]').item()
    elif type(v).__name__ == 'Period':                   # a month or a day period: its ISO text
        return str(v)
    if type(v).__module__.startswith('numpy') and hasattr(v, 'item'):
        v = v.item()
    if hasattr(v, 'to_pydatetime'):                       # pandas Timestamp
        v = v.to_pydatetime()
    if isinstance(v, bool) or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return None if math.isnan(v) else v if math.isfinite(v) else _bad('a non-finite number (inf)')
    if isinstance(v, Decimal):
        return {'$decimal': str(v)} if v.is_finite() else _bad('a non-finite Decimal')
    if isinstance(v, dt.datetime):
        if (v.hour, v.minute, v.second, v.microsecond) == (0, 0, 0, 0):
            return {'$date': v.date().isoformat()}
        return {'$datetime': v.isoformat()}
    if isinstance(v, dt.date):
        return {'$date': v.isoformat()}
    if isinstance(v, (list, tuple, dict)) or _is_frame(v) or _is_series(v):
        raise ShapeError('A list or table cell holds another list/table: flatten the result')
    raise ShapeError(f'Unsupported value type {type(v).__name__}: result must be a number, string, date, boolean, '
                     'a list of those, or a DataFrame (for a table)')


def _bad(what):
    raise ShapeError(f'Result contains {what}')


def shape(value):
    if _is_frame(value):
        if _meaningful_index(value.index):
            value = value.reset_index()
        return _table(value.columns, list(value.itertuples(index=False, name=None)))
    if _is_series(value):
        if _meaningful_index(value.index):
            return shape(value.reset_index())             # columns named after the index and the series
        if len(value) > MAX_ITEMS:
            _bad('too many items')
        return [cell(v) for v in value.tolist()]
    if type(value).__module__.startswith(('numpy', 'pandas')) and hasattr(value, 'tolist') and getattr(value, 'ndim', 0) == 1:
        if getattr(getattr(value, 'dtype', None), 'kind', '') in 'mM':
            return [cell(v) for v in value]               # datetime64 values: tolist() would give nanoseconds
        return [cell(v) for v in value.tolist()]          # ndarray, Index, unique()
    if isinstance(value, (list, tuple)):
        if value and all(isinstance(v, dict) for v in value):
            columns = list(value[0])
            if columns and all(list(v) == columns for v in value):
                return _table(columns, [[v[c] for c in columns] for v in value])
        if len(value) > MAX_ITEMS:
            _bad('too many items')
        return [cell(v) for v in value]
    if isinstance(value, dict):
        if set(value) == {'columns', 'rows'} and isinstance(value['columns'], list) and isinstance(value['rows'], list):
            return _table(value['columns'], [list(r) for r in value['rows']])
        columns = {k: (v.tolist() if hasattr(v, 'tolist') and not isinstance(v, str) else v) for k, v in value.items()}
        if columns and all(isinstance(v, (list, tuple)) for v in columns.values()) and len({len(v) for v in columns.values()}) == 1:
            return _table(list(columns), [list(r) for r in zip(*columns.values())])
        raise ShapeError('A dict result is ambiguous: for a table assign a DataFrame (one row per object, first column '
                         'the name), for a list a Python list, for one value the value itself')
    return cell(value)
