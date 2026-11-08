from __future__ import annotations

import re
import unicodedata
from typing import Any, Sequence

from datamate.norm import accent_count, fold_key, name_key

from .normalize_models import ColumnRole, OrderStatus, TableKind


def _description_key(text: str) -> str:
    return fold_key(re.split(r"[,;(:]", text.strip().rstrip("."))[0])


def _keys(table: dict[str, Sequence[str]]) -> dict[str, str]:
    return {_description_key(text): role for role, texts in table.items() for text in texts}


def _spelling(text: str) -> str:
    return " ".join("".join(sorted(unicodedata.normalize("NFD", word))) for word in name_key(text).split())


def _header_keys(table: dict[str, Sequence[str]]) -> dict[str, tuple[tuple[str, str], ...]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for role, texts in table.items():
        for text in texts:
            out.setdefault(fold_key(text), []).append((_spelling(text) if accent_count(text) else "", role))
    return {key: tuple(found) for key, found in out.items()}


DESCRIPTION_ROLES = _keys({
    "order_id": ("mã đơn", "số thứ tự đơn", "số hoá đơn"),
    "order_date": ("ngày bán",),
    "order_time": ("thời điểm đặt đơn", "giờ đặt đơn"),
    "status": ("trạng thái đơn", "trạng thái phiếu nhập"),
    "customer_name": ("tên khách", "tên khách thành viên"),
    "customer_code": ("mã khách",),
    "customer_phone": ("số điện thoại",),
    "customer_group": ("nhóm khách",),
    "staff": ("mã nhân viên bán", "thợ làm phiếu", "họ tên thợ"),
    "payment_method": ("hình thức thanh toán", "hình thức thanh toán của đơn"),
    "channel": ("kênh bán",),
    "order_discount": ("giảm giá của cả đơn", "tiền bớt cho cả đơn"),
    "shipping_fee": ("phí giao hàng", "phí giao hàng của cả đơn"),
    "order_total": ("tổng tiền đơn", "số khách phải trả cho cả đơn", "khách cần trả cho cả đơn"),
    "paid_amount": ("đã thanh toán", "khách đã trả cho cả đơn", "số tiền khách trả cho cả đơn"),
    "debt_amount": ("còn nợ", "số khách còn nợ của đơn", "khách còn nợ của cả đơn"),
    "note": ("ghi chú", "ghi chú của đơn"),
    "line_no": ("số thứ tự dòng trong đơn", "số thứ tự dòng trong phiếu nhập"),
    "item_code": ("mã hàng",),
    "item_name": ("tên hàng", "tên", "hàng bán"),
    "item_group": ("nhóm hàng",),
    "unit": ("đơn vị tính", "đơn vị nhập"),
    "base_unit": ("đơn vị cơ bản",),
    "big_unit": ("đơn vị lớn",),
    "unit_factor": ("hệ số",),
    "quantity": ("số lượng", "số lượng nhập"),
    "base_quantity": ("số lượng đã đổi ra đơn vị cơ bản",),
    "unit_price": ("đơn giá", "giá bán hiện tại", "đơn giá một máy / một cái"),
    "line_discount": ("giảm giá", "tiền giảm của cả dòng"),
    "line_amount": ("thành tiền sau giảm", "thành tiền của dòng", "tiền nhập của cả dòng", "tiền hàng của đơn"),
    "unit_cost": ("giá vốn", "giá nhập một đơn vị"),
    "document_id": ("mã phiếu nhập", "mã phiếu thu"),
    "record_date": ("ngày nhập", "thời điểm thu", "ngày sửa", "ngày vào làm"),
    "amount": ("số tiền", "tổng tiền phiếu nhập", "tổng tiền của cả phiếu", "tổng tiền cả phiếu"),
    "supplier": ("mã nhà cung cấp", "nhà cung cấp"),
    "stock": ("tồn kho",),
    "lot_id": ("số lô",),
    "expiry_date": ("hạn sử dụng",),
    "active_ingredient": ("hoạt chất",),
    "is_prescription": ("thuốc kê đơn",),
    "due_date": ("hạn thanh toán",),
})

HEADER_ROLES = _header_keys({
    "order_id": ("Đơn số", "Ma don", "MaHoaDon", "Mã hóa đơn", "Mã bill", "Mã giao dịch", "Order ID"),
    "order_date": ("Ngày HĐ", "NgayLap", "Ngày bán"),
    "order_time": ("Giờ tạo đơn", "ThoiGianLap"),
    "status": ("Trạng thái giao", "TinhTrang"),
    "customer_name": ("Khách hàng (tên)", "Khách hàng mua", "Khách", "Khách hàng", "Tên khách hàng", "Tên KH", "ten_kh"),
    "customer_code": ("Mã khách", "Mã KH mua", "MaKhachHang", "Mã KH", "Mã khách hàng", "Customer ID"),
    "customer_phone": ("SĐT", "SoDienThoai", "Điện thoại", "Số điện thoại"),
    "customer_group": ("Kiểu khách", "LoaiKhachHang", "Nhóm khách hàng", "Hạng"),
    "staff": ("Mã NV bán", "MaNhanVien", "Mã NV", "Người bán"),
    "payment_method": ("Hình thức thanh toán", "PTTT", "PhuongThucTT", "PhuongThuc", "Phương thức thanh toán", "Phương thức TT"),
    "channel": ("Nguồn", "KenhBanHang", "Kênh bán", "Nguồn đơn"),
    "order_discount": ("Bớt", "ChietKhau"),
    "shipping_fee": ("Phí ship", "PhiVanChuyen"),
    "order_total": ("Tổng thanh toán", "TongThanhToan", "Tổng sau giảm giá"),
    "paid_amount": ("Da tra", "KhachDaTra", "Khách trả", "Đã trả", "Khách đã trả", "Đã thu"),
    "debt_amount": ("Công nợ", "ConPhaiThu", "Nợ", "Còn nợ"),
    "note": ("Ghi chú", "Lưu ý", "DienGiai"),
    "line_no": ("Dòng", "SoThuTu", "TT dòng"),
    "item_code": ("Barcode", "Mã H.hóa", "Mã vạch", "ma_sp", "MaHangHoa", "Mã hàng", "Mã HH", "ID SP", "Mã món"),
    "item_name": ("Hàng hóa", "Tên hàng hóa", "ten_hang", "Product", "Item", "Hàng", "Tên hàng", "Máy", "Chi tiết hàng", "Món"),
    "item_group": ("Nhóm hàng", "Loại", "DanhMuc", "Nhóm hàng(3 Cấp)", "Phân loại"),
    "item_alias": ("Ghi tắt",),
    "unit": ("ĐV", "ĐVT nhập", "DonViTinh"),
    "base_unit": ("DonViCoSo",),
    "unit_factor": ("Bằng", "HeSoQuyDoi"),
    "quantity": ("S.L", "SL", "SL nhập", "Slg"),
    "base_quantity": ("SL (ĐV cơ bản)", "SLQuyDoi", "Số lượng quy đổi", "SL cơ bản"),
    "unit_price": ("Giá 1 đv", "Giá lẻ", "GiaDonVi", "GiaBanLe", "Giá", "Giá bán", "Giá niêm yết"),
    "line_discount": ("Giảm (đ)", "Khuyến mãi"),
    "line_amount": ("Thành tiền (đ)", "TriGia", "Thành tiền"),
    "unit_cost": ("Giá vốn lúc bán", "Giá vốn hiện tại", "GiaVonLucBan", "GiaVonHang", "Giá nhập", "DonGiaNhap", "Giá vốn"),
    "document_id": ("Mã thanh toán", "Số phiếu", "MaPhieuThu", "MaPhieuNhap", "Mã nhập hàng", "Mã phiếu nhập", "Mã phiếu", "Phiếu thu"),
    "record_date": ("Ngày TT", "Ngày nhập", "NgayGioThu", "NgayNhapKho", "Ngày nhận", "Thời gian thu", "Ngày chi"),
    "amount": ("Tiền thu", "SoTienThu", "Tiền chi", "TongGiaTriNhap", "Giá thu", "Cần trả NCC", "Giá trị", "Số tiền thu", "So tien"),
    "supplier": ("Nhà cung cấp", "MaNhaCungCap", "Mã NCC"),
    "stock": ("Ton kho", "TonCuoi", "Tồn cuối kỳ"),
    "lot_id": ("MaLo",),
    "expiry_date": ("HanSuDung",),
    "active_ingredient": ("ThanhPhanChinh", "Hoạt chất"),
    "is_prescription": ("BanTheoDon", "Kê đơn"),
})

STATUS_RULES: tuple[tuple[re.Pattern[str], OrderStatus], ...] = (
    (re.compile(r"\bhuy\b|cancel|khong giao duoc"), "huỷ"),
    (re.compile(r"hoan thanh|\bxong\b|^ok$|complete|da giao|da lay|thanh cong"), "hoàn thành"),
    (re.compile(r"\btra\b|\bhoan\b|return"), "trả hàng"),
    (re.compile(r"\bdang\b|cho giao|chua giao|xu ly|ship"), "đang giao"),
)
DATE_HEADERS = frozenset(fold_key(text) for text in ("Ngày", "Thời gian"))
UNIT_HEADERS = frozenset(fold_key(text) for text in ("ĐVT", "Đơn vị tính", "Đơn vị", "Đ.vị"))
LINE_ID_HEADER = fold_key("STT")
DISCOUNT_HEADERS = frozenset(fold_key(text) for text in ("Giảm giá", "CK"))
TOTAL_HEADER = fold_key("Tổng tiền")
PRICE_HEADER = fold_key("Đơn giá")
FACTOR_HEADER = fold_key("Quy đổi")
STATUS_HEADER = fold_key("Trạng thái")
CREATED_HEADER = fold_key("Thời gian tạo")
QUANTITY_HEADER = fold_key("Số lượng")
CONTEXT_FIRST = {LINE_ID_HEADER: 0, QUANTITY_HEADER: 1}
ITEM_ROLES = frozenset({"item_name", "item_code"})
NUMBER = re.compile(r"^\s*[\d.,]+\s*$")
NAME_HEADER = fold_key("TenGoi")
REPAIR_HEADERS = {fold_key("Xe"), fold_key("Làm gì")}
SECTION = re.compile(r"^## Cột trong (.+)$", re.M)
COLUMN_LINE = re.compile(r"^- \*\*(.+?)\*\*: (.+)$", re.M)


def readme_columns(readme: str) -> dict[str, dict[str, str]]:
    """Mô tả cột của từng file theo các mục `Cột trong` của README."""
    marks = list(SECTION.finditer(readme))
    out: dict[str, dict[str, str]] = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(readme)
        body = re.split(r"^## ", readme[mark.end() : end], flags=re.M)[0]
        out[fold_key(mark.group(1))] = {fold_key(column): _description_key(text) for column, text in COLUMN_LINE.findall(body)}
    return out


def table_kind(roles: set[str], *, name: str) -> TableKind:
    folded = fold_key(name)
    if "order_id" in roles and "document_id" not in roles and roles & {"order_date", "order_time", "line_amount", "quantity", "base_quantity", "item_code", "item_name", "order_total"}:
        return "sales"
    if not roles & {"order_id", "document_id", "supplier"} and "nhap" not in folded and {"order_date", "item_name"} <= roles and roles & {"line_amount", "quantity"}:
        return "sales"
    if "order_id" in roles and "document_id" in roles and "amount" in roles:
        return "receipts"
    if "document_id" in roles or "supplier" in roles or "nhap" in folded:
        return "purchases"
    if roles & {"unit_price", "item_group", "unit_factor", "base_unit"} and roles & {"item_name", "item_code"}:
        return "catalog"
    if "stock" in roles or "ton kho" in folded or "the kho" in folded or "lot_id" in roles:
        return "inventory"
    if roles & {"item_name", "item_code"}:
        return "catalog"
    if roles & {"customer_name", "customer_code"}:
        return "customers"
    if "staff" in roles:
        return "staff"
    return "other"


def header_role(column: str) -> str | None:
    """Vai trò theo tên cột: hai cách ghi có dấu phải khớp dấu, chỉ bỏ qua dấu khi một bên viết không dấu; `Hạng` không phải `Hàng`."""
    known = HEADER_ROLES.get(fold_key(column), ())
    written = _spelling(column) if accent_count(column) else ""
    exact = {role for spelling, role in known if written and spelling == written}
    found = exact or {role for spelling, role in known if not spelling or not written}
    return next(iter(found)) if len(found) == 1 else None


def context_role(key: str, given: set[str], *, purchase: bool, numbers: bool) -> str | None:
    """Vai trò của tên cột mơ hồ, đọc theo các vai trò khác trong cùng bảng."""
    order_table = "order_id" in given and not given & {"document_id", "supplier"}
    if key == LINE_ID_HEADER:
        return "line_no" if given & {"order_id", "document_id"} else "order_id"
    if key == STATUS_HEADER:
        return "status" if given & {"order_id", "document_id"} else None
    if key == CREATED_HEADER:
        return "order_time" if order_table else None
    if key == QUANTITY_HEADER:
        return None if "lot_id" in given else "quantity"
    if key in DATE_HEADERS:
        return None if given & {"order_date", "record_date"} else "order_date" if order_table else "record_date"
    if key in UNIT_HEADERS:
        return "unit" if given & {"quantity", "unit_factor"} else "base_unit"
    if key in DISCOUNT_HEADERS:
        return "line_discount" if given & ITEM_ROLES else "order_discount"
    if key == TOTAL_HEADER:
        return "line_amount" if given & ITEM_ROLES else "order_total" if order_table else "amount"
    if key == PRICE_HEADER:
        return "unit_cost" if purchase else "unit_price"
    if key == FACTOR_HEADER:
        return "unit_factor" if numbers else None
    return None


class ReadmeMapper:
    """Map cột bằng tra cứu deterministic: mô tả ở README trước, tên cột sau, rồi tên cột mơ hồ theo ngữ cảnh bảng; cùng giao diện với ColumnMapper."""

    def __init__(self, readme: str) -> None:
        self._sections = readme_columns(readme)

    def propose(self, group: Any, *, feedback: str | None = None) -> Any:
        from .normalize import MappingProposal

        source = group.sources[0]
        folded = {fold_key(column) for column in group.columns}
        section = max(self._sections.values(), key=lambda known: len(folded & set(known)), default={})
        where = fold_key(f"{source.file} {source.sheet}")
        customers = "khach" in where
        roles: list[ColumnRole] = []
        for column in group.columns:
            key = fold_key(column)
            role = DESCRIPTION_ROLES.get(section.get(key, "")) or header_role(column)
            if role == "item_name" and customers:
                role = "customer_name"
            if key == NAME_HEADER:
                role = "customer_name" if customers else "item_name" if "san_pham" in where or "san pham" in where else None
            if role is not None:
                roles.append(ColumnRole(column=column, role=role))
        given = {item.role for item in roles}
        mapped = {item.column for item in roles}
        purchase = "nhap" in where or bool(given & {"document_id", "supplier"})
        for index, column in sorted(enumerate(group.columns), key=lambda pair: CONTEXT_FIRST.get(fold_key(pair[1]), len(CONTEXT_FIRST))):
            if column in mapped:
                continue
            cells = [row[index] for row in group.sample if index < len(row) and row[index].strip()]
            role = context_role(fold_key(column), given, purchase=purchase, numbers=bool(cells) and all(NUMBER.match(cell) for cell in cells))
            if role is not None and role not in given:
                roles.append(ColumnRole(column=column, role=role))
                given.add(role)
        kind = "repairs" if REPAIR_HEADERS <= folded else table_kind(given, name=f"{source.file} {source.sheet}")
        return MappingProposal(kind=kind, columns=tuple(roles))

    def statuses(self, values: Sequence[tuple[str, int]]) -> dict[str, OrderStatus | None]:
        out: dict[str, OrderStatus | None] = {}
        for value, _ in values:
            key = fold_key(value)
            out[value] = next((status for pattern, status in STATUS_RULES if pattern.search(key)), None)
        return out
