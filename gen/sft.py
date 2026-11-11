"""SFT samples from v4 runs: each model turn of a question whose final answer matches the gold, as
(messages exactly as the runner built them, completion = the model's JSON output).

Kept turns: the turn that produced the submitted answer, and earlier turns that ran cleanly as `explore` actions.
Failed turns are not imitated, but they stay in the history of later turns (the model learns to recover from them).
Runs on any split that has answers.jsonl (train, synthetic splits); never on public/private test runs.

python -m gen.sft --run outputs/runs/<run> [--split data/train] --out sft.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from datamate import prompt  # noqa: E402
from datamate.catalog import build_catalog, lookup  # noqa: E402
from datamate.config import load_config, load_dotenv  # noqa: E402
from datamate.data import load_business  # noqa: E402
from datamate.eval import correct  # noqa: E402
from datamate.llm import LLM  # noqa: E402
from datamate.runner import load_rulebook  # noqa: E402
from datamate.solve import STOPPED, _echo  # noqa: E402

FORBIDDEN = ('public_test', 'private_test')


def _jsonl(path):
    return [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]


def run_split(run: Path) -> Path:
    cfg = run / 'config.yaml'
    text = cfg.read_text(encoding='utf-8') if cfg.exists() else ''
    for line in text.splitlines():
        if line.strip().startswith('split:'):
            return Path(line.split(':', 1)[1].strip())
    raise SystemExit(f'{run}: pass --split')


DISTILL = ('You get a question about a shop\'s data, the private notes an analyst wrote while solving it, and the '
           'program they wrote next. Rewrite the notes as the reasoning written just before that program, in the notes\' '
           'language. Line 1: "ASKED: <measure> of <entity> for <period>". Then the steps in order: each rule applied and '
           'how, the full label mapping of every status column filtered, the traps checked, the approach. Only what the '
           'notes and the program support; never mention notes, drafts or another person; no answer type line; no code block; plain text; at '
           'most 1500 characters, much shorter for a simple question.')


class Distiller:
    """Teacher thinking -> the visible reasoning of the action (cached by content): the student, run without
    thinking, learns to write its reasoning before the code."""
    def __init__(self, config: Path, cache_dir: Path):
        load_dotenv()
        cfg = load_config(config)['llm']
        self.llm = LLM({**cfg, 'max_tokens': 2048, 'max_comment_lines': 0})
        self.cache = cache_dir / 'distill'
        self.cache.mkdir(parents=True, exist_ok=True)

    def __call__(self, job):
        question, thinking, action = job
        key = hashlib.sha1(json.dumps([question, thinking, prompt.render_action(action)], ensure_ascii=False).encode()).hexdigest()
        path = self.cache / f'{key}.txt'
        if path.exists():
            return path.read_text(encoding='utf-8')
        user = f"QUESTION: {question}\n\nNOTES:\n{thinking[:30000]}\n\nPROGRAM (answer type {action['answer_type']}):\n{action.get('code', '(none: a decision)')}"
        try:
            text = self.llm.chat([{'role': 'system', 'content': DISTILL}, {'role': 'user', 'content': user}],
                                 deadline=time.monotonic() + 300).text.strip().strip('`').strip()
        except Exception as exc:                      # noqa: BLE001 - the teacher's own plan stays
            print(f'distill failed: {type(exc).__name__}: {str(exc)[:200]}', file=sys.stderr)
            return None
        if not text.startswith('ASKED') or '```' in text or len(text) > 2500:
            print(f'distill rejected ({len(text)} chars): {text[:80]!r}', file=sys.stderr)
            return None
        path.write_text(text, encoding='utf-8')
        return text


def samples(run: Path, split: Path, cache_dir: Path, plans=None, jobs=None):
    """plans: (id, turn) -> distilled reasoning, used in the completion and in the history of later turns.
    jobs: when a list, collect (key, (question, thinking, action)) for every action with teacher thinking, yield nothing."""
    if any(f in str(split) for f in FORBIDDEN):
        raise SystemExit('refusing to build training samples from a test split')
    cfg = load_config(run / 'config.yaml') if (run / 'config.yaml').exists() else load_config()
    max_calls = cfg['agent']['max_calls']
    questions = {q['id']: q for q in _jsonl(split / 'questions.jsonl')}
    gold = {a['id']: a for a in _jsonl(split / 'answers.jsonl')}
    rulebook, _, changed, system = load_rulebook(split / 'rulebook.md')
    saved = run / 'system_prompt.md'
    if saved.exists():
        system = saved.read_text(encoding='utf-8')
    subs = {s['id']: s for s in _jsonl(run / 'submission.jsonl')} if (run / 'submission.jsonl').exists() else {}
    shops = {}
    for path in sorted((run / 'logs').glob('*.json')):
        log = json.loads(path.read_text(encoding='utf-8'))
        qid = log['id']
        q, g = questions.get(qid), gold.get(qid)
        if q is None or g is None:
            continue
        pred = subs.get(qid) or {'type': log.get('type'), 'answer': log.get('answer')}
        if not correct(pred, g):
            continue
        b = log['business_id']
        if b not in shops:
            business = load_business(split / 'data' / b, split / 'calendar.csv', cache_dir)
            shops[b] = (business, build_catalog(business, rulebook, changed))
        business, catalog = shops[b]
        trace = log.get('trace', [])
        outputs = {e['turn']: e for e in trace if e['event'] == 'model'}
        obs = {e['turn']: e['observation'] for e in trace if e['event'] == 'observation'}
        last_turn = max(outputs) if outputs else -1
        history = []
        matches = lookup(q['question'], business)
        for t in sorted(outputs):
            e, terminal = outputs[t], t == max_calls - 1
            try:
                action = {'action': 'invalid'} if e['finish'] in STOPPED else prompt.parse_action(e['output'], terminal)
            except prompt.ActionError:
                action = {'action': 'invalid'}
            if action['action'] != 'invalid' and e.get('reasoning'):
                if jobs is not None:
                    jobs.append(((qid, t), (q['question'], e['reasoning'], action)))
                elif plans and plans.get((qid, t)):
                    action = {**action, 'plan': plans[(qid, t)]}
            explored_ok = action.get('answer_type') == prompt.EXPLORE and t in obs and 'error' not in obs[t]
            keep = jobs is None and action['action'] != 'invalid' and (t == last_turn or explored_ok)
            if keep:
                msgs = prompt.messages(catalog, q['question'], q['as_of_date'], matches, history, max_calls - t,
                                       terminal, system)
                yield {'id': qid, 'turn': t, 'business_id': b, 'messages': msgs,
                       'completion': prompt.render_action(action),
                       'meta': {'run': run.name, 'calls': log.get('calls'), 'type': g['type'], 'final': t == last_turn}}
            if t in obs:
                history.append((_echo(action), obs[t]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', required=True, action='append')
    ap.add_argument('--split')
    ap.add_argument('--out', required=True)
    ap.add_argument('--cache', default=str(ROOT / 'outputs' / 'cache'))
    ap.add_argument('--distill', metavar='CONFIG', help='teacher config: rewrite its thinking as the visible reasoning')
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    n, distilled = 0, 0
    with open(a.out, 'w', encoding='utf-8') as f:
        for r in a.run:
            run = Path(r)
            split = Path(a.split) if a.split else run_split(run)
            plans = None
            if a.distill:
                jobs = []
                list(samples(run, split, Path(a.cache), jobs=jobs))
                with ThreadPoolExecutor(a.workers) as pool:
                    texts = list(pool.map(Distiller(Path(a.distill), Path(a.cache)), [j for _, j in jobs]))
                plans = {k: t for (k, _), t in zip(jobs, texts) if t}
                distilled += len(plans)
            for s in samples(run, split, Path(a.cache), plans=plans):
                f.write(json.dumps(s, ensure_ascii=False, default=str) + '\n')
                n += 1
    print(f'{n} samples -> {a.out}' + (f' ({distilled} turns with distilled reasoning)' if a.distill else ''))


if __name__ == '__main__':
    main()
