from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from datamate import Clock, Period, fmt, fold_key, parse_datetime, parse_money, parse_number, read_table, squeeze
from datamate.fmt import load_questions, write_answers
from datamate.tabio import drop_subtotal_rows, sheet_names

SHOP = "dev_004"
EXPERIMENT_ROOT = CODE_ROOT.parent
DATA_DIR = Path("/Users/lebahoai/Workspace/zalo/2026/public_test/data") / SHOP
QUESTIONS_PATH = DATA_DIR / "questions.jsonl"
ANSWERS_PATH = EXPERIMENT_ROOT / "out" / "answers" / f"{SHOP}.jsonl"

STATUS_DONE = "hoàn thành"
STATUS_CANCELLED = "huỷ"
STATUS_RETURNED = "trả hàng"
STATUS_SHIPPING = "đang giao"

STATUS_MAP = {
    "hoàn thành": STATUS_DONE,
    "đã hoàn thành": STATUS_DONE,
    "đã xong": STATUS_DONE,
    "huỷ đơn": STATUS_CANCELLED,
    "không giao được": STATUS_CANCELLED,
    "đổi trả": STATUS_RETURNED,
    "hàng trả về": STATUS_RETURNED,
    "đã trả hàng": STATUS_RETURNED,
    "trả lại": STATUS_RETURNED,
    "đang ship": STATUS_SHIPPING,
    "đang vận chuyển": STATUS_SHIPPING,
    "đang giao hàng": STATUS_SHIPPING,
}

WALK_IN_NAMES = frozenset({"kl", "lẻ", "khách lẻ"})

BUNDLE_ITEMS = (
    "Ống PVC Bình Minh D32 cây 4m",
    "Ống PVC Bình Minh D50 cây 4m",
    "Ống PVC Bình Minh D90 cây 4m",
)
BUNDLE_UNIT = "bó"
BUNDLE_FACTOR = 10.0

SALE_COLUMNS = {
    "Khách hàng (tên)": "khach_raw",
    "Giờ": "gio",
    "Thời gian": "thoi_gian",
    "Ma don": "ma_don_raw",
    "SL bán": "sl_raw",
    "dvt": "dvt",
    "Hàng bán": "hang_raw",
    "Trạng thái xử lý": "trang_thai_raw",
    "Giá 1 đv": "don_gia_raw",
    "Amount": "thanh_tien_raw",
    "Tổng phiếu": "tong_phieu_raw",
}

_LEADING_NUMBER = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)")


def leading_quantity(value: Any) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = _LEADING_NUMBER.match(squeeze(value))
    if match is None:
        raise ValueError(f"unreadable quantity: {value!r}")
    return float(match.group(1).replace(",", "."))


def status_of(raw: Any) -> str:
    key = squeeze(raw).casefold()
    if key not in STATUS_MAP:
        raise ValueError(f"unknown order status: {raw!r}")
    return STATUS_MAP[key]


class Ledger:
    """Sổ bán, danh mục quy đổi, bảng giá, sổ giao, sổ hạn nợ, sổ nhập và tồn kho của dev_004 đã ingest."""

    def __init__(self) -> None:
        self.units = self._read_units()
        self.names = self._read_canonical_names()
        self.lines = self._read_lines()
        self.orders = self._build_orders()
        self.prices = self._read_prices()
        self.deliveries = self._read_deliveries()
        self.due = self._read_due()
        self.purchases = self._read_purchases()
        self.data_span = Period(start=self.orders["ngay"].min(), end=self.orders["ngay"].max(), label="dữ liệu")

    def _read_units(self) -> dict[tuple[str, str], tuple[float, str]]:
        frame = read_table(DATA_DIR / "DanhMuc.xlsx", header_row=0)
        out: dict[tuple[str, str], tuple[float, str]] = {}
        for _, row in frame.iterrows():
            factor = parse_number(row["Hệ số"])
            if factor is None:
                raise ValueError(f"missing factor: {row.to_dict()}")
            out[(fold_key(row["Hàng"]), squeeze(row["Loại ĐV"]))] = (factor, squeeze(row["ĐV gốc"]))
        for name in BUNDLE_ITEMS:
            out[(fold_key(name), BUNDLE_UNIT)] = (BUNDLE_FACTOR, "cây")
        return out

    def _read_canonical_names(self) -> dict[str, str]:
        stock = read_table(DATA_DIR / "TonKho.xlsx", header_row=0)
        return {fold_key(v): squeeze(v) for v in stock["Tên sản phẩm"]}

    def _read_lines(self) -> pd.DataFrame:
        parts: list[pd.DataFrame] = []
        for sheet in sheet_names(DATA_DIR / "SoBanHang.xlsx"):
            raw = read_table(DATA_DIR / "SoBanHang.xlsx", sheet=sheet, header_row=1)
            raw = drop_subtotal_rows(raw, key_columns=["Hàng bán"])
            raw = raw.rename(columns=SALE_COLUMNS)
            raw["sheet"] = sheet
            raw["row_in_sheet"] = range(len(raw))
            parts.append(raw)
        frame = pd.concat(parts, ignore_index=True)
        frame["ma_don"] = frame["ma_don_raw"].map(lambda v: squeeze(v) or None).ffill()
        raw_cols = list(SALE_COLUMNS.values()) + ["ma_don"]
        before = len(frame)
        frame = frame[~frame.duplicated(subset=raw_cols, keep="first")].reset_index(drop=True)
        self.exact_duplicates_dropped = before - len(frame)
        frame["is_head"] = frame["ma_don_raw"].notna()
        frame["sl"] = frame["sl_raw"].map(leading_quantity)
        frame["is_return_line"] = frame["sl"] < 0
        frame["dvt"] = frame["dvt"].map(squeeze)
        frame["hang_key"] = frame["hang_raw"].map(fold_key)
        frame["hang"] = frame["hang_key"].map(lambda k: self.names.get(k))
        if frame["hang"].isna().any():
            missing = sorted(frame.loc[frame["hang"].isna(), "hang_raw"].map(squeeze).unique())
            raise ValueError(f"items not in stock list: {missing}")
        frame["he_so"] = [self.units.get((k, u), (1.0, u))[0] for k, u in zip(frame["hang_key"], frame["dvt"])]
        frame["dv_goc"] = [self.units.get((k, u), (1.0, u))[1] for k, u in zip(frame["hang_key"], frame["dvt"])]
        frame["sl_goc"] = frame["sl"] * frame["he_so"]
        frame["don_gia"] = frame["don_gia_raw"].map(parse_money)
        frame["thanh_tien"] = frame["thanh_tien_raw"].map(parse_money)
        frame["tong_phieu"] = frame["tong_phieu_raw"].map(parse_money)
        frame["gio"] = frame["gio"].map(parse_datetime)
        return frame

    def _build_orders(self) -> pd.DataFrame:
        heads = self.lines[self.lines["is_head"] & ~self.lines["is_return_line"]]
        if heads["ma_don"].duplicated().any():
            raise ValueError(f"order head repeated: {heads.loc[heads['ma_don'].duplicated(), 'ma_don'].tolist()[:5]}")
        orders = heads[["ma_don", "khach_raw", "gio", "thoi_gian", "trang_thai_raw", "tong_phieu", "sheet"]].copy()
        orders["trang_thai"] = orders["trang_thai_raw"].map(status_of)
        returned = set(self.lines.loc[self.lines["is_return_line"], "ma_don"])
        orders["has_return_line"] = orders["ma_don"].isin(returned)
        orders.loc[orders["has_return_line"], "trang_thai"] = STATUS_RETURNED
        orders["khach"] = orders["khach_raw"].map(squeeze)
        orders["vang_lai"] = orders["khach"].map(lambda v: v.casefold() in WALK_IN_NAMES or v == "")
        orders["khach_key"] = [None if w else fold_key(k) for k, w in zip(orders["khach"], orders["vang_lai"])]
        orders["ngay"] = orders["gio"].map(lambda v: v.date())
        sold = self.lines[~self.lines["is_return_line"]]
        orders = orders.merge(sold.groupby("ma_don")["thanh_tien"].sum().rename("doanh_thu"), on="ma_don", how="left")
        orders["tinh_doanh_thu"] = orders["trang_thai"].isin([STATUS_DONE, STATUS_SHIPPING])
        return orders.sort_values("ma_don").reset_index(drop=True)

    def _read_prices(self) -> pd.DataFrame:
        frame = read_table(DATA_DIR / "BangGia.xlsx", header_row=0)
        out = pd.DataFrame(
            {
                "hang": frame["Diễn giải"].map(lambda v: self.names[fold_key(v)]),
                "ngay": frame["Ngày áp dụng"].map(lambda v: parse_datetime(v).date()),
                "gia_cu": frame["Giá cũ"].map(parse_money),
                "gia_moi": frame["Giá mới"].map(parse_money),
            }
        )
        return out.sort_values(["hang", "ngay"], kind="stable").reset_index(drop=True)

    def _read_deliveries(self) -> pd.DataFrame:
        frame = read_table(DATA_DIR / "SoGiaoHang.xlsx", header_row=0)
        return pd.DataFrame(
            {
                "ma_don": frame["Số đơn"].map(squeeze),
                "dot": frame["Lượt giao"].map(lambda v: int(parse_number(v))),
                "ngay": frame["Thời gian giao"].map(lambda v: parse_datetime(v).date()),
                "hang": frame["Hàng hóa"].map(lambda v: self.names[fold_key(v)]),
                "sl_goc": frame["Số lượng giao"].map(parse_number),
                "dv_goc": frame["ĐV gốc"].map(squeeze),
                "xe": frame["Biển số xe"].map(squeeze),
            }
        )

    def _read_due(self) -> pd.DataFrame:
        frame = read_table(DATA_DIR / "SoHanNo.xlsx", header_row=0)
        return pd.DataFrame(
            {
                "ma_don": frame["Mã đơn hàng"].map(squeeze),
                "ky_han": frame["Kỳ hạn"].map(lambda v: int(parse_number(v))),
                "ngay_phai_tra": frame["Ngày phải trả"].map(lambda v: parse_datetime(v).date()),
            }
        )

    def _read_purchases(self) -> pd.DataFrame:
        frame = read_table(DATA_DIR / "SoNhapHang.xlsx", header_row=0)
        return pd.DataFrame(
            {
                "so_phieu": frame["Số phiếu"].map(squeeze),
                "hang": frame["Product"].map(lambda v: self.names[fold_key(v)]),
                "dvt": frame["ĐVT"].map(squeeze),
                "ghi_chu": frame["Ghi chú"].map(squeeze),
                "ncc": frame["Nhà cung cấp"].map(squeeze),
                "thanh_tien": frame["Thành tiền"].map(parse_money),
                "gia_nhap": frame["Giá nhập"].map(parse_money),
                "ngay": frame["Ngày nhập"].map(lambda v: parse_datetime(v).date()),
                "sl": frame["SL nhập"].map(parse_number),
            }
        )


class Answerer:
    """Các phép tính theo rulebook trên sổ của dev_004, mỗi hàm một luật."""

    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def placed(self, period: Period, as_of: date) -> pd.DataFrame:
        orders = self.ledger.orders
        end = min(period.end, as_of)
        return orders[(orders["ngay"] >= period.start) & (orders["ngay"] <= end)]

    def revenue_orders(self, period: Period, as_of: date) -> pd.DataFrame:
        frame = self.placed(period, as_of)
        return frame[frame["tinh_doanh_thu"]]

    def revenue(self, period: Period, as_of: date) -> int:
        return int(self.revenue_orders(period, as_of)["doanh_thu"].sum())

    def order_count(self, period: Period, as_of: date) -> int:
        return len(self.revenue_orders(period, as_of))

    def average_order_value(self, period: Period, as_of: date) -> int:
        frame = self.revenue_orders(period, as_of)
        if frame.empty:
            raise ValueError(f"no orders in {period}")
        return fmt.money(frame["doanh_thu"].sum() / len(frame))

    def pct_change(self, current: float, previous: float) -> float:
        if previous == 0:
            raise ValueError("previous period is zero")
        return fmt.percent((current - previous) / previous * 100.0)

    def shift_orders(self, period: Period, as_of: date, shift: str) -> pd.DataFrame:
        clock = Clock(as_of)
        frame = self.revenue_orders(period, as_of)
        return frame[frame["gio"].map(clock.shift_of) == shift]

    def daily_revenue(self, period: Period, as_of: date) -> pd.Series:
        return self.revenue_orders(period, as_of).groupby("ngay")["doanh_thu"].sum()

    def days_with_revenue_at_least(self, period: Period, as_of: date, threshold: int) -> int:
        return int((self.daily_revenue(period, as_of) >= threshold).sum())

    def best_revenue_day(self, period: Period, as_of: date) -> date:
        daily = self.daily_revenue(period, as_of)
        top = daily.max()
        return min(day for day, value in daily.items() if value == top)

    def orders_with_revenue_at_least(self, period: Period, as_of: date, threshold: int) -> int:
        return int((self.revenue_orders(period, as_of)["doanh_thu"] >= threshold).sum())

    def best_month(self, months: tuple[tuple[int, int], ...], as_of: date) -> str:
        values = [(self.revenue(Clock(as_of).month(m, y), as_of), (y, m)) for y, m in months]
        top = max(v for v, _ in values)
        winners = [ym for v, ym in values if v == top]
        if len(winners) > 1:
            raise ValueError(f"tie in best month: {winners}")
        return fmt.month_answer(winners[0])

    def cancelled_count(self, period: Period, as_of: date) -> int:
        return int((self.placed(period, as_of)["trang_thai"] == STATUS_CANCELLED).sum())

    def cancel_rate(self, period: Period, as_of: date) -> float:
        frame = self.placed(period, as_of)
        return fmt.percent((frame["trang_thai"] == STATUS_CANCELLED).sum() / len(frame) * 100.0)

    def peak_hour(self, period: Period, as_of: date) -> int:
        hours = self.revenue_orders(period, as_of)["gio"].map(lambda t: t.hour).value_counts()
        top = hours.max()
        return int(min(h for h, n in hours.items() if n == top))

    def orders_per_customer(self, period: Period, as_of: date) -> pd.Series:
        frame = self.revenue_orders(period, as_of)
        frame = frame[~frame["vang_lai"]]
        return frame.groupby("khach_key").size()

    def customers_with_at_least(self, period: Period, as_of: date, n: int) -> int:
        return int((self.orders_per_customer(period, as_of) >= n).sum())

    def share_customers_with_at_least(self, period: Period, as_of: date, n: int) -> float:
        counts = self.orders_per_customer(period, as_of)
        return fmt.percent((counts >= n).sum() / len(counts) * 100.0)

    def top_customer_by_orders(self, period: Period, as_of: date) -> str:
        counts = self.orders_per_customer(period, as_of)
        top = counts.max()
        names = self.ledger.orders.drop_duplicates("khach_key").set_index("khach_key")["khach"]
        winners = sorted(names[k] for k, v in counts.items() if v == top)
        return winners[0]

    def sold_lines(self, period: Period, as_of: date) -> pd.DataFrame:
        valid = set(self.revenue_orders(period, as_of)["ma_don"])
        lines = self.ledger.lines
        return lines[lines["ma_don"].isin(valid) & ~lines["is_return_line"]]

    def base_quantity_by_item(self, period: Period, as_of: date) -> pd.Series:
        return self.sold_lines(period, as_of).groupby("hang")["sl_goc"].sum()

    def item_base_quantity(self, period: Period, as_of: date, item: str) -> float:
        return float(self.base_quantity_by_item(period, as_of).get(item, 0.0))

    def top_items(self, period: Period, as_of: date, k: int) -> tuple[str, ...]:
        qty = self.base_quantity_by_item(period, as_of)
        ranked = sorted(qty.items(), key=lambda kv: (-kv[1], kv[0]))
        if len(ranked) > k and ranked[k - 1][1] == ranked[k][1]:
            raise ValueError(f"tie at cutoff {k}: {ranked[k - 1]} vs {ranked[k]}")
        return tuple(name for name, _ in ranked[:k])

    def unsold_items(self, period: Period, as_of: date) -> int:
        before = set(self.base_quantity_by_item(Period(start=self.ledger.data_span.start, end=period.start - timedelta(days=1)), as_of).index)
        during = set(self.base_quantity_by_item(period, as_of).index)
        return len(before - during)

    def price_rise_effect(self, item: str, rise_day: date, days: int, as_of: date) -> float:
        after = Period(start=rise_day, end=rise_day + timedelta(days=days - 1))
        before = Period(start=rise_day - timedelta(days=days), end=rise_day - timedelta(days=1))
        return self.pct_change(self.item_base_quantity(after, as_of, item), self.item_base_quantity(before, as_of, item))

    def check_price_rise(self, item: str, rise_day: date, new_price: int) -> None:
        prices = self.ledger.prices
        rows = prices[(prices["hang"] == item) & (prices["ngay"] == rise_day)]
        if len(rows) != 1 or int(rows["gia_moi"].iloc[0]) != new_price or not rows["gia_moi"].iloc[0] > rows["gia_cu"].iloc[0]:
            raise ValueError(f"price rise not in price list: {item} {rise_day} {new_price}")

    def visible_deliveries(self, as_of: date) -> pd.DataFrame:
        frame = self.ledger.deliveries
        return frame[frame["ngay"] <= as_of]

    def delivery_rounds_in(self, period: Period, as_of: date) -> int:
        frame = self.visible_deliveries(as_of)
        frame = frame[(frame["ngay"] >= period.start) & (frame["ngay"] <= period.end)]
        return len(frame.drop_duplicates(["ma_don", "dot"]))

    def orders_delivered_in_rounds(self, order_period: Period, as_of: date, min_rounds: int) -> int:
        placed = set(self.placed(order_period, as_of)["ma_don"])
        frame = self.visible_deliveries(as_of)
        frame = frame[frame["ma_don"].isin(placed)]
        rounds = frame.groupby("ma_don")["dot"].nunique()
        return int((rounds >= min_rounds).sum())

    def delivered_quantity(self, order_period: Period, as_of: date, item: str) -> float:
        placed = set(self.placed(order_period, as_of)["ma_don"])
        frame = self.visible_deliveries(as_of)
        frame = frame[frame["ma_don"].isin(placed) & (frame["hang"] == item)]
        return float(frame["sl_goc"].sum())

    def credit_orders(self, as_of: date) -> pd.DataFrame:
        due = self.ledger.due.merge(self.ledger.orders[["ma_don", "ngay", "trang_thai"]], on="ma_don", how="left")
        if due["ngay"].isna().any():
            raise ValueError("credit order missing from sales book")
        due = due[(due["ngay"] <= as_of) & (due["trang_thai"] != STATUS_CANCELLED)]
        return due

    def credit_orders_due_after(self, as_of: date) -> int:
        frame = self.credit_orders(as_of)
        return int((frame["ngay_phai_tra"] > as_of).sum())

    def credit_orders_due_in(self, period: Period, as_of: date) -> int:
        frame = self.credit_orders(as_of)
        return int(((frame["ngay_phai_tra"] >= period.start) & (frame["ngay_phai_tra"] <= period.end)).sum())

    def purchase_frame(self, period: Period, as_of: date) -> pd.DataFrame:
        frame = self.ledger.purchases
        end = min(period.end, as_of)
        return frame[(frame["ngay"] >= period.start) & (frame["ngay"] <= end)]

    def purchase_total(self, period: Period, as_of: date) -> int:
        return int(self.purchase_frame(period, as_of)["thanh_tien"].sum())

    def top_supplier_by_amount(self, period: Period, as_of: date) -> str:
        totals = self.purchase_frame(period, as_of).groupby("ncc")["thanh_tien"].sum()
        top = totals.max()
        return sorted(n for n, v in totals.items() if v == top)[0]


PVC_D32 = "Ống PVC Bình Minh D32 cây 4m"
PVC_D50 = "Ống PVC Bình Minh D50 cây 4m"
PVC_D90 = "Ống PVC Bình Minh D90 cây 4m"
CADIVI_VCMD = "Dây điện Cadivi VCmd 2x2.5 cuộn 100m"
DULUX = "Sơn Dulux Weathershield Powerflexx 5L"
VIGLACERA = "Gạch ốp tường Viglacera 30x60 thùng 8 viên"
ION_LIFE = "Nước kiềm Ion Life 19L"
GAS_PETROLIMEX = "Gas Petrolimex 12kg"
CAT_XAY_TO = "Cát xây tô"

UNANSWERABLE = {
    "q_36182821dc30": "sổ bán chỉ ghi tên khách, không file nào ghi địa chỉ hay tên đường của khách",
    "q_20221903b95b": "không file nào ghi lý do huỷ đơn; trạng thái huỷ chỉ có 'Huỷ đơn' và 'Không giao được'",
    "q_ed4d0362d039": "không file nào có cột nhóm hàng; README chỉ nêu tên vài nhóm, không ghi mặt hàng nào thuộc nhóm nào",
    "q_ef77106ccec0": "không file nào có cột nhóm hàng; README chỉ nêu tên vài nhóm, không ghi mặt hàng nào thuộc nhóm nào",
    "q_fcc5aeef7f8d": "không file nào có cột nhóm hàng; README chỉ nêu tên vài nhóm, không ghi mặt hàng nào thuộc nhóm nào",
}

ABSTAIN: dict[str, str] = {}


def month_of(clock: Clock, month: int, year: int) -> Period:
    return clock.month(month, year)


def solve(a: Answerer, qid: str, clock: Clock) -> tuple[str, Any]:
    t = clock.as_of
    m = lambda month, year: month_of(clock, month, year)
    rev = lambda p: a.revenue(p, t)
    specs: dict[str, Any] = {
        "q_009187cd2960": lambda: ("number", fmt.quantity(a.item_base_quantity(m(5, 2026), t, PVC_D50))),
        "q_013b4ff35811": lambda: ("number", rev(clock.this_week())),
        "q_02feb595d6b7": lambda: ("number", fmt.quantity(a.item_base_quantity(m(3, 2026), t, PVC_D32))),
        "q_03622bae312b": lambda: ("percent", a.share_customers_with_at_least(m(6, 2025), t, 4)),
        "q_10831a6f3a2b": lambda: ("number", a.credit_orders_due_after(t)),
        "q_169a123623e6": lambda: ("percent", a.share_customers_with_at_least(m(6, 2025), t, 3)),
        "q_1a312c2f71ac": lambda: ("percent", a.price_rise_effect(ION_LIFE, date(2025, 10, 18), 30, t)),
        "q_1adddf599009": lambda: ("number", a.credit_orders_due_after(t)),
        "q_203767dd52af": lambda: ("number", a.peak_hour(m(3, 2026), t)),
        "q_22a7258b62bf": lambda: ("percent", a.pct_change(rev(clock.this_month()), rev(clock.last_month_same_days()))),
        "q_2927db159ea7": lambda: ("number", a.order_count(clock.last_n_days(30), t)),
        "q_30b4b858e958": lambda: ("list", list(a.top_items(clock.last_week(), t, 5))),
        "q_32ee3f6d23b0": lambda: ("list", [rev(m(11, 2025)), rev(m(12, 2025)), rev(m(1, 2026))]),
        "q_334da0ba920d": lambda: ("number", a.unsold_items(clock.last_n_days(7), t)),
        "q_3992410a9fd6": lambda: ("number", rev(clock.last_n_days(30))),
        "q_3b30972705b7": lambda: ("number", rev(m(1, 2025))),
        "q_3dd4582ecb10": lambda: ("percent", a.pct_change(rev(m(2, 2026)), rev(m(1, 2026)))),
        "q_41922e7c51ec": lambda: ("percent", a.pct_change(
            int(a.shift_orders(m(1, 2026), t, "chiều")["doanh_thu"].sum()),
            int(a.shift_orders(m(1, 2026), t, "sáng")["doanh_thu"].sum()),
        )),
        "q_48964017991a": lambda: ("number", a.average_order_value(m(6, 2025), t)),
        "q_4cb8711073bd": lambda: ("percent", a.pct_change(
            len(a.shift_orders(clock.last_week(), t, "chiều")), len(a.shift_orders(clock.last_week(), t, "sáng"))
        )),
        "q_52dfb164f8ad": lambda: ("date", fmt.day_answer(a.best_revenue_day(m(5, 2026), t))),
        "q_59f27903845e": lambda: ("number", fmt.quantity(a.delivered_quantity(m(4, 2025), t, CADIVI_VCMD))),
        "q_5c681795e6a0": lambda: ("number", a.orders_delivered_in_rounds(m(11, 2025), t, 2)),
        "q_5d6f195dd3e7": lambda: ("number", a.average_order_value(m(1, 2025), t)),
        "q_5da7465fcd06": lambda: ("number", a.purchase_total(m(1, 2025), t)),
        "q_6019a30cd4fe": lambda: ("number", a.order_count(clock.year_to_date(), t)),
        "q_617cccfd98d1": lambda: ("number", a.cancelled_count(m(3, 2025), t)),
        "q_618001244985": lambda: ("number", a.cancelled_count(m(8, 2025), t)),
        "q_621a456cc773": lambda: ("number", a.customers_with_at_least(m(1, 2026), t, 2)),
        "q_62ec9b7dc79b": lambda: ("list", list(a.top_items(m(3, 2025), t, 5))),
        "q_69dbf1d3cdc5": lambda: ("string", a.top_customer_by_orders(m(5, 2026), t)),
        "q_6bd9c92d0d7e": lambda: ("percent", a.pct_change(rev(m(2, 2026)), rev(m(2, 2025)))),
        "q_6f1b365ba206": lambda: ("string", a.top_items(clock.last_week(), t, 1)[0]),
        "q_6fbb662472fc": lambda: ("number", rev(clock.last_week())),
        "q_6fe399991adb": lambda: ("number", a.customers_with_at_least(m(8, 2025), t, 4)),
        "q_71ead7c337f8": lambda: ("number", a.order_count(clock.year_to_date(), t)),
        "q_7305db18bf51": lambda: ("number", a.credit_orders_due_in(m(4, 2026), t)),
        "q_76edb5c73d98": lambda: ("number", fmt.quantity(a.delivered_quantity(m(3, 2026), t, DULUX))),
        "q_7be6937cf882": lambda: ("number", a.orders_delivered_in_rounds(m(6, 2025), t, 2)),
        "q_7c851b82747f": lambda: ("number", rev(clock.year_to_date())),
        "q_8046cdbac1d4": lambda: ("number", a.days_with_revenue_at_least(m(1, 2026), t, 40_000_000)),
        "q_837cd5892764": lambda: ("percent", a.pct_change(rev(clock.this_month()), rev(clock.last_month_same_days()))),
        "q_8f668570af59": lambda: ("number", a.average_order_value(clock.last_week(), t)),
        "q_90375e5beeab": lambda: ("number", a.order_count(clock.this_week(), t)),
        "q_91a333e16eae": lambda: ("boolean", bool(rev(m(3, 2026)) > rev(m(2, 2026)) and rev(m(4, 2026)) > rev(m(3, 2026)))),
        "q_936c6ef612b2": lambda: ("number", a.orders_delivered_in_rounds(m(3, 2026), t, 2)),
        "q_9bcd14f14b1f": lambda: ("percent", a.share_customers_with_at_least(m(4, 2026), t, 3)),
        "q_9eddae22a244": lambda: ("number", a.credit_orders_due_after(t)),
        "q_a05a32f136e4": lambda: ("number", a.order_count(clock.year_to_date(), t)),
        "q_a119f396d2af": lambda: ("percent", a.cancel_rate(m(2, 2025), t)),
        "q_a18fefbb07ad": lambda: ("number", a.credit_orders_due_in(m(11, 2025), t)),
        "q_ab1417ed8c1b": lambda: ("number", a.orders_with_revenue_at_least(m(5, 2026), t, 1_800_000)),
        "q_ab952d97e345": lambda: ("number", a.unsold_items(clock.last_n_days(7), t)),
        "q_ad782d8acb44": lambda: ("percent", a.pct_change(rev(clock.this_month()), rev(clock.last_month_same_days()))),
        "q_ae7e44a0dc30": lambda: ("number", a.delivery_rounds_in(clock.this_month(), t)),
        "q_af96aaf1f4e2": lambda: ("number", a.credit_orders_due_in(m(2, 2026), t)),
        "q_afc5f7f5f476": lambda: ("number", rev(clock.today())),
        "q_b290d99f9130": lambda: ("percent", a.pct_change(rev(m(4, 2026)), rev(m(4, 2025)))),
        "q_b47894fc33f6": lambda: ("list", [rev(m(5, 2025)), rev(m(6, 2025)), rev(m(7, 2025))]),
        "q_b82c713cb7b5": lambda: ("number", a.orders_with_revenue_at_least(m(10, 2025), t, 550_000)),
        "q_ba1f08439ec8": lambda: ("date", a.best_month(((2026, 1), (2026, 2), (2026, 3)), t)),
        "q_ba477e8e6161": lambda: ("percent", a.pct_change(rev(m(4, 2025)), rev(m(3, 2025)))),
        "q_bf178ff24ac3": lambda: ("list", [rev(m(10, 2025)), rev(m(11, 2025)), rev(m(12, 2025))]),
        "q_bfe72da5b2f7": lambda: ("number", a.average_order_value(m(8, 2025), t)),
        "q_c03e79a805ac": lambda: ("number", rev(m(9, 2025))),
        "q_c1976ad22afb": lambda: ("number", a.days_with_revenue_at_least(m(9, 2025), t, 43_000_000)),
        "q_c34ede239480": lambda: ("number", fmt.quantity(a.item_base_quantity(m(5, 2026), t, PVC_D90))),
        "q_c78fdf218577": lambda: ("number", a.delivery_rounds_in(m(7, 2025), t)),
        "q_c8fde55544b6": lambda: ("number", a.delivery_rounds_in(m(11, 2025), t)),
        "q_cdf9857d8c64": lambda: ("string", a.top_supplier_by_amount(m(1, 2026), t)),
        "q_ce3bd6c20b25": lambda: ("number", a.unsold_items(Period(start=date(2026, 2, 15), end=date(2026, 2, 21)), t)),
        "q_cf2c969d8471": lambda: ("number", fmt.quantity(a.delivered_quantity(m(5, 2025), t, VIGLACERA))),
        "q_d3390eedd851": lambda: ("number", int(a.shift_orders(m(5, 2025), t, "sáng")["doanh_thu"].sum())),
        "q_d62edb3b5bc6": lambda: ("date", a.best_month(((2025, 6), (2025, 7), (2025, 8)), t)),
        "q_d6ff23824813": lambda: ("string", a.top_customer_by_orders(m(8, 2025), t)),
        "q_d790faf2293a": lambda: ("number", rev(clock.year_to_date())),
        "q_d965d0bc2205": lambda: ("percent", a.pct_change(rev(m(3, 2025)), rev(m(2, 2025)))),
        "q_db10e5d30a18": lambda: ("number", a.average_order_value(clock.last_week(), t)),
        "q_dcb25c39e1cc": lambda: ("number", len(a.shift_orders(m(2, 2025), t, "chiều"))),
        "q_de45f4311dbe": lambda: ("number", a.orders_with_revenue_at_least(m(5, 2026), t, 3_700_000)),
        "q_e634d19ed4f2": lambda: ("percent", a.price_rise_effect(GAS_PETROLIMEX, date(2025, 10, 31), 30, t)),
        "q_e93bd9fb7c9a": lambda: ("number", a.days_with_revenue_at_least(m(8, 2025), t, 39_000_000)),
        "q_ec61b4f5b9ab": lambda: ("percent", a.pct_change(
            len(a.shift_orders(clock.last_week(), t, "chiều")), len(a.shift_orders(clock.last_week(), t, "sáng"))
        )),
        "q_edb6d4859798": lambda: ("string", a.top_customer_by_orders(m(10, 2025), t)),
        "q_f156d23d04fe": lambda: ("number", a.order_count(clock.this_week(), t)),
        "q_f274c9241995": lambda: ("percent", a.cancel_rate(m(5, 2025), t)),
        "q_f56deeb4120b": lambda: ("date", a.best_month(((2025, 12), (2026, 1), (2026, 2)), t)),
        "q_f75e58af3bcb": lambda: ("number", a.customers_with_at_least(m(10, 2025), t, 4)),
        "q_f82dc784b8c9": lambda: ("number", rev(m(4, 2026))),
        "q_f963e5fc774c": lambda: ("percent", a.price_rise_effect(CAT_XAY_TO, date(2025, 6, 22), 14, t)),
        "q_ffbacc923206": lambda: ("number", a.average_order_value(clock.last_week(), t)),
    }
    if qid not in specs:
        raise ValueError(f"no spec for question: {qid}")
    return specs[qid]()


PRICE_RISES = (
    (ION_LIFE, date(2025, 10, 18), 79_500),
    (GAS_PETROLIMEX, date(2025, 10, 31), 546_000),
    (CAT_XAY_TO, date(2025, 6, 22), 315_000),
)


def build_lines(ledger: Ledger) -> tuple[dict[str, Any], ...]:
    answerer = Answerer(ledger)
    for item, day, price in PRICE_RISES:
        answerer.check_price_rise(item, day, price)
    out: list[dict[str, Any]] = []
    for question in load_questions(QUESTIONS_PATH):
        qid = question["id"]
        if qid in UNANSWERABLE:
            out.append(fmt.answer_line(qid, "unanswerable", reason=UNANSWERABLE[qid]))
            continue
        if qid in ABSTAIN:
            out.append(fmt.answer_line(qid, "abstain"))
            continue
        kind, value = solve(answerer, qid, Clock(question["as_of_date"]))
        out.append(fmt.answer_line(qid, kind, value))
    return tuple(out)


def main() -> None:
    ledger = Ledger()
    lines = build_lines(ledger)
    written = write_answers(ANSWERS_PATH, lines)
    print(f"wrote {written} lines to {ANSWERS_PATH}")


if __name__ == "__main__":
    main()
