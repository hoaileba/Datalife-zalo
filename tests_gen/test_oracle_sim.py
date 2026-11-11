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
