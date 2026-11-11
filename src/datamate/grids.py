"""Raw cell grids from CSV/XLSX/SQLite and the table layout inside a grid (header row, labels, table names).

In:  a business folder.  Out: `Grid`s (one per CSV file, XLSX sheet or SQLite table).
Format only, no business knowledge.
"""
from __future__ import annotations

import csv
import io
import re
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .values import fold, nfc, parse_datetime, parse_number

csv.field_size_limit(min(sys.maxsize, 2 ** 31 - 1))       # one huge cell must not fail the file


# ---------------------------------------------------------------- grids
@dataclass
class Grid:
    src: str            # 'file.csv', 'file.xlsx:Sheet', 'file.sqlite:table'
    rows: list
    is_sql: bool = False


def _clean(v):
    if isinstance(v, str):
        v = nfc(v)
        return None if v.strip() == '' else v
    if isinstance(v, float) and v != v:
        return None
    return v


def _pad(rows):
    width = max((len(r) for r in rows), default=0)
    return [list(r) + [None] * (width - len(r)) for r in rows]


_BOMS = ((b'\xef\xbb\xbf', 'utf-8-sig'), (b'\xff\xfe\x00\x00', 'utf-32'), (b'\x00\x00\xfe\xff', 'utf-32'),
         (b'\xff\xfe', 'utf-16'), (b'\xfe\xff', 'utf-16'))


def decode_text(raw: bytes) -> str:
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                break
    head = raw[:4096]
    if head and head.count(0) * 4 > len(head):          # BOM-less UTF-16
        enc = 'utf-16-le' if head[1::2].count(0) > head[0::2].count(0) else 'utf-16-be'
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    for enc in ('utf-8', 'cp1258'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1')


def read_csv(path: Path) -> list[Grid]:
    text = decode_text(path.read_bytes())
    if text.count('\n') > len(re.findall(r'\r(?!\n)', text)):      # LF line ends: a lone CR sits inside a field
        text = re.sub(r'\r(?!\n)', ' ', text)
    try:
        dialect = csv.Sniffer().sniff(text[:20000], delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    rows = [[_clean(v) for v in r] for r in csv.reader(io.StringIO(text, newline=''), dialect)]
    return [Grid(path.name, _pad(rows))]


def read_xlsx(path: Path) -> list[Grid]:
    from python_calamine import CalamineWorkbook
    book = CalamineWorkbook.from_path(str(path))
    return [Grid(f'{path.name}:{sheet}', _pad([[_clean(v) for v in r] for r in
                 book.get_sheet_by_name(sheet).to_python(skip_empty_area=False)]))
            for sheet in book.sheet_names]


def read_sqlite(path: Path, problems=None) -> list[Grid]:
    """Tables and views; one unreadable object is skipped (noted in `problems`). Read-only even for a WAL database
    on a read-only disk (immutable retry)."""
    try:
        return _read_sqlite(path, 'mode=ro', problems)
    except sqlite3.OperationalError:
        return _read_sqlite(path, 'mode=ro&immutable=1', problems)


def _read_sqlite(path, mode, problems):
    out = []
    with sqlite3.connect(f'file:{path.as_posix()}?{mode}', uri=True) as con:
        objects = con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
                              "AND name NOT LIKE 'sqlite_%'").fetchall()
        for name, kind in objects:
            quoted = '"' + name.replace('"', '""') + '"'
            try:
                try:
                    cur = con.execute(f'SELECT * FROM {quoted}' + (' ORDER BY rowid' if kind == 'table' else ''))
                except sqlite3.DatabaseError:
                    cur = con.execute(f'SELECT * FROM {quoted}')                  # WITHOUT ROWID, virtual tables
                head = [d[0] for d in cur.description]
                out.append(Grid(f'{path.name}:{name}', _pad([head] + [[_clean(v) for v in r] for r in cur.fetchall()]), True))
            except sqlite3.DatabaseError as exc:
                if problems is not None:
                    problems.append(f'{path.name}:{name}: {type(exc).__name__}: {exc}'[:300])
    return out


READERS = {'.csv': read_csv, '.tsv': read_csv, '.xlsx': read_xlsx, '.xlsm': read_xlsx, '.xls': read_xlsx,
           '.xlsb': read_xlsx, '.ods': read_xlsx, '.sqlite': read_sqlite, '.db': read_sqlite, '.sqlite3': read_sqlite}


def read_business(folder: Path, problems=None) -> list[Grid]:
    """Grids of every data file. A file that fails to read is skipped and noted in `problems`, never fatal; editor
    leftovers (~$x.xlsx, ._x.csv, hidden files) are ignored; other files (README, unknown types) are listed."""
    out = []
    for f in sorted(Path(folder).iterdir()):
        if f.name.startswith(('~$', '.')) or f.name.endswith(('-wal', '-shm', '-journal')):
            continue
        if not f.is_file():
            if problems is not None:
                problems.append(f'{f.name}/: subfolder not read')
            continue
        reader = READERS.get(f.suffix.lower())
        if reader is None:
            if f.name.lower() != 'readme.md' and problems is not None:
                problems.append(f'{f.name}: not read (unsupported file type)')
            continue
        try:
            out += [g for g in (reader(f, problems) if reader is read_sqlite else reader(f)) if g.rows]
        except Exception as exc:                                       # corrupt, encrypted, not really that type
            if problems is not None:
                problems.append(f'{f.name}: unreadable, {type(exc).__name__}: {exc}'[:300])
    return out


# ---------------------------------------------------------------- layout
# A total label starts with "tổng"/"cộng" (accents kept: "Công tắc", the surname "Tống" are not totals) or "total",
# or is just "TC". Without accents on the keyword ("Tong cong", "Tong cong (VNĐ)") the folded keyword decides when the
# label has no accent at all, or when the next word is a total word.
TOTAL_RE = re.compile(r'^(tổng|cộng|total)\b|^tc:?$')
TOTAL_NEXT = re.compile(r'^(tong|cong) (cong|so|tien|doanh|thu|ngay|thang|nam|quy|tuan|ky|ca|chung|luy)\b')
MONTHS = 'jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|' \
         'nov|november|dec|december'
_PERIOD = rf'(t|th|thang|month|q|quy|nam|year)\s*\d{{1,4}}|({MONTHS})\s*\d{{2,4}}'
# Trailing period tokens of a folded name: "ban hang t10 2025", "so ban hang 1", "ban hang thang01 2026", "doanh thu q1",
# "ban hang jan2025", "bao cao thang 10 nam 2025". Bare trailing digits always go ("top10" -> "top"); a month name only
# with digits ("dien may" stays).
PARTITION_SUFFIX = re.compile(rf'(\s*(\d{{1,2}}|20\d{{2}})|(^|\s)({_PERIOD}))+$')
GENERIC_SHEET = re.compile(r'(sheet|trang tinh|data)\s*\d*|(thang|t)\s*\d{1,2}([ _\-/.]\d{2,4})?|\d{1,2}[ _\-/.]\d{2,4}|'
                           r'\d{4}|nam \d{4}')


def is_total_label(v) -> bool:
    if not isinstance(v, str) or parse_number(v) is not None:
        return False
    label = nfc(v).strip().lower()
    if TOTAL_RE.match(label):
        return True
    head = label.split(' ', 1)[0]
    # no accent on the keyword: a total word must follow ("Tong cong"), or the label is the keyword alone; "Tong Ngoc
    # Chi" is the surname Tống
    return head.isascii() and bool(TOTAL_NEXT.match(fold(label)) or fold(label) in ('tong', 'cong'))


def period_free(name: str) -> str:
    """Folded name without trailing period tokens ('' if the name is only a period)."""
    return PARTITION_SUFFIX.sub('', fold(name)).strip()


def partition_stem(src: str) -> str:
    """Folded file stem without period tokens: the files of one split table share it."""
    return period_free(re.sub(r'\.[A-Za-z0-9]+$', '', src.split(':', 1)[0]))


def _texty(v) -> bool:
    return isinstance(v, str) and parse_number(v) is None


def find_header(rows, is_sql):
    """(header row, group header row above it or None): among the first 20 rows that are mostly text and fill most
    columns, the one whose labels stand over the most columns that the rows below it fill (a wide title row such as
    "Kỳ báo cáo: | Năm 2025 | | Đơn vị tính: | VNĐ" puts cells over empty columns); the first on a tie."""
    if is_sql or not rows:
        return 0, None
    width = max((sum(v is not None for v in r) for r in rows[:300]), default=0)
    best, score = None, -1
    for i, r in enumerate(rows[:20]):
        cells = [v for v in r if v is not None]
        if len(cells) >= max(2, 0.6 * width) and sum(_texty(v) for v in cells) >= 0.8 * len(cells):
            below = [x for x in rows[i + 1:i + 41] if any(v is not None for v in x)]
            fit = sum(sum(j < len(x) and x[j] is not None for x in below) * 2 >= len(below) for j, v in enumerate(r) if v is not None)
            best, score = (i, fit) if fit > score else (best, score)
    if best is None:
        return 0, None
    above = [j for j, v in enumerate(rows[best - 1]) if v is not None] if best else []
    cells = sum(v is not None for v in rows[best])
    return best, (best - 1 if 2 <= len(above) < cells and (above[-1] - above[0]) >= len(above) else None)


def labels_of(rows, h, group, merged=None):
    """Column labels; a repeated label is prefixed by its group header (or numbered). merged: sub_header labels."""
    if merged is not None:
        rows, h, group = [merged], 0, None
    groups, current = [], None
    for v in (rows[group] if group is not None else [None] * len(rows[h])):
        current = v if v is not None else current
        groups.append(current)
    out, seen = [], Counter()
    for j, v in enumerate(rows[h]):
        label = re.sub(r'\s+', ' ', nfc(str(v))).strip() if v is not None else f'col_{j}'
        seen[label] += 1
        if seen[label] > 1:
            label = f'{nfc(str(groups[j]))} / {label}' if groups[j] is not None else f'{label}_{seen[label]}'
        out.append(label)
    return out


def column_positions(base, labels):
    """For each label of `base`, its column in `labels` (same folded labels, maybe reordered): the same exact label
    first, then the next unused column with the same folded label, so "Giá" and "GIÁ" in one header keep their own."""
    free = list(range(len(labels)))
    out = [None] * len(base)
    for same in (lambda a, b: a == b, lambda a, b: fold(a) == fold(b)):
        for k, x in enumerate(base):
            j = None if out[k] is not None else next((j for j in free if same(labels[j], x)), None)
            if j is not None:
                out[k] = j
                free.remove(j)
    return out


def same_as_header(row, header_folded) -> bool:
    return len(row) == len(header_folded) and all((fold(v) if v is not None else '') == h
                                                  for v, h in zip(row, header_folded))


def table_name(src: str, multi_sheet: bool) -> str:
    file, _, sheet = src.partition(':')
    stem = partition_stem(src)
    named_sheet = sheet and not GENERIC_SHEET.fullmatch(fold(sheet))
    if named_sheet and (multi_sheet or not stem or file.lower().endswith(('.sqlite', '.db', '.sqlite3'))):
        stem = sheet                                     # files named only by period ("T1.xlsx"): the sheet names the table
    return re.sub(r'\W+', '_', fold(stem)).strip('_') or 'data'
