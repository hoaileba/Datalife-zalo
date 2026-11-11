"""Oracle vs train gold on the train shops whose files are (nearly) the raw ledger: parse each question, compute the
oracle answer, score with datamate.eval.correct. No model calls.

python scripts/calibrate_oracle.py [--shops biz_123,biz_111] [--show intent] [--miss]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from datamate.eval import correct  # noqa: E402
from gen import ledger as LG  # noqa: E402
from gen.oracle import Rules, View, answer  # noqa: E402
from gen.parse import Names, parse  # noqa: E402

TRAIN = ROOT / 'data' / 'train'
INDUSTRY = {'biz_111': 'cafe', 'biz_127': 'restaurant', 'biz_129': 'restaurant', 'biz_106': 'cafe', 'biz_108': 'grocery'}
KIOTVIET = {'biz_106', 'biz_108'}
CACHE = ROOT.parent / 'datamate_v4' / 'outputs' / 'cache'


def load(b):
    d = TRAIN / 'data' / b
    if (d / 'pos.sqlite').exists():
        return LG.load_sqlite_pos(d)
    if b in KIOTVIET:
        return LG.load_kiotviet(d, INDUSTRY[b], CACHE if CACHE.exists() else None)
    return LG.load_normalized_csv(d, LG.G_COLUMNS[b], INDUSTRY[b])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shops', default='biz_123,biz_111,biz_127,biz_129,biz_106')
    ap.add_argument('--show', default='')
    ap.add_argument('--miss', action='store_true', help='print every wrong / unparsed question')
    args = ap.parse_args()
    Q = [json.loads(l) for l in open(TRAIN / 'questions.jsonl', encoding='utf-8')]
    A = {a['id']: a for a in map(json.loads, open(TRAIN / 'answers.jsonl', encoding='utf-8'))}
    stats = collections.defaultdict(collections.Counter)
    total = collections.Counter()
    for b in args.shops.split(','):
        L = load(b)
        names = Names(L)
        views = {}
        for q in (q for q in Q if q['business_id'] == b):
            as_of = dt.date.fromisoformat(q['as_of_date'])
            g = A[q['id']]
            try:
                spec = parse(q['question'], as_of, L, names)
            except Exception as e:  # noqa: BLE001
                spec = None
                print('PARSE ERROR', q['question'], e)
            if spec is None:
                stats['UNPARSED'][g['type']] += 1
                total['unparsed'] += 1
                if args.miss:
                    print(f"  ?? {b} {q['as_of_date']} | {q['question']} => {g['type']} {json.dumps(g.get('answer'), ensure_ascii=False)[:80]}")
                continue
            if spec.get('period') is None and 'period' in spec:
                spec = {**spec, 'period': {'kind': 'today'}}
            V = views.get(as_of) or views.setdefault(as_of, View(L, as_of, Rules()))
            try:
                t, v = answer(L, spec, as_of, view=V)
            except Exception as e:  # noqa: BLE001
                t, v = 'error', repr(e)[:80]
            ok = correct({'type': t, 'answer': v}, g)
            stats[spec['intent']]['ok' if ok else 'bad'] += 1
            total['ok' if ok else 'bad'] += 1
            if (not ok and args.miss) or spec['intent'] == args.show:
                print(f"  {'OK' if ok else 'XX'} {b} {q['as_of_date']} [{spec['intent']}] {q['question']}\n"
                      f"      spec={ {k: v2 for k, v2 in spec.items() if k != 'intent'} }\n"
                      f"      got={t} {json.dumps(v, ensure_ascii=False, default=str)[:120]}  gold={g['type']} "
                      f"{json.dumps(g.get('answer'), ensure_ascii=False)[:120]}")
    for k, c in sorted(stats.items(), key=lambda kv: -sum(kv[1].values())):
        print(f'{k:28s} {dict(c)}')
    n = sum(total.values())
    print(f"TOTAL {n}: ok {total['ok']} bad {total['bad']} unparsed {total['unparsed']} "
          f"(ok of parsed {total['ok'] / max(1, total['ok'] + total['bad']):.1%})")


if __name__ == '__main__':
    main()
