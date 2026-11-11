"""Fast checks of gen.render / gen.noise / gen.readme on a small slice of biz_123's ledger.

run: PYTHONPATH=src:. python -m pytest tests_gen/test_render.py -q
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from datamate.data import load_business
from datamate.values import parse_number, parse_qty
from gen import noise as N
from gen.ledger import Ledger, load_sqlite_pos
from gen.render import FAMILIES, families_for, render

ROOT = Path(__file__).resolve().parents[1]
SHOP = ROOT / 'data' / 'train' / 'data' / 'biz_123'
CALENDAR = ROOT / 'data' / 'train' / 'calendar.csv'
_spec = importlib.util.spec_from_file_location('check_render', ROOT / 'scripts' / 'check_render.py')
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def slice_ledger(L, until='2025-02-20'):
    """Orders before `until` and everything hanging off them; masters kept whole."""
    T = dict(L.tables)
    o = T['orders'][pd.to_datetime(T['orders']['created']) < until]
    ids = set(o['order_id'])
    T['orders'] = o
    for t in ('lines', 'payments', 'returns', 'line_lots', 'deliveries'):
        if t in T:
            T[t] = T[t][T[t]['order_id'].isin(ids)]
    if 'purchases' in T:
        T['purchases'] = T['purchases'][pd.to_datetime(T['purchases']['date']) < until]
        pids = set(T['purchases']['purchase_id'])
        T['purchase_lines'] = T['purchase_lines'][T['purchase_lines']['purchase_id'].isin(pids)]
        T['lots'] = T['lots'][T['lots']['purchase_id'].isin(pids)]
    if 'stock_moves' in T:
        T['stock_moves'] = T['stock_moves'][pd.to_datetime(T['stock_moves']['time']) < until]
    if 'prices' in T:
        T['prices'] = T['prices'][pd.to_datetime(T['prices']['date']) < until]
    shop = dict(L.shop, end=(pd.Timestamp(until) - pd.Timedelta(days=1)).date())
    return Ledger(shop, T)


@pytest.fixture(scope='module')
def small():
    if not SHOP.exists():
        pytest.skip('train data not present')
    return slice_ledger(load_sqlite_pos(SHOP))


def test_families_for_full_ledger(small):
    assert families_for(small) == FAMILIES


def test_families_need_order_ids(small):
    shop = dict(small.shop, caps=set(small.shop['caps']) - {'order_ids', 'product_ids'})
    assert families_for(Ledger(shop, small.tables)) == ['H', 'B']


@pytest.mark.parametrize('fam', FAMILIES)
def test_render_reads_back(small, fam, tmp_path):
    res = render(small, fam, tmp_path / fam, np.random.default_rng(7))
    assert (tmp_path / fam / 'README.md').exists()
    readme = (tmp_path / fam / 'README.md').read_text(encoding='utf-8')
    assert readme.startswith(f'# Dữ liệu {small.shop["business_id"]}')
    assert f'Dữ liệu có đến hết {small.shop["end"]:%d/%m/%Y}.' in readme
    for f in res['files']:
        assert (tmp_path / fam / f).exists() and f'`{f}`' in readme
    biz = load_business(tmp_path / fam, CALENDAR)
    assert not biz.unreadable
    if fam == 'H':
        rev, *_ , issues = check.recovered_revenue_sqlite(biz)
    else:
        rev, n_raw, n_dedup, issues = check.recovered_revenue(
            biz, res['extras']['lines'], res['extras']['status_map'], 'order_id' in res['extras']['lines']['cols'],
            res['extras'].get('orders'))
        assert n_dedup >= len(small.lines)
    assert not issues
    assert abs(rev.sum() - check.ledger_revenue(small).sum()) < 0.5


def test_caps_dropped_by_family(small, tmp_path):
    caps = {f: render(small, f, tmp_path / f, np.random.default_rng(3))['caps'] for f in ('B', 'D', 'H', 'A')}
    assert not caps['B'] & {'order_ids', 'customers', 'customer_ids', 'payment_method', 'debt'}
    assert 'product_ids' not in caps['D']
    assert 'stock_history' in caps['H'] and 'payments' in caps['H']
    assert 'stock' not in caps['A'] and 'customer_ids' not in caps['A']


def test_no_duplicates_in_notebook(small, tmp_path):
    nz = N.draw_noise(np.random.default_rng(1), 'heavy')
    nz.dup_rate = 0.05
    res = render(small, 'B', tmp_path / 'B', np.random.default_rng(1), nz)
    assert res['extras'].get('duplicate_rows', 0) == 0


def test_deterministic(small, tmp_path):
    def digest(d):
        return hashlib.sha256(b''.join((d / f).read_bytes() for f in sorted(p.name for p in d.iterdir()))).hexdigest()
    for k in ('a', 'b'):
        render(small, 'E', tmp_path / k, np.random.default_rng(11))
    assert digest(tmp_path / 'a') == digest(tmp_path / 'b')


def test_fill_down_layout(small, tmp_path):
    nz = N.draw_noise(np.random.default_rng(2))
    nz.fill_down = True
    res = render(small, 'D', tmp_path / 'D', np.random.default_rng(2), nz)
    biz = load_business(tmp_path / 'D', CALENDAR)
    name = check.find_lines_table(biz, res['extras']['lines']['cols'])
    assert any('filled from the group' in c['about'] for p in biz.profiles if p['table'] == name for c in p['columns'])
    assert 'Dòng tiếp theo của một đơn' in (tmp_path / 'D' / 'README.md').read_text(encoding='utf-8')


# ---------------------------------------------------------------- noise helpers
@pytest.mark.parametrize('v', [0, 800, 1000, 25500, 45000, 1_440_000, 16_560_000, 2_000_000, -49_000, 1_234_567])
def test_money_styles_keep_value(v):
    rng = np.random.default_rng(0)
    for _ in range(50):
        cell = N.money(v, {s: 1.0 for s in N.MONEY_STYLES}, rng)
        assert (parse_number(cell) if isinstance(cell, str) else float(cell)) == v


def test_qty_text_parses():
    rng = np.random.default_rng(0)
    assert N.qty(3, 'chai', 1.0, rng) == '3 chai'
    assert parse_qty(N.qty(2, 'xe 4m3', 1.0, rng)) == (2.0, 'xe 4m3')
    assert N.qty(3, 'chai', 0.0, rng) == 3


def test_spelling_variants_only_change_writing():
    rng = np.random.default_rng(0)
    name = 'Cà phê muối (M)'
    key = lambda s: N.strip_accents(' '.join(s.split())).lower()
    for v in N.spelling_variants(name, rng, 5):
        assert v != name and key(v) == key(name)


def test_status_labels_unique_state():
    rng = np.random.default_rng(0)
    labels = N.draw_labels(rng, N.STATUS_POOL)
    seen = {}
    for st, ls in labels.items():
        for lab in ls:
            assert seen.setdefault(lab, st) == st
    flat = [lab for ls in N.STATUS_POOL.values() for lab in ls]
    assert len(flat) == len(set(flat))


def test_duplicates_follow_original():
    rows = [[i] for i in range(1000)]
    out, n = N.duplicate_rows(rows, 0.02, np.random.default_rng(0))
    assert len(out) == 1000 + n and 5 < n < 40
    assert sum(out[i] == out[i + 1] for i in range(len(out) - 1)) == n      # each copy right after its original


def test_catalog_cost_marker(small, tmp_path):
    """'catalog_cost' iff a product master with a cost column was written (H always: san_pham.GiaVonHang)."""
    for fam in FAMILIES:
        for sd in range(4):
            res = render(small, fam, tmp_path / f'{fam}{sd}', np.random.default_rng(sd))
            biz = load_business(tmp_path / f'{fam}{sd}', CALENDAR) if fam != 'H' else None
            if fam == 'H':
                assert 'catalog_cost' in res['caps']
            elif fam in ('G', 'D', 'A', 'B', 'C', 'S', 'P'):
                assert 'catalog_cost' not in res['caps']
            else:
                has = any(set(['Giá vốn', 'Giá vốn hiện tại']) & set(df.columns) and 'Mã hóa đơn' not in df.columns
                          and len(df) == len(small.products) for df in biz.tables.values())
                assert ('catalog_cost' in res['caps']) == bool(has)
