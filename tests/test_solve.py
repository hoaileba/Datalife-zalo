"""One question end to end with a scripted model (solve.py): auto-submit, repair, confirm, abstain paths."""
import time

import pytest

from conftest import FakeLLM, program
from datamate.catalog import build_catalog
from datamate.data import _fingerprint, load_business
from datamate.llm import Reply
from datamate.solve import Context, solve

Q = {'id': 'q1', 'question': 'Doanh thu tháng này?', 'as_of': '2026-03-20'}
SUM = ["df = dm.dedup(tables['ban_hang'])", "result = int(df[df['Trạng thái'] == 'Hoàn thành']['Thành tiền'].sum())"]


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


def test_error_goes_back_and_the_fix_is_submitted(make):
    llm, out = make([program(["result = tables['ban_hang']['Mã khách'].nunique()"]), program(SUM)])
    assert out.answer == 140000 and out.calls == 2
    feedback = llm.calls[1]['messages'][-1]['content']
    assert 'KeyError' in feedback and 'line 1' in feedback


def test_suspicious_result_is_returned_then_confirmed(make):
    empty = program(["result = []"], answer_type='list')
    llm, out = make([empty, {'action': 'answer', 'plan': 'really none', 'answer_type': 'list'}])
    assert (out.answer, out.reason) == ([], 'confirmed')
    assert 'not_finalized' in llm.calls[1]['messages'][-1]['content']


def test_all_zero_result_cannot_be_confirmed(make):
    zero = program(["result = 0"])
    confirm = {'action': 'answer', 'plan': 'really zero', 'answer_type': 'number'}
    abstain = {'action': 'answer', 'plan': 'filters match nothing', 'answer_type': 'abstain'}
    llm, out = make([zero, confirm, abstain])
    assert 'cannot be confirmed' in llm.calls[2]['messages'][-1]['content']
    assert (out.answer_type, out.reason) == ('abstain', 'model_decision')


def test_same_failure_twice_abstains(make):
    bad = program(["result = tables['ban_hang']['khong co'].sum()"])
    llm, out = make([bad, bad])
    assert (out.answer_type, out.reason, out.calls) == ('abstain', 'repeated_error', 2)


def test_stopped_or_invalid_output_is_explained(make):
    llm, out = make([Reply('{"action":"python", ...', 'comments', None, 0.0), program(SUM)])
    assert out.answer == 140000 and 'comment lines' in llm.calls[1]['messages'][-1]['content']
    llm, out = make(['garbage', program(SUM)])
    assert out.answer == 140000 and 'Answer type' in llm.calls[1]['messages'][-1]['content']


def test_model_decisions_and_call_cap(make):
    assert make([{'action': 'answer', 'plan': 'no data', 'answer_type': 'unanswerable'}])[1].answer_type == 'unanswerable'
    failing = [program([f"result = tables['ban_hang']['x{i}'].sum()"]) for i in range(2)]   # max_calls 3: the last turn answers
    llm, out = make(failing + [{'action': 'answer', 'plan': 'p', 'answer_type': 'abstain'}])
    assert out.answer_type == 'abstain' and 'terminal_only="true"' in llm.calls[2]['messages'][1]['content']
    llm, out = make(failing + [program(SUM)])                                         # a last-turn program is submitted
    assert (out.answer, out.calls) == (140000, 3)


def test_a_failing_or_flagged_program_comes_back_with_its_step_trace(make):
    bad = program(["df = tables['ban_hang']", "done = df[df['Trạng thái'] == 'xong']", "result = done['khong co'].sum()"])
    llm, out = make([bad, program(SUM)])
    feedback = llm.calls[1]['messages'][-1]['content']
    assert '<trace>' in feedback and 'line 1 df:' in feedback and 'line 2 done: table 0 rows' in feedback
    empty = program(["df = tables['ban_hang']", "result = []"], answer_type='list')
    llm, out = make([empty, {'action': 'answer', 'plan': 'really none', 'answer_type': 'list'}])
    assert '<trace>' in llm.calls[1]['messages'][-1]['content']
    llm, out = make([program(SUM)])                                                   # submitted at once: not shown
    assert out.trace[1]['trace'] and len(llm.calls) == 1



def test_explore_is_shown_never_submitted(make):
    look = program(["df = tables['ban_hang']", "print(df['Trạng thái'].value_counts())", "result = len(df)"], 'explore')
    llm, out = make([look, program(SUM)])
    assert (out.answer, out.calls, out.reason) == (140000, 2, 'auto_finalized')          # the count of rows was not sent
    shown = llm.calls[1]['messages'][-1]['content']
    assert '"explored"' in shown and 'Hoàn thành' in shown
    llm, out = make([program(["print(tables['ban_hang'].shape)"], 'explore'), program(SUM)])   # no result: fine
    assert out.answer == 140000


def test_unanswerable_written_as_a_value_is_submitted_as_unanswerable(make):
    llm, out = make([program(["result = 'unanswerable'"], 'string')])
    assert (out.answer_type, out.answer) == ('unanswerable', None)
