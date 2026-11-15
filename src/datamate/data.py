"""Business data as pandas tables for the agent, plus a profile of every column. Format fixes only.

In:  a business folder (CSV/XLSX/SQLite + README.md) and the split's calendar.csv.
Out: `Business` with `tables` {name: DataFrame} in sandbox dtypes (int64 / float64 / str / datetime64 / bool /
     object for mixed) and `profiles` (rows, sources, dropped rows, exact duplicates, per-column stats).
Kept: header detection; blank, repeated-header, one-cell note and one-label total rows dropped; partitions of one
table (sheets, files named _1/_2026) concatenated with `__source`; numbers, quantities, dates parsed from content
with the original text kept in `<col>__raw` when the source held text.
Not done (business rules belong to the agent): duplicate removal, fill-down, status normalization, entity merging.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import pickle
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .grids import column_positions, decode_text, find_header, labels_of, read_business, table_name
from .columns import date_order, decimal_mark, to_series, type_column
from .layout import GROUP_TOTAL, body_rows, fill_groups, partition_groups, run_totals, sub_header, title_lines
from .values import fold, nfc, parse_datetime, parse_number, parse_qty, year_hint

READER_VERSION = 'thin/v5.0'
ENUM_LIMIT = 30             # at most this many distinct values: list them all with counts
INDEX_LIMIT = 5000          # text columns with at most this many distinct values get a lookup index
SAMPLES = 5
SOURCE_COL, RAW_SUFFIX, UNIT_SUFFIX, SECTION_COL, START_COL = '__source', '__raw', '__unit', '__section', '__group_start'

@dataclass
class Business:
    id: str
    readme: str
    tables: dict = field(default_factory=dict)       # name -> DataFrame
    profiles: list = field(default_factory=list)     # one dict per table, same order as tables
    unreadable: list = field(default_factory=list)   # files/objects skipped by the reader, with the reason


# ---------------------------------------------------------------- tables
def parse_grids(folder: Path, problems=None):
    """{source: header labels, data rows, dropped rows and examples, section of each row, text above the header}."""
    parsed = {}
    for g in read_business(folder, problems):
        h, group = find_header(g.rows, g.is_sql)
        merged = None if g.is_sql else sub_header(g.rows, h)
        data, dropped, extra = body_rows(g.rows, h + (merged is not None), g.is_sql)
        parsed[g.src] = {'grid': g, 'labels': labels_of(g.rows, h, group, merged), 'data': data, 'dropped': dropped,
                         'title': title_lines(g.rows, h, group), **extra}
    return parsed


def build_tables(folder: Path, problems=None):
    """[(name, DataFrame, meta)] for one business folder."""
    parsed = parse_grids(folder, problems)
    sheets = Counter(src.split(':')[0] for src in parsed)
    out, used = [], set()
    for srcs in partition_groups(parsed):
        name = table_name(srcs[0], sheets[srcs[0].split(':')[0]] > 1 and len(srcs) == 1)
        while name in used:
            name += '_2'
        used.add(name)
        rows = [(s, i) for s in srcs for i in parsed[s]['data']]
        columns, notes = typed_columns(parsed, srcs, rows)
        if any(parsed[s]['section'] for s in srcs):
            columns[SECTION_COL] = to_series('text', [parsed[s]['section'].get(i) for s, i in rows])
            notes[SECTION_COL] = 'text of the one-cell row heading the section this row is in (such as a group name)'
        if len(srcs) > 1:
            columns[SOURCE_COL], notes[SOURCE_COL] = pd.Series([s for s, _ in rows], dtype='str'), 'origin sheet/file of the row'
        frame, filled = fill_groups(pd.DataFrame(columns) if columns else pd.DataFrame(index=range(len(rows))))
        if not filled and (runs := run_totals(frame))[1]:
            frame, filled = runs[0], {**runs[1], 'columns': []}
        if filled:                                      # rulebook: blank cells on the following lines of a group = first line
            for c in filled['columns']:
                notes[c] += f"; blank on {filled['rows']} lines continuing a group (key \"{filled['key']}\"), filled from the group's first line"
            for c in filled['totals']:
                notes[c] += f'; blank on the rows that start a group: their value was the sum of the group\'s other lines, now in "{c + GROUP_TOTAL}"'
                notes[c + GROUP_TOTAL] = f'"{c}" of the group\'s first row (the sum of its other lines), on that row only'
            if 'start' in filled:
                frame[START_COL] = filled['start']
                notes[START_COL] = 'True on the rows that carried the group cells in the file (others were filled; blank them to undo)'
        examples = {k: list(dict.fromkeys(e for s in srcs for e in parsed[s]['examples'].get(k, [])))[:3]
                    for k in {k for s in srcs for k in parsed[s]['examples']}}
        meta = {'sources': source_summary(srcs), 'dropped_rows': dict(sum((parsed[s]['dropped'] for s in srcs), Counter())),
                'dropped_examples': examples, 'notes': notes,
                'title': list(dict.fromkeys(t for s in srcs for t in parsed[s]['title']))[:5]}
        out.append((name, frame, meta))
    return out


def typed_columns(parsed, srcs, rows):
    """Columns of one table in sandbox dtypes, with the companions (__unit, __raw) and a note per column."""
    columns, notes = {}, {}
    position = {s: column_positions(parsed[srcs[0]]['labels'], parsed[s]['labels']) for s in srcs}
    for j, label in enumerate(parsed[srcs[0]]['labels']):
        raw = [parsed[s]['grid'].rows[i][position[s][j]] for s, i in rows]      # columns in any order
        kind, values, units = type_column(raw, [s for s, _ in rows], label)
        columns[label] = to_series(kind, values)
        note = kind
        if kind == 'quantity':
            columns[label + UNIT_SUFFIX] = to_series('text', units)
            notes[label + UNIT_SUFFIX] = f'unit written in "{label}"'
        texts = [v for v in raw if isinstance(v, str)]
        if kind == 'date' and date_order(texts) == 'md':
            note += '; text dates read as month/day/year (cells with a second part above 12 show it)'
        if kind == 'number' and (mark := decimal_mark(texts)) and (n := sum(parse_number(v) != parse_number(v, mark) for v in texts)):
            note += f'; {n} cells such as "1{mark}250" read with "{mark}" as the decimal mark, as other cells of the column show'
        serials = kind == 'date' and any(isinstance(v, (int, float)) and not isinstance(v, bool) for v in raw)
        if kind in ('number', 'quantity', 'date') and (texts or serials):     # numbers read as dates stay undoable
            columns[label + RAW_SUFFIX] = to_series('text', [None if v is None else nfc(str(v)) for v in raw])
            notes[label + RAW_SUFFIX] = f'original text of "{label}"'
            note += f'; read from Excel serial numbers, original in "{label + RAW_SUFFIX}"' if serials and not texts else \
                f'; parsed from text, original in "{label + RAW_SUFFIX}"'
            unparsed = sum(o is not None and p is None for o, p in zip(raw, values))
            if unparsed:
                note += f'; {unparsed} cells did not parse (blank here)'
        notes[label] = note
    return columns, notes


def source_summary(sources):
    """'DonHang.xlsx (18 sheets)' instead of every sheet; rows keep the detail in __source."""
    files = Counter(s.split(':', 1)[0] for s in sources)
    return [f'{f} ({n} sheets)' if n > 1 else next(s for s in sources if s.split(':', 1)[0] == f) for f, n in files.items()]


def calendar_table(path: Path):
    """The split's solar-lunar calendar as a table (dates, lunar dates, holidays)."""
    try:
        text = Path(path).read_text(encoding='utf-8-sig')
    except (OSError, UnicodeDecodeError):
        text = 'date\n'                                  # no calendar: an empty table, questions still run
    rows = list(csv.reader(io.StringIO(text, newline=''))) or [['date']]
    header, body = rows[0], [r + [''] * (len(rows[0]) - len(r)) for r in rows[1:]]
    columns, notes = {}, {}
    for j, name in enumerate(header):
        raw = [r[j].strip() or None for r in body]
        if {v.lower() for v in raw if v is not None} <= {'true', 'false'}:
            kind, values = 'bool', [None if v is None else v.lower() == 'true' for v in raw]
        else:
            kind, values, _ = type_column(raw, [''] * len(raw), name)
        columns[name], notes[name] = to_series(kind, values), kind
    frame = pd.DataFrame(columns)
    if 'date' in frame and 'weekday' in frame and len(frame) and (frame['date'].dt.day_of_week + 1 == frame['weekday']).all():
        notes['weekday'] += '; 1=Monday .. 7=Sunday (checked against date)'
    return frame, {'sources': [Path(path).name], 'dropped_rows': {}, 'notes': notes}


# ---------------------------------------------------------------- profile
def is_text(series: pd.Series) -> bool:
    """A text column: pandas 3 'str' dtype, or (pandas 2) object dtype holding only strings."""
    if str(series.dtype) == 'str':
        return True
    return series.dtype == object and series.dropna().map(lambda v: isinstance(v, str)).all()


def _display(v):
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat() if v == v.normalize() else v.isoformat(sep=' ')
    if isinstance(v, (float, np.floating)) and float(v).is_integer():
        return str(int(v))
    return str(v)


def _stored(v):
    """A value as code compares it: Python int/bool/str, never a display string with the count."""
    if isinstance(v, (bool, np.bool_, int, np.integer)):
        return bool(v) if isinstance(v, (bool, np.bool_)) else int(v)
    finite = isinstance(v, (float, np.floating)) and np.isfinite(v)
    return (int(v) if float(v).is_integer() else float(v)) if finite else _display(v)


def profile_column(series: pd.Series, note: str):
    present = series.dropna()
    counts = present.astype(str).value_counts() if present.dtype == object else present.value_counts()
    col = {'type': str(series.dtype), 'about': note, 'distinct': int(len(counts))}
    blank = int(len(series) - len(present))
    if blank:
        col['blank'] = blank
    numeric_or_date = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series) \
        or pd.api.types.is_datetime64_any_dtype(series)
    if numeric_or_date and len(present):
        col['range'] = f'{_display(present.min())} .. {_display(present.max())}'
    numeric = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0] if numeric else _display(kv[0])))
    if len(counts) <= ENUM_LIMIT and not pd.api.types.is_float_dtype(series) and not pd.api.types.is_datetime64_any_dtype(series):
        col['all_values'] = [[_stored(v), int(c)] for v, c in ordered]      # [stored value, rows]: copy the value alone
    elif ordered:
        col['examples'] = [_stored(v) for v, _ in ordered[:SAMPLES]]       # same value form as all_values
    if is_text(series):
        padded = int((present != present.str.strip()).sum())
        if padded:
            col['about'] += f'; {padded} values have leading/trailing spaces: strip before matching or joining'
    return col


def profile_table(name, frame, meta):
    content = [c for c in frame.columns if c not in (SOURCE_COL, START_COL)]   # as kit.dedup counts them
    duplicates = int(frame.duplicated(subset=content).sum()) if content and len(frame) else 0
    columns, lookup = [], {}
    for c in frame.columns:
        col = profile_column(frame[c], meta['notes'].get(c, ''))
        columns.append({'name': c, **col})
        if is_text(frame[c]) and 0 < col['distinct'] <= INDEX_LIMIT:
            lookup[c] = sorted(frame[c].dropna().value_counts().items())
    return {'table': name, 'rows': len(frame), 'sources': meta['sources'], 'dropped_rows': meta['dropped_rows'],
            'dropped_examples': meta.get('dropped_examples', {}), 'title': meta.get('title', []),
            'exact_duplicate_rows': duplicates, 'columns': columns, 'lookup': lookup}


# ---------------------------------------------------------------- business (cached)
def _fingerprint(folder: Path, calendar: Path):
    h = hashlib.sha256(f'{READER_VERSION}|pandas {pd.__version__}|{__name__}'.encode())   # pickles are pandas- and package-name-specific
    for f in sorted([*Path(folder).iterdir(), Path(calendar)]):
        if f.is_file():
            h.update(f.name.encode()); h.update(f.read_bytes())
    return h.hexdigest()[:24]


def load_business(folder: Path, calendar: Path, cache_dir: Path | None = None) -> Business:
    """Read, type and profile one business; cached on disk by file contents and reader version."""
    folder = Path(folder)
    cache = Path(cache_dir) / f'{folder.name}-{_fingerprint(folder, calendar)}.pkl' if cache_dir else None
    if cache and cache.exists():
        try:
            with open(cache, 'rb') as f:
                return pickle.load(f)
        except Exception:                                  # damaged cache file: rebuild it
            cache.unlink(missing_ok=True)
    readme = next((decode_text(f.read_bytes()) for f in sorted(folder.iterdir()) if f.name.lower() == 'readme.md' and f.is_file()), '')
    business = Business(folder.name, readme)
    for name, frame, meta in [*build_tables(folder, business.unreadable), ('calendar', *calendar_table(calendar))]:
        business.tables[name] = frame
        business.profiles.append(profile_table(name, frame, meta))
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix('.tmp')
        with open(tmp, 'wb') as f:
            pickle.dump(business, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(cache)
    return business
