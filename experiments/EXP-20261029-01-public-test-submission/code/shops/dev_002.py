from __future__ import annotations

import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd
from pydantic import BaseModel, ConfigDict

CODE_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = CODE_ROOT.parent
REPO_ROOT = EXPERIMENT_ROOT.parents[1]
SHOP = "dev_002"
DATA_DIR = REPO_ROOT / "public_test" / "data" / SHOP
QUESTIONS_PATH = DATA_DIR / "questions.jsonl"
ANSWERS_PATH = EXPERIMENT_ROOT / "out" / "answers" / f"{SHOP}.jsonl"
SALES_SHEET = "DonHang_ChiTiet"
HEADER_ROW = 3
CONVERSION_FILE = "DanhSachQuyDoi.xlsx"

sys.path.insert(0, str(CODE_ROOT))

from datamate import Clock, fmt, parse_date, parse_money, parse_number, read_table, squeeze  # noqa: E402

WALK_IN_KEYS = frozenset({"khach le", "le", "kl"})
REVENUE_STATUSES = frozenset({"Đã hoàn thành", "Đang giao dịch"})
CANCELLED_STATUS = "Đã hủy"
RETURNED_STATUS = "Đã hoàn hàng"
REPEATED_HEADER_MARK = "Mã đơn hàng"
SUBTOTAL_LABELS = ("TỔNG NGÀY", "TỔNG THÁNG")
TOPPING_PREFIX = "topping "
INLINE_TOPPING = re.compile(r"^(?P<mon>.+?) \+ (?:(?P<parts>\d+) )?(?P<topping>.+?) \((?P<money>[\d.,]+)đ\)$")
SIZE_SUFFIX = re.compile(r"\((?P<size>[ml])\)$", re.IGNORECASE)


def strip_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    without_marks = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", without_marks).replace("đ", "d").replace("Đ", "D")


def ident(value: Any) -> str:
    """Khoá nhận dạng bỏ dấu, bỏ hoa thường, bỏ khoảng trắng lặp — rulebook §8 tên gọi."""
    return strip_diacritics(squeeze(value)).casefold()


def item_key(value: Any) -> str:
    """Khoá mặt hàng: topping ghi inline và topping ghi dòng riêng là một mặt hàng — rulebook §6."""
    key = ident(value)
    if key.startswith(TOPPING_PREFIX):
        return key[len(TOPPING_PREFIX) :]
    return key


def is_walk_in(value: Any) -> bool:
    return ident(value) in WALK_IN_KEYS


class SaleLine(BaseModel):
    """Một dòng mặt hàng đã tách món khỏi topping, tiền và số lượng đã quy về đơn vị cơ bản."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    day: date
    status: str
    customer: str
    is_walk_in: bool
    item_key: str
    item_name: str
    base_unit: str
    base_quantity: float
    amount: int
    size: str


class ShopBook(BaseModel):
    """Toàn bộ sổ bán hàng dev_002 sau khi nối 17 file và tách topping."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    lines: tuple[SaleLine, ...]
    order_status: dict[str, str]
    order_day: dict[str, date]
    order_amount: dict[str, int]
    order_customer: dict[str, str]
    display_name: dict[str, str]
    first_day: date
    last_day: date


def _sales_files() -> tuple[Path, ...]:
    files = sorted(DATA_DIR.glob("BanHang_T*.xlsx"))
    if not files:
        raise ValueError("no sales files found")
    return tuple(files)


def _month_of_file(path: Path) -> tuple[int, int]:
    match = re.search(r"BanHang_T(\d{1,2})_(\d{4})\.xlsx$", path.name)
    if match is None:
        raise ValueError(f"cannot read month from file name: {path.name}")
    return int(match.group(2)), int(match.group(1))


def _read_conversions() -> dict[tuple[str, str], tuple[str, float]]:
    frame = read_table(DATA_DIR / CONVERSION_FILE, sheet=0, header_row=0)
    table: dict[tuple[str, str], tuple[str, float]] = {}
    for _, row in frame.iterrows():
        name = item_key(row["Tên sản phẩm"])
        big = ident(row["Đơn vị quy đổi"])
        factor = parse_number(row["Tỉ lệ quy đổi"])
        base = squeeze(row["Đơn vị cơ bản"])
        if factor is None or factor <= 0:
            raise ValueError(f"bad conversion factor for {name}")
        table[(name, big)] = (base, factor)
    return table


def _raw_body() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in _sales_files():
        frame = read_table(path, sheet=SALES_SHEET, header_row=HEADER_ROW)
        year, month = _month_of_file(path)
        frame = frame.assign(_year=year, _month=month)
        frames.append(frame)
    raw = pd.concat(frames, ignore_index=True)
    repeated_header = raw["Mã đơn hàng"].map(squeeze) == REPEATED_HEADER_MARK
    subtotal = raw["Mã đơn hàng"].isna()
    orphan_labels = {squeeze(v).split(" ")[0] + " " + squeeze(v).split(" ")[1] for v in raw.loc[subtotal, "Tên khách hàng"]}
    unexplained = [label for label in orphan_labels if not any(label.startswith(known) for known in SUBTOTAL_LABELS)]
    if unexplained:
        raise ValueError(f"unexplained rows without order id: {unexplained}")
    return raw[~repeated_header & ~subtotal].reset_index(drop=True)


def _resolve_base(name_key: str, unit: str, quantity: float, conversions: dict[tuple[str, str], tuple[str, float]]) -> tuple[str, float]:
    found = conversions.get((name_key, ident(unit)))
    if found is None:
        return squeeze(unit), quantity
    base, factor = found
    return base, quantity * factor


def _size_of(name: str) -> str:
    match = SIZE_SUFFIX.search(squeeze(name))
    return match.group("size").upper() if match else ""


def load_book() -> ShopBook:
    body = _raw_body()
    conversions = _read_conversions()
    lines: list[SaleLine] = []
    order_status: dict[str, str] = {}
    order_day: dict[str, date] = {}
    order_amount: dict[str, int] = {}
    order_customer: dict[str, str] = {}
    spelling_counts: dict[str, dict[str, int]] = {}
    for row in body.itertuples(index=False):
        values = dict(zip(body.columns, row))
        order_id = squeeze(values["Mã đơn hàng"])
        day = parse_date(values["Ngày đặt hàng"])
        if day is None:
            raise ValueError(f"unparsable order date on {order_id}")
        if day.year != values["_year"] or day.month != values["_month"]:
            raise ValueError(f"order {order_id} dated {day} sits in file for {values['_year']}-{values['_month']}")
        status = squeeze(values["Trạng thái đơn hàng"])
        customer = squeeze(values["Tên khách hàng"])
        raw_name = squeeze(values["Tên sản phẩm"])
        quantity = parse_number(values["Số lượng sản phẩm"])
        amount = parse_money(values["Tổng tiền"])
        if quantity is None or amount is None:
            raise ValueError(f"unparsable quantity or amount on {order_id}")
        if order_id in order_status and order_status[order_id] != status:
            raise ValueError(f"order {order_id} carries two statuses")
        order_status[order_id] = status
        order_day[order_id] = day
        order_customer[order_id] = customer
        order_amount[order_id] = order_amount.get(order_id, 0) + amount

        inline = INLINE_TOPPING.match(raw_name)
        if inline is None:
            dish_name, dish_amount = raw_name, amount
            topping: tuple[str, int, int] | None = None
        else:
            dish_name = squeeze(inline.group("mon"))
            topping_money = parse_money(inline.group("money"))
            if topping_money is None:
                raise ValueError(f"unparsable topping money on {order_id}")
            parts = int(inline.group("parts") or 1)
            dish_amount = amount - topping_money
            topping = (squeeze(inline.group("topping")), parts, topping_money)

        dish_key = item_key(dish_name)
        base_unit, base_quantity = _resolve_base(dish_key, values["Đơn vị tính"], quantity, conversions)
        spelling_counts.setdefault(dish_key, {}).setdefault(dish_name, 0)
        spelling_counts[dish_key][dish_name] += 1
        lines.append(
            SaleLine(
                order_id=order_id,
                day=day,
                status=status,
                customer=customer,
                is_walk_in=is_walk_in(customer),
                item_key=dish_key,
                item_name=dish_name,
                base_unit=base_unit,
                base_quantity=base_quantity,
                amount=dish_amount,
                size=_size_of(dish_name),
            )
        )
        if topping is not None:
            topping_name, parts, topping_money = topping
            lines.append(
                SaleLine(
                    order_id=order_id,
                    day=day,
                    status=status,
                    customer=customer,
                    is_walk_in=is_walk_in(customer),
                    item_key=item_key(topping_name),
                    item_name=topping_name,
                    base_unit="phần",
                    base_quantity=float(parts),
                    amount=topping_money,
                    size="",
                )
            )
    display: dict[str, str] = {}
    for key, counts in spelling_counts.items():
        display[key] = max(sorted(counts), key=lambda name: (counts[name], _accent_score(name)))
    days = [line.day for line in lines]
    return ShopBook(
        lines=tuple(lines),
        order_status=order_status,
        order_day=order_day,
        order_amount=order_amount,
        order_customer=order_customer,
        display_name=display,
        first_day=min(days),
        last_day=max(days),
    )


def _accent_score(name: str) -> int:
    return sum(1 for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) == "Mn")


def revenue_orders(book: ShopBook, start: date, end: date) -> tuple[str, ...]:
    """Rulebook §1: đơn tính vào doanh thu là đơn không huỷ, không trả hàng; đơn đang giao vẫn tính."""
    return tuple(
        sorted(
            order_id
            for order_id, day in book.order_day.items()
            if start <= day <= end and book.order_status[order_id] in REVENUE_STATUSES
        )
    )


def orders_in_period(book: ShopBook, start: date, end: date) -> tuple[str, ...]:
    return tuple(sorted(order_id for order_id, day in book.order_day.items() if start <= day <= end))


def revenue(book: ShopBook, start: date, end: date) -> int:
    return sum(book.order_amount[order_id] for order_id in revenue_orders(book, start, end))


def order_count(book: ShopBook, start: date, end: date) -> int:
    return len(revenue_orders(book, start, end))


def cancelled_count(book: ShopBook, start: date, end: date) -> int:
    return sum(1 for order_id in orders_in_period(book, start, end) if book.order_status[order_id] == CANCELLED_STATUS)


def cancel_rate_percent(book: ShopBook, start: date, end: date) -> float:
    total = len(orders_in_period(book, start, end))
    if total == 0:
        raise ValueError(f"no order in period {start}..{end}")
    return 100.0 * cancelled_count(book, start, end) / total


def average_order_value(book: ShopBook, start: date, end: date) -> int:
    count = order_count(book, start, end)
    if count == 0:
        raise ValueError(f"no revenue order in period {start}..{end}")
    return fmt.money(revenue(book, start, end) / count)


def percent_change(current: float, previous: float) -> float:
    if previous == 0:
        raise ValueError("previous period is zero")
    return 100.0 * (current - previous) / previous


def revenue_lines(book: ShopBook, start: date, end: date) -> tuple[SaleLine, ...]:
    return tuple(line for line in book.lines if start <= line.day <= end and line.status in REVENUE_STATUSES)


def quantity_by_item(book: ShopBook, start: date, end: date) -> dict[str, float]:
    totals: dict[str, float] = {}
    for line in revenue_lines(book, start, end):
        totals[line.item_key] = totals.get(line.item_key, 0.0) + line.base_quantity
    return totals


def top_items_by_quantity(book: ShopBook, start: date, end: date, k: int) -> tuple[str, ...]:
    """Rulebook §3: bán chạy theo số lượng quy về đơn vị cơ bản, bằng nhau thì theo tên tăng dần."""
    totals = quantity_by_item(book, start, end)
    ranked = sorted(totals.items(), key=lambda pair: (-pair[1], book.display_name[pair[0]]))
    return tuple(book.display_name[key] for key, _ in ranked[:k])


def quantity_of_item(book: ShopBook, start: date, end: date, name: str) -> float:
    key = item_key(name)
    if key not in book.display_name:
        raise ValueError(f"unknown item: {name}")
    return quantity_by_item(book, start, end).get(key, 0.0)


def quantity_by_size(book: ShopBook, start: date, end: date, size: str, unit: str) -> float:
    """Rulebook §6 Cà phê: size M, L là món có tên kết thúc bằng (M) hoặc (L), không phân biệt hoa thường."""
    return sum(line.base_quantity for line in revenue_lines(book, start, end) if line.size == size and line.base_unit == unit)


def revenue_by_day(book: ShopBook, start: date, end: date) -> dict[date, int]:
    totals: dict[date, int] = {}
    for order_id in revenue_orders(book, start, end):
        day = book.order_day[order_id]
        totals[day] = totals.get(day, 0) + book.order_amount[order_id]
    return totals


def best_revenue_day(book: ShopBook, start: date, end: date) -> date:
    totals = revenue_by_day(book, start, end)
    if not totals:
        raise ValueError(f"no revenue in period {start}..{end}")
    return min(totals, key=lambda day: (-totals[day], day))


def _named_customer_orders(book: ShopBook, start: date, end: date) -> dict[str, list[str]]:
    """Rulebook §3: shop không có mã khách thì xác định khách theo tên; đơn khách lẻ không tính."""
    grouped: dict[str, list[str]] = {}
    for order_id in revenue_orders(book, start, end):
        customer = book.order_customer[order_id]
        if is_walk_in(customer):
            continue
        grouped.setdefault(ident(customer), []).append(order_id)
    return grouped


def _customer_display(book: ShopBook, key: str, orders: Sequence[str]) -> str:
    spellings = sorted({book.order_customer[order_id] for order_id in orders})
    return max(spellings, key=lambda name: (_accent_score(name), name))


def top_customers_by_revenue(book: ShopBook, start: date, end: date, k: int) -> tuple[str, ...]:
    grouped = _named_customer_orders(book, start, end)
    scored = [
        (key, sum(book.order_amount[order_id] for order_id in orders), _customer_display(book, key, orders))
        for key, orders in grouped.items()
    ]
    ranked = sorted(scored, key=lambda row: (-row[1], row[2]))
    return tuple(row[2] for row in ranked[:k])


def most_loyal_customer(book: ShopBook, start: date, end: date) -> str:
    """Rulebook §3: khách trung thành nhất là khách có nhiều ngày có mua nhất trong kỳ."""
    grouped = _named_customer_orders(book, start, end)
    scored = [
        (len({book.order_day[order_id] for order_id in orders}), _customer_display(book, key, orders))
        for key, orders in grouped.items()
    ]
    if not scored:
        raise ValueError(f"no named customer in period {start}..{end}")
    return min(scored, key=lambda row: (-row[0], row[1]))[1]


NO_ITEM_GROUP_COLUMN = "so ban hang cua shop khong co cot nhom hang, khong co danh muc san pham ghi nhom; rulebook §3 lay nhom hang theo cot nhom hang"


def build_answers(book: ShopBook) -> tuple[dict[str, Any], ...]:
    questions = fmt.load_questions(QUESTIONS_PATH)
    out: list[dict[str, Any]] = []
    for question in questions:
        qid = question["id"]
        clock = Clock(question["as_of_date"])
        out.append(_answer_one(book, clock, qid))
    if len(out) != len(questions):
        raise ValueError("answer count does not match question count")
    return tuple(out)


def _month(book: ShopBook, clock: Clock, month: int, year: int) -> tuple[date, date]:
    period = clock.month(month, year)
    return period.start, min(period.end, clock.as_of)


def _answer_one(book: ShopBook, clock: Clock, qid: str) -> dict[str, Any]:
    if qid in ("q_008fdebb6ec9", "q_459109bda652", "q_ae10c252dc7a"):
        return fmt.answer_line(qid, "unanswerable", reason=NO_ITEM_GROUP_COLUMN)

    if qid == "q_00bf8df3ea0b":
        day = clock.today()
        return fmt.answer_line(qid, "number", fmt.money(revenue(book, day.start, day.end)))
    if qid == "q_f4e0630ebcb1":
        day = clock.today()
        return fmt.answer_line(qid, "number", fmt.money(revenue(book, day.start, day.end)))
    if qid in ("q_1f1a1f45b377", "q_61cfc26159fa", "q_c120861e5dd1"):
        day = clock.yesterday()
        return fmt.answer_line(qid, "number", fmt.money(revenue(book, day.start, day.end)))
    if qid == "q_03bbdfa6e0d5":
        day = clock.today()
        return fmt.answer_line(qid, "number", fmt.count(order_count(book, day.start, day.end)))
    if qid in ("q_585664a97754", "q_663c209f7209"):
        day = clock.yesterday()
        return fmt.answer_line(qid, "number", fmt.count(order_count(book, day.start, day.end)))

    if qid == "q_7616f1a1f0ee":
        start, end = _month(book, clock, 1, 2026)
        return fmt.answer_line(qid, "number", fmt.money(revenue(book, start, end)))
    if qid == "q_dbb084b9361d":
        start, end = _month(book, clock, 5, 2025)
        return fmt.answer_line(qid, "number", fmt.money(revenue(book, start, end)))
    if qid == "q_fe5788dae82e":
        start, end = _month(book, clock, 12, 2025)
        return fmt.answer_line(qid, "number", fmt.money(revenue(book, start, end)))

    if qid == "q_040d437fdf09":
        start, end = _month(book, clock, 1, 2025)
        return fmt.answer_line(qid, "number", average_order_value(book, start, end))
    if qid == "q_04e55a8f8c0c":
        start, end = _month(book, clock, 6, 2025)
        return fmt.answer_line(qid, "number", average_order_value(book, start, end))
    if qid == "q_363b113bf3bd":
        start, end = _month(book, clock, 11, 2025)
        return fmt.answer_line(qid, "number", average_order_value(book, start, end))

    if qid == "q_0ac818a0f5f2":
        start, end = _month(book, clock, 2, 2026)
        return fmt.answer_line(qid, "percent", fmt.percent(cancel_rate_percent(book, start, end)))
    if qid == "q_5896bf2cce00":
        start, end = _month(book, clock, 4, 2025)
        return fmt.answer_line(qid, "percent", fmt.percent(cancel_rate_percent(book, start, end)))
    if qid == "q_c2ba3823e50f":
        start, end = _month(book, clock, 2, 2025)
        return fmt.answer_line(qid, "percent", fmt.percent(cancel_rate_percent(book, start, end)))

    if qid == "q_0c62d2078959":
        start, end = _month(book, clock, 6, 2025)
        return fmt.answer_line(qid, "number", fmt.count(cancelled_count(book, start, end)))
    if qid == "q_e6c703f05070":
        start, end = _month(book, clock, 4, 2025)
        return fmt.answer_line(qid, "number", fmt.count(cancelled_count(book, start, end)))
    if qid == "q_e76cb855b50c":
        start, end = _month(book, clock, 2, 2025)
        return fmt.answer_line(qid, "number", fmt.count(cancelled_count(book, start, end)))

    if qid == "q_2ac539902fe6":
        now = _month(book, clock, 2, 2026)
        before = _month(book, clock, 2, 2025)
        return fmt.answer_line(qid, "percent", fmt.percent(percent_change(revenue(book, *now), revenue(book, *before))))
    if qid == "q_2ed4740ec705":
        now = _month(book, clock, 3, 2026)
        before = _month(book, clock, 3, 2025)
        return fmt.answer_line(qid, "percent", fmt.percent(percent_change(revenue(book, *now), revenue(book, *before))))
    if qid == "q_a79c3c340077":
        now = _month(book, clock, 4, 2026)
        before = _month(book, clock, 4, 2025)
        return fmt.answer_line(qid, "percent", fmt.percent(percent_change(revenue(book, *now), revenue(book, *before))))
    if qid == "q_45cb42f4dc7b":
        now = _month(book, clock, 8, 2025)
        before = _month(book, clock, 7, 2025)
        return fmt.answer_line(qid, "percent", fmt.percent(percent_change(revenue(book, *now), revenue(book, *before))))
    if qid == "q_4ef479fd4803":
        now = _month(book, clock, 10, 2025)
        before = _month(book, clock, 9, 2025)
        return fmt.answer_line(qid, "percent", fmt.percent(percent_change(revenue(book, *now), revenue(book, *before))))
    if qid == "q_d857fdab9c0a":
        now = _month(book, clock, 4, 2026)
        before = _month(book, clock, 3, 2026)
        return fmt.answer_line(qid, "percent", fmt.percent(percent_change(revenue(book, *now), revenue(book, *before))))

    if qid == "q_4847f9b75280":
        start, end = _month(book, clock, 11, 2025)
        return fmt.answer_line(qid, "date", fmt.day_answer(best_revenue_day(book, start, end)))
    if qid == "q_f118a00dc479":
        start, end = _month(book, clock, 7, 2025)
        return fmt.answer_line(qid, "date", fmt.day_answer(best_revenue_day(book, start, end)))

    if qid == "q_54bbf080f0cd":
        start, end = _month(book, clock, 6, 2025)
        return fmt.answer_line(qid, "list", list(top_items_by_quantity(book, start, end, 3)))
    if qid == "q_a77ff9dcc3e7":
        start, end = _month(book, clock, 10, 2025)
        return fmt.answer_line(qid, "list", list(top_items_by_quantity(book, start, end, 3)))

    if qid == "q_0ef28ee17f12":
        start, end = _month(book, clock, 3, 2025)
        return fmt.answer_line(qid, "number", fmt.quantity(quantity_of_item(book, start, end, "Nước ép cam (M)")))
    if qid == "q_b2bbe9c1e9fc":
        start, end = _month(book, clock, 2, 2025)
        return fmt.answer_line(qid, "number", fmt.quantity(quantity_of_item(book, start, end, "Cà phê sữa (M)")))
    if qid == "q_dec759a2f085":
        start, end = _month(book, clock, 4, 2026)
        return fmt.answer_line(qid, "number", fmt.quantity(quantity_of_item(book, start, end, "Latte (M)")))

    if qid == "q_c64c6d29f583":
        period = clock.this_month()
        return fmt.answer_line(qid, "number", fmt.quantity(quantity_by_size(book, period.start, period.end, "M", "ly")))
    if qid == "q_cfcb5f8a241f":
        period = clock.this_month()
        return fmt.answer_line(qid, "number", fmt.quantity(quantity_by_size(book, period.start, period.end, "L", "ly")))

    if qid == "q_9b5377726889":
        period = clock.quarter(2, 2025)
        return fmt.answer_line(qid, "number", fmt.count(order_count(book, period.start, min(period.end, clock.as_of))))

    if qid == "q_735ea0888aab":
        start, end = _month(book, clock, 3, 2025)
        return fmt.answer_line(qid, "string", most_loyal_customer(book, start, end))
    if qid == "q_ede70b7f6c13":
        start, end = _month(book, clock, 9, 2025)
        return fmt.answer_line(qid, "list", list(top_customers_by_revenue(book, start, end, 3)))

    raise ValueError(f"no rule for question: {qid}")


def main() -> None:
    book = load_book()
    lines = build_answers(book)
    written = fmt.write_answers(ANSWERS_PATH, lines)
    print(f"{SHOP}: wrote {written} answers to {ANSWERS_PATH}")


if __name__ == "__main__":
    main()
