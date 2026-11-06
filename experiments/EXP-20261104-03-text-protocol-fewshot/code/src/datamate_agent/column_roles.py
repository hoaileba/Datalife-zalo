from __future__ import annotations

import re
from typing import Any, Sequence

from datamate.norm import fold_key

from .normalize_models import ColumnRole, OrderStatus, TableKind


def _description_key(text: str) -> str:
    return fold_key(re.split(r"[,;(:]", text.strip().rstrip("."))[0])


def _keys(table: dict[str, Sequence[str]]) -> dict[str, str]:
    return {_description_key(text): role for role, texts in table.items() for text in texts}


def _header_keys(table: dict[str, Sequence[str]]) -> dict[str, str]:
    return {fold_key(text): role for role, texts in table.items() for text in texts}


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
    "order_id": ("Đơn số", "Ma don", "MaHoaDon", "STT"),
    "order_date": ("Ngày HĐ", "NgayLap"),
    "order_time": ("Giờ tạo đơn", "ThoiGianLap"),
    "status": ("Trạng thái giao", "TinhTrang"),
    "customer_name": ("Khách hàng (tên)", "Khách hàng mua", "Khách"),
    "customer_code": ("Mã khách", "Mã KH mua", "MaKhachHang"),
    "customer_phone": ("SĐT", "SoDienThoai"),
    "customer_group": ("Đối tượng KH", "LoaiKhachHang"),
    "staff": ("Mã NV bán", "MaNhanVien", "Mã NV"),
    "payment_method": ("Hình thức thanh toán", "PTTT", "PhuongThucTT", "PhuongThuc"),
    "channel": ("Nguồn", "KenhBanHang"),
    "order_discount": ("Bớt", "ChietKhau"),
    "shipping_fee": ("Phí ship", "PhiVanChuyen"),
    "order_total": ("Tổng thanh toán", "TongThanhToan"),
    "paid_amount": ("Da tra", "KhachDaTra", "Khách trả", "Đã trả"),
    "debt_amount": ("Công nợ", "ConPhaiThu", "Nợ"),
    "note": ("Ghi chú", "Lưu ý", "DienGiai"),
    "line_no": ("Dòng", "SoThuTu"),
    "item_code": ("Barcode", "Mã H.hóa", "Mã vạch", "ma_sp", "MaHangHoa"),
    "item_name": ("Hàng hóa", "Tên hàng hóa", "ten_hang", "Product", "Item", "Hàng", "Tên hàng", "Máy"),
    "item_group": ("Nhóm hàng", "Loại", "DanhMuc"),
    "item_alias": ("Ghi tắt",),
    "unit": ("ĐV", "ĐVT nhập", "DonViTinh"),
    "base_unit": ("DVT", "ĐVT", "DonViCoSo"),
    "unit_factor": ("Bằng", "HeSoQuyDoi"),
    "quantity": ("S.L", "SL", "SL nhập"),
    "base_quantity": ("SL (ĐV cơ bản)", "SLQuyDoi"),
    "unit_price": ("Giá 1 đv", "Giá lẻ", "GiaDonVi", "GiaBanLe", "Giá"),
    "line_discount": ("Giảm (đ)",),
    "line_amount": ("Thành tiền (đ)", "TriGia", "Thành tiền"),
    "unit_cost": ("Giá vốn lúc bán", "Giá vốn hiện tại", "GiaVonLucBan", "GiaVonHang", "Giá nhập", "DonGiaNhap"),
    "document_id": ("Mã thanh toán", "Số phiếu", "MaPhieuThu", "MaPhieuNhap"),
    "record_date": ("Ngày TT", "Ngày nhập", "NgayGioThu", "NgayNhapKho", "Ngày nhận"),
    "amount": ("Tiền thu", "SoTienThu", "Tiền chi", "TongGiaTriNhap", "Giá thu"),
    "supplier": ("Nhà cung cấp", "MaNhaCungCap"),
    "stock": ("Ton kho", "TonCuoi"),
    "lot_id": ("MaLo",),
    "expiry_date": ("HanSuDung",),
    "active_ingredient": ("ThanhPhanChinh",),
    "is_prescription": ("BanTheoDon",),
})

STATUS_RULES: tuple[tuple[re.Pattern[str], OrderStatus], ...] = (
    (re.compile(r"\bhuy\b|cancel|khong giao duoc"), "huỷ"),
    (re.compile(r"hoan thanh|\bxong\b|^ok$|complete|da giao|da lay|thanh cong"), "hoàn thành"),
    (re.compile(r"\btra\b|\bhoan\b|return"), "trả hàng"),
    (re.compile(r"\bdang\b|cho giao|chua giao|xu ly|ship"), "đang giao"),
)
DATE_HEADER = fold_key("Ngày")
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


class ReadmeMapper:
    """Map cột bằng tra cứu tất định: mô tả ở README trước, tên cột sau; cùng giao diện với ColumnMapper."""

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
            role = DESCRIPTION_ROLES.get(section.get(key, "")) or HEADER_ROLES.get(key)
            if role == "item_name" and customers:
                role = "customer_name"
            if key == NAME_HEADER:
                role = "customer_name" if customers else "item_name" if "san_pham" in where or "san pham" in where else None
            if role is not None:
                roles.append(ColumnRole(column=column, role=role))
        given = {item.role for item in roles}
        if DATE_HEADER in folded and not given & {"order_date", "record_date"}:
            date_role = "order_date" if "order_id" in given else "record_date"
            roles.append(ColumnRole(column=next(column for column in group.columns if fold_key(column) == DATE_HEADER), role=date_role))
            given.add(date_role)
        kind = "repairs" if REPAIR_HEADERS <= folded else table_kind(given, name=f"{source.file} {source.sheet}")
        return MappingProposal(kind=kind, columns=tuple(roles))

    def statuses(self, values: Sequence[tuple[str, int]]) -> dict[str, OrderStatus | None]:
        out: dict[str, OrderStatus | None] = {}
        for value, _ in values:
            key = fold_key(value)
            out[value] = next((status for pattern, status in STATUS_RULES if pattern.search(key)), None)
        return out
