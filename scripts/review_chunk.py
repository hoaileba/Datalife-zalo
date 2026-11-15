"""Chunks of 100 finished questions of the final run, for the periodic review (no model calls).

Questions are ordered by the time their pass-1 record finished (all p1_* folders); a question's pass-2 record is used
when pass 1 was wrong. For chunk k this prints, per question: id, part, intent, outcome, the gate result
(gen.sft.teacher_turns), turns, tokens; and writes the kept completions (and a dropped reason) to
outputs/tmp/review_chunks/chunk_<k>.md for reading.

  python scripts/review_chunk.py --list            # how many chunks are complete
  python scripts/review_chunk.py --chunk 3         # summary + outputs/tmp/review_chunks/chunk_3.md
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
T = ROOT / 'outputs' / 'teacher' / 'final'
OUT = ROOT / 'outputs' / 'tmp' / 'review_chunks'


def records(pattern='p1_*'):
    rows = []
    for run in sorted(T.glob(pattern)):
        for f in (run / 'logs').glob('*.json'):
            rows.append((f.stat().st_mtime, run.name, f))
    rows.sort()
    return rows


def best(run_name, f):
    """(record, folder) used for the question: the pass-2 record when pass 1 was not correct and pass 2 exists."""
    rec = json.loads(f.read_text(encoding='utf-8'))
    if rec.get('outcome') != 'correct':
        p2 = T / run_name.replace('p1_', 'p2_', 1) / 'logs' / f.name
        if p2.exists():
            return json.loads(p2.read_text(encoding='utf-8')), p2.parent.parent.name
    return rec, run_name


def meta_of(rec):
    split = Path((rec.get('input') or {}).get('split') or '')
    m = split / 'meta.jsonl'
    if m.exists():
        for line in open(m, encoding='utf-8'):
            d = json.loads(line)
            if d.get('id') == rec['id']:
                return d
    return {}


def main():
    from gen import sft
    ap = argparse.ArgumentParser()
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--chunk', type=int)
    ap.add_argument('--size', type=int, default=100)
    ap.add_argument('--partial', action='store_true', help='the last chunk of a finished series (fewer than --size)')
    ap.add_argument('--root', default=str(T), help='teacher root (outputs/teacher/forced for the forced-turn runs)')
    ap.add_argument('--runs', default='p1_*', help='pass-1 folders of this review series (glob under outputs/teacher/final)')
    a = ap.parse_args()
    globals()['T'] = Path(a.root)
    rows = records(a.runs)
    if a.list or a.chunk is None:
        print(f'{len(rows)} finished questions -> {len(rows) // a.size} complete chunks of {a.size}')
        return
    part = rows[a.chunk * a.size:(a.chunk + 1) * a.size]
    ap_partial = '--partial' in sys.argv
    if len(part) < a.size and not ap_partial:
        raise SystemExit(f'chunk {a.chunk} not complete yet ({len(part)}/{a.size})')
    OUT.mkdir(parents=True, exist_ok=True)
    md, stats = [], collections.Counter()
    for _, run_name, f in part:
        rec, folder = best(run_name, f)
        m = meta_of(rec)
        turns = sft.teacher_turns(rec)
        final = next((x for x in turns if x['final']), None)
        gate = 'kept' if final and final['keep'] else (final or {}).get('why') or 'no_turn'
        stats[gate] += 1
        line = (f"{rec['id']} | {folder} | {m.get('intent') or '(train)'} | gold {rec.get('gold', {}).get('type')} | "
                f"{rec.get('outcome')} | gate {gate} | turns {len(turns)} | tok {rec.get('totals', {}).get('prompt_tokens')}")
        print(line)
        md.append(f'## {line}\n\nQUESTION: {rec.get("question")} (as_of {rec.get("as_of")})\nGOLD: {json.dumps(rec.get("gold", {}).get("answer"), ensure_ascii=False)[:300]}  '
                  f'GOT: {json.dumps(rec.get("answer"), ensure_ascii=False)[:300]}\n')
        for x in turns:
            ev = next((e for e in rec['trace'] if e.get('event') == 'model' and e.get('turn') == x['turn']), {})
            obs = x.get('observation') or {}
            md.append(f"### turn {x['turn']} keep={x['keep']} why={x['why']} obs={obs.get('status')}\n\n{ev.get('output', '')}\n")
            if obs.get('error'):
                md.append(f"OBSERVATION ERROR: {obs['error'][:800]}\n")
    (OUT / f"chunk_{a.runs.replace('*', '').replace('p1_', '').replace('/', '')}{a.chunk}.md").write_text('\n'.join(md), encoding='utf-8')
    print(dict(stats), '->', OUT / f"chunk_{a.runs.replace('*', '').replace('p1_', '').replace('/', '')}{a.chunk}.md")


if __name__ == '__main__':
    main()
