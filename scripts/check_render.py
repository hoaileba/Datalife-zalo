"""Render a ledger in every applicable family and read each shop back with the production reader.

For each family: no unreadable files; the lines table found; line rows within the injected-duplicate tolerance;
revenue (rulebook §1: lines of orders neither cancelled nor returned) recovered per month from the files equals the
ledger's. Prints one row per family; exit code 1 on any failure.

usage: PYTHONPATH=src:. python scripts/check_render.py [shop_dir_or_ledger.pkl] [--seed N] [--out DIR] [--families HEDC]
       PYTHONPATH=src:. python scripts/check_render.py --sim grocery,cafe --sim-seeds 1,2 --days 200
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from datamate.data import load_business  # noqa: E402
from gen.ledger import Ledger, load_sqlite_pos  # noqa: E402
from gen.render import families_for, render  # noqa: E402

CALENDAR = ROOT / 'data' / 'train' / 'calendar.csv'
SCRATCH = Path('/tmp/claude-1000/-mnt-ssd4t-dungnd4-zac-2026-datamate-v4/c29ef651-7697-4b73-926f-a033630614e4/scratchpad')


def ledger_revenue(L):
    o = L.orders
    ok = set(o.loc[o['status'].isin(['completed', 'delivering']), 'order_id'])
    ln = L.lines[L.lines['order_id'].isin(ok)].merge(o[['order_id', 'created']], on='order_id')
    month = pd.to_datetime(ln['created']).dt.to_period('M')
    return ln.groupby(month)['amount'].sum()


def find_lines_table(biz, cols):
    want = set(cols.values())
    best = None
    for name, df in biz.tables.items():
        if want <= set(df.columns) and (best is None or len(df) > len(biz.tables[best])):
            best = name
    return best


def recovered_revenue_sqlite(biz):
    t = {n.lower(): df for n, df in biz.tables.items()}
    ln = t['chi_tiet_don']
    o = t['don_hang']
    col = lambda df, *names: next(c for c in df.columns if c.lower().replace('_', '') in names)
    oid_l, amt = col(ln, 'mahoadon'), col(ln, 'trigia')
    content = [c for c in ln.columns if '__' not in c]
    n_raw = len(ln)
    ln = ln.drop_duplicates(subset=content)
    oid_o, st, created = col(o, 'mahoadon'), col(o, 'tinhtrang'), col(o, 'thoigianlap')
    ok = o[o[st].isin(['completed', 'shipping'])]
    m = ln.merge(ok[[oid_o, created]], left_on=oid_l, right_on=oid_o)
    rev = m.groupby(pd.to_datetime(m[created]).dt.to_period('M'))[amt].sum()
    return rev, n_raw, len(ln), {}


def recovered_revenue(biz, meta, status_map, keyed, orders_meta=None):
    cols = meta['cols']
    name = find_lines_table(biz, cols)
    if name is None:
        raise AssertionError(f'lines table not found for headers {sorted(cols.values())}')
    df = biz.tables[name].copy()
    n_raw = len(df)
    content = [c for c in df.columns if '__' not in c]
    if keyed:
        df = df.drop_duplicates(subset=content)
    if 'status' not in cols:                          # status/date on the invoice list: join by order id
        oc = orders_meta['cols']
        on = find_lines_table(biz, oc)
        if on is None:
            raise AssertionError('orders table not found')
        o = biz.tables[on]
        date_col = oc.get('date') or oc.get('created')
        o = o[[oc['order_id'], oc['status'], date_col]].drop_duplicates(subset=[oc['order_id']])
        o.columns = ['__oid', '__status', '__date']
        df = df.merge(o, left_on=cols['order_id'], right_on='__oid', how='left')
        cols = {**cols, 'status': '__status', 'date': '__date'}
    st = df[cols['status']].map(status_map)
    unknown = df.loc[st.isna(), cols['status']].value_counts().head(5).to_dict()
    amount = pd.to_numeric(df[cols['amount']], errors='coerce')
    bad_amount = int(amount.isna().sum())
    date_key = 'date' if 'date' in cols else 'created'
    dates = pd.to_datetime(df[cols[date_key]], errors='coerce')
    bad_dates = int(dates.isna().sum())
    if 'order_id' in cols:
        returned = set(df.loc[st == 'returned', cols['order_id']])
        if 'qty' in cols:
            q = pd.to_numeric(df[cols['qty']], errors='coerce')
            returned |= set(df.loc[q < 0, cols['order_id']])
        good = st.isin(['completed', 'delivering']) & ~df[cols['order_id']].isin(returned)
    else:
        good = st.isin(['completed', 'delivering'])
    rev = amount[good].groupby(dates[good].dt.to_period('M')).sum()
    issues = {}
    if unknown:
        issues['unknown_status'] = unknown
    if bad_amount:
        issues['unparsed_amount'] = bad_amount
    if bad_dates:
        issues['unparsed_dates'] = bad_dates
    return rev, n_raw, len(df), issues


def check_family(L, fam, out_root, seed):
    rng = np.random.default_rng(seed)
    out = Path(out_root) / f'{L.shop["business_id"]}_{fam}'
    t0 = time.time()
    res = render(L, fam, out, rng)
    t_render = time.time() - t0
    biz = load_business(out, CALENDAR)
    issues = {}
    if biz.unreadable:
        issues['unreadable'] = biz.unreadable
    if fam == 'H':
        rev, n_raw, n_dedup, more = recovered_revenue_sqlite(biz)
    else:
        rev, n_raw, n_dedup, more = recovered_revenue(biz, res['extras']['lines'], res['extras']['status_map'],
                                                     keyed='order_id' in res['extras']['lines']['cols'],
                                                     orders_meta=res['extras'].get('orders'))
    issues.update(more)
    gold = ledger_revenue(L)
    both = pd.concat([gold.rename('gold'), rev.rename('got')], axis=1).fillna(0)
    diff = both[(both['gold'] - both['got']).abs() > 0.5]
    if len(diff):
        issues['revenue_months_off'] = {str(k): (int(r.gold), int(r.got)) for k, r in diff.head(4).iterrows()}
    n_lines = len(L.lines)
    dups = res['extras'].get('duplicate_rows', 0)
    totals_rows = n_dedup
    expected = n_lines + (len(L.returns) * 3 if fam == 'C' else 0)
    if not (n_lines <= totals_rows <= expected) and fam != 'C':
        issues['line_rows'] = (n_lines, totals_rows)
    if fam == 'C' and not (n_lines <= totals_rows <= expected):
        issues['line_rows'] = (n_lines, totals_rows)
    return {'family': fam, 'files': len(res['files']), 'rows_read': n_raw, 'rows_dedup': totals_rows,
            'ledger_lines': n_lines, 'dups_injected': dups, 'revenue_gold': int(gold.sum()), 'revenue_got': int(rev.sum()),
            'caps': len(res['caps']), 'verbosity': res['noise'].verbosity, 'sec': round(t_render, 1), 'issues': issues}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('source', nargs='?', default=str(ROOT / 'data' / 'train' / 'data' / 'biz_123'))
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--out', default=None)
    ap.add_argument('--families', default=None)
    ap.add_argument('--sim', default=None, help="comma list of industries for gen.sim ledgers ('all' = every one)")
    ap.add_argument('--sim-seeds', default='1')
    ap.add_argument('--days', type=int, default=200, help='sim span in days (speed)')
    a = ap.parse_args()
    out_root = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix='render_', dir=SCRATCH if SCRATCH.exists() else None))
    if a.sim:
        failed = 0
        for L in sim_ledgers(a.sim, a.sim_seeds, a.days):
            failed += run_ledger(L, a, out_root)
        sys.exit(1 if failed else 0)
    src = Path(a.source)
    L = Ledger.load(src) if src.suffix == '.pkl' else load_sqlite_pos(src)
    sys.exit(1 if run_ledger(L, a, out_root) else 0)


INDUSTRIES = ['grocery', 'cafe', 'building', 'pharmacy', 'restaurant', 'cosmetics', 'mother_baby', 'stationery',
              'bakery', 'motorbike_repair', 'pet_shop', 'agri_supply']


def sim_ledgers(industries, seeds, days):
    import datetime as dt
    from gen.sim import make_spec, simulate
    inds = INDUSTRIES if industries == 'all' else industries.split(',')
    for ind in inds:
        for sd in (int(x) for x in seeds.split(',')):
            spec = make_spec(ind, np.random.default_rng(sd), f'syn_{ind}_{sd}')
            spec['end'] = spec['start'] + dt.timedelta(days=days)
            yield simulate(spec, sd)


def run_ledger(L, a, out_root):
    """Check every applicable family of one ledger; returns the number of failing families."""
    fams = [f for f in families_for(L) if not a.families or f in a.families]
    print(f'{L.shop["business_id"]}: {len(L.orders)} orders, {len(L.lines)} lines -> {out_root}')
    print(f'{"fam":3} {"files":>5} {"read":>7} {"dedup":>7} {"ledger":>7} {"dups":>5} {"revenue_gold":>13} '
          f'{"revenue_got":>13} {"caps":>4} {"readme":>7} {"sec":>5}  issues')
    failed = 0
    for i, fam in enumerate(fams):
        try:
            r = check_family(L, fam, out_root, a.seed + i)
        except Exception as exc:                      # report and continue
            import traceback
            traceback.print_exc()
            print(f'{fam:3} FAILED {type(exc).__name__}: {exc}')
            failed += 1
            continue
        failed += bool(r['issues'])
        print(f'{fam:3} {r["files"]:>5} {r["rows_read"]:>7} {r["rows_dedup"]:>7} {r["ledger_lines"]:>7} '
              f'{r["dups_injected"]:>5} {r["revenue_gold"]:>13} {r["revenue_got"]:>13} {r["caps"]:>4} '
              f'{r["verbosity"]:>7} {r["sec"]:>5}  {r["issues"] or "ok"}', flush=True)
    return failed


if __name__ == '__main__':
    main()
