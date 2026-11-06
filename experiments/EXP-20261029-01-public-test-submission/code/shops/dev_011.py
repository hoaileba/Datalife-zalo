from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

CODE_ROOT = Path("/Users/lebahoai/Workspace/zalo/2026/experiments/EXP-20261029-01-public-test-submission/code")
EXP_ROOT = CODE_ROOT.parent
DATA_DIR = Path("/Users/lebahoai/Workspace/zalo/2026/public_test/data/dev_011")
BOOK = DATA_DIR / "SoBanHang.xlsx"
QUESTIONS = DATA_DIR / "questions.jsonl"
ANSWERS = EXP_ROOT / "out" / "answers" / "dev_011.jsonl"

SHEET_CATALOG = "Ghi tắt"
SHEET_SALES = "Sổ bán hàng"

RETURN_MARKERS = ("trả lại", "mang trả", "trả hàng", "hoàn")
CANCEL_MARKERS = ("huỷ", "hủy")
SHIPPING_MARKERS = ("đang giao", "chờ giao", "giao sau")

LOAI_MAY = ("máy mới", "máy cũ")
CAPACITY = re.compile(r"\s+\d+\s*GB\b", re.IGNORECASE)

sys.path.insert(0, str(CODE_ROOT))

from pydantic import BaseModel, ConfigDict  # noqa: E402

from datamate import Clock, fmt, name_key, parse_date, parse_money, parse_number, squeeze  # noqa: E402
from datamate.periods import Period  # noqa: E402
from datamate.tabio import read_table  # noqa: E402


class Item(BaseModel):
    """Một mặt hàng trong danh mục: tên đầy đủ, loại hàng, dòng máy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    full_name: str
    loai: str
    dong_may: str


class Line(BaseModel):
    """Một dòng hàng của một đơn trong sổ bán hàng."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item: Item
    quantity: float
    unit_price: int
    amount: int


class Order(BaseModel):
    """Một hoá đơn: ngày, khách, các dòng hàng và các khoản của cả đơn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stt: int
    day: date
    customer: str
    note: str
    discount: int
    trade_in: int
    customer_paid: int
    lines: tuple[Line, ...]

    @property
    def status(self) -> str:
        low = name_key(self.note)
        if any(marker in low for marker in CANCEL_MARKERS):
            return "huỷ"
        if any(marker in low for marker in RETURN_MARKERS):
            return "trả hàng"
        if any(marker in low for marker in SHIPPING_MARKERS):
            return "đang giao"
        return "hoàn thành"

    @property
    def counts_as_sale(self) -> bool:
        return self.status in ("hoàn thành", "đang giao")

    @property
    def revenue(self) -> int:
        return sum(line.amount for line in self.lines)


def dong_may_of(full_name: str) -> str:
    match = CAPACITY.search(full_name)
    return full_name[: match.start()].strip() if match is not None else full_name.strip()


def load_catalog() -> dict[str, Item]:
    frame = read_table(BOOK, sheet=SHEET_CATALOG)
    catalog: dict[str, Item] = {}
    for _, row in frame.iterrows():
        full_name = squeeze(row["Tên hàng"])
        loai = squeeze(row["Loại"])
        if full_name == "" or loai == "":
            raise ValueError(f"catalog row without name or loai: {dict(row)}")
        item = Item(full_name=full_name, loai=loai, dong_may=dong_may_of(full_name))
        for key in (squeeze(row["Ghi tắt"]), full_name):
            if key == "":
                raise ValueError(f"catalog row without key: {dict(row)}")
            catalog[name_key(key)] = item
    return catalog


def load_orders() -> tuple[Order, ...]:
    catalog = load_catalog()
    frame = read_table(BOOK, sheet=SHEET_SALES)
    groups: dict[int, dict[str, Any]] = {}
    current: int | None = None
    for _, row in frame.iterrows():
        stt = parse_number(row["STT"])
        day = parse_date(row["Ngày"])
        if day is None:
            raise ValueError(f"sales row without date: {dict(row)}")
        if stt is not None:
            current = int(stt)
            if current in groups:
                raise ValueError(f"duplicate order number: {current}")
            groups[current] = {
                "stt": current,
                "day": day,
                "customer": squeeze(row["Khách"]),
                "note": squeeze(row["Ghi chú"]),
                "discount": parse_money(row["Bớt"], default=0),
                "trade_in": parse_money(row["Thu máy cũ"], default=0),
                "customer_paid": parse_money(row["Khách trả"], default=0),
                "lines": [],
            }
        if current is None:
            raise ValueError(f"sales row before any order number: {dict(row)}")
        key = name_key(row["Hàng"])
        if key not in catalog:
            raise ValueError(f"unknown item name: {squeeze(row['Hàng'])}")
        quantity = parse_number(row["SL"])
        amount = parse_money(row["Thành tiền"])
        unit_price = parse_money(row["Giá"])
        if quantity is None or amount is None or unit_price is None:
            raise ValueError(f"sales row with unreadable numbers: {dict(row)}")
        groups[current]["lines"].append(Line(item=catalog[key], quantity=quantity, unit_price=unit_price, amount=amount))
    orders = []
    for payload in groups.values():
        payload["lines"] = tuple(payload["lines"])
        orders.append(Order(**payload))
    return tuple(orders)


class Book:
    """Sổ bán hàng dev_011 đã ingest, cùng mọi phép đo rulebook áp lên nó."""

    def __init__(self, orders: tuple[Order, ...]) -> None:
        if not orders:
            raise ValueError("empty sales book")
        self.orders = orders
        self.first_day = min(order.day for order in orders)
        self.last_day = max(order.day for order in orders)

    def in_period(self, period: Period, as_of: date, *, sales_only: bool = True) -> tuple[Order, ...]:
        return tuple(
            order
            for order in self.orders
            if period.contains(order.day) and order.day <= as_of and (order.counts_as_sale or not sales_only)
        )

    def doanh_thu(self, period: Period, as_of: date) -> int:
        return sum(order.revenue for order in self.in_period(period, as_of))

    def so_don(self, period: Period, as_of: date) -> int:
        return len(self.in_period(period, as_of))

    def khach_phai_tra(self, period: Period, as_of: date) -> int:
        return sum(order.customer_paid for order in self.in_period(period, as_of))

    def thu_may_cu(self, period: Period, as_of: date) -> int:
        return sum(order.trade_in for order in self.in_period(period, as_of))

    def so_may_ban(self, period: Period, as_of: date, *, loai: tuple[str, ...] = LOAI_MAY) -> float:
        return sum(
            line.quantity
            for order in self.in_period(period, as_of)
            for line in order.lines
            if line.item.loai in loai
        )

    def so_luong_dong_may(self, period: Period, as_of: date, dong: str) -> float:
        target = name_key(dong)
        return sum(
            line.quantity
            for order in self.in_period(period, as_of)
            for line in order.lines
            if line.item.loai in LOAI_MAY and name_key(line.item.dong_may) == target
        )

    def so_luong_mat_hang(self, period: Period, as_of: date, full_name: str) -> float:
        target = name_key(full_name)
        return sum(
            line.quantity
            for order in self.in_period(period, as_of)
            for line in order.lines
            if name_key(line.item.full_name) == target
        )

    def tien_mat_hang(self, period: Period, as_of: date, full_name: str) -> int:
        target = name_key(full_name)
        return sum(
            line.amount
            for order in self.in_period(period, as_of)
            for line in order.lines
            if name_key(line.item.full_name) == target
        )

    def doanh_thu_nhom(self, period: Period, as_of: date, loai: str) -> int:
        return sum(
            line.amount
            for order in self.in_period(period, as_of)
            for line in order.lines
            if line.item.loai == loai
        )

    def doanh_thu_theo_ngay(self, period: Period, as_of: date) -> tuple[tuple[date, int], ...]:
        buckets: dict[date, int] = defaultdict(int)
        for order in self.in_period(period, as_of):
            buckets[order.day] += order.revenue
        return tuple(sorted(buckets.items(), key=lambda pair: (-pair[1], pair[0])))

    def ban_chay(self, period: Period, as_of: date) -> tuple[tuple[str, float], ...]:
        buckets: dict[str, float] = defaultdict(float)
        for order in self.in_period(period, as_of):
            for line in order.lines:
                buckets[line.item.full_name] += line.quantity
        return tuple(sorted(buckets.items(), key=lambda pair: (-pair[1], name_key(pair[0]))))

    def status_counts(self) -> Counter[str]:
        return Counter(order.status for order in self.orders)


def build_answers(book: Book) -> tuple[dict[str, Any], ...]:
    questions = {row["id"]: row for row in fmt.load_questions(QUESTIONS)}
    out: list[dict[str, Any]] = []

    def clock(qid: str) -> Clock:
        return Clock(questions[qid]["as_of_date"])

    def as_of(qid: str) -> date:
        return clock(qid).as_of

    def money_line(qid: str, period: Period) -> dict[str, Any]:
        return fmt.answer_line(qid, "number", fmt.money(book.doanh_thu(period, as_of(qid))))

    def order_count_line(qid: str, period: Period) -> dict[str, Any]:
        return fmt.answer_line(qid, "number", fmt.count(book.so_don(period, as_of(qid))))

    out.append(order_count_line("q_0a3308eb76bb", clock("q_0a3308eb76bb").yesterday()))
    out.append(order_count_line("q_3ef55d803554", clock("q_3ef55d803554").yesterday()))
    out.append(order_count_line("q_622165f81458", clock("q_622165f81458").today()))
    out.append(order_count_line("q_8960949c2614", clock("q_8960949c2614").yesterday()))
    out.append(order_count_line("q_358aa8d56087", clock("q_358aa8d56087").quarter(4, 2025)))
    out.append(order_count_line("q_3766bf6cf1c6", clock("q_3766bf6cf1c6").quarter(1, 2026)))

    out.append(money_line("q_69a3f480bb53", clock("q_69a3f480bb53").yesterday()))
    out.append(money_line("q_e2a2674f8f4d", clock("q_e2a2674f8f4d").today()))
    out.append(money_line("q_ed841139ac0a", clock("q_ed841139ac0a").today()))
    out.append(money_line("q_ee860111a8df", clock("q_ee860111a8df").yesterday()))
    out.append(money_line("q_f0c8b2fbb77f", clock("q_f0c8b2fbb77f").yesterday()))
    out.append(money_line("q_4e7e3bde5a15", clock("q_4e7e3bde5a15").quarter(3, 2025)))
    out.append(money_line("q_bae86e8e80f2", clock("q_bae86e8e80f2").month(6, 2026)))
    out.append(money_line("q_e53ff8441ef1", clock("q_e53ff8441ef1").month(7, 2025)))
    out.append(money_line("q_e9bb51886662", clock("q_e9bb51886662").month(11, 2025)))

    out.append(
        fmt.answer_line(
            "q_1040545087b6", "number", fmt.money(book.thu_may_cu(clock("q_1040545087b6").this_month(), as_of("q_1040545087b6")))
        )
    )
    out.append(
        fmt.answer_line(
            "q_650a53225054", "number", fmt.money(book.thu_may_cu(clock("q_650a53225054").month(6, 2025), as_of("q_650a53225054")))
        )
    )
    out.append(
        fmt.answer_line(
            "q_701bf339bd9e", "number", fmt.money(book.thu_may_cu(clock("q_701bf339bd9e").month(11, 2025), as_of("q_701bf339bd9e")))
        )
    )

    out.append(
        fmt.answer_line(
            "q_5bfa542cd172", "number", fmt.money(book.khach_phai_tra(clock("q_5bfa542cd172").month(6, 2025), as_of("q_5bfa542cd172")))
        )
    )
    out.append(
        fmt.answer_line(
            "q_8db0ee0aa5d1", "number", fmt.money(book.khach_phai_tra(clock("q_8db0ee0aa5d1").this_month(), as_of("q_8db0ee0aa5d1")))
        )
    )
    out.append(
        fmt.answer_line(
            "q_edce3c50d4f7", "number", fmt.money(book.khach_phai_tra(clock("q_edce3c50d4f7").month(12, 2025), as_of("q_edce3c50d4f7")))
        )
    )

    out.append(
        fmt.answer_line(
            "q_51621c1657c5", "number", fmt.money(book.doanh_thu_nhom(clock("q_51621c1657c5").month(3, 2026), as_of("q_51621c1657c5"), "máy mới"))
        )
    )
    out.append(
        fmt.answer_line(
            "q_9f4af1e4fecd", "number", fmt.money(book.doanh_thu_nhom(clock("q_9f4af1e4fecd").month(6, 2025), as_of("q_9f4af1e4fecd"), "máy cũ"))
        )
    )
    out.append(
        fmt.answer_line(
            "q_f1772e835811", "number", fmt.money(book.doanh_thu_nhom(clock("q_f1772e835811").month(9, 2025), as_of("q_f1772e835811"), "phụ kiện"))
        )
    )

    out.append(
        fmt.answer_line(
            "q_8cb214a6bdcd", "number", fmt.count(book.so_may_ban(clock("q_8cb214a6bdcd").month(5, 2026), as_of("q_8cb214a6bdcd")))
        )
    )
    out.append(
        fmt.answer_line(
            "q_a29355405c06", "number", fmt.count(book.so_may_ban(clock("q_a29355405c06").month(6, 2025), as_of("q_a29355405c06")))
        )
    )
    out.append(
        fmt.answer_line(
            "q_d99e832f3190", "number", fmt.count(book.so_may_ban(clock("q_d99e832f3190").month(7, 2025), as_of("q_d99e832f3190")))
        )
    )
    out.append(
        fmt.answer_line(
            "q_97a88c5a5568",
            "number",
            fmt.count(book.so_may_ban(clock("q_97a88c5a5568").this_month(), as_of("q_97a88c5a5568"), loai=("máy cũ",))),
        )
    )
    out.append(
        fmt.answer_line(
            "q_a652f5fcb0fe",
            "number",
            fmt.count(book.so_may_ban(clock("q_a652f5fcb0fe").month(6, 2026), as_of("q_a652f5fcb0fe"), loai=("máy cũ",))),
        )
    )
    out.append(
        fmt.answer_line(
            "q_df258c67efec",
            "number",
            fmt.count(book.so_may_ban(clock("q_df258c67efec").month(4, 2026), as_of("q_df258c67efec"), loai=("máy cũ",))),
        )
    )

    out.append(
        fmt.answer_line(
            "q_12712b3cc328",
            "number",
            fmt.count(book.so_luong_dong_may(clock("q_12712b3cc328").this_month(), as_of("q_12712b3cc328"), "Xiaomi Redmi Note 14")),
        )
    )
    out.append(
        fmt.answer_line(
            "q_8a1878ffe6e6",
            "number",
            fmt.count(book.so_luong_dong_may(clock("q_8a1878ffe6e6").month(6, 2026), as_of("q_8a1878ffe6e6"), "Samsung Galaxy A56 5G")),
        )
    )
    out.append(
        fmt.answer_line(
            "q_d622b78573c8",
            "number",
            fmt.count(book.so_luong_dong_may(clock("q_d622b78573c8").this_month(), as_of("q_d622b78573c8"), "iPhone 16 Pro Max")),
        )
    )

    out.append(
        fmt.answer_line(
            "q_83e204622a9f",
            "number",
            fmt.money(book.tien_mat_hang(clock("q_83e204622a9f").month(7, 2026), as_of("q_83e204622a9f"), "Củ sạc nhanh 20W Type-C")),
        )
    )
    out.append(
        fmt.answer_line(
            "q_9ee4a6de0ca1",
            "number",
            fmt.money(book.tien_mat_hang(clock("q_9ee4a6de0ca1").month(1, 2026), as_of("q_9ee4a6de0ca1"), "Giá đỡ điện thoại để bàn")),
        )
    )
    out.append(
        fmt.answer_line(
            "q_c9afaa1f4f9e",
            "number",
            fmt.count(book.so_luong_mat_hang(clock("q_c9afaa1f4f9e").month(10, 2025), as_of("q_c9afaa1f4f9e"), "Thẻ nhớ microSD 64GB")),
        )
    )

    for qid, period in (
        ("q_30afaf6d51ca", clock("q_30afaf6d51ca").month(11, 2025)),
        ("q_c90bed5d2614", clock("q_c90bed5d2614").month(4, 2026)),
    ):
        ranked = book.doanh_thu_theo_ngay(period, as_of(qid))
        if not ranked:
            raise ValueError(f"no revenue day in period for {qid}")
        out.append(fmt.answer_line(qid, "date", fmt.day_answer(ranked[0][0])))

    for qid, period in (
        ("q_3176702f9d3e", clock("q_3176702f9d3e").month(1, 2026)),
        ("q_a85371a13fe2", clock("q_a85371a13fe2").month(7, 2026)),
    ):
        ranked = book.ban_chay(period, as_of(qid))
        if not ranked:
            raise ValueError(f"no item sold in period for {qid}")
        out.append(fmt.answer_line(qid, "string", ranked[0][0]))

    missing = set(questions) - {line["id"] for line in out}
    extra = {line["id"] for line in out} - set(questions)
    if missing or extra:
        raise ValueError(f"answer set mismatch, missing={sorted(missing)} extra={sorted(extra)}")
    order_in_file = list(questions)
    by_id = {line["id"]: line for line in out}
    return tuple(by_id[qid] for qid in order_in_file)


def main() -> None:
    book = Book(load_orders())
    lines = build_answers(book)
    written = fmt.write_answers(ANSWERS, lines)
    print(f"orders={len(book.orders)} range={book.first_day}..{book.last_day} status={dict(book.status_counts())}")
    print(f"written={written} questions={len(fmt.load_questions(QUESTIONS))}")


if __name__ == "__main__":
    main()
