"""Rulebook variants (S4): one default of the train rulebook changed, in the text AND in the oracle's Rules, so the
same shop + question gets the answer of the changed rule. The v4 agent sees the edit as `rulebook_changes`
(datamate.rules.compare) and must follow it over the cookbook.

Variants are made up from the train rulebook only (never from another split's rulebook).
VARIANTS: name -> (Rules overrides, [(old line fragment, new line fragment)], intents the change affects)
"""
from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from .oracle import Rules

TRAIN_RULEBOOK = Path(__file__).resolve().parents[1] / 'data' / 'train' / 'rulebook.md'

VARIANTS = {
    'week_sunday': (dict(week_start=6), [(
        '| Tuần | bắt đầu **thứ Hai**. **Tuần này**: từ thứ Hai của tuần chứa hôm nay đến hết hôm nay. **Tuần trước, tuần rồi**: **cả** tuần liền trước, thứ Hai đến Chủ nhật |',
        '| Tuần | bắt đầu **Chủ nhật**. **Tuần này**: từ Chủ nhật của tuần chứa hôm nay đến hết hôm nay. **Tuần trước, tuần rồi**: **cả** tuần liền trước, Chủ nhật đến thứ Bảy |')],
        {'*': ['this_week', 'last_week']}),
    'returns_count': (dict(exclude_returned=False), [(
        '| Đơn tính vào doanh thu | đơn **không huỷ** và **không trả hàng**. Đơn có trả hàng, **kể cả chỉ trả một phần**, là đơn trả hàng: bỏ **cả đơn**. Đơn đang giao vẫn tính |',
        '| Đơn tính vào doanh thu | mọi đơn **không huỷ**, kể cả đơn trả hàng (tính cả đơn, không trừ phần trả). Đơn đang giao vẫn tính |'),
        ('| Số đơn | chỉ tính đơn không huỷ, không trả;', '| Số đơn | chỉ tính đơn không huỷ (đơn trả hàng vẫn tính);')],
        None),
    'delivering_out': (dict(count_delivering=False), [(
        'là đơn trả hàng: bỏ **cả đơn**. Đơn đang giao vẫn tính |',
        'là đơn trả hàng: bỏ **cả đơn**. Đơn **đang giao chưa tính**: chỉ tính khi đã hoàn thành |'),
        # the order count follows the same set (the oracle counts §1 orders): its own line says so too
        ('| Số đơn | chỉ tính đơn không huỷ, không trả;', '| Số đơn | chỉ tính đơn không huỷ, không trả, **không đang giao**;')],
        None),
    'revenue_shipping': (dict(revenue_shipping=True), [(
        '**không** cộng thuế VAT, **không** gồm phí giao hàng.',
        '**không** cộng thuế VAT, **có cộng** phí giao hàng của đơn.')],
        None),
    'revenue_voucher': (dict(revenue_order_discount=True), [(
        '**Không** trừ giảm giá trên cả đơn (khuyến mãi theo tổng tiền đơn, voucher shop),',
        '**Có trừ** giảm giá trên cả đơn (khuyến mãi theo tổng tiền đơn, voucher shop),')],
        None),
    'cancel_rate_no_returns': (dict(cancel_rate_all_orders=False), [(
        '| Tỉ lệ đơn huỷ trong kỳ | phần trăm đơn huỷ trong **mọi đơn đặt trong kỳ** (theo ngày đặt, **mọi trạng thái**: cả đơn huỷ, đơn trả, đơn đang giao). Làm tròn 2 chữ số thập phân. |',
        '| Tỉ lệ đơn huỷ trong kỳ | phần trăm đơn huỷ trong các đơn đặt trong kỳ **không tính đơn trả hàng** (theo ngày đặt; gồm đơn huỷ, đơn hoàn thành, đơn đang giao). Làm tròn 2 chữ số thập phân. |')],
        {'*': ['cancel_rate']}),
    'this_month_full_prev': (dict(this_month_same_days=False), [(
        'So với tháng trước thì lấy **cùng số ngày** của tháng trước: từ ngày 1 đến hết ngày trùng số với hôm nay; tháng trước không có ngày đó thì đến hết tháng trước |',
        'So với tháng trước thì lấy **cả tháng trước**, từ ngày 1 đến hết ngày cuối tháng |')],
        {'*': ['revenue_change_pct', 'revenue_diff']}),
    'tet_short': (dict(tet_end=(1, 5)), [(
        'đến **hết** ngày dương của **mùng 10 tháng Giêng** (năm âm Y).',
        'đến **hết** ngày dương của **mùng 5 tháng Giêng** (năm âm Y).')],
        {'*': ['tet']}),
    'shifts_split': (dict(morning=(6, 11), afternoon=(12, 17)), [(
        'ca sáng 06:00–13:59, ca chiều 14:00–21:59.',
        'ca sáng 06:00–11:59, ca chiều 12:00–17:59 (đơn từ 18:00 là ca tối, không thuộc hai ca này).')],
        {'*': ['shift_revenue', 'shift_orders', 'shift_change_pct']}),
    'avg_purchase_simple': (dict(avg_purchase_weighted=False), [(
        '| Giá nhập bình quân một mặt hàng trong tháng | bình quân **theo số lượng nhập**, **không** phải trung bình cộng các mức giá nhập;',
        '| Giá nhập bình quân một mặt hàng trong tháng | **trung bình cộng** giá nhập của các dòng nhập (mỗi dòng một lần, không theo số lượng);')],
        {'*': ['avg_purchase_price']}),
    'pct_one_decimal': (dict(pct_decimals=1), [(
        'Phần trăm và số trung bình khác làm tròn 2 chữ số thập phân, trừ khi một luật khác trong rulebook ghi khác.',
        'Phần trăm làm tròn **1 chữ số thập phân** (nửa lên); số trung bình khác làm tròn 2 chữ số thập phân.'),
        ('Làm tròn 2 chữ số thập phân. |', 'Làm tròn 1 chữ số thập phân. |'),
        ('Tiền đúng từng đồng, số đếm đúng từng đơn vị, phần trăm đúng 2 chữ số thập phân.',      # §9 grading line
         'Tiền đúng từng đồng, số đếm đúng từng đơn vị, phần trăm đúng 1 chữ số thập phân.')],
        {'type': ['percent']}),
}


def rulebook_text(name, base: str | None = None) -> str:
    text = base if base is not None else TRAIN_RULEBOOK.read_text(encoding='utf-8')
    for old, new in VARIANTS[name][1]:
        if old not in text:
            raise ValueError(f'variant {name}: line not found: {old[:60]}')
        text = text.replace(old, new)
    return text


def rules_of(name) -> Rules:
    return replace(Rules(), **VARIANTS[name][0])


def affected(name, spec, answer_type, default_answer, variant_answer):
    """A question is a useful S4 sample when the variant changes its answer."""
    return default_answer != variant_answer


# ---------------------------------------------------------------- paraphrases (meaning unchanged)
def paraphrase_format(base: str | None = None) -> str:
    """The train rulebook retyped without changing a word: table rows as bullets (`- **Luật**: mặc định`), the
    table header rows as plain lines, bold dropped from paragraphs, the other tone placement (hủy -> huỷ), curly
    quotes. datamate.rules keys ignore all of this, so the agent must see no rulebook_changes."""
    text = base if base is not None else TRAIN_RULEBOOK.read_text(encoding='utf-8')
    out = []
    for line in text.split('\n'):
        s = line.strip()
        if s.startswith('|') and s.endswith('|'):
            cells = [c.strip() for c in s.strip('|').split('|')]
            if all(re.fullmatch(r':?-{3,}:?', c) for c in cells):
                continue                                      # table rule
            if len(cells) >= 2:
                head, rest = cells[0], ' | '.join(cells[1:])
                line = f'- **{head.strip("*")}**: {rest}' if head else f'- {rest}'
        elif s and not s.startswith('#'):
            line = line.replace('**', '')
        line = re.sub(r'(?<!\w)hủy', 'huỷ', re.sub(r'(?<!\w)Hủy', 'Huỷ', line))
        out.append(line)
    return '\n'.join(out)


# Same meaning, other words (a writer of another split would reword like this). datamate.rules compares words, so
# each reworded line is listed in rulebook_changes and loses its recipe: the answers stay those of the standard rules.
REWORDINGS = [
    ('Mọi đáp án chuẩn tính theo các luật dưới đây.', 'Đáp án chuẩn đều được tính theo những luật sau.'),
    ('| Tuần | bắt đầu **thứ Hai**.', '| Tuần | tuần mở đầu bằng **thứ Hai**.'),
    ('| Bán chạy | theo **số lượng quy về đơn vị cơ bản**, không theo số dòng hay số tiền;',
     '| Bán chạy | xếp theo **số lượng đã quy ra đơn vị cơ bản**, không xếp theo số dòng hay theo tiền;'),
    ('| Tháng M/Y | cả tháng, từ ngày 1 đến hết ngày cuối tháng |', '| Tháng M/Y | trọn tháng: từ mùng 1 tới hết ngày cuối cùng của tháng |'),
    ('| Từ X đến Y, nhóm X–Y | gồm cả X và Y |', '| Từ X đến Y, nhóm X–Y | tính luôn cả X lẫn Y |'),
    ('| Phần trăm thay đổi, tăng trưởng | so với **kỳ trước**; giảm thì ra **số âm** |',
     '| Phần trăm thay đổi, tăng trưởng | đem so với **kỳ liền trước**; nếu giảm thì kết quả là **số âm** |'),
]


def paraphrase_words(base: str | None = None) -> str:
    text = base if base is not None else TRAIN_RULEBOOK.read_text(encoding='utf-8')
    for old, new in REWORDINGS:
        if old not in text:
            raise ValueError(f'rewording: line not found: {old[:60]}')
        text = text.replace(old, new)
    return text
