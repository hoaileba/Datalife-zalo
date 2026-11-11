"""Final answer: validate the shaped result against answer_type, normalize to the submission format
(docs/zac/evaluation.md), and the cheap checks a result must pass before it is submitted without the model.

In:  answer_type and a value from shape.shape (JSON-safe, dates/decimals tagged).
Out: the JSON `answer` value (numbers are JSON numbers; floats rounded half-up to 2 places as before; dates ISO).
Invariant: every submission line written by `submission_line` is valid for its type, or the question abstains.
"""
from __future__ import annotations

import math
import re
from decimal import Decimal, ROUND_HALF_UP

from .helpers import norm

COMPUTED = ('number', 'percent', 'string', 'date', 'boolean', 'list', 'table')
SCALARS = ('number', 'percent', 'string', 'date', 'boolean')
PLACES = 2                                   # floats are quantized half-up to 2 places; ints stay exact
PERCENT_WORDS = re.compile(r'\b(phan tram|ti le|ty le)\b')


class AnswerError(Exception):
    pass


def _number(v):
    if isinstance(v, dict) and '$decimal' in v:
        v = Decimal(v['$decimal'])
    if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and not math.isfinite(v):
        return None
    try:                                                  # round(v, 9): 14.374999999999998 is the tie 14.375
        d = (v if isinstance(v, Decimal) else Decimal(repr(round(v, 9)))).quantize(Decimal(1).scaleb(-PLACES), rounding=ROUND_HALF_UP)
    except ArithmeticError:
        raise AnswerError(f'The number {v!r} is too large to be an answer'[:200])
    return int(d) if d == d.to_integral_value() else float(d)


def _date(v):
    if isinstance(v, dict) and '$date' in v:
        return v['$date']
    if isinstance(v, dict) and '$datetime' in v:
        raise AnswerError('A datetime with a time of day is not a date: use .date() or format it as YYYY-MM-DD')
    if isinstance(v, str) and re.fullmatch(r'\d{4}-\d{2}(-\d{2})?', v.strip()):
        return v.strip()
    raise AnswerError(f'Expected a date (YYYY-MM-DD) or month (YYYY-MM), got {v!r}'[:200])


def _cell(v):
    """One list item or table cell in submission form."""
    if v is None:
        raise AnswerError('The result contains a blank (None/NaN) value: filter or fill it before answering')
    if isinstance(v, dict) and ('$date' in v or '$datetime' in v):
        return v.get('$date') or v['$datetime'][:10]
    n = _number(v)
    if n is not None:
        return n
    if isinstance(v, str) and v.strip().lower() in BLANK_TEXT:
        raise AnswerError(f'The result contains {v!r}, a blank written as text: filter or fill it before answering')
    if isinstance(v, (str, bool)):
        return v
    raise AnswerError(f'Unsupported value in the result: {v!r}'[:200])


def finalize(answer_type, value):
    """Submission `answer` for a computed answer_type, or AnswerError saying what to fix."""
    if answer_type not in COMPUTED:
        raise AnswerError(f'Unknown answer_type {answer_type!r}')
    if answer_type in SCALARS:
        if isinstance(value, dict) and 'columns' in value:
            if len(value['columns']) != 1 or len(value['rows']) != 1:
                raise AnswerError(f"Answer type {answer_type} needs one value, the result is a table with columns "
                                  f"{value['columns']} and {len(value['rows'])} rows: assign the single value itself")
            value = value['rows'][0][0]
        if isinstance(value, list):
            if len(value) != 1:
                raise AnswerError(f'Answer type {answer_type} needs one value, the result is a list of {len(value)}')
            value = value[0]
    if answer_type in ('number', 'percent'):
        n = _number(value)
        if n is None:
            raise AnswerError(f'Answer type {answer_type} needs a finite number, got {value!r}'[:200])
        return n
    if answer_type == 'string':
        if not isinstance(value, str) or not value.strip() or value.strip().lower() in BLANK_TEXT:
            raise AnswerError(f'Answer type string needs a non-empty name, got {value!r}'[:200])
        return value
    if answer_type == 'boolean':
        if not isinstance(value, bool):
            raise AnswerError(f'Answer type boolean needs True or False, got {value!r}'[:200])
        return value
    if answer_type == 'date':
        return _date(value)
    if answer_type == 'list':
        if isinstance(value, dict) and 'columns' in value:
            if len(value['columns']) != 1:
                raise AnswerError(f"A list needs one column, the result has {value['columns']}: assign list(series.index) "
                                  'for the names or list(series) for the values, in the asked order')
            value = [r[0] for r in value['rows']]
        if not isinstance(value, list):
            value = [value]
        return [_cell(v) for v in value]
    if not isinstance(value, dict) or 'columns' not in value:
        raise AnswerError('Answer type table needs a DataFrame: one row per object, first column the name, then the measures')
    if not value['columns']:
        raise AnswerError('The table has no columns')
    return {'columns': column_names(value['columns']), 'rows': [[_cell(c) for c in row] for row in value['rows']]}


def column_names(columns):
    """Table column names in the reference form: no accents, lower case, words joined by "_" ("Khách Trọ" ->
    "khach_tro"), so the scorer matches columns by name, whatever their order. Kept as they are if two collide."""
    slugs = [norm(str(c)).replace(' ', '_') or str(c) for c in columns]
    return slugs if len(set(slugs)) == len(slugs) else [str(c) for c in columns]


ALL_ZERO = 'every numeric value is 0'           # a result with this issue cannot be confirmed, only fixed or abstained


BLANK_TEXT = {'nan', 'none', 'null', 'nat', '<na>'}
NUMBER_TEXT = re.compile(r'-?[1-9]\d*(\.\d+)?|-?0\.\d+')       # not a code: no leading zero, no letters
UNANSWERABLE_TEXT = {'unanswerable', 'khong tra loi duoc', 'khong the tra loi'}
DATE_TEXT = re.compile(r'\d{4}-\d{2}(-\d{2})?')


def retype(answer_type, answer):
    """(answer_type, answer) with a date or month written as text submitted as a date: the format has one type per kind."""
    if answer_type == 'string' and isinstance(answer, str) and DATE_TEXT.fullmatch(answer.strip()):
        return 'date', answer.strip()
    if isinstance(answer, str) and norm(answer) in UNANSWERABLE_TEXT:      # the program concluded it, as a value
        return 'unanswerable', None
    return answer_type, answer


def issues(answer_type, answer, question):
    """Reasons not to submit without asking the model again; empty means the answer may be submitted."""
    found = []
    if answer_type == 'list' and not answer:
        found.append('empty list')
    if answer_type == 'table' and not answer['rows']:
        found.append('empty table')
    cells = answer if isinstance(answer, list) else [c for r in answer['rows'] for c in r] if isinstance(answer, dict) else [answer]
    numbers = [c for c in cells if isinstance(c, (int, float)) and not isinstance(c, bool)]
    if numbers and all(n == 0 for n in numbers):
        found.append(ALL_ZERO + ': check that the filters (names, dates, statuses) matched rows')
    if isinstance(answer, dict) and answer.get('rows') and len(answer['columns']) > 2:
        text = [j for j in range(len(answer['columns'])) if all(isinstance(r[j], str) for r in answer['rows'])]
        if len(text) >= 2:
            found.append(f"the table has {len(text)} text columns {[answer['columns'][j] for j in text]}: one column names "
                         'the object (first), the others are the asked measures; drop the extra code/name column')
    if any(isinstance(c, str) and NUMBER_TEXT.fullmatch(c.strip()) for c in cells):
        found.append('a value is a number written as text: give numbers as numbers')
    if ('%' in question or PERCENT_WORDS.search(norm(question))) and answer_type != 'percent':
        found.append(f'the question asks for a percentage but the Answer type is {answer_type}')
    return found


def submission_line(qid, answer_type, answer=None):
    """One submission.jsonl object; abstain and unanswerable carry no answer."""
    if answer_type in ('abstain', 'unanswerable'):
        return {'id': qid, 'type': answer_type, 'answer': None}
    return {'id': qid, 'type': answer_type, 'answer': answer}
