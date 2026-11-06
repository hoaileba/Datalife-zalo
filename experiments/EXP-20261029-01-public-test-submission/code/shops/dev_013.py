from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from datamate import Clock, Period, fmt, fold_key, parse_datetime, parse_money, parse_number, read_table
from datamate.fmt import load_questions, write_answers
from datamate.tabio import drop_repeated_header_rows, drop_subtotal_rows, sheet_names

SHOP = "dev_013"
EXPERIMENT_ROOT = CODE_ROOT.parent
DATA_DIR = Path("/Users/lebahoai/Workspace/zalo/2026/public_test/data") / SHOP
QUESTIONS_PATH = DATA_DIR / "questions.jsonl"
ANSWERS_PATH = EXPERIMENT_ROOT / "out" / "answers" / f"{SHOP}.jsonl"
SALES_PATHS = (DATA_DIR / "BanHang_2025.xlsx", DATA_DIR / "BanHang_2026.xlsx")
ADMIN_PATH = DATA_DIR / "QuanLy.xlsx"

SALES_HEADER_ROW = 1
ORDER_KEY = "HĐ"
RAW_SALES_COLUMNS = ("ĐG", "TT", "SL", "ĐVT", "Tên hàng", "HĐ", "Ngày", "Khách", "Kênh", "Ghi chú")

KIND_ITEM = "item"
KIND_VOUCHER = "voucher"
KIND_POINTS = "points"
KIND_SHIP = "ship"
POINTS_PATTERN = re.compile(r"^Dùng (\d+) điểm$")
POINT_VALUE = 100

STATUS_DONE = "hoàn thành"
STATUS_CANCELLED = "huỷ"
STATUS_SHIPPING = "đang giao"
STATUS_BY_NOTE = {
    "": STATUS_DONE,
    "cancel": STATUS_CANCELLED,
    "huỷ": STATUS_CANCELLED,
    "đang giao": STATUS_SHIPPING,
    "chưa giao": STATUS_SHIPPING,
}
REVENUE_STATUSES = frozenset({STATUS_DONE, STATUS_SHIPPING})

WALK_IN = "Khách lẻ"
CHANNEL_STORE = "Tại tiệm"
CHANNEL_ZALO = "Zalo"
CHANNEL_MARKETPLACE = "Sàn TMĐT"

GROUP_DIAPER = "bỉm tã"
GROUP_FORMULA = "sữa bột"
GROUP_HOUSEHOLD = "đồ dùng"
GROUP_BOTTLE = "bình sữa"

DAY_MONTH_ONLY = re.compile(r"^\d{1,2}/\d{1,2}$")
CONVERSION_PART = re.compile(r"^1\s+(\S+)\s*=\s*(\d+)\s+(\S+)$")

DATA_START = date(2025, 5, 1)
DATA_END = date(2026, 6, 30)


def _text(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _money(value: Any) -> int:
    parsed = parse_money(value)
    if parsed is None:
        raise ValueError(f"unparseable money: {value!r}")
    return parsed


def _sale_date(value: Any, *, sheet_year: int) -> date:
    text = _text(value)
    if DAY_MONTH_ONLY.match(text):
        value = f"{text}/{sheet_year}"
    moment = parse_datetime(value)
    if moment is None:
        raise ValueError(f"unparseable sale date: {value!r}")
    return moment.date()


def _line_kind(name: str) -> str:
    if name == "Voucher":
        return KIND_VOUCHER
    if name == "Phí ship":
        return KIND_SHIP
    if POINTS_PATTERN.match(name):
        return KIND_POINTS
    return KIND_ITEM


def _read_sales_sheet(path: Path, sheet: str) -> pd.DataFrame:
    frame = read_table(path, sheet=sheet, header_row=SALES_HEADER_ROW, header_rows=1)
    missing = [c for c in RAW_SALES_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"sales sheet {sheet} missing columns: {missing}")
    frame = frame[list(RAW_SALES_COLUMNS)].copy()
    frame["sheet"] = sheet
    frame["sheet_year"] = int(sheet[-4:])
    return frame


def load_raw_sales() -> pd.DataFrame:
    frames = [_read_sales_sheet(path, sheet) for path in SALES_PATHS for sheet in sheet_names(path)]
    frame = pd.concat(frames, ignore_index=True)
    frame = drop_subtotal_rows(frame, key_columns=[ORDER_KEY])
    return drop_repeated_header_rows(frame)


def dedupe_within_order(frame: pd.DataFrame) -> pd.DataFrame:
    """Rulebook §8: dòng trùng mọi ô trong cùng một hoá đơn là lỗi xuất file."""
    return frame.drop_duplicates(subset=list(RAW_SALES_COLUMNS)).reset_index(drop=True)


def load_catalog() -> pd.DataFrame:
    frame = read_table(ADMIN_PATH, sheet="DanhMuc", header_row=0)
    frame = frame.copy()
    frame["key"] = frame["Tên hàng"].map(fold_key)
    if frame["key"].duplicated().any():
        raise ValueError("duplicate catalog names")
    frame["number_size"] = frame["Số / Size"].map(_text)
    frame["brand"] = frame["Hãng"].map(_text)
    frame["group"] = frame["Nhóm"].map(_text)
    frame["base_unit"] = frame["ĐVT"].map(_text)
    return frame.reset_index(drop=True)


def unit_factors(catalog: pd.DataFrame) -> dict[tuple[str, str], int]:
    factors: dict[tuple[str, str], int] = {}
    for key, base, rule in zip(catalog["key"], catalog["base_unit"], catalog["Quy đổi"]):
        factors[(key, base)] = 1
        for part in _text(rule).split(";"):
            part = part.strip()
            if not part:
                continue
            match = CONVERSION_PART.match(part)
            if match is None or match.group(3) != base:
                raise ValueError(f"unparseable conversion: {part!r}")
            factors[(key, match.group(1))] = int(match.group(2))
    return factors


def build_lines(raw: pd.DataFrame, catalog: pd.DataFrame) -> pd.DataFrame:
    lines = dedupe_within_order(raw).copy()
    lines["name"] = lines["Tên hàng"].map(_text)
    lines["kind"] = lines["name"].map(_line_kind)
    lines["amount"] = lines["TT"].map(_money)
    items = lines["kind"] == KIND_ITEM
    lines["sale_date"] = None
    lines.loc[items, "sale_date"] = [
        _sale_date(v, sheet_year=y) for v, y in zip(lines.loc[items, "Ngày"], lines.loc[items, "sheet_year"])
    ]
    head = lines[items].groupby(ORDER_KEY, sort=False).agg(
        order_date=("sale_date", "first"),
        customer=("Khách", "first"),
        channel=("Kênh", "first"),
        note=("Ghi chú", lambda s: _text(s.dropna().iloc[0]).casefold() if s.notna().any() else ""),
        dates=("sale_date", "nunique"),
    )
    if (head["dates"] > 1).any():
        raise ValueError("order with more than one date")
    unknown = set(head["note"]) - set(STATUS_BY_NOTE)
    if unknown:
        raise ValueError(f"unknown status notes: {sorted(unknown)}")
    head["status"] = head["note"].map(STATUS_BY_NOTE)
    orphan_orders = set(lines[ORDER_KEY]) - set(head.index)
    if orphan_orders:
        raise ValueError(f"orders without item lines: {sorted(orphan_orders)[:5]}")
    lines = lines.join(head[["order_date", "customer", "channel", "status"]], on=ORDER_KEY)
    lines["key"] = lines["name"].map(fold_key)
    info = catalog.set_index("key")[["Tên hàng", "group", "brand", "number_size", "base_unit"]].rename(columns={"Tên hàng": "item"})
    lines = lines.join(info, on="key")
    item_lines = lines["kind"] == KIND_ITEM
    if lines.loc[item_lines, "item"].isna().any():
        raise ValueError("sold item not in catalog")
    factors = unit_factors(catalog)
    lines["qty"] = None
    qty: list[float] = []
    for key, unit, raw_qty in zip(lines.loc[item_lines, "key"], lines.loc[item_lines, "ĐVT"], lines.loc[item_lines, "SL"]):
        factor = factors.get((key, _text(unit)))
        if factor is None:
            raise ValueError(f"no conversion for {key!r} unit {unit!r}")
        number = parse_number(raw_qty)
        if number is None:
            raise ValueError(f"unparseable quantity: {raw_qty!r}")
        qty.append(number * factor)
    lines.loc[item_lines, "qty"] = qty
    return lines.reset_index(drop=True)


def load_customers() -> pd.DataFrame:
    frame = read_table(ADMIN_PATH, sheet="KhachHang", header_row=0).copy()
    frame["registered"] = frame["Ngày đăng ký"].map(lambda v: parse_datetime(v).date())
    return frame


def load_purchases() -> pd.DataFrame:
    frame = read_table(ADMIN_PATH, sheet="NhapHang", header_row=0).copy()
    frame["receipt_date"] = frame["Ngày"].map(lambda v: parse_datetime(v).date())
    frame["amount"] = frame["Thành tiền"].map(_money)
    return frame


class Book:
    """Sổ bán hàng đã làm sạch của tiệm mẹ và bé, cùng danh mục, khách và sổ nhập."""

    def __init__(self, lines: pd.DataFrame, *, customers: pd.DataFrame, purchases: pd.DataFrame) -> None:
        self.lines = lines
        self.customers = customers
        self.purchases = purchases

    def _in(self, frame: pd.DataFrame, period: Period, column: str = "order_date") -> pd.DataFrame:
        return frame[(frame[column] >= period.start) & (frame[column] <= period.end)]

    def revenue_items(self, period: Period) -> pd.DataFrame:
        frame = self.lines[(self.lines["kind"] == KIND_ITEM) & self.lines["status"].isin(REVENUE_STATUSES)]
        return self._in(frame, period)

    def revenue(self, period: Period) -> int:
        return int(self.revenue_items(period)["amount"].sum())

    def order_revenues(self, period: Period) -> pd.Series:
        return self.revenue_items(period).groupby(ORDER_KEY)["amount"].sum()

    def average_order_value(self, period: Period) -> int:
        orders = self.order_revenues(period)
        if orders.empty:
            raise ValueError(f"no orders in {period}")
        return fmt.money(orders.sum() / len(orders))

    def orders_at_least(self, period: Period, threshold: int) -> int:
        return int((self.order_revenues(period) >= threshold).sum())

    def days_at_least(self, period: Period, threshold: int) -> int:
        daily = self.revenue_items(period).groupby("order_date")["amount"].sum()
        return int((daily >= threshold).sum())

    def adjustment_total(self, period: Period, kind: str) -> int:
        frame = self.lines[(self.lines["kind"] == kind) & self.lines["status"].isin(REVENUE_STATUSES)]
        return abs(int(self._in(frame, period)["amount"].sum()))

    def group_revenue(self, period: Period, group: str) -> int:
        frame = self.revenue_items(period)
        if group not in set(self.lines["group"].dropna()):
            raise ValueError(f"unknown group: {group}")
        return int(frame[frame["group"] == group]["amount"].sum())

    def channel_revenue(self, period: Period, channel: str) -> int:
        frame = self.revenue_items(period)
        if channel not in set(self.lines["channel"].dropna()):
            raise ValueError(f"unknown channel: {channel}")
        return int(frame[frame["channel"] == channel]["amount"].sum())

    def formula_units(self, period: Period, number: str) -> pd.Series:
        frame = self.revenue_items(period)
        frame = frame[(frame["group"] == GROUP_FORMULA) & (frame["number_size"] == number)]
        return frame.groupby("brand")["qty"].sum()

    def diaper_units(self, period: Period) -> pd.DataFrame:
        frame = self.revenue_items(period)
        return frame[frame["group"] == GROUP_DIAPER]

    def diaper_size_units(self, period: Period, size: str) -> float:
        frame = self.diaper_units(period)
        return float(frame[frame["number_size"] == size]["qty"].sum())

    def diaper_share(self, period: Period, *, size: str | None = None, brand: str | None = None) -> float:
        frame = self.diaper_units(period)
        total = float(frame["qty"].sum())
        if total == 0:
            raise ValueError(f"no diapers sold in {period}")
        part = frame
        if size is not None:
            part = part[part["number_size"] == size]
        if brand is not None:
            if brand not in set(frame["brand"]):
                raise ValueError(f"unknown diaper brand: {brand}")
            part = part[part["brand"] == brand]
        return fmt.percent(100.0 * float(part["qty"].sum()) / total)

    def item_units(self, period: Period, catalog_name: str) -> float:
        frame = self.revenue_items(period)
        return float(frame[frame["item"] == catalog_name]["qty"].sum())

    def stale_item_count(self, period: Period) -> int:
        sold = self.lines[(self.lines["kind"] == KIND_ITEM) & self.lines["status"].isin(REVENUE_STATUSES)]
        before = set(sold[sold["order_date"] < period.start]["item"])
        during = set(self._in(sold, period)["item"])
        return len(before - during)

    def top_customers(self, period: Period, k: int) -> tuple[str, ...]:
        frame = self.revenue_items(period)
        frame = frame[frame["customer"] != WALK_IN]
        totals = frame.groupby("customer")["amount"].sum().reset_index()
        totals = totals.sort_values(["amount", "customer"], ascending=[False, True])
        return tuple(totals["customer"].head(k))

    def new_members(self, period: Period) -> int:
        dates = self.customers["registered"]
        return int(((dates >= period.start) & (dates <= period.end)).sum())

    def main_supplier(self, period: Period) -> str:
        frame = self._in(self.purchases, period, "receipt_date")
        counts = frame.groupby("Nhà cung cấp")["Số phiếu"].nunique().reset_index()
        counts = counts.sort_values(["Số phiếu", "Nhà cung cấp"], ascending=[False, True])
        return str(counts.iloc[0]["Nhà cung cấp"])

    def top_supplier_by_amount(self, period: Period) -> str:
        frame = self._in(self.purchases, period, "receipt_date")
        totals = frame.groupby("Nhà cung cấp")["amount"].sum().reset_index()
        totals = totals.sort_values(["amount", "Nhà cung cấp"], ascending=[False, True])
        return str(totals.iloc[0]["Nhà cung cấp"])


def load_book() -> Book:
    catalog = load_catalog()
    lines = build_lines(load_raw_sales(), catalog)
    return Book(lines, customers=load_customers(), purchases=load_purchases())


def pct_change(current: float, previous: float) -> float:
    if previous == 0:
        raise ValueError("previous period is zero")
    return fmt.percent(100.0 * (current - previous) / previous)


def share(part: float, whole: float) -> float:
    if whole == 0:
        raise ValueError("share of zero")
    return fmt.percent(100.0 * part / whole)


def top_brand(units: pd.Series) -> str:
    frame = units.reset_index()
    frame.columns = ["brand", "qty"]
    frame = frame.sort_values(["qty", "brand"], ascending=[False, True])
    return str(frame.iloc[0]["brand"])


Answer = tuple[str, Any]
Solver = Callable[[Book, Clock], Answer]


def m(year: int, month: int, clock: Clock) -> Period:
    return clock.month(month, year)


def price_effect_period(start: date, days: int) -> tuple[Period, Period]:
    after = Period(start=start, end=start + timedelta(days=days - 1))
    before = Period(start=start - timedelta(days=days), end=start - timedelta(days=1))
    return after, before


CHEESE = "Phô mai Con Bò Cười hộp 8 miếng"
UNANSWERABLE_BRANCH = "shop không ghi chi nhánh hay địa chỉ khách; kênh chỉ có Tại tiệm, Zalo, Sàn TMĐT"
UNANSWERABLE_GENDER = "shop không ghi giới tính khách; KhachHang chỉ có tên, SĐT, tên bé, ngày đăng ký, điểm"


def _price_effect(book: Book, clock: Clock) -> Answer:
    after, before = price_effect_period(date(2025, 6, 7), 30)
    return ("percent", pct_change(book.item_units(after, CHEESE), book.item_units(before, CHEESE)))


SOLVERS: dict[str, Solver] = {
    "q_00c4e24fa228": lambda b, c: ("number", b.group_revenue(m(2026, 6, c), GROUP_HOUSEHOLD)),
    "q_07b7be37628b": lambda b, c: ("percent", pct_change(b.revenue(c.this_month()), b.revenue(c.last_month_same_days()))),
    "q_099a18d1ed60": lambda b, c: ("number", b.revenue(m(2025, 8, c))),
    "q_102720daf6a9": lambda b, c: ("number", b.revenue(c.year_to_date())),
    "q_14a10f251fd0": lambda b, c: ("string", top_brand(b.formula_units(m(2026, 3, c), "Số 2"))),
    "q_162c076a350d": lambda b, c: ("number", b.revenue(c.year_to_date())),
    "q_1af400957d96": lambda b, c: ("number", b.orders_at_least(m(2025, 5, c), 760_000)),
    "q_1c7bef344864": lambda b, c: ("number", b.adjustment_total(m(2026, 6, c), KIND_VOUCHER)),
    "q_1d7f8fb3a5df": lambda b, c: ("unanswerable", UNANSWERABLE_BRANCH),
    "q_1fc8004b6900": lambda b, c: ("number", fmt.quantity(b.formula_units(c.this_month(), "Số 4").sum())),
    "q_24a84f354ed0": lambda b, c: ("number", fmt.quantity(b.formula_units(c.this_month(), "Số 2").sum())),
    "q_2767f0fad8f7": lambda b, c: ("number", b.revenue(m(2026, 6, c))),
    "q_2dc771b39303": lambda b, c: ("number", b.days_at_least(m(2026, 6, c), 15_000_000)),
    "q_344459d9755f": lambda b, c: ("percent", pct_change(b.revenue(c.this_month()), b.revenue(c.last_month_same_days()))),
    "q_3e36677e62a9": lambda b, c: ("percent", share(b.group_revenue(m(2026, 6, c), GROUP_FORMULA), b.revenue(m(2026, 6, c)))),
    "q_4263ec258265": lambda b, c: ("number", b.average_order_value(m(2026, 6, c))),
    "q_4497ce0830d8": lambda b, c: ("number", b.adjustment_total(m(2026, 5, c), KIND_SHIP)),
    "q_48958d7402b0": lambda b, c: ("percent", pct_change(b.revenue(m(2026, 6, c)), b.revenue(m(2026, 5, c)))),
    "q_49a2ce6052b9": lambda b, c: ("number", fmt.quantity(b.diaper_size_units(m(2026, 5, c), "Size XL"))),
    "q_51b767a7dd05": _price_effect,
    "q_5355ac6722f8": lambda b, c: ("number", b.adjustment_total(m(2026, 6, c), KIND_SHIP)),
    "q_53b6abf6f47b": lambda b, c: ("number", b.average_order_value(c.last_week())),
    "q_5599ff7c9e28": lambda b, c: ("number", b.revenue(c.year_to_date())),
    "q_5cd8a3c09d08": lambda b, c: ("number", b.adjustment_total(m(2025, 12, c), KIND_VOUCHER)),
    "q_5fcac0749f24": lambda b, c: ("number", b.stale_item_count(c.last_n_days(7))),
    "q_6830bf77b8c5": lambda b, c: ("string", b.main_supplier(m(2025, 11, c))),
    "q_6c89c24d2349": lambda b, c: ("number", b.orders_at_least(m(2025, 7, c), 780_000)),
    "q_6d9ad1c46242": lambda b, c: ("number", b.revenue(c.last_week())),
    "q_77c3255f0d26": lambda b, c: ("number", b.adjustment_total(c.this_month(), KIND_VOUCHER)),
    "q_78f694893432": lambda b, c: ("number", fmt.quantity(b.diaper_size_units(c.this_month(), "Size L"))),
    "q_7d236c308111": lambda b, c: ("percent", b.diaper_share(c.this_month(), brand="Bobby")),
    "q_94a2e7ebecc0": lambda b, c: ("percent", b.diaper_share(c.this_month(), size="Size XL")),
    "q_95f39e8f5fd0": lambda b, c: ("percent", b.diaper_share(m(2026, 1, c), size="Size NB")),
    "q_9f57a164d2b7": lambda b, c: ("list", [b.revenue(m(2026, k, c)) for k in (1, 2, 3)]),
    "q_ab0d1507c71c": lambda b, c: ("percent", b.diaper_share(c.this_month(), brand="Moony")),
    "q_aea7033d3c8c": lambda b, c: ("list", [b.channel_revenue(m(2026, 5, c), CHANNEL_MARKETPLACE), b.channel_revenue(m(2026, 5, c), CHANNEL_ZALO)]),
    "q_b362a46fa102": lambda b, c: ("number", fmt.quantity(b.diaper_size_units(m(2026, 5, c), "Size M"))),
    "q_b5034a203b3b": lambda b, c: ("percent", pct_change(b.revenue(c.this_month()), b.revenue(c.last_month_same_days()))),
    "q_b6d81403be69": lambda b, c: ("number", b.group_revenue(m(2026, 6, c), GROUP_BOTTLE)),
    "q_ba2c318fc2be": lambda b, c: ("percent", share(b.channel_revenue(m(2025, 11, c), CHANNEL_STORE), b.revenue(m(2025, 11, c)))),
    "q_c4f79f600dc0": lambda b, c: ("number", b.revenue(c.last_n_days(30))),
    "q_c9c0246005b6": lambda b, c: ("number", b.days_at_least(m(2025, 9, c), 15_000_000)),
    "q_d0fb06a1ebb2": lambda b, c: ("unanswerable", UNANSWERABLE_GENDER),
    "q_d4d9ce010db3": lambda b, c: ("number", b.orders_at_least(m(2026, 6, c), 450_000)),
    "q_dae1955698d3": lambda b, c: ("number", b.adjustment_total(c.this_month(), KIND_SHIP)),
    "q_dbb9f4aff4c3": lambda b, c: ("number", b.adjustment_total(m(2026, 6, c), KIND_POINTS)),
    "q_dcd34fbf05f0": lambda b, c: ("percent", b.diaper_share(m(2026, 2, c), brand="Huggies")),
    "q_e36c0b269181": lambda b, c: ("number", b.new_members(m(2026, 5, c))),
    "q_e4641e459f38": lambda b, c: ("list", list(b.top_customers(c.last_week(), 5))),
    "q_ec9ca5f0dec1": lambda b, c: ("number", b.revenue(m(2025, 12, c))),
    "q_ed68b2a7cb63": lambda b, c: ("percent", b.diaper_share(c.this_month(), size="Size M")),
    "q_ee58dba4a73e": lambda b, c: ("number", b.average_order_value(c.last_week())),
    "q_ef32b18b17d5": lambda b, c: ("list", [b.revenue(m(2025, k, c)) for k in (5, 6, 7)]),
    "q_f83c96ab5362": lambda b, c: ("percent", share(b.channel_revenue(c.this_month(), CHANNEL_MARKETPLACE), b.revenue(c.this_month()))),
    "q_facbc1f20a16": lambda b, c: ("list", [b.revenue(m(2025, k, c)) for k in (9, 10, 11)]),
    "q_fe2a9de157ee": lambda b, c: ("number", b.days_at_least(m(2025, 12, c), 18_000_000)),
    "q_ffaf8aecc5ea": lambda b, c: ("number", b.average_order_value(c.last_week())),
}

ABSTAIN: frozenset[str] = frozenset()


def answer_all(book: Book) -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    for question in load_questions(QUESTIONS_PATH):
        qid = question["id"]
        if qid in ABSTAIN or qid not in SOLVERS:
            out.append(fmt.answer_line(qid, "abstain"))
            continue
        clock = Clock(question["as_of_date"])
        kind, value = SOLVERS[qid](book, clock)
        if kind == "unanswerable":
            out.append(fmt.answer_line(qid, "unanswerable", reason=value))
        else:
            out.append(fmt.answer_line(qid, kind, value))
    return tuple(out)


def main() -> None:
    book = load_book()
    lines = answer_all(book)
    written = write_answers(ANSWERS_PATH, lines)
    print(f"wrote {written} lines to {ANSWERS_PATH}")


if __name__ == "__main__":
    main()
