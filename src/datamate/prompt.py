"""Messages for the model and parsing of its action (prompt v5, docs/PROMPT_V5.md). The model writes plain text:
ASKED / RULES / PLAN (or CAUSE first after a failure, NEED for a look), then ONE ```python block that ends with
result = {"type": ..., "answer": ...}: the program decides the answer type, a look, unanswerable or abstain
(shape.typed). No JSON around code: code inside JSON strings costs small models accuracy and escaping errors.

In:  catalog (catalog.py: shop tables, readme, rulebook), question, as_of, lookup matches, history of (action, observation).
Out: chat messages; `parse_action(raw)` -> {'action': 'python', 'plan', 'code'};
     `render_action(action)` -> the same text form (history, SFT samples).
Invariant: one system prompt for every set (no per-set cookbook); the first user message is
<rulebook> (same for a set) + <shop> (same for a shop) before the per-question tags (prefix cache).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pandas as pd

from .notes import NOTE_PARTS, TABLE_NOTES
from .values import fold

ASSETS = Path(__file__).with_name('assets')


def _read(name):
    """A prompt file in assets/, with its {{include file}} lines expanded."""
    text = ASSETS.joinpath(name).read_text(encoding='utf-8')
    return re.sub(r'\{\{include ([\w.]+)\}\}', lambda m: _read(m.group(1)).strip(), text)


SYSTEM = _read('prompt.md').replace('{{table_notes}}', TABLE_NOTES)


def system_prompt(gone=frozenset()):
    """The one system prompt (`gone` is ignored: kept for the gen/ callers of the v4 per-set prompt)."""
    return SYSTEM


LAST_TURN = ('This is the last turn: a look, a new (unchecked) unanswerable or a new answer the host flags (section 2 lists what '
             'it flags) cannot be submitted and ends as abstain; a flagged result resent unchanged with "checked": True is submitted.')
EXPLORE = 'explore'                        # internal name of a look ({"type": "look"}): shown, never submitted
FENCE = re.compile(r'```[ \t]*(?:python|py)?[ \t]*\n', re.I)


class ActionError(Exception):
    pass


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def render_action(action):                           # the text form of an action, as the model writes it
    if action.get('action') != 'python':
        return '(output not in the required form)'
    return f"{(action.get('plan') or '').strip()}\n```python\n{action['code'].strip()}\n```".strip()


def _tag(tag, body, **attrs):
    return f'<{tag}' + ''.join(f' {k}="{v}"' for k, v in attrs.items() if v not in (None, '', [], {})) + f'>\n{str(body).strip()}\n</{tag}>'


def _flat(x):                                         # one item as plain text: `key: value; ...` for a dict
    if isinstance(x, dict):
        return '; '.join(f'{k}: {_flat(v)}' for k, v in x.items())
    if isinstance(x, (list, tuple)):                 # groups of spellings: "a / b | c / d"
        return (' | ' if any(isinstance(v, (list, tuple)) for v in x) else ' / ').join(_flat(v) for v in x)
    return str(x)


def _lines(value):                                   # one line per item; a dict: `key: item` lines
    if isinstance(value, dict):
        return '\n'.join(f'{k}: {_flat(x)}' for k, v in value.items() for x in (v if isinstance(v, list) else [v]))
    return '\n'.join(_flat(x) for x in (value if isinstance(value, list) else [value]))


def _column(c):                                       # numbers and dates: the range says it, no values listed
    kind = c.get('about') or c.get('type') or ''
    parts = [c['name'], kind, f"{c['distinct']} distinct" if 'distinct' in c else None,
             f"{c['blank']} blank" if c.get('blank') else None, c.get('range'), None if kind.startswith(('number', 'date')) else
             'values: ' + '; '.join(f'{v} ×{n}' for v, n in c['all_values']) if 'all_values' in c else
             'e.g. ' + '; '.join(map(str, c['examples'])) if c.get('examples') else None]
    return ' | '.join(str(p) for p in parts if p)


def _notes(notes):                                     # joins: only the ones where some values do not join
    joins = [f"{j['key']} (master {j['master']}): " + '; '.join(f'{k}: {v}' for k, v in j['others'].items() if not str(v).startswith('all '))
             for j in notes.get('joins', []) if any(not str(v).startswith('all ') for v in j['others'].values())]
    if joins:
        return {**notes, 'joins': joins}
    note = notes.get('note', '').replace(f"joins: {NOTE_PARTS['joins']} ", '').replace(f" joins: {NOTE_PARTS['joins']}", '')
    return {**{k: v for k, v in notes.items() if k != 'joins'}, 'note': note}


def _lookup(matches):                                 # one line per stored value; its other spellings on the same line
    groups = {}
    for m in matches:
        groups.setdefault((m['table'], m['column'], fold(m['value']), m['match']), []).append(m)
    return '\n'.join(f"{t}.{c} = " + ' | '.join(f"'{m['value']}' ({m['rows']} rows" + ''.join(f"; {col} {'/'.join(vals)}" for col, vals in (m.get('codes') or {}).items()) + ')' for m in ms) + f" ({how}"
                     + (f'; written {len(ms)} ways: match the ones you mean with isin; a different tone mark can be another name' if len(ms) > 1 else '') + ')' for (t, c, _, how), ms in groups.items())


def render_state(catalog, question, as_of, lookup, remaining_calls, terminal_only, turn=1):
    """<rulebook> (same for a set), <shop> (same for a shop), then the question's own tags (prefix cache)."""
    tables = [_tag('table', '\n'.join([_column(c) for c in t['columns']] + [f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else _flat(v)}" for k, v in t.items() if k not in (
        'table', 'rows', 'source_files', 'columns', 'exact_duplicate_rows')]), name=t['table'], rows=t['rows'],
        files=', '.join(t.get('source_files', [])), exact_duplicate_rows=t.get('exact_duplicate_rows')) for t in catalog.get('schemas', [])]
    groups = [f"{g['table']}.{g['column']} ({g['kind']}): " + '; '.join(f'{k} = {v}' for k, v in g['labels'].items())
              for g in catalog.get('label_groups', [])]
    shop = [*tables, *([_tag('label_groups', '\n'.join(groups))] if groups else []),
            *[_tag(k, _lines(_notes(catalog[k]) if k == 'data_notes' else catalog[k])) for k in ('data_notes', 'unreadable_files') if catalog.get(k)],
            _tag('readme', catalog.get('readme') or '(empty)')]
    day = pd.Timestamp(as_of)
    return '\n'.join([_tag('rulebook', catalog.get('rulebook') or '(empty)'), _tag('shop', '\n'.join(shop)),
                      _tag('question', question, as_of=day.strftime('%Y-%m-%d'), weekday=day.day_name(),
                           turn=f'{turn}/{turn + remaining_calls - 1}'),
                      _tag('data_lookup', _lookup(lookup) or 'none')])


def render_observation(observation):                 # <result status=...>: <error>, <issues>, <output> (stdout), <trace>, <next>
    parts = [_tag({'stdout': 'output', 'result': 'value'}.get(k, k), _lines(v)) for k, v in observation.items() if k != 'status' and v not in (None, '', [])]
    return _tag('result', '\n'.join(parts), status=observation.get('status'))


def messages(catalog, question, as_of, lookup, history, remaining_calls, terminal_only, system=SYSTEM):
    out = [{'role': 'system', 'content': system},
           {'role': 'user', 'content': render_state(catalog, question, as_of, lookup, remaining_calls + len(history), terminal_only)}]
    for action, observation in history:
        out.append({'role': 'assistant', 'content': render_action(action)})
        out.append({'role': 'user', 'content': render_observation(observation)})
    if history:                                       # the turn count of the first message stays fixed (prefix cache)
        out[-1]['content'] += f'\n<turn>{len(history) + 1}/{len(history) + remaining_calls}</turn>'
        if remaining_calls == 1:
            out[-1]['content'] += f'\n<last_turn>{LAST_TURN}</last_turn>'
    return out


# ---------------------------------------------------------------- parsing
def _ends_with_result(code):    # only expressions after the last `result =` (a cut program may set result early, then refine it)
    def assigns(node):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else []
        return any(isinstance(t, ast.Name) and t.id == 'result' for t in targets)
    body = ast.parse(code).body
    last = max((i for i, node in enumerate(body) if assigns(node)), default=None)
    return last is not None and all(isinstance(node, ast.Expr) for node in body[last + 1:])


def _cut_code(body):                                 # a block cut by the token cap: its complete lines, if they end with result
    lines = body.split('\n')
    for code in ('\n'.join(lines).rstrip(), '\n'.join(lines[:-1]).rstrip()):     # the last line may be cut mid-way
        try:
            if code and _ends_with_result(code):
                return code
        except SyntaxError:
            continue
    raise ActionError('The ```python block was not closed and the program is not complete: write a shorter program.')


def parse_action(raw, terminal_only=False):          # terminal_only: kept for callers; a last-turn program runs too
    """The reasoning, then the first ```python block; text after the block is dropped."""
    text = (raw or '').strip()
    fence = FENCE.search(text)
    if not fence:
        raise ActionError('Every reply ends with ONE ```python block whose last line is result = {"type": ..., "answer": ...} '
                          '(also for a look, unanswerable or abstain).')
    body = text[fence.end():]
    end = body.find('```')
    code = (body[:end] if end >= 0 else _cut_code(body)).strip('\n')
    if not code.strip():
        raise ActionError('The ```python block is empty.')
    return {'action': 'python', 'plan': text[:fence.start()].strip(), 'code': code}
