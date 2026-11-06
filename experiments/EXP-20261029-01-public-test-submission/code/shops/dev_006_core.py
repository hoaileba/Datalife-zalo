from __future__ import annotations

import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

CODE_ROOT = Path(__file__).resolve().parents[1]
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from datamate import Clock, Period, fmt, fold_key, parse_money, squeeze
from datamate.norm import round2, round_money

REPO_ROOT = Path("/Users/lebahoai/Workspace/zalo/2026")
SHOP = "dev_006"
DB_PATH = REPO_ROOT / "public_test" / "data" / SHOP / "pos.sqlite"
QUESTIONS_PATH = REPO_ROOT / "public_test" / "data" / SHOP / "questions.jsonl"
ANSWERS_PATH = CODE_ROOT.parent / "out" / "answers" / f"{SHOP}.jsonl"
NOTES_PATH = CODE_ROOT.parent / "logs" / f"{SHOP}-notes.md"

REVENUE_STATUSES = frozenset({"completed", "shipping"})
LINE_COLUMNS = (
    "IDCuaHang",
    "MaHoaDon",
    "SoThuTu",
    "MaHangHoa",
    "DonViTinh",
    "SL",
    "SLQuyDoi",
    "GiaDonVi",
    "ChietKhau",
    "TriGia",
    "GiaVonLucBan",
)


class Order:
    """Một đơn bán của dev_006, đã gắn sẵn doanh thu dòng hàng và ngày đặt."""

    __slots__ = (
        "code",
        "moment",
        "day",
        "status",
        "customer",
        "employee",
        "channel",
        "payment",
        "goods",
        "order_discount",
        "shipping_fee",
        "total_due",
        "paid",
    )

    def __init__(self, row: Sequence[Any]) -> None:
        self.code: str = row[0]
        self.moment: datetime = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
        self.day: date = self.moment.date()
        self.status: str = row[2]
        self.customer: str = squeeze(row[3])
        self.employee: str = squeeze(row[4])
        self.channel: str = squeeze(row[5])
        self.payment: str = squeeze(row[6])
        self.goods: int = int(row[7])
        self.order_discount: int = int(row[8])
        self.shipping_fee: int = int(row[9])
        self.total_due: int = int(row[10])
        self.paid: int = int(row[11])

    @property
    def counts_as_revenue(self) -> bool:
        return self.status in REVENUE_STATUSES


class Line:
    """Một dòng hàng của đơn, sau khi đã bỏ dòng trùng khít của cùng đơn."""

    __slots__ = ("order", "seq", "product", "unit", "qty", "base_qty", "unit_price", "discount", "amount", "unit_cost")

    def __init__(self, row: Sequence[Any]) -> None:
        self.order: str = row[1]
        self.seq: int = int(row[2])
        self.product: str = row[3]
        self.unit: str = squeeze(row[4])
        self.qty: int = int(row[5])
        self.base_qty: int = int(row[6])
        self.unit_price: int = int(row[7])
        self.discount: int = int(row[8])
        self.amount: int = int(row[9])
        self.unit_cost: int = int(row[10])

    @property
    def cost(self) -> int:
        return self.qty * self.unit_cost

    @property
    def gross_profit(self) -> int:
        return self.amount - self.cost


class Payment:
    """Một lần khách trả tiền cho một đơn."""

    __slots__ = ("code", "order", "moment", "day", "amount", "method")

    def __init__(self, row: Sequence[Any]) -> None:
        self.code: str = row[0]
        self.order: str = row[1]
        self.moment: datetime = datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
        self.day: date = self.moment.date()
        amount = parse_money(row[3])
        if amount is None:
            raise ValueError(f"unreadable payment amount: {row[3]!r}")
        self.amount: int = amount
        self.method: str = squeeze(row[4])


class Product:
    """Một mặt hàng trong danh mục, kèm đơn vị cơ bản, giá vốn và thông tin thuốc."""

    __slots__ = ("code", "name", "category", "base_unit", "retail_price", "base_cost", "ingredient", "prescription", "factors")

    def __init__(self, row: Sequence[Any]) -> None:
        self.code: str = row[0]
        self.name: str = squeeze(row[1])
        self.category: str = squeeze(row[2])
        self.base_unit: str = squeeze(row[3])
        self.retail_price: int = int(row[4])
        self.base_cost: int = int(row[5])
        self.ingredient: str = squeeze(row[6])
        self.prescription: bool = bool(row[7])
        self.factors: dict[str, int] = {}


class Lot:
    """Một lô nhập của một mặt hàng, kèm hạn dùng và giá nhập một đơn vị cơ bản."""

    __slots__ = ("code", "product", "receipt", "expiry", "qty_in", "base_cost")

    def __init__(self, row: Sequence[Any]) -> None:
        self.code: str = row[0]
        self.product: str = row[1]
        self.receipt: str = row[2]
        self.expiry: date = date.fromisoformat(row[3])
        self.qty_in: int = int(row[4])
        self.base_cost: int = int(row[5])


class Movement:
    """Một dòng thẻ kho: phát sinh theo đơn vị cơ bản và tồn sau phát sinh."""

    __slots__ = ("code", "product", "moment", "day", "kind", "qty", "doc_kind", "doc", "balance")

    def __init__(self, row: Sequence[Any]) -> None:
        self.code: str = row[0]
        self.product: str = row[1]
        self.moment: datetime = datetime.strptime(row[2], "%Y-%m-%d %H:%M:%S")
        self.day: date = self.moment.date()
        self.kind: str = row[3]
        self.qty: int = int(row[4])
        self.doc_kind: str = row[5]
        self.doc: str = row[6]
        self.balance: int = int(row[7])


class Receipt:
    """Một phiếu nhập hàng."""

    __slots__ = ("code", "supplier", "day", "status", "total")

    def __init__(self, row: Sequence[Any]) -> None:
        self.code: str = row[0]
        self.supplier: str = row[1]
        self.day: date = date.fromisoformat(row[2])
        self.status: str = row[3]
        self.total: int = int(row[4])


class PriceChange:
    """Một lần đổi giá bán lẻ theo đơn vị cơ bản."""

    __slots__ = ("product", "day", "price")

    def __init__(self, row: Sequence[Any]) -> None:
        self.product: str = row[0]
        self.day: date = date.fromisoformat(row[1])
        self.price: int = int(row[2])


class Shop:
    """Toàn bộ dữ liệu dev_006 đã ingest, dedupe và index theo đơn, mặt hàng, lô."""

    def __init__(self, db_path: Path | str = DB_PATH) -> None:
        connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            self._load(connection)
        finally:
            connection.close()
        self.data_start = min(order.day for order in self.orders)
        self.data_end = max(order.day for order in self.orders)

    def _load(self, connection: sqlite3.Connection) -> None:
        query = connection.execute
        self.orders: tuple[Order, ...] = tuple(
            Order(row)
            for row in query(
                "select MaHoaDon, ThoiGianLap, TinhTrang, MaKhachHang, MaNhanVien, KenhBanHang,"
                " PhuongThucTT, TongTienHang, ChietKhau, PhiVanChuyen, TongThanhToan, KhachDaTra"
                " from don_hang order by MaHoaDon"
            )
        )
        self.order_by_code: dict[str, Order] = {order.code: order for order in self.orders}
        if len(self.order_by_code) != len(self.orders):
            raise ValueError("duplicate order code in don_hang")

        columns = ", ".join(LINE_COLUMNS)
        self.lines: tuple[Line, ...] = tuple(
            Line(row) for row in query(f"select distinct {columns} from chi_tiet_don order by MaHoaDon, SoThuTu")
        )
        self.lines_by_order: dict[str, list[Line]] = {}
        for line in self.lines:
            self.lines_by_order.setdefault(line.order, []).append(line)

        self.payments: tuple[Payment, ...] = tuple(
            Payment(row)
            for row in query("select MaPhieuThu, MaHoaDon, NgayGioThu, SoTienThu, PhuongThuc from thanh_toan order by MaPhieuThu")
        )
        self.payments_by_order: dict[str, list[Payment]] = {}
        for payment in self.payments:
            self.payments_by_order.setdefault(payment.order, []).append(payment)

        self.products: dict[str, Product] = {}
        for row in query(
            "select sp.MaHangHoa, sp.TenGoi, sp.DanhMuc, sp.DonViCoSo, sp.GiaBanLe, sp.GiaVonHang,"
            " coalesce(tt.ThanhPhanChinh, ''), coalesce(tt.BanTheoDon, 0)"
            " from san_pham sp left join thong_tin_thuoc tt on tt.MaHangHoa = sp.MaHangHoa"
            " order by sp.MaHangHoa"
        ):
            product = Product(row)
            self.products[product.code] = product
        for code, unit, factor in query("select MaHangHoa, DonViTinh, HeSoQuyDoi from don_vi_sp"):
            self.products[code].factors[squeeze(unit)] = int(factor)

        self.customers: dict[str, tuple[str, str]] = {
            row[0]: (squeeze(row[1]), squeeze(row[2]))
            for row in query("select MaKhachHang, TenGoi, LoaiKhachHang from khach_hang")
        }
        self.employees: dict[str, str] = {row[0]: squeeze(row[1]) for row in query("select MaNhanVien, TenGoi from nhan_vien")}
        self.suppliers: dict[str, str] = {row[0]: squeeze(row[1]) for row in query("select MaNhaCungCap, TenGoi from nha_cung_cap")}

        self.receipts: tuple[Receipt, ...] = tuple(
            Receipt(row)
            for row in query("select MaPhieuNhap, MaNhaCungCap, NgayNhapKho, TinhTrang, TongGiaTriNhap from phieu_nhap order by MaPhieuNhap")
        )
        self.receipt_lines: tuple[tuple[str, str, str, int, int], ...] = tuple(
            (row[0], row[1], squeeze(row[2]), int(row[3]), int(row[4]))
            for row in query("select MaPhieuNhap, MaHangHoa, DonViTinh, SL, DonGiaNhap from chi_tiet_nhap")
        )

        self.lots: dict[str, Lot] = {}
        for row in query("select MaLo, MaHangHoa, MaPhieuNhap, HanSuDung, SLNhapQuyDoi, DonGiaNhap from lo_hang order by MaLo"):
            lot = Lot(row)
            self.lots[lot.code] = lot
        self.lot_consumption: tuple[tuple[str, str, int, int, int], ...] = tuple(
            (row[0], row[1], int(row[2]), int(row[3]), int(row[4]))
            for row in query("select MaHoaDon, MaLo, SoThuTu, SLQuyDoi, SLTraQuyDoi from chi_tiet_don_lo")
        )

        self.movements: tuple[Movement, ...] = tuple(
            Movement(row)
            for row in query(
                "select MaGiaoDichKho, MaHangHoa, NgayGioPhatSinh, LoaiGiaoDich, SLQuyDoi, KieuChungTu, MaChungTu, TonCuoi"
                " from the_kho order by MaHangHoa, NgayGioPhatSinh, MaGiaoDichKho"
            )
        )
        self.price_changes: tuple[PriceChange, ...] = tuple(
            PriceChange(row) for row in query("select MaHangHoa, NgayApDung, GiaBanLe from lich_su_gia order by MaHangHoa, NgayApDung")
        )
        self.returns: tuple[tuple[str, datetime, int], ...] = tuple(
            (row[0], datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S"), int(row[2]))
            for row in query("select MaHoaDon, NgayGioTra, TienHoanTra from tra_hang")
        )

    def product_by_name(self, text: str) -> Product:
        wanted = fold_key(text)
        hits = [product for product in self.products.values() if fold_key(product.name) == wanted]
        if len(hits) != 1:
            raise ValueError(f"product name not unique: {text!r} -> {len(hits)} hits")
        return hits[0]

    def customer_by_name(self, text: str) -> str:
        wanted = fold_key(text)
        hits = [code for code, (name, _) in self.customers.items() if fold_key(name) == wanted]
        if len(hits) != 1:
            raise ValueError(f"customer name not unique: {text!r} -> {len(hits)} hits")
        return hits[0]

    def employee_by_name(self, text: str) -> str:
        wanted = fold_key(text)
        hits = [code for code, name in self.employees.items() if fold_key(name) == wanted]
        if len(hits) != 1:
            raise ValueError(f"employee name not unique: {text!r} -> {len(hits)} hits")
        return hits[0]

    def orders_in(self, period: Period, clock: Clock, *, revenue_only: bool = True) -> tuple[Order, ...]:
        return tuple(
            order
            for order in self.orders
            if period.contains(order.day) and clock.visible(order.day) and (order.counts_as_revenue or not revenue_only)
        )

    def revenue(self, period: Period, clock: Clock, *, keep=None) -> int:
        total = 0
        for order in self.orders_in(period, clock):
            if keep is not None and not keep(order):
                continue
            total += order.goods
        return total

    def revenue_lines(self, period: Period, clock: Clock) -> tuple[tuple[Order, Line], ...]:
        out: list[tuple[Order, Line]] = []
        for order in self.orders_in(period, clock):
            for line in self.lines_by_order.get(order.code, ()):
                out.append((order, line))
        return tuple(out)

    def stock_at(self, moment: date) -> dict[str, int]:
        balance: dict[str, int] = {code: 0 for code in self.products}
        for movement in self.movements:
            if movement.day <= moment:
                balance[movement.product] += movement.qty
        return balance

    def lot_balances(self) -> dict[str, int]:
        balance = {code: lot.qty_in for code, lot in self.lots.items()}
        for _order, lot_code, _seq, sold, returned in self.lot_consumption:
            balance[lot_code] += returned - sold
        return balance

    def outstanding_at(self, moment: date) -> dict[str, int]:
        out: dict[str, int] = {}
        for order in self.orders:
            if order.payment != "debt" or order.status == "cancelled":
                continue
            if order.day > moment:
                continue
            paid = sum(p.amount for p in self.payments_by_order.get(order.code, ()) if p.day <= moment)
            rest = order.total_due - paid
            if rest > 0:
                out[order.code] = rest
        return out

    def new_debt_in(self, period: Period, clock: Clock) -> dict[str, int]:
        out: dict[str, int] = {}
        for order in self.orders:
            if order.payment != "debt" or order.status == "cancelled":
                continue
            if not period.contains(order.day) or not clock.visible(order.day):
                continue
            same_day = sum(p.amount for p in self.payments_by_order.get(order.code, ()) if p.day == order.day)
            rest = order.total_due - same_day
            if rest != 0:
                out[order.code] = rest
        return out

    def debt_collected_in(self, period: Period, clock: Clock) -> tuple[tuple[Order, Payment], ...]:
        out: list[tuple[Order, Payment]] = []
        for order in self.orders:
            if order.payment != "debt" or order.status == "cancelled":
                continue
            for payment in self.payments_by_order.get(order.code, ()):
                if payment.day <= order.day:
                    continue
                if period.contains(payment.day) and clock.visible(payment.day):
                    out.append((order, payment))
        return tuple(out)


def percent_change(current: float, baseline: float) -> float:
    if baseline == 0:
        raise ValueError("baseline is zero")
    return round2((current - baseline) / baseline * 100.0)


def share(part: float, whole: float) -> float:
    if whole == 0:
        raise ValueError("whole is zero")
    return round2(part / whole * 100.0)


def pick_top(scores: dict[str, float], *, limit: int = 1) -> tuple[tuple[str, float], ...]:
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return tuple(ordered[:limit])
