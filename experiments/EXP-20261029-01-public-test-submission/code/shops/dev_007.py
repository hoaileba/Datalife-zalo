from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from datamate import Clock, Period, census, drop_subtotal_rows, fmt, parse_date, parse_datetime, parse_money, parse_number, read_table

EXP_ROOT = CODE_ROOT.parent
DATA_DIR = CODE_ROOT.parents[2] / "public_test" / "data" / "dev_007"
QUESTIONS_PATH = DATA_DIR / "questions.jsonl"
ANSWERS_PATH = EXP_ROOT / "out" / "answers" / "dev_007.jsonl"

STATUS_MAP = {"Xong": "hoàn thành", "Đã hủy đơn": "huỷ", "Đã trả hàng": "trả hàng", "Đang xử lý": "đang giao"}
SERVICE_FEE_CODE = "SP0061"
CHANNEL_STORE = "store"
CHANNEL_ZALO = "zalo_oa"
CHANNEL_PHONE = "phone"
MONEY_COLUMNS = ("Thành tiền", "Đơn giá (đ)", "Tiền giảm", "Tổng tiền hàng", "Giảm giá HĐ", "Khách trả", "Còn nợ")
ORDER_COLUMNS = ("Tổng tiền hàng", "Giảm giá HĐ", "Khách trả", "Còn nợ", "Tiến độ", "Nguồn", "Nhân viên bán", "Mã khách mua", "Nhóm khách hàng", "moment", "day")


def load_invoice_lines() -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = read_table(DATA_DIR / "chi_tiet_hoa_don.csv", header_row=0)
    report: dict[str, Any] = {"census": census(raw, key_columns=["Mã bill"]), "rows_raw": len(raw)}
    body = drop_subtotal_rows(raw, key_columns=["Mã bill"])
    report["subtotal_rows"] = len(raw) - len(body)
    text_columns = list(body.columns)
    report["duplicate_rows_in_groups"] = int(body.duplicated(keep=False).sum())
    report["duplicate_extra_copies"] = int(body.duplicated().sum())
    report["duplicate_same_bill_and_no"] = int(body.duplicated(subset=["Mã bill", "No."]).sum())
    report["raw_sum_by_bill"] = body.assign(_v=body["Thành tiền"].map(parse_money)).groupby("Mã bill")["_v"].sum()
    deduped = body.drop_duplicates(subset=text_columns).reset_index(drop=True)
    others = [c for c in text_columns if c != "Mã bill"]
    report["identical_lines_across_bills"] = int(deduped.duplicated(subset=others).sum())
    lines = deduped.copy()
    for column in MONEY_COLUMNS:
        lines[column] = lines[column].map(parse_money)
        if lines[column].isna().any():
            raise ValueError(f"unparsed money in {column}")
    for column in ("Sluong", "Số lượng lẻ"):
        lines[column] = lines[column].map(parse_number)
        if lines[column].isna().any():
            raise ValueError(f"unparsed number in {column}")
    lines["moment"] = lines["Giờ bán"].map(parse_datetime)
    lines["day"] = lines["Ngày giao dịch"].map(parse_date)
    if lines["moment"].isna().any() or lines["day"].isna().any():
        raise ValueError("unparsed date in invoice lines")
    if (lines["moment"].map(lambda m: m.date()) != lines["day"]).any():
        raise ValueError("sale time and sale day disagree")
    unknown = set(lines["Tiến độ"]) - set(STATUS_MAP)
    if unknown:
        raise ValueError(f"unknown status: {unknown}")
    lines["status"] = lines["Tiến độ"].map(STATUS_MAP)
    return lines, report


def build_orders(lines: pd.DataFrame) -> pd.DataFrame:
    grouped = lines.groupby("Mã bill", sort=True)
    spread = grouped[list(ORDER_COLUMNS)].nunique(dropna=False)
    if (spread > 1).any().any():
        raise ValueError(f"order header varies inside bill: {spread.columns[(spread > 1).any()].tolist()}")
    orders = grouped.agg(
        goods=("Thành tiền", "sum"),
        header_goods=("Tổng tiền hàng", "first"),
        status=("status", "first"),
        channel=("Nguồn", "first"),
        staff=("Nhân viên bán", "first"),
        customer=("Mã khách mua", "first"),
        group=("Nhóm khách hàng", "first"),
        moment=("moment", "first"),
        day=("day", "first"),
    )
    orders["customer"] = orders["customer"].fillna("")
    orders["group"] = orders["group"].fillna("")
    orders["counted"] = ~orders["status"].isin(("huỷ", "trả hàng"))
    shift_clock = Clock(orders["day"].max())
    orders["shift"] = orders["moment"].map(lambda moment: shift_clock.shift_of(moment) or "")
    return orders


def load_catalog() -> pd.DataFrame:
    raw = read_table(DATA_DIR / "danh_muc_hang.csv", header_row=0)
    catalog = raw.copy()
    catalog["cost"] = catalog["Giá vốn"].map(parse_money)
    catalog["stock"] = catalog["Tồn cuối"].map(parse_number)
    return catalog.set_index("Mã SKU")


def load_imports() -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = read_table(DATA_DIR / "chi_tiet_nhap_hang.csv", header_row=0)
    report: dict[str, Any] = {"census": census(raw, key_columns=["Mã phiếu nhập"]), "rows_raw": len(raw)}
    report["duplicate_extra_copies"] = int(raw.duplicated().sum())
    report["duplicate_same_slip_and_stt"] = int(raw.duplicated(subset=["Mã phiếu nhập", "STT"]).sum())
    body = raw.drop_duplicates().reset_index(drop=True)
    body["amount"] = body["Thành tiền"].map(parse_money)
    body["slip_total"] = body["Tổng tiền phiếu"].map(parse_money)
    body["qty"] = body["SL nhập"].map(parse_number)
    body["price"] = body["Giá nhập"].map(parse_money)
    body["day"] = body["Ngày nhập"].map(parse_date)
    if body[["amount", "slip_total", "qty", "price", "day"]].isna().any().any():
        raise ValueError("unparsed import field")
    report["line_mismatch"] = int(((body["qty"] * body["price"]) - body["amount"]).abs().gt(0.5).sum())
    slips = body.groupby("Mã phiếu nhập").agg(total=("amount", "sum"), header=("slip_total", "first"), day=("day", "first"), status=("Trạng thái phiếu", "first"))
    report["slip_mismatch"] = int((slips["total"] != slips["header"]).sum())
    report["slips"] = len(slips)
    report["statuses"] = body["Trạng thái phiếu"].value_counts().to_dict()
    return slips, report


LINES, INVOICE_REPORT = load_invoice_lines()
ORDERS = build_orders(LINES)
CATALOG = load_catalog()
SLIPS, IMPORT_REPORT = load_imports()
DATA_START = ORDERS["day"].min()
DATA_END = ORDERS["day"].max()


def orders_placed(period: Period, clock: Clock) -> pd.DataFrame:
    end = min(period.end, clock.as_of)
    mask = (ORDERS["day"] >= period.start) & (ORDERS["day"] <= end)
    return ORDERS[mask]


def revenue_orders(period: Period, clock: Clock) -> pd.DataFrame:
    placed = orders_placed(period, clock)
    return placed[placed["counted"]]


def revenue_lines(period: Period, clock: Clock) -> pd.DataFrame:
    bills = revenue_orders(period, clock).index
    return LINES[LINES["Mã bill"].isin(bills)]


def item_lines(period: Period, clock: Clock) -> pd.DataFrame:
    lines = revenue_lines(period, clock)
    return lines[lines["Mã vạch"] != SERVICE_FEE_CODE]


def revenue(period: Period, clock: Clock, *, keep: Callable[[pd.DataFrame], pd.Series] | None = None) -> int:
    orders = revenue_orders(period, clock)
    if keep is not None:
        orders = orders[keep(orders)]
    return fmt.money(orders["goods"].sum())


def order_count(period: Period, clock: Clock, *, keep: Callable[[pd.DataFrame], pd.Series] | None = None) -> int:
    orders = revenue_orders(period, clock)
    if keep is not None:
        orders = orders[keep(orders)]
    return fmt.count(len(orders))


def cancelled_count(period: Period, clock: Clock) -> int:
    placed = orders_placed(period, clock)
    return fmt.count(int((placed["status"] == "huỷ").sum()))


def cancel_rate(period: Period, clock: Clock) -> float:
    placed = orders_placed(period, clock)
    if placed.empty:
        raise ValueError("no orders placed in period")
    return fmt.percent(100.0 * float((placed["status"] == "huỷ").sum()) / len(placed))


def percent_change(current: float, previous: float) -> float:
    if previous == 0:
        raise ValueError("previous period is zero")
    return fmt.percent(100.0 * (current - previous) / previous)


def average_order_value(period: Period, clock: Clock) -> int:
    orders = revenue_orders(period, clock)
    if orders.empty:
        raise ValueError("no revenue orders in period")
    return fmt.money(orders["goods"].sum() / len(orders))


def product_group_share(period: Period, clock: Clock, group: str) -> float:
    lines = revenue_lines(period, clock)
    if group not in set(LINES["Phân loại"]):
        raise ValueError(f"unknown product group: {group}")
    total = lines["Thành tiền"].sum()
    return fmt.percent(100.0 * lines.loc[lines["Phân loại"] == group, "Thành tiền"].sum() / total)


def product_group_revenue(period: Period, clock: Clock, group: str) -> int:
    if group not in set(LINES["Phân loại"]):
        raise ValueError(f"unknown product group: {group}")
    lines = revenue_lines(period, clock)
    return fmt.money(lines.loc[lines["Phân loại"] == group, "Thành tiền"].sum())


def product_revenue(period: Period, clock: Clock, code: str) -> int:
    lines = revenue_lines(period, clock)
    return fmt.money(lines.loc[lines["Mã vạch"] == code, "Thành tiền"].sum())


def code_of(name: str) -> str:
    hits = CATALOG.index[CATALOG["Hàng bán"] == name]
    if len(hits) != 1:
        raise ValueError(f"catalog name not unique: {name}")
    return str(hits[0])


def base_units_sold(period: Period, clock: Clock, *, unit: str, group: str | None = None) -> int | float:
    codes = set(CATALOG.index[CATALOG["ĐVT"] == unit])
    if group is not None:
        codes &= set(CATALOG.index[CATALOG["Nhóm"] == group])
    if not codes:
        raise ValueError(f"no product with base unit {unit}")
    lines = item_lines(period, clock)
    return fmt.quantity(lines.loc[lines["Mã vạch"].isin(codes), "Số lượng lẻ"].sum())


def ranked(scores: pd.Series) -> tuple[str, ...]:
    frame = scores.rename("score").reset_index()
    frame.columns = ["key", "score"]
    frame = frame.sort_values(["score", "key"], ascending=[False, True])
    return tuple(frame["key"].tolist())


def catalog_name(code: str) -> str:
    return str(CATALOG.loc[code, "Hàng bán"])


def best_sellers(period: Period, clock: Clock, k: int) -> tuple[str, ...]:
    lines = item_lines(period, clock)
    return tuple(catalog_name(code) for code in ranked(lines.groupby("Mã vạch")["Số lượng lẻ"].sum())[:k])


def most_ordered_item(period: Period, clock: Clock) -> str:
    lines = item_lines(period, clock)
    return catalog_name(ranked(lines.groupby("Mã vạch")["Mã bill"].nunique())[0])


def top_customers(period: Period, clock: Clock, k: int) -> tuple[str, ...]:
    orders = revenue_orders(period, clock)
    orders = orders[orders["customer"] != ""]
    return ranked(orders.groupby("customer")["goods"].sum())[:k]


def top_staff(period: Period, clock: Clock) -> str:
    orders = revenue_orders(period, clock)
    return ranked(orders.groupby("staff")["goods"].sum())[0]


def best_revenue_day(period: Period, clock: Clock) -> str:
    orders = revenue_orders(period, clock)
    daily = orders.groupby("day")["goods"].sum()
    return fmt.day_answer(ranked(daily)[0])


def import_spend(period: Period, clock: Clock) -> int:
    end = min(period.end, clock.as_of)
    slips = SLIPS[(SLIPS["day"] >= period.start) & (SLIPS["day"] <= end) & (SLIPS["status"] != "Đã huỷ")]
    return fmt.money(slips["total"].sum())


def stock_value_end_of_data() -> int:
    items = CATALOG[CATALOG["stock"].fillna(0) > 0]
    return fmt.money((items["stock"] * items["cost"]).sum())


def in_shift(name: str) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda orders: orders["shift"] == name


def on_channel(name: str) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda orders: orders["channel"] == name


def by_staff(code: str) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda orders: orders["staff"] == code


def in_customer_group(name: str) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda orders: (orders["customer"] != "") & (orders["group"] == name)


HANDLERS: dict[str, Callable[[Clock], tuple[str, Any]]] = {}


def answer(question_id: str) -> Callable[[Callable[[Clock], tuple[str, Any]]], Callable[[Clock], tuple[str, Any]]]:
    def register(func: Callable[[Clock], tuple[str, Any]]) -> Callable[[Clock], tuple[str, Any]]:
        if question_id in HANDLERS:
            raise ValueError(f"duplicate handler: {question_id}")
        HANDLERS[question_id] = func
        return func

    return register


@answer("q_014cdcc1da6e")
def _afternoon_revenue_aug_2026(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.month(8, 2026), c, keep=in_shift("chiều"))


@answer("q_0acdf488056e")
def _change_apr_2026(c: Clock) -> tuple[str, Any]:
    return "percent", percent_change(revenue(c.month(4, 2026), c), revenue(c.month(3, 2026), c))


@answer("q_0f7d15097a8c")
def _orders_q3_2025(c: Clock) -> tuple[str, Any]:
    return "number", order_count(c.quarter(3, 2025), c)


@answer("q_14565ad8b459")
def _revenue_yesterday_a(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.yesterday(), c)


@answer("q_20fc83f06434")
def _revenue_q3_2025(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.quarter(3, 2025), c)


@answer("q_244e072341dc")
def _imports_this_month(c: Clock) -> tuple[str, Any]:
    return "number", import_spend(c.this_month(), c)


@answer("q_27e230ca0ed6")
def _share_khai_vi_aug_2025(c: Clock) -> tuple[str, Any]:
    return "percent", product_group_share(c.month(8, 2025), c, "khai vị")


@answer("q_2e131da8a651")
def _cancel_rate_jun_2026(c: Clock) -> tuple[str, Any]:
    return "percent", cancel_rate(c.month(6, 2026), c)


@answer("q_38f7a53691b3")
def _change_jan_2026(c: Clock) -> tuple[str, Any]:
    return "percent", percent_change(revenue(c.month(1, 2026), c), revenue(c.month(12, 2025), c))


@answer("q_393d0d4ee0e2")
def _cans_yesterday_a(c: Clock) -> tuple[str, Any]:
    return "number", base_units_sold(c.yesterday(), c, unit="lon")


@answer("q_39f9f14db2a0")
def _cancelled_feb_2026(c: Clock) -> tuple[str, Any]:
    return "number", cancelled_count(c.month(2, 2026), c)


@answer("q_3a7a64626d2d")
def _loyal_share_this_month(c: Clock) -> tuple[str, Any]:
    period = c.this_month()
    return "percent", fmt.percent(100.0 * revenue(period, c, keep=in_customer_group("thân thiết")) / revenue(period, c))


@answer("q_3b67b4302890")
def _share_hai_san_may_2026(c: Clock) -> tuple[str, Any]:
    return "percent", product_group_share(c.month(5, 2026), c, "hải sản")


@answer("q_3cd196c4dc4d")
def _cancelled_jul_2026(c: Clock) -> tuple[str, Any]:
    return "number", cancelled_count(c.month(7, 2026), c)


@answer("q_3d519482d665")
def _orders_today(c: Clock) -> tuple[str, Any]:
    return "number", order_count(c.today(), c)


@answer("q_3f807c338eb9")
def _goi_dec_2025(c: Clock) -> tuple[str, Any]:
    return "number", product_group_revenue(c.month(12, 2025), c, "gỏi")


@answer("q_4ad0311ba5f9")
def _revenue_yesterday_b(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.yesterday(), c)


@answer("q_4bb10819b3a3")
def _cancelled_mar_2025(c: Clock) -> tuple[str, Any]:
    return "number", cancelled_count(c.month(3, 2025), c)


@answer("q_4e331ce1a042")
def _morning_revenue_last_week(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.last_week(), c, keep=in_shift("sáng"))


@answer("q_4fe561cc6493")
def _cancel_rate_jul_2025(c: Clock) -> tuple[str, Any]:
    return "percent", cancel_rate(c.month(7, 2025), c)


@answer("q_520e8c3f5c02")
def _zalo_this_month(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.this_month(), c, keep=on_channel(CHANNEL_ZALO))


@answer("q_5336ec08027b")
def _revenue_yesterday_c(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.yesterday(), c)


@answer("q_55cfcde4c03f")
def _afternoon_orders_last_week(c: Clock) -> tuple[str, Any]:
    return "number", order_count(c.last_week(), c, keep=in_shift("chiều"))


@answer("q_575157e63e1c")
def _top5_customers_mar_2025(c: Clock) -> tuple[str, Any]:
    return "list", list(top_customers(c.month(3, 2025), c, 5))


@answer("q_588a7c489b8e")
def _change_aug_2026_yoy(c: Clock) -> tuple[str, Any]:
    return "percent", percent_change(revenue(c.month(8, 2026), c), revenue(c.month(8, 2025), c))


@answer("q_599716cf226a")
def _nv004_mar_2026(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.month(3, 2026), c, keep=by_staff("NV004"))


@answer("q_5e195033ee9d")
def _sg_special_aug_2025(c: Clock) -> tuple[str, Any]:
    return "number", product_revenue(c.month(8, 2025), c, code_of("Bia Sài Gòn Special lon"))


@answer("q_6172ede181a5")
def _zalo_phone_mar_2026(c: Clock) -> tuple[str, Any]:
    period = c.month(3, 2026)
    return "list", [revenue(period, c, keep=on_channel(CHANNEL_ZALO)), revenue(period, c, keep=on_channel(CHANNEL_PHONE))]


@answer("q_699d8e8772a3")
def _nv001_feb_2026(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.month(2, 2026), c, keep=by_staff("NV001"))


@answer("q_6a52cddced60")
def _sun_ga_aug_2026(c: Clock) -> tuple[str, Any]:
    return "number", product_revenue(c.month(8, 2026), c, code_of("Sụn gà rang muối"))


@answer("q_6b6025944b9d")
def _trung_chien_jul_2025(c: Clock) -> tuple[str, Any]:
    return "number", product_revenue(c.month(7, 2025), c, code_of("Trứng chiên thịt bằm"))


@answer("q_6b9c81934530")
def _revenue_oct_2025(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.month(10, 2025), c)


@answer("q_75f74a3060c8")
def _aov_feb_2026(c: Clock) -> tuple[str, Any]:
    return "number", average_order_value(c.month(2, 2026), c)


@answer("q_77085d36e011")
def _stock_value_2026_09_19(c: Clock) -> tuple[str, Any]:
    if c.as_of != DATA_END:
        raise ValueError("stock snapshot only valid at end of data")
    return "number", stock_value_end_of_data()


@answer("q_791de98789d5")
def _top_staff_jul_2026(c: Clock) -> tuple[str, Any]:
    return "string", top_staff(c.month(7, 2026), c)


@answer("q_79a79df3f048")
def _change_aug_2025(c: Clock) -> tuple[str, Any]:
    return "percent", percent_change(revenue(c.month(8, 2025), c), revenue(c.month(7, 2025), c))


@answer("q_8103cddd9040")
def _top3_aug_2026(c: Clock) -> tuple[str, Any]:
    return "list", list(best_sellers(c.month(8, 2026), c, 3))


@answer("q_859861209455")
def _imports_aug_2026(c: Clock) -> tuple[str, Any]:
    return "number", import_spend(c.month(8, 2026), c)


@answer("q_8818447349a6")
def _zalo_store_this_month(c: Clock) -> tuple[str, Any]:
    period = c.this_month()
    return "list", [revenue(period, c, keep=on_channel(CHANNEL_ZALO)), revenue(period, c, keep=on_channel(CHANNEL_STORE))]


@answer("q_8ab2403c8c80")
def _revenue_jul_2026(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.month(7, 2026), c)


@answer("q_8ef70e6d70f8")
def _top3_may_2025(c: Clock) -> tuple[str, Any]:
    return "list", list(best_sellers(c.month(5, 2025), c, 3))


@answer("q_91368b04415b")
def _afternoon_vs_morning_revenue_last_week(c: Clock) -> tuple[str, Any]:
    period = c.last_week()
    return "percent", percent_change(revenue(period, c, keep=in_shift("chiều")), revenue(period, c, keep=in_shift("sáng")))


@answer("q_980cef2c769c")
def _change_jun_2026_yoy(c: Clock) -> tuple[str, Any]:
    return "percent", percent_change(revenue(c.month(6, 2026), c), revenue(c.month(6, 2025), c))


@answer("q_99e67ed05dd8")
def _best_day_jul_2026(c: Clock) -> tuple[str, Any]:
    return "date", best_revenue_day(c.month(7, 2026), c)


@answer("q_99fba89f30fa")
def _nv005_jun_2026(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.month(6, 2026), c, keep=by_staff("NV005"))


@answer("q_a2ed59a92ab8")
def _revenue_today(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.today(), c)


@answer("q_a6a66b57f28c")
def _cans_yesterday_b(c: Clock) -> tuple[str, Any]:
    return "number", base_units_sold(c.yesterday(), c, unit="lon")


@answer("q_a7dd46bc4b38")
def _favourite_jul_2025(c: Clock) -> tuple[str, Any]:
    return "string", most_ordered_item(c.month(7, 2025), c)


@answer("q_a9f96bee3fa4")
def _loyal_revenue_jun_2026(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.month(6, 2026), c, keep=in_customer_group("thân thiết"))


@answer("q_af0446a26a67")
def _aov_nov_2025(c: Clock) -> tuple[str, Any]:
    return "number", average_order_value(c.month(11, 2025), c)


@answer("q_b3a65abd54c2")
def _revenue_q1_2026(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.quarter(1, 2026), c)


@answer("q_b70a59e2e970")
def _cancel_rate_oct_2025(c: Clock) -> tuple[str, Any]:
    return "percent", cancel_rate(c.month(10, 2025), c)


@answer("q_be3f968523bf")
def _afternoon_vs_morning_orders_jun_2026(c: Clock) -> tuple[str, Any]:
    period = c.month(6, 2026)
    return "percent", percent_change(order_count(period, c, keep=in_shift("chiều")), order_count(period, c, keep=in_shift("sáng")))


@answer("q_d0c41c37777e")
def _plates_chien_xao_jan_2026(c: Clock) -> tuple[str, Any]:
    return "number", base_units_sold(c.month(1, 2026), c, unit="đĩa", group="chiên xào")


@answer("q_d547526c4d5d")
def _top_staff_jan_2026(c: Clock) -> tuple[str, Any]:
    return "string", top_staff(c.month(1, 2026), c)


@answer("q_d75952be2f51")
def _revenue_may_2026(c: Clock) -> tuple[str, Any]:
    return "number", revenue(c.month(5, 2026), c)


@answer("q_e2e4e0639619")
def _tastiest_nov_2025(c: Clock) -> tuple[str, Any]:
    return "unanswerable", None


@answer("q_e2f1ef732951")
def _aov_aug_2026(c: Clock) -> tuple[str, Any]:
    return "number", average_order_value(c.month(8, 2026), c)


@answer("q_e322d691b4be")
def _change_feb_2026_yoy(c: Clock) -> tuple[str, Any]:
    return "percent", percent_change(revenue(c.month(2, 2026), c), revenue(c.month(2, 2025), c))


@answer("q_e6ccb4744594")
def _best_day_jan_2026(c: Clock) -> tuple[str, Any]:
    return "date", best_revenue_day(c.month(1, 2026), c)


def main() -> None:
    questions = fmt.load_questions(QUESTIONS_PATH)
    out: list[dict[str, Any]] = []
    for question in questions:
        if question["business_id"] != "dev_007":
            raise ValueError(f"foreign question: {question['id']}")
        handler = HANDLERS.get(question["id"])
        if handler is None:
            out.append(fmt.answer_line(question["id"], "abstain"))
            continue
        kind, value = handler(Clock(question["as_of_date"]))
        out.append(fmt.answer_line(question["id"], kind, value))
    written = fmt.write_answers(ANSWERS_PATH, out)
    if written != len(questions):
        raise ValueError(f"wrote {written} lines for {len(questions)} questions")
    print(f"dev_007: {written} lines -> {ANSWERS_PATH}")


if __name__ == "__main__":
    main()
