from __future__ import annotations

import csv
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Callable

CODE_ROOT = Path("/Users/lebahoai/Workspace/zalo/2026/experiments/EXP-20261029-01-public-test-submission/code")
EXP_ROOT = CODE_ROOT.parent
DATA_DIR = Path("/Users/lebahoai/Workspace/zalo/2026/public_test/data/dev_009")
INVOICE_CSV = DATA_DIR / "danh_sach_hoa_don.csv"
QUESTIONS = DATA_DIR / "questions.jsonl"
ANSWERS_OUT = EXP_ROOT / "out" / "answers" / "dev_009.jsonl"

sys.path.insert(0, str(CODE_ROOT))

from datamate import Clock, Period, answer_line, fmt, load_questions, parse_datetime, parse_money, squeeze  # noqa: E402

SUBTOTAL_MARKER = "Tổng ngày"
EXCLUDED_FROM_REVENUE = frozenset({"hủy đơn", "trả hàng"})
CANCELLED = "hủy đơn"
RETURNED = "trả hàng"


class Invoice:
    """Một hoá đơn ở mức đơn của dev_009: ngày đặt, trạng thái, tiền hàng, tổng đơn, nợ."""

    __slots__ = ("code", "day", "status", "goods_value", "order_total", "debt", "paid", "partner")

    def __init__(
        self,
        *,
        code: str,
        day: date,
        status: str,
        goods_value: int,
        order_total: int,
        debt: int,
        paid: int,
        partner: str,
    ) -> None:
        self.code = code
        self.day = day
        self.status = status
        self.goods_value = goods_value
        self.order_total = order_total
        self.debt = debt
        self.paid = paid
        self.partner = partner

    @property
    def counts_as_revenue(self) -> bool:
        return self.status not in EXCLUDED_FROM_REVENUE


def read_invoices(path: Path = INVOICE_CSV) -> tuple[tuple[Invoice, ...], tuple[dict[str, Any], ...]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = tuple(csv.reader(handle))
    header = [squeeze(cell) for cell in rows[0]]
    expected = ["Ngày tháng", "Trạng thái đơn", "TongTien", "Mã hóa đơn", "Nợ", "Đã thu", "Đối tác", "Giá trị hàng"]
    if header != expected:
        raise ValueError(f"unexpected header: {header}")
    invoices: list[Invoice] = []
    subtotals: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for raw in rows[1:]:
        if len(raw) != len(expected):
            raise ValueError(f"row width {len(raw)} != {len(expected)}: {raw}")
        cells = tuple(squeeze(cell) for cell in raw)
        if cells[0] == "":
            if not cells[6].startswith(SUBTOTAL_MARKER):
                raise ValueError(f"row without date is not a subtotal marker: {cells}")
            subtotals.append(
                {
                    "label": cells[6],
                    "order_total": parse_money(cells[2]),
                    "paid": parse_money(cells[5]),
                    "goods_value": parse_money(cells[7]),
                }
            )
            continue
        if cells in seen:
            continue
        seen.add(cells)
        moment = parse_datetime(cells[0])
        if moment is None:
            raise ValueError(f"unparsable date: {cells[0]!r}")
        if cells[1] == "":
            raise ValueError(f"invoice without status: {cells}")
        invoices.append(
            Invoice(
                code=cells[3],
                day=moment.date(),
                status=cells[1],
                goods_value=parse_money(cells[7]),
                order_total=parse_money(cells[2]),
                debt=parse_money(cells[4]),
                paid=parse_money(cells[5]),
                partner=cells[6],
            )
        )
    return tuple(invoices), tuple(subtotals)


def revenue_in(invoices: tuple[Invoice, ...], period: Period, *, as_of: date) -> int:
    return fmt.money(
        sum(inv.goods_value for inv in invoices if inv.counts_as_revenue and period.contains(inv.day) and inv.day <= as_of)
    )


def order_count_in(invoices: tuple[Invoice, ...], period: Period, *, as_of: date) -> int:
    return fmt.count(
        sum(1 for inv in invoices if inv.counts_as_revenue and period.contains(inv.day) and inv.day <= as_of)
    )


def revenue_by_day(invoices: tuple[Invoice, ...], period: Period, *, as_of: date) -> dict[date, int]:
    totals: dict[date, int] = {}
    for inv in invoices:
        if not inv.counts_as_revenue or not period.contains(inv.day) or inv.day > as_of:
            continue
        totals[inv.day] = totals.get(inv.day, 0) + inv.goods_value
    return totals


def best_revenue_day(invoices: tuple[Invoice, ...], period: Period, *, as_of: date) -> date:
    totals = revenue_by_day(invoices, period, as_of=as_of)
    if not totals:
        raise ValueError(f"no revenue day in period {period}")
    best = max(totals.values())
    return min(day for day, value in totals.items() if value == best)


def data_span(invoices: tuple[Invoice, ...]) -> Period:
    days = [inv.day for inv in invoices]
    return Period(start=min(days), end=max(days), label="khoảng ngày dữ liệu")


def build_answers(invoices: tuple[Invoice, ...]) -> tuple[dict[str, Any], ...]:
    plan: dict[str, Callable[[Clock], tuple[str, Any]]] = {
        "q_0329c9711c55": lambda c: ("number", order_count_in(invoices, c.today(), as_of=c.as_of)),
        "q_0b0081426a17": lambda c: ("number", revenue_in(invoices, c.today(), as_of=c.as_of)),
        "q_0bac8c88238d": lambda c: ("number", revenue_in(invoices, c.yesterday(), as_of=c.as_of)),
        "q_128fd07d838e": lambda c: ("number", order_count_in(invoices, c.yesterday(), as_of=c.as_of)),
        "q_318e4b474262": lambda c: ("number", revenue_in(invoices, c.yesterday(), as_of=c.as_of)),
        "q_37a4aca072a6": lambda c: ("number", order_count_in(invoices, c.quarter(4, 2025), as_of=c.as_of)),
        "q_48469d4fc5d1": lambda c: ("date", fmt.day_answer(best_revenue_day(invoices, c.month(8, 2025), as_of=c.as_of))),
        "q_545c34b86eb0": lambda c: ("number", order_count_in(invoices, c.quarter(1, 2025), as_of=c.as_of)),
        "q_599dbed4790f": lambda c: ("number", order_count_in(invoices, c.yesterday(), as_of=c.as_of)),
        "q_5cb9576befc6": lambda c: ("number", revenue_in(invoices, c.month(5, 2025), as_of=c.as_of)),
        "q_66ee0467ce9e": lambda c: ("number", order_count_in(invoices, c.yesterday(), as_of=c.as_of)),
        "q_7dbd343490cd": lambda c: ("number", order_count_in(invoices, c.quarter(1, 2026), as_of=c.as_of)),
        "q_8620011d3670": lambda c: ("number", revenue_in(invoices, c.month(2, 2025), as_of=c.as_of)),
        "q_88aeb2f7b1a7": lambda c: ("number", revenue_in(invoices, c.yesterday(), as_of=c.as_of)),
        "q_a13017cca903": lambda c: ("number", revenue_in(invoices, c.quarter(1, 2026), as_of=c.as_of)),
        "q_acfd51bb9870": lambda c: ("number", revenue_in(invoices, c.today(), as_of=c.as_of)),
        "q_c04e8d3d46b0": lambda c: ("number", revenue_in(invoices, c.month(3, 2026), as_of=c.as_of)),
        "q_c4b294bc0479": lambda c: ("number", revenue_in(invoices, c.quarter(2, 2025), as_of=c.as_of)),
        "q_d29c19d6d13e": lambda c: ("number", revenue_in(invoices, c.quarter(1, 2025), as_of=c.as_of)),
        "q_dfe6c970b819": lambda c: ("date", fmt.day_answer(best_revenue_day(invoices, c.month(1, 2025), as_of=c.as_of))),
        "q_eb7f3881e7e9": lambda c: ("date", fmt.day_answer(best_revenue_day(invoices, c.month(6, 2025), as_of=c.as_of))),
    }
    questions = load_questions(QUESTIONS)
    if set(plan) != {q["id"] for q in questions}:
        raise ValueError("plan does not cover exactly the question ids")
    span = data_span(invoices)
    lines: list[dict[str, Any]] = []
    for question in questions:
        clock = Clock(question["as_of_date"])
        answer_type, value = plan[question["id"]](clock)
        lines.append(answer_line(question["id"], answer_type, value))
    if span.start > date(2025, 1, 1) or span.end < date(2026, 6, 24):
        raise ValueError(f"data span narrower than README claim: {span}")
    return tuple(lines)


def main() -> int:
    invoices, subtotals = read_invoices()
    if len(subtotals) != 540:
        raise ValueError(f"unexpected subtotal row count: {len(subtotals)}")
    status_mix = Counter(inv.status for inv in invoices)
    lines = build_answers(invoices)
    written = fmt.write_answers(ANSWERS_OUT, lines)
    print(f"invoices={len(invoices)} statuses={dict(status_mix)} span={data_span(invoices)} written={written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
