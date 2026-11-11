"""Write the exact messages the model gets at prediction time, for a TRAIN question, to a folder (one file per message).

    PYTHONIOENCODING=utf-8 PYTHONPATH=src:. python scripts/show_prompt.py --business biz_123 --out /tmp/p
    ... --question 5          the 5th question of that shop (default 0)
    ... --variant week_sunday  rulebook changed by a gen.variants variant (shows rulebook_changes, cookbook without that recipe)
    ... --history              add three real turns run in the sandbox: an explore, a failing program, a flagged result

Never reads data/public_test (training data only). No model call.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from datamate import prompt, solve  # noqa: E402
from datamate.catalog import build_catalog, lookup  # noqa: E402
from datamate.config import load_config  # noqa: E402
from datamate.data import _fingerprint, load_business  # noqa: E402
from datamate.runner import load_rulebook  # noqa: E402
from datamate.sandbox import Limits, execute  # noqa: E402


def turns(pkl, as_of, table, status_col):
    """Three real turns: explore the status labels, a program with a wrong column, a program with an empty result."""
    acts = [
        {'action': 'python', 'plan': 'ASKED: labels of the status column.', 'answer_type': 'explore',
         'code': f"df = tables['{table}']\nprint(dm.values(df, '{status_col}'))"},
        {'action': 'python', 'plan': 'ASKED: test.', 'answer_type': 'number',
         'code': f"df = tables['{table}']\ndone = df[df['{status_col}'] == 'no such label']\nresult = done['no such column'].sum()"},
        {'action': 'python', 'plan': 'ASKED: test.', 'answer_type': 'list',
         'code': f"df = tables['{table}']\ndone = df[df['{status_col}'] == 'no such label']\nresult = list(done.index[:3])"},
    ]
    out = []
    for i, a in enumerate(acts):
        trace = []
        _, _, obs = solve._run_program({**a, 'turn': i}, {'question': 'q', 'as_of': as_of},
                                       type('C', (), {'tables_path': str(pkl), 'config': load_config()})(), 1e18, trace)
        out.append((a, obs))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--business', required=True)
    ap.add_argument('--question', type=int, default=0)
    ap.add_argument('--variant')
    ap.add_argument('--history', action='store_true')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    split, cfg = ROOT / 'data' / 'train', load_config()
    rb_path = split / 'rulebook.md'
    if a.variant:
        from gen.variants import rulebook_text
        rb_path = Path(tempfile.mkdtemp()) / 'rulebook.md'
        rb_path.write_text(rulebook_text(a.variant), encoding='utf-8')
    rulebook, _, changed, system = load_rulebook(rb_path)
    qs = [json.loads(l) for l in open(split / 'questions.jsonl', encoding='utf-8') if json.loads(l)['business_id'] == a.business]
    q = qs[a.question]
    folder, calendar, cache = split / 'data' / a.business, split / 'calendar.csv', Path(cfg['run']['cache_dir'])
    cache = cache if cache.is_absolute() else ROOT / cache
    business = load_business(folder, calendar, cache)
    catalog = build_catalog(business, rulebook, changed)
    history = []
    if a.history:
        pkl = cache / f'{folder.name}-{_fingerprint(folder, calendar)}.pkl'
        group = next(iter(catalog.get('label_groups', [])), None)
        if group:
            history = turns(pkl, q['as_of_date'], group['table'], group['column'])
    left = cfg['agent']['max_calls'] - len(history)
    msgs = prompt.messages(catalog, q['question'], q['as_of_date'], lookup(q['question'], business), history, left,
                           left == 1, system)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for i, m in enumerate(msgs):
        (out / f'{i}_{m["role"]}.txt').write_text(m['content'], encoding='utf-8')
    print(json.dumps({'question': q['question'], 'messages': [(m['role'], len(m['content'])) for m in msgs]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
