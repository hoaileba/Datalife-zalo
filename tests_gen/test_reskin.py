"""Reskinned shops and teacher samples replayed on them (gen.shopio, gen.remap, gen.reskin, gen.reskin_replay), and
the rulebook paraphrase check (gen.variants). No model calls: a scripted model plays the teacher on a tiny split.

run: PYTHONPATH=src:. python -m pytest tests_gen/test_reskin.py -q
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest
import yaml

from datamate.catalog import build_catalog
from datamate.config import load_config
from datamate.data import load_business
from datamate.llm import Reply
from datamate.prompt import render_action
from datamate.rules import compare, load_train_units
from gen import package, reskin, reskin_replay, teacher, validate
from gen import variants as V
from gen.remap import NameMap
from gen.shopio import read_shop, write_shop

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('dm_conftest', ROOT / 'tests' / 'conftest.py')
conftest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conftest)
TRAIN = ROOT / 'data' / 'train'


# ---------------------------------------------------------------- remap
@pytest.fixture
def nm():
    return NameMap({'so_ban_hang': 'BanLe', 'Mã hóa đơn': 'Số HĐ', 'Status': 'Tình trạng', 'so_luong': 'SL bán',
                    'SL': 'Số lượng', 'Hàng': 'Tên hàng', 'Khách hàng': 'Bên mua', 'SoBanHang.xlsx': 'DoanhSo.xlsx'},
                   {'hủy': 'Đã hủy', 'Đã hủy đơn': 'Hủy bỏ', 'cancelled': 'CANCEL'})


def test_map_code_literals_attributes_and_fstrings(nm):
    code = ("s = tables['so_ban_hang']\n"
            "s = s[~s['Status'].isin(['hủy', 'Đã hủy đơn'])]  # bỏ 'hủy'\n"
            "g = s.groupby('Mã hóa đơn').agg(status=('Status', 'first'))\n"
            "x = g['status'] + s['so luong'] if False else s['ma hoa don']\n"
            "print(f\"{len(s)} rows of so_ban_hang, {s['Mã hóa đơn'].nunique()} Mã hóa đơn\")\n"
            "y = s.so_luong + s['so_luong__unit']\n")
    out = nm.map_code(code)
    assert "tables['BanLe']" in out and "s['Tình trạng'].isin(['Đã hủy', 'Hủy bỏ'])" in out
    assert "# bỏ 'Đã hủy'" in out and "('Tình trạng', 'first')" in out
    assert "g['status']" in out                                 # a name the program made: never mapped by fold
    assert "s['SL bán']" in out and "s['Số HĐ']" in out         # accent/case spellings the tables accept
    assert 'rows of BanLe' in out and "{s['Số HĐ'].nunique()} Số HĐ" in out
    assert "s['SL bán__unit']" in out and 's.so_luong +' in out  # attribute to a non-identifier name stays...
    assert nm.stale(code=out) == ['attr:so_luong']               # ...and is reported


def test_map_prose_quotes_distinctive_and_sentence_start(nm):
    text = ("Khách hàng nợ nhiều nhất. Cột 'Status' ghi nhãn ('hủy', Đã hủy đơn); bảng so_ban_hang có so_luong và SL, "
            "file SoBanHang.xlsx. Xem **Hàng** và cột Khách hàng. cancelled = ['cancelled'], Hàng lẻ.")
    out = nm.map_prose(text)
    assert out.startswith('Khách hàng nợ')                       # a plain phrase opening a sentence
    assert "'Tình trạng'" in out and "('Đã hủy', Hủy bỏ)" in out
    assert 'bảng BanLe có SL bán và Số lượng' in out              # "SL bán" is not rescanned into "Số lượng bán"
    assert 'DoanhSo.xlsx' in out and '**Tên hàng**' in out and 'cột Bên mua' in out
    assert "cancelled = ['CANCEL']" in out and 'Hàng lẻ' in out  # single plain words stay words
    assert nm.stale(prose=out) == []
    assert nm.stale(prose="dùng 'Status'") == ['prose:Status']


def test_stale_label_fragment_and_answers(nm):
    assert 'fragment:hủy' not in nm.stale(code="s['x'].str.contains('Đã hủy')")
    assert nm.stale(code="s['x'].str.contains('đơn')") == ['fragment:đơn']    # a piece of an old label only
    g = nm.map_answer({'id': 'q', 'type': 'list', 'answer': ['hủy', 'Cà phê'], 'alias': [['HUY'], []]})
    assert g['answer'] == ['Đã hủy', 'Cà phê']
    assert nm.map_answer({'id': 'q', 'type': 'string', 'answer': 'Status', 'alias': []}) is None
    assert nm.map_answer({'id': 'q', 'type': 'number', 'answer': 5}) == {'id': 'q', 'type': 'number', 'answer': 5}


# ---------------------------------------------------------------- shop files
def test_shopio_round_trip_mini(tmp_path):
    split = conftest.make_split(tmp_path / 's', [])
    src = split / 'data' / 'biz_1'
    dst = tmp_path / 'copy'
    write_shop(read_shop(src), dst)
    shutil.copy(src / 'README.md', dst / 'README.md')
    a = load_business(src, split / 'calendar.csv')
    b = load_business(dst, split / 'calendar.csv')
    assert list(a.tables) == list(b.tables)
    for t in a.tables:
        assert a.tables[t].equals(b.tables[t])


@pytest.mark.parametrize('shop', ['biz_101', 'biz_123', 'biz_105'])
def test_reskin_real_shop(shop, tmp_path):
    """A train shop (CSV / SQLite / monthly XLSX sheets): read back with nothing unreadable, every table equal to the
    original once mapped, the catalog shows the new names, README names only new ones."""
    if not (TRAIN / 'data' / shop).is_dir():
        pytest.skip('no train data here')
    plan = reskin.reskin_shop(TRAIN / 'data' / shop, tmp_path / shop, TRAIN / 'calendar.csv', f'test:{shop}',
                              ROOT / 'outputs' / 'cache')
    assert plan['ok'], plan['problems']
    assert plan['columns_renamed'] > 3 and plan['readme_stale'] == []
    new = load_business(tmp_path / shop, TRAIN / 'calendar.csv')
    orig = load_business(TRAIN / 'data' / shop, TRAIN / 'calendar.csv', ROOT / 'outputs' / 'cache')
    assert new.unreadable == [] and len(new.tables) == len(orig.tables)
    cols = {c['name'] for p in build_catalog(new, '')['schemas'] for c in p['columns']}
    assert set(plan['columns'].values()) & cols
    assert not (set(plan['columns']) - set(plan['columns'].values())) & cols   # an old header is never left over
    nm = NameMap(plan['names'], plan['label_map'], plan['keep'])
    assert nm.stale(prose=(tmp_path / shop / 'README.md').read_text(encoding='utf-8')
                    .replace('**', '')) == [] or plan['readme'] != 'full'


# ---------------------------------------------------------------- end to end: teacher run -> reskin -> replay -> package
SALES2 = ('Mã đơn,Ngày,Khách hàng,Sản phẩm,SL,Thành tiền,Trạng thái,Phương thức thanh toán\n'
          'D1,01/03/2026,Nguyễn Văn An,Cà phê sữa,2,50000,Hoàn thành,Tiền mặt\n'
          'D2,02/03/2026,Trần Thị Bình,Trà đào,1,35000,Đã hủy,Chuyển khoản\n'
          'D3,15/03/2026,Nguyễn Văn An,Bạc xỉu,3,90000,Hoàn thành,Chuyển khoản\n'
          'D4,16/03/2026,Lê Văn Cường,Trà đào,2,70000,Trả hàng,Tiền mặt\n')
SUM = ("df = kit.dedup(tables['ban_hang'])\n"
       "assert set(df['Trạng thái']) <= {'Hoàn thành', 'Đã hủy', 'Trả hàng'}, 'unmapped label'\n"
       "result = int(df[df['Trạng thái'] == 'Hoàn thành']['Thành tiền'].sum())")
REPLIES = {
    'sum': {'action': 'python', 'code': SUM,
            'plan': "ASKED: doanh thu. Bảng `ban_hang`, cột 'Thành tiền'; nhãn 'Hoàn thành' tính, 'Đã hủy' và 'Trả hàng' bỏ."},
    'explore': {'action': 'python', 'plan': "Xem nhãn của cột 'Trạng thái'.",
                'code': "print(tables['ban_hang']['Trạng thái'].value_counts())\nresult = {'type': 'look'}"},
    'keyerror': {'action': 'python', 'plan': 'p', 'code': "result = tables['ban_hang']['Không có'].sum()"},
    'cash': {'action': 'python', 'plan': "Đơn 'Tiền mặt' không huỷ, không trả.",
             'code': "df = tables['ban_hang']\nresult = int(df[(df['Phương thức thanh toán'] == 'Tiền mặt') & "
                     "(df['Trạng thái'] == 'Hoàn thành')]['Thành tiền'].sum())"},
    'spaced': {'action': 'python', 'plan': 'p',       # a spelling only the tolerant read accepts
               'code': "df = tables['ban_hang']\nresult = int((df['Trạng thái '] == 'Hoàn thành').sum())"},
}


def _v5(code):                       # prompt v5: the last `result = X` becomes the result dict
    head, _, value = code.rpartition('result = ')
    return code if value.startswith('{') else f"{head}result = {{'type': 'number', 'answer': {value}}}"


for _r in REPLIES.values():
    _r['code'] = _v5(_r['code'])
REPLIES['sum_fix'] = dict(REPLIES['sum'], plan='CAUSE: BIND - the column did not exist.\n' + REPLIES['sum']['plan'])
for _r in REPLIES.values():                  # the clean answer form gen.sft.form_problem requires
    cause, _, rest = _r['plan'].rpartition('\n') if _r['plan'].startswith('CAUSE:') else ('', '', _r['plan'])
    _r['plan'] = (cause + '\n' if cause else '') + f'REASON:\n{rest}\nASKED: x | y | z | shape: one number\nRULES:\n- [r] -> r\nPLAN:\nBIND: ban_hang'

QUESTIONS = {                                  # text -> (gold, replies)
    'Doanh thu tháng này?': ({'type': 'number', 'answer': 140000}, ['sum']),
    'Doanh thu tháng 3 là bao nhiêu?': ({'type': 'number', 'answer': 140000}, ['explore', 'sum']),
    'Tổng tiền các đơn hoàn thành?': ({'type': 'number', 'answer': 140000}, ['keyerror', 'sum_fix']),
    'Doanh thu tiền mặt tháng 3?': ({'type': 'number', 'answer': 50000}, ['cash']),
    'Có mấy dòng hoàn thành?': ({'type': 'number', 'answer': 2}, ['spaced']),
}


class Teacher:
    def __init__(self, cfg):
        self.cfg = cfg

    def chat(self, messages, response_format=None, max_tokens=None, deadline=None):
        if len(messages) == 1:
            return Reply('ok', 'stop', {'prompt_tokens': 1, 'completion_tokens': 1}, 0.0)
        user = messages[1]['content']
        text = next(q for q in QUESTIONS if q in user)
        turn = sum(m['role'] == 'assistant' for m in messages)
        return Reply(render_action(REPLIES[QUESTIONS[text][1][turn]]), 'stop', {'prompt_tokens': 10, 'completion_tokens': 5},
                     0.0, 'thinking about ban_hang and Trạng thái')


@pytest.fixture(scope='module')
def world(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('reskin')
    qs, gold = [], []
    for i, (text, (g, _)) in enumerate(QUESTIONS.items(), 1):
        qs.append({'id': f'q_{i}', 'question': text})
        gold.append({'id': f'q_{i}', **g, 'alias': []})
    split = conftest.make_split(tmp / 'mini', qs)
    (split / 'data' / 'biz_1' / 'ban_hang.csv').write_text(SALES2, encoding='utf-8')
    (split / 'data' / 'biz_1' / 'README.md').write_text(
        '# Quán demo\n\n## File\n- `ban_hang.csv` (csv)\n\n## Cột trong `ban_hang.csv`\n- **Mã đơn**: mã đơn\n'
        '- **Trạng thái**: trạng thái đơn\n- **SL**: số lượng\n\n## Quy ước\n- **Trạng thái**: **Trạng thái** ghi '
        'Hoàn thành, Đã hủy hoặc Trả hàng.\n', encoding='utf-8')
    (split / 'answers.jsonl').write_text(''.join(json.dumps(g, ensure_ascii=False) + '\n' for g in gold), encoding='utf-8')
    cfg = load_config()
    cfg['llm'].update(base_url_env='DM_FAKE_URL', api_key_env='DM_FAKE_KEY', max_concurrency=2)
    cfg['run'].update(cache_dir=str(tmp / 'cache'), workers=2)
    (tmp / 'config.yaml').write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding='utf-8')
    mp = pytest.MonkeyPatch()
    mp.setenv('DM_FAKE_URL', 'http://fake.local/v1')
    mp.setattr(teacher, 'LLM', Teacher)
    mp.setattr(reskin, 'P_COLUMN', 1.0)                           # every header, label and sheet changes
    mp.setattr(reskin, 'P_LABEL', 1.0)
    run = tmp / 'run'
    teacher.main(['--split', str(split), '--out', str(run), '--config', str(tmp / 'config.yaml'), '--all', '--yes'])
    summary = reskin.build_copy(1, tmp / 'gen', 7, ['biz_1'], 1, tmp / 'cache', train=split)
    rsplit = tmp / 'gen' / 'reskin_1'
    rrun = tmp / 'rrun'
    reskin_replay.main(['--teacher', str(run), '--split', str(rsplit), '--out', str(rrun), '--workers', '2'])
    mp.undo()
    return {'tmp': tmp, 'split': split, 'run': run, 'rsplit': rsplit, 'rrun': rrun, 'summary': summary}


def lines(path):
    return [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]


def test_reskin_split_files(world):
    s = world['summary']
    assert s['shops_ok'] == 1 and s['questions'] == 5
    plan = json.loads((world['rsplit'] / 'reskin.json').read_text(encoding='utf-8'))['shops']['biz_1']
    assert {'Trạng thái', 'Thành tiền', 'SL'} <= set(plan['columns'])
    assert {'Hoàn thành', 'Đã hủy', 'Trả hàng', 'Tiền mặt', 'Chuyển khoản'} == set(plan['label_map'])
    assert plan['tables'] == {'ban_hang': plan['tables']['ban_hang']} and plan['tables']['ban_hang'] != 'ban_hang'
    meta = lines(world['rsplit'] / 'meta.jsonl')
    assert all(m['orig_id'] == m['id'] and m['variant'] == 'reskin_1' for m in meta)
    readme = next((world['rsplit'] / 'data' / 'biz_1').glob('README.md')).read_text(encoding='utf-8')
    assert 'ban_hang' not in readme and 'Trạng thái' not in readme           # a note title that is a column follows it
    assert f"- **{plan['columns']['Trạng thái']}**: **{plan['columns']['Trạng thái']}** ghi" in readme
    assert plan['label_map']['Hoàn thành'] in readme


def test_replay_keeps_and_drops(world):
    s = json.loads((world['rrun'] / 'summary.json').read_text(encoding='utf-8'))
    assert s['kept_total'] == 4 and s['dropped_total'] == {'stale_name': 1}      # q_5: 'Trạng thái ' is not mapped
    plan = json.loads((world['rsplit'] / 'reskin.json').read_text(encoding='utf-8'))['shops']['biz_1']
    new_status = plan['columns']['Trạng thái']
    rec = json.loads((world['rrun'] / 'logs' / 'q_2.json').read_text(encoding='utf-8'))
    obs = next(e for e in rec['trace'] if e['event'] == 'observation')['observation']
    assert plan['label_map']['Hoàn thành'] in obs['stdout'] and 'Hoàn thành' not in obs['stdout']   # real output on the copy
    msgs = rec['llm_calls'][1]['messages']
    assert new_status in msgs[2]['content'] and 'Trạng thái' not in msgs[2]['content']
    assert all(c['reasoning'] == '' for c in rec['llm_calls'])
    rec3 = json.loads((world['rrun'] / 'logs' / 'q_3.json').read_text(encoding='utf-8'))
    err = next(e for e in rec3['trace'] if e['event'] == 'observation')['observation']['error']
    assert 'KeyError' in err and plan['tables']['ban_hang'] in err               # the repair turn sees the copy's tables


def test_package_merges_original_and_reskin(world, tmp_path):
    out = tmp_path / 'pkg'
    stats = package.build([world['run'], world['rrun']], out, quiet=True, tokenizer='/nonexistent',
                          cache_dir=world['tmp'] / 'cache', val_shops=())
    assert stats['validation']['ok'], stats['validation']
    assert stats['prompt'] == {'same': stats['samples']['train']}            # rebuilt prompts = replayed ones
    meta = lines(out / 'train_meta.jsonl')
    by_q = {}
    for m in meta:
        by_q.setdefault(m['group'], set()).add(m['split'])
    assert len(by_q['q_1']) == 2                                            # original and copy share the group
    res = validate.check(out, rebuild=True, replay=True, workers=2)
    assert res['ok'], res
    stats = package.build([world['run'], world['rrun']], tmp_path / 'pkg1', quiet=True, tokenizer='/nonexistent',
                          cache_dir=world['tmp'] / 'cache', val_shops=(), per_group=1)
    assert stats['dropped_records']['per_group'] == 4
    assert {m['run'] for m in lines(tmp_path / 'pkg1' / 'train_meta.jsonl')} == {'run'}   # first-listed run wins
    stats = package.build([world['run'], world['rrun']], tmp_path / 'pkg_val', quiet=True, tokenizer='/nonexistent',
                          cache_dir=world['tmp'] / 'cache', val_shops=('biz_1',))
    assert stats['samples']['train'] == 0 and stats['validation']['ok']      # a held-out shop: its copies too


# ---------------------------------------------------------------- rulebook paraphrases
def test_paraphrase_format_has_no_changes():
    if not V.TRAIN_RULEBOOK.exists():
        pytest.skip('no train rulebook here')
    d = compare(V.paraphrase_format(), load_train_units())
    assert d['changes'] == [] and not d['gone'] and not d['full']
    w = compare(V.paraphrase_words(), load_train_units())             # reworded lines: listed unless aligned by name
    assert 0 < len(w['changes']) <= len(V.REWORDINGS) and not w['full']   # with the same meaning (known limitation)
    for name in V.VARIANTS:
        d = compare(V.rulebook_text(name), load_train_units())
        assert d['changes'] and not d['full'], name


def test_kept_names_protect_their_words():
    nm = NameMap({'Mã hàng': 'Mã SKU', 'don_hang': 'hoa_don'}, {'trả hàng': 'Hoàn hàng'},
                 keep=['Đã trả hàng', 'Mã hàng bán', 'don_hang_ct'])
    code = "x = s[s['Trạng thái'].isin(['trả hàng', 'Đã trả hàng'])]['Mã hàng bán']\ny = tables['don_hang_ct']"
    out = nm.map_code(code)
    assert "['Hoàn hàng', 'Đã trả hàng']" in out and "['Mã hàng bán']" in out and "tables['don_hang_ct']" in out
    assert nm.map_prose("nhãn 'Đã trả hàng' và Mã hàng bán, cột 'Mã hàng'") == "nhãn 'Đã trả hàng' và Mã hàng bán, cột 'Mã SKU'"
    assert nm.stale(code=out) == []


def test_header_groups_keep_marks_and_labels_keep_their_group():
    g = lambda h: reskin.HEADERS[reskin.header_group(h)][0] if reskin.header_group(h) is not None else None
    assert g('Hàng') == 'Tên hàng' and g('Hạng') == 'Nhóm khách hàng' and g('Hãng') == 'Thương hiệu'
    assert g('TongThanhToan') == 'Tổng sau giảm giá' and g('GiaVonLucBan') == 'Giá vốn lúc bán' and g('Giá vốn') == 'Giá vốn'
    for style in reskin.LABEL_POOLS.values():                   # every pool label has a category the agent can group
        for cat, pool in style.items():
            assert any(reskin.label_concept(x) for x in pool), cat
    assert reskin.label_concept('Đã hủy') == ('order status', 'cancelled')
    assert reskin.label_concept('Đã hoàn hàng') == ('order status', 'returned')   # train status words (catalog.LABEL_WORDS)


def test_a_kept_name_is_not_mapped_by_its_spelling():
    nm = NameMap({'Thành tiền': 'T.Tiền'}, {}, keep=['Thanh tien'])
    assert nm.map_code("x = df['Thanh tien'] + p['thanh tien'] + q['Thành tiền']") == \
        "x = df['Thanh tien'] + p['thanh tien'] + q['T.Tiền']"
    assert nm.stale(code="df['Thanh tien']") == []


def test_lowercase_labels_only_when_quoted():
    nm = NameMap({}, {'trả hàng': 'Hoàn hàng', 'Đã hủy': 'Hủy bỏ'})
    out = nm.map_prose("Đơn trả hàng vẫn tính; nhãn 'trả hàng' và Đã hủy bị bỏ.")
    assert out == "Đơn trả hàng vẫn tính; nhãn 'Hoàn hàng' và Hủy bỏ bị bỏ."
    assert nm.stale(prose=out) == []
