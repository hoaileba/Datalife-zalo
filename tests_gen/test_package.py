"""Teacher run -> SFT package -> validation, end to end on a tiny synthetic split with a scripted model (no API).

gen.teacher runs for real (threads, records, resume) with its LLM class replaced by a script keyed by question; then
gen.package builds the hand-off folder and gen.validate checks it. Covered: final and explore turns, a repair after an
error and after an unreadable reply, a confirmation turn, a wrong answer, unanswerable (weak), an API error retried by
--resume, an augmented copy grouped with its original, held-out shops, too-long samples, a missing system prompt,
prompt drift after the data changed, tampering caught by the validator.

run: PYTHONPATH=src:. python -m pytest tests_gen/test_package.py -q
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml

from datamate.config import load_config
from datamate.llm import Reply
from datamate.prompt import parse_action, render_action
from gen import package, sft, teacher, validate
from gen.tokens import TokenCounter, completion_text

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('dm_conftest', ROOT / 'tests' / 'conftest.py')
conftest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conftest)

SUM = ["df = dm.dedup(tables['ban_hang'])", "result = int(df[df['Trạng thái'] == 'Hoàn thành']['Thành tiền'].sum())"]
QUESTIONS = {   # question text -> (gold, replies per turn)
    'Doanh thu tháng này?': ({'type': 'number', 'answer': 140000}, ['sum']),
    'Doanh thu tháng 3 là bao nhiêu?': ({'type': 'number', 'answer': 140000}, ['explore', 'sum']),
    'Tổng tiền các đơn hoàn thành?': ({'type': 'number', 'answer': 140000}, ['keyerror', 'sum']),
    'Tổng tiền bán được tháng này?': ({'type': 'number', 'answer': 140000}, ['garbage', 'sum']),
    'Có bao nhiêu khách hàng?': ({'type': 'number', 'answer': 2}, ['one']),
    'Lương nhân viên tháng này?': ({'type': 'unanswerable', 'answer': None}, ['unanswerable']),
    'Doanh thu tuần này?': ({'type': 'number', 'answer': 140000}, ['api_error', 'sum']),
    'Các món bị trả lại?': ({'type': 'list', 'answer': []}, ['empty', 'confirm']),
}
AUG = ('q_aug0_1', 'Doanh thu thang nay', 'q_1')      # an augmented copy of q_1, same shop, same gold


def reply(kind):
    return {'sum': {'action': 'python', 'plan': 'ASKED: revenue', 'answer_type': 'number', 'code': '\n'.join(SUM)},
            'explore': {'action': 'python', 'plan': 'look at statuses', 'answer_type': 'explore',
                        'code': "print(tables['ban_hang']['Trạng thái'].value_counts())"},
            'keyerror': {'action': 'python', 'plan': 'p', 'answer_type': 'number', 'code': "result = tables['ban_hang']['Không có'].sum()"},
            'one': {'action': 'python', 'plan': 'p', 'answer_type': 'number', 'code': 'result = 1'},
            'empty': {'action': 'python', 'plan': 'returns', 'answer_type': 'list', 'code': 'result = []'},
            'confirm': {'action': 'answer', 'plan': 'No line is a return: the list is empty.', 'answer_type': 'list'},
            'unanswerable': {'action': 'answer', 'plan': 'No salary table in the data.', 'answer_type': 'unanswerable'}}[kind]


class ScriptedLLM:
    """Stands in for datamate.llm.LLM inside gen.teacher: the reply of turn t of a question is its script[t]."""
    fail_api = True

    def __init__(self, cfg):
        self.cfg = cfg

    def chat(self, messages, response_format=None, max_tokens=None, deadline=None):
        if len(messages) == 1:                                   # gen.teacher's preflight call
            return Reply('ok', 'stop', {'prompt_tokens': 1, 'completion_tokens': 1}, 0.0)
        user = messages[1]['content']
        text = next(q for q in sorted(QUESTIONS, key=len, reverse=True) if q in user or (q == 'Doanh thu tháng này?' and AUG[1] in user))
        turn = sum(m['role'] == 'assistant' for m in messages)
        kind = QUESTIONS[text][1][turn]
        if kind == 'api_error':
            if ScriptedLLM.fail_api:
                raise RuntimeError('balance exhausted')
            kind = QUESTIONS[text][1][turn + 1]
        out = 'I will write it.\nno answer type line here' if kind == 'garbage' else render_action(reply(kind))
        usage = {'prompt_tokens': 3000, 'completion_tokens': 200, 'prompt_cache_hit_tokens': 2800}
        return Reply(out, 'stop', usage, 0.01, 'teacher thinking', {'id': 'fake'})


@pytest.fixture(scope='module')
def world(tmp_path_factory):
    """A split with two shops (biz_1, biz_2 = same files) and a finished teacher run over it."""
    tmp = tmp_path_factory.mktemp('pkg')
    qs, gold = [], []
    for i, (text, (g, _)) in enumerate(QUESTIONS.items(), 1):
        qs.append({'id': f'q_{i}', 'question': text})
        gold.append({'id': f'q_{i}', **g, 'alias': []})
    qs.append({'id': AUG[0], 'question': AUG[1]})
    gold.append({'id': AUG[0], **QUESTIONS['Doanh thu tháng này?'][0], 'alias': []})
    split = conftest.make_split(tmp / 'mini', qs)
    shutil.copytree(split / 'data' / 'biz_1', split / 'data' / 'biz_2')
    (split / 'data' / 'biz_2' / 'README.md').write_text('# Quán thứ hai\nBảng ban_hang: mỗi dòng một món.', encoding='utf-8')
    with open(split / 'questions.jsonl', 'a', encoding='utf-8') as f:     # one question on the second shop
        f.write(json.dumps({'id': 'q_b2', 'business_id': 'biz_2', 'question': 'Doanh thu tháng này?', 'as_of_date': '2026-03-20'},
                           ensure_ascii=False) + '\n')
    gold.append({'id': 'q_b2', **QUESTIONS['Doanh thu tháng này?'][0], 'alias': []})
    (split / 'answers.jsonl').write_text(''.join(json.dumps(g, ensure_ascii=False) + '\n' for g in gold), encoding='utf-8')
    cfg = load_config()
    cfg['llm'].update(base_url_env='DM_FAKE_URL', api_key_env='DM_FAKE_KEY', max_concurrency=2)
    cfg['run'].update(cache_dir=str(tmp / 'cache'), workers=2)
    (tmp / 'config.yaml').write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding='utf-8')
    mp = pytest.MonkeyPatch()
    mp.setenv('DM_FAKE_URL', 'http://fake.local/v1')
    mp.setattr(teacher, 'LLM', ScriptedLLM)
    run = tmp / 'run'
    args = ['--split', str(split), '--out', str(run), '--config', str(tmp / 'config.yaml'), '--all', '--yes']
    ScriptedLLM.fail_api = True
    teacher.main(args)
    first = json.loads((run / 'logs' / 'q_7.json').read_text(encoding='utf-8'))
    ScriptedLLM.fail_api = False
    teacher.main(args + ['--resume'])                         # the API error record runs again
    mp.undo()
    return {'tmp': tmp, 'split': split, 'run': run, 'first_q7': first}


def build(world, name, **kw):
    kw.setdefault('tokenizer', '/nonexistent')                 # estimates: the test does not depend on a tokenizer
    kw.setdefault('cache_dir', world['tmp'] / 'cache')
    kw.setdefault('val_shops', ('biz_2',))
    out = world['tmp'] / name
    return out, package.build([world['run']], out, quiet=True, **kw)


def lines(path):
    return [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]


def test_teacher_records_and_resume_retry(world):
    run = world['run']
    recs = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in (run / 'logs').glob('*.json')}
    assert len(recs) == 10
    assert world['first_q7']['reason'] == 'llm_error'
    assert recs['q_7']['outcome'] == 'correct'                 # retried by --resume
    assert recs['q_5']['outcome'] == 'wrong'
    assert recs['q_8']['reason'] == 'confirmed' and recs['q_8']['correct']
    assert recs['q_6']['type'] == 'unanswerable'
    assert (run / 'sft' / 'train.jsonl').exists()             # exported by the run itself (recorded prompts)


def test_turn_selection_and_flags(world):
    recs = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in (world['run'] / 'logs').glob('*.json')}
    keep = lambda q: [(x['turn'], x['keep'], x['why']) for x in sft.teacher_turns(recs[q])]
    assert keep('q_2') == [(0, True, None), (1, True, None)]                  # clean explore + final
    assert keep('q_3') == [(0, False, 'failed_turn'), (1, True, None)]        # error repaired
    assert keep('q_4') == [(0, False, 'invalid'), (1, True, None)]            # unreadable reply repaired
    assert keep('q_5') == [(0, False, 'not_correct')]
    assert keep('q_8') == [(0, False, 'failed_turn'), (1, True, None)]        # not_finalized, then confirmed
    assert sft.weak_flags(recs['q_6']) == ['unanswerable', 'no_program']
    s3 = sft.teacher_samples(recs['q_3'], world['run'])
    assert len(s3) == 1 and s3[0]['meta']['recovered'] and len(s3[0]['prompt']) == 4    # failed turn in the history only
    assert sft.group_of('q_aug3_abc') == 'q_abc' and sft.group_of('q_abc') == 'q_abc' and sft.group_of('x', 'q_y') == 'q_y'


def test_package_end_to_end(world):
    out, stats = build(world, 'p_current')
    assert stats['validation']['ok'], stats['validation']
    assert stats['prompt'] == {'same': stats['samples']['train'] + stats['samples']['val']}   # current code = recorded
    train, val = lines(out / 'train.jsonl'), lines(out / 'val.jsonl')
    tmeta, vmeta = lines(out / 'train_meta.jsonl'), lines(out / 'val_meta.jsonl')
    assert all(set(s) == {'id', 'prompt', 'completion'} for s in train + val)
    assert [m['key'] for m in tmeta] == [s['id'] for s in train]
    ids = {m['id'] for m in tmeta}
    assert ids == {'q_1', 'q_2', 'q_3', 'q_4', 'q_6', 'q_7', 'q_8', 'q_aug0_1'}      # q_5 wrong: out
    assert {m['id'] for m in vmeta} == {'q_b2'}                                      # held-out shop
    assert sum(not m['final'] for m in tmeta) == 1                                   # the explore turn of q_2
    assert {m['group'] for m in tmeta if m['id'] in ('q_1', 'q_aug0_1')} == {'q_1'}
    assert next(m for m in tmeta if m['id'] == 'q_6')['weak'] == ['unanswerable', 'no_program']
    vq = lines(out / 'val_questions.jsonl')
    assert [q['id'] for q in vq] == ['q_b2']
    for s in train + val:                                    # completions are their own normal form
        assert render_action(parse_action(s['completion'][0]['content'])) == s['completion'][0]['content']
    assert (out / 'sft_lora.py').exists() and '{{' not in (out / 'README.md').read_text(encoding='utf-8')
    assert stats['dropped_records']['outcome_wrong'] == 1


def test_package_check_rebuild_and_replay(world):
    out, _ = build(world, 'p_check')
    res = validate.check(out, rebuild=True, replay=True, workers=2)
    assert res['ok'], res
    assert res['counts']['rebuilt'] == res['counts']['train_samples'] + res['counts']['val_samples']
    assert res['counts']['replay_correct'] == 7               # finals with a program (q_6 decides, q_8 confirms)


def test_filters(world):
    _, stats = build(world, 'p_filters', drop_weak=('unanswerable',), explore=False, val_shops=())
    assert stats['dropped_samples'] == {'weak:unanswerable': 1, 'explore': 1}
    assert stats['samples']['val'] == 0 and stats['validation']['ok']
    _, stats = build(world, 'p_short', max_len=1500)
    assert stats['samples'] == {'train': 0, 'val': 0, 'train_final': 0, 'val_final': 0} and stats['dropped_samples']['too_long'] >= 9
    out, stats = build(world, 'p_frac', val_shops=(), val_frac=0.5, seed=3)
    tg = {m['group'] for m in lines(out / 'train_meta.jsonl')}
    vg = {m['group'] for m in lines(out / 'val_meta.jsonl')}
    assert not tg & vg and stats['validation']['ok']


def test_per_question_keeps_the_best_record(world, tmp_path):
    run2 = tmp_path / 'run2'
    shutil.copytree(world['run'], run2)
    for p in (run2 / 'logs').glob('*.json'):                  # same questions, another run: duplicates by question
        rec = json.loads(p.read_text(encoding='utf-8'))
        rec['calls'] = (rec.get('calls') or 1) + 1
        p.write_text(json.dumps(rec, ensure_ascii=False), encoding='utf-8')
    out = tmp_path / 'p2'
    stats = package.build([world['run'], run2], out, quiet=True, tokenizer='/nonexistent', cache_dir=world['tmp'] / 'cache',
                          val_shops=('biz_2',))
    assert stats['dropped_records']['per_question'] == stats['records']['correct'] / 2
    assert {m['run'] for m in lines(out / 'train_meta.jsonl')} == {'run'}          # fewer calls wins


def test_missing_system_prompt_and_drift(world, tmp_path):
    run2 = tmp_path / 'run'
    shutil.copytree(world['run'], run2)
    (run2 / 'system_prompt.md').unlink()
    shutil.rmtree(run2 / 'system_prompts')
    stats = package.build([run2], tmp_path / 'p_nosys', quiet=True, prompts='recorded', tokenizer='/nonexistent')
    assert stats['dropped_records'].get('unusable:system prompt not saved in the run') == stats['records']['correct']
    # the data changed after the teacher run: the catalog (README) differs -> prompts drift
    split2 = tmp_path / 'split2'
    shutil.copytree(world['split'], split2)
    run3 = tmp_path / 'run3'
    shutil.copytree(world['run'], run3)
    for p in (run3 / 'logs').glob('*.json'):
        rec = json.loads(p.read_text(encoding='utf-8'))
        rec['input']['split'] = str(split2)
        p.write_text(json.dumps(rec, ensure_ascii=False), encoding='utf-8')
    (split2 / 'data' / 'biz_1' / 'README.md').write_text('# Quán khác\nBảng ban_hang: mô tả mới.', encoding='utf-8')
    out = tmp_path / 'p_drift'
    stats = package.build([run3], out, quiet=True, tokenizer='/nonexistent', cache_dir=tmp_path / 'cache', val_shops=())
    assert stats['prompt'].get('drift', 0) >= 8 and stats['validation']['ok']
    meta = lines(out / 'train_meta.jsonl')
    assert all(m['prompt_source'] == 'current' for m in meta)
    assert any('mô tả mới' in s['prompt'][1]['content'] for s in lines(out / 'train.jsonl'))
    stats = package.build([run3], tmp_path / 'p_drop', quiet=True, tokenizer='/nonexistent', cache_dir=tmp_path / 'cache',
                          val_shops=(), drop_drift=True)
    assert stats['dropped_samples']['prompt_drift'] >= 8


def test_validator_catches_tampering(world, tmp_path):
    out, _ = build(world, 'p_tamper')
    bad = tmp_path / 'bad'
    shutil.copytree(out, bad)
    rows = lines(bad / 'train.jsonl')
    rows[0]['completion'][0]['content'] = 'no answer type'
    vrows = lines(bad / 'val.jsonl') + [rows[1]]              # a train sample also in val: duplicate id, group leak
    vmeta = lines(bad / 'val_meta.jsonl') + [lines(bad / 'train_meta.jsonl')[1]]
    for name, rr in (('train.jsonl', rows), ('val.jsonl', vrows), ('val_meta.jsonl', vmeta)):
        (bad / name).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rr), encoding='utf-8')
    res = validate.check(bad)
    kinds = {e.split(':')[0] for e in res['errors']}
    assert not res['ok'] and {'hash', 'completion_parse', 'duplicate_id', 'group_leak', 'stats'} <= kinds


def test_refuses_test_splits(tmp_path):
    run = tmp_path / 'public_test_run'
    (run / 'logs').mkdir(parents=True)
    with pytest.raises(SystemExit):
        package.build([run], tmp_path / 'x', quiet=True)


def test_token_counter_estimate_and_exact():
    est = TokenCounter('/nonexistent')
    msgs = [{'role': 'system', 'content': 'a' * 2800}, {'role': 'user', 'content': 'b' * 280}]
    p, c = est.count(msgs, 'Answer type: number')
    assert not est.exact and p > 1100 and c >= 8
    exact = TokenCounter()
    if not exact.exact:
        pytest.skip(f'no Gemma tokenizer here: {exact.why}')
    text = exact.render_prompt(msgs)
    assert text.startswith('<bos><|turn>system\n') and text.endswith('<|turn>model\n<|channel>thought\n<channel|>')
    assert completion_text(' x \n') == 'x<turn|>'
    p2, c2 = exact.count(msgs, 'Answer type: number')
    assert p2 < p and c2 <= c                                  # the estimate errs on the long side
