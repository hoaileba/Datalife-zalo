from __future__ import annotations

import re
from typing import Any

import pandas as pd

from ..norm import fold_key
from ..periods import Period

BABY_HELPERS = ("order_fee_total", "group_share", "top_brand", "new_members")
FEE_PATTERNS = {"voucher": r"^voucher$", "ship": r"^phi ship$", "points": r"^dung \d+ diem$"}
EXCLUDED_STATUS = ("huỷ", "trả hàng")


class BabyMixin:
    """Dòng voucher, phí ship, dùng điểm và thuộc tính hãng, size trong danh mục."""

    def order_fee_total(self, period: Period, kind: str) -> int:
        """Tổng dương của voucher, ship hoặc points theo ngày hoá đơn, chỉ hoá đơn không huỷ, không trả."""
        if kind not in FEE_PATTERNS:
            raise ValueError(f"unknown kind {kind}, allowed {sorted(FEE_PATTERNS)}")
        rows = self._rows()
        rows = rows[~rows["status_norm"].isin(EXCLUDED_STATUS)]
        rows = self._select(rows, period=period, shift=None, filters={})
        kept = rows["item_name"].map(lambda cell: not pd.isna(cell) and re.match(FEE_PATTERNS[kind], fold_key(str(cell))) is not None)
        return int(abs(pd.to_numeric(rows.loc[kept, "line_amount"], errors="coerce").sum()))

    def group_share(self, period: Period, group: str, **filters: Any) -> float:
        """Phần trăm số lượng của phần lọc trên tổng số lượng cả nhóm hàng cùng kỳ."""
        return round(100 * self.quantity(period, group=group, **filters) / self.quantity(period, group=group), 2)

    def top_brand(self, period: Period, *, group: str | None = None, size: str | None = None) -> str:
        """Hãng bán nhiều số lượng nhất trong kỳ, lọc theo nhóm và số hoặc size."""
        return self.ranking(by="brand", metric="quantity", period=period, group=group, size=size).index[0]

    def new_members(self, period: Period) -> int:
        """Số khách có ngày đăng ký trong kỳ, kể cả khách chưa mua."""
        days = pd.to_datetime(self._book("member_date")["member_date"], errors="coerce")
        return int(((days >= pd.Timestamp(period.start)) & (days <= pd.Timestamp(period.end))).sum())
