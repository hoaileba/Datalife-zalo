"""Reference answers computed on the clean ledger (gen.ledger), following the train rulebook (§1-§10).

answer(ledger, spec, as_of, rules=Rules()) -> (type, value), type as in submission.jsonl; ('unanswerable', None) when
the shop's files do not carry what the question needs, or the period lies wholly outside the data.

A spec: {'intent': <name>, ...params, 'period': <periods spec>}. Every rule the train rulebook sets is a field of
Rules, so rulebook variants (gen.variants) change the answer the same way they change the rulebook text.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal

import numpy as np
import pandas as pd

from . import periods as P


@dataclass(frozen=True)
class Rules:
    exclude_returned: bool = True          # §1 orders with any return are out of revenue (whole order)
    count_delivering: bool = True          # §1 orders in delivery count
    week_start: int = 0                    # §2 Monday
    tet_start: tuple = (12, 23)            # §2 23 tháng Chạp
    tet_end: tuple = (1, 10)               # §2 mùng 10 tháng Giêng
    morning: tuple = (6, 13)               # §2 ca sáng 06:00-13:59
    afternoon: tuple = (14, 21)            # §2 ca chiều 14:00-21:59
    this_month_same_days: bool = True      # §2 tháng này vs tháng trước: same number of days
    cancel_rate_all_orders: bool = True    # §1 denominator: every order of the period (any status)
    revenue_shipping: bool = False         # §1 revenue excludes delivery fees
    revenue_order_discount: bool = False   # §1 order-level discounts not deducted
    service_fee_is_item: bool = False      # §3 'Phí phục vụ' is not an item (still revenue)
    debt_skip_methods: tuple = ('cod',)    # §4 COD orders are not debt
    debt_skip_channels: tuple = ('marketplace', 'shopee', 'lazada', 'tiktok')
    debt_age_from_order: bool = True       # §4 age from the order date
    avg_purchase_weighted: bool = True     # §5 weighted by quantity
    pct_decimals: int = 2
    # ---- rules a split rulebook may add or change (gen.rulebook_gen); defaults = the train rulebook's meaning
    sections: tuple = ()                   # industry sections the rulebook carries (gate the intents they define)
    addon_is_item: bool = True             # toppings / khăn lạnh are items unless the rulebook says otherwise
    service_prefix: str = 'dịch vụ'        # 'tiền công, doanh thu dịch vụ' = lines whose group starts with this
    guests_missing_as_one: bool = False    # an order without a guest count counts as one guest
    per_guest_round: int = 0               # decimals of revenue per guest (-3 = to the thousand đồng)
    seasons: tuple = ()                    # ((key, label, (m1, d1), (m2, d2)), ...); m1 > m2 = starts the year before
    bestseller_by: str = 'qty'             # 'bán chạy' ranks by quantity (or 'revenue')
    last_n_include_today: bool = True      # 'N ngày gần nhất' ends today (False: ends yesterday)
    repeat_min: int = 2                    # 'xe quay lại' = a plate with at least this many orders in the period


# ------------------------------------------------------------------ rounding and helpers
def half_up(x, places=0):
    q = Decimal(1).scaleb(-places)
    v = Decimal(str(float(x))).quantize(q, rounding=ROUND_HALF_UP)
    return int(v) if places == 0 else float(v)


def pct(a, b, rules):
    if b == 0:
        return None
    return half_up((a - b) / b * 100, rules.pct_decimals)


def share(a, b, rules):
    if b == 0:
        return None
    return half_up(a / b * 100, rules.pct_decimals)


class Unanswerable(Exception):
    pass


def need(L, *caps):
    for c in caps:
        if not L.has(c):
            raise Unanswerable(c)


def ts_end(d):
    return pd.Timestamp(d) + pd.Timedelta(days=1)          # exclusive end of day d


class View:
    """Cached derived tables of one ledger at one as_of."""

    def __init__(self, L, as_of, rules):
        self.L, self.as_of, self.R = L, as_of, rules
        o = L.orders
        self.orders_all = o[o.created < ts_end(as_of)].copy()       # records after today have not happened
        self.orders_all['day'] = self.orders_all.created.dt.normalize()
        bad = {'cancelled'} | ({'returned'} if rules.exclude_returned else set())
        if not rules.count_delivering:
            bad.add('delivering')
        self.valid = self.orders_all[~self.orders_all.status.isin(bad)]
        lines = L.lines.merge(self.orders_all[['order_id', 'day', 'created', 'status', 'customer_id']],
                              on='order_id', how='inner')
        prod = L.products.set_index('product_id')
        lines['kind'] = lines.product_id.map(prod['kind']).fillna('goods')
        self.lines_all = lines
        self.vlines = lines[lines.order_id.isin(self.valid.order_id)]
        rev = self.vlines.groupby('order_id').amount.sum()
        if rules.revenue_shipping or rules.revenue_order_discount:
            extra = self.valid.set_index('order_id')
            if rules.revenue_shipping:
                rev = rev.add(extra.shipping.fillna(0), fill_value=0)
            if rules.revenue_order_discount:
                rev = rev.sub(extra.discount.fillna(0), fill_value=0)
        self.order_rev = self.valid.set_index('order_id').assign(rev=rev).rev.fillna(0)
        self.data_start = pd.Timestamp(L.shop['start'])
        self.data_end = pd.Timestamp(min(L.shop['end'], as_of))

    # -------- periods
    def bounds(self, spec):
        s, e = P.bounds(spec, self.as_of, self.R)
        e = min(e, self.as_of)
        if pd.Timestamp(e) < self.data_start or pd.Timestamp(s) > self.data_end:
            raise Unanswerable('period outside data')
        return pd.Timestamp(s), pd.Timestamp(e)

    def in_period(self, df, spec, col='day'):
        s, e = self.bounds(spec)
        return df[(df[col] >= s) & (df[col] <= e)]

    def items(self, df):
        """Lines that are items (§3: the service-fee line is not an item; toppings when the rulebook says so)."""
        if not self.R.service_fee_is_item:
            df = df[df.kind != 'fee']
        return df if self.R.addon_is_item else df[df.kind != 'addon']

    def revenue(self, spec):
        o = self.in_period(self.valid, spec)
        return float(self.order_rev.reindex(o.order_id).sum())


def _name(L, pid):
    return L.products.set_index('product_id').name.get(pid, pid)


def _rank(series, k, ascending=False):
    """Values desc, ties by code asc (§9)."""
    df = series.rename('v').reset_index()
    key = df.columns[0]
    df = df.sort_values(['v', key], ascending=[ascending, True])
    return df.head(k)


def _unit_factor(L, pid, unit):
    if unit is None:
        return 1
    base = L.products.set_index('product_id').base_unit.get(pid)
    if base is not None and str(unit).lower() == str(base).lower():
        return 1
    u = L.units[(L.units.product_id == pid) & (L.units.unit.str.lower() == str(unit).lower())]
    if u.empty:
        return 1
    return float(u.factor.iloc[0])


def _as_number(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    xf = float(x)
    return int(xf) if xf == int(xf) else xf


# ------------------------------------------------------------------ intents
INTENTS = {}


def intent(name, *caps):
    def deco(fn):
        INTENTS[name] = (fn, caps)
        return fn
    return deco


@intent('revenue')
def _revenue(V, s):
    return 'number', half_up(V.revenue(s['period']))


@intent('revenue_list')
def _revenue_list(V, s):
    return 'list', [half_up(V.revenue(p)) for p in s['periods']]


def _ref(V, s):
    ref = s.get('ref')
    if ref == 'before_tet':
        return P.before_tet(s['period'], V.as_of, V.R)
    return ref or P.previous(s['period'], V.as_of, V.R)


@intent('revenue_change_pct')
def _revenue_change_pct(V, s):
    ref = _ref(V, s)
    a, b = V.revenue(s['period']), V.revenue(ref)
    v = pct(a, b, V.R)
    if v is None:
        raise Unanswerable('zero base')
    return 'percent', v


@intent('revenue_diff')
def _revenue_diff(V, s):
    ref = _ref(V, s)
    return 'number', half_up(V.revenue(s['period']) - V.revenue(ref))


@intent('revenue_trend_up')
def _trend(V, s):
    v = [V.revenue(p) for p in s['periods']]
    return 'boolean', all(b > a for a, b in zip(v, v[1:]))


@intent('best_month')
def _best_month(V, s):
    v = [(V.revenue(p), p) for p in s['periods']]
    best = max(v, key=lambda t: t[0])[1]
    return 'date', f"{best['y']:04d}-{best['m']:02d}"


@intent('best_day')
def _best_day(V, s):
    o = V.in_period(V.valid, s['period'])
    r = V.order_rev.reindex(o.order_id).groupby(o.day.values).sum()
    worst = s.get('worst', False)
    r = r.sort_index()
    d = r.idxmin() if worst else r.idxmax()
    return 'date', pd.Timestamp(d).strftime('%Y-%m-%d')


@intent('days_over')
def _days_over(V, s):
    o = V.in_period(V.valid, s['period'])
    r = V.order_rev.reindex(o.order_id).groupby(o.day.values).sum()
    return 'number', int((r >= s['threshold']).sum() if s.get('inclusive', True) else (r > s['threshold']).sum())


@intent('order_count')
def _order_count(V, s):
    return 'number', int(V.in_period(V.valid, s['period']).order_id.nunique())


@intent('orders_over')
def _orders_over(V, s):
    o = V.in_period(V.valid, s['period'])
    r = V.order_rev.reindex(o.order_id)
    return 'number', int((r >= s['threshold']).sum() if s.get('inclusive', True) else (r > s['threshold']).sum())


@intent('cancel_count')
def _cancel_count(V, s):
    o = V.in_period(V.orders_all, s['period'])
    return 'number', int((o.status == 'cancelled').sum())


@intent('cancel_rate')
def _cancel_rate(V, s):
    o = V.in_period(V.orders_all, s['period'])
    if not V.R.cancel_rate_all_orders:
        o = o[o.status != 'returned']
    return 'percent', share((o.status == 'cancelled').sum(), len(o), V.R)


@intent('avg_order')
def _avg_order(V, s):
    o = V.in_period(V.valid, s['period'])
    if len(o) == 0:
        raise Unanswerable('no orders')
    return 'number', half_up(V.order_rev.reindex(o.order_id).sum() / len(o))


def _item_lines(V, s):
    return V.in_period(V.vlines, s['period'])


@intent('revenue_item')
def _revenue_item(V, s):
    l = _item_lines(V, s)
    return 'number', half_up(l[l.product_id == s['item']].amount.sum())


@intent('qty_item')
def _qty_item(V, s):
    l = _item_lines(V, s)
    q = l[l.product_id == s['item']].base_qty.sum() / _unit_factor(V.L, s['item'], s.get('unit'))
    return 'number', _as_number(half_up(q, 2))


@intent('revenue_group', 'groups')
def _revenue_group(V, s):
    l = _item_lines(V, s)
    ids = V.L.products[V.L.products.group == s['group']].product_id
    return 'number', half_up(l[l.product_id.isin(ids)].amount.sum())


@intent('group_share', 'groups')
def _group_share(V, s):
    l = _item_lines(V, s)
    ids = V.L.products[V.L.products.group == s['group']].product_id
    return 'percent', share(l[l.product_id.isin(ids)].amount.sum(), V.revenue(s['period']), V.R)


@intent('qty_unit')
def _qty_unit(V, s):
    l = V.items(_item_lines(V, s))
    ids = V.L.products[V.L.products.base_unit.str.lower() == s['unit'].lower()].product_id
    return 'number', _as_number(half_up(l[l.product_id.isin(ids)].base_qty.sum(), 2))


@intent('qty_size')
def _qty_size(V, s):
    l = V.items(_item_lines(V, s))
    names = V.L.products.set_index('product_id').name
    end = f"({s['size'].upper()})" if s.get('style', 'paren') == 'paren' else f"SIZE {s['size'].upper()}"
    mask = l.product_id.map(names).str.strip().str.upper().str.endswith(end)
    return 'number', _as_number(l[mask].base_qty.sum())


@intent('top_items')
def _top_items(V, s):
    l = V.items(_item_lines(V, s))
    by = s.get('by', 'qty')
    if by == 'qty' and V.R.bestseller_by == 'revenue':
        by = 'revenue'                             # the rulebook ranks 'bán chạy' by revenue
    if by == 'qty':
        v = l.groupby('product_id').base_qty.sum()
    elif by == 'revenue':
        v = l.groupby('product_id').amount.sum()
    elif by == 'profit':
        need(V.L, 'unit_cost')
        v = (l.amount - l.qty * l.unit_cost).groupby(l.product_id).sum()
    else:
        raise ValueError(by)
    if v.empty:
        raise Unanswerable('no sales')
    top = _rank(v, s.get('k', 1))
    names = [_name(V.L, p) for p in top.product_id]
    return ('string', names[0]) if s.get('k', 1) == 1 and not s.get('as_list') else ('list', names)


@intent('items_min_orders')
def _items_min_orders(V, s):
    l = V.items(_item_lines(V, s))
    n = l.groupby('product_id').order_id.nunique()
    return 'number', int((n >= s['n']).sum())


def _customer_key(V):
    """§3: by customer code; walk-ins (no code) are not customers."""
    need(V.L, 'customers')
    return 'customer_id'


@intent('top_customers', 'customer_ids')
def _top_customers(V, s):
    o = V.in_period(V.valid, s['period'])
    o = o[o.customer_id.notna()]
    if s.get('by', 'revenue') == 'revenue':
        v = V.order_rev.reindex(o.order_id).groupby(o.customer_id.values).sum()
    else:
        v = o.groupby('customer_id').order_id.nunique()
    v.index.name = 'customer_id'
    if v.empty:
        raise Unanswerable('no customer orders')
    top = _rank(v, s.get('k', 1))
    names = V.L.customers.set_index('customer_id').name
    out = [names.get(c, c) for c in top.customer_id]
    return ('string', out[0]) if s.get('k', 1) == 1 and not s.get('as_list') else ('list', out)


@intent('customers_min_orders', 'customer_ids')
def _customers_min_orders(V, s):
    o = V.in_period(V.valid, s['period'])
    n = o[o.customer_id.notna()].groupby('customer_id').order_id.nunique()
    return 'number', int((n >= s['n']).sum())


@intent('customers_min_orders_share', 'customer_ids')
def _customers_min_orders_share(V, s):
    o = V.in_period(V.valid, s['period'])
    n = o[o.customer_id.notna()].groupby('customer_id').order_id.nunique()
    return 'percent', share((n >= s['n']).sum(), len(n), V.R)


@intent('customer_count', 'customer_ids')
def _customer_count(V, s):
    o = V.in_period(V.valid, s['period'])
    return 'number', int(o.customer_id.dropna().nunique())


def _group_orders(V, s):
    o = V.in_period(V.valid, s['period'])
    grp = V.L.customers.set_index('customer_id')['group']
    return o[o.customer_id.map(grp) == s['group']]


@intent('cust_group_revenue', 'customer_groups')
def _cust_group_revenue(V, s):
    return 'number', half_up(V.order_rev.reindex(_group_orders(V, s).order_id).sum())


@intent('cust_group_share', 'customer_groups')
def _cust_group_share(V, s):
    a = V.order_rev.reindex(_group_orders(V, s).order_id).sum()
    return 'percent', share(a, V.revenue(s['period']), V.R)


def _rev_by(V, s, col, values):
    o = V.in_period(V.valid, s['period'])
    return [half_up(V.order_rev.reindex(o[o[col] == v].order_id).sum()) for v in values]


@intent('payment_revenue', 'payment_method')
def _payment_revenue(V, s):
    v = _rev_by(V, s, 'payment_method', s['methods'])
    return ('list', v) if len(v) > 1 else ('number', v[0])


@intent('payment_share', 'payment_method')
def _payment_share(V, s):
    return 'percent', share(_rev_by(V, s, 'payment_method', [s['method']])[0], V.revenue(s['period']), V.R)


@intent('channel_revenue', 'channel')
def _channel_revenue(V, s):
    v = _rev_by(V, s, 'channel', s['channels'])
    return ('list', v) if len(v) > 1 else ('number', v[0])


@intent('channel_share', 'channel')
def _channel_share(V, s):
    return 'percent', share(_rev_by(V, s, 'channel', [s['channel']])[0], V.revenue(s['period']), V.R)


def _shift_orders(V, o, shift):
    h0, h1 = V.R.morning if shift == 'morning' else V.R.afternoon
    h = o.created.dt.hour
    return o[(h >= h0) & (h <= h1)]


@intent('shift_revenue', 'time')
def _shift_revenue(V, s):
    o = _shift_orders(V, V.in_period(V.valid, s['period']), s['shift'])
    return 'number', half_up(V.order_rev.reindex(o.order_id).sum())


@intent('shift_orders', 'time')
def _shift_orders_count(V, s):
    o = _shift_orders(V, V.in_period(V.valid, s['period']), s['shift'])
    return 'number', int(len(o))


@intent('shift_change_pct', 'time')
def _shift_change(V, s):
    o = V.in_period(V.valid, s['period'])
    if s.get('measure') == 'orders':
        a, b = len(_shift_orders(V, o, 'afternoon')), len(_shift_orders(V, o, 'morning'))
        return 'percent', pct(a, b, V.R)
    a = V.order_rev.reindex(_shift_orders(V, o, 'afternoon').order_id).sum()
    b = V.order_rev.reindex(_shift_orders(V, o, 'morning').order_id).sum()
    return 'percent', pct(a, b, V.R)


@intent('staff_revenue', 'staff')
def _staff_revenue(V, s):
    o = V.in_period(V.valid, s['period'])
    return 'number', half_up(V.order_rev.reindex(o[o.staff_id == s['staff']].order_id).sum())


@intent('top_staff', 'staff')
def _top_staff(V, s):
    o = V.in_period(V.valid, s['period'])
    v = V.order_rev.reindex(o.order_id).groupby(o.staff_id.values).sum()
    v.index.name = 'staff_id'
    if v.empty:
        raise Unanswerable('no orders')
    sid = _rank(v, 1).staff_id.iloc[0]
    return 'string', sid if s.get('as_code', True) else V.L.staff.set_index('staff_id').name.get(sid, sid)


def _rx_ids(V, rx):
    d = V.L.drugs
    ids = set(d[d.rx].product_id)
    allp = set(V.L.products.product_id)
    return ids if rx else allp - ids


@intent('rx_revenue', 'drugs')
def _rx_revenue(V, s):
    l = _item_lines(V, s)
    return 'number', half_up(l[l.product_id.isin(_rx_ids(V, s['rx']))].amount.sum())


@intent('rx_share', 'drugs')
def _rx_share(V, s):
    l = _item_lines(V, s)
    a = l[l.product_id.isin(_rx_ids(V, s['rx']))].amount.sum()
    return 'percent', share(a, V.revenue(s['period']), V.R)


@intent('ingredient_revenue', 'drugs')
def _ingredient_revenue(V, s):
    l = _item_lines(V, s)
    d = V.L.drugs
    ids = d[d.ingredient.str.strip().str.lower() == s['ingredient'].strip().lower()].product_id
    return 'number', half_up(l[l.product_id.isin(ids)].amount.sum())


@intent('gross_profit', 'unit_cost')
def _gross_profit(V, s):
    l = _item_lines(V, s)
    return 'number', half_up((l.amount - l.qty * l.unit_cost).sum())


@intent('net_profit', 'unit_cost', 'expenses')
def _net_profit(V, s):
    l = _item_lines(V, s)
    s0, e0 = V.bounds(s['period'])
    ex = V.L.expenses
    ex = ex[(ex.date >= s0) & (ex.date <= e0)].amount.sum()
    return 'number', half_up((l.amount - l.qty * l.unit_cost).sum() - ex)


def _purchases(V, s):
    p = V.L.purchases
    p = p[(p.status != 'cancelled') & (p.date < ts_end(V.as_of))]
    s0, e0 = V.bounds(s['period'])
    return p[(p.date >= s0) & (p.date <= e0)]


@intent('purchase_total', 'purchases')
def _purchase_total(V, s):
    return 'number', half_up(_purchases(V, s).total.sum())


@intent('top_supplier', 'purchases')
def _top_supplier(V, s):
    p = _purchases(V, s)
    v = p.groupby('supplier_id').total.sum()
    if v.empty:
        raise Unanswerable('no purchases in the period')
    sid = _rank(v, 1).supplier_id.iloc[0]
    return 'string', V.L.suppliers.set_index('supplier_id').name.get(sid, sid)


@intent('avg_purchase_price', 'purchases')
def _avg_purchase_price(V, s):
    p = _purchases(V, s)
    pl = V.L.purchase_lines
    pl = pl[pl.purchase_id.isin(p.purchase_id) & (pl.product_id == s['item'])].copy()
    if pl.empty:
        raise Unanswerable('no purchase of the item in the month')
    unit = s.get('unit')
    f_line = pl.unit.map(lambda u: _unit_factor(V.L, s['item'], u))
    f_q = _unit_factor(V.L, s['item'], unit)
    qty = pl.qty * f_line / f_q                   # in the asked unit
    cost = pl.unit_cost / f_line * f_q
    if V.R.avg_purchase_weighted:
        return 'number', half_up((qty * cost).sum() / qty.sum())
    return 'number', half_up(cost.mean())


@intent('purchase_minus_sales', 'purchases')
def _purchase_minus_sales(V, s):
    p = _purchases(V, s)
    pl = V.L.purchase_lines
    pl = pl[pl.purchase_id.isin(p.purchase_id) & (pl.product_id == s['item'])]
    bought = (pl.qty * pl.unit.map(lambda u: _unit_factor(V.L, s['item'], u))).sum()
    l = _item_lines(V, s)
    sold = l[l.product_id == s['item']].base_qty.sum()
    return 'number', _as_number(half_up((bought - sold) / _unit_factor(V.L, s['item'], s.get('unit')), 2))


@intent('price_on_day')
def _price_on_day(V, s):
    l = V.lines_all
    d = pd.Timestamp(s['date'])
    l = l[(l.day == d) & (l.product_id == s['item'])]
    if l.empty:
        raise Unanswerable('item not sold that day')
    f = l.unit.map(lambda u: _unit_factor(V.L, s['item'], u))
    per_base = (l.unit_price / f).round(6)
    v = per_base.mode().iloc[0] * _unit_factor(V.L, s['item'], s.get('unit'))
    return 'number', _as_number(half_up(v, 2))


@intent('price_effect')
def _price_effect(V, s):
    n, d = s['n'], s['date']
    after = {'kind': 'range', 'start': d, 'end': d + dt.timedelta(days=n - 1)}
    before = {'kind': 'range', 'start': d - dt.timedelta(days=n), 'end': d - dt.timedelta(days=1)}
    l = V.vlines[V.vlines.product_id == s['item']]
    qa = V.in_period(l, after).base_qty.sum()
    qb = V.in_period(l, before).base_qty.sum()
    v = pct(qa, qb, V.R)
    if v is None:
        raise Unanswerable('no sales before')
    return 'percent', v


# ---- stock
def _stock_at(V, date):
    m = V.L.stock_moves
    m = m[m.time < ts_end(date)]
    sort = ['time', 'seq'] if 'seq' in m.columns else ['time']
    return m.sort_values(sort).groupby('product_id').balance.last()


@intent('stock_end', 'stock')
def _stock_end(V, s):
    b = _stock_at(V, s['date']).get(s['item'], 0)
    return 'number', _as_number(half_up(b / _unit_factor(V.L, s['item'], s.get('unit')), 2))


@intent('stock_big_small', 'stock')
def _stock_big_small(V, s):
    b = int(_stock_at(V, s['date']).get(s['item'], 0))
    f = int(_unit_factor(V.L, s['item'], s['big_unit']))
    return 'list', [b // f, b % f]


@intent('stock_value', 'stock', 'catalog_cost')
def _stock_value(V, s):
    b = _stock_at(V, s['date'])
    b = b[b > 0]
    cost = V.L.products.set_index('product_id').cost
    return 'number', half_up((b * cost.reindex(b.index)).sum())


@intent('out_of_stock_count', 'stock')
def _out_of_stock(V, s):
    b = _stock_at(V, s['date'])
    goods = V.L.products[V.L.products.kind == 'goods'].product_id
    return 'number', int((b.reindex(goods).fillna(0) <= 0).sum())


@intent('unsold_count')
def _unsold(V, s):
    s0, e0 = V.bounds(s['period'])
    l = V.items(V.vlines)
    before = set(l[l.day < s0].product_id)
    during = set(l[(l.day >= s0) & (l.day <= e0)].product_id)
    return 'number', len(before - during)


# ---- lots (pharmacy)
def _lot_left(V, date):
    lots = V.L.lots.merge(V.L.purchases[['purchase_id', 'date', 'status']], on='purchase_id', how='left')
    lots = lots[(lots.date < ts_end(date)) & (lots.status != 'cancelled')]
    ll = V.L.line_lots.merge(V.lines_all[['order_id', 'line_no', 'created', 'status']].drop_duplicates(
        ['order_id', 'line_no']), on=['order_id', 'line_no'])
    ll = ll[(ll.created < ts_end(date)) & (ll.status != 'cancelled')]
    out = ll.groupby('lot').base_qty.sum() - ll.groupby('lot').returned_base_qty.sum()
    lots = lots.assign(left=lots.base_qty - lots.lot.map(out).fillna(0))
    return lots[lots.left > 0]


def _expiring(V, s):
    d = pd.Timestamp(s['date'])
    end = d + pd.Timedelta(days=s['n'])
    lots = _lot_left(V, s['date'])
    return lots[(lots.expiry >= d) & (lots.expiry <= end)]


@intent('expiring_items', 'lots')
def _expiring_items(V, s):
    e = _expiring(V, s).sort_values(['expiry', 'product_id'])
    ids = list(dict.fromkeys(e.product_id))
    return 'list', [_name(V.L, p) for p in ids]


@intent('expiring_count', 'lots')
def _expiring_count(V, s):
    return 'number', int(_expiring(V, s).product_id.nunique())


@intent('expiring_value', 'lots')
def _expiring_value(V, s):
    e = _expiring(V, s)
    return 'number', half_up((e.left * e.base_cost).sum())


@intent('nearest_lot_expiry', 'lots')
def _nearest_lot(V, s):
    lots = _lot_left(V, s['date'])
    lots = lots[(lots.product_id == s['item']) & (lots.expiry >= pd.Timestamp(s['date']))]
    if lots.empty:
        raise Unanswerable('no lot left')
    return 'date', lots.expiry.min().strftime('%Y-%m-%d')


# ---- debt
def _debt_orders(V, date):
    o = V.orders_all
    o = o[(o.created < ts_end(date)) & (o.status != 'cancelled')]
    o = o[~o.payment_method.isin(V.R.debt_skip_methods) & ~o.channel.fillna('').isin(V.R.debt_skip_channels)]
    pay = V.L.payments
    paid = pay[pay.time < ts_end(date)].groupby('order_id').amount.sum()
    o = o.assign(left=o.total - o.order_id.map(paid).fillna(0))
    return o[o.left > 0.5]


@intent('debt_total', 'debt')
def _debt_total(V, s):
    return 'number', half_up(_debt_orders(V, s['date']).left.sum())


@intent('debt_customers', 'debt', 'customer_ids')
def _debt_customers(V, s):
    o = _debt_orders(V, s['date'])
    return 'number', int(o.customer_id.dropna().nunique())


@intent('debt_top', 'debt', 'customer_ids')
def _debt_top(V, s):
    o = _debt_orders(V, s['date'])
    o = o[o.customer_id.notna()]
    v = o.groupby('customer_id').left.sum()
    top = _rank(v, s.get('k', 5))
    names = V.L.customers.set_index('customer_id').name
    return 'table', {'columns': ['khach_hang', 'so_tien_no'],
                     'rows': [[names.get(c, c), half_up(x)] for c, x in zip(top.customer_id, top.v)]}


def _age(V, o, date):
    return (pd.Timestamp(date) - o.created.dt.normalize()).dt.days


@intent('debt_over_age', 'debt')
def _debt_over_age(V, s):
    o = _debt_orders(V, s['date'])
    return 'number', half_up(o[_age(V, o, s['date']) > s['days']].left.sum())


@intent('debt_aging', 'debt')
def _debt_aging(V, s):
    o = _debt_orders(V, s['date'])
    a = _age(V, o, s['date'])
    edges = s.get('edges', [7, 15])
    out, lo = [], -1
    for e in edges:
        out.append(half_up(o[(a > lo) & (a <= e)].left.sum()))
        lo = e
    out.append(half_up(o[a > lo].left.sum()))
    return 'list', out


def _debt_flows(V, s, customer=None):
    o = V.orders_all
    o = o[(o.payment_method == 'debt') & (o.status != 'cancelled')]
    if customer is not None:
        o = o[o.customer_id == customer]
    pay = V.L.payments.merge(o[['order_id', 'day', 'total']], on='order_id')
    pay = pay[pay.time < ts_end(V.as_of)]
    pay['pday'] = pay.time.dt.normalize()
    s0, e0 = V.bounds(s['period'])
    new_o = o[(o.day >= s0) & (o.day <= e0)]
    same_day = pay[pay.pday == pay.day].groupby('order_id').amount.sum()
    new = (new_o.total - new_o.order_id.map(same_day).fillna(0)).sum()
    later = pay[(pay.pday > pay.day) & (pay.pday >= s0) & (pay.pday <= e0)].amount.sum()
    return half_up(new), half_up(later)


@intent('debt_collected', 'debt')
def _debt_collected(V, s):
    return 'number', _debt_flows(V, s)[1]


@intent('debt_new', 'debt')
def _debt_new(V, s):
    return 'number', _debt_flows(V, s)[0]


@intent('debt_new_paid', 'debt', 'customer_ids')
def _debt_new_paid(V, s):
    return 'list', list(_debt_flows(V, s, s['customer']))


@intent('deliveries_count', 'deliveries')
def _deliveries(V, s):
    d = V.L.deliveries
    d = d.assign(day=pd.to_datetime(d.date).dt.normalize())
    return 'number', int(len(V.in_period(d, s['period'])))


# ---- split rulebook sections (gen.rulebook_gen): tables/guests, services, vehicles
def _visits(V, o):
    v = V.L.visits.set_index('order_id')
    return v.reindex(o.order_id)


@intent('guests_total', 'guests')
def _guests_total(V, s):
    o = V.in_period(V.valid, s['period'])
    g = _visits(V, o).guests
    if V.R.guests_missing_as_one:
        g = g.fillna(1)
    return 'number', int(g.fillna(0).sum())


@intent('revenue_per_guest', 'guests')
def _revenue_per_guest(V, s):
    o = V.in_period(V.valid, s['period'])
    g = _visits(V, o).guests
    if V.R.guests_missing_as_one:
        g = g.fillna(1)
    n = g.fillna(0).sum()
    if n == 0:
        raise Unanswerable('no guests')
    return 'number', _as_number(half_up(V.order_rev.reindex(o.order_id).sum() / n, V.R.per_guest_round)
                                if V.R.per_guest_round >= 0 else
                                half_up(V.order_rev.reindex(o.order_id).sum() / n / 10 ** -V.R.per_guest_round)
                                * 10 ** -V.R.per_guest_round)


@intent('area_revenue', 'tables')
def _area_revenue(V, s):
    o = V.in_period(V.valid, s['period'])
    a = _visits(V, o).area.values
    return 'number', half_up(V.order_rev.reindex(o.order_id[a == s['area']]).sum())


def table_revenue(V, s):
    o = V.in_period(V.valid, s['period'])
    t = _visits(V, o).table
    keep = t.notna().values
    v = V.order_rev.reindex(o.order_id[keep]).groupby(t[keep].values).sum()
    v.index.name = 'table'
    return v


@intent('top_table', 'tables')
def _top_table(V, s):
    v = table_revenue(V, s)
    if v.empty:
        raise Unanswerable('no table orders')
    return 'string', str(_rank(v, 1).table.iloc[0])


def _service_mask(V, l):
    g = l.product_id.map(V.L.products.set_index('product_id').group).fillna('').astype(str).str.strip().str.lower()
    return g.str.startswith(V.R.service_prefix.lower())


@intent('service_revenue', 'groups')
def _service_revenue(V, s):
    l = _item_lines(V, s)
    m = _service_mask(V, l)
    if s.get('part') == 'goods':                  # the rest: parts and goods (a service fee line is no good)
        m = ~m & (l.kind != 'fee')
    return 'number', half_up(l[m].amount.sum())


@intent('service_share', 'groups')
def _service_share(V, s):
    l = _item_lines(V, s)
    return 'percent', share(l[_service_mask(V, l)].amount.sum(), V.revenue(s['period']), V.R)


def _plate_orders(V, s):
    o = V.in_period(V.valid, s['period'])
    p = _visits(V, o).plate
    return p[p.notna()]


@intent('vehicle_count', 'plates')
def _vehicle_count(V, s):
    return 'number', int(_plate_orders(V, s).nunique())


@intent('repeat_vehicles', 'plates')
def _repeat_vehicles(V, s):
    c = _plate_orders(V, s).value_counts()
    return 'number', int((c >= s.get('n', V.R.repeat_min)).sum())


# ------------------------------------------------------------------ entry point
def answer(L, spec, as_of, rules: Rules = Rules(), view: View | None = None):
    if spec['intent'] == 'unanswerable':
        return 'unanswerable', None
    fn, caps = INTENTS[spec['intent']]
    V = view if view is not None and view.as_of == as_of and view.R == rules else View(L, as_of, rules)
    try:
        need(L, *caps)
        return fn(V, spec)
    except Unanswerable:
        return 'unanswerable', None
