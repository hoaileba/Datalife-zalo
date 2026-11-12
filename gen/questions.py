"""Question specs for a ledger: intents in train proportions, parameters drawn from the shop's own data, as_of dates
like train (one main as_of = end of data for most questions, random ones for relative periods), answers by the oracle.

sample(L, rng, n) -> list of {'spec', 'as_of', 'type', 'answer'} (unanswerable ones included when the shop lacks
what the intent needs, or the period lies outside the data). Ranking questions with a tie at the k boundary are
dropped (evaluation.md), as are answers that are empty/None.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from . import periods as P
from .oracle import INTENTS, Rules, View, answer

# intent -> weight (≈ train shares measured on the 3000 questions; rare intents get a floor so they appear)
WEIGHTS = {
    'revenue': 14, 'revenue_item': 4, 'revenue_group': 3, 'group_share': 5, 'order_count': 6, 'avg_order': 5.5,
    'cancel_rate': 4.5, 'cancel_count': 3.5, 'best_day': 4, 'revenue_change_pct': 6, 'revenue_list': 1,
    'revenue_trend_up': 0.6, 'best_month': 0.6, 'days_over': 0.6, 'orders_over': 0.8, 'top_items': 3,
    'top_customers': 2, 'customers_min_orders': 1.2, 'customers_min_orders_share': 0.8, 'items_min_orders': 0.6,
    'cust_group_revenue': 0.8, 'cust_group_share': 0.8, 'payment_revenue': 0.5, 'channel_revenue': 0.5,
    'channel_share': 0.3, 'shift_revenue': 1.5, 'shift_orders': 0.6, 'shift_change_pct': 0.6, 'staff_revenue': 0.4,
    'top_staff': 0.3, 'rx_revenue': 1.5, 'rx_share': 0.8, 'ingredient_revenue': 1, 'gross_profit': 0.4,
    'net_profit': 0.3, 'purchase_total': 1.5, 'top_supplier': 0.3, 'avg_purchase_price': 1, 'purchase_minus_sales': 0.3,
    'price_on_day': 2, 'price_effect': 2.8, 'qty_item': 2.6, 'qty_unit': 1, 'qty_size': 2.6, 'stock_end': 1.2,
    'stock_big_small': 0.6, 'stock_value': 0.5, 'out_of_stock_count': 0.4, 'unsold_count': 2.5,
    'expiring_items': 0.3, 'expiring_count': 0.3, 'expiring_value': 0.3, 'nearest_lot_expiry': 0.4,
    'debt_total': 0.8, 'debt_customers': 0.4, 'debt_top': 0.6, 'debt_over_age': 0.3, 'debt_aging': 0.2,
    'debt_collected': 0.8, 'debt_new_paid': 0.6, 'deliveries_count': 0.5, 'customer_count': 0.3,
    'payment_share': 0.2, 'revenue_diff': 0.4, 'debt_new': 0.1, 'unanswerable': 1.0,
    # split-rulebook sections (gen.rulebook_gen): drawn only in shops of those trades whose rulebook defines them
    # (a trade's own measures: ~15-20 % of the questions of its shops, as a test of that trade would ask them)
    'guests_total': 7, 'revenue_per_guest': 7, 'area_revenue': 4, 'top_table': 3,
    'service_revenue': 9, 'service_share': 5, 'vehicle_count': 6, 'repeat_vehicles': 6,
}
INDUSTRY_ONLY = {'qty_size': ('cafe',), 'rx_revenue': ('pharmacy',), 'rx_share': ('pharmacy',),
                 'ingredient_revenue': ('pharmacy',), 'expiring_items': ('pharmacy',), 'expiring_count': ('pharmacy',),
                 'expiring_value': ('pharmacy',), 'nearest_lot_expiry': ('pharmacy',)}
# intents a split rulebook section opens to more trades: intent -> {section: trades}
SECTION_ONLY = {
    **{i: {'tables': ('restaurant', 'hotpot')} for i in ('guests_total', 'revenue_per_guest', 'area_revenue', 'top_table')},
    **{i: {'service': ('motorbike_repair', 'spa_salon', 'pet_shop', 'phone_shop')} for i in ('service_revenue', 'service_share')},
    **{i: {'vehicles': ('motorbike_repair',)} for i in ('vehicle_count', 'repeat_vehicles')},
    'qty_size': {'size_word': ('fashion',), 'milk_tea': ('milk_tea',)},
    **{i: {'expiry': ('cosmetics', 'mother_baby', 'agri_supply')}
       for i in ('expiring_items', 'expiring_count', 'expiring_value', 'nearest_lot_expiry')},
}
SEASON_TRADES = {'dong_xuan': 'agri_supply', 'he_thu': 'agri_supply', 'tuu_truong': 'stationery'}
# period kinds of the train questions, measured with gen.parse.find_period on the 3000 questions (scripts/check_syn.py
# dist): month .64, day .07, today .06, yesterday .06, this_month .05, last_week .04, quarter .03, ...
PERIOD_MIX = [('month', 0.62), ('day', 0.05), ('today', 0.06), ('yesterday', 0.06), ('this_month', 0.05),
              ('last_week', 0.04), ('quarter', 0.03), ('last_n_days', 0.02), ('ytd', 0.02), ('range', 0.015),
              ('this_week', 0.01), ('tet', 0.01)]


def allowed(intent, industry, rules):
    """May this intent be asked in a shop of `industry` under `rules` (sections of the split rulebook)?"""
    if industry in INDUSTRY_ONLY.get(intent, (industry,)) and intent not in SECTION_ONLY:
        return True
    if intent in INDUSTRY_ONLY and industry in INDUSTRY_ONLY[intent]:
        return True
    return any(sec in rules.sections and industry in trades for sec, trades in SECTION_ONLY.get(intent, {}).items())
RELATIVE = ['today', 'yesterday', 'this_month', 'last_week', 'this_week', 'last_n_days', 'ytd']
RANKED = {'top_items', 'top_customers', 'top_staff', 'top_supplier', 'best_day', 'best_month', 'top_table'}


class Sampler:
    def __init__(self, L, rng, rules=Rules(), mix='v1'):
        self.L, self.rng, self.R, self.mix = L, rng, rules, mix
        self.start, self.end = L.shop['start'], L.shop['end']
        months, d = [], self.start
        while d <= self.end:
            months.append((d.year, d.month))
            d = P.month_end(d.year, d.month) + dt.timedelta(days=1)
        self.months = months
        self.full_months = [m for m in months if P.month_end(*m) <= self.end]
        self.views = {}

    def stock_date_ok(self, date):
        """Stock at `date` can be read from the files: a stock card, or end stock rolled back with purchases."""
        caps = self.L.shop['caps']
        if 'stock' not in caps:
            return True                       # asked anyway: the oracle answers unanswerable
        return 'stock_history' in caps or 'purchases' in caps or date == self.end

    def view(self, as_of):
        if as_of not in self.views:
            self.views[as_of] = View(self.L, as_of, self.R)
        return self.views[as_of]

    # ---------------- params
    def month(self, full=True, as_of=None):
        as_of = as_of or self.cur_as_of
        ms = [m for m in (self.full_months if full else self.months) if P.month_end(*m) <= as_of] or \
            [m for m in self.months if dt.date(m[0], m[1], 1) <= as_of]
        y, m = ms[int(self.rng.integers(len(ms)))]
        return {'kind': 'month', 'y': y, 'm': m}

    def seasons(self, as_of):
        """Season windows of the split rulebook for this trade that start in the data and end by as_of."""
        out = []
        for key, label, *_ in self.R.seasons:
            if SEASON_TRADES.get(key) != self.L.shop.get('industry'):
                continue
            for y in range(self.start.year, as_of.year + 2):
                spec = {'kind': 'season', 'name': key, 'year': y, 'label': label}
                s, e = P.bounds(spec, as_of, self.R)
                if s >= self.start and e <= as_of:
                    out.append(spec)
        return out

    def period(self, as_of, relative_ok=True):
        if self.mix == 'train':
            return self.period_train(as_of, relative_ok)
        r = self.rng.random()
        if relative_ok and r < 0.25:
            k = RELATIVE[int(self.rng.integers(len(RELATIVE)))]
            if k == 'last_n_days':
                return {'kind': k, 'n': int(self.rng.choice([7, 14, 30]))}
            return {'kind': k}
        if r < 0.32 and len(self.full_months) >= 3:
            mm = self.month()
            q = (mm['m'] - 1) // 3 + 1
            if P.month_end(mm['y'], 3 * q) <= as_of:
                return {'kind': 'quarter', 'y': mm['y'], 'q': q}
        if r < 0.35:
            s = self.start + dt.timedelta(days=int(self.rng.integers(0, max(1, (as_of - self.start).days - 14))))
            return {'kind': 'range', 'start': s, 'end': s + dt.timedelta(days=int(self.rng.choice([6, 9, 13])))}
        return self.month()

    def period_train(self, as_of, relative_ok=True):
        """Period kinds in the train shares; a season of the split rulebook for 15 % of its trade's questions."""
        rng = self.rng
        seas = self.seasons(as_of)
        if seas and rng.random() < 0.15:
            return seas[int(rng.integers(len(seas)))]
        boost = getattr(self, 'period_boost', {})
        mix = [(k, w * boost.get(k, 1.0)) for k, w in PERIOD_MIX
               if relative_ok or k in ('month', 'quarter', 'range', 'day', 'tet')]
        k = mix[int(rng.choice(len(mix), p=np.array([w for _, w in mix]) / sum(w for _, w in mix)))][0]
        if k == 'quarter' and len(self.full_months) >= 3:
            mm = self.month()
            q = (mm['m'] - 1) // 3 + 1
            if P.month_end(mm['y'], 3 * q) <= as_of:
                return {'kind': 'quarter', 'y': mm['y'], 'q': q}
            return mm
        if k == 'last_n_days':
            return {'kind': k, 'n': int(rng.choice([7, 7, 14, 30, 30]))}
        if k == 'range':
            s0 = self.start + dt.timedelta(days=int(rng.integers(0, max(1, (as_of - self.start).days - 14))))
            return {'kind': 'range', 'start': s0, 'end': s0 + dt.timedelta(days=int(rng.choice([6, 9, 13, 20])))}
        if k == 'day':
            span = (as_of - self.start).days
            if span < 3:
                return self.month()
            return {'kind': 'day', 'date': as_of - dt.timedelta(days=int(rng.integers(2, span)))}
        if k == 'tet':
            ys = []
            for y in (2025, 2026, 2027):
                try:
                    s0, e0 = P.bounds({'kind': 'tet', 'year': y}, as_of, self.R)
                except ValueError:
                    continue
                if s0 >= self.start and e0 <= as_of:
                    ys.append(y)
            return {'kind': 'tet', 'year': int(rng.choice(ys))} if ys else self.month()
        if k in ('month', 'quarter'):
            return self.month()
        return {'kind': k}

    def rise_visible(self, V, pid, d, price):
        """A price rise the files show on its day: the price list is written, or the item sold at the new price
        (per base unit) on day d and never before (else the agent would date the rise elsewhere)."""
        if 'prices' in self.L.shop['caps']:      # caps = what the rendered files carry (gen.build)
            return True
        l = V.lines_all[V.lines_all.product_id == pid]
        l = l[(l.unit_price / l.base_qty * l.qty).round(0) >= price - 0.5]
        return not l.empty and l.day.min().date() == d

    def sold_item(self, V, period=None, goods=False):
        l = V.vlines if period is None else V.in_period(V.vlines, period)
        l = l[l.kind == 'goods'] if goods else l[l.kind != 'fee']
        if l.empty:
            return None
        ids = l.product_id.value_counts()
        return ids.index[int(self.rng.integers(min(len(ids), 40)))]

    def item_unit(self, pid, big=False):
        u = self.L.units[self.L.units.product_id == pid]
        base = self.L.products.set_index('product_id').base_unit.get(pid)
        if big:
            return None if u.empty else u.unit.iloc[int(self.rng.integers(len(u)))]
        if not u.empty and self.rng.random() < 0.3:
            return u.unit.iloc[int(self.rng.integers(len(u)))]
        return base

    def threshold(self, values, money=True):
        if len(values) == 0:
            return None
        q = float(np.quantile(values, self.rng.uniform(0.3, 0.9)))
        if money:
            step = 10 ** max(3, int(np.log10(max(q, 1))) - 1)
            return int(round(q / step) * step)
        return max(1, int(round(q)))

    # ---------------- one spec
    def spec(self, intent, as_of):
        L, rng = self.L, self.rng
        self.cur_as_of = as_of
        if intent == 'unanswerable':                # facts no shop file records (opinions, dosage, address...)
            return {'intent': 'unanswerable', 'period': {'kind': 'this_month'}}
        V = self.view(as_of)
        per = self.period(as_of)
        S = lambda **kw: {'intent': intent, **kw}
        if intent in ('debt_collected', 'debt_new') and 'payments' not in L.shop['caps']:
            return None
        if intent in ('revenue', 'order_count', 'avg_order', 'cancel_rate', 'cancel_count', 'gross_profit',
                      'purchase_total', 'top_supplier', 'customer_count', 'top_staff', 'unsold_count',
                      'deliveries_count', 'debt_collected', 'debt_new'):
            if intent == 'unsold_count':
                per = per if per['kind'] in ('last_week', 'last_n_days', 'range', 'this_week') else {'kind': 'last_n_days', 'n': 7}
            return S(period=per)
        if intent == 'net_profit':
            return S(period=self.month())
        if intent == 'revenue_change_pct' or intent == 'revenue_diff':
            p = per if per['kind'] in ('month', 'quarter', 'this_month', 'last_week') else self.month()
            spec = S(period=p)
            if p['kind'] == 'month' and rng.random() < 0.2:
                spec['ref'] = {**p, 'y': p['y'] - 1}
            if self.mix == 'train' and p['kind'] == 'this_month':
                spec['ref_text'] = 'neutral'      # 'so với tháng trước': the rulebook decides which days
            return spec
        if intent in ('revenue_list', 'revenue_trend_up', 'best_month'):
            fm = [m for m in self.full_months if P.month_end(*m) <= as_of]
            if len(fm) < 3:
                return None
            i = int(rng.integers(0, len(fm) - 2))
            return S(periods=[{'kind': 'month', 'y': y, 'm': m} for y, m in fm[i:i + 3]])
        if intent == 'best_day':
            return S(period=self.month(), worst=False)
        if intent in ('days_over', 'orders_over'):
            p = self.month()
            o = V.in_period(V.valid, p)
            r = V.order_rev.reindex(o.order_id)
            if intent == 'days_over':
                r = r.groupby(o.day.values).sum()
            return S(threshold=self.threshold(r.values), period=p)
        if intent in ('revenue_item', 'qty_item'):
            pid = self.sold_item(V)
            if pid is None:
                return None
            spec = S(item=pid, period=per)
            if intent == 'qty_item':
                spec['unit'] = self.item_unit(pid)
            return spec
        if intent in ('revenue_group', 'group_share'):
            g = L.products[L.products.kind != 'fee'].group.dropna().unique()
            return S(group=g[int(rng.integers(len(g)))], period=per)
        if intent == 'top_items':
            k = int(rng.choice([1, 1, 3, 5]))
            by = rng.choice(['qty', 'qty', 'qty', 'revenue'])
            return S(k=k, by=by, period=per, as_list=k > 1)
        if intent == 'top_customers':
            k = int(rng.choice([1, 3, 5]))
            return S(k=k, by=rng.choice(['revenue', 'orders']), period=per, as_list=k > 1)
        if intent in ('customers_min_orders', 'customers_min_orders_share'):
            p = self.month()
            o = V.in_period(V.valid, p)
            n = o[o.customer_id.notna()].groupby('customer_id').order_id.nunique()
            return S(n=self.threshold(n.values, money=False) if len(n) else 3, period=p)
        if intent == 'items_min_orders':
            p = self.month()
            l = V.in_period(V.vlines, p)
            n = l.groupby('product_id').order_id.nunique()
            return S(n=self.threshold(n.values, money=False) if len(n) else 10, period=p)
        if intent in ('cust_group_revenue', 'cust_group_share'):
            g = L.customers.group.dropna().unique()
            return S(group=g[int(rng.integers(len(g)))], period=per)
        if intent == 'payment_revenue':
            m = list(rng.choice(['cash', 'transfer', 'ewallet', 'cod'], size=int(rng.choice([1, 2])), replace=False))
            return S(methods=m, period=per)
        if intent == 'payment_share':
            return S(method=rng.choice(['cash', 'transfer', 'ewallet', 'cod']), period=per)
        if intent == 'channel_revenue':
            return S(channels=list(rng.choice(['store', 'phone', 'zalo_oa'], size=2, replace=False)), period=per)
        if intent == 'channel_share':
            return S(channel=rng.choice(['phone', 'zalo_oa']), period=per)
        if intent in ('shift_revenue', 'shift_orders'):
            return S(shift=rng.choice(['morning', 'afternoon']), period=per)
        if intent == 'shift_change_pct':
            return S(period=per)
        if intent == 'staff_revenue':
            return S(staff=L.staff.staff_id.iloc[int(rng.integers(len(L.staff)))], period=per)
        if intent in ('rx_revenue', 'rx_share'):
            return S(rx=bool(rng.random() < 0.7), period=per)
        if intent == 'ingredient_revenue':
            ing = L.drugs.ingredient.dropna().value_counts()
            return S(ingredient=ing.index[int(rng.integers(min(len(ing), 15)))], period=per)
        if intent in ('avg_purchase_price', 'purchase_minus_sales'):
            p = self.month()
            pu = L.purchases[(L.purchases.date >= pd.Timestamp(P.bounds(p, as_of, self.R)[0])) &
                             (L.purchases.date <= pd.Timestamp(P.bounds(p, as_of, self.R)[1]))]
            pl = L.purchase_lines[L.purchase_lines.purchase_id.isin(pu.purchase_id)]
            if pl.empty:
                return None
            pid = pl.product_id.iloc[int(rng.integers(len(pl)))]
            unit = pl[pl.product_id == pid].unit.iloc[0] if intent == 'avg_purchase_price' else self.item_unit(pid)
            return S(item=pid, unit=unit, period=p)
        if intent == 'price_on_day':
            l = V.lines_all[V.lines_all.kind != 'fee']
            r = l.iloc[int(rng.integers(len(l)))]
            return S(item=r.product_id, date=r.day.date(), unit=self.item_unit(r.product_id))
        if intent == 'price_effect':
            pr = L.prices.sort_values('date')
            rises = []
            for pid, g in pr.groupby('product_id'):
                v = g.price.values
                for i in range(1, len(v)):
                    if v[i] > v[i - 1] and g.date.iloc[i].date() <= as_of - dt.timedelta(days=30):
                        rises.append((pid, g.date.iloc[i].date(), v[i]))
            if not rises:
                return None
            pid, d, price = rises[int(rng.integers(len(rises)))]
            spec = S(item=pid, date=d, n=int(rng.choice([7, 14, 30])), new_price=float(price),
                     unit=L.products.set_index('product_id').base_unit.get(pid))
            if self.mix == 'train' and not self.rise_visible(V, pid, d, price):
                del spec['new_price']             # the question then names the day of the rise
            return spec
        if intent in ('qty_unit',):
            u = L.products[L.products.kind != 'fee'].base_unit.value_counts()
            return S(unit=u.index[int(rng.integers(min(3, len(u))))], period=per)
        if intent == 'qty_size':
            if L.shop.get('industry') == 'fashion':
                return S(size=str(rng.choice(['S', 'M', 'L', 'XL'])), style='word', period=per)
            return S(size=rng.choice(['M', 'L']), period=per)
        if intent in ('guests_total', 'revenue_per_guest', 'top_table'):
            return S(period=per)
        if intent == 'area_revenue':
            a = [x for x in L.visits.area.dropna().unique() if x != 'Mang về']
            return S(area=str(a[int(rng.integers(len(a)))]), period=per) if len(a) else None
        if intent == 'service_revenue':
            return S(period=per, part='goods') if rng.random() < 0.3 else S(period=per)
        if intent in ('service_share', 'vehicle_count'):
            return S(period=per)
        if intent == 'repeat_vehicles':
            return S(period=per if per['kind'] not in ('today', 'yesterday', 'day') else self.month(),
                     **({'n': int(rng.choice([2, 3]))} if rng.random() < 0.3 else {}))
        if intent in ('stock_end', 'stock_big_small'):
            pid = self.sold_item(V, goods=True)
            if pid is None or not self.stock_date_ok(as_of):
                return None
            date = as_of if rng.random() < 0.7 else as_of - dt.timedelta(days=int(rng.integers(1, 60)))
            if not self.stock_date_ok(date):
                date = as_of
            if intent == 'stock_big_small':
                big = self.item_unit(pid, big=True)
                return S(item=pid, date=date, big_unit=big) if big else None
            unit = self.item_unit(pid)
            if self.mix == 'train':               # stock in a big unit is the [big, base] list of §5 (stock_big_small)
                unit = L.products.set_index('product_id').base_unit.get(pid)
            return S(item=pid, date=date, unit=unit)
        if intent in ('stock_value', 'out_of_stock_count'):
            if not self.stock_date_ok(as_of):
                return None
            d = as_of if rng.random() < 0.7 else as_of - dt.timedelta(days=int(rng.integers(1, 60)))
            return S(date=d if self.stock_date_ok(d) else as_of)
        if intent in ('expiring_items', 'expiring_count', 'expiring_value'):
            return S(date=as_of, n=int(rng.choice([30, 60, 90, 120])))
        if intent == 'nearest_lot_expiry':
            pid = self.sold_item(V, goods=True)
            return S(item=pid, date=as_of) if pid else None
        if intent in ('debt_total', 'debt_customers', 'debt_top', 'debt_over_age', 'debt_aging'):
            if 'payments' in L.shop['caps']:
                date = as_of if rng.random() < 0.6 else as_of - dt.timedelta(days=int(rng.integers(1, 90)))
            elif as_of == self.end:
                date = as_of                  # only end-of-data balances in the files
            else:
                return None
            if intent == 'debt_top':
                return S(date=date, k=int(rng.choice([3, 5])))
            if intent == 'debt_over_age':
                return S(date=date, days=int(rng.choice([7, 15, 30])))
            return S(date=date)
        if intent in ('debt_new_paid',) and 'payments' not in L.shop['caps']:
            return None
        if intent == 'debt_new_paid':
            o = L.orders[(L.orders.payment_method == 'debt') & L.orders.customer_id.notna()]
            if o.empty:
                return None
            c = o.customer_id.iloc[int(rng.integers(len(o)))]
            d = o[o.customer_id == c].created.iloc[0]
            return S(customer=c, period={'kind': 'month', 'y': d.year, 'm': d.month})
        return None

    def as_of_for(self, main):
        """Most questions at the main as_of (end of data); some at a random day (relative periods)."""
        if self.rng.random() < 0.75:
            return main
        d0 = self.start + dt.timedelta(days=60)
        return d0 + dt.timedelta(days=int(self.rng.integers(0, max(1, (self.end - d0).days + 1))))


def _tie_at_k(V, spec, strict=False):
    """True when the reference ranking would have a tie at the k boundary (such questions are excluded); strict:
    also a tie anywhere inside the top k (its order would rest on codes the files may not show)."""
    import gen.oracle as O
    it = spec['intent']
    k = spec.get('k', 1)
    try:
        if it == 'top_items':
            l = V.items(V.in_period(V.vlines, spec['period']))
            col = {'qty': 'base_qty', 'revenue': 'amount'}.get(spec.get('by', 'qty'))
            if col is None:
                v = (l.amount - l.qty * l.unit_cost).groupby(l.product_id).sum()
            else:
                v = l.groupby('product_id')[col].sum()
        elif it == 'top_customers':
            o = V.in_period(V.valid, spec['period'])
            o = o[o.customer_id.notna()]
            v = (V.order_rev.reindex(o.order_id).groupby(o.customer_id.values).sum() if spec.get('by') == 'revenue'
                 else o.groupby('customer_id').order_id.nunique())
        elif it == 'best_day':
            o = V.in_period(V.valid, spec['period'])
            v = V.order_rev.reindex(o.order_id).groupby(o.day.values).sum()
        elif it == 'debt_top':
            o = O._debt_orders(V, spec['date'])
            v = o[o.customer_id.notna()].groupby('customer_id').left.sum()
        elif it == 'top_table':
            v = O.table_revenue(V, spec)
        elif it == 'top_staff':
            o = V.in_period(V.valid, spec['period'])
            v = V.order_rev.reindex(o.order_id).groupby(o.staff_id.values).sum()
        elif it == 'top_supplier':
            v = O._purchases(V, spec).groupby('supplier_id').total.sum()
        elif it == 'best_month':
            v = pd.Series([V.revenue(p) for p in spec['periods']])
        else:
            return False
    except O.Unanswerable:
        return False
    v = np.sort(np.asarray(v, dtype=float))[::-1]
    if strict and len(v) > 1 and np.any(np.abs(np.diff(v[:min(len(v), k + 1)])) < 1e-9):
        return True
    if len(v) <= k:
        return False
    return abs(v[k - 1] - v[k]) < 1e-9


ORDER_INTENTS = {'order_count', 'avg_order', 'cancel_rate', 'cancel_count', 'items_min_orders', 'orders_over',
                 'customers_min_orders', 'customers_min_orders_share', 'customer_count', 'top_customers'}
ABSOLUTE = {'month', 'quarter', 'range', 'day', 'tet', 'season', 'year'}


def sample(L, rng, n, main_as_of=None, rules=Rules(), weights=WEIGHTS, unanswerable_drop=0.85, mix='v1',
           period_boost=None):
    """mix='train' (syn_v2): period kinds in train shares (period_boost multiplies some), no order-level question on
    files without order ids, ~no zero answers (2 of 3000 in train), no repeat of an absolute question at another
    as_of, no tie anywhere inside a ranked list."""
    smp = Sampler(L, rng, rules, mix)
    smp.period_boost = period_boost or {}
    if mix == 'train':
        unanswerable_drop = max(unanswerable_drop, 0.92)      # cap-missing unanswerables near the train 2-4 %
        weights = {**weights, 'revenue': weights['revenue'] * 0.7,       # train: revenue questions 23 %
                   'unsold_count': weights['unsold_count'] * 2}          # most zero answers are dropped
    main = main_as_of or L.shop['end']
    ind = L.shop['industry']
    if mix == 'v1':
        names = [i for i in weights if (i in INTENTS or i == 'unanswerable') and ind in INDUSTRY_ONLY.get(i, (ind,))
                 and i not in SECTION_ONLY.keys() - INDUSTRY_ONLY.keys()]
    else:
        names = [i for i in weights if (i in INTENTS or i == 'unanswerable') and allowed(i, ind, rules)]
    w = np.array([weights[i] for i in names], dtype=float)
    w /= w.sum()
    out, tries, seen = [], 0, set()
    while len(out) < n and tries < n * 20:
        tries += 1
        it = names[int(rng.choice(len(names), p=w))]
        as_of = smp.as_of_for(main)
        try:
            spec = smp.spec(it, as_of)
        except Exception:  # noqa: BLE001 - a parameter the shop cannot provide
            spec = None
        if spec is None:
            continue
        if mix == 'train' and it in ORDER_INTENTS and 'order_ids' not in L.shop['caps']:
            continue                          # train never asks order counts of files without order ids
        key = repr(sorted((k, repr(v)) for k, v in spec.items()))
        absolute = all(p.get('kind') in ABSOLUTE for p in ([spec['period']] if 'period' in spec else [])
                       + list(spec.get('periods', []))) and 'date' not in spec
        if not (mix == 'train' and absolute):
            key += str(as_of)
        if key in seen:
            continue
        V = smp.view(as_of)
        if it in RANKED | {'debt_top'} and _tie_at_k(V, spec, strict=mix == 'train'):
            continue
        t, a = answer(L, spec, as_of, rules, view=V)
        if t != 'unanswerable' and (a is None or a == [] or (isinstance(a, float) and np.isnan(a))):
            continue
        if mix == 'train' and t == 'number' and a == 0 and rng.random() < 0.95:
            continue                          # zero answers: 2 of 3000 train questions
        if t == 'unanswerable' and it != 'unanswerable' and rng.random() < unanswerable_drop:
            continue                      # keep unanswerables near the train share (~2-5 %)
        seen.add(key)
        out.append({'spec': spec, 'as_of': as_of, 'type': t, 'answer': a})
    return out
