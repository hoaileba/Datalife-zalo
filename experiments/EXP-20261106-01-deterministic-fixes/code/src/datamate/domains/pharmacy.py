from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from ..norm import fold_key

PHARMACY_HELPERS = ("expiring_lots", "expiring_value", "expiring_items", "nearest_expiry", "out_of_stock_count")


class PharmacyMixin:
    """Tồn theo lô và hạn dùng, đọc qua khái niệm lot_received, lot_sold, lot_returned."""

    def _lots_left(self, day: str | date | None = None) -> pd.DataFrame:
        limit = pd.Timestamp(day if day is not None else self.clock.as_of)
        lots = self._book("lot_received")
        if not {"lot_id", "expiry_date"} <= set(lots.columns):
            lots = next((self._book_named(name, "lot_received") for name in self._tables_with("lot_received") if {"lot_id", "expiry_date"} <= set(self.tables[name].columns)), None)
            if lots is None:
                raise ValueError("shop has no lot table: answer is unanswerable if the question needs it")
        used = self._book("lot_sold", "lot_returned")
        placed = used["order_id"].map(self.orders.drop_duplicates("order_id").set_index("order_id")["order_date"])
        used = used[pd.to_datetime(placed).dt.normalize() <= limit]
        net = pd.to_numeric(used["lot_sold"], errors="coerce").fillna(0) - pd.to_numeric(used["lot_returned"], errors="coerce").fillna(0)
        out = net.groupby(used["lot_id"]).sum()
        left = pd.to_numeric(lots["lot_received"], errors="coerce") - lots["lot_id"].map(out).fillna(0)
        return lots.assign(left=left, expiry=pd.to_datetime(lots["expiry_date"], errors="coerce"))[left > 0]

    def _lot_cost(self, lots: pd.DataFrame) -> pd.Series:
        if "unit_cost" in lots.columns:
            return pd.to_numeric(lots["unit_cost"], errors="coerce")
        detail = self._purchase_lines()
        if not {"document_id", "item_code"} <= set(detail.columns):
            raise ValueError("shop has no lot cost: answer is unanswerable if the question needs it")
        amounts = detail.groupby(["document_id", "item_code"]).agg(amount=("purchase_amount", "sum"))
        keys = pd.MultiIndex.from_frame(lots[["document_id", "item_code"]])
        received = pd.to_numeric(lots["lot_received"], errors="coerce")
        totals = lots.assign(received=received).groupby(["document_id", "item_code"])["received"].sum()
        return pd.Series(amounts["amount"].reindex(keys).values / totals.reindex(keys).values, index=lots.index)

    def _expiring(self, days: int | None, start: str | None, end: str | None) -> pd.DataFrame:
        first = pd.Timestamp(start) if start is not None else pd.Timestamp(self.clock.as_of)
        last = pd.Timestamp(end) if end is not None else first + pd.Timedelta(days=days or 0)
        lots = self._lots_left()
        return lots[(lots["expiry"] >= first) & (lots["expiry"] <= last)]

    def expiring_lots(self, days: int | None = None, *, start: str | None = None, end: str | None = None) -> int:
        """Số lô còn tồn có hạn từ start đến end, mặc định từ hôm nay đến hết hôm nay cộng days."""
        return len(self._expiring(days, start, end))

    def expiring_value(self, days: int | None = None, *, start: str | None = None, end: str | None = None) -> int:
        """Tiền vốn của phần còn tồn các lô đó, theo giá nhập của chính lô."""
        lots = self._expiring(days, start, end)
        return int(round((lots["left"] * self._lot_cost(lots)).sum()))

    def _item_names(self) -> dict[Any, str]:
        rows = self._rows().dropna(subset=["item_code", "item_name"]) if "item_code" in self._rows().columns else None
        names = {} if rows is None else dict(zip(rows["item_code"], rows["item_name"]))
        for name, frame in self.tables.items():
            if name.startswith("catalog") and {"item_code", "item_name"} <= set(frame.columns):
                names.update({code: item for code, item in zip(frame["item_code"], frame["item_name"]) if not pd.isna(code) and not pd.isna(item)})
        return names

    def expiring_items(self, days: int | None = None, *, start: str | None = None, end: str | None = None) -> list[str]:
        """Mặt hàng có lô còn tồn trong khoảng hạn, hạn sớm nhất trước, cùng hạn theo mã."""
        lots = self._expiring(days, start, end).sort_values(["expiry", "item_code"]).drop_duplicates("item_code")
        names = self._item_names()
        return [names.get(code, code) for code in lots["item_code"]]

    def nearest_expiry(self, item: str) -> str:
        """Hạn sớm nhất trong các lô còn tồn chưa quá hạn tại hôm nay của một mặt hàng."""
        lots = self._lots_left()
        lots = lots[lots["expiry"] >= pd.Timestamp(self.clock.as_of)]
        wanted = fold_key(item)
        names = self._item_names()
        folded = lots["item_code"].map(lambda code: fold_key(str(names.get(code, code))))
        matched = lots[(folded == wanted) | folded.map(lambda name: wanted in name)]
        if matched.empty:
            raise ValueError(f"no item matches {item!r} among lots in stock")
        return matched["expiry"].min().strftime("%Y-%m-%d")

    def out_of_stock_count(self, day: str | date | None = None) -> int:
        """Số mặt hàng có tồn bằng 0 lúc hết ngày."""
        return int((self._stock_levels(day)["stock"] <= 0).sum())
