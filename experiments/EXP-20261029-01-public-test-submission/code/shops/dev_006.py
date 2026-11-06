from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from datamate import Clock, Period, fmt
from datamate.norm import round2
from dev_006_core import ANSWERS_PATH, QUESTIONS_PATH, Line, Order, Shop, percent_change, pick_top, share

SHOP = Shop()
HANDLERS: dict[str, Callable[[Clock], tuple[str, Any]]] = {}


def answer(question_id: str):
    def register(func: Callable[[Clock], tuple[str, Any]]):
        if question_id in HANDLERS:
            raise ValueError(f"duplicate handler: {question_id}")
        HANDLERS[question_id] = func
        return func

    return register


def revenue(period: Period, clock: Clock, *, keep: Callable[[Order], bool] | None = None) -> int:
    return SHOP.revenue(period, clock, keep=keep)


def order_count(period: Period, clock: Clock, *, keep: Callable[[Order], bool] | None = None) -> int:
    return sum(1 for order in SHOP.orders_in(period, clock) if keep is None or keep(order))


def group_of(order: Order) -> str:
    if order.customer == "":
        return ""
    return SHOP.customers[order.customer][1]


def daily_revenue(period: Period, clock: Clock) -> dict[date, int]:
    out: dict[date, int] = {day: 0 for day in period.each_day() if clock.visible(day)}
    for order in SHOP.orders_in(period, clock):
        out[order.day] = out.get(order.day, 0) + order.goods
    return out


def base_qty_by_product(period: Period, clock: Clock) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for _order, line in SHOP.revenue_lines(period, clock):
        out[line.product] += line.base_qty
    return dict(out)


def gross_profit_by_product(period: Period, clock: Clock) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for _order, line in SHOP.revenue_lines(period, clock):
        out[line.product] += line.gross_profit
    return dict(out)


def revenue_by_product_filter(period: Period, clock: Clock, keep: Callable[[str], bool]) -> int:
    total = 0
    for _order, line in SHOP.revenue_lines(period, clock):
        if keep(line.product):
            total += line.amount
    return total


def customer_order_counts(period: Period, clock: Clock) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for order in SHOP.orders_in(period, clock):
        if order.customer != "":
            out[order.customer] += 1
    return dict(out)


def customer_revenue(period: Period, clock: Clock) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for order in SHOP.orders_in(period, clock):
        if order.customer != "":
            out[order.customer] += order.goods
    return dict(out)


def shift_revenue(period: Period, clock: Clock) -> dict[str, int]:
    out = {"sáng": 0, "chiều": 0}
    for order in SHOP.orders_in(period, clock):
        shift = clock.shift_of(order.moment)
        if shift is None:
            raise ValueError(f"order outside both shifts: {order.code} {order.moment}")
        out[shift] += order.goods
    return out


def purchase_total(period: Period, clock: Clock) -> int:
    return sum(r.total for r in SHOP.receipts if period.contains(r.day) and clock.visible(r.day) and r.status != "cancelled")


def purchase_by_supplier(period: Period, clock: Clock) -> tuple[dict[str, int], dict[str, int]]:
    money: dict[str, int] = defaultdict(int)
    count: dict[str, int] = defaultdict(int)
    for receipt in SHOP.receipts:
        if period.contains(receipt.day) and clock.visible(receipt.day) and receipt.status != "cancelled":
            money[receipt.supplier] += receipt.total
            count[receipt.supplier] += 1
    return dict(money), dict(count)


def purchased_base_qty(period: Period, clock: Clock, product_code: str) -> int:
    factors = SHOP.products[product_code].factors
    base_unit = SHOP.products[product_code].base_unit
    total = 0
    receipt_day = {r.code: r.day for r in SHOP.receipts if r.status != "cancelled"}
    for receipt, product, unit, qty, _price in SHOP.receipt_lines:
        if product != product_code or receipt not in receipt_day:
            continue
        day = receipt_day[receipt]
        if not period.contains(day) or not clock.visible(day):
            continue
        factor = 1 if unit == base_unit else factors[unit]
        total += qty * factor
    return total


def live_lots(clock: Clock) -> tuple[tuple[str, int], ...]:
    balances = SHOP.lot_balances()
    return tuple((code, balances[code]) for code in sorted(balances) if balances[code] > 0)


def lots_expiring(clock: Clock, window_days: int, *, end: date | None = None) -> tuple[tuple[str, int], ...]:
    last = end if end is not None else clock.as_of + timedelta(days=window_days)
    return tuple((code, qty) for code, qty in live_lots(clock) if clock.as_of <= SHOP.lots[code].expiry <= last)


def products_by_earliest_expiry(lots: tuple[tuple[str, int], ...]) -> tuple[str, ...]:
    earliest: dict[str, date] = {}
    for code, _qty in lots:
        lot = SHOP.lots[code]
        if lot.product not in earliest or lot.expiry < earliest[lot.product]:
            earliest[lot.product] = lot.expiry
    ordered = sorted(earliest.items(), key=lambda item: (item[1], item[0]))
    return tuple(SHOP.products[code].name for code, _day in ordered)


def nearest_expiry(clock: Clock, product_name: str) -> date:
    product = SHOP.product_by_name(product_name)
    candidates = [
        SHOP.lots[code].expiry
        for code, _qty in live_lots(clock)
        if SHOP.lots[code].product == product.code and SHOP.lots[code].expiry >= clock.as_of
    ]
    if not candidates:
        raise ValueError(f"no live lot for {product_name!r}")
    return min(candidates)


def price_increase_day(product_code: str, new_price: int) -> date:
    history = [pc for pc in SHOP.price_changes if pc.product == product_code]
    for before, current in zip(history, history[1:]):
        if current.price > before.price and current.price == new_price:
            return current.day
    raise ValueError(f"no increase to {new_price} for {product_code}")


def price_effect_percent(product_name: str, new_price: int, window: int, clock: Clock) -> float:
    product = SHOP.product_by_name(product_name)
    day = price_increase_day(product.code, new_price)
    after = Period(start=day, end=day + timedelta(days=window - 1))
    before = Period(start=day - timedelta(days=window), end=day - timedelta(days=1))
    sold_after = base_qty_by_product(after, clock).get(product.code, 0)
    sold_before = base_qty_by_product(before, clock).get(product.code, 0)
    return percent_change(sold_after, sold_before)


def debt_by_customer(moment: date) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for order_code, rest in SHOP.outstanding_at(moment).items():
        order = SHOP.order_by_code[order_code]
        if order.customer == "":
            continue
        out[order.customer] += rest
    return dict(out)


def top_debt_table(clock: Clock, limit: int) -> dict[str, Any]:
    rows = sorted(debt_by_customer(clock.as_of).items(), key=lambda item: (-item[1], item[0]))[:limit]
    return fmt.table(
        columns=["khach_hang", "so_tien_no"],
        rows=[[SHOP.customers[code][0], fmt.money(amount)] for code, amount in rows],
    )


def customer_new_debt(period: Period, clock: Clock, customer_code: str) -> int:
    total = 0
    for order_code, amount in SHOP.new_debt_in(period, clock).items():
        if SHOP.order_by_code[order_code].customer == customer_code:
            total += amount
    return total


def customer_debt_paid(period: Period, clock: Clock, customer_code: str) -> int:
    return sum(p.amount for order, p in SHOP.debt_collected_in(period, clock) if order.customer == customer_code)


@answer("q_033e37dde4d5")
def gói_bán_tuần_này(clock: Clock) -> tuple[str, Any]:
    qty = base_qty_by_product(clock.this_week(), clock)
    total = sum(count for code, count in qty.items() if SHOP.products[code].base_unit == "gói")
    return "number", fmt.count(total)


@answer("q_0389b0c41da6")
def tết_2026_so_trước_tết(clock: Clock) -> tuple[str, Any]:
    now = revenue(clock.tet(2026), clock)
    before = revenue(clock.before_tet(2026), clock)
    return "percent", fmt.percent(percent_change(now, before))


@answer("q_049f0a34efdc")
def khách_từ_4_đơn_02_2026(clock: Clock) -> tuple[str, Any]:
    counts = customer_order_counts(clock.month(2, 2026), clock)
    return "number", fmt.count(sum(1 for n in counts.values() if n >= 4))


@answer("q_052834325528")
def ca_chiều_so_ca_sáng_10_2025(clock: Clock) -> tuple[str, Any]:
    by_shift = shift_revenue(clock.month(10, 2025), clock)
    return "percent", fmt.percent(percent_change(by_shift["chiều"], by_shift["sáng"]))


@answer("q_0641a621b596")
def dthu_t4_t6_2025(clock: Clock) -> tuple[str, Any]:
    return "list", [fmt.money(revenue(clock.month(m, 2025), clock)) for m in (4, 5, 6)]


@answer("q_0878814b6a76")
def ncc_nhiều_tiền_nhất_tháng_này(clock: Clock) -> tuple[str, Any]:
    money, _count = purchase_by_supplier(clock.this_month(), clock)
    best = pick_top({code: value for code, value in money.items()})[0][0]
    return "string", SHOP.suppliers[best]


@answer("q_0a9819711554")
def lê_sơn_trung_t7_2026(clock: Clock) -> tuple[str, Any]:
    code = SHOP.customer_by_name("Lê Sơn Trung")
    period = clock.month(7, 2026)
    return "list", [fmt.money(customer_new_debt(period, clock, code)), fmt.money(customer_debt_paid(period, clock, code))]


@answer("q_0b78b53675c1")
def bán_chạy_nhất_tết_2026(clock: Clock) -> tuple[str, Any]:
    qty = base_qty_by_product(clock.tet(2026), clock)
    return "string", SHOP.products[pick_top(qty)[0][0]].name


@answer("q_0ca19cd317cb")
def sp_có_lô_hết_hạn_90_ngày(clock: Clock) -> tuple[str, Any]:
    return "list", list(products_by_earliest_expiry(lots_expiring(clock, 90)))


@answer("q_113d86c3eb6a")
def dthu_8_2025_so_tháng_trước(clock: Clock) -> tuple[str, Any]:
    now = revenue(clock.month(8, 2025), clock)
    before = revenue(clock.month(7, 2025), clock)
    return "percent", fmt.percent(percent_change(now, before))


@answer("q_169bfdcce0ae")
def khách_từ_6_đơn_12_2025(clock: Clock) -> tuple[str, Any]:
    counts = customer_order_counts(clock.month(12, 2025), clock)
    return "percent", fmt.percent(share(sum(1 for n in counts.values() if n >= 6), len(counts)))


@answer("q_1c2ff6b4820f")
def lãi_gộp_cao_nhất_2_2026(clock: Clock) -> tuple[str, Any]:
    profit = gross_profit_by_product(clock.month(2, 2026), clock)
    return "string", SHOP.products[pick_top(profit)[0][0]].name


@answer("q_210d0cfc81e5")
def berocca_lô_cận_date(clock: Clock) -> tuple[str, Any]:
    return "date", fmt.day_answer(nearest_expiry(clock, "Berocca Performance viên sủi tuýp 10 viên"))


@answer("q_29efb04a938b")
def khách_nữ_5_2025(clock: Clock) -> tuple[str, Any]:
    return "unanswerable", "khach_hang.NamNu rỗng toàn bộ 320 dòng, shop không ghi giới tính khách"


@answer("q_2d5eb3a196b7")
def thu_nợ_11_2025(clock: Clock) -> tuple[str, Any]:
    collected = SHOP.debt_collected_in(clock.month(11, 2025), clock)
    return "number", fmt.money(sum(p.amount for _order, p in collected))


@answer("q_35c586d5d831")
def sỉ_trung_bình_đơn_9_2025(clock: Clock) -> tuple[str, Any]:
    orders = [o for o in SHOP.orders_in(clock.month(9, 2025), clock) if group_of(o) == "sỉ"]
    return "number", fmt.money(sum(o.goods for o in orders) / len(orders))


@answer("q_393267cfdee1")
def tiền_vốn_lô_đến_06_12_2026(clock: Clock) -> tuple[str, Any]:
    lots = lots_expiring(clock, 0, end=date(2026, 12, 6))
    return "number", fmt.money(sum(qty * SHOP.lots[code].base_cost for code, qty in lots))


@answer("q_39abf982c56e")
def lãi_gộp_cao_nhất_7_2025(clock: Clock) -> tuple[str, Any]:
    profit = gross_profit_by_product(clock.month(7, 2025), clock)
    return "string", SHOP.products[pick_top(profit)[0][0]].name


@answer("q_3b70619cf8cc")
def từ_hùng_hằng_4_2025(clock: Clock) -> tuple[str, Any]:
    code = SHOP.employee_by_name("Từ Hùng Hằng")
    return "number", fmt.money(revenue(clock.month(4, 2025), clock, keep=lambda o: o.employee == code))


@answer("q_3c935a94dc79")
def nợ_theo_tuổi_17_12_2025(clock: Clock) -> tuple[str, Any]:
    buckets = [0, 0, 0]
    for order_code, rest in SHOP.outstanding_at(clock.as_of).items():
        age = (clock.as_of - SHOP.order_by_code[order_code].day).days
        index = 0 if age <= 7 else (1 if age <= 15 else 2)
        buckets[index] += rest
    return "list", [fmt.money(value) for value in buckets]


@answer("q_411cb8ae0f94")
def oresol_lô_cận_date(clock: Clock) -> tuple[str, Any]:
    return "date", fmt.day_answer(nearest_expiry(clock, "Oresol 245 DHG hộp 20 gói"))


@answer("q_41a1d3818421")
def khách_từ_6_đơn_08_2025(clock: Clock) -> tuple[str, Any]:
    counts = customer_order_counts(clock.month(8, 2025), clock)
    return "percent", fmt.percent(share(sum(1 for n in counts.values() if n >= 6), len(counts)))


@answer("q_41e962bb640f")
def dthu_tuần_trước(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(revenue(clock.last_week(), clock))


@answer("q_468d8ef6f198")
def sỉ_dthu_tháng_này(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(revenue(clock.this_month(), clock, keep=lambda o: group_of(o) == "sỉ"))


@answer("q_4807f35b3b8c")
def urgo_miếng_07_2025(clock: Clock) -> tuple[str, Any]:
    product = SHOP.product_by_name("Băng cá nhân Urgo Transparent hộp 100 miếng")
    return "number", fmt.count(base_qty_by_product(clock.month(7, 2025), clock).get(product.code, 0))


@answer("q_481401f5b908")
def augmentin_lô_cận_date(clock: Clock) -> tuple[str, Any]:
    return "date", fmt.day_answer(nearest_expiry(clock, "Augmentin 625mg hộp 2 vỉ x 7 viên"))


@answer("q_4838293f61b5")
def bình_quân_đơn_tuần_rồi_2025_04(clock: Clock) -> tuple[str, Any]:
    orders = SHOP.orders_in(clock.last_week(), clock)
    return "number", fmt.money(sum(o.goods for o in orders) / len(orders))


@answer("q_48b77f4a1b30")
def vương_chi_hà_11_2025(clock: Clock) -> tuple[str, Any]:
    code = SHOP.customer_by_name("Vương Chi Hà")
    period = clock.month(11, 2025)
    return "list", [fmt.money(customer_new_debt(period, clock, code)), fmt.money(customer_debt_paid(period, clock, code))]


@answer("q_4b2f4e1688fa")
def đơn_huỷ_4_2026(clock: Clock) -> tuple[str, Any]:
    period = clock.month(4, 2026)
    return "number", fmt.count(
        sum(1 for o in SHOP.orders if period.contains(o.day) and clock.visible(o.day) and o.status == "cancelled")
    )


@answer("q_4b3bc2d8b207")
def số_khách_nợ_13_12_2025(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.count(len(debt_by_customer(clock.as_of)))


@answer("q_4c8fda6cf0df")
def top3_nợ_11_05_2026(clock: Clock) -> tuple[str, Any]:
    return "table", top_debt_table(clock, 3)


@answer("q_4d20e306e0bc")
def hết_hàng_cuối_ngày_07_06_2026(clock: Clock) -> tuple[str, Any]:
    stock = SHOP.stock_at(clock.as_of)
    return "number", fmt.count(sum(1 for value in stock.values() if value == 0))


@answer("q_4e3c77d294d3")
def tại_quầy_5_2026(clock: Clock) -> tuple[str, Any]:
    period = clock.month(5, 2026)
    part = revenue(period, clock, keep=lambda o: o.channel == "store")
    return "percent", fmt.percent(share(part, revenue(period, clock)))


@answer("q_501cc0b20b1b")
def acyclovir_tăng_giá(clock: Clock) -> tuple[str, Any]:
    return "percent", fmt.percent(price_effect_percent("Acyclovir Stella kem 5% tuýp 5g", 18000, 30, clock))


@answer("q_51f4751e4eb3")
def cod_và_ewallet_3_2026(clock: Clock) -> tuple[str, Any]:
    period = clock.month(3, 2026)
    return "list", [
        fmt.money(revenue(period, clock, keep=lambda o: o.payment == "cod")),
        fmt.money(revenue(period, clock, keep=lambda o: o.payment == "ewallet")),
    ]


@answer("q_5598af728eea")
def top3_bán_chạy_11_2025(clock: Clock) -> tuple[str, Any]:
    qty = base_qty_by_product(clock.month(11, 2025), clock)
    return "list", [SHOP.products[code].name for code, _value in pick_top(qty, limit=3)]


@answer("q_57028085023b")
def lãi_gộp_2_2026(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(sum(gross_profit_by_product(clock.month(2, 2026), clock).values()))


@answer("q_57632dfbe478")
def dthu_11_2025(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(revenue(clock.month(11, 2025), clock))


@answer("q_583a942f4d85")
def thân_thiết_bình_quân_tháng_này(clock: Clock) -> tuple[str, Any]:
    orders = [o for o in SHOP.orders_in(clock.this_month(), clock) if group_of(o) == "thân thiết"]
    return "number", fmt.money(sum(o.goods for o in orders) / len(orders))


@answer("q_5e7b3b2822b9")
def hapacol_tăng_giá(clock: Clock) -> tuple[str, Any]:
    return "percent", fmt.percent(price_effect_percent("Hapacol 250 hộp 24 gói", 2100, 7, clock))


@answer("q_60022421ae73")
def vitaminc_nhập_trừ_bán_9_2025(clock: Clock) -> tuple[str, Any]:
    product = SHOP.product_by_name("Vitamin C 500mg Quapharco hộp 10 vỉ x 10 viên")
    period = clock.month(9, 2025)
    bought = purchased_base_qty(period, clock, product.code)
    sold = base_qty_by_product(period, clock).get(product.code, 0)
    return "number", fmt.count(bought - sold)


@answer("q_611bf24dd2f9")
def ncc_chính_11_2025(clock: Clock) -> tuple[str, Any]:
    _money, count = purchase_by_supplier(clock.month(11, 2025), clock)
    return "string", SHOP.suppliers[pick_top(count)[0][0]]


@answer("q_624351bf768f")
def chuyển_khoản_6_2025(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(revenue(clock.month(6, 2025), clock, keep=lambda o: o.payment == "transfer"))


@answer("q_647711394825")
def đinh_đạt_đức_10_2025(clock: Clock) -> tuple[str, Any]:
    code = SHOP.employee_by_name("Đinh Đạt Đức")
    return "number", fmt.money(revenue(clock.month(10, 2025), clock, keep=lambda o: o.employee == code))


@answer("q_64e62d4bea7d")
def bình_quân_đơn_tuần_trước_2026_03(clock: Clock) -> tuple[str, Any]:
    orders = SHOP.orders_in(clock.last_week(), clock)
    return "number", fmt.money(sum(o.goods for o in orders) / len(orders))


@answer("q_682e548226be")
def dthu_3_tháng_tới_3_2026(clock: Clock) -> tuple[str, Any]:
    return "list", [fmt.money(revenue(clock.month(m, 2026), clock)) for m in (1, 2, 3)]


@answer("q_68d46c34c960")
def dthu_5_6_7_2026(clock: Clock) -> tuple[str, Any]:
    return "list", [fmt.money(revenue(clock.month(m, 2026), clock)) for m in (5, 6, 7)]


@answer("q_690a98214478")
def tháng_này_so_cùng_số_ngày(clock: Clock) -> tuple[str, Any]:
    now = revenue(clock.this_month(), clock)
    before = revenue(clock.last_month_same_days(), clock)
    return "percent", fmt.percent(percent_change(now, before))


@answer("q_69b7d08012e5")
def nợ_còn_27_03_2026(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(sum(SHOP.outstanding_at(clock.as_of).values()))


@answer("q_6c18fd06a115")
def số_đơn_hôm_nay_2025_06_06(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.count(order_count(clock.today(), clock))


@answer("q_6c4f54f5fb85")
def sp_còn_hàng_hsd_tới_05_01_2027(clock: Clock) -> tuple[str, Any]:
    lots = lots_expiring(clock, 0, end=date(2027, 1, 5))
    return "list", list(products_by_earliest_expiry(lots))


@answer("q_6cb40ee1f329")
def costar_omega_lọ_12_2025(clock: Clock) -> tuple[str, Any]:
    product = SHOP.product_by_name("Costar Omega 3 1000mg lọ 100 viên")
    return "number", fmt.count(base_qty_by_product(clock.month(12, 2025), clock).get(product.code, 0))


@answer("q_6dc8a5070da6")
def zyrtec_viên_7_2026(clock: Clock) -> tuple[str, Any]:
    product = SHOP.product_by_name("Zyrtec 10mg hộp 1 vỉ x 10 viên")
    return "number", fmt.count(base_qty_by_product(clock.month(7, 2026), clock).get(product.code, 0))


@answer("q_6f0c8057ccdb")
def nhập_hàng_8_2025(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(purchase_total(clock.month(8, 2025), clock))


@answer("q_715e9ea420ef")
def ngày_dthu_từ_8400000_2_2026(clock: Clock) -> tuple[str, Any]:
    by_day = daily_revenue(clock.month(2, 2026), clock)
    return "number", fmt.count(sum(1 for value in by_day.values() if value >= 8_400_000))


@answer("q_78569aa4cbd0")
def kê_đơn_tháng_này(clock: Clock) -> tuple[str, Any]:
    period = clock.this_month()
    part = revenue_by_product_filter(period, clock, lambda code: SHOP.products[code].prescription)
    return "percent", fmt.percent(share(part, revenue(period, clock)))


@answer("q_78737a198776")
def khách_từ_4_đơn_5_2025(clock: Clock) -> tuple[str, Any]:
    counts = customer_order_counts(clock.month(5, 2025), clock)
    return "percent", fmt.percent(share(sum(1 for n in counts.values() if n >= 4), len(counts)))


@answer("q_7b45716b3dda")
def nhập_hàng_6_2025(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(purchase_total(clock.month(6, 2025), clock))


@answer("q_7bc2b2afb992")
def dthu_5_2026_so_tháng_trước(clock: Clock) -> tuple[str, Any]:
    now = revenue(clock.month(5, 2026), clock)
    before = revenue(clock.month(4, 2026), clock)
    return "percent", fmt.percent(percent_change(now, before))


@answer("q_86198c3c128b")
def top5_bán_chạy_tuần_này(clock: Clock) -> tuple[str, Any]:
    qty = base_qty_by_product(clock.this_week(), clock)
    return "list", [SHOP.products[code].name for code, _value in pick_top(qty, limit=5)]


@answer("q_8865baf2a84d")
def ca_chiều_so_ca_sáng_6_2026(clock: Clock) -> tuple[str, Any]:
    by_shift = shift_revenue(clock.month(6, 2026), clock)
    return "percent", fmt.percent(percent_change(by_shift["chiều"], by_shift["sáng"]))


@answer("q_8c88fcb609eb")
def phosphalugel_tăng_giá(clock: Clock) -> tuple[str, Any]:
    return "percent", fmt.percent(price_effect_percent("Phosphalugel hộp 26 gói", 5400, 30, clock))


@answer("q_908d0d681cd8")
def ngày_dthu_từ_9700000_6_2026(clock: Clock) -> tuple[str, Any]:
    by_day = daily_revenue(clock.month(6, 2026), clock)
    return "number", fmt.count(sum(1 for value in by_day.values() if value >= 9_700_000))


@answer("q_928423a8bbc6")
def dthu_7_2026_so_7_2025(clock: Clock) -> tuple[str, Any]:
    now = revenue(clock.month(7, 2026), clock)
    before = revenue(clock.month(7, 2025), clock)
    return "percent", fmt.percent(percent_change(now, before))


@answer("q_94acd8f437f4")
def lãi_gộp_cao_nhất_5_2026(clock: Clock) -> tuple[str, Any]:
    profit = gross_profit_by_product(clock.month(5, 2026), clock)
    return "string", SHOP.products[pick_top(profit)[0][0]].name


@answer("q_95a45f58351b")
def số_đơn_hôm_nay_2025_05_10(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.count(order_count(clock.today(), clock))


@answer("q_976e38598dde")
def thân_thiết_dthu_7_2026(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(revenue(clock.month(7, 2026), clock, keep=lambda o: group_of(o) == "thân thiết"))


@answer("q_9ab76e4d9f5e")
def top3_khách_tuần_rồi(clock: Clock) -> tuple[str, Any]:
    scores = customer_revenue(clock.last_week(), clock)
    return "list", [SHOP.customers[code][0] for code, _value in pick_top(scores, limit=3)]


@answer("q_9d8949165b5e")
def khách_sộp_5_2026(clock: Clock) -> tuple[str, Any]:
    period = clock.month(5, 2026)
    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for order in SHOP.orders_in(period, clock):
        if order.customer == "":
            continue
        totals[order.customer] += order.goods
        counts[order.customer] += 1
    averages = {code: totals[code] / counts[code] for code in counts if counts[code] >= 3}
    return "string", SHOP.customers[pick_top(averages)[0][0]][0]


@answer("q_9ed7874d83b8")
def dthu_quý_2_2025(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(revenue(clock.quarter(2, 2025), clock))


@answer("q_a0046e6fede0")
def nhóm_giảm_đau_hạ_sốt_2_2026(clock: Clock) -> tuple[str, Any]:
    period = clock.month(2, 2026)
    return "number", fmt.money(revenue_by_product_filter(period, clock, lambda code: SHOP.products[code].category == "giảm đau hạ sốt"))


@answer("q_a91c8a25a22f")
def kê_đơn_12_2025(clock: Clock) -> tuple[str, Any]:
    period = clock.month(12, 2025)
    return "number", fmt.money(revenue_by_product_filter(period, clock, lambda code: SHOP.products[code].prescription))


@answer("q_ae44d3539448")
def diệp_hồng_hồng_3_2026(clock: Clock) -> tuple[str, Any]:
    code = SHOP.customer_by_name("Diệp Hồng Hồng")
    period = clock.month(3, 2026)
    return "list", [fmt.money(customer_new_debt(period, clock, code)), fmt.money(customer_debt_paid(period, clock, code))]


@answer("q_b01bee67cde2")
def hết_hàng_cuối_ngày_25_10_2025(clock: Clock) -> tuple[str, Any]:
    stock = SHOP.stock_at(clock.as_of)
    return "number", fmt.count(sum(1 for value in stock.values() if value == 0))


@answer("q_b189b9465fe7")
def ngày_dthu_cao_nhất_2_2026(clock: Clock) -> tuple[str, Any]:
    by_day = daily_revenue(clock.month(2, 2026), clock)
    best = sorted(by_day.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return "date", fmt.day_answer(best)


@answer("q_b24515210e17")
def lãi_gộp_6_2025(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(sum(gross_profit_by_product(clock.month(6, 2025), clock).values()))


@answer("q_b6f52d2a9ace")
def nhóm_dụng_cụ_y_tế_8_2025(clock: Clock) -> tuple[str, Any]:
    period = clock.month(8, 2025)
    return "number", fmt.money(revenue_by_product_filter(period, clock, lambda code: SHOP.products[code].category == "dụng cụ y tế"))


@answer("q_bb4017bc0666")
def tỉ_lệ_huỷ_9_2025(clock: Clock) -> tuple[str, Any]:
    period = clock.month(9, 2025)
    everything = [o for o in SHOP.orders if period.contains(o.day) and clock.visible(o.day)]
    cancelled = sum(1 for o in everything if o.status == "cancelled")
    return "percent", fmt.percent(share(cancelled, len(everything)))


@answer("q_bbfddbd1d363")
def nợ_quá_7_ngày_10_10_2025(clock: Clock) -> tuple[str, Any]:
    total = 0
    for order_code, rest in SHOP.outstanding_at(clock.as_of).items():
        if (clock.as_of - SHOP.order_by_code[order_code].day).days > 7:
            total += rest
    return "number", fmt.money(total)


@answer("q_bd0fbda87c14")
def loratadin_11_2025(clock: Clock) -> tuple[str, Any]:
    period = clock.month(11, 2025)
    return "number", fmt.money(revenue_by_product_filter(period, clock, lambda code: SHOP.products[code].ingredient == "Loratadin"))


@answer("q_beeab8ab97fc")
def bình_quân_đơn_tuần_trước_2026_02(clock: Clock) -> tuple[str, Any]:
    orders = SHOP.orders_in(clock.last_week(), clock)
    return "number", fmt.money(sum(o.goods for o in orders) / len(orders))


@answer("q_c0f375f0d480")
def tỉ_lệ_huỷ_5_2026(clock: Clock) -> tuple[str, Any]:
    period = clock.month(5, 2026)
    everything = [o for o in SHOP.orders if period.contains(o.day) and clock.visible(o.day)]
    cancelled = sum(1 for o in everything if o.status == "cancelled")
    return "percent", fmt.percent(share(cancelled, len(everything)))


@answer("q_c1a3be0d7376")
def hết_hàng_cuối_ngày_01_06_2025(clock: Clock) -> tuple[str, Any]:
    stock = SHOP.stock_at(clock.as_of)
    return "number", fmt.count(sum(1 for value in stock.values() if value == 0))


@answer("q_c3439f11c9b0")
def tiền_vốn_hết_hạn_180_ngày(clock: Clock) -> tuple[str, Any]:
    lots = lots_expiring(clock, 180)
    return "number", fmt.money(sum(qty * SHOP.lots[code].base_cost for code, qty in lots))


@answer("q_c788ebe0ce0b")
def hagifen_nhập_trừ_bán_9_2025(clock: Clock) -> tuple[str, Any]:
    product = SHOP.product_by_name("Hagifen 400mg DHG hộp 10 vỉ x 10 viên")
    period = clock.month(9, 2025)
    bought = purchased_base_qty(period, clock, product.code)
    sold = base_qty_by_product(period, clock).get(product.code, 0)
    return "number", fmt.count(bought - sold)


@answer("q_ca9e9c233325")
def thu_nợ_9_2025(clock: Clock) -> tuple[str, Any]:
    collected = SHOP.debt_collected_in(clock.month(9, 2025), clock)
    return "number", fmt.money(sum(p.amount for _order, p in collected))


@answer("q_cfa36137a14a")
def thân_thiết_tỉ_trọng_th4(clock: Clock) -> tuple[str, Any]:
    period = clock.month(4)
    part = revenue(period, clock, keep=lambda o: group_of(o) == "thân thiết")
    return "percent", fmt.percent(share(part, revenue(period, clock)))


@answer("q_d1e7b2bde646")
def kê_đơn_6_2025(clock: Clock) -> tuple[str, Any]:
    period = clock.month(6, 2025)
    return "number", fmt.money(revenue_by_product_filter(period, clock, lambda code: SHOP.products[code].prescription))


@answer("q_d3ed369d528c")
def số_khách_nợ_16_11_2025(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.count(len(debt_by_customer(clock.as_of)))


@answer("q_d41b61e31b85")
def tháng_dthu_cao_nhất_6_7_8_2025(clock: Clock) -> tuple[str, Any]:
    scores = {f"2025-{m:02d}": revenue(clock.month(m, 2025), clock) for m in (6, 7, 8)}
    return "date", pick_top(scores)[0][0]


@answer("q_d721d81da2d5")
def nợ_đơn_quá_7_ngày_28_12_2025(clock: Clock) -> tuple[str, Any]:
    total = 0
    for order_code, rest in SHOP.outstanding_at(clock.as_of).items():
        if (clock.as_of - SHOP.order_by_code[order_code].day).days > 7:
            total += rest
    return "number", fmt.money(total)


@answer("q_d76d6563e547")
def lãi_gộp_11_2025(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(sum(gross_profit_by_product(clock.month(11, 2025), clock).values()))


@answer("q_d770b2c75598")
def biosubtyl_nhập_trừ_bán_11_2025(clock: Clock) -> tuple[str, Any]:
    product = SHOP.product_by_name("Biosubtyl-II hộp 25 gói")
    period = clock.month(11, 2025)
    bought = purchased_base_qty(period, clock, product.code)
    sold = base_qty_by_product(period, clock).get(product.code, 0)
    return "number", fmt.count(bought - sold)


@answer("q_d8706faef72f")
def dthu_hôm_qua(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(revenue(clock.yesterday(), clock))


@answer("q_e5fc1ce4c0a1")
def dthu_hôm_nay_2025_07_06(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(revenue(clock.today(), clock))


@answer("q_e97f2c304dc0")
def nhóm_ho_cảm_cúm_3_2026(clock: Clock) -> tuple[str, Any]:
    period = clock.month(3, 2026)
    part = revenue_by_product_filter(period, clock, lambda code: SHOP.products[code].category == "ho cảm cúm")
    return "percent", fmt.percent(share(part, revenue(period, clock)))


@answer("q_ee2df6a3e957")
def top3_nợ_08_05_2026(clock: Clock) -> tuple[str, Any]:
    return "table", top_debt_table(clock, 3)


@answer("q_f1c0ff1d2330")
def giá_trị_tồn_kho_08_08_2026(clock: Clock) -> tuple[str, Any]:
    stock = SHOP.stock_at(clock.as_of)
    total = sum(qty * SHOP.products[code].base_cost for code, qty in stock.items() if qty > 0)
    return "number", fmt.money(total)


@answer("q_f20f4f3ec923")
def panadol500_viên_5_2025(clock: Clock) -> tuple[str, Any]:
    product = SHOP.product_by_name("Panadol 500mg hộp 10 vỉ x 12 viên")
    return "number", fmt.count(base_qty_by_product(clock.month(5, 2025), clock).get(product.code, 0))


@answer("q_f264ab49a2c8")
def vitamine_chai_5_2026(clock: Clock) -> tuple[str, Any]:
    product = SHOP.product_by_name("Nature's Bounty Vitamin E 400 IU chai 30 viên")
    return "number", fmt.count(base_qty_by_product(clock.month(5, 2026), clock).get(product.code, 0))


@answer("q_f823bf8a8442")
def dthu_10_2025(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(revenue(clock.month(10, 2025), clock))


@answer("q_f9182884552a")
def nhập_hàng_tháng_này(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.money(purchase_total(clock.this_month(), clock))


@answer("q_f9912ee059c9")
def võ_trung_hoa_6_2026(clock: Clock) -> tuple[str, Any]:
    code = SHOP.employee_by_name("Võ Trung Hoa")
    return "number", fmt.money(revenue(clock.month(6, 2026), clock, keep=lambda o: o.employee == code))


@answer("q_f9f2c930f630")
def số_đơn_7_ngày_gần_nhất(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.count(order_count(clock.last_n_days(7), clock))


@answer("q_fa1084dc1d3f")
def bà_bầu_acemuc(clock: Clock) -> tuple[str, Any]:
    return "unanswerable", "dữ liệu không có chống chỉ định hay thông tin thai kỳ của mặt hàng"


@answer("q_fb409424a396")
def số_lô_hết_hạn_120_ngày(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.count(len(lots_expiring(clock, 120)))


@answer("q_fbaf2023cfb6")
def tiffy_nhập_viên_6_2025(clock: Clock) -> tuple[str, Any]:
    product = SHOP.product_by_name("Tiffy Dey hộp 25 vỉ x 4 viên")
    return "number", fmt.count(purchased_base_qty(clock.month(6, 2025), clock, product.code))


@answer("q_fbe115817066")
def số_khách_nợ_16_06_2025(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.count(len(debt_by_customer(clock.as_of)))


@answer("q_fc8cdf9ab156")
def đơn_từ_280000_10_2025(clock: Clock) -> tuple[str, Any]:
    return "number", fmt.count(order_count(clock.month(10, 2025), clock, keep=lambda o: o.goods >= 280_000))


@answer("q_ff354156a3c4")
def sỉ_tỉ_trọng_6_2026(clock: Clock) -> tuple[str, Any]:
    period = clock.month(6, 2026)
    part = revenue(period, clock, keep=lambda o: group_of(o) == "sỉ")
    return "percent", fmt.percent(share(part, revenue(period, clock)))


@answer("q_ffd749264313")
def dthu_9_2025_so_tháng_trước(clock: Clock) -> tuple[str, Any]:
    now = revenue(clock.month(9, 2025), clock)
    before = revenue(clock.month(8, 2025), clock)
    return "percent", fmt.percent(percent_change(now, before))


def build() -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    questions = fmt.load_questions(QUESTIONS_PATH)
    lines: list[dict[str, Any]] = []
    failures: list[tuple[str, str]] = []
    for question in questions:
        handler = HANDLERS.get(question["id"])
        if handler is None:
            failures.append((question["id"], "no handler"))
            lines.append(fmt.answer_line(question["id"], "abstain"))
            continue
        clock = Clock(question["as_of_date"])
        try:
            kind, value = handler(clock)
        except Exception as error:
            failures.append((question["id"], f"{type(error).__name__}: {error}"))
            lines.append(fmt.answer_line(question["id"], "abstain"))
            continue
        if kind == "unanswerable":
            lines.append(fmt.answer_line(question["id"], "unanswerable", reason=value))
        else:
            lines.append(fmt.answer_line(question["id"], kind, value))
    return lines, failures


def main() -> int:
    lines, failures = build()
    written = fmt.write_answers(ANSWERS_PATH, lines)
    for question_id, reason in failures:
        print(f"FAIL {question_id}: {reason}")
    print(f"written {written} lines to {ANSWERS_PATH}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
