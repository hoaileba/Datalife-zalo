from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import pandas as pd

CODE_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = CODE_ROOT.parent
REPO_ROOT = EXPERIMENT_ROOT.parents[1]
SHOP = "dev_005"
DATA_DIR = REPO_ROOT / "public_test" / "data" / SHOP
QUESTIONS_PATH = DATA_DIR / "questions.jsonl"
ANSWERS_PATH = EXPERIMENT_ROOT / "out" / "answers" / f"{SHOP}.jsonl"
SALES_SHEET = "DonHang_ChiTiet"
SALES_HEADER_ROW = 3
CATALOG_FILE = "DanhSachSanPham.xlsx"
DRUG_FILE = "DanhSachThuoc.xlsx"
CONVERSION_FILE = "DanhSachQuyDoi.xlsx"
LOT_FILE = "DonHang_Lo.xlsx"

sys.path.insert(0, str(CODE_ROOT))

from datamate import Clock, Period, fmt, fold_key, parse_date, parse_money, parse_number, read_table, squeeze  # noqa: E402
from datamate.tabio import fill_group  # noqa: E402

WALK_IN_KEYS = frozenset({"khach le", "le", "kl"})
DONE_STATUSES = frozenset({"ok", "Đã giao"})
CANCELLED_STATUSES = frozenset({"hủy", "Đã huỷ"})
RETURNED_STATUSES = frozenset({"trả lại", "Trả hàng"})
IN_TRANSIT_STATUSES = frozenset({"Đang xử lý"})
QTY_HEAD = re.compile(r"^(-?[\d.,]+)")
RATIO_WITH_UNIT = re.compile(r"^([\d.,]+)\s+(\S.*)$")


class Catalog:
    """Danh mục 80 mặt hàng của nhà thuốc: mã, đơn vị cơ bản, nhóm hàng, hoạt chất, kê đơn."""

    def __init__(self, data_dir: Path) -> None:
        products = read_table(data_dir / CATALOG_FILE, header_row=0)
        drugs = read_table(data_dir / DRUG_FILE, header_row=0)
        ratios = read_table(data_dir / CONVERSION_FILE, header_row=0)
        self._sku_of_fold: dict[str, str] = {}
        self._name: dict[str, str] = {}
        self._base_unit: dict[str, str] = {}
        self._group: dict[str, str] = {}
        for _, row in products.iterrows():
            sku = squeeze(row["Mã SKU"])
            name = squeeze(row["Tên sản phẩm"])
            self._name[sku] = name
            self._base_unit[sku] = squeeze(row["Đơn vị"])
            self._group[sku] = squeeze(row["Loại sản phẩm"])
            self._sku_of_fold[fold_key(name)] = sku
        self._substance: dict[str, str] = {}
        self._prescription: dict[str, bool] = {}
        for _, row in drugs.iterrows():
            sku = squeeze(row["Mã SKU"])
            if sku not in self._name:
                raise ValueError(f"drug sku not in catalog: {sku}")
            self._substance[sku] = squeeze(row["Hoạt chất"])
            self._prescription[sku] = squeeze(row["Thuốc kê đơn"]).casefold() in {"true", "1"}
        self._factor: dict[tuple[str, str], float] = {}
        raw_ratio: dict[str, dict[str, tuple[float, str | None]]] = {}
        for _, row in ratios.iterrows():
            sku = self.sku_of(squeeze(row["Tên sản phẩm"]))
            unit = squeeze(row["Đơn vị quy đổi"])
            base = squeeze(row["Đơn vị cơ bản"])
            if base != self._base_unit[sku]:
                raise ValueError(f"conversion base unit disagrees with catalog for {sku}")
            text = squeeze(row["Tỉ lệ quy đổi"])
            with_unit = RATIO_WITH_UNIT.match(text)
            if with_unit is None:
                raw_ratio.setdefault(sku, {})[unit] = (float(parse_number(text)), None)
            else:
                raw_ratio.setdefault(sku, {})[unit] = (float(parse_number(with_unit.group(1))), squeeze(with_unit.group(2)))
        for sku, table in raw_ratio.items():
            for unit in table:
                self._factor[(sku, unit)] = self._resolve(sku, unit, table, set())

    def _resolve(self, sku: str, unit: str, table: dict[str, tuple[float, str | None]], seen: set[str]) -> float:
        if unit == self._base_unit[sku]:
            return 1.0
        if unit in seen:
            raise ValueError(f"cyclic conversion for {sku}: {unit}")
        if unit not in table:
            raise ValueError(f"unknown unit {unit} for {sku}")
        value, reference = table[unit]
        if reference is None:
            return value
        return value * self._resolve(sku, reference, table, seen | {unit})

    def sku_of(self, name: str) -> str:
        key = fold_key(name)
        if key not in self._sku_of_fold:
            raise ValueError(f"product not in catalog: {name}")
        return self._sku_of_fold[key]

    def name_of(self, sku: str) -> str:
        return self._name[sku]

    def base_unit(self, sku: str) -> str:
        return self._base_unit[sku]

    def group_of(self, sku: str) -> str:
        return self._group[sku]

    def substance_of(self, sku: str) -> str:
        return self._substance.get(sku, "")

    def is_prescription(self, sku: str) -> bool:
        return self._prescription.get(sku, False)

    def to_base(self, sku: str, unit: str) -> float:
        if unit == self._base_unit[sku]:
            return 1.0
        key = (sku, unit)
        if key not in self._factor:
            raise ValueError(f"no conversion for {sku} unit {unit}")
        return self._factor[key]

    def skus(self) -> tuple[str, ...]:
        return tuple(sorted(self._name))


def status_bucket(raw: str) -> str:
    if raw in DONE_STATUSES:
        return "hoàn thành"
    if raw in CANCELLED_STATUSES:
        return "huỷ"
    if raw in RETURNED_STATUSES:
        return "trả hàng"
    if raw in IN_TRANSIT_STATUSES:
        return "đang giao"
    raise ValueError(f"unknown order status: {raw}")


def load_sales(data_dir: Path, catalog: Catalog) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(data_dir.glob("BanHang_Thang*.xlsx")):
        frame = read_table(path, sheet=SALES_SHEET, header_row=SALES_HEADER_ROW)
        frame["source_file"] = path.name
        frames.append(frame)
    if not frames:
        raise ValueError("no sales files found")
    merged = pd.concat(frames, ignore_index=True)
    merged = fill_group(merged, ["Mã đơn hàng", "Ngày đặt hàng", "Trạng thái đơn hàng", "Tên khách hàng"])
    out = pd.DataFrame()
    out["order_id"] = merged["Mã đơn hàng"].map(squeeze)
    out["order_date"] = merged["Ngày đặt hàng"].map(parse_date)
    out["status"] = merged["Trạng thái đơn hàng"].map(squeeze).map(status_bucket)
    out["customer"] = merged["Tên khách hàng"].map(squeeze)
    out["customer_key"] = out["customer"].map(fold_key)
    out["is_walk_in"] = out["customer_key"].isin(WALK_IN_KEYS)
    out["product_name"] = merged["Tên sản phẩm"].map(squeeze)
    out["sku"] = out["product_name"].map(catalog.sku_of)
    out["line_unit"] = merged["Đơn vị tính"].map(squeeze)
    out["quantity"] = merged["Số lượng sản phẩm"].map(_quantity_value)
    out["unit_price"] = merged["Giá sản phẩm"].map(parse_money)
    out["amount"] = merged["Tổng tiền"].map(parse_money)
    out["base_quantity"] = [q * catalog.to_base(s, u) for q, s, u in zip(out["quantity"], out["sku"], out["line_unit"])]
    if out["order_date"].isna().any() or out["amount"].isna().any():
        raise ValueError("sales rows with unparsable date or amount")
    return out


def _quantity_value(raw: Any) -> float:
    text = squeeze(raw)
    head = QTY_HEAD.match(text)
    if head is None:
        raise ValueError(f"unparsable quantity: {text!r}")
    value = parse_number(head.group(1))
    if value is None:
        raise ValueError(f"unparsable quantity: {text!r}")
    return float(value)


class Sales:
    """Mọi phép tính doanh thu, đơn, khách của dev_005, đã áp luật §1 và luật ngày as_of."""

    def __init__(self, lines: pd.DataFrame, catalog: Catalog) -> None:
        self._lines = lines
        self._catalog = catalog
        self.first_day: date = lines["order_date"].min()
        self.last_day: date = lines["order_date"].max()

    @property
    def lines(self) -> pd.DataFrame:
        return self._lines

    @property
    def catalog(self) -> Catalog:
        return self._catalog

    def visible(self, clock: Clock) -> pd.DataFrame:
        return self._lines[self._lines["order_date"] <= clock.as_of]

    def in_period(self, clock: Clock, period: Period, *, revenue_only: bool = True) -> pd.DataFrame:
        frame = self.visible(clock)
        frame = frame[(frame["order_date"] >= period.start) & (frame["order_date"] <= period.end)]
        if revenue_only:
            frame = frame[frame["status"].isin({"hoàn thành", "đang giao"})]
        return frame

    def revenue(self, clock: Clock, period: Period) -> int:
        return fmt.money(self.in_period(clock, period)["amount"].sum())

    def order_count(self, clock: Clock, period: Period) -> int:
        return int(self.in_period(clock, period)["order_id"].nunique())

    def order_revenue(self, clock: Clock, period: Period) -> pd.Series:
        return self.in_period(clock, period).groupby("order_id")["amount"].sum()

    def daily_revenue(self, clock: Clock, period: Period) -> pd.Series:
        return self.in_period(clock, period).groupby("order_date")["amount"].sum()

    def cancelled_orders(self, clock: Clock, period: Period) -> int:
        frame = self.in_period(clock, period, revenue_only=False)
        return int(frame[frame["status"] == "huỷ"]["order_id"].nunique())

    def all_orders(self, clock: Clock, period: Period) -> int:
        return int(self.in_period(clock, period, revenue_only=False)["order_id"].nunique())

    def customer_orders(self, clock: Clock, period: Period) -> pd.Series:
        frame = self.in_period(clock, period)
        frame = frame[~frame["is_walk_in"]]
        return frame.groupby("customer")["order_id"].nunique()

    def customer_revenue(self, clock: Clock, period: Period) -> pd.Series:
        frame = self.in_period(clock, period)
        frame = frame[~frame["is_walk_in"]]
        return frame.groupby("customer")["amount"].sum()

    def sku_revenue(self, clock: Clock, period: Period) -> pd.Series:
        return self.in_period(clock, period).groupby("sku")["amount"].sum()

    def sku_base_quantity(self, clock: Clock, period: Period) -> pd.Series:
        return self.in_period(clock, period).groupby("sku")["base_quantity"].sum()

    def revenue_where(self, clock: Clock, period: Period, predicate: Callable[[str], bool]) -> int:
        frame = self.in_period(clock, period)
        mask = frame["sku"].map(predicate)
        return fmt.money(frame[mask]["amount"].sum())


def percent_change(current: float, baseline: float) -> float:
    if baseline == 0:
        raise ValueError("baseline is zero, percent change undefined")
    return fmt.percent((current - baseline) / baseline * 100.0)


def top_by(series: pd.Series, *, key_order: Callable[[str], Any] | None = None, limit: int = 1) -> tuple[str, ...]:
    order = key_order or (lambda k: k)
    ranked = sorted(series.items(), key=lambda kv: (-float(kv[1]), order(kv[0])))
    return tuple(name for name, _ in ranked[:limit])


def price_jump_effect(sales: Sales, clock: Clock, product: str, jump_day: date, window: int) -> float:
    sku = sales.catalog.sku_of(product)
    after = Period(start=jump_day, end=jump_day + timedelta(days=window - 1))
    before = Period(start=jump_day - timedelta(days=window), end=jump_day - timedelta(days=1))
    totals: list[float] = []
    for period in (after, before):
        frame = sales.in_period(clock, period)
        totals.append(float(frame[frame["sku"] == sku]["base_quantity"].sum()))
    return percent_change(totals[0], totals[1])


def ratio_of_customers_with_min_orders(sales: Sales, clock: Clock, period: Period, minimum: int) -> float:
    counts = sales.customer_orders(clock, period)
    if len(counts) == 0:
        raise ValueError("no identified customers in period")
    return fmt.percent(float((counts >= minimum).sum()) / float(len(counts)) * 100.0)


def orders_with_group(sales: Sales, clock: Clock, period: Period, group: str) -> int:
    frame = sales.in_period(clock, period)
    mask = frame["sku"].map(lambda s: sales.catalog.group_of(s) == group)
    return int(frame[mask]["order_id"].nunique())


def group_revenue_share(sales: Sales, clock: Clock, period: Period, group: str) -> float:
    total = sales.revenue(clock, period)
    part = sales.revenue_where(clock, period, lambda s: sales.catalog.group_of(s) == group)
    return fmt.percent(float(part) / float(total) * 100.0)


def build_answers(sales: Sales, questions: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    catalog = sales.catalog
    lines: list[dict[str, Any]] = []

    def clock_of(question_id: str) -> Clock:
        for question in questions:
            if question["id"] == question_id:
                return Clock(question["as_of_date"])
        raise ValueError(f"question not found: {question_id}")

    def money_answer(question_id: str, period_of: Callable[[Clock], Period]) -> None:
        clock = clock_of(question_id)
        lines.append(fmt.answer_line(question_id, "number", sales.revenue(clock, period_of(clock))))

    def count_answer(question_id: str, period_of: Callable[[Clock], Period]) -> None:
        clock = clock_of(question_id)
        lines.append(fmt.answer_line(question_id, "number", sales.order_count(clock, period_of(clock))))

    def average_order_answer(question_id: str, period_of: Callable[[Clock], Period]) -> None:
        clock = clock_of(question_id)
        period = period_of(clock)
        revenue = sales.revenue(clock, period)
        count = sales.order_count(clock, period)
        lines.append(fmt.answer_line(question_id, "number", fmt.money(revenue / count)))

    def change_answer(question_id: str, current_of: Callable[[Clock], Period], baseline_of: Callable[[Clock], Period]) -> None:
        clock = clock_of(question_id)
        current = sales.revenue(clock, current_of(clock))
        baseline = sales.revenue(clock, baseline_of(clock))
        lines.append(fmt.answer_line(question_id, "percent", percent_change(current, baseline)))

    def prescription_money(question_id: str, period_of: Callable[[Clock], Period], *, prescribed: bool) -> None:
        clock = clock_of(question_id)
        value = sales.revenue_where(clock, period_of(clock), lambda s: catalog.is_prescription(s) == prescribed)
        lines.append(fmt.answer_line(question_id, "number", value))

    def prescription_share(question_id: str, period_of: Callable[[Clock], Period]) -> None:
        clock = clock_of(question_id)
        period = period_of(clock)
        part = sales.revenue_where(clock, period, catalog.is_prescription)
        total = sales.revenue(clock, period)
        lines.append(fmt.answer_line(question_id, "percent", fmt.percent(float(part) / float(total) * 100.0)))

    def substance_money(question_id: str, period_of: Callable[[Clock], Period], substance: str) -> None:
        clock = clock_of(question_id)
        value = sales.revenue_where(clock, period_of(clock), lambda s: catalog.substance_of(s) == substance)
        lines.append(fmt.answer_line(question_id, "number", value))

    def product_money(question_id: str, period_of: Callable[[Clock], Period], product: str) -> None:
        clock = clock_of(question_id)
        sku = catalog.sku_of(product)
        value = sales.revenue_where(clock, period_of(clock), lambda s: s == sku)
        lines.append(fmt.answer_line(question_id, "number", value))

    def days_at_least(question_id: str, period_of: Callable[[Clock], Period], threshold: int) -> None:
        clock = clock_of(question_id)
        daily = sales.daily_revenue(clock, period_of(clock))
        lines.append(fmt.answer_line(question_id, "number", int((daily >= threshold).sum())))

    def best_day(question_id: str, period_of: Callable[[Clock], Period]) -> None:
        clock = clock_of(question_id)
        daily = sales.daily_revenue(clock, period_of(clock))
        ranked = sorted(daily.items(), key=lambda kv: (-float(kv[1]), kv[0]))
        lines.append(fmt.answer_line(question_id, "date", fmt.day_answer(ranked[0][0])))

    def orders_at_least(question_id: str, period_of: Callable[[Clock], Period], threshold: int) -> None:
        clock = clock_of(question_id)
        totals = sales.order_revenue(clock, period_of(clock))
        lines.append(fmt.answer_line(question_id, "number", int((totals >= threshold).sum())))

    def top_customer_by_orders(question_id: str, period_of: Callable[[Clock], Period]) -> None:
        clock = clock_of(question_id)
        counts = sales.customer_orders(clock, period_of(clock))
        lines.append(fmt.answer_line(question_id, "string", top_by(counts)[0]))

    def top_customer_by_money(question_id: str, period_of: Callable[[Clock], Period], limit: int) -> None:
        clock = clock_of(question_id)
        totals = sales.customer_revenue(clock, period_of(clock))
        names = top_by(totals, limit=limit)
        if limit == 1:
            lines.append(fmt.answer_line(question_id, "string", names[0]))
        else:
            lines.append(fmt.answer_line(question_id, "list", list(names)))

    def customers_with_min_orders(question_id: str, period_of: Callable[[Clock], Period], minimum: int) -> None:
        clock = clock_of(question_id)
        counts = sales.customer_orders(clock, period_of(clock))
        lines.append(fmt.answer_line(question_id, "number", int((counts >= minimum).sum())))

    def share_customers_with_min_orders(question_id: str, period_of: Callable[[Clock], Period], minimum: int) -> None:
        clock = clock_of(question_id)
        lines.append(fmt.answer_line(question_id, "percent", ratio_of_customers_with_min_orders(sales, clock, period_of(clock), minimum)))

    def month_series(question_id: str, months: Sequence[tuple[int, int]]) -> None:
        clock = clock_of(question_id)
        values = [sales.revenue(clock, clock.month(month, year)) for year, month in months]
        lines.append(fmt.answer_line(question_id, "list", values))

    def best_month(question_id: str, months: Sequence[tuple[int, int]]) -> None:
        clock = clock_of(question_id)
        scored = [((year, month), sales.revenue(clock, clock.month(month, year))) for year, month in months]
        ranked = sorted(scored, key=lambda kv: (-kv[1], kv[0]))
        lines.append(fmt.answer_line(question_id, "date", fmt.month_answer(ranked[0][0])))

    def strictly_increasing(question_id: str, months: Sequence[tuple[int, int]]) -> None:
        clock = clock_of(question_id)
        values = [sales.revenue(clock, clock.month(month, year)) for year, month in months]
        rising = all(later > earlier for earlier, later in zip(values, values[1:]))
        lines.append(fmt.answer_line(question_id, "boolean", rising))

    def best_in_group(question_id: str, period_of: Callable[[Clock], Period], group: str) -> None:
        clock = clock_of(question_id)
        totals = sales.sku_revenue(clock, period_of(clock))
        inside = totals[[catalog.group_of(s) == group for s in totals.index]]
        best = top_by(inside)[0]
        lines.append(fmt.answer_line(question_id, "string", catalog.name_of(best)))

    def group_money(question_id: str, period_of: Callable[[Clock], Period], group: str) -> None:
        clock = clock_of(question_id)
        value = sales.revenue_where(clock, period_of(clock), lambda s: catalog.group_of(s) == group)
        lines.append(fmt.answer_line(question_id, "number", value))

    def group_share(question_id: str, period_of: Callable[[Clock], Period], group: str) -> None:
        clock = clock_of(question_id)
        lines.append(fmt.answer_line(question_id, "percent", group_revenue_share(sales, clock, period_of(clock), group)))

    def cancelled_count(question_id: str, period_of: Callable[[Clock], Period]) -> None:
        clock = clock_of(question_id)
        lines.append(fmt.answer_line(question_id, "number", sales.cancelled_orders(clock, period_of(clock))))

    def cancelled_share(question_id: str, period_of: Callable[[Clock], Period]) -> None:
        clock = clock_of(question_id)
        period = period_of(clock)
        total = sales.all_orders(clock, period)
        cancelled = sales.cancelled_orders(clock, period)
        lines.append(fmt.answer_line(question_id, "percent", fmt.percent(float(cancelled) / float(total) * 100.0)))

    this_month = lambda clock: clock.this_month()
    last_week = lambda clock: clock.last_week()
    this_week = lambda clock: clock.this_week()
    ytd = lambda clock: clock.year_to_date()

    def month_of(year: int, month: int) -> Callable[[Clock], Period]:
        return lambda clock: clock.month(month, year)

    def last_days(n: int) -> Callable[[Clock], Period]:
        return lambda clock: clock.last_n_days(n)

    money_answer("q_03bee605bf7f", month_of(2025, 10))
    money_answer("q_32235635199c", month_of(2025, 1))
    money_answer("q_7f8c9bee1754", month_of(2025, 6))
    money_answer("q_83107c3303b5", last_week)
    money_answer("q_8fafcdce942f", ytd)
    money_answer("q_60f97553a06e", ytd)
    money_answer("q_7672cf2a7ca9", ytd)
    money_answer("q_8eacb946fa1a", last_days(7))
    money_answer("q_bff16856342f", this_week)

    count_answer("q_037178b58fcc", ytd)
    count_answer("q_9a905959d8ff", ytd)
    count_answer("q_f8715dcf6ad0", ytd)
    count_answer("q_38b56b8238b5", last_days(7))
    count_answer("q_f0bb331484b7", last_days(7))
    count_answer("q_b3c75e9f2c97", last_week)

    average_order_answer("q_0dff1966b7c3", last_week)
    average_order_answer("q_5aad27b686f6", last_week)
    average_order_answer("q_a0b76dd10f70", last_week)
    average_order_answer("q_3ed8a306be83", month_of(2026, 3))
    average_order_answer("q_4eb97c2cc49a", month_of(2026, 2))
    average_order_answer("q_c011cf38470d", month_of(2025, 11))

    change_answer("q_01d1099489a0", this_month, lambda clock: clock.last_month_same_days())
    change_answer("q_1473ee8c46fd", this_month, lambda clock: clock.last_month_same_days())
    change_answer("q_4633acb03075", this_month, lambda clock: clock.last_month_same_days())
    change_answer("q_21c1f1a2bf98", month_of(2026, 2), month_of(2025, 2))
    change_answer("q_2362d5a2c101", month_of(2026, 4), month_of(2025, 4))
    change_answer("q_5e570feb5c4c", month_of(2026, 3), month_of(2025, 3))
    change_answer("q_c65b4afeafd1", month_of(2025, 5), month_of(2025, 4))
    change_answer("q_fc4f06f3006b", month_of(2025, 6), month_of(2025, 5))

    cancelled_count("q_44ae4ba9010d", month_of(2025, 5))
    cancelled_count("q_6cd986ac9717", month_of(2025, 2))
    cancelled_count("q_cc69cb411f24", month_of(2025, 10))
    cancelled_share("q_34e7f4ed662a", month_of(2025, 8))
    cancelled_share("q_e6ffb654ce0b", this_month)

    prescription_money("q_05421814d0e3", this_month, prescribed=True)
    prescription_money("q_62cb89435b45", month_of(2025, 6), prescribed=True)
    prescription_money("q_9692709e7d81", month_of(2025, 11), prescribed=True)
    prescription_money("q_105bc863feea", month_of(2026, 4), prescribed=False)
    prescription_money("q_107e86e608dc", month_of(2025, 6), prescribed=False)
    prescription_money("q_b9c6ed02f53d", month_of(2026, 1), prescribed=False)
    prescription_share("q_0da15db21978", month_of(2025, 5))
    prescription_share("q_a1195f9fe04c", month_of(2025, 7))
    prescription_share("q_9498d6b37278", this_month)

    substance_money("q_632bc2910cb3", month_of(2025, 7), "Povidon iod")
    substance_money("q_8caa49a3fc7d", this_month, "Vitamin C")
    substance_money("q_fda16d2c768c", this_month, "Paracetamol + Phenylephrin + Clorpheniramin")

    product_money("q_5b50ea8b0bae", month_of(2025, 2), "Savi Losartan 50mg hộp 3 vỉ x 10 viên")
    product_money("q_da623a004480", month_of(2025, 3), "Prednisolon 5mg Boston chai 500 viên")

    best_in_group("q_1fafcc702c72", month_of(2026, 2), "vitamin khoáng chất")
    best_in_group("q_47d9c87fa49d", month_of(2026, 2), "mắt mũi họng")
    group_money("q_d5157cc4acfe", month_of(2025, 10), "mắt mũi họng")
    group_share("q_978b7f61250e", month_of(2025, 11), "thực phẩm chức năng")
    group_share("q_c0d31d97c743", month_of(2025, 11), "ho cảm cúm")

    clock_dung_ngoai = clock_of("q_8ef1f824e97e")
    lines.append(
        fmt.answer_line(
            "q_8ef1f824e97e",
            "number",
            orders_with_group(sales, clock_dung_ngoai, clock_dung_ngoai.month(1, 2026), "dùng ngoài"),
        )
    )

    days_at_least("q_69cc1e2a87ca", month_of(2025, 3), 10_000_000)
    days_at_least("q_827cb0083082", month_of(2026, 1), 9_300_000)
    days_at_least("q_a010ef0a217f", month_of(2026, 3), 11_000_000)
    best_day("q_2199b91fe707", month_of(2025, 3))
    best_day("q_a418a876f69f", month_of(2025, 9))

    orders_at_least("q_7f61dbb4d934", month_of(2025, 8), 40_000)
    orders_at_least("q_a1deeb0f213d", month_of(2025, 12), 130_000)
    orders_at_least("q_c8c553b90c18", month_of(2026, 3), 42_000)

    top_customer_by_orders("q_382bb57c049d", month_of(2025, 3))
    top_customer_by_orders("q_89d88aa1eae8", month_of(2025, 9))
    top_customer_by_orders("q_f18a6235b749", month_of(2025, 4))
    top_customer_by_money("q_81ad9f46a16d", last_week, 5)
    top_customer_by_money("q_e39bf5fd32c6", this_week, 1)
    share_customers_with_min_orders("q_15dd37187b0d", month_of(2025, 6), 4)
    share_customers_with_min_orders("q_409bb74c67b4", month_of(2025, 6), 6)
    share_customers_with_min_orders("q_5529c849e209", month_of(2025, 5), 6)
    customers_with_min_orders("q_4812f4775924", month_of(2025, 3), 6)
    customers_with_min_orders("q_6066d5e1f466", month_of(2025, 12), 6)
    customers_with_min_orders("q_ca85266e5cfa", month_of(2026, 3), 6)

    month_series("q_3af7b33f08a6", ((2025, 11), (2025, 12), (2026, 1)))
    month_series("q_7d043dbd4908", ((2025, 7), (2025, 8), (2025, 9)))
    month_series("q_be70a1626009", ((2026, 2), (2026, 3), (2026, 4)))
    best_month("q_8c680cbcf6b0", ((2025, 4), (2025, 5), (2025, 6)))
    best_month("q_d62189fd9ee2", ((2025, 3), (2025, 4), (2025, 5)))
    strictly_increasing("q_766d53528ee4", ((2025, 2), (2025, 3), (2025, 4)))
    strictly_increasing("q_f4a5eee7f524", ((2025, 1), (2025, 2), (2025, 3)))

    clock_quantity = clock_of("q_cd3203f2d813")
    nurofen = catalog.sku_of("Nurofen for Children hỗn dịch chai 60ml")
    nurofen_qty = sales.in_period(clock_quantity, clock_quantity.month(9, 2025))
    lines.append(
        fmt.answer_line(
            "q_cd3203f2d813",
            "number",
            fmt.quantity(float(nurofen_qty[nurofen_qty["sku"] == nurofen]["base_quantity"].sum())),
        )
    )

    clock_top5 = clock_of("q_4dff582efe40")
    quantities = sales.sku_base_quantity(clock_top5, clock_top5.last_week())
    best_sellers = top_by(quantities, limit=5)
    lines.append(fmt.answer_line("q_4dff582efe40", "list", [catalog.name_of(s) for s in best_sellers]))

    lines.append(
        fmt.answer_line(
            "q_0ea6fdb19b86",
            "percent",
            price_jump_effect(sales, clock_of("q_0ea6fdb19b86"), "Efticol 0,9% lốc 10 lọ x 10ml", date(2026, 1, 26), 30),
        )
    )
    lines.append(
        fmt.answer_line(
            "q_18d3b12b578f",
            "percent",
            price_jump_effect(sales, clock_of("q_18d3b12b578f"), "Tiffy Dey hộp 25 vỉ x 4 viên", date(2025, 6, 2), 14),
        )
    )
    lines.append(
        fmt.answer_line(
            "q_378a68e7ff82",
            "percent",
            price_jump_effect(sales, clock_of("q_378a68e7ff82"), "Tiffy Dey hộp 25 vỉ x 4 viên", date(2025, 10, 16), 30),
        )
    )

    lines.append(
        fmt.answer_line(
            "q_1bd68f25b288",
            "unanswerable",
            reason="file bán hàng chỉ ghi ngày đặt, không có giờ tạo đơn nên không xác định được khung giờ cao điểm",
        )
    )
    lines.append(
        fmt.answer_line(
            "q_576830198619",
            "unanswerable",
            reason="shop không ghi giới tính khách, chỉ có tên khách trên đơn",
        )
    )
    return tuple(lines)


def load_questions(path: Path) -> tuple[dict[str, Any], ...]:
    with path.open(encoding="utf-8") as handle:
        return tuple(json.loads(line) for line in handle if line.strip())


def main() -> None:
    catalog = Catalog(DATA_DIR)
    sales = Sales(load_sales(DATA_DIR, catalog), catalog)
    questions = load_questions(QUESTIONS_PATH)
    answers = build_answers(sales, questions)
    answered = {line["id"] for line in answers}
    missing = [q["id"] for q in questions if q["id"] not in answered]
    extra = sorted(answered - {q["id"] for q in questions})
    if missing:
        raise ValueError(f"questions without an answer: {missing}")
    if extra:
        raise ValueError(f"answers for unknown questions: {extra}")
    if len(answers) != len(questions):
        raise ValueError(f"answer count {len(answers)} != question count {len(questions)}")
    order = {q["id"]: i for i, q in enumerate(questions)}
    ANSWERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ANSWERS_PATH.open("w", encoding="utf-8") as handle:
        for line in sorted(answers, key=lambda a: order[a["id"]]):
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    buckets: dict[str, int] = {}
    for line in answers:
        buckets[line["type"]] = buckets.get(line["type"], 0) + 1
    print(f"{SHOP}: {len(answers)} answers -> {ANSWERS_PATH}")
    print("types:", dict(sorted(buckets.items())))
    print("data range:", sales.first_day, "..", sales.last_day)


if __name__ == "__main__":
    main()
