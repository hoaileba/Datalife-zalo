"""Messages for the model and parsing of its action, written as plain text (reasoning, an "Answer type:" line, then
a ```python block; no JSON: code inside JSON strings costs small models accuracy and escaping errors).

In:  catalog (catalog.py), question, as_of, lookup matches, history of (action, observation).
Out: chat messages; `parse_action(raw)` -> validated action dict
     {'action': 'python', 'plan', 'answer_type', 'code'} or {'action': 'answer', 'plan', 'answer_type'};
     `render_action(action)` -> the same text form (history, SFT samples).
Invariant: the first user message starts with the business catalog, identical for every question of a business
(prefix cache); per-question fields come last.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from . import rules
from .answer import COMPUTED
from .notes import NOTE_PARTS
from .values import fold

ASSETS = Path(__file__).with_name('assets')


GONE_NOTE = (' (THIS SET CHANGED OR DROPPED THIS RULE: follow rulebook_changes for it; this recipe stays only for the '
             'recipes that refer to it by name or by its §)')


def _read(name):
    """A prompt file in assets/, with its {{include file}} lines expanded."""
    text = ASSETS.joinpath(name).read_text(encoding='utf-8')
    return re.sub(r'\{\{include ([\w.]+)\}\}', lambda m: _read(m.group(1)).strip(), text)


def cookbook(gone=frozenset()):
    """Prompt section 4 from assets/cookbook_train.yaml without the recipes of the standard lines this set changed or
    dropped (`gone`, rules.compare). A recipe that another kept recipe refers to, by its [tag] or by its section ("§10"
    in a recipe of another section), stays, marked."""
    book = rules.load_cookbook()
    number = lambda s: int(re.match(r'##\s*§(\d+)', s['title'])[1])
    entries = [(number(s), e) for s in book['sections'] for e in s['entries']]
    out = {id(e) for _, e in entries if any(rules.key(r) in gone for r in e['rules'])}
    tag = lambda e: (re.match(r'- \[([^\]]+)\]', e['recipe']) or [None, None])[1]     # no tag: never cited by name
    kept = [(n, e['recipe']) for n, e in entries if id(e) not in out]
    cited = {t for _, r in kept for t in re.findall(r'\[([^\]\'"<]+)\]', r)[1:]}
    cited_sections = {int(m) for n, r in kept for m in re.findall(r'§(\d+)', r) if int(m) != n}
    parts = [book['preamble'].rstrip('\n')]
    for s in book['sections']:
        lines = [s['title']]
        for e in s['entries']:
            recipe = e['recipe'].rstrip('\n')
            if id(e) in out:
                if tag(e) not in cited and number(s) not in cited_sections:
                    continue
                recipe = recipe.replace(f'[{tag(e)}]', f'[{tag(e)}]{GONE_NOTE}', 1) if tag(e) else GONE_NOTE.strip() + ' ' + recipe
            lines.append(recipe)
        parts.append('\n'.join(lines))
    return '\n\n'.join(parts)


def system_prompt(gone=frozenset()):
    """Instructions + the cookbook of this set (constant for a run, so the serving engine's prefix cache covers it)."""
    return _read('prompt.md').replace('{{cookbook}}', cookbook(gone))


SYSTEM = system_prompt()                   # the standard (train) rulebook: every recipe


EXPLORE = 'explore'                        # a python action that only looks at the data: shown, never submitted
TYPE_LINE = re.compile(r'^[ \t>*_#`-]*answer[ _]?type[ *_`]*:[ *_`"]*([a-z]+)', re.I | re.M)
FENCE = re.compile(r'```[ \t]*(?:python|py)?[ \t]*\n', re.I)


class ActionError(Exception):
    pass


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def render_action(action):                           # the text form of an action, as the model writes it
    if action.get('action') not in ('python', 'answer'):
        return '(output not in the required form)'
    reasoning = '\n'.join(x for x in (action.get('diagnosis'), action.get('plan')) if x).strip()
    text = f"Answer type: {action['answer_type']}\n{reasoning}".strip()
    if action['action'] == 'python':
        code = action.get('code') or '\n'.join(action.get('code_lines', []))
        text += f'\n```python\n{code.strip()}\n```'
    return text


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
    return '\n'.join(f"{t}.{c} = " + ' | '.join(f"'{m['value']}' ({m['rows']} rows)" for m in ms) + f" ({how}"
                     + (f'; written {len(ms)} ways: match all of them' if len(ms) > 1 else '') + ')' for (t, c, _, how), ms in groups.items())


def render_state(catalog, question, as_of, lookup, remaining_calls, terminal_only):    # <shop> first: same for a shop (prefix cache)
    tables = [_tag('table', '\n'.join([_column(c) for c in t['columns']] + [f"{k}: {', '.join(map(str, v)) if isinstance(v, list) else _flat(v)}" for k, v in t.items() if k not in (
        'table', 'rows', 'source_files', 'columns', 'exact_duplicate_rows')]), name=t['table'], rows=t['rows'],
        files=', '.join(t.get('source_files', [])), exact_duplicate_rows=t.get('exact_duplicate_rows')) for t in catalog.get('schemas', [])]
    groups = [f"{g['table']}.{g['column']} ({g['kind']}): " + '; '.join(f'{k} = {v}' for k, v in g['labels'].items())
              for g in catalog.get('label_groups', [])]
    parts = [_tag('notes', catalog.get('notes') or ''), *tables, *([_tag('label_groups', '\n'.join(groups))] if groups else []),
             *[_tag(k, _lines(_notes(catalog[k]) if k == 'data_notes' else catalog[k])) for k in ('data_notes', 'unreadable_files') if catalog.get(k)],
             *[_tag('document', d['text'] or '(empty)', name=d['name']) for d in catalog.get('documents', [])],
             *([_tag('rulebook_changes', '\n'.join(f'- {x}' for x in catalog['rulebook_changes']))] if catalog.get('rulebook_changes') else [])]
    return '\n'.join([_tag('shop', '\n'.join(parts)), _tag('question', question, as_of=str(as_of), remaining_calls=remaining_calls,
                      terminal_only=str(terminal_only).lower()), _tag('data_lookup', _lookup(lookup) or 'none')])


def render_observation(observation):                 # <result status=...>: <error>, <issues>, <output> (stdout), <trace>, <next>
    parts = [_tag({'stdout': 'output', 'result': 'value'}.get(k, k), _lines(v)) for k, v in observation.items() if k != 'status' and v not in (None, '', [])]
    return _tag('result', '\n'.join(parts), status=observation.get('status'))


def messages(catalog, question, as_of, lookup, history, remaining_calls, terminal_only, system=SYSTEM):
    out = [{'role': 'system', 'content': system},
           {'role': 'user', 'content': render_state(catalog, question, as_of, lookup, remaining_calls, terminal_only)}]
    for action, observation in history:
        out.append({'role': 'assistant', 'content': render_action(action)})
        out.append({'role': 'user', 'content': render_observation(observation)})
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
    text = (raw or '').strip()
    fence = FENCE.search(text)
    head = text[:fence.start()] if fence else text
    kinds = TYPE_LINE.findall(head) or TYPE_LINE.findall(text)
    if not kinds:
        raise ActionError('Start your reply with the line "Answer type: <type>".')
    kind = kinds[-1].lower()
    plan = TYPE_LINE.sub('', head).strip()
    if fence:
        body = text[fence.end():]
        end = body.find('```')
        code = (body[:end] if end >= 0 else _cut_code(body)).strip('\n')
        if kind not in (*COMPUTED, EXPLORE):
            raise ActionError(f'Answer type must be one of {[*COMPUTED, EXPLORE]} for a program.')
        if not code.strip():
            raise ActionError('The ```python block is empty.')
        return {'action': 'python', 'plan': plan, 'rules': [], 'answer_type': kind, 'code': code}
    if kind not in (*COMPUTED, 'unanswerable', 'abstain'):
        raise ActionError('Without a program, Answer type must be a computed type (submits your last result), '
                          'unanswerable or abstain.')
    return {'action': 'answer', 'plan': plan, 'answer_type': kind}
