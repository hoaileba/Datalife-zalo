from __future__ import annotations

from typing import Any

import pandas as pd

from ..norm import fold_key, parse_datetime
from ..periods import Period

DELIVERY_HELPERS = ("delivery_rounds", "orders_min_rounds", "delivered_quantity")


class DeliveryMixin:
    """Sổ giao hàng nhiều đợt, đọc qua khái niệm delivery_round và delivery_date."""

    def _deliveries(self) -> pd.DataFrame:
        book = self._book("delivery_round", "delivery_date")
        days = pd.to_datetime(book["delivery_date"].map(parse_datetime), errors="coerce").dt.normalize()
        return book.assign(day=days)[days <= pd.Timestamp(self.clock.as_of)]

    def delivery_rounds(self, period: Period) -> int:
        """Số đợt có ngày giao trong kỳ, mỗi đợt của mỗi đơn tính một đợt."""
        book = self._deliveries()
        kept = book[(book["day"] >= pd.Timestamp(period.start)) & (book["day"] <= pd.Timestamp(period.end))]
        return int(kept[["order_id", "delivery_round"]].drop_duplicates().shape[0])

    def _deliveries_of_orders(self, period: Period) -> pd.DataFrame:
        book = self._deliveries()
        placed = pd.to_datetime(self.orders["order_date"]).dt.normalize()
        chosen = self.orders.loc[(placed >= pd.Timestamp(period.start)) & (placed <= pd.Timestamp(period.end)), "order_id"]
        return book[book["order_id"].isin(chosen)]

    def orders_min_rounds(self, period: Period, *, rounds: int = 2) -> int:
        """Số đơn đặt trong kỳ đã giao từ rounds đợt trở lên tính đến hôm nay."""
        book = self._deliveries_of_orders(period)
        return int((book.groupby("order_id")["delivery_round"].nunique() >= rounds).sum())

    def delivered_quantity(self, period: Period, *, item: Any) -> float:
        """Số lượng đã giao đến hôm nay của các đơn đặt trong kỳ, theo đơn vị cơ bản."""
        book = self._deliveries_of_orders(period)
        wanted = fold_key(str(item))
        names = book["item_name"].map(lambda cell: fold_key(str(cell)))
        total = pd.to_numeric(book.loc[names == wanted, "base_quantity"], errors="coerce").sum()
        return int(total) if float(total).is_integer() else float(total)
