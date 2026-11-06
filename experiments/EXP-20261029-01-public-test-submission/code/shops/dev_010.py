from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from datamate import Clock, Period, fmt, fold_key, parse_date, parse_datetime, parse_money, parse_number, read_table, squeeze
from datamate.fmt import load_questions, write_answers
from datamate.tabio import drop_repeated_header_rows

SHOP = "dev_010"
EXPERIMENT_ROOT = CODE_ROOT.parent
DATA_DIR = Path("/Users/lebahoai/Workspace/zalo/2026/public_test/data") / SHOP
QUESTIONS_PATH = DATA_DIR / "questions.jsonl"
ANSWERS_PATH = EXPERIMENT_ROOT / "out" / "answers" / f"{SHOP}.jsonl"

ORDER_CODE = re.compile(r"^ORD\d+$")

STATUS_DONE = "hoàn thành"
STATUS_CANCELLED = "huỷ"
STATUS_RETURNED = "trả hàng"
STATUS_SHIPPING = "đang giao"

STATUS_MAP = {
    "completed": STATUS_DONE,
    "cancelled": STATUS_CANCELLED,
    "returned": STATUS_RETURNED,
    "shipping": STATUS_SHIPPING,
}

PAY_METHODS = frozenset({"cash", "transfer", "ewallet", "cod", "debt"})
CHANNELS = frozenset({"store", "phone", "zalo_oa"})

UNIT_FACTORS = {
    ("Tã dán Bobby size M 76 miếng", "thùng"): 4,
    ("Tã quần Huggies Dry size L 68 miếng", "thùng"): 4,
    ("Tã dán Merries size M 64 miếng", "thùng"): 4,
    ("Miếng lót sơ sinh Bobby Newborn 1 108 miếng", "thùng"): 6,
    ("Bột ăn dặm Ridielac Gold gạo sữa 200g", "thùng"): 12,
    ("Khăn ướt Bobby không mùi 100 tờ", "lốc"): 4,
    ("Khăn ướt Bobby không mùi 100 tờ", "thùng"): 24,
    ("Sữa tắm gội Johnson's Baby 500ml", "thùng"): 12,
    ("Sữa tắm Lactacyd BB 250ml", "thùng"): 12,
    ("Nước giặt xả D-nee 3000ml", "thùng"): 4,
    ("Váng sữa Monte vani vỉ 4 hộp 55g", "thùng"): 6,
    ("Phấn rôm Johnson's Baby 200g", "thùng"): 24,
    ("Tắm gội toàn thân D-nee Pure 380ml", "thùng"): 12,
    ("Nước rửa bình sữa D-nee 620ml", "thùng"): 12,
    ("Tã quần Moony size L 44 miếng", "thùng"): 4,
    ("Tã dán Huggies Dry Newborn 60 miếng", "thùng"): 6,
    ("Tã quần Bobby size XL 62 miếng", "thùng"): 4,
    ("Cháo tươi SG Food Baby gà cà rốt 240g", "thùng"): 30,
    ("Tăm bông trẻ em Sakura hộp 180 que", "lốc"): 12,
    ("Phô mai Con Bò Cười hộp 8 miếng", "thùng"): 24,
    ("Sữa pha sẵn GrowPLUS+ đỏ 110ml lốc 4", "thùng"): 12,
}

QUESTION_ITEM_ALIASES = {
    "gang tay tat chan so sinh set 3 doi": "SP0044",
    "hoa qua nghien hippis organic 100g": "SP0058",
}


class Ledger:
    """Năm bảng quan hệ của dev_010 đã ingest, kiểm kê và nối khoá."""

    def __init__(self) -> None:
        self.catalog = self._read_catalog()
        self.customers = self._read_customers()
        self.daily_subtotals, self.orders = self._read_orders()
        self.lines = self._read_lines()
        self.payments = self._read_payments()
        self.orders = self._attach_line_totals()
        self.data_span = Period(start=self.orders["ngay"].min(), end=self.orders["ngay"].max(), label="dữ liệu")

    def _read_catalog(self) -> pd.DataFrame:
        frame = read_table(DATA_DIR / "san_pham.csv", header_row=0)
        frame = frame.rename(columns={"Mã vạch": "ma_hang", "ten_hang": "ten_hang", "Đơn vị tính": "dvt_co_ban", "Nhóm hàng": "nhom_hang"})
        frame["ma_hang"] = frame["ma_hang"].map(squeeze)
        frame["ten_hang"] = frame["ten_hang"].map(squeeze)
        frame["dvt_co_ban"] = frame["dvt_co_ban"].map(squeeze)
        frame["nhom_hang"] = frame["nhom_hang"].map(squeeze)
        if frame["ma_hang"].duplicated().any():
            raise ValueError("duplicate product codes in catalog")
        return frame[["ma_hang", "ten_hang", "dvt_co_ban", "nhom_hang"]].reset_index(drop=True)

    def _read_customers(self) -> pd.DataFrame:
        frame = read_table(DATA_DIR / "khach_hang.csv", header_row=0)
        frame = frame.rename(columns={"Mã khách": "ma_khach", "Khách lẻ/sỉ": "ten_khach", "Loại khách": "nhom_khach"})
        frame["ma_khach"] = frame["ma_khach"].map(squeeze)
        frame["ten_khach"] = frame["ten_khach"].map(squeeze)
        frame["nhom_khach"] = frame["nhom_khach"].map(squeeze)
        if frame["ma_khach"].duplicated().any():
            raise ValueError("duplicate customer codes")
        return frame[["ma_khach", "ten_khach", "nhom_khach"]].reset_index(drop=True)

    def _read_orders(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        raw = read_table(DATA_DIR / "don_hang.csv", header_row=0)
        raw["so_ct"] = raw["Số CT"].map(squeeze)
        is_order = raw["so_ct"].str.match(ORDER_CODE)
        subtotals = raw[~is_order].copy()
        frame = raw[is_order].copy()
        if frame["so_ct"].duplicated().any():
            raise ValueError("duplicate order codes")
        for column in ("Thành tiền", "Con no", "Tiền giảm", "Phí vận chuyển", "Khách trả"):
            frame[column] = frame[column].map(lambda v: parse_money(v))
            subtotals[column] = subtotals[column].map(lambda v: parse_money(v))
        frame = frame.rename(
            columns={
                "so_ct": "ma_don",
                "Kênh đặt": "kenh",
                "Thành tiền": "tong_don",
                "Con no": "con_no_ghi",
                "Phương thức TT": "hinh_thuc",
                "Tiền giảm": "giam_don",
                "Phí vận chuyển": "phi_giao",
                "Khách trả": "khach_tra_ghi",
                "Mã thẻ": "ma_khach",
            }
        )
        frame["ngay"] = frame["Date"].map(parse_date)
        frame["trang_thai"] = frame["Xử lý"].map(self._status_of)
        frame["ma_khach"] = frame["ma_khach"].map(lambda v: squeeze(v) or None)
        frame["kenh"] = frame["kenh"].map(squeeze)
        frame["hinh_thuc"] = frame["hinh_thuc"].map(squeeze)
        if frame["ngay"].isna().any():
            raise ValueError("order without parsable date")
        if not set(frame["hinh_thuc"]) <= PAY_METHODS:
            raise ValueError(f"unknown pay method: {set(frame['hinh_thuc']) - PAY_METHODS}")
        if not set(frame["kenh"]) <= CHANNELS:
            raise ValueError(f"unknown channel: {set(frame['kenh']) - CHANNELS}")
        frame = frame.merge(self.customers[["ma_khach", "nhom_khach"]], on="ma_khach", how="left")
        orphan = frame["ma_khach"].notna() & frame["nhom_khach"].isna()
        if orphan.any():
            raise ValueError(f"orders with unknown customer: {int(orphan.sum())}")
        keep = ["ma_don", "ngay", "kenh", "hinh_thuc", "trang_thai", "ma_khach", "nhom_khach", "tong_don", "giam_don", "phi_giao", "khach_tra_ghi", "con_no_ghi"]
        return subtotals.reset_index(drop=True), frame[keep].reset_index(drop=True)

    @staticmethod
    def _status_of(raw: Any) -> str:
        key = squeeze(raw).casefold()
        if key not in STATUS_MAP:
            raise ValueError(f"unknown order status: {raw!r}")
        return STATUS_MAP[key]

    def _read_lines(self) -> pd.DataFrame:
        raw = read_table(DATA_DIR / "chi_tiet_don.csv", header_row=0)
        frame = drop_repeated_header_rows(raw)
        frame = frame.drop_duplicates().reset_index(drop=True)
        frame = frame.rename(columns={"Mã bill": "ma_don", "Mã H.hóa": "ma_hang", "No.": "stt", "dvt": "dvt_dong"})
        frame["ma_don"] = frame["ma_don"].map(squeeze)
        frame["ma_hang"] = frame["ma_hang"].map(squeeze)
        frame["dvt_dong"] = frame["dvt_dong"].map(squeeze)
        frame["thanh_tien"] = frame["Cộng"].map(lambda v: parse_money(v))
        frame["giam_dong"] = frame["CK"].map(lambda v: parse_money(v))
        frame["don_gia"] = frame["Đơn giá (đ)"].map(lambda v: parse_money(v))
        frame["so_luong"] = frame["SoLuong"].map(lambda v: parse_number(v))
        frame["sl_co_ban"] = frame["SL quy đổi"].map(lambda v: parse_number(v))
        if frame.duplicated(subset=["ma_don", "stt"]).any():
            raise ValueError("line numbers repeat inside an order after exact dedupe")
        frame = frame.merge(self.catalog, on="ma_hang", how="left")
        if frame["ten_hang"].isna().any():
            raise ValueError(f"lines with unknown product: {int(frame['ten_hang'].isna().sum())}")
        frame = frame.merge(self.orders[["ma_don", "ngay", "trang_thai", "ma_khach", "nhom_khach", "hinh_thuc", "kenh"]], on="ma_don", how="left")
        if frame["ngay"].isna().any():
            raise ValueError(f"lines with unknown order: {int(frame['ngay'].isna().sum())}")
        keep = ["ma_don", "stt", "ma_hang", "ten_hang", "nhom_hang", "dvt_dong", "dvt_co_ban", "so_luong", "sl_co_ban", "don_gia", "giam_dong", "thanh_tien", "ngay", "trang_thai", "ma_khach", "nhom_khach", "hinh_thuc", "kenh"]
        return frame[keep].reset_index(drop=True)

    def _read_payments(self) -> pd.DataFrame:
        frame = read_table(DATA_DIR / "thanh_toan.csv", header_row=0)
        frame = frame.rename(columns={"Loại TT": "loai", "Ngay thu": "thoi_diem", "So tien": "so_tien", "Mã đơn": "ma_don", "Mã TT": "ma_phieu"})
        frame["ma_don"] = frame["ma_don"].map(squeeze)
        frame["loai"] = frame["loai"].map(squeeze)
        frame["so_tien"] = frame["so_tien"].map(lambda v: parse_money(v))
        frame["thoi_diem"] = frame["thoi_diem"].map(parse_datetime)
        frame["ngay_thu"] = frame["thoi_diem"].map(lambda v: v.date())
        if frame["ma_phieu"].duplicated().any():
            raise ValueError("duplicate payment codes")
        orphan = ~frame["ma_don"].isin(set(self.orders["ma_don"]))
        if orphan.any():
            raise ValueError(f"payments with unknown order: {int(orphan.sum())}")
        return frame[["ma_phieu", "ma_don", "loai", "so_tien", "thoi_diem", "ngay_thu"]].reset_index(drop=True)

    def _attach_line_totals(self) -> pd.DataFrame:
        sums = self.lines.groupby("ma_don", sort=False).agg(doanh_thu=("thanh_tien", "sum"), so_dong=("stt", "size")).reset_index()
        out = self.orders.merge(sums, on="ma_don", how="left")
        out["so_dong"] = out["so_dong"].fillna(0).astype(int)
        out["doanh_thu"] = out["doanh_thu"].fillna(0).astype(int)
        return out

    def visible_orders(self, period: Period, clock: Clock) -> pd.DataFrame:
        mask = (self.orders["ngay"] >= period.start) & (self.orders["ngay"] <= period.end) & (self.orders["ngay"] <= clock.as_of)
        return self.orders[mask]

    def revenue_orders(self, period: Period, clock: Clock) -> pd.DataFrame:
        placed = self.visible_orders(period, clock)
        return placed[~placed["trang_thai"].isin((STATUS_CANCELLED, STATUS_RETURNED))]

    def revenue_lines(self, period: Period, clock: Clock) -> pd.DataFrame:
        kept = set(self.revenue_orders(period, clock)["ma_don"])
        return self.lines[self.lines["ma_don"].isin(kept)]

    def product_code(self, spoken: str) -> str:
        target = fold_key(spoken)
        if target in QUESTION_ITEM_ALIASES:
            return QUESTION_ITEM_ALIASES[target]
        hits = self.catalog[self.catalog["ten_hang"].map(fold_key) == target]
        if len(hits) != 1:
            raise ValueError(f"product name does not resolve to one code: {spoken}")
        return str(hits["ma_hang"].iloc[0])


def revenue(book: Ledger, period: Period, clock: Clock) -> int:
    return int(book.revenue_orders(period, clock)["doanh_thu"].sum())


def order_count(book: Ledger, period: Period, clock: Clock) -> int:
    return int(len(book.revenue_orders(period, clock)))


def average_order_revenue(book: Ledger, period: Period, clock: Clock) -> int:
    kept = book.revenue_orders(period, clock)
    if kept.empty:
        raise ValueError(f"no revenue orders in {period}")
    return fmt.money(kept["doanh_thu"].sum() / len(kept))


def percent_change(current: float, base: float) -> float:
    if base == 0:
        raise ValueError("percent change against zero base")
    return fmt.percent((current - base) / base * 100.0)


def cancelled_count(book: Ledger, period: Period, clock: Clock) -> int:
    placed = book.visible_orders(period, clock)
    return int((placed["trang_thai"] == STATUS_CANCELLED).sum())


def cancel_rate(book: Ledger, period: Period, clock: Clock) -> float:
    placed = book.visible_orders(period, clock)
    if placed.empty:
        raise ValueError(f"no orders placed in {period}")
    return fmt.percent((placed["trang_thai"] == STATUS_CANCELLED).sum() / len(placed) * 100.0)


def item_revenue(book: Ledger, period: Period, clock: Clock, ma_hang: str) -> int:
    lines = book.revenue_lines(period, clock)
    return int(lines.loc[lines["ma_hang"] == ma_hang, "thanh_tien"].sum())


def product_group_revenue(book: Ledger, period: Period, clock: Clock, group: str) -> int:
    if group not in set(book.catalog["nhom_hang"]):
        raise ValueError(f"unknown product group: {group}")
    lines = book.revenue_lines(period, clock)
    return int(lines.loc[lines["nhom_hang"] == group, "thanh_tien"].sum())


def customer_group_revenue(book: Ledger, period: Period, clock: Clock, group: str) -> int:
    if group not in set(book.customers["nhom_khach"]):
        raise ValueError(f"unknown customer group: {group}")
    kept = book.revenue_orders(period, clock)
    return int(kept.loc[kept["nhom_khach"] == group, "doanh_thu"].sum())


def payment_method_revenue(book: Ledger, period: Period, clock: Clock, method: str) -> int:
    if method not in PAY_METHODS:
        raise ValueError(f"unknown pay method: {method}")
    kept = book.revenue_orders(period, clock)
    return int(kept.loc[kept["hinh_thuc"] == method, "doanh_thu"].sum())


def channel_revenue(book: Ledger, period: Period, clock: Clock, channel: str) -> int:
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel: {channel}")
    kept = book.revenue_orders(period, clock)
    return int(kept.loc[kept["kenh"] == channel, "doanh_thu"].sum())


def share_percent(part: int, whole: int) -> float:
    if whole == 0:
        raise ValueError("share of zero whole")
    return fmt.percent(part / whole * 100.0)


def best_revenue_day(book: Ledger, period: Period, clock: Clock) -> date:
    per_day = book.revenue_orders(period, clock).groupby("ngay")["doanh_thu"].sum()
    top = per_day.max()
    return min(day for day, value in per_day.items() if value == top)


def busiest_day(book: Ledger, period: Period, clock: Clock) -> date:
    per_day = book.revenue_orders(period, clock).groupby("ngay").size()
    top = per_day.max()
    return min(day for day, value in per_day.items() if value == top)


def base_quantity_of_unit(book: Ledger, period: Period, clock: Clock, unit: str) -> float:
    if unit not in set(book.catalog["dvt_co_ban"]):
        raise ValueError(f"no product has base unit {unit}")
    lines = book.revenue_lines(period, clock)
    return float(lines.loc[lines["dvt_co_ban"] == unit, "sl_co_ban"].sum())


def best_sellers(book: Ledger, period: Period, clock: Clock, top: int) -> tuple[str, ...]:
    per_item = book.revenue_lines(period, clock).groupby("ma_hang")["sl_co_ban"].sum().reset_index()
    ranked = per_item.sort_values(["sl_co_ban", "ma_hang"], ascending=[False, True]).reset_index(drop=True)
    if len(ranked) > top and ranked["sl_co_ban"].iloc[top - 1] == ranked["sl_co_ban"].iloc[top]:
        raise ValueError(f"tie at best-seller cut {top} in {period}")
    names = dict(zip(book.catalog["ma_hang"], book.catalog["ten_hang"]))
    return tuple(names[code] for code in ranked["ma_hang"].head(top))


def top_customer_by_revenue(book: Ledger, period: Period, clock: Clock) -> str:
    kept = book.revenue_orders(period, clock)
    per_customer = kept[kept["ma_khach"].notna()].groupby("ma_khach")["doanh_thu"].sum().reset_index()
    ranked = per_customer.sort_values(["doanh_thu", "ma_khach"], ascending=[False, True]).reset_index(drop=True)
    return str(ranked["ma_khach"].iloc[0])


def debt_by_order(book: Ledger, day: date) -> pd.DataFrame:
    orders = book.orders
    debtors = orders[(orders["hinh_thuc"] == "debt") & (orders["trang_thai"] != STATUS_CANCELLED) & (orders["ngay"] <= day)]
    paid = book.payments[book.payments["ngay_thu"] <= day].groupby("ma_don")["so_tien"].sum()
    out = debtors[["ma_don", "ma_khach", "ngay", "tong_don"]].copy()
    out["da_tra"] = out["ma_don"].map(paid).fillna(0).astype(int)
    out["con_no"] = out["tong_don"] - out["da_tra"]
    if (out["con_no"] < 0).any():
        raise ValueError("overpaid debt order")
    return out[out["con_no"] > 0].reset_index(drop=True)


def total_debt(book: Ledger, day: date) -> int:
    return int(debt_by_order(book, day)["con_no"].sum())


def debtors_ranked(book: Ledger, day: date) -> pd.DataFrame:
    owed = debt_by_order(book, day)
    per_customer = owed[owed["ma_khach"].notna()].groupby("ma_khach")["con_no"].sum().reset_index()
    return per_customer.sort_values(["con_no", "ma_khach"], ascending=[False, True]).reset_index(drop=True)


def top_debtors_table(book: Ledger, day: date, top: int) -> dict[str, Any]:
    ranked = debtors_ranked(book, day)
    if len(ranked) > top and ranked["con_no"].iloc[top - 1] == ranked["con_no"].iloc[top]:
        raise ValueError(f"tie at debtor cut {top}")
    rows = [[str(code), int(owed)] for code, owed in zip(ranked["ma_khach"].head(top), ranked["con_no"].head(top))]
    return fmt.table(columns=["khach_hang", "con_no"], rows=rows)


def debt_collected(book: Ledger, period: Period, clock: Clock) -> int:
    orders = book.orders
    debt_orders = orders[(orders["hinh_thuc"] == "debt") & (orders["trang_thai"] != STATUS_CANCELLED)][["ma_don", "ngay"]]
    pays = book.payments.merge(debt_orders, on="ma_don", how="inner")
    later = pays[(pays["ngay_thu"] > pays["ngay"]) & (pays["ngay_thu"] >= period.start) & (pays["ngay_thu"] <= period.end) & (pays["ngay_thu"] <= clock.as_of)]
    return int(later["so_tien"].sum())


def build_answers(book: Ledger) -> tuple[dict[str, Any], ...]:
    questions = load_questions(QUESTIONS_PATH)
    as_of = {q["id"]: q["as_of_date"] for q in questions}
    answers: dict[str, dict[str, Any]] = {}

    def put(qid: str, answer_type: str, value: Any = None, *, reason: str | None = None) -> None:
        if qid not in as_of:
            raise ValueError(f"unknown question id: {qid}")
        if qid in answers:
            raise ValueError(f"question answered twice: {qid}")
        answers[qid] = fmt.answer_line(qid, answer_type, value, reason=reason)

    def ck(qid: str) -> Clock:
        return Clock(as_of[qid])

    def rev_month(qid: str, month: int, year: int) -> int:
        return revenue(book, ck(qid).month(month, year), ck(qid))

    put("q_08c521dda3d9", "number", revenue(book, ck("q_08c521dda3d9").quarter(4, 2025), ck("q_08c521dda3d9")))
    put("q_0ae9b7cf7003", "number", customer_group_revenue(book, ck("q_0ae9b7cf7003").month(4, 2026), ck("q_0ae9b7cf7003"), "sỉ"))
    put("q_0e1eff36bbc5", "percent", percent_change(rev_month("q_0e1eff36bbc5", 2, 2026), rev_month("q_0e1eff36bbc5", 1, 2026)))
    put("q_16e72d67a5f4", "number", debt_collected(book, ck("q_16e72d67a5f4").month(12, 2025), ck("q_16e72d67a5f4")))
    put("q_17743de8e260", "number", cancelled_count(book, ck("q_17743de8e260").month(6, 2026), ck("q_17743de8e260")))
    put("q_1f7113a48e4b", "number", fmt.quantity(base_quantity_of_unit(book, ck("q_1f7113a48e4b").yesterday(), ck("q_1f7113a48e4b"), "gói")))
    clock = ck("q_219f01962c05")
    put("q_219f01962c05", "list", [channel_revenue(book, clock.month(1, 2026), clock, "store"), channel_revenue(book, clock.month(1, 2026), clock, "phone")])
    put("q_2edd77d63f85", "percent", cancel_rate(book, ck("q_2edd77d63f85").month(7, 2026), ck("q_2edd77d63f85")))
    clock = ck("q_2f1be262f623")
    put("q_2f1be262f623", "number", item_revenue(book, clock.month(1, 2026), clock, book.product_code("Găng tay tất chân sơ sinh set 3 đôi")))
    put("q_32e315da86e6", "date", fmt.day_answer(best_revenue_day(book, ck("q_32e315da86e6").month(9, 2025), ck("q_32e315da86e6"))))
    put("q_37ee6372a9be", "number", average_order_revenue(book, ck("q_37ee6372a9be").month(2, 2026), ck("q_37ee6372a9be")))
    clock = ck("q_3d543c5b23c8")
    put("q_3d543c5b23c8", "percent", share_percent(product_group_revenue(book, clock.month(6, 2025), clock, "bỉm tã"), revenue(book, clock.month(6, 2025), clock)))
    put("q_3f61cde37841", "date", fmt.day_answer(busiest_day(book, ck("q_3f61cde37841").month(8, 2025), ck("q_3f61cde37841"))))
    clock = ck("q_427b79554ed7")
    put("q_427b79554ed7", "number", item_revenue(book, clock.month(9, 2025), clock, book.product_code("Nước giặt xả D-nee 3000ml")))
    put("q_4647d2db74e4", "number", order_count(book, ck("q_4647d2db74e4").quarter(3, 2025), ck("q_4647d2db74e4")))
    put("q_4b0def80878e", "number", revenue(book, ck("q_4b0def80878e").yesterday(), ck("q_4b0def80878e")))
    put("q_4d7022ecbc52", "percent", percent_change(rev_month("q_4d7022ecbc52", 5, 2026), rev_month("q_4d7022ecbc52", 5, 2025)))
    put("q_547fb41358ed", "percent", percent_change(rev_month("q_547fb41358ed", 6, 2026), rev_month("q_547fb41358ed", 6, 2025)))
    put("q_56f2859cb47d", "number", average_order_revenue(book, ck("q_56f2859cb47d").month(12, 2025), ck("q_56f2859cb47d")))
    put("q_57942b4c8feb", "number", cancelled_count(book, ck("q_57942b4c8feb").month(11, 2025), ck("q_57942b4c8feb")))
    clock = ck("q_5ac3fc3e264c")
    put("q_5ac3fc3e264c", "percent", share_percent(payment_method_revenue(book, clock.month(7, 2025), clock, "transfer"), revenue(book, clock.month(7, 2025), clock)))
    put("q_5c5d114695ca", "percent", cancel_rate(book, ck("q_5c5d114695ca").month(6, 2026), ck("q_5c5d114695ca")))
    clock = ck("q_605c59254c52")
    put("q_605c59254c52", "list", [payment_method_revenue(book, clock.this_month(), clock, "cash"), payment_method_revenue(book, clock.this_month(), clock, "ewallet")])
    put("q_6b3e51830db0", "number", int(len(debtors_ranked(book, date(2026, 9, 6)))))
    put("q_6cb10c20f215", "number", debt_collected(book, ck("q_6cb10c20f215").month(7, 2025), ck("q_6cb10c20f215")))
    put("q_76bdadbeb802", "unanswerable", reason="dữ liệu không ghi mức độ thân thiện của khách")
    put("q_7e293cd1013a", "number", revenue(book, ck("q_7e293cd1013a").yesterday(), ck("q_7e293cd1013a")))
    put("q_7f7b0eab2ab3", "number", revenue(book, ck("q_7f7b0eab2ab3").today(), ck("q_7f7b0eab2ab3")))
    put("q_807c3cdae34f", "percent", percent_change(rev_month("q_807c3cdae34f", 12, 2025), rev_month("q_807c3cdae34f", 11, 2025)))
    put("q_81bd98f792f6", "number", customer_group_revenue(book, ck("q_81bd98f792f6").month(4, 2026), ck("q_81bd98f792f6"), "thân thiết"))
    clock = ck("q_84ccc0e4f51d")
    put("q_84ccc0e4f51d", "percent", share_percent(customer_group_revenue(book, clock.month(8, 2026), clock, "thân thiết"), revenue(book, clock.month(8, 2026), clock)))
    put("q_85b3a96e689b", "number", product_group_revenue(book, ck("q_85b3a96e689b").month(5, 2025), ck("q_85b3a96e689b"), "bình sữa"))
    put("q_908ce2873a57", "string", top_customer_by_revenue(book, ck("q_908ce2873a57").month(5, 2026), ck("q_908ce2873a57")))
    put("q_914529f4d2e2", "number", order_count(book, ck("q_914529f4d2e2").yesterday(), ck("q_914529f4d2e2")))
    put("q_9e6f314a5bd8", "table", top_debtors_table(book, date(2026, 7, 31), 5))
    put("q_a33f5513b520", "number", average_order_revenue(book, ck("q_a33f5513b520").month(11, 2025), ck("q_a33f5513b520")))
    put("q_aacb2ba3f300", "number", debt_collected(book, ck("q_aacb2ba3f300").month(11, 2025), ck("q_aacb2ba3f300")))
    put("q_acb6a360a60d", "number", revenue(book, ck("q_acb6a360a60d").yesterday(), ck("q_acb6a360a60d")))
    put("q_ad5492b5897c", "percent", cancel_rate(book, ck("q_ad5492b5897c").month(6, 2025), ck("q_ad5492b5897c")))
    put("q_b36cb72072f1", "number", cancelled_count(book, ck("q_b36cb72072f1").month(4, 2026), ck("q_b36cb72072f1")))
    clock = ck("q_b61b5951799d")
    put("q_b61b5951799d", "percent", share_percent(product_group_revenue(book, clock.month(5, 2026), clock, "ăn dặm"), revenue(book, clock.month(5, 2026), clock)))
    put("q_ba875ec0872f", "number", rev_month("q_ba875ec0872f", 8, 2026))
    put("q_bc879c2a6de5", "table", top_debtors_table(book, date(2026, 9, 6), 3))
    put("q_cb0b3be99b62", "percent", percent_change(rev_month("q_cb0b3be99b62", 7, 2026), rev_month("q_cb0b3be99b62", 7, 2025)))
    put("q_d1c95d7db2ae", "number", fmt.quantity(base_quantity_of_unit(book, ck("q_d1c95d7db2ae").yesterday(), ck("q_d1c95d7db2ae"), "gói")))
    clock = ck("q_d27e2e7a44a6")
    put("q_d27e2e7a44a6", "number", item_revenue(book, clock.month(1, 2026), clock, book.product_code("Hoa quả nghiền HiPPiS Organic 100g")))
    put("q_d2c646bb39ec", "number", total_debt(book, date(2026, 9, 6)))
    put("q_d4ef0c5d0bb2", "list", list(best_sellers(book, ck("q_d4ef0c5d0bb2").month(7, 2025), ck("q_d4ef0c5d0bb2"), 5)))
    put("q_d69464555c58", "number", order_count(book, ck("q_d69464555c58").yesterday(), ck("q_d69464555c58")))
    put("q_d778fbbd804e", "percent", percent_change(rev_month("q_d778fbbd804e", 7, 2025), rev_month("q_d778fbbd804e", 6, 2025)))
    put("q_d8da698d3e5d", "number", order_count(book, ck("q_d8da698d3e5d").quarter(2, 2026), ck("q_d8da698d3e5d")))
    put("q_e2bedb87cc3d", "number", revenue(book, ck("q_e2bedb87cc3d").quarter(1, 2026), ck("q_e2bedb87cc3d")))
    put("q_e848f74be11e", "number", rev_month("q_e848f74be11e", 4, 2026))
    put("q_edf890b68dfd", "number", order_count(book, ck("q_edf890b68dfd").yesterday(), ck("q_edf890b68dfd")))
    put("q_ef0073de2935", "number", rev_month("q_ef0073de2935", 10, 2025))
    put("q_f7fcc8fad30b", "number", order_count(book, ck("q_f7fcc8fad30b").today(), ck("q_f7fcc8fad30b")))
    put("q_fb290d8944ec", "date", fmt.day_answer(best_revenue_day(book, ck("q_fb290d8944ec").month(7, 2025), ck("q_fb290d8944ec"))))
    put("q_fbc812dde384", "string", best_sellers(book, ck("q_fbc812dde384").month(11, 2025), ck("q_fbc812dde384"), 1)[0])
    clock = ck("q_fc4223c66403")
    put("q_fc4223c66403", "percent", share_percent(customer_group_revenue(book, clock.month(12, 2025), clock, "sỉ"), revenue(book, clock.month(12, 2025), clock)))

    missing = [q["id"] for q in questions if q["id"] not in answers]
    if missing:
        raise ValueError(f"questions without answer line: {missing}")
    return tuple(answers[q["id"]] for q in questions)


def main() -> None:
    book = Ledger()
    written = write_answers(ANSWERS_PATH, build_answers(book))
    print(f"{SHOP}: wrote {written} answers to {ANSWERS_PATH}")


if __name__ == "__main__":
    main()
