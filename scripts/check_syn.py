"""Checks of a synthetic split (gen.build_v2) without model calls.

  load   every shop through datamate.data.load_business: unreadable files, tables, columns, rows, file formats
  cross  gold vs an independent recomputation: plain pandas on the tables the agent sees (production reader), located
         by the headers the renderer wrote (<split>/_render/<shop>.json), with the split rulebook's Rules; it shares
         no code with gen.oracle (own period bounds, status mapping, dedup, joins)
  dist   answer types, intent buckets (scripts/train_intents.py rules), period kinds (gen.parse.find_period), noise
         statistics (gen.surface.noise_stats), shop shape (tables, columns, formats, README) vs data/train
  tokens first-turn prompt tokens (gen.package rebuild = the agent's own prompt; Gemma tokenizer when installed)

python scripts/check_syn.py data_gen/syn_v2/t1 [more splits] --what load,cross,dist,tokens [--sample 40] [--json out]
Never reads data/public_test.
"""
from __future__ import annotations

import argparse
import calendar as _cal
import collections
import datetime as dt
import json
import random
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT), str(ROOT / 'scripts')]

TRAIN = ROOT / 'data' / 'train'


def read_jsonl(p):
    return [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]


def forbid(path):
    if 'public_test' in str(Path(path).resolve()):
        raise SystemExit('public_test is never read')


# ====================================================================== load
def load_stats(split: Path):
    from datamate.data import load_business
    rows = []
    for d in sorted((split / 'data').iterdir()):
        b = load_business(d, split / 'calendar.csv', None)
        tabs = {n: t for n, t in b.tables.items() if n != 'calendar'}
        rows.append({'shop': d.name, 'unreadable': len(b.unreadable), 'tables': len(tabs),
                     'columns': sum(len([c for c in t.columns if not str(c).startswith('__') and '__' not in str(c)])
                                    for t in tabs.values()),
                     'rows': sum(len(t) for t in tabs.values()),
                     'formats': ''.join(sorted({p.suffix[1] for p in d.iterdir() if p.suffix in ('.csv', '.xlsx', '.sqlite')})),
                     'readme_chars': len((d / 'README.md').read_text(encoding='utf-8')) if (d / 'README.md').exists() else 0})
        del b
    return rows


# ====================================================================== independent recomputation
def half_up(x, places=0):
    v = Decimal(str(float(x))).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return int(v) if places == 0 else float(v)


def _date(v):
    return dt.date.fromisoformat(v) if isinstance(v, str) else v


def lunar_to_solar(cal, y, m, d):
    hit = cal[(cal.lunar_year == y) & (cal.lunar_month == m) & (cal.lunar_day == d) & ~cal.lunar_leap]
    return hit.date.iloc[0].date()


def bounds(per, as_of, R, cal):
    """Inclusive [start, end] of a period, from the rulebook text's meaning (own code, not gen.periods)."""
    k = per['kind']
    if k == 'month':
        return dt.date(per['y'], per['m'], 1), dt.date(per['y'], per['m'], _cal.monthrange(per['y'], per['m'])[1])
    if k == 'quarter':
        m0 = 3 * per['q'] - 2
        return dt.date(per['y'], m0, 1), dt.date(per['y'], m0 + 2, _cal.monthrange(per['y'], m0 + 2)[1])
    if k == 'range':
        return _date(per['start']), _date(per['end'])
    if k == 'day':
        return _date(per['date']), _date(per['date'])
    if k == 'today':
        return as_of, as_of
    if k == 'yesterday':
        return as_of - dt.timedelta(1), as_of - dt.timedelta(1)
    if k == 'this_month':
        return as_of.replace(day=1), as_of
    if k == 'ytd':
        return as_of.replace(month=1, day=1), as_of
    if k in ('this_week', 'last_week'):
        ws = R.get('week_start', 0)
        mon = as_of - dt.timedelta((as_of.weekday() - ws) % 7)
        return (mon, as_of) if k == 'this_week' else (mon - dt.timedelta(7), mon - dt.timedelta(1))
    if k == 'last_n_days':
        n = per['n']
        if R.get('last_n_include_today', True):
            return as_of - dt.timedelta(n - 1), as_of
        return as_of - dt.timedelta(n), as_of - dt.timedelta(1)
    if k == 'tet':
        (m1, d1), (m2, d2) = R.get('tet_start', (12, 23)), R.get('tet_end', (1, 10))
        return lunar_to_solar(cal, per['year'] - 1, m1, d1), lunar_to_solar(cal, per['year'], m2, d2)
    if k == 'season':
        for key, _lab, (m1, d1), (m2, d2) in R.get('seasons', ()):
            if key == per['name']:
                y = per['year']
                return dt.date(y - 1 if (m1, d1) > (m2, d2) else y, m1, d1), dt.date(y, m2, d2)
    raise KeyError(k)


def _spell(v):
    import re
    import unicodedata
    s = unicodedata.normalize('NFD', str(v).lower()).replace('đ', 'd').replace('đ'.upper(), 'd')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', s).strip()


def _find(tables, headers):
    best = None
    for n, t in tables.items():
        if set(headers) <= set(t.columns) and (best is None or len(t) > len(tables[best])):
            best = n
    return best


def _num(s):
    from datamate.values import parse_number
    if s.dtype != object:
        return pd.to_numeric(s, errors='coerce')
    return s.map(lambda v: parse_number(v) if isinstance(v, str) else v).astype(float)


def _dates(s):
    if np.issubdtype(s.dtype, np.datetime64):
        return s.dt.normalize()
    return pd.to_datetime(s, errors='coerce', dayfirst=True).dt.normalize()


class Shop:
    """The facts a question needs, read back from the agent's tables."""

    def __init__(self, split, bid, R, cal):
        from datamate.data import load_business
        self.R, self.cal = R, cal
        self.info = json.loads((split / '_render' / f'{bid}.json').read_text(encoding='utf-8'))
        ex = self.info['extras']
        self.family = self.info['family']
        b = load_business(split / 'data' / bid, split / 'calendar.csv', None)
        T = {n: t for n, t in b.tables.items() if n != 'calendar'}
        self.ok = False
        if self.family == 'H':
            self._from_sqlite(T)
        else:
            self._from_sheets(T, ex)

    def _from_sheets(self, T, ex):
        cols = ex['lines']['cols']
        name = _find(T, cols.values())
        if name is None:
            return
        df = T[name]
        keyed = 'order_id' in cols
        content = [c for c in df.columns if '__' not in str(c)]
        if keyed:
            df = df.drop_duplicates(subset=content)        # rulebook §8: identical lines of one order = export error
        L = pd.DataFrame({k: df[h].values for k, h in cols.items()})
        if 'status' not in cols and ex.get('orders'):
            oc = ex['orders']['cols']
            o = T[_find(T, oc.values())]
            o = pd.DataFrame({k: o[h].values for k, h in oc.items()}).drop_duplicates('order_id')
            keep = ['order_id', 'status'] + [k for k in ('date', 'created') if k in o and k not in L]
            L = L.merge(o[keep], on='order_id', how='left')
            self.orders_tab = o
        else:
            self.orders_tab = None
        self.L = L
        self.status_map = ex['status_map']
        self._finish()
        vis = ex.get('visits')
        self.visits = None
        if vis and keyed:
            src = self.orders_tab if vis['level'] == 'orders' and self.orders_tab is not None else None
            if src is None:
                if vis['level'] == 'orders':          # invoice list with the visit columns
                    vt = T[_find(T, list(vis['cols'].values()) + [ex['orders']['cols']['order_id']])]
                    src = pd.DataFrame({'order_id': vt[ex['orders']['cols']['order_id']].values,
                                        **{k: vt[h].values for k, h in vis['cols'].items()}})
                else:
                    src = L
            self.visits = src[['order_id'] + [k for k in vis['cols'] if k in src]].dropna(subset=['order_id']) \
                .drop_duplicates('order_id').set_index('order_id')
        self.money = {}
        for sh in ex.get('sheets', []):
            c = sh['cols']
            for k in ('shipping', 'order_discount'):
                if k in c and 'order_id' in c and k not in self.money:
                    t = T.get(_find(T, list(c.values())))       # the sheet itself: all its headers
                    if t is not None:
                        m = pd.DataFrame({'o': t[c['order_id']].values, 'v': _num(t[c[k]].astype(object)).values})
                        self.money[k] = m.dropna(subset=['o']).drop_duplicates('o').set_index('o').v
        self.groups = None
        if 'group' in cols:
            self.L['group_'] = self.L['group']
        else:
            for sh in ex.get('sheets', []):
                c = sh['cols']
                if 'group' in c and ({'product_id', 'product_name'} & set(c)) and 'order_id' not in c:
                    key = 'product_id' if 'product_id' in c and 'product_id' in cols else 'product_name'
                    if key not in cols:
                        continue
                    t = T.get(_find(T, [c[key], c['group']]))
                    if t is None:
                        continue
                    m = dict(zip(t[c[key]].map(_spell), t[c['group']]))   # §8: one name written several ways
                    self.L['group_'] = self.L[key].map(_spell).map(m)
                    break

    def _from_sqlite(self, T):
        t = {n.lower(): x for n, x in T.items()}

        def col(df, *names):
            return next(c for c in df.columns if c.lower().replace('_', '') in names)
        ln, o = t['chi_tiet_don'], t['don_hang']
        ln = ln.drop_duplicates(subset=[c for c in ln.columns if '__' not in c])
        L = pd.DataFrame({'order_id': ln[col(ln, 'mahoadon')].values, 'amount': ln[col(ln, 'trigia')].values,
                          'qty': ln[col(ln, 'sl')].values, 'unit': ln[col(ln, 'donvitinh')].values,
                          'product_id': ln[col(ln, 'mahanghoa')].values})
        oo = pd.DataFrame({'order_id': o[col(o, 'mahoadon')].values, 'status': o[col(o, 'tinhtrang')].values,
                           'created': o[col(o, 'thoigianlap')].values})
        self.money = {'shipping': pd.Series(_num(o[col(o, 'phivanchuyen')]).values, index=o[col(o, 'mahoadon')].values),
                      'order_discount': pd.Series(_num(o[col(o, 'chietkhau')]).values, index=o[col(o, 'mahoadon')].values)}
        self.L = L.merge(oo, on='order_id', how='left')
        self.status_map = {'completed': 'completed', 'cancelled': 'cancelled', 'returned': 'returned',
                           'shipping': 'delivering'}
        self._finish()
        self.visits = None
        if 'luot_phuc_vu' in t:
            v = t['luot_phuc_vu']
            ren = {}
            for c in v.columns:
                k = c.lower().replace('_', '')
                ren[c] = {'mahoadon': 'order_id', 'soban': 'table', 'khuvuc': 'area', 'sokhach': 'guests',
                          'biensoxe': 'plate'}.get(k, c)
            self.visits = v.rename(columns=ren).drop_duplicates('order_id').set_index('order_id')
        sp = t.get('san_pham')
        if sp is not None:
            m = dict(zip(sp[col(sp, 'mahanghoa')], sp[col(sp, 'danhmuc')]))
            self.L['group_'] = self.L['product_id'].map(m)

    def _finish(self):
        L = self.L
        L['st'] = L['status'].map(self.status_map)
        L['amount'] = _num(L['amount'])
        if 'qty' in L:
            from datamate.values import parse_qty
            L['q'] = L['qty'].map(lambda v: parse_qty(v)[0] if isinstance(v, str) else v).astype(float)
        dcol = 'created' if 'created' in L and L['created'].notna().any() else 'date'
        L['day'] = _dates(L[dcol])
        if 'order_id' in L:                   # §1: an order belongs to the period of its order date (a return row
            L['day'] = L.groupby('order_id').day.transform('min')       # written later keeps the order's date)
        self.ok = L['st'].notna().mean() > 0.99 and L['day'].notna().mean() > 0.99

    # ---------------- facts
    def orders(self, per, as_of):
        s, e = bounds(per, as_of, self.R, self.cal)
        e = min(e, as_of)
        L = self.L[(self.L.day >= pd.Timestamp(s)) & (self.L.day <= pd.Timestamp(e))]
        return L

    def order_rev(self, V):
        """Revenue per valid order (§1 of the split rulebook: lines, + delivery fee, − order voucher when it says so)."""
        r = V.groupby('order_id').amount.sum()
        if self.R.get('revenue_shipping'):
            r = r + self.money['shipping'].reindex(r.index).fillna(0)
        if self.R.get('revenue_order_discount'):
            r = r - self.money['order_discount'].reindex(r.index).fillna(0)
        return r

    def valid_lines(self, L):
        bad = {'cancelled'}
        if not self.R.get('count_delivering', True):
            bad.add('delivering')
        if 'order_id' in L:
            ret = set(L.loc[L.st == 'returned', 'order_id'])
            if 'q' in L:
                ret |= set(L.loc[L.q < 0, 'order_id'])
            if self.R.get('exclude_returned', True):
                return L[~L.st.isin(bad | {'returned'}) & ~L.order_id.isin(ret)]
            return L[~L.st.isin(bad) & ~(L.q < 0 if 'q' in L else False)]
        return L[~L.st.isin(bad | ({'returned'} if self.R.get('exclude_returned', True) else set()))]


def reference(shop: Shop, spec, as_of):
    """(type, value) or None when this check does not cover the question."""
    R = shop.R
    it = spec['intent']
    money = R.get('revenue_shipping') or R.get('revenue_order_discount')
    per = spec.get('period')
    if per is None and it not in ('revenue_list',):
        return None
    keyed = 'order_id' in shop.L
    if it == 'revenue_list':
        out = []
        for p in spec['periods']:
            V = shop.valid_lines(shop.orders(p, as_of))
            out.append(half_up(shop.order_rev(V).sum() if keyed else V.amount.sum()))
        return 'list', out
    L = shop.orders(per, as_of)
    V = shop.valid_lines(L)
    if not keyed:
        return ('number', half_up(V.amount.sum())) if it == 'revenue' and not money else None
    orev = shop.order_rev(V)
    rev = orev.sum()
    if it == 'revenue':
        return 'number', half_up(rev)
    nord = V.order_id.nunique()
    if it == 'order_count':
        return 'number', int(nord)
    if it == 'avg_order':
        return ('number', half_up(rev / nord)) if nord else None
    if it in ('cancel_count', 'cancel_rate'):
        st = L.groupby('order_id').st.first()
        if 'q' in L:
            st[L[L.q < 0].order_id.unique()] = 'returned'
        if it == 'cancel_count':
            return 'number', int((st == 'cancelled').sum())
        if not R.get('cancel_rate_all_orders', True):
            st = st[st != 'returned']
        return 'percent', half_up((st == 'cancelled').sum() / len(st) * 100, R.get('pct_decimals', 2))
    if it in ('days_over', 'orders_over', 'best_day'):
        if it == 'orders_over':
            r = orev
        else:
            r = orev.groupby(V.groupby('order_id').day.first().reindex(orev.index).values).sum()
        if it == 'best_day':
            r = r.sort_index()
            d = r.idxmin() if spec.get('worst') else r.idxmax()
            return 'date', pd.Timestamp(d).strftime('%Y-%m-%d')
        th = spec['threshold']
        return 'number', int((r >= th).sum() if spec.get('inclusive', True) else (r > th).sum())
    if it in ('service_revenue', 'service_share'):
        if 'group_' not in V:
            return None
        g = V.group_.fillna('').astype(str).str.strip().str.lower().str.startswith(R.get('service_prefix', 'dịch vụ'))
        if it == 'service_share':
            return 'percent', half_up(V.amount[g].sum() / rev * 100, R.get('pct_decimals', 2))
        if spec.get('part') == 'goods':
            return None                                   # needs the fee line's kind; not covered here
        return 'number', half_up(V.amount[g].sum())
    if it == 'qty_unit':
        if 'unit' not in V or str(spec['unit']).lower() != 'kg' or shop.info['industry'] != 'fruit_shop':
            return None                                   # kg goods sold only by the kg (fruit shops)
        return 'number', (lambda x: int(x) if float(x).is_integer() else x)(half_up(V.q[V.unit.astype(str).str.lower() == 'kg'].sum(), 2))
    vis = shop.visits
    if it in ('guests_total', 'revenue_per_guest', 'area_revenue', 'top_table', 'vehicle_count', 'repeat_vehicles'):
        if vis is None:
            return None
        ords = orev
        v = vis.reindex(ords.index)
        if it in ('guests_total', 'revenue_per_guest'):
            g = _num(v['guests'].astype(object))
            if R.get('guests_missing_as_one'):
                g = g.fillna(1)
            n = g.fillna(0).sum()
            if it == 'guests_total':
                return 'number', int(n)
            r = R.get('per_guest_round', 0)
            x = ords.sum() / n
            return 'number', half_up(x) if r >= 0 else half_up(x / 10 ** -r) * 10 ** -r
        if it == 'area_revenue':
            return 'number', half_up(ords[(v['area'] == spec['area']).values].sum())
        if it == 'top_table':
            t = v['table']
            s = ords[t.notna().values].groupby(t[t.notna()].values).sum()
            s = s.rename('v').reset_index().sort_values(['v', 'index'], ascending=[False, True])
            return 'string', str(s['index'].iloc[0])
        pl = v['plate'].dropna()
        if it == 'vehicle_count':
            return 'number', int(pl.nunique())
        return 'number', int((pl.value_counts() >= spec.get('n', R.get('repeat_min', 2))).sum())
    return None


def _same(t, a, gt, ga):
    if t != gt:
        return False
    if t in ('number', 'percent'):
        return abs(float(a) - float(ga)) < 1e-6
    if t == 'list':
        return len(a) == len(ga) and all(abs(float(x) - float(y)) < 1e-6 for x, y in zip(a, ga))
    if t == 'string':
        from datamate.values import fold
        return fold(str(a)) == fold(str(ga))
    return a == ga


def cross(split: Path, sample, seed=0):
    cal = pd.read_csv(split / 'calendar.csv', parse_dates=['date'])
    parts = json.loads((split / '_render' / 'rulebook_parts.json').read_text(encoding='utf-8'))
    R = parts['rules']
    R['seasons'] = [(k, lab, tuple(a), tuple(b)) for k, lab, a, b in R.get('seasons', [])]
    for k in ('tet_start', 'tet_end'):
        R[k] = tuple(R[k])
    gold = {a['id']: a for a in read_jsonl(split / 'answers.jsonl')}
    meta = read_jsonl(split / 'meta.jsonl')
    by_shop = collections.defaultdict(list)
    for m in meta:
        by_shop[m['business_id']].append(m)
    rnd = random.Random(seed)
    res = []
    for bid, ms in sorted(by_shop.items()):
        shop = Shop(split, bid, R, cal)
        if not shop.ok:
            res.append({'shop': bid, 'family': shop.family, 'intent': '*', 'status': 'unread'})
            continue
        ms = [m for m in ms if gold[m['id']]['type'] != 'unanswerable']
        rnd.shuffle(ms)
        n = 0
        for m in ms:
            if n >= sample:
                break
            try:
                ref = reference(shop, m['spec'], dt.date.fromisoformat(m['as_of']))
            except Exception as exc:  # noqa: BLE001 - reported
                ref = ('error', repr(exc)[:120])
            if ref is None:
                continue
            n += 1
            g = gold[m['id']]
            ok = ref[0] != 'error' and _same(ref[0], ref[1], g['type'], g['answer'])
            res.append({'shop': bid, 'family': shop.family, 'industry': m['industry'], 'intent': m['intent'],
                        'id': m['id'], 'status': 'ok' if ok else 'diff', 'gold': g['answer'], 'ref': ref[1]})
        del shop
    return res


# ====================================================================== distributions
def bucket(q, a):
    import train_intents
    return train_intents.intent(q['question'], a)


def period_kind(text, as_of):
    from gen.parse import find_period
    from gen.textnorm import norm_question
    p = find_period(norm_question(text), as_of)
    return p['kind'] if p else 'none'


def dist(splits):
    from gen.surface import noise_stats
    out = {}
    for name, path in [('train', TRAIN)] + [(s.name, s) for s in splits]:
        Q = read_jsonl(path / 'questions.jsonl')
        A = {a['id']: a for a in read_jsonl(path / 'answers.jsonl')}
        n = len(Q)
        out[name] = {
            'n': n,
            'type': {k: round(v / n, 3) for k, v in collections.Counter(A[q['id']]['type'] for q in Q).most_common()},
            'bucket': {k: round(v / n, 3) for k, v in collections.Counter(bucket(q, A[q['id']]) for q in Q).most_common(14)},
            'period': {k: round(v / n, 3) for k, v in collections.Counter(
                period_kind(q['question'], dt.date.fromisoformat(q['as_of_date'])) for q in Q).most_common()},
            'noise': {k: round(v, 3) for k, v in noise_stats([q['question'] for q in Q]).items()},
            'q_per_shop': round(n / max(1, len({q['business_id'] for q in Q})), 1),
            'as_of_main_share': None,
        }
    return out


# ====================================================================== tokens
def tokens(split: Path, sample, seed=0):
    from gen.package import Split
    from gen.tokens import TokenCounter
    tc = TokenCounter()
    sp = Split(split, ROOT / 'outputs' / 'cache')
    Q = read_jsonl(split / 'questions.jsonl')
    rnd = random.Random(seed)
    by = collections.defaultdict(list)
    for q in Q:
        by[q['business_id']].append(q)
    out = []
    for bid, qs in sorted(by.items()):
        for q in rnd.sample(qs, min(sample, len(qs))):
            rec = {'business_id': bid, 'question': q['question'], 'as_of': q['as_of_date'], 'input': {'max_calls': 3}}
            msgs = sp.rebuild(rec, [], 0)
            p, _ = tc.count(msgs, 'x')
            out.append({'shop': bid, 'tokens': p, 'system_chars': len(msgs[0]['content']),
                        'user_chars': len(msgs[1]['content'])})
    return out, tc.exact


def pct(xs, ps=(50, 90, 99, 100)):
    xs = sorted(xs)
    return {p: xs[min(len(xs) - 1, int(len(xs) * p / 100))] for p in ps} if xs else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('splits', nargs='+')
    ap.add_argument('--what', default='load,cross,dist,tokens')
    ap.add_argument('--sample', type=int, default=40, help='cross: questions per shop; tokens: per shop / 10')
    ap.add_argument('--json')
    a = ap.parse_args()
    splits = [Path(s) for s in a.splits]
    for s in splits:
        forbid(s)
    what = a.what.split(',')
    report = {}
    if 'load' in what:
        rows = [dict(r, split=s.name) for s in splits for r in load_stats(s)]
        df = pd.DataFrame(rows)
        print(df.groupby('split')[['unreadable', 'tables', 'columns', 'rows', 'readme_chars']].agg(['sum', 'min', 'max']).to_string())
        print('unreadable files:', int(df.unreadable.sum()), '| formats:', dict(collections.Counter(df.formats)))
        report['load'] = rows
    if 'cross' in what:
        rows = [dict(r, split=s.name) for s in splits for r in cross(s, a.sample)]
        df = pd.DataFrame(rows)
        print(df.groupby(['intent', 'status']).size().unstack(fill_value=0).to_string())
        print(df.groupby(['family', 'status']).size().unstack(fill_value=0).to_string())
        bad = df[df.status != 'ok']
        for r in bad.head(25).itertuples():
            print('  ', r.split, r.shop, r.family, r.intent, getattr(r, 'id', ''), 'gold', getattr(r, 'gold', ''), 'ref', getattr(r, 'ref', ''))
        print(f'cross-check: {int((df.status == "ok").sum())} ok / {len(df)}')
        report['cross'] = rows
    if 'dist' in what:
        d = dist(splits)
        for k in ('type', 'bucket', 'period'):
            print(f'--- {k}')
            print(pd.DataFrame({n: v[k] for n, v in d.items()}).fillna(0).to_string())
        print('--- noise')
        print(pd.DataFrame({n: v['noise'] for n, v in d.items()}).to_string())
        report['dist'] = d
    if 'tokens' in what:
        rows, exact = [], False
        for s in splits:
            r, exact = tokens(s, max(1, a.sample // 10))
            rows += [dict(x, split=s.name) for x in r]
        t = [r['tokens'] for r in rows]
        print(f'first-turn prompt tokens ({"exact Gemma" if exact else "estimate"}), n={len(t)}: {pct(t)}')
        report['tokens'] = {'exact': exact, 'pct': pct(t), 'rows': rows}
    if a.json:
        Path(a.json).write_text(json.dumps(report, ensure_ascii=False, default=str, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
