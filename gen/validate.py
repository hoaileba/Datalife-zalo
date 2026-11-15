"""Check a hand-off SFT package (gen.package) before it leaves: format, provenance, completions, lengths, split.

    python -m gen.validate outputs/sft/train_v1                     # fast checks (seconds)
    python -m gen.validate outputs/sft/train_v1 --rebuild --replay  # + prompts vs the current agent code,
                                                                    #   + final programs re-run against the gold

Errors (exit 1):
  - files: train/val jsonl + aligned meta, stats.json, README.md, val_questions.jsonl; file hashes match stats.json;
  - format: {"id", "prompt", "completion"}; prompt = system, user, (assistant, user)*; completion = one assistant
    message; ids unique across train and val;
  - provenance: no sample from a public/private test split; every id is a question of its source split; a rewritten
    train question (q_aug<k>_<x>) has its original in data/train;
  - completion: parses with datamate.prompt.parse_action and is its own normal form (render_action of the parse);
    a final turn is not an explore, an explore turn has a program;
  - prompt: the user message carries the sample's question, as_of and turn (later turns: a <turn> tag at the end);
  - lengths: every sample within the package max_len (recounted with the Gemma tokenizer when --recount);
  - split: no question group on both sides, no held-out shop in train; every val sample's question is in val_questions.jsonl;
  - --rebuild: each prompt equals what datamate.prompt.messages builds now (needs the source data);
  - --replay: each final program, re-run in the sandbox with the current host code, still gives the gold answer.
Warnings: estimated token counts, prompt drift recorded at build time, weak labels, empty val.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from datamate import prompt  # noqa: E402
from datamate.answer import COMPUTED  # noqa: E402
from gen.sft import AUG_ID, teacher_turns  # noqa: E402

FORBIDDEN = ('public_test', 'private_test')
FILES = ('train.jsonl', 'val.jsonl', 'train_meta.jsonl', 'val_meta.jsonl', 'stats.json', 'README.md', 'val_questions.jsonl')
FINAL_TYPES = (*COMPUTED, 'unanswerable', 'abstain')
NONFINAL_KINDS = ('looked', 'not_finalized')       # gen.sft.imitable: a look, a flagged answer later confirmed


def _jsonl(path: Path):
    with open(path, encoding='utf-8') as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                yield n, json.loads(line)


def _resolve(p):
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def _roles_ok(msgs):
    roles = [m.get('role') for m in msgs]
    if len(roles) < 2 or roles[0] != 'system' or roles[1] != 'user' or len(roles) % 2:
        return False
    return all(r == ('assistant' if i % 2 == 0 else 'user') for i, r in enumerate(roles[2:]))


class Report:
    def __init__(self):
        self.errors, self.warnings, self.counts = [], [], collections.Counter()

    def error(self, kind, detail):
        self.counts['error:' + kind] += 1
        if self.counts['error:' + kind] <= 5:                # five examples per kind, all counted
            self.errors.append(f'{kind}: {detail}')

    def warn(self, text):
        self.warnings.append(text)

    def result(self):
        extra = [f'{k[6:]}: {n} in all' for k, n in self.counts.items() if k.startswith('error:') and n > 5]
        return {'ok': not self.errors, 'errors': self.errors + extra, 'warnings': self.warnings, 'counts': dict(self.counts)}


def check(pkg, stats=None, rebuild=False, replay=False, recount=False, tokenizer=None, workers=8):
    """Validate the package folder; returns {'ok', 'errors', 'warnings', 'counts'}."""
    pkg, r = Path(pkg), Report()
    for name in FILES:
        if name != 'stats.json' and not (pkg / name).is_file():
            r.error('missing_file', name)
    if not (pkg / 'sft_lora.py').is_file():
        r.warn('sft_lora.py not in the package (train/sft_lora.py missing at build time)')
    from_file = stats is None
    if from_file:
        try:
            stats = json.loads((pkg / 'stats.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            r.error('stats', f'stats.json unreadable: {exc}')
            return r.result()
    if r.errors:
        return r.result()
    max_len = (stats.get('options') or {}).get('max_len')
    if from_file:
        for name, f in (stats.get('files') or {}).items():
            p = pkg / name
            if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() != f.get('sha256'):
                r.error('hash', f'{name} changed since the package was built')

    questions, sides, ids = {}, {}, set()
    groups, shops = {'train': set(), 'val': set()}, {'train': set(), 'val': set()}
    train_ids = {q['id'] for _, q in _jsonl(ROOT / 'data' / 'train' / 'questions.jsonl')} if (ROOT / 'data' / 'train' / 'questions.jsonl').exists() else None
    counter = None
    if recount:
        from gen.tokens import TokenCounter
        counter = TokenCounter(tokenizer, required=True)
    for side in ('train', 'val'):
        metas = list(_jsonl(pkg / f'{side}_meta.jsonl'))
        rows = list(_jsonl(pkg / f'{side}.jsonl'))
        sides[side] = []
        if len(metas) != len(rows):
            r.error('meta', f'{side}: {len(rows)} samples but {len(metas)} meta lines')
        if (stats.get('samples') or {}).get(side) not in (None, len(rows)):
            r.error('stats', f"{side}: stats.json says {stats['samples'][side]} samples, file has {len(rows)}")
        for (n, s), (_, m) in zip(rows, metas):
            where = f'{side}.jsonl:{n}'
            r.counts[f'{side}_samples'] += 1
            if set(s) != {'id', 'prompt', 'completion'}:
                r.error('format', f'{where}: keys {sorted(s)}')
                continue
            if m.get('key') != s['id']:
                r.error('meta', f'{where}: meta key {m.get("key")!r} != id {s["id"]!r}')
            if s['id'] in ids:
                r.error('duplicate_id', f'{where}: {s["id"]}')
            ids.add(s['id'])
            msgs, comp = s['prompt'], s['completion']
            if not isinstance(msgs, list) or not all(isinstance(x, dict) and set(x) == {'role', 'content'} and
                                                      isinstance(x['content'], str) and x['content'].strip() for x in msgs):
                r.error('format', f'{where}: prompt messages must be {{role, content}} with text')
                continue
            if not _roles_ok(msgs):
                r.error('roles', f'{where}: {[x["role"] for x in msgs]}')
            if not (isinstance(comp, list) and len(comp) == 1 and comp[0].get('role') == 'assistant'
                    and isinstance(comp[0].get('content'), str) and comp[0]['content'].strip()):
                r.error('format', f'{where}: completion must be one assistant message with text')
                continue
            text = comp[0]['content']
            # provenance
            split = m.get('split') or ''
            if any(f in split for f in FORBIDDEN) or any(f in str(m.get('run_path', '')) for f in FORBIDDEN):
                r.error('test_split', f'{where}: {split}')
                continue
            if split not in questions:
                qp = _resolve(split) / 'questions.jsonl'
                questions[split] = {q['id']: q for _, q in _jsonl(qp)} if qp.is_file() else None
                if questions[split] is None:
                    r.warn(f'{split}: source split not found here, ids not checked against it')
            qs = questions[split]
            if qs is not None and m.get('id') not in qs:
                r.error('unknown_id', f'{where}: {m.get("id")} not in {split}/questions.jsonl')
            aug = AUG_ID.match(m.get('id') or '')
            if aug and f'q_{aug.group(1)}' not in (train_ids or ()) and f'q_{aug.group(1)}' not in (qs or {}):
                r.error('unknown_id', f'{where}: original of {m["id"]} in neither data/train nor its split')
            # completion
            terminal = m.get('turn') == (m.get('max_calls') or 3) - 1
            try:
                action = prompt.parse_action(text, terminal)
            except prompt.ActionError as exc:
                r.error('completion_parse', f'{where}: {exc}')
                continue
            if prompt.render_action(action) != text:
                r.error('completion_form', f'{where}: not in the normal form render_action writes')
            if action.get('action') != 'python' or (m.get('final') and 'result' not in (action.get('code') or '')):
                r.error('completion_type', f'{where}: no program (a final turn ends with result = {{...}})')
            if m.get('final'):
                if m.get('answer_type') not in FINAL_TYPES:
                    r.error('completion_type', f'{where}: final turn with answer type {m.get("answer_type")}')
                elif m.get('gold_type') and m['answer_type'] != m['gold_type']:
                    r.counts['final_type_differs_from_gold'] += 1
            elif m.get('answer_type') not in NONFINAL_KINDS:
                r.error('completion_type', f'{where}: non-final turn that is neither a look nor a confirmed answer')
            # prompt content
            user = msgs[1]['content']
            if m.get('question') and m['question'].strip() not in user:
                r.error('prompt_question', f'{where}: question text not in the user message')
            if m.get('as_of') and f'as_of="{m["as_of"]}"' not in user:
                r.error('prompt_question', f'{where}: as_of {m["as_of"]} not in the user message')
            calls, turn = m.get('max_calls') or 3, m.get('turn') or 0
            last = re.sub(r'\n?<last_turn>.*?</last_turn>\s*$', '', msgs[-1]['content'], flags=re.S)   # the last turn's note
            if f'turn="1/{calls}"' not in user or (turn and not last.endswith(f'<turn>{turn + 1}/{calls}</turn>')):
                r.error('prompt_question', f'{where}: turn tags do not match turn {turn}')
            if isinstance(m.get('turn'), int) and len(msgs) > 2 + 2 * m['turn']:
                r.error('roles', f'{where}: {len(msgs)} messages for turn {m["turn"]}')
            # lengths
            total = m.get('total_tokens')
            if counter is not None:
                p, c = counter.count(msgs, text)
                if (p, c) != (m.get('prompt_tokens'), m.get('completion_tokens')):
                    r.counts['recount_differs'] += 1
                total = p + c
            if max_len and (total is None or total > max_len):
                r.error('too_long', f'{where}: {total} tokens > max_len {max_len}')
            groups[side].add(m.get('group'))
            shops[side].add(m.get('shop'))
            r.counts[f'{side}_drift'] += bool(m.get('prompt_drift'))
            r.counts['rebuild_failed'] += bool(m.get('rebuild_error'))
            r.counts[f'{side}_weak'] += bool(m.get('weak'))
            r.counts[f'{side}_estimated_tokens'] += not m.get('tokens_exact')
            sides[side].append((s, m))
    both = groups['train'] & groups['val']
    if both:
        r.error('group_leak', f'{len(both)} question groups on both sides, e.g. {sorted(both)[:3]}')
    both = shops['train'] & set(stats.get('val_shops') or ())     # held-out shops; --val-frac splits inside shops
    if both:
        r.error('shop_leak', f'{len(both)} held-out shops in train, e.g. {sorted(both)[:3]}')
    if (pkg / 'val_questions.jsonl').is_file():
        listed = {(q['split'], q['id']) for _, q in _jsonl(pkg / 'val_questions.jsonl')}
        missing = [m['id'] for _, m in sides['val'] if (m.get('split'), m.get('id')) not in listed]
        if missing:
            r.error('val_questions', f'{len(missing)} val samples not in val_questions.jsonl, e.g. {missing[:3]}')
        leaked = [m['id'] for _, m in sides['train'] if (m.get('split'), m.get('id')) in listed]
        if leaked:
            r.error('val_questions', f'{len(leaked)} train samples are val questions, e.g. {leaked[:3]}')
    if not sides['val']:
        r.warn('val is empty')
    if r.counts['train_estimated_tokens'] + r.counts['val_estimated_tokens']:
        r.warn('token counts are estimates (no Gemma tokenizer at build time): python -m gen.tokens --fetch, '
               'pip install tokenizers jinja2, rebuild')
    if r.counts['train_drift'] + r.counts['val_drift']:
        r.warn(f"{r.counts['train_drift'] + r.counts['val_drift']} prompts differed from the recorded ones at build time "
               '(the agent code changed after the teacher run; --prompts current used the new ones)')
    if r.counts['rebuild_failed']:
        r.warn(f"{r.counts['rebuild_failed']} prompts could not be rebuilt at build time (source data missing?): recorded ones kept")
    if r.counts['final_type_differs_from_gold']:
        r.warn(f"{r.counts['final_type_differs_from_gold']} final turns declare a type other than the gold's (retyped answers)")
    if rebuild:
        _rebuild(sides, r)
    if replay:
        _replay(sides, r, workers)
    return r.result()


def _record(m):
    return json.loads((_resolve(m['run_path']) / m['record']).read_text(encoding='utf-8'))


def _rebuild(sides, r):
    from gen.package import Split
    splits = {}
    for side, rows in sides.items():
        for s, m in rows:
            try:
                rec = _record(m)
                split = splits.setdefault(m['split'], Split(_resolve(m['split']), ROOT / 'outputs' / 'cache'))
                current = split.rebuild(rec, teacher_turns(rec), m['turn'])
            except Exception as exc:                        # noqa: BLE001
                r.error('rebuild', f'{s["id"]}: {type(exc).__name__}: {exc}'[:300])
                continue
            r.counts['rebuilt'] += 1
            if current != s['prompt']:
                r.error('prompt_mismatch', f'{side} {s["id"]}: differs from datamate.prompt.messages now')


def _replay(sides, r, workers):
    from datamate.answer import AnswerError, finalize, retype, submission_line
    from datamate.eval import correct
    from datamate.sandbox import Limits, execute
    from gen.package import Split
    splits, gold = {}, {}
    jobs = []
    for side, rows in sides.items():
        for s, m in rows:
            if not m.get('final'):
                continue
            action = prompt.parse_action(s['completion'][0]['content'])
            if action['action'] != 'python':
                continue                                       # a confirmation or a decision: no program of its own
            jobs.append((s, m, action))

    for _, m, _ in jobs:                                      # shared state before the threads start
        if m['split'] not in splits:
            splits[m['split']] = Split(_resolve(m['split']), ROOT / 'outputs' / 'cache')
            splits[m['split']].agent()
            p = _resolve(m['split']) / 'answers.jsonl'
            gold[m['split']] = {g['id']: g for _, g in _jsonl(p)} if p.is_file() else {}

    def one(job):
        s, m, action = job
        businesses, _ = splits[m['split']].agent()
        _, _, tables = businesses.get(m['business_id'])
        run = execute(action['code'], tables, m['as_of'], Limits(wall_seconds=60))
        if not run.ok:
            return s['id'], 'error'
        try:
            res = run.result if isinstance(run.result, dict) else {}
            if res.get('type') in ('unanswerable', 'abstain'):
                kind, answer = res['type'], None
            else:
                kind, answer = retype(res.get('type'), finalize(res.get('type'), res.get('answer')))
        except AnswerError:
            return s['id'], 'invalid'
        g = gold[m['split']].get(m['id'])
        return s['id'], 'correct' if g and correct(submission_line(m['id'], kind, answer), g) else 'wrong'
    with ThreadPoolExecutor(workers) as pool:
        for sid, outcome in pool.map(one, jobs):
            r.counts['replay_' + outcome] += 1
            if outcome != 'correct':
                r.error('replay', f'{sid}: {outcome} with the current host code')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('package')
    ap.add_argument('--rebuild', action='store_true', help='rebuild every prompt with the current agent code and compare')
    ap.add_argument('--replay', action='store_true', help='re-run every final program and compare with the gold')
    ap.add_argument('--recount', action='store_true', help='recount tokens with the Gemma tokenizer')
    ap.add_argument('--tokenizer')
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args(argv)
    res = check(a.package, rebuild=a.rebuild, replay=a.replay, recount=a.recount, tokenizer=a.tokenizer, workers=a.workers)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if not res['ok']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
