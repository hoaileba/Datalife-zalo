"""Write the prompt the model gets as ONE Markdown file for review (no model call).

From a question (built by the same code as a real run: load_rulebook -> build_catalog -> prompt.messages), with the
model's outputs of the newest run that answered it (gen.teacher record or runner log, under outputs/teacher and
outputs/runs; --run picks one, --prompt-only skips them):
    PYTHONIOENCODING=utf-8 PYTHONPATH=src:. python scripts/prompt_md.py --split data/train --id q_3c3a0109c0b5 --out p.md
    ... --split data/train --business biz_123 --index 5      the 6th question of that shop
    ... --rulebook <file>                                      another rulebook (changed lines, cookbook without them)
From a gen.teacher record (every call as it was sent, with the teacher's thinking, output and the sandbox runs):
    python scripts/prompt_md.py --record outputs/teacher/smoke/logs/q_3c3a0109c0b5.json --out p.md
    ... --no-reasoning   leave the thinking out

The system prompt is written once (section 1); each call shows the messages after it. Refuses test splits.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

from datamate import prompt  # noqa: E402
from datamate.catalog import build_catalog, lookup  # noqa: E402
from datamate.config import load_config  # noqa: E402
from datamate.data import load_business  # noqa: E402
from datamate.runner import load_rulebook, read_jsonl  # noqa: E402
from datamate.solve import STOPPED, _echo  # noqa: E402

TEST_SPLITS = ('public_test', 'private_test')


def fence(text, lang=''):
    """A code fence longer than any backtick run inside the text, so the content is shown verbatim."""
    text = '' if text is None else str(text)
    n = max([3] + [len(m) + 1 for m in re.findall(r'`{3,}', text)])
    return f"{'`' * n}{lang}\n{text}\n{'`' * n}"


def head(q, extra=()):
    rows = [('id', q.get('id')), ('business_id', q.get('business_id')), ('as_of', q.get('as_of_date') or q.get('as_of')),
            *extra]
    return '\n'.join(f'- **{k}**: {v}' for k, v in rows if v is not None) + f"\n\n> {q.get('question')}\n"


def messages_md(msgs, system_written):
    """The messages of one call; the system prompt points to section 1 when it is the one written there."""
    out = []
    for i, m in enumerate(msgs):
        content = m.get('content')
        if m['role'] == 'system' and (content is None or content == system_written):
            out.append(f'#### [{i}] system\n\n*(system prompt ở mục 1, {m.get("chars") or len(content or "")} ký tự)*\n')
        else:
            out.append(f"#### [{i}] {m['role']} ({len(content or '')} ký tự)\n\n{fence(content)}\n")
    return '\n'.join(out)


def from_question(a):
    split = Path(a.split)
    if any(t in str(split.resolve()) for t in TEST_SPLITS):
        raise SystemExit('refusing a test split')
    cfg = load_config(a.config)
    rulebook, stats, changed, system = load_rulebook(Path(a.rulebook) if a.rulebook else split / 'rulebook.md')
    qs = read_jsonl(split / 'questions.jsonl')
    if a.id:
        q = next((x for x in qs if x.get('id') == a.id), None) or sys.exit(f'{a.id} not in {split}')
    else:
        q = [x for x in qs if x.get('business_id') == a.business][a.index]
    cache = Path(cfg['run']['cache_dir']); cache = cache if cache.is_absolute() else ROOT / cache
    business = load_business(split / 'data' / q['business_id'], split / 'calendar.csv', cache)
    catalog = build_catalog(business, rulebook, changed)
    max_calls = cfg['agent']['max_calls']
    msgs = prompt.messages(catalog, q['question'], q['as_of_date'], lookup(q['question'], business), [], max_calls,
                           max_calls == 1, system)
    gold = {g['id']: g for g in read_jsonl(split / 'answers.jsonl')}.get(q['id']) if (split / 'answers.jsonl').exists() else None
    record = None if a.prompt_only else find_record(q['id'], a.run)
    if record:
        rec = load_record(record, q, split, catalog, business, system, max_calls)
        return render_record(rec, record, system, a, gold)
    parts = [f"# Prompt: {q['id']}\n", head(q, [('split', str(split)), ('rulebook', json.dumps(stats)),
                                                 ('gold', json.dumps(gold, ensure_ascii=False) if gold else None)]),
             f'## 1. System prompt ({len(system)} ký tự)\n', fence(system, 'markdown'), '',
             f'## 2. Messages của lượt gọi đầu ({len(msgs)} message, {sum(len(m["content"]) for m in msgs)} ký tự)\n',
             messages_md(msgs, system)]
    return '\n'.join(parts)


def find_record(qid, run=None):
    """The newest log of this question: in --run, else under outputs/teacher and outputs/runs."""
    roots = [Path(run)] if run else [*ROOT.glob('outputs/teacher/*'), *ROOT.glob('outputs/runs/*')]
    hits = [p for r in roots for p in (r / 'logs').glob(f'{qid}*.json')]
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def load_record(path, q, split, catalog, business, system, max_calls):
    """A gen.teacher record as is; a runner log gets its llm_calls rebuilt from the trace (messages by prompt.messages)."""
    r = json.loads(Path(path).read_text(encoding='utf-8'))
    if r.get('llm_calls') is not None:
        return r
    trace = r.get('trace', [])
    obs = {e['turn']: e['observation'] for e in trace if e.get('event') == 'observation'}
    history, calls, matches = [], [], lookup(q['question'], business)
    for e in [e for e in trace if e.get('event') == 'model']:
        t, terminal = e['turn'], e['turn'] == max_calls - 1
        msgs = prompt.messages(catalog, q['question'], q['as_of_date'], matches, history, max_calls - t, terminal, system)
        calls.append({'index': t, 'messages': msgs, 'output': e.get('output'), 'reasoning': e.get('reasoning'),
                      'finish': e.get('finish'), 'seconds': e.get('seconds'),
                      'tokens': {'prompt': (e.get('usage') or {}).get('prompt_tokens'),
                                 'completion': (e.get('usage') or {}).get('completion_tokens')}})
        try:
            action = {'action': 'invalid'} if e.get('finish') in STOPPED else prompt.parse_action(e.get('output') or '', terminal)
        except prompt.ActionError:
            action = {'action': 'invalid'}
        if t in obs:
            history.append((_echo(action), obs[t]))
    gold = r.get('gold') or ({g['id']: g for g in read_jsonl(split / 'answers.jsonl')}.get(q['id'])
                             if (split / 'answers.jsonl').exists() else None)
    if gold and 'outcome' not in r:
        from datamate.eval import correct
        r['outcome'] = 'abstain' if r.get('type') == 'abstain' else 'correct' if correct(r, gold) else 'wrong'
    return {**r, 'question': q['question'], 'question_row': q, 'llm_calls': calls, 'input': {'model': None},
            'gold': gold, 'sample': 0}


def from_record(a):
    path = Path(a.record)
    r = json.loads(path.read_text(encoding='utf-8'))
    run = path.parent.parent
    system = (run / 'system_prompt.md').read_text(encoding='utf-8') if (run / 'system_prompt.md').exists() else None
    return render_record(r, path, system, a)


def render_record(r, path, system, a, gold=None):
    t = r.get('totals') or {
        'llm_calls': len(r.get('llm_calls', [])),
        **{f'{n}_tokens': sum((e.get('usage') or {}).get(f'{n}_tokens') or 0 for e in r.get('trace', []) if e.get('event') == 'model')
           for n in ('prompt', 'completion')},
        'reasoning_tokens': sum(((e.get('usage') or {}).get('completion_tokens_details') or {}).get('reasoning_tokens') or 0
                                for e in r.get('trace', []) if e.get('event') == 'model')}
    gold = r.get('gold') or gold
    parts = [f"# Record: {r['id']} (sample {r.get('sample', 0)})\n", f'- **log**: {path}\n',
             head({**(r.get('question_row') or {}), 'question': r.get('question')},
                  [('model', r['input'].get('model')), ('outcome', r.get('outcome')), ('reason', r.get('reason')),
                   ('answer', json.dumps({'type': r.get('type'), 'answer': r.get('answer')}, ensure_ascii=False)),
                   ('gold', json.dumps(gold, ensure_ascii=False) if gold else None),
                   ('calls', t.get('llm_calls')), ('tokens prompt/completion/reasoning',
                                                   f"{t.get('prompt_tokens')}/{t.get('completion_tokens')}/{t.get('reasoning_tokens')}"),
                   ('seconds', r.get('seconds'))])]
    if system:
        parts += [f'## 1. System prompt ({len(system)} ký tự)\n', fence(system, 'markdown'), '']
    else:
        parts += ['## 1. System prompt\n', f'*(không có {run}/system_prompt.md)*\n']
    execs = {}
    for e in r.get('trace', []):
        if e.get('event') in ('execution', 'observation'):
            execs.setdefault(e.get('turn'), []).append(e)
    for c in r.get('llm_calls', []):
        n = c['index']
        u = c.get('tokens') or {}
        parts += [f"## {n + 2}. Lượt gọi {n}  (finish={c.get('finish')}, {c.get('seconds')}s, prompt {u.get('prompt')} tok, "
                  f"completion {u.get('completion')} tok)\n", '### Input\n', messages_md(c.get('messages') or [], system)]
        if c.get('error'):
            parts += ['### Lỗi gọi model\n', fence(c['error'])]
        if c.get('reasoning') and not a.no_reasoning:
            parts += [f"### Thinking ({len(c['reasoning'])} ký tự)\n", fence(c['reasoning'])]
        parts += [f"### Output ({len(c.get('output') or '')} ký tự)\n", fence(c.get('output'))]
        for e in execs.get(n, []):
            if e['event'] == 'execution':
                info = ', '.join(f'{k}={e[k]}' for k in ('ok', 'answer_type', 'seconds') if e.get(k) is not None)
                parts += [f"### Chạy code ({info}{', explore' if e.get('explore') else ''})\n", fence(e.get('code'), 'python')]
                if e.get('result') is not None:
                    parts += ['Result:\n', fence(e['result'], 'json')]
                for k in ('stdout', 'trace'):
                    if e.get(k):
                        parts += [f'{k}:\n', fence(e[k])]
                if e.get('error'):
                    parts += ['error:\n', fence(json.dumps(e['error'], ensure_ascii=False, indent=1), 'json')]
                if e.get('issues'):
                    parts += ['issues:\n', fence('\n'.join(e['issues']))]
            else:
                parts += ['### Observation gửi lại model\n', fence(json.dumps(e['observation'], ensure_ascii=False, indent=1), 'json')]
        parts.append('')
    return '\n'.join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--record', help='a gen.teacher record (logs/<id>.json)')
    ap.add_argument('--split', help='folder with questions.jsonl, rulebook.md, calendar.csv, data/')
    ap.add_argument('--id')
    ap.add_argument('--business')
    ap.add_argument('--index', type=int, default=0)
    ap.add_argument('--rulebook')
    ap.add_argument('--config', default=str(ROOT / 'config.yaml'))
    ap.add_argument('--no-reasoning', action='store_true')
    ap.add_argument('--run', help='run folder whose log of this question is shown (default: the newest one found)')
    ap.add_argument('--prompt-only', action='store_true', help='only the prompt of the first call, no outputs')
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    if a.record:
        text = from_record(a)
    elif a.split and (a.id or a.business):
        text = from_question(a)
    else:
        raise SystemExit('pass --record, or --split with --id or --business')
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text, encoding='utf-8')
    print(f'{a.out}: {len(text)} chars, {text.count(chr(10))} lines')


if __name__ == '__main__':
    main()
