"""SFT samples from v4 runs, in the one sample format used end to end (gen.package, the hand-off package,
train/sft_lora.py):

    {"id": <sample key>, "prompt": [messages], "completion": [{"role": "assistant", "content": <reply text>}], "meta": {...}}

`prompt` is what the agent sends the model at that turn (system prompt, user message with the catalog, earlier turns
and their observations); `completion` is the model's reply normalised to the text form the agent parses
(`prompt.render_action`), which is also how the agent echoes it in the history of later turns.

Kept turns of a question whose final answer matches the gold: the turn that produced the submitted answer, and
earlier `explore` turns that ran cleanly. Failed turns are not imitated, but they stay in the history of later turns
(the model learns to recover from them). Never on public/private test runs.

python -m gen.sft --teacher outputs/teacher/<run>     # teacher run -> <run>/sft/ (gen.teacher writes it itself)
python -m gen.sft --run outputs/runs/<run> [--split data/train] --out sft.jsonl    # runner logs (rebuilt prompts)
The hand-off package (several runs, filters, train/val split, README, validation): python -m gen.package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
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
                yield {'id': f'{run.name}/{qid}/s0/t{t}', 'prompt': msgs,
                       'completion': [{'role': 'assistant', 'content': prompt.render_action(action)}],
                       'meta': {'schema': SFT_SCHEMA, 'id': qid, 'group': group_of(qid), 'business_id': b, 'turn': t,
                                'final': t == last_turn, 'run': run.name, 'split': str(split), 'calls': log.get('calls'),
                                'gold_type': g['type'], 'answer_type': action.get('answer_type'), 'source': 'runner_log'}}
            if t in obs:
                history.append((_echo(action), obs[t]))


# ---------- teacher runs (gen.teacher): the exact messages sent ----------

SFT_SCHEMA = 'datamate_sft/v2'
AUG_ID = re.compile(r'^q_aug\d+_(.+)$')


def group_of(qid, orig=None):
    """Question group for the train/val split: every rewrite of one question goes to the same side. An augmented
    copy `q_aug<k>_<x>` (gen.augment_train) belongs with its original `q_<x>`; other generators give `orig_id`."""
    if orig:
        return orig
    m = AUG_ID.match(qid or '')
    return f'q_{m.group(1)}' if m else qid


def parse_turn(event, terminal):
    """The action of one model turn, read as solve read it (a stopped or unreadable reply is `invalid`)."""
    if event.get('finish') in STOPPED:
        return {'action': 'invalid'}
    try:
        return prompt.parse_action(event.get('output') or '', terminal)
    except prompt.ActionError:
        return {'action': 'invalid'}


def teacher_turns(rec):
    """Each model turn of a teacher record: {turn, action, observation, final, keep, why}. A turn is kept when the
    record is correct, its reply parses, the reply ended normally (finish `stop`), and it is either the final turn or
    an `explore` that ran cleanly; `why` names the first rule a dropped turn broke."""
    max_calls = (rec.get('input') or {}).get('max_calls') or 3
    trace = rec.get('trace') or []
    outputs = {e['turn']: e for e in trace if e.get('event') == 'model'}
    obs = {e['turn']: e['observation'] for e in trace if e.get('event') == 'observation'}
    last = max(outputs, default=-1)
    out = []
    for t in sorted(outputs):
        e = outputs[t]
        action = parse_turn(e, t == max_calls - 1)
        explored_ok = action.get('answer_type') == prompt.EXPLORE and t in obs and 'error' not in obs[t]
        why = ('not_correct' if not rec.get('correct') else 'invalid' if action['action'] == 'invalid'
               else f"finish_{e.get('finish')}" if e.get('finish') != 'stop'
               else None if t == last or explored_ok else 'failed_turn')
        out.append({'turn': t, 'action': action, 'observation': obs.get(t), 'final': t == last, 'keep': why is None,
                    'why': why, 'finish': e.get('finish')})
    return out


def history_of(turns, t):
    """The history solve built before turn t: each earlier (echoed action, observation)."""
    return [(_echo(x['action']), x['observation']) for x in turns if x['turn'] < t and x['observation'] is not None]


def weak_flags(rec):
    """Why a correct record may be right by luck (kept, flagged; gen.package --drop-weak drops them):
    unanswerable (graded by type only), boolean (a coin flip), zero (a 0 result also comes from filters that match
    nothing), no_program (decided without running any program)."""
    gold = rec.get('gold') or {}
    flags = []
    if gold.get('type') in ('unanswerable', 'boolean'):
        flags.append(gold['type'])
    ans = rec.get('answer')
    if rec.get('type') in ('number', 'percent') and isinstance(ans, (int, float)) and not isinstance(ans, bool) and ans == 0:
        flags.append('zero')
    if not any(e.get('event') == 'execution' for e in rec.get('trace') or []):
        flags.append('no_program')
    return flags


def _system_text(run: Path, digest: str, cache: dict):
    if digest not in cache:
        text = None
        for p in (run / 'system_prompts' / f'{digest[:16]}.md', run / 'system_prompt.md'):
            if p.exists():
                t = p.read_text(encoding='utf-8')
                if hashlib.sha256(t.encode('utf-8')).hexdigest() == digest:
                    text = t
                    break
        cache[digest] = text
    return cache[digest]


def recorded_messages(rec, run: Path, t, systems=None):
    """The messages of turn t exactly as sent (a system prompt stored by reference is read back and its hash checked)."""
    systems = {} if systems is None else systems
    calls = [c for c in rec.get('llm_calls') or [] if 'error' not in c]
    if t >= len(calls):
        raise ValueError(f'no recorded call: turn {t}')
    msgs = []
    for m in calls[t]['messages']:
        if 'content' not in m:
            text = _system_text(run, m.get('content_sha256', ''), systems)
            if text is None:
                raise ValueError(f"system prompt not saved in the run: {m.get('content_sha256', '')[:12]}")
            m = {'role': m['role'], 'content': text}
        msgs.append({'role': m['role'], 'content': m['content']})
    return msgs, calls[t]


def _sha1(x):
    return hashlib.sha1(json.dumps(x, ensure_ascii=False).encode('utf-8')).hexdigest()


def teacher_samples(rec, run: Path, systems=None):
    """Canonical SFT samples of one teacher record (empty when nothing is kept). Raises ValueError when the record
    cannot be used (missing call, system prompt not saved, call and trace disagree)."""
    run = Path(run)
    turns = teacher_turns(rec)
    inp = rec.get('input') or {}
    flags = weak_flags(rec)
    res = []
    for x in turns:
        if not x['keep']:
            continue
        t = x['turn']
        msgs, call = recorded_messages(rec, run, t, systems)
        model_event = next(e for e in rec['trace'] if e.get('event') == 'model' and e.get('turn') == t)
        if call.get('output') != model_event.get('output'):
            raise ValueError(f'call and trace disagree: turn {t}')
        if msgs[-1]['role'] != 'user' or msgs[0]['role'] != 'system':
            raise ValueError(f'unexpected roles: turn {t}')
        completion = prompt.render_action(x['action'])
        qid, k = rec['id'], rec.get('sample', 0)
        meta = {'schema': SFT_SCHEMA, 'id': qid, 'group': group_of(qid, (rec.get('question_row') or {}).get('orig_id')),
                'business_id': rec.get('business_id'), 'split': inp.get('split'), 'run': run.name,
                'run_id': rec.get('run_id'), 'record': f"logs/{rec['_file']}" if rec.get('_file') else None,
                'sample': k, 'turn': t, 'final': x['final'], 'turns': len(turns), 'max_calls': inp.get('max_calls') or 3,
                'answer_type': x['action'].get('answer_type'), 'gold_type': (rec.get('gold') or {}).get('type'),
                'reason': rec.get('reason'), 'calls': rec.get('calls'),
                'recovered': any(not y['keep'] and y['turn'] < t for y in turns), 'weak': flags,
                'question': rec.get('question'), 'as_of': rec.get('as_of'),
                'teacher': inp.get('model'), 'temperature': inp.get('temperature'), 'seed': inp.get('seed'),
                'system_sha256': hashlib.sha256(msgs[0]['content'].encode('utf-8')).hexdigest(),
                'teacher_prompt_tokens': (call.get('usage') or {}).get('prompt_tokens'),
                'prompt_chars': sum(len(m['content']) for m in msgs), 'completion_chars': len(completion),
                'prompt_sha1': _sha1(msgs), 'completion_sha1': _sha1(completion)}
        res.append({'id': f'{run.name}/{qid}/s{k}/t{t}', 'prompt': msgs,
                    'completion': [{'role': 'assistant', 'content': completion}], 'meta': meta})
    return res


def export_teacher(run: Path, out: Path | None = None, quiet=False):
    """<run>/sft/: the hand-off package of this one run, built from recorded prompts (gen.package; no data loading,
    so it is cheap enough to refresh during a run). The package for training: python -m gen.package."""
    from gen.package import build                  # late: gen.package imports this module
    run = Path(run)
    return build([run], Path(out) if out else run / 'sft', prompts='recorded', quiet=quiet)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--teacher', action='append', help='teacher run folder: write <run>/sft/ (no other option needed)')
    ap.add_argument('--run', action='append')
    ap.add_argument('--split')
    ap.add_argument('--out')
    ap.add_argument('--cache', default=str(ROOT / 'outputs' / 'cache'))
    ap.add_argument('--distill', metavar='CONFIG', help='teacher config: rewrite its thinking as the visible reasoning')
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    if a.teacher:
        for r in a.teacher:
            export_teacher(Path(r))
        return
    if not (a.run and a.out):
        raise SystemExit('pass --teacher <run>, or --run <runner run> --out <file>')
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
