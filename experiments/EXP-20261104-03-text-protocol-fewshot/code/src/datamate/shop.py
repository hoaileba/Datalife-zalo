from __future__ import annotations

import re
from datetime import date, timedelta
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
FILTER_COLUMNS = {"item": "item_name", "group": "item_group", "channel": "channel", "payment": "payment_method", "customer_group": "customer_group", "customer": "customer_key", "staff": "staff", "ingredient": "active_ingredient", "unit": "base_unit"}
TRUTHY = {"true", "1", "co", "x", "yes"}
LOOKUP_LIMIT = 30
HELPERS = ("revenue", "order_count", "quantity", "average_order", "cancel_rate", "cancelled_orders", "ranking", "sold_orders", "customer_count", "item_count", "sale_price", "price_effect", "debt_added", "debt_repaid", "debt_at", "debtors", "debtor_count", "purchase_cost", "avg_purchase_price", "top_supplier", "stock", "gross_profit", "net_profit", "expenses")
DEBT_PAYMENTS = {"debt", "ghi no"}
DATE_COLUMNS = ("order_date", "record_date")
NOT_ITEM = re.compile(r"^(voucher|phi ship|dung \d+ diem)$")
CONVERSION = re.compile(r"^\s*1?\s*(.+?)\s*=\s*(\d+)\s*(.+?)\s*$")


def _folded(value: Any) -> str:
    return fold_key(str(value)).replace("_", " ")


class Tables(dict):
    """Các bảng trong norm/, gọi sai tên thì lỗi kèm danh sách tên đúng."""

    def __missing__(self, key: str) -> pd.DataFrame:
        raise KeyError(f"no table {key!r}, tables are {sorted(self)}")


def _tables(root: Path) -> Tables:
    return Tables({path.stem: load(path) for path in sorted(root.glob("*.csv")) if not path.name.endswith(".dropped.csv")})


def _visible(frame: pd.DataFrame, as_of: date) -> pd.DataFrame:
    for column in DATE_COLUMNS:
        if column in frame.columns:
            days = pd.to_datetime(frame[column], errors="coerce").dt.normalize()
            return frame[days.isna() | (days <= pd.Timestamp(as_of))].reset_index(drop=True)
    return frame


def _pick_lines(tables: dict[str, pd.DataFrame]) -> pd.DataFrame | None:
    ranked = [frame for name, frame in tables.items() if name.startswith("sales") and "line_amount" in frame.columns and "order_date" in frame.columns]
    if ranked:
        return max(ranked, key=lambda frame: ("item_name" in frame.columns or "item_code" in frame.columns, len(frame)))
    repairs = next((frame for name, frame in tables.items() if name.startswith("repairs")), None)
    if repairs is None:
        return None
    return repairs.assign(order_id=range(1, len(repairs) + 1), order_date=repairs["record_date"], line_amount=repairs["amount"].fillna(0), item_name=repairs["Làm gì"])


def _add_catalog(lines: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    out = lines
    catalogs = [frame for name, frame in tables.items() if name.startswith("catalog")]
    for frame in catalogs:
        if "item_alias" in frame.columns and "item_name" in frame.columns and "item_name" in out.columns:
            names = pd.concat([frame.assign(key=frame["item_alias"]), frame.assign(key=frame["item_name"])]).dropna(subset=["key"])
            donor = names.assign(key=lambda f: f["key"].map(_folded)).drop_duplicates("key").set_index("key")
            keys = out["item_name"].map(lambda cell: None if pd.isna(cell) else _folded(cell))
            full = keys.map(donor["item_name"])
            out = out.assign(item_name=full.where(full.notna(), out["item_name"]))
            if "item_group" in donor.columns and "item_group" not in out.columns:
                out = out.assign(item_group=keys.map(donor["item_group"]))
    for frame in catalogs:
        for key in ("item_code", "item_name"):
            if key not in frame.columns or key not in out.columns:
                continue
            fields = [column for column in ("item_name", "item_group", "base_unit", "big_unit", "unit_factor", "active_ingredient", "is_prescription") if column != key and column in frame.columns and column not in out.columns]
            if not fields:
                continue
            donor = frame.dropna(subset=[key]).assign(join_key=lambda f: f[key].map(_folded)).drop_duplicates("join_key").set_index("join_key")
            keys = out[key].map(lambda cell: None if pd.isna(cell) else _folded(cell))
            out = out.assign(**{field: keys.map(donor[field]) for field in fields})
    return out


def _conversions(tables: dict[str, pd.DataFrame]) -> dict[tuple[str, str], float]:
    factors: dict[tuple[str, str], float] = {}
    for name, frame in tables.items():
        if name.startswith("catalog") and {"item_name", "Quy đổi"} <= set(frame.columns):
            for item, rule in zip(frame["item_name"], frame["Quy đổi"]):
                for part in str(rule).split(";") if not pd.isna(rule) else ():
                    match = CONVERSION.match(part)
                    if match is not None and not pd.isna(item):
                        factors[(_folded(item), _folded(match.group(1)))] = float(match.group(2))
    return factors


def _add_base_quantity(lines: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if "base_quantity" in lines.columns or "quantity" not in lines.columns:
        return lines
    factors = _conversions(tables)
    if factors and {"item_name", "unit"} <= set(lines.columns):
        scale = [factors.get((_folded(item), _folded(unit)), 1.0) for item, unit in zip(lines["item_name"], lines["unit"])]
        return lines.assign(base_quantity=lines["quantity"] * scale)
    if not {"unit", "big_unit", "unit_factor"} <= set(lines.columns):
        return lines.assign(base_quantity=lines["quantity"])
    big = lines["unit"].map(lambda cell: None if pd.isna(cell) else _folded(cell)) == lines["big_unit"].map(lambda cell: None if pd.isna(cell) else _folded(cell))
    return lines.assign(base_quantity=lines["quantity"] * pd.to_numeric(lines["unit_factor"], errors="coerce").fillna(1).where(big, 1))


def _mark_returns(lines: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    returned: set[Any] = set()
    if "quantity" in lines.columns:
        returned |= set(lines.loc[pd.to_numeric(lines["quantity"], errors="coerce") < 0, "order_id"])
    for name, frame in tables.items():
        if "tra_hang" in name and "order_id" in frame.columns:
            returned |= set(frame["order_id"].dropna())
    if not returned:
        return lines
    hit = lines["order_id"].isin(returned)
    out = lines.assign(is_revenue=lines["is_revenue"].where(~hit, False))
    return out.assign(status_norm=out["status_norm"].where(~hit | (out["status_norm"] == "huỷ"), "trả hàng")) if "status_norm" in out.columns else out


def _add_customers(lines: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if "customer_code" not in lines.columns:
        return lines
    out = lines
    for name, frame in tables.items():
        if name.startswith("customers") and "customer_code" in frame.columns:
            donor = frame.drop_duplicates("customer_code").set_index("customer_code")
            fields = [column for column in ("customer_name", "customer_group") if column in frame.columns and column not in out.columns]
            out = out.assign(**{field: out["customer_code"].map(donor[field]) for field in fields})
    return out


def _add_keys(lines: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    out = _add_base_quantity(lines, tables).copy()
    walk_in = out["is_walk_in"].fillna(False).astype(bool) if "is_walk_in" in out.columns else pd.Series(False, index=out.index)
    if "customer_code" in out.columns and out["customer_code"].notna().any():
        out["customer_key"] = out["customer_code"].where(~walk_in)
    elif "customer_name" in out.columns:
        out["customer_key"] = out["customer_name"].where(~walk_in).map(lambda value: value if pd.isna(value) else _folded(value))
    if "item_name" in out.columns:
        folded = out["item_name"].map(lambda cell: cell if pd.isna(cell) else _folded(cell))
        out["item_key"] = out["item_code"].where(out["item_code"].notna(), folded) if "item_code" in out.columns else folded
    if "is_revenue" not in out.columns:
        out["is_revenue"] = True
    out["is_revenue"] = out["is_revenue"].fillna(True).astype(bool)
    if "item_name" in out.columns:
        not_item = out["item_name"].map(lambda cell: not pd.isna(cell) and NOT_ITEM.match(_folded(cell)) is not None)
        out["is_revenue"] = out["is_revenue"] & ~not_item
    return out


class Shop:
    """Một shop đã chuẩn hoá nhìn từ một ngày as_of: bảng lines, orders và các số đo theo rulebook."""

    def __init__(self, root: Path | str, *, as_of: str, calendar: str) -> None:
        self.clock = Clock(as_of, calendar=load_calendar(calendar))
        loaded = _tables(Path(root))
        picked = _pick_lines(loaded)
        self.tables = Tables({name: _visible(frame, self.clock.as_of) for name, frame in loaded.items()})
        self.lines: pd.DataFrame | None = None
        self.orders: pd.DataFrame | None = None
        if picked is not None:
            lines = _mark_returns(_add_keys(_add_customers(_add_catalog(picked, self.tables), self.tables), self.tables), self.tables)
            visible = pd.to_datetime(lines["order_date"]).dt.normalize() <= pd.Timestamp(self.clock.as_of)
            self.lines = lines[visible].reset_index(drop=True)
            self.orders = self._orders()

    def _orders(self) -> pd.DataFrame:
        kept = [column for column in ORDER_COLUMNS if column in self.lines.columns]
        grouped = self.lines.groupby("order_id", sort=False)
        return grouped[kept].first().assign(revenue=grouped["line_amount"].sum()).reset_index()

    def _match(self, frame: pd.DataFrame, *, key: str, value: Any) -> pd.Series:
        column = "customer_name" if key == "customer" and "customer_name" in frame.columns else FILTER_COLUMNS[key]
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
        unknown = set(filters) - set(FILTER_COLUMNS) - {"size", "prescription"}
        if unknown:
            raise ValueError(f"unknown filters {sorted(unknown)}, allowed {sorted(FILTER_COLUMNS)}, size, prescription and shift")
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
            if value is None:
                continue
            if key == "size":
                out = out[out["item_name"].map(lambda cell: not pd.isna(cell) and str(cell).strip().casefold().endswith(f"({str(value).casefold()})"))]
            elif key == "prescription":
                if "is_prescription" not in out.columns:
                    raise ValueError("shop has no prescription column: answer is unanswerable if the question needs it")
                out = out[out["is_prescription"].map(lambda cell: not pd.isna(cell) and _folded(cell) in TRUTHY) == bool(value)]
            else:
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
        column = "order_date" if by == "day" else "item_key" if by == "item" else FILTER_COLUMNS[by]
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
        elif metric == "profit":
            result = (grouped["line_amount"].sum() - self._line_cost(rows).groupby(rows[column]).sum()).dropna()
        else:
            raise ValueError(f"unknown metric {metric}")
        ranked = pd.DataFrame({"value": result, "tie": result.index.astype(str)}).sort_values(["value", "tie"], ascending=[False, True], kind="stable")["value"]
        if by == "item":
            names = rows.dropna(subset=[column]).groupby(column)["item_name"].agg(lambda cells: cells.mode().iloc[0])
            ranked.index = [names.get(key, key) for key in ranked.index]
        if by == "day":
            ranked.index = pd.to_datetime(ranked.index).strftime("%Y-%m-%d")
        if by == "customer":
            names = rows.dropna(subset=[column]).groupby(column)["customer_name"].first() if "customer_name" in rows.columns else None
            if names is not None:
                ranked.index = [names.get(key, key) for key in ranked.index]
        ranked.index.name = by
        return ranked

    def _line_cost(self, rows: pd.DataFrame) -> pd.Series:
        if "unit_cost" not in rows.columns:
            raise ValueError("shop has no cost on sales lines: answer is unanswerable if the question needs it")
        return pd.to_numeric(rows["quantity"], errors="coerce") * pd.to_numeric(rows["unit_cost"], errors="coerce")

    def cancelled_orders(self, period: Period | None = None) -> int:
        """Số đơn trạng thái huỷ đặt trong kỳ."""
        rows = self._select(self._rows(), period=period, shift=None, filters={})
        return int(rows.loc[rows["status_norm"] == "huỷ", "order_id"].nunique())

    def top_supplier(self, period: Period | None = None) -> str:
        """Nhà cung cấp có tiền nhập cao nhất trong kỳ."""
        rows = self._purchase_lines()
        if period is not None:
            rows = rows[(rows["day"] >= pd.Timestamp(period.start)) & (rows["day"] <= pd.Timestamp(period.end))]
        if "supplier" not in rows.columns:
            raise ValueError("shop has no supplier column: answer is unanswerable if the question needs it")
        totals = rows.groupby("supplier")["purchase_amount"].sum()
        return str(totals.sort_values(ascending=False, kind="stable").index[0])

    def gross_profit(self, period: Period | None = None, *, shift: str | None = None, **filters: Any) -> int:
        """Lãi gộp: doanh thu trừ số lượng nhân giá vốn ghi trên dòng bán."""
        rows = self._sold(period, shift, filters)
        return int(round(rows["line_amount"].sum() - self._line_cost(rows).sum()))

    def expenses(self, period: Period) -> int:
        """Tổng mọi khoản trong sổ chi phí của kỳ."""
        for name, frame in self.tables.items():
            if "chi" in _folded(name).replace("_", " ").split() or "chiphi" in _folded(name).replace(" ", ""):
                dates = [column for column in frame.columns if _folded(column) in ("record_date", "ngay chi", "ngay")]
                money = [column for column in frame.columns if _folded(column) in ("amount", "so tien", "line_amount")]
                if dates and money:
                    days = pd.to_datetime(frame[dates[0]], errors="coerce").dt.normalize()
                    return int(pd.to_numeric(frame.loc[(days >= pd.Timestamp(period.start)) & (days <= pd.Timestamp(period.end)), money[0]], errors="coerce").sum())
        raise ValueError("shop has no expense book: answer is unanswerable if the question needs it")

    def net_profit(self, period: Period) -> int:
        """Lãi ròng: lãi gộp của kỳ trừ mọi khoản trong sổ chi phí của kỳ."""
        return self.gross_profit(period) - self.expenses(period)

    def customer_count(self, period: Period | None = None, *, min_orders: int = 1, **filters: Any) -> int:
        """Số khách có ít nhất min_orders đơn tính doanh thu trong kỳ, không tính khách lẻ."""
        rows = self._sold(period, None, filters).dropna(subset=["customer_key"])
        return int((rows.groupby("customer_key")["order_id"].nunique() >= min_orders).sum())

    def item_count(self, period: Period | None = None, *, min_orders: int = 1, **filters: Any) -> int:
        """Số mặt hàng có mặt trong ít nhất min_orders đơn tính doanh thu của kỳ."""
        rows = self._sold(period, None, filters)
        rows = rows[~self._service_fee(rows)]
        return int((rows.groupby("item_name")["order_id"].nunique() >= min_orders).sum())

    def sale_price(self, item: str, day: str) -> int:
        """Đơn giá trên dòng bán của mặt hàng ngày đó cho một đơn vị cơ bản, trước chiết khấu, tính cả đơn huỷ, trả."""
        rows = self._select(self._rows(), period=self.clock.day(day), shift=None, filters={"item": item})
        if rows.empty:
            raise ValueError(f"no sale of {item!r} on {day}")
        factor = pd.to_numeric(rows["base_quantity"], errors="coerce") / pd.to_numeric(rows["quantity"], errors="coerce")
        return int(round((pd.to_numeric(rows["unit_price"], errors="coerce") / factor.replace(0, 1).fillna(1)).mode().iloc[0]))

    def price_effect(self, item: str, day: str, *, days: int) -> float:
        """Phần trăm đổi số lượng N ngày kể từ ngày đổi giá so với N ngày ngay trước."""
        start = date.fromisoformat(day)
        after = Period(start=start, end=start + timedelta(days=days - 1))
        before = Period(start=start - timedelta(days=days), end=start - timedelta(days=1))
        return pct_change(self.quantity(after, item=item), self.quantity(before, item=item))

    def _purchase_lines(self) -> pd.DataFrame:
        frames = {name: frame for name, frame in self.tables.items() if name.startswith("purchases")}
        detail = next((frame for frame in frames.values() if "quantity" in frame.columns and ({"unit_cost", "line_amount"} & set(frame.columns))), None)
        if detail is None:
            raise ValueError("shop has no purchase lines: answer is unanswerable if the question needs it")
        out = detail
        if "record_date" not in out.columns:
            header = next((frame for frame in frames.values() if {"record_date", "document_id"} <= set(frame.columns)), None)
            if header is None:
                raise ValueError("shop has no purchase dates: answer is unanswerable if the question needs it")
            kept = [column for column in ("document_id", "record_date", "status", "supplier") if column in header.columns]
            out = out.merge(header[kept].drop_duplicates("document_id"), on="document_id", how="left", suffixes=("", "_header"))
        if "status" in out.columns:
            out = out[~out["status"].map(lambda cell: not pd.isna(cell) and "huy" in _folded(cell))]
        if "item_name" not in out.columns and "item_code" in out.columns and self.lines is not None and "item_code" in self.lines.columns:
            names = self.lines.dropna(subset=["item_code", "item_name"]).drop_duplicates("item_code").set_index("item_code")["item_name"]
            out = out.assign(item_name=out["item_code"].map(names))
        quantity = pd.to_numeric(out["quantity"], errors="coerce")
        cost = pd.to_numeric(out["line_amount"], errors="coerce") if "line_amount" in out.columns else quantity * pd.to_numeric(out["unit_cost"], errors="coerce")
        return out.assign(quantity=quantity, purchase_amount=cost, day=pd.to_datetime(out["record_date"], errors="coerce").dt.normalize())

    def avg_purchase_price(self, period: Period, *, item: str) -> int:
        """Giá nhập bình quân theo số lượng nhập, theo đơn vị nhập, bỏ phiếu huỷ."""
        rows = self._purchase_lines()
        rows = rows[(rows["day"] >= pd.Timestamp(period.start)) & (rows["day"] <= pd.Timestamp(period.end))]
        rows = rows[self._match(rows, key="item", value=item)]
        if rows.empty or rows["quantity"].sum() == 0:
            raise ValueError(f"no purchase of {item!r} in {period}")
        return int(rows["purchase_amount"].sum() / rows["quantity"].sum() + 0.5)

    def debtor_count(self, day: str | date | None = None) -> int:
        """Số khách còn nợ lúc hết ngày, không tính khách lẻ."""
        return len(self.debtors(day))

    def debtors(self, day: str | date | None = None) -> pd.Series:
        """Còn nợ theo khách lúc hết ngày, giảm dần, không tính khách lẻ."""
        limit = pd.Timestamp(day if day is not None else self.clock.as_of)
        debt = self._debt_orders(None)
        debt = debt[debt["order_day"] <= limit]
        receipts = self._receipts()
        paid = receipts[receipts["paid_day"] <= limit].groupby("order_id")["amount"].sum()
        left = debt.assign(left=debt["order_total"] - debt["order_id"].map(paid).fillna(0))
        left = left[(left["left"] > 0) & left["customer_key"].notna()]
        totals = left.groupby("customer_key")["left"].sum()
        names = left.groupby("customer_key")["customer_name"].first() if "customer_name" in left.columns else totals.index.to_series()
        ranked = pd.DataFrame({"value": totals, "tie": totals.index.astype(str)}).sort_values(["value", "tie"], ascending=[False, True])["value"]
        ranked.index = [names.get(key, key) for key in ranked.index]
        return ranked.astype(int)

    def stock(self, *, item: str, day: str | date | None = None) -> float:
        """Tồn của mặt hàng lúc hết ngày theo đơn vị cơ bản."""
        for frame in self.tables.values():
            if "stock" in frame.columns and "item_name" in frame.columns:
                rows = frame[self._match(frame, key="item", value=item)]
                if len(rows):
                    total = pd.to_numeric(rows["stock"], errors="coerce").sum()
                    return int(total) if float(total).is_integer() else float(total)
        raise ValueError("shop has no stock table: answer is unanswerable if the question needs it")

    def sold_orders(self, period: Period | None = None, *, shift: str | None = None, **filters: Any) -> pd.DataFrame:
        """Các đơn tính vào doanh thu trong kỳ, mỗi dòng một đơn, có cột revenue của cả đơn."""
        return self.orders[self.orders["order_id"].isin(self._sold(period, shift, filters)["order_id"])].reset_index(drop=True)

    def _receipts(self) -> pd.DataFrame:
        for name, frame in self.tables.items():
            if name.startswith("receipts") and {"order_id", "record_date", "amount"} <= set(frame.columns):
                days = pd.to_datetime(frame["record_date"]).dt.normalize()
                return frame.assign(paid_day=days)
        raise ValueError("shop has no receipts table: read the debt book in tables[...]")

    def _debt_orders(self, customer: str | None) -> pd.DataFrame:
        orders = self.orders
        if "payment_method" not in orders.columns or "order_total" not in orders.columns:
            raise ValueError("shop has no payment method or order total: read the debt book in tables[...]")
        kept = orders[orders["payment_method"].map(lambda cell: not pd.isna(cell) and _folded(cell) in DEBT_PAYMENTS) & (orders["status_norm"] != "huỷ")]
        kept = kept.assign(order_day=pd.to_datetime(kept["order_date"]).dt.normalize())
        return kept if customer is None else kept[self._match(kept, key="customer", value=customer)]

    def debt_added(self, period: Period, *, customer: str | None = None) -> int:
        """Nợ thêm trong kỳ: phần tổng đơn chưa trả ngay trong ngày mua, của đơn ghi nợ đặt trong kỳ."""
        debt = self._debt_orders(customer)
        debt = debt[(debt["order_day"] >= pd.Timestamp(period.start)) & (debt["order_day"] <= pd.Timestamp(period.end))]
        receipts = self._receipts().merge(debt[["order_id", "order_day"]], on="order_id")
        paid = receipts[receipts["paid_day"] == receipts["order_day"]].groupby("order_id")["amount"].sum()
        return int((debt["order_total"] - debt["order_id"].map(paid).fillna(0)).sum())

    def debt_repaid(self, period: Period, *, customer: str | None = None) -> int:
        """Thu nợ trong kỳ: các khoản trả sau ngày mua có ngày trả trong kỳ, của mọi đơn ghi nợ."""
        receipts = self._receipts().merge(self._debt_orders(customer)[["order_id", "order_day"]], on="order_id")
        later = receipts[(receipts["paid_day"] > receipts["order_day"]) & (receipts["paid_day"] >= pd.Timestamp(period.start)) & (receipts["paid_day"] <= pd.Timestamp(period.end))]
        return int(later["amount"].sum())

    def debt_at(self, day: str | date | None = None, *, customer: str | None = None) -> int:
        """Còn nợ lúc hết ngày: cộng phần chưa trả của các đơn còn nợ > 0, từ đầu dữ liệu."""
        limit = pd.Timestamp(day if day is not None else self.clock.as_of)
        debt = self._debt_orders(customer)
        debt = debt[debt["order_day"] <= limit]
        receipts = self._receipts()
        paid = receipts[receipts["paid_day"] <= limit].groupby("order_id")["amount"].sum()
        left = debt["order_total"] - debt["order_id"].map(paid).fillna(0)
        return int(left[left > 0].sum())

    def purchase_cost(self, period: Period | None = None, *, supplier: str | None = None) -> int:
        """Tiền nhập hàng trong kỳ theo ngày phiếu, bỏ phiếu huỷ."""
        frames = [frame for name, frame in self.tables.items() if name.startswith("purchases") and "record_date" in frame.columns and ({"amount", "line_amount"} & set(frame.columns))]
        if not frames:
            raise ValueError("shop has no purchase table with date and amount: answer is unanswerable if the question needs it")
        amount = "amount" if "amount" in frames[0].columns else "line_amount"
        frame = frames[0].drop_duplicates("document_id") if amount == "amount" and "document_id" in frames[0].columns else frames[0]
        days = pd.to_datetime(frame["record_date"]).dt.normalize()
        keep = pd.Series(True, index=frame.index)
        if period is not None:
            keep &= (days >= pd.Timestamp(period.start)) & (days <= pd.Timestamp(period.end))
        if "status" in frame.columns:
            keep &= ~frame["status"].map(lambda cell: not pd.isna(cell) and "huy" in _folded(cell))
        if supplier is not None:
            if "supplier" not in frame.columns:
                raise ValueError("shop has no supplier column: answer is unanswerable if the question needs it")
            keep &= frame["supplier"].map(lambda cell: not pd.isna(cell) and _folded(supplier) in _folded(cell))
        return int(pd.to_numeric(frame.loc[keep, amount], errors="coerce").sum())

    def _service_fee(self, rows: pd.DataFrame) -> pd.Series:
        if "item_name" not in rows.columns:
            return pd.Series(False, index=rows.index)
        return rows["item_name"].map(lambda cell: not pd.isna(cell) and SERVICE_FEE in _folded(cell))


def pct_change(new: float, old: float) -> float:
    """Phần trăm thay đổi so với kỳ cũ, giảm ra số âm, làm tròn 2 chữ số."""
    if old == 0:
        raise ValueError("old value is 0, percent change undefined")
    return round((new - old) / old * 100, 2)
