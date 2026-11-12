"""Canonical ledger: the clean world a shop's files are rendered from, and the oracle computes answers on.

Schema (pandas DataFrames, clean dtypes, English names; ids are strings):
  shop        dict: business_id, name, industry, start (date), end (date), caps (set of capability names)
  products    product_id, name, group, base_unit, price (base unit), cost (base unit), kind ('goods'|'made'|'fee')
  units       product_id, unit, factor (base units in one unit), price
  customers   customer_id, name, group, phone, address
  staff       staff_id, name, role
  suppliers   supplier_id, name
  orders      order_id, created (datetime), customer_id (None = walk-in), staff_id, channel, status
              ('completed'|'cancelled'|'returned'|'delivering'), subtotal, discount, shipping, vat, total,
              payment_method ('cash'|'transfer'|'ewallet'|'cod'|'debt'), promo, area
  lines       order_id, line_no, product_id, unit, qty, base_qty, unit_price, line_discount, amount, unit_cost
  payments    payment_id, order_id, time, amount, method
  returns     return_id, order_id, time, reason, refund
  purchases   purchase_id, supplier_id, date, status ('received'|'cancelled'), total, note
  purchase_lines  purchase_id, line_no, product_id, unit, qty, unit_cost, lot, expiry
  stock_moves product_id, time, kind, base_qty (signed), doc_id, balance
  prices      product_id, date, price (base unit)
  lots        lot, product_id, purchase_id, expiry, base_qty, base_cost
  line_lots   order_id, line_no, lot, base_qty, returned_base_qty
  drugs       product_id, ingredient, rx (bool)
  expenses    date, category, amount, note
  deliveries  order_id, trip_no, date, plate, driver
  visits      order_id, table, area, guests (None = not written, e.g. takeaway), plate (vehicle of a repair order)
Empty optional tables are empty DataFrames with the columns above; `caps` says which exist in the shop's files.
"""
from __future__ import annotations

import datetime as dt
import pickle
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

COLUMNS = {
    'products': ['product_id', 'name', 'group', 'base_unit', 'price', 'cost', 'kind'],
    'units': ['product_id', 'unit', 'factor', 'price'],
    'customers': ['customer_id', 'name', 'group', 'phone', 'address'],
    'staff': ['staff_id', 'name', 'role'],
    'suppliers': ['supplier_id', 'name'],
    'orders': ['order_id', 'created', 'customer_id', 'staff_id', 'channel', 'status', 'subtotal', 'discount',
               'shipping', 'vat', 'total', 'payment_method', 'promo', 'area'],
    'lines': ['order_id', 'line_no', 'product_id', 'unit', 'qty', 'base_qty', 'unit_price', 'line_discount',
              'amount', 'unit_cost'],
    'payments': ['payment_id', 'order_id', 'time', 'amount', 'method'],
    'returns': ['return_id', 'order_id', 'time', 'reason', 'refund'],
    'purchases': ['purchase_id', 'supplier_id', 'date', 'status', 'total', 'note'],
    'purchase_lines': ['purchase_id', 'line_no', 'product_id', 'unit', 'qty', 'unit_cost', 'lot', 'expiry'],
    'stock_moves': ['product_id', 'time', 'kind', 'base_qty', 'doc_id', 'balance'],
    'prices': ['product_id', 'date', 'price'],
    'lots': ['lot', 'product_id', 'purchase_id', 'expiry', 'base_qty', 'base_cost'],
    'line_lots': ['order_id', 'line_no', 'lot', 'base_qty', 'returned_base_qty'],
    'drugs': ['product_id', 'ingredient', 'rx'],
    'expenses': ['date', 'category', 'amount', 'note'],
    'deliveries': ['order_id', 'trip_no', 'date', 'plate', 'driver'],
    'visits': ['order_id', 'table', 'area', 'guests', 'plate'],
}

# Capabilities: what kind of information the shop's files carry (questions needing a missing one are unanswerable).
CAPS = ['customers', 'customer_ids', 'customer_groups', 'staff', 'time', 'channel', 'payment_method', 'debt',
        'purchases', 'stock', 'lots', 'prices', 'drugs', 'expenses', 'deliveries', 'unit_cost', 'units', 'groups',
        'order_ids', 'product_ids', 'tables', 'guests', 'plates']


@dataclass
class Ledger:
    shop: dict
    tables: dict = field(default_factory=dict)

    def __getattr__(self, name):
        if name in COLUMNS:
            t = self.tables.get(name)
            return t if t is not None else pd.DataFrame(columns=COLUMNS[name])
        raise AttributeError(name)

    def has(self, cap):
        return cap in self.shop['caps']

    def save(self, path):
        Path(path).write_bytes(pickle.dumps(self))

    @staticmethod
    def load(path):
        return pickle.loads(Path(path).read_bytes())


def _readme_end(readme: str):
    m = re.search(r'có đến hết (\d{1,2})/(\d{1,2})/(\d{4})', readme)
    return dt.date(int(m[3]), int(m[2]), int(m[1])) if m else None


def _dt(series):
    return pd.to_datetime(series, errors='coerce')


# ------------------------------------------------------------------ loaders of train shops (calibration only)
def load_sqlite_pos(shop_dir) -> Ledger:
    """biz_123-style pos.sqlite: nearly the raw world. Dedups exact duplicate rows (injected export noise)."""
    shop_dir = Path(shop_dir)
    con = sqlite3.connect(shop_dir / 'pos.sqlite')
    raw = {t: pd.read_sql(f'select * from "{t}"', con).drop_duplicates()
           for (t,) in con.execute("select name from sqlite_master where type='table'")}
    readme = (shop_dir / 'README.md').read_text(encoding='utf-8')
    sp = raw['san_pham']
    T = {}
    T['products'] = pd.DataFrame({'product_id': sp.MaHangHoa, 'name': sp.TenGoi, 'group': sp.DanhMuc,
                                  'base_unit': sp.DonViCoSo, 'price': sp.GiaBanLe, 'cost': sp.GiaVonHang,
                                  'kind': 'goods'})
    u = raw['don_vi_sp']
    T['units'] = pd.DataFrame({'product_id': u.MaHangHoa, 'unit': u.DonViTinh, 'factor': u.HeSoQuyDoi,
                               'price': u.GiaDonVi})
    k = raw['khach_hang']
    T['customers'] = pd.DataFrame({'customer_id': k.MaKhachHang, 'name': k.TenGoi, 'group': k.LoaiKhachHang,
                                   'phone': k.SoDienThoai, 'address': k.DiaChiLienHe})
    nv = raw['nhan_vien']
    T['staff'] = pd.DataFrame({'staff_id': nv.MaNhanVien, 'name': nv.TenGoi, 'role': nv.ChucVu})
    T['suppliers'] = pd.DataFrame({'supplier_id': raw['nha_cung_cap'].MaNhaCungCap,
                                   'name': raw['nha_cung_cap'].TenGoi})
    o = raw['don_hang']
    T['orders'] = pd.DataFrame({
        'order_id': o.MaHoaDon, 'created': _dt(o.ThoiGianLap), 'customer_id': o.MaKhachHang.where(o.MaKhachHang.notna(), None),
        'staff_id': o.MaNhanVien, 'channel': o.KenhBanHang, 'status': o.TinhTrang.map(
            {'completed': 'completed', 'cancelled': 'cancelled', 'returned': 'returned',
             'shipping': 'delivering', 'delivering': 'delivering'}).fillna(o.TinhTrang),
        'subtotal': o.TongTienHang, 'discount': o.ChietKhau, 'shipping': o.PhiVanChuyen, 'vat': o.ThueGTGT,
        'total': o.TongThanhToan, 'payment_method': o.PhuongThucTT, 'promo': o.MaKhuyenMai, 'area': None})
    c = raw['chi_tiet_don']
    T['lines'] = pd.DataFrame({'order_id': c.MaHoaDon, 'line_no': c.SoThuTu, 'product_id': c.MaHangHoa,
                               'unit': c.DonViTinh, 'qty': c.SL, 'base_qty': c.SLQuyDoi, 'unit_price': c.GiaDonVi,
                               'line_discount': c.ChietKhau, 'amount': c.TriGia, 'unit_cost': c.GiaVonLucBan})
    t = raw['thanh_toan']
    T['payments'] = pd.DataFrame({'payment_id': t.MaPhieuThu, 'order_id': t.MaHoaDon, 'time': _dt(t.NgayGioThu),
                                  'amount': t.SoTienThu, 'method': t.PhuongThuc})
    r = raw['tra_hang']
    T['returns'] = pd.DataFrame({'return_id': r.MaPhieuTra, 'order_id': r.MaHoaDon, 'time': _dt(r.NgayGioTra),
                                 'reason': r.NguyenNhan, 'refund': r.TienHoanTra})
    p = raw['phieu_nhap']
    T['purchases'] = pd.DataFrame({'purchase_id': p.MaPhieuNhap, 'supplier_id': p.MaNhaCungCap,
                                   'date': _dt(p.NgayNhapKho), 'status': p.TinhTrang, 'total': p.TongGiaTriNhap,
                                   'note': p.DienGiai})
    pl = raw['chi_tiet_nhap']
    T['purchase_lines'] = pd.DataFrame({'purchase_id': pl.MaPhieuNhap, 'line_no': pl.SoThuTu,
                                        'product_id': pl.MaHangHoa, 'unit': pl.DonViTinh, 'qty': pl.SL,
                                        'unit_cost': pl.DonGiaNhap, 'lot': pl.MaLo, 'expiry': _dt(pl.HanSuDung)})
    s = raw['the_kho']
    T['stock_moves'] = pd.DataFrame({'product_id': s.MaHangHoa, 'time': _dt(s.NgayGioPhatSinh),
                                     'kind': s.LoaiGiaoDich, 'base_qty': s.SLQuyDoi, 'doc_id': s.MaChungTu,
                                     'balance': s.TonCuoi, 'seq': s.MaGiaoDichKho})
    g = raw['lich_su_gia']
    T['prices'] = pd.DataFrame({'product_id': g.MaHangHoa, 'date': _dt(g.NgayApDung), 'price': g.GiaBanLe})
    lo = raw['lo_hang']
    T['lots'] = pd.DataFrame({'lot': lo.MaLo, 'product_id': lo.MaHangHoa, 'purchase_id': lo.MaPhieuNhap,
                              'expiry': _dt(lo.HanSuDung), 'base_qty': lo.SLNhapQuyDoi, 'base_cost': lo.DonGiaNhap})
    ll = raw['chi_tiet_don_lo']
    T['line_lots'] = pd.DataFrame({'order_id': ll.MaHoaDon, 'line_no': ll.SoThuTu, 'lot': ll.MaLo,
                                   'base_qty': ll.SLQuyDoi, 'returned_base_qty': ll.SLTraQuyDoi})
    d = raw['thong_tin_thuoc']
    T['drugs'] = pd.DataFrame({'product_id': d.MaHangHoa, 'ingredient': d.ThanhPhanChinh,
                               'rx': d.BanTheoDon.astype(int).astype(bool)})
    T['lines'] = T['lines'].drop_duplicates()
    start = T['orders'].created.min().date().replace(day=1)
    caps = {'customers', 'customer_ids', 'customer_groups', 'staff', 'time', 'channel', 'payment_method', 'debt',
            'purchases', 'stock', 'lots', 'prices', 'drugs', 'unit_cost', 'units', 'groups', 'order_ids',
            'product_ids', 'stock_history', 'payments', 'catalog_cost'}
    shop = {'business_id': shop_dir.name, 'name': raw['chi_nhanh'].TenGoi.iloc[0], 'industry': 'pharmacy',
            'start': start, 'end': _readme_end(readme), 'caps': caps}
    return Ledger(shop, T)


def _num(series):
    from datamate.values import parse_number
    return series.map(lambda v: parse_number(v) if isinstance(v, str) else v).astype(float)


def _date(series):
    from datamate.values import parse_datetime
    return pd.to_datetime(series.map(lambda v: parse_datetime(v)), errors='coerce')


def _qty(series):
    from datamate.values import parse_qty
    def one(v):
        if isinstance(v, str):
            q = parse_qty(v)
            return q[0] if isinstance(q, tuple) else q
        return v
    return series.map(one).astype(float)


def load_normalized_csv(shop_dir, cols: dict, industry: str) -> Ledger:
    """Family G (don_hang/chi_tiet_don/khach_hang/san_pham/thanh_toan CSV). cols maps canonical -> file column per
    file. Calibration helper: the column maps are written by hand for the three train shops."""
    shop_dir = Path(shop_dir)
    rd = lambda f: pd.read_csv(shop_dir / f, dtype=str, encoding='utf-8-sig')
    readme = (shop_dir / 'README.md').read_text(encoding='utf-8')
    o, c, k, s, t = (rd(f) for f in ('don_hang.csv', 'chi_tiet_don.csv', 'khach_hang.csv', 'san_pham.csv',
                                     'thanh_toan.csv'))
    m = cols
    T = {}
    T['products'] = pd.DataFrame({'product_id': s[m['sp_id']], 'name': s[m['sp_name']], 'group': s[m['sp_group']],
                                  'base_unit': s[m['sp_unit']], 'price': _num(s[m['sp_price']]), 'cost': None,
                                  'kind': 'goods'})
    T['products'].loc[T['products'].name.str.strip().str.lower() == 'phí phục vụ', 'kind'] = 'fee'
    T['customers'] = pd.DataFrame({'customer_id': k[m['kh_id']], 'name': k[m['kh_name']],
                                   'group': k[m['kh_group']] if m.get('kh_group') else None,
                                   'phone': None, 'address': None})
    status = {'completed': 'completed', 'cancelled': 'cancelled', 'returned': 'returned', 'shipping': 'delivering'}
    cust = o[m['o_cust']]
    T['orders'] = pd.DataFrame({'order_id': o[m['o_id']], 'created': _date(o[m['o_date']]),
                                'customer_id': cust.where(cust.notna(), None), 'staff_id': None,
                                'channel': o[m['o_channel']] if m.get('o_channel') else None,
                                'status': o[m['o_status']].map(status).fillna(o[m['o_status']]),
                                'subtotal': None, 'discount': None, 'shipping': None, 'vat': 0,
                                'total': _num(o[m['o_total']]), 'payment_method': o[m['o_pay']], 'promo': None,
                                'area': None})
    T['lines'] = pd.DataFrame({'order_id': c[m['l_order']], 'line_no': c[m['l_no']], 'product_id': c[m['l_prod']],
                               'unit': c[m['l_unit']], 'qty': _qty(c[m['l_qty']]), 'base_qty': _qty(c[m['l_base']]),
                               'unit_price': _num(c[m['l_price']]), 'line_discount': 0,
                               'amount': _num(c[m['l_amount']]), 'unit_cost': None})
    T['lines'] = T['lines'].drop_duplicates()
    T['payments'] = pd.DataFrame({'payment_id': t[m['p_id']], 'order_id': t[m['p_order']],
                                  'time': _date(t[m['p_time']]), 'amount': _num(t[m['p_amount']]),
                                  'method': t[m['p_method']]})
    units = re.findall(r'-\s*(.+?): 1 (\S+) = (\d+) (\S+)', readme)
    name2id = dict(zip(T['products'].name, T['products'].product_id))
    T['units'] = pd.DataFrame([{'product_id': name2id.get(n.strip()), 'unit': u, 'factor': int(f), 'price': None}
                               for n, u, f, _ in units], columns=COLUMNS['units'])
    start = T['orders'].created.min().date().replace(day=1)
    caps = {'customers', 'customer_ids', 'payment_method', 'debt', 'units', 'groups', 'order_ids', 'product_ids',
            'payments'}
    if m.get('kh_group'):
        caps.add('customer_groups')
    if m.get('o_channel'):
        caps.add('channel')
    shop = {'business_id': shop_dir.name, 'name': shop_dir.name, 'industry': industry, 'start': start,
            'end': _readme_end(readme), 'caps': caps}
    return Ledger(shop, T)


G_COLUMNS = {
    'biz_111': dict(sp_id='SKU', sp_name='Sản phẩm', sp_group='Nhom hang', sp_unit='Đơn vị', sp_price='Giá',
                    kh_id='ma_kh', kh_name='Khách lẻ/sỉ', kh_group='Nhóm',
                    o_id='Mã chứng từ', o_date='NgayBan', o_cust='Số KH', o_channel='Bán qua', o_status='Xử lý',
                    o_total='Tổng bill', o_pay='Phương thức TT',
                    l_order='Ma don', l_no='Thứ tự', l_prod='ID SP', l_unit='Đơn vị (tính)', l_qty='SL',
                    l_base='SL quy đổi', l_price='Giá đơn vị', l_amount='T.Tiền',
                    p_id='Mã phiếu thu', p_order='Số HĐ', p_time='Thời gian thu', p_amount='Tiền',
                    p_method='Phương thức'),
    'biz_127': dict(sp_id='Mã sản phẩm bán', sp_name='Tên SP', sp_group='Danh mục', sp_unit='Đơn vị cơ bản',
                    sp_price='Giá niêm yết', kh_id='Mã KH', kh_name='Khách hàng (tên)', kh_group=None,
                    o_id='Mã chứng từ', o_date='Ngày', o_cust='Customer ID', o_channel='Loại bán',
                    o_status='Tình trạng', o_total='Tổng đơn', o_pay='Trả bằng',
                    l_order='Mã đơn hàng', l_no='No.', l_prod='Mã mặt hàng', l_unit='DVT', l_qty='SoLuong',
                    l_base='Số lượng lẻ', l_price='Đơn giá (đ)', l_amount='Amount',
                    p_id='Mã GD', p_order='Số CT', p_time='Ngày thu', p_amount='Giá trị', p_method='HTTT'),
    'biz_129': dict(sp_id='Mã HH', sp_name='Tên sản phẩm', sp_group='Nhom hang', sp_unit='Đơn vị tính',
                    sp_price='Giá hiện tại', kh_id='Mã khách lẻ/sỉ', kh_name='KH', kh_group='Nhóm',
                    o_id='Số phiếu', o_date='Ngày bán', o_cust='Mã khách mua', o_channel=None,
                    o_status='Tình trạng đơn', o_total='Phải thu', o_pay='Hình thức thanh toán',
                    l_order='Số CT', l_no='TT dòng', l_prod='Mã hàng bán', l_unit='ĐV tính', l_qty='S.L',
                    l_base='Quy ra ĐV lẻ', l_price='Giá 1 đv', l_amount='Tiền bán',
                    p_id='Mã GD', p_order='Mã giao dịch', p_time='Thời điểm', p_amount='Tiền', p_method='PTTT'),
}


# ------------------------------------------------------------------ family E (KiotViet-like lists), calibration
def _status(label):
    from datamate.values import fold
    f = fold(label or '')
    if f in ('xong', 'ok', 'completed') or re.search(r'hoan thanh|da xong|thanh cong|da giao|da lay|xong', f):
        return 'completed'
    if 'huy' in f or 'khong giao' in f or 'cancel' in f:
        return 'cancelled'
    if 'tra' in f or 'hoan' in f or 'return' in f:
        return 'returned'
    if 'dang' in f or 'cho giao' in f or 'shipping' in f or 'van chuyen' in f:
        return 'delivering'
    return 'completed'


def _method(label):
    from datamate.values import fold
    f = fold(label or '')
    for k, v in (('tien mat', 'cash'), ('cash', 'cash'), ('chuyen khoan', 'transfer'), ('transfer', 'transfer'),
                 ('vi', 'ewallet'), ('cod', 'cod'), ('thu ho', 'cod'), ('no', 'debt'), ('debt', 'debt')):
        if k in f.split() or k in f:
            return v
    return f


def load_kiotviet(shop_dir, industry, cache_dir=None) -> Ledger:
    """biz_106-style DanhSach* lists through the production reader (typed columns). Stock history is rebuilt
    backwards from 'Tồn cuối kỳ' (stock at the end of the data) with purchases, sales and returns."""
    import sys as _s
    from datamate.data import load_business
    shop_dir = Path(shop_dir)
    B = load_business(shop_dir, shop_dir.parents[1] / 'calendar.csv', cache_dir)
    t = B.tables
    readme = (shop_dir / 'README.md').read_text(encoding='utf-8')
    sp, hd, ct = t['danh_sach_san_pham'], t['danh_sach_hoa_don'], t['danh_sach_hoa_don_chi_tiet']
    T = {}
    T['products'] = pd.DataFrame({'product_id': sp['Mã hàng'], 'name': sp['Tên hàng'], 'group': sp['Nhóm hàng(3 Cấp)'],
                                  'base_unit': sp['ĐVT'], 'price': sp['Giá bán'], 'cost': sp.get('Giá vốn'), 'kind': 'goods'})
    if industry in ('cafe', 'restaurant'):
        dv = t.get('danh_sach_don_vi_tinh')
        has_units = set(dv['Mã hàng']) if dv is not None else set()
        T['products'].loc[~T['products'].product_id.isin(has_units), 'kind'] = 'made'
    T['products'].loc[T['products'].name.str.strip().str.lower() == 'phí phục vụ', 'kind'] = 'fee'
    dv = t.get('danh_sach_don_vi_tinh')
    T['units'] = (pd.DataFrame({'product_id': dv['Mã hàng'], 'unit': dv['ĐVT'], 'factor': dv['Quy đổi'], 'price': dv['Giá bán']})
                  if dv is not None else pd.DataFrame(columns=COLUMNS['units']))
    kh = t['danh_sach_khach_hang']
    T['customers'] = pd.DataFrame({'customer_id': kh['Mã khách hàng'], 'name': kh['Tên khách hàng'],
                                   'group': kh.get('Nhóm khách hàng'), 'phone': None, 'address': None})
    cust = hd['Mã KH'].where(hd['Mã KH'].notna(), None)
    T['orders'] = pd.DataFrame({'order_id': hd['Mã hóa đơn'], 'created': hd['Thời gian tạo'], 'customer_id': cust,
                                'staff_id': hd.get('Người bán'), 'channel': hd.get('Kênh bán'),
                                'status': hd['Trạng thái'].map(_status), 'subtotal': hd['Tổng tiền hàng'],
                                'discount': hd['Giảm giá'], 'shipping': 0, 'vat': 0, 'total': hd['Tổng sau giảm giá'],
                                'payment_method': hd['Phương thức thanh toán'].map(_method), 'promo': None, 'area': None})
    ct = ct.drop(columns=[c for c in ct.columns if c.endswith('__raw') or c == '__source']).drop_duplicates()
    T['lines'] = pd.DataFrame({'order_id': ct['Mã hóa đơn'], 'line_no': ct['STT'], 'product_id': ct['Mã hàng'],
                               'unit': ct['Đơn vị tính'], 'qty': ct['Số lượng'], 'base_qty': ct['Số lượng quy đổi'],
                               'unit_price': ct['Đơn giá'], 'line_discount': ct['Giảm giá'], 'amount': ct['Thành tiền'],
                               'unit_cost': ct['Giá vốn']})
    sq = t.get('so_quy')
    if sq is not None:
        T['payments'] = pd.DataFrame({'payment_id': sq['Mã phiếu'], 'order_id': sq['Mã hóa đơn'], 'time': sq['Thời gian'],
                                      'amount': sq['Giá trị'], 'method': sq['Phương thức thanh toán'].map(_method)})
    nh, nct = t['danh_sach_nhap_hang'], t['danh_sach_chi_tiet_nhap_hang']
    T['purchases'] = pd.DataFrame({'purchase_id': nh['Mã nhập hàng'], 'supplier_id': nh['Mã NCC'], 'date': nh['Thời gian'],
                                   'status': nh['Trạng thái'].map(lambda s: 'cancelled' if 'hủy' in str(s).lower() or 'huỷ' in str(s).lower() else 'received'),
                                   'total': nh['Cần trả NCC'], 'note': nh['Ghi chú']})
    T['purchase_lines'] = pd.DataFrame({'purchase_id': nct['Mã nhập hàng'], 'line_no': nct['STT'], 'product_id': nct['Mã hàng'],
                                        'unit': nct['ĐVT'], 'qty': nct['Số lượng'], 'unit_cost': nct['Đơn giá'],
                                        'lot': None, 'expiry': None})
    T['suppliers'] = pd.DataFrame(columns=COLUMNS['suppliers'])
    end = _readme_end(readme)
    # stock history: end stock, then moves (purchases +, sales -, cancelled orders none)
    tk = t['bao_cao_ton_kho']
    fac = {(r.product_id, str(r.unit)): r.factor for r in T['units'].itertuples()}
    pl = T['purchase_lines'].merge(T['purchases'][['purchase_id', 'date', 'status']], on='purchase_id')
    pl = pl[pl.status != 'cancelled']
    mv_in = pd.DataFrame({'product_id': pl.product_id, 'time': pl.date,
                          'base_qty': pl.qty * [fac.get((p, str(u)), 1) for p, u in zip(pl.product_id, pl.unit)],
                          'kind': 'in_purchase', 'doc_id': pl.purchase_id})
    lo = T['lines'].merge(T['orders'][['order_id', 'created', 'status']], on='order_id')
    lo = lo[lo.status != 'cancelled']
    mv_out = pd.DataFrame({'product_id': lo.product_id, 'time': lo.created, 'base_qty': -lo.base_qty,
                           'kind': 'out_sale', 'doc_id': lo.order_id})
    mv = pd.concat([mv_in, mv_out]).sort_values('time', kind='stable').reset_index(drop=True)
    mv = mv[mv.time < pd.Timestamp(end) + pd.Timedelta(days=1)]
    endq = dict(zip(tk['Mã hàng'], tk['Tồn cuối kỳ']))
    total = mv.groupby('product_id').base_qty.sum()
    opening = {p: endq.get(p, 0) - total.get(p, 0) for p in set(endq) | set(total.index)}
    mv['balance'] = mv.groupby('product_id').base_qty.cumsum() + mv.product_id.map(opening)
    mv['seq'] = range(len(mv))
    T['stock_moves'] = mv
    caps = {'customers', 'customer_ids', 'time', 'payment_method', 'debt', 'purchases', 'stock', 'unit_cost',
            'units', 'groups', 'order_ids', 'product_ids', 'payments', 'catalog_cost'}
    shop = {'business_id': shop_dir.name, 'name': shop_dir.name, 'industry': industry,
            'start': T['orders'].created.min().date().replace(day=1), 'end': end, 'caps': caps}
    return Ledger(shop, T)
