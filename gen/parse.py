"""Train question -> oracle spec (intent + params), by rules on the normalized text and the shop's ledger names.

Used to calibrate the oracle against the train gold answers and to re-ask train intents with new parameters.
Returns None when no rule matches (the question is left out, never guessed).
"""
from __future__ import annotations

import datetime as dt
import re

from .textnorm import fold, norm_question


def _d(s):
    d, m, y = (int(x) for x in s.split('/'))
    return dt.date(y, m, d)


DATE = r'(\d{1,2}/\d{1,2}/\d{4})'


def _month_spec(y, m):
    return {'kind': 'month', 'y': int(y), 'm': int(m)}


def find_months(t):
    out = []
    for m in re.finditer(r'thang (\d{1,2})(?:/| nam )(\d{4})', t):
        out.append(_month_spec(m[2], m[1]))
    if re.search(r'\bthang\b', t):                      # "3 tháng 11/2025, 12/2025, 1/2026": bare M/YYYY after a month word
        bare = [_month_spec(m[2], m[1]) for m in re.finditer(r'(?<![\d/])(\d{1,2})/(\d{4})', t)]
        if len(bare) > len(out):
            out = bare
    if len(out) == 2 and re.search(r'tu thang \S+ (?:den|toi) thang', t):   # "từ tháng 8/2025 tới tháng 10/2025": every month
        a, b = out
        i, j = a['y'] * 12 + a['m'] - 1, b['y'] * 12 + b['m'] - 1
        if 0 < j - i < 24:
            out = [_month_spec(k // 12, k % 12 + 1) for k in range(i, j + 1)]
    return out


def find_period(t, as_of):
    if m := re.search(r'tu (?:ngay )?' + DATE + r' den (?:het )?(?:ngay )?' + DATE, t):
        return {'kind': 'range', 'start': _d(m[1]), 'end': _d(m[2])}
    if m := re.search(r'quy (\d)(?:/| nam )(\d{4})', t):
        return {'kind': 'quarter', 'y': int(m[2]), 'q': int(m[1])}
    if m := re.search(r'thang (\d{1,2})(?:/| nam )(\d{4})', t):
        return _month_spec(m[2], m[1])
    if re.search(r'\btet\b', t):
        if m := re.search(r'tet (?:nam )?(\d{4})', t):
            return {'kind': 'tet', 'year': int(m[1])}
        return {'kind': 'tet', 'year': as_of.year}
    if re.search(r'thang nay|dau thang nay', t):
        return {'kind': 'this_month'}
    if re.search(r'tuan (roi|truoc)', t):
        return {'kind': 'last_week'}
    if re.search(r'tuan nay', t):
        return {'kind': 'this_week'}
    if m := re.search(r'(\d+) ngay gan (nhat|day)', t):
        return {'kind': 'last_n_days', 'n': int(m[1])}
    if re.search(r'dau nam|ngay 1/1 den|nam nay', t):
        return {'kind': 'ytd'}
    if re.search(r'hom qua', t):
        return {'kind': 'yesterday'}
    if re.search(r'hom nay', t):
        return {'kind': 'today'}
    if m := re.search(r'ngay ' + DATE, t):
        return {'kind': 'day', 'date': _d(m[1])}
    return None


def find_date(t, as_of):
    """'đến hết ngày X', 'cuối ngày hôm nay' -> the date of a stock/debt question."""
    if m := re.search(r'(?:het|cuoi|den) (?:ngay )?' + DATE, t):
        return _d(m[1])
    if m := re.search(r'ngay ' + DATE, t):
        return _d(m[1])
    return as_of


def _toks(s):
    return ' '.join(re.findall(r'[a-z]+|\d+', s))


class Names:
    """Folded names of the ledger, longest first, for finding the entity a question names."""

    def __init__(self, L):
        self.L = L
        p = L.products
        # keys go through the question normalizer, so a name reads the same as in a normalized question ('Air-X' -> 'ai x')
        self.products = sorted(((norm_question(str(n)), pid) for pid, n in zip(p.product_id, p.name)), key=lambda t: -len(t[0]))
        self.groups = sorted({norm_question(str(g)): g for g in p.group.dropna()}.items(), key=lambda t: -len(t[0]))
        c = L.customers
        self.customers = sorted(((norm_question(re.sub(r'[\d()\-+]+', ' ', str(n))).strip(), cid)
                                 for cid, n in zip(c.customer_id, c.name)), key=lambda t: -len(t[0]))
        s = L.staff
        self.staff = [(norm_question(str(n)), sid) for sid, n in zip(s.staff_id, s.name)]
        d = L.drugs
        self.ingredients = sorted({norm_question(str(i)): i for i in d.ingredient.dropna()}.items(), key=lambda t: -len(t[0]))
        units = set(L.products.base_unit.dropna().map(fold)) | set(L.units.unit.dropna().map(fold))
        self.units = sorted(units, key=len, reverse=True)

    @staticmethod
    def _find(t, pairs):
        t2 = ' ' + _toks(t) + ' '
        for key, val in pairs:
            k2 = ' ' + _toks(key) + ' '
            if len(k2) > 3 and k2 in t2:
                return val
        return None

    def product(self, t):
        return self._find(t, self.products)

    @staticmethod
    def take(t, pairs, placeholder, start=0):
        """(value, t with the name's span replaced by a placeholder word) for the first (longest) name found in t[start:],
        so words inside a name ('Bánh tét', 'Quang Huy', 'nhóm kê đơn') never trigger an intent rule."""
        spans = [(m.start(), m.end(), m[0]) for m in re.finditer(r'[a-z]+|\d+', t) if m.start() >= start]
        toks = [x[2] for x in spans]
        for key, val in pairs:
            k = re.findall(r'[a-z]+|\d+', key)
            if not k or len(' '.join(k)) < 2:
                continue
            for i in range(len(toks) - len(k) + 1):
                if toks[i:i + len(k)] == k:
                    return val, t[:spans[i][0]] + placeholder + t[spans[i + len(k) - 1][1]:]
        return None, t

    def group(self, t):
        m = re.search(r'nhom (?:hang )?(.+)', t)
        return self._find(m[1], self.groups) if m else None

    def customer(self, t):
        return self._find(t, self.customers)

    def staff_id(self, t):
        if m := re.search(r'\bnv ?(\d{3})\b', t):
            return 'NV' + m[1]
        return self._find(t, self.staff)

    def ingredient(self, t):
        m = re.search(r'hoat chat (.+)', t)
        return self._find(m[1], self.ingredients) if m else None

    def unit_after(self, t, words=r'bao nhieu|may|so|tinh theo|theo'):
        for u in self.units:
            if re.search(rf'(?:{words}) {re.escape(u)}\b', t):
                return u
        return None


SUBJECTIVE = (r'tan tam|le phep|chu dao|tay nghe|lanh nghe|khen|quy men|nen uong|moi lan may|nha o duong|'
              r'khach (o )?duong|khach nu|khach nam\b(?! (nay|ngoai|truoc|\d))|\bvi (loi|mua nham|giao tre)|tra vi|\bly do (khach|tra|huy|ma|gi)|'
              r'thai do|nhiet tinh|\bhai long|lieu dung|tac dung phu|gioi tinh')


def price_change_date(L, pid, price):
    """First date the item's price list rises to `price` (§5 Hiệu ứng tăng giá)."""
    p = L.prices[L.prices.product_id == pid].sort_values('date')
    prev = None
    for d, v in zip(p.date, p.price):
        if prev is not None and v > prev:
            per_unit = {v} | {v * f for f in L.units[L.units.product_id == pid].factor}
            if any(abs(x - price) < 0.5 for x in per_unit):
                return d.date()
        prev = v
    return None


def _money(s):
    return int(re.sub(r'[.,]', '', s))


def _orig_unit(L, pid, folded_unit):
    if folded_unit is None:
        return None
    cands = [L.products.set_index('product_id').base_unit.get(pid)] + list(L.units[L.units.product_id == pid].unit)
    for c in cands:
        if c is not None and fold(c) == folded_unit:
            return c
    return None


def _cmp_pair(months, t):
    """(period, reference) of a two-month comparison: 'So với tháng 3/2025, doanh thu tháng 4/2025 ...' names the
    reference first."""
    m = re.search(r'\bso (?:voi |vs )?thang (\d{1,2})(?:/| nam )(\d{4})', t)
    if m and _month_spec(m[2], m[1]) == months[0]:
        return months[1], months[0]
    return months[0], months[1]


def _this_month_words(spec, t):
    """'Tháng này' vs the previous month: the window the question's words fix ('cùng kỳ / cùng số ngày của tháng
    trước' = same days, 'cả tháng trước' = whole month) wins over the rulebook; plain 'tháng trước' leaves it to the
    rulebook (no ref_text)."""
    if (spec.get('period') or {}).get('kind') != 'this_month':
        return spec
    if re.search(r'cung ky(?! nam)|cung so ngay|cung khoang', t):
        return {**spec, 'ref_text': 'same_days'}
    if re.search(r'(ca|tron|toan bo|het) thang (truoc|roi|lien truoc)', t):
        return {**spec, 'ref_text': 'full'}
    return spec


def parse(question, as_of, L, names: Names | None = None):
    names = names or Names(L)
    t = norm_question(question)
    grp0 = staff0 = None
    if (gm := re.search(r'nhom (?:hang )?', t)) and not re.search(r'nhom (si|le|than thiet|vip)\b', t):
        grp0, t = names.take(t, names.groups, 'xgrp', gm.end())
    item, t = names.take(t, names.products, 'xsp')
    if re.search(r'nhan vien|nguoi ban', t):
        staff0, t = names.take(t, names.staff, 'xnv')
    ing0 = None
    if hm := re.search(r'hoat chat ', t):
        ing0, t = names.take(t, names.ingredients, 'xhc', hm.end())
    cust0 = None
    if re.search(r'no them|mua chiu them|ghi no them', t):
        cust0, t = names.take(t, names.customers, 'xkh')
    per = find_period(t, as_of)
    unit = names.unit_after(t)
    S = lambda intent, **kw: {'intent': intent, **kw}

    # ---- questions the data never answers (opinions, facts no shop file records)
    if re.search(SUBJECTIVE, t):
        return {'intent': 'unanswerable'}

    # ---- debt
    if re.search(r'tuoi no', t):
        edges = [int(m[2]) for m in re.finditer(r'(?<![\d/])(\d+) ?- ?(\d+)(?![\d/])', t)]
        extra = {'edges': edges} if len(edges) >= 2 and edges != [7, 15] else {}
        return S('debt_aging', date=find_date(t, as_of), **extra)
    if re.search(r'no them|mua chiu them|ghi no them', t):
        cust = cust0 or names.customer(t)
        return S('debt_new_paid', customer=cust, period=per) if cust else S('debt_new', period=per)
    if re.search(r'tra no|thu hoi|tra bot no|cong no tu khach', t) and per:
        return S('debt_collected', period=per)
    if re.search(r'\bno\b|cong no|chua tra het|con thieu', t):
        date = find_date(t, as_of)
        if m := re.search(r'(?:qua|hon) (\d+) ngay', t):
            return S('debt_over_age', date=date, days=int(m[1]))
        if m := re.search(r'(\d+) khach', t):
            return S('debt_top', date=date, k=int(m[1]))
        if re.search(r'(so|bao nhieu|may) khach|con bao nhieu khach|khach chua tra het', t) and not re.search(r'bao nhieu tien|so tien|tong cong|tong so tien', t):
            return S('debt_customers', date=date)
        return S('debt_total', date=date)

    # ---- lots / expiry
    if re.search(r'het han\b|han dung', t):
        date = as_of
        if m := re.search(r'tu ' + DATE, t):
            date = _d(m[1])
        n = None
        if m := re.search(r'(\d+) ngay toi', t):
            n = int(m[1])
        elif m := re.search(r'tu ' + DATE + r' den (?:het )?(?:ngay )?' + DATE, t):
            n = (_d(m[2]) - _d(m[1])).days
        if re.search(r'gan het han nhat|som nhat', t) and item:
            return S('nearest_lot_expiry', item=item, date=find_date(t, as_of) if 'het ngay' in t else as_of)
        if n is None:
            return None
        if re.search(r'tien von|tien|gia tri', t):
            return S('expiring_value', date=date, n=n)
        if re.search(r'may mat hang|bao nhieu mat hang|so mat hang', t):
            return S('expiring_count', date=date, n=n)
        return S('expiring_items', date=date, n=n)

    # ---- price effect
    if re.search(r'tang gia|len gia|doi gia', t) and item:
        m = re.search(r'(\d+) ngay', t)
        dm = re.search(DATE, t)
        date = _d(dm[1]) if dm else None
        if date is None and (pm := re.search(r'len (?:gia )?(\d[\d.,]*) (?:dong|d\b)', t)):
            date = price_change_date(L, item, _money(pm[1]))
        if m and date:
            return S('price_effect', item=item, date=date, n=int(m[1]))

    # ---- stock
    if re.search(r'gia tri.*\bkho\b|\bkho\b.*(dang|gia tri|tien)|tien hang (nam )?trong kho|hang con trong kho dang', t):
        return S('stock_value', date=find_date(t, as_of))
    if re.search(r'het hang', t):
        return S('out_of_stock_count', date=find_date(t, as_of))
    if re.search(r'ton kho|trong kho|con lai|con bao nhieu|con may', t) and item:
        date = find_date(t, as_of)
        if re.search(r'\b(chan|nguyen)\b', t):
            big = None
            for u in names.units:
                if re.search(rf'\b{re.escape(u)} (?:xsp )?(chan|nguyen)\b', t):
                    big = u
                    break
            return S('stock_big_small', item=item, date=date, big_unit=_orig_unit(L, item, big))
        return S('stock_end', item=item, date=date, unit=_orig_unit(L, item, unit))

    # ---- purchases
    if re.search(r'nhap tru|tru so ban|chenh', t) and item:
        return S('purchase_minus_sales', item=item, period=per, unit=_orig_unit(L, item, unit))
    if re.search(r'nhap.*binh quan|binh quan.*nhap|gia nhap', t) and item:
        u = None
        for x in names.units:
            if re.search(rf'(?:mot|1) {re.escape(x)}\b', t):
                u = x
                break
        return S('avg_purchase_price', item=item, period=per, unit=_orig_unit(L, item, u))
    if re.search(r'nha cung cap', t):
        return S('top_supplier', period=per)
    if re.search(r'nhap', t) and re.search(r'tien|gia tri|phieu', t):
        return S('purchase_total', period=per)

    # ---- profit
    if re.search(r'lai rong|loi rong|loi nhuan rong|tru het chi phi', t):
        return S('net_profit', period=per)
    if re.search(r'(?<!cong )\blai\b|\bloi\b|loi nhuan', t):
        if re.search(r'hang nao|mat hang|san pham|mon nao', t):
            return S('top_items', by='profit', period=per, k=1)
        return S('gross_profit', period=per)

    # ---- price on a day
    if re.search(r'don gia|gia bao nhieu|gia ban|ban .* gia', t) and item and re.search(DATE, t):
        u = None
        for x in names.units:
            if re.search(rf'(?:mot|1) {re.escape(x)}\b', t):
                u = x
                break
        return S('price_on_day', item=item, date=_d(re.search(DATE, t)[1]), unit=_orig_unit(L, item, u))

    # ---- pharmacy
    if re.search(r'hoat chat', t):
        ing = ing0 or names.ingredient(t)
        return S('ingredient_revenue', ingredient=ing, period=per) if ing else None
    if re.search(r'ke don', t):
        rx = not re.search(r'khong (can )?(phai )?ke don|tru thuoc ke don', t)
        if re.search(r'%|phan tram|ti le|ty le|chiem', t):
            return S('rx_share', rx=rx, period=per)
        return S('rx_revenue', rx=rx, period=per)

    # ---- deliveries
    if re.search(r'dot (giao|hang)|giao hang', t):
        return S('deliveries_count', period=per)

    # ---- cancel
    if re.search(r'\bhuy\b', t):
        if re.search(r'%|phan tram|ti le|ty le', t):
            return S('cancel_rate', period=per)
        return S('cancel_count', period=per)

    # ---- shifts
    if re.search(r'ca (sang|chieu)', t):
        if re.search(r'ca chieu.*ca sang|so voi ca sang', t) and re.search(r'%|phan tram', t):
            return S('shift_change_pct', period=per, measure='orders' if re.search(r'so don|bao nhieu don', t) else 'revenue')
        shift = 'morning' if 'ca sang' in t else 'afternoon'
        if re.search(r'(may|bao nhieu|so) don', t):
            return S('shift_orders', shift=shift, period=per)
        return S('shift_revenue', shift=shift, period=per)

    # ---- staff
    if re.search(r'nhan vien|nguoi ban', t):
        sid = names.staff_id(t) or staff0
        if sid:
            return S('staff_revenue', staff=sid, period=per)
        if re.search(r'cao nhat|nhieu nhat|gioi nhat|nhieu tien nhat', t):
            return S('top_staff', period=per)
        return None

    # ---- payment methods / channels
    PAY = [('cod', 'cod'), ('vi dien tu', 'ewallet'), ('tien mat', 'cash'), ('tien tuoi', 'cash'), ('chuyen khoan', 'transfer'),
           ('ghi no', 'debt')]
    CH = [('dien thoai', 'phone'), ('tai quay', 'store'), ('zalo', 'zalo_oa')]
    found = sorted([(t.find(k), v) for k, v in PAY if k in t])
    if found and re.search(r'tra bang|thanh toan|cac don', t):
        if re.search(r'%|phan tram|chiem', t) and len(found) == 1:
            return S('payment_share', method=found[0][1], period=per)
        return S('payment_revenue', methods=[v for _, v in found], period=per)
    found = sorted([(t.find(k), v) for k, v in CH if k in t])
    if found:
        if re.search(r'%|phan tram|chiem', t) and len(found) == 1:
            return S('channel_share', channel=found[0][1], period=per)
        return S('channel_revenue', channels=[v for _, v in found], period=per)

    # ---- customer groups
    if m := re.search(r'nhom (si|le|than thiet|vip)\b', t):
        g = {'si': 'sỉ', 'le': 'lẻ', 'than thiet': 'thân thiết', 'vip': 'vip'}[m[1]]
        if re.search(r'%|phan tram|chiem|phan cua', t):
            return S('cust_group_share', group=g, period=per)
        return S('cust_group_revenue', group=g, period=per)

    # ---- customers
    if re.search(r'khach', t):
        n = re.search(r'(?:it nhat|tu|>=) (\d+) don', t)
        if n:
            if re.search(r'%|phan tram|ti le|ty le', t):
                return S('customers_min_orders_share', n=int(n[1]), period=per)
            return S('customers_min_orders', n=int(n[1]), period=per)
        k = re.search(r'(?<![/\d])\b(\d{1,2}) khach', t)
        if not k and re.search(r'(bao nhieu|may|so) khach', t):
            return S('customer_count', period=per)
        by = 'orders' if re.search(r'nhieu don|so don|nhieu lan', t) else 'revenue'
        if k:
            return S('top_customers', k=int(k[1]), by=by, period=per)
        if re.search(r'nhat', t):
            return S('top_customers', k=1, by=by, period=per)
    if re.search(r'\bai (mua|chi)', t) and re.search(r'nhat', t) and not re.search(r'khong ai mua', t):
        by = 'orders' if re.search(r'nhieu don|so don|nhieu lan', t) else 'revenue'
        return S('top_customers', k=1, by=by, period=per)

    # ---- items in N orders
    if m := re.search(r'(\d+) don(?: hang)? khac nhau|(?:it nhat|tu) (\d+) don', t):
        if re.search(r'mat hang|san pham', t):
            return S('items_min_orders', n=int(m[1] or m[2]), period=per)

    # ---- unsold
    if re.search(r'(mat hang|hang|san pham) e\b|\be han\b|khong ban (ra )?duoc|khong ai mua|ko ai mua', t):
        return S('unsold_count', period=per)

    # ---- top items
    if re.search(r'ban chay|hot nhat|ban nhieu nhat|ban duoc nhieu nhat|chay nhat', t) and not item:
        k = re.search(r'(\d+) (?:mat hang|san pham|mon|hang)', t)
        if k:
            return S('top_items', k=int(k[1]), by='qty', period=per, as_list=True)
        return S('top_items', k=1, by='qty', period=per)
    if not item and re.search(r'\b(hang|mon|san pham) nao|(\d+) (mat hang|san pham|mon)', t) and \
            re.search(r'(doanh thu|nhieu tien) (cao|lon|nhieu) nhat|nhieu tien nhat', t):
        k = re.search(r'(?<![/\d])\b(\d{1,2}) (?:mat hang|san pham|mon|hang)', t)
        if k:
            return S('top_items', k=int(k[1]), by='revenue', period=per, as_list=True)
        return S('top_items', k=1, by='revenue', period=per)

    # ---- monthly comparisons
    months = find_months(t)
    if len(months) >= 3 and re.search(r'lan luot|tung thang|moi thang', t):
        return S('revenue_list', periods=months)
    if re.search(r'tang lien tuc|tang deu', t) and len(months) >= 2:
        return S('revenue_trend_up', periods=months)
    if re.search(r'thang nao', t) and len(months) >= 2:
        return S('best_month', periods=months)
    if m := re.search(r'(\d) thang lien (nhau|tiep)', t):
        if re.search(r'ket thuc', t) and months:
            end = months[0]
            out = []
            for i in range(int(m[1]) - 1, -1, -1):
                y, mo = divmod(end['y'] * 12 + end['m'] - 1 - i, 12)
                out.append(_month_spec(y, mo + 1))
            return S('revenue_list', periods=out)
        if len(months) >= 2:
            a, b = months[0], months[-1]
            out = []
            i = a['y'] * 12 + a['m'] - 1
            while i <= b['y'] * 12 + b['m'] - 1:
                out.append(_month_spec(i // 12, i % 12 + 1))
                i += 1
            return S('revenue_list', periods=out)

    if re.search(r'ngay nao', t):
        return S('best_day', period=per, worst=bool(re.search(r'thap nhat|it nhat|it tien nhat', t)))
    if re.search(r'may ngay|so ngay|bao nhieu ngay', t):
        m = re.search(r'(\d[\d.,]*) (?:dong|d\b)', t)
        if m:
            return S('days_over', threshold=_money(m[1]), period=per)

    # ---- growth
    if re.search(r'%|phan tram|tang truong', t) and re.search(r'so voi|so vs|\bso cung ky|tang hay giam|tang ?/ ?giam|thay doi|hon hay kem', t):
        if len(months) >= 2:
            a, b = _cmp_pair(months, t)
            return S('revenue_change_pct', period=a, ref=b)
        if per and per['kind'] == 'month' and re.search(r'cung ky nam (ngoai|truoc)', t):
            return S('revenue_change_pct', period=per, ref={**per, 'y': per['y'] - 1})
        if per and per['kind'] == 'tet' and re.search(r'nam ngoai|nam truoc', t):
            return S('revenue_change_pct', period=per)
        if per and per['kind'] == 'tet' and re.search(r'truoc tet', t):
            m = re.search(r'(\d+) ngay (?:ngay )?truoc tet', t)       # the question names the days: they win
            return S('revenue_change_pct', period=per,
                     ref={'kind': 'before_tet', 'days': int(m[1])} if m else 'before_tet')
        return _this_month_words(S('revenue_change_pct', period=per), t)
    if re.search(r'doanh thu|ban duoc', t) and re.search(r'so voi|so vs|tru di|tru doanh thu|chenh lech', t) and \
            re.search(r'tien|dong|bao nhieu', t):
        if len(months) >= 2:
            a, b = _cmp_pair(months, t)
            return S('revenue_diff', period=a, ref=b)
        if per and per['kind'] == 'month' and re.search(r'cung ky nam (ngoai|truoc)', t):
            return S('revenue_diff', period=per, ref={**per, 'y': per['y'] - 1})
        return _this_month_words(S('revenue_diff', period=per), t)

    if re.search(r'tien hang|doanh thu', t) and re.search(r'don', t) and (m := re.search(r'(\d[\d.,]*) (?:dong|d\b)', t)):
        return S('orders_over', threshold=_money(m[1]), period=per)

    if re.search(r'trung binh|binh quan', t):
        return S('avg_order', period=per)

    # ---- group / share
    grp = grp0 or names.group(t)
    if grp:
        if re.search(r'%|phan tram|chiem|ti trong|ty trong|dong gop', t):
            return S('group_share', group=grp, period=per)
        return S('revenue_group', group=grp, period=per)

    # ---- size
    if m := re.search(r'size (m|l)\b', t):
        return S('qty_size', size=m[1].upper(), period=per)

    # ---- quantities
    if item and unit and re.search(r'(bao nhieu|may|so) ' + re.escape(unit), t):
        return S('qty_item', item=item, unit=_orig_unit(L, item, unit), period=per)
    if item:
        return S('revenue_item', item=item, period=per)
    if unit and re.search(r'(bao nhieu|may|so) ' + re.escape(unit) + r'\b', t) and not re.search(r'(may|bao nhieu|so) don', t):
        base = {fold(u): u for u in L.products.base_unit.dropna()}
        if unit in base:
            return S('qty_unit', unit=base[unit], period=per)

    if re.search(r'(may|bao nhieu|so) don|so don|don hang', t) and not re.search(r'doanh thu|tien', t):
        return S('order_count', period=per)
    if re.search(r'doanh thu|tien|ban duoc', t) and per:
        return S('revenue', period=per)
    return None
