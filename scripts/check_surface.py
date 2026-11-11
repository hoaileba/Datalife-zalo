"""Round trip of gen.surface: random spec -> realize -> noisify -> gen.parse.parse -> same oracle answer. No model calls.

python scripts/check_surface.py [--n 2400] [--shops biz_123,biz_111,biz_127,biz_129] [--seed 0] [--fails 3] [--stats]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from datamate.eval import correct  # noqa: E402
from gen import surface as SF  # noqa: E402
from gen.oracle import Rules, View, answer  # noqa: E402
from gen.parse import Names, parse  # noqa: E402
from scripts.calibrate_oracle import load  # noqa: E402

ORACLE_ERRORS = collections.Counter()
DEFAULT_SHOPS = 'biz_123,biz_111,biz_127,biz_129,biz_106'


def as_of_dates(L, rng, k=6):
    start, end = L.shop['start'], L.shop['end']
    lo = start + dt.timedelta(days=150)
    out = [end]
    for _ in range(k - 1):
        out.append(lo + dt.timedelta(days=rng.randrange(max(1, (end - lo).days))))
    return out


def same_answer(a, b):
    if a[0] != b[0]:
        return False
    return correct({'type': a[0], 'answer': a[1]}, {'type': b[0], 'answer': b[1], 'alias': []})


def round_trip(shops, n, seed=0, noise=True, rates=None):
    """Yields (intent, ok, intent_ok, informative, text, spec, parsed, a0, a1)."""
    rng = random.Random(seed)
    per_shop = max(1, n // len(shops))
    for b in shops:
        L = load(b)
        names = Names(L)
        dates = as_of_dates(L, rng)
        views = {d: View(L, d, Rules()) for d in dates}
        ctxs = {d: SF.make_ctx(L, None, d) for d in dates}
        intents = [i for i in SF.ALL_INTENTS]
        made = 0
        tries = 0
        while made < per_shop and tries < per_shop * 5:
            tries += 1
            it = intents[made % len(intents)] if rng.random() < 0.7 else rng.choice(intents)
            d = rng.choice(dates)
            try:
                spec = SF.sample_spec(L, d, rng, it)
            except (IndexError, ValueError):
                spec = None
            if spec is None:
                continue
            try:
                q = SF.realize(spec, ctxs[d], rng, marked=True)
            except ValueError:
                continue
            text = SF.noisify(q, rng, rates) if noise else SF.unmark(q)
            try:
                a0 = answer(L, spec, d, view=views[d])
            except Exception as e:  # noqa: BLE001  (oracle errors are the oracle's: reported, not counted)
                ORACLE_ERRORS[spec['intent']] += 1
                continue
            made += 1
            try:
                ps = parse(text, d, L, names)
            except Exception as e:  # noqa: BLE001
                ps = {'intent': f'ERROR {e!r}'[:60]}
            if ps is not None and 'period' in ps and ps.get('period') is None:
                ps = {**ps, 'period': {'kind': 'today'}}
            try:
                a1 = answer(L, ps, d, view=views[d]) if ps and not ps['intent'].startswith('ERROR') else ('none', None)
            except Exception as e:  # noqa: BLE001
                a1 = ('error', repr(e)[:60])
            yield (spec['intent'], same_answer(a0, a1), bool(ps) and ps['intent'] == spec['intent'],
                   a0[0] != 'unanswerable' or spec['intent'] == 'unanswerable', text, spec, ps, a0, a1, b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=2400)
    ap.add_argument('--shops', default=DEFAULT_SHOPS)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--fails', type=int, default=3, help='failures printed per intent')
    ap.add_argument('--clean', action='store_true', help='no noise layers')
    ap.add_argument('--stats', action='store_true', help='noise statistics of 3000 generated questions vs train')
    args = ap.parse_args()
    shops = args.shops.split(',')
    if args.stats:
        return stats(shops, args.seed)
    tot = collections.defaultdict(collections.Counter)
    shown = collections.Counter()
    for it, ok, iok, inf, text, spec, ps, a0, a1, b in round_trip(shops, args.n, args.seed, not args.clean):
        c = tot[it]
        c['n'] += 1
        c['ok'] += ok
        c['intent'] += iok
        c['inf'] += inf
        c['inf_ok'] += ok and inf
        if not ok and shown[it] < args.fails:
            shown[it] += 1
            print(f'XX [{it}] {b} {text}\n    spec={_short(spec)}\n    parsed={_short(ps)}\n    {a0} vs {a1}')
    print(f"\n{'intent':28s} {'n':>5s} {'answer':>7s} {'intent':>7s} {'informative ok':>15s}")
    T = collections.Counter()
    for it in sorted(tot):
        c = tot[it]
        T.update(c)
        print(f"{it:28s} {c['n']:5d} {c['ok'] / c['n']:7.1%} {c['intent'] / c['n']:7.1%} "
              f"{c['inf_ok']:6d}/{c['inf']:<6d}")
    print(f"{'TOTAL':28s} {T['n']:5d} {T['ok'] / T['n']:7.1%} {T['intent'] / T['n']:7.1%} "
          f"{T['inf_ok']:6d}/{T['inf']:<6d} ({T['inf_ok'] / max(1, T['inf']):.1%} of informative)")
    if ORACLE_ERRORS:
        print('oracle raised on (skipped):', dict(ORACLE_ERRORS))


def _short(s):
    return json.dumps(s, ensure_ascii=False, default=str)[:220] if s is not None else None


def stats(shops, seed):
    rng = random.Random(seed)
    train = [json.loads(l)['question'] for l in open(ROOT / 'data' / 'train' / 'questions.jsonl', encoding='utf-8')]
    gen = [t for _, _, _, _, t, *_ in round_trip(shops, 3000, seed)]
    a, g = SF.noise_stats(train), SF.noise_stats(gen)
    print(f"{'statistic':28s} {'train':>7s} {'generated':>10s}   (train n={len(train)}, generated n={len(gen)})")
    for k in a:
        print(f'{k:28s} {a[k]:7.1%} {g[k]:10.1%}')
    print('\nexamples:')
    for t in rng.sample(gen, 25):
        print('  ', t)


if __name__ == '__main__':
    main()
