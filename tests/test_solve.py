"""One question end to end with a scripted model (solve.py): auto-submit, repair, checked, look, unanswerable, abstain."""
import time

import pytest

from conftest import FakeLLM, decision, program
from datamate.catalog import build_catalog
from datamate.data import _fingerprint, load_business
from datamate.llm import Reply
from datamate.solve import Context, solve

Q = {'id': 'q1', 'question': 'Doanh thu tháng này?', 'as_of': '2026-03-20'}
SUM = ["df = kit.dedup(tables['ban_hang'])", "result = int(df[df['Trạng thái'] == 'Hoàn thành']['Thành tiền'].sum())"]


@pytest.fixture
def make(split, cfg, tmp_path):
    folder, calendar = split / 'data' / 'biz_1', split / 'calendar.csv'
    business = load_business(folder, calendar, tmp_path / 'c')
    path = tmp_path / 'c' / f'biz_1-{_fingerprint(folder, calendar)}.pkl'
    def make(replies, question=Q):
        llm = FakeLLM(replies)
        return llm, solve(question, Context(llm, build_catalog(business, 'R'), business, str(path), cfg), time.monotonic() + 120)
    return make


def test_first_program_is_submitted_at_once(make):
    llm, out = make([program(SUM)])
    assert (out.answer_type, out.answer, out.reason, out.calls) == ('number', 140000, 'auto_finalized', 1)
    assert out.trace[1]['answer_type'] == 'number'


def test_error_goes_back_and_the_fix_is_submitted(make):
    llm, out = make([program(["result = tables['ban_hang']['Mã khách'].nunique()"]), program(SUM)])
    assert out.answer == 140000 and out.calls == 2
    feedback = llm.calls[1]['messages'][-1]['content']
    assert 'KeyError' in feedback and 'line 1' in feedback


def test_a_plain_result_is_an_error_that_explains_the_dict(make):
    llm, out = make([program(SUM, None), program(SUM)])
    assert out.answer == 140000 and 'result must be a dict with a "type"' in llm.calls[1]['messages'][-1]['content']


def test_flagged_result_comes_back_and_checked_submits_it(make):
    llm, out = make([program(["result = []"], 'list'), program(["result = []"], 'list', checked=True)])
    assert (out.answer_type, out.answer, out.reason) == ('list', [], 'confirmed')
    assert 'not_finalized' in llm.calls[1]['messages'][-1]['content'] and '"checked": True' in llm.calls[1]['messages'][-1]['content']


def test_checked_on_the_first_turn_does_not_skip_the_checks(make):
    llm, out = make([program(["result = []"], 'list', checked=True), decision('abstain')])
    assert out.answer_type == 'abstain' and 'not_finalized' in llm.calls[1]['messages'][-1]['content']


def test_all_zero_results_are_submitted_at_once(make):
    llm, out = make([program(["result = 0"])])
    assert (out.answer_type, out.answer, out.reason, out.calls) == ('number', 0, 'auto_finalized', 1)
    llm, out = make([program(["result = pd.DataFrame({'mon': ['a', 'b'], 'so': [0, 0]})"], 'table')])
    assert (out.answer_type, out.reason, out.calls) == ('table', 'auto_finalized', 1)


def test_same_failure_twice_abstains(make):
    bad = program(["result = tables['ban_hang']['khong co'].sum()"])
    llm, out = make([bad, bad])
    assert (out.answer_type, out.reason, out.calls) == ('abstain', 'repeated_error', 2)


def test_stopped_or_invalid_output_is_explained(make):
    llm, out = make([Reply('ASKED: x\n```python\n# a\n# b', 'comments', None, 0.0), program(SUM)])
    assert out.answer == 140000 and 'comment lines' in llm.calls[1]['messages'][-1]['content']
    llm, out = make(['garbage', program(SUM)])
    assert out.answer == 140000 and 'ONE ```python block' in llm.calls[1]['messages'][-1]['content']


def test_abstain_and_call_cap(make):
    assert make([decision('abstain')])[1].answer_type == 'abstain'
    failing = [program([f"result = tables['ban_hang']['x{i}'].sum()"]) for i in range(2)]   # max_calls 3: the last turn answers
    llm, out = make(failing + [decision('abstain')])
    assert out.answer_type == 'abstain' and '<turn>3/3</turn>' in llm.calls[2]['messages'][-1]['content']
    llm, out = make(failing + [program(SUM)])                                         # a last-turn program is submitted
    assert (out.answer, out.calls) == (140000, 3)


def test_unanswerable_comes_back_with_evidence_then_checked(make):
    no = ["df = tables['ban_hang']", "assert 'giới tính' not in df.columns"]
    llm, out = make([program(no + ["result = {'type': 'unanswerable', 'reason': 'no gender column'}"], None),
                     decision('unanswerable', 'no gender column', checked=True)])
    assert (out.answer_type, out.reason, out.calls) == ('unanswerable', 'model_decision', 2)
    back = llm.calls[1]['messages'][-1]['content']
    assert 'no gender column' in back and 'ban_hang: 4 rows; dates Ngày 2026-03-01..2026-03-15' in back
    llm, out = make([decision('unanswerable', 'x', checked=True), program(SUM)])             # checked before any flag: shown first
    assert out.answer == 140000


def test_unanswerable_written_as_a_value_is_checked_too(make):
    llm, out = make([program(["result = 'unanswerable'"], 'string'), program(["result = 'unanswerable'"], 'string', checked=True)])
    assert (out.answer_type, out.answer, out.calls) == ('unanswerable', None, 2)


def test_a_failing_or_flagged_program_comes_back_with_its_step_trace(make):
    bad = program(["df = tables['ban_hang']", "done = df[df['Trạng thái'] == 'xong']", "result = done['khong co'].sum()"])
    llm, out = make([bad, program(SUM)])
    feedback = llm.calls[1]['messages'][-1]['content']
    assert '<trace>' in feedback and 'line 1 df:' in feedback and 'line 2 done: table 0 rows' in feedback
    llm, out = make([program(["df = tables['ban_hang']", "result = []"], 'list'), decision('abstain')])
    assert '<trace>' in llm.calls[1]['messages'][-1]['content']
    llm, out = make([program(SUM)])                                                   # submitted at once: not shown
    assert out.trace[1]['trace'] and len(llm.calls) == 1


def test_look_is_shown_never_submitted(make):
    look = program(["df = tables['ban_hang']", "print(df['Trạng thái'].value_counts())"], 'explore')
    llm, out = make([look, program(SUM)])
    assert (out.answer, out.calls, out.reason) == (140000, 2, 'auto_finalized')
    shown = llm.calls[1]['messages'][-1]['content']
    assert '"looked"' in shown and 'Hoàn thành' in shown and out.trace[1]['explore']
    llm, out = make([program(["print(tables['ban_hang'].shape)"], None), program(SUM)])     # no result line: a look
    assert out.answer == 140000 and 'No result was assigned' in llm.calls[1]['messages'][-1]['content']


def test_a_kit_function_called_as_a_method_gets_a_hint(make):
    llm, out = make([program(["df = tables['ban_hang'].dedup()", "result = len(df)"]), program(SUM)])
    assert 'write kit.dedup(df, ...)' in llm.calls[1]['messages'][-1]['content'] and out.answer == 140000
    llm, out = make([program(["df = dm.dedup(tables['ban_hang'])", "result = int(df['Thành tiền'].sum() * 0) + 140000"])])
    assert out.answer == 140000                                                   # old programs (dm) still run


def test_json_style_literals_and_flag_kinds(make):
    llm, out = make([program(["result = []"], 'list'),
                     program(["result = {'type': 'list', 'answer': [], 'checked': true}"], None)])      # JSON true runs
    assert (out.answer_type, out.reason) == ('list', 'confirmed')
    llm, out = make([program(["result = []"], 'list'), decision('unanswerable', 'x', checked=True), decision('abstain')])
    assert out.answer_type == 'abstain'                     # a flagged answer never lets an unseen unanswerable through
    assert 'shop table' in llm.calls[2]['messages'][-1]['content'] and 'flag' not in llm.calls[1]['messages'][-1]['content'].split('<next>')[0]


def test_a_failing_print_in_a_look_says_its_error(make):
    llm, out = make([program(["print(tables['ban_hang']['khong co'])"], 'explore'), program(SUM)])
    shown = llm.calls[1]['messages'][-1]['content']
    assert out.answer == 140000 and 'print on line 1 failed (KeyError:' in shown and 'Columns:' in shown


def test_checked_must_resend_the_flagged_answer_unchanged(make):
    llm, out = make([program(["result = []"], 'list'), program(["result = ['x']"], 'list', checked=True)])
    assert (out.answer, out.reason) == (['x'], 'auto_finalized')          # a changed clean answer is simply submitted
    llm, out = make([program(["result = []"], 'list'),
                     program(["result = pd.DataFrame({'a': [], 'b': []})"], 'table', checked=True), decision('abstain')])
    assert out.answer_type == 'abstain'                                    # another flagged answer is not confirmed by it


def test_kit_between_used_as_a_mask_gets_a_hint(make):
    bad = program(["df = tables['ban_hang']", "s, e = kit.month_range(as_of)", "mask = df['Trạng thái'] == 'Hoàn thành'",
                   "mask &= kit.between(df, 'Ngày', s, e)", "result = int(df[mask]['Thành tiền'].sum())"])
    llm, out = make([bad, program(SUM)])
    assert 'kit.between returns the ROWS' in llm.calls[1]['messages'][-1]['content'] and out.answer == 140000


def test_window_rows_refuse_to_be_a_mask_and_constants_stay_out_of_traces(make):
    bad = program(["DATE = 'Ngày'", "df = tables['ban_hang']", "s, e = kit.month_range(as_of)", "rows = kit.between(df, DATE, s, e)",
                   "mask = df['Trạng thái'] == 'Hoàn thành'", "mask &= rows", "result = int(df[mask]['Thành tiền'].sum())"])
    llm, out = make([bad, program(SUM)])
    back = llm.calls[1]['messages'][-1]['content']
    assert 'A mask was combined with a table' in back and 'line 1 DATE' not in back and out.answer == 140000
    llm, out = make([program(["df = tables['ban_hang']", "s, e = kit.month_range(as_of)",
                              "result = int(df[(df['Trạng thái'] == 'Hoàn thành') & kit.between(df, 'Ngày', s, e)]['Thành tiền'].sum())"]),
                     program(SUM)])
    assert 'kit.between returns the ROWS' in llm.calls[1]['messages'][-1]['content']
    llm, out = make([program(["df = tables['ban_hang']", "s, e = kit.month_range(as_of)", "rows = kit.between(df, 'Ngày', s, e)",
                              "rows = rows[rows['Trạng thái'] == 'Hoàn thành']", "result = int(kit.dedup(rows)['Thành tiền'].sum())"])])
    assert out.answer == 140000                                       # the rows themselves work as a table


def test_last_turn_is_said_and_an_error_keeps_the_unanswerable_flag(make):
    un = decision('unanswerable', 'no gender column')
    bad = program(["result = tables['ban_hang']['khong co'].sum()"])
    llm, out = make([un, bad, decision('unanswerable', 'no gender column', checked=True)])
    assert (out.answer_type, out.reason) == ('unanswerable', 'model_decision')          # flag of turn 1 survives the error
    assert '<last_turn>' in llm.calls[2]['messages'][-1]['content'] and '<last_turn>' not in llm.calls[1]['messages'][-1]['content']


def test_an_answer_text_starting_with_unanswerable_is_checked(make):
    llm, out = make([program(["result = 'unanswerable: no data'"], 'string'), decision('abstain')])
    assert out.answer_type == 'abstain' and 'not_finalized' in llm.calls[1]['messages'][-1]['content']


def test_value_constants_stay_visible_in_errors_and_lookup_shows_codes(make, split):
    bad = program(["DATE = 'Ngày'", "WANTED = 'Cà phê đen'", "df = tables['ban_hang']", "rows = df[df['Sản phẩm'] == WANTED]",
                   "assert len(rows) > 0, 'item not found'", "result = len(rows)"])
    llm, out = make([bad, program(SUM)])
    back = llm.calls[1]['messages'][-1]['content']
    assert "WANTED: str 'Cà phê đen'" in back and 'line 1 DATE' not in back
