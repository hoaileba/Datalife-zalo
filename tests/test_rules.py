"""Rulebook units vs the train rulebook (rules.py): standard lines, changes, removed lines, rewrites."""
from pathlib import Path

import pytest

from datamate.rules import COOKBOOK, changes, compare, key, load_cookbook, load_train_units, train_lines, units

ROOT = Path(__file__).resolve().parents[1]
BOOK = '# Rulebook\n\n## 1. Đơn\n| Luật | Mặc định |\n|---|---|\n| Đơn huỷ | không tính |\n| Đơn mới | tính |\n'
TRAIN = {k: line for k, line in units(BOOK)}


def test_units_skip_blank_lines_and_separators():
    assert [line for _, line in units(BOOK)] == ['# Rulebook', '## 1. Đơn', '| Luật | Mặc định |', '| Đơn huỷ | không tính |', '| Đơn mới | tính |']
    assert [line for _, line in units('|---|---|\n|--- tính cả đơn nháp |')] == ['|--- tính cả đơn nháp |']   # content kept


def test_key_keeps_words_numbers_and_operators_only():
    assert key('| Đơn  huỷ | không tính |') == key('|Đơn huỷ|không tính|') == key('- Đơn hủy: “không tính”.')   # retyped
    assert key('## 7. Không trả lời được') == key('### 8. Không trả lời được')                  # heading level, number
    assert key('Câu **không trả lời được** khi `as_of`') == key('Câu không trả lời được khi as_of')
    assert key('| Đơn hoà | x |') == key('| Đơn hòa | x |') and key('Đơn huỷ') == key('Đơn huỷ')    # tone, NFC
    assert key('| Đơn mới | tính |') != key('| Đơn mới | tính, kể cả đơn nháp |')                  # a word
    assert key('Tết: 23 tháng Chạp') != key('Tết: 25 tháng Chạp') and key('giá 1.000') != key('giá 1 000')
    for a, b in [('năm âm Y - 1', 'năm âm Y + 1'), ('ngày D + N', 'ngày D − N'), ('còn nợ > 0', 'còn nợ ≥ 0'),
                 ('Đúng +1, sai −1', 'Đúng −1, sai +1'), ('giảm 10%', 'giảm 10')]:
        assert key(a) != key(b), (a, b)                                                       # operators matter
    assert key('năm âm Y - 1') == key('năm âm Y − 1') == key('năm âm Y – 1')                  # dash forms are one minus
    for a, b in [('(năm âm Y − 1)', '(năm âm Y-1)'), ('nhóm X–Y', 'nhóm X - Y'), ('Tỉ lệ, tỉ trọng', 'Tỷ lệ, tỷ trọng'),
                 ('quý, lý, kỹ', 'quí, lí, kĩ'), ('06:00–13:59', '6:00-13:59'), ('mùng 10', 'mồng 10'), ('tháng 03', 'tháng 3')]:
        assert key(a) == key(b), (a, b)                                                       # ordinary retyping
    assert key('Thuý, y tá, tuy') != key('Thuí, i tá, tui') and key('năm âm Y-1') != key('năm âm Y+1')
    for a, b in [('0,05', '0,5'), ('1,05 lần', '1,5 lần'), ('1.000', '1.0'), ('mã SP001', 'mã SP1'), ('2,05 %', '2,5 %')]:
        assert key(a) != key(b), (a, b)                                                   # zeros inside numbers count
    for a, b in [('12,4 %', '12,4%'), ('D + N', 'D+N'), ('nợ > 0', 'nợ >0'), ('a → b', 'a -> b'), ('2 x 3', '2 × 3'),
                 ('mã KH-001', 'mã KH–001'), ('Y–1', 'Y-1')]:
        assert key(a) == key(b), (a, b)                                                       # operator spacing, arrows


def test_cookbook_file_holds_every_train_line_once():
    train = ROOT / 'data' / 'train' / 'rulebook.md'
    if not train.exists():
        pytest.skip('train data not present')
    text = train.read_text(encoding='utf-8')
    stored = sorted(line.strip() for line in train_lines(load_cookbook()))
    assert stored == sorted(line.strip() for _, line in units(text)) and COOKBOOK.name == 'cookbook_train.yaml'
    assert set(load_train_units()) == {k for k, _ in units(text)}
    assert compare(text, load_train_units()) == {'changes': [], 'gone': set(), 'full': False}


def test_changes_list_new_edited_and_rescoped_rules_with_their_section():
    book = BOOK.replace('| Đơn mới | tính |', '| Đơn mới | tính, kể cả đơn nháp |') + '\n### Sửa xe\n| Đơn huỷ | không tính |\n'
    assert changes(book, TRAIN) == ['1. Đơn: | Đơn mới | tính, kể cả đơn nháp |',
                                    'Sửa xe: | Đơn huỷ | không tính |']                  # a standard line under a new heading
    assert changes(BOOK.replace('# Rulebook', '# Rulebook (bộ test)'), TRAIN) == []            # the title is no scope
    assert changes(BOOK.replace('## 1. Đơn', '## 2. Đơn'), TRAIN) == []                       # renumbered heading


def test_compare_gone_standard_lines_and_rewrites():
    book = BOOK.replace('| Đơn mới | tính |', '| Đơn mới | tính, kể cả đơn nháp |')        # edited: old line gone
    assert compare(book, TRAIN) == {'changes': ['1. Đơn: | Đơn mới | tính, kể cả đơn nháp |'],
                                    'gone': {key('| Đơn mới | tính |')}, 'full': False}
    assert not compare(BOOK.replace('| Đơn huỷ | không tính |\n', ''), TRAIN)['full']       # 1 of 5 gone
    assert compare(BOOK.replace('| Đơn huỷ | không tính |\n| Đơn mới | tính |\n', ''), TRAIN)['full']  # 2 of 5: rewrite
    rewrite = '# R\n' + '\n'.join(f'- luật mới số {i}' for i in range(10))
    assert compare(rewrite, TRAIN) == {'changes': [], 'gone': set(), 'full': True}


def test_rulebook_document_changes_system_prompt_and_full(tmp_path, monkeypatch):
    import datamate.runner as runner
    from datamate.prompt import SYSTEM
    from datamate.runner import FULL, ONLY_CHANGES, load_rulebook
    big = dict(TRAIN, **{key(f'| Luật {i} | x |'): f'| Luật {i} | x |' for i in range(10)})
    monkeypatch.setattr(runner, 'load_train_units', lambda: big)
    book = tmp_path / 'rulebook.md'
    book.write_text(BOOK + '\n'.join(f'| Luật {i} | x |' for i in range(1, 10)) + '\n### Sửa xe\n| Lượt xe | một lượt |\n',
                    encoding='utf-8')
    text, stats, found, system = load_rulebook(book)
    assert text == ONLY_CHANGES and found == ['Sửa xe: | Lượt xe | một lượt |']
    assert stats == {'units': len(units(book.read_text(encoding='utf-8'))), 'changed': 1, 'gone': 1, 'full': False}
    assert system == SYSTEM                                         # the gone line ("Luật 0") carries no recipe
    book.write_text('# R\n' + '\n'.join(f'- luật mới số {i}' for i in range(10)), encoding='utf-8')
    text, stats, found, system = load_rulebook(book)
    assert text.startswith(FULL) and 'luật mới số 9' in text and found == [] and stats['full'] and system == SYSTEM


def test_rulebook_file_read_tolerantly(tmp_path):
    from datamate.runner import STANDARD, load_rulebook
    text, stats, found, _ = load_rulebook(tmp_path / 'missing.md')                  # no rulebook: nothing listed, run goes on
    assert text == STANDARD and found == [] and stats['units'] == 0          # no changed line: the standard rules
    book = tmp_path / 'rulebook.md'
    book.write_text(BOOK, encoding='utf-8')
    expected = load_rulebook(book)[2]
    book.write_bytes(('﻿' + BOOK).encode('utf-8'))                              # BOM: the heading is still a heading
    assert load_rulebook(book)[2] == expected
    book.write_bytes(BOOK.encode('utf-16'))                                          # not UTF-8
    assert load_rulebook(book)[2] == expected
