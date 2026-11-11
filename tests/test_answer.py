"""Result shapes (shape.py), answer validation and submission format (answer.py, eval.py)."""
import json
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from datamate.answer import AnswerError, finalize, issues, submission_line
from datamate.eval import correct, format_ok, score
from datamate.helpers import TolerantFrame
from datamate.shape import ShapeError, shape


@pytest.mark.parametrize('value, expected', [
    (TolerantFrame(pd.DataFrame({'a': [1], 'b': ['x']})), {'columns': ['a', 'b'], 'rows': [[1, 'x']]}),
    (pd.DataFrame({'k': ['x', 'y'], 'v': [1, 2]}).groupby('k')[['v']].sum(), {'columns': ['k', 'v'], 'rows': [['x', 1], ['y', 2]]}),
    (pd.DataFrame({'k': ['x', 'y'], 'v': [1, 2]}).groupby('k')['v'].sum(), {'columns': ['k', 'v'], 'rows': [['x', 1], ['y', 2]]}),
    (pd.Series(['a', 'b'], index=[3, 7]), ['a', 'b']),
    (np.array(['a', 'b']), ['a', 'b']),
    ([{'n': 'x', 'v': 1}, {'n': 'y', 'v': 2}], {'columns': ['n', 'v'], 'rows': [['x', 1], ['y', 2]]}),
    ({'n': ['x', 'y'], 'v': [1, 2]}, {'columns': ['n', 'v'], 'rows': [['x', 1], ['y', 2]]}),
    (np.int64(3), 3), (Decimal('2.50'), {'$decimal': '2.50'}), (pd.Timestamp('2026-03-01'), {'$date': '2026-03-01'}),
])
def test_unambiguous_shapes(value, expected):
    assert shape(value) == expected


@pytest.mark.parametrize('value, match', [({'x': 1, 'y': 2}, 'ambiguous'), (pd.DataFrame([[1, 2]], columns=['a', 'a']), 'repeated'),
                                          (float('inf'), 'non-finite'), (object(), 'Unsupported')])
def test_ambiguous_or_invalid_shapes_explain_the_fix(value, match):
    with pytest.raises(ShapeError, match=match):
        shape(value)


def test_finalize_numbers_dates_lists_tables():
    assert finalize('number', 26841000.0) == 26841000 and finalize('percent', 12.4567) == 12.46
    assert finalize('percent', {'$decimal': '12.40'}) == 12.4 and finalize('number', 2.675) == 2.68     # half-up, exact
    assert finalize('number', {'columns': ['v'], 'rows': [[5]]}) == 5 and finalize('string', ['Trà đào']) == 'Trà đào'
    assert finalize('date', {'$date': '2026-03-01'}) == '2026-03-01' and finalize('date', '2026-03') == '2026-03'
    assert finalize('list', {'columns': ['n'], 'rows': [['a'], ['b']]}) == ['a', 'b']
    assert finalize('table', {'columns': ['n', 'v'], 'rows': [['a', 1.5]]}) == {'columns': ['n', 'v'], 'rows': [['a', 1.5]]}
    for kind, value in (('number', 'abc'), ('boolean', 1), ('date', {'$datetime': '2026-03-01T10:00:00'}),
                        ('list', {'columns': ['a', 'b'], 'rows': []}), ('table', [1, 2]), ('list', [None])):
        with pytest.raises(AnswerError):
            finalize(kind, value)


def test_checks_before_auto_submit():
    assert issues('list', [], 'q') == ['empty list'] and issues('number', 0, 'q')
    assert issues('number', 12.5, 'Tỉ lệ đơn huỷ là bao nhiêu?') and not issues('percent', 12.5, 'Tỉ lệ đơn huỷ?')
    assert not issues('number', 5, 'Bao nhiêu đơn?')


def test_every_submission_line_is_valid_json_with_numbers():
    for kind, answer in (('number', 3), ('percent', 2.15), ('string', 'x'), ('date', '2026-01-02'), ('boolean', False),
                         ('list', ['a', 1]), ('table', {'columns': ['a', 'b'], 'rows': [['x', 3.5]]}), ('abstain', None),
                         ('unanswerable', None)):
        line = json.loads(json.dumps(submission_line('q', kind, answer)))
        assert format_ok(line), kind
    assert not format_ok({'type': 'percent', 'answer': '2.15'}) and not format_ok({'type': 'number', 'answer': True})


def test_local_score():
    gold = {'a': {'type': 'number', 'answer': 5}, 'b': {'type': 'string', 'answer': 'Trà đào', 'alias': ['SP01']},
            'c': {'type': 'list', 'answer': ['x', 'y']}}
    preds = {'a': {'type': 'number', 'answer': 5.0}, 'b': {'type': 'string', 'answer': 'sp01'}, 'c': {'type': 'abstain', 'answer': None}}
    assert score(preds, gold) == {'n': 3, 'pa': 0.6667, 'correct': 2, 'wrong': 0, 'abstain': 1}
    assert not correct({'type': 'list', 'answer': ['y', 'x']}, gold['c'])


def test_month_or_date_text_is_submitted_as_date():
    from datamate.answer import retype
    assert retype('string', '2025-04') == ('date', '2025-04')
    assert retype('string', ' 2025-04-30 ') == ('date', '2025-04-30')
    assert retype('string', 'Thép hộp 40x80') == ('string', 'Thép hộp 40x80')
    assert retype('number', 2025) == ('number', 2025)



def test_table_columns_take_the_reference_form():
    from datamate.answer import column_names
    assert column_names(['Khách Trọ', 'Số tiền nợ (đ)', 'TÊN_HÀNG']) == ['khach_tro', 'so_tien_no_d', 'ten_hang']
    assert column_names(['Khách hàng', 'khach_hang']) == ['Khách hàng', 'khach_hang']        # would collide: kept
    table = finalize('table', {'columns': ['Khách hàng', 'Số tiền nợ'], 'rows': [['Chị Lan', 3200000]]})
    assert table['columns'] == ['khach_hang', 'so_tien_no']
