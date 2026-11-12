"""Oracle vs train gold (calibration) and simulator invariants. No model calls.

PYTHONPATH=src:. python -m pytest -q tests_gen
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from gen import oracle, periods  # noqa: E402
from gen.questions import sample  # noqa: E402
from gen.sim import make_spec, simulate  # noqa: E402
from gen.variants import VARIANTS, rules_of  # noqa: E402


def test_calibration_matches_train_gold():
    out = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'calibrate_oracle.py')], capture_output=True,
                         text=True, cwd=ROOT, env={'PYTHONIOENCODING': 'utf-8', 'PATH': '/usr/bin:/bin'})
    last = out.stdout.strip().splitlines()[-1]
    assert 'bad 0 unparsed 0' in last, out.stdout[-3000:] + out.stderr[-2000:]


def test_periods_rules():
    R = oracle.Rules()
    as_of = dt.date(2026, 3, 4)                                  # a Wednesday
    assert periods.bounds({'kind': 'last_week'}, as_of, R) == (dt.date(2026, 2, 23), dt.date(2026, 3, 1))
    assert periods.bounds({'kind': 'this_week'}, as_of, R) == (dt.date(2026, 3, 2), as_of)
    assert periods.bounds({'kind': 'last_n_days', 'n': 7}, as_of, R) == (dt.date(2026, 2, 26), as_of)
    p = periods.previous({'kind': 'this_month'}, dt.date(2026, 3, 31), R)
    assert (p['start'], p['end']) == (dt.date(2026, 2, 1), dt.date(2026, 2, 28))
    s, e = periods.bounds({'kind': 'tet', 'year': 2026}, as_of, R)
    assert s < dt.date(2026, 2, 17) < e                          # Tết Bính Ngọ: 17/02/2026
    R2 = rules_of('week_sunday')
    assert periods.bounds({'kind': 'last_week'}, as_of, R2) == (dt.date(2026, 2, 22), dt.date(2026, 2, 28))


def test_half_up():
    assert oracle.half_up(2.5) == 3 and oracle.half_up(12.345, 2) == 12.35 and oracle.half_up(-1.005, 2) == -1.01


@pytest.fixture(scope='module')
def shop():
    spec = make_spec('restaurant', np.random.default_rng(3), 'syn_t')
    spec['end'] = spec['start'] + dt.timedelta(days=200)          # small and fast
    return simulate(spec, 3)


def test_sim_invariants(shop):
    L = shop
    l = L.lines
    assert np.allclose(l.amount, l.qty * l.unit_price - l.line_discount)
    o = L.orders.set_index('order_id')
    sub = l.groupby('order_id').amount.sum()
    assert np.allclose(o.subtotal.reindex(sub.index), sub)
    assert np.allclose(o.total, o.subtotal - o.discount + o.shipping)
    assert ((o.shipping > 0) == (o.channel != 'store')).all()
    paid = L.payments.groupby('order_id').amount.sum()
    assert (paid <= o.total.reindex(paid.index) + 0.5).all()
    assert (L.stock_moves.balance >= -1e-9).all()
    fee = L.products[L.products.kind == 'fee'].product_id
    if len(fee):
        fl = l[l.product_id.isin(fee)].set_index('order_id').amount
        dishes = l[~l.product_id.isin(fee)].groupby('order_id').amount.sum()
        assert np.allclose(fl, (dishes.reindex(fl.index) * 0.05).round())


def test_questions_have_answers(shop):
    qs = sample(shop, np.random.default_rng(0), 60)
    assert len(qs) >= 50
    assert all(q['type'] == 'unanswerable' or q['answer'] is not None for q in qs)


def test_every_variant_changes_some_answer(shop):
    qs = sample(shop, np.random.default_rng(1), 150)
    changed = set()
    for v in VARIANTS:
        R = rules_of(v)
        for q in qs:
            if oracle.answer(shop, q['spec'], q['as_of'], R) != (q['type'], q['answer']):
                changed.add(v)
                break
    assert len(changed) >= 6, changed


# ---------------------------------------------------------------- the question's words and the rulebook
def test_question_words_fix_the_comparison_window(shop):
    """'cùng kỳ / cùng số ngày của tháng trước' wins over a rulebook that compares 'tháng này' with the whole previous
    month (rulebook intro: the question wins when it says otherwise); plain 'tháng trước' follows the rulebook."""
    from gen.parse import Names, parse
    from gen.questions import Sampler
    import random
    from gen import surface as S
    full = rules_of('this_month_full_prev')
    as_of = shop.shop['end'] - dt.timedelta(days=12)
    as_of = as_of.replace(day=min(as_of.day, 20))
    base = {'intent': 'revenue_change_pct', 'period': {'kind': 'this_month'}}
    default = oracle.answer(shop, base, as_of)
    assert oracle.answer(shop, {**base, 'ref_text': 'same_days'}, as_of, full) == default
    assert oracle.answer(shop, base, as_of, full) != default
    assert oracle.answer(shop, {**base, 'ref_text': 'full'}, as_of) == oracle.answer(shop, base, as_of, full)
    names = Names(shop)
    for text, want in (('Doanh thu tháng này thay đổi bao nhiêu % so với cùng kỳ tháng trước', 'same_days'),
                       ('dthu thang nay so voi cung so ngay cua th truoc tang hay giam may %', 'same_days'),
                       ('Doanh thu tháng này thay đổi bao nhiêu % so với cả tháng trước', 'full'),
                       ('Doanh thu tháng này thay đổi bao nhiêu % so với tháng trước', None)):
        assert parse(text, as_of, shop, names).get('ref_text') == want, text
    tet = parse('Dịp Tết 2026 có doanh thu hơn hay kém 17 ngày trước Tết bao nhiêu %?', as_of, shop, names)
    assert tet['ref'] == {'kind': 'before_tet', 'days': 17}
    s, _ = periods.bounds({'kind': 'tet', 'year': 2026}, as_of, oracle.Rules())
    r = periods.before_tet({'kind': 'tet', 'year': 2026}, as_of, rules_of('tet_short'), days=17)
    assert (r['start'], r['end']) == (s - dt.timedelta(days=17), s - dt.timedelta(days=1))
    # the generator writes neutral words when the rulebook's window is not the train one, explicit ones otherwise
    for rules, want in ((full, 'neutral'), (oracle.Rules(), 'same_days')):
        smp = Sampler(shop, np.random.default_rng(0), rules)
        spec = next(sp for sp in (smp.spec('revenue_change_pct', as_of) for _ in range(300))
                    if sp['period']['kind'] == 'this_month')
        assert spec['ref_text'] == want
        for seed in range(10):
            text = S.realize(spec, S.make_ctx(shop, spec, as_of), random.Random(seed))
            assert ('cùng' in text) == (want == 'same_days'), text


def test_undetermined_questions():
    R = oracle.Rules()
    vou, ret, dlv = rules_of('revenue_voucher'), rules_of('returns_count'), rules_of('delivering_out')
    for it in ('group_share', 'revenue_item', 'rx_share', 'service_share'):
        assert oracle.undetermined({'intent': it}, vou) and not oracle.undetermined({'intent': it}, R)
    assert oracle.undetermined({'intent': 'top_items', 'by': 'revenue'}, vou)
    assert not oracle.undetermined({'intent': 'top_items'}, vou) and not oracle.undetermined({'intent': 'revenue'}, vou)
    for rules in (ret, dlv):
        assert oracle.undetermined({'intent': 'top_items'}, rules) and not oracle.undetermined({'intent': 'revenue'}, rules)
    assert not oracle.undetermined({'intent': 'group_share'}, rules_of('revenue_shipping'))


def test_gross_profit_uses_the_revenue_of_the_rulebook(shop):
    per = {'kind': 'month', 'y': shop.shop['start'].year, 'm': shop.shop['start'].month + 1}
    as_of = shop.shop['end']
    spec = {'intent': 'gross_profit', 'period': per}
    ship, R = rules_of('revenue_shipping'), oracle.Rules()
    rev = {r: oracle.answer(shop, {'intent': 'revenue', 'period': per}, as_of, r)[1] for r in (R, ship)}
    assert rev[ship] > rev[R]                                      # the month has delivery fees
    assert oracle.answer(shop, spec, as_of, ship)[1] - oracle.answer(shop, spec, as_of, R)[1] == rev[ship] - rev[R]


def test_price_on_a_day_of_two_prices_per_base_unit_is_not_asked():
    """§5 Giá bán: the price written on the day's lines per base unit. A big unit priced below n x base the same day
    gives two answers: undetermined. A day with one price per base unit stays (its answer: that price x the factor)."""
    L = simulate(make_spec('pet_shop', np.random.default_rng(5), 'syn_p'), 5)
    big = L.units[L.units.factor > 1]
    day = L.orders.set_index('order_id').created.dt.normalize()
    l = L.lines[L.lines.product_id.isin(big.product_id)].assign(day=lambda x: x.order_id.map(day))
    f = l.apply(lambda r: oracle._unit_factor(L, r.product_id, r.unit), axis=1)
    l = l.assign(pb=(l.unit_price / f).round(6))
    g = l.groupby(['product_id', 'day']).agg(units=('unit', 'nunique'), prices=('pb', 'nunique'))
    two = g[(g.units > 1) & (g.prices > 1)].index
    one = g[(g.units == 1) & (g.prices == 1)].index
    assert len(two) and len(one)
    R = oracle.Rules()
    pid, d = two[0]
    unit = big[big.product_id == pid].unit.iloc[0]
    assert oracle.undetermined({'intent': 'price_on_day', 'item': pid, 'date': d.date(), 'unit': unit}, R, L)
    pid, d = one[0]
    spec = {'intent': 'price_on_day', 'item': pid, 'date': d.date()}
    assert not oracle.undetermined(spec, R, L)
    assert oracle.answer(L, spec, L.shop['end'])[1] == l[(l.product_id == pid) & (l.day == d)].pb.iloc[0]


def test_event_word_units_are_named_as_units():
    import random
    from gen import surface as S
    ctx = S.Ctx(as_of=dt.date(2026, 3, 4))
    for seed in range(20):
        text = S.realize({'intent': 'qty_unit', 'unit': 'lần', 'period': {'kind': 'month', 'y': 2026, 'm': 2}}, ctx,
                         random.Random(seed))
        assert 'tính theo lần' in text, text
