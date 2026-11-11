"""Mix SFT sample files (gen.sft output) into one training set and its held-out eval set.

- caps samples per (intent) so frequent intents (monthly revenue) do not dominate;
- keeps at most `--per-question` samples per question id (the final turn first);
- holds out whole shops (--holdout-shops) and/or whole industries/families (from a split's meta.jsonl);
- writes chat-format lines: {"messages": [system, user, (assistant/user history...), {"role": "assistant", ...}]}.

python -m gen.mix --in a.jsonl b.jsonl --meta data/syn_v1/meta.jsonl --cap 400 --holdout-industries restaurant \
    --out train.jsonl --eval-out eval.jsonl
"""
from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path


def _jsonl(p):
    return [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]


def chat(sample):
    return {'messages': list(sample['messages']) + [{'role': 'assistant', 'content': sample['completion']}],
            'id': sample['id'], 'turn': sample['turn'], 'business_id': sample['business_id']}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='inputs', nargs='+', required=True)
    ap.add_argument('--meta', nargs='*', default=[], help='meta.jsonl of synthetic splits (intent, industry, family)')
    ap.add_argument('--train-gold-intents', default='', help='optional jsonl {id, intent} for train questions')
    ap.add_argument('--cap', type=int, default=400, help='max samples per intent')
    ap.add_argument('--per-question', type=int, default=2)
    ap.add_argument('--holdout-shops', default='')
    ap.add_argument('--holdout-industries', default='')
    ap.add_argument('--holdout-families', default='')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--out', required=True)
    ap.add_argument('--eval-out', required=True)
    a = ap.parse_args()
    meta = {}
    for m in a.meta:
        for r in _jsonl(m):
            meta[r['id']] = r
    if a.train_gold_intents:
        for r in _jsonl(a.train_gold_intents):
            meta.setdefault(r['id'], r)
    hs = set(filter(None, a.holdout_shops.split(',')))
    hi = set(filter(None, a.holdout_industries.split(',')))
    hf = set(filter(None, a.holdout_families.split(',')))
    rnd = random.Random(a.seed)
    samples = [s for p in a.inputs for s in _jsonl(p)]
    rnd.shuffle(samples)
    samples.sort(key=lambda s: not s['meta'].get('final', True))           # final turns first (stable)
    per_q, per_intent = collections.Counter(), collections.Counter()
    train, held = [], []
    for s in samples:
        m = meta.get(s['id'], {})
        out = held if (s['business_id'] in hs or m.get('industry') in hi or m.get('family') in hf) else train
        if per_q[s['id']] >= a.per_question:
            continue
        intent = m.get('intent', 'unknown')
        if out is train and per_intent[intent] >= a.cap:
            continue
        per_q[s['id']] += 1
        if out is train:
            per_intent[intent] += 1
        out.append(chat(s))
    for path, rows in ((a.out, train), (a.eval_out, held)):
        with open(path, 'w', encoding='utf-8') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f'train {len(train)}  held-out {len(held)}')
    for k, v in per_intent.most_common():
        print(f'  {k:28s} {v}')


if __name__ == '__main__':
    main()
