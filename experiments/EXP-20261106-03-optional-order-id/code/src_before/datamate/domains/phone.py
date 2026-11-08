from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from ..norm import fold_key, parse_datetime, parse_money
from ..periods import Period

PHONE_HELPERS = (
    "machines_sold", "top_machine_lines", "brand_share", "new_machine_share", "average_machine_price", "customer_payable", "average_customer_payable",
    "trade_in_total", "trade_in_order_share", "warranty_count", "warranty_rate", "warranted_machines", "warranty_top_line",
    "installment_remaining", "installment_overdue", "overdue_customers", "installments_due",
)


def machine_line(name: Any) -> str:
    words = str(name).split()
    capacity = next((index for index, word in enumerate(words) if fold_key(word).endswith("gb") and any(ch.isdigit() for ch in word)), None)
    return " ".join(words[:capacity]) if capacity else str(name)


def machine_brand(name: Any) -> str:
    first = str(name).split()[0] if str(name).split() else ""
    return "Apple" if fold_key(first) == "iphone" else first


def machine_kind(kind: str) -> str:
    key = fold_key(kind)
    return key if key.startswith("may ") else f"may {key}"


def _money(value: Any) -> int:
    return parse_money(value, default=0) or 0


def _day(value: Any) -> pd.Timestamp | None:
    moment = parse_datetime(value)
    return None if moment is None else pd.Timestamp(moment).normalize()


class PhoneMixin:
    """Máy bán theo dòng và hãng, thu máy cũ, bảo hành, trả góp, đọc qua khái niệm."""

    def _machine_rows(self, period: Period, *, kinds: tuple[str, ...] = ("may moi", "may cu")) -> pd.DataFrame:
        self._book("machine_id")
        rows = self._sold(period, None, {})
        return rows[rows["item_group"].map(lambda cell: fold_key(str(cell)) in kinds)]

    def machines_sold(self, period: Period, *, line: str | None = None, brand: str | None = None, kind: str | None = None) -> int:
        """Số máy bán trong kỳ, lọc theo dòng máy, hãng, hoặc loại `máy mới`, `máy cũ`; không gồm phụ kiện."""
        rows = self._machine_rows(period, kinds=(machine_kind(kind),) if kind else ("may moi", "may cu"))
        if line is not None:
            rows = rows[rows["item_name"].map(lambda name: fold_key(machine_line(name)) == fold_key(line))]
        if brand is not None:
            rows = rows[rows["item_name"].map(lambda name: fold_key(machine_brand(name)) == fold_key(brand))]
        return int(rows["quantity"].sum())

    def top_machine_lines(self, period: Period, *, count: int = 1) -> list[str]:
        """Dòng máy bán nhiều máy nhất, giảm dần, bằng nhau theo tên."""
        rows = self._machine_rows(period)
        totals = rows.groupby(rows["item_name"].map(machine_line))["quantity"].sum()
        ranked = pd.DataFrame({"value": totals, "tie": totals.index}).sort_values(["value", "tie"], ascending=[False, True])
        return ranked.index[:count].tolist()

    def brand_share(self, period: Period, brand: str) -> float:
        """Phần trăm số máy của một hãng trên tổng số máy bán."""
        return round(100 * self.machines_sold(period, brand=brand) / self.machines_sold(period), 2)

    def new_machine_share(self, period: Period) -> float:
        """Phần trăm tiền máy mới trên tổng tiền bán máy, không gồm phụ kiện."""
        rows = self._machine_rows(period)
        fresh = rows[rows["item_group"].map(lambda cell: fold_key(str(cell)) == "may moi")]
        return round(100 * fresh["line_amount"].sum() / rows["line_amount"].sum(), 2)

    def average_machine_price(self, period: Period) -> int:
        """Tiền bán máy chia số máy, không gồm phụ kiện."""
        rows = self._machine_rows(period)
        return int(rows["line_amount"].sum() / rows["quantity"].sum() + 0.5)

    def _sold_orders_first(self, period: Period) -> pd.DataFrame:
        return self._sold(period, None, {}).drop_duplicates("order_id")

    def customer_payable(self, period: Period) -> int:
        """Tổng khách phải trả của đơn không huỷ, không trả, sau bớt và sau trừ máy cũ."""
        return int(self._sold_orders_first(period)["paid_amount"].map(_money).sum())

    def average_customer_payable(self, period: Period) -> int:
        """Khách phải trả bình quân một đơn."""
        orders = self._sold_orders_first(period)
        return int(orders["paid_amount"].map(_money).sum() / len(orders) + 0.5)

    def _trade_in_ids(self, column: pd.Series) -> pd.Series:
        return column.map(lambda cell: None if pd.isna(cell) else str(cell).removesuffix(".0"))

    def trade_in_total(self, period: Period) -> int:
        """Tổng tiền thu máy cũ của các đơn trong kỳ, đơn không huỷ, không trả."""
        orders = self._sold_orders_first(period)
        if self._has_concepts("trade_in_order", "trade_in_amount"):
            book = self._book("trade_in_order", "trade_in_amount")
            kept = self._trade_in_ids(book["trade_in_order"]).isin(set(self._trade_in_ids(orders["order_id"])))
            return int(book.loc[kept, "trade_in_amount"].map(_money).sum())
        column = self._column_of("trade_in_amount", orders)
        return int(orders[column].map(_money).sum())

    def trade_in_order_share(self, period: Period) -> float:
        """Phần trăm số đơn có thu máy cũ trên tổng số đơn trong kỳ."""
        orders = self._sold_orders_first(period)
        if self._has_concepts("trade_in_order", "trade_in_amount"):
            ids = set(self._trade_in_ids(self._book("trade_in_order", "trade_in_amount")["trade_in_order"]))
            hits = self._trade_in_ids(orders["order_id"]).isin(ids).sum()
        else:
            hits = (orders[self._column_of("trade_in_amount", orders)].map(_money) > 0).sum()
        return round(100 * hits / len(orders), 2)

    def _warranty(self) -> pd.DataFrame:
        book = self._book("warranty_fault", "machine_id")
        return book.assign(day=pd.to_datetime(book["record_date"], errors="coerce").dt.normalize())

    def _warranty_in(self, period: Period) -> pd.DataFrame:
        book = self._warranty()
        return book[(book["day"] >= pd.Timestamp(period.start)) & (book["day"] <= pd.Timestamp(period.end))]

    def warranty_count(self, period: Period) -> int:
        """Số lượt bảo hành có ngày nhận trong kỳ."""
        return len(self._warranty_in(period))

    def warranty_rate(self, period: Period) -> float:
        """Tỉ lệ bảo hành: số lượt trong kỳ chia số máy bán trong kỳ."""
        return round(100 * self.warranty_count(period) / self.machines_sold(period), 2)

    def warranted_machines(self, period: Period) -> int:
        """Số máy bán trong kỳ đã mang tới bảo hành ít nhất một lần tính đến hôm nay."""
        rows = self._machine_rows(period)
        column = self._column_of("machine_id", rows)
        sold = {part.strip() for cell in rows[column].dropna() for part in str(cell).split("/")}
        seen = set(self._warranty()["machine_id"].astype(str).str.strip())
        return len(sold & seen)

    def warranty_top_line(self, period: Period) -> str:
        """Dòng máy có nhiều lượt bảo hành nhất trong kỳ."""
        return self._warranty_in(period)["item_name"].value_counts().index[0]

    def _contracts(self, limit: pd.Timestamp) -> tuple[dict[str, Any], ...]:
        book = self._book("installment_terms", "installment_monthly", "installment_due_day", "installment_prepaid", "installment_paid_date", "installment_paid")
        out = []
        for order_id, rows in book.groupby("order_id", sort=False):
            head = rows.iloc[0]
            if pd.isna(head["order_date"]):
                continue
            bought = pd.Timestamp(head["order_date"]).normalize()
            if bought > limit:
                continue
            paid = [(_day(day), _money(amount)) for day, amount in zip(rows["installment_paid_date"], rows["installment_paid"])]
            out.append({
                "order_id": order_id,
                "bought": bought,
                "customer": str(head["customer_name"]),
                "total": _money(head["unit_price"]) - _money(head["installment_prepaid"]),
                "monthly": _money(head["installment_monthly"]),
                "dues": _due_dates(bought, terms=int(float(head["installment_terms"])), day=int(float(head["installment_due_day"]))),
                "paid": sum(amount for day, amount in paid if day is not None and day <= limit),
            })
        return tuple(out)

    def _limit(self, day: str | date | Period | None) -> pd.Timestamp:
        return pd.Timestamp(day.end if isinstance(day, Period) else day if day is not None else self.clock.as_of)

    def installment_remaining(self, day: str | date | None = None, *, customer: str | None = None) -> int:
        """Tiền góp chưa trả lúc hết ngày, tính cả kỳ chưa tới hạn."""
        contracts = self._contracts(self._limit(day))
        wanted = fold_key(customer) if customer else None
        return int(sum(row["total"] - row["paid"] for row in contracts if wanted is None or wanted in fold_key(row["customer"])))

    def _overdue(self, limit: pd.Timestamp) -> tuple[tuple[dict[str, Any], int], ...]:
        return tuple((row, max(0, sum(due < limit for due in row["dues"]) * row["monthly"] - row["paid"])) for row in self._contracts(limit))

    def installment_overdue(self, day: str | date | None = None) -> int:
        """Tiền của các kỳ góp có hạn trước ngày hỏi mà chưa góp đủ."""
        return int(sum(amount for _, amount in self._overdue(self._limit(day))))

    def overdue_customers(self, day: str | date | None = None) -> int:
        """Số khách trả góp còn kỳ quá hạn."""
        return len({row["customer"] for row, amount in self._overdue(self._limit(day)) if amount > 0})

    def installments_due(self, customer: str, day: str | date | None = None) -> int:
        """Số kỳ góp đã tới hạn của một khách, tính cả kỳ hạn đúng ngày hỏi."""
        limit = self._limit(day)
        wanted = fold_key(customer)
        return sum(sum(due <= limit for due in row["dues"]) for row in self._contracts(limit) if wanted in fold_key(row["customer"]))

    def _ledger_left(self, limit: pd.Timestamp, customer: str | None) -> pd.DataFrame:
        """Nợ theo đơn gồm sổ nợ và sổ góp, dùng khi shop ghi công nợ ở sổ riêng."""
        rows = []
        if self._has_concepts("debt_paid_date"):
            book = self._book("debt_paid_date")
            for _, group in book.groupby("note", sort=False):
                head = group.iloc[0]
                if pd.isna(head["record_date"]):
                    continue
                bought = pd.Timestamp(head["record_date"]).normalize()
                if bought <= limit:
                    paid = sum(_money(amount) for amount, day in zip(group["paid_amount"], group["debt_paid_date"]) if (_day(day) is not None and _day(day) <= limit))
                    rows.append({"customer_name": head["customer_name"], "order_day": bought, "left": _money(head["debt_amount"]) - paid})
        if self._has_concepts("installment_terms"):
            rows.extend({"customer_name": row["customer"], "order_day": row["bought"], "left": row["total"] - row["paid"]} for row in self._contracts(limit))
        frame = pd.DataFrame(rows, columns=["customer_name", "order_day", "left"])
        frame["customer_key"] = frame["customer_name"].map(lambda cell: None if pd.isna(cell) else fold_key(str(cell)))
        return frame if customer is None else frame[frame["customer_key"].map(lambda key: key is not None and fold_key(customer) in key)]


def _due_dates(bought: pd.Timestamp, *, terms: int, day: int) -> tuple[pd.Timestamp, ...]:
    out = []
    for index in range(1, terms + 1):
        month = bought.to_period("M") + index
        out.append(pd.Timestamp(year=month.year, month=month.month, day=min(day, month.days_in_month)))
    return tuple(out)
