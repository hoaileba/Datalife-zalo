"""Gap-filling real train questions for the final data (advisor review 2026-11-15), solved on the reskinned tables.

Unused train questions (not in data_gen/final_ids/A_all.txt, not the held-out shops biz_108/110/130, not C_shops*)
chosen by coarse intent (scripts/train_intents.py) and answer type to fill what the kept data lacks: prescription
questions (generated worlds cannot produce them), debt/purchase/shift/customer/stock/expiry/return/profit, the rarer
answer types, and revenue. At most CAP per shop; each id goes to reskin_1 or reskin_2 by a hash.
  python scripts/select_train_gap.py      -> data_gen/final_ids/G_r1.txt, G_r2.txt
"""
import collections
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from train_intents import A, Q, intent   # noqa: E402

IDS = ROOT / 'data_gen' / 'final_ids'
VAL_SHOPS = {'biz_108', 'biz_110', 'biz_130'}
CAP = 20
QUOTA = {   # bucket -> how many (None = all unused)
    'rx': None, 'expiry': None,
    'debt': 60, 'purchase': 60, 'shift': 60, 'customer': 60, 'stock': 36, 'return': 15, 'profit': 15,
    'type:table': None, 'type:string': None, 'type:unanswerable': None, 'type:list': None, 'revenue': 150,
}
GROUP = {'debt_age': 'debt', 'debt_new': 'debt', 'debt_paid': 'debt', 'debt': 'debt', 'avg_cost': 'purchase',
         'purchase': 'purchase', 'shift': 'shift', 'customer': 'customer', 'cust_group': 'customer',
         'stock': 'stock', 'stock_value': 'stock', 'out_of_stock': 'stock', 'expiry': 'expiry', 'return': 'return',
         'gross_profit': 'profit', 'net_profit': 'profit', 'rx': 'rx', 'revenue': 'revenue'}


def main():
    used = set()
    for f in ('A_all.txt', 'C_shops.txt', 'C_shops2.txt'):
        used |= set((IDS / f).read_text().split())
    pool = collections.defaultdict(list)
    for q in Q:
        if q['id'] in used or q['business_id'] in VAL_SHOPS:
            continue
        t = A[q['id']]['type']
        b = f'type:{t}' if f'type:{t}' in QUOTA else GROUP.get(intent(q['question'], A[q['id']]))
        if b in QUOTA:
            pool[b].append(q)
    rng = random.Random(15)
    per_shop, chosen = collections.Counter(), []
    for b, n in QUOTA.items():          # scarce buckets first: they take the shop slots before revenue
        qs = pool[b][:]
        rng.shuffle(qs)
        got = 0
        for q in qs:
            if n is not None and got >= n:
                break
            if per_shop[q['business_id']] >= CAP:
                continue
            per_shop[q['business_id']] += 1
            chosen.append((b, q))
            got += 1
        print(f'{b:18s} pool {len(pool[b]):4d} chosen {got}')
    side = {1: [], 2: []}
    for b, q in chosen:
        side[1 + int(hashlib.sha1(q['id'].encode()).hexdigest(), 16) % 2].append(q['id'])
    for k, ids in side.items():
        (IDS / f'G_r{k}.txt').write_text('\n'.join(ids) + '\n')
    print(f'{len(chosen)} questions, {len(per_shop)} shops (max {max(per_shop.values())}/shop); '
          f'r1 {len(side[1])}, r2 {len(side[2])}')


if __name__ == '__main__':
    main()
