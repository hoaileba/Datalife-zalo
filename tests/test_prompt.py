"""Messages and action parsing (prompt.py, prompt v5: ASKED / RULES / PLAN, a TYPE line, then the program)."""
import re

import pytest

from datamate.notes import TABLE_NOTES
from datamate.prompt import SYSTEM, ActionError, messages, parse_action, render_action, render_state

PROGRAM = ("ASKED: doanh thu | đơn hoàn thành | tháng 3/2026 | shape: one number\nRULES:\n- [Đơn tính vào doanh thu] -> bỏ huỷ\n"
           "PLAN:\n- cancelled = ['Hủy']\n```python\nx = 1\nresult = {'type': 'number', 'answer': x}\n```")
CODE = "x = 1\nresult = {'type': 'number', 'answer': x}"


def test_system_prompt_is_one_fixed_text():
    assert '{{' not in SYSTEM and TABLE_NOTES in SYSTEM and '```python' in SYSTEM
    assert 'kit.dedup(df)' in SYSTEM and 'dm.' not in SYSTEM                     # the helpers are kit, never dm
    assert 'cookbook' not in SYSTEM.lower() and 'rulebook_changes' not in SYSTEM
    for part in ('ASKED:', 'RULES:', 'PLAN:', 'result = {"type": "number", "answer": total}', 'CAUSE:', 'NEED:', '"checked": True',
                 '{"type": "look"}', '{"type": "abstain"}', '# 5. Methods'):
        assert part in SYSTEM, part


def test_rulebook_then_shop_then_question():
    catalog = {'schemas': [], 'readme': 'README text', 'rulebook': 'RULE TEXT'}
    a = messages(catalog, 'Câu 1?', '2026-03-01', [], [], 3, False)[1]['content']
    b = messages(catalog, 'Câu 2?', '2026-03-02', [], [], 3, False)[1]['content']
    prefix = a[:a.index('</shop>')]
    assert a.startswith('<rulebook>\nRULE TEXT\n</rulebook>\n<shop>') and b.startswith(prefix)
    assert a.index('<readme>') < a.index('</shop>') < a.index('<question')
    assert '<question as_of="2026-03-01" weekday="Sunday" turn="1/3">' in a


def test_parse_valid_actions():
    a = parse_action(PROGRAM)
    assert a == {'action': 'python', 'plan': PROGRAM[:PROGRAM.index('\n```python')], 'code': CODE}
    assert render_action(a) == PROGRAM                                                           # round trip
    assert parse_action('**PLAN**\n```py\nresult = 1\n```')['code'] == 'result = 1'
    assert parse_action(PROGRAM + '\nDone.')['code'] == CODE                                    # text after the block dropped


def test_cut_programs_are_salvaged_only_when_complete():
    head = 'ASKED: x\n```python\n'
    assert parse_action(head + 'x = 1\nresult = x\nprint(le')['code'] == 'x = 1\nresult = x'
    assert parse_action(head + 'x = 1\nresult = x\nprint(x)')['code'] == 'x = 1\nresult = x\nprint(x)'
    with pytest.raises(ActionError, match='not closed'):
        parse_action(head + 'result = 0\nx = 2\nz = (x')                  # cut before the real end: never the early result
    with pytest.raises(ActionError, match='not closed'):
        parse_action(head + 'x = 1\ny = 2')


def test_invalid_actions_explain():
    with pytest.raises(ActionError, match='ONE ```python block'):
        parse_action('ASKED: x\nTYPE: abstain')                        # every reply carries its program
    with pytest.raises(ActionError, match='empty'):
        parse_action('ASKED: x\n```python\n\n```')
    assert render_action({'action': 'invalid'}).startswith('(output not')


def test_history_is_written_in_the_text_form_and_turns_counted():
    action = parse_action(PROGRAM)
    msgs = messages({'schemas': []}, 'q', '2026-01-01', [], [(action, {'status': 'error', 'error': 'E'})], 2, False)
    assert msgs[1]['content'] == messages({'schemas': []}, 'q', '2026-01-01', [], [], 3, False)[1]['content']  # fixed prefix
    assert msgs[2] == {'role': 'assistant', 'content': PROGRAM}
    assert msgs[3]['content'] == '<result status="error">\n<error>\nE\n</error>\n</result>\n<turn>2/3</turn>'
    assert msgs[0]['content'] == SYSTEM


def test_lookup_groups_spellings_and_notes_drop_empty_joins():
    look = [{'table': 't', 'column': 'c', 'value': v, 'rows': n, 'match': 'mentioned in question'} for v, n in (('Siro  ăn', 3), ('Siro Ăn', 2))]
    from datamate.notes import NOTE_PARTS
    notes = {'note': f"Facts. joins: {NOTE_PARTS['joins']} units: y.", 'joins': [{'key': 'k', 'master': 'm.k', 'others': {'a.k': 'all 3 values found'}}]}
    text = render_state({'data_notes': notes}, 'q', '2026-01-01', look, 3, False)
    assert "t.c = 'Siro  ăn' (3 rows) | 'Siro Ăn' (2 rows) (mentioned in question; written 2 ways" in text
    assert 'joins' not in text.split('<data_notes>')[1]


def test_methods_carry_no_rule_defaults():
    methods = SYSTEM[SYSTEM.index('# 5. Methods'):SYSTEM.index('# 6.')]
    for default in (r'start(s)? on Monday', r'thứ Hai', r'2 decimals', r'to the đồng', r'keeps identical rows', r'sum over orders with debt'):
        assert not re.search(default, methods), default        # Methods never restate a rule: the rulebook does


def test_system_prompt_says_how_to_read_the_input():
    for part in ('"values: v ×rows', '"e.g. ..."', 'exact_duplicate_rows', 'text_above_header', '<label_groups>',
                 '"not matched"', '<data_notes>', '"mentioned in question"', '"contains ..."', '<result>', 'evidence'):
        assert part in SYSTEM, part
