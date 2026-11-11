"""gen.surface: templates cover every intent, noise keeps numbers and names, realize∘noisify round-trips through
gen.parse to the same oracle answer. No model calls.  pytest tests_gen/test_surface.py"""
from __future__ import annotations

import collections
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from gen import surface as SF  # noqa: E402
from gen.oracle import INTENTS  # noqa: E402
from gen.textnorm import detelex_word, fold, norm_question  # noqa: E402


def test_every_intent_has_three_templates():
    counts = SF.template_counts()
    missing = {i: counts.get(i, 0) for i in list(INTENTS) + ['unanswerable'] if counts.get(i, 0) < 3}
    assert not missing, missing


def test_telex_is_undone_by_the_normalizer():
    for w in ['được', 'tháng', 'hàng', 'nào', 'năm', 'lên', 'giảm', 'số', 'của', 'hết', 'tiền', 'đơn', 'tổng']:
        tw = SF.telex(w)
        assert detelex_word(tw) == fold(w), (w, tw)
        assert norm_question(f'doanh thu {tw} 6/2025') == norm_question(f'doanh thu {w} 6/2025')
    assert SF.telex('được') == 'dduwowcj' and SF.telex('tháng') == 'thangs'


def test_noise_keeps_numbers_dates_and_names():
    rng = random.Random(0)
    q = 'Ngày 15/06/2025 cửa hàng bán ⟦Panadol Extra hộp 15 vỉ x 12 viên⟧ giá bao nhiêu một hộp, ngưỡng 1.250.000 đồng?'
    for _ in range(300):
        out = SF.noisify(q, rng, {'telex': 0.5, 'english': 0.5, 'prefix': 0.5})
        assert '15/06/2025' in out and '1.250.000' in out
        assert fold('Panadol Extra hộp 15 vỉ x 12 viên') in fold(out)
        assert '⟦' not in out and '⟧' not in out


def test_round_trip_small():
    from scripts.check_surface import round_trip
    tot, ok = collections.Counter(), collections.Counter()
    bad = []
    for it, good, *_rest in round_trip(['biz_123', 'biz_111'], 400, seed=11):
        tot[it] += 1
        ok[it] += good
        if not good:
            bad.append((it, _rest[3]))
    rate = sum(ok.values()) / sum(tot.values())
    assert rate >= 0.97, (rate, bad[:5])


def test_noise_stats_close_to_train():
    rng = random.Random(3)
    from scripts.check_surface import load
    L = load('biz_111')
    import datetime as dt
    ctx = SF.make_ctx(L, None, L.shop['end'])
    qs = []
    for i in range(1500):
        it = SF.ALL_INTENTS[i % len(SF.ALL_INTENTS)]
        spec = SF.sample_spec(L, L.shop['end'], rng, it)
        if spec is None:
            continue
        try:
            qs.append(SF.noisify(SF.realize(spec, ctx, rng, marked=True), rng))
        except ValueError:
            pass
    st = SF.noise_stats(qs)
    assert 0.45 < st['lowercase start'] < 0.6
    assert 0.2 < st['no accents'] < 0.33
    assert 0.4 < st['ends with ?/.'] < 0.56
    assert 0.04 < st['telex typo'] < 0.12
    assert all(not re.search(r'[⟦⟧{}\[\]]', q) for q in qs)
