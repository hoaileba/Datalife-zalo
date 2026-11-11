"""How often each data-changing reader rule fires on a split: aggregate counts only (safe on public_test).

    PYTHONPATH=src python scripts/robust/audit.py data/train [data/public_test]

Counts per split: header not on the first row, two-row and group headers, text above the header, dropped rows by
kind (totals by label / by arithmetic, notes, footers, sections), column kinds, cells that did not parse, date columns typed from Excel
serials or from the header word alone, d/m dates with no day > 12 (order unproven) or with a second part > 12 (m/d
order), number columns mixing "1.234" (read as thousands) with decimals, leading-zero codes, partitions merged,
fill-down. Nothing per shop or per value is printed.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from datamate import columns as data, grids, layout
from datamate.data import build_tables
from datamate.values import fold, parse_number

DM = re.compile(r'\s*(\d{1,2})[/\-.](\d{1,2})(?:[/\-.]\d{2,4})?(?:[ ,].*)?')
THOUSANDS = re.compile(r'[+-]?\d{1,3}[.,]\d{3}')                # one separator, 3 digits after: read as thousands
DECIMAL = re.compile(r'[+-]?\d+[.,]\d{1,2}|[+-]?\d+[.,]\d{4,}')  # one separator, not 3 digits after: a decimal


def audit_grid(g, c: Counter):
    rows = g.rows
    h, group = grids.find_header(rows, g.is_sql)
    merged = None if g.is_sql else layout.sub_header(rows, h)
    c['grids'] += 1
    c['grids_header_below_row_1'] += h > 0
    c['grids_two_row_header'] += merged is not None
    c['grids_with_group_header'] += group is not None
    c['grids_with_text_above_header'] += bool(layout.title_lines(rows, h, group))
    body, dropped, extra = layout.body_rows(rows, h + (merged is not None), g.is_sql)
    for k, n in dropped.items():
        c[f'dropped_{k}'] += n
    c['rows_given_a_section'] += len(extra['section'])
    return h, group, body


def audit_column(raw, sources, label, c: Counter):
    kind, values, _ = data.type_column(raw, sources, label)
    present = [v for v in raw if v is not None]
    c[f'columns_{kind}'] += 1
    if not present:
        return
    texts = [v for v in present if isinstance(v, str)]
    if kind in ('number', 'quantity', 'date'):
        unparsed = sum(o is not None and p is None for o, p in zip(raw, values))
        c['cells_unparsed_blank'] += unparsed
        c['columns_with_unparsed_cells'] += unparsed > 0
    if kind == 'text' and any(isinstance(v, str) and data.LEADING_ZERO.fullmatch(v.strip()) for v in present):
        c['columns_text_by_leading_zero'] += 1
        if sum(parse_number(v) is not None for v in present) == len(present):
            c['columns_text_by_leading_zero_all_numeric'] += 1
    if kind == 'date':
        nums = sum(isinstance(v, (int, float)) and not isinstance(v, bool) for v in present)
        if nums:
            c['date_columns_from_serial_numbers'] += 1
        explicit = any(data._explicit_date(v) for v in present)
        if not explicit:
            c['date_columns_from_header_word_only'] += 1
        parts = [DM.fullmatch(v) for v in texts]
        parts = [(int(m[1]), int(m[2])) for m in parts if m]
        if parts:
            if any(b > 12 for _, b in parts):
                c['date_columns_second_part_over_12 (m/d order)'] += 1
            elif not any(a > 12 for a, _ in parts):
                c['date_columns_dm_order_unproven'] += 1
            else:
                c['date_columns_dm_order_proven'] += 1
        short = sum(bool(data.SHORT_DATE.fullmatch(v)) for v in texts)
        c['date_cells_without_year'] += short
    if kind == 'number' and texts:
        th = sum(bool(THOUSANDS.fullmatch(v.strip())) for v in texts)
        de = sum(bool(DECIMAL.fullmatch(v.strip())) for v in texts)
        if th and de:
            c['number_columns_mixing_1.234_and_decimals'] += 1
        elif th and th == len(texts) and all(re.fullmatch(r'[+-]?\d{1,3}[.,]\d{3}', v.strip()) for v in texts):
            c['number_columns_all_x.xxx (thousands or 3 decimals?)'] += 1


def audit_business(folder: Path, c: Counter):
    problems = []
    parsed = {}
    for g in grids.read_business(folder, problems):
        h, group, body = audit_grid(g, c)
        merged = None if g.is_sql else layout.sub_header(g.rows, h)
        parsed[g.src] = {'grid': g, 'labels': grids.labels_of(g.rows, h, group, merged), 'data': body}
    c['files_unreadable'] += len(problems)
    for srcs in layout.partition_groups(parsed):
        c['tables'] += 1
        c['tables_merged_from_partitions'] += len(srcs) > 1
        rows = [(s, i) for s in srcs for i in parsed[s]['data']]
        position = {s: grids.column_positions(parsed[srcs[0]]['labels'], parsed[s]['labels']) for s in srcs}
        for j, label in enumerate(parsed[srcs[0]]['labels']):
            raw = [parsed[s]['grid'].rows[i][position[s][j]] for s, i in rows]
            audit_column(raw, [s for s, _ in rows], label, c)
    for _, frame, meta in build_tables(folder):
        for note in meta['notes'].values():
            c['columns_filled_down'] += 'filled from the group' in note
            c['columns_decimal_mark_from_column'] += 'decimal mark' in note
            c['columns_dates_month_first'] += 'month/day/year' in note


def main(splits):
    out = {}
    for split in splits:
        c = Counter()
        for folder in sorted((Path(split) / 'data').iterdir()):
            if folder.is_dir():
                c['businesses'] += 1
                audit_business(folder, c)
        out[Path(split).name] = dict(sorted(c.items()))
    keys = sorted({k for v in out.values() for k in v})
    names = list(out)
    print(f'{"rule":58}' + ''.join(f'{n:>14}' for n in names))
    for k in keys:
        print(f'{k:58}' + ''.join(f'{out[n].get(k, 0):>14}' for n in names))
    return out


if __name__ == '__main__':
    json.dump(main(sys.argv[1:] or ['data/train']), open('/dev/null', 'w'))
