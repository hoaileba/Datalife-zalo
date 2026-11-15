"""Noise measured on a shop's data, for the catalog (catalog.data_notes): what the column profiles do not show.

In:  `Business` (data.py).  Out: {'note', 'joins', 'spelling_variants', 'code_names', 'units'} (parts found) or None.
- joins: same-named text columns of several tables vs the table where the column is unique (the master).
- spelling_variants: values equal up to case, spaces, punctuation or missing all accents (not a different tone mark).
- code_names: a code written with several names on its rows (a real code -> name pair: 90 % of codes, one name).
- units: items written in several units; unit values are words written after a number somewhere in the shop.
Measured from the data only (no word lists); a failure drops the notes, never the shop.
"""
from __future__ import annotations

import re

import pandas as pd

from .data import INDEX_LIMIT, RAW_SUFFIX, SECTION_COL, SOURCE_COL, START_COL, UNIT_SUFFIX, is_text
from .helpers import norm


TABLE_NOTES = (   # how every table was read: the same for all shops (system prompt section 4)
    'Tables are read from the source files with their ORIGINAL column headers. Only format fixes were applied: '
    'header detection (a two-row header joined as "upper / lower"; rows above the header shown as text_above_header: '
    'they may say what the export covers); rows that are not records removed, counted in dropped_rows with examples: '
    'blank, repeated header, totals (a total label, or numbers equal to the sum of their block), one-cell notes '
    'after the data, signature footers; one-cell rows heading sections become the column '
    f'"{SECTION_COL}"; partitions of one table (monthly sheets, files named _1/_2/_2026) concatenated, with '
    f'"{SOURCE_COL}" naming the origin sheet/file. Numbers, quantities and dates are parsed from content (decimal '
    'mark and day/month order as the column\'s own cells show, noted when it matters); when the '
    f'source held text, "<col>{RAW_SUFFIX}" keeps the original (listed only where some cells did not parse). '
    f'Quantities written with a unit ("2 gói") keep the unit in "<col>{UNIT_SUFFIX}". Line tables where only the '
    'first line of an order carries the order cells (id, date, status, customer) have those cells filled down to '
    f'the following lines of the order (noted on the columns; "{START_COL}" marks the lines that carried them). NOT '
    'applied: duplicate removal, status normalization, entity merging, unit conversion: apply the rulebook and '
    'README in code.')

NOTE_PARTS = {
    'joins': 'a column name shared by several tables, checked against the table where it is unique (the master): values '
             'and rows of the other tables that the master does not have will not join.',
    'spelling_variants': 'one value written several ways that differ only in case, spaces or missing accents: group '
                         'by the code; without a code, by kit.name_key(column, master column): an unaccented form goes with '
                         'its one accented form (plain kit.norm also merges names that differ by a tone mark, '
                         'which are different names).',
    'code_names': 'one code written with several names on its rows: group by the code, take the name from the master.',
    'units': 'items written in several units in one table: convert to the base unit before summing quantities.'}
MAX_NOTES, MIN_KEY_VALUES, MAX_VARIANT_VALUES = 8, 20, 50000


def _text_columns(frame):
    names = [c for c in frame.columns if isinstance(c, str)]
    return [c for c in names if not c.endswith((RAW_SUFFIX, UNIT_SUFFIX)) and not c.startswith('__')
            and names.count(c) == 1 and is_text(frame[c])]


def _unique(series):
    s = series.dropna()
    return len(s) > 0 and s.is_unique


def _joins(tables, text):
    """Same-named text columns of several tables, against the master: the table where the column is unique and that
    holds most of the other tables' values. A table with more than half of its values outside the master holds
    something else (or the master is partial): not reported. Not unique anywhere (a status): not a key."""
    by_name, out = {}, []
    for t in sorted(tables):
        f = tables[t]
        for c in text[t]:
            values = f[c].dropna().astype(str).str.strip()
            if values.nunique() >= MIN_KEY_VALUES:
                by_name.setdefault(norm(c), []).append((t, c, values))
    for key in sorted(by_name):
        cols = by_name[key]
        masters = [x for x in cols if x[2].is_unique]
        if len({t for t, _, _ in cols}) < 2 or not masters:
            continue
        def covered(m):                                         # how much of the other tables this master holds
            known = set(m[2])
            return sum(len(set(v) & known) for t, c, v in cols if (t, c) != m[:2])
        mt, mc, mv = max(masters, key=lambda m: (covered(m), m[2].nunique(), m[0]))
        known, others = set(mv), {}
        for t, c, v in cols:
            if (t, c) == (mt, mc):
                continue
            missing = v[~v.isin(known)]
            spelled = {norm(x, accents=True) for x in known}
            if sum(norm(x, accents=True) not in spelled for x in missing.unique()) > 0.5 * v.nunique():
                continue                    # not the same thing (or a partial table), even allowing for case/spaces
            others[f'{t}.{c}'] = (f'all {v.nunique()} values found' if missing.empty else
                                  f'{missing.nunique()} of {v.nunique()} values ({len(missing)} rows) not in the master')
        if others:
            out.append({'key': mc, 'master': f'{mt}.{mc}', 'others': others})
    return out


def _spelling_variants(tables, text):
    """Values that differ only in case, spaces, punctuation or by missing all their accents (a tone mark changes the
    name: Doãn / Đoàn, Hà / Hạ are not variants). Columns unique per row (a master list) are skipped."""
    out = []
    for t in sorted(tables):
        f = tables[t]
        for c in text[t]:
            s = f[c].dropna()
            if s.empty or _unique(s) or s.nunique() > MAX_VARIANT_VALUES:
                continue
            groups = {}
            for v in sorted(set(s.astype(str))):                       # same text up to case/spaces/punctuation
                groups.setdefault(norm(v, accents=True), []).append(v)
            folded = {}
            for a in groups:
                folded.setdefault(norm(a), []).append(a)
            for forms in folded.values():                              # an all-ASCII form joins its one accented form
                plain = [a for a in forms if a.isascii()]
                accented = [a for a in forms if not a.isascii()]
                if plain and len(accented) == 1:
                    groups[accented[0]] += [v for a in plain for v in groups.pop(a)]
            several = sorted(sorted(g)[:3] for g in groups.values() if len(g) > 1)
            if several:
                out.append({'column': f'{t}.{c}', 'values_written_several_ways': len(several), 'examples': several[:2]})
    return sorted(out, key=lambda x: (-x['values_written_several_ways'], x['column']))[:MAX_NOTES]


def _code_names(tables, text):
    """A code column (no spaces) and a name column (words) of the same table where nearly every code has one name
    (after dm.norm): codes whose rows still write that name several ways."""
    out = []
    for t in sorted(tables):
        f = tables[t]
        cols = [c for c in text[t] if f[c].notna().any()]
        spaced = {c: f[c].dropna().astype(str).str.strip().str.contains(' ').mean() for c in cols}
        normed = {}
        for name in (c for c in cols if spaced[c] >= 0.5):
            values = f[name].dropna().unique()
            normed[name] = f[name].map(dict(zip(values, map(norm, values))))       # each distinct value once
        for a in (c for c in cols if spaced[c] <= 0.1 and f[c].nunique() >= 10):
            for name, n in normed.items():
                if name == a:
                    continue
                pair = pd.DataFrame({'code': f[a], 'name': f[name], 'norm': n}).dropna()
                one_name = pair.drop_duplicates(['code', 'norm'])['code'].value_counts()
                if pair.empty or (one_name == 1).mean() < 0.9:
                    continue
                written = pair.drop_duplicates(['code', 'name'])['code'].value_counts()
                several = written[written > 1]
                if len(several):
                    code = several.sort_index().sort_values(ascending=False, kind='stable').index[0]
                    out.append({'code': f'{t}.{a}', 'name': name, 'codes_with_several_names': len(several),
                                'example': [code, sorted(pair.loc[pair['code'] == code, 'name'].unique())[:3]]})
    return sorted(out, key=lambda x: (-x['codes_with_several_names'], x['code']))[:MAX_NOTES]


def _counted_words(business, tables, text):
    """Words written right after a number in the README ("1 lốc = 6 lon"), in original cell text ("5 chai") or in
    names ("hộp 10 vỉ"): units."""
    texts = [business.readme or '']
    for t, f in tables.items():
        for c in f.columns:
            if not isinstance(c, str):
                continue
            values = f[c].dropna()
            named = c in text[t] and values.astype(str).str.contains(' ').mean() >= 0.5
            if c.endswith((RAW_SUFFIX, UNIT_SUFFIX)) or named:
                texts += [str(v) for v in values.unique()[:500]]
    found = set()
    for text in texts:
        for m in re.finditer(r'\d[\d.,]*\s*([^\W\d_]+(?: \d+[^\W\d_]+)?)', norm(text, accents=True)):
            found.update({m[1], m[1].split()[0]})
    return found


def _units(business, tables, text):
    """Unit columns: 2-30 distinct values, most of them written after a number somewhere in the shop. Item columns:
    repeated names that carry those words, appear in the README followed by a counted unit ("Coca 330ml: 1 lốc = 6
    lon"), or are found in another table that carries units (a master where they are unique, or a conversion table
    with two unit columns)."""
    counted, readme, out = _counted_words(business, tables, text), norm(business.readme or '', accents=True), []
    counted_re = '|'.join(sorted(map(re.escape, counted), key=len, reverse=True)) or '(?!)'   # "<item> 1 lốc"
    unit_cols = {}
    for t in sorted(tables):
        f = tables[t]
        cols = [c for c in f.columns if isinstance(c, str) and (c.endswith(UNIT_SUFFIX) or c in text[t])]
        unit_cols[t] = [u for u in cols if 1 < len(v := f[u].dropna().astype(str).unique()) <= 30
                        and sum(norm(x, accents=True) in counted for x in v) >= 0.5 * len(v)]
    plain_units = {t: [u for u in unit_cols[t] if not u.endswith(UNIT_SUFFIX)] for t in tables}
    masters = {(t, norm(c)) for t, f in tables.items() for c in text[t]        # a master or a conversion
               if unit_cols[t] and (_unique(f[c]) or len(plain_units[t]) >= 2)}  # table (two unit columns)
    words = {norm(x, accents=True) for t, f in tables.items() for u in unit_cols[t] for x in f[u].dropna().astype(str).unique()}
    for t in sorted(tables):
        f = tables[t]
        for item in text[t]:
            keys = f[item].dropna().astype(str)
            if item in unit_cols[t] or not 5 <= keys.nunique() <= INDEX_LIMIT or len(keys) < 2 * keys.nunique():
                continue                                              # items repeat on the lines of a line table
            names = pd.Series(keys.unique()).map(lambda v: norm(v, accents=True))
            carries = names.map(lambda v: bool(words & set(v.split()))).mean() >= 0.3
            in_readme = names.map(lambda v: len(v) >= 4 and bool(re.search(re.escape(v) + r' \d[\d.,]* ?(' + counted_re + r')\b', readme))).mean() >= 0.3
            if not (carries or in_readme or any(m == norm(item) and o != t for o, m in masters)):
                continue
            for u in unit_cols[t]:
                per = f[[item, u]].dropna().drop_duplicates()[item].value_counts()
                several = per[per > 1]
                if len(several):
                    top = several.sort_index().sort_values(ascending=False, kind='stable').index[0]
                    out.append({'table': t, 'item': item, 'unit': u, 'items_in_several_units': len(several),
                                'example': [top, sorted(map(str, f.loc[f[item] == top, u].dropna().unique()))[:4]]})
    plain = {(o['table'], o['item']) for o in out if not o['unit'].endswith(UNIT_SUFFIX)}     # a __unit twin repeats it
    out = [o for o in out if not (o['unit'].endswith(UNIT_SUFFIX) and (o['table'], o['item']) in plain)]
    return sorted(out, key=lambda x: (-x['items_in_several_units'], x['table'], x['item']))[:MAX_NOTES]


def data_notes(business):
    """Noise measured on the data (the catalog shows the rest). A failure only drops the notes, never the shop."""
    try:
        tables = {k: v for k, v in business.tables.items() if k != 'calendar'}
        text = {t: _text_columns(f) for t, f in tables.items()}          # each column's type checked once
        parts = {'joins': _joins(tables, text), 'spelling_variants': _spelling_variants(tables, text),
                 'code_names': _code_names(tables, text), 'units': _units(business, tables, text)}
    except Exception:
        return None
    parts = {k: v for k, v in parts.items() if v}
    if not parts:
        return None
    return {'note': "Facts measured on this shop's data, not rules. " + ' '.join(f'{k}: {NOTE_PARTS[k]}' for k in parts), **parts}
