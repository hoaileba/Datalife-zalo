"""Concatenate gen.package folders into one (e.g. a thinking-ON package + a thinking-OFF package).

Meta rows get `mode` = "think" (completion has `reasoning`) or "nothink". train/sft_lora.py picks the render per
sample from the same field, so one adapter learns both modes. stats.json is recomputed for the result (counts,
lengths, distributions per mode); README/val_questions come from the first package unless --readme is given.
Ids must not collide across packages (a collision stops the script).

No model calls.
  python scripts/sft_concat.py --packages outputs/sft/train_v3 outputs/sft/_reskin_off --out outputs/sft/train_v3_mix
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import shutil
from pathlib import Path

from sft_thinking import quantiles, read_jsonl

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--packages', nargs='+', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--readme', help='README to put in the result (default: the first package\'s)')
    a = ap.parse_args()
    pkgs, out = [Path(p) for p in a.packages], Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stats = json.loads((pkgs[0] / 'stats.json').read_text(encoding='utf-8'))
    lengths, dist, samples = {}, {}, {}
    for side in ('train', 'val'):
        seen, metas_all = set(), []
        with open(out / f'{side}.jsonl', 'w', encoding='utf-8') as fr, open(out / f'{side}_meta.jsonl', 'w', encoding='utf-8') as fm:
            for p in pkgs:
                if not (p / f'{side}.jsonl').exists():
                    continue
                with open(p / f'{side}.jsonl', encoding='utf-8') as rows, open(p / f'{side}_meta.jsonl', encoding='utf-8') as metas:
                    for line, mline in zip(rows, metas):
                        r, m = json.loads(line), json.loads(mline)
                        if r['id'] != m['key']:
                            raise SystemExit(f'{p}/{side}: rows and meta disagree at {r["id"]}')
                        if r['id'] in seen:
                            raise SystemExit(f'duplicate sample id {r["id"]} ({p})')
                        seen.add(r['id'])
                        m['mode'] = 'think' if r['completion'][0].get('reasoning') else 'nothink'
                        m.setdefault('thinking_tokens', 0)
                        m['package'] = p.name
                        fr.write(line if line.endswith('\n') else line + '\n')
                        fm.write(json.dumps(m, ensure_ascii=False) + '\n')
                        metas_all.append(m)
        if not metas_all:
            continue
        by_mode = collections.defaultdict(list)
        for m in metas_all:
            by_mode[m['mode']].append(m)
        samples[side] = len(metas_all)
        samples[f'{side}_final'] = sum(1 for m in metas_all if m.get('final'))
        for mode, ms in by_mode.items():
            samples[f'{side}_{mode}'] = len(ms)
        lengths[side] = {mode: {k: quantiles([m[k] for m in ms]) for k in
                                ('prompt_tokens', 'thinking_tokens', 'completion_tokens', 'total_tokens')}
                         for mode, ms in by_mode.items()}
        dist[side] = {mode: {k: dict(collections.Counter(str(m.get(k)) for m in ms).most_common())
                             for k in ('run', 'gold_type', 'answer_type', 'final', 'turn', 'industry')}
                      for mode, ms in by_mode.items()}
        dist[side]['questions'] = len({m['group'] for m in metas_all})
        print(side, samples[side], {k: len(v) for k, v in by_mode.items()}, flush=True)

    for f in pkgs[0].iterdir():
        if f.is_file() and f.suffix != '.jsonl' and f.name not in ('stats.json', 'filtered.json', 'thinking.json'):
            shutil.copy2(f, out / f.name)
    vq = {}
    for p in pkgs:                                          # every held-out question of every package, once
        if (p / 'val_questions.jsonl').exists():
            for q in read_jsonl(p / 'val_questions.jsonl'):
                vq[(q['split'], q['id'])] = q
    (out / 'val_questions.jsonl').write_text(''.join(json.dumps(q, ensure_ascii=False) + '\n' for q in vq.values()), encoding='utf-8')
    shutil.copy2(ROOT / 'train' / 'sft_lora.py', out / 'sft_lora.py')
    if a.readme:
        shutil.copy2(a.readme, out / 'README.md')
    stats.update(samples=samples, lengths=lengths, distributions=dist,
                 max_total_tokens=max(v['total_tokens']['max'] for s in lengths.values() for v in s.values()))
    stats.setdefault('derived', []).append({'by': 'scripts/sft_concat.py', 'from': [str(p) for p in pkgs]})
    stats['files'] = {f.name: {'bytes': f.stat().st_size, 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()}
                      for f in sorted(out.iterdir()) if f.is_file() and f.name != 'stats.json'}
    (out / 'stats.json').write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'samples': samples, 'total_tokens': {s: {m: v['total_tokens'] for m, v in d.items()}
                                                          for s, d in lengths.items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
