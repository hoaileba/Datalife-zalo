"""syn_v2: synthetic splits for the private test (new business types, their own rulebook), one folder per rulebook.

The private test has 10-20 shops of business types absent from train and ships its own rulebook (docs/zac/data.md).
A split shares one rulebook, so syn_v2 is several sub-splits, each with a rulebook composed by gen.rulebook_gen for
its trades (train rulebook + trade sections; changed defaults; dropped sections; reworded lines):

  <out>/<split>/{data/, rulebook.md, calendar.csv, questions.jsonl, answers.jsonl, meta.jsonl, _render/}
  <out>/manifest.json   splits, trades, profiles, rulebook parts, counts

Held out for validation: the split `val` (trades VAL_INDUSTRIES only; its own rulebook: changed defaults and a
section alternative no train split has, the whole text retyped; mostly family P) and the
family P (only in `val` and in a few shops of t5: held-out family on seen trades). `gen.package --val-industries
hotpot,spa_salon --val-families P` keeps both out of train.

python -m gen.build_v2 --out data_gen/syn_v2 [--shops-scale 1.0] [--questions 65] [--jobs 3] [--only t1,val]
No model calls. ~10-15 s per shop; peak ~0.5 GB per process.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

VAL_INDUSTRIES = ('hotpot', 'spa_salon')
VAL_FAMILY = 'P'
# name -> (profile, trades, shops, seed). Every new trade appears under >= 2 rulebooks; train trades are mixed in so
# the student keeps their rules while it learns to read the new ones.
SPLITS = {
    't1': ('train', ['restaurant', 'motorbike_repair', 'fruit_shop', 'fashion', 'milk_tea', 'mother_baby', 'grocery',
                     'agri_supply', 'stationery'], 9, 11),
    't2': ('mixed', ['restaurant', 'milk_tea', 'cafe', 'bakery', 'fruit_shop'], 9, 12),
    't3': ('mixed', ['motorbike_repair', 'phone_shop', 'pet_shop', 'building', 'agri_supply'], 9, 13),
    't4': ('mixed', ['fashion', 'cosmetics', 'mother_baby', 'pharmacy', 'stationery'], 9, 14),
    't5': ('mixed', ['restaurant', 'fruit_shop', 'motorbike_repair', 'grocery', 'phone_shop', 'cosmetics'], 9, 15),
    't6': ('reworded', ['milk_tea', 'fashion', 'pet_shop', 'agri_supply', 'mother_baby', 'bakery'], 9, 16),
    't7': ('mixed', ['stationery', 'phone_shop', 'fruit_shop', 'pet_shop', 'restaurant', 'pharmacy'], 9, 17),
    'val': ('rewrite', ['hotpot', 'spa_salon'], 8, 19),
}
# Changed defaults of each split (every one of gen.rulebook_gen.STACKABLE but the held-out ones appears in a train
# split); val's are never in a train split, nor is its section alternative, and its whole text is retyped.
HELD_OUT = ('bestseller_revenue', 'last_n_before_today')
FORCE = {
    't1': [],
    't2': ['revenue_voucher', 'cancel_rate_no_returns'],
    't3': ['returns_count', 'shifts_split', 'tet_short'],
    't4': ['pct_one_decimal', 'avg_purchase_simple'],
    't5': ['week_sunday', 'revenue_shipping', 'this_month_full_prev'],
    't6': ['delivering_out', 'tet_from_25'],
    't7': ['this_month_full_prev', 'avg_purchase_simple', 'week_sunday'],
    'val': list(HELD_OUT),
}
ALTS = {'val': {'tables': 'per_guest_thousand'}}
ALTS_HELD = ('per_guest_thousand',)


def family_plans(scale):
    """Families of every shop of every split: train splits together in the train shares (P only in t5, the
    held-out family on seen trades); the val split mostly P."""
    from gen.build import TRAIN_FAMILY_WEIGHTS, stratified
    rng = np.random.default_rng(7)
    sizes = {n: max(1, round(v[2] * scale)) for n, v in SPLITS.items()}
    train = [n for n in SPLITS if n != 'val']
    pool = stratified({k: v for k, v in TRAIN_FAMILY_WEIGHTS.items() if k != VAL_FAMILY},
                      sum(sizes[n] for n in train), rng)
    plans, i = {}, 0
    for n in train:
        plans[n] = pool[i:i + sizes[n]]
        i += sizes[n]
    plans['t5'][:2] = [VAL_FAMILY, VAL_FAMILY]
    v = sizes['val']
    plans['val'] = [VAL_FAMILY] * (v - v // 2) + ['E', 'D', 'F', 'A', 'G', 'C'][:v // 2]
    return plans


def build_one(out_root, name, n_questions, scale):
    from gen.build import TRAIN_FAMILY_WEIGHTS, build
    from gen.rulebook_gen import changes_of, compose
    profile, trades, shops, seed = SPLITS[name]
    shops = max(1, round(shops * scale))
    rng = np.random.default_rng(seed)
    comp = compose(trades, rng, profile, title=f'bộ {name}', force=FORCE[name] or None,
                   exclude=() if name == 'val' else HELD_OUT, alts=ALTS.get(name),
                   alts_exclude=() if name == 'val' else ALTS_HELD)
    comp.parts['name'] = f'v2_{name}'
    ch = changes_of(comp.text)
    comp.parts['rulebook_changes'] = len(ch['changes'])
    comp.parts['standard_lines_gone'] = len(ch['gone'])
    comp.parts['full_text'] = ch['full']
    if name == 'val':
        fw = {VAL_FAMILY: 3.0, 'E': 1, 'D': 1, 'F': 1, 'A': 1}       # the held-out family dominates the val split
    elif name == 't5':                       # held-out family on seen trades: these shops go to val by family
        fw = {**TRAIN_FAMILY_WEIGHTS, VAL_FAMILY: 4.0}
    else:
        fw = {k: v for k, v in TRAIN_FAMILY_WEIGHTS.items() if k != VAL_FAMILY}
    first_id = {'t1': 2001, 't2': 2101, 't3': 2201, 't4': 2301, 't5': 2401, 't6': 2501, 't7': 2601,
                'val': 2901}[name]
    t0 = time.time()
    n = build(Path(out_root) / name, shops, n_questions, trades, seed=seed, composed=comp, family_weights=fw,
              mix='train', split_name=name, first_id=first_id, family_plan=family_plans(scale)[name])
    return name, {'profile': profile, 'trades': trades, 'shops': shops, 'questions': n, 'seed': seed,
                  'parts': comp.parts, 'sec': round(time.time() - t0)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='data_gen/syn_v2')
    ap.add_argument('--questions', type=int, default=65)
    ap.add_argument('--shops-scale', type=float, default=1.0)
    ap.add_argument('--jobs', type=int, default=3)
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    names = a.only.split(',') if a.only else list(SPLITS)
    for nm in names:
        if nm != 'val' and set(SPLITS[nm][1]) & set(VAL_INDUSTRIES):
            raise SystemExit(f'{nm}: a held-out trade in a train split')
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    man_path = out / 'manifest.json'
    man = json.loads(man_path.read_text()) if man_path.exists() else {}
    man.setdefault('val', {'industries': list(VAL_INDUSTRIES), 'family': VAL_FAMILY, 'split': 'val'})
    man.setdefault('splits', {})
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        futs = [ex.submit(build_one, out, nm, a.questions, a.shops_scale) for nm in names]
        for f in futs:
            nm, info = f.result()
            man['splits'][nm] = info
            print(f'== {nm}: {info["shops"]} shops, {info["questions"]} questions, {info["sec"]} s, '
                  f'changes {info["parts"]["rulebook_changes"]}', flush=True)
            man_path.write_text(json.dumps(man, ensure_ascii=False, indent=1, default=str), encoding='utf-8')


if __name__ == '__main__':
    main()
