"""S2a: train questions written another way, same data and gold answers (no model calls).

- every shop: questions written formally (capital first letter, ending with ?/.) get the noise layers
  (gen.surface.noisify), so the same gold answer is asked in the noisy style; already-noisy ones are left out
  (stacking noise would leave the train distribution);
- shops whose ledger is calibrated (oracle == gold on all their questions: biz_123/111/127/129/106): parse ->
  realize with another template + noise; kept only when the oracle answer of the parsed spec equals the gold.

Output: a split folder with data/ and calendar.csv linked to train, rulebook copied, new question ids
(q_aug<k>_<orig id>), answers copied from train.

python -m gen.augment_train --out data_gen/train_aug --copies 2 --seed 0
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from datamate.eval import correct  # noqa: E402
from gen import surface as S  # noqa: E402
from gen.oracle import Rules, View, answer  # noqa: E402
from gen.parse import Names, parse  # noqa: E402

TRAIN = ROOT / 'data' / 'train'
CALIBRATED = ['biz_123', 'biz_111', 'biz_127', 'biz_129', 'biz_106']


def _formal(q):
    q = q.strip()
    return q[:1].isupper() and q[-1:] in '?.'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--copies', type=int, default=2)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    os.symlink((TRAIN / 'data').resolve(), out / 'data')
    os.symlink((TRAIN / 'calendar.csv').resolve(), out / 'calendar.csv')
    shutil.copy(TRAIN / 'rulebook.md', out / 'rulebook.md')
    Q = [json.loads(l) for l in open(TRAIN / 'questions.jsonl', encoding='utf-8')]
    A = {x['id']: x for x in map(json.loads, open(TRAIN / 'answers.jsonl', encoding='utf-8'))}
    rnd = random.Random(a.seed)
    sys.path.insert(0, str(ROOT / 'scripts'))
    from calibrate_oracle import load
    ledgers = {}
    fq, fa = open(out / 'questions.jsonl', 'w', encoding='utf-8'), open(out / 'answers.jsonl', 'w', encoding='utf-8')
    n_noise = n_real = 0
    for q in Q:
        b, g = q['business_id'], A[q['id']]
        texts = []
        if _formal(q['question']):
            texts += [S.noisify(q['question'], rnd) for _ in range(a.copies)]
            n_noise += len(texts)
        if b in CALIBRATED:
            if b not in ledgers:
                L = load(b)
                ledgers[b] = (L, Names(L), {})
            L, names, views = ledgers[b]
            as_of = dt.date.fromisoformat(q['as_of_date'])
            spec = parse(q['question'], as_of, L, names)
            if spec is not None and spec['intent'] != 'unanswerable':
                V = views.get(as_of) or views.setdefault(as_of, View(L, as_of, Rules()))
                for _ in range(a.copies):
                    try:
                        text = S.noisify(S.realize(spec, S.make_ctx(L, spec, as_of), rnd), rnd)
                        s2 = parse(text, as_of, L, names)
                        t, v = answer(L, s2, as_of, view=V) if s2 else (None, None)
                    except Exception:  # noqa: BLE001
                        continue
                    if correct({'type': t, 'answer': v}, g):
                        texts.append(text)
                        n_real += 1
        for k, text in enumerate(dict.fromkeys(t for t in texts if t != q['question'])):
            qid = f'q_aug{k}_{q["id"][2:]}'
            fq.write(json.dumps({**q, 'id': qid, 'question': text}, ensure_ascii=False) + '\n')
            fa.write(json.dumps({**g, 'id': qid}, ensure_ascii=False) + '\n')
    fq.close()
    fa.close()
    print(f'noisy copies {n_noise}, re-phrased (oracle-checked) {n_real} -> {out}')


if __name__ == '__main__':
    main()
