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
from gen.oracle import Rules, answer, undetermined  # noqa: E402
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
    sample), plus some it does not move (the model must not over-apply a change). Questions the variant's rulebook
    does not fix (gen.oracle.undetermined) stay in the list: callers drop them."""
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


# export families in the train shares (30 shops: E 6, F 5, D 5, G 3, A 3, B 3, C 2, H 1 + A' and I, not rendered),
# plus the two families absent from train
TRAIN_FAMILY_WEIGHTS = {'E': 6, 'F': 5, 'D': 5, 'G': 3, 'A': 3, 'B': 3, 'C': 2, 'H': 1.5, 'S': 1.5, 'P': 1.5}


def pick_family(fams, rng, weights=None):
    if not weights:
        return fams[int(rng.integers(len(fams)))]
    w = np.array([weights.get(f, 0.0) for f in fams], dtype=float)
    if w.sum() == 0:
        return fams[int(rng.integers(len(fams)))]
    return fams[int(rng.choice(len(fams), p=w / w.sum()))]


def stratified(weights, n, rng):
    """n families in the shares of `weights` (largest remainder), shuffled."""
    tot = sum(weights.values())
    raw = {f: n * w / tot for f, w in weights.items()}
    k = {f: int(v) for f, v in raw.items()}
    for f in sorted(raw, key=lambda f: raw[f] - k[f], reverse=True)[:n - sum(k.values())]:
        k[f] += 1
    plan = [f for f, c in k.items() for _ in range(c)]
    return [plan[i] for i in rng.permutation(len(plan))]


def build(out: Path, n_shops: int, n_questions: int, industries, seed=0, variant=None, families=None,
          first_id=901, composed=None, family_weights=None, mix='v1', split_name=None, family_plan=None):
    """composed: a gen.rulebook_gen.Composed (split rulebook + its Rules) instead of the train rulebook / a variant;
    family_weights: {family: weight} (TRAIN_FAMILY_WEIGHTS) instead of a uniform choice; mix='train': period kinds
    and split-rulebook intents of gen.questions (v1 = the syn_v1 behaviour); family_plan: the family of each shop
    (stratified by the caller), used when applicable."""
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
    if composed is not None:
        rules, rb = composed.rules, composed.text
        (out / '_render').mkdir()
        (out / '_render' / 'rulebook_parts.json').write_text(json.dumps(
            {'parts': composed.parts, 'rules': {k: v for k, v in vars(rules).items()}}, ensure_ascii=False,
            default=str, indent=1), encoding='utf-8')
    (out / 'rulebook.md').write_text(rb, encoding='utf-8')
    fq, fa, fm = (open(out / f, 'w', encoding='utf-8') for f in ('questions.jsonl', 'answers.jsonl', 'meta.jsonl'))
    qn = dropped = 0
    for i in range(n_shops):
        ind = industries[i % len(industries)]
        bid = f'syn_{first_id + i}'
        spec = make_spec(ind, rng, bid)
        L = simulate(spec, int(rng.integers(1 << 30)))
        fams = [f for f in R.families_for(L) if families is None or f in families]
        money = [k for k, on in (('shipping', rules.revenue_shipping), ('order_discount', rules.revenue_order_discount))
                 if on]
        if money:                             # revenue needs order-level money: a family with order ids
            fams = [f for f in fams if f != 'B']
        fam = pick_family(fams, rng, family_weights)
        if family_plan and i < len(family_plan) and family_plan[i] in fams:
            fam = family_plan[i]
        shop_dir = out / 'data' / bid
        shown = list(money)
        if composed is not None and fam != 'B':     # the columns also appear where the rulebook ignores them, so a
            for k in ('shipping', 'order_discount'):  # column never stands in for reading the rule
                if k not in shown and rng.random() < 0.35:
                    shown.append(k)
        rendered = R.render(L, fam, shop_dir, rng, order_money=tuple(shown))
        L.shop['caps'] = set(rendered['caps'])
        if composed is not None:              # side files for the checks (outside data/: the agent never sees them)
            (out / '_render' / f'{bid}.json').write_text(json.dumps(
                {'family': fam, 'industry': ind, 'caps': sorted(rendered['caps']), 'extras': rendered['extras'],
                 'start': str(L.shop['start']), 'end': str(L.shop['end'])}, ensure_ascii=False, default=str),
                encoding='utf-8')
        business = load_business(shop_dir, out / 'calendar.csv', None)
        values = _text_values(business)
        codes = _codes(L)
        if variant:
            qs = variant_questions(L, rng, n_questions, variant, rules)
        else:
            kw = {}
            if composed is not None:          # more of the questions the split's changed defaults move
                from gen.questions import WEIGHTS
                from gen.rulebook_gen import focus
                iw, pw = focus(composed.parts)
                kw = {'weights': {k: v * iw.get(k, 1.0) for k, v in WEIGHTS.items()}, 'period_boost': pw}
            qs = sample(L, rng, n_questions, rules=rules, mix=mix, **kw)
        if composed is not None:
            # moved = the split's own text (changed defaults, section alternatives) changes this answer
            from gen.rulebook_gen import base_rules
            base = base_rules(rules, composed.parts)
            for q in qs:
                q['moved'] = base != rules and answer(L, q['spec'], q['as_of'], base) != (q['type'], q['answer'])
        for q in qs:                      # sampled after rendering: the rendered caps decide unanswerable
            t, a = q['type'], q['answer']
            qn += 1
            qid = f'q_syn{seed:02d}_{qn:06d}' if split_name is None else f'q_{split_name}_{qn:05d}'
            ctx = S.make_ctx(L, q['spec'], q['as_of'])
            prng = random.Random(int(rng.integers(1 << 62)))       # surface.py uses random.Random
            if undetermined(q['spec'], rules, L):  # the rulebook does not fix this answer: never asked (dropped after
                dropped += 1                    # its id and text seed are drawn: the other questions stay the same)
                continue
            text = S.noisify(S.realize(q['spec'], ctx, prng), prng)
            fq.write(json.dumps({'id': qid, 'business_id': bid, 'question': text,
                                 'as_of_date': q['as_of'].isoformat()}, ensure_ascii=False) + '\n')
            line = {'id': qid, 'type': t, 'answer': a, 'alias': answer_alias(t, a, codes, values, L.shop['caps'])}
            fa.write(json.dumps(line, ensure_ascii=False) + '\n')
            fm.write(json.dumps({'id': qid, 'intent': q['spec']['intent'], 'family': fam, 'industry': ind,
                                 'variant': variant or (composed.parts.get('name') if composed else None),
                                 'moved': q.get('moved'), 'spec': q['spec'], 'business_id': bid,
                                 'as_of': q['as_of'].isoformat(), 'split': split_name},
                                ensure_ascii=False, default=str) + '\n')
        print(f'{bid} {ind:16s} {fam:6s} orders={len(L.orders):6d} questions={len(qs)}', flush=True)
    for f in (fq, fa, fm):
        f.close()
    return qn - dropped


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
