"""`dm`: generic helpers available to agent code in the sandbox, and TolerantFrame (tables[...] returns one).

Mechanics only, no business rules. Anything a rulebook or README decides (week start, whether a period stops
at as_of, which statuses are excluded, which column is the key) is a required argument chosen by the agent.
The one default taken from the competition itself is the ranking tie-break: equal values ordered by code
ascending (docs/zac/evaluation.md). A call that cannot be read one way (a week start 7, a date it cannot read,
a ranking with no clear code) raises with the fix, rather than return a plausible wrong value.
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
import unicodedata

import numpy as np
import pandas as pd
from pandas.core.indexing import _LocIndexer

from .values import _CURRENCY, decimal_mark, parse_datetime, parse_number
from .windows import _day, _window, day_range, days_back, month_range, quarter_range, week_range, year_range  # noqa: F401
from .names import name_key  # noqa: F401

__all__ = ['norm', 'name_key', 'factors', 'name', 'col', 'days_back', 'dedup', 'to_num', 'to_date', 'month_range', 'week_range', 'quarter_range', 'year_range',
           'day_range', 'between', 'drop_groups', 'top', 'values']


UNANSWERABLE_TEXT = ('unanswerable', 'khong tra loi duoc', 'khong the tra loi')


def says_unanswerable(value):
    """A text answer that concludes 'unanswerable' (its normalized text starts with such a phrase). Not a kit function."""
    return isinstance(value, str) and norm(value).startswith(UNANSWERABLE_TEXT)


# ---------------------------------------------------------------- text and columns
def norm(text, accents=False):
    """Comparable form of a name: NFC, lower case, punctuation to spaces, single spaces.
    accents=False also removes Vietnamese diacritics (đ -> d). A Series is normalized value by value."""
    if isinstance(text, pd.Series):
        return text.map({v: norm(v, accents) for v in text.dropna().unique()}).fillna('')
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ''
    if isinstance(text, (float, np.floating)) and float(text).is_integer():
        text = int(text)                    # a code stored as 12.0 (a column with blanks) is "12"
    s = unicodedata.normalize('NFC', str(text)).casefold()
    if not accents:
        s = unicodedata.normalize('NFD', s.replace('đ', 'd'))
        s = ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn')
    s = re.sub(r'[\W_]+', ' ', s)          # underscores separate words too (zalo_oa ~ zalo oa)
    return ' '.join(s.split())


def name(df, name):
    """Real column label for `name`: exact, else the one column equal after norm(). Raises KeyError listing the
    closest labels (a shorter name such as "Ngày" never picks "Ngày giao hàng" silently)."""
    if name in df.columns:
        return name
    hits = [c for c in df.columns if isinstance(c, str) and norm(c) == norm(name)]
    if len(hits) == 1:
        return hits[0]
    labels = [str(c) for c in df.columns]
    close = difflib.get_close_matches(norm(name), [norm(c) for c in labels], n=5, cutoff=0.4)
    raise KeyError(f'{name!r} is ambiguous: {hits}' if hits else
                   f'No column {name!r}. Closest: {[c for c in labels if norm(c) in close] or labels[:10]}')


class _TolerantLoc(_LocIndexer):
    def __setitem__(self, key, value):          # df.loc[mask, 'so luong'] = ... writes "Số lượng"
        if isinstance(key, tuple) and len(key) == 2 and isinstance(key[1], (str, list)):
            cols = key[1] if isinstance(key[1], list) else [key[1]]
            cols = [self.obj._tolerant_label(c, new_ok=True) if isinstance(c, str) else c for c in cols]
            key = (key[0], cols if isinstance(key[1], list) else cols[0])
        super().__setitem__(key, value)


class TolerantFrame(pd.DataFrame):
    """DataFrame whose column lookup tolerates accent/case/punctuation differences when exactly one column
    matches after norm(), for reads and writes (df['so luong'] = ... updates "Số lượng"); otherwise the KeyError
    lists the table's columns and the closest ones. Results of pandas operations stay TolerantFrame."""
    @property
    def _constructor(self):
        return TolerantFrame

    @property
    def loc(self):
        return _TolerantLoc('loc', self)

    def _tolerant_label(self, key, new_ok=False):
        if not isinstance(key, str) or key in self.columns: return key
        hits = [c for c in self.columns if isinstance(c, str) and norm(c) == norm(key)]
        if len(hits) == 1: return hits[0]
        if new_ok and not hits: return key                      # a new column
        labels = [str(c) for c in self.columns]
        close = difflib.get_close_matches(norm(key), [norm(c) for c in labels], n=3, cutoff=0.5)
        raise KeyError(f'Column {key!r} not in this table ({"ambiguous: " + str(hits) if hits else "no match"}). '
                       f'Closest: {[c for c in labels if norm(c) in close]}. Columns: {[c for c in labels if not c.endswith("__raw")]}')

    def __setitem__(self, key, value):
        super().__setitem__(self._tolerant_label(key, new_ok=True) if isinstance(key, str) else key, value)

    def __getitem__(self, key):
        if isinstance(key, pd.Series) and key.dtype == object and key.map(lambda v: v is None or v is pd.NA or isinstance(v, (bool, np.bool_)) or v != v).all():
            key = key.map(lambda v: bool(v) if isinstance(v, (bool, np.bool_)) else False).astype(bool)          # a mask built on a column with blanks: blank = not selected
        if (isinstance(key, pd.DataFrame) and not all(str(t) == 'bool' for t in key.dtypes)
                and list(key.columns) == list(self.columns) and key.index.isin(self.index).all()):
            return self.loc[key.index]                    # df[filtered_df]: an already filtered frame used as a mask
        try:
            return super().__getitem__(key)
        except KeyError:
            if isinstance(key, str): return super().__getitem__(self._tolerant_label(key))
            if isinstance(key, list) and key and all(isinstance(k, str) for k in key):
                return super().__getitem__([self._tolerant_label(k) for k in key])
            raise


def col(df, label):
    """The column itself (a Series), looked up like name(). Not advertised; kept because the model uses it."""
    return df[name(df, label)]


# ---------------------------------------------------------------- numbers and dates
_NUM = re.compile(r'[-+]?\d[\d.,\s]*')


def _one_number(v, mark=None):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if pd.isna(v) else v
    if (exact := parse_number(str(v), mark)) is not None:       # 19tr990, 120k, (5.000), 1.234.567 đ, .5, 5.000-
        return int(exact) if float(exact).is_integer() else exact
    m = _NUM.search(str(v))
    rest = str(v)[:m.start()] + str(v)[m.end():] if m else ''
    if not m or re.search(r'\d', rest) or (m.start() and str(v)[m.start() - 1].isalpha()):
        return None                         # codes (SP001), dates (01/02/2025), ranges (10-20): not one number
    f = parse_number(re.sub(r'\s', '', m.group()).rstrip('.,'), mark)   # the number inside "2,5 kg", "12%"
    return None if f is None else int(f) if f.is_integer() and abs(f) < 2 ** 53 else f


def to_num(values):
    """Numbers from mixed cells: '10,000' -> 10000, '1.234.567 đ' -> 1234567, '2,5 kg' -> 2.5. A cell that is not one
    number (a code 'SP001', a date, a range '10-20') -> None: check how many became None before summing. "1.250" is
    1250 unless the values themselves prove "." a decimal mark ("0.500", "1,234.5"), as the tables were read: convert
    the whole column before filtering. One cell in, one number out."""
    if isinstance(values, (pd.DataFrame, dict)): raise TypeError('to_num: pass one column (df[col]); for several use df[cols].apply(kit.to_num)')
    if values is None or isinstance(values, (str, int, float, dt.date, np.generic)):
        return _one_number(values, decimal_mark([values]) if isinstance(values, str) else None)
    vals = list(values)
    mark = decimal_mark([v for v in vals if isinstance(v, str)])
    memo = {v: _one_number(v, mark) for v in {v for v in vals if isinstance(v, str)}}
    out = [memo[v] if isinstance(v, str) else _one_number(v) for v in vals]
    return pd.Series(out, index=values.index if isinstance(values, pd.Series) else None, dtype=object)


def _one_date(v, dayfirst, excel_serial):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
        return pd.NaT
    if isinstance(v, (dt.datetime, dt.date, pd.Timestamp)):
        return pd.Timestamp(v)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return pd.Timestamp('1899-12-30') + pd.Timedelta(seconds=round(float(v) * 86400)) if excel_serial else pd.NaT
    s = str(v).strip()
    if (d := parse_datetime(s, None, serial_ok=False, dayfirst=dayfirst)) is not None:
        return pd.Timestamp(d)              # d/m/y, y/m/d, "ngày 3 tháng 4 năm 2025": as the tables were read
    if not re.search(r'[^\W\d_]', s):       # only digits and marks ("1,044,000", "2025"): not a date
        return pd.NaT
    try:
        return pd.to_datetime(s, dayfirst=dayfirst)        # month names, ISO with T/Z
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


def to_date(values, dayfirst=True, excel_serial=False):
    """Timestamps from date objects or text. Numbers are Excel serial days only when excel_serial=True.
    Unparsable -> NaT; count them before filtering. One cell in, one Timestamp out."""
    if isinstance(values, (pd.DataFrame, dict)): raise TypeError('to_date: pass one column (df[col]); for several use df[cols].apply(kit.to_date)')
    if values is None or isinstance(values, (str, int, float, dt.date, np.generic)):
        return _one_date(values, dayfirst, excel_serial)
    if isinstance(values, pd.Series) and pd.api.types.is_datetime64_any_dtype(values):
        return values
    memo = {}

    def one(v):
        try:
            if v not in memo: memo[v] = _one_date(v, dayfirst, excel_serial)
            return memo[v]
        except TypeError:                           # unhashable cell
            return _one_date(v, dayfirst, excel_serial)
    return pd.Series([one(v) for v in values], index=values.index if isinstance(values, pd.Series) else None, dtype='datetime64[ns]')


def between(df, column, start, end, dayfirst=True, excel_serial=False):
    """Rows whose `column` date lies in [start, end], both ends inclusive, compared by calendar day. Raises when the
    column does not hold dates (most cells unreadable) or when end is before start."""
    start, end = _window(_day(start), _day(end))
    cells = df[name(df, column)]
    days = to_date(cells, dayfirst, excel_serial).dt.normalize()
    if days.notna().sum() * 2 < cells.notna().sum():
        hint = '; numbers: pass excel_serial=True if they are Excel dates' if pd.api.types.is_numeric_dtype(cells) else ''
        raise ValueError(f'between: column {column!r} does not hold dates (e.g. {cells.dropna().head(3).tolist()}){hint}')
    rows = df[(days >= start) & (days <= end)]
    return WindowRows(rows) if isinstance(rows, TolerantFrame) else rows


MASK_HINT = ('kit.between returns the ROWS of the window (a table), not a mask: rows = kit.between(df, col, start, end); '
             'inside a mask write (df[col] >= start) & (df[col] < end + pd.Timedelta(days=1)).')


class WindowRows(TolerantFrame):
    """The rows kit.between returns: a table that refuses &, |, ^ and ~ (the usual mistake: using it as a mask)."""
    @property
    def _constructor(self):
        return TolerantFrame

    def _not_a_mask(self, *args):
        raise TypeError(MASK_HINT)

    __and__ = __rand__ = __or__ = __ror__ = __xor__ = __rxor__ = __invert__ = _not_a_mask


# ---------------------------------------------------------------- dates, groups and ranking
def dedup(df):
    """Drop rows identical in every column, keeping the first. Layout markers are ignored: the __source partition
    label, and __group_start (a line repeated as a group's continuation row is the same line as the group's first)."""
    return df[~df.drop(columns=[c for c in ('__source', '__group_start') if c in df.columns]).duplicated(keep='first')]


def drop_groups(df, group_column, mask):
    """Remove every row of each group (e.g. an order) in which `mask` is True for at least one row. A row without a
    group key is removed only by its own mask (blank keys are not one group)."""
    key = df[name(df, group_column)]
    if isinstance(mask, pd.Series) and not mask.index.equals(df.index):
        raise ValueError('drop_groups: the mask must be built from the same rows as df (same index); build it from df')
    hit = pd.Series([v is not None and v is not pd.NA and v == v and bool(v) for v in mask], index=df.index, dtype=bool)
    bad = set(key[hit].dropna())
    return df[~(key.isin(bad) | (key.isna() & hit))]


def top(data, by=None, k=None, ascending=False, tie=None):
    """Sort for a ranking and keep the first k. Equal values (to 9 decimals) are ordered by the code ascending: the
    `tie` column or index level when given, else the index of a Series or of a frame indexed by code (a groupby
    result), else the frame's only text column. Raises when the code is not clear (two text columns, a two-level
    index): pass tie='<code column>'. Inspect rows around position k for ties before answering."""
    series, ix = isinstance(data, pd.Series), data.index
    if series and by is not None and k is None:            # dm.top(per, 3): the 3 went to `by`, k would be all rows
        raise TypeError('kit.top(series, k=3): pass k by name (by= is for a DataFrame column)')
    by_code = not (ix.nlevels == 1 and ix.name is None and pd.api.types.is_integer_dtype(ix))   # not row numbers
    frame = (data.rename('_value').to_frame() if series else data).reset_index(drop=not by_code)
    frame.index = range(len(frame))
    value = '_value' if series else name(frame, by)
    levels = list(frame.columns[:ix.nlevels]) if by_code else []
    if tie is not None:
        key = name(frame, tie)
    elif len(levels) == 1:
        key = levels[0]
    else:
        texts = [c for c in frame.columns if c != value and (frame[c].dtype == object or str(frame[c].dtype) == 'str'
                 or pd.api.types.is_integer_dtype(frame[c]))]          # integer codes count too
        if levels or len(texts) != 1:
            raise ValueError(f'top: which column is the code that breaks ties? pass tie= one of {levels or texts}')
        key = texts[0]
    num = pd.to_numeric(frame[value], errors='coerce')                   # object sums of dm.to_num output too
    rank = num.round(9) if num.notna().sum() == frame[value].notna().sum() else frame[value]
    order = frame.assign(_rank=rank).sort_values(['_rank', key], ascending=[ascending, True], kind='mergesort').index
    out = data.iloc[list(order)]
    return out if k is None else out.head(k)


def values(df, column, n=30):
    """Distinct values with counts, most frequent first: use it to decide which labels a rule covers."""
    return df[name(df, column)].value_counts(dropna=False).head(n)


SIDE = re.compile(r'\s*(\d[\d.,]*)\s*([^\W\d_(].*?)\s*')          # "24 lon", "12 chai 1,5L", "1 xe 4m3", "1 hộp 30"
PIECE = re.compile(r'[,.;]\s+|(?<=[^\W\d_)])\s*[,.;]\s*(?=\d)|\s+(?:và|hoặc|and)\s+')     # one rule per piece


def _side(text):
    """(quantity, unit) of one side of a rule, or None: "<n> <unit>", or "<n1> <u1> x <n2> <u2>" = n1*n2 <u2>."""
    if m := re.fullmatch(r'(.+?)\s+[x×]\s+(.+)', text.strip()):
        a, b = _side(m[1]), _side(m[2])
        return (a[0] * b[0], b[1]) if a and b else None
    m = SIDE.fullmatch(text)
    words = m[2].split() if m else []                   # a bare number only as the last word ("hộp 30", not "lon 330 ml")
    ok = m and to_num(m[1]) and all(re.search(r'[^\W\d_()]', w) or '(' in w or ')' in w or i == len(words) - 1 for i, w in enumerate(words))
    return (to_num(m[1]), m[2].strip()) if ok else None


def factors(values, base=None):
    """Unit rules as text ("1 thùng = 24 lon; mỗi lốc = 6 lon", "Bia A: 1 thùng = 24 lon; Bia B: 1 thùng = 20 lon",
    README "- <item>: 1 hộp = 10 vỉ x 10 viên") -> DataFrame [row, item (text before ":", else None), unit, factor =
    base units in ONE unit, base, unit_key, base_key (norm: join on these)], one row per pair of sides as written;
    base='<unit>' (the item list's base unit) follows chains to it. A rule-shaped text it cannot read raises."""
    if isinstance(values, (pd.DataFrame, dict)):
        raise TypeError('factors: pass one column, a list of texts or a text')
    items = values.items() if isinstance(values, pd.Series) else enumerate([values] if isinstance(values, str) else values)
    rows, unread = [], []
    for key, text in items:
        for part in re.split(r'[;\n]|\.\s+(?=[^\W\d_][^:=.]*:)', str(text)) if text is not None else []:
            item, rule = part.rsplit(':', 1) if ':' in part else (None, part)
            item = item.strip().lstrip('-*• ').strip() or None if item is not None else None
            for piece in PIECE.split(re.sub(r'\bmỗi\s+', '1 ', rule.strip().lstrip('-*• '), flags=re.I)):     # "mỗi lốc" = "1 lốc"
                texts = [t for t in piece.split('=') if not _CURRENCY.search(t)] if '=' in piece else []   # price sides out
                sides = [_side(t) for t in texts] if len(texts) > 1 else []
                if sides and not all(sides):
                    unread += [piece.strip()] if all(re.match(r'\s*\d', t) for t in texts) else []   # rule-shaped only
                elif sides:
                    rows += [{'row': key, 'item': item, 'unit': u, 'factor': sides[j][0] / q, 'base': sides[j][1], 'last': j == len(sides) - 1}
                             for i, (q, u) in enumerate(sides) for j in range(i + 1, len(sides))]
    if unread:                                                          # never a silent factor 1 downstream
        raise ValueError(f'kit.factors could not read {unread[:5]}: write those factors yourself (or pass only the lines it reads)')
    for r in rows if base is not None else []:                        # chains toward the base unit asked for
        seen = {norm(r['unit'])}
        while norm(r['base']) != norm(base) and (nxt := next((x for x in rows if (x['row'], x['item']) == (r['row'], r['item'])
                                                            and norm(x['unit']) == norm(r['base']) and norm(x['base']) not in seen), None)):
            r['factor'], r['base'] = r['factor'] * nxt['factor'], nxt['base']
            seen.add(norm(nxt['unit']))
    if base is not None:                                                # one row per unit: the one in `base` when there is one
        reach = {(r['row'], r['item'], norm(r['unit'])) for r in rows if norm(r['base']) == norm(base)}
        rows = [r for r in rows if norm(r['base']) == norm(base) or (r['row'], r['item'], norm(r['unit'])) not in reach]
    rows = [r for r in rows if r.pop('last') or (base is not None and norm(r['base']) == norm(base))]   # no unit twice
    out = pd.DataFrame(rows, columns=['row', 'item', 'unit', 'factor', 'base'])
    out = out.assign(unit_key=norm(out['unit'].astype(object)), base_key=norm(out['base'].astype(object)))
    if (clash := out.drop_duplicates(['row', 'item', 'unit_key', 'factor']).duplicated(['row', 'item', 'unit_key'])).any():
        raise ValueError(f"kit.factors: two factors for one unit {out.loc[clash[clash].index, 'unit'].tolist()[:3]}: decide which rule applies")
    return out.drop_duplicates(['row', 'item', 'unit_key']).reset_index(drop=True)
