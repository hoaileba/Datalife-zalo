"""Oracle spec -> Vietnamese question text, and the train noise layers on top of it.

  realize(spec, ctx, rng, marked=False) -> canonical question (templates learned from the train phrasings)
  noisify(text, rng, rates=TRAIN_RATES) -> the question as a shop owner types it (prefix, particle, abbreviations,
                                            telex typos, English words, lowercase, accents off, punctuation)
  make_ctx(L, as_of)                     -> display names of one shop for realize
  sample_spec(L, as_of, rng, intent)     -> a random valid spec of one intent, parameters drawn from the ledger
  noise_stats(questions)                 -> the noise statistics noisify is calibrated on (train vs generated)

Entity names (products, groups, customers, staff, ingredients) are wrapped in ⟦ ⟧ by realize(..., marked=True), so
noisify leaves them intact except for whole-question lowercasing / accent stripping (as in train); noisify always
returns unmarked text. Numbers and dates are never touched. gen.parse.parse is the inverse of realize∘noisify
(checked by scripts/check_surface.py).
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

from . import periods as P
from .oracle import INTENTS, Rules
from .textnorm import KNOWN, detelex_word, fold

MO, MC = '⟦', '⟧'


def mark(s):
    return f'{MO}{s}{MC}'


def unmark(s):
    return s.replace(MO, '').replace(MC, '')


# ====================================================================== context
INDUSTRY_WORDS = {
    'pharmacy': ['cửa hàng', 'nhà thuốc'], 'cafe': ['quán', 'cửa hàng'], 'restaurant': ['quán', 'cửa hàng'],
    'grocery': ['cửa hàng', 'tiệm'], 'construction': ['cửa hàng'],
}
PAY_WORDS = {'cash': ['tiền mặt'], 'transfer': ['chuyển khoản'], 'ewallet': ['ví điện tử'], 'cod': ['COD']}
CHANNEL_WORDS = {'store': ['bán tại quầy'], 'phone': ['bán qua điện thoại'], 'zalo_oa': ['bán qua Zalo OA']}
CUST_GROUP_WORDS = {'sỉ': 'sỉ', 'lẻ': 'lẻ', 'thân thiết': 'thân thiết', 'vip': 'VIP'}
STREETS = ['Hai Bà Trưng', 'Trần Não', 'Lê Trọng Tấn', 'Nguyễn Văn Linh', 'Hậu Giang', 'Lê Lợi', 'Phan Xích Long',
           'Cách Mạng Tháng Tám', 'Võ Văn Tần', 'Nguyễn Trãi']


@dataclass
class Ctx:
    as_of: dt.date
    industry: str = 'shop'
    shop_words: list = field(default_factory=lambda: ['cửa hàng'])
    products: dict = field(default_factory=dict)      # product_id -> name as in the master data
    customers: dict = field(default_factory=dict)     # customer_id -> name (phone numbers stripped)
    staff: dict = field(default_factory=dict)         # staff_id -> name
    ingredients: list = field(default_factory=list)
    base_units: dict = field(default_factory=dict)    # product_id -> base unit


def clean_customer_name(n):
    n = re.sub(r'\(?\+?\d[\d .\-]{6,}\)?', ' ', str(n))
    return re.sub(r'\s+', ' ', n).strip(' -–,')


def make_ctx(L, spec=None, as_of=None) -> Ctx:
    """Display names of one shop. Called as make_ctx(L, spec, as_of) (spec unused, kept for the builder's API) or
    make_ctx(L, as_of)."""
    if as_of is None and isinstance(spec, dt.date):
        spec, as_of = None, spec
    p = L.products
    ind = L.shop.get('industry', 'shop')
    words = INDUSTRY_WORDS.get(ind, ['cửa hàng', 'tiệm'])
    sw = L.shop.get('shop_word')
    if sw:
        words = [sw, 'cửa hàng'] if sw != 'cửa hàng' else ['cửa hàng']
    return Ctx(
        as_of=as_of, industry=ind, shop_words=words,
        products=dict(zip(p.product_id, p.name)),
        customers={c: clean_customer_name(n) for c, n in zip(L.customers.customer_id, L.customers.name)},
        staff=dict(zip(L.staff.staff_id, L.staff.name)),
        ingredients=sorted(set(L.drugs.ingredient.dropna())),
        base_units=dict(zip(p.product_id, p.base_unit)),
    )


# ====================================================================== periods as text
def dmy(d, pad=True):
    return f'{d.day:02d}/{d.month:02d}/{d.year}' if pad else f'{d.day}/{d.month}/{d.year}'


def month_text(y, m, rng):
    return rng.choice([f'tháng {m}/{y}', f'tháng {m}/{y}', f'tháng {m} năm {y}'])


def period_text(per, as_of, rng):
    """(bare phrase, phrase after a verb: 'trong tháng 6/2025', 'từ đầu năm đến nay', ...)."""
    k = per['kind']
    if k == 'day':
        d = per['date']
        if d == as_of:
            return period_text({'kind': 'today'}, as_of, rng)
        if d == as_of - dt.timedelta(days=1):
            return period_text({'kind': 'yesterday'}, as_of, rng)
        s = f'ngày {dmy(d, rng.random() < 0.8)}'
        return s, rng.choice([s, 'trong ' + s])
    if k == 'today':
        s = rng.choice(['hôm nay', 'hôm nay', 'ngày hôm nay'])
        return s, rng.choice([s, 'trong ngày hôm nay'])
    if k == 'yesterday':
        s = rng.choice(['hôm qua', 'hôm qua', 'ngày hôm qua'])
        return s, rng.choice([s, 'trong ngày hôm qua'])
    if k == 'month':
        s = month_text(per['y'], per['m'], rng)
    elif k == 'this_month':
        s = rng.choice(['tháng này', 'tháng này', 'từ đầu tháng này đến nay'])
    elif k == 'quarter':
        s = rng.choice([f"quý {per['q']}/{per['y']}", f"quý {per['q']} năm {per['y']}"])
    elif k == 'this_week':
        s = 'tuần này'
    elif k == 'last_week':
        s = rng.choice(['tuần rồi', 'tuần trước'])
    elif k == 'last_n_days':
        s = rng.choice([f"{per['n']} ngày gần nhất", f"{per['n']} ngày gần đây"])
    elif k == 'ytd':
        s = rng.choice(['từ đầu năm tới hết hôm nay', 'từ đầu năm đến nay', 'từ ngày 1/1 đến hết hôm nay',
                        'năm nay (tính từ đầu năm đến hết hôm nay)'])
    elif k == 'range':
        a, b = per['start'], per['end']
        pad = rng.random() < 0.8
        s = rng.choice([f'từ {dmy(a, pad)} đến hết {dmy(b, pad)}', f'từ ngày {dmy(a, pad)} đến ngày {dmy(b, pad)}',
                        f'từ ngày {dmy(a, pad)} đến hết ngày {dmy(b, pad)}'])
    elif k == 'tet':
        y = per['year']
        opts = [f'dịp Tết {y}', f'Tết {y}', f'dịp Tết năm {y}']
        if y == as_of.year:
            opts += ['dịp Tết năm nay', 'Tết năm nay']
        s = rng.choice(opts)
    elif k == 'season':                       # a window named by the split rulebook
        lab, y = per.get('label') or per['name'], per['year']
        s = rng.choice([f'{lab} {y}', f'{lab} năm {y}'])
    else:
        raise ValueError(k)
    return s, (s if s.startswith(('từ', 'trong')) else 'trong ' + s)


# units that are also words for times or durations: 'bán được bao nhiêu lần' asks a count of sales, not of a unit
EVENT_UNITS = {'lan', 'luot', 'buoi', 'ngay', 'gio', 'phut', 'tuan', 'thang', 'nam', 'ca', 'dot', 'chuyen'}


def prev_text(per, ref, as_of, rng):
    """The comparison period of a change question, as text (None = cannot be written unambiguously)."""
    k = per['kind']
    if ref == 'before_tet':
        return rng.choice(['cùng số ngày ngay trước Tết', 'quãng ngày dài bằng vậy ngay trước Tết'])
    if isinstance(ref, dict) and ref.get('kind') == 'before_tet':
        return f"{ref['days']} ngày ngay trước Tết"
    if ref is not None:
        if ref.get('kind') == 'month' and k == 'month':
            if (ref['y'], ref['m']) == (per['y'] - 1, per['m']) and rng.random() < 0.5:
                return rng.choice(['cùng kỳ năm ngoái', 'cùng kỳ năm trước'])
            return month_text(ref['y'], ref['m'], rng)
        if ref.get('kind') == 'quarter' and k == 'quarter':
            return f"quý {ref['q']}/{ref['y']}"
        return None
    if k == 'month':
        return rng.choice(['tháng trước', 'tháng liền trước', 'tháng trước đó'])
    if k == 'quarter':
        return rng.choice(['quý trước', 'quý liền trước', 'quý trước đó'])
    if k == 'this_month':
        return rng.choice(['cùng kỳ tháng trước', 'cùng số ngày của tháng trước'])
    if k == 'last_week':
        return rng.choice(['tuần trước đó', 'tuần liền trước'])
    if k == 'last_n_days':
        return rng.choice([f"{per['n']} ngày trước đó", f"{per['n']} ngày liền trước"])
    if k == 'tet':
        return 'dịp Tết năm ngoái' if per['year'] == as_of.year and rng.random() < 0.5 else f"Tết {per['year'] - 1}"
    return None


def money(x, rng):
    s = f'{int(x):,}'.replace(',', '.')
    return rng.choice([f'{s} đồng', f'{s} đồng', f'{s}đ'])


# ====================================================================== templates
# {P} period, {Pt} period after a verb ('trong tháng 6/2025'), {S} shop word, {I} item, {U}/{B}/{u} units, {G} group,
# {k} {n} numbers, {D} {D2} dates, {X} money, {A}/{B2} payment or channel words, {CG} customer group, {C} customer,
# {NV} staff. [a|b] = pick one. Templates whose first word is an order (Cho tôi, Liệt kê, Đếm...) end with '.'.
T = {
    'revenue': [
        'Doanh thu {P} là bao nhiêu', 'Tổng doanh thu {P} là bao nhiêu', '{P} {S} bán được tổng cộng bao nhiêu tiền',
        'Cho tôi biết doanh thu {P}', '{Pt}, doanh thu của {S} là [bao nhiêu|được bao nhiêu]',
        '{S} thu về bao nhiêu tiền {Pt}', 'Tính giúp tổng doanh thu {P}', '{P} {S} [bán|bán ra] được bao nhiêu tiền',
    ],
    'revenue_list': [
        'Doanh thu {n} tháng liền nhau kết thúc ở tháng {END} là bao nhiêu mỗi tháng, từ tháng cũ đến tháng mới',
        'Doanh thu {n} tháng liên tiếp từ tháng {START} đến tháng {END} lần lượt là bao nhiêu',
        'Liệt kê doanh thu từng tháng trong {n} tháng liền nhau kết thúc ở tháng {END}, theo thứ tự từ cũ đến mới',
    ],
    'revenue_change_pct': [
        'Doanh thu {P} thay đổi bao nhiêu % so với {R}', 'So với {R}, doanh thu {P} tăng hay giảm mấy phần trăm',
        'Doanh thu {P} hơn hay kém {R} bao nhiêu phần trăm', 'Doanh thu {P} tăng trưởng bao nhiêu % so với {R}',
        '{P} doanh thu thay đổi bao nhiêu phần trăm so với {R}', 'Doanh thu {P} so với {R} tăng/giảm mấy %',
    ],
    'revenue_diff': [
        'Doanh thu {P} tăng hay giảm bao nhiêu tiền so với {R}', 'Doanh thu {P} trừ đi doanh thu {R} thì được bao nhiêu tiền',
        'So với {R}, doanh thu {P} chênh lệch bao nhiêu tiền (giảm thì ghi số âm)',
        'Doanh thu {P} so với {R} tăng hay giảm bao nhiêu đồng',
    ],
    'revenue_trend_up': [
        'Từ tháng {M1} qua tháng {M2} rồi tháng {M3}, doanh thu có tăng liên tục không',
        'Doanh thu các tháng {M1}, {M2} và {M3} có tăng đều không',
        'Doanh thu có tăng liên tục qua các tháng {M1}, {M2}, {M3} không',
    ],
    'best_month': [
        'Từ tháng {START} tới tháng {END}, tháng nào {S} bán được nhiều tiền nhất',
        'Trong các tháng {LIST}, {S} có doanh thu cao nhất vào tháng nào', 'Xét {n} tháng {LIST}, doanh thu tháng nào lớn nhất',
        'Trong {n} tháng từ tháng {START} đến tháng {END}, tháng nào có doanh thu cao nhất',
    ],
    'best_day': [
        '{P} ngày nào {S} bán được nhiều tiền nhất', 'Ngày nào {Pt} doanh thu cao nhất',
        '{Pt}, xét theo doanh thu, ngày nào bán đắt nhất', 'Doanh thu ngày nào cao nhất {Pt}',
    ],
    'best_day:worst': [
        '{Pt}, ngày nào doanh thu thấp nhất', '{P} ngày nào {S} bán được ít tiền nhất', 'Ngày nào {Pt} doanh thu ít nhất',
    ],
    'days_over': [
        '{P} có mấy ngày doanh thu đạt {X} trở lên', '{P} có bao nhiêu ngày đạt doanh thu từ {X} trở lên',
        'Có mấy ngày {Pt} {S} bán được từ {X} trở lên', 'Đếm số ngày {Pt} có doanh thu từ {X} trở lên',
    ],
    'order_count': [
        '{P} {S} có bao nhiêu đơn hàng', '{P} {S} bán được mấy đơn', 'Số đơn {P} là bao nhiêu',
        '{P} có tổng cộng bao nhiêu đơn', 'Cho tôi biết số đơn {P}', '{S} bán được bao nhiêu đơn {Pt}',
        'Tổng số đơn hàng {P} là bao nhiêu',
    ],
    'orders_over': [
        '{Pt}, bao nhiêu đơn có tiền hàng đạt {X} trở lên', '{P} có bao nhiêu đơn có doanh thu từ {X} trở lên',
        'Đếm số đơn {Pt} có tiền hàng từ {X} trở lên',
    ],
    'cancel_count': [
        'Trong {P}, {S} có mấy đơn ở trạng thái huỷ', 'Đếm số đơn đã huỷ {Pt}', 'Số đơn bị huỷ {Pt} là bao nhiêu',
        '{P} có bao nhiêu đơn hàng bị huỷ', '{P} bị huỷ mấy đơn', '{P} có bao nhiêu đơn bị hủy',
    ],
    'cancel_rate': [
        '{P} tỉ lệ đơn bị huỷ là bao nhiêu phần trăm', '{P} {S} có bao nhiêu % đơn bị huỷ', 'Tỉ lệ huỷ đơn {P} là bao nhiêu %',
        '{Pt}, tỉ lệ đơn huỷ là bao nhiêu phần trăm', 'Trong tổng số đơn {P}, đơn bị huỷ chiếm bao nhiêu %',
        'Tỷ lệ đơn hủy {P} là mấy %',
    ],
    'avg_order': [
        'Doanh thu trung bình trên một đơn {P} là bao nhiêu', '{P} doanh thu bình quân mỗi đơn là bao nhiêu',
        'Giá trị trung bình một đơn {P} là bao nhiêu', 'Trung bình mỗi đơn {P} mang về bao nhiêu doanh thu',
        '{P} bình quân mỗi đơn hàng trị giá bao nhiêu tiền',
    ],
    'top_items:qty1': [
        'Mặt hàng nào bán chạy nhất {P}', '{P}, mặt hàng nào bán chạy nhất', 'Mặt hàng hot nhất {P} là mặt hàng nào',
        'Sản phẩm bán được nhiều nhất {P} là gì',
    ],
    'top_items:qtyk': [
        'Cho tôi {k} mặt hàng bán chạy nhất {Pt}', '{k} mặt hàng bán chạy nhất {P} là những mặt hàng nào',
        '{P} top {k} hàng bán chạy nhất là gì', 'Liệt kê {k} sản phẩm bán chạy nhất {P}',
    ],
    'top_items:profit': [
        '{P} hàng nào lời nhất', 'Hàng nào có tổng lãi gộp cao nhất {P}', 'Sản phẩm mang lại lợi nhuận gộp lớn nhất {Pt} là gì',
    ],
    'top_items:revenue': [
        'Mặt hàng nào có doanh thu cao nhất {P}', '{P} hàng nào bán được nhiều tiền nhất',
        'Sản phẩm nào mang về doanh thu lớn nhất {Pt}',
    ],
    'top_items:revenuek': [
        '{k} mặt hàng có doanh thu cao nhất {P} là những mặt hàng nào', 'Liệt kê {k} sản phẩm có doanh thu cao nhất {P}',
    ],
    'items_min_orders': [
        '{Pt}, số sản phẩm xuất hiện ở từ {n} đơn hàng khác nhau trở lên là bao nhiêu',
        'Đếm số mặt hàng có mặt ở ≥ {n} đơn hàng khác nhau {Pt}', '{P} có bao nhiêu mặt hàng được bán trong ít nhất {n} đơn',
    ],
    'top_customers:rev1': [
        '{P} khách nào mua nhiều tiền nhất', 'Ai là khách chi tiêu nhiều nhất {Pt}', 'Khách mua nhiều tiền nhất {P} là ai',
        '{P} ai mua hàng nhiều tiền nhất',
    ],
    'top_customers:revk': [
        'Cho tôi {k} khách mua nhiều tiền nhất {P}', 'Liệt kê {k} khách chi tiêu nhiều nhất {Pt}',
        '{k} khách hàng có tổng tiền mua cao nhất {P} là ai', 'Top {k} khách hàng mua nhiều tiền nhất {P} là ai',
    ],
    'top_customers:ord1': [
        '{P} ai là khách mua nhiều lần nhất, tính theo số đơn', '{P} khách hàng nào mua nhiều đơn nhất',
        'Khách nào có số đơn nhiều nhất {Pt}',
    ],
    'top_customers:ordk': [
        '{k} khách mua nhiều đơn nhất {P} là ai', 'Liệt kê {k} khách có số đơn nhiều nhất {Pt}',
    ],
    'customers_min_orders': [
        '{Pt}, số khách mua ít nhất {n} đơn là bao nhiêu', 'Đếm số khách đã mua ≥ {n} đơn {Pt}',
        '{P} có mấy khách mua từ {n} đơn trở lên',
    ],
    'customers_min_orders_share': [
        '{P} khách mua từ {n} đơn trở lên chiếm bao nhiêu % số khách đã mua',
        'Trong số khách đã mua hàng {P}, bao nhiêu phần trăm mua từ {n} đơn trở lên',
        'Tỉ lệ khách mua ít nhất {n} đơn {Pt} là bao nhiêu %',
    ],
    'customer_count': [
        '{P} có bao nhiêu khách [hàng |]mua hàng, chỉ tính khách có mã', 'Số khách hàng đã mua hàng {Pt} là bao nhiêu',
        '{P} {S} có mấy khách [đến mua|mua hàng]',
    ],
    'cust_group_revenue': [
        'Doanh thu từ khách nhóm {CG} {P} là bao nhiêu', '{P}, các khách thuộc nhóm {CG} mua tổng cộng bao nhiêu tiền hàng',
        'Cho tôi biết doanh thu các đơn của khách nhóm {CG} {P}',
    ],
    'cust_group_share': [
        '{P}, doanh thu từ khách nhóm {CG} chiếm bao nhiêu % tổng doanh thu của {S}',
        'Trong tổng doanh thu {P}, phần của khách nhóm {CG} là mấy phần trăm',
        'Tỉ trọng doanh thu của khách nhóm {CG} trong tổng doanh thu {P} là bao nhiêu phần trăm',
        'Khách nhóm {CG} đóng góp bao nhiêu % tổng doanh thu {P}',
    ],
    'payment_revenue:2': [
        'Doanh thu các đơn trả bằng {A} và doanh thu các đơn trả bằng {B2} {P} lần lượt là bao nhiêu',
        '{P}, doanh thu các đơn trả bằng {A} và các đơn trả bằng {B2} mỗi loại bao nhiêu',
        'So doanh thu các đơn trả bằng {A} với doanh thu các đơn trả bằng {B2} {P}: mỗi bên bao nhiêu',
        'Cho tôi doanh thu các đơn trả bằng {A} và doanh thu các đơn trả bằng {B2} {P}',
    ],
    'payment_revenue:1': [
        'Tính doanh thu các đơn trả bằng {A} {P}', '{P} doanh thu các đơn thanh toán bằng {A} là bao nhiêu',
        'Doanh thu các đơn trả bằng {A} {P} được bao nhiêu',
    ],
    'payment_share': [
        '{P}, doanh thu các đơn trả bằng {A} chiếm bao nhiêu phần trăm tổng doanh thu',
        'Trong tổng doanh thu {P}, doanh thu các đơn trả bằng {A} chiếm bao nhiêu %',
        'Doanh thu các đơn trả bằng {A} {P} bằng bao nhiêu % tổng doanh thu {P}',
    ],
    'channel_revenue:2': [
        'Doanh thu các đơn {A} và doanh thu các đơn {B2} {P} lần lượt là bao nhiêu',
        '{P}, doanh thu các đơn {A} và các đơn {B2} mỗi loại bao nhiêu',
        'So doanh thu các đơn {A} với doanh thu các đơn {B2} {P}: mỗi bên bao nhiêu',
    ],
    'channel_revenue:1': [
        '{P} doanh thu các đơn {A} được bao nhiêu', 'Doanh thu các đơn {A} {P} là bao nhiêu', 'Tính doanh thu các đơn {A} {P}',
    ],
    'channel_share': [
        '{P}, doanh thu các đơn {A} chiếm bao nhiêu % tổng doanh thu',
        'Tỉ trọng doanh thu các đơn {A} trong tổng doanh thu {P} là bao nhiêu phần trăm',
        'Trong tổng doanh thu {P}, doanh thu các đơn {A} chiếm bao nhiêu %',
    ],
    'shift_revenue': [
        'Tổng tiền bán hàng của {SH} {P} là bao nhiêu', 'Doanh thu {SH} {P} được bao nhiêu', '{P} {SH} bán được bao nhiêu tiền',
    ],
    'shift_orders': [
        '{P} {SH} bán được mấy đơn', 'Số đơn {SH} {P} là bao nhiêu', '{P} {SH} có bao nhiêu đơn',
    ],
    'shift_change_pct': [
        '{P} ca chiều so với ca sáng thì doanh thu chênh bao nhiêu %',
        '{Pt}, doanh thu ca chiều hơn hay kém ca sáng bao nhiêu phần trăm', '{P} doanh thu ca chiều chênh ca sáng bao nhiêu phần trăm',
    ],
    'shift_change_pct:orders': [
        '{P} ca chiều so với ca sáng thì số đơn chênh bao nhiêu %', '{P} số đơn ca chiều chênh ca sáng bao nhiêu phần trăm',
        '{Pt}, số đơn ca chiều hơn hay kém ca sáng bao nhiêu phần trăm',
    ],
    'staff_revenue': [
        'Nhân viên mã {NV} {P} bán được tổng cộng bao nhiêu tiền', 'Doanh thu của nhân viên mã {NV} {P} là bao nhiêu',
        '{P} tiền hàng các đơn do nhân viên mã {NV} bán cộng lại là bao nhiêu', '{P} nhân viên {NVN} bán được bao nhiêu tiền',
    ],
    'top_staff': [
        'Ai là người bán có doanh thu cao nhất {P}', 'Nhân viên bán giỏi nhất {P} là ai', '{P} nhân viên nào bán được nhiều tiền nhất',
    ],
    'rx_revenue:1': [
        '{P} {S} bán thuốc kê đơn được bao nhiêu tiền', '{P} thu được bao nhiêu tiền từ các thuốc phải kê đơn',
        'Doanh thu thuốc kê đơn {P} là bao nhiêu',
    ],
    'rx_revenue:0': [
        'Doanh thu hàng không kê đơn {P} là bao nhiêu', '{P} {S} bán hàng không kê đơn được bao nhiêu tiền',
        '{P} thu được bao nhiêu tiền từ hàng không cần kê đơn',
    ],
    'rx_share:1': [
        'Tỉ lệ doanh thu thuốc kê đơn trên tổng doanh thu {P} là bao nhiêu %', '{P} tiền bán thuốc kê đơn chiếm mấy % tổng doanh thu',
        'Doanh thu thuốc kê đơn {P} bằng bao nhiêu % tổng doanh thu',
    ],
    'rx_share:0': [
        'Doanh thu hàng không kê đơn {P} bằng bao nhiêu % tổng doanh thu', '{P} hàng không kê đơn chiếm bao nhiêu phần trăm doanh thu',
    ],
    'ingredient_revenue': [
        'Doanh thu thuốc hoạt chất {ING} {P} là bao nhiêu', '{P} các thuốc có hoạt chất {ING} bán được bao nhiêu tiền',
        'Thuốc có hoạt chất {ING} {P} bán được tổng cộng bao nhiêu tiền',
    ],
    'gross_profit': [
        '{P} lãi gộp của {S} là bao nhiêu', '{P} {S} lãi gộp bao nhiêu tiền', 'Lợi nhuận gộp {P} là bao nhiêu',
    ],
    'net_profit': [
        'Trừ hết chi phí rồi thì {P} còn lãi ròng bao nhiêu', '{P} {S} lãi ròng được bao nhiêu tiền',
        'Lợi nhuận ròng {P} sau khi trừ chi phí là bao nhiêu',
    ],
    'purchase_total': [
        '{P} tổng giá trị các phiếu nhập hàng là bao nhiêu', 'Tổng tiền nhập hàng {P} là bao nhiêu',
        '{P} {S} chi bao nhiêu tiền nhập hàng',
    ],
    'top_supplier': [
        '{P} {S} nhập nhiều tiền hàng nhất từ nhà cung cấp nào', '{P} tiền nhập hàng từ nhà cung cấp nào cao nhất',
        'Nhà cung cấp nào được {S} nhập nhiều tiền nhất {P}',
    ],
    'avg_purchase_price': [
        '{P} giá nhập bình quân một {U} {I} là bao nhiêu', '{P} {S} nhập {I} bình quân bao nhiêu tiền một {U}',
        'Giá nhập bình quân một {U} {I} {Pt} là bao nhiêu',
    ],
    'purchase_minus_sales': [
        'Lấy số nhập trừ số bán của {I} {Pt} thì được bao nhiêu {U}', '{P}, số nhập trừ số bán của {I} là bao nhiêu {U}',
        'Chênh lệch giữa số nhập và số bán của {I} {P} là bao nhiêu {U}',
    ],
    'price_on_day': [
        'Ngày {D} {S} bán {I} với đơn giá bao nhiêu một {U}', 'Giá bán một {U} {I} vào ngày {D} là bao nhiêu',
        'Ngày {D} {S} bán {I} giá bao nhiêu một {U}',
    ],
    'price_effect': [
        'Kể từ khi {I} lên giá ngày {D}, {n} ngày đầu bán được nhiều hay ít hơn {n} ngày liền trước đó bao nhiêu phần trăm, tính theo số {U}',
        'Từ ngày {D}, {I} tăng giá; so {n} ngày kể từ ngày tăng giá với {n} ngày ngay trước đó, lượng bán tính theo {U} thay đổi bao nhiêu %',
        '{I} đổi giá từ ngày {D}. So {n} ngày kể từ ngày đó với {n} ngày trước đó, số {U} bán ra tăng hay giảm bao nhiêu phần trăm',
    ],
    'price_effect:price': [
        'Kể từ khi {I} lên giá {X}/{U}, {n} ngày đầu bán được nhiều hay ít hơn {n} ngày liền trước đó bao nhiêu phần trăm, tính theo số {U}',
        '{I} lên giá {X} từ ngày {D}; so {n} ngày kể từ ngày tăng giá với {n} ngày ngay trước đó, lượng bán tính theo {U} tăng hay giảm bao nhiêu %',
        'Từ ngày {D}, {I} tăng giá lên {X}. So {n} ngày kể từ ngày {D} với {n} ngày ngay trước đó, số {U} bán ra thay đổi bao nhiêu phần trăm',
    ],
    'stock_end': [
        '{WHEN} {I} còn bao nhiêu {U}', 'Tồn kho {I} {WHEN2} là bao nhiêu {U}', '{WHEN}, {I} trong kho còn mấy {U}',
    ],
    'stock_big_small': [
        '{WHEN} {I} còn mấy {B} chẵn, mấy {u} lẻ', 'Tồn kho {I} {WHEN2} được mấy {B} chẵn và mấy {u} lẻ',
        '{WHEN} trong kho còn bao nhiêu {B} {I} nguyên và bao nhiêu {u} lẻ',
    ],
    'stock_value': [
        '{WHEN}, số hàng còn trong kho đáng bao nhiêu tiền, tính theo giá vốn',
        '{WHEN}, tổng giá trị hàng còn trong kho tính theo giá vốn là bao nhiêu tiền',
        'Tiền hàng nằm trong kho {WHEN2} là bao nhiêu, tính theo giá vốn',
    ],
    'out_of_stock_count': [
        '{WHEN}, {S} có mấy mặt hàng đang hết hàng', '{WHEN} có bao nhiêu mặt hàng hết hàng',
        'Số mặt hàng đã hết hàng {WHEN2} là bao nhiêu',
    ],
    'unsold_count': [
        '{P} có bao nhiêu mặt hàng từng bán trước đó nhưng không bán được cái nào',
        '{Pt}, có mấy mặt hàng không ai mua dù trước đó đã từng bán', 'Số mặt hàng ế {Pt} là bao nhiêu',
    ],
    'expiring_items': [
        'Hàng nào hết hạn trong {n} ngày tới, {RANGE}, mà hiện vẫn còn tồn kho',
        'Liệt kê các mặt hàng còn lô tồn có hạn dùng trong {n} ngày tới ({RANGE})',
        'Những sản phẩm nào đang còn hàng có hạn dùng {RANGE}',
    ],
    'expiring_count': [
        '{WHEN}, có mấy mặt hàng còn lô tồn sắp hết hạn trong {n} ngày tới, tức hạn dùng {RANGE}',
        'Có bao nhiêu mặt hàng còn tồn có hạn dùng {RANGE}', 'Số mặt hàng còn lô tồn hết hạn trong {n} ngày tới ({RANGE}) là bao nhiêu',
    ],
    'expiring_value': [
        'Tiền vốn đang nằm ở các lô còn tồn có hạn dùng {RANGE} là bao nhiêu',
        'Giá trị theo giá vốn của các lô còn tồn sẽ hết hạn trong {n} ngày tới ({RANGE}) là bao nhiêu tiền',
        'Các lô còn tồn hết hạn trong {n} ngày tới, {RANGE}, đang giữ bao nhiêu tiền vốn',
    ],
    'nearest_lot_expiry': [
        'Lô {I} gần hết hạn nhất có hạn dùng ngày nào', '{WHEN}, lô {I} gần hết hạn nhất có hạn dùng ngày nào',
        'Trong các lô {I} còn tồn, lô hết hạn sớm nhất có hạn dùng ngày nào',
    ],
    'debt_total': [
        '{DW}, khách hàng còn nợ {S} tổng cộng bao nhiêu tiền', 'Khách còn nợ {S} tổng cộng bao nhiêu {DW2}',
        'Tổng công nợ khách hàng chưa thu {DW2} là bao nhiêu', '{DW}, tổng số tiền khách còn nợ là bao nhiêu',
    ],
    'debt_customers': [
        '{DW}, số khách còn công nợ với {S} là bao nhiêu', '{DW}, có bao nhiêu khách còn nợ {S}',
        '{DW}, {S} còn bao nhiêu khách chưa trả hết nợ',
    ],
    'debt_top': [
        'Liệt kê {k} khách nợ nhiều nhất {DW2}, kèm số tiền còn nợ', 'Top {k} khách hàng có công nợ lớn nhất {DW2} và số nợ của từng người',
        '{DW}, {k} khách nào đang nợ nhiều nhất, mỗi người còn nợ bao nhiêu',
    ],
    'debt_over_age': [
        '{DW}, tổng số tiền khách còn nợ ở các đơn đã đặt quá {n} ngày là bao nhiêu',
        '{DW}, các đơn đặt đã hơn {n} ngày mà khách chưa trả hết còn nợ bao nhiêu tiền',
        'Số tiền còn nợ của các đơn đã quá {n} ngày tính từ ngày đặt, {DW2}, là bao nhiêu',
    ],
    'debt_aging': [
        '{DW}, số tiền còn nợ chia theo tuổi nợ {AGES} là bao nhiêu',
        'Tuổi nợ khách {DW2}: số tiền còn nợ của nhóm {AGES} lần lượt là bao nhiêu',
        'Chia công nợ {DW2} theo tuổi nợ ({AGES}), mỗi nhóm bao nhiêu tiền',
    ],
    'debt_collected': [
        '{P} thu hồi được bao nhiêu tiền công nợ từ khách mua chịu', '{P} {S} thu được bao nhiêu tiền khách trả nợ',
        '{P} khách trả nợ cho các đơn đã mua chịu tổng cộng bao nhiêu tiền', '{Pt}, tiền khách trả bớt nợ các đơn mua chịu được bao nhiêu',
    ],
    'debt_new': [
        '{P} khách mua chịu thêm tổng cộng bao nhiêu tiền', '{Pt}, tổng số tiền khách ghi nợ thêm là bao nhiêu',
        '{P} các khách nợ thêm bao nhiêu tiền',
    ],
    'debt_new_paid': [
        '{P} khách {C} ghi nợ thêm bao nhiêu và trả nợ được bao nhiêu? Ghi hai số theo thứ tự: nợ thêm, trả được',
        '{Pt}, khách {C} mua chịu thêm bao nhiêu và trả bớt nợ được bao nhiêu? Trả lời hai số: nợ thêm, trả được',
        '{P}, {C} ghi nợ thêm bao nhiêu tiền và đã trả nợ được bao nhiêu',
    ],
    'deliveries_count': [
        'Đếm số đợt giao hàng {Pt}', '{P} có tổng cộng bao nhiêu đợt giao hàng', 'Số chuyến giao hàng {P} là bao nhiêu',
    ],
    'qty_item': [
        '{P} {S} bán được tổng cộng bao nhiêu {U} {I}', 'Trong {P} {S} bán được mấy {U} {I}',
        'Số {U} {I} bán được {Pt} là bao nhiêu', '{P} mặt hàng {I} bán được tổng cộng bao nhiêu {U}',
    ],
    'revenue_item': [
        'Doanh thu của {I} {Pt} là bao nhiêu', 'Tiền bán {I} {P} là bao nhiêu', '{P} mặt hàng {I} thu về bao nhiêu tiền',
        '{P} bán {I} được bao nhiêu tiền',
    ],
    'revenue_group': [
        'Doanh thu nhóm hàng {G} {P} là bao nhiêu', '{P} các mặt hàng nhóm {G} thu được tổng cộng bao nhiêu tiền',
        'Nhóm {G} {P} bán được bao nhiêu tiền',
    ],
    'group_share': [
        'Doanh thu nhóm hàng {G} chiếm bao nhiêu % tổng doanh thu {P}', 'Tỉ trọng của nhóm {G} trong doanh thu {P} là bao nhiêu %',
        '{P} nhóm {G} chiếm bao nhiêu % doanh thu', '{Pt}, nhóm {G} đóng góp bao nhiêu % doanh thu cả {S}',
    ],
    'qty_unit': [
        '{P} bán được bao nhiêu {U}', 'Cộng mọi mặt hàng tính theo {U}, {P} bán ra được mấy {U}',
        'Số {U} bán được {P} là bao nhiêu, cộng mọi mặt hàng tính theo {U}', '{P} tổng cộng bán được bao nhiêu {U}',
    ],
    'qty_size': [
        '{P} {S} bán được bao nhiêu ly size {SZ}', '{P} {S} bán ra tổng cộng mấy ly size {SZ}, cộng tất cả các món',
        'Trong {P}, số ly size {SZ} bán được là bao nhiêu, tính mọi loại đồ uống',
    ],
    'unanswerable': [
        'Nhân viên {NVN} làm việc có tận tâm với khách không', '{NVN} có lễ phép, chu đáo với khách không',
        'Nhân viên nào có tay nghề cao nhất {S}', 'Ai trong {S} được khách quý mến nhất',
        'Thái độ phục vụ của nhân viên {NVN} có tốt không', '{S} có mấy khách nhà ở đường {STREET}',
        '{P} khách nữ mua tổng cộng bao nhiêu tiền', 'Trong {P}, khách nam chiếm bao nhiêu % doanh thu',
        '{P} có bao nhiêu đơn bị huỷ vì giao trễ', '{P}, trả hàng vì lỗi và trả vì mua nhầm, bên nào nhiều đơn hơn',
        'Lý do khách trả hàng nhiều nhất {P} là gì', 'Khách có hài lòng với cách phục vụ của {S} không',
        '{P} khách ở đường {STREET} mua tổng cộng bao nhiêu tiền',
    ],
    'qty_unit:named': [                   # a unit that is also a word for times or durations (lần, lượt, ngày...):
        'Cộng mọi mặt hàng tính theo {U}, {P} bán ra được mấy {U}',          # 'bán được bao nhiêu lần' would read
        'Số {U} bán được {P} là bao nhiêu, cộng mọi mặt hàng tính theo {U}',  # as a count of sales
    ],
    'qty_size:word': [
        '{P} {S} bán được bao nhiêu sản phẩm size {SZ}', 'Tổng số món đồ size {SZ} bán ra {Pt} là bao nhiêu',
        'Hàng size {SZ} {P} bán được mấy cái, tính mọi mẫu',
    ],
    'guests_total': [
        '{P} {S} phục vụ bao nhiêu khách', 'Tổng số khách {P} là bao nhiêu', 'Có bao nhiêu khách đến ăn {Pt}',
        '{P} {S} đón được mấy khách', 'Số lượt khách {P} là bao nhiêu',
    ],
    'revenue_per_guest': [
        'Doanh thu bình quân một khách {P} là bao nhiêu', '{P} trung bình mỗi khách chi bao nhiêu tiền',
        'Mỗi khách {Pt} mang lại bao nhiêu doanh thu, tính trung bình', 'Bình quân đầu người {P} là bao nhiêu tiền',
    ],
    'area_revenue': [
        'Doanh thu ở {A} {P} là bao nhiêu', '{P} {A} bán được bao nhiêu tiền', '{A} {Pt} thu về bao nhiêu tiền',
    ],
    'top_table': [
        'Bàn nào có doanh thu cao nhất {P}', '{P} bàn nào bán được nhiều tiền nhất', 'Bàn mang về nhiều doanh thu nhất {Pt} là bàn nào',
    ],
    'service_revenue': [
        'Tiền công dịch vụ {P} là bao nhiêu', 'Doanh thu dịch vụ {P} được bao nhiêu', '{P} {S} thu được bao nhiêu tiền công',
        'Tổng tiền làm dịch vụ {Pt} là bao nhiêu',
    ],
    'service_revenue:goods': [
        'Tiền bán hàng hoá, không tính dịch vụ, {P} là bao nhiêu', '{P} bán hàng (không kể tiền công dịch vụ) được bao nhiêu tiền',
        'Doanh thu phần hàng hoá ngoài dịch vụ {P} là bao nhiêu',
    ],
    'service_share': [
        'Dịch vụ chiếm bao nhiêu % doanh thu {P}', 'Tỉ trọng doanh thu dịch vụ {P} là bao nhiêu phần trăm',
        '{P} tiền công dịch vụ chiếm mấy phần trăm tổng doanh thu',
    ],
    'vehicle_count': [
        '{P} {S} sửa cho bao nhiêu xe', 'Có bao nhiêu xe vào {S} {Pt}', 'Số xe đến làm {P} là bao nhiêu',
    ],
    'repeat_vehicles': [
        '{P} có bao nhiêu xe quay lại', 'Bao nhiêu xe quay lại {S} {Pt}', 'Đếm số xe quay lại {Pt}',
    ],
    'repeat_vehicles:n': [
        '{P} có bao nhiêu xe đến {S} từ {n} lần trở lên', 'Đếm số xe vào làm từ {n} lượt trở lên {Pt}',
    ],
    # facts a shop's sales export never records, per trade (S6: the data cannot answer, not 0)
    'unanswerable:hotpot': ['Bàn nào khách ngồi lâu nhất {P}', 'Khách {P} có khen món lẩu Thái không',
                            'Món nào bị khách chê nhiều nhất {P}'],
    'unanswerable:restaurant': ['Bàn nào khách ngồi lâu nhất {P}', 'Món nào bị khách chê nhiều nhất {P}'],
    'unanswerable:motorbike_repair': ['Xe nào sửa lâu nhất {P}', 'Thợ nào sửa xe nhanh nhất {S}',
                                      'Xe Honda chiếm bao nhiêu phần trăm số xe {P}'],
    'unanswerable:spa_salon': ['Khách nào hài lòng nhất với dịch vụ {P}', 'Kỹ thuật viên nào được khách khen nhiều nhất',
                               'Bao nhiêu khách quay lại vì được giới thiệu {P}'],
    'unanswerable:fashion': ['Màu nào được khách chọn nhiều nhất {P}', 'Khách mua áo có mặc vừa không',
                             'Bao nhiêu khách đổi hàng vì chật {P}'],
    'unanswerable:fruit_shop': ['Trái cây nhập từ vườn nào ngọt nhất', 'Bao nhiêu kg trái cây bị hư phải bỏ {P}',
                                'Xoài cát Hòa Lộc lấy ở tỉnh nào'],
    'unanswerable:milk_tea': ['Khách thích ít đường hay nhiều đường hơn {P}', 'Bao nhiêu ly bị khách chê nhạt {P}'],
    'unanswerable:phone_shop': ['Máy nào bị bảo hành nhiều nhất {P}', 'Khách mua iPhone có trả góp không',
                                'Bao nhiêu máy bán ra còn hạn bảo hành'],
    'unanswerable:pet_shop': ['Giống chó nào đến tắm nhiều nhất {P}', 'Bé mèo nào được cắt tỉa lông đẹp nhất'],
    'unanswerable:agri_supply': ['Bà con trồng lúa hay trồng rau mua nhiều phân hơn {P}',
                                 'Ruộng của khách nào được mùa nhất'],
    'unanswerable:drug': [
        'Thuốc có hoạt chất {ING} người lớn nên uống mỗi lần mấy viên', 'Liều dùng của {I} cho trẻ em là bao nhiêu',
        '{I} có tác dụng phụ gì không',
    ],
}

ORDER_WORDS = ('cho tôi', 'cho mình', 'liệt kê', 'đếm', 'tính', 'giúp mình', 'lấy', 'chia')


def template_counts():
    out = {}
    for k, v in T.items():
        out[k.split(':')[0]] = out.get(k.split(':')[0], 0) + len(v)
    return out


def _expand(s, rng):
    return re.sub(r'\[([^\]]*)\]', lambda m: rng.choice(m[1].split('|')), s)


def _fill(tpl, rng, **kw):
    s = _expand(tpl, rng)
    s = s.format(**{k: v for k, v in kw.items() if '{' + k + '}' in s})
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r' ,', ',', s)
    return s


def _finish(s):
    i = next((j for j, c in enumerate(s) if c.isalpha()), None)
    if i is not None and s[i] != MO and not s.startswith(MO):
        s = s[:i] + s[i].upper() + s[i + 1:]
    low = unmark(s).lower()
    end = '.' if low.startswith(ORDER_WORDS) else '?'
    return s.rstrip(' ?.') + end


# ====================================================================== realize
def _when(date, as_of, rng):
    """(sentence-start, trailing) phrases of a stock-like date."""
    if date == as_of:
        a = rng.choice(['Cuối ngày hôm nay', 'Hết hôm nay', 'Tính đến cuối ngày hôm nay'])
        return a, rng.choice(['cuối ngày hôm nay', 'tính đến hết hôm nay'])
    d = dmy(date)
    a = rng.choice([f'Cuối ngày {d}', f'Hết ngày {d}', f'Tính đến hết ngày {d}', f'Đến cuối ngày {d}'])
    return a, rng.choice([f'cuối ngày {d}', f'đến hết ngày {d}', f'tính đến hết ngày {d}'])


def _debt_when(date, as_of, rng):
    d = dmy(date)
    a = rng.choice([f'Tính đến hết ngày {d}', f'Đến hết ngày {d}', f'Tính tới hết ngày {d}'])
    return a, rng.choice([f'tính đến hết ngày {d}', f'đến hết ngày {d}'])


def _unit_word(spec, ctx, key='unit'):
    u = spec.get(key)
    if u is None:
        u = ctx.base_units.get(spec.get('item'))
    return str(u) if u is not None else 'cái'


def _months_list(periods, rng):
    ms = [f"{p['m']}/{p['y']}" for p in periods]
    head = ', '.join(ms[:-1])
    return f'{head} và {ms[-1]}' if len(ms) > 1 else ms[0]


def realize(spec, ctx: Ctx, rng, marked=False) -> str:
    """Canonical Vietnamese question for an oracle spec (entity names wrapped in ⟦ ⟧ when marked)."""
    it = spec['intent']
    as_of = ctx.as_of
    kw = {'S': rng.choice(ctx.shop_words)}
    per = spec.get('period')
    if per is not None:
        kw['P'], kw['Pt'] = period_text(per, as_of, rng)
    key = it
    if 'item' in spec:
        kw['I'] = mark(ctx.products.get(spec['item'], spec['item']))
    if it == 'revenue_list':
        ps = spec['periods']
        kw.update(n=len(ps), START=f"{ps[0]['m']}/{ps[0]['y']}", END=f"{ps[-1]['m']}/{ps[-1]['y']}")
    elif it in ('revenue_change_pct', 'revenue_diff'):
        kw['R'] = prev_text(per, spec.get('ref'), as_of, rng)
        if spec.get('ref_text') == 'neutral' and per['kind'] == 'this_month':
            kw['R'] = rng.choice(['tháng trước', 'tháng trước đó'])     # which days: the rulebook says
        elif spec.get('ref_text') == 'full' and per['kind'] == 'this_month':
            kw['R'] = rng.choice(['cả tháng trước', 'trọn tháng trước'])  # the words fix the window
        if kw['R'] is None:
            raise ValueError(f'cannot write the reference period of {spec}')
    elif it == 'revenue_trend_up':
        ps = spec['periods']
        if len(ps) != 3:
            key = 'revenue_trend_up:n'
        kw.update({f'M{i + 1}': f"{p['m']}/{p['y']}" for i, p in enumerate(ps)})
        if len(ps) != 3:
            tpl = rng.choice(['Doanh thu các tháng {LIST} có tăng đều không',
                              'Doanh thu có tăng liên tục qua các tháng {LIST} không'])
            return _out(_fill(tpl, rng, LIST=_months_list(ps, rng)), marked)
    elif it == 'best_month':
        ps = spec['periods']
        consecutive = all((b['y'] * 12 + b['m']) - (a['y'] * 12 + a['m']) == 1 for a, b in zip(ps, ps[1:]))
        kw.update(n=len(ps), LIST=_months_list(ps, rng), START=f"{ps[0]['m']}/{ps[0]['y']}",
                  END=f"{ps[-1]['m']}/{ps[-1]['y']}")
        if not consecutive:
            tpl = rng.choice(T['best_month'][1:3])
            return _out(_finish(_fill(tpl, rng, **kw)), marked)
    elif it == 'best_day':
        key = 'best_day:worst' if spec.get('worst') else 'best_day'
    elif it in ('days_over', 'orders_over'):
        kw['X'] = money(spec['threshold'], rng)
    elif it == 'top_items':
        by, k = spec.get('by', 'qty'), spec.get('k', 1)
        kw['k'] = k
        key = {'qty': 'top_items:qty1' if k == 1 else 'top_items:qtyk', 'profit': 'top_items:profit',
               'revenue': 'top_items:revenue' if k == 1 else 'top_items:revenuek'}[by]
    elif it in ('items_min_orders', 'customers_min_orders', 'customers_min_orders_share'):
        kw['n'] = spec['n']
    elif it == 'top_customers':
        k = spec.get('k', 1)
        kw['k'] = k
        key = 'top_customers:' + ('rev' if spec.get('by', 'revenue') == 'revenue' else 'ord') + ('1' if k == 1 else 'k')
    elif it in ('cust_group_revenue', 'cust_group_share'):
        kw['CG'] = CUST_GROUP_WORDS.get(spec['group'], spec['group'])
    elif it in ('payment_revenue', 'channel_revenue'):
        vals = spec['methods'] if it == 'payment_revenue' else spec['channels']
        words = PAY_WORDS if it == 'payment_revenue' else CHANNEL_WORDS
        kw['A'] = rng.choice(words[vals[0]])
        if len(vals) > 1:
            kw['B2'] = rng.choice(words[vals[1]])
        key = f'{it}:{min(len(vals), 2)}'
    elif it == 'payment_share':
        kw['A'] = rng.choice(PAY_WORDS[spec['method']])
    elif it == 'channel_share':
        kw['A'] = rng.choice(CHANNEL_WORDS[spec['channel']])
    elif it == 'shift_change_pct':
        key = 'shift_change_pct:orders' if spec.get('measure') == 'orders' else it
    elif it in ('shift_revenue', 'shift_orders'):
        kw['SH'] = 'ca sáng' if spec['shift'] == 'morning' else 'ca chiều'
    elif it == 'staff_revenue':
        kw['NV'] = mark(spec['staff'])
        name = ctx.staff.get(spec['staff'])
        tpls = T[it] if name else T[it][:3]
        kw['NVN'] = mark(name) if name else ''
        return _out(_finish(_fill(rng.choice(tpls), rng, **kw)), marked)
    elif it in ('rx_revenue', 'rx_share'):
        key = f"{it}:{int(bool(spec['rx']))}"
    elif it == 'ingredient_revenue':
        kw['ING'] = mark(spec['ingredient'])
    elif it in ('avg_purchase_price', 'purchase_minus_sales', 'price_on_day', 'qty_item', 'stock_end'):
        kw['U'] = _unit_word(spec, ctx)
        if 'date' in spec:
            kw['D'] = dmy(spec['date'])
    elif it == 'price_effect':
        kw.update(D=dmy(spec['date']), n=spec['n'], U=_unit_word(spec, ctx))
        if spec.get('new_price'):
            kw['X'] = money(spec['new_price'], rng)
            key = 'price_effect:price'
    elif it == 'stock_big_small':
        kw.update(B=str(spec['big_unit']), u=_unit_word({'item': spec['item']}, ctx))
    elif it in ('expiring_items', 'expiring_count', 'expiring_value'):
        d, n = spec['date'], spec['n']
        kw['n'] = n
        kw['RANGE'] = f'từ {dmy(d)} đến hết {dmy(d + dt.timedelta(days=n))}'   # every template carries the start date
    elif it in ('debt_top',):
        kw['k'] = spec.get('k', 5)
    elif it == 'debt_over_age':
        kw['n'] = spec['days']
    elif it == 'debt_aging':
        e = spec.get('edges', [7, 15])
        parts, lo = [], 0
        for x in e:
            parts.append(f'{lo}–{x}' + rng.choice(['', ' ngày']))
            lo = x + 1
        kw['AGES'] = ', '.join(parts) + f' và trên {e[-1]} ngày'
    elif it == 'debt_new_paid':
        kw['C'] = mark(ctx.customers.get(spec['customer'], spec['customer']))
    elif it == 'revenue_group' or it == 'group_share':
        kw['G'] = mark(spec['group'])
    elif it == 'qty_unit':
        kw['U'] = str(spec['unit'])
        if fold(kw['U']).strip() in EVENT_UNITS:
            key = 'qty_unit:named'
    elif it == 'qty_size':
        kw['SZ'] = spec['size'].upper()
        if spec.get('style') == 'word':
            key = 'qty_size:word'
    elif it == 'area_revenue':
        kw['A'] = mark(spec['area'])
    elif it == 'service_revenue' and spec.get('part') == 'goods':
        key = 'service_revenue:goods'
    elif it == 'repeat_vehicles' and spec.get('n'):
        kw['n'] = spec['n']
        key = 'repeat_vehicles:n'
    elif it == 'unanswerable':
        names = list(ctx.staff.values()) or ['Lan', 'Minh Anh', 'Hoàng Nam']
        kw.update(NVN=mark(rng.choice(names)), STREET=rng.choice(STREETS))
        if 'P' not in kw:
            kw['P'], kw['Pt'] = period_text({'kind': 'this_month'}, as_of, rng)
        pool = list(T['unanswerable'])
        trade = T.get(f'unanswerable:{ctx.industry}')
        if trade and rng.random() < 0.6:
            pool = list(trade)
        if ctx.ingredients and ctx.products:
            kw['ING'] = mark(rng.choice(ctx.ingredients))
            kw.setdefault('I', mark(rng.choice(list(ctx.products.values()))))
            pool += T['unanswerable:drug']
        return _out(_finish(_fill(rng.choice(pool), rng, **kw)), marked)
    if 'date' in spec and it in ('stock_end', 'stock_big_small', 'stock_value', 'out_of_stock_count', 'nearest_lot_expiry',
                                 'expiring_count'):
        kw['WHEN'], kw['WHEN2'] = _when(spec['date'], as_of, rng)
        if it == 'nearest_lot_expiry' and spec['date'] != as_of:
            d = dmy(spec['date'])
            kw['WHEN'] = rng.choice([f'Tính đến hết ngày {d}', f'Hết ngày {d}'])
            return _out(_finish(_fill(T[it][1], rng, **kw)), marked)
    if it.startswith('debt_') and 'date' in spec:
        kw['DW'], kw['DW2'] = _debt_when(spec['date'], as_of, rng)
    tpls = T[key]
    if it == 'nearest_lot_expiry':
        tpls = [tpls[0], tpls[2]]
    return _out(_finish(_fill(rng.choice(tpls), rng, **kw)), marked)


def _out(s, marked):
    s = _finish(s)
    return s if marked else unmark(s)


# ====================================================================== noise
TRAIN_RATES = {
    'prefix': 0.22, 'suffix': 0.16, 'lower_start': 0.52, 'no_accent_if_lower': 0.495, 'lower_names_if_lower': 0.5,
    'punct_if_upper': 0.96, 'punct_if_lower': 0.04,
    'dthu': 0.47, 'bao_nhieu': 0.28, 'bare_nhieu': 0.25, 'duoc': 0.38, 'hom_nay': 0.4, 'hom_qua': 0.8,
    'truoc': 0.22, 'voi': 0.28, 'th_truoc': 0.7, 'san_pham': 0.5, 'khong': 0.23, 'nhieu': 0.05, 'la_gi': 0.1,
    'pay_abbr': 0.15,
    'telex': 0.075, 'telex_two': 0.42, 'english': 0.05,
}

PREFIXES = [('Xem giúp', 0.047), ('Cho hỏi', 0.036), ('Cho tôi biết', 0.028), ('Cho mình hỏi', 0.022),
            ('check giùm', 0.022), ('coi giùm', 0.02), ('Giúp mình', 0.009), ('e', 0.013), ('ê', 0.008),
            ('ee', 0.003), ('check gium', 0.006)]
SUFFIXES = [('nhỉ', 0.037), ('vậy', 0.037), ('z', 0.018), ('ạ', 0.017), ('ta', 0.014), ('ha', 0.01),
            ('đó', 0.016), ('hả', 0.008), ('vaayj', 0.002)]


def _wchoice(rng, pairs):
    tot = sum(w for _, w in pairs)
    x = rng.random() * tot
    for v, w in pairs:
        x -= w
        if x <= 0:
            return v
    return pairs[-1][0]


def _segments(s):
    """[(text, protected)] of a marked string."""
    out, i = [], 0
    for m in re.finditer(re.escape(MO) + r'(.*?)' + re.escape(MC), s):
        if m.start() > i:
            out.append([s[i:m.start()], False])
        out.append([m[1], True])
        i = m.end()
    if i < len(s):
        out.append([s[i:], False])
    return out


def _sub_free(segs, pat, repl, rng, rate, flags=re.I):
    """Replace pat in unprotected segments, each occurrence with probability rate (repl may be a list/callable)."""
    for sg in segs:
        if sg[1]:
            continue

        def one(m):
            if rng.random() >= rate:
                return m[0]
            r = repl(m) if callable(repl) else (rng.choice(repl) if isinstance(repl, list) else repl)
            return m.expand(r) if '\\' in r else r
        sg[0] = re.sub(pat, one, sg[0], flags=flags)


def strip_accents(s):
    s = unicodedata.normalize('NFD', s).replace('đ', 'd').replace('Đ', 'D')
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return unicodedata.normalize('NFC', s.replace('đ', 'd').replace('Đ', 'D'))


TONE_KEYS = {'́': 's', '̀': 'f', '̉': 'r', '̃': 'x', '̣': 'j'}
MOD_KEYS = {('a', '̂'): 'aa', ('e', '̂'): 'ee', ('o', '̂'): 'oo', ('a', '̆'): 'aw',
            ('o', '̛'): 'ow', ('u', '̛'): 'uw'}


def telex(word, partial=False):
    """Raw telex keystrokes of a Vietnamese word: 'được' -> 'dduwowcj', 'tháng' -> 'thangs' (partial: marks of the
    vowels dropped, 'của' -> 'cuar')."""
    w = unicodedata.normalize('NFD', word.lower())
    out, tone = [], ''
    i = 0
    while i < len(w):
        c = w[i]
        if c == 'đ':
            out.append('d' if partial else 'dd')
        elif unicodedata.category(c) == 'Mn':
            if c in TONE_KEYS:
                tone = TONE_KEYS[c]
            elif out and (out[-1][-1], c) in MOD_KEYS and not partial:
                out[-1] = out[-1][:-1] + MOD_KEYS[(out[-1][-1], c)]
        else:
            out.append(c)
        i += 1
    return ''.join(out) + tone


def _telex_ok(word, tw):
    f = fold(word)
    return f in KNOWN and tw != f and tw not in KNOWN and detelex_word(tw) == f


def _lower(s):
    return s.lower()


def noisify(text, rng, rates=None) -> str:
    """Train-like surface noise on a (marked or plain) canonical question; returns plain text."""
    R = {**TRAIN_RATES, **(rates or {})}
    s = text.rstrip(' ?.')
    end_mark = text.rstrip()[-1] if text.rstrip()[-1:] in ('?', '.') else '?'
    plain_low = unmark(s).lower()
    # ---- prefix / particle
    if rng.random() < R['prefix'] and not plain_low.startswith(ORDER_WORDS + ('xem', 'check', 'coi')):
        pre = _wchoice(rng, PREFIXES)
        first = s[0]
        s = f'{pre} ' + (s[0].lower() + s[1:] if first != MO else s)
    if rng.random() < R['suffix'] and '?' not in s and not plain_low.endswith(('không', 'là ai', 'ngày nào')):
        s = s + ' ' + _wchoice(rng, SUFFIXES)
    segs = _segments(s)
    # ---- abbreviations (only on template words)
    _sub_free(segs, r'\bdoanh thu\b', 'dthu', rng, R['dthu'])
    _sub_free(segs, r'\b(là|được|về) bao nhiêu(?=$| %| phần trăm| tiền\b(?! nhất))', [r'\1 nhiêu', r'\1 nhiu'], rng,
              R['bare_nhieu'] * R['bao_nhieu'] * 2)
    _sub_free(segs, r'\bbao nhiêu\b', ['bn', 'bnhiu', 'bao nhiu'], rng, R['bao_nhieu'])
    _sub_free(segs, r'\bđược\b', ['đc', 'đc', 'dc'], rng, R['duoc'])
    _sub_free(segs, r'\bhôm nay\b', ['hnay', 'bữa nay'], rng, R['hom_nay'])
    _sub_free(segs, r'\bhôm qua\b', ['hqua', 'bữa qua'], rng, R['hom_qua'])
    _sub_free(segs, r'\btháng trước\b', 'th trước', rng, R['th_truoc'])
    _sub_free(segs, r'\btrước\b', 'trc', rng, R['truoc'])
    _sub_free(segs, r'\bvới\b', 'vs', rng, R['voi'])
    _sub_free(segs, r'\bsản phẩm\b', 'sp', rng, R['san_pham'])
    _sub_free(segs, r'\bkhông\b(?= kê đơn| ai| cần)', 'ko', rng, R['khong'])
    _sub_free(segs, r'\bnhiều\b', 'nhìu', rng, R['nhieu'])
    _sub_free(segs, r'\blà gì\b', 'là j', rng, R['la_gi'])
    _sub_free(segs, r'\btiền mặt\b', 'tm', rng, R['pay_abbr'])
    _sub_free(segs, r'\bchuyển khoản\b', 'ck', rng, R['pay_abbr'])
    # ---- English code switch
    if rng.random() < R['english']:
        opts = [(r'\bdoanh thu\b', 'revenue'), (r'(?<!hoá )(?<!kê )\bđơn\b(?! giá)(?! hàng khác)', 'bill'),
                (r'(?<!hoá )(?<!kê )\bđơn hàng\b(?! khác)', 'order'), (r'\btổng cộng\b', 'total'),
                (r'\bbán chạy nhất\b', 'best seller')]
        opts = [o for o in opts if any(not sg[1] and re.search(o[0], sg[0], re.I) for sg in segs)]
        if opts:
            pat, rep = rng.choice(opts)
            _sub_free(segs, pat, rep, rng, 1.0)
    # ---- telex typos (one or two template words)
    if rng.random() < R['telex']:
        cands = []
        for si, sg in enumerate(segs):
            if sg[1]:
                continue
            for m in re.finditer(r'[^\W\d_]+', sg[0]):
                w = m[0]
                if w != strip_accents(w) or w.lower() in ('hom', 'nhieu', 'bao'):
                    tw = telex(w, partial=rng.random() < 0.1)
                    if _telex_ok(w, tw):
                        cands.append((si, m.start(), m.end(), tw))
        if cands:
            n = 2 if rng.random() < R['telex_two'] and len(cands) > 1 else 1
            pick = sorted(rng.sample(cands, n), key=lambda c: (c[0], -c[1]))
            for si, a, b, tw in pick:
                segs[si][0] = segs[si][0][:a] + tw + segs[si][0][b:]
    # ---- case / accents / punctuation
    low = rng.random() < R['lower_start']
    if low:
        lower_names = rng.random() < R['lower_names_if_lower']
        for sg in segs:
            if not sg[1] or lower_names:
                sg[0] = _lower(sg[0])
        if rng.random() < R['no_accent_if_lower']:
            for sg in segs:
                sg[0] = strip_accents(sg[0])
    out = ''.join(sg[0] for sg in segs)
    if not low:
        i = next((j for j, c in enumerate(out) if c.isalpha()), None)
        if i is not None:
            out = out[:i] + out[i].upper() + out[i + 1:]
    if rng.random() < (R['punct_if_lower'] if low else R['punct_if_upper']):
        out = out + end_mark
    return re.sub(r'\s+', ' ', out).strip()


# ====================================================================== noise statistics
ABBR_STATS = [('dthu', r'\bdthu\b'), ('bn|bnhiu|bao nhiu|nhiu', r'\b(bn|bnhiu|bao nhiu)\b|(?<!bao )\bnhi[eêu]u\b(?! nhất| hơn| tiền nhất)'),
              ('đc/dc', r'\b(đc|dc)\b'), ('hnay/bữa nay', r'\bhnay\b|\b(bữa|bua) nay\b'),
              ('hqua/bữa qua', r'\bhqua\b|\b(bữa|bua) qua\b'), ('trc', r'\btrc\b'), ('vs', r'\bvs\b'),
              ('th trước', r'\bth (trước|truoc|trc)\b'), ('sp', r'\bsp\b'),
              ('english', r'\b(revenue|bill|order|total|best seller)\b'), ('check', r'\bcheck\b')]


def noise_stats(questions):
    n = max(1, len(questions))
    st = {}

    def first_alpha(q):
        return next((c for c in q if c.isalpha()), 'A')
    st['lowercase start'] = sum(first_alpha(q).islower() for q in questions) / n
    st['no accents'] = sum(all(ord(c) < 128 or c in '≥–—' for c in q) for q in questions) / n
    st['ends with ?/.'] = sum(q.rstrip()[-1:] in ('?', '.') for q in questions) / n
    st['prefix'] = sum(bool(re.match(r'(cho mình hỏi|cho hỏi|xem giúp|xem giup|cho tôi biết|cho toi biet|check|coi|'
                                     r'giúp mình|giup minh|cho minh hoi|cho hoi|ee?\b|ê\b)', q.lower())) for q in questions) / n
    st['particle'] = sum(bool(re.search(r'\b(nhỉ|nhi|ạ|vậy|vay|vaayj|z|ta|đó|do|ha|hả)\s*[?.]?$', q.lower()))
                         for q in questions) / n
    for k, p in ABBR_STATS:
        st[k] = sum(bool(re.search(p, q.lower())) for q in questions) / n
    tel = 0
    for q in questions:
        toks = re.findall(r'[a-z]+', fold(q))
        if any(t not in KNOWN and detelex_word(t) != t and detelex_word(t) in KNOWN for t in toks):
            tel += 1
    st['telex typo'] = tel / n
    return st


# ====================================================================== random specs (round-trip check, generators)
def _months(L, as_of, full=True):
    start = pd.Timestamp(L.shop['start']).date()
    end = min(L.shop['end'], as_of)
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        if not full or P.month_end(y, m) <= end:
            out.append((y, m))
        y, m = P.add_months(y, m, 1)
    return out


def _tet_years(L, as_of):
    out = []
    for y in range(L.shop['start'].year, as_of.year + 1):
        try:
            s, e = P.bounds({'kind': 'tet', 'year': y}, as_of, Rules())
        except ValueError:
            continue
        if s >= L.shop['start'] and s <= as_of:
            out.append(y)
    return out


PERIOD_WEIGHTS = {'month': 0.5, 'this_month': 0.07, 'quarter': 0.06, 'last_week': 0.05, 'this_week': 0.03,
                  'last_n_days': 0.06, 'ytd': 0.04, 'range': 0.05, 'today': 0.04, 'yesterday': 0.04, 'day': 0.03,
                  'tet': 0.03}


def random_period(L, as_of, rng, kinds=None):
    kinds = kinds or list(PERIOD_WEIGHTS)
    ms = _months(L, as_of)
    tets = _tet_years(L, as_of)
    kinds = [k for k in kinds if (k != 'tet' or tets) and (k not in ('month', 'quarter') or ms)]
    k = _wchoice(rng, [(k, PERIOD_WEIGHTS.get(k, 0.05)) for k in kinds])
    start = L.shop['start']
    if k == 'month':
        y, m = rng.choice(ms)
        return {'kind': 'month', 'y': y, 'm': m}
    if k == 'quarter':
        qs = sorted({(y, (m - 1) // 3 + 1) for y, m in ms})
        y, q = rng.choice(qs)
        return {'kind': 'quarter', 'y': y, 'q': q}
    if k == 'last_n_days':
        return {'kind': 'last_n_days', 'n': rng.choice([7, 7, 14, 30, 30, 60, 90])}
    if k == 'range':
        span = (as_of - start).days
        a = start + dt.timedelta(days=rng.randrange(max(1, span - 7)))
        b = min(as_of, a + dt.timedelta(days=rng.choice([6, 6, 13, 20, 29])))
        return {'kind': 'range', 'start': a, 'end': b}
    if k == 'day':
        return {'kind': 'day', 'date': as_of - dt.timedelta(days=rng.randrange(2, max(3, (as_of - start).days)))}
    if k == 'tet':
        return {'kind': 'tet', 'year': rng.choice(tets)}
    return {'kind': k}


def _month_spec(y, m):
    return {'kind': 'month', 'y': y, 'm': m}


def _period_items(L, as_of, per):
    s, e = P.bounds(per, as_of, Rules())
    o = L.orders[(L.orders.created >= pd.Timestamp(s)) & (L.orders.created < pd.Timestamp(e) + pd.Timedelta(days=1))]
    return L.lines[L.lines.order_id.isin(o.order_id)], o


def _round_nice(x):
    if x <= 0:
        return 1000
    mag = 10 ** max(3, len(str(int(x))) - 2)
    return int(round(x / mag) * mag) or mag


def sample_spec(L, as_of, rng, intent):
    """A random spec of `intent` with parameters drawn from the ledger (None if the shop cannot carry it)."""
    S = lambda **kw: {'intent': intent, **kw}
    per = lambda kinds=None: random_period(L, as_of, rng, kinds)
    prod = L.products
    sold = L.lines.product_id.value_counts()
    sold_ids = [p for p in sold.index if p in set(prod.product_id)]
    ms = _months(L, as_of)
    if intent == 'unanswerable':
        return S(period=per(['month', 'this_month']))
    if intent == 'shift_change_pct':
        return S(period=per(), measure=rng.choice(['revenue', 'orders']))
    if intent in ('revenue', 'order_count', 'avg_order', 'cancel_count', 'cancel_rate', 'gross_profit', 'net_profit',
                  'purchase_total', 'top_supplier', 'customer_count', 'debt_collected', 'debt_new', 'deliveries_count',
                  'top_staff', 'unsold_count'):
        kinds = None
        if intent == 'unsold_count':
            kinds = ['month', 'this_month', 'last_week', 'last_n_days', 'quarter']
        return S(period=per(kinds))
    if intent == 'revenue_list':
        if len(ms) < 3:
            return None
        n = rng.choice([2, 3, 3, 4])
        i = rng.randrange(n - 1, len(ms))
        return S(periods=[_month_spec(*m) for m in ms[i - n + 1:i + 1]])
    if intent in ('revenue_change_pct', 'revenue_diff'):
        kinds = ['month', 'month', 'this_month', 'quarter', 'last_week', 'last_n_days', 'tet']
        p = per(kinds)
        ref = None
        if p['kind'] == 'month' and rng.random() < 0.35:
            cands = [m for m in ms if m < (p['y'], p['m'])]
            if cands:
                same = (p['y'] - 1, p['m'])
                y, m = same if same in cands and rng.random() < 0.6 else rng.choice(cands)
                ref = _month_spec(y, m)
        if p['kind'] == 'tet' and intent == 'revenue_change_pct' and rng.random() < 0.4:
            ref = 'before_tet'
        return S(period=p, ref=ref) if ref else S(period=p)
    if intent in ('revenue_trend_up', 'best_month'):
        if len(ms) < 3:
            return None
        n = 3 if intent == 'revenue_trend_up' or rng.random() < 0.7 else rng.choice([2, 4])
        i = rng.randrange(n - 1, len(ms))
        return S(periods=[_month_spec(*m) for m in ms[i - n + 1:i + 1]])
    if intent == 'best_day':
        return S(period=per(['month', 'this_month', 'quarter', 'last_week', 'last_n_days', 'range']),
                 worst=rng.random() < 0.25)
    if intent in ('days_over', 'orders_over'):
        p = per(['month', 'month', 'this_month', 'quarter', 'last_n_days'])
        _, o = _period_items(L, as_of, p)
        if o.empty:
            return S(period=p, threshold=1_000_000)
        if intent == 'days_over':
            daily = o.groupby(o.created.dt.normalize()).total.sum()
            x = daily.quantile(rng.uniform(0.2, 0.9))
        else:
            x = o.total.quantile(rng.uniform(0.5, 0.95))
        return S(period=p, threshold=_round_nice(x))
    if intent == 'top_items':
        by = _wchoice(rng, [('qty', 0.6), ('profit', 0.2 if L.has('unit_cost') else 0), ('revenue', 0.2)])
        k = 1 if by == 'profit' or rng.random() < 0.5 else rng.choice([3, 5])
        return S(period=per(), by=by, k=k, **({'as_list': True} if k > 1 else {}))
    if intent == 'items_min_orders':
        p = per(['month', 'month', 'this_month', 'quarter'])
        l, _ = _period_items(L, as_of, p)
        c = l.groupby('product_id').order_id.nunique()
        n = int(c.quantile(rng.uniform(0.3, 0.9))) if len(c) else 5
        return S(period=p, n=max(2, n))
    if intent == 'top_customers':
        by = 'revenue' if rng.random() < 0.7 else 'orders'
        k = 1 if rng.random() < 0.5 else rng.choice([3, 5])
        return S(period=per(), by=by, k=k, **({'as_list': True} if k > 1 else {}))
    if intent in ('customers_min_orders', 'customers_min_orders_share'):
        return S(period=per(['month', 'month', 'this_month', 'quarter', 'last_n_days']), n=rng.choice([2, 3, 3, 4, 5, 6]))
    if intent in ('cust_group_revenue', 'cust_group_share'):
        gs = [g for g in L.customers.group.dropna().unique() if g in CUST_GROUP_WORDS]
        return S(period=per(), group=rng.choice(gs)) if gs else None
    if intent in ('payment_revenue', 'payment_share'):
        vals = [m for m in L.orders.payment_method.dropna().unique() if m in PAY_WORDS]
        if not vals:
            return None
        if intent == 'payment_share':
            return S(period=per(), method=rng.choice(vals))
        return S(period=per(), methods=rng.sample(vals, min(len(vals), rng.choice([1, 2, 2]))))
    if intent in ('channel_revenue', 'channel_share'):
        vals = [m for m in L.orders.channel.dropna().unique() if m in CHANNEL_WORDS]
        if not vals:
            return None
        if intent == 'channel_share':
            return S(period=per(), channel=rng.choice(vals))
        return S(period=per(), channels=rng.sample(vals, min(len(vals), rng.choice([1, 2, 2]))))
    if intent in ('shift_revenue', 'shift_orders'):
        return S(period=per(), shift=rng.choice(['morning', 'afternoon']))
    if intent == 'staff_revenue':
        ids = list(L.staff.staff_id) or ['NV001', 'NV002']
        return S(period=per(), staff=rng.choice(ids))
    if intent in ('rx_revenue', 'rx_share'):
        return S(period=per(), rx=rng.random() < 0.7)
    if intent == 'ingredient_revenue':
        ings = sorted(set(L.drugs.ingredient.dropna()))
        return S(period=per(), ingredient=rng.choice(ings)) if ings else None
    if intent in ('avg_purchase_price', 'purchase_minus_sales'):
        pl = L.purchase_lines.merge(L.purchases[['purchase_id', 'date', 'status']], on='purchase_id')
        pl = pl[(pl.status != 'cancelled') & (pl.date <= pd.Timestamp(as_of)) & pl.product_id.isin(prod.product_id)]
        if pl.empty:
            return None
        r = pl.iloc[rng.randrange(len(pl))]
        p = _month_spec(r.date.year, r.date.month)
        units = [None] + list(L.units[L.units.product_id == r.product_id].unit)
        return S(item=r.product_id, period=p, unit=rng.choice(units))
    if intent == 'price_on_day':
        o = L.orders[L.orders.created <= pd.Timestamp(as_of)]
        l = L.lines[L.lines.order_id.isin(o.order_id.sample(min(len(o), 300), random_state=rng.randrange(10**6)))]
        l = l[l.product_id.isin(prod.product_id)]
        if l.empty:
            return None
        r = l.iloc[rng.randrange(len(l))]
        d = o.set_index('order_id').created.get(r.order_id).date()
        units = [None] + list(L.units[L.units.product_id == r.product_id].unit)
        return S(item=r.product_id, date=d, unit=rng.choice(units))
    if intent == 'price_effect':
        pr = L.prices.sort_values('date')
        rises = []
        for pid, g in pr.groupby('product_id'):
            v = list(g.price)
            for i in range(1, len(v)):
                if v[i] > v[i - 1] and g.date.iloc[i].date() <= as_of:
                    rises.append((pid, g.date.iloc[i].date(), float(v[i])))
        if rises:
            pid, d, price = rng.choice(rises)
            spec = S(item=pid, date=d, n=rng.choice([7, 14]))
            if rng.random() < 0.5:
                units = [(None, 1.0)] + [(u, float(f)) for u, f in
                                         zip(L.units[L.units.product_id == pid].unit, L.units[L.units.product_id == pid].factor)]
                u, f = rng.choice(units)
                spec.update(new_price=price * f, unit=u)
            return spec
        if not sold_ids:
            return None
        pid = rng.choice(sold_ids[:30])
        d = L.shop['start'] + dt.timedelta(days=rng.randrange(30, max(31, (as_of - L.shop['start']).days - 14)))
        return S(item=pid, date=d, n=rng.choice([7, 14]))
    if intent in ('stock_end', 'stock_big_small', 'stock_value', 'out_of_stock_count'):
        if not L.has('stock'):
            return None
        d = as_of if rng.random() < 0.6 else as_of - dt.timedelta(days=rng.randrange(1, 120))
        if intent in ('stock_value', 'out_of_stock_count'):
            return S(date=d)
        ids = list(L.stock_moves.product_id.unique())
        pid = rng.choice(ids)
        units = list(L.units[(L.units.product_id == pid) & (L.units.factor > 1)].unit)
        if intent == 'stock_big_small':
            if not units:
                return None
            return S(item=pid, date=d, big_unit=rng.choice(units))
        return S(item=pid, date=d, unit=rng.choice([None] + units))
    if intent in ('expiring_items', 'expiring_count', 'expiring_value'):
        if not L.has('lots'):
            return None
        d = as_of if rng.random() < 0.7 else as_of - dt.timedelta(days=rng.randrange(1, 90))
        return S(date=d, n=rng.choice([30, 60, 90, 120, 180]))
    if intent == 'nearest_lot_expiry':
        if not L.has('lots'):
            return None
        d = as_of if rng.random() < 0.7 else as_of - dt.timedelta(days=rng.randrange(1, 90))
        return S(item=rng.choice(list(L.lots.product_id.unique())), date=d)
    if intent in ('debt_total', 'debt_customers', 'debt_top', 'debt_over_age', 'debt_aging'):
        d = as_of if rng.random() < 0.4 else as_of - dt.timedelta(days=rng.randrange(1, 200))
        d = max(d, L.shop['start'] + dt.timedelta(days=20))
        if intent == 'debt_top':
            return S(date=d, k=rng.choice([3, 5]))
        if intent == 'debt_over_age':
            return S(date=d, days=rng.choice([7, 15, 30]))
        if intent == 'debt_aging':
            return S(date=d, edges=[7, 15] if rng.random() < 0.7 else [30, 60])
        return S(date=d)
    if intent == 'debt_new_paid':
        o = L.orders[(L.orders.payment_method == 'debt') & L.orders.customer_id.notna()]
        if o.empty:
            return None
        cid = o.customer_id.iloc[rng.randrange(len(o))]
        return S(customer=cid, period=per(['month', 'month', 'this_month', 'quarter']))
    if intent == 'qty_item':
        pid = rng.choice(sold_ids)
        units = list(L.units[L.units.product_id == pid].unit)
        return S(item=pid, period=per(), unit=rng.choice([None, None] + units))
    if intent == 'revenue_item':
        return S(item=rng.choice(sold_ids), period=per())
    if intent in ('revenue_group', 'group_share'):
        gs = list(prod.group.dropna().unique())
        return S(group=rng.choice(gs), period=per()) if gs else None
    if intent == 'qty_unit':
        us = list(prod[prod.kind != 'fee'].base_unit.dropna().unique())
        return S(unit=rng.choice(us), period=per()) if us else None
    if intent == 'qty_size':
        if not prod.name.str.strip().str.upper().str.endswith(('(M)', '(L)')).any():
            return None
        return S(size=rng.choice(['M', 'L']), period=per())
    raise KeyError(intent)


# intents of split-rulebook sections (gen.rulebook_gen) have no train phrasing to parse back: not in the round trip
SECTION_INTENTS = {'guests_total', 'revenue_per_guest', 'area_revenue', 'top_table', 'service_revenue', 'service_share',
                   'vehicle_count', 'repeat_vehicles'}
ALL_INTENTS = sorted(set(INTENTS) - SECTION_INTENTS) + ['unanswerable']
