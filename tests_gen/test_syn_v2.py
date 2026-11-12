"""Direction 3 generator: new trades, split rulebooks (gen.rulebook_gen), visit facts, the v2 builder and its
independent cross-check (scripts/check_syn.py). No model calls.

PYTHONPATH=src:. python -m pytest -q tests_gen/test_syn_v2.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
from datamate.rules import load_train_units
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT), str(ROOT / 'scripts')]

from gen import oracle, periods, rulebook_gen as RG, variants  # noqa: E402
from gen.questions import SECTION_ONLY, allowed, sample  # noqa: E402
from gen.sim import make_spec, simulate  # noqa: E402

CAL = ROOT / 'data' / 'train' / 'calendar.csv'


def short_ledger(ind, seed=1, days=75):
    spec = make_spec(ind, np.random.default_rng(seed), f'syn_{ind}')
    spec['end'] = spec['start'] + dt.timedelta(days=days)
    return simulate(spec, seed)


@pytest.fixture(scope='module')
def hotpot():
    return short_ledger('hotpot')


@pytest.fixture(scope='module')
def repair():
    return short_ledger('motorbike_repair', seed=2)


# ---------------------------------------------------------------- rulebooks
def test_train_profile_adds_sections_only():
    c = RG.compose(['hotpot', 'motorbike_repair', 'fruit_shop'], np.random.default_rng(0), 'train')
    base = (ROOT / 'data' / 'train' / 'rulebook.md').read_text(encoding='utf-8')
    assert all(line in c.text for line in base.splitlines())            # nothing of the train rulebook changed
    assert set(c.rules.sections) >= {'tables', 'service', 'vehicles', 'weighed', 'addon'}
    assert c.rules.addon_is_item is False                              # the 'train' profile says: not an item
    ch = RG.changes_of(c.text)
    assert not ch['full'] and not ch['gone']
    assert any('Số khách' in x for x in ch['changes']) and any('Xe quay lại' in x for x in ch['changes'])
    # changed meaning only through the new sections: every other field keeps the train default
    keep = {k for k in ('sections', 'addon_is_item')}
    assert all(getattr(c.rules, f) == getattr(oracle.Rules(), f) for f in vars(c.rules) if f not in keep)


def test_format_paraphrase_makes_no_fake_changes():
    c = RG.compose(['milk_tea', 'agri_supply'], np.random.default_rng(1), 'mixed', n_variants=2)
    a, b = RG.changes_of(c.text), RG.changes_of(variants.paraphrase_format(c.text))
    assert len(a['changes']) == len(b['changes']) and a['gone'] == b['gone']


@pytest.mark.parametrize('name', RG.STACKABLE)
def test_each_changed_default_is_in_text_and_rules(name):
    c = RG.compose(['grocery'], np.random.default_rng(0), 'mixed', force=[name])
    assert c.parts['variants'] == [name]
    over = RG.EXTRA[name][0] if name in RG.EXTRA else variants.VARIANTS[name][0]
    assert all(getattr(c.rules, k) == v for k, v in over.items())
    assert RG.changes_of(c.text)['changes'], name                     # the agent sees the edit


def test_clashing_defaults_never_stack():
    for seed in range(40):
        c = RG.compose(['grocery', 'cafe'], np.random.default_rng(seed), 'mixed', n_variants=3)
        for clash in RG.CLASH:
            assert len(clash & set(c.parts['variants'])) <= 1


def test_section_alternatives_follow_text():
    for seed in range(30):
        c = RG.compose(['hotpot', 'motorbike_repair', 'agri_supply', 'stationery'], np.random.default_rng(seed), 'mixed')
        alts = c.parts['alts']
        assert ('từ 3 phiếu trở lên' in c.text) == (alts.get('vehicles') == 'repeat3') == (c.rules.repeat_min == 3)
        assert ('tính là **1 khách**' in c.text) == c.rules.guests_missing_as_one
        assert ('**nghìn đồng**' in c.text) == (c.rules.per_guest_round == -3)
        assert ('vẫn là **món**' in c.text) == c.rules.addon_is_item
        keys = {k for k, *_ in c.rules.seasons}
        assert keys == {'dong_xuan', 'he_thu', 'tuu_truong'}
        assert ('15/11 năm Y − 1' in c.text) == (('dong_xuan', 'vụ Đông Xuân', (11, 15), (4, 15)) in c.rules.seasons)


def test_dropped_sections_only_for_absent_trades():
    for seed in range(20):
        c = RG.compose(['pharmacy', 'fashion'], np.random.default_rng(seed), 'reworded')
        assert '### Nhà thuốc' in c.text and 'pharmacy' not in c.parts['dropped']


# ---------------------------------------------------------------- periods
def test_season_and_last_n_rules():
    R = replace(oracle.Rules(), seasons=(('dong_xuan', 'vụ Đông Xuân', (11, 1), (3, 31)),), last_n_include_today=False)
    assert periods.bounds({'kind': 'season', 'name': 'dong_xuan', 'year': 2026}, dt.date(2026, 5, 1), R) == \
        (dt.date(2025, 11, 1), dt.date(2026, 3, 31))
    assert periods.bounds({'kind': 'last_n_days', 'n': 7}, dt.date(2026, 3, 4), R) == \
        (dt.date(2026, 2, 25), dt.date(2026, 3, 3))


# ---------------------------------------------------------------- simulator
def test_weighed_lines_and_addons():
    L = short_ledger('fruit_shop', seed=3)
    dec = L.lines[L.lines.qty % 1 != 0]
    assert len(dec) > 100 and (L.products.set_index('product_id').base_unit[dec.product_id] == 'kg').all()
    gross = (dec.qty * dec.unit_price).map(lambda x: np.floor(x + 0.5))
    assert np.allclose(dec.amount, gross - dec.line_discount)
    M = short_ledger('milk_tea', seed=4)
    kind = M.products.set_index('product_id').kind
    k = M.lines.product_id.map(kind)
    per_order = M.lines.assign(k=k).groupby('order_id').k.agg(set)
    assert any('addon' in s for s in per_order) and all('made' in s for s in per_order if 'addon' in s)


def test_visits(hotpot, repair):
    v = hotpot.visits
    assert set(v.order_id) == set(hotpot.orders.order_id)
    take = v[v.area == 'Mang về']
    assert take.guests.isna().all() and take.table.isna().all() and v.guests.notna().mean() > 0.7
    assert {'tables', 'guests'} <= hotpot.shop['caps'] and 'plates' in repair.shop['caps']
    assert repair.visits.plate.notna().all() and repair.visits.plate.value_counts().max() < 0.05 * len(repair.visits)


# ---------------------------------------------------------------- oracle on the new intents
def test_new_intents_by_hand(hotpot, repair):
    as_of = hotpot.shop['end']
    per = {'kind': 'month', 'y': hotpot.shop['start'].year, 'm': hotpot.shop['start'].month}
    o = hotpot.orders[~hotpot.orders.status.isin(['cancelled', 'returned']) &
                      (pd.to_datetime(hotpot.orders.created).dt.month == per['m'])]
    v = hotpot.visits.set_index('order_id').loc[o.order_id]
    rev = hotpot.lines[hotpot.lines.order_id.isin(o.order_id)].amount.sum()
    R = oracle.Rules(sections=('tables',))
    assert oracle.answer(hotpot, {'intent': 'guests_total', 'period': per}, as_of, R) == ('number', int(v.guests.sum()))
    R1 = replace(R, guests_missing_as_one=True, per_guest_round=-3)
    n1 = v.guests.fillna(1).sum()
    want = int(oracle.half_up(rev / n1 / 1000) * 1000)
    assert oracle.answer(hotpot, {'intent': 'revenue_per_guest', 'period': per}, as_of, R1) == ('number', want)
    t = oracle.answer(hotpot, {'intent': 'top_table', 'period': per}, as_of, R)
    by = hotpot.lines[hotpot.lines.order_id.isin(o.order_id)].groupby('order_id').amount.sum()
    tab = by.groupby(v.table.reindex(by.index)).sum()
    assert t == ('string', tab.sort_values(ascending=False).index[0])
    per2 = {'kind': 'month', 'y': repair.shop['start'].year, 'm': repair.shop['start'].month}
    a2 = oracle.answer(repair, {'intent': 'repeat_vehicles', 'period': per2}, repair.shop['end'], oracle.Rules())
    a3 = oracle.answer(repair, {'intent': 'repeat_vehicles', 'period': per2}, repair.shop['end'],
                       oracle.Rules(repeat_min=3))
    assert a2[1] >= a3[1] >= 0


def test_section_gating():
    R0 = oracle.Rules()
    R1 = oracle.Rules(sections=('tables', 'service', 'size_word'))
    assert not allowed('guests_total', 'hotpot', R0) and allowed('guests_total', 'hotpot', R1)
    assert not allowed('guests_total', 'grocery', R1)
    assert allowed('qty_size', 'cafe', R0) and allowed('qty_size', 'fashion', R1) and not allowed('qty_size', 'fashion', R0)
    assert allowed('revenue', 'fashion', R0)
    assert set(SECTION_ONLY) >= {'service_revenue', 'repeat_vehicles'}


def test_sample_v1_unchanged_intents(hotpot):
    qs = sample(hotpot, np.random.default_rng(0), 30)                 # the syn_v1 path never draws section intents
    assert not {q['spec']['intent'] for q in qs} & (set(SECTION_ONLY) - {'qty_size', 'expiring_items', 'expiring_count',
                                                                         'expiring_value', 'nearest_lot_expiry'})


# ---------------------------------------------------------------- render + build + independent check
def test_visit_columns_read_back(hotpot, tmp_path):
    from datamate.data import load_business
    from gen.render import render
    for fam in ('G', 'A'):
        res = render(hotpot, fam, tmp_path / fam, np.random.default_rng(1))
        b = load_business(tmp_path / fam, CAL, None)
        ex = res['extras']['visits']
        h = ex['cols']['guests']
        t = next(t for t in b.tables.values() if h in t.columns)
        if ex['level'] == 'lines':
            t = t.drop_duplicates(res['extras']['lines']['cols']['order_id'])
        assert pd.to_numeric(t[h], errors='coerce').sum() == hotpot.visits.guests.sum()
        assert {'tables', 'guests'} <= res['caps']


def test_build_v2_split_and_cross_check(tmp_path, monkeypatch):
    from gen import build_v2
    import check_syn
    monkeypatch.setitem(build_v2.SPLITS, 'tiny', ('mixed', ['hotpot', 'motorbike_repair'], 2, 5))
    monkeypatch.setattr(build_v2, 'build_one', build_v2.build_one)
    from gen.build import build
    from gen.rulebook_gen import compose
    comp = compose(['hotpot', 'motorbike_repair'], np.random.default_rng(5), 'mixed', force=['week_sunday'])
    comp.parts['name'] = 'v2_tiny'
    import gen.sim as sim
    orig = sim.make_spec

    def short(*a, **k):
        s = orig(*a, **k)
        s['end'] = s['start'] + dt.timedelta(days=100)
        return s
    monkeypatch.setattr('gen.build.make_spec', short)
    n = build(tmp_path / 'tiny', 2, 40, ['hotpot', 'motorbike_repair'], seed=5, composed=comp, mix='train',
              split_name='tiny', first_id=3001)
    assert n == 80
    meta = [json.loads(l) for l in open(tmp_path / 'tiny' / 'meta.jsonl', encoding='utf-8')]
    assert {m['split'] for m in meta} == {'tiny'} and all(m['business_id'].startswith('syn_30') for m in meta)
    assert (tmp_path / 'tiny' / '_render' / 'syn_3001.json').exists()
    assert not list((tmp_path / 'tiny' / 'data').rglob('_render*'))           # side files outside the agent's view
    rows = check_syn.cross(tmp_path / 'tiny', sample=60)
    assert rows and all(r['status'] == 'ok' for r in rows), [r for r in rows if r['status'] != 'ok'][:3]


def test_one_line_per_product_per_order():
    """Two identical lines of one order read as an export duplicate (rulebook §8): the simulator never writes them."""
    for ind, seed in (('milk_tea', 4), ('hotpot', 5)):
        L = short_ledger(ind, seed=seed, days=40)
        assert not L.lines.duplicated(['order_id', 'product_id']).any()


def test_order_money_written_when_revenue_needs_it(tmp_path):
    """A rulebook that counts the delivery fee / order voucher in revenue needs them in the files of every family."""
    from datamate.data import load_business
    from gen.render import families_for, render
    L = short_ledger('fruit_shop', seed=6, days=40)
    L.orders.loc[L.orders.index[:200:7], 'channel'] = 'phone'           # make sure some orders pay a delivery fee
    for fam in [f for f in families_for(L) if f not in ('B', 'H')]:
        res = render(L, fam, tmp_path / fam, np.random.default_rng(2), order_money=('shipping', 'order_discount'))
        b = load_business(tmp_path / fam, CAL, None)
        assert not b.unreadable
        cols = {k for sh in res['extras']['sheets'] for k in sh['cols']}
        assert {'shipping', 'order_discount'} <= cols, fam


def test_rewrite_profile_lists_its_changed_rules_by_name():
    c = RG.compose(['hotpot', 'spa_salon'], np.random.default_rng(3), 'rewrite', force=['bestseller_revenue'],
                   alts={'tables': 'per_guest_thousand'})
    ch = RG.changes_of(c.text)                     # retyped rules aligned by name: no full text, the edit is listed
    assert not ch['full'] and any('**Bán chạy**' in line and '**doanh thu**' in line for line in ch['changes'])
    from datamate.rules import key
    old = next(l for l in load_train_units().values() if l.startswith('| Bán chạy |'))
    assert key(old) in ch['gone']
    assert c.rules.bestseller_by == 'revenue' and c.rules.per_guest_round == -3
    assert '| Luật | Mặc định |' not in c.text and '**Số khách** — mặc định:' in c.text


def test_pct_one_decimal_leaves_no_two_decimal_line():
    c = RG.compose(['grocery'], np.random.default_rng(0), 'mixed', force=['pct_one_decimal'])
    assert 'phần trăm đúng 2 chữ số' not in c.text


def test_held_out_defaults_not_drawn():
    for seed in range(30):
        c = RG.compose(['hotpot'], np.random.default_rng(seed), 'mixed', n_variants=3,
                       exclude=('bestseller_revenue', 'last_n_before_today'), alts_exclude=('per_guest_thousand',))
        assert not set(c.parts['variants']) & {'bestseller_revenue', 'last_n_before_today'}
        assert c.parts['alts'].get('tables') != 'per_guest_thousand'


def test_train_mix_sampling_rules(hotpot):
    """mix='train': no order-level questions without order ids, no repeated absolute question, few zeros."""
    L = hotpot
    L.shop['caps'] = set(L.shop['caps']) - {'order_ids'}
    try:
        qs = sample(L, np.random.default_rng(1), 60, rules=oracle.Rules(sections=('tables',)), mix='train')
    finally:
        L.shop['caps'] = set(L.shop['caps']) | {'order_ids'}
    from gen.questions import ORDER_INTENTS
    assert not {q['spec']['intent'] for q in qs} & ORDER_INTENTS
    zeros = sum(q['type'] == 'number' and q['answer'] == 0 for q in qs)
    assert zeros <= 2


def test_base_rules_undo_alternatives_and_defaults():
    c = RG.compose(['restaurant', 'motorbike_repair'], np.random.default_rng(0), 'mixed', force=['week_sunday'],
                   alts={'tables': 'guests_one', 'vehicles': 'repeat3'})
    b = RG.base_rules(c.rules, c.parts)
    assert (b.week_start, b.guests_missing_as_one, b.repeat_min) == (0, False, 2)
    assert b.sections == c.rules.sections


def test_rewrite_text_has_no_empty_examples_or_nested_bold():
    c = RG.compose(['hotpot'], np.random.default_rng(1), 'rewrite', force=['bestseller_revenue'])
    assert 'ví dụ đúng ;' not in c.text and 'ví dụ sai \n' not in c.text
    assert '**Hai dòng của **' not in c.text and 'xếp chung theo số đó' not in c.text
