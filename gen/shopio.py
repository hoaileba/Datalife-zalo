"""Read a shop's data files as raw cell grids and write them back in the same format (CSV dialect and BOM, XLSX
sheets, SQLite tables with their declared types), so a rewrite that changes only names reads back to the same values.

    files = read_shop(folder)            # {file name: ShopFile}
    write_shop(files, out_folder)        # same formats; README.md is not touched (the caller writes it)

Cells: CSV cells are the raw text (no stripping), XLSX cells are what python-calamine returns (str, float, int, bool,
date, datetime; empty -> ''), SQLite cells are the stored Python values. Used by gen.reskin; checked there by
reading both folders with datamate.data.load_business and comparing every table.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from datamate.grids import decode_text

from .xlsx import write_xlsx

DATA_SUFFIXES = {'.csv', '.tsv', '.xlsx', '.xlsm', '.sqlite', '.db', '.sqlite3'}


@dataclass
class Sheet:
    name: str | None                 # XLSX sheet / SQLite table; None for CSV
    rows: list                       # list of lists of cells; SQLite: rows without the header
    columns: list | None = None      # SQLite: column names
    types: list | None = None        # SQLite: declared column types


@dataclass
class ShopFile:
    name: str
    kind: str                        # csv | xlsx | sqlite
    sheets: list = field(default_factory=list)
    csv: dict = field(default_factory=dict)      # delimiter, quotechar, lineterminator, bom


def _read_csv(path: Path) -> ShopFile:
    raw = path.read_bytes()
    text = decode_text(raw)
    if text.count('\n') > len(re.findall(r'\r(?!\n)', text)):      # as datamate.grids.read_csv
        text = re.sub(r'\r(?!\n)', ' ', text)
    try:
        dialect = csv.Sniffer().sniff(text[:20000], delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    rows = [list(r) for r in csv.reader(io.StringIO(text, newline=''), dialect)]
    head = text[:20000]
    style = {'delimiter': dialect.delimiter, 'quotechar': dialect.quotechar or '"',
             'lineterminator': '\r\n' if '\r\n' in head else '\n', 'bom': raw.startswith(b'\xef\xbb\xbf')}
    return ShopFile(path.name, 'csv', [Sheet(None, rows)], style)


def _read_xlsx(path: Path) -> ShopFile:
    from python_calamine import CalamineWorkbook
    book = CalamineWorkbook.from_path(str(path))
    sheets = [Sheet(s, [list(r) for r in book.get_sheet_by_name(s).to_python(skip_empty_area=False)]) for s in book.sheet_names]
    return ShopFile(path.name, 'xlsx', sheets)


def _read_sqlite(path: Path) -> ShopFile:
    out = ShopFile(path.name, 'sqlite')
    with sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True) as con:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid")]
        for name in names:
            q = '"' + name.replace('"', '""') + '"'
            info = con.execute(f'PRAGMA table_info({q})').fetchall()
            rows = [list(r) for r in con.execute(f'SELECT * FROM {q} ORDER BY rowid')]
            out.sheets.append(Sheet(name, rows, [c[1] for c in info], [c[2] for c in info]))
        if con.execute("SELECT count(*) FROM sqlite_master WHERE type='view'").fetchone()[0]:
            raise ValueError(f'{path.name}: SQLite views are not rewritten')
    return out


def read_shop(folder: Path) -> dict:
    """{file name: ShopFile} for every data file of the shop (README and other files are not data)."""
    out = {}
    for f in sorted(Path(folder).iterdir()):
        if not f.is_file() or f.name.startswith(('~$', '.')):
            continue
        suffix = f.suffix.lower()
        if suffix in ('.csv', '.tsv'):
            out[f.name] = _read_csv(f)
        elif suffix in ('.xlsx', '.xlsm'):
            out[f.name] = _read_xlsx(f)
        elif suffix in ('.sqlite', '.db', '.sqlite3'):
            out[f.name] = _read_sqlite(f)
    return out


def _csv_text(v):
    return '' if v is None else str(v)


def write_file(sf: ShopFile, path: Path):
    if sf.kind == 'csv':
        buf = io.StringIO()
        st = sf.csv
        csv.writer(buf, delimiter=st['delimiter'], quotechar=st['quotechar'], lineterminator=st['lineterminator'],
                   quoting=csv.QUOTE_MINIMAL).writerows([[_csv_text(v) for v in r] for r in sf.sheets[0].rows])
        path.write_bytes((b'\xef\xbb\xbf' if st['bom'] else b'') + buf.getvalue().encode('utf-8'))
    elif sf.kind == 'xlsx':
        names = write_xlsx(path, [(s.name, [[None if v == '' else _xlsx_cell(v) for v in r] for r in s.rows]) for s in sf.sheets])
        if names != [s.name for s in sf.sheets]:
            raise ValueError(f'{sf.name}: sheet names changed by the writer: {names}')
    elif sf.kind == 'sqlite':
        if path.exists():
            path.unlink()
        with sqlite3.connect(path) as con:
            for s in sf.sheets:
                q = '"' + s.name.replace('"', '""') + '"'
                cols = ', '.join('"' + c.replace('"', '""') + '"' + (f' {t}' if t else '') for c, t in zip(s.columns, s.types))
                con.execute(f'CREATE TABLE {q} ({cols})')
                if s.rows:
                    con.executemany(f'INSERT INTO {q} VALUES ({", ".join("?" * len(s.columns))})', s.rows)
            con.commit()
    else:
        raise ValueError(sf.kind)


def _xlsx_cell(v):
    if isinstance(v, dt.time):                   # a time-only cell: Excel keeps it as a fraction of a day
        raise ValueError('time-only XLSX cells are not supported')
    if isinstance(v, dt.timedelta):
        raise ValueError('duration XLSX cells are not supported')
    return v


def write_shop(files: dict, folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    for sf in files.values():
        write_file(sf, folder / sf.name)
