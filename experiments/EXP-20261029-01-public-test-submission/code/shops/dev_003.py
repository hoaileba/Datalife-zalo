from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from datamate import Clock, Period, fmt, fold_key  # noqa: E402
from dev_003_book import (  # noqa: E402
    ANSWERS_PATH,
    QUESTIONS_PATH,
    REVENUE_STATUSES,
    STATUS_CANCELLED,
    Order,
    SaleLine,
    ShopBook,
)

COD_FORM = "Thu hộ (COD)"
DEBT_FORM = "Ghi nợ"
COUNTER_SOURCE = "store"
LOYAL_SEGMENT = "thân thiết"
MORNING = "sáng"
AFTERNOON = "chiều"
TABLE_DEBT_COLUMNS = ("khach_hang", "so_tien_no")


class Shop:
    """Lớp trả lời câu hỏi dev_003: mọi luật rulebook áp trên ShopBook đã ingest."""

    def __init__(self, book: ShopBook) -> None:
        self.book = book
        self.payments_by_order: dict[str, list[tuple[date, int]]] = defaultdict(list)
        for receipt in book.receipts:
            self.payments_by_order[receipt.order_id].append((receipt.day, receipt.amount))

    def orders_in(self, period: Period, *, as_of: date, statuses: Iterable[str] | None = None) -> tuple[Order, ...]:
        wanted = frozenset(statuses) if statuses is not None else None
        out = []
        for order in self.book.orders.values():
            if not period.contains(order.day) or order.day > as_of:
                continue
            if wanted is not None and order.status not in wanted:
                continue
            out.append(order)
        return tuple(out)

    def revenue_orders_in(self, period: Period, *, as_of: date) -> tuple[Order, ...]:
        return self.orders_in(period, as_of=as_of, statuses=REVENUE_STATUSES)

    def revenue_lines_in(self, period: Period, *, as_of: date) -> tuple[SaleLine, ...]:
        keep = {o.order_id for o in self.revenue_orders_in(period, as_of=as_of)}
        return tuple(ln for ln in self.book.lines if ln.order_id in keep)

    def revenue(self, period: Period, *, as_of: date) -> int:
        return sum(o.goods_amount for o in self.revenue_orders_in(period, as_of=as_of))

    def order_count(self, period: Period, *, as_of: date) -> int:
        return len(self.revenue_orders_in(period, as_of=as_of))

    def gross_profit_lines(self, lines: Iterable[SaleLine]) -> int:
        return sum(ln.amount - round(ln.sold_quantity * ln.unit_cost) for ln in lines)

    def gross_profit(self, period: Period, *, as_of: date) -> int:
        return self.gross_profit_lines(self.revenue_lines_in(period, as_of=as_of))

    def expenses(self, period: Period) -> int:
        return sum(e.amount for e in self.book.expenses if period.contains(e.day))

    def net_profit(self, period: Period, *, as_of: date) -> int:
        return self.gross_profit(period, as_of=as_of) - self.expenses(period)

    def daily_revenue(self, period: Period, *, as_of: date) -> dict[date, int]:
        out: dict[date, int] = defaultdict(int)
        for order in self.revenue_orders_in(period, as_of=as_of):
            out[order.day] += order.goods_amount
        return dict(out)

    def base_quantity(self, lines: Iterable[SaleLine], *, predicate: Callable[[SaleLine], bool]) -> float:
        return sum(ln.base_quantity for ln in lines if predicate(ln))

    def outstanding(self, order: Order, *, until: date) -> int:
        paid = sum(amount for day, amount in self.payments_by_order.get(order.order_id, ()) if day <= until)
        return order.payable - paid

    def debt_orders(self, *, until: date) -> tuple[tuple[Order, int], ...]:
        out: list[tuple[Order, int]] = []
        for order in self.book.orders.values():
            if order.day > until or order.status == STATUS_CANCELLED or order.payment_form == COD_FORM:
                continue
            left = self.outstanding(order, until=until)
            if left > 0:
                out.append((order, left))
        return tuple(out)

    def debt_by_customer(self, *, until: date) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for order, left in self.debt_orders(until=until):
            if order.walk_in:
                continue
            out[order.customer_code] += left
        return dict(out)

    def new_debt(self, period: Period, *, as_of: date, customer_code: str | None = None) -> int:
        total = 0
        for order in self.book.orders.values():
            if order.payment_form != DEBT_FORM or order.status == STATUS_CANCELLED:
                continue
            if not period.contains(order.day) or order.day > as_of:
                continue
            if customer_code is not None and order.customer_code != customer_code:
                continue
            same_day = sum(a for d, a in self.payments_by_order.get(order.order_id, ()) if d == order.day)
            total += order.payable - same_day
        return total

    def debt_collected(self, period: Period, *, as_of: date, customer_code: str | None = None) -> int:
        total = 0
        for order in self.book.orders.values():
            if order.payment_form != DEBT_FORM or order.status == STATUS_CANCELLED:
                continue
            if customer_code is not None and order.customer_code != customer_code:
                continue
            for day, amount in self.payments_by_order.get(order.order_id, ()):
                if day > order.day and period.contains(day) and day <= as_of:
                    total += amount
        return total

    def customer_code_by_name(self, query: str) -> str:
        key = fold_key(query)
        hits = [code for code, info in self.book.customers.items() if fold_key(info["name"]).startswith(key)]
        if len(hits) != 1:
            raise ValueError(f"customer name not unique: {query!r} -> {hits}")
        return hits[0]

    def customer_name(self, code: str) -> str:
        return self.book.customers[code]["name"]

    def orders_per_customer(self, period: Period, *, as_of: date) -> dict[str, int]:
        out: dict[str, int] = defaultdict(int)
        for order in self.revenue_orders_in(period, as_of=as_of):
            if order.walk_in:
                continue
            out[order.customer_code] += 1
        return dict(out)

    def item_rank(self, lines: Iterable[SaleLine], *, by: Callable[[Sequence[SaleLine]], float]) -> tuple[tuple[str, float], ...]:
        grouped: dict[str, list[SaleLine]] = defaultdict(list)
        for line in lines:
            grouped[line.item_code].append(line)
        scored = [(code, by(rows)) for code, rows in grouped.items()]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return tuple(scored)

    def item_name(self, code: str) -> str:
        return self.book.catalog[code]["name"]

    def price_change_day(self, item_code: str, new_price: int) -> date:
        hits = [p.day for p in self.book.prices if p.item_code == item_code and p.new_price == new_price and p.old_price is not None]
        if not hits:
            raise ValueError(f"no price increase to {new_price} for {item_code}")
        return min(hits)

    def item_code_by_name(self, query: str) -> str:
        key = fold_key(query)
        hits = [code for code, info in self.book.catalog.items() if fold_key(info["name"]) == key]
        if len(hits) != 1:
            raise ValueError(f"item name not unique: {query!r}")
        return hits[0]


def percent_change(new: float, old: float) -> float:
    if old == 0:
        raise ValueError("percent change against zero base")
    return (new - old) / old * 100.0


def shift_of(order: Order) -> str:
    minutes = order.created_at.hour * 60 + order.created_at.minute
    if 6 * 60 <= minutes <= 13 * 60 + 59:
        return MORNING
    if 14 * 60 <= minutes <= 21 * 60 + 59:
        return AFTERNOON
    raise ValueError(f"order outside both shifts: {order.order_id}")


def ends_with_size(name: str, size: str) -> bool:
    return name.casefold().endswith(f"({size})")


def window_pair(day: date, length: int) -> tuple[Period, Period]:
    after = Period(start=day, end=day + timedelta(days=length - 1))
    before = Period(start=day - timedelta(days=length), end=day - timedelta(days=1))
    return after, before


def build_answers(shop: Shop) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}

    def put(qid: str, answer_type: str, answer: Any = None, *, reason: str | None = None) -> None:
        if qid in out:
            raise ValueError(f"question answered twice: {qid}")
        out[qid] = fmt.answer_line(qid, answer_type, answer, reason=reason)

    def money_in(qid: str, as_of: str, period_of: Callable[[Clock], Period]) -> None:
        clock = Clock(as_of)
        put(qid, "number", fmt.money(shop.revenue(period_of(clock), as_of=clock.as_of)))

    def count_in(qid: str, as_of: str, period_of: Callable[[Clock], Period]) -> None:
        clock = Clock(as_of)
        put(qid, "number", fmt.count(shop.order_count(period_of(clock), as_of=clock.as_of)))

    def avg_order_value(qid: str, as_of: str, period_of: Callable[[Clock], Period]) -> None:
        clock = Clock(as_of)
        period = period_of(clock)
        orders = shop.revenue_orders_in(period, as_of=clock.as_of)
        if not orders:
            raise ValueError(f"no orders for {qid}")
        put(qid, "number", fmt.money(sum(o.goods_amount for o in orders) / len(orders)))

    def month_over_month(qid: str, as_of: str, year: int, month: int) -> None:
        clock = Clock(as_of)
        now = clock.month(month, year)
        prev_year, prev_month = (year, month - 1) if month > 1 else (year - 1, 12)
        before = clock.month(prev_month, prev_year)
        put(qid, "percent", fmt.percent(percent_change(shop.revenue(now, as_of=clock.as_of), shop.revenue(before, as_of=clock.as_of))))

    def this_month_vs_last(qid: str, as_of: str) -> None:
        clock = Clock(as_of)
        now = shop.revenue(clock.this_month(), as_of=clock.as_of)
        before = shop.revenue(clock.last_month_same_days(), as_of=clock.as_of)
        put(qid, "percent", fmt.percent(percent_change(now, before)))

    def days_at_least(qid: str, as_of: str, year: int, month: int, threshold: int) -> None:
        clock = Clock(as_of)
        daily = shop.daily_revenue(clock.month(month, year), as_of=clock.as_of)
        put(qid, "number", fmt.count(sum(1 for value in daily.values() if value >= threshold)))

    def customers_at_least(qid: str, as_of: str, year: int, month: int, threshold: int) -> None:
        clock = Clock(as_of)
        counts = shop.orders_per_customer(clock.month(month, year), as_of=clock.as_of)
        put(qid, "number", fmt.count(sum(1 for n in counts.values() if n >= threshold)))

    def customer_share_at_least(qid: str, as_of: str, year: int, month: int, threshold: int) -> None:
        clock = Clock(as_of)
        counts = shop.orders_per_customer(clock.month(month, year), as_of=clock.as_of)
        if not counts:
            raise ValueError(f"no customers for {qid}")
        hits = sum(1 for n in counts.values() if n >= threshold)
        put(qid, "percent", fmt.percent(hits / len(counts) * 100.0))

    def items_in_at_least_orders(qid: str, as_of: str, year: int, month: int, threshold: int) -> None:
        clock = Clock(as_of)
        lines = shop.revenue_lines_in(clock.month(month, year), as_of=clock.as_of)
        seen: dict[str, set[str]] = defaultdict(set)
        for line in lines:
            seen[line.item_code].add(line.order_id)
        put(qid, "number", fmt.count(sum(1 for orders in seen.values() if len(orders) >= threshold)))

    def orders_at_least_value(qid: str, as_of: str, year: int, month: int, threshold: int) -> None:
        clock = Clock(as_of)
        orders = shop.revenue_orders_in(clock.month(month, year), as_of=clock.as_of)
        put(qid, "number", fmt.count(sum(1 for o in orders if o.goods_amount >= threshold)))

    def cancelled_count(qid: str, as_of: str, year: int, month: int) -> None:
        clock = Clock(as_of)
        put(qid, "number", fmt.count(len(shop.orders_in(clock.month(month, year), as_of=clock.as_of, statuses=(STATUS_CANCELLED,)))))

    def group_revenue(qid: str, as_of: str, year: int, month: int, group: str) -> None:
        clock = Clock(as_of)
        lines = shop.revenue_lines_in(clock.month(month, year), as_of=clock.as_of)
        put(qid, "number", fmt.money(sum(ln.amount for ln in lines if ln.group == group)))

    def group_share(qid: str, as_of: str, year: int, month: int, group: str) -> None:
        clock = Clock(as_of)
        period = clock.month(month, year)
        lines = shop.revenue_lines_in(period, as_of=clock.as_of)
        total = shop.revenue(period, as_of=clock.as_of)
        put(qid, "percent", fmt.percent(sum(ln.amount for ln in lines if ln.group == group) / total * 100.0))

    def group_quantity(qid: str, as_of: str, year: int, month: int, group: str) -> None:
        clock = Clock(as_of)
        lines = shop.revenue_lines_in(clock.month(month, year), as_of=clock.as_of)
        put(qid, "number", fmt.quantity(shop.base_quantity(lines, predicate=lambda ln: ln.group == group)))

    def item_quantity(qid: str, as_of: str, year: int, month: int, item: str) -> None:
        clock = Clock(as_of)
        code = shop.item_code_by_name(item)
        lines = shop.revenue_lines_in(clock.month(month, year), as_of=clock.as_of)
        put(qid, "number", fmt.quantity(shop.base_quantity(lines, predicate=lambda ln: ln.item_code == code)))

    def item_revenue(qid: str, as_of: str, year: int, month: int, item: str) -> None:
        clock = Clock(as_of)
        code = shop.item_code_by_name(item)
        lines = shop.revenue_lines_in(clock.month(month, year), as_of=clock.as_of)
        put(qid, "number", fmt.money(sum(ln.amount for ln in lines if ln.item_code == code)))

    def size_quantity(qid: str, as_of: str, year: int, month: int, size: str) -> None:
        clock = Clock(as_of)
        lines = shop.revenue_lines_in(clock.month(month, year), as_of=clock.as_of)
        put(qid, "number", fmt.quantity(shop.base_quantity(lines, predicate=lambda ln: ends_with_size(ln.item_name, size))))

    def cups_in(qid: str, as_of: str, period_of: Callable[[Clock], Period]) -> None:
        clock = Clock(as_of)
        lines = shop.revenue_lines_in(period_of(clock), as_of=clock.as_of)
        put(qid, "number", fmt.quantity(shop.base_quantity(lines, predicate=lambda ln: ln.base_unit == "ly")))

    def best_gross_profit_item(qid: str, as_of: str, year: int, month: int) -> None:
        clock = Clock(as_of)
        lines = shop.revenue_lines_in(clock.month(month, year), as_of=clock.as_of)
        ranked = shop.item_rank(lines, by=shop.gross_profit_lines)
        put(qid, "string", shop.item_name(ranked[0][0]))

    def shift_revenue(qid: str, as_of: str, year: int, month: int, shift: str) -> None:
        clock = Clock(as_of)
        orders = shop.revenue_orders_in(clock.month(month, year), as_of=clock.as_of)
        put(qid, "number", fmt.money(sum(o.goods_amount for o in orders if shift_of(o) == shift)))

    def shift_orders(qid: str, as_of: str, year: int, month: int, shift: str) -> None:
        clock = Clock(as_of)
        orders = shop.revenue_orders_in(clock.month(month, year), as_of=clock.as_of)
        put(qid, "number", fmt.count(sum(1 for o in orders if shift_of(o) == shift)))

    def shift_gap_percent(qid: str, as_of: str, year: int, month: int, measure: str) -> None:
        clock = Clock(as_of)
        orders = shop.revenue_orders_in(clock.month(month, year), as_of=clock.as_of)
        if measure == "revenue":
            morning = sum(o.goods_amount for o in orders if shift_of(o) == MORNING)
            afternoon = sum(o.goods_amount for o in orders if shift_of(o) == AFTERNOON)
        else:
            morning = sum(1 for o in orders if shift_of(o) == MORNING)
            afternoon = sum(1 for o in orders if shift_of(o) == AFTERNOON)
        put(qid, "percent", fmt.percent(percent_change(afternoon, morning)))

    def staff_revenue(qid: str, as_of: str, staff: str, period_of: Callable[[Clock], Period]) -> None:
        clock = Clock(as_of)
        orders = shop.revenue_orders_in(period_of(clock), as_of=clock.as_of)
        put(qid, "number", fmt.money(sum(o.goods_amount for o in orders if o.staff == staff)))

    def payment_form_revenue(qid: str, as_of: str, form: str, period_of: Callable[[Clock], Period]) -> None:
        clock = Clock(as_of)
        orders = shop.revenue_orders_in(period_of(clock), as_of=clock.as_of)
        put(qid, "number", fmt.money(sum(o.goods_amount for o in orders if o.payment_form == form)))

    def best_month(qid: str, as_of: str, months: Sequence[tuple[int, int]]) -> None:
        clock = Clock(as_of)
        scored = [((y, m), shop.revenue(clock.month(m, y), as_of=clock.as_of)) for y, m in months]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        put(qid, "date", fmt.month_answer(scored[0][0]))

    def monotone_increasing(qid: str, as_of: str, months: Sequence[tuple[int, int]]) -> None:
        clock = Clock(as_of)
        values = [shop.revenue(clock.month(m, y), as_of=clock.as_of) for y, m in months]
        put(qid, "boolean", all(b > a for a, b in zip(values, values[1:])))

    def monthly_revenue_list(qid: str, as_of: str, months: Sequence[tuple[int, int]]) -> None:
        clock = Clock(as_of)
        put(qid, "list", [fmt.money(shop.revenue(clock.month(m, y), as_of=clock.as_of)) for y, m in months])

    def debt_total_over_age(qid: str, as_of: str, until: str, days: int) -> None:
        limit = date.fromisoformat(until)
        total = sum(left for order, left in shop.debt_orders(until=limit) if (limit - order.day).days > days)
        put(qid, "number", fmt.money(total))

    def debt_customer_count(qid: str, as_of: str, until: str) -> None:
        limit = date.fromisoformat(until)
        put(qid, "number", fmt.count(len(shop.debt_by_customer(until=limit))))

    def debt_age_buckets(qid: str, as_of: str, until: str) -> None:
        limit = date.fromisoformat(until)
        buckets = [0, 0, 0]
        for order, left in shop.debt_orders(until=limit):
            age = (limit - order.day).days
            if age <= 7:
                buckets[0] += left
            elif age <= 15:
                buckets[1] += left
            else:
                buckets[2] += left
        put(qid, "list", [fmt.money(v) for v in buckets])

    def debt_top_customers(qid: str, as_of: str, until: str, top: int) -> None:
        limit = date.fromisoformat(until)
        ranked = sorted(shop.debt_by_customer(until=limit).items(), key=lambda pair: (-pair[1], pair[0]))[:top]
        rows = [[shop.customer_name(code), fmt.money(value)] for code, value in ranked]
        put(qid, "table", fmt.table(columns=list(TABLE_DEBT_COLUMNS), rows=rows))

    def price_effect(qid: str, as_of: str, item: str, new_price: int, length: int) -> None:
        clock = Clock(as_of)
        code = shop.item_code_by_name(item)
        day = shop.price_change_day(code, new_price)
        after, before = window_pair(day, length)
        sold_after = shop.base_quantity(shop.revenue_lines_in(after, as_of=clock.as_of), predicate=lambda ln: ln.item_code == code)
        sold_before = shop.base_quantity(shop.revenue_lines_in(before, as_of=clock.as_of), predicate=lambda ln: ln.item_code == code)
        put(qid, "percent", fmt.percent(percent_change(sold_after, sold_before)))

    def purchase_minus_sales(qid: str, as_of: str, year: int, month: int, item: str) -> None:
        clock = Clock(as_of)
        period = clock.month(month, year)
        code = shop.item_code_by_name(item)
        bought = sum(p.base_quantity for p in shop.book.purchases if period.contains(p.day) and p.item_code == code and p.day <= clock.as_of)
        sold = shop.base_quantity(shop.revenue_lines_in(period, as_of=clock.as_of), predicate=lambda ln: ln.item_code == code)
        put(qid, "number", fmt.quantity(bought - sold))

    money_in("q_1c0ec38b3d82", "2026-08-21", lambda c: c.tet(2026))
    money_in("q_30934dcc3831", "2026-02-18", lambda c: c.year_to_date())
    money_in("q_32201ceda2ad", "2026-08-21", lambda c: c.month(3, 2025))
    money_in("q_49286a4905a7", "2026-08-21", lambda c: c.month(7, 2026))
    money_in("q_49f27251c376", "2026-04-03", lambda c: c.last_n_days(30))
    money_in("q_6eb11974483f", "2026-04-12", lambda c: c.year_to_date())
    money_in("q_a420c0b8ca8a", "2026-02-10", lambda c: c.year_to_date())
    money_in("q_a57177cbc6da", "2026-03-20", lambda c: c.last_n_days(30))
    money_in("q_b0ce2336c79b", "2026-08-21", lambda c: c.month(2, 2026))
    money_in("q_de25e5a7e1c6", "2025-06-28", lambda c: c.this_week())

    count_in("q_188436bf8db3", "2026-08-21", lambda c: c.quarter(2, 2025))
    count_in("q_1a5c000274ee", "2025-11-09", lambda c: c.this_week())
    count_in("q_27b5996a5f4c", "2025-10-09", lambda c: c.last_n_days(7))
    count_in("q_31ee2863c718", "2026-03-24", lambda c: c.year_to_date())
    count_in("q_50152c2cebd6", "2026-05-03", lambda c: c.year_to_date())
    count_in("q_7d4d7cb3aa73", "2026-02-14", lambda c: c.last_n_days(7))

    avg_order_value("q_01ac0fc9f2a2", "2026-08-18", lambda c: c.last_week())
    avg_order_value("q_09542f67d04a", "2026-03-31", lambda c: c.last_week())
    avg_order_value("q_4b260819febf", "2026-08-21", lambda c: c.month(5, 2025))
    avg_order_value("q_51ba2dc4fd49", "2025-12-09", lambda c: c.last_week())
    avg_order_value("q_77ce65543f25", "2026-08-21", lambda c: c.month(12, 2025))
    avg_order_value("q_900c545f4ed7", "2026-08-21", lambda c: c.month(7, 2026))

    month_over_month("q_3d231754f550", "2026-08-21", 2026, 4)
    month_over_month("q_9956cc60cbb1", "2026-08-21", 2025, 11)
    month_over_month("q_e0e7974d6923", "2026-08-21", 2025, 4)

    this_month_vs_last("q_5f2d481dc5d4", "2025-12-09")
    this_month_vs_last("q_78a7454fde5d", "2025-12-19")
    this_month_vs_last("q_9142ba5ec94a", "2025-08-08")

    days_at_least("q_373a4857ee55", "2026-08-21", 2025, 3, 7_600_000)
    days_at_least("q_4809f845893d", "2026-08-21", 2025, 10, 9_100_000)
    days_at_least("q_78360acadac0", "2026-08-21", 2026, 7, 8_900_000)

    customers_at_least("q_4c849b6df27d", "2026-08-21", 2025, 12, 9)
    customers_at_least("q_656e9a89ca5d", "2026-08-21", 2025, 12, 12)
    customers_at_least("q_780126890512", "2026-08-21", 2025, 7, 11)
    customer_share_at_least("q_6779a7bd2b29", "2026-08-21", 2025, 9, 12)
    customer_share_at_least("q_84edb29b003b", "2026-08-21", 2025, 3, 11)
    customer_share_at_least("q_b40a1380b99c", "2026-08-21", 2026, 4, 12)

    items_in_at_least_orders("q_1341cdede99a", "2026-08-21", 2025, 5, 122)
    items_in_at_least_orders("q_94cca7f32768", "2026-08-21", 2026, 5, 152)
    items_in_at_least_orders("q_b88ec465ade3", "2026-08-21", 2025, 7, 128)

    orders_at_least_value("q_8ee6eb9187d0", "2026-08-21", 2025, 8, 52_000)
    orders_at_least_value("q_9ff971a2b435", "2026-08-21", 2025, 5, 130_000)
    orders_at_least_value("q_effb17cba303", "2026-08-21", 2025, 9, 55_000)

    cancelled_count("q_84201f553dff", "2026-08-21", 2026, 2)
    cancelled_count("q_ef01edd61255", "2026-08-21", 2026, 3)
    cancelled_count("q_f04b126554e3", "2026-08-21", 2025, 5)

    group_revenue("q_d5d84e9e6570", "2026-08-21", 2025, 11, "trà")
    group_share("q_29f0281751c0", "2026-08-21", 2025, 7, "nước ép")
    group_share("q_38c42c83e2ff", "2026-08-21", 2025, 5, "đá xay")
    group_quantity("q_54e2a0754e8b", "2026-08-21", 2026, 1, "cà phê")
    group_quantity("q_929a9dcb0a38", "2026-08-21", 2025, 9, "trà sữa")

    item_quantity("q_4217e6c4305e", "2026-08-21", 2025, 11, "Bánh tiramisu")
    item_quantity("q_64045044c253", "2026-08-21", 2025, 3, "Bánh croissant")
    item_quantity("q_b4ad3b8d023f", "2026-08-21", 2025, 9, "Topping Thạch cà phê")
    item_revenue("q_596f5cfa121c", "2026-08-21", 2026, 5, "Cà phê muối (M)")
    item_revenue("q_cf5c5dac1b20", "2026-08-21", 2026, 7, "Topping Trân châu đen")

    size_quantity("q_1602cfcc7d42", "2026-08-21", 2026, 3, "m")
    size_quantity("q_39b7dafd15a3", "2026-08-21", 2025, 5, "l")
    cups_in("q_c28a03d7a959", "2025-06-23", lambda c: c.last_n_days(7))
    cups_in("q_ce16270f4c20", "2025-12-27", lambda c: c.last_n_days(30))

    best_gross_profit_item("q_07ceefc30333", "2026-08-21", 2026, 4)
    best_gross_profit_item("q_383e2d2f282a", "2026-08-21", 2025, 6)
    best_gross_profit_item("q_c4eef10ab4ae", "2026-08-21", 2026, 1)

    shift_revenue("q_36f612a6b301", "2026-08-21", 2025, 4, AFTERNOON)
    shift_revenue("q_92353891a456", "2026-08-21", 2025, 3, MORNING)
    shift_orders("q_16fc554b8db0", "2026-08-21", 2026, 7, MORNING)
    shift_gap_percent("q_42f82d1abde5", "2026-08-21", 2026, 1, "orders")
    shift_gap_percent("q_5d05956fc827", "2026-08-21", 2026, 3, "revenue")

    staff_revenue("q_28f2fdb96198", "2026-08-21", "NV005", lambda c: c.month(3, 2026))
    staff_revenue("q_82bbd52c42dc", "2026-08-21", "NV001", lambda c: c.this_month())
    staff_revenue("q_f539cf51f360", "2026-08-21", "NV004", lambda c: c.this_month())

    payment_form_revenue("q_cda272637d58", "2026-08-21", "Chuyển khoản", lambda c: c.this_month())

    best_month("q_ca1e5f9e682b", "2026-08-21", ((2025, 3), (2025, 4), (2025, 5)))
    best_month("q_cbf274008dc9", "2026-08-21", ((2026, 1), (2026, 2), (2026, 3)))
    best_month("q_e768afaaf811", "2026-08-21", ((2025, 12), (2026, 1), (2026, 2)))

    monotone_increasing("q_10a0c4fec3d2", "2026-08-21", ((2025, 5), (2025, 6), (2025, 7)))
    monotone_increasing("q_7584b6b0ebbb", "2026-08-21", ((2025, 8), (2025, 9), (2025, 10)))
    monotone_increasing("q_99045ceea1f1", "2026-08-21", ((2025, 11), (2025, 12), (2026, 1)))

    monthly_revenue_list("q_62010007db00", "2026-08-21", ((2026, 4), (2026, 5), (2026, 6)))
    monthly_revenue_list("q_6396e1b202a6", "2026-08-21", ((2025, 7), (2025, 8), (2025, 9)))

    debt_total_over_age("q_715e82ce7602", "2026-07-11", "2026-07-11", 7)
    debt_total_over_age("q_93ff6d28c50b", "2025-06-09", "2025-06-09", 7)
    debt_customer_count("q_3e30ac2f9cc9", "2026-05-15", "2026-05-15")
    debt_customer_count("q_935d887c9cd9", "2025-07-16", "2025-07-16")
    debt_customer_count("q_b7bc96270d9f", "2025-07-02", "2025-07-02")
    debt_age_buckets("q_59b28582f30e", "2025-07-06", "2025-07-06")
    debt_age_buckets("q_7ab1e13137e3", "2026-06-17", "2026-06-17")
    debt_age_buckets("q_aa47ce3a127a", "2026-04-05", "2026-04-05")
    debt_top_customers("q_403bdc83bc9c", "2026-05-12", "2026-05-12", 5)
    debt_top_customers("q_7d7ea7cccf26", "2026-06-12", "2026-06-12", 3)
    debt_top_customers("q_fbb0ba502475", "2025-06-30", "2025-06-30", 5)

    price_effect("q_45d6cbc135b3", "2026-08-21", "Trà vải (L)", 47_000, 30)
    price_effect("q_c810dcd56aa3", "2026-08-21", "Topping Thạch cà phê", 7_400, 30)
    price_effect("q_dd2362109dd4", "2026-08-21", "Bạc xỉu (M)", 35_000, 14)

    purchase_minus_sales("q_b4171cc74531", "2026-08-21", 2026, 3, "Bánh croissant")
    purchase_minus_sales("q_ce8675d1ef06", "2026-08-21", 2025, 10, "Bánh tiramisu")

    answer_remaining(shop, put)
    return out


def answer_remaining(shop: Shop, put: Callable[..., None]) -> None:
    clock = Clock("2026-08-21")

    period = clock.month(10, 2025)
    put("q_06dfe652d857", "number", fmt.money(shop.net_profit(period, as_of=clock.as_of)))
    period = clock.month(7, 2026)
    put("q_6022f2c64913", "number", fmt.money(shop.net_profit(period, as_of=clock.as_of)))
    period = clock.month(1, 2026)
    put("q_f9fee7c180b4", "number", fmt.money(shop.net_profit(period, as_of=clock.as_of)))

    put("q_101e84f9b702", "number", fmt.money(shop.gross_profit(clock.month(6), as_of=clock.as_of)))
    put("q_481f40acc2f3", "number", fmt.money(shop.gross_profit(clock.month(6, 2025), as_of=clock.as_of)))
    put("q_65b2eba9c91c", "number", fmt.money(shop.gross_profit(clock.month(5, 2025), as_of=clock.as_of)))

    period = clock.month(12, 2025)
    slips = {(p.supplier, p.slip) for p in shop.book.purchases if period.contains(p.day)}
    by_supplier: Counter = Counter()
    for supplier, _slip in slips:
        by_supplier[supplier] += 1
    ranked = sorted(by_supplier.items(), key=lambda pair: (-pair[1], pair[0]))
    put("q_08b923f3c5c5", "string", ranked[0][0])

    period = clock.month(6, 2025)
    spend: Counter = Counter()
    for purchase in shop.book.purchases:
        if period.contains(purchase.day):
            spend[purchase.supplier] += purchase.amount
    ranked = sorted(spend.items(), key=lambda pair: (-pair[1], pair[0]))
    put("q_30f08ce67f3e", "string", ranked[0][0])

    period = clock.month(6, 2025)
    counts = shop.orders_per_customer(period, as_of=clock.as_of)
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    put("q_0cb6a1a6f1ef", "string", shop.customer_name(ranked[0][0]))

    period = clock.month(10, 2025)
    days: dict[str, set[date]] = defaultdict(set)
    for order in shop.revenue_orders_in(period, as_of=clock.as_of):
        if not order.walk_in:
            days[order.customer_code].add(order.day)
    ranked = sorted(days.items(), key=lambda pair: (-len(pair[1]), pair[0]))
    put("q_6e929cf36203", "string", shop.customer_name(ranked[0][0]))

    period = clock.month(12, 2025)
    loyal = {code for code, info in shop.book.customers.items() if info["segment"] == LOYAL_SEGMENT}
    orders = [o for o in shop.revenue_orders_in(period, as_of=clock.as_of) if o.customer_code in loyal]
    put("q_12d78074f059", "number", fmt.money(sum(o.goods_amount for o in orders) / len(orders)))

    period = clock.month(8, 2025)
    orders = [o for o in shop.revenue_orders_in(period, as_of=clock.as_of) if o.customer_code in loyal]
    put("q_ba2fc11fac40", "number", fmt.money(sum(o.goods_amount for o in orders)))

    period = clock.month(1, 2026)
    orders = [o for o in shop.revenue_orders_in(period, as_of=clock.as_of) if o.customer_code in loyal]
    total = shop.revenue(period, as_of=clock.as_of)
    put("q_f98cecea1595", "percent", fmt.percent(sum(o.goods_amount for o in orders) / total * 100.0))

    period = clock.month(9, 2025)
    lines = shop.revenue_lines_in(period, as_of=clock.as_of)
    tea_orders = {ln.order_id for ln in lines if ln.group == "trà"}
    put("q_848a1bcdb5f9", "number", fmt.count(len(tea_orders)))

    period = clock.month(11, 2025)
    lines = [ln for ln in shop.revenue_lines_in(period, as_of=clock.as_of) if ln.group == "sinh tố"]
    ranked = shop.item_rank(lines, by=lambda rows: sum(r.base_quantity for r in rows))
    put("q_63cf15f33b1c", "string", shop.item_name(ranked[0][0]))

    period = clock.month(2, 2026)
    lines = [ln for ln in shop.revenue_lines_in(period, as_of=clock.as_of) if ln.group == "bánh"]
    ranked = shop.item_rank(lines, by=lambda rows: sum(r.amount for r in rows))
    put("q_6a752a1d37b5", "string", shop.item_name(ranked[0][0]))

    period = clock.month(7, 2025)
    lines = shop.revenue_lines_in(period, as_of=clock.as_of)
    ranked = shop.item_rank(lines, by=lambda rows: sum(r.base_quantity for r in rows))
    put("q_b53e7cf12ac2", "list", [shop.item_name(code) for code, _ in ranked[:5]])

    week = Clock("2026-05-16")
    lines = shop.revenue_lines_in(week.this_week(), as_of=week.as_of)
    ranked = shop.item_rank(lines, by=lambda rows: sum(r.base_quantity for r in rows))
    put("q_e47610290a38", "list", [shop.item_name(code) for code, _ in ranked[:5]])

    lines = shop.revenue_lines_in(clock.tet(2026), as_of=clock.as_of)
    ranked = shop.item_rank(lines, by=lambda rows: sum(r.base_quantity for r in rows))
    put("q_e4f0a9bdf74b", "string", shop.item_name(ranked[0][0]))

    tet = shop.revenue(clock.tet(2026), as_of=clock.as_of)
    before = shop.revenue(clock.before_tet(2026), as_of=clock.as_of)
    put("q_2c8d4481ca57", "percent", fmt.percent(percent_change(tet, before)))

    now = shop.revenue(clock.month(5, 2026), as_of=clock.as_of)
    before = shop.revenue(clock.month(5, 2025), as_of=clock.as_of)
    put("q_2fba3cf485d7", "percent", fmt.percent(percent_change(now, before)))

    now = shop.revenue(clock.month(4, 2026), as_of=clock.as_of)
    before = shop.revenue(clock.month(4, 2025), as_of=clock.as_of)
    put("q_8df7e247960b", "percent", fmt.percent(percent_change(now, before)))

    orders = shop.revenue_orders_in(clock.this_month(), as_of=clock.as_of)
    put("q_665fbfdbfb70", "number", fmt.money(sum(o.goods_amount for o in orders if o.source == COUNTER_SOURCE)))

    period = clock.month(7, 2025)
    orders = shop.revenue_orders_in(period, as_of=clock.as_of)
    wallet = sum(o.goods_amount for o in orders if o.payment_form == "Ví điện tử")
    cash = sum(o.goods_amount for o in orders if o.payment_form == "Tiền mặt")
    put("q_fe36c469e9f8", "list", [fmt.money(wallet), fmt.money(cash)])

    daily = shop.daily_revenue(clock.month(7, 2026), as_of=clock.as_of)
    best = sorted(daily.items(), key=lambda pair: (-pair[1], pair[0]))[0][0]
    put("q_f86ac4d1df98", "date", fmt.day_answer(best))

    limit = date(2026, 4, 22)
    total = sum(left for order, left in shop.debt_orders(until=limit) if (limit - order.day).days > 7)
    put("q_44f5bc574708", "number", fmt.money(total))

    code = shop.customer_code_by_name("Ha Duy Trung")
    period = clock.month(9, 2025)
    put(
        "q_3f0d7d1b1eb1",
        "list",
        [
            fmt.money(shop.new_debt(period, as_of=clock.as_of, customer_code=code)),
            fmt.money(shop.debt_collected(period, as_of=clock.as_of, customer_code=code)),
        ],
    )

    code = shop.customer_code_by_name("Luu Son Hang")
    period = clock.month(10, 2025)
    put(
        "q_7470c487f115",
        "list",
        [
            fmt.money(shop.new_debt(period, as_of=clock.as_of, customer_code=code)),
            fmt.money(shop.debt_collected(period, as_of=clock.as_of, customer_code=code)),
        ],
    )

    put("q_77264ae59960", "number", fmt.money(shop.debt_collected(clock.month(7, 2025), as_of=clock.as_of)))
    put("q_b621b30b4b22", "number", fmt.money(shop.debt_collected(clock.this_month(), as_of=clock.as_of)))
    put("q_bfbe25641230", "number", fmt.money(shop.debt_collected(clock.month(6, 2026), as_of=clock.as_of)))

    put(
        "q_b5e65648c9dc",
        "unanswerable",
        reason="sổ bán hàng không có cột lý do huỷ đơn, không file nào của shop ghi lý do huỷ",
    )
    put(
        "q_a897b21c864d",
        "unanswerable",
        reason="sổ bán hàng không ghi lý do trả hàng, không lọc được đơn trả vì gọi nhầm món",
    )


def main() -> int:
    book = ShopBook()
    shop = Shop(book)
    answers = build_answers(shop)
    questions = fmt.load_questions(QUESTIONS_PATH)
    missing = [q["id"] for q in questions if q["id"] not in answers]
    extra = [qid for qid in answers if qid not in {q["id"] for q in questions}]
    if missing or extra:
        raise ValueError(f"answer set mismatch: missing={missing} extra={extra}")
    return fmt.write_answers(ANSWERS_PATH, [answers[q["id"]] for q in questions])


if __name__ == "__main__":
    print(main())
