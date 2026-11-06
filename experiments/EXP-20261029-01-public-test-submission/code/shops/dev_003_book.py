from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

CODE_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = CODE_ROOT.parent
REPO_ROOT = EXPERIMENT_ROOT.parents[1]
SHOP = "dev_003"
DATA_DIR = REPO_ROOT / "public_test" / "data" / SHOP
QUESTIONS_PATH = DATA_DIR / "questions.jsonl"
ANSWERS_PATH = EXPERIMENT_ROOT / "out" / "answers" / f"{SHOP}.jsonl"
SALES_FILES = ("BanHang_TongHop_2025.xlsx", "BanHang_TongHop_2026.xlsx")
MASTER_FILE = "BanHang_TongHop_2025.xlsx"
RECEIPT_FILE = "BanHang_PhieuThu.xlsx"
SHIFT_FILE = "BaoCaoCa.xlsx"
EXPENSE_FILE = "SoTay_ChiPhi.xlsx"
PURCHASE_FILE = "SoTay_NhapHang.xlsx"
STOCK_FILE = "ton_kho.csv"
NOTEBOOK_HEADER_ROW = 2

sys.path.insert(0, str(CODE_ROOT))

from datamate import fold_key, parse_date, parse_datetime, parse_money, parse_number, read_table, squeeze  # noqa: E402

STATUS_DONE = "Xong"
STATUS_CANCELLED = "Đã hủy đơn"
STATUS_RETURNED = "Khách trả"
STATUS_SHIPPING = "Đang vận chuyển"
REVENUE_STATUSES = frozenset({STATUS_DONE, STATUS_SHIPPING})
ALL_STATUSES = frozenset({STATUS_DONE, STATUS_CANCELLED, STATUS_RETURNED, STATUS_SHIPPING})
WALK_IN_KEYS = frozenset({"khach le", "le", "kl"})
DATA_FIRST_DAY = date(2025, 3, 1)
DATA_LAST_DAY = date(2026, 8, 21)


def ident(value: Any) -> str:
    return fold_key(value)


def is_walk_in_name(value: Any) -> bool:
    return ident(value) in WALK_IN_KEYS


class SaleLine(BaseModel):
    """Một dòng hàng của sổ bán hàng, số lượng đã quy về đơn vị cơ bản."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    created_at: datetime
    day: date
    status: str
    payment_form: str
    source: str
    staff: str
    customer_code: str
    customer_name: str
    walk_in: bool
    item_code: str
    item_name: str
    group: str
    base_unit: str
    base_quantity: float
    amount: int
    unit_cost: int
    sold_quantity: float


class Order(BaseModel):
    """Một đơn hàng: trạng thái, tiền hàng (§1) và tổng khách phải trả (§4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    created_at: datetime
    day: date
    status: str
    payment_form: str
    source: str
    staff: str
    customer_code: str
    customer_name: str
    walk_in: bool
    goods_amount: int
    order_discount: int
    ship_fee: int
    payable: int


class Receipt(BaseModel):
    """Một lần khách trả tiền cho một đơn."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str
    paid_at: datetime
    day: date
    form: str
    amount: int


class Purchase(BaseModel):
    """Một dòng phiếu nhập hàng của sổ tay."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    slip: str
    day: date
    supplier: str
    item_name: str
    item_code: str
    unit: str
    quantity: float
    base_quantity: float
    amount: int


class Expense(BaseModel):
    """Một khoản chi vận hành trong sổ chi phí."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    day: date
    group: str
    amount: int


class PriceChange(BaseModel):
    """Một lần đổi giá bán của một mặt hàng, theo đơn vị cơ bản."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_code: str
    day: date
    old_price: int | None
    new_price: int


class ShopBook:
    """Toàn bộ dữ liệu dev_003 đã ingest, nối bằng mã và đã bỏ dòng trùng lặp xuất file."""

    def __init__(self, data_dir: Path | str = DATA_DIR) -> None:
        self.data_dir = Path(data_dir)
        self.catalog = self._read_catalog()
        self.conversion = self._read_conversion()
        self.customers = self._read_customers()
        self.lines, self.orders = self._read_sales()
        self.receipts = self._read_receipts()
        self.purchases = self._read_purchases()
        self.expenses = self._read_expenses()
        self.prices = self._read_prices()
        self.shifts = self._read_shifts()
        self.stock = self._read_stock()
        self._validate()

    def _validate(self) -> None:
        unknown = {o.status for o in self.orders.values()} - ALL_STATUSES
        if unknown:
            raise ValueError(f"order status outside rulebook four: {sorted(unknown)}")
        days = [o.day for o in self.orders.values()]
        if (min(days), max(days)) != (DATA_FIRST_DAY, DATA_LAST_DAY):
            raise ValueError(f"sales date range moved: {min(days)}..{max(days)}")
        for order in self.orders.values():
            if order.payable != order.goods_amount - order.order_discount + order.ship_fee:
                raise ValueError(f"order total does not reconcile: {order.order_id}")
        by_order: dict[str, int] = {}
        for line in self.lines:
            by_order[line.order_id] = by_order.get(line.order_id, 0) + line.amount
        for order_id, total in by_order.items():
            if total != self.orders[order_id].goods_amount:
                raise ValueError(f"line sum does not match order goods amount: {order_id}")

    def _read_catalog(self) -> dict[str, dict[str, Any]]:
        frame = read_table(self.data_dir / MASTER_FILE, sheet="BanHang_HangHoa", header_row=0)
        out: dict[str, dict[str, Any]] = {}
        for _, row in frame.iterrows():
            code = squeeze(row["Mã H.hóa"])
            if code == "":
                raise ValueError("catalog row without item code")
            out[code] = {
                "name": squeeze(row["Tên hàng hóa"]),
                "group": squeeze(row["Nhóm hàng"]),
                "unit": squeeze(row["DVT"]),
                "retail_price": parse_money(row["Giá lẻ"], default=0) or 0,
                "current_cost": parse_money(row["Giá vốn hiện tại"], default=0) or 0,
            }
        return out

    def _read_conversion(self) -> dict[tuple[str, str], float]:
        frame = read_table(self.data_dir / MASTER_FILE, sheet="BanHang_DonViQuyDoi", header_row=0)
        out: dict[tuple[str, str], float] = {}
        for _, row in frame.iterrows():
            code = squeeze(row["Mã vạch"])
            unit = ident(row["Quy cách"])
            factor = parse_number(row["Bằng"])
            if factor is None or factor <= 0:
                raise ValueError(f"bad conversion factor for {code}")
            out[(code, unit)] = float(factor)
        return out

    def _read_customers(self) -> dict[str, dict[str, str]]:
        frame = read_table(self.data_dir / MASTER_FILE, sheet="BanHang_KhachHang", header_row=0)
        out: dict[str, dict[str, str]] = {}
        for _, row in frame.iterrows():
            code = squeeze(row["Mã KH mua"])
            if code == "":
                raise ValueError("customer row without code")
            out[code] = {"name": squeeze(row["Khách hàng mua"]), "segment": squeeze(row["Kiểu khách"])}
        return out

    def factor(self, item_code: str, unit: str) -> float:
        return self.conversion.get((item_code, ident(unit)), 1.0)

    def _read_sales(self) -> tuple[tuple[SaleLine, ...], dict[str, Order]]:
        frames = [read_table(self.data_dir / name, sheet="BanHang", header_row=0) for name in SALES_FILES]
        if len({tuple(f.columns) for f in frames}) != 1:
            raise ValueError("sales sheets do not share one header")
        raw = pd.concat(frames, ignore_index=True)
        raw = raw.drop_duplicates().reset_index(drop=True)
        lines: list[SaleLine] = []
        orders: dict[str, Order] = {}
        for _, row in raw.iterrows():
            order_id = squeeze(row["Đơn số"])
            created_at = parse_datetime(row["Giờ tạo đơn"])
            if order_id == "" or created_at is None:
                raise ValueError(f"sales row without order id or timestamp: {order_id!r}")
            item_code = squeeze(row["Barcode"])
            info = self.catalog.get(item_code)
            if info is None:
                raise ValueError(f"unknown item code in sales: {item_code!r}")
            customer_code = squeeze(row["Mã khách"])
            customer_name = squeeze(row["Khách hàng (tên)"])
            walk_in = customer_code == ""
            if walk_in and not is_walk_in_name(customer_name):
                raise ValueError(f"order {order_id} has no customer code but a real name {customer_name!r}")
            unit = ident(row["ĐV"])
            sold = parse_number(row["S.L"])
            base = parse_number(row["SL (ĐV cơ bản)"])
            if sold is None or base is None:
                raise ValueError(f"sales row without quantity: {order_id}")
            lines.append(
                SaleLine(
                    order_id=order_id,
                    created_at=created_at,
                    day=created_at.date(),
                    status=squeeze(row["Trạng thái giao"]),
                    payment_form=squeeze(row["Hình thức thanh toán"]),
                    source=squeeze(row["Nguồn"]),
                    staff=squeeze(row["Mã NV bán"]),
                    customer_code=customer_code,
                    customer_name=customer_name,
                    walk_in=walk_in,
                    item_code=item_code,
                    item_name=info["name"],
                    group=info["group"],
                    base_unit=info["unit"],
                    base_quantity=float(base),
                    amount=parse_money(row["Thành tiền (đ)"], default=0) or 0,
                    unit_cost=parse_money(row["Giá vốn lúc bán"], default=0) or 0,
                    sold_quantity=float(sold),
                )
            )
            if order_id not in orders:
                orders[order_id] = Order(
                    order_id=order_id,
                    created_at=created_at,
                    day=created_at.date(),
                    status=squeeze(row["Trạng thái giao"]),
                    payment_form=squeeze(row["Hình thức thanh toán"]),
                    source=squeeze(row["Nguồn"]),
                    staff=squeeze(row["Mã NV bán"]),
                    customer_code=customer_code,
                    customer_name=customer_name,
                    walk_in=walk_in,
                    goods_amount=parse_money(row["Tiền hàng trước giảm"], default=0) or 0,
                    order_discount=parse_money(row["Tiền giảm"], default=0) or 0,
                    ship_fee=parse_money(row["Phí ship"], default=0) or 0,
                    payable=parse_money(row["Tổng thanh toán"], default=0) or 0,
                )
        return tuple(lines), orders

    def _read_receipts(self) -> tuple[Receipt, ...]:
        frame = read_table(self.data_dir / RECEIPT_FILE, header_row=0)
        out: list[Receipt] = []
        for _, row in frame.iterrows():
            order_id = squeeze(row["Ma don"])
            paid_at = parse_datetime(row["Ngày TT"])
            if order_id == "" or paid_at is None:
                raise ValueError("receipt row without order id or date")
            if order_id not in self.orders:
                raise ValueError(f"receipt for unknown order: {order_id!r}")
            out.append(
                Receipt(
                    order_id=order_id,
                    paid_at=paid_at,
                    day=paid_at.date(),
                    form=squeeze(row["PTTT"]),
                    amount=parse_money(row["Tiền thu"], default=0) or 0,
                )
            )
        return tuple(out)

    def _read_purchases(self) -> tuple[Purchase, ...]:
        frame = read_table(self.data_dir / PURCHASE_FILE, header_row=NOTEBOOK_HEADER_ROW)
        by_fold = {fold_key(info["name"]): code for code, info in self.catalog.items()}
        out: list[Purchase] = []
        for _, row in frame.iterrows():
            slip = squeeze(row["Số phiếu"])
            day = parse_date(row["Ngày nhập"])
            if slip == "" or day is None:
                raise ValueError("purchase row without slip or date")
            name = squeeze(row["Product"])
            code = by_fold.get(fold_key(name), "")
            if code == "":
                raise ValueError(f"purchase item not in catalog: {name!r}")
            unit = ident(row["ĐVT nhập"])
            quantity = parse_number(row["SL nhập"])
            if quantity is None:
                raise ValueError(f"purchase row without quantity: {slip}")
            out.append(
                Purchase(
                    slip=slip,
                    day=day,
                    supplier=squeeze(row["Nhà cung cấp"]),
                    item_name=self.catalog[code]["name"],
                    item_code=code,
                    unit=unit,
                    quantity=float(quantity),
                    base_quantity=float(quantity) * self.factor(code, unit),
                    amount=parse_money(row["Thành tiền"], default=0) or 0,
                )
            )
        return tuple(out)

    def _read_expenses(self) -> tuple[Expense, ...]:
        frame = read_table(self.data_dir / EXPENSE_FILE, header_row=NOTEBOOK_HEADER_ROW)
        out: list[Expense] = []
        for _, row in frame.iterrows():
            day = parse_date(row["Ngày mua"])
            amount = parse_money(row["Tiền chi"])
            if day is None or amount is None:
                raise ValueError("expense row without date or amount")
            out.append(Expense(day=day, group=squeeze(row["Nhóm"]), amount=amount))
        return tuple(out)

    def _read_prices(self) -> tuple[PriceChange, ...]:
        frame = read_table(self.data_dir / MASTER_FILE, sheet="BanHang_LichSuGia", header_row=0)
        out: list[PriceChange] = []
        for _, row in frame.iterrows():
            code = squeeze(row["Mã H.hóa"])
            day = parse_date(row["Ngày áp dụng"])
            new_price = parse_money(row["Giá mới"])
            if code == "" or day is None or new_price is None:
                raise ValueError("price row incomplete")
            out.append(PriceChange(item_code=code, day=day, old_price=parse_money(row["Giá cũ"]), new_price=new_price))
        return tuple(out)

    def _read_shifts(self) -> pd.DataFrame:
        frame = read_table(self.data_dir / SHIFT_FILE, header_row=0)
        frame = frame.assign(
            day=frame["Ngày"].map(parse_date),
            shift=frame["Ca"].map(squeeze),
            staff=frame["Mã NV"].map(squeeze),
            cash_in=frame["Tiền mặt thu"].map(lambda v: parse_money(v, default=0)),
            cash_out=frame["Tiền mặt hoàn khách"].map(lambda v: parse_money(v, default=0)),
            cash_net=frame["Tiền mặt ròng của ca"].map(lambda v: parse_money(v, default=0)),
        )
        if frame["day"].isna().any():
            raise ValueError("shift report row without date")
        return frame

    def _read_stock(self) -> dict[str, float]:
        frame = read_table(self.data_dir / STOCK_FILE)
        out: dict[str, float] = {}
        for _, row in frame.iterrows():
            code = squeeze(row["ma_sp"])
            quantity = parse_number(row["Ton kho"])
            if code == "" or quantity is None:
                raise ValueError("stock row incomplete")
            out[code] = float(quantity)
        return out

    def revenue_orders(self) -> tuple[Order, ...]:
        return tuple(o for o in self.orders.values() if o.status in REVENUE_STATUSES)

    def revenue_lines(self) -> tuple[SaleLine, ...]:
        return tuple(ln for ln in self.lines if ln.status in REVENUE_STATUSES)
