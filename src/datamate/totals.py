"""Totals found by arithmetic, whatever words a shop uses: rows whose numbers are the sum of a block of rows.

In:  grid rows and their data row indexes (layout.body_rows), or a typed table with its groups (layout.fill_groups).
Out: `sum_totals` -> the data rows that are subtotals/totals; `group_totals` -> the number columns whose value on the
     first row of each group (an invoice row above its item lines) is the sum of the group's other lines.
Linear time: block sums come from prefix sums; a candidate row is matched to its block by a hash of the prefix value.
A total is sparser than every line of the block it sums; a line equal to a sum by chance is not.
"""
from __future__ import annotations

from bisect import bisect_left
from heapq import heappop, heappush
from collections import Counter

import pandas as pd

from .values import parse_number

SHARE = 0.9             # group_totals: share of the groups (with 2+ lines) where the first row is the sum


def _num(v):
    return None if isinstance(v, bool) else parse_number(v)


def _cell(row, j):
    return row[j] if j < len(row) else None


def typical_fill(rows, idx):
    """Filled cells of a typical full row: the 75th percentile, so continuation lines and totals sit below it."""
    filled = sorted(sum(v is not None for v in rows[i]) for i in idx)
    return filled[(3 * len(filled)) // 4] if filled else 0


def _numbers(rows, data):
    """(numbers of each data row, columns numeric on half the rows, prefix sums of those columns by data position)."""
    nums = {i: [_num(v) for v in rows[i]] for i in data}
    numeric = [j for j in range(max((len(r) for r in nums.values()), default=0))
               if sum(_cell(nums[i], j) is not None for i in data) >= 0.5 * len(data)]
    prefix = {j: [0.0] for j in numeric}
    for i in data:
        for j in numeric:
            prefix[j].append(prefix[j][-1] + (_cell(nums[i], j) or 0.0))
    return nums, numeric, prefix


def _matches(row, present, total, n_rows):
    if not present or n_rows < 2 or not any(row[j] for j in present) or (len(present) == 1 and n_rows < 3):
        return False
    return all(abs(row[j] - (t := total(j))) <= max(1e-6 * abs(t), 0.005) for j in present)


def candidates_of(rows, data, labelled, numeric, nums):
    """Rows that may be totals: sparser than a full row (or full with a total label), holding a non-zero number."""
    typical = typical_fill(rows, data)
    return [k for k, i in enumerate(data) if (sum(v is not None for v in rows[i]) < typical or i in labelled)
            and any(_cell(nums[i], j) for j in numeric)]


def sum_totals(rows, data, boundaries, labelled=()):
    """Data rows that are totals (_sum_totals), keeping only those whose layout (which columns are filled) is mostly
    totals among the data rows: a line of an order that equals a sum by chance shares its layout with thousands of
    lines and is put back."""
    barred = set()
    for _ in range(2):
        found = _sum_totals(rows, data, boundaries, labelled, frozenset(barred))
        layout = lambda i: tuple(v is not None for v in rows[i])
        rows_of = Counter(layout(i) for i in data)
        hits = Counter(layout(i) for i in found)
        bad = {i for i in found if i not in labelled and hits[layout(i)] < 0.5 * rows_of[layout(i)]}
        if not bad:
            return found
        barred |= bad
    return [i for i in found if i not in barred]


def _sum_totals(rows, data, boundaries, labelled=(), barred=frozenset()):
    """Data rows that are totals: their numbers each equal the sum of that column over the detail rows of a block
    next to them: above (from the table start, a total row or any earlier block start: a month total over day
    totals), or else below (a total printed first). Two or more equal numbers are needed, or one over three or
    more rows; at least one is not zero. Totals found are left out of the sums that follow."""
    if len(data) < 3:
        return []
    nums, numeric, prefix = _numbers(rows, data)
    labelled, filled = set(labelled), [sum(v is not None for v in rows[i]) for i in data]
    cands = [k for k in candidates_of(rows, data, labelled, numeric, nums) if data[k] not in barred and (data[k] in labelled
             or filled[k] < max(filled[max(0, k - 3):k + 4]))] if numeric else []     # sparser than a row nearby
    if not cands:
        return []
    starts = {0} | {k for k in range(1, len(data)) if any(data[k - 1] < b < data[k] for b in boundaries)}
    found, cum, found_set = [], {j: [0.0] for j in numeric}, set()     # found positions (sorted), running sums

    def adj(j, p):                                          # prefix at position p without the totals found before p
        return prefix[j][p] - cum[j][bisect_left(found, p)]

    def ok(k, a, b):                                        # a total is sparser than every line it sums (a line that
        row = nums[data[k]]                                 # equals a sum by chance is as full as its neighbours)
        present = [j for j in numeric if _cell(row, j) is not None]
        if not _matches(row, present, lambda j: adj(j, b) - adj(j, a), b - a - (bisect_left(found, b) - bisect_left(found, a))):
            return False
        lines = [filled[p] for p in range(a, b) if p != k and p not in found_set]
        return data[k] in labelled or (bool(lines) and filled[k] < min(lines))

    index, pending = {}, sorted(starts)                     # a heap of block starts not yet indexed
    for k in cands:                                         # pass 1: blocks above, in row order (found stays sorted)
        while pending and pending[0] <= k - 2:
            s = heappop(pending)
            for j in numeric:                               # same prefix (zero rows): the first and the 4 latest
                (at := index.setdefault((j, round(adj(j, s), 2)), [])).append(s)
                del at[1:-4]
        row = nums[data[k]]
        j0 = next(j for j in numeric if _cell(row, j) is not None)
        if any(ok(k, s, k) for s in index.get((j0, round(adj(j0, k) - row[j0], 2)), [])):
            found.append(k)
            found_set.add(k)
            for j in numeric:
                cum[j].append(cum[j][-1] + (_cell(row, j) or 0.0))
        heappush(pending, k + 1)                            # every candidate starts a block, confirmed or not
        starts.add(k + 1)
    ends = {}                                               # pass 2: blocks below, ending at a block start or the end
    for e in sorted(starts | {len(data)}):
        for j in numeric:
            ends.setdefault((j, round(adj(j, e), 2)), []).append(e)
    top = []
    for k in (k for k in cands if k not in set(found)):
        row = nums[data[k]]
        j0 = next(j for j in numeric if _cell(row, j) is not None)
        at = ends.get((j0, round(adj(j0, k + 1) + row[j0], 2)), [])
        if any(ok(k, k + 1, e) for e in at[bisect_left(at, k + 3):][:4]):
            top.append(k)
    shape_of = lambda k: tuple(v is not None for v in rows[data[k]])          # one-line blocks: a row laid out like
    known = {shape_of(k) for k in found}                                        # the totals found, equal to the line
    one = [k for k in cands if k not in found_set and k not in top and k - 1 in starts and k - 1 not in found_set
           and shape_of(k) in known and filled[k] < filled[k - 1] and ok_one(nums[data[k]], nums[data[k - 1]], numeric)]
    return sorted(data[k] for k in found + top + one)


def ok_one(row, line, numeric):
    present = [j for j in numeric if _cell(row, j) is not None]
    return any(row[j] for j in present) and all(_cell(line, j) is not None and abs(row[j] - line[j]) <= 0.005 for j in present)


def recurring_totals(rows, data):
    """Rows holding a text that recurs (3+ times, on under half the rows) and, on 90% of its rows, sits on a row whose
    numbers are the sums of the lines since its previous occurrence: a "Subtotal" written in the product column, a
    total word no list knows. Such rows are totals wherever the text stands."""
    nums, numeric, prefix = _numbers(rows, data)
    seen = {}
    for k, i in enumerate(data):
        for j, v in enumerate(rows[i]):
            if isinstance(v, str) and j not in numeric:
                seen.setdefault((j, v), []).append(k)
    out = []
    for ks in seen.values():
        if 3 <= len(ks) <= len(data) / 2:
            hits = sum(_matches(nums[data[k]], [j for j in numeric if _cell(nums[data[k]], j) is not None],
                                lambda j: prefix[j][k] - prefix[j][a + 1 if a >= 0 else 0], 2) and k - a > 1
                       for a, k in zip([-1] + ks, ks))
            if hits >= SHARE * len(ks):
                out += [data[k] for k in ks]
    return out


def group_totals(df, start, columns):
    """{number column: rows to move}: groups whose first row is laid out unlike its lines (blank where every other
    line is filled: an invoice row above its item lines; never a lot's import row above its sales, which fills the
    same columns) and holds, in the column, the sum of the group's other lines. A column counts when that is so in
    at least SHARE of its groups with two or more lines and a non-zero sum (three at least); only those groups move."""
    group, out = start.cumsum(), {}
    others = df[~start].notna().groupby(group[~start]).all()                  # columns every line of the group fills
    first_blank = df[start].isna().set_axis(group[start].to_numpy())
    unlike = (first_blank.reindex(others.index) & others).any(axis=1)
    for c in columns:
        s = df[c]
        if not pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s):
            continue
        lines = s[~start].groupby(group[~start])
        size, total = lines.count(), lines.sum()
        some = size[(size >= 1) & (total != 0)].index       # 0 = 0 proves nothing (discount columns)
        first = pd.Series(s[start].to_numpy(), index=group[start].to_numpy()).reindex(some)
        hit = ((first - total.reindex(some)).abs() <= 0.005 + 1e-6 * total.reindex(some).abs()) & unlike.reindex(some).fillna(False)
        multi = size.reindex(some) >= 2
        if multi.sum() >= 3 and hit[multi].mean() >= SHARE:
            out[c] = start & group.isin(hit[hit].index)
    return out


def move_totals(df, sums, suffix):
    """Move each column's group totals (group_totals) to "<col><suffix>", blank in the column."""
    df = df.copy()
    for c, rows in sums.items():
        df[c + suffix] = df[c].where(rows)
        df[c] = df[c].mask(rows)
    return df
