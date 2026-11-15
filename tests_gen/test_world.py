"""Unique worlds (gen.world, gen.world_rules, gen.industries, gen.industry_gen checks), no model calls.

A fake generated trade with every trait goes into the registry; its rulebook rows carry the trait's Rules fields,
a world is rebuilt the same from its seed, opaque names hide the files' meaning and the copy reads back.
run: PYTHONPATH=src:. python -m pytest tests_gen/test_world.py -q
"""
from __future__ import annotations

import json
import random

import numpy as np
import pytest

from gen import industries, industry_gen, world, world_rules

TRADE = {
    'meta': {'shop_word': 'tiệm', 'label': 'đồ chơi gỗ thủ công', 'tet': 1.8, 'orders': [20, 50], 'lines': 1.8, 'staff': 3,
             'lots': True},
    'items': [{'name': f'Xe gỗ kéo dây mẫu {i}', 'group': ['xe gỗ', 'xếp hình', 'búp bê', 'dịch vụ khắc tên'][i % 4],
               'unit': 'cái' if i % 4 != 3 else 'lần', 'price': 50000 + 7000 * i, 'kind': 'made' if i % 4 == 3 else 'goods',
               **({'units': [['thùng', 12]]} if i % 5 == 0 and i % 4 != 3 else {}),
               **({'sizes': ['S', 'M', 'L'], 'size_fmt': '{n} size {s}', 'size_step': 5000} if i % 6 == 1 else {})}
              for i in range(24)],
    'traits': {'service': True, 'sizes': 'word', 'addon_group': None,
               'season': {'label': 'mùa trung thu', 'start': [8, 15], 'end': [9, 30]}},
    'unanswerable': ['Bé nào thích món đồ chơi nhất {P}'], 'val': False,
}


@pytest.fixture
def trade(tmp_path, monkeypatch):
    path = tmp_path / 'industries_gen.json'
    path.write_text(json.dumps({'toy_wood': TRADE}, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(industries, 'PATH', path)
    industries.reload()
    yield 'toy_wood'
    industries.reload()


def test_traits_give_sections_and_rules(trade):
    assert industries.sections(trade) == {'expiry', 'service', 'size_word', 'season'}
    assert industries.sizes(trade) == ['S', 'M', 'L']
    assert industries.season_trade('season_toy_wood') == trade
    c = world_rules.compose_world(trade, np.random.default_rng(1))
    assert set(c.rules.sections) == industries.sections(trade)
    (key, label, start, end), = c.rules.seasons
    assert key == 'season_toy_wood' and label == 'mùa trung thu'
    assert 'Mùa trung thu năm Y' in c.text or 'mùa trung thu' in c.text.lower()
    assert '`size <cỡ>`' in c.text and 'Size S, M, L' in c.text


def test_rulebooks_differ_and_repeat_from_seed(trade):
    a = world_rules.compose_world(trade, np.random.default_rng(5))
    b = world_rules.compose_world(trade, np.random.default_rng(5))
    texts = {world_rules.compose_world(trade, np.random.default_rng(s)).text for s in range(8)}
    assert a.text == b.text and a.rules == b.rules
    assert len(texts) == 8                                      # every world its own rulebook


def test_bank_paraphrase_replaces_a_line_in_heavy_worlds(trade):
    base = world_rules.compose_world(trade, np.random.default_rng(2))
    line = next(ln for ln in world_rules.lines(base.text) if ln.startswith('| Đơn bị huỷ'))
    bank = {line: ['| Đơn bị huỷ | đơn mang trạng thái huỷ. Đơn trả hàng **không** được coi là đơn huỷ |']}
    styles = set()
    for s in range(40):
        c = world_rules.compose_world(trade, np.random.default_rng(s), bank, p_reword=1.0)
        styles.add(c.parts['style'])
        if c.parts['style'] == 'train':          # train wording, tables, no paraphrase, no trade in the title
            assert 'được coi là đơn huỷ' not in c.text and c.parts['layout'] == 'table'
            assert 'đồ chơi' not in c.text.split('\n')[0]
        elif c.parts['layout'] == 'table':
            assert 'được coi là đơn huỷ' in c.text
    assert styles == {'train', 'heavy'}


def test_reword_keeps_bullets():
    bank = {'- Thông tin file không ghi thì không suy ra.': ['Thông tin mà file không ghi thì không được suy ra.']}
    out = world_rules.reword('- Thông tin file không ghi thì không suy ra.', np.random.default_rng(0), bank, 1.0)
    assert out == '- Thông tin mà file không ghi thì không được suy ra.'


def test_distractor_sections_do_not_change_rules(trade):
    c = world_rules.compose_world(trade, np.random.default_rng(3), distractors=[])
    assert set(c.rules.sections) == industries.sections(trade) and c.parts['distractors'] == []


def test_opaque_names(tmp_path):
    used = set()
    names = [world.opaque_stem(random.Random(i), used) for i in range(200)]
    assert len(set(n.lower() for n in names)) == 200
    assert not any(world.PERIOD_RE.match(n).group(2) for n in names)     # never read as a partition suffix


def test_build_world_repeats_and_reads_back(trade, tmp_path):
    a = world.build_world('w_t1', 11, tmp_path / 'a', [trade], bank={})
    b = world.build_world('w_t1', 11, tmp_path / 'b', [trade], bank={})
    assert {k: v for k, v in a.items() if k != 'sec'} == {k: v for k, v in b.items() if k != 'sec'}
    split = tmp_path / 'a' / 'w_t1'
    q = json.loads((split / 'questions.jsonl').read_text(encoding='utf-8'))
    g = json.loads((split / 'answers.jsonl').read_text(encoding='utf-8'))
    assert q['business_id'] == 'w_t1' and g['id'] == q['id'] and (split / 'rulebook.md').exists()
    assert not (split / '_raw').exists()
    side = json.loads((split / '_world.json').read_text(encoding='utf-8'))
    shop = split / 'data' / 'w_t1'
    files = {p.name for p in shop.iterdir()} - {'README.md'}
    if side['naming'] == 'opaque':
        assert set(side['plan_files'].values()) == files                   # every file renamed
    from datamate.data import load_business
    assert not load_business(shop, split / 'calendar.csv', None).unreadable


def test_readme_check():
    orig = '# Dữ liệu\n- `t_ab.xlsx` (xlsx) — bán hàng\n- **Thành tiền**: tiền\n- Dữ liệu có đến hết 05/03/2026.\n- 1 thùng = 24 chai'
    good = 'Thư mục có `t_ab.xlsx` (bán hàng), cột **Thành tiền**. Dữ liệu có đến hết 05/03/2026. 1 thùng = 24 chai.'
    assert world.readme_ok(orig, good) == []
    assert world.readme_ok(orig, good.replace('24', '12'))                # a number lost
    assert world.readme_ok(orig, good, avoid=['bán hàng'])                # an old name leaked


def test_industry_check_rejects_and_accepts():
    r = {'sector': 'x', 'visits': None, 'lots': False, 'service': False, 'sizes': False, 'weighed': True, 'addon': False,
         'season': False}
    items = [{'name': f'Cam sành loại {i}', 'group': ['cam', 'bưởi', 'táo', 'nho'][i % 4], 'unit': 'kg',
              'price': 30000 + i * 1000, 'kind': 'goods'} for i in range(24)]
    d = {'key': 'citrus_shop', 'label': 'trái cây có múi', 'shop_word': 'cửa hàng', 'tet': 1.5, 'orders': [30, 90],
         'lines': 2.0, 'staff': 3, 'items': items, 'unanswerable': ['a', 'b', 'c']}
    assert industry_gen.check(d, r, {}, set()) == []
    assert industry_gen.check({**d, 'items': items[:5]}, r, {}, set())
    assert industry_gen.check(d, r, {industry_gen._fold('trái cây có múi'): 'x'}, set())       # a trade we have
    e = industry_gen.entry(d, r, val=False)
    assert e['meta']['decimal_units'] == ['kg'] and e['traits']['sizes'] is None
