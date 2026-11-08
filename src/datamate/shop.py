from __future__ import annotations

import difflib
import functools
import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from .calendar_vn import load_calendar
from .clean import load
from .domains import DOMAIN_HELPERS, DOMAIN_MIXINS, DOMAIN_REQUIREMENTS
from .norm import display_name, fold_key, parse_datetime, parse_number
from .periods import Clock, Period

SERVICE_FEE = "phi phuc vu"
MORNING_HOURS = range(6, 14)
AFTERNOON_HOURS = range(14, 22)
ORDER_COLUMNS = ("order_date", "hour", "status_norm", "is_revenue", "customer_key", "customer_name", "customer_code", "customer_group", "is_walk_in", "staff", "channel", "payment_method", "order_total", "paid_amount", "debt_amount", "order_discount", "shipping_fee", "note")
FILTER_COLUMNS = {"item": "item_name", "group": "item_group", "channel": "channel", "payment": "payment_method", "customer_group": "customer_group", "customer": "customer_key", "staff": "staff", "ingredient": "active_ingredient", "unit": "base_unit", "brand": "brand", "hour": "hour"}
TRUTHY = {"true", "1", "co", "x", "yes"}
BY_ALIASES = {"item_name": "item", "item_code": "item", "item_group": "group", "customer_name": "customer", "customer_code": "customer", "customer_key": "customer", "staff_name": "staff", "payment_method": "payment", "order_date": "day", "date": "day"}
EXPENSE_TABLE = re.compile(r"chi_?phi")
EXPENSE_DATES = ("record_date", "ngay chi", "ngay mua", "ngay")
EXPENSE_AMOUNTS = ("amount", "so tien", "line_amount")
STAFF_PREFIX = re.compile(r"^(?:a|anh|chi|c)[\s.]+")
VEHICLE_PLATE = re.compile(r"\d{2}[A-Za-z]\d?-\d{3}\.?\d{2}")
CLOSE_MATCHES = 5
LOOKUP_LIMIT = 30
HELPERS = ("revenue", "order_count", "quantity", "average_order", "cancel_rate", "cancelled_orders", "ranking", "sold_orders", "customer_count", "item_count", "sale_price", "price_effect", "debt_added", "debt_repaid", "debt_at", "debt_aged", "debtors", "debtor_count", "purchase_cost", "avg_purchase_price", "top_supplier", "stock", "stock_big", "stock_value", "purchase_minus_sold", "purchase_quantity", "gross_profit", "net_profit", "expenses", "unsold_count", "due_orders", "best_month", "main_supplier", "price_raise_date") + DOMAIN_HELPERS
DEBT_PAYMENTS = {"debt", "ghi no"}
DATE_COLUMNS = ("order_date", "record_date")
NOT_ITEM = re.compile(r"^(voucher|phi ship|dung \d+ diem)$")
CONVERSION = re.compile(r"^\s*1?\s*(.+?)\s*=\s*(\d+)\s*(.+?)\s*$")
ADDON = re.compile(r"\s\+\s(?:(\d+)\s+)?([^+]+?)\s*\(([\d.,]+)đ\)")
FILTER_SYNONYMS = {
    "payment": (("cash", "tien mat", "tien tuoi", "tm"), ("transfer", "chuyen khoan", "ck"), ("ewallet", "vi dien tu", "vi"), ("cod", "thu ho", "thu ho (cod)", "xi o di", "ship cod"), ("debt", "ghi no")),
    "channel": (("store", "tai quay", "tai tiem", "tai cua hang"), ("phone", "dien thoai", "qua dien thoai"), ("zalo oa", "zalo"), ("san tmdt", "san thuong mai dien tu", "san")),
}
NOTE_AMOUNT = r"(\d[\d.,]*)\s*(k|nghin|tr(?:ieu)?\s*\d*|d)?"
NOTE_SETTLED = re.compile(r"\b(du|het)\b")
NOTE_OWED = re.compile(rf"\b(?:no|thieu(?: lai)?|ghi so)\s+{NOTE_AMOUNT}")
NOTE_PREPAID = re.compile(rf"\b(?:dua truoc|tra|ck)\s+{NOTE_AMOUNT}")


def name_tokens(frame: pd.DataFrame) -> set[str]:
    return {_folded(value) for value in frame.get("source_sheet", pd.Series(dtype=object)).dropna().unique()}


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
    for frame in catalogs + catalogs:
        for key in ("item_code", "item_name"):
            if key not in frame.columns or key not in out.columns:
                continue
            fields = [column for column in ("item_code", "item_name", "item_group", "base_unit", "big_unit", "unit_factor", "active_ingredient", "is_prescription") if column != key and column in frame.columns and column not in out.columns]
            if not fields:
                continue
            donor = frame.dropna(subset=[key]).assign(join_key=lambda f: f[key].map(_folded)).drop_duplicates("join_key").set_index("join_key")
            keys = out[key].map(lambda cell: None if pd.isna(cell) else _folded(cell))
            out = out.assign(**{field: keys.map(donor[field]) for field in fields})
    return out


def _note_money(digits: str, unit: str | None) -> float:
    label = (unit or "").replace(" ", "")
    if label.startswith("tr"):
        tail = label.removeprefix("trieu").removeprefix("tr")
        return float(digits.replace(",", ".")) * 1_000_000 + (float(f"0.{tail}") * 1_000_000 if tail else 0)
    amount = parse_number(digits) or 0.0
    return amount * 1000 if label in ("k", "nghin") else amount


def _note_left(note: Any, total: float) -> float:
    """Phần còn nợ của một đơn đọc từ ghi chú tự do, ghi chú là tình trạng đến ngày cuối dữ liệu."""
    text = _folded(note)
    if NOTE_SETTLED.search(text):
        return 0.0
    owed = NOTE_OWED.search(text)
    if owed is not None:
        return _note_money(owed.group(1), owed.group(2))
    prepaid = NOTE_PREPAID.search(text)
    return total - _note_money(prepaid.group(1), prepaid.group(2)) if prepaid is not None else total


def _split_addons(lines: pd.DataFrame) -> pd.DataFrame:
    """Tách topping ghi chung ô với món thành dòng riêng, tiền topping chuyển khỏi dòng món."""
    if not {"item_name", "line_amount"} <= set(lines.columns):
        return lines
    names = lines["item_name"].astype("string")
    joined = names.str.contains(ADDON.pattern, regex=True, na=False)
    if not joined.any():
        return lines
    known = {_folded(name): str(name) for name in lines["item_name"].dropna().unique() if " + " not in str(name)}
    bases = lines[joined].copy()
    addons = []
    for index, row in bases.iterrows():
        text = str(row["item_name"])
        found = ADDON.findall(text)
        amounts = [parse_number(amount) or 0.0 for _, _, amount in found]
        bases.at[index, "item_name"] = text[: text.index(" + ")].strip()
        bases.at[index, "line_amount"] = row["line_amount"] - sum(amounts)
        for (count, name, _), amount in zip(found, amounts):
            portions = float(count or 1)
            label = known.get(f"topping {_folded(name)}", known.get(_folded(name), f"Topping {name}"))
            addons.append({**row.to_dict(), "item_name": label, "quantity": portions, "line_amount": amount, "unit_price": amount / portions, "unit": "phần"})
    return pd.concat([lines[~joined], bases, pd.DataFrame(addons)], ignore_index=True)


def _conversions(tables: dict[str, pd.DataFrame]) -> dict[tuple[str, str], float]:
    factors: dict[tuple[str, str], float] = {}
    catalogs = {name: frame for name, frame in tables.items() if name.startswith("catalog")}
    names = {code: item for frame in catalogs.values() if {"item_code", "item_name"} <= set(frame.columns) for code, item in zip(frame["item_code"], frame["item_name"]) if not pd.isna(code) and not pd.isna(item)}
    for frame in catalogs.values():
        label = next((column for column in ("unit", "Quy cách") if column in frame.columns), None)
        if label is not None and {"item_code", "unit_factor"} <= set(frame.columns):
            for code, factor, unit in zip(frame["item_code"], pd.to_numeric(frame["unit_factor"], errors="coerce"), frame[label]):
                if code in names and not pd.isna(factor) and not pd.isna(unit):
                    factors[(_folded(names[code]), _folded(unit))] = float(factor)
    for frame in catalogs.values():
        if {"item_name", "big_unit", "unit_factor"} <= set(frame.columns):
            factors.update(_chained_factors(frame))
    for name, frame in tables.items():
        if name.startswith("catalog") and {"item_name", "Quy đổi"} <= set(frame.columns):
            for item, rule in zip(frame["item_name"], frame["Quy đổi"]):
                for part in str(rule).split(";") if not pd.isna(rule) else ():
                    match = CONVERSION.match(part)
                    if match is not None and not pd.isna(item):
                        factors[(_folded(item), _folded(match.group(1)))] = float(match.group(2))
    return factors


def _chained_factors(frame: pd.DataFrame) -> dict[tuple[str, str], float]:
    """Hệ số ra đơn vị cơ bản của mọi đơn vị lớn; hệ số ghi kèm đơn vị (`factor_unit`, như `25 vỉ`) thì nhân qua đơn vị đó."""
    steps: dict[str, dict[str, tuple[float, str | None]]] = {}
    for row in frame.itertuples(index=False):
        item, big, factor = getattr(row, "item_name"), getattr(row, "big_unit"), pd.to_numeric(getattr(row, "unit_factor"), errors="coerce")
        if pd.isna(item) or pd.isna(big) or pd.isna(factor):
            continue
        via = getattr(row, "factor_unit", None)
        steps.setdefault(_folded(item), {})[_folded(big)] = (float(factor), None if via is None or pd.isna(via) else _folded(via))
    out: dict[tuple[str, str], float] = {}
    for item, units in steps.items():
        for unit in units:
            factor, via, seen = 1.0, unit, set()
            while via in units and via not in seen:
                seen.add(via)
                step, via = units[via]
                factor *= step
            out[(item, unit)] = factor
    return out


def _add_base_quantity(lines: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if "base_quantity" in lines.columns or "quantity" not in lines.columns:
        return lines
    scale = pd.Series(1.0, index=lines.index)
    if {"unit", "big_unit", "unit_factor"} <= set(lines.columns):
        big = lines["unit"].map(lambda cell: None if pd.isna(cell) else _folded(cell)) == lines["big_unit"].map(lambda cell: None if pd.isna(cell) else _folded(cell))
        scale = pd.to_numeric(lines["unit_factor"], errors="coerce").fillna(1).where(big, 1.0)
    factors = _conversions(tables)
    if factors and {"item_name", "unit"} <= set(lines.columns):
        named = [factors.get((_folded(item), _folded(unit))) for item, unit in zip(lines["item_name"], lines["unit"])]
        scale = pd.Series(named, index=lines.index, dtype=float).fillna(scale)
    return lines.assign(base_quantity=lines["quantity"] * scale)


def _mark_returns(lines: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if "order_id" not in lines.columns:
        return lines
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


def _add_staff(lines: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Tên thợ viết tắt trên sổ đổi về họ tên trong bảng nhân viên khi tên cuối khớp đúng một người."""
    if "staff" not in lines.columns:
        return lines
    for name, frame in tables.items():
        if name.startswith("staff") and "staff" in frame.columns:
            by_last: dict[str, list[str]] = {}
            for full in frame["staff"].dropna().unique():
                by_last.setdefault(_folded(full).split()[-1], []).append(str(full))

            def resolve(cell: Any) -> Any:
                if pd.isna(cell):
                    return cell
                short = STAFF_PREFIX.sub("", _folded(cell)).strip()
                found = by_last.get(short.split()[-1]) if short else None
                return found[0] if found and len(found) == 1 else cell

            return lines.assign(staff=lines["staff"].map(resolve))
    return lines


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


def _add_catalog_attributes(lines: pd.DataFrame, tables: dict[str, pd.DataFrame], concepts: dict[str, dict[str, str]]) -> pd.DataFrame:
    """Hãng và số, size lấy từ danh mục theo tên hàng, trống ở danh mục thì không xếp vào đâu."""
    out = lines
    for table, found in concepts.items():
        frame = tables.get(table)
        if frame is None or "item_name" not in frame.columns:
            continue
        donor = frame.dropna(subset=["item_name"]).drop_duplicates("item_name").set_index("item_name")
        for concept, target in (("item_brand", "brand"), ("item_size", "size_label")):
            if concept in found:
                out = out.assign(**{target: out["item_name"].map(donor[found[concept]])})
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
        out["is_item_line"] = ~not_item
    return out


class Shop(*DOMAIN_MIXINS):
    """Một shop đã chuẩn hoá nhìn từ một ngày as_of: bảng lines, orders và các số đo theo rulebook."""

    def __init__(self, root: Path | str, *, as_of: str, calendar: str) -> None:
        self.clock = Clock(as_of, calendar=load_calendar(calendar))
        loaded = _tables(Path(root))
        concepts_file = Path(root) / "concepts.json"
        self._concepts: dict[str, dict[str, str]] = json.loads(concepts_file.read_text(encoding="utf-8")) if concepts_file.exists() else {}
        picked = _pick_lines(loaded)
        self.tables = Tables({name: _visible(frame, self.clock.as_of) for name, frame in loaded.items()})
        self.lines: pd.DataFrame | None = None
        self.orders: pd.DataFrame | None = None
        self._big_units: dict[tuple[str, str], float] | None = None
        if picked is not None:
            lines = _mark_returns(_add_keys(_add_catalog_attributes(_add_staff(_add_customers(_add_catalog(_split_addons(picked), loaded), loaded), loaded), loaded, self._concepts), loaded), self.tables)
            visible = pd.to_datetime(lines["order_date"]).dt.normalize() <= pd.Timestamp(self.clock.as_of)
            self.lines = lines[visible].reset_index(drop=True)
            self.orders = self._orders() if "order_id" in self.lines.columns else None

    def _require_period(self, period: Period) -> None:
        """Kỳ hỏi nằm hẳn ngoài khoảng ngày có dữ liệu bán thì shop không có dữ liệu cho kỳ đó."""
        if self.lines is None or not len(self.lines):
            return
        first = pd.to_datetime(self.lines["order_date"]).min().date()
        if period.end < first or period.start > self.clock.as_of:
            raise ValueError(f"shop has no sales data in {period.start}..{period.end}, data runs {first}..{self.clock.as_of}: check the period matches the question, answer is unanswerable only if the question asks exactly this period")

    def _require_orders(self) -> None:
        if self.lines is not None and "order_id" not in self.lines.columns:
            raise ValueError("shop has no order id: answer is unanswerable if the question needs it")

    def _orders(self) -> pd.DataFrame:
        kept = [column for column in ORDER_COLUMNS if column in self.lines.columns]
        grouped = self.lines.groupby("order_id", sort=False)
        items = self.lines[self.lines["is_item_line"]] if "is_item_line" in self.lines.columns else self.lines
        revenue = items.groupby("order_id")["line_amount"].sum()
        first = grouped[kept].first()
        return first.assign(revenue=revenue.reindex(first.index).fillna(0)).reset_index()

    def _match(self, frame: pd.DataFrame, *, key: str, value: Any) -> pd.Series:
        column = "customer_name" if key == "customer" and "customer_name" in frame.columns else FILTER_COLUMNS[key]
        if column not in frame.columns:
            raise ValueError(f"shop has no column for {key}: answer is unanswerable if the question needs it")
        folded = frame[column].map(lambda cell: None if pd.isna(cell) else _folded(cell))
        wanted = _folded(self._staff_code(value) if key == "staff" else value)
        exact = folded.isin(next((group for group in FILTER_SYNONYMS.get(key, ()) if wanted in group), (wanted,)))
        if exact.any():
            return exact
        partial = folded.map(lambda cell: cell is not None and wanted in cell)
        if partial.any():
            same_model = folded.map(lambda cell: cell is not None and re.search(rf"(?<!\w){re.escape(wanted)}(?:$|\s+\d)", cell) is not None)
            return same_model if same_model.any() else partial
        everywhere = self.lines[column].dropna().map(_folded) if self.lines is not None and column in self.lines.columns else pd.Series(dtype=object)
        if everywhere.map(lambda cell: wanted == cell or wanted in cell).any():
            return pd.Series(False, index=frame.index)
        known = sorted({str(cell) for cell in (self.lines[column].dropna() if self.lines is not None and column in self.lines.columns else frame[column].dropna())})
        close = difflib.get_close_matches(str(value), known, n=CLOSE_MATCHES, cutoff=0.5)
        groups = sorted({str(cell) for cell in self.lines["item_group"].dropna()}) if key == "item" and self.lines is not None and "item_group" in self.lines.columns else []
        tip = f", if this is a group use group= with one of {groups}" if groups else ""
        raise ValueError(f"no {key} matches {value!r}, closest are {close}{tip}, values are {known[:LOOKUP_LIMIT]}")

    def _has_concepts(self, *concepts: str) -> bool:
        return any(all(name in found for name in concepts) and table in self.tables for table, found in self._concepts.items())

    def _tables_with(self, concept: str) -> tuple[str, ...]:
        return tuple(table for table, found in self._concepts.items() if concept in found and table in self.tables)

    def _book_named(self, table: str, *concepts: str) -> pd.DataFrame:
        found = self._concepts[table]
        return self.tables[table].rename(columns={found[name]: name for name in concepts})

    def _book(self, *concepts: str) -> pd.DataFrame:
        """Bảng đầu tiên có đủ các khái niệm, cột đổi tên theo khái niệm."""
        for table, found in self._concepts.items():
            if all(name in found for name in concepts) and table in self.tables:
                return self._book_named(table, *concepts)
        raise ValueError(f"shop has no {', '.join(concepts)}: answer is unanswerable if the question needs it")

    def _column_of(self, concept: str, frame: pd.DataFrame) -> str:
        for found in self._concepts.values():
            if concept in found and found[concept] in frame.columns:
                return found[concept]
        raise ValueError(f"shop has no {concept}: answer is unanswerable if the question needs it")

    def domains(self) -> tuple[str, ...]:
        """Các ngành shop này có đủ khái niệm."""
        return tuple(name for name, needed in DOMAIN_REQUIREMENTS.items() if self._has_concepts(*needed))

    def _staff_code(self, value: Any) -> Any:
        wanted = _folded(value)
        for name, frame in self.tables.items():
            if name.startswith("staff") and "staff" in frame.columns:
                for column in frame.columns.difference(["staff", "source_file", "source_sheet", "source_row"]):
                    hits = frame[frame[column].map(lambda cell: not pd.isna(cell) and _folded(cell) == wanted)]
                    if len(hits):
                        return hits["staff"].iloc[0]
        return value

    def _rows(self) -> pd.DataFrame:
        if self.lines is None:
            raise ValueError("shop has no sales table, use tables[...]")
        return self.lines

    def _select(self, frame: pd.DataFrame, *, period: Period | None, shift: str | None, filters: dict[str, Any]) -> pd.DataFrame:
        filters = {BY_ALIASES.get(key, key): value for key, value in filters.items()}
        unknown = set(filters) - set(FILTER_COLUMNS) - {"size", "prescription", "min_amount"}
        if unknown:
            raise ValueError(f"unknown filters {sorted(unknown)}, allowed {sorted(FILTER_COLUMNS)}, size, prescription, min_amount and shift")
        out = frame
        if period is not None:
            self._require_period(period)
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
            if key == "size" and "size_label" in out.columns:
                wanted = _folded(value).removeprefix("size ")
                out = out[out["size_label"].map(lambda cell: not pd.isna(cell) and _folded(cell).removeprefix("size ") == wanted)]
            elif key == "size":
                pattern = re.compile(rf"(\({re.escape(str(value))}\)\s*$|\bsize\s+{re.escape(str(value))}\b)", re.IGNORECASE)
                out = out[out["item_name"].map(lambda cell: not pd.isna(cell) and pattern.search(str(cell)) is not None)]
            elif key == "min_amount":
                out = out[pd.to_numeric(out["line_amount"], errors="coerce") >= value]
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
        self._require_orders()
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
        self._require_orders()
        rows = self._select(self._rows(), period=period, shift=None, filters={}).drop_duplicates("order_id")
        return round(100 * float((rows["status_norm"] == "huỷ").sum()) / len(rows), 2) if len(rows) else 0.0

    def ranking(self, *, by: str, metric: str = "revenue", period: Period | None = None, shift: str | None = None, min_orders: int = 1, **filters: Any) -> pd.Series:
        """Bảng xếp hạng giảm dần. by: item, group, customer, staff, channel, payment, day, hour, brand. metric: revenue, quantity, orders, days, cancelled, average_order."""
        by = BY_ALIASES.get(by, by)
        if by not in ("day",) and by not in FILTER_COLUMNS:
            raise ValueError(f"unknown by {by!r}, allowed day and {sorted(FILTER_COLUMNS)}")
        column = "order_date" if by == "day" else "item_key" if by == "item" else FILTER_COLUMNS[by]
        if metric in ("orders", "cancelled", "average_order"):
            self._require_orders()
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
        if metric == "average_order":
            sums, counts = grouped["line_amount"].sum(), grouped["order_id"].nunique()
            result = (sums / counts)[counts >= min_orders]
        elif metric == "revenue":
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
            names = self._display_names(column, "item_name", "catalog")
            ranked.index = [names.get(key, key) for key in ranked.index]
        if by == "day":
            ranked.index = pd.to_datetime(ranked.index).strftime("%Y-%m-%d")
        if by == "customer":
            names = self._display_names(column, "customer_name", "customers") if "customer_name" in self.lines.columns else None
            if names is not None:
                ranked.index = [names.get(key, key) for key in ranked.index]
        ranked.index.name = by
        return ranked

    @functools.lru_cache(maxsize=None)
    def _display_names(self, key: str, column: str, kind: str) -> pd.Series:
        """Cách ghi đưa vào đáp án cho mỗi khoá, tính một lần trên toàn bộ `lines`."""
        official = frozenset(str(cell) for table, frame in self.tables.items() if table.startswith(kind) and column in frame.columns for cell in frame[column].dropna())
        return self.lines.dropna(subset=[key, column]).groupby(key)[column].agg(lambda cells: display_name(cells, official))

    def _line_cost(self, rows: pd.DataFrame) -> pd.Series:
        if "unit_cost" not in rows.columns:
            raise ValueError("shop has no cost on sales lines: answer is unanswerable if the question needs it")
        return pd.to_numeric(rows["quantity"], errors="coerce") * pd.to_numeric(rows["unit_cost"], errors="coerce")

    def cancelled_orders(self, period: Period | None = None) -> int:
        """Số đơn trạng thái huỷ đặt trong kỳ."""
        self._require_orders()
        rows = self._select(self._rows(), period=period, shift=None, filters={})
        return int(rows.loc[rows["status_norm"] == "huỷ", "order_id"].nunique())

    def main_supplier(self, period: Period | None = None) -> str:
        """Nhà cung cấp chính: nhiều phiếu nhập nhất trong kỳ, bỏ phiếu huỷ; khác nhà cung cấp nhập nhiều tiền nhất."""
        rows = self._purchase_lines()
        if period is not None:
            rows = rows[(rows["day"] >= pd.Timestamp(period.start)) & (rows["day"] <= pd.Timestamp(period.end))]
        if not {"supplier", "document_id"} <= set(rows.columns):
            raise ValueError("shop has no supplier or purchase document: answer is unanswerable if the question needs it")
        counts = rows.groupby("supplier")["document_id"].nunique()
        return pd.DataFrame({"value": counts, "tie": counts.index.astype(str)}).sort_values(["value", "tie"], ascending=[False, True]).index[0]

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
            if EXPENSE_TABLE.search(_folded(name)):
                dates = [column for column in frame.columns if _folded(column) in EXPENSE_DATES]
                money = [column for column in frame.columns if _folded(column) in EXPENSE_AMOUNTS]
                if dates and money:
                    days = frame[dates[0]].map(parse_datetime).map(lambda moment: pd.NaT if moment is None else pd.Timestamp(moment).normalize())
                    keep = (days >= pd.Timestamp(period.start)) & (days <= pd.Timestamp(period.end))
                    return int(pd.to_numeric(frame.loc[keep, money[0]], errors="coerce").sum())
        raise ValueError("shop has no expense book: answer is unanswerable if the question needs it")

    def net_profit(self, period: Period) -> int:
        """Lãi ròng: lãi gộp của kỳ trừ mọi khoản trong sổ chi phí của kỳ."""
        return self.gross_profit(period) - self.expenses(period)

    def customer_count(self, period: Period | None = None, *, min_orders: int = 1, **filters: Any) -> int:
        """Số khách có ít nhất min_orders đơn tính doanh thu trong kỳ, không tính khách lẻ."""
        self._require_orders()
        rows = self._sold(period, None, filters).dropna(subset=["customer_key"])
        return int((rows.groupby("customer_key")["order_id"].nunique() >= min_orders).sum())

    def item_count(self, period: Period | None = None, *, min_orders: int = 1, **filters: Any) -> int:
        """Số mặt hàng có mặt trong ít nhất min_orders đơn tính doanh thu của kỳ."""
        self._require_orders()
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

    def price_raise_date(self, item: str, price: float) -> str:
        """Ngày đầu tiên mặt hàng tăng lên đúng mức giá, theo bảng giá."""
        wanted = _folded(item)
        book = self._book("price_date", "price_value")
        if "item_name" in book.columns:
            names = book["item_name"]
        else:
            lookup = {code: name for frame in self.tables.values() if {"item_code", "item_name"} <= set(frame.columns) for code, name in zip(frame["item_code"], frame["item_name"])}
            names = book["item_code"].map(lookup)
        rows = book[names.map(lambda cell: not pd.isna(cell) and _folded(cell) == wanted)]
        rows = rows.assign(value=pd.to_numeric(rows["price_value"], errors="coerce"), when=rows["price_date"].map(parse_datetime).map(pd.Timestamp)).sort_values("when")
        raised = rows[(rows["value"] == price) & (rows["value"] > rows["value"].shift())]
        if raised.empty:
            raise ValueError(f"no price rise of {item!r} to {price} in the price list")
        return raised["when"].iloc[0].strftime("%Y-%m-%d")

    def price_effect(self, item: str, day: str | None = None, *, days: int, price: float | None = None) -> float:
        """Phần trăm đổi số lượng N ngày kể từ ngày đổi giá so với N ngày ngay trước; không biết ngày thì cho price."""
        start = date.fromisoformat(day if day is not None else self.price_raise_date(item, price))
        after = Period(start=start, end=start + timedelta(days=days - 1))
        before = Period(start=start - timedelta(days=days), end=start - timedelta(days=1))
        return pct_change(self.quantity(after, item=item), self.quantity(before, item=item))

    def _purchase_lines(self) -> pd.DataFrame:
        frames = {name: frame for name, frame in self.tables.items() if name.startswith("purchases")}
        detail = next((frame for frame in frames.values() if "quantity" in frame.columns and ({"unit_cost", "line_amount"} & set(frame.columns))), None)
        if detail is None:
            detail = next((frame for frame in frames.values() if "quantity" in frame.columns and "lo" not in name_tokens(frame)), None)
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
        unit_cost = pd.to_numeric(out["unit_cost"], errors="coerce") if "unit_cost" in out.columns else pd.Series(float("nan"), index=out.index)
        cost = pd.to_numeric(out["line_amount"], errors="coerce") if "line_amount" in out.columns else quantity * unit_cost
        return out.assign(quantity=quantity, purchase_amount=cost, day=pd.to_datetime(out["record_date"], errors="coerce").dt.normalize())

    def avg_purchase_price(self, period: Period, *, item: str) -> int:
        """Giá nhập bình quân theo số lượng nhập, theo đơn vị nhập, bỏ phiếu huỷ."""
        rows = self._purchase_lines()
        rows = rows[(rows["day"] >= pd.Timestamp(period.start)) & (rows["day"] <= pd.Timestamp(period.end))]
        rows = rows[self._match(rows, key="item", value=item)]
        if rows.empty or rows["quantity"].sum() == 0:
            raise ValueError(f"no purchase of {item!r} in {period}")
        return int(rows["purchase_amount"].sum() / rows["quantity"].sum() + 0.5)

    def debt_aged(self, day: str | date | Period | None = None, min_days: int = 0, max_days: int | None = None) -> int:
        """Còn nợ lúc hết ngày của các đơn có tuổi nợ từ min_days đến max_days, tuổi tính từ ngày đặt."""
        limit = pd.Timestamp(day.end if isinstance(day, Period) else day if day is not None else self.clock.as_of)
        debt = self._debt_left(limit, None)
        age = (limit - debt["order_day"]).dt.days
        keep = (debt["left"] > 0) & (age >= min_days)
        if max_days is not None:
            keep &= age <= max_days
        return int(debt.loc[keep, "left"].sum())

    def debtor_count(self, day: str | date | None = None) -> int:
        """Số khách còn nợ lúc hết ngày, không tính khách lẻ."""
        return len(self.debtors(day))

    def debtors(self, day: str | date | Period | None = None) -> pd.Series:
        """Còn nợ theo khách lúc hết ngày, giảm dần, không tính khách lẻ."""
        limit = pd.Timestamp(day.end if isinstance(day, Period) else day if day is not None else self.clock.as_of)
        left = self._debt_left(limit, None)
        left = left[(left["left"] > 0) & left["customer_key"].notna()]
        totals = left.groupby("customer_key")["left"].sum()
        names = left.groupby("customer_key")["customer_name"].first() if "customer_name" in left.columns else totals.index.to_series()
        ranked = pd.DataFrame({"value": totals, "tie": totals.index.astype(str)}).sort_values(["value", "tie"], ascending=[False, True])["value"]
        ranked.index = [names.get(key, key) for key in ranked.index]
        return ranked.astype(int)

    def _stock_levels(self, day: str | date | None = None) -> pd.DataFrame:
        """Tồn từng mặt hàng lúc hết ngày theo đơn vị cơ bản: cộng dồn thẻ kho, hoặc bảng tồn, hoặc nhập trừ bán."""
        limit = pd.Timestamp(day if day is not None else self.clock.as_of)
        for frame in self.tables.values():
            if {"item_code", "base_quantity", "NgayGioPhatSinh"} <= set(frame.columns):
                moments = frame["NgayGioPhatSinh"].map(parse_datetime).map(lambda moment: pd.NaT if moment is None else pd.Timestamp(moment).normalize())
                totals = pd.to_numeric(frame.loc[moments <= limit, "base_quantity"], errors="coerce").groupby(frame["item_code"]).sum()
                return pd.DataFrame({"key": totals.index.map(_folded), "stock": totals.values})
        for frame in self.tables.values():
            if "stock" in frame.columns and ({"item_name", "item_code"} & set(frame.columns)):
                key = "item_name" if "item_name" in frame.columns else "item_code"
                return pd.DataFrame({"key": frame[key].map(_folded), "stock": pd.to_numeric(frame["stock"], errors="coerce")}).dropna(subset=["key"])
        return self._stock_from_purchases(limit)

    def _stock_from_purchases(self, limit: pd.Timestamp) -> pd.DataFrame:
        bought = self._purchase_lines()
        bought = bought[bought["day"] <= limit]
        factors = _conversions(self.tables)
        units = bought["unit"] if "unit" in bought.columns else pd.Series("", index=bought.index)
        base = [quantity * factors.get((_folded(name), _folded(unit)), self._big_factor(name, unit)) for quantity, name, unit in zip(bought["quantity"], bought["item_name"], units)]
        rows = self._rows()
        sold = rows[rows["is_revenue"] & (pd.to_datetime(rows["order_date"]).dt.normalize() <= limit)]
        total = pd.Series(base, index=bought.index).groupby(bought["item_name"].map(_folded)).sum().subtract(sold.groupby(sold["item_name"].map(_folded))["base_quantity"].sum(), fill_value=0)
        return pd.DataFrame({"key": total.index, "stock": total.values})

    def _stock_key(self, item: str, levels: pd.DataFrame) -> pd.Series:
        rows = self._rows()
        matched = rows[self._match(rows, key="item", value=item)]
        keys = set(matched["item_name"].map(_folded))
        if "item_code" in matched.columns:
            keys |= set(matched["item_code"].dropna().map(_folded))
        return levels["key"].isin(keys)

    def stock(self, *, item: str, day: str | date | None = None) -> float:
        """Tồn của mặt hàng lúc hết ngày theo đơn vị cơ bản."""
        levels = self._stock_levels(day)
        total = levels.loc[self._stock_key(item, levels), "stock"].sum()
        return int(total) if float(total).is_integer() else float(total)

    def stock_big(self, *, item: str, day: str | date | None = None) -> list[int]:
        """Tồn theo đơn vị lớn: [số đơn vị lớn nguyên, số đơn vị cơ bản lẻ]."""
        rows = self._rows()
        matched = rows[self._match(rows, key="item", value=item)]
        factor = pd.to_numeric(matched["unit_factor"], errors="coerce").dropna() if "unit_factor" in matched.columns else pd.Series(dtype=float)
        if factor.empty:
            raise ValueError(f"no big unit factor for {item!r}: read the conversion table in tables[...]")
        whole, rest = divmod(int(self.stock(item=item, day=day)), int(factor.iloc[0]))
        return [whole, rest]

    def stock_value(self, day: str | date | None = None) -> int:
        """Giá trị hàng tồn: tồn từng hàng nhân giá vốn trong danh mục, chỉ tính hàng còn tồn."""
        levels = self._stock_levels(day)
        levels = levels[levels["stock"] > 0]
        for name, frame in self.tables.items():
            if name.startswith("catalog") and "unit_cost" in frame.columns and ({"item_code", "item_name"} & set(frame.columns)):
                key = "item_code" if "item_code" in frame.columns and levels["key"].isin(frame["item_code"].dropna().map(_folded)).any() else "item_name"
                cost = pd.to_numeric(frame["unit_cost"], errors="coerce").groupby(frame[key].map(_folded)).first()
                return int(round((levels["stock"] * levels["key"].map(cost).fillna(0)).sum()))
        raise ValueError("shop has no catalog cost: answer is unanswerable if the question needs it")

    def purchase_minus_sold(self, period: Period, *, item: str) -> float:
        """Số lượng nhập trừ số lượng của đơn tính doanh thu trong kỳ, cùng đơn vị cơ bản."""
        total = self.purchase_quantity(period, item=item) - self.quantity(period, item=item)
        return int(total) if float(total).is_integer() else float(total)

    def purchase_quantity(self, period: Period, *, item: str) -> float:
        """Số lượng nhập trong kỳ theo đơn vị cơ bản, bỏ phiếu huỷ."""
        rows = self._purchase_lines()
        rows = rows[(rows["day"] >= pd.Timestamp(period.start)) & (rows["day"] <= pd.Timestamp(period.end))]
        rows = rows[self._match(rows, key="item", value=item)]
        factors = _conversions(self.tables)
        unit = rows["unit"] if "unit" in rows.columns else pd.Series("", index=rows.index)
        bought = sum(quantity * factors.get((_folded(name), _folded(label)), self._big_factor(name, label)) for quantity, name, label in zip(rows["quantity"], rows["item_name"], unit))
        return int(bought) if float(bought).is_integer() else float(bought)

    def _big_factor(self, name: Any, unit: Any) -> float:
        if self._big_units is None:
            rows = self._rows()
            kept = rows.dropna(subset=["item_name", "big_unit", "unit_factor"]).drop_duplicates("item_name") if {"big_unit", "unit_factor"} <= set(rows.columns) else rows.iloc[0:0]
            self._big_units = {(_folded(item), _folded(big)): float(factor) for item, big, factor in zip(kept.get("item_name", ()), kept.get("big_unit", ()), kept.get("unit_factor", ()))}
        return self._big_units.get((_folded(name), _folded(unit)), 1.0)

    def unsold_count(self, period: Period) -> int:
        """Số mặt hàng ế: đã bán trước kỳ nhưng trong kỳ không có đơn tính doanh thu nào."""
        rows = self._rows()
        rows = rows[rows["is_revenue"] & ~self._service_fee(rows)]
        days = pd.to_datetime(rows["order_date"]).dt.normalize()
        before = set(rows.loc[days < pd.Timestamp(period.start), "item_key"].dropna())
        during = set(rows.loc[(days >= pd.Timestamp(period.start)) & (days <= pd.Timestamp(period.end)), "item_key"].dropna())
        return len(before - during)

    def due_orders(self, period: Period | None = None, *, after: str | date | None = None) -> int:
        """Số đơn bán nợ đã đặt đến hôm nay, không huỷ, có ngày phải trả trong kỳ hoặc sau một ngày."""
        for frame in self.tables.values():
            if {"order_id", "due_date"} <= set(frame.columns):
                visible = self.orders[self.orders["status_norm"] != "huỷ"]["order_id"]
                due = frame[frame["order_id"].isin(visible)]
                days = pd.to_datetime(due["due_date"], errors="coerce").dt.normalize()
                keep = pd.Series(True, index=due.index)
                if period is not None:
                    keep &= (days >= pd.Timestamp(period.start)) & (days <= pd.Timestamp(period.end))
                if after is not None:
                    keep &= days > pd.Timestamp(after)
                return int(due.loc[keep, "order_id"].nunique())
        raise ValueError("shop has no due date column: answer is unanswerable if the question needs it")

    def best_month(self, periods: list[Period]) -> str:
        """Tháng doanh thu cao nhất trong các kỳ cho trước, dạng YYYY-MM."""
        return max(periods, key=self.revenue).start.strftime("%Y-%m")

    def sold_orders(self, period: Period | None = None, *, shift: str | None = None, **filters: Any) -> pd.DataFrame:
        """Các đơn tính vào doanh thu trong kỳ, mỗi dòng một đơn, có cột revenue của cả đơn."""
        self._require_orders()
        return self.orders[self.orders["order_id"].isin(self._sold(period, shift, filters)["order_id"])].reset_index(drop=True)

    def _receipts(self) -> pd.DataFrame:
        for name, frame in self.tables.items():
            if name.startswith("receipts") and {"order_id", "record_date", "amount"} <= set(frame.columns):
                days = pd.to_datetime(frame["record_date"]).dt.normalize()
                return frame.assign(paid_day=days)
        raise ValueError("shop has no receipts table: read the debt book in tables[...]")

    def _debt_left(self, limit: pd.Timestamp, customer: str | None) -> pd.DataFrame:
        if self._has_concepts("debt_paid_date") or self._has_concepts("installment_terms"):
            return self._ledger_left(limit, customer)
        debt = self._debt_orders(customer)
        debt = debt[debt["order_day"] <= limit]
        if "note" in debt.columns and debt["note"].notna().any() and not any(name.startswith("receipts") for name in self.tables):
            return debt.assign(left=[_note_left(note, total) if not pd.isna(note) else total for note, total in zip(debt["note"], debt["order_total"])])
        receipts = self._receipts()
        paid = receipts[receipts["paid_day"] <= limit].groupby("order_id")["amount"].sum()
        return debt.assign(left=debt["order_total"] - debt["order_id"].map(paid).fillna(0))

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

    def debt_at(self, day: str | date | Period | None = None, *, customer: str | None = None) -> int:
        """Còn nợ lúc hết ngày: cộng phần chưa trả của các đơn còn nợ > 0, từ đầu dữ liệu."""
        limit = pd.Timestamp(day.end if isinstance(day, Period) else day if day is not None else self.clock.as_of)
        left = self._debt_left(limit, customer)["left"]
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


def increasing(values: list[float]) -> bool:
    """Mỗi số đều lớn hơn số liền trước."""
    return all(left < right for left, right in zip(values, values[1:]))


def pct_change(new: float, old: float) -> float:
    """Phần trăm thay đổi so với kỳ cũ, giảm ra số âm, làm tròn 2 chữ số."""
    if old == 0:
        raise ValueError("old value is 0, percent change undefined")
    return round((new - old) / old * 100, 2)
