"""Rows of one grid around its header (data or layout, the text above it), its sources and its groups.

In:  grid rows and the header row (grids.find_header).  Out: `body_rows` (data rows, dropped kinds and examples,
sections), `sub_header`, `title_lines`, `partition_groups`, `fill_groups`, `run_totals`.
Layout rows: blank, repeated header, totals (a total label with numbers, or arithmetic: totals.py), notes after the
data, footers (text in a number/date column after the data), section heads (shaped unlike their column). Content
and arithmetic decide, not the words a shop uses: "Sum", "Grand total" or no label at all is still a total.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter, defaultdict

import pandas as pd

from .grids import GENERIC_SHEET, is_total_label, partition_stem, period_free, same_as_header
from .totals import group_totals, move_totals, recurring_totals, sum_totals, typical_fill
from .values import fold, nfc, parse_datetime, parse_number, shape

EXAMPLES, FOOTER_ROWS = 3, 6      # examples kept per dropped kind (shown to the model); rows of a footer at most
GROUP_TOTAL = '__group_total'
SEPARATORS = ('blank', 'total', 'total_by_sum')      # rows that set a footer or notes apart from the data


def _num(v):
    return None if isinstance(v, bool) else parse_number(v)


def _texty(v):
    return isinstance(v, str) and parse_number(v) is None


def _word(v):
    """Text that is neither a number nor a date."""
    return _texty(v) and parse_datetime(v, None, serial_ok=False) is None


def _show(row):
    return ' | '.join(nfc(str(v)).strip() for v in row if v is not None)[:100]


def title_lines(rows, h, group=None):
    """Non-empty rows above the header (the group header row excepted), each as 'cell | cell'."""
    return [_show(r) for k, r in enumerate(rows[:h]) if k != group and any(v is not None for v in r)]


def body_rows(rows, h, is_sql=False):
    """(data row indexes, Counter of dropped kinds, {'examples': {kind: [row text]}, 'section': {data row: text}}).
    One-cell text rows: after the data and set apart by a blank or total row they are notes; when one comes before the first data row they head
    sections ("Nhóm: Bia") and their text goes to the rows below them; otherwise they are records with blank cells
    (a supplier known by name only) and stay. SQL tables keep every row."""
    if is_sql:
        return list(range(h + 1, len(rows))), Counter(), {'examples': {}, 'section': {}}
    header = [fold(v) if v is not None else '' for v in rows[h]]
    width = max(1, sum(v is not None for v in rows[h]))
    typical = typical_fill(rows, [i for i in range(h + 1, len(rows)) if sum(v is not None for v in rows[i]) > 1])
    data, kinds, labelled, single = [], {}, set(), []
    for i in range(h + 1, len(rows)):
        cells = [v for v in rows[i] if v is not None]
        if not cells:
            kinds[i] = 'blank'
        elif same_as_header(rows[i], header):
            kinds[i] = 'repeated_header'
        elif (len(total := [v for v in cells if is_total_label(v)]) == 1
              and all(parse_number(v) is not None for v in cells if v is not total[0])):
            if len(cells) < typical:
                kinds[i] = 'total'
            else:                               # a full row: a total only if its numbers are sums ("Tổng hợp hải sản")
                labelled.add(i)
                data.append(i)
        elif len(cells) == 1 and _texty(cells[0]) and width >= 3:
            single.append(i)
        else:
            data.append(i)
    for i in recurring_totals(rows, data):
        kinds[i] = 'total'
    data = [i for i in data if i not in kinds]
    for i in sum_totals(rows, data, [i for i, k in kinds.items() if k == 'total'], labelled):
        kinds[i] = 'total' if i in labelled else 'total_by_sum'
    for i in footer(rows, sorted(set(data) | set(single)), kinds):
        kinds[i] = 'note' if i in single else 'footer'
    data = [i for i in data if i not in kinds]
    section = sections(rows, data, [i for i in single if i not in kinds], kinds)
    data = sorted(set(data) | {i for i in single if i not in kinds})
    dropped, examples = Counter(kinds.values()), {}
    for i, k in sorted(kinds.items()):
        if k not in ('blank', 'repeated_header') and len(examples.setdefault(k, [])) < EXAMPLES \
                and (text := _show(rows[i])) not in examples[k]:
            examples[k].append(text)
    return data, dropped, {'examples': examples, 'section': section}


def sections(rows, data, single, kinds):
    """One-cell rows: notes after the last data row when a blank or total row sets them apart; section heads when one
    precedes the first data row and their text is shaped unlike the values of its column ("Nhóm: Bia" over codes
    "BI001"; a supplier name among supplier names is a record) ({data row: text of its section}); the others are
    left as data. Kinds are set in place."""
    after = [i for i in single if not data or i > data[-1]]
    if after and (not data or kinds.get(after[0] - 1) in SEPARATORS):      # set apart from the data: notes
        for i in after:
            kinds[i] = 'note'
    heads = [i for i in single if i not in kinds and _odd_cells(rows, i, data)]          # its one cell is odd
    if not heads or heads[0] > data[0]:
        return {}
    out, current = {}, None
    for i in range(heads[0], data[-1] + 1):
        if i in heads:
            current = _show(rows[i])
            kinds[i] = 'section'
        elif current is not None and i not in kinds:
            out[i] = current
    return out


def _odd_cells(rows, i, data, rare=0.1):
    """Cells of row i whose shape under `rare` of the data rows have in that column."""
    sample = data[:: max(1, len(data) // 500)]
    return [j for j, v in enumerate(rows[i]) if v is not None and sum(
        j < len(rows[r]) and rows[r][j] is not None and shape(rows[r][j]) == shape(v) for r in sample) < rare * max(1, len(sample))]


def footer(rows, candidates, kinds):
    """The last rows when they form a short block of text-only rows after a blank or total row, in a table whose
    records hold numbers, dates or bools, each row of the block made of odd cells (text in a column of numbers, dates
    or bools, such as "Thủ quỹ" under the quantity, or a shape rare in its column): at least half of them, more than
    half when the row fills every column all records fill. Items with no price yet, or priced "Liên hệ", stay."""
    rest = [i for i in candidates if i not in kinds]
    records = [i for i in rest if any(v is not None and not _word(v) for v in rows[i]) and sum(v is not None for v in rows[i]) > 1]
    if not records:
        return []
    sample = records[:: max(1, len(records) // 500)]
    width = max(len(rows[r]) for r in sample)
    filled = lambda j: sum(j < len(rows[r]) and rows[r][j] is not None for r in sample)
    typed = lambda j: sum(j < len(rows[r]) and rows[r][j] is not None and not _word(rows[r][j]) for r in sample) >= 0.9 * len(sample)
    always = [j for j in range(width) if filled(j) == len(sample)]
    cells = lambda i: sum(v is not None for v in rows[i])
    odd = lambda i: len({j for j, v in enumerate(rows[i]) if _word(v) and typed(j)} | set(_odd_cells(rows, i, sample)))
    full = lambda i: all(j < len(rows[i]) and rows[i][j] is not None for j in always)
    tail = []
    for i in reversed(rest):
        if len(tail) == FOOTER_ROWS or not all(_texty(v) for v in rows[i] if v is not None) \
                or (2 * odd(i) <= cells(i) if full(i) else 2 * odd(i) < cells(i)):
            break
        tail.append(i)
    if not tail or len(tail) == len(rest) or kinds.get(min(tail) - 1) not in SEPARATORS:
        return []
    return tail


def sub_header(rows, h):
    """Labels of a two-row header, or None: the row under the header is all text, puts a label under at least one
    blank header cell (a merged group such as "Bán" over "Số lượng | Tiền"), is followed by numbers or dates, and is
    no first record: most of its cells are shaped unlike their column and none recurs in it ("KH001 | Anh Minh | Sỉ"). A column with both rows
    set is "upper / lower"; a blank upper cell takes the merged label on its left."""
    if h + 2 >= len(rows):
        return None
    top, sub = rows[h], rows[h + 1]
    cells = [v for v in sub if v is not None]
    data_like = [v for v in rows[h + 2] if v is not None and not _word(v)]
    if len(cells) < 2 or not all(_texty(v) for v in cells) or not data_like \
            or not any(sub[j] is not None and top[j] is None for j in range(len(sub))):
        return None
    below = rows[h + 2:h + 52]
    like = 0                                            # a first record: its cells look like (or recur in) the data
    for j, v in enumerate(sub):
        col = [r[j] for r in below if j < len(r) and r[j] is not None]
        if v is not None and v in col:
            return None
        like += v is not None and (len(col) < 0.5 * len(below) or sum(shape(x) == shape(v) for x in col) >= 0.5 * len(col))
    if like * 2 > len(cells):
        return None
    out, carry = [], None
    for up, low in zip(top, sub):
        carry = up if up is not None else (carry if low is not None else None)
        label = ' / '.join(re.sub(r'\s+', ' ', nfc(str(x))).strip() for x in (carry, low) if x is not None)
        out.append(label or None)
    return out


def partition_key(src: str) -> str:
    """partition_stem plus the sheet name without period tokens, unless generic ("T1".."T12", "Sheet1")."""
    sheet = src.split(':', 1)[1] if ':' in src else ''
    named = sheet and not GENERIC_SHEET.fullmatch(fold(sheet))
    return partition_stem(src) + (f' : {period_free(sheet)}' if named and period_free(sheet) else '')


def partition_groups(parsed):
    """Sources of one table, in file order: the same file stem without period tokens and the same column labels
    (folded, any order, repeats counted). Sheets of one workbook named otherwise ("Nhập kho" / "Xuất kho", "Jan" /
    "Feb") are one table only when their dates do not overlap (periods), never when they do (two kinds of rows).
    Partitions with different columns stay apart (ban_hang, ban_hang_2): merging a subset would also fold a lookup
    list (Sheet2 = products) into a fact table, and the sources listed per table show the split."""
    groups, order = defaultdict(list), {s: n for n, s in enumerate(parsed)}
    for src, p in parsed.items():
        groups[(tuple(sorted(fold(x) for x in p['labels'])), partition_key(src))].append(src)
    tables = defaultdict(list)
    for (labels, _), srcs in groups.items():
        tables[(labels, partition_stem(srcs[0]))].append(srcs)
    out = []
    for parts in tables.values():
        spans = [date_span(parsed, srcs) for srcs in parts] if len(parts) > 1 else [None]
        if None not in spans and all(b[0] >= a[1] for a, b in zip(sorted(spans), sorted(spans)[1:])):
            out.append(sorted((s for srcs in parts for s in srcs), key=order.get))
        else:
            out += parts
    return sorted(out, key=lambda srcs: order[srcs[0]])


def date_span(parsed, srcs):
    """(first, last) date of the sources' rows in the column holding a date on 80% of them, or None."""
    rows = [parsed[s]['grid'].rows[i] for s in srcs for i in parsed[s].get('data', [])]
    as_date = lambda v: parse_datetime(v, None, serial_ok=False) if isinstance(v, (str, dt.date)) else None
    for j in range(max((len(r) for r in rows), default=0)):
        dates = [d for r in rows if j < len(r) and (d := as_date(r[j])) is not None]
        if rows and len(dates) >= 0.8 * len(rows):
            return min(dates), max(dates)
    return None


# ---------------------------------------------------------------- groups written once (order header cells)
def _one_per_group(key, source=None, share=0.98):
    """A key column whose set values name one group each. A value repeated on the very next row (an export duplicate)
    or across a sheet change (a group running on) is not a new group; at least `share` of the rest are distinct."""
    new = key.notna() & ~((key == key.ffill().shift()) & ((key == key.shift()) | (source is not None and source != source.shift())))
    return new.any() and key[new].nunique() >= share * new.sum()


def _row_ids(df, source):
    """Text columns set on every row and distinct on every row: each row is its own record (a customer or supplier
    list with optional cells, an order list), never the continuation line of a group."""
    return [c for c in df.columns if c != source and '__' not in str(c) and len(df) > 1 and df[c].notna().all()
            and df[c].map(lambda v: isinstance(v, str)).all() and df[c].is_unique]


def fill_groups(df, source='__source'):
    """(df, info): lines that continue a group (order) leave the group's cells blank; fill them from the group's first
    row. Key = a column blank on some rows, set on the first row, with unique set values (one per group); the filled
    columns are those blank on every row where the key is blank. Not applied when a text column identifies every row
    on its own. A number column whose first-row value is the sum of the group's other lines (an invoice row above its
    item lines) moves that value to "<col>__group_total". info = {'key', 'columns', 'rows', 'start': True on the
    rows that carried the cells, 'totals': such columns} or None."""
    best = None
    if _row_ids(df, source):
        return df, None
    for k in df.columns:
        m = df[k].isna()
        if k == source or '__' in str(k) or not 0.05 < m.mean() < 0.95 or m.iloc[0] or not _one_per_group(df[k], df.get(source)):
            continue
        cols = [c for c in df.columns if c not in (k, source) and df[c].isna()[m].all() and df[c].notna().any()]
        real = [c for c in cols if str(c).split('__')[0] != k]          # the key's own __raw/__unit copies do not count
        if real and (best is None or len(cols) > len(best[1])):
            best = (k, cols, m)
    if best is None:
        return df, None
    k, cols, m = best
    start = ~m if source not in df.columns else ~m | (df[source] != df[source].shift())
    group, df = start.cumsum(), df.copy()
    for c in [k, *cols]:
        df[c] = df[c].groupby(group).transform('first')
    begin = pd.Series(~m.to_numpy(), index=df.index)
    sums = group_totals(df, begin, [c for c in df.columns if c not in (k, source, *cols) and '__' not in str(c)])
    df = move_totals(df, sums, GROUP_TOTAL)                  # an invoice row's total over its own item lines
    return df, {'key': k, 'columns': [k, *cols], 'rows': int(m.sum()), 'start': begin, 'totals': list(sums)}


def run_totals(df, source='__source'):
    """(df, info) for a table whose groups are runs of rows sharing a key ("HD0001" on the invoice row and on each of
    its item lines): a number column whose first row in each run is the sum of the run's other rows moves that value
    to "<col>__group_total". info = {'key', 'totals'} or None."""
    for k in df.columns:
        key = df[k]
        if k == source or '__' in str(k) or len(df) < 6 or not key.notna().all() or not key.map(lambda v: isinstance(v, str)).all():
            continue
        start = key != key.shift()
        runs = int(start.sum())
        if not 3 <= runs <= 0.8 * len(df) or key[start].nunique() < 0.98 * runs:
            continue
        sums = group_totals(df, start, [c for c in df.columns if c != k and '__' not in str(c)])
        if sums:
            return move_totals(df, sums, GROUP_TOTAL), {'key': k, 'totals': list(sums)}
    return df, None
