"""Build a synthetic split in the train package layout:

  <out>/data/<business_id>/{files..., README.md}  rulebook.md  calendar.csv  questions.jsonl  answers.jsonl
  <out>/meta.jsonl   one line per question: spec, intent, family, industry, variant (for analysis; not read by the agent)

python -m gen.build --out data/syn_v1 --shops 20 --questions 100 [--industries grocery,cafe,...] [--variant week_sunday]
       [--seed 0]

Answers come from the oracle on the clean ledger; alias = every spelling of the answer's name found in the rendered
files (read back with the production reader) plus its code, as in the train answers.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from gen import variants  # noqa: E402
from gen.oracle import Rules, answer  # noqa: E402
from gen.questions import sample  # noqa: E402
from gen.sim import TRAIN_META, make_spec, simulate  # noqa: E402

TRAIN = ROOT / 'data' / 'train'
NEW_INDUSTRIES = ['cosmetics', 'mother_baby', 'stationery', 'bakery', 'motorbike_repair', 'pet_shop', 'agri_supply']
ALL_INDUSTRIES = list(TRAIN_META) + NEW_INDUSTRIES


def _fold(s):
    from datamate.values import fold
    return fold(s)


def _text_values(business):
    """Distinct text cells of every table of the rendered shop, by folded form."""
    out = {}
    for name, df in business.tables.items():
        if name == 'calendar':
            continue
        for c in df.columns:
            if c.endswith('__raw') or c.startswith('__') or df[c].dtype != object:
                continue
            for v in df[c].dropna().unique()[:50000]:
                if isinstance(v, str) and 2 <= len(v) <= 120:
                    out.setdefault(_fold(re.sub(r'[\s\-–()]*\(?0\d[\d\s.]{8,}\)?\s*$', '', v)), set()).add(v)
    return out


def _alias(name, code, values):
    al = set(values.get(_fold(name), set())) - {name}
    if code:
        al.add(code)
    return sorted(al)


def _codes(L):
    m = {}
    for t, idc, namec in (('products', 'product_id', 'name'), ('customers', 'customer_id', 'name'),
                          ('suppliers', 'supplier_id', 'name'), ('staff', 'staff_id', 'name')):
        df = getattr(L, t)
        if len(df):
            m.update(dict(zip(df[namec], df[idc])))
    return m


def answer_alias(kind, ans, codes, values, caps):
    def one(n):
        code = codes.get(n) if ('product_ids' in caps or not str(codes.get(n, '')).startswith('SP')) else None
        return _alias(n, code, values)
    if kind == 'string':
        return one(ans)
    if kind == 'list' and ans and all(isinstance(x, str) for x in ans):
        return [one(x) for x in ans]
    if kind == 'table':
        return [one(r[0]) for r in ans['rows']]
    return []


def variant_questions(L, rng, n, variant, rules, keep_unaffected=0.3):
    """S4: questions of a rulebook variant, mostly ones whose answer the changed rule moves (the point of the
    sample), plus some it does not move (the model must not over-apply a change)."""
    from gen.questions import WEIGHTS
    focus = (variants.VARIANTS[variant][2] or {}).get('*', [])
    w = dict(WEIGHTS)
    for k in focus:
        if k in w:
            w[k] *= 15
    out, tries = [], 0
    while len(out) < n and tries < 6:
        tries += 1
        for q in sample(L, rng, n * 2, rules=rules, weights=w):
            base = answer(L, q['spec'], q['as_of'], Rules())
            moved = base != (q['type'], q['answer'])
            if moved or rng.random() < keep_unaffected:
                out.append({**q, 'moved': moved})
            if len(out) >= n:
                break
    return out


def build(out: Path, n_shops: int, n_questions: int, industries, seed=0, variant=None, families=None,
          first_id=901):
    from datamate.data import load_business
    from gen import render as R
    from gen import surface as S
    rng = np.random.default_rng(seed)
    if out.exists():
        shutil.rmtree(out)
    (out / 'data').mkdir(parents=True)
    shutil.copy(TRAIN / 'calendar.csv', out / 'calendar.csv')
    rules = Rules()
    rb = (TRAIN / 'rulebook.md').read_text(encoding='utf-8')
    if variant:
        rules = variants.rules_of(variant)
        rb = variants.rulebook_text(variant)
    (out / 'rulebook.md').write_text(rb, encoding='utf-8')
    fq, fa, fm = (open(out / f, 'w', encoding='utf-8') for f in ('questions.jsonl', 'answers.jsonl', 'meta.jsonl'))
    qn = 0
    for i in range(n_shops):
        ind = industries[i % len(industries)]
        bid = f'syn_{first_id + i}'
        spec = make_spec(ind, rng, bid)
        L = simulate(spec, int(rng.integers(1 << 30)))
        fams = [f for f in R.families_for(L) if families is None or f in families]
        fam = fams[int(rng.integers(len(fams)))]
        shop_dir = out / 'data' / bid
        rendered = R.render(L, fam, shop_dir, rng)
        L.shop['caps'] = set(rendered['caps'])
        business = load_business(shop_dir, out / 'calendar.csv', None)
        values = _text_values(business)
        codes = _codes(L)
        if variant:
            qs = variant_questions(L, rng, n_questions, variant, rules)
        else:
            qs = sample(L, rng, n_questions, rules=rules)
        for q in qs:                      # sampled after rendering: the rendered caps decide unanswerable
            t, a = q['type'], q['answer']
            qn += 1
            qid = f'q_syn{seed:02d}_{qn:06d}'
            ctx = S.make_ctx(L, q['spec'], q['as_of'])
            prng = random.Random(int(rng.integers(1 << 62)))       # surface.py uses random.Random
            text = S.noisify(S.realize(q['spec'], ctx, prng), prng)
            fq.write(json.dumps({'id': qid, 'business_id': bid, 'question': text,
                                 'as_of_date': q['as_of'].isoformat()}, ensure_ascii=False) + '\n')
            line = {'id': qid, 'type': t, 'answer': a, 'alias': answer_alias(t, a, codes, values, L.shop['caps'])}
            fa.write(json.dumps(line, ensure_ascii=False) + '\n')
            fm.write(json.dumps({'id': qid, 'intent': q['spec']['intent'], 'family': fam, 'industry': ind,
                                 'variant': variant, 'moved': q.get('moved'), 'spec': q['spec']},
                                ensure_ascii=False, default=str) + '\n')
        print(f'{bid} {ind:16s} {fam:6s} orders={len(L.orders):6d} questions={len(qs)}', flush=True)
    for f in (fq, fa, fm):
        f.close()
    return qn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--shops', type=int, default=10)
    ap.add_argument('--questions', type=int, default=100)
    ap.add_argument('--industries', default=','.join(ALL_INDUSTRIES))
    ap.add_argument('--families', default='')
    ap.add_argument('--variant', default='')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--first-id', type=int, default=901)
    a = ap.parse_args()
    n = build(Path(a.out), a.shops, a.questions, a.industries.split(','), a.seed, a.variant or None,
              a.families.split(',') if a.families else None, a.first_id)
    print(f'{n} questions -> {a.out}')


if __name__ == '__main__':
    main()
