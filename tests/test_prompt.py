"""Messages, schema and action parsing (prompt.py)."""
import json
import re

import pytest

from datamate.prompt import SYSTEM, ActionError, messages, parse_action, render_action


def test_system_prompt_is_complete():
    assert '{{' not in SYSTEM and '```python' in SYSTEM and 'dm.dedup' in SYSTEM


def test_catalog_prefix_is_identical_across_questions():
    catalog = {'notes': 'n', 'schemas': [], 'documents': []}
    a = messages(catalog, 'Câu 1?', '2026-03-01', [], [], 3, False)[1]['content']
    b = messages(catalog, 'Câu 2?', '2026-03-02', [], [], 3, False)[1]['content']
    shop = a[:a.index('</shop>')]
    assert shop.startswith('<shop>') and b.startswith(shop) and a.index('<question') > a.index('</shop>')


PROGRAM = 'Answer type: number\nASKED: doanh thu tháng 3.\ncancelled = [\'Hủy\']\n```python\nx = 1\nresult = x\n```'


def test_parse_valid_actions():
    a = parse_action(PROGRAM)
    assert a == {'action': 'python', 'plan': "ASKED: doanh thu tháng 3.\ncancelled = ['Hủy']", 'rules': [], 'answer_type': 'number',
                 'code': 'x = 1\nresult = x'}
    assert parse_action('No data on gender.\nAnswer type: unanswerable') == {'action': 'answer', 'plan': 'No data on gender.',
                                                                            'answer_type': 'unanswerable'}
    assert parse_action('**Answer type:** `percent`\n```py\nresult = 1\n```')['answer_type'] == 'percent'   # markdown dressing
    assert render_action(parse_action(PROGRAM)) == PROGRAM                                                      # round trip


def test_cut_programs_are_salvaged_only_when_complete():
    head = 'ASKED: x\nAnswer type: number\n```python\n'
    assert parse_action(head + 'x = 1\nresult = x\nprint(le')['code'] == 'x = 1\nresult = x'
    assert parse_action(head + 'x = 1\nresult = x\nprint(x)')['code'] == 'x = 1\nresult = x\nprint(x)'
    with pytest.raises(ActionError, match='not closed'):
        parse_action(head + 'result = 0\nx = 2\nz = (x')                  # cut before the real end: never the early result
    with pytest.raises(ActionError, match='not closed'):
        parse_action(head + 'x = 1\ny = 2')


def test_invalid_actions_explain():
    with pytest.raises(ActionError, match='Answer type'):
        parse_action('```python\nresult = 1\n```')
    with pytest.raises(ActionError, match='for a program'):
        parse_action('Answer type: money\n```python\nresult = 1\n```')
    with pytest.raises(ActionError, match='Without a program'):
        parse_action('Answer type: explore')
    assert parse_action(PROGRAM, terminal_only=True)['action'] == 'python'          # a last-turn program runs too
    assert parse_action('ASKED: x\nAnswer type: list\n```python\nresult = []\n```')['answer_type'] == 'list'   # line not first: read
    assert render_action({'action': 'invalid'}).startswith('(output not')


def test_history_is_written_in_the_text_form():
    action = parse_action(PROGRAM)
    msgs = messages({'notes': ''}, 'q', '2026-01-01', [], [(action, {'status': 'error', 'error': 'E'})], 2, False)
    assert msgs[2] == {'role': 'assistant', 'content': PROGRAM} and msgs[3]['content'] == '<result status="error">\n<error>\nE\n</error>\n</result>'


def test_system_prompt_forms_and_messages():
    assert 'rulebook_changes' in SYSTEM and 'ASKED' in SYSTEM and 'label_groups' in SYSTEM
    assert 'Answer type: number' in SYSTEM and '```python' in SYSTEM and '"action"' not in SYSTEM 
    assert '# 4. Cookbook' in SYSTEM and '<role>' not in SYSTEM
    assert messages({'notes': ''}, 'q', '2026-01-01', [], [], 3, False)[0]['content'] == SYSTEM


def test_cookbook_covers_every_train_rule_and_is_included():
    from datamate.prompt import cookbook
    from datamate.rules import load_cookbook
    book = load_cookbook()
    assert cookbook() in SYSTEM and '{{' not in SYSTEM
    assert all(e['rules'] or e['recipe'].startswith('- [Format]') for s in book['sections'] for e in s['entries'])
    for s in book['sections']:
        for e in s['entries']:
            assert e['recipe'] in SYSTEM + '\n' or e['recipe'].rstrip('\n') in SYSTEM


def test_cookbook_drops_the_recipes_of_gone_rules_and_marks_cited_ones():
    from datamate.prompt import GONE_NOTE, cookbook
    from datamate.rules import key, load_cookbook
    entries = {re.match(r'- \[([^\]]+)\]', e['recipe'])[1]: e for s in load_cookbook()['sections'] for e in s['entries']}
    names = ('Giao nhiều đợt', 'Đơn thuộc kỳ nào', 'Tồn theo đơn vị lớn')
    gone = frozenset(key(r) for name in names for r in entries[name]['rules'])
    text = cookbook(gone)
    assert '- [Giao nhiều đợt]' not in text and '- [Số đơn]' in text                # nobody cites it: dropped
    assert '- [Tồn theo đơn vị lớn]' + GONE_NOTE + '\n' in text + '\n'    # cited by name: only the name and the note
    assert '- [Đơn thuộc kỳ nào]' + GONE_NOTE + '\n' in text + '\n'       # cited by section: "orders that count (§1)"
    assert entries['Đơn thuộc kỳ nào']['recipe'].split('] ', 1)[1][:40] not in text   # the old method is gone
    assert cookbook() == cookbook(frozenset({key('| Không có | dòng này |')}))
    assert all(e['recipe'].startswith('- [') for s in load_cookbook()['sections'] for e in s['entries'])   # every recipe tagged
    assert all(re.fullmatch(r'## §\d+ .+', s['title']) for s in load_cookbook()['sections'])        # titles carry §N


def test_lookup_groups_spellings_and_notes_drop_empty_joins():
    from datamate.prompt import render_state
    look = [{'table': 't', 'column': 'c', 'value': v, 'rows': n, 'match': 'mentioned in question'} for v, n in (('Siro  ăn', 3), ('Siro Ăn', 2))]
    from datamate.notes import NOTE_PARTS
    notes = {'note': f"Facts. joins: {NOTE_PARTS['joins']} units: y.", 'joins': [{'key': 'k', 'master': 'm.k', 'others': {'a.k': 'all 3 values found'}}]}
    text = render_state({'notes': 'n', 'data_notes': notes}, 'q', '2026-01-01', look, 3, False)
    assert "t.c = 'Siro  ăn' (3 rows) | 'Siro Ăn' (2 rows) (mentioned in question; written 2 ways" in text
    assert 'joins' not in text.split('<data_notes>')[1]


def test_recipes_cited_by_the_instructions_keep_their_name_when_gone():
    from datamate.prompt import GONE_NOTE, cookbook
    from datamate.rules import key, load_cookbook
    entry = next(e for s in load_cookbook()['sections'] for e in s['entries'] if e['recipe'].startswith('- [Bảng không ghi theo đơn]'))
    text = cookbook(frozenset(key(r) for r in entry['rules']))
    assert '- [Bảng không ghi theo đơn]' + GONE_NOTE in text                 # prompt.md cites it: the name stays
