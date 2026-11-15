"""Part A of the final SFT data (outputs/tmp/PLAN_FINAL_DATA.md): train questions for the teacher, no model calls.

27 train shops (the held-out val shops biz_108/110/130 never), at most PER_SHOP questions per shop, intents
interleaved round robin inside each shop (scripts/train_intents.py buckets) so every shop gives its spread of
question kinds; seeded. Writes the full id list and the first-batch list (a slice spread over all shops).

python scripts/select_train_a.py --n 900 --first 35 --out data_gen/final_ids
  -> data_gen/final_ids/A_all.txt (900 ids, batch order) and A_first.txt (the first 35 of that order)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAL_SHOPS = ('biz_108', 'biz_110', 'biz_130')        # gen.package.DEFAULT_VAL_SHOPS


def intents():
    spec = importlib.util.spec_from_file_location('train_intents', ROOT / 'scripts' / 'train_intents.py')
    mod = importlib.util.module_from_spec(spec)
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(mod)
    return {q['id']: mod.intent(q['question'], mod.A.get(q['id'])) for q in mod.Q}, mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=900)
    ap.add_argument('--first', type=int, default=35)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--out', default=str(ROOT / 'data_gen' / 'final_ids'))
    a = ap.parse_args()
    qs = [json.loads(l) for l in open(ROOT / 'data' / 'train' / 'questions.jsonl', encoding='utf-8')]
    lab, _ = intents()
    rng = random.Random(a.seed)
    shops = defaultdict(lambda: defaultdict(list))
    for q in qs:
        if q['business_id'] in VAL_SHOPS:
            continue
        shops[q['business_id']][lab.get(q['id']) or 'other'].append(q['id'])
    per_shop = -(-a.n // len(shops))
    order = {}
    for b, by_int in sorted(shops.items()):
        lists = [rng.sample(v, len(v)) for _, v in sorted(by_int.items())]
        rng.shuffle(lists)
        picked = []
        while len(picked) < per_shop and any(lists):
            for lst in lists:
                if lst and len(picked) < per_shop:
                    picked.append(lst.pop())
        order[b] = picked
    # batch order: round robin over shops, so any prefix spreads over all shops
    seq, k = [], 0
    while len(seq) < a.n and any(k < len(v) for v in order.values()):
        for b in sorted(order):
            if k < len(order[b]) and len(seq) < a.n:
                seq.append(order[b][k])
        k += 1
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'A_all.txt').write_text('\n'.join(seq) + '\n', encoding='utf-8')
    (out / 'A_first.txt').write_text('\n'.join(seq[:a.first]) + '\n', encoding='utf-8')
    print(f'{len(seq)} ids over {len(order)} shops (<= {per_shop} each), first {a.first} -> {out}')


if __name__ == '__main__':
    main()
