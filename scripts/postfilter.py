"""Drop samples after a gen.package build: reviewer ids found after the build started (plain records only; a forced-turn
sample of the same question is kept). Writes <package>/POSTFILTER.json. No model calls.
  python scripts/postfilter.py --package outputs/sft/final --ids q_a q_b ...
"""
import argparse
import json
from pathlib import Path

FORCED_RUNS = ('main_', 'extra_', 'pilot_')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--package', required=True)
    ap.add_argument('--ids', nargs='+', required=True)
    ap.add_argument('--why', default='review after the build started')
    a = ap.parse_args()
    d, ids = Path(a.package), set(a.ids)
    rows = open(d / 'train.jsonl', encoding='utf-8').read().splitlines()
    meta = open(d / 'train_meta.jsonl', encoding='utf-8').read().splitlines()
    keep_r, keep_m, removed = [], [], []
    for r, m in zip(rows, meta):
        mm = json.loads(m)
        if mm['id'] in ids and not str(mm.get('run', '')).split('/')[-1].startswith(FORCED_RUNS):
            removed.append({'id': mm['id'], 'key': mm['key'], 'why': a.why})
            continue
        keep_r.append(r)
        keep_m.append(m)
    (d / 'train.jsonl').write_text('\n'.join(keep_r) + '\n', encoding='utf-8')
    (d / 'train_meta.jsonl').write_text('\n'.join(keep_m) + '\n', encoding='utf-8')
    (d / 'POSTFILTER.json').write_text(json.dumps({'removed_after_build': removed, 'train_before': len(rows),
                                                   'train_after': len(keep_r)}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(rows), '->', len(keep_r))


if __name__ == '__main__':
    main()
