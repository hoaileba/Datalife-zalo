"""World simulator: a shop spec -> canonical Ledger (gen.ledger), day by day.

Parameters follow what was measured on the train shops (docs/PLAN_TRAINDATA.md §1.1): Tết multiplier per
industry, weekend factor per shop, payday bump, trend; status, payment and channel mixes; +15k shipping iff phone/zalo;
KM01 -10k; restaurant service fee = 5% of the dishes; debt paid at sale in part then 1-3 equal instalments; price
rises +4-9%; restocking every 1-2 days, PN00001 = opening stock; FEFO lots (pharmacy); deliveries (building).

simulate(spec, seed) -> Ledger. make_spec(industry, rng, business_id) draws a spec.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

import numpy as np
import pandas as pd

from . import catalogs, periods
from .ledger import COLUMNS, Ledger

TRAIN_META = {   # orders/day range, Tết multiplier, mean lines/order, pre-Tết bump
    'grocery': dict(shop_word='cửa hàng', label='tạp hoá', tet=2.3, pre_tet=1.5, orders=[40, 140], lines=1.9),
    'cafe': dict(shop_word='quán', label='cà phê', tet=0.5, pre_tet=1.0, orders=[60, 160], lines=1.6),
    'building': dict(shop_word='cửa hàng', label='vật liệu xây dựng', tet=0.5, pre_tet=1.2, orders=[20, 40], lines=1.8),
    'pharmacy': dict(shop_word='nhà thuốc', label='nhà thuốc', tet=1.2, pre_tet=1.1, orders=[40, 90], lines=1.9),
    'restaurant': dict(shop_word='quán', label='nhà hàng', tet=0.5, pre_tet=1.0, orders=[40, 90], lines=3.0,
                       visits='tables', takeaway=0.15),
}

SURNAMES = ('Nguyễn Trần Lê Phạm Hoàng Huỳnh Phan Vũ Võ Đặng Bùi Đỗ Hồ Ngô Dương Lý Đoàn Trịnh Đinh Mai Lưu Tô Hà '
            'Thân Kiều Châu Tăng Diệp Quách La Vương Hứa Chung Phùng Lương Doãn Triệu').split()
MIDDLES = 'Văn Thị Minh Ngọc Thu Hồng Đức Hải Thanh Quang Bích Hương Gia Khánh Tâm Hoàng Phương Duy Hạnh An'.split()
GIVENS = ('An Anh Bảo Bình Chi Cường Dũng Dương Đạt Giang Hà Hải Hạnh Hiếu Hoà Hùng Hương Khánh Khoa Lan Linh Loan '
          'Long Mai Minh Nam Ngân Ngọc Nhung Oanh Phong Phúc Phương Quang Quân Sơn Tâm Thảo Thắng Thu Trang Trung '
          'Tú Tuấn Vy Yến Đức Lâm').split()
STREETS = ('Lê Lợi|Nguyễn Huệ|Trần Hưng Đạo|Hai Bà Trưng|Lý Thường Kiệt|Nguyễn Trãi|Cách Mạng Tháng 8|Phan Đình Phùng|'
           'Nguyễn Văn Linh|Võ Văn Kiệt|Lê Văn Sỹ|Phạm Văn Đồng|Bạch Đằng|Trần Não|Nguyễn Oanh|Hậu Giang').split('|')
HEAVY_GROUPS = ('xi măng', 'cát đá', 'gạch', 'sắt thép', 'thép', 'tôn')


def _meta(industry):
    if industry in TRAIN_META:
        return TRAIN_META[industry]
    import yaml
    new = yaml.safe_load(catalogs.ASSETS.joinpath('new_industries.yaml').read_text(encoding='utf-8'))
    m = dict(new[industry]['meta'])
    m.setdefault('pre_tet', 1.2 if m['tet'] > 1 else 1.0)
    return m


def _round_price(x):
    step = 500 if x < 100000 else 1000
    return int(max(step, round(x / step) * step))


def person_name(rng):
    return f'{rng.choice(SURNAMES)} {rng.choice(MIDDLES)} {rng.choice(GIVENS)}'


def make_spec(industry, rng, business_id='syn_001', caps_drop=()):
    meta = _meta(industry)
    start_m = int(rng.integers(1, 7))
    start = dt.date(2025, start_m, 1)
    months = min(int(rng.integers(14, 21)), 2026 * 12 + 9 - (2025 * 12 + start_m) + 1)   # train data ends by 09/2026
    y, m = periods.add_months(2025, start_m, months - 1)
    end = dt.date(y, m, int(rng.integers(5, periods.month_end(y, m).day + 1)))
    return dict(business_id=business_id, industry=industry, start=start, end=end,
                orders_per_day=float(rng.uniform(*meta['orders'])), weekend=float(rng.uniform(0.65, 1.5)),
                trend=float(rng.uniform(-0.35, 0.35)), payday=float(rng.uniform(0.05, 0.12)),
                n_customers=int(rng.integers(180, 381)), walkin=float(rng.uniform(0.25, 0.5)),
                cancel=float(rng.uniform(0.01, 0.04)), returned=float(rng.uniform(0.003, 0.015)),
                debt=float(rng.uniform(0.01, 0.03)), promo=float(rng.uniform(0.0, 0.15)),
                remote=float(rng.uniform(0.0, 0.15)), expenses=bool(rng.random() < 0.35),
                lots=industry == 'pharmacy' or bool(meta.get('lots')),
                deliveries=industry == 'building' or bool(rng.random() < 0.1),
                price_changes=float(rng.uniform(0.15, 0.4)), caps_drop=tuple(caps_drop),
                decimal_units=tuple(meta.get('decimal_units', ())), visits=meta.get('visits'),
                takeaway=float(meta.get('takeaway', 0.1)), staff=int(meta.get('staff', 3)))


class _Stock:
    """Base-unit stock per product, moving-average cost, FEFO lots."""

    def __init__(self, lots_on):
        self.qty = defaultdict(float)
        self.avg = {}
        self.lots = defaultdict(list)          # pid -> [[expiry, lot, left]]
        self.lots_on = lots_on

    def receive(self, pid, base_qty, base_cost, lot=None, expiry=None):
        q0 = self.qty[pid]
        a0 = self.avg.get(pid, base_cost)
        self.qty[pid] = q0 + base_qty
        self.avg[pid] = (q0 * a0 + base_qty * base_cost) / (q0 + base_qty) if q0 + base_qty > 0 else base_cost
        if self.lots_on and lot:
            self.lots[pid].append([expiry, lot, base_qty])
            self.lots[pid].sort()

    def take(self, pid, base_qty, day):
        """Remove base_qty (FEFO, skipping lots with < 7 days left). Returns [(lot, q)] or None if short."""
        if self.qty[pid] < base_qty:
            return None
        self.qty[pid] -= base_qty
        if not self.lots_on:
            return []
        out, need = [], base_qty
        for rec in self.lots[pid]:
            if need <= 0:
                break
            if rec[2] <= 0 or rec[0] < pd.Timestamp(day + dt.timedelta(days=7)):
                continue
            q = min(rec[2], need)
            rec[2] -= q
            need -= q
            out.append((rec[1], q))
        if need > 0:                            # only short-dated lots left: sell them anyway
            for rec in self.lots[pid]:
                if need <= 0:
                    break
                q = min(rec[2], need)
                if q > 0:
                    rec[2] -= q
                    need -= q
                    out.append((rec[1], q))
        return out

    def give_back(self, pid, base_qty, lot=None):
        self.qty[pid] += base_qty
        if self.lots_on and lot:
            for rec in self.lots[pid]:
                if rec[1] == lot:
                    rec[2] += base_qty


def simulate(spec, seed=0) -> Ledger:
    rng = np.random.default_rng(seed)
    ind = spec['industry']
    meta = _meta(ind)
    cat = catalogs.load()[ind]
    # ---------------- products
    keep = max(15, int(len(cat) * rng.uniform(0.75, 1.0) if ind in TRAIN_META or ind == 'restaurant'
                       else len(cat) * rng.uniform(0.6, 0.95)))  # new trades: shops of one trade differ more
    idx = sorted(rng.choice(len(cat), size=min(keep, len(cat)), replace=False))
    if ind == 'restaurant':
        fee = [i for i, e in enumerate(cat) if e['kind'] == 'fee']
        idx = sorted(set(idx) | set(fee))
    prods, units = [], []
    for n, i in enumerate(idx, 1):
        e = cat[i]
        pid = f'SP{n:04d}'
        price = _round_price(e['price'] * rng.uniform(0.92, 1.08)) if e['kind'] != 'fee' else 0
        cost = e.get('cost')
        if cost is None or ind != 'pharmacy':
            cost = price * (rng.uniform(0.3, 0.45) if e['kind'] == 'made' else rng.uniform(0.62, 0.82))
        prods.append(dict(product_id=pid, name=e['name'], group=e['group'], base_unit=e['base_unit'],
                          price=float(price), cost=float(round(cost)), kind=e['kind']))
        for u, f in e.get('units') or []:
            units.append(dict(product_id=pid, unit=u, factor=int(f), price=float(_round_price(price * f * rng.uniform(0.94, 1.0)))))
    P = pd.DataFrame(prods)
    U = pd.DataFrame(units, columns=COLUMNS['units'])
    ufac = defaultdict(dict)
    for r in U.itertuples():
        ufac[r.product_id][r.unit] = (r.factor, r.price)
    drugs = None
    if ind == 'pharmacy':
        drugs = pd.DataFrame([dict(product_id=p['product_id'], ingredient=cat[i].get('ingredient'),
                                   rx=bool(cat[i].get('rx'))) for p, i in zip(prods, idx)])
    pids = list(P.product_id)
    sellable = [p for p, k in zip(P.product_id, P.kind) if k not in ('fee', 'addon')]
    addons = [p for p, k in zip(P.product_id, P.kind) if k == 'addon']
    pop = rng.zipf(1.6, size=len(sellable)).astype(float)
    pop = np.minimum(pop, 40)
    pop /= pop.sum()
    kind = dict(zip(P.product_id, P.kind))
    base_cost = dict(zip(P.product_id, P.cost))
    group = dict(zip(P.product_id, P.group))
    bunit = dict(zip(P.product_id, P.base_unit))
    # ---------------- prices over time
    start, end = spec['start'], spec['end']
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    price_rows = [dict(product_id=p['product_id'], date=pd.Timestamp(start), price=p['price']) for p in prods if p['kind'] != 'fee']
    changes = defaultdict(list)                  # pid -> [(date, new_price)]
    for p in prods:
        if p['kind'] == 'fee' or rng.random() > spec['price_changes']:
            continue
        cur = p['price']
        for d in sorted(rng.choice(len(days) - 30, size=int(rng.integers(1, 4)), replace=False) + 15):
            cur = _round_price(cur * rng.uniform(1.04, 1.09))
            changes[p['product_id']].append((days[d], float(cur)))
            price_rows.append(dict(product_id=p['product_id'], date=pd.Timestamp(days[d]), price=float(cur)))
    def price_at(pid, day):
        v = _price0[pid]
        for d, pr in changes.get(pid, ()):
            if d <= day:
                v = pr
        return v
    _price0 = dict(zip(P.product_id, P.price))
    # ---------------- people
    customers = []
    names_seen = []
    for i in range(1, spec['n_customers'] + 1):
        nm = person_name(rng)
        if names_seen and rng.random() < 0.02:
            nm = names_seen[int(rng.integers(len(names_seen)))]      # two codes, same name (§3)
        names_seen.append(nm)
        customers.append(dict(customer_id=f'KH{i:04d}', name=nm,
                              group=rng.choice(['lẻ', 'thân thiết', 'sỉ'], p=[0.6, 0.3, 0.1]),
                              phone='0' + str(rng.choice([3, 7, 8, 9])) + ''.join(map(str, rng.integers(0, 10, 8))),
                              address=f'{int(rng.integers(1, 999))} {rng.choice(STREETS)}'))
    C = pd.DataFrame(customers)
    cweights = rng.pareto(1.2, size=len(C)) + 0.2
    cweights /= cweights.sum()
    n_staff = int(spec.get('staff', 3))
    roles = (['owner', 'cashier', 'sales'] + ['sales'] * 8)[:n_staff]
    staff = pd.DataFrame([dict(staff_id=f'NV{i:03d}', name=person_name(rng), role=r) for i, r in enumerate(roles, 1)])
    staff_p = np.array([0.3, 0.45, 0.25] if n_staff == 3 else rng.dirichlet(np.full(n_staff, 3.0)))
    staff_p = staff_p / staff_p.sum()
    # visits: restaurant tables/guests, repair-shop vehicles (plates)
    vis_kind = spec.get('visits')
    visits = []
    areas = []
    if vis_kind == 'tables':
        pool = [('Tầng 1', 'T1-{:02d}', 12), ('Tầng 2', 'T2-{:02d}', 10), ('Sân vườn', 'SV{:02d}', 8),
                ('Phòng VIP', 'VIP{}', 3), ('Khu A', 'A{:02d}', 10), ('Khu B', 'B{:02d}', 10)]
        pick = rng.choice(len(pool), size=int(rng.integers(2, 4)), replace=False)
        areas = [pool[i] for i in sorted(pick)]
        tables = [(a, f.format(j)) for a, f, n in areas for j in range(1, n + 1)]
        tw = rng.pareto(2.0, size=len(tables)) + 0.5
        tw /= tw.sum()
    plate_of = {}
    plate_pool = []
    if vis_kind == 'plates':
        def plate():
            return (f"{rng.choice([59, 51, 50, 61, 72, 63])}{rng.choice(list('BCDFGHKLMNPSTUVXYZ'))}"
                    f"{int(rng.integers(1, 10))}-{int(rng.integers(100, 1000))}.{int(rng.integers(10, 100))}")
        plate_pool = [plate() for _ in range(int(spec['n_customers'] * 1.5))]
        pw = rng.exponential(1.0, size=len(plate_pool)) + 0.05
        pw /= pw.sum()
    suppliers = pd.DataFrame([dict(supplier_id=f'NCC{i:03d}', name='Cty ' + ' '.join(person_name(rng).split()[::2]))
                              for i in range(1, 6)])
    # ---------------- Tết windows
    tet = []
    for y in (2025, 2026, 2027):
        try:
            s, e = periods.bounds({'kind': 'tet', 'year': y}, end, _R)
            tet.append((s, e))
        except ValueError:
            pass
    def factor(day):
        f = 1.0
        if day.weekday() >= 5:
            f *= spec['weekend']
        if day.day <= 5:
            f *= 1 + spec['payday']
        f *= 1 + spec['trend'] * (day - start).days / max(1, (end - start).days)
        for s, e in tet:
            if s <= day <= e:
                f *= meta['tet']
            elif s - dt.timedelta(days=14) <= day < s:
                f *= meta.get('pre_tet', 1.0)
        return f
    # ---------------- simulation state
    stock = _Stock(spec['lots'])
    orders, lines, payments, returns, purchases, plines, moves, lots, line_lots, deliveries = ([] for _ in range(10))
    seq = [0]
    def move(pid, t, k, q, doc):
        seq[0] += 1
        moves.append(dict(product_id=pid, time=t, kind=k, base_qty=q, doc_id=doc, balance=stock.qty[pid], seq=seq[0]))
    pn = [0]
    lot_n = [0]
    def purchase(day, items, note=None):
        pn[0] += 1
        pid_ = f'PN{pn[0]:05d}'
        sup = suppliers.supplier_id.iloc[int(rng.integers(len(suppliers)))]
        status = 'cancelled' if (pn[0] > 1 and rng.random() < 0.015) else 'received'
        t = pd.Timestamp(day) + pd.Timedelta(hours=6)
        total = 0
        for ln, (p, q_base) in enumerate(items, 1):
            us = sorted(ufac[p].items(), key=lambda kv: -kv[1][0])
            if us and q_base >= us[0][1][0]:
                unit, f = us[0][0], us[0][1][0]
            else:
                unit, f = bunit[p], 1
            q = max(1, int(math.ceil(q_base / f)))
            bc = base_cost[p] * rng.uniform(0.96, 1.04)
            ucost = float(round(bc * f))
            lot = expiry = None
            if spec['lots']:
                lot_n[0] += 1
                lot = f"{chr(65 + int(rng.integers(26)))}{day:%y%m}{lot_n[0] % 1000:03d}"
                expiry = pd.Timestamp(day + dt.timedelta(days=int(rng.integers(120, 1100))))
            plines.append(dict(purchase_id=pid_, line_no=ln, product_id=p, unit=unit, qty=q, unit_cost=ucost,
                               lot=lot, expiry=expiry))
            total += q * ucost
            if status == 'received':
                stock.receive(p, q * f, ucost / f, lot, expiry)
                if lot:
                    lots.append(dict(lot=lot, product_id=p, purchase_id=pid_, expiry=expiry, base_qty=q * f,
                                     base_cost=float(round(ucost / f))))
                move(p, t, 'in_purchase', q * f, pid_)
        purchases.append(dict(purchase_id=pid_, supplier_id=sup, date=pd.Timestamp(day), status=status,
                              total=float(total), note=note))
    goods = [p for p in pids if kind[p] == 'goods']
    expected = {p: spec['orders_per_day'] * meta['lines'] * pop[sellable.index(p)] * 1.6 for p in goods}
    purchase(start, [(p, max(5, int(expected[p] * rng.uniform(6, 12)))) for p in goods], note='nhập đầu kỳ')
    on = [0]
    pay_n = [0]
    ret_n = [0]
    pending_pay = []                             # (time, order_id, amount, method)
    fee_pid = next((p for p in pids if kind[p] == 'fee'), None)
    for day in days:
        # restock every 1-2 days
        if day > start and rng.random() < 0.65:
            need = [(p, int(expected[p] * rng.uniform(4, 9))) for p in goods
                    if stock.qty[p] < expected[p] * rng.uniform(2, 4)]
            if need:
                purchase(day, need)
        n = rng.poisson(spec['orders_per_day'] * factor(day))
        if n == 0:
            continue
        hours = np.where(rng.random(n) < 0.5, rng.normal(9, 1.5, n), rng.normal(18.5, 1.8, n))
        hours = np.clip(hours, 6.0, 21.98)
        secs = np.sort((hours * 3600).astype(int))
        for s in secs:
            created = pd.Timestamp(day) + pd.Timedelta(seconds=int(s))
            on[0] += 1
            oid = f'ORD{on[0]:06d}'
            walkin = rng.random() < spec['walkin']
            cust = None if walkin else C.customer_id.iloc[int(rng.choice(len(C), p=cweights))]
            channel = 'store'
            if rng.random() < spec['remote']:
                channel = 'phone' if rng.random() < 0.5 else 'zalo_oa'
            k = min(6, 1 + rng.geometric(1 / meta['lines']) - 1 if meta['lines'] > 1 else 1)
            k = max(1, k)
            chosen = list(dict.fromkeys(rng.choice(sellable, size=k, p=pop)))
            vis = None
            if vis_kind == 'tables':
                if rng.random() < spec.get('takeaway', 0.1):
                    vis = dict(order_id=oid, table=None, area='Mang về', guests=None, plate=None)
                else:
                    a, t = tables[int(rng.choice(len(tables), p=tw))]
                    g = int(min(14, max(1, round(rng.gamma(2.2, 1.6)))))
                    vis = dict(order_id=oid, table=t, area=a, guests=g, plate=None)
            elif vis_kind == 'plates':
                if cust is not None:                       # a regular customer brings one of their bikes
                    mine = plate_of.setdefault(cust, [])
                    if not mine or (rng.random() < 0.3 and len(mine) < 12):
                        mine.append(plate_pool[int(rng.integers(len(plate_pool)))])
                    pl = mine[int(rng.integers(len(mine)))]
                else:
                    pl = plate_pool[int(rng.choice(len(plate_pool), p=pw))]
                vis = dict(order_id=oid, table=None, area=None, guests=None, plate=pl)
            olines, ln = [], 0
            status = 'completed'
            r = rng.random()
            if r < spec['cancel']:
                status = 'cancelled'
            elif r < spec['cancel'] + spec['returned']:
                status = 'returned'
            elif (end - day).days < 3 and channel != 'store' or ((end - day).days < 2 and rng.random() < 0.08):
                status = 'delivering'
            for p in chosen:
                unit, f, uprice = bunit[p], 1, price_at(p, day)
                if ufac[p] and rng.random() < 0.18:
                    unit = list(ufac[p])[int(rng.integers(len(ufac[p])))]
                    f = ufac[p][unit][0]
                    uprice = float(_round_price(uprice * f * ufac[p][unit][1] / max(1, _price0[p] * f)))
                q = int(rng.choice([1, 1, 1, 2, 2, 3, 4, 5, 6, 10], p=[.3, .15, .1, .15, .08, .08, .04, .04, .03, .03]))
                if ind == 'building' and f == 1 and bunit[p] in ('viên', 'kg', 'm'):
                    q *= int(rng.choice([10, 50, 100]))
                if f == 1 and bunit[p] in spec.get('decimal_units', ()):
                    q = float(min(8.0, max(0.2, round(float(rng.lognormal(0.1, 0.6)), 2))))   # weighed: 1.35 kg
                base_q = q * f
                taken = []
                if kind[p] == 'goods' and status != 'cancelled':
                    taken = stock.take(p, base_q, day)
                    if taken is None:
                        continue                       # out of stock: the line is not sold
                disc = 0.0
                if rng.random() < 0.05:
                    disc = float(round(q * uprice * rng.choice([0.05, 0.1]) / 1000) * 1000)
                ln += 1
                ucost = float(round(stock.avg.get(p, base_cost[p]) * f))
                gross = float(q * uprice) if float(q).is_integer() else float(math.floor(q * uprice + 0.5))
                olines.append(dict(order_id=oid, line_no=ln, product_id=p, unit=unit, qty=q, base_qty=base_q,
                                   unit_price=float(uprice), line_discount=disc, amount=gross - disc,
                                   unit_cost=ucost))
                if kind[p] == 'goods' and status != 'cancelled':
                    move(p, created, 'out_sale', -base_q, oid)
                    for lot, lq in taken:
                        line_lots.append(dict(order_id=oid, line_no=ln, lot=lot, base_qty=lq, returned_base_qty=0))
            if addons and olines:
                if vis_kind == 'tables':                       # one khăn lạnh per guest, most dine-in tables
                    if vis and vis['guests'] and rng.random() < 0.8:
                        ad = addons[int(rng.integers(len(addons)))]
                        ln += 1
                        pr = price_at(ad, day)
                        olines.append(dict(order_id=oid, line_no=ln, product_id=ad, unit=bunit[ad], qty=vis['guests'],
                                           base_qty=vis['guests'], unit_price=float(pr), line_discount=0.0,
                                           amount=float(pr * vis['guests']), unit_cost=0.0))
                else:                                          # toppings on some drinks: one line per topping
                    tops = {}                                  # (two identical lines of one order would read as an
                    for _ in range(sum(1 for l in olines if kind[l['product_id']] == 'made')):   # export duplicate, §8)
                        if rng.random() < 0.45:
                            ad = addons[int(rng.integers(len(addons)))]
                            tops[ad] = tops.get(ad, 0) + int(rng.choice([1, 1, 1, 2]))
                    for ad, qa in tops.items():
                        ln += 1
                        pr = price_at(ad, day)
                        olines.append(dict(order_id=oid, line_no=ln, product_id=ad, unit=bunit[ad], qty=qa,
                                           base_qty=qa, unit_price=float(pr), line_discount=0.0,
                                           amount=float(pr * qa), unit_cost=0.0))
            if not olines:
                on[0] -= 1
                continue
            if vis is not None:
                visits.append(vis)
            sub = sum(l['amount'] for l in olines)
            if fee_pid and rng.random() < 0.13 + 0.1 * (len(olines) > 3):
                ln += 1
                fee = float(round(sub * 0.05))
                olines.append(dict(order_id=oid, line_no=ln, product_id=fee_pid, unit='lần', qty=1, base_qty=1,
                                   unit_price=fee, line_discount=0.0, amount=fee, unit_cost=0.0))
                sub += fee
            lines.extend(olines)
            disc = 10000.0 if (rng.random() < spec['promo'] and sub > 20000) else 0.0
            ship = 15000.0 if channel != 'store' else 0.0
            total = sub - disc + ship
            method = rng.choice(['cash', 'transfer', 'ewallet', 'cod'], p=[0.5, 0.35, 0.1, 0.05])
            if cust is not None and rng.random() < spec['debt'] * 3 and status != 'cancelled':
                method = 'debt'
            orders.append(dict(order_id=oid, created=created, customer_id=cust,
                               staff_id=staff.staff_id.iloc[int(rng.choice(n_staff, p=staff_p))],
                               channel=channel, status=status, subtotal=sub, discount=disc, shipping=ship, vat=0.0,
                               total=total, payment_method=method, promo='KM01' if disc else None, area=None))
            if status == 'cancelled':
                continue
            if method == 'debt':
                first = float(round(total * rng.choice([0, 0, 0.2, 0.3, 0.5]) / 1000) * 1000)
                if first:
                    pending_pay.append((created, oid, first, 'cash'))
                left = total - first
                n_i = int(rng.choice([1, 2, 3], p=[0.4, 0.4, 0.2]))
                part = math.floor(left / n_i)
                t = created
                for j in range(n_i):
                    t = t + pd.Timedelta(days=int(rng.integers(5, 21)), hours=int(rng.integers(0, 5)))
                    amt = part if j < n_i - 1 else left - part * (n_i - 1)
                    if rng.random() < 0.03:
                        break                               # never paid off
                    pending_pay.append((t, oid, float(amt), rng.choice(['cash', 'transfer'])))
            elif method == 'cod':
                pending_pay.append((created + pd.Timedelta(days=int(rng.integers(1, 4))), oid, total, 'cod'))
            else:
                pending_pay.append((created, oid, total, method))
            if status == 'returned':
                ret_n[0] += 1
                rt = created + pd.Timedelta(days=int(rng.integers(0, 8)), hours=int(rng.integers(1, 6)))
                back = olines if rng.random() < 0.5 else olines[:1]
                refund = 0.0
                for l in back:
                    if kind[l['product_id']] != 'goods':
                        continue
                    stock.give_back(l['product_id'], l['base_qty'])
                    move(l['product_id'], rt, 'in_return', l['base_qty'], f'TH{ret_n[0]:05d}')
                    for ll in line_lots:
                        if ll['order_id'] == oid and ll['line_no'] == l['line_no']:
                            ll['returned_base_qty'] = ll['base_qty']
                    refund += l['amount']
                returns.append(dict(return_id=f'TH{ret_n[0]:05d}', order_id=oid, time=rt,
                                    reason=rng.choice(['mua nhầm', 'hàng lỗi', 'gần hết hạn', 'không vừa ý']),
                                    refund=refund))
            if spec['deliveries'] and status != 'cancelled' and any(
                    any(h in str(group[l['product_id']]).lower() for h in HEAVY_GROUPS) for l in olines):
                trips = int(rng.choice([1, 2, 3], p=[0.78, 0.2, 0.02]))
                for j in range(trips):
                    deliveries.append(dict(order_id=oid, trip_no=j + 1,
                                           date=pd.Timestamp(day + dt.timedelta(days=int(j * rng.integers(1, 4)))),
                                           plate=rng.choice(['51C-123.45', '51D-678.90']),
                                           driver=rng.choice(['Anh Tư', 'Anh Năm'])))
    end_ts = pd.Timestamp(end) + pd.Timedelta(days=1)
    for t, oid, amt, m in sorted(pending_pay, key=lambda x: x[0]):
        if t < end_ts:
            pay_n[0] += 1
            payments.append(dict(payment_id=f'PAY{pay_n[0]:06d}', order_id=oid, time=t, amount=amt, method=m))
    expenses = []
    if spec['expenses']:
        rent = _round_price(rng.uniform(5e6, 25e6))
        for y, m in sorted({(d.year, d.month) for d in days}):
            expenses.append(dict(date=pd.Timestamp(dt.date(y, m, 1)), category='tiền thuê mặt bằng', amount=float(rent), note=None))
            if dt.date(y, m, 5) <= end:
                expenses.append(dict(date=pd.Timestamp(dt.date(y, m, 5)), category='tiền điện nước',
                                     amount=float(_round_price(rng.uniform(1e6, 4e6))), note=None))
            me = periods.month_end(y, m)
            if me <= end:
                expenses.append(dict(date=pd.Timestamp(me), category='lương nhân viên',
                                     amount=float(_round_price(rng.uniform(8e6, 20e6))), note=None))
            if rng.random() < 0.15:
                d = dt.date(y, m, int(rng.integers(1, 28)))
                if d <= end:
                    expenses.append(dict(date=pd.Timestamp(d), category='sửa chữa', amount=float(_round_price(rng.uniform(3e5, 5e6))), note='thay thiết bị'))
    T = dict(products=P, units=U, customers=C, staff=staff, suppliers=suppliers,
             orders=pd.DataFrame(orders, columns=COLUMNS['orders']), lines=pd.DataFrame(lines, columns=COLUMNS['lines']),
             payments=pd.DataFrame(payments, columns=COLUMNS['payments']),
             returns=pd.DataFrame(returns, columns=COLUMNS['returns']),
             purchases=pd.DataFrame(purchases, columns=COLUMNS['purchases']),
             purchase_lines=pd.DataFrame(plines, columns=COLUMNS['purchase_lines']),
             stock_moves=pd.DataFrame(moves, columns=COLUMNS['stock_moves'] + ['seq']),
             prices=pd.DataFrame(price_rows, columns=COLUMNS['prices']),
             lots=pd.DataFrame(lots, columns=COLUMNS['lots']),
             line_lots=pd.DataFrame(line_lots, columns=COLUMNS['line_lots']),
             expenses=pd.DataFrame(expenses, columns=COLUMNS['expenses']),
             deliveries=pd.DataFrame(deliveries, columns=COLUMNS['deliveries']),
             visits=pd.DataFrame(visits, columns=COLUMNS['visits']))
    if drugs is not None:
        T['drugs'] = drugs
    caps = {'customers', 'customer_ids', 'customer_groups', 'staff', 'time', 'channel', 'payment_method', 'debt',
            'purchases', 'stock', 'prices', 'unit_cost', 'units', 'groups', 'order_ids', 'product_ids',
            'stock_history', 'payments', 'catalog_cost'}
    if spec['lots']:
        caps.add('lots')
    if drugs is not None:
        caps.add('drugs')
    if expenses:
        caps.add('expenses')
    if deliveries:
        caps.add('deliveries')
    if vis_kind == 'tables' and visits:
        caps |= {'tables', 'guests'}
    if vis_kind == 'plates' and visits:
        caps.add('plates')
    caps -= set(spec.get('caps_drop', ()))
    shop = dict(business_id=spec['business_id'], name=f"{meta['label'].title()} {person_name(rng).split()[-1]}",
                industry=ind, start=start, end=end, caps=caps, shop_word=meta['shop_word'], spec=spec)
    return Ledger(shop, T)


class _R:                                      # default Tết bounds for the simulator's seasonality
    week_start = 0
    tet_start = (12, 23)
    tet_end = (1, 10)
