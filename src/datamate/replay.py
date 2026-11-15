"""Re-run the programs of an earlier run with the current host code, without calling the model: measures a
host-side change (sandbox, shapes, answer checks) at zero model cost.

    python -m datamate.replay outputs/runs/<run> --split data/train
Prints aggregates only: programs re-run, how many ran before/after, final answers changed.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .answer import AnswerError, finalize
from .config import ROOT, load_config
from .data import _fingerprint, load_business
from .sandbox import Limits, execute


def replay(run: Path, split: Path, cfg) -> dict:
    stats = Counter()
    questions = {json.loads(l)['id']: json.loads(l) for l in open(split / 'questions.jsonl', encoding='utf-8')}
    cache = Path(cfg['run']['cache_dir']); cache = cache if cache.is_absolute() else ROOT / cache
    for path in sorted((run / 'logs').glob('*.json')):
        log = json.loads(path.read_text(encoding='utf-8'))
        q = questions[log['id']]
        folder, calendar = split / 'data' / q['business_id'], split / 'calendar.csv'
        load_business(folder, calendar, cache)
        tables = cache / f'{folder.name}-{_fingerprint(folder, calendar)}.pkl'
        models = {e['turn']: e for e in log.get('trace', []) if e['event'] == 'model'}
        for e in (e for e in log.get('trace', []) if e['event'] == 'execution'):
            stats['programs'] += 1
            stats['ran_before'] += e['ok']
            run_now = execute(e['code'], tables, q['as_of_date'], Limits(wall_seconds=cfg['sandbox']['wall_seconds']), typed=False)
            stats['ran_now'] += run_now.ok
            try:
                kind = json.loads(models[e['turn']]['output']).get('answer_type')
            except (ValueError, KeyError):
                kind = None
            if run_now.ok and kind:
                try:
                    finalize(kind, run_now.result)
                    stats['valid_now'] += 1
                except AnswerError:
                    pass
    return dict(stats)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('run')
    ap.add_argument('--split', required=True)
    args = ap.parse_args(argv)
    print(json.dumps(replay(Path(args.run), Path(args.split), load_config())))


if __name__ == '__main__':
    main()
