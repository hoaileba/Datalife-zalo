"""Question phrasing augmentation of a gen.package folder (user 2026-11-15): month/year written the short ways people
type them, and a few central-dialect words, in a share of the TRAIN questions. The forms extend those already in the
real train questions (data/train has "T6", "6/2025"...); the meaning, the gold and the completion are unchanged.

  tháng 6/2025, tháng 6 năm 2025  ->  Th6/2025 | T6/2025 | 6-2025 | 6/25 | th6/2025
  này -> ni, gì -> chi  (a few questions)

Only the question text inside the user message (and the meta) changes; a sample whose question does not appear verbatim
in its user message is left alone. No model calls.
  python scripts/augment_dates.py --package outputs/sft/final --share 0.35
"""
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path

MONTH = re.compile(r'(?i)\b(th[áa]ng)\s+(\d{1,2})\s*(?:/|\s+n[ăa]m\s+)(\d{4})\b')
FORMS = [lambda m, y: f'Th{m}/{y}', lambda m, y: f'T{m}/{y}', lambda m, y: f'{m}-{y}', lambda m, y: f'{m}/{y[2:]}',
         lambda m, y: f'th{m}/{y}', lambda m, y: f't{m}/{y}']
DIALECT = [(re.compile(r'\bnày\b'), 'ni'), (re.compile(r'\bgì\b'), 'chi')]


def rewrite(q, rng):
    out = MONTH.sub(lambda m: rng.choice(FORMS)(int(m.group(2)), m.group(3)), q)
    if rng.random() < 0.25:
        for rx, new in DIALECT:
            out = rx.sub(new, out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--package', required=True)
    ap.add_argument('--share', type=float, default=0.35, help='share of the train samples whose question has a month/year')
    ap.add_argument('--seed', type=int, default=11)
    a = ap.parse_args()
    d = Path(a.package)
    rng = random.Random(a.seed)
    rows = open(d / 'train.jsonl', encoding='utf-8').read().splitlines()
    meta = open(d / 'train_meta.jsonl', encoding='utf-8').read().splitlines()
    changed, by_q = [], {}
    for i, (r, m) in enumerate(zip(rows, meta)):
        mm = json.loads(m)
        q = mm.get('question') or ''
        if not (MONTH.search(q) or any(rx.search(q) for rx, _ in DIALECT)):
            continue
        if q not in by_q:                              # the turns of one question get the same rewrite
            by_q[q] = rewrite(q, rng) if rng.random() < a.share else q
        new = by_q[q]
        if new == q:
            continue
        s = json.loads(r)
        user = s['prompt'][1]['content']
        if q not in user:
            continue
        for msg in s['prompt']:
            if msg['role'] == 'user':
                msg['content'] = msg['content'].replace(q, new)
        mm['question'], mm['question_original'] = new, q
        rows[i], meta[i] = json.dumps(s, ensure_ascii=False), json.dumps(mm, ensure_ascii=False)
        changed.append({'line': i + 1, 'id': mm['id'], 'from': q, 'to': new})
    (d / 'train.jsonl').write_text('\n'.join(rows) + '\n', encoding='utf-8')
    (d / 'train_meta.jsonl').write_text('\n'.join(meta) + '\n', encoding='utf-8')
    (d / 'AUGMENT_DATES.json').write_text(json.dumps({'changed': len(changed), 'share': a.share, 'seed': a.seed,
                                                      'samples': changed}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{len(changed)} train samples rewritten of {len(rows)}')
    for c in changed[:8]:
        print(' ', c['from'], '->', c['to'])


if __name__ == '__main__':
    main()
