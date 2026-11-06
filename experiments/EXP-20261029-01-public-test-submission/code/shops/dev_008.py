from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import pandas as pd

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from datamate import Clock, Period, fmt, fold_key, parse_date, parse_money, parse_number, read_table, squeeze
from datamate.fmt import load_questions, write_answers
from datamate.tabio import drop_subtotal_rows

SHOP = "dev_008"
EXPERIMENT_ROOT = CODE_ROOT.parent
DATA_DIR = Path("/Users/lebahoai/Workspace/zalo/2026/public_test/data") / SHOP
QUESTIONS_PATH = DATA_DIR / "questions.jsonl"
ANSWERS_PATH = EXPERIMENT_ROOT / "out" / "answers" / f"{SHOP}.jsonl"

STATUS_DONE = "hoàn thành"
STATUS_CANCELLED = "huỷ"
STATUS_RETURNED = "trả hàng"
STATUS_SHIPPING = "đang giao"

STATUS_MAP = {
    "đã lấy": STATUS_DONE,
    "thành công": STATUS_DONE,
    "đã xong": STATUS_DONE,
    "hủy đơn": STATUS_CANCELLED,
    "khách hủy": STATUS_CANCELLED,
    "hoàn trả": STATUS_RETURNED,
    "trả hàng": STATUS_RETURNED,
    "đã hoàn hàng": STATUS_RETURNED,
    "đang giao": STATUS_SHIPPING,
    "đang giao dịch": STATUS_SHIPPING,
}

SERVICE_FEE_CODE = "SP0061"

QUESTION_ITEM_ALIASES = {
    "dau phu ran gion": "SP0009",
    "canh chua ca trau": "SP0016",
    "chao ngao": "SP0060",
    "ma lon nuong nuoc mam": "SP0052",
    "bo luc lac khoai tay": "SP0013",
    "muc ran nuoc mam": "SP0024",
}

PAID_OFF_MARKS = ("đã trả đủ", "trả hết rồi", "đủ rồi")
MONEY_TAIL = r"([\d][\d.,]*\s*(?:đ|k|nghìn|nghin|triệu|trieu|tr\d*)?)"


class Ledger:
    """Sổ bán hàng, danh mục hàng và sổ nhập của dev_008 đã ingest và kiểm kê."""

    def __init__(self) -> None:
        self.catalog = self._read_catalog()
        self.lines = self._read_lines()
        self.orders = self._build_orders()
        self.purchases = self._read_purchases()
        self.data_span = Period(start=self.orders["ngay"].min(), end=self.orders["ngay"].max(), label="dữ liệu")
        self._validate()

    def _read_catalog(self) -> pd.DataFrame:
        frame = read_table(DATA_DIR / "DanhMucHang.xlsx", header_row=0)
        frame = frame.rename(columns={"Mã sản phẩm bán": "ma_hang", "Hàng": "ten_hang", "DVT": "dvt", "Loại hàng": "nhom_hang"})
        frame["ton"] = frame["Tồn thực"].map(lambda v: parse_number(v, default=0.0))
        frame["gia_von"] = frame["Giá vốn"].map(lambda v: parse_money(v, default=0))
        frame["gia_hien_tai"] = frame["Giá hiện tại"].map(lambda v: parse_money(v, default=0))
        frame["ten_hang"] = frame["ten_hang"].map(squeeze)
        return frame[["ma_hang", "ten_hang", "dvt", "nhom_hang", "ton", "gia_von", "gia_hien_tai"]].reset_index(drop=True)

    def _read_lines(self) -> pd.DataFrame:
        parts: list[pd.DataFrame] = []
        for name in ("ChiTietHoaDon_1.xlsx", "ChiTietHoaDon_2.xlsx"):
            raw = read_table(DATA_DIR / name, header_row=0)
            parts.append(drop_subtotal_rows(raw, key_columns=["Bill", "Ma hang"]))
        frame = pd.concat(parts, ignore_index=True).drop_duplicates().reset_index(drop=True)
        frame = frame.rename(
            columns={
                "Bill": "bill",
                "Ma hang": "ma_hang",
                "Tên hàng": "ten_hang_dong",
                "Nhóm hàng": "nhom_hang",
                "Đơn vị (tính)": "dvt_dong",
                "Mã người mua": "ma_khach",
                "Nhóm khách hàng": "nhom_khach",
                "Nhân viên bán": "nhan_vien",
                "Kênh bán": "kenh_ban",
                "Thanh toán bằng": "thanh_toan",
                "TT đơn": "tt_don_raw",
                "Note": "note",
                "Khu vực": "khu_vuc",
            }
        )
        frame["thanh_tien"] = frame["Thành tiền"].map(lambda v: parse_money(v, default=0))
        frame["sl_co_ban"] = frame["SL lẻ"].map(lambda v: parse_number(v, default=0.0))
        frame["sl_dong"] = frame["SLg"].map(lambda v: parse_number(v, default=0.0))
        frame["don_gia"] = frame["Đơn giá (đ)"].map(lambda v: parse_money(v, default=0))
        frame["gio_ban"] = frame["Giờ bán"]
        frame["ngay"] = frame["gio_ban"].map(lambda v: v.date())
        frame["trang_thai"] = frame["tt_don_raw"].map(self._status_of)
        frame["ma_khach"] = frame["ma_khach"].map(lambda v: squeeze(v) or None)
        return frame

    @staticmethod
    def _status_of(raw: Any) -> str:
        key = squeeze(raw).casefold()
        if key not in STATUS_MAP:
            raise ValueError(f"unknown order status: {raw!r}")
        return STATUS_MAP[key]

    def _build_orders(self) -> pd.DataFrame:
        grouped = self.lines.groupby("bill", sort=True)
        orders = grouped.agg(
            ngay=("ngay", "first"),
            gio_ban=("gio_ban", "first"),
            trang_thai=("trang_thai", "first"),
            ma_khach=("ma_khach", "first"),
            nhom_khach=("nhom_khach", "first"),
            nhan_vien=("nhan_vien", "first"),
            kenh_ban=("kenh_ban", "first"),
            thanh_toan=("thanh_toan", "first"),
            note=("note", "first"),
            doanh_thu=("thanh_tien", "sum"),
            tong_tien_hang=("Tổng tiền hàng", "first"),
            giam_gia_hd=("Giảm giá HĐ", "first"),
            tong_tien=("Tong tien", "first"),
            phi_ship=("Phi ship", "first"),
        ).reset_index()
        orders["tong_tien_hang"] = orders["tong_tien_hang"].map(lambda v: parse_money(v, default=0))
        orders["giam_gia_hd"] = orders["giam_gia_hd"].map(lambda v: parse_money(v, default=0))
        orders["tong_tien"] = orders["tong_tien"].map(lambda v: parse_money(v, default=0))
        orders["phi_ship"] = orders["phi_ship"].map(lambda v: parse_money(v, default=0))
        orders["ca"] = orders["gio_ban"].map(lambda v: "sáng" if v.hour * 60 + v.minute <= 13 * 60 + 59 else "chiều")
        orders["con_no"] = [self._remaining_debt(row.note, row.tong_tien) for row in orders.itertuples()]
        return orders

    @staticmethod
    def _remaining_debt(note: Any, order_total: int) -> int:
        text = squeeze(note)
        if text == "":
            return 0
        low = text.casefold()
        if any(mark in low for mark in PAID_OFF_MARKS):
            return 0
        if "nợ cả đơn" in low:
            return order_total
        for keyword in ("còn thiếu", "thiếu lại"):
            found = re.search(keyword + r"\s*" + MONEY_TAIL, low)
            if found is not None:
                return parse_money(found.group(1), default=0)
        if "còn lại ghi sổ" in low:
            paid = re.search(r"(?:đưa trước|trả|ck)\s*" + MONEY_TAIL, low)
            if paid is None:
                raise ValueError(f"unparsed debt note: {text!r}")
            return order_total - parse_money(paid.group(1), default=0)
        for keyword in ("ghi sổ", "ghi nợ", "nợ"):
            found = re.search(keyword + r"\s*" + MONEY_TAIL, low)
            if found is not None and found.group(1).strip() != "":
                return parse_money(found.group(1), default=0)
        raise ValueError(f"unparsed debt note: {text!r}")

    def _read_purchases(self) -> pd.DataFrame:
        frame = read_table(DATA_DIR / "ChiTietNhapHang.xlsx", header_row=0)
        frame = frame.rename(
            columns={"Mã phiếu nhập": "ma_phieu", "Mã NCC": "ma_ncc", "Mã vạch": "ma_hang", "Trạng thái phiếu": "trang_thai_phieu"}
        )
        frame["ngay"] = frame["Ngày nhập"].map(parse_date)
        frame["thanh_tien"] = frame["Thành tiền"].map(lambda v: parse_money(v, default=0))
        frame["sl_nhap"] = frame["SL nhập"].map(lambda v: parse_number(v, default=0.0))
        if frame["ngay"].isna().any():
            raise ValueError("purchase rows with unparsed date")
        return frame

    def _validate(self) -> None:
        bad_line = (self.lines["sl_dong"] * self.lines["don_gia"] - self.lines["Giảm (đ)"].map(lambda v: parse_money(v, default=0)) - self.lines["thanh_tien"]).abs()
        if bool((bad_line > 0.5).any()):
            raise ValueError("line total does not match quantity times unit price")
        if bool((self.orders["doanh_thu"] - self.orders["tong_tien_hang"]).abs().gt(0.5).any()):
            raise ValueError("order line sum does not match order goods total")
        expected = self.orders["tong_tien_hang"] - self.orders["giam_gia_hd"] + self.orders["phi_ship"]
        if bool((expected - self.orders["tong_tien"]).abs().gt(0.5).any()):
            raise ValueError("order payable does not match goods minus discount plus shipping")
        if bool((self.orders["con_no"] < 0).any()) or bool((self.orders["con_no"] > self.orders["tong_tien"]).any()):
            raise ValueError("remaining debt outside order total")

    def revenue_orders(self, period: Period, clock: Clock) -> pd.DataFrame:
        mask = self.orders["trang_thai"].isin((STATUS_DONE, STATUS_SHIPPING))
        mask &= self.orders["ngay"].map(period.contains)
        mask &= self.orders["ngay"].map(clock.visible)
        return self.orders[mask]

    def placed_orders(self, period: Period, clock: Clock) -> pd.DataFrame:
        mask = self.orders["ngay"].map(period.contains) & self.orders["ngay"].map(clock.visible)
        return self.orders[mask]

    def revenue_lines(self, period: Period, clock: Clock) -> pd.DataFrame:
        bills = set(self.revenue_orders(period, clock)["bill"])
        return self.lines[self.lines["bill"].isin(bills)]

    def unit_of(self, ma_hang: str) -> str:
        row = self.catalog[self.catalog["ma_hang"] == ma_hang]
        if row.empty:
            raise ValueError(f"item not in catalog: {ma_hang}")
        return str(row.iloc[0]["dvt"])

    def name_of(self, ma_hang: str) -> str:
        row = self.catalog[self.catalog["ma_hang"] == ma_hang]
        if row.empty:
            raise ValueError(f"item not in catalog: {ma_hang}")
        return str(row.iloc[0]["ten_hang"])

    def code_of_question_name(self, spoken: str) -> str:
        key = fold_key(spoken)
        if key in QUESTION_ITEM_ALIASES:
            return QUESTION_ITEM_ALIASES[key]
        for row in self.catalog.itertuples():
            if fold_key(row.ten_hang) == key:
                return str(row.ma_hang)
        raise ValueError(f"no catalog item for question name: {spoken!r}")


def revenue(book: Ledger, period: Period, clock: Clock) -> int:
    return int(book.revenue_orders(period, clock)["doanh_thu"].sum())


def order_count(book: Ledger, period: Period, clock: Clock) -> int:
    return int(len(book.revenue_orders(period, clock)))


def average_order_revenue(book: Ledger, period: Period, clock: Clock) -> int:
    rows = book.revenue_orders(period, clock)
    if len(rows) == 0:
        raise ValueError(f"no orders in {period}")
    return fmt.money(rows["doanh_thu"].sum() / len(rows))


def percent_change(current: float, base: float) -> float:
    if base == 0:
        raise ValueError("percent change against zero base")
    return fmt.percent((current - base) / base * 100.0)


def cancel_rate(book: Ledger, period: Period, clock: Clock) -> float:
    placed = book.placed_orders(period, clock)
    if len(placed) == 0:
        raise ValueError(f"no orders placed in {period}")
    cancelled = int((placed["trang_thai"] == STATUS_CANCELLED).sum())
    return fmt.percent(cancelled / len(placed) * 100.0)


def daily_revenue(book: Ledger, period: Period, clock: Clock) -> pd.Series:
    rows = book.revenue_orders(period, clock)
    return rows.groupby("ngay")["doanh_thu"].sum()


def days_with_revenue_at_least(book: Ledger, period: Period, clock: Clock, floor: int) -> int:
    series = daily_revenue(book, period, clock)
    return int((series >= floor).sum())


def orders_with_revenue_at_least(book: Ledger, period: Period, clock: Clock, floor: int) -> int:
    rows = book.revenue_orders(period, clock)
    return int((rows["doanh_thu"] >= floor).sum())


def items_in_at_least_n_orders(book: Ledger, period: Period, clock: Clock, floor: int) -> int:
    sold = book.revenue_lines(period, clock)
    sold = sold[sold["ma_hang"] != SERVICE_FEE_CODE]
    counts = sold.groupby("ma_hang")["bill"].nunique()
    return int((counts >= floor).sum())


def customers_with_at_least_n_orders(book: Ledger, period: Period, clock: Clock, floor: int) -> tuple[int, int]:
    rows = book.revenue_orders(period, clock)
    rows = rows[rows["ma_khach"].notna()]
    counts = rows.groupby("ma_khach")["bill"].nunique()
    return int((counts >= floor).sum()), int(len(counts))


def base_quantity_by_unit(book: Ledger, period: Period, clock: Clock, unit: str) -> float:
    sold = book.revenue_lines(period, clock)
    units = dict(zip(book.catalog["ma_hang"], book.catalog["dvt"]))
    mask = sold["ma_hang"].map(lambda code: units.get(code) == unit)
    return float(sold[mask]["sl_co_ban"].sum())


def item_base_quantity(book: Ledger, period: Period, clock: Clock, ma_hang: str) -> float:
    sold = book.revenue_lines(period, clock)
    return float(sold[sold["ma_hang"] == ma_hang]["sl_co_ban"].sum())


def item_revenue(book: Ledger, period: Period, clock: Clock, ma_hang: str) -> int:
    sold = book.revenue_lines(period, clock)
    return int(sold[sold["ma_hang"] == ma_hang]["thanh_tien"].sum())


def group_revenue(book: Ledger, period: Period, clock: Clock, group: str) -> int:
    sold = book.revenue_lines(period, clock)
    return int(sold[sold["nhom_hang"].map(lambda v: squeeze(v)) == group]["thanh_tien"].sum())


def best_sellers(book: Ledger, period: Period, clock: Clock, top: int) -> tuple[str, ...]:
    sold = book.revenue_lines(period, clock)
    sold = sold[sold["ma_hang"] != SERVICE_FEE_CODE]
    totals = sold.groupby("ma_hang")["sl_co_ban"].sum().reset_index()
    totals = totals.sort_values(["sl_co_ban", "ma_hang"], ascending=[False, True])
    return tuple(book.name_of(code) for code in totals["ma_hang"].head(top))


def purchase_cost(book: Ledger, period: Period, clock: Clock) -> int:
    rows = book.purchases
    mask = rows["ngay"].map(period.contains) & rows["ngay"].map(clock.visible)
    return int(rows[mask]["thanh_tien"].sum())


def price_effect_percent(book: Ledger, clock: Clock, ma_hang: str, changed_on: date, window: int) -> float:
    after = Period(start=changed_on, end=changed_on + timedelta(days=window - 1), label="sau")
    before = Period(start=changed_on - timedelta(days=window), end=changed_on - timedelta(days=1), label="trước")
    return percent_change(item_base_quantity(book, after, clock, ma_hang), item_base_quantity(book, before, clock, ma_hang))


def top_customers_by_revenue(book: Ledger, period: Period, clock: Clock, top: int) -> tuple[str, ...]:
    rows = book.revenue_orders(period, clock)
    rows = rows[rows["ma_khach"].notna()]
    totals = rows.groupby("ma_khach")["doanh_thu"].sum().reset_index()
    totals = totals.sort_values(["doanh_thu", "ma_khach"], ascending=[False, True])
    return tuple(str(v) for v in totals["ma_khach"].head(top))


def customer_with_most_orders(book: Ledger, period: Period, clock: Clock) -> str:
    rows = book.revenue_orders(period, clock)
    rows = rows[rows["ma_khach"].notna()]
    counts = rows.groupby("ma_khach")["bill"].nunique().reset_index()
    counts = counts.sort_values(["bill", "ma_khach"], ascending=[False, True])
    return str(counts.iloc[0]["ma_khach"])


def customer_with_most_cancellations(book: Ledger, period: Period, clock: Clock) -> str:
    rows = book.placed_orders(period, clock)
    rows = rows[(rows["trang_thai"] == STATUS_CANCELLED) & rows["ma_khach"].notna()]
    counts = rows.groupby("ma_khach")["bill"].nunique().reset_index()
    counts = counts.sort_values(["bill", "ma_khach"], ascending=[False, True])
    return str(counts.iloc[0]["ma_khach"])


def employee_revenue(book: Ledger, period: Period, clock: Clock, code: str) -> int:
    rows = book.revenue_orders(period, clock)
    return int(rows[rows["nhan_vien"].map(lambda v: squeeze(v)) == code]["doanh_thu"].sum())


def best_employee(book: Ledger, period: Period, clock: Clock) -> str:
    rows = book.revenue_orders(period, clock)
    totals = rows.groupby("nhan_vien")["doanh_thu"].sum().reset_index()
    totals = totals.sort_values(["doanh_thu", "nhan_vien"], ascending=[False, True])
    return str(totals.iloc[0]["nhan_vien"])


def channel_revenue(book: Ledger, period: Period, clock: Clock, channel: str) -> int:
    rows = book.revenue_orders(period, clock)
    return int(rows[rows["kenh_ban"].map(lambda v: squeeze(v)) == channel]["doanh_thu"].sum())


def payment_revenue(book: Ledger, period: Period, clock: Clock, method: str) -> int:
    rows = book.revenue_orders(period, clock)
    return int(rows[rows["thanh_toan"].map(lambda v: squeeze(v)) == method]["doanh_thu"].sum())


def customer_group_revenue(book: Ledger, period: Period, clock: Clock, group: str) -> int:
    rows = book.revenue_orders(period, clock)
    return int(rows[rows["nhom_khach"].map(lambda v: squeeze(v)) == group]["doanh_thu"].sum())


def customer_group_average_order(book: Ledger, period: Period, clock: Clock, group: str) -> int:
    rows = book.revenue_orders(period, clock)
    rows = rows[rows["nhom_khach"].map(lambda v: squeeze(v)) == group]
    if len(rows) == 0:
        raise ValueError(f"no orders for customer group {group}")
    return fmt.money(rows["doanh_thu"].sum() / len(rows))


def shift_revenue(book: Ledger, period: Period, clock: Clock, shift: str) -> int:
    rows = book.revenue_orders(period, clock)
    return int(rows[rows["ca"] == shift]["doanh_thu"].sum())


def shift_order_count(book: Ledger, period: Period, clock: Clock, shift: str) -> int:
    rows = book.revenue_orders(period, clock)
    return int((rows["ca"] == shift).sum())


def best_revenue_day(book: Ledger, period: Period, clock: Clock) -> date:
    series = daily_revenue(book, period, clock)
    if series.empty:
        raise ValueError(f"no revenue in {period}")
    frame = series.reset_index().sort_values(["doanh_thu", "ngay"], ascending=[False, True])
    return frame.iloc[0]["ngay"]


def best_revenue_month(book: Ledger, clock: Clock, months: Sequence[tuple[int, int]]) -> tuple[int, int]:
    scored = [(revenue(book, Period(start=date(y, m, 1), end=_month_end(y, m), label=f"{m}/{y}"), clock), y, m) for y, m in months]
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    return scored[0][1], scored[0][2]


def _month_end(year: int, month: int) -> date:
    return date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)


def outstanding_debt(book: Ledger) -> pd.DataFrame:
    rows = book.orders
    rows = rows[(rows["con_no"] > 0) & (rows["trang_thai"] != STATUS_CANCELLED)]
    return rows


def debt_age_days(book: Ledger, as_of: date) -> pd.Series:
    rows = outstanding_debt(book)
    return (pd.Series([as_of] * len(rows), index=rows.index) - rows["ngay"]).map(lambda d: d.days)


def stock_value(book: Ledger) -> int:
    rows = book.catalog
    return fmt.money(float((rows["ton"] * rows["gia_von"]).sum()))


def build_answers(book: Ledger) -> tuple[dict[str, Any], ...]:
    questions = {row["id"]: row for row in load_questions(QUESTIONS_PATH)}
    clock_of = {qid: Clock(row["as_of_date"]) for qid, row in questions.items()}
    out: list[dict[str, Any]] = []

    def put(qid: str, answer_type: str, value: Any = None, *, reason: str | None = None) -> None:
        out.append(fmt.answer_line(qid, answer_type, value, reason=reason))

    def ck(qid: str) -> Clock:
        return clock_of[qid]

    put("q_01ba91ff94c6", "list", list(best_sellers(book, ck("q_01ba91ff94c6").last_week(), ck("q_01ba91ff94c6"), 5)))
    put("q_06de4545fe25", "number", items_in_at_least_n_orders(book, ck("q_06de4545fe25").month(1, 2026), ck("q_06de4545fe25"), 187))
    put("q_0bee4ad8f965", "number", average_order_revenue(book, ck("q_0bee4ad8f965").last_week(), ck("q_0bee4ad8f965")))
    put("q_0c0a1a780164", "number", payment_revenue(book, ck("q_0c0a1a780164").this_month(), ck("q_0c0a1a780164"), "ewallet"))
    put("q_0e72ff8aa98e", "number", orders_with_revenue_at_least(book, ck("q_0e72ff8aa98e").month(5, 2026), ck("q_0e72ff8aa98e"), 1_100_000))
    put("q_0ef1608808dd", "number", purchase_cost(book, ck("q_0ef1608808dd").month(3, 2026), ck("q_0ef1608808dd")))
    put("q_121c6959016d", "number", days_with_revenue_at_least(book, ck("q_121c6959016d").month(4, 2026), ck("q_121c6959016d"), 40_000_000))
    put("q_129b29f14e89", "number", purchase_cost(book, ck("q_129b29f14e89").month(6, 2025), ck("q_129b29f14e89")))
    put("q_15711c61bb0d", "unanswerable", reason="sổ không ghi đánh giá thái độ phục vụ của nhân viên")
    put("q_15a8893ff6f9", "number", fmt.quantity(base_quantity_by_unit(book, ck("q_15a8893ff6f9").last_week(), ck("q_15a8893ff6f9"), "đĩa")))
    put("q_16ec75d6c8a4", "number", order_count(book, ck("q_16ec75d6c8a4").year_to_date(), ck("q_16ec75d6c8a4")))
    put("q_180163673aaa", "string", best_employee(book, ck("q_180163673aaa").month(11, 2025), ck("q_180163673aaa")))
    put("q_1a35be96a5bd", "number", fmt.quantity(base_quantity_by_unit(book, ck("q_1a35be96a5bd").this_week(), ck("q_1a35be96a5bd"), "đĩa")))
    put("q_1e1b499d3c87", "number", revenue(book, ck("q_1e1b499d3c87").month(7, 2025), ck("q_1e1b499d3c87")))
    put("q_21b93db251ef", "number", order_count(book, ck("q_21b93db251ef").last_n_days(30), ck("q_21b93db251ef")))
    put(
        "q_2302c71da33e",
        "percent",
        fmt.percent(group_revenue(book, ck("q_2302c71da33e").month(10, 2025), ck("q_2302c71da33e"), "cơm mì cháo") / revenue(book, ck("q_2302c71da33e").month(10, 2025), ck("q_2302c71da33e")) * 100.0),
    )
    put("q_26212108a6e6", "number", customer_group_average_order(book, ck("q_26212108a6e6").this_month(), ck("q_26212108a6e6"), "thân thiết"))
    put("q_2bd15109007c", "number", fmt.quantity(base_quantity_by_unit(book, ck("q_2bd15109007c").last_n_days(30), ck("q_2bd15109007c"), "lon")))
    put(
        "q_2db4f43d56bd",
        "percent",
        percent_change(revenue(book, ck("q_2db4f43d56bd").this_month(), ck("q_2db4f43d56bd")), revenue(book, ck("q_2db4f43d56bd").last_month_same_days(), ck("q_2db4f43d56bd"))),
    )
    put("q_37305e6af527", "number", revenue(book, ck("q_37305e6af527").last_week(), ck("q_37305e6af527")))
    put("q_3de82903c4c6", "number", revenue(book, ck("q_3de82903c4c6").year_to_date(), ck("q_3de82903c4c6")))
    put("q_3e9418af3a85", "number", revenue(book, ck("q_3e9418af3a85").last_n_days(7), ck("q_3e9418af3a85")))
    put("q_416be8994e14", "number", days_with_revenue_at_least(book, ck("q_416be8994e14").month(3, 2025), ck("q_416be8994e14"), 34_000_000))
    put(
        "q_429155557e11",
        "percent",
        percent_change(revenue(book, ck("q_429155557e11").month(6, 2026), ck("q_429155557e11")), revenue(book, ck("q_429155557e11").month(5, 2026), ck("q_429155557e11"))),
    )
    put(
        "q_48cbee311a9e",
        "percent",
        percent_change(revenue(book, ck("q_48cbee311a9e").this_month(), ck("q_48cbee311a9e")), revenue(book, ck("q_48cbee311a9e").last_month_same_days(), ck("q_48cbee311a9e"))),
    )
    put("q_4cdc20a8b400", "percent", cancel_rate(book, ck("q_4cdc20a8b400").month(3, 2025), ck("q_4cdc20a8b400")))
    put("q_4df5a9b089cd", "number", order_count(book, ck("q_4df5a9b089cd").year_to_date(), ck("q_4df5a9b089cd")))
    put("q_4df64734eb4d", "number", orders_with_revenue_at_least(book, ck("q_4df64734eb4d").month(1, 2025), ck("q_4df64734eb4d"), 410_000))
    put("q_5160c511711f", "number", item_revenue(book, ck("q_5160c511711f").month(10, 2025), ck("q_5160c511711f"), book.code_of_question_name("Đậu phụ rán giòn")))
    put("q_5217c0d650c8", "date", fmt.day_answer(best_revenue_day(book, ck("q_5217c0d650c8").month(4, 2025), ck("q_5217c0d650c8"))))
    put(
        "q_522627a83f38",
        "list",
        [
            revenue(book, ck("q_522627a83f38").month(12, 2025), ck("q_522627a83f38")),
            revenue(book, ck("q_522627a83f38").month(1, 2026), ck("q_522627a83f38")),
            revenue(book, ck("q_522627a83f38").month(2, 2026), ck("q_522627a83f38")),
        ],
    )
    put("q_56ffb6b638d7", "percent", price_effect_percent(book, ck("q_56ffb6b638d7"), book.code_of_question_name("Má lợn nướng nước mắm"), date(2026, 4, 15), 30))
    put(
        "q_5816b4178500",
        "percent",
        percent_change(revenue(book, ck("q_5816b4178500").month(1, 2026), ck("q_5816b4178500")), revenue(book, ck("q_5816b4178500").month(1, 2025), ck("q_5816b4178500"))),
    )
    put(
        "q_58215441e762",
        "percent",
        percent_change(revenue(book, ck("q_58215441e762").month(5, 2026), ck("q_58215441e762")), revenue(book, ck("q_58215441e762").month(5, 2025), ck("q_58215441e762"))),
    )
    put("q_5971d8343cc7", "number", fmt.quantity(item_base_quantity(book, ck("q_5971d8343cc7").month(9, 2025), ck("q_5971d8343cc7"), book.code_of_question_name("Cháo ngao"))))
    put(
        "q_5a5a452f87d4",
        "percent",
        percent_change(shift_revenue(book, ck("q_5a5a452f87d4").month(5, 2025), ck("q_5a5a452f87d4"), "chiều"), shift_revenue(book, ck("q_5a5a452f87d4").month(5, 2025), ck("q_5a5a452f87d4"), "sáng")),
    )
    hit, base = customers_with_at_least_n_orders(book, ck("q_5ab41aca6861").month(3, 2026), ck("q_5ab41aca6861"), 9)
    put("q_5ab41aca6861", "percent", fmt.percent(hit / base * 100.0))
    put("q_5b4680c1ccf2", "string", best_sellers(book, ck("q_5b4680c1ccf2").this_week(), ck("q_5b4680c1ccf2"), 1)[0])
    put(
        "q_5df03c21af61",
        "percent",
        percent_change(shift_order_count(book, ck("q_5df03c21af61").month(4, 2025), ck("q_5df03c21af61"), "chiều"), shift_order_count(book, ck("q_5df03c21af61").month(4, 2025), ck("q_5df03c21af61"), "sáng")),
    )
    put("q_5f4f4f35f9fb", "number", average_order_revenue(book, ck("q_5f4f4f35f9fb").month(3), ck("q_5f4f4f35f9fb")))
    put(
        "q_5f750197dcc0",
        "percent",
        fmt.percent(customer_group_revenue(book, ck("q_5f750197dcc0").this_month(), ck("q_5f750197dcc0"), "thân thiết") / revenue(book, ck("q_5f750197dcc0").this_month(), ck("q_5f750197dcc0")) * 100.0),
    )
    put("q_65162e8741f6", "percent", price_effect_percent(book, ck("q_65162e8741f6"), book.code_of_question_name("bo luc lac khoai tay"), date(2025, 11, 14), 7))
    debt = outstanding_debt(book)
    top_debt = debt.groupby("ma_khach")["con_no"].sum().reset_index().sort_values(["con_no", "ma_khach"], ascending=[False, True])
    put(
        "q_67412073e116",
        "table",
        fmt.table(columns=["khach_hang", "so_tien_no"], rows=[[str(r.ma_khach), int(r.con_no)] for r in top_debt.head(5).itertuples()]),
    )
    put("q_693e2a329c10", "list", list(top_customers_by_revenue(book, ck("q_693e2a329c10").last_week(), ck("q_693e2a329c10"), 5)))
    put("q_6ad74d9cb245", "number", average_order_revenue(book, ck("q_6ad74d9cb245").last_week(), ck("q_6ad74d9cb245")))
    put("q_6bf3b5bc42fc", "number", customers_with_at_least_n_orders(book, ck("q_6bf3b5bc42fc").month(5), ck("q_6bf3b5bc42fc"), 9)[0])
    put(
        "q_6bf3c6b59786",
        "percent",
        fmt.percent(channel_revenue(book, ck("q_6bf3c6b59786").month(1, 2026), ck("q_6bf3c6b59786"), "store") / revenue(book, ck("q_6bf3c6b59786").month(1, 2026), ck("q_6bf3c6b59786")) * 100.0),
    )
    put("q_7260611e1637", "number", employee_revenue(book, ck("q_7260611e1637").this_month(), ck("q_7260611e1637"), "NV001"))
    put("q_73aa64c2c7cf", "number", days_with_revenue_at_least(book, ck("q_73aa64c2c7cf").month(7, 2025), ck("q_73aa64c2c7cf"), 38_000_000))
    put("q_78b932b4a560", "number", stock_value(book))
    put("q_7e5199bfe720", "number", purchase_cost(book, ck("q_7e5199bfe720").this_month(), ck("q_7e5199bfe720")))
    put(
        "q_7e7b3dc1de86",
        "list",
        [
            channel_revenue(book, ck("q_7e7b3dc1de86").month(6, 2025), ck("q_7e7b3dc1de86"), "store"),
            channel_revenue(book, ck("q_7e7b3dc1de86").month(6, 2025), ck("q_7e7b3dc1de86"), "phone"),
        ],
    )
    put("q_856d8521b9ea", "number", order_count(book, ck("q_856d8521b9ea").year_to_date(), ck("q_856d8521b9ea")))
    put(
        "q_86dd535ae674",
        "percent",
        percent_change(shift_order_count(book, ck("q_86dd535ae674").month(10, 2025), ck("q_86dd535ae674"), "chiều"), shift_order_count(book, ck("q_86dd535ae674").month(10, 2025), ck("q_86dd535ae674"), "sáng")),
    )
    ages = debt_age_days(book, date(2026, 7, 22))
    put(
        "q_8a85aa9be5ef",
        "list",
        [
            int(debt.loc[ages[(ages >= 0) & (ages <= 7)].index, "con_no"].sum()),
            int(debt.loc[ages[(ages >= 8) & (ages <= 15)].index, "con_no"].sum()),
            int(debt.loc[ages[ages > 15].index, "con_no"].sum()),
        ],
    )
    put("q_8d52a75f3314", "string", customer_with_most_orders(book, ck("q_8d52a75f3314").month(1, 2026), ck("q_8d52a75f3314")))
    put("q_8db445924873", "number", customers_with_at_least_n_orders(book, ck("q_8db445924873").month(11, 2025), ck("q_8db445924873"), 8)[0])
    put("q_95aa9007198f", "unanswerable", reason="sổ không ghi thái độ hay mức độ khó tính của khách")
    put(
        "q_9649687d5e8b",
        "list",
        [
            revenue(book, ck("q_9649687d5e8b").month(3, 2025), ck("q_9649687d5e8b")),
            revenue(book, ck("q_9649687d5e8b").month(4, 2025), ck("q_9649687d5e8b")),
            revenue(book, ck("q_9649687d5e8b").month(5, 2025), ck("q_9649687d5e8b")),
        ],
    )
    put("q_9aa0981148ef", "number", shift_revenue(book, ck("q_9aa0981148ef").month(1, 2026), ck("q_9aa0981148ef"), "sáng"))
    put("q_9b5bf8a560a1", "number", revenue(book, ck("q_9b5bf8a560a1").last_n_days(30), ck("q_9b5bf8a560a1")))
    put("q_a6e86ecce3f6", "number", employee_revenue(book, ck("q_a6e86ecce3f6").month(5, 2026), ck("q_a6e86ecce3f6"), "NV005"))
    hit, base = customers_with_at_least_n_orders(book, ck("q_a904adc2606a").month(2, 2026), ck("q_a904adc2606a"), 5)
    put("q_a904adc2606a", "percent", fmt.percent(hit / base * 100.0))
    put("q_b0bffe2031c5", "string", customer_with_most_orders(book, ck("q_b0bffe2031c5").month(9, 2025), ck("q_b0bffe2031c5")))
    put("q_b38db1ef2bcc", "string", customer_with_most_cancellations(book, ck("q_b38db1ef2bcc").quarter(3, 2025), ck("q_b38db1ef2bcc")))
    put("q_b696d918fcc6", "number", group_revenue(book, ck("q_b696d918fcc6").month(11, 2025), ck("q_b696d918fcc6"), "chiên xào"))
    put("q_baa735ba5e5f", "unanswerable", reason="sổ không ghi lý do trả hàng của đơn")
    put("q_bdbe8ca608ce", "date", fmt.month_answer(best_revenue_month(book, ck("q_bdbe8ca608ce"), ((2026, 2), (2026, 3), (2026, 4)))))
    put("q_be4ad5df428d", "number", revenue(book, ck("q_be4ad5df428d").year_to_date(), ck("q_be4ad5df428d")))
    put("q_beed6d8924db", "number", employee_revenue(book, ck("q_beed6d8924db").month(8, 2025), ck("q_beed6d8924db"), "NV002"))
    put("q_bfecad2e9a15", "number", items_in_at_least_n_orders(book, ck("q_bfecad2e9a15").month(5, 2025), ck("q_bfecad2e9a15"), 172))
    hit, base = customers_with_at_least_n_orders(book, ck("q_c16ed84d6481").month(7, 2025), ck("q_c16ed84d6481"), 6)
    put("q_c16ed84d6481", "percent", fmt.percent(hit / base * 100.0))
    r6 = revenue(book, ck("q_c6940f281136").month(6, 2025), ck("q_c6940f281136"))
    r7 = revenue(book, ck("q_c6940f281136").month(7, 2025), ck("q_c6940f281136"))
    r8 = revenue(book, ck("q_c6940f281136").month(8, 2025), ck("q_c6940f281136"))
    put("q_c6940f281136", "boolean", bool(r7 > r6 and r8 > r7))
    put("q_c76ae61c6092", "number", order_count(book, ck("q_c76ae61c6092").last_n_days(30), ck("q_c76ae61c6092")))
    put("q_ca2c1d05618a", "percent", cancel_rate(book, ck("q_ca2c1d05618a").this_month(), ck("q_ca2c1d05618a")))
    put("q_caf3b2f243d4", "date", fmt.month_answer(best_revenue_month(book, ck("q_caf3b2f243d4"), ((2026, 4), (2026, 5), (2026, 6)))))
    put("q_cb02efab0f93", "number", average_order_revenue(book, ck("q_cb02efab0f93").month(5, 2025), ck("q_cb02efab0f93")))
    put("q_cd0cfcf59c38", "number", average_order_revenue(book, ck("q_cd0cfcf59c38").month(9, 2025), ck("q_cd0cfcf59c38")))
    put(
        "q_cdd8eec83c7a",
        "percent",
        percent_change(shift_revenue(book, ck("q_cdd8eec83c7a").last_week(), ck("q_cdd8eec83c7a"), "chiều"), shift_revenue(book, ck("q_cdd8eec83c7a").last_week(), ck("q_cdd8eec83c7a"), "sáng")),
    )
    put(
        "q_d2f89e3c815d",
        "percent",
        fmt.percent(group_revenue(book, ck("q_d2f89e3c815d").month(5, 2026), ck("q_d2f89e3c815d"), "bia") / revenue(book, ck("q_d2f89e3c815d").month(5, 2026), ck("q_d2f89e3c815d")) * 100.0),
    )
    put(
        "q_d3ef941d6105",
        "percent",
        percent_change(revenue(book, ck("q_d3ef941d6105").month(2, 2025), ck("q_d3ef941d6105")), revenue(book, ck("q_d3ef941d6105").month(1, 2025), ck("q_d3ef941d6105"))),
    )
    put("q_db00aee1a23d", "number", int(debt["ma_khach"].nunique()))
    put("q_dd874c3e9e03", "number", average_order_revenue(book, ck("q_dd874c3e9e03").last_week(), ck("q_dd874c3e9e03")))
    put("q_de54a69c7dce", "number", customers_with_at_least_n_orders(book, ck("q_de54a69c7dce").month(10, 2025), ck("q_de54a69c7dce"), 8)[0])
    put(
        "q_e096ce51b13d",
        "percent",
        percent_change(revenue(book, ck("q_e096ce51b13d").this_month(), ck("q_e096ce51b13d")), revenue(book, ck("q_e096ce51b13d").last_month_same_days(), ck("q_e096ce51b13d"))),
    )
    put("q_e18836a94216", "number", items_in_at_least_n_orders(book, ck("q_e18836a94216").month(4, 2025), ck("q_e18836a94216"), 157))
    put(
        "q_ea97617772d0",
        "percent",
        percent_change(revenue(book, ck("q_ea97617772d0").month(4, 2026), ck("q_ea97617772d0")), revenue(book, ck("q_ea97617772d0").month(3, 2026), ck("q_ea97617772d0"))),
    )
    put("q_ec17ef854d8a", "number", customer_group_revenue(book, ck("q_ec17ef854d8a").month(3, 2026), ck("q_ec17ef854d8a"), "thân thiết"))
    put("q_f15ae79ed4ba", "percent", cancel_rate(book, ck("q_f15ae79ed4ba").month(8, 2025), ck("q_f15ae79ed4ba")))
    put("q_f16bd70756d1", "number", revenue(book, ck("q_f16bd70756d1").year_to_date(), ck("q_f16bd70756d1")))
    put("q_f53d89a0743e", "number", revenue(book, ck("q_f53d89a0743e").month(9, 2025), ck("q_f53d89a0743e")))
    put("q_f56bee880344", "number", revenue(book, ck("q_f56bee880344").month(8, 2025), ck("q_f56bee880344")))
    put("q_f971c5fb2353", "percent", price_effect_percent(book, ck("q_f971c5fb2353"), book.code_of_question_name("Mực rán nước mắm"), date(2025, 5, 29), 14))
    put("q_f9a0fa4ed236", "number", int(debt.loc[ages[ages > 10].index, "con_no"].sum()))
    put("q_f9c2f8a2a73e", "number", item_revenue(book, ck("q_f9c2f8a2a73e").month(10, 2025), ck("q_f9c2f8a2a73e"), book.code_of_question_name("Canh chua cá tràu")))
    put("q_fa29edc5f8ab", "date", fmt.day_answer(best_revenue_day(book, ck("q_fa29edc5f8ab").month(10, 2025), ck("q_fa29edc5f8ab"))))
    r9 = revenue(book, ck("q_fb4bf09137a7").month(9, 2025), ck("q_fb4bf09137a7"))
    r10 = revenue(book, ck("q_fb4bf09137a7").month(10, 2025), ck("q_fb4bf09137a7"))
    r11 = revenue(book, ck("q_fb4bf09137a7").month(11, 2025), ck("q_fb4bf09137a7"))
    put("q_fb4bf09137a7", "boolean", bool(r10 > r9 and r11 > r10))
    put("q_fbf739189e42", "number", int(debt["con_no"].sum()))
    put("q_ffc8757f6b7d", "number", orders_with_revenue_at_least(book, ck("q_ffc8757f6b7d").month(7, 2025), ck("q_ffc8757f6b7d"), 1_000_000))

    answered = {line["id"] for line in out}
    missing = [qid for qid in questions if qid not in answered]
    if missing:
        raise ValueError(f"questions without an answer line: {missing}")
    extra = [qid for qid in answered if qid not in questions]
    if extra:
        raise ValueError(f"answer lines for unknown questions: {extra}")
    order = list(questions)
    by_id = {line["id"]: line for line in out}
    return tuple(by_id[qid] for qid in order)


def main() -> None:
    book = Ledger()
    written = write_answers(ANSWERS_PATH, build_answers(book))
    print(f"{SHOP}: wrote {written} answers to {ANSWERS_PATH}")


if __name__ == "__main__":
    main()
