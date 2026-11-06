from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .calendar_vn import load_calendar
from .clean import load
from .norm import fold_key
from .periods import Clock, Period

SERVICE_FEE = "phi phuc vu"
MORNING_HOURS = range(6, 14)
AFTERNOON_HOURS = range(14, 22)
ORDER_COLUMNS = ("order_date", "hour", "status_norm", "is_revenue", "customer_key", "customer_name", "customer_code", "customer_group", "is_walk_in", "staff", "channel", "payment_method", "order_total", "paid_amount", "debt_amount", "order_discount", "shipping_fee", "note")
FILTER_COLUMNS = {"item": "item_name", "group": "item_group", "channel": "channel", "payment": "payment_method", "customer_group": "customer_group", "customer": "customer_key", "staff": "staff"}
LOOKUP_LIMIT = 30


def _folded(value: Any) -> str:
    return fold_key(str(value)).replace("_", " ")


def _tables(root: Path) -> dict[str, pd.DataFrame]:
    return {path.stem: load(path) for path in sorted(root.glob("*.csv")) if not path.name.endswith(".dropped.csv")}


def _pick_lines(tables: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    ranked = [frame for name, frame in tables.items() if name.startswith("sales") and "line_amount" in frame.columns]
    if not ranked:
        return None
    return max(ranked, key=lambda frame: ("item_name" in frame.columns or "item_code" in frame.columns, len(frame)))


def _add_catalog(lines: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    out = lines
    for name, frame in tables.items():
        if not name.startswith("catalog") or "item_code" not in frame.columns or "item_code" not in out.columns:
            continue
        fields = [column for column in ("item_name", "item_group", "base_unit") if column in frame.columns and column not in out.columns]
        if fields:
            donor = frame.drop_duplicates("item_code").set_index("item_code")
            out = out.assign(**{field: out["item_code"].map(donor[field]) for field in fields})
    return out


def _add_keys(lines: pd.DataFrame) -> pd.DataFrame:
    out = lines.copy()
    if "base_quantity" not in out.columns and "quantity" in out.columns:
        out["base_quantity"] = out["quantity"]
    walk_in = out["is_walk_in"].fillna(False).astype(bool) if "is_walk_in" in out.columns else pd.Series(False, index=out.index)
    if "customer_code" in out.columns and out["customer_code"].notna().any():
        out["customer_key"] = out["customer_code"].where(~walk_in)
    elif "customer_name" in out.columns:
        out["customer_key"] = out["customer_name"].where(~walk_in).map(lambda value: value if pd.isna(value) else _folded(value))
    if "is_revenue" not in out.columns:
        out["is_revenue"] = True
    out["is_revenue"] = out["is_revenue"].fillna(True).astype(bool)
    return out


class Shop:
    """Một shop đã chuẩn hoá nhìn từ một ngày as_of: bảng lines, orders và các số đo theo rulebook."""

    def __init__(self, root: Path | str, *, as_of: str, calendar: str) -> None:
        self.clock = Clock(as_of, calendar=load_calendar(calendar))
        self.tables = _tables(Path(root))
        picked = _pick_lines(self.tables)
        self.lines: pd.DataFrame | None = None
        self.orders: pd.DataFrame | None = None
        if picked is not None:
            lines = _add_keys(_add_catalog(picked, self.tables))
            visible = pd.to_datetime(lines["order_date"]).dt.normalize() <= pd.Timestamp(self.clock.as_of)
            self.lines = lines[visible].reset_index(drop=True)
            self.orders = self._orders()

    def _orders(self) -> pd.DataFrame:
        kept = [column for column in ORDER_COLUMNS if column in self.lines.columns]
        grouped = self.lines.groupby("order_id", sort=False)
        return grouped[kept].first().assign(revenue=grouped["line_amount"].sum()).reset_index()

    def _match(self, frame: pd.DataFrame, *, key: str, value: Any) -> pd.Series:
        column = FILTER_COLUMNS[key]
        if column not in frame.columns:
            raise ValueError(f"shop has no column for {key}: answer is unanswerable if the question needs it")
        folded = frame[column].map(lambda cell: None if pd.isna(cell) else _folded(cell))
        wanted = _folded(value)
        exact = folded == wanted
        if exact.any():
            return exact
        partial = folded.map(lambda cell: cell is not None and wanted in cell)
        if partial.any():
            return partial
        known = sorted(str(cell) for cell in frame[column].dropna().unique())[:LOOKUP_LIMIT]
        raise ValueError(f"no {key} matches {value!r}, values are {known}")

    def _rows(self) -> pd.DataFrame:
        if self.lines is None:
            raise ValueError("shop has no sales table, use tables[...]")
        return self.lines

    def _select(self, frame: pd.DataFrame, *, period: Period | None, shift: str | None, filters: dict[str, Any]) -> pd.DataFrame:
        unknown = set(filters) - set(FILTER_COLUMNS)
        if unknown:
            raise ValueError(f"unknown filters {sorted(unknown)}, allowed {sorted(FILTER_COLUMNS)} and shift")
        out = frame
        if period is not None:
            days = pd.to_datetime(out["order_date"]).dt.normalize()
            out = out[(days >= pd.Timestamp(period.start)) & (days <= pd.Timestamp(period.end))]
        if shift is not None:
            if "hour" not in out.columns:
                raise ValueError("shop has no order hour: answer is unanswerable if the question needs a shift")
            hours = MORNING_HOURS if "sang" in _folded(shift) else AFTERNOON_HOURS
            out = out[out["hour"].isin(list(hours))]
        for key, value in filters.items():
            if value is not None:
                out = out[self._match(out, key=key, value=value)]
        return out

    def _sold(self, period: Period | None, shift: str | None, filters: dict[str, Any]) -> pd.DataFrame:
        lines = self._rows()
        return self._select(lines[lines["is_revenue"]], period=period, shift=shift, filters=filters)

    def revenue(self, period: Period | None = None, *, shift: str | None = None, **filters: Any) -> int:
        return int(self._sold(period, shift, filters)["line_amount"].sum())

    def order_count(self, period: Period | None = None, *, shift: str | None = None, **filters: Any) -> int:
        return int(self._sold(period, shift, filters)["order_id"].nunique())

    def quantity(self, period: Period | None = None, *, shift: str | None = None, **filters: Any) -> float:
        rows = self._sold(period, shift, filters)
        total = rows.loc[~self._service_fee(rows), "base_quantity"].sum()
        return int(total) if float(total).is_integer() else float(total)

    def average_order(self, period: Period | None = None, *, shift: str | None = None, **filters: Any) -> int:
        count = self.order_count(period, shift=shift, **filters)
        if count == 0:
            return 0
        return int(self.revenue(period, shift=shift, **filters) / count + 0.5)

    def cancel_rate(self, period: Period | None = None) -> float:
        rows = self._select(self._rows(), period=period, shift=None, filters={}).drop_duplicates("order_id")
        return round(100 * float((rows["status_norm"] == "huỷ").sum()) / len(rows), 2) if len(rows) else 0.0

    def ranking(self, *, by: str, metric: str = "revenue", period: Period | None = None, shift: str | None = None, **filters: Any) -> pd.Series:
        """Bảng xếp hạng giảm dần. by: item, group, customer, staff, channel, payment, day. metric: revenue, quantity, orders, days, cancelled."""
        column = "order_date" if by == "day" else FILTER_COLUMNS[by]
        if metric == "cancelled":
            lines = self._rows()
            rows = self._select(lines[lines["status_norm"] == "huỷ"], period=period, shift=shift, filters=filters)
        else:
            rows = self._sold(period, shift, filters)
        if column not in rows.columns:
            raise ValueError(f"shop has no column for {by}: answer is unanswerable if the question needs it")
        if by == "item":
            rows = rows[~self._service_fee(rows)]
        grouped = rows.dropna(subset=[column]).groupby(column)
        if metric == "revenue":
            result = grouped["line_amount"].sum()
        elif metric == "quantity":
            result = grouped["base_quantity"].sum()
        elif metric in ("orders", "cancelled"):
            result = grouped["order_id"].nunique()
        elif metric == "days":
            result = grouped["order_date"].nunique()
        else:
            raise ValueError(f"unknown metric {metric}")
        return result.sort_values(ascending=False, kind="stable")

    def _service_fee(self, rows: pd.DataFrame) -> pd.Series:
        if "item_name" not in rows.columns:
            return pd.Series(False, index=rows.index)
        return rows["item_name"].map(lambda cell: not pd.isna(cell) and SERVICE_FEE in _folded(cell))


def pct_change(new: float, old: float) -> float:
    """Phần trăm thay đổi so với kỳ cũ, giảm ra số âm, làm tròn 2 chữ số."""
    if old == 0:
        raise ValueError("old value is 0, percent change undefined")
    return round((new - old) / old * 100, 2)
