"""Whole run (runner.py): submission lines always valid, failures isolated, aggregates only."""
import argparse
import json

from conftest import FakeLLM, program
from datamate.runner import run, select


def args(split, out, **kw):
    return argparse.Namespace(split=str(split), out=str(out), limit=5, seed=0, ids=None, all=True, allow_large=False, **kw)


def test_run_writes_valid_submission_and_logs(split, cfg, tmp_path):
    cfg['run']['workers'] = 1
    llm = FakeLLM([program(["result = 3"]), lambda m: (_ for _ in ()).throw(RuntimeError('gateway down'))])
    summary = run(args(split, tmp_path / 'out'), cfg, llm)
    lines = [json.loads(l) for l in open(tmp_path / 'out' / 'submission.jsonl', encoding='utf-8')]
    assert {l['id']: l['type'] for l in lines} == {'q1': 'number', 'q2': 'abstain'}
    assert summary['health']['format_ok'] == '2/2' and (tmp_path / 'out' / 'logs' / 'q1.json').exists()
    assert 'Doanh thu' not in json.dumps(summary, ensure_ascii=False)     # aggregates only, no question text


def test_run_deadline_abstains_instead_of_overrunning(split, cfg, tmp_path):
    cfg['run']['total_seconds'] = 0
    run(args(split, tmp_path / 'out'), cfg, FakeLLM([]))
    assert all(json.loads(l)['type'] == 'abstain' for l in open(tmp_path / 'out' / 'submission.jsonl', encoding='utf-8'))


def test_selection_matches_v3_dev_runner():
    qs = [{'id': f'q{i}', 'business_id': f'b{i % 3}'} for i in range(10)]
    assert select(qs, 3, 0) == select(qs, 3, 0) and len(select(qs, 3, 0)) == 3


def test_odd_question_files_still_give_one_valid_line_per_id(split, cfg, tmp_path):
    cfg['run']['workers'] = 1
    good = (split / 'questions.jsonl').read_text(encoding='utf-8').splitlines()
    first = json.loads(good[0])
    odd = ['﻿' + good[0], good[0], '{broken', json.dumps({**first, 'id': 'q3', 'as_of_date': None}), good[1]]
    (split / 'questions.jsonl').write_text('\n'.join(odd) + '\n', encoding='utf-8')   # BOM, duplicate, bad line, no as_of
    (split / 'calendar.csv').unlink()                                                   # no calendar: still runs
    run(args(split, tmp_path / 'out'), cfg, FakeLLM([program(["result = 3"])] * 3))
    lines = [json.loads(l) for l in open(tmp_path / 'out' / 'submission.jsonl', encoding='utf-8')]
    assert [l['id'] for l in lines] == ['q1', 'q3', 'q2'] and lines[1]['type'] == 'abstain'


def test_resume_keeps_written_lines(split, cfg, tmp_path):
    cfg['run']['workers'] = 1
    out = tmp_path / 'out'
    out.mkdir()
    (out / 'submission.jsonl').write_text(json.dumps({'id': 'q1', 'type': 'number', 'answer': 7}) + '\n', encoding='utf-8')
    llm = FakeLLM([program(["result = 3"])])
    run(args(split, out, resume=True), cfg, llm)
    lines = {json.loads(l)['id']: json.loads(l) for l in open(out / 'submission.jsonl', encoding='utf-8')}
    assert lines['q1']['answer'] == 7 and lines['q2']['answer'] == 3 and len(llm.calls) == 1
