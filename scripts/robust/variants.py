"""Metamorphic test of the reader: rewrite each train shop's files in another layout or format that keeps the data
(title rows, totals with other labels, numbers/dates written as text in other conventions, monthly sheets, CSV
encodings, page-break headers, footers...) and check that the tables read back hold the same values.

    PYTHONPATH=src python scripts/robust/variants.py [--only biz_101,...] [--variants a,b] [--examples 3]

Baseline = the same shop rewritten with no change (same writer), so writer differences do not count. Columns are
matched by folded label, rows compared as sorted tuples of canonical values (number, ISO date, stripped text), so
a variant that only reorders rows or columns passes. Train data only.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import math
import random
import re
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from xlsx_writer import write_xlsx  # noqa: E402

from datamate import columns, data, grids, layout  # noqa: E402
from datamate.values import fold, parse_datetime, parse_number  # noqa: E402

TRAIN = Path('data/train/data')
INTERNAL = (data.RAW_SUFFIX, data.UNIT_SUFFIX, data.SOURCE_COL)


# ---------------------------------------------------------------- files <-> grids
def read_files(folder: Path):
    """{file name: [(sheet, rows)]} for the CSV/XLSX files (SQLite shops are skipped)."""
    out = defaultdict(list)
    for g in grids.read_business(folder):
        if g.is_sql:
            return None
        file, _, sheet = g.src.partition(':')
        out[file].append((sheet or None, [list(r) for r in g.rows]))
    return dict(out)


def write_files(files, folder: Path, readme: Path, csv_style=None):
    folder.mkdir(parents=True)
    if readme.exists():
        shutil.copy(readme, folder / 'README.md')
    for name, sheets in files.items():
        path = folder / name
        if path.suffix.lower() == '.csv':
            write_csv(path, sheets[0][1], **(csv_style or {}))
        else:
            write_xlsx(path, [(s or 'Sheet1', rows) for s, rows in sheets])


def text_of(v):
    if v is None:
        return ''
    if isinstance(v, dt.datetime):
        return v.strftime('%Y-%m-%d %H:%M:%S') if (v.hour, v.minute, v.second) != (0, 0, 0) else v.strftime('%Y-%m-%d')
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def write_csv(path, rows, delimiter=',', encoding='utf-8'):
    buf = io.StringIO()
    csv.writer(buf, delimiter=delimiter, lineterminator='\r\n').writerows([[text_of(v) for v in r] for r in rows])
    text = buf.getvalue()
    if encoding == 'cp1258':                     # Windows Vietnamese: precomposed vowels (â, ơ...) + a combining tone mark
        raw = ''.join(c if c.encode('cp1258', 'ignore') else cp1258_char(c) for c in text).encode('cp1258', errors='replace')
    else:
        raw = text.encode(encoding)
    path.write_bytes(raw)


def cp1258_char(c):
    tones = '\u0300\u0301\u0303\u0309\u0323'
    parts = unicodedata.normalize('NFD', c)
    tone = ''.join(x for x in parts if x in tones)
    base = unicodedata.normalize('NFC', ''.join(x for x in parts if x not in tones))
    return base + tone


# ---------------------------------------------------------------- variants (rows -> rows, per sheet)
def header_index(rows):
    return grids.find_header(rows, False)[0]


def is_date(v):
    return isinstance(v, (dt.date, dt.datetime)) or (isinstance(v, str) and parse_datetime(v, None, serial_ok=False) is not None)


def as_dt(v):
    return v if isinstance(v, dt.datetime) else parse_datetime(v, None, serial_ok=False)


def map_cells(rows, fn, numbers=False, dates=False):
    """Apply fn to the data cells below the header that are numbers (not dates, nor Excel serials under a date header)
    or dates."""
    h = header_index(rows)
    out = [list(r) for r in rows]
    serial = {j for j, v in enumerate(rows[h]) if v is not None and columns.DATE_HEADER.search(fold(str(v)))}
    for r in out[h + 1:]:
        for j, v in enumerate(r):
            if j in serial and not dates:
                continue
            if dates and is_date(v):
                r[j] = fn(as_dt(v))
            elif numbers and not isinstance(v, bool) and not is_date(v) and isinstance(v, (int, float)):
                r[j] = fn(v)
    return out


def numeric_columns(rows, h):
    body = [r for r in rows[h + 1:] if any(v is not None for v in r)]
    out = []
    for j in range(len(rows[h])):
        vals = [r[j] for r in body if r[j] is not None]
        if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) or (isinstance(v, str) and parse_number(v) is not None and not is_date(v))
                        for v in vals):
            out.append(j)
    return out


def total_row(rows, label, at_top=False):
    h = header_index(rows)
    cols = numeric_columns(rows, h)
    body = [rows[i] for i in layout.body_rows(rows, h)[0]]          # the records only (existing totals left out)
    if not cols or len(body) < 2:
        return rows
    tot = [None] * len(rows[h])
    for j in cols:
        s = sum(parse_number(r[j]) or 0 for r in body if r[j] is not None)
        tot[j] = int(s) if float(s).is_integer() else round(s, 6)
    free = next((j for j in range(len(tot)) if j not in cols), None)
    if free is None:
        return rows
    tot[free] = label or None
    return rows[:h + 1] + [tot] + rows[h + 1:] if at_top else rows + [tot]


def vn_number(v):          # 1.234.567 / 1.234,5
    s = f'{v:,.6f}'.rstrip('0').rstrip('.') if isinstance(v, float) and not v.is_integer() else f'{int(v):,}'
    return s.replace(',', '_').replace('.', ',').replace('_', '.')


def en_number(v):          # 1,234,567 / 1,234.5
    return f'{v:,.6f}'.rstrip('0').rstrip('.') if isinstance(v, float) and not v.is_integer() else f'{int(v):,}'


def page_breaks(rows, every=40):
    h = header_index(rows)
    out = rows[:h + 1]
    for k, r in enumerate(rows[h + 1:], 1):
        out.append(r)
        if k % every == 0:
            out += [[None] * len(r), list(rows[h])]
    return out


def title_rows(rows):
    w = len(rows[0]) if rows else 1
    pad = lambda *cells: list(cells) + [None] * (w - len(cells))
    return [pad('BÁO CÁO CHI TIẾT BÁN HÀNG'), pad('Từ ngày 01/01/2025 đến ngày 31/12/2025'), pad()] + rows


def title_rows_wide(rows):
    w = len(rows[0]) if rows else 1
    pad = lambda *cells: (list(cells) + [None] * w)[:max(w, len(cells))]
    return [pad('Kỳ báo cáo:', 'Năm 2025', None, 'Đơn vị tính:', 'VNĐ'), pad()] + rows


def footer(rows):
    w = len(rows[0]) if rows else 1
    sign = [None] * max(w, 4)
    sign[0], sign[min(3, w - 1)] = 'Người lập biểu', 'Kế toán trưởng'
    return rows + [[None] * w, sign[:max(w, 4)], [None] * w, ['(Ký, họ tên)'] + [None] * (w - 1)]


def shift(rows):
    return [[None]] * 2 + [[None] + list(r) for r in rows]


def accentless_header(rows):
    h = header_index(rows)
    out = [list(r) for r in rows]
    out[h] = [v if v is None else unicodedata.normalize('NFD', str(v).replace('Đ', 'D').replace('đ', 'd'))
              .encode('ascii', 'ignore').decode().upper() for v in out[h]]
    return out


DATE_FORMATS = {
    'dates_dd/mm/yyyy': lambda d: d.strftime('%d/%m/%Y'),
    'dates_d/m/yyyy': lambda d: f'{d.day}/{d.month}/{d.year}',
    'dates_dd-mm-yyyy': lambda d: d.strftime('%d-%m-%Y'),
    'dates_dd/mm/yy': lambda d: d.strftime('%d/%m/%y'),
    'dates_mm/dd/yyyy (US)': lambda d: d.strftime('%m/%d/%Y'),
    'dates_text_with_time': lambda d: d.strftime('%d/%m/%Y %H:%M:%S'),
    'dates_excel_serial_number': lambda d: round((d - dt.datetime(1899, 12, 30)).total_seconds() / 86400, 6),
}

def with_time(fmt):
    """Date text in `fmt`, plus the time of day when the cell has one (nothing is lost)."""
    return lambda d: fmt(d) + (d.strftime(' %H:%M:%S') if (d.hour, d.minute, d.second) != (0, 0, 0) and '%H' not in fmt.__code__.co_consts.__repr__() else '')


SHEET_VARIANTS = {
    'identity': lambda rows: rows,
    'title_rows': title_rows,
    'title_rows_wide': title_rows_wide,
    'footer_signatures': footer,
    'page_breaks': page_breaks,
    'shift_right_down': shift,
    'header_accentless_upper': accentless_header,
    'numbers_vn_text': lambda rows: map_cells(rows, vn_number, numbers=True),
    'numbers_en_text': lambda rows: map_cells(rows, en_number, numbers=True),
    'numbers_vnd_suffix': lambda rows: map_cells(rows, lambda v: vn_number(v) + ' đ', numbers=True),
    **{k: (lambda f: lambda rows: map_cells(rows, f, dates=True))(f if 'serial' in k else with_time(f)) for k, f in DATE_FORMATS.items()},
    **{f'total_{lab or "unlabeled"}': (lambda lab: lambda rows: total_row(rows, lab))(lab)
       for lab in ('Tổng cộng', 'TỔNG CỘNG', 'Tong cong', 'Cộng', 'Total', 'Grand Total', 'Sum', 'Tổng số', '')},
    'total_at_top': lambda rows: total_row(rows, 'Tổng cộng', at_top=True),
}
FILE_VARIANTS = ('csv_semicolon_utf8sig', 'csv_utf16', 'csv_cp1258', 'csv_tab', 'xlsx_to_csv', 'csv_to_xlsx', 'monthly_sheets')


def apply(files, variant):
    """(files, csv_style) for a variant."""
    if variant in SHEET_VARIANTS:
        fn = SHEET_VARIANTS[variant]
        return {n: [(s, fn(rows)) for s, rows in sh] for n, sh in files.items()}, None
    if variant.startswith('csv_') and variant != 'csv_to_xlsx':
        style = {'csv_semicolon_utf8sig': dict(delimiter=';', encoding='utf-8-sig'), 'csv_utf16': dict(encoding='utf-16'),
                 'csv_cp1258': dict(encoding='cp1258'), 'csv_tab': dict(delimiter='\t')}[variant]
        return files, style
    if variant == 'xlsx_to_csv':
        return {(n if len(sh) == 1 else f'{Path(n).stem}_{s}.xlsx').rsplit('.', 1)[0] + '.csv' if not n.endswith('.csv') else n:
                [(None, rows)] for n, sh in files.items() for s, rows in sh}, None
    if variant == 'csv_to_xlsx':
        return {(n[:-4] + '.xlsx' if n.endswith('.csv') else n): sh for n, sh in files.items()}, None
    if variant == 'monthly_sheets':
        return {n: monthly(n, sh) for n, sh in files.items()}, None
    raise KeyError(variant)


def monthly(name, sheets):
    """A sheet with a date column split into one sheet per month ('T1-2025'); CSV stays whole."""
    if name.endswith('.csv') or len(sheets) != 1:
        return sheets
    rows = sheets[0][1]
    h = header_index(rows)
    body = rows[h + 1:]
    col = next((j for j in range(len(rows[h])) if sum(is_date(r[j]) for r in body) >= 0.9 * max(1, len(body))), None)
    if col is None or len(body) < 10:
        return sheets
    parts = defaultdict(list)
    for r in body:
        d = as_dt(r[col]) if is_date(r[col]) else None
        parts[f'T{d.month}-{d.year}' if d else 'Khac'].append(r)
    return [(k, rows[:h + 1] + v) for k, v in parts.items()]


# ---------------------------------------------------------------- compare
def canon(v):
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 6)
    return re.sub(r'\s+', ' ', str(v)).strip()


def tables_of(folder):
    out = {}
    for name, frame, _ in data.build_tables(folder):
        cols = {fold(c): c for c in frame.columns if not str(c).endswith(INTERNAL) and not re.fullmatch(r'col_\d+', str(c))}
        out[name] = (frame, cols)
    return out


def compare(base, other):
    """Counter of differences between two {table: (frame, cols)}."""
    c, examples = Counter(), []
    for name, (fa, ca) in base.items():
        if name not in other:
            # a renamed table (monthly sheets, csv split): match by the same folded columns
            cand = [n for n, (_, cb) in other.items() if set(cb) == set(ca)]
            if len(cand) != 1:
                c['tables_missing'] += 1
                examples.append(f'missing table {name}')
                continue
            fb, cb = other[cand[0]]
        else:
            fb, cb = other[name]
        common = [k for k in ca if k in cb]
        if len(common) < len(ca):
            c['columns_missing'] += len(ca) - len(common)
            examples.append(f'{name}: columns missing {[ca[k] for k in ca if k not in cb][:4]}')
        for k in common:
            ka, kb = str(fa[ca[k]].dtype), str(fb[cb[k]].dtype)
            if kind(ka) != kind(kb):
                c['columns_type_changed'] += 1
                examples.append(f'{name}.{ca[k]}: {ka} -> {kb}')
        ra = sorted(map(repr, zip(*[fa[ca[k]].map(canon) for k in common]))) if common else []
        rb = sorted(map(repr, zip(*[fb[cb[k]].map(canon) for k in common]))) if common else []
        if len(ra) != len(rb):
            c['tables_row_count_changed'] += 1
            examples.append(f'{name}: rows {len(ra)} -> {len(rb)}')
        diff = Counter(ra) - Counter(rb)
        if diff:
            c['tables_with_changed_rows'] += 1
            c['rows_changed'] += sum(diff.values())
            if len(ra) == len(rb):
                a = next(iter(diff))
                b = next(iter(Counter(rb) - Counter(ra)), None)
                examples.append(f'{name}: {a[:220]}\n      -> {(b or "")[:220]}')
        c['tables_compared'] += 1
    return c, examples


def kind(dtype):
    return 'num' if dtype.startswith(('int', 'float')) else 'date' if dtype.startswith('datetime') else 'bool' if dtype == 'bool' else 'text'


# ---------------------------------------------------------------- run
def run_business(args):
    folder, variants = args
    files = read_files(folder)
    if not files:
        return folder.name, {}
    tmp = Path(tempfile.mkdtemp(prefix='variants_'))
    try:
        write_files(apply(files, 'identity')[0], tmp / 'identity', folder / 'README.md')
        base = tables_of(tmp / 'identity')
        out = {}
        for v in variants:
            try:
                vf, style = apply(files, v)
                write_files(vf, tmp / v.replace('/', '_'), folder / 'README.md', style)
                out[v] = compare(base, tables_of(tmp / v.replace('/', '_')))
            except Exception as exc:                      # a variant that crashes the reader is a finding too
                out[v] = (Counter({'reader_crash': 1}), [f'{type(exc).__name__}: {exc}'[:300]])
        return folder.name, out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--variants', default='')
    ap.add_argument('--examples', type=int, default=2)
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    variants = [v for v in [*SHEET_VARIANTS, *FILE_VARIANTS] if v != 'identity'] if not a.variants else a.variants.split(',')
    shops = [f for f in sorted(TRAIN.iterdir()) if f.is_dir() and (not a.only or f.name in a.only.split(','))]
    total, shops_hit, examples = defaultdict(Counter), defaultdict(set), defaultdict(list)
    with ProcessPoolExecutor(a.workers) as pool:
        for shop, res in pool.map(run_business, [(f, variants) for f in shops]):
            for v, (c, ex) in res.items():
                total[v].update(c)
                if any(k != 'tables_compared' for k in c):
                    shops_hit[v].add(shop)
                    examples[v] += [f'{shop} {e}' for e in ex[:a.examples]]
    print(f'{"variant":34}{"shops":>6}{"tables":>7}{"miss":>6}{"type":>6}{"nrows":>6}{"tbl≠":>6}{"rows≠":>8}{"crash":>6}')
    for v in variants:
        c = total[v]
        print(f'{v:34}{len(shops_hit[v]):>6}{c["tables_compared"]:>7}{c["tables_missing"]:>6}{c["columns_type_changed"]:>6}'
              f'{c["tables_row_count_changed"]:>6}{c["tables_with_changed_rows"]:>6}{c["rows_changed"]:>8}{c["reader_crash"]:>6}')
    if a.examples:
        for v in variants:
            for e in examples[v][:a.examples * 3]:
                print(f'[{v}] {e}')


if __name__ == '__main__':
    main()
