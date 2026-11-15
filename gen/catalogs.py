"""Product catalogs per industry: harvested once from the train shops (each train industry shares one catalog with
the same names and codes), plus hand-written catalogs of industries absent from train (assets/new_industries.yaml).

python -m gen.catalogs   -> writes gen/assets/catalogs.json
Catalog entry: name, group, base_unit, price (base unit), cost (base unit), kind ('goods'|'made'|'fee'),
units [[unit, factor]], ingredient, rx (pharmacy only).
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
TRAIN = ROOT / 'data' / 'train' / 'data'
ASSETS = Path(__file__).with_name('assets')

INDUSTRY_OF = {**{f'biz_{i}': 'grocery' for i in (101, 102, 103, 107, 108, 109, 110)},
               **{f'biz_{i}': 'cafe' for i in (104, 105, 106, 111, 112)},
               **{f'biz_{i}': 'building' for i in range(113, 119)},
               **{f'biz_{i}': 'pharmacy' for i in range(119, 125)},
               **{f'biz_{i}': 'restaurant' for i in range(125, 131)}}

# industries that cook/mix on the spot: their items are not "bought to sell" (rulebook §5 hết hàng)
MADE_GROUPS = {'cafe': None, 'restaurant': None}


def readme_units():
    """'- Name: 1 U = N base' lines of every train README, per industry."""
    out = defaultdict(dict)
    for d in sorted(TRAIN.iterdir()):
        text = (d / 'README.md').read_text(encoding='utf-8')
        for name, unit, f, base in re.findall(r'^\s*-\s*(.+?): 1 (.+?) = (\d+) (\S+)\s*$', text, re.M):
            out[INDUSTRY_OF[d.name]].setdefault(name.strip(), {})[unit.strip()] = int(f)
    return out


def _clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return v


def _num(v):
    sys.path.insert(0, str(ROOT / 'src'))
    from datamate.values import parse_number
    x = parse_number(v) if isinstance(v, str) else v
    return None if x is None or pd.isna(x) else float(x)


def harvest():
    units = readme_units()
    cat = {}
    # pharmacy: biz_123 sqlite (products, conversions, drug info)
    import sqlite3
    con = sqlite3.connect(TRAIN / 'biz_123' / 'pos.sqlite')
    sp = pd.read_sql('select * from san_pham', con)
    dv = pd.read_sql('select * from don_vi_sp', con)
    tt = pd.read_sql('select * from thong_tin_thuoc', con).set_index('MaHangHoa')
    cat['pharmacy'] = [dict(name=r.TenGoi, group=r.DanhMuc, base_unit=r.DonViCoSo, price=float(r.GiaBanLe),
                            cost=float(r.GiaVonHang), kind='goods',
                            units=[[u.DonViTinh, int(u.HeSoQuyDoi)] for u in dv[dv.MaHangHoa == r.MaHangHoa].itertuples()],
                            ingredient=tt.ThanhPhanChinh.get(r.MaHangHoa), rx=bool(int(tt.BanTheoDon.get(r.MaHangHoa, 0))))
                       for r in sp.itertuples()]

    def from_csv(path, name, group, unit, price, industry):
        df = pd.read_csv(path, dtype=str, encoding='utf-8-sig')
        rows = []
        for _, r in df.iterrows():
            p = _num(r[price])
            u = units[industry].get(r[name], {})
            rows.append(dict(name=r[name], group=r[group], base_unit=r[unit], price=p, cost=None,
                             kind='fee' if r[name].strip().lower() == 'phí phục vụ' else 'goods',
                             units=[[k, v] for k, v in u.items()]))
        return rows

    cat['cafe'] = from_csv(TRAIN / 'biz_111' / 'san_pham.csv', 'Sản phẩm', 'Nhom hang', 'Đơn vị', 'Giá', 'cafe')
    cat['restaurant'] = from_csv(TRAIN / 'biz_129' / 'san_pham.csv', 'Tên sản phẩm', 'Nhom hang', 'Đơn vị tính',
                                 'Giá hiện tại', 'restaurant')
    # grocery and building: xlsx masters
    g = pd.read_excel(TRAIN / 'biz_108' / 'DanhSachSanPham.xlsx', dtype=str, header=None, engine='calamine')
    hdr = next(i for i in range(10) if 'Tên hàng' in list(g.iloc[i].astype(str)))
    g.columns = g.iloc[hdr]
    g = g.iloc[hdr + 1:]
    cat['grocery'] = [dict(name=r['Tên hàng'], group=r['Nhóm hàng(3 Cấp)'], base_unit=r['ĐVT'], price=_num(r['Giá bán']),
                           cost=None, kind='goods', units=[[k, v] for k, v in units['grocery'].get(r['Tên hàng'], {}).items()])
                      for _, r in g.iterrows() if isinstance(r['Tên hàng'], str)]
    b = pd.read_excel(TRAIN / 'biz_115' / 'Danh sách hàng hóa.xlsx', dtype=str, header=None, engine='calamine')
    hdr = next(i for i in range(10) if 'Tên hàng hóa' in list(b.iloc[i].astype(str)))
    b.columns = b.iloc[hdr]
    b = b.iloc[hdr + 1:]
    cat['building'] = [dict(name=r['Tên hàng hóa'], group=r['Nhóm hàng hóa'], base_unit=r['Đơn vị tính'], price=None,
                            cost=_num(r['Giá vốn']), kind='goods',
                            units=[[k, v] for k, v in units['building'].get(r['Tên hàng hóa'], {}).items()])
                       for _, r in b.iterrows() if isinstance(r['Tên hàng hóa'], str)]
    for ind in ('cafe', 'restaurant'):
        for e in cat[ind]:
            if e['kind'] != 'fee' and not e['units']:
                e['kind'] = 'made'                 # cooked/mixed on the spot (not bought to sell)
    new = yaml.safe_load((ASSETS / 'new_industries.yaml').read_text(encoding='utf-8'))
    for ind, spec in new.items():
        cat[ind] = [dict(name=n, group=e['group'], base_unit=e['unit'], price=float(p),
                         cost=None, kind=e.get('kind', 'goods'), units=[list(u) for u in e.get('units', [])])
                    for e in spec['items'] for n, p in _sized(e)]
    for ind, items in cat.items():
        for e in items:
            if e['price'] is None and e['cost'] is not None:
                e['price'] = round(e['cost'] * 1.25 / 500) * 500
            if e['cost'] is None and e['price'] is not None:
                e['cost'] = None                   # drawn per shop by the simulator
    return cat


def _sized(e):
    """(name, price) of one yaml entry: one per size when it lists sizes (price + size_step per size)."""
    if not e.get('sizes'):
        return [(e['name'], e['price'])]
    fmt, step = e.get('size_fmt', '{n} ({s})'), e.get('size_step', 0)
    return [(fmt.format(n=e['name'], s=s), e['price'] + i * step) for i, s in enumerate(e['sizes'])]


def load():
    return json.loads((ASSETS / 'catalogs.json').read_text(encoding='utf-8'))


def catalog(ind):
    """One industry's catalog: harvested/hand-written (catalogs.json) or model-generated (gen.industries)."""
    from . import industries
    if industries.is_generated(ind):
        return industries.catalog(ind)
    return load()[ind]


if __name__ == '__main__':
    c = harvest()
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / 'catalogs.json').write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding='utf-8')
    for k, v in c.items():
        print(k, len(v), 'with units', sum(bool(e['units']) for e in v), 'kinds',
              dict(pd.Series([e['kind'] for e in v]).value_counts()))
