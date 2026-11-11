"""Local scoring (docs/zac/evaluation.md: +1 correct, 0 abstain, -1 wrong), strict format check, and code-flow
health of a run. Aggregates only: safe to print for public runs.

In:  submission lines, gold answers (answers.jsonl), per-question logs.  Out: dicts of counts.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

TYPES = {'number', 'percent', 'string', 'date', 'boolean', 'list', 'table', 'unanswerable', 'abstain'}


def norm_str(s):
    s = unicodedata.normalize('NFC', str(s)).lower()
    return re.sub(r'\s+', ' ', ''.join(ch if ch.isalnum() or ch.isspace() else ' ' for ch in s)).strip()


def _num(x):
    if isinstance(x, bool):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _cell(p, g, alias=None):
    if _num(g) is not None and not isinstance(g, str):        # a numeric gold needs a JSON number, not text
        return _number(p) and abs(p - g) < 1e-9
    return p is not None and norm_str(p) in {norm_str(g)} | {norm_str(a) for a in (alias or [])}


def _table(pred, gold, alias):
    if not isinstance(pred, dict) or 'columns' not in pred or 'rows' not in pred:
        return False
    gc, pc = [norm_str(c) for c in gold['columns']], [norm_str(c) for c in pred['columns']]
    if len(gc) != len(pc):
        return False
    order = [pc.index(c) for c in gc] if Counter(gc) == Counter(pc) and len(set(gc)) == len(gc) else list(range(len(gc)))
    rows = [[r[i] for i in order] for r in pred['rows'] if len(r) == len(gc)]
    if len(rows) != len(gold['rows']) or len(pred['rows']) != len(gold['rows']):
        return False
    used = [False] * len(rows)
    for grow, a in zip(gold['rows'], alias or [None] * len(gold['rows'])):
        j = next((j for j, r in enumerate(rows) if not used[j] and all(_cell(p, g, a) for p, g in zip(r, grow))), None)
        if j is None:
            return False
        used[j] = True
    return True


def correct(pred, gold):
    if pred.get('type') != gold['type']:
        return False
    t, p, g, alias = gold['type'], pred.get('answer'), gold.get('answer'), gold.get('alias')
    if t == 'number':
        return _number(p) and _num(g) is not None and abs(p - _num(g)) < 1e-9
    if t == 'percent':
        return _number(p) and _num(g) is not None and round(p, 2) == round(_num(g), 2)
    if t == 'string':
        return _cell(p, g, alias)
    if t == 'date':
        return isinstance(p, str) and p.strip() == g
    if t == 'boolean':
        return isinstance(p, bool) and p == g
    if t == 'list':
        return isinstance(p, list) and len(p) == len(g) and all(_cell(x, y, a) for x, y, a in zip(p, g, alias or [None] * len(g)))
    if t == 'table':
        return _table(p, g, alias)
    return t == 'unanswerable'


def score(preds, gold):
    """PA over the questions in `preds` that have a gold answer."""
    marks = [0 if p.get('type') == 'abstain' else 1 if correct(p, gold[q]) else -1 for q, p in preds.items() if q in gold]
    n = len(marks) or 1
    return {'n': len(marks), 'pa': round(sum(marks) / n, 4), 'correct': marks.count(1), 'wrong': marks.count(-1),
            'abstain': marks.count(0)}


def _number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def format_ok(line):
    """Strict submission format (type and shape, not value): numbers must be JSON numbers."""
    kind, a = line.get('type'), line.get('answer')
    if kind not in TYPES:
        return False
    if kind in ('abstain', 'unanswerable'):
        return a is None
    if kind in ('number', 'percent'):
        return _number(a)
    if kind == 'string':
        return isinstance(a, str) and bool(a.strip())
    if kind == 'date':
        return isinstance(a, str) and re.fullmatch(r'\d{4}-\d{2}(-\d{2})?', a) is not None
    if kind == 'boolean':
        return isinstance(a, bool)
    if kind == 'list':
        return isinstance(a, list) and all(_number(x) or isinstance(x, (str, bool)) for x in a)
    return (isinstance(a, dict) and set(a) == {'columns', 'rows'} and len(set(a['columns'])) == len(a['columns'])
            and all(isinstance(r, list) and len(r) == len(a['columns']) and all(_number(x) or isinstance(x, (str, bool)) for x in r)
                    for r in a['rows']))


def _error_kind(error):
    text = str(error)
    for key, label in (('Output started repeating', 'cut/repetition'), ('comment lines', 'cut/comments'),
                       ('token cap', 'cut/length'), ('JSON', 'invalid JSON'), ('never assigned result', 'no result'),
                       ('KeyError', 'KeyError'), ('SyntaxError', 'syntax'), ('Timeout', 'timeout'),
                       ('MemoryError', 'memory'), ('MemoryLimit', 'memory')):
        if key in text:
            return label
    head = text.split(':', 1)[0]
    return head if re.fullmatch(r'\w+', head) else 'other'


def health(logs, lines):
    """Code-flow health: calls, first-call finalization, failed programs by kind, cut outputs, format."""
    stats, errors, chars = Counter(), Counter(), []
    for log in logs:
        trace = log.get('trace', [])
        models = [e for e in trace if e['event'] == 'model']
        stats['calls'] += len(models)
        stats['cut'] += sum(e['finish'] in ('length', 'repetition', 'comments') for e in models)
        chars += [len(e['output']) for e in models]
        stats['programs'] += sum(e['event'] == 'execution' for e in trace)
        stats['failed_programs'] += sum(e['event'] == 'execution' and not e['ok'] and not e.get('explore') for e in trace)
        stats['explore'] += sum(e['event'] == 'execution' and bool(e.get('explore')) for e in trace)
        stats['check_failed'] += sum(e['event'] == 'observation' and e['observation']['status'] == 'not_finalized' for e in trace)
        for e in trace:
            if e['event'] == 'observation' and e['observation']['status'] == 'error':
                errors[_error_kind(e['observation']['error'])] += 1
        stats['first_finalized'] += log.get('reason') == 'auto_finalized' and len(models) == 1
        stats[log.get('reason', 'unknown')] += 1
    seconds = sorted(log.get('seconds', 0) for log in logs)
    return {'questions': len(logs), 'calls': stats['calls'], 'first_finalized': stats['first_finalized'],
            'auto_finalized': stats['auto_finalized'], 'programs': stats['programs'],
            'failed_programs': stats['failed_programs'], 'explore': stats['explore'], 'check_failed': stats['check_failed'], 'cut': stats['cut'],
            'abstain': sum(l.get('type') == 'abstain' for l in lines), 'format_ok': f'{sum(map(format_ok, lines))}/{len(lines)}',
            'errors': dict(errors.most_common()), 'out_chars_median_max': [sorted(chars)[len(chars) // 2] if chars else None, max(chars, default=None)],
            'seconds_median_max': [seconds[len(seconds) // 2] if seconds else None, seconds[-1] if seconds else None],
            'reasons': {k: stats[k] for k in ('auto_finalized', 'confirmed', 'model_decision', 'repeated_error', 'call_cap',
                                              'deadline', 'llm_error', 'host_error') if stats[k]}}
