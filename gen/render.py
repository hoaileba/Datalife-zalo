"""Render a canonical ledger (gen.ledger) as one shop folder in an "export format family", plus README.md.

render(ledger, family, out_dir, rng, noise=None) -> {'files', 'caps', 'family', 'aliases', 'extras', 'noise'}
families_for(ledger) -> families whose needs the ledger meets.

Families (train shops in brackets): H sqlite [123], G normalized CSV [111/127/129], E KiotViet list exports
[106/108/119/120/128; 109 workbook], F MISA sổ chi tiết bán hàng [112/115/116/118/130], D Sapo DonHang_ChiTiet with
fill-down [102/103/104/121/122], A flat CSV of lines [101/114/125], B owner's notebook [107/113/126], C handwritten
monthly ledger [105/117]; new (not in train): S Google-Sheets CSV export with English headers, P pivot workbook
(daily summary sheet + quarterly detail sheets).

The renderer changes presentation only. Gold answers come from the ledger; the only facts added are ones the ledger
has no field for (due days of debt orders, which delivery trip carries which line) and they are returned in
'extras'. 'caps' = the ledger's caps the files still carry, plus markers: 'stock_history' (stock card rows, else only
end stock), 'payments' (one row per payment, else only end debt), 'catalog_cost'.
"""
from __future__ import annotations

import csv
import datetime as dt
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import noise as N
from .pools import (DOC, DOC_MASTER, FIELD_KIND, FILLER_CUSTOMER, FILLER_DOC, FILLER_ORDER, FILLER_PRODUCT, MONTH_SHEET,
                    SYN, SYN_EN)
from .xlsx import write_xlsx

FAMILIES = ['H', 'G', 'E', 'F', 'D', 'A', 'B', 'C', 'S', 'P']
SPLIT_ROWS = 100_000
FILL_KEYS = ('order_id', 'date', 'status', 'customer_name')


# ---------------------------------------------------------------- output model
@dataclass
class Sheet:
    name: str
    headers: list
    keys: list
    rows: list
    above: list = field(default_factory=list)      # title / filter rows above the header
    group: list | None = None                       # grouped header row right above the header
    below: list = field(default_factory=list)       # notes after the data

    def grid(self):
        out = [list(r) for r in self.above]
        if self.group is not None:
            out.append(self.group)
        return out + [self.headers] + self.rows + [list(r) for r in self.below]


@dataclass
class OutFile:
    name: str
    sheets: list
    role: str = 'list'           # sales | list ; README documents sales files at the 'partial' level
    master: bool = False         # README describes names as "tên" (entity list)


@dataclass
class Ctx:
    L: object
    rng: np.random.Generator
    nz: N.Noise
    family: str
    files: list = field(default_factory=list)
    caps: set = field(default_factory=set)
    conventions: list = field(default_factory=list)     # (kind, params)
    intro: list = field(default_factory=list)
    aliases: dict = field(default_factory=lambda: {'product': {}, 'customer': {}})
    extras: dict = field(default_factory=dict)
    doc_override: dict = field(default_factory=dict)   # (file, header) -> doc

    def keep(self, *caps):
        self.caps |= {c for c in caps if self.L.has(c)}

    def alias(self, kind, key, text):
        if key is not None and isinstance(text, str):
            self.aliases[kind].setdefault(key, set()).add(text)


# ---------------------------------------------------------------- canonical views
def _isna(v):
    return v is None or (isinstance(v, float) and v != v) or v is pd.NaT


def views(L):
    """(orders, lines) DataFrames with names, dates and payment state joined in."""
    P = L.products.set_index('product_id')
    C = L.customers.set_index('customer_id') if len(L.customers) else pd.DataFrame(columns=['name', 'phone', 'group'])
    o = L.orders.copy()
    o['created'] = pd.to_datetime(o['created'])
    o['date'] = o['created'].dt.normalize()
    paid = L.payments.groupby('order_id')['amount'].sum() if len(L.payments) else pd.Series(dtype=float)
    o['paid'] = o['order_id'].map(paid).fillna(0)
    o.loc[o['status'] == 'cancelled', 'paid'] = 0
    o['debt_left'] = np.where(o['status'] == 'cancelled', 0, (o['total'] - o['paid']).clip(lower=0))
    o['customer_id'] = o['customer_id'].where(o['customer_id'].notna(), None)
    o['customer_name'] = o['customer_id'].map(C['name']) if len(C) else None
    o = o.sort_values(['created', 'order_id'], kind='mergesort').reset_index(drop=True)
    keep = ['order_id', 'created', 'date', 'status', 'customer_id', 'customer_name', 'payment_method', 'channel',
            'staff_id']
    ln = L.lines.merge(o[keep], on='order_id', how='inner')
    ln['product_name'] = ln['product_id'].map(P['name'])
    ln['group'] = ln['product_id'].map(P['group'])
    ln['base_unit'] = ln['product_id'].map(P['base_unit'])
    ln['kind'] = ln['product_id'].map(P['kind']) if 'kind' in P else 'goods'
    ln = ln.sort_values(['created', 'order_id', 'line_no'], kind='mergesort').reset_index(drop=True)
    return o, ln


def end_stock(L):
    """Balance per product at the end of the data (last stock card row); NaN when the product has no stock card
    (made-to-order items, fees): such products are left out of stock lists, never written as 0."""
    if not len(L.stock_moves):
        return None
    m = L.stock_moves.copy()
    m['time'] = pd.to_datetime(m['time'])
    sort = ['time', 'seq'] if 'seq' in m else ['time']
    last = m.sort_values(sort, kind='mergesort').groupby('product_id')['balance'].last()
    return L.products['product_id'].map(last)


def walkin_names(nz):
    return set(nz.walkin)


# ---------------------------------------------------------------- display of names, statuses
class Display:
    """Per-shop writings: order -> status label / customer writing; product rows -> name writing."""

    def __init__(self, ctx: Ctx, orders, codes_for_customers: bool, product_variants=True, english=None):
        self.ctx, rng, nz = ctx, ctx.rng, ctx.nz
        labels = english or nz.status_labels
        self.status = {oid: N.label(s, labels, rng) for oid, s in zip(orders['order_id'], orders['status'])}
        ctx.extras['status_map'] = {lab: st for st, labs in labels.items() for lab in labs}
        self.customer = {}
        for oid, cid, name in zip(orders['order_id'], orders['customer_id'], orders['customer_name']):
            if cid is None or _isna(name):
                self.customer[oid] = N._pick(rng, nz.walkin)
                continue
            text = name
            if rng.random() < nz.cust_variant_p:
                lv = N.letter_variant(name) if codes_for_customers and rng.random() < 0.3 else None
                text = lv or N._pick(rng, N.spelling_variants(name, rng, 1))
            self.customer[oid] = text
            ctx.alias('customer', cid, text)
        P = ctx.L.products
        self.prod_variants = {}
        if product_variants:
            for pid, name in zip(P['product_id'], P['name']):
                if rng.random() < nz.prod_variant_share and str(name).strip().lower() != 'phí phục vụ':
                    self.prod_variants[pid] = N.spelling_variants(str(name), rng)

    def product(self, pid, name):
        v = self.prod_variants.get(pid)
        text = name if not v or self.ctx.rng.random() >= self.ctx.nz.prod_variant_p else N._pick(self.ctx.rng, v)
        self.ctx.alias('product', pid, text)
        return text


# ---------------------------------------------------------------- column layout
def _fold(s):
    return N.strip_accents(str(s)).lower().replace(' ', '')


def choose_headers(keys, rng, vendor=None, synonyms=True, pools=None):
    """A header per key: the vendor's name when given (and synonyms off), else a random synonym; unique by fold."""
    pools = pools or SYN
    used, out = set(), []
    for k in keys:
        cands = []
        if vendor and k in vendor and not synonyms:
            cands = [vendor[k]]
        cands += [c for c in rng.permutation(pools.get(k, SYN.get(k, [k]))).tolist()]
        h = next((c for c in cands if _fold(c) not in used), None) or f'{cands[0]} ({len(out) + 1})'
        used.add(_fold(h))
        out.append(h)
    return out


def arrange(keys, headers, rng, shuffle):
    idx = list(range(len(keys)))
    if shuffle:
        idx = rng.permutation(len(keys)).tolist()
    return [keys[i] for i in idx], [headers[i] for i in idx]


@dataclass
class Fmt:
    money: dict = field(default_factory=lambda: {'int': 1.0})
    date: str = 'dmy'
    datetime: str = 'cell'             # cell (real datetime) | iso_dt | dmy_hm
    qty_rate: float = 0.0
    xlsx: bool = True
    noyear_rate: float = 0.0
    serial: bool = True                # allow Excel serials (per shop knob) in date columns


def cell_values(df, key, fmt: Fmt, ctx: Ctx):
    """Formatted cells of one canonical column."""
    rng, nz = ctx.rng, ctx.nz
    kind = FIELD_KIND.get(key, 'text')
    vals = df[key].tolist() if key in df else [None] * len(df)
    if kind == 'money':
        return [N.money(v, fmt.money, rng) for v in vals]
    if kind == 'qty':
        units = df['unit'].tolist() if 'unit' in df else [None] * len(df)
        return [N.qty(v, u, fmt.qty_rate, rng) for v, u in zip(vals, units)]
    if kind == 'num':
        return [N.num(v) for v in vals]
    if kind == 'bool':
        return [None if _isna(v) else bool(v) for v in vals]
    if kind == 'date':
        knobs = nz if fmt.serial and fmt.xlsx else N.Noise(serial_rate=0.0, thg_rate=nz.thg_rate)
        out = []
        for v in vals:
            d = N.to_py_datetime(v)
            out.append(None if d is None else N.date_cell(d, fmt.date, knobs, rng, fmt.xlsx, fmt.noyear_rate))
        return out
    if kind == 'datetime':
        out = []
        for v in vals:
            d = N.to_py_datetime(v)
            if d is None:
                out.append(None)
            elif fmt.datetime == 'cell' and fmt.xlsx:
                out.append(d)
            else:
                out.append(N.date_text(d, 'iso_dt' if fmt.datetime in ('cell', 'iso_dt') else 'dmy_hm'))
        return out
    return [None if _isna(v) else (v if isinstance(v, str) else (N.num(v) if isinstance(v, (int, float, np.number))
                                                                 else str(v))) for v in vals]


def table_rows(df, keys, fmt, ctx):
    cols = [cell_values(df, k, fmt, ctx) for k in keys]
    return [list(r) for r in zip(*cols)] if cols else []


FILLER_VALUES = {
    'Được bán trực tiếp': lambda r: 1, 'Tồn lớn nhất': lambda r: 999999999, 'Định mức tồn tối đa': lambda r: 999999999,
    'Tồn nhỏ nhất': lambda r: 0, 'Định mức tồn tối thiểu': lambda r: 0, 'Loại hàng hóa': lambda r: 'Hàng hóa',
    'Mã barcode': lambda r: (str(8930000000000 + int(r.integers(10 ** 9, 10 ** 10)))[:13] if r.random() < 0.3 else None),
    'Trạng thái': lambda r: 'Đang hoạt động', 'Người tạo': lambda r: 'admin', 'Loại hình khách': lambda r: 'Cá nhân',
    'Tổng điểm': lambda r: 0, 'Điểm tích lũy': lambda r: 0,
    'Ngày sinh': lambda r: (f'{int(r.integers(1, 29)):02d}/{int(r.integers(1, 13)):02d}/{int(r.integers(1965, 2004))}'
                            if r.random() < 0.2 else None),
}


def add_fillers(keys, headers, rows, pool, rng, k_range=(3, 9)):
    """Filler columns (blank or constant) mixed into a master list."""
    k = int(rng.integers(*k_range))
    taken = {_fold(h) for h in headers}
    picks = [h for h in rng.permutation(pool).tolist() if _fold(h) not in taken][:k]
    for h in picks:
        f = FILLER_VALUES.get(h, lambda r: None)
        keys.append('filler')
        headers.append(h)
        for row in rows:
            row.append(f(rng))
    return keys, headers, rows


def shuffle_cols(keys, headers, rows, rng):
    idx = rng.permutation(len(keys)).tolist()
    return [keys[i] for i in idx], [headers[i] for i in idx], [[r[i] for i in idx] for r in rows]


def month_sheets(df, rng, pattern=None):
    """[(sheet name, frame)] one per month of df['date'] (or 'del_date' ...), in time order."""
    pattern = pattern or N._pick(rng, MONTH_SHEET)
    col = 'date' if 'date' in df else df.columns[0]
    per = pd.to_datetime(df[col]).dt.to_period('M')
    return [(pattern.format(m=p.month, y=p.year), g) for p, g in df.groupby(per, sort=True)], pattern


def split_files(stem, ext, sheets_or_rows, rng, limit=SPLIT_ROWS):
    """File names for a table too long for one file: _1, _2 ... every `limit` rows."""
    return [f'{stem}_{i + 1}.{ext}' for i in range(len(sheets_or_rows))]


def chunk(rows, limit=SPLIT_ROWS):
    return [rows[i:i + limit] for i in range(0, len(rows), limit)] or [[]]


# ---------------------------------------------------------------- writing
def write_files(ctx: Ctx, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    names = []
    for f in ctx.files:
        path = out_dir / f.name
        if f.name.endswith('.csv'):
            grid = f.sheets[0].grid()
            with open(path, 'w', encoding='utf-8-sig', newline='') as fh:
                w = csv.writer(fh)
                for r in grid:
                    w.writerow(['' if v is None else _csv_text(v) for v in r])
        elif f.name.endswith('.xlsx'):
            write_xlsx(path, [(s.name, s.grid()) for s in f.sheets])
        names.append(f.name)
    return names


def _csv_text(v):
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    if isinstance(v, float) and v.is_integer():
        return str(v)
    if isinstance(v, dt.datetime):
        return v.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(v, dt.date):
        return v.strftime('%d/%m/%Y')
    return str(v)


def add_file(ctx, name, sheets, role='list', master=False):
    ctx.files.append(OutFile(name, sheets if isinstance(sheets, list) else [sheets], role, master))


def doc_for(key, master):
    if master and key in DOC_MASTER:
        return DOC_MASTER[key]
    return DOC.get(key, '')


def readme_columns(ctx):
    """{file: [(header, doc)]} from the first sheet of each file (fillers documented only when notable)."""
    out = {}
    for f in ctx.files:
        if f.name.endswith('.sqlite'):
            continue
        s = f.sheets[0]
        cols = []
        for h, k in zip(s.headers, s.keys):
            d = ctx.doc_override.get((f.name, h)) or (FILLER_DOC.get(h) if k == 'filler' else doc_for(k, f.master))
            if d:
                cols.append((h, d))
        out[f.name] = cols
    return out


# ---------------------------------------------------------------- shared tables (lists)
def units_rows(L, by_name):
    U = L.units.merge(L.products[['product_id', 'name', 'base_unit']], on='product_id', how='left')
    U = U[U['factor'] != 1]
    U = U.rename(columns={'name': 'product_name', 'unit': 'unit_big', 'price': 'unit_big_price'})
    return U.reset_index(drop=True)


def inline_units(ctx):
    U = units_rows(ctx.L, True)
    items = [(n, u, int(f) if float(f).is_integer() else f, b) for n, u, f, b in
             zip(U['product_name'], U['unit_big'], U['factor'], U['base_unit'])]
    ctx.conventions.append(('units_inline', {'items': items}))


def list_sheet(ctx, df, keys, fmt, vendor=None, synonyms=True, shuffle=True, fillers=None, name='Sheet1', above=None):
    headers = choose_headers(keys, ctx.rng, vendor, synonyms)
    rows = table_rows(df, keys, fmt, ctx)
    keys, headers = list(keys), list(headers)
    if fillers:
        keys, headers, rows = add_fillers(keys, headers, rows, fillers, ctx.rng)
    if shuffle:
        keys, headers, rows = shuffle_cols(keys, headers, rows, ctx.rng)
    return Sheet(name, headers, keys, rows, above=above or [])


def product_frame(ctx, with_phone=False):
    P = ctx.L.products.rename(columns={'name': 'product_name'}).copy()
    st = end_stock(ctx.L)
    if st is not None:
        P['stock_end'] = st.values
    return P


def customer_frame(ctx):
    C = ctx.L.customers.rename(columns={'name': 'customer_name', 'group': 'cust_group'}).copy()
    rng, nz = ctx.rng, ctx.nz
    names = []
    for cid, n, p in zip(C['customer_id'], C['customer_name'], C['phone']):
        t = N.with_phone(n, p, rng) if rng.random() < nz.phone_in_master else n
        ctx.alias('customer', cid, t)
        names.append(t)
    C['customer_name'] = names
    return C


def purchase_frames(ctx):
    L = ctx.L
    pu = L.purchases.copy()
    pu['pur_date'] = pd.to_datetime(pu['date'])
    pu['pur_status'] = pu['status'].map({'received': 'Đã nhập hàng', 'cancelled': 'Đã hủy'}).fillna(pu['status'])
    pu['pur_total'] = pu['total']
    pu['pur_note'] = pu['note']
    sup = L.suppliers.set_index('supplier_id')['name'] if len(L.suppliers) else pd.Series(dtype=str)
    pu['supplier_name'] = pu['supplier_id'].map(sup)
    pl = L.purchase_lines.merge(pu[['purchase_id', 'pur_date', 'supplier_id', 'supplier_name', 'pur_note',
                                    'pur_status']], on='purchase_id', how='left')
    pl = pl.merge(L.products[['product_id', 'name']].rename(columns={'name': 'product_name'}), on='product_id',
                  how='left')
    pl['pur_unit'], pl['pur_qty'], pl['pur_unit_cost'] = pl['unit'], pl['qty'], pl['unit_cost']
    pl['pur_line_total'] = pl['qty'] * pl['unit_cost']
    return pu, pl


def return_lines(ctx, ln):
    """Negative lines for returned items (family C): returned base qty per line from line_lots when known, else the
    lines whose amounts make up the refund (first line when nothing fits). Dated at the return time."""
    L = ctx.L
    if not len(L.returns):
        return ln.iloc[0:0]
    rt = L.returns.copy()
    rt['time'] = pd.to_datetime(rt['time'])
    per_line = None
    if len(L.line_lots) and 'returned_base_qty' in L.line_lots:
        per_line = L.line_lots.groupby(['order_id', 'line_no'])['returned_base_qty'].sum()
    out = []
    g = ln.groupby('order_id')
    for oid, t, refund in zip(rt['order_id'], rt['time'], rt['refund']):
        if oid not in g.groups:
            continue
        lines = g.get_group(oid)
        picked = []
        if per_line is not None:
            for _, r in lines.iterrows():
                back = per_line.get((oid, r['line_no']), 0)
                if back > 0:
                    f = back / r['base_qty'] if r['base_qty'] else 1
                    picked.append((r, f))
        if not picked:
            acc = 0
            for _, r in lines.iterrows():
                if acc + r['amount'] <= refund + 0.5:
                    picked.append((r, 1.0))
                    acc += r['amount']
            if not picked:
                picked = [(lines.iloc[0], 1.0)]
        for r, f in picked:
            q = r['qty'] * f
            if not float(q).is_integer():
                q, f = r['qty'], 1.0
            x = r.copy()
            x['qty'], x['base_qty'], x['amount'] = -q, -r['base_qty'] * f, -round(r['amount'] * f)
            x['created'], x['date'] = t, t.normalize()
            out.append(x)
    return pd.DataFrame(out) if out else ln.iloc[0:0]


def total_row(headers, keys, label_key, amount_key, label, amount):
    row = [None] * len(headers)
    if label_key in keys and amount_key in keys:
        row[keys.index(label_key)] = label
        row[keys.index(amount_key)] = N.num(amount)
        return row
    return None


def sales_display(ctx, ln, disp, keep_product=True):
    """Lines frame with display columns (status label, customer writing, product writing)."""
    d = ln.copy()
    d['status'] = [disp.status[o] for o in d['order_id']]
    d['customer_name'] = [disp.customer[o] for o in d['order_id']]
    if keep_product:
        d['product_name'] = [disp.product(p, n) for p, n in zip(d['product_id'], d['product_name'])]
    return d


def dedupe_mark(ctx, n):
    ctx.extras['duplicate_rows'] = ctx.extras.get('duplicate_rows', 0) + n


# ---------------------------------------------------------------- family H: sqlite
H_SCHEMA = {
    'chi_nhanh': ('shop', [('IDCuaHang', 'bid'), ('MaChiNhanh', 'branch'), ('TenGoi', 'name')]),
    'nhan_vien': ('staff', [('MaNhanVien', 'staff_id'), ('TenGoi', 'name'), ('ChucVu', 'role')]),
    'khach_hang': ('customers', [('MaKhachHang', 'customer_id'), ('TenGoi', 'name'), ('SoDienThoai', 'phone'),
                                 ('LoaiKhachHang', 'group'), ('DiaChiLienHe', 'address')]),
    'nha_cung_cap': ('suppliers', [('MaNhaCungCap', 'supplier_id'), ('TenGoi', 'name')]),
    'san_pham': ('products', [('MaHangHoa', 'product_id'), ('TenGoi', 'name'), ('DanhMuc', 'group'),
                              ('DonViCoSo', 'base_unit'), ('GiaBanLe', 'price'), ('GiaVonHang', 'cost')]),
    'don_vi_sp': ('units', [('MaHangHoa', 'product_id'), ('DonViTinh', 'unit'), ('HeSoQuyDoi', 'factor'),
                            ('GiaDonVi', 'price')]),
    'phieu_nhap': ('purchases', [('MaPhieuNhap', 'purchase_id'), ('MaNhaCungCap', 'supplier_id'),
                                 ('NgayNhapKho', 'date'), ('TinhTrang', 'status'), ('TongGiaTriNhap', 'total'),
                                 ('DienGiai', 'note')]),
    'chi_tiet_nhap': ('purchase_lines', [('MaPhieuNhap', 'purchase_id'), ('SoThuTu', 'line_no'),
                                         ('MaHangHoa', 'product_id'), ('DonViTinh', 'unit'), ('SL', 'qty'),
                                         ('DonGiaNhap', 'unit_cost'), ('MaLo', 'lot'), ('HanSuDung', 'expiry')]),
    'don_hang': ('orders', [('MaHoaDon', 'order_id'), ('MaKhachHang', 'customer_id'), ('MaNhanVien', 'staff_id'),
                            ('KenhBanHang', 'channel'), ('ThoiGianLap', 'created'), ('NgayLap', 'day'),
                            ('TinhTrang', 'status'), ('TongTienHang', 'subtotal'), ('ChietKhau', 'discount'),
                            ('PhiVanChuyen', 'shipping'), ('ThueGTGT', 'vat'), ('TongThanhToan', 'total'),
                            ('PhuongThucTT', 'payment_method'), ('MaKhuyenMai', 'promo'), ('KhuVuc', 'area')]),
    'chi_tiet_don': ('lines', [('MaHoaDon', 'order_id'), ('SoThuTu', 'line_no'), ('MaHangHoa', 'product_id'),
                               ('DonViTinh', 'unit'), ('SL', 'qty'), ('SLQuyDoi', 'base_qty'),
                               ('GiaDonVi', 'unit_price'), ('ChietKhau', 'line_discount'), ('TriGia', 'amount'),
                               ('GiaVonLucBan', 'unit_cost')]),
    'thanh_toan': ('payments', [('MaPhieuThu', 'payment_id'), ('MaHoaDon', 'order_id'), ('NgayGioThu', 'time'),
                                ('SoTienThu', 'amount'), ('PhuongThuc', 'method')]),
    'tra_hang': ('returns', [('MaPhieuTra', 'return_id'), ('MaHoaDon', 'order_id'), ('NgayGioTra', 'time'),
                             ('NguyenNhan', 'reason'), ('TienHoanTra', 'refund')]),
    'the_kho': ('stock_moves', [('MaGiaoDichKho', 'seq'), ('MaHangHoa', 'product_id'), ('NgayGioPhatSinh', 'time'),
                                ('LoaiGiaoDich', 'kind'), ('SLQuyDoi', 'base_qty'), ('KieuChungTu', 'doc_kind'),
                                ('MaChungTu', 'doc_id'), ('TonCuoi', 'balance')]),
    'lich_su_gia': ('prices', [('MaHangHoa', 'product_id'), ('NgayApDung', 'date'), ('GiaBanLe', 'price')]),
    'lo_hang': ('lots', [('MaHangHoa', 'product_id'), ('MaLo', 'lot'), ('MaPhieuNhap', 'purchase_id'),
                         ('HanSuDung', 'expiry'), ('SLNhapQuyDoi', 'base_qty'), ('DonGiaNhap', 'base_cost')]),
    'chi_tiet_don_lo': ('line_lots', [('MaHoaDon', 'order_id'), ('SoThuTu', 'line_no'), ('MaLo', 'lot'),
                                      ('SLQuyDoi', 'base_qty'), ('SLTraQuyDoi', 'returned_base_qty')]),
    'thong_tin_thuoc': ('drugs', [('MaHangHoa', 'product_id'), ('ThanhPhanChinh', 'ingredient'),
                                  ('BanTheoDon', 'rx')]),
    'chi_phi': ('expenses', [('NgayChi', 'date'), ('KhoanChi', 'category'), ('SoTien', 'amount'),
                             ('GhiChu', 'note')]),
    'giao_hang': ('deliveries', [('MaHoaDon', 'order_id'), ('LanGiao', 'trip_no'), ('NgayGiao', 'date'),
                                 ('BienSoXe', 'plate'), ('TaiXe', 'driver')]),
}
H_STATUS = {'completed': 'completed', 'cancelled': 'cancelled', 'returned': 'returned', 'delivering': 'shipping'}


def _snake(name):
    import re
    s = re.sub(r'(?<=[a-z])(?=[A-Z])', '_', name).lower()
    return s


def _sql_value(v):
    if _isna(v):
        return None
    if isinstance(v, (pd.Timestamp, dt.datetime)):
        t = pd.Timestamp(v)
        return t.strftime('%Y-%m-%d') if t == t.normalize() else t.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(v, dt.date):
        return v.isoformat()
    if isinstance(v, (bool, np.bool_)):
        return int(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return int(v) if float(v).is_integer() else float(v)
    return v


def render_H(ctx: Ctx, out_dir: Path):
    L, rng, nz = ctx.L, ctx.rng, ctx.nz
    snake = rng.random() < 0.4
    con = sqlite3.connect(out_dir / 'pos.sqlite')
    tables = []
    for tname, (src, cols) in H_SCHEMA.items():
        if src == 'shop':
            df = pd.DataFrame([{'bid': L.shop['business_id'], 'branch': 'CN01', 'name': L.shop.get('name')}])
        else:
            df = getattr(L, src).copy()
        if not len(df):
            continue
        if src == 'orders':
            df['status'] = df['status'].map(H_STATUS).fillna(df['status'])
            df['day'] = pd.to_datetime(df['created']).dt.normalize()
        if src == 'stock_moves':
            if 'seq' not in df:
                df['seq'] = [f'MV{i + 1:07d}' for i in range(len(df))]
            df['doc_kind'] = df['kind'].map({'out_sale': 'HD', 'in_purchase': 'PN', 'in_return': 'TH'}).fillna('KHAC')
        present = [(c, k) for c, k in cols if k in df.columns]
        out = pd.DataFrame({(_snake(c) if snake else c): df[k].map(_sql_value) for c, k in present})
        if src != 'shop':
            out.insert(0, 'id_cua_hang' if snake else 'IDCuaHang', L.shop['business_id'])
        if src == 'lines' and nz.dup_rate:
            rows, n = N.duplicate_rows(out.values.tolist(), nz.dup_rate, rng)
            dedupe_mark(ctx, n)
            out = pd.DataFrame(rows, columns=out.columns)
        out.to_sql(tname, con, index=False)
        tables.append((tname, src, dict(present)))
    con.close()
    add_file(ctx, 'pos.sqlite', [], role='sales')
    ctx.extras['sqlite_tables'] = [t for t, _, _ in tables]
    ctx.caps = set(L.shop['caps']) | {'stock_history', 'payments'} if len(L.stock_moves) else set(L.shop['caps'])
    if len(L.payments):
        ctx.caps.add('payments')
    ctx.intro.append('File máy POS xuất ra.')
    c = (lambda n: _snake(n)) if snake else (lambda n: n)
    ctx.conventions.append(('sqlite_tables', {'tables': [t for t, _, _ in tables],
                                              'join': f'Mã đơn nối `don_hang` với `chi_tiet_don`. Ngày giờ dạng text.'}))
    ctx.conventions.append(('raw', {'text': f'**Dòng hàng**: `chi_tiet_don.{c("TriGia")}` là thành tiền của dòng (đã trừ '
                                            f'giảm giá dòng); `chi_tiet_don.{c("SLQuyDoi")}` là số lượng đã đổi ra đơn vị cơ bản.'}))
    if len(L.payments):
        ctx.conventions.append(('debt_payments', {'pay': f'thanh_toan.{c("SoTienThu")}', 'total': f'don_hang.{c("TongThanhToan")}', 'code': True}))
    if L.has('unit_cost'):
        ctx.conventions.append(('unit_cost', {'col': f'chi_tiet_don.{c("GiaVonLucBan")}', 'code': True}))
    if len(L.stock_moves):
        ctx.conventions.append(('stock_moves', {'col': f'the_kho.{c("TonCuoi")}'}))
    if len(L.lots):
        ctx.conventions.append(('lots', {}))
    if len(L.purchases):
        ctx.conventions.append(('purchase_total', {'cost': f'chi_tiet_nhap.{c("DonGiaNhap")}',
                                                   'total': f'phieu_nhap.{c("TongGiaTriNhap")}', 'code': True}))
    if len(L.prices):
        ctx.conventions.append(('prices_h', {'price': f'lich_su_gia.{c("GiaBanLe")}', 'date': f'lich_su_gia.{c("NgayApDung")}'}))
    if len(L.drugs):
        ctx.conventions.append(('drugs', {'col': f'thong_tin_thuoc.{c("BanTheoDon")}', 'code': True}))
    if len(L.expenses):
        ctx.conventions.append(('expenses', {'col': f'chi_phi.{c("SoTien")}', 'code': True}))
    _fee_convention(ctx)
    ctx.conventions.append(('units_table', {'file': 'don_vi_sp', 'table': True}))


def _fee_convention(ctx):
    P = ctx.L.products
    if 'kind' in P and (P['kind'] == 'fee').any():
        ctx.conventions.append(('service_fee', {'name': P.loc[P['kind'] == 'fee', 'name'].iloc[0]}))


# ---------------------------------------------------------------- family G: normalized CSV, English enums
def render_G(ctx: Ctx, out_dir: Path):
    L, rng, nz = ctx.L, ctx.rng, ctx.nz
    o, ln = views(L)
    fmt = Fmt(money={'int': 0.85, 'dot_d': 0.15} if rng.random() < 0.3 else {'int': 1.0}, date='dmy', xlsx=False,
              qty_rate=nz.qty_unit_rate, datetime='iso_dt')
    fmt.date = N._pick(rng, ['dmy', 'iso', 'dmy'])
    od = o.copy()
    od['status'] = od['status'].map({k: v[0] for k, v in N.STATUS_EN.items()})
    ctx.extras['status_map'] = {v[0]: k for k, v in N.STATUS_EN.items()}
    od['payment_method'] = od['payment_method'].map(N.PAY_EN)
    keys = ['order_id', 'date', 'customer_id', 'status', 'total', 'paid', 'debt_left', 'payment_method']
    has_channel = rng.random() < 0.6 and L.has('channel')
    if has_channel:
        keys.append('channel')
    s = list_sheet(ctx, od, keys, fmt, fillers=['Diễn giải'] if rng.random() < 0.3 else None)
    add_file(ctx, 'don_hang.csv', s, role='sales')
    lk = ['order_id', 'line_no', 'product_id', 'unit', 'qty', 'base_qty', 'unit_price', 'amount']
    if rng.random() < 0.4:
        lk.append('line_discount')
    s = list_sheet(ctx, ln, lk, fmt)
    s.rows, n = N.duplicate_rows(s.rows, nz.dup_rate, rng)
    dedupe_mark(ctx, n)
    add_file(ctx, 'chi_tiet_don.csv', s, role='sales')
    P = product_frame(ctx)
    s = list_sheet(ctx, P, ['product_id', 'product_name', 'group', 'base_unit', 'price'], fmt, fillers=FILLER_PRODUCT)
    add_file(ctx, 'san_pham.csv', s, master=True)
    has_cgroup = False
    if len(L.customers):
        ck = ['customer_id', 'customer_name', 'phone', 'address']
        has_cgroup = rng.random() < 0.7 and L.has('customer_groups')
        if has_cgroup:
            ck.append('cust_group')
        s = list_sheet(ctx, customer_frame(ctx), ck, fmt, fillers=FILLER_CUSTOMER)
        add_file(ctx, 'khach_hang.csv', s, master=True)
    if len(L.payments):
        pay = L.payments.rename(columns={'time': 'pay_time', 'amount': 'pay_amount', 'method': 'pay_method'})
        pay['pay_method'] = pay['pay_method'].map(N.PAY_EN).fillna(pay['pay_method'])
        s = list_sheet(ctx, pay, ['payment_id', 'order_id', 'pay_time', 'pay_amount', 'pay_method'], fmt)
        add_file(ctx, 'thanh_toan.csv', s)
        ctx.keep('debt')
        ctx.caps.add('payments')
    ctx.keep('customers', 'customer_ids', 'payment_method', 'debt', 'units', 'groups', 'order_ids', 'product_ids')
    if has_cgroup:
        ctx.keep('customer_groups')
    if has_channel:
        ctx.keep('channel')
    ctx.intro.append('Dữ liệu bán hàng của tiệm, gồm vài file nối với nhau qua mã.')
    hdr = {f.name: dict(zip(f.sheets[0].keys, f.sheets[0].headers)) for f in ctx.files}
    pm = hdr['don_hang.csv']['payment_method']
    ctx.doc_override[('don_hang.csv', pm)] = ('hình thức thanh toán của đơn: cash tiền mặt, transfer chuyển khoản, '
                                              'ewallet ví điện tử, cod giao hàng thu tiền, debt ghi nợ')
    ctx.doc_override[('don_hang.csv', hdr['don_hang.csv']['status'])] = (
        'trạng thái đơn: completed hoàn thành, cancelled huỷ, returned trả hàng, shipping đang giao')
    if len(L.payments):
        ctx.conventions.append(('debt_payments', {'pay': hdr['thanh_toan.csv']['pay_amount'],
                                                  'total': hdr['don_hang.csv']['total']}))
    _fee_convention(ctx)
    inline_units(ctx)


# ---------------------------------------------------------------- family E: KiotViet list exports
E_VENDOR = {
    'orders': {'order_id': 'Mã hóa đơn', 'date': 'Thời gian', 'customer_id': 'Mã KH', 'customer_name': 'Khách hàng',
               'subtotal': 'Tổng tiền hàng', 'order_discount': 'Giảm giá', 'total': 'Tổng sau giảm giá',
               'paid': 'Khách đã trả', 'payment_method': 'Phương thức thanh toán', 'status': 'Trạng thái',
               'created': 'Thời gian tạo', 'debt_left': 'Còn nợ', 'channel': 'Kênh bán', 'staff_id': 'Người bán'},
    'lines': {'order_id': 'Mã hóa đơn', 'line_no': 'STT', 'product_id': 'Mã hàng', 'product_name': 'Tên hàng',
              'unit': 'Đơn vị tính', 'qty': 'Số lượng', 'unit_price': 'Đơn giá', 'line_discount': 'Giảm giá',
              'amount': 'Thành tiền', 'base_qty': 'Số lượng quy đổi', 'unit_cost': 'Giá vốn'},
    'products': {'product_id': 'Mã hàng', 'product_name': 'Tên hàng', 'group': 'Nhóm hàng(3 Cấp)', 'price': 'Giá bán',
                 'base_unit': 'ĐVT', 'cost': 'Giá vốn'},
    'customers': {'customer_id': 'Mã khách hàng', 'customer_name': 'Tên khách hàng', 'phone': 'Điện thoại',
                  'cust_group': 'Nhóm khách hàng', 'address': 'Địa chỉ'},
    'stock': {'product_id': 'Mã hàng', 'product_name': 'Tên hàng', 'base_unit': 'ĐVT', 'stock_end': 'Tồn cuối kỳ'},
    'purchases': {'purchase_id': 'Mã nhập hàng', 'pur_date': 'Thời gian', 'supplier_id': 'Mã NCC',
                  'pur_total': 'Cần trả NCC', 'pur_status': 'Trạng thái', 'pur_note': 'Ghi chú'},
    'purchase_lines': {'purchase_id': 'Mã nhập hàng', 'line_no': 'STT', 'product_id': 'Mã hàng', 'pur_unit': 'ĐVT',
                       'pur_qty': 'Số lượng', 'pur_unit_cost': 'Đơn giá', 'lot': 'Lô', 'expiry': 'Hạn sử dụng'},
    'payments': {'payment_id': 'Mã phiếu', 'pay_time': 'Thời gian', 'order_id': 'Mã hóa đơn',
                 'pay_method': 'Phương thức thanh toán', 'pay_amount': 'Giá trị'},
    'units': {'product_id': 'Mã hàng', 'unit_big': 'ĐVT', 'factor': 'Quy đổi', 'unit_big_price': 'Giá bán'},
    'lots': {'purchase_id': 'Mã nhập hàng', 'product_id': 'Mã hàng', 'lot': 'Lô', 'expiry': 'Hạn sử dụng',
             'lot_base_qty': 'Số lượng (ĐVT cơ bản)'},
    'line_lots': {'order_id': 'Mã hóa đơn', 'line_no': 'STT', 'lot': 'Lô', 'll_base_qty': 'Số lượng (ĐVT cơ bản)',
                  'll_returned': 'Số lượng trả (ĐVT cơ bản)'},
    'drugs': {'product_id': 'Mã hàng', 'ingredient': 'Hoạt chất', 'rx': 'Thuốc kê đơn'},
    'area': {'order_id': 'Mã hóa đơn', 'area': 'Khu vực'},
    'expenses': {'exp_date': 'Ngày chi', 'exp_category': 'Khoản chi', 'exp_amount': 'Số tiền', 'exp_note': 'Ghi chú'},
}


def _vendor_sheet(ctx, df, keys, fmt, vendor, fillers=None, name='Sheet1', above=None, syn_p=0.25, shuffle_p=0.7):
    syn = ctx.rng.random() < syn_p
    return list_sheet(ctx, df, keys, fmt, vendor=vendor, synonyms=syn, shuffle=ctx.rng.random() < shuffle_p,
                      fillers=fillers, name=name, above=above)


def render_E(ctx: Ctx, out_dir: Path):
    L, rng, nz = ctx.L, ctx.rng, ctx.nz
    o, ln = views(L)
    disp = Display(ctx, o, codes_for_customers=True)
    lab_pay = {k: N._pick(rng, v) for k, v in nz.pay_labels.items()}
    fmt = Fmt(money={'comma': 0.85, 'int': 0.15}, date='dmy', datetime='cell')
    od = o.copy()
    od['status'] = [disp.status[x] for x in od['order_id']]
    od['customer_name'] = [disp.customer[x] for x in od['order_id']]
    od['payment_method'] = od['payment_method'].map(lab_pay).fillna(od['payment_method'])
    od['order_discount'] = od['discount']
    keys = ['order_id', 'date', 'customer_id', 'customer_name', 'subtotal', 'order_discount', 'total', 'paid',
            'status']
    opt = {'created': 0.85, 'debt_left': 0.8 if L.has('debt') else 0, 'payment_method': 0.6, 'channel': 0.4,
           'staff_id': 0.3}
    on = [k for k, p in opt.items() if rng.random() < p and (k not in ('channel', 'staff_id') or L.has(
        'channel' if k == 'channel' else 'staff'))]
    keys += on
    workbook = rng.random() < 0.2
    title = rng.random() < 0.3
    lists = []                                                   # (list name, Sheet)
    # invoices: one file, maybe one sheet per month
    if not workbook and rng.random() < 0.35:
        parts, _ = month_sheets(od, rng)
        headers_s = _vendor_sheet(ctx, od.head(0), keys, fmt, E_VENDOR['orders'], fillers=FILLER_ORDER[:2])
        sheets = []
        for name, g in parts:
            rows = table_rows(g, [k for k in headers_s.keys if k != 'filler'], fmt, ctx)
            sheets.append(Sheet(name, headers_s.headers, headers_s.keys, _realign(rows, headers_s)))
        add_file(ctx, 'DanhSachHoaDon.xlsx', sheets, role='sales')
        ctx.intro_month = 'DanhSachHoaDon.xlsx'
    else:
        s = _vendor_sheet(ctx, od, keys, fmt, E_VENDOR['orders'], fillers=FILLER_ORDER[:2] if rng.random() < 0.5 else None,
                          above=[['DANH SÁCH HÓA ĐƠN'], []] if title else None)
        lists.append(('DanhSachHoaDon', s))
    # invoice lines (never inside the workbook: too long)
    lk = ['order_id', 'product_id', 'product_name', 'qty', 'unit_price', 'line_discount', 'amount', 'base_qty']
    if rng.random() < 0.7:
        lk.insert(1, 'line_no')
    if rng.random() < 0.6:
        lk.append('unit')
    with_cost = L.has('unit_cost') and rng.random() < 0.6
    if with_cost:
        lk.append('unit_cost')
    ld = sales_display(ctx, ln, disp)
    s = _vendor_sheet(ctx, ld, lk, fmt, E_VENDOR['lines'])
    s.rows, n = N.duplicate_rows(s.rows, nz.dup_rate, rng)
    dedupe_mark(ctx, n)
    if title:
        s.above = [['DANH SÁCH CHI TIẾT HÓA ĐƠN'], []]
    _add_split(ctx, 'DanhSachHoaDonChiTiet', s, role='sales')
    P = product_frame(ctx)
    pk = ['product_id', 'product_name', 'group', 'price', 'base_unit']
    if 'cost' in P and P['cost'].notna().all() and rng.random() < 0.5:
        pk.append('cost')
    lists.append(('DanhSachSanPham', _vendor_sheet(ctx, P, pk, fmt, E_VENDOR['products'], fillers=FILLER_PRODUCT)))
    has_cgroup = False
    if len(L.customers):
        ck = ['customer_id', 'customer_name', 'phone']
        has_cgroup = L.has('customer_groups') and rng.random() < 0.75
        ck += ['cust_group'] if has_cgroup else []
        ck += ['address'] if rng.random() < 0.6 else []
        lists.append(('DanhSachKhachHang', _vendor_sheet(ctx, customer_frame(ctx), ck, fmt, E_VENDOR['customers'],
                                                         fillers=FILLER_CUSTOMER)))
    if 'stock_end' in P and L.has('stock'):
        lists.append(('BaoCaoTonKho', _vendor_sheet(ctx, P[P['stock_end'].notna()], ['product_id', 'product_name', 'base_unit', 'stock_end'],
                                                    Fmt(), E_VENDOR['stock'], shuffle_p=0.2)))
        ctx.keep('stock')
    if len(L.purchases) and L.has('purchases'):
        pu, pl = purchase_frames(ctx)
        lists.append(('DanhSachNhapHang', _vendor_sheet(ctx, pu, ['purchase_id', 'pur_date', 'supplier_id', 'pur_total',
                                                                  'pur_status', 'pur_note'],
                                                        Fmt(money={'comma': 0.2, 'int': 0.8}), E_VENDOR['purchases'],
                                                        shuffle_p=0.2)))
        plk = ['purchase_id', 'line_no', 'product_id', 'pur_unit', 'pur_qty', 'pur_unit_cost']
        if len(L.lots):
            plk += ['lot', 'expiry']
        lists.append(('DanhSachChiTietNhapHang', _vendor_sheet(ctx, pl, plk, Fmt(money={'comma': 0.7, 'int': 0.3},
                                                                                 date='date'),
                                                               E_VENDOR['purchase_lines'], shuffle_p=0.2)))
        ctx.keep('purchases')
    if len(L.payments) and L.has('debt') and rng.random() < 0.5:
        pay = L.payments.rename(columns={'time': 'pay_time', 'amount': 'pay_amount', 'method': 'pay_method'})
        pay['pay_method'] = pay['pay_method'].map(lab_pay).fillna(pay['pay_method'])
        lists.append(('SoQuy', _vendor_sheet(ctx, pay, ['payment_id', 'pay_time', 'order_id', 'pay_method',
                                                        'pay_amount'], Fmt(money={'dot_d': 1.0}),
                                             E_VENDOR['payments'], shuffle_p=0.3)))
        ctx.caps.add('payments')
    U = units_rows(L, False)
    if len(U):
        lists.append(('DanhSachDonViTinh', _vendor_sheet(ctx, U, ['product_id', 'unit_big', 'factor', 'unit_big_price'],
                                                         Fmt(), E_VENDOR['units'], shuffle_p=0.2)))
    if len(L.lots) and L.has('lots'):
        lots = L.lots.rename(columns={'base_qty': 'lot_base_qty'})
        lists.append(('DanhSachLoHang', _vendor_sheet(ctx, lots, ['purchase_id', 'product_id', 'lot', 'expiry',
                                                                  'lot_base_qty'], Fmt(), E_VENDOR['lots'],
                                                      shuffle_p=0.2)))
        ll = L.line_lots.rename(columns={'base_qty': 'll_base_qty', 'returned_base_qty': 'll_returned'})
        s = _vendor_sheet(ctx, ll, ['order_id', 'line_no', 'lot', 'll_base_qty', 'll_returned'], Fmt(),
                          E_VENDOR['line_lots'], shuffle_p=0.2)
        _add_split(ctx, 'DanhSachHoaDonChiTietLo', s)
        ctx.keep('lots')
    if len(L.drugs) and L.has('drugs'):
        lists.append(('DanhSachThuoc', _vendor_sheet(ctx, L.drugs, ['product_id', 'ingredient', 'rx'], Fmt(),
                                                     E_VENDOR['drugs'], shuffle_p=0.0)))
        ctx.keep('drugs')
    if 'area' in L.orders and L.orders['area'].notna().any():
        a = L.orders[L.orders['area'].notna()]
        lists.append(('DanhSachHoaDonKhuVuc', _vendor_sheet(ctx, a, ['order_id', 'area'], Fmt(), E_VENDOR['area'],
                                                            shuffle_p=0.0)))
    if len(L.expenses) and L.has('expenses') and rng.random() < 0.6:
        ex = L.expenses.rename(columns={'date': 'exp_date', 'category': 'exp_category', 'amount': 'exp_amount',
                                        'note': 'exp_note'})
        lists.append(('SoChiPhi', _vendor_sheet(ctx, ex, ['exp_date', 'exp_category', 'exp_amount', 'exp_note'],
                                                Fmt(money={'comma': 0.5, 'k': 0.5}), E_VENDOR['expenses'])))
        ctx.keep('expenses')
    book = 'DuLieuBanHang.xlsx'
    if workbook:
        sheets = []
        for name, s in lists:
            s.name = name
            sheets.append(s)
        add_file(ctx, book, sheets, role='sales')
    else:
        for name, s in lists:
            add_file(ctx, f'{name}.xlsx', s, role='sales' if name == 'DanhSachHoaDon' else 'list',
                     master=name in ('DanhSachSanPham', 'DanhSachKhachHang'))
    # caps and README
    ctx.keep('customers', 'customer_ids', 'units', 'groups', 'order_ids', 'product_ids')
    if 'created' in on:
        ctx.keep('time')
    if 'debt_left' in on or 'payments' in ctx.caps:
        ctx.keep('debt')
    for k, cap in (('payment_method', 'payment_method'), ('channel', 'channel'), ('staff_id', 'staff')):
        if k in on:
            ctx.keep(cap)
    if has_cgroup:
        ctx.keep('customer_groups')
    if with_cost:
        ctx.keep('unit_cost')
    if workbook:
        names = ', '.join(f'`{n}`' for n, _ in lists)
        ctx.intro += ['File máy POS xuất ra.', f'Các danh sách {names} nằm chung file `{book}`, mỗi danh sách một sheet.']
    else:
        ctx.intro.append(N._pick(rng, ['File máy POS xuất ra.',
                                       'File Excel xuất từ phần mềm bán hàng, mỗi danh sách một file (danh sách dài '
                                       'tách thành nhiều file, tên thêm đuôi _1, _2…), nối với nhau qua mã. '
                                       'Ngày dạng dd/mm/yyyy.']))
    if getattr(ctx, 'intro_month', None):
        ctx.intro.append(f'File `{ctx.intro_month}` chia mỗi tháng một sheet, tên sheet ghi tháng và năm.')
    H = _headers_by_list(ctx, lists)
    if 'payments' in ctx.caps:
        ctx.conventions.append(('debt_payments', {'pay': H['SoQuy']['pay_amount'],
                                                  'total': H['DanhSachHoaDon']['total']}))
    elif 'debt_left' in on:
        ctx.conventions.append(('debt_left', {'col': H['DanhSachHoaDon']['debt_left']}))
    if with_cost:
        ctx.conventions.append(('unit_cost', {'col': H['DanhSachHoaDonChiTiet']['unit_cost']}))
    if 'BaoCaoTonKho' in H:
        ctx.conventions.append(('stock_end', {'col': H['BaoCaoTonKho']['stock_end']}))
    if 'DanhSachLoHang' in H:
        ctx.conventions.append(('lots', {}))
    if 'DanhSachNhapHang' in H:
        ctx.conventions.append(('purchase_total', {'cost': H['DanhSachChiTietNhapHang']['pur_unit_cost'],
                                                   'total': H['DanhSachNhapHang']['pur_total']}))
    if 'DanhSachThuoc' in H:
        ctx.conventions.append(('drugs', {'col': H['DanhSachThuoc']['rx']}))
    if 'SoChiPhi' in H:
        ctx.conventions.append(('expenses', {'col': H['SoChiPhi']['exp_amount']}))
    _fee_convention(ctx)
    if len(U):
        ctx.conventions.append(('units_table', {'file': book if workbook else 'DanhSachDonViTinh.xlsx'}))
    else:
        inline_units(ctx)


def _realign(rows, sheet):
    """Rows built on the non-filler keys, re-expanded to the sheet's columns (fillers blank)."""
    pos = [i for i, k in enumerate(sheet.keys) if k != 'filler']
    out = []
    for r in rows:
        full = [None] * len(sheet.keys)
        for i, v in zip(pos, r):
            full[i] = v
        out.append(full)
    return out


def _headers_by_list(ctx, lists):
    H = {name: dict(zip(s.keys, s.headers)) for name, s in lists}
    for f in ctx.files:
        stem = f.name.rsplit('.', 1)[0].split('_')[0] if f.name.endswith('.xlsx') else f.name
        if f.sheets:
            H.setdefault(stem, dict(zip(f.sheets[0].keys, f.sheets[0].headers)))
    return H


def _add_split(ctx, stem, sheet: Sheet, role='list', ext='xlsx'):
    parts = chunk(sheet.rows)
    if len(parts) == 1:
        add_file(ctx, f'{stem}.{ext}', sheet, role)
        return
    for i, rows in enumerate(parts):
        add_file(ctx, f'{stem}_{i + 1}.{ext}', Sheet(sheet.name, sheet.headers, sheet.keys, rows, list(sheet.above)),
                 role)


# ---------------------------------------------------------------- monthly sheets helper for line books
def monthly_book(ctx, stem, frame, keys, headers, fmt, total=None, above=None, group=None, below=None,
                 year_split=False, pattern=None, ext='xlsx', role='sales', dup=True, post=None):
    """One sheet per month (maybe two files: _1 and _<last year>); rows formatted per sheet; optional total row per
    sheet ('Tổng tháng m/yyyy' under the label key, amount under the amount key)."""
    parts, pattern = month_sheets(frame, ctx.rng, pattern)
    sheets = []
    for name, g in parts:
        rows = table_rows(g, keys, fmt, ctx)
        if dup:
            rows, n = N.duplicate_rows(rows, ctx.nz.dup_rate, ctx.rng)
            dedupe_mark(ctx, n)
        if post:
            rows = post(rows, keys)
        sh = Sheet(name, headers, keys, rows, above=list(above or []), group=group, below=list(below or []))
        if total:
            d = pd.to_datetime(g['date']).iloc[0]
            tr = total_row(headers, keys, total[0], total[1], f'Tổng tháng {d.month}/{d.year}', g['amount'].sum())
            if tr:
                sh.below.insert(0, tr)
        sheets.append(sh)
    if year_split and len(sheets) > 12:
        last_year = parts[-1][1]['date'].iloc[0].year
        cut = next((i for i, (_, g) in enumerate(parts) if g['date'].iloc[0].year == last_year and i >= 6), 12)
        add_file(ctx, f'{stem}_1.{ext}', sheets[:cut], role)
        add_file(ctx, f'{stem}_{last_year}.{ext}', sheets[cut:], role)
        return [f'{stem}_1.{ext}', f'{stem}_{last_year}.{ext}']
    if sum(len(s.rows) for s in sheets) > SPLIT_ROWS:
        files, cur, n = [], [], 0
        for s in sheets:
            if cur and n + len(s.rows) > SPLIT_ROWS:
                files.append(cur)
                cur, n = [], 0
            cur.append(s)
            n += len(s.rows)
        files.append(cur)
        names = [f'{stem}_{i + 1}.{ext}' for i in range(len(files))]
        for nm, ss in zip(names, files):
            add_file(ctx, nm, ss, role)
        return names
    add_file(ctx, f'{stem}.{ext}', sheets, role)
    return [f'{stem}.{ext}']


def single_book(ctx, stem, frame, keys, headers, fmt, total=None, above=None, ext='xlsx', role='sales', dup=True,
                post=None, below=None):
    rows = table_rows(frame, keys, fmt, ctx)
    if dup:
        rows, n = N.duplicate_rows(rows, ctx.nz.dup_rate, ctx.rng)
        dedupe_mark(ctx, n)
    if post:
        rows = post(rows, keys)
    parts = chunk(rows)
    names = [f'{stem}.{ext}'] if len(parts) == 1 else [f'{stem}_{i + 1}.{ext}' for i in range(len(parts))]
    for i, (nm, rs) in enumerate(zip(names, parts)):
        sh = Sheet('Sheet1', headers, keys, rs, above=list(above or []), below=list(below or []) if i == len(parts) - 1 else [])
        if total and i == len(parts) - 1:
            d = pd.to_datetime(frame['date']).iloc[-1]
            tr = total_row(headers, keys, total[0], total[1], f'Tổng tháng {d.month}/{d.year}',
                           frame.loc[pd.to_datetime(frame['date']).dt.to_period('M') == d.to_period('M'), 'amount'].sum())
            if tr:
                sh.below.insert(0, tr)
        add_file(ctx, nm, sh, role)
    return names


def month_intro(ctx, names):
    if names:
        ctx.intro.append(f'File {", ".join(f"`{n}`" for n in names)} chia mỗi tháng một sheet, tên sheet ghi tháng và năm.')


# ---------------------------------------------------------------- family F: MISA sổ chi tiết bán hàng
F_LINES = ['date', 'order_id', 'product_name', 'unit', 'qty', 'unit_price', 'amount', 'status', 'base_qty']
F_VENDOR = {'date': 'Ngày', 'order_id': 'Mã đơn hàng', 'product_name': 'Tên hàng hóa', 'unit': 'Đơn vị tính',
            'qty': 'Số lượng', 'unit_price': 'Đơn giá', 'amount': 'Thành tiền', 'status': 'Trạng thái',
            'base_qty': 'Số lượng quy đổi', 'customer_name': 'Khách hàng'}
F_PRODUCTS = {'product_id': 'Mã hàng hóa', 'product_name': 'Tên hàng hóa', 'group': 'Nhóm hàng hóa',
              'base_unit': 'Đơn vị tính', 'price': 'Giá bán', 'cost': 'Giá vốn'}
F_DELIV = {'del_date': 'Ngày giao hàng', 'order_id': 'Mã đơn hàng', 'trip_no': 'Lần giao',
           'product_name': 'Tên hàng hóa', 'base_unit': 'Đơn vị tính', 'del_qty': 'Số lượng giao',
           'plate': 'Biển số xe', 'driver': 'Người giao hàng'}
F_DUE = {'order_id': 'Mã đơn hàng', 'due_days': 'Số ngày được nợ', 'due_date': 'Hạn thanh toán'}


def delivery_frame(ctx, ln):
    """Delivery rows per line and trip: with k trips, line i goes with trip (i mod k)+1 (the ledger only says which
    trips an order had); quantities in base units."""
    D = ctx.L.deliveries
    if not len(D):
        return None
    trips = D.groupby('order_id')
    rows = []
    for oid, lines in ln[ln['order_id'].isin(D['order_id'])].groupby('order_id', sort=False):
        t = trips.get_group(oid).sort_values('trip_no')
        k = len(t)
        for i, (_, r) in enumerate(lines.iterrows()):
            tr = t.iloc[i % k]
            rows.append({'del_date': tr['date'], 'order_id': oid, 'trip_no': tr['trip_no'],
                         'product_name': r['product_name'], 'base_unit': r['base_unit'], 'del_qty': r['base_qty'],
                         'plate': tr['plate'], 'driver': tr['driver'], 'date': tr['date']})
        for _, tr in t.iloc[len(lines):].iterrows():                 # more trips than lines: repeat the last line
            r = lines.iloc[-1]
            rows.append({'del_date': tr['date'], 'order_id': oid, 'trip_no': tr['trip_no'],
                         'product_name': r['product_name'], 'base_unit': r['base_unit'], 'del_qty': 0,
                         'plate': tr['plate'], 'driver': tr['driver'], 'date': tr['date']})
    df = pd.DataFrame(rows)
    df['del_date'] = pd.to_datetime(df['del_date'])
    return df.sort_values(['del_date', 'order_id', 'trip_no'], kind='mergesort')


def due_frame(ctx, o):
    """Credit terms of debt orders (not in the ledger): 30 or 60 days from the order date; kept in extras."""
    d = o[(o['payment_method'] == 'debt') & (o['status'] != 'cancelled')].copy()
    if not len(d):
        return None
    d['due_days'] = ctx.rng.choice([30, 60], size=len(d), p=[0.75, 0.25])
    d['due_date'] = d['date'] + pd.to_timedelta(d['due_days'], unit='D')
    ctx.extras['due_terms'] = dict(zip(d['order_id'], d['due_days'].astype(int)))
    return d


def render_F(ctx: Ctx, out_dir: Path):
    L, rng, nz = ctx.L, ctx.rng, ctx.nz
    o, ln = views(L)
    disp = Display(ctx, o, codes_for_customers=False)
    fmt = Fmt(money={'comma4': 1.0}, date='dmy', qty_rate=nz.qty_unit_rate)
    keys = list(F_LINES)
    with_cust = len(L.customers) > 0 and rng.random() < 0.6
    if with_cust:
        keys.append('customer_name')
    syn = rng.random() < 0.3
    headers = choose_headers(keys, rng, F_VENDOR, syn)
    if rng.random() < 0.3:
        keys, headers = arrange(keys, headers, rng, True)
    ld = sales_display(ctx, ln, disp)
    workbook = rng.random() < 0.2
    title = [['SỔ CHI TIẾT BÁN HÀNG'], ['Kỳ báo cáo: toàn bộ', 'Kênh bán: Tất cả'], []] if rng.random() < 0.6 else None
    total = ('product_name', 'amount') if rng.random() < 0.35 else None
    lists, month_files = [], []
    if workbook:
        rows = table_rows(ld, keys, fmt, ctx)
        rows, n = N.duplicate_rows(rows, nz.dup_rate, rng)
        dedupe_mark(ctx, n)
        lists.append(('So_chi_tiet_ban_hang', Sheet('So_chi_tiet_ban_hang', headers, keys, rows, above=title or [])))
    elif rng.random() < 0.6:
        month_files = monthly_book(ctx, 'So_chi_tiet_ban_hang', ld, keys, headers, fmt, total=total, above=title,
                                   year_split=rng.random() < 0.3)
    else:
        single_book(ctx, 'So_chi_tiet_ban_hang', ld, keys, headers, fmt, total=total, above=title)
    P = product_frame(ctx)
    price_or_cost = 'cost' if 'cost' in P and P['cost'].notna().all() and rng.random() < 0.4 else 'price'
    lists.append(('Danh sách hàng hóa', _vendor_sheet(ctx, P, ['product_id', 'product_name', 'group', 'base_unit',
                                                               price_or_cost], Fmt(money={'comma4': 1.0}), F_PRODUCTS,
                                                      fillers=FILLER_PRODUCT, syn_p=0.2)))
    dv = delivery_frame(ctx, ln) if L.has('deliveries') else None
    if dv is not None:
        lists.append(('Bảng kê phiếu giao hàng', _vendor_sheet(
            ctx, dv, list(F_DELIV), Fmt(), F_DELIV, syn_p=0.2, shuffle_p=0.2,
            above=[['BẢNG KÊ PHIẾU GIAO HÀNG'], ['Kỳ báo cáo: toàn bộ'], []] if title else None)))
        ctx.keep('deliveries')
    du = due_frame(ctx, o) if (L.shop.get('industry') == 'building' or dv is not None) and L.has('debt') else None
    if du is not None:
        lists.append(('Chi tiết công nợ theo hạn', _vendor_sheet(
            ctx, du, list(F_DUE), Fmt(), F_DUE, syn_p=0.2, shuffle_p=0.0,
            above=[['CHI TIẾT CÔNG NỢ THEO HẠN THANH TOÁN'], []] if title else None)))
    if workbook:
        add_file(ctx, 'Bao_cao_ban_hang.xlsx', [s for _, s in lists], role='sales')
        for name, s in lists:
            s.name = name
    else:
        for name, s in lists:
            add_file(ctx, f'{name}.xlsx', s, master=name == 'Danh sách hàng hóa')
    ctx.keep('order_ids', 'groups', 'units')
    if with_cust:
        ctx.keep('customers')
    ctx.intro.append(N._pick(rng, [
        'File Excel xuất từ phần mềm bán hàng, mỗi báo cáo, danh sách một file. Sổ chi tiết bán hàng: mỗi dòng một dòng '
        'hàng, thông tin đơn lặp lại ở mọi dòng của đơn; sổ không có mã hàng, nối với danh sách hàng hóa qua tên hàng '
        'hóa. Ngày dạng dd/mm/yyyy.',
        'File Excel xuất từ phần mềm bán hàng. Sổ chi tiết bán hàng: mỗi dòng một dòng hàng, thông tin đơn lặp lại ở '
        'mọi dòng.']))
    if workbook:
        ctx.intro.append('Các báo cáo, danh sách nằm chung file `Bao_cao_ban_hang.xlsx`, mỗi báo cáo một sheet.')
    month_intro(ctx, [n for n in month_files])
    H = {name: dict(zip(s.keys, s.headers)) for name, s in lists}
    if du is not None:
        h = H['Chi tiết công nợ theo hạn']
        ctx.conventions.append(('due', {'due': h['due_date'], 'days': h['due_days']}))
    if dv is not None:
        h = H['Bảng kê phiếu giao hàng']
        ctx.conventions.append(('deliveries', {'trip': h['trip_no'], 'qty': h['del_qty']}))
    _fee_convention(ctx)
    inline_units(ctx)


# ---------------------------------------------------------------- family D: Sapo DonHang_ChiTiet (+ fill-down)
D_LINES = ['order_id', 'date', 'status', 'customer_name', 'product_name', 'qty', 'unit_price', 'amount', 'unit']
D_VENDOR = {'order_id': 'Mã đơn hàng', 'date': 'Ngày đặt hàng', 'status': 'Trạng thái đơn hàng',
            'customer_name': 'Tên khách hàng', 'product_name': 'Tên sản phẩm', 'qty': 'Số lượng sản phẩm',
            'unit_price': 'Giá sản phẩm', 'amount': 'Tổng tiền', 'unit': 'Đơn vị tính'}
D_UNITS = {'product_name': 'Tên sản phẩm', 'unit_big': 'Đơn vị quy đổi', 'factor': 'Tỉ lệ quy đổi',
           'base_unit': 'Đơn vị cơ bản'}
D_PH = {'product_id': 'Mã SKU', 'product_name': 'Tên sản phẩm', 'base_unit': 'Đơn vị', 'group': 'Nhóm sản phẩm',
        'ingredient': 'Hoạt chất', 'rx': 'Thuốc kê đơn', 'purchase_id': 'Mã đơn nhập', 'pur_date': 'Ngày nhập',
        'supplier_id': 'Mã nhà cung cấp', 'lot': 'Mã lô', 'expiry': 'Hạn sử dụng', 'lot_base_qty': 'Số lượng nhập',
        'pur_unit_cost': 'Đơn giá nhập', 'order_id': 'Mã đơn hàng', 'll_base_qty': 'Số lượng',
        'll_returned': 'Số lượng trả'}


def fill_down_post(rows, keys):
    """Blank the order cells on the continuation lines of each order (rows must be grouped by order)."""
    pos = [keys.index(k) for k in FILL_KEYS if k in keys]
    oid = keys.index('order_id')
    prev = None
    for r in rows:
        cur = r[oid]
        if cur == prev:
            for p in pos:
                r[p] = None
        prev = cur
    return rows


def render_D(ctx: Ctx, out_dir: Path):
    L, rng, nz = ctx.L, ctx.rng, ctx.nz
    o, ln = views(L)
    disp = Display(ctx, o, codes_for_customers=False)
    fmt = Fmt(money={'comma': 0.5, 'str': 0.3, 'int': 0.1, 'k': 0.05, 'dot_d': 0.05}, date='dmy',
              qty_rate=nz.qty_unit_rate)
    keys = list(D_LINES)
    syn = rng.random() < 0.3
    headers = choose_headers(keys, rng, D_VENDOR, syn)
    ld = sales_display(ctx, ln, disp)
    fill = nz.fill_down
    above = [['Trạng thái đơn hàng', 'Đặt hàng (Đã duyệt)'], []] if fill or rng.random() < 0.2 else None
    total = ('customer_name', 'amount') if rng.random() < 0.35 else None
    post = fill_down_post if fill else None
    workbook = rng.random() < 0.2
    month_files = []
    if rng.random() < 0.6:
        month_files = monthly_book(ctx, 'DonHang_ChiTiet', ld, keys, headers, fmt, total=total, above=above,
                                   year_split=rng.random() < 0.3, post=post)
    else:
        single_book(ctx, 'DonHang_ChiTiet', ld, keys, headers, fmt, total=total, above=above, post=post)
    lists = []
    U = units_rows(L, True)
    lists.append(('DanhSachQuyDoi', list_sheet(ctx, U, list(D_UNITS), Fmt(), vendor=D_UNITS, synonyms=False,
                                               shuffle=False)))
    pharmacy = len(L.drugs) > 0 and L.has('drugs')
    with_cost = False
    if pharmacy:
        P = product_frame(ctx)
        lists.append(('DanhSachSanPham', list_sheet(ctx, P, ['product_id', 'product_name', 'base_unit'], Fmt(),
                                                    vendor=D_PH, synonyms=False, fillers=FILLER_PRODUCT)))
        lists.append(('DanhSachThuoc', list_sheet(ctx, L.drugs, ['product_id', 'ingredient', 'rx'], Fmt(), vendor=D_PH,
                                                  synonyms=False, shuffle=False)))
        ctx.keep('drugs')
        if len(L.lots) and L.has('lots'):
            pu, pl = purchase_frames(ctx)
            lists.append(('DonNhapHang', list_sheet(ctx, pu, ['purchase_id', 'pur_date', 'supplier_id'], Fmt(),
                                                    vendor=D_PH, synonyms=False, shuffle=False)))
            lots = L.lots.rename(columns={'base_qty': 'lot_base_qty', 'base_cost': 'pur_unit_cost'})
            lk = ['purchase_id', 'product_id', 'lot', 'expiry', 'lot_base_qty']
            with_cost = rng.random() < 0.5
            if with_cost:
                lk.append('pur_unit_cost')
                ctx.doc_override[('DonNhapHang_ChiTiet.xlsx', 'Đơn giá nhập')] = 'giá nhập một đơn vị cơ bản của lô'
            lists.append(('DonNhapHang_ChiTiet', list_sheet(ctx, lots, lk, Fmt(), vendor=D_PH, synonyms=False,
                                                            shuffle=False)))
            ll = L.line_lots.rename(columns={'base_qty': 'll_base_qty', 'returned_base_qty': 'll_returned'})
            ll = ll.merge(ln[['order_id', 'line_no', 'created']], on=['order_id', 'line_no'], how='left')
            s = list_sheet(ctx, ll, ['order_id', 'lot', 'll_base_qty', 'll_returned'], Fmt(), vendor=D_PH,
                           synonyms=False, shuffle=False)
            _add_split(ctx, 'DonHang_Lo', s)
            ctx.keep('lots')
            if with_cost:
                ctx.keep('purchases')
    if workbook:
        add_file(ctx, 'DuLieuXuat.xlsx', [s for _, s in lists])
        for name, s in lists:
            s.name = name
        units_file = 'DuLieuXuat.xlsx'
    else:
        for name, s in lists:
            add_file(ctx, f'{name}.xlsx', s, master=name == 'DanhSachSanPham')
        units_file = 'DanhSachQuyDoi.xlsx'
    ctx.keep('order_ids', 'units')
    if len(L.customers):
        ctx.keep('customers')
    ctx.intro.append(N._pick(rng, [
        'File Excel xuất từ phần mềm bán hàng, mỗi danh sách một file (danh sách dài tách thành nhiều file, tên thêm '
        'đuôi _1, _2… hoặc đuôi năm _2025, _2026…). File đơn hàng mỗi dòng một sản phẩm, thông tin đơn lặp lại ở mọi '
        'dòng của đơn; file này không có mã sản phẩm, nối với các danh sách sản phẩm qua tên sản phẩm. Ngày dạng '
        'dd/mm/yyyy.',
        'File Excel xuất từ phần mềm bán hàng. File đơn hàng mỗi dòng một sản phẩm.']))
    if workbook:
        ctx.intro.append(f'Các danh sách {", ".join(f"`{n}`" for n, _ in lists)} nằm chung file `DuLieuXuat.xlsx`, '
                         f'mỗi danh sách một sheet.')
    month_intro(ctx, month_files)
    if fill:
        h = dict(zip(keys, headers))
        ctx.conventions.append(('fill_down', {'cols': [h[k] for k in FILL_KEYS]}))
    if pharmacy and 'DonHang_Lo' in ' '.join(f.name for f in ctx.files):
        ctx.conventions.append(('lots', {}))
        ctx.conventions.append(('drugs', {'col': D_PH['rx']}))
    _fee_convention(ctx)
    ctx.conventions.append(('units_table', {'file': units_file}))


# ---------------------------------------------------------------- family A: flat CSV of lines
def render_A(ctx: Ctx, out_dir: Path):
    L, rng, nz = ctx.L, ctx.rng, ctx.nz
    o, ln = views(L)
    disp = Display(ctx, o, codes_for_customers=False)
    fmt = Fmt(money=N._pick(rng, [{'comma': 1.0}, {'int': 0.6, 'comma': 0.4}, {'int': 1.0}]), xlsx=False,
              date=N._pick(rng, ['dmy', 'thg', 'dmy']), qty_rate=nz.qty_unit_rate)
    keys = ['order_id', 'date', 'status', 'product_name', 'unit', 'qty', 'base_qty', 'unit_price', 'amount']
    with_cust = len(L.customers) > 0 and rng.random() < 0.8
    if with_cust:
        keys.append('customer_name')
    if L.has('product_ids') and rng.random() < 0.2:
        keys.append('product_id')
    headers = choose_headers(keys, rng)
    keys, headers = arrange(keys, headers, rng, True)
    ld = sales_display(ctx, ln, disp)
    names = single_book(ctx, 'ban_hang', ld, keys, headers, fmt, ext='csv')
    ctx.keep('order_ids', 'units')
    if with_cust:
        ctx.keep('customers')
    if 'product_id' in keys:
        ctx.keep('product_ids')
    ctx.intro.append('Một file phẳng, mỗi dòng một bản ghi (một dòng hàng trong đơn).')
    if len(names) > 1:
        ctx.intro.append('File dài tách thành nhiều file, tên thêm đuôi _1, _2….')
    _fee_convention(ctx)
    inline_units(ctx)


# ---------------------------------------------------------------- family B: owner's notebook (no order id/customer)
def render_B(ctx: Ctx, out_dir: Path):
    L, rng, nz = ctx.L, ctx.rng, ctx.nz
    o, ln = views(L)
    disp = Display(ctx, o, codes_for_customers=False)
    fmt = Fmt(money=N._pick(rng, [{'comma': 1.0}, {'int': 0.5, 'dot_d': 0.5}, {'comma': 0.7, 'int': 0.3}]),
              date=N._pick(rng, ['dmy', 'date', 'dmy']), qty_rate=nz.qty_unit_rate)
    keys = ['status', 'amount', 'date', 'qty', 'product_name', 'unit_price', 'unit', 'base_qty']
    headers = choose_headers(keys, rng)
    keys, headers = arrange(keys, headers, rng, True)
    ld = sales_display(ctx, ln, disp)
    rows = table_rows(ld, keys, fmt, ctx)
    if rng.random() < 0.5:                                # monthly total rows ('TỔNG THÁNG 7') between months
        per = pd.to_datetime(ld['date']).dt.to_period('M').tolist()
        out, li, ai = [], keys.index('product_name'), keys.index('amount')
        acc = 0
        for i, r in enumerate(rows):
            out.append(r)
            acc += ld['amount'].iat[i]
            if i == len(rows) - 1 or per[i + 1] != per[i]:
                t = [None] * len(keys)
                t[li], t[ai] = f'TỔNG THÁNG {per[i].month}', N.money(acc, fmt.money, rng)
                out.append(t)
                acc = 0
        rows = out
    parts = chunk(rows)
    for i, rs in enumerate(parts):
        add_file(ctx, 'SoBanHang.xlsx' if len(parts) == 1 else f'SoBanHang_{i + 1}.xlsx',
                 Sheet('Sheet1', headers, keys, rs), role='sales')
    ctx.keep('units')
    ctx.intro.append('Sổ bán hàng chủ tiệm tự ghi trên Excel, một sheet: mỗi dòng một mặt hàng khách mua, không ghi mã '
                     'đơn, không ghi tên khách.')
    _fee_convention(ctx)
    inline_units(ctx)


# ---------------------------------------------------------------- family C: handwritten monthly ledger
C_GROUP = {'product_name': 'Hàng', 'qty': 'Hàng', 'unit': 'Hàng', 'amount': 'Tiền', 'unit_price': 'Tiền',
           'status': 'Tiền', 'time': 'Đơn', 'order_id': 'Đơn', 'date': 'Đơn', 'customer_name': 'Đơn'}


def render_C(ctx: Ctx, out_dir: Path):
    L, rng, nz = ctx.L, ctx.rng, ctx.nz
    o, ln = views(L)
    disp = Display(ctx, o, codes_for_customers=False)
    fmt = Fmt(money={'dot_d': 0.7, 'k': 0.2, 'tr': 0.1}, date='dmy', qty_rate=nz.qty_unit_rate,
              noyear_rate=float(rng.uniform(0.2, 0.5)) if rng.random() < 0.4 else 0.0)
    keys = ['product_name', 'qty', 'unit', 'amount', 'status', 'unit_price', 'time', 'order_id', 'date']
    with_cust = len(L.customers) > 0 and rng.random() < 0.85
    if with_cust:
        keys.append('customer_name')
    headers = choose_headers(keys, rng)
    order = list(rng.permutation(['Hàng', 'Tiền', 'Đơn']))
    blocks = []
    for gname in order:
        idx = [i for i, k in enumerate(keys) if C_GROUP[k] == gname]
        blocks += rng.permutation(idx).tolist()
    keys, headers = [keys[i] for i in blocks], [headers[i] for i in blocks]
    group = [None] * len(keys)
    last = None
    for j, k in enumerate(keys):
        if C_GROUP[k] != last:
            group[j] = C_GROUP[k]
            last = C_GROUP[k]
    ld = sales_display(ctx, ln, disp)
    ld['time'] = ld['created']
    neg = return_lines(ctx, ln)
    if len(neg):
        neg = sales_display(ctx, neg, disp)
        neg['time'] = neg['created']
        ld = pd.concat([ld, neg], ignore_index=True).sort_values(['created', 'order_id'], kind='mergesort')
    note = [['Ghi chú: số liệu ghi tay']] if rng.random() < 0.6 else []
    names = monthly_book(ctx, 'SoBanHang', ld, keys, headers, fmt, group=group, below=note,
                         year_split=rng.random() < 0.4, pattern=N._pick(rng, MONTH_SHEET[2:4]))
    U = units_rows(L, True)
    lists = []
    if len(U):
        lists.append(('DanhMuc', list_sheet(ctx, U, ['product_name', 'base_unit', 'unit_big', 'factor'], Fmt())))
    P = product_frame(ctx)
    if 'stock_end' in P and L.has('stock'):
        lists.append(('TonKho', list_sheet(ctx, P[P['stock_end'].notna()], ['product_name', 'base_unit', 'stock_end'], Fmt())))
        ctx.keep('stock')
    if len(L.purchases) and L.has('purchases'):
        pu, pl = purchase_frames(ctx)
        pl = pl[pl['pur_status'] != 'Đã hủy'] if rng.random() < 0.5 else pl
        lists.append(('SoNhapHang', list_sheet(ctx, pl, ['purchase_id', 'pur_date', 'pur_note', 'pur_line_total',
                                                         'supplier_name', 'product_name', 'pur_unit_cost', 'pur_unit',
                                                         'pur_qty'],
                                               Fmt(money={'int': 0.4, 'comma': 0.2, 'dot_d': 0.2, 'k': 0.1, 'tr': 0.1},
                                                   date=N._pick(rng, ['date', 'dmy'])))))
        ctx.keep('purchases')
    if len(L.prices) and L.has('prices'):
        pr = L.prices.merge(L.products[['product_id', 'name']], on='product_id').rename(
            columns={'name': 'product_name', 'date': 'price_date', 'price': 'price_new'})
        pr = pr.sort_values(['product_id', 'price_date'], kind='mergesort')
        pr['price_old'] = pr.groupby('product_id')['price_new'].shift()
        lists.append(('BangGia', list_sheet(ctx, pr, ['price_date', 'product_name', 'price_new', 'price_old'],
                                            Fmt(money={'dot_d': 1.0}, date=N._pick(rng, ['date', 'dmy'])))))
        ctx.keep('prices')
    dv = delivery_frame(ctx, ln) if L.has('deliveries') else None
    if dv is not None:
        lists.append(('SoGiaoHang', list_sheet(ctx, dv, list(F_DELIV), Fmt(date='thg'))))
        ctx.keep('deliveries')
    du = due_frame(ctx, o) if dv is not None and L.has('debt') else None
    if du is not None:
        lists.append(('SoHanNo', list_sheet(ctx, du, list(F_DUE), Fmt(), shuffle=False)))
    if len(L.expenses) and L.has('expenses'):
        ex = L.expenses.rename(columns={'date': 'exp_date', 'category': 'exp_category', 'amount': 'exp_amount',
                                        'note': 'exp_note'})
        s = list_sheet(ctx, ex, ['exp_note', 'exp_date', 'exp_category', 'exp_amount'], Fmt(money={'k': 1.0}),
                       above=[['SỔ CHI PHÍ CỬA HÀNG'], []])
        lists.append(('SoChiPhi', s))
        ctx.keep('expenses')
    for name, s in lists:
        add_file(ctx, f'{name}.xlsx', s)
    ctx.keep('order_ids', 'time', 'units')
    if with_cust:
        ctx.keep('customers')
    ctx.intro.append('Sổ bán hàng ghi tay chuyển sang Excel, mỗi tháng một sheet.')
    H = {name: dict(zip(s.keys, s.headers)) for name, s in lists}
    ctx.doc_override.update({(n, dict(zip(keys, headers))['time']): 'giờ đặt đơn (dòng trả hàng: lúc trả)'
                             for n in names})
    if len(neg):
        ctx.conventions.append(('returns_negative', {}))
    if 'TonKho' in H:
        ctx.conventions.append(('stock_end', {'col': H['TonKho']['stock_end']}))
    if du is not None:
        ctx.conventions.append(('due', {'due': H['SoHanNo']['due_date'], 'days': H['SoHanNo']['due_days']}))
    if dv is not None:
        ctx.conventions.append(('deliveries', {'trip': H['SoGiaoHang']['trip_no'], 'qty': H['SoGiaoHang']['del_qty']}))
    if 'SoNhapHang' in H:
        ctx.conventions.append(('purchase_line_total', {'cost': H['SoNhapHang']['pur_unit_cost'],
                                                        'total': H['SoNhapHang']['pur_line_total']}))
    if 'BangGia' in H:
        h = H['BangGia']
        ctx.conventions.append(('prices', {'new': h['price_new'], 'date': h['price_date'], 'old': h['price_old']}))
    if 'SoChiPhi' in H:
        ctx.conventions.append(('expenses', {'col': H['SoChiPhi']['exp_amount']}))
    _fee_convention(ctx)
    if len(U):
        ctx.conventions.append(('units_table', {'file': 'DanhMuc.xlsx'}))
    else:
        inline_units(ctx)


# ---------------------------------------------------------------- family S (new): Google-Sheets CSV, English headers
def _en_case(h, mode):
    return {'as_is': h, 'lower': h.lower(), 'snake': h.lower().replace(' ', '_').replace('#', 'no').replace('(', '')
            .replace(')', '')}[mode]


def render_S(ctx: Ctx, out_dir: Path):
    L, rng, nz = ctx.L, ctx.rng, ctx.nz
    o, ln = views(L)
    disp = Display(ctx, o, codes_for_customers=False, english=N.draw_labels(rng, N.STATUS_EN2, 0.3))
    pay = {k: v for k, v in N.PAY_EN2.items()}
    fmt = Fmt(money=N._pick(rng, [{'int': 1.0}, {'comma': 1.0}, {'float': 1.0}]), xlsx=False, date='iso',
              datetime=N._pick(rng, ['iso_dt', 'dmy_hm']), qty_rate=0.0)
    case = N._pick(rng, ['as_is', 'lower', 'snake'])
    keys = ['order_id', 'created', 'status', 'product_id', 'product_name', 'unit', 'qty', 'unit_price', 'amount']
    if len(L.customers) and rng.random() < 0.7:
        keys.append('customer_name')
    if rng.random() < 0.5:
        keys.append('base_qty')
    if L.has('payment_method') and rng.random() < 0.6:
        keys.append('payment_method')
    if L.has('channel') and rng.random() < 0.4:
        keys.append('channel')
    headers = [_en_case(h, case) for h in choose_headers(keys, rng, pools=SYN_EN)]
    keys, headers = arrange(keys, headers, rng, rng.random() < 0.5)
    ld = sales_display(ctx, ln, disp)
    ld['payment_method'] = ld['payment_method'].map(pay)
    names = single_book(ctx, 'orders_export', ld, keys, headers, fmt, ext='csv')
    P = product_frame(ctx)
    ik = ['product_id', 'product_name', 'group', 'base_unit', 'price']
    s = list_sheet(ctx, P, ik, Fmt(xlsx=False), synonyms=True, shuffle=False)
    s.headers = [_en_case(h, case) for h in choose_headers(ik, rng, pools=SYN_EN)]
    add_file(ctx, 'items.csv', s, master=True)
    U = units_rows(L, False)
    if len(U):
        uk = ['product_id', 'unit_big', 'factor']
        s = list_sheet(ctx, U, uk, Fmt(xlsx=False), shuffle=False)
        s.headers = [_en_case(h, case) for h in choose_headers(uk, rng, pools=SYN_EN)]
        add_file(ctx, 'uom.csv', s)
    ctx.keep('order_ids', 'product_ids', 'groups', 'units', 'time')
    for k, cap in (('customer_name', 'customers'), ('payment_method', 'payment_method'), ('channel', 'channel')):
        if k in keys:
            ctx.keep(cap)
    ctx.intro.append('Bảng tính Google Sheets của tiệm, tải về dạng CSV; tên cột tiếng Anh. Mỗi dòng của '
                     f'`{names[0]}` là một dòng hàng, thông tin đơn lặp lại ở mọi dòng của đơn.')
    h = dict(zip(keys, headers))
    labels = {st: ls for st, ls in disp_labels(disp, o).items()}
    ctx.doc_override[(names[0], h['status'])] = 'trạng thái đơn: ' + '; '.join(
        f'{", ".join(v)} = {VI_STATE[k]}' for k, v in labels.items() if v)
    if 'payment_method' in h:
        ctx.doc_override[(names[0], h['payment_method'])] = ('hình thức thanh toán: Cash tiền mặt, Bank transfer chuyển '
                                                             'khoản, E-wallet ví điện tử, COD giao hàng thu tiền, '
                                                             'On credit ghi nợ')
    _fee_convention(ctx)
    if len(U):
        ctx.conventions.append(('units_table', {'file': 'uom.csv'}))
    else:
        inline_units(ctx)


VI_STATE = {'completed': 'hoàn thành', 'cancelled': 'huỷ', 'returned': 'trả hàng', 'delivering': 'đang giao'}


def disp_labels(disp, o):
    out = {}
    for oid, st in zip(o['order_id'], o['status']):
        out.setdefault(st, set()).add(disp.status[oid])
    return {k: sorted(v) for k, v in out.items()}


# ---------------------------------------------------------------- family P (new): pivot summary + quarterly details
def render_P(ctx: Ctx, out_dir: Path):
    L, rng, nz = ctx.L, ctx.rng, ctx.nz
    o, ln = views(L)
    disp = Display(ctx, o, codes_for_customers=False)
    fmt = Fmt(money={'int': 0.7, 'comma': 0.3}, date=N._pick(rng, ['date', 'dmy']), qty_rate=nz.qty_unit_rate)
    day = o.groupby('date').size().rename('day_orders').to_frame()
    ok = ln[ln['status'] != 'cancelled']
    day['day_amount'] = ok.groupby('date')['amount'].sum()
    day = day.fillna(0).reset_index()
    sk = ['date', 'day_orders', 'day_amount']
    summary = list_sheet(ctx, day, sk, Fmt(money={'int': 1.0}, date='date'), shuffle=False, name='TongHopNgay')
    summary.below = [['Tổng cộng', N.num(day['day_orders'].sum()), N.num(day['day_amount'].sum())]]
    keys = ['order_id', 'date', 'status', 'product_id', 'product_name', 'unit', 'qty', 'base_qty', 'unit_price',
            'amount']
    if len(L.customers) and rng.random() < 0.6:
        keys.append('customer_name')
    headers = choose_headers(keys, rng)
    keys, headers = arrange(keys, headers, rng, rng.random() < 0.5)
    ld = sales_display(ctx, ln, disp)
    per = pd.to_datetime(ld['date']).dt.to_period('Q')
    details = []
    for q, g in ld.groupby(per, sort=True):
        rows = table_rows(g, keys, fmt, ctx)
        rows, n = N.duplicate_rows(rows, nz.dup_rate, rng)
        dedupe_mark(ctx, n)
        details.append(Sheet(f'Q{q.quarter}-{q.year}', headers, keys, rows))
    P = product_frame(ctx)
    plist = list_sheet(ctx, P, ['product_id', 'product_name', 'group', 'base_unit', 'price'], Fmt(), name='DanhMucHang')
    U = units_rows(L, False)
    sheets = [summary] + details + [plist]
    if len(U):
        sheets.append(list_sheet(ctx, U, ['product_id', 'unit_big', 'factor'], Fmt(), name='QuyDoi', shuffle=False))
    if sum(len(s.rows) for s in details) > SPLIT_ROWS:          # long: details by year in separate workbooks
        add_file(ctx, 'BaoCaoBanHang.xlsx', [summary, plist] + sheets[len(details) + 2:], role='sales')
        years = sorted({s.name.split('-')[1] for s in details})
        for y in years:
            add_file(ctx, f'ChiTietBanHang_{y}.xlsx', [s for s in details if s.name.endswith(y)], role='sales')
        book_note = 'Chi tiết từng dòng hàng ở các file `ChiTietBanHang_<năm>.xlsx`, mỗi quý một sheet.'
    else:
        add_file(ctx, 'BaoCaoBanHang.xlsx', sheets, role='sales')
        book_note = 'Chi tiết từng dòng hàng ở các sheet theo quý (Q1-2025, Q2-2025…).'
    ctx.keep('order_ids', 'product_ids', 'groups', 'units')
    if 'customer_name' in keys:
        ctx.keep('customers')
    ctx.intro.append('Báo cáo bán hàng xuất từ phần mềm, một workbook: sheet `TongHopNgay` là bảng tổng hợp theo ngày. '
                     + book_note + ' Danh mục hàng ở sheet `DanhMucHang`.')
    ctx.conventions.append(('summary_sheet', {'sheet': 'TongHopNgay', 'amount': summary.headers[2]}))
    _fee_convention(ctx)
    if len(U):
        ctx.conventions.append(('units_table', {'where': 'sheet `QuyDoi` của `BaoCaoBanHang.xlsx`'}))
    else:
        inline_units(ctx)


# ---------------------------------------------------------------- entry points
RENDERERS = {'H': render_H, 'G': render_G, 'E': render_E, 'F': render_F, 'D': render_D, 'A': render_A, 'B': render_B,
             'C': render_C, 'S': render_S, 'P': render_P}
NEEDS = {'H': set(), 'G': {'order_ids', 'product_ids'}, 'E': {'order_ids', 'product_ids'}, 'F': {'order_ids'},
         'D': {'order_ids'}, 'A': {'order_ids'}, 'B': set(), 'C': {'order_ids'}, 'S': {'order_ids', 'product_ids'},
         'P': {'order_ids', 'product_ids'}}


def lines_meta(ctx):
    """Where the order lines went: {'files': [...], 'cols': {key: header}} (the first sheet holding lines)."""
    for f in ctx.files:
        for s in f.sheets:
            if {'amount', 'qty'} <= set(s.keys) and ({'product_name', 'product_id'} & set(s.keys)):
                same = [g.name for g in ctx.files if g.sheets and g.sheets[0].headers == s.headers]
                return {'files': same, 'cols': {k: h for k, h in zip(s.keys, s.headers) if k != 'filler'}}
    return None


def catalog_cost_written(ctx):
    """A product master (no order id) carries a per-product cost column; H: san_pham.GiaVonHang has values."""
    if ctx.family == 'H':
        P = ctx.L.products
        return 'cost' in P and P['cost'].notna().any()
    return any('cost' in s.keys and 'order_id' not in s.keys and 'product_id' in s.keys or
               'cost' in s.keys and 'order_id' not in s.keys and 'product_name' in s.keys
               for f in ctx.files for s in f.sheets)


def orders_meta(ctx):
    """The invoice list when order status/date live there (one row per order): {'files', 'cols'} or None."""
    for f in ctx.files:
        for s in f.sheets:
            if {'order_id', 'status'} <= set(s.keys) and 'qty' not in s.keys:
                return {'files': [f.name], 'cols': {k: h for k, h in zip(s.keys, s.headers) if k != 'filler'}}
    return None


def families_for(ledger):
    """Families the ledger can be rendered in (needs: order ids / product codes in the ledger, some lines)."""
    if not len(ledger.lines):
        return []
    return [f for f in FAMILIES if NEEDS[f] <= set(ledger.shop['caps'])]


def render(ledger, family, out_dir, rng, noise=None):
    """Write one shop folder; return {'files', 'caps', 'family', 'aliases', 'extras', 'noise'}."""
    from .readme import write_readme
    if family not in families_for(ledger):
        raise ValueError(f'family {family} not applicable to {ledger.shop["business_id"]}')
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    nz = noise or N.draw_noise(rng)
    ctx = Ctx(ledger, rng, nz, family)
    RENDERERS[family](ctx, out_dir)
    files = write_files(ctx, out_dir) if family != 'H' else ['pos.sqlite']
    ctx.extras['lines'] = lines_meta(ctx)
    ctx.caps.discard('catalog_cost')
    if catalog_cost_written(ctx):
        ctx.caps.add('catalog_cost')
    ctx.extras['orders'] = orders_meta(ctx)
    write_readme(ctx, out_dir)
    return {'files': files, 'caps': set(ctx.caps), 'family': family,
            'aliases': {k: {e: sorted(v) for e, v in d.items()} for k, d in ctx.aliases.items()},
            'extras': ctx.extras, 'noise': nz}
