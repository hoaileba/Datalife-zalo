"""Run questions end to end: submission.jsonl (flushed after every question), one log per question, summary.

Dev:     python -m datamate.runner --split data/train --limit 5 --out outputs/runs/t5
Predict: python -m datamate.runner --split /data --out /result --all
Prints aggregates only (counts, PA, health), never questions or answers: safe for public runs.
Every question is isolated: any failure becomes an abstain line and the run continues. A global time budget
(config run.total_seconds) turns the remaining questions into abstains instead of overrunning.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .answer import submission_line
from .catalog import build_catalog
from .config import ROOT, load_config, load_dotenv
from .data import _fingerprint, load_business
from .grids import decode_text
from .eval import format_ok, health, score
from .llm import LLM
from .prompt import system_prompt
from .rules import compare, load_train_units, units
from .solve import Context, solve


def read_jsonl(path):
    """Objects of a JSON-lines file; a BOM is ignored and a line that does not parse is skipped (never fatal)."""
    out = []
    with open(path, encoding='utf-8-sig', errors='replace') as f:
        for line in f:
            try:
                obj = json.loads(line) if line.strip() else None
            except ValueError:
                obj = None
            if isinstance(obj, dict):
                out.append(obj)
    return out


def select(questions, limit, seed):
    """Same selection as the v3 dev runner: shuffle with the seed, take `limit`, order by business."""
    questions = list(questions)
    random.Random(seed).shuffle(questions)
    return sorted(questions[:limit], key=lambda q: (q['business_id'], q['id']))

ONLY_CHANGES = ('The standard rules are in the cookbook of the system prompt (section 4). The rules of this set that '
                'differ from the standard or are new are listed in rulebook_changes, word for word: they win.')
STANDARD = 'This set uses the standard rules: they are in the cookbook of the system prompt (section 4).'
FULL = ("This set's rulebook differs from the standard in most lines, so here it is in full. It wins over the cookbook "
        'of the system prompt wherever they differ.\n\n')


def load_rulebook(path: Path):
    """(rulebook document for the prompt, counts, changed lines for catalog.rulebook_changes, system prompt). The
    cookbook of the system prompt carries the standard (train) rules minus the ones this set changed or dropped; the
    changed and new lines are listed word for word; a rewritten rulebook is sent whole with the whole cookbook."""
    text = decode_text(path.read_bytes()) if path.is_file() else ''     # a missing or odd file never stops the run
    diff = compare(text, load_train_units())
    stats = {'units': len(units(text)), 'changed': len(diff['changes']), 'gone': len(diff['gone']), 'full': diff['full']}
    system = system_prompt(frozenset(diff['gone']))
    return (FULL + text if diff['full'] else ONLY_CHANGES if diff['changes'] else STANDARD), stats, diff['changes'], system


def snapshot(out: Path, cfg, system):
    """The config and the system prompt this run uses, saved next to its logs (the trace viewer rebuilds inputs from them)."""
    import yaml
    (out / 'config.yaml').write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
    (out / 'system_prompt.md').write_text(system, encoding='utf-8')


class Businesses:
    """Load each business once (thread-safe); keeps its catalog and the pickle path the sandbox reads."""
    def __init__(self, split: Path, rulebook: str, cache_dir: Path, changed=()):
        self.split, self.rulebook, self.cache_dir, self.changed = split, rulebook, cache_dir, list(changed)
        self.items, self.locks, self.lock = {}, {}, threading.Lock()

    def get(self, business_id):
        with self.lock:
            lock = self.locks.setdefault(business_id, threading.Lock())
        with lock:
            if business_id not in self.items:
                folder, calendar = self.split / 'data' / business_id, self.split / 'calendar.csv'
                try:
                    business = load_business(folder, calendar, self.cache_dir)
                    path = self.cache_dir / f'{folder.name}-{_fingerprint(folder, calendar)}.pkl'
                    self.items[business_id] = (business, build_catalog(business, self.rulebook, self.changed), path)
                except Exception as exc:                       # remembered: later questions do not reload and fail
                    self.items[business_id] = exc
            item = self.items[business_id]
            if isinstance(item, Exception):
                raise item
            return item


def writable_dir(*candidates) -> Path:
    """The first directory we can create and write a file in (the image may be read-only or run as another user)."""
    for d in candidates:
        try:
            d = Path(d)
            d.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=d):
                return d
        except OSError:
            continue
    return Path(tempfile.mkdtemp(prefix='datamate_cache_'))


def load_questions(split, args, cfg):
    """The questions to answer, one per id (duplicates and id-less lines dropped; missing fields stay None)."""
    questions = read_jsonl(split / 'questions.jsonl')
    if getattr(args, 'ids', None):
        questions = [q for q in questions if q.get('id') in set(args.ids)]
    elif not args.all:
        questions = select(questions, args.limit, args.seed)
    if not args.all and len(questions) > cfg['run']['dev_limit'] and not args.allow_large:
        raise SystemExit(f"{len(questions)} questions > dev limit {cfg['run']['dev_limit']}: pass --allow-large (needs approval)")
    seen, kept = set(), []
    for q in questions:
        if q.get('id') is not None and str(q['id']) not in seen:
            seen.add(str(q['id']))
            kept.append({'id': q['id'], 'business_id': q.get('business_id'), 'question': q.get('question') or '',
                         'as_of': q.get('as_of_date')})
    return kept


def write_submission(out, questions, lines):
    """The final file, atomically: every question id exactly once, in question order (abstain when missing)."""
    with open(out / 'submission.jsonl.tmp', 'w', encoding='utf-8') as f:
        for q in questions:
            f.write(json.dumps(lines.get(q['id']) or submission_line(q['id'], 'abstain'), ensure_ascii=False) + '\n')
    os.replace(out / 'submission.jsonl.tmp', out / 'submission.jsonl')


def run(args, cfg, llm=None):
    split, out = Path(args.split), Path(args.out)
    (out / 'logs').mkdir(parents=True, exist_ok=True)
    rulebook, rulebook_stats, changed, system = load_rulebook(Path(getattr(args, 'rulebook', None) or split / 'rulebook.md'))
    snapshot(out, cfg, system)
    questions = load_questions(split, args, cfg)
    started = time.monotonic()                                # the budget counts from container start when given
    already = max(0.0, time.time() - float(os.environ['DATAMATE_START'])) if os.environ.get('DATAMATE_START') else 0.0
    run_deadline = started + cfg['run']['total_seconds'] - already
    write_lock, lines, logs = threading.Lock(), {}, []
    done = {} if not getattr(args, 'resume', False) else {l['id']: l for l in read_jsonl(out / 'submission.jsonl') if 'type' in l}
    submission = open(out / 'submission.jsonl', 'a' if done else 'w', encoding='utf-8')   # opened before anything can fail
    lines.update(done)
    cache = Path(cfg['run']['cache_dir']); cache = cache if cache.is_absolute() else ROOT / cache
    cache = writable_dir(cache, Path(tempfile.gettempdir()) / 'datamate_cache', out / 'cache')   # sandbox reads it
    businesses = Businesses(split, rulebook, cache, changed)
    llm = llm or LLM(cfg['llm'])

    def one(q):
        t0 = time.monotonic()
        log = {'id': q['id'], 'business_id': q['business_id']}
        try:
            if time.monotonic() > run_deadline - 10:
                kind, answer, log['reason'], log['trace'], log['calls'] = 'abstain', None, 'run_deadline', [], 0
            elif not (q['business_id'] and q['question'] and q['as_of']):
                kind, answer, log['reason'], log['trace'], log['calls'] = 'abstain', None, 'bad_question', [], 0
            else:
                business, catalog, path = businesses.get(q['business_id'])
                deadline = min(t0 + cfg['agent']['question_seconds'], run_deadline)
                result = solve(q, Context(llm, catalog, business, str(path), cfg, system), deadline)
                kind, answer = result.answer_type, result.answer
                log.update(reason=result.reason, calls=result.calls, trace=result.trace)
        except Exception as exc:                               # host bug: this question abstains, the run goes on
            kind, answer = 'abstain', None
            log.update(reason='host_error', error=traceback.format_exc()[-3000:], trace=[], calls=0)
        line = submission_line(q['id'], kind, answer)
        if not format_ok(line):                                # never write an invalid line
            line, log['reason'] = submission_line(q['id'], 'abstain'), 'format_guard'
        log.update(type=line['type'], answer=line['answer'], seconds=round(time.monotonic() - t0, 2))
        with write_lock:
            submission.write(json.dumps(line, ensure_ascii=False) + '\n'); submission.flush()
            (out / 'logs' / f"{q['id']}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
            lines[q['id']] = line; logs.append(log)

    todo = [q for q in questions if q['id'] not in done]
    with ThreadPoolExecutor(max_workers=cfg['run']['workers']) as pool:
        list(pool.map(one, todo))
        retry = [q for q in todo if lines.get(q['id'], {}).get('type') == 'abstain'
                 and any(l['id'] == q['id'] and l.get('reason') == 'llm_error' for l in logs)]
        if retry and time.monotonic() < run_deadline - 60:   # the model server was down: a second pass
            list(pool.map(one, retry))
    submission.close()
    write_submission(out, questions, lines)
    summary = {'split': str(split), 'n': len(questions), 'seconds': round(time.monotonic() - started, 1),
               'rulebook': rulebook_stats, 'health': health(logs, list(lines.values()))}
    if (split / 'answers.jsonl').exists():
        gold = {g['id']: g for g in read_jsonl(split / 'answers.jsonl')}
        summary['score'] = score(lines, gold)
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--split', required=True, help='folder with questions.jsonl, rulebook.md, calendar.csv, data/')
    ap.add_argument('--out', required=True)
    ap.add_argument('--limit', type=int, default=5)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--ids', nargs='*')
    ap.add_argument('--all', action='store_true', help='every question (submission run)')
    ap.add_argument('--allow-large', action='store_true', help='dev run above the 6-question limit (needs approval)')
    ap.add_argument('--rulebook', help='rulebook file instead of <split>/rulebook.md (dev only)')
    ap.add_argument('--config', default=str(ROOT / 'config.yaml'))
    ap.add_argument('--resume', action='store_true', help='keep the lines already in <out>/submission.jsonl')
    args = ap.parse_args(argv)
    load_dotenv()
    summary = run(args, load_config(args.config))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
