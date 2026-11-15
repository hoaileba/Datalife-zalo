"""Shared fixtures: a tiny synthetic split (no real data), a scripted fake model, the default config."""
import datetime as dt
import json
from pathlib import Path

import pytest

from datamate.config import load_config
from datamate.llm import Reply

CALENDAR = 'date,weekday,lunar_day,lunar_month,lunar_year,lunar_leap,holiday\n' + '\n'.join(
    f'2026-03-{d:02d},{dt.date(2026, 3, d).isoweekday()},{d},2,2026,false,' for d in range(1, 32))
SALES = ('Báo cáo bán hàng tháng 3\n'
         'Mã đơn,Ngày,Khách hàng,Sản phẩm,SL,Thành tiền,Trạng thái\n'
         'D1,01/03/2026,Nguyễn Văn An,Cà phê sữa,2,"50.000",Hoàn thành\n'
         'D1,01/03/2026,Nguyễn Văn An,Cà phê sữa,2,"50.000",Hoàn thành\n'
         'D2,02/03/2026,Trần Thị Bình,Trà đào,1,"35.000",Đã hủy\n'
         'D3,15/03/2026,Nguyễn Văn An,Bạc xỉu,3,"90.000",Hoàn thành\n'
         ',,,,,,\n'
         'Tổng cộng,,,,6,"225.000",\n')


def make_split(root: Path, questions):
    biz = root / 'data' / 'biz_1'
    biz.mkdir(parents=True)
    (biz / 'ban_hang.csv').write_text(SALES, encoding='utf-8')
    (biz / 'README.md').write_text('# Quán demo\nBảng ban_hang: mỗi dòng một món của đơn.', encoding='utf-8')
    (root / 'calendar.csv').write_text(CALENDAR, encoding='utf-8')
    (root / 'rulebook.md').write_text('# Rulebook\n## 1. Đơn\n| Luật | Mặc định |\n|---|---|\n| Đơn huỷ | không tính |\n', encoding='utf-8')
    with open(root / 'questions.jsonl', 'w', encoding='utf-8') as f:
        for q in questions:
            f.write(json.dumps({'business_id': 'biz_1', 'as_of_date': '2026-03-20', **q}, ensure_ascii=False) + '\n')
    return root


@pytest.fixture
def split(tmp_path):
    return make_split(tmp_path / 'split', [{'id': 'q1', 'question': 'Doanh thu tháng này?'},
                                           {'id': 'q2', 'question': 'Khách Nguyễn Văn An mua bao nhiêu đơn?'}])


@pytest.fixture
def cfg(tmp_path):
    c = load_config()
    c['run']['cache_dir'] = str(tmp_path / 'cache')
    return c


class FakeLLM:
    """Replies in order; a callable reply receives the messages. Records every call."""
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def chat(self, messages, response_format=None, max_tokens=None, deadline=None):
        self.calls.append({'messages': messages, 'response_format': response_format})
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(messages)
        if isinstance(reply, Reply):
            return reply
        from datamate.prompt import render_action
        return Reply(reply if isinstance(reply, str) else render_action(reply), 'stop', None, 0.0)


def program(lines, answer_type='number', plan='p', checked=False):
    """A scripted reply: the last `result = X` becomes the result dict of that type (None: lines kept as they are)."""
    lines = list(lines)
    if answer_type == 'explore':
        lines = lines[:-1] if lines and lines[-1].startswith('result = ') else lines
        lines.append("result = {'type': 'look'}")
    elif answer_type and lines and lines[-1].startswith('result = '):
        value = lines[-1][len('result = '):]
        lines[-1] = f"result = {{'type': {answer_type!r}, 'answer': {value}" + (", 'checked': True}" if checked else '}')
    return {'action': 'python', 'plan': plan, 'code': '\n'.join(lines)}


def decision(kind, reason='', checked=False):
    """A reply whose program only decides: abstain or unanswerable."""
    extra = (f", 'reason': {reason!r}" if reason else '') + (", 'checked': True" if checked else '')
    return program([f"result = {{'type': {kind!r}{extra}}}"], None)
