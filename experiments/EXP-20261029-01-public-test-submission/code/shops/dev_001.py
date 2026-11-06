from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

CODE_ROOT = Path("/Users/lebahoai/Workspace/zalo/2026/experiments/EXP-20261029-01-public-test-submission/code")
DATA_DIR = Path("/Users/lebahoai/Workspace/zalo/2026/public_test/data/dev_001")
OUT_PATH = CODE_ROOT.parent / "out" / "answers" / "dev_001.jsonl"
SALES_FILE = DATA_DIR / "So_chi_tiet_ban_hang.xlsx"
CATALOG_FILE = DATA_DIR / "Danh sách hàng hóa.xlsx"
QUESTIONS_FILE = DATA_DIR / "questions.jsonl"
SALES_HEADER_ROW = 3
CATALOG_HEADER_ROW = 0

if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

import pandas as pd

from datamate import Clock, fmt, fold_key, parse_date, parse_money, parse_number, read_table, squeeze
from datamate.tabio import census, drop_subtotal_rows

STATUS_BY_LABEL = {
    "hoàn thành": "hoàn thành",
    "đã xong": "hoàn thành",
    "đã hủy đơn": "huỷ",
    "khách hủy": "huỷ",
    "đã hoàn hàng": "trả hàng",
    "hàng trả về": "trả hàng",
    "đang giao hàng": "đang giao",
}
REVENUE_STATUSES = ("hoàn thành", "đang giao")
WALKIN_KEYS = frozenset({"le", "khach le", "kl"})


class SalesBook:
    """Sổ chi tiết bán hàng của dev_001 đã ingest: dòng hàng, đơn, và danh mục hàng hoá."""

    def __init__(self, lines: pd.DataFrame, orders: pd.DataFrame, catalog: pd.DataFrame) -> None:
        if lines.empty or orders.empty or catalog.empty:
            raise ValueError("sales book cannot be built from empty frames")
        self.lines = lines
        self.orders = orders
        self.catalog = catalog

    def visible_lines(self, as_of: date) -> pd.DataFrame:
        return self.lines[self.lines["date"] <= as_of]

    def visible_orders(self, as_of: date) -> pd.DataFrame:
        return self.orders[self.orders["date"] <= as_of]

    def revenue_lines(self, as_of: date, start: date, end: date) -> pd.DataFrame:
        frame = self.visible_lines(as_of)
        in_period = (frame["date"] >= start) & (frame["date"] <= end)
        return frame[in_period & frame["status"].isin(REVENUE_STATUSES)]

    def revenue_orders(self, as_of: date, start: date, end: date) -> pd.DataFrame:
        frame = self.visible_orders(as_of)
        in_period = (frame["date"] >= start) & (frame["date"] <= end)
        return frame[in_period & frame["status"].isin(REVENUE_STATUSES)]

    def placed_orders(self, as_of: date, start: date, end: date) -> pd.DataFrame:
        frame = self.visible_orders(as_of)
        in_period = (frame["date"] >= start) & (frame["date"] <= end)
        return frame[in_period]

    def canonical_name(self, wanted: str) -> str:
        key = fold_key(wanted)
        hit = self.catalog[self.catalog["fold"] == key]
        if hit.empty:
            raise ValueError(f"item not in catalog: {wanted}")
        return str(hit.iloc[0]["name"])


def load_catalog() -> pd.DataFrame:
    raw = read_table(CATALOG_FILE, header_row=CATALOG_HEADER_ROW)
    frame = pd.DataFrame(
        {
            "code": [squeeze(v) for v in raw["Mã hàng hóa"]],
            "name": [squeeze(v) for v in raw["Tên hàng hóa"]],
            "group": [squeeze(v) for v in raw["Nhóm hàng hóa"]],
            "base_unit": [squeeze(v) for v in raw["Đơn vị tính"]],
            "price": [parse_money(v) for v in raw["Giá bán"]],
            "cost": [parse_money(v) for v in raw["Giá vốn"]],
        }
    )
    frame["fold"] = [fold_key(v) for v in frame["name"]]
    if frame["fold"].duplicated().any():
        raise ValueError("catalog has two rows with the same folded name")
    return frame


def load_lines(catalog: pd.DataFrame) -> pd.DataFrame:
    raw = read_table(SALES_FILE, header_row=SALES_HEADER_ROW)
    kept = drop_subtotal_rows(raw, key_columns=["Mã đơn hàng"])
    frame = pd.DataFrame(
        {
            "date": [parse_date(v) for v in kept["Ngày"]],
            "order": [squeeze(v) for v in kept["Mã đơn hàng"]],
            "raw_name": [squeeze(v) for v in kept["Tên hàng hóa"]],
            "unit": [squeeze(v) for v in kept["Đơn vị tính"]],
            "qty": [parse_number(v) for v in kept["Số lượng"]],
            "unit_price": [parse_money(v) for v in kept["Đơn giá"]],
            "amount": [parse_money(v) for v in kept["Thành tiền"]],
            "base_qty": [parse_number(v) for v in kept["Số lượng quy đổi"]],
            "raw_status": [squeeze(v) for v in kept["Trạng thái"]],
            "raw_customer": [squeeze(v) for v in kept["Khách hàng"]],
        }
    )
    if frame[["date", "qty", "unit_price", "amount", "base_qty"]].isna().any().any():
        raise ValueError("sales sheet has unparsable date, quantity or money cells")
    unknown = sorted({s for s in frame["raw_status"] if s.casefold() not in STATUS_BY_LABEL})
    if unknown:
        raise ValueError(f"unknown order statuses: {unknown}")
    frame["status"] = [STATUS_BY_LABEL[s.casefold()] for s in frame["raw_status"]]
    frame["fold"] = [fold_key(v) for v in frame["raw_name"]]
    frame["cust_key"] = [fold_key(v) for v in frame["raw_customer"]]
    frame["walkin"] = frame["cust_key"].isin(WALKIN_KEYS)
    index = catalog.set_index("fold")
    frame["code"] = frame["fold"].map(index["code"])
    frame["name"] = frame["fold"].map(index["name"])
    frame["group"] = frame["fold"].map(index["group"])
    frame["base_unit"] = frame["fold"].map(index["base_unit"])
    missing = sorted(set(frame.loc[frame["code"].isna(), "raw_name"]))
    if missing:
        raise ValueError(f"item names absent from catalog: {missing}")
    single_token = sorted({n for n in frame.loc[~frame["walkin"], "raw_customer"] if " " not in n})
    if single_token:
        raise ValueError(f"customer names look like walk-in labels, not people: {single_token}")
    deduped = frame.drop_duplicates(
        subset=["order", "raw_name", "unit", "qty", "unit_price", "amount", "base_qty", "raw_status", "raw_customer", "date"]
    )
    if len(deduped) != len(frame):
        raise ValueError("identical duplicate lines inside one order were not expected at dev_001")
    return frame


def build_orders(lines: pd.DataFrame) -> pd.DataFrame:
    if int((lines.groupby("order")["date"].nunique() > 1).sum()):
        raise ValueError("an order carries two different dates")
    if int((lines.groupby("order")["status"].nunique() > 1).sum()):
        raise ValueError("an order carries two different statuses")
    grouped = lines.groupby("order", sort=True)
    orders = grouped.agg(
        date=("date", "first"),
        status=("status", "first"),
        revenue=("amount", "sum"),
        cust_key=("cust_key", "first"),
        raw_customer=("raw_customer", "first"),
        walkin=("walkin", "first"),
        line_count=("amount", "size"),
    )
    return orders.reset_index()


def load_book() -> SalesBook:
    catalog = load_catalog()
    lines = load_lines(catalog)
    return SalesBook(lines=lines, orders=build_orders(lines), catalog=catalog)


def revenue_of_period(book: SalesBook, as_of: date, start: date, end: date) -> int:
    return fmt.money(book.revenue_lines(as_of, start, end)["amount"].sum())


def revenue_of_item(book: SalesBook, as_of: date, start: date, end: date, item: str) -> int:
    frame = book.revenue_lines(as_of, start, end)
    key = fold_key(item)
    return fmt.money(frame[frame["fold"] == key]["amount"].sum())


def revenue_of_group(book: SalesBook, as_of: date, start: date, end: date, group: str) -> int:
    frame = book.revenue_lines(as_of, start, end)
    return fmt.money(frame[frame["group"] == group]["amount"].sum())


def order_count_of_period(book: SalesBook, as_of: date, start: date, end: date) -> int:
    return fmt.count(len(book.revenue_orders(as_of, start, end)))


def cancelled_order_count(book: SalesBook, as_of: date, start: date, end: date) -> int:
    frame = book.placed_orders(as_of, start, end)
    return fmt.count(int((frame["status"] == "huỷ").sum()))


def cancel_rate_percent(book: SalesBook, as_of: date, start: date, end: date) -> float:
    frame = book.placed_orders(as_of, start, end)
    if frame.empty:
        raise ValueError("no order placed in period")
    return fmt.percent(100.0 * float((frame["status"] == "huỷ").sum()) / float(len(frame)))


def average_order_value(book: SalesBook, as_of: date, start: date, end: date) -> int:
    frame = book.revenue_orders(as_of, start, end)
    if frame.empty:
        raise ValueError("no revenue order in period")
    return fmt.money(float(frame["revenue"].sum()) / float(len(frame)))


def orders_at_least(book: SalesBook, as_of: date, start: date, end: date, floor: int) -> int:
    frame = book.revenue_orders(as_of, start, end)
    return fmt.count(int((frame["revenue"] >= floor).sum()))


def days_at_least(book: SalesBook, as_of: date, start: date, end: date, floor: int) -> int:
    frame = book.revenue_orders(as_of, start, end)
    daily = frame.groupby("date")["revenue"].sum()
    return fmt.count(int((daily >= floor).sum()))


def customer_orders(book: SalesBook, as_of: date, start: date, end: date) -> pd.Series:
    frame = book.revenue_orders(as_of, start, end)
    named = frame[~frame["walkin"]]
    return named.groupby("cust_key")["revenue"].size()


def customers_at_least(book: SalesBook, as_of: date, start: date, end: date, floor: int) -> int:
    counts = customer_orders(book, as_of, start, end)
    return fmt.count(int((counts >= floor).sum()))


def customer_share_at_least(book: SalesBook, as_of: date, start: date, end: date, floor: int) -> float:
    counts = customer_orders(book, as_of, start, end)
    if counts.empty:
        raise ValueError("no named customer bought in period")
    return fmt.percent(100.0 * float((counts >= floor).sum()) / float(len(counts)))


def _customer_name(book: SalesBook, as_of: date, start: date, end: date, key: str) -> str:
    frame = book.revenue_orders(as_of, start, end)
    hit = frame[frame["cust_key"] == key]
    return str(hit.iloc[0]["raw_customer"])


def top_customer_by_orders(book: SalesBook, as_of: date, start: date, end: date) -> str:
    frame = book.revenue_orders(as_of, start, end)
    named = frame[~frame["walkin"]]
    if named.empty:
        raise ValueError("no named customer bought in period")
    table = named.groupby(["cust_key", "raw_customer"]).size().reset_index(name="orders")
    table = table.sort_values(["orders", "raw_customer"], ascending=[False, True])
    return str(table.iloc[0]["raw_customer"])


def top_customer_by_revenue(book: SalesBook, as_of: date, start: date, end: date) -> str:
    frame = book.revenue_orders(as_of, start, end)
    named = frame[~frame["walkin"]]
    if named.empty:
        raise ValueError("no named customer bought in period")
    table = named.groupby(["cust_key", "raw_customer"])["revenue"].sum().reset_index(name="revenue")
    table = table.sort_values(["revenue", "raw_customer"], ascending=[False, True])
    return str(table.iloc[0]["raw_customer"])


def best_sellers(book: SalesBook, as_of: date, start: date, end: date, top: int) -> tuple[str, ...]:
    frame = book.revenue_lines(as_of, start, end)
    if frame.empty:
        raise ValueError("no sales line in period")
    table = frame.groupby(["code", "name"])["base_qty"].sum().reset_index()
    table = table.sort_values(["base_qty", "code"], ascending=[False, True])
    return tuple(str(v) for v in table.head(top)["name"])


def group_leader_by_revenue(book: SalesBook, as_of: date, start: date, end: date, group: str) -> str:
    frame = book.revenue_lines(as_of, start, end)
    scoped = frame[frame["group"] == group]
    if scoped.empty:
        raise ValueError(f"no sales line of group {group} in period")
    table = scoped.groupby(["code", "name"])["amount"].sum().reset_index()
    table = table.sort_values(["amount", "code"], ascending=[False, True])
    return str(table.iloc[0]["name"])


def group_leader_by_base_quantity(book: SalesBook, as_of: date, start: date, end: date, group: str) -> str:
    frame = book.revenue_lines(as_of, start, end)
    scoped = frame[frame["group"] == group]
    if scoped.empty:
        raise ValueError(f"no sales line of group {group} in period")
    table = scoped.groupby(["code", "name"])["base_qty"].sum().reset_index()
    table = table.sort_values(["base_qty", "code"], ascending=[False, True])
    return str(table.iloc[0]["name"])


def group_revenue_share_percent(book: SalesBook, as_of: date, start: date, end: date, group: str) -> float:
    frame = book.revenue_lines(as_of, start, end)
    total = float(frame["amount"].sum())
    if total <= 0:
        raise ValueError("shop revenue is zero in period")
    return fmt.percent(100.0 * float(frame[frame["group"] == group]["amount"].sum()) / total)


def orders_touching_group(book: SalesBook, as_of: date, start: date, end: date, group: str) -> int:
    frame = book.revenue_lines(as_of, start, end)
    return fmt.count(frame[frame["group"] == group]["order"].nunique())


def items_in_at_least_orders(book: SalesBook, as_of: date, start: date, end: date, floor: int) -> int:
    frame = book.revenue_lines(as_of, start, end)
    spread = frame.groupby("code")["order"].nunique()
    return fmt.count(int((spread >= floor).sum()))


def base_quantity_of_unit(book: SalesBook, as_of: date, start: date, end: date, unit: str) -> int | float:
    frame = book.revenue_lines(as_of, start, end)
    return fmt.quantity(frame[frame["base_unit"] == unit]["base_qty"].sum())


def base_quantity_of_item(book: SalesBook, as_of: date, start: date, end: date, item: str) -> float:
    frame = book.revenue_lines(as_of, start, end)
    key = fold_key(item)
    return float(frame[frame["fold"] == key]["base_qty"].sum())


def price_rise_quantity_percent(book: SalesBook, as_of: date, item: str, rise_day: date, window: int) -> float:
    after_end = rise_day + timedelta(days=window - 1)
    before_start = rise_day - timedelta(days=window)
    before_end = rise_day - timedelta(days=1)
    after = base_quantity_of_item(book, as_of, rise_day, after_end, item)
    before = base_quantity_of_item(book, as_of, before_start, before_end, item)
    if before <= 0:
        raise ValueError("no base quantity before the price rise")
    return fmt.percent(100.0 * (after - before) / before)


def change_percent(current: int, previous: int) -> float:
    if previous == 0:
        raise ValueError("previous period revenue is zero")
    return fmt.percent(100.0 * float(current - previous) / float(previous))


def best_month(book: SalesBook, as_of: date, months: Sequence[tuple[int, int]]) -> str:
    clock = Clock(as_of)
    scored = []
    for year, month in months:
        period = clock.month(month, year)
        scored.append(((year, month), revenue_of_period(book, as_of, period.start, period.end)))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return fmt.month_answer(scored[0][0])


def best_day(book: SalesBook, as_of: date, start: date, end: date) -> str:
    frame = book.revenue_orders(as_of, start, end)
    if frame.empty:
        raise ValueError("no revenue order in period")
    daily = frame.groupby("date")["revenue"].sum().reset_index()
    daily = daily.sort_values(["revenue", "date"], ascending=[False, True])
    return fmt.day_answer(daily.iloc[0]["date"])


def monthly_revenues(book: SalesBook, as_of: date, months: Sequence[tuple[int, int]]) -> tuple[int, ...]:
    clock = Clock(as_of)
    out: list[int] = []
    for year, month in months:
        period = clock.month(month, year)
        out.append(revenue_of_period(book, as_of, period.start, period.end))
    return tuple(out)


def rises_every_month(book: SalesBook, as_of: date, months: Sequence[tuple[int, int]]) -> bool:
    series = monthly_revenues(book, as_of, months)
    return all(series[i] < series[i + 1] for i in range(len(series) - 1))


def month_over_month_percent(book: SalesBook, as_of: date, year: int, month: int, base_year: int, base_month: int) -> float:
    clock = Clock(as_of)
    now = clock.month(month, year)
    before = clock.month(base_month, base_year)
    return change_percent(
        revenue_of_period(book, as_of, now.start, now.end),
        revenue_of_period(book, as_of, before.start, before.end),
    )


def this_month_vs_last_month_same_days_percent(book: SalesBook, as_of: date) -> float:
    clock = Clock(as_of)
    now = clock.this_month()
    before = clock.last_month_same_days()
    return change_percent(
        revenue_of_period(book, as_of, now.start, now.end),
        revenue_of_period(book, as_of, before.start, before.end),
    )


def build_answers(book: SalesBook) -> tuple[dict[str, Any], ...]:
    questions = fmt.load_questions(QUESTIONS_FILE)
    handlers = answer_handlers(book)
    lines: list[dict[str, Any]] = []
    for question in questions:
        handler = handlers.get(question["id"])
        if handler is None:
            raise ValueError(f"no handler for question {question['id']}")
        lines.append(handler(date.fromisoformat(question["as_of_date"])))
    return tuple(lines)


def answer_handlers(book: SalesBook) -> dict[str, Callable[[date], dict[str, Any]]]:
    def month_revenue(qid: str, year: int, month: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "number", revenue_of_period(book, as_of, period.start, period.end))

        return run

    def item_month_revenue(qid: str, item: str, year: int, month: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "number", revenue_of_item(book, as_of, period.start, period.end, item))

        return run

    def group_month_revenue(qid: str, group: str, year: int, month: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "number", revenue_of_group(book, as_of, period.start, period.end, group))

        return run

    def month_average_order(qid: str, year: int, month: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "number", average_order_value(book, as_of, period.start, period.end))

        return run

    def last_week_average_order(qid: str) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).last_week()
            return fmt.answer_line(qid, "number", average_order_value(book, as_of, period.start, period.end))

        return run

    def month_orders_at_least(qid: str, year: int, month: int, floor: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "number", orders_at_least(book, as_of, period.start, period.end, floor))

        return run

    def month_days_at_least(qid: str, year: int, month: int, floor: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "number", days_at_least(book, as_of, period.start, period.end, floor))

        return run

    def month_customers_at_least(qid: str, year: int, month: int, floor: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "number", customers_at_least(book, as_of, period.start, period.end, floor))

        return run

    def month_customer_share(qid: str, year: int, month: int, floor: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "percent", customer_share_at_least(book, as_of, period.start, period.end, floor))

        return run

    def month_top_customer_orders(qid: str, year: int, month: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "string", top_customer_by_orders(book, as_of, period.start, period.end))

        return run

    def month_cancelled(qid: str, year: int, month: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "number", cancelled_order_count(book, as_of, period.start, period.end))

        return run

    def month_orders_touching_group(qid: str, group: str, year: int, month: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "number", orders_touching_group(book, as_of, period.start, period.end, group))

        return run

    def month_items_in_orders(qid: str, year: int, month: int, floor: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "number", items_in_at_least_orders(book, as_of, period.start, period.end, floor))

        return run

    def month_group_leader_revenue(qid: str, group: str, year: int, month: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = Clock(as_of).month(month, year)
            return fmt.answer_line(qid, "string", group_leader_by_revenue(book, as_of, period.start, period.end, group))

        return run

    def months_list_revenue(qid: str, months: Sequence[tuple[int, int]]) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            return fmt.answer_line(qid, "list", list(monthly_revenues(book, as_of, months)))

        return run

    def months_best(qid: str, months: Sequence[tuple[int, int]]) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            return fmt.answer_line(qid, "date", best_month(book, as_of, months))

        return run

    def months_rising(qid: str, months: Sequence[tuple[int, int]]) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            return fmt.answer_line(qid, "boolean", rises_every_month(book, as_of, months))

        return run

    def months_change(qid: str, year: int, month: int, base_year: int, base_month: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            return fmt.answer_line(qid, "percent", month_over_month_percent(book, as_of, year, month, base_year, base_month))

        return run

    def this_month_change(qid: str) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            return fmt.answer_line(qid, "percent", this_month_vs_last_month_same_days_percent(book, as_of))

        return run

    def price_rise(qid: str, item: str, rise_day: str, window: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            return fmt.answer_line(
                qid, "percent", price_rise_quantity_percent(book, as_of, item, date.fromisoformat(rise_day), window)
            )

        return run

    def unanswerable(qid: str, reason: str) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            return fmt.answer_line(qid, "unanswerable", reason=reason)

        return run

    def period_revenue(qid: str, window: Callable[[Clock], Any]) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = window(Clock(as_of))
            return fmt.answer_line(qid, "number", revenue_of_period(book, as_of, period.start, period.end))

        return run

    def period_order_count(qid: str, window: Callable[[Clock], Any]) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = window(Clock(as_of))
            return fmt.answer_line(qid, "number", order_count_of_period(book, as_of, period.start, period.end))

        return run

    def period_best_sellers(qid: str, window: Callable[[Clock], Any], top: int) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = window(Clock(as_of))
            return fmt.answer_line(qid, "list", list(best_sellers(book, as_of, period.start, period.end, top)))

        return run

    def period_unit_quantity(qid: str, window: Callable[[Clock], Any], unit: str) -> Callable[[date], dict[str, Any]]:
        def run(as_of: date) -> dict[str, Any]:
            period = window(Clock(as_of))
            return fmt.answer_line(qid, "number", base_quantity_of_unit(book, as_of, period.start, period.end, unit))

        return run

    year_to_date = lambda clock: clock.year_to_date()
    this_week = lambda clock: clock.this_week()
    last_week = lambda clock: clock.last_week()
    today = lambda clock: clock.today()

    return {
        "q_01d1fc600b26": item_month_revenue("q_01d1fc600b26", "Bia Heineken 330ml", 2025, 7),
        "q_0537f6e4f5ab": months_best("q_0537f6e4f5ab", ((2025, 3), (2025, 4), (2025, 5))),
        "q_05ab1c71dcaa": month_top_customer_orders("q_05ab1c71dcaa", 2025, 4),
        "q_08f075b54698": period_order_count("q_08f075b54698", year_to_date),
        "q_09e3efc66c68": month_average_order("q_09e3efc66c68", 2025, 5),
        "q_0ed1ebc4fe4d": month_customers_at_least("q_0ed1ebc4fe4d", 2025, 11, 4),
        "q_0f59f61affd1": period_order_count("q_0f59f61affd1", year_to_date),
        "q_11c915f78c7e": period_order_count("q_11c915f78c7e", this_week),
        "q_1618b7c50ae7": month_customer_share("q_1618b7c50ae7", 2025, 7, 3),
        "q_18b0cb2e9c4c": month_orders_at_least("q_18b0cb2e9c4c", 2025, 8, 180_000),
        "q_1e3b66ee62f2": unanswerable("q_1e3b66ee62f2", "sổ bán hàng không có cột kênh bán hay hình thức đặt hàng của từng đơn"),
        "q_23f483dd4193": period_order_count("q_23f483dd4193", this_week),
        "q_262952036572": period_best_sellers("q_262952036572", last_week, 3),
        "q_278b0742d740": month_items_in_orders("q_278b0742d740", 2026, 4, 84),
        "q_279180641d59": month_items_in_orders("q_279180641d59", 2025, 7, 74),
        "q_29e1057e3fbd": this_month_change("q_29e1057e3fbd"),
        "q_33dcfa1e37c9": lambda as_of: fmt.answer_line(
            "q_33dcfa1e37c9",
            "percent",
            cancel_rate_percent(book, as_of, Clock(as_of).month(7, 2025).start, Clock(as_of).month(7, 2025).end),
        ),
        "q_37d9de7f49d9": months_change("q_37d9de7f49d9", 2026, 4, 2026, 3),
        "q_3b20bc6d6427": price_rise("q_3b20bc6d6427", "Đậu phộng rang muối 200g", "2025-09-01", 30),
        "q_3cac54cdb967": period_revenue("q_3cac54cdb967", lambda clock: clock.last_n_days(7)),
        "q_49b8346acb90": month_revenue("q_49b8346acb90", 2025, 11),
        "q_4cffc6443c2c": month_revenue("q_4cffc6443c2c", 2026, 1),
        "q_4f77d67fdf9c": month_days_at_least("q_4f77d67fdf9c", 2025, 11, 9_500_000),
        "q_5415c46d8a2e": month_days_at_least("q_5415c46d8a2e", 2026, 2, 18_000_000),
        "q_55929bed8ced": month_orders_at_least("q_55929bed8ced", 2025, 2, 190_000),
        "q_55e2e56d2787": lambda as_of: fmt.answer_line(
            "q_55e2e56d2787",
            "date",
            best_day(book, as_of, Clock(as_of).month(5, 2026).start, Clock(as_of).month(5, 2026).end),
        ),
        "q_5860bae9659f": this_month_change("q_5860bae9659f"),
        "q_5aef26f2ebb6": unanswerable("q_5aef26f2ebb6", "dữ liệu không ghi giới tính khách hàng, chỉ có tên khách trên đơn"),
        "q_5dce492e5f1a": months_change("q_5dce492e5f1a", 2026, 3, 2025, 3),
        "q_625ec1abde64": period_revenue("q_625ec1abde64", today),
        "q_6c9f50b55906": month_customer_share("q_6c9f50b55906", 2025, 6, 5),
        "q_6dd1a1921d60": last_week_average_order("q_6dd1a1921d60"),
        "q_6ed01172bd03": unanswerable("q_6ed01172bd03", "dữ liệu không ghi địa chỉ hay đường của khách hàng"),
        "q_7196b4e35b1b": month_average_order("q_7196b4e35b1b", 2025, 9),
        "q_72e220b80878": month_top_customer_orders("q_72e220b80878", 2025, 9),
        "q_7dff48b107f0": group_month_revenue("q_7dff48b107f0", "thực phẩm", 2025, 2),
        "q_8426163ea7bd": period_revenue("q_8426163ea7bd", last_week),
        "q_8694ac4443ef": month_orders_touching_group("q_8694ac4443ef", "bia", 2026, 1),
        "q_8728cb609428": months_change("q_8728cb609428", 2026, 2, 2025, 2),
        "q_8fef6f1e6ff0": period_order_count("q_8fef6f1e6ff0", today),
        "q_92c6660df209": month_cancelled("q_92c6660df209", 2025, 2),
        "q_95427850405e": period_unit_quantity("q_95427850405e", lambda clock: clock.last_n_days(30), "gói"),
        "q_9d4a0d4b4bcd": months_list_revenue("q_9d4a0d4b4bcd", ((2025, 7), (2025, 8), (2025, 9))),
        "q_9e28638a40cb": period_revenue("q_9e28638a40cb", year_to_date),
        "q_9e82414141dd": month_top_customer_orders("q_9e82414141dd", 2025, 1),
        "q_a5c0d50944b4": month_orders_touching_group("q_a5c0d50944b4", "bánh kẹo", 2025, 9),
        "q_a6cf2d550014": lambda as_of: fmt.answer_line(
            "q_a6cf2d550014",
            "string",
            group_leader_by_base_quantity(book, as_of, Clock(as_of).month(11, 2025).start, Clock(as_of).month(11, 2025).end, "gạo"),
        ),
        "q_a8da9136963f": period_order_count("q_a8da9136963f", lambda clock: clock.last_n_days(7)),
        "q_aa7c51569962": months_change("q_aa7c51569962", 2025, 2, 2025, 1),
        "q_ab14596b6b93": months_change("q_ab14596b6b93", 2025, 10, 2025, 9),
        "q_ab595fc253e0": last_week_average_order("q_ab595fc253e0"),
        "q_af1b6f2ebf9b": period_revenue("q_af1b6f2ebf9b", year_to_date),
        "q_b1ee04ab9d3f": months_best("q_b1ee04ab9d3f", ((2026, 2), (2026, 3), (2026, 4))),
        "q_b3c49510b3b7": lambda as_of: fmt.answer_line(
            "q_b3c49510b3b7",
            "percent",
            group_revenue_share_percent(book, as_of, Clock(as_of).month(4, 2025).start, Clock(as_of).month(4, 2025).end, "hoá phẩm"),
        ),
        "q_b3c5bd56d757": month_cancelled("q_b3c5bd56d757", 2026, 5),
        "q_b723bbe29e20": month_orders_at_least("q_b723bbe29e20", 2025, 11, 400_000),
        "q_b7ad6a55cf62": month_orders_touching_group("q_b7ad6a55cf62", "đồ ăn vặt", 2025, 9),
        "q_b963dcade0d3": month_cancelled("q_b963dcade0d3", 2026, 4),
        "q_b9de131bae7d": lambda as_of: fmt.answer_line(
            "q_b9de131bae7d",
            "string",
            top_customer_by_revenue(book, as_of, Clock(as_of).month(8, 2025).start, Clock(as_of).month(8, 2025).end),
        ),
        "q_be8b3469756d": months_rising("q_be8b3469756d", ((2025, 6), (2025, 7), (2025, 8))),
        "q_bf314c953c1e": group_month_revenue("q_bf314c953c1e", "bánh kẹo", 2025, 10),
        "q_c0287211ca77": month_customer_share("q_c0287211ca77", 2025, 10, 3),
        "q_c0a590d269df": period_unit_quantity("q_c0a590d269df", last_week, "chai"),
        "q_c2eaa7985cf2": months_change("q_c2eaa7985cf2", 2026, 5, 2025, 5),
        "q_c33e026f59e7": month_group_leader_revenue("q_c33e026f59e7", "gia vị", 2025, 11),
        "q_c3652d93727e": month_revenue("q_c3652d93727e", 2025, 12),
        "q_c4fc35ebf2ee": unanswerable("q_c4fc35ebf2ee", "dữ liệu không ghi chất lượng, đánh giá hay tỉ lệ lỗi của mặt hàng"),
        "q_c6bfd1c2506f": period_unit_quantity("q_c6bfd1c2506f", last_week, "gói"),
        "q_c8f95328ca75": price_rise("q_c8f95328ca75", "Dầu gội Clear 630g", "2025-05-28", 30),
        "q_caba1ee84f03": months_list_revenue("q_caba1ee84f03", ((2025, 2), (2025, 3), (2025, 4))),
        "q_cc893126c047": month_group_leader_revenue("q_cc893126c047", "chăm sóc cá nhân", 2025, 11),
        "q_d4b2f0aaf69a": item_month_revenue("q_d4b2f0aaf69a", "Bia Sài Gòn Special 330ml", 2025, 8),
        "q_d52c9b04ca54": months_rising("q_d52c9b04ca54", ((2026, 1), (2026, 2), (2026, 3))),
        "q_d95266d008e5": item_month_revenue("q_d95266d008e5", "Sữa đặc Ông Thọ 380g", 2025, 5),
        "q_d9f743469198": price_rise("q_d9f743469198", "Sữa đặc Ông Thọ 380g", "2025-11-13", 30),
        "q_dad922a3924a": period_revenue("q_dad922a3924a", last_week),
        "q_dce7cb2e38a8": month_customers_at_least("q_dce7cb2e38a8", 2025, 10, 5),
        "q_e2bfd7f28a9a": this_month_change("q_e2bfd7f28a9a"),
        "q_e3f5a85b72b4": months_list_revenue("q_e3f5a85b72b4", ((2026, 4), (2026, 5), (2026, 6))),
        "q_e966e0e6802e": months_best("q_e966e0e6802e", ((2026, 3), (2026, 4), (2026, 5))),
        "q_e9eeeaa6cb03": month_customers_at_least("q_e9eeeaa6cb03", 2025, 4, 3),
        "q_eced47bf8f4b": last_week_average_order("q_eced47bf8f4b"),
        "q_f09bd63b0751": months_rising("q_f09bd63b0751", ((2025, 12), (2026, 1), (2026, 2))),
        "q_f5fae09ccd1e": month_days_at_least("q_f5fae09ccd1e", 2025, 8, 10_000_000),
        "q_f66f667088cb": lambda as_of: fmt.answer_line(
            "q_f66f667088cb",
            "list",
            list(best_sellers(book, as_of, Clock(as_of).month(6, 2026).start, Clock(as_of).month(6, 2026).end, 3)),
        ),
        "q_fa3b2b76f9b3": month_items_in_orders("q_fa3b2b76f9b3", 2026, 1, 79),
        "q_fa92cbe8434c": month_average_order("q_fa92cbe8434c", 2025, 6),
    }


def inventory_report(book: SalesBook) -> str:
    raw = read_table(SALES_FILE, header_row=SALES_HEADER_ROW)
    report = [census(raw, key_columns=["Mã đơn hàng"])]
    report.append(f"lines kept={len(book.lines)} orders={len(book.orders)}")
    report.append(f"date range={book.lines['date'].min()}..{book.lines['date'].max()}")
    report.append("status: " + ", ".join(f"{k}={v}" for k, v in book.orders["status"].value_counts().items()))
    return "\n".join(report)


def main() -> int:
    book = load_book()
    print(inventory_report(book))
    lines = build_answers(book)
    written = fmt.write_answers(OUT_PATH, lines)
    print(f"written={written} -> {OUT_PATH}")
    return written


if __name__ == "__main__":
    main()
