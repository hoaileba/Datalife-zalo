"""Reskin train shops (S2, no model calls): same rows and numbers, other names. Each copy renames files, sheets,
SQLite tables, column headers (synonyms of the same meaning, in the style of the original header) and status/payment
labels (synonyms of the same category, consistent across every table), shuffles column order, and rewrites README.md
with the new names at a chosen detail level. Gold answers stay valid (a label answer is mapped; an answer that is a
renamed name drops the question).

    python -m gen.reskin --out data_gen --copies 2 [--seed 0] [--shops biz_101,...] [--workers 4]
    -> data_gen/reskin_<k>/  data/<business_id>/ (same ids as train), questions.jsonl, answers.jsonl (mapped),
       meta.jsonl (orig_id, intent, variant=reskin_<k>), rulebook.md, calendar.csv, reskin.json (per shop: every
       rename, README level, checks), val_questions.jsonl + val_ids.txt (held-out shops: memorization check)

Every copy is checked: datamate.data.load_business reads it with no unreadable file, and every table equals the
original table once names and labels are mapped (same rows, same values, same dtypes); a column or file whose rename
or shuffle changes what the reader sees is put back and the shop written again.
Teacher samples on the copies (no model calls): python -m gen.reskin_replay.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]

import pandas as pd  # noqa: E402

from datamate.data import SOURCE_COL, load_business  # noqa: E402
from datamate.grids import _clean, find_header  # noqa: E402
from datamate.helpers import norm  # noqa: E402
from datamate.layout import sub_header  # noqa: E402
from datamate.values import nfc  # noqa: E402
from gen.pools import DOC, DOC_MASTER, FILLER_DOC  # noqa: E402
from gen.remap import NameMap  # noqa: E402
from gen.shopio import ShopFile, read_shop, write_shop  # noqa: E402

TRAIN = ROOT / 'data' / 'train'
VAL_SHOPS = ('biz_108', 'biz_110', 'biz_130')          # gen.package.DEFAULT_VAL_SHOPS
LEVELS = (('full', .5), ('partial', .3), ('brief', .2))

# ---------------------------------------------------------------- column headers
# Synonym sets of train headers: every member means the same thing in every table where a train shop uses it (a
# header used for two meanings, such as "Trạng thái" of orders and of customers, sits in a generic set). '~' marks a
# header recognised but never chosen as a new name (industry words such as "Món").
HEADERS = [
    ['Mã hóa đơn', 'Mã đơn hàng', 'Mã đơn', 'Số hóa đơn', 'Mã HĐ', 'Số HĐ', 'Mã bill', 'Order ID', 'So hoa don', 'Ma don', 'Mã đơn bán'],
    ['Mã phiếu', 'Số phiếu', 'Mã chứng từ', 'Số CT', 'Số chứng từ', 'Mã GD', 'Mã giao dịch'],
    ['Ngày bán', 'Ngày đặt hàng', 'Ngày đặt', 'Ngày mua', 'Ngày lập', 'Ngày giao dịch', 'Ngày chứng từ', 'NgayBan', 'Ngày hóa đơn', 'ngay_ban'],
    ['Ngày', 'Ngày tháng', 'Ngày ghi sổ'],
    ['Thời gian tạo', 'Thời điểm đặt', 'Thời gian lập', 'ThoiGianLap', 'Ngày giờ tạo', 'Giờ tạo đơn'],
    ['Thời gian', 'Ngày giờ', 'Thời điểm'],
    ['Giờ', 'Giờ bán', 'Giờ tạo'],
    ['Trạng thái', 'Tình trạng', 'Status', 'TinhTrang', 'trang_thai'],
    ['Trạng thái đơn', 'Tình trạng đơn', 'Trạng thái đơn hàng', 'Trạng thái xử lý', 'Xử lý', 'Kết quả', 'Ghi chú TT', 'Tình trạng đơn hàng'],
    ['Khách hàng', 'Tên khách hàng', 'Tên khách', 'Khách', 'Tên KH', 'TenKH', 'Người mua', 'Bên mua', 'Đối tác', 'Khách hàng (tên)', 'ten_kh'],
    ['Mã KH', 'Mã khách hàng', 'Mã khách', 'Số KH', 'Customer ID', 'Mã KH mua', 'Mã khách mua', 'ma_kh', 'MaKhachHang'],
    ['Tên hàng', 'Tên hàng hóa', 'Tên sản phẩm', 'Sản phẩm', 'Mặt hàng', 'Hàng hóa', 'Tên SP', 'Hàng', 'Tên mặt hàng', 'Product',
     'Chi tiết hàng', 'Hàng bán', 'Ten hang', 'ten_hang', 'TenHang', '~Món', '~Tên món'],
    ['Mã hàng', 'Mã hàng hóa', 'Mã sản phẩm', 'Mã SP', 'Mã SKU', 'SKU', 'ID SP', 'Mã HH', 'Mã mặt hàng', 'Ma hang', 'ma_sp',
     'MaHangHoa', 'Mã hàng bán', '~Mã món', '~Mã sản phẩm bán'],
    ['Đơn vị tính', 'ĐVT', 'Đơn vị', 'Đ.vị', 'DVT', 'dvt', 'DonVi', 'Unit', 'ĐV tính', 'Đơn vị (tính)', 'DonViTinh'],
    ['Đơn vị cơ bản', 'ĐV cơ bản', 'Đơn vị gốc', 'ĐV gốc', 'ĐV nhỏ', 'Đơn vị lẻ', 'DonViCoSo'],
    ['Đơn vị quy đổi', 'ĐV lớn', 'Đơn vị lớn'],
    ['Số lượng', 'SL', 'So luong', 'so_luong', 'SoLuong', 'S.L', 'Sluong', 'Slg', 'Số lượng hàng'],
    ['SL bán', 'Số lượng bán', 'Số lượng sản phẩm', 'SL hàng bán'],
    ['Số lượng quy đổi', 'SL quy đổi', 'Quy ra ĐV lẻ', 'Số lượng lẻ', 'SL lẻ', 'SL cơ bản', 'SL quy ra lẻ', 'SLQuyDoi',
     'Số lượng (ĐVT cơ bản)', 'SL (ĐVT cơ bản)'],
    ['Số lượng trả (ĐVT cơ bản)', 'SL trả (ĐVT cơ bản)', 'SL trả quy đổi', 'SLTraQuyDoi'],
    ['Đơn giá', 'Giá đơn vị', 'Giá', 'Đơn giá (đ)', 'Giá 1 đv', 'don_gia', 'GiaDonVi'],
    ['Giá bán', 'Giá bán lẻ', 'Giá lẻ', 'Đơn giá bán', 'Price', 'Giá sản phẩm', 'GiaBanLe'],
    ['Giá niêm yết', 'Giá bán niêm yết', '~Giá hiện tại'],
    ['Thành tiền', 'Thanh tien', 'T.Tiền', 'Trị giá', 'Thành tiền (đ)', 'thanh_tien', 'Amount', 'TriGia', '~Tiền bán'],
    ['Tiền', 'Số tiền', 'Giá trị'],
    ['Giảm giá', 'Chiết khấu', 'CK', 'Khuyến mãi', 'ChietKhau'],
    ['Tổng tiền hàng', 'Tien hang', 'Tiền hàng trước giảm', 'TongTienHang', 'Tiền hàng'],
    ['Tổng sau giảm giá', 'Khách cần trả', 'Tổng thanh toán', 'Phải thu', 'Tổng bill', 'Tổng đơn', 'TongThanhToan', 'Khách phải trả'],
    ['Tổng tiền', 'Tong tien', 'TongTien', 'Tổng', 'Tổng cộng'],
    ['Khách đã trả', 'Khách trả', 'Đã thu', 'Đã thanh toán', 'Da tra', 'KhachDaTra', '~Thanh toán'],
    ['Còn nợ', 'Chưa trả', 'Còn lại', 'Dư nợ', 'Còn phải thu', 'ConPhaiThu', 'Nợ còn lại'],
    ['Phương thức thanh toán', 'Phương thức TT', 'Hình thức thanh toán', 'PTTT', 'HTTT', 'Trả bằng', 'Phương thức',
     'PhuongThucTT', 'PhuongThuc', 'Hình thức TT'],
    ['Kênh bán', 'Bán qua', 'Loại bán', 'Nguồn đơn', 'Kênh bán hàng', 'KenhBanHang'],
    ['Người bán', 'Nhân viên bán', 'NV bán'],
    ['Mã NV bán', 'Mã nhân viên', 'MaNhanVien', 'Mã NV'],
    ['Nhóm hàng', 'Nhóm hàng hóa', 'Nhom hang', 'Danh mục', 'Phân loại', '~Nhóm hàng(3 Cấp)', 'Ngành hàng', 'DanhMuc'],
    ['Nhóm khách hàng', 'Nhóm KH', 'Nhóm', 'Hạng', 'Nhóm khách', 'Đối tượng KH', 'LoaiKhachHang', 'Loại khách'],
    ['Điện thoại', 'Số điện thoại', 'Di động', 'Phone', 'SĐT', 'SoDienThoai'],
    ['Địa chỉ', 'Addr', 'Địa chỉ liên hệ', 'DiaChiLienHe'],
    ['Tỉ lệ quy đổi', 'Hệ số', 'Hệ số QĐ', 'Quy đổi', 'Bằng', 'Hệ số quy đổi', 'HeSoQuyDoi'],
    ['Mã phiếu thu', 'Phiếu thu', 'Số phiếu thu', 'MaPhieuThu'],
    ['Thời gian thu', 'Ngày thu', 'Ngày giờ thu', 'NgayGioThu'],
    ['Số tiền thu', 'Tiền thu', 'SoTienThu'],
    ['Mã nhập hàng', 'Mã phiếu nhập', 'Mã đơn nhập', 'Số phiếu nhập', 'MaPhieuNhap'],
    ['Ngày nhập', 'Ngày nhập kho', 'NgayNhapKho', 'Ngày nhập hàng'],
    ['Mã NCC', 'Mã nhà cung cấp', 'MaNhaCungCap'],
    ['Nhà cung cấp', 'Tên NCC', 'Tên nhà cung cấp'],
    ['Cần trả NCC', 'Tổng tiền nhập', 'Tổng giá trị nhập', 'TongGiaTriNhap'],
    ['SL nhập', 'Số lượng nhập'],
    ['Giá nhập', 'Đơn giá nhập', 'DonGiaNhap'],
    ['ĐVT nhập', 'Đơn vị nhập'],
    ['Lô', 'Mã lô', 'Số lô', 'MaLo'],
    ['Hạn sử dụng', 'HSD', 'Hạn dùng', 'HanSuDung'],
    ['Hoạt chất', 'Thành phần chính', 'ThanhPhanChinh'],
    ['Thuốc kê đơn', 'Kê đơn', 'Bán theo đơn', 'BanTheoDon'],
    ['Tồn cuối kỳ', 'Tồn cuối', 'Tồn thực', 'Ton kho', 'Tồn kho', 'TonCuoi'],
    ['Ngày áp dụng', 'Từ ngày', 'NgayApDung'],
    ['Giá mới', 'Giá bán mới'],
    ['Giá cũ', 'Giá trước'],
    ['Ngày giao hàng', 'Ngày chở', 'Ngày giao'],
    ['Lần giao', 'Lượt giao', 'Đợt giao'],
    ['Số lượng giao', 'SL thực giao', 'SL giao'],
    ['Biển số xe', 'Biển số'],
    ['Người giao hàng', 'Người chở', 'Tài xế'],
    ['Số ngày được nợ', 'Hạn nợ (ngày)', 'Số ngày nợ'],
    ['Hạn thanh toán', 'Han tra', 'Hạn trả'],
    ['Ngày chi'],
    ['Mục', 'Khoản chi', 'Loại chi'],
    ['So tien', 'Số tiền chi', 'Tiền chi'],
    ['Giá vốn', 'Giá vốn (đ)', 'GiaVonHang', 'Giá vốn đơn vị'],
    ['Giá vốn lúc bán', 'GiaVonLucBan', 'Giá vốn khi bán'],
    ['Giá vốn hiện tại', 'Giá vốn hiện hành'],
    ['STT', 'Thứ tự', 'No.', 'TT dòng', 'SoThuTu', 'Dòng số'],
    ['Ghi chú', 'Ghi chu', 'Diễn giải', 'DienGiai'],
    ['Email', 'E-mail', 'email', 'Thư điện tử'],
    ['Ngày sinh', 'Sinh nhật', 'ngay_sinh'],
    ['Mã số thuế', 'MST'],
    ['CCCD', 'Số CMND/CCCD', 'cccd', 'CMND/CCCD'],
    ['Tên công ty', 'Công ty', 'cong_ty'],
    ['Điểm tích lũy', 'Điểm hiện tại', 'diem_hien_tai'],
    ['Người tạo', 'nguoi_tao', 'Tạo bởi'],
    ['Mã barcode', 'Mã vạch EAN', 'Mã vạch', 'ma_vach_ean'],
    ['Thương hiệu', '~Hãng', 'thuong_hieu', 'Nhãn hiệu'],
    ['Vị trí', 'Vị trí kệ', 'vi_tri'],
    ['Mô tả sản phẩm', 'Mô tả chi tiết', 'Mô tả'],
    ['Hình ảnh', 'Hình ảnh (url1,url2...)', 'hinh_anh', 'Ảnh'],
    ['Tồn lớn nhất', 'Định mức tồn tối đa', 'ton_lon_nhat'],
    ['Tồn nhỏ nhất', 'Định mức tồn tối thiểu', 'ton_nho_nhat'],
    ['Loại hàng hóa', 'Loại sản phẩm', 'loai_hang_hoa'],
    ['Được bán trực tiếp', 'Bán trực tiếp', 'ban_truc_tiep'],
]


def header_key(h: str) -> str:
    """CamelCase and snake_case split into words, then folded: 'TongThanhToan' ~ 'Tổng thanh toán'."""
    s = re.sub(r'(?<=[a-zà-ỹđ])(?=[A-ZĐ])', ' ', str(h)).replace('_', ' ')
    return norm(s)


def _accent_key(h: str) -> str:
    return norm(re.sub(r'(?<=[a-zà-ỹđ])(?=[A-ZĐ])', ' ', str(h)).replace('_', ' '), accents=True)


_BY_ACCENT, _BY_FOLD = {}, {}
for _i, _group in enumerate(HEADERS):
    for _h in _group:
        _BY_ACCENT.setdefault(_accent_key(_h.lstrip('~')), set()).add(_i)
        _BY_FOLD.setdefault(header_key(_h.lstrip('~')), set()).add(_i)


def header_group(h: str):
    """The synonym set of a header, or None. A header with Vietnamese marks matches with its marks ("Hạng" is not
    "Hàng"); one written without marks matches by its folded words only when that names one set."""
    if strip_accents(h) != h:
        found = _BY_ACCENT.get(_accent_key(h), set())
    else:
        found = _BY_ACCENT.get(_accent_key(h), set()) or _BY_FOLD.get(header_key(h), set())
    return next(iter(found)) if len(found) == 1 else None


def strip_accents(s: str) -> str:
    s = s.replace('đ', 'd').replace('Đ', 'D')
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def name_style(h: str) -> str:
    """camel (TongThanhToan, SL), snake (so_luong, cccd), ascii (Thanh tien: no accents), or plain."""
    if re.fullmatch(r'[a-z0-9]+(_[a-z0-9]+)*', h):
        return 'snake'
    if re.fullmatch(r'[A-Za-z0-9.]+', h):
        return 'camel'
    if re.fullmatch(r'[A-Za-z0-9 .()/]+', h):
        return 'ascii'
    return 'plain'


def render_style(name: str, style: str) -> str:
    words = re.findall(r'[^\W_]+', re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', strip_accents(name)))
    if style == 'camel':
        return ''.join(w[:1].upper() + w[1:] for w in words)
    if style == 'snake':
        return '_'.join(w.lower() for w in words)
    if style == 'ascii':
        return ' '.join(words)
    return name


# ---------------------------------------------------------------- labels
LABEL_CATEGORY = {   # norm(label) of every unambiguous train status/payment label -> category
    'da huy': 'cancelled', 'huy don': 'cancelled', 'da huy don': 'cancelled', 'huy': 'cancelled', 'khach huy': 'cancelled',
    'cancelled': 'cancelled', 'cancel': 'cancelled',
    'doi tra': 'returned', 'hoan tra': 'returned', 'hang tra ve': 'returned', 'tra hang': 'returned', 'tra lai': 'returned',
    'da tra hang': 'returned', 'returned': 'returned', 'da hoan hang': 'returned',
    'xong': 'completed', 'da hoan thanh': 'completed', 'thanh cong': 'completed', 'da xong': 'completed',
    'hoan thanh': 'completed', 'completed': 'completed', 'da giao': 'completed',
    'dang giao': 'delivering', 'dang giao hang': 'delivering', 'dang van chuyen': 'delivering', 'cho giao': 'delivering',
    'shipping': 'delivering',
    'tien mat': 'cash', 'cash': 'cash', 'chuyen khoan': 'transfer', 'transfer': 'transfer', 'thu ho cod': 'cod',
    'cod': 'cod', 'ghi no': 'debt', 'debt': 'debt', 'vi dien tu': 'ewallet', 'ewallet': 'ewallet',
}
# Left as they are (their category is a judgement the teacher's reasoning may discuss): 'đã lấy', 'ok', 'Đang xử lý',
# 'Đang giao dịch', 'đang gửi', 'Không giao được'.
LABEL_POOLS = {
    'vi': {
        'cancelled': ['Đã hủy', 'Hủy', 'Đã huỷ', 'Hủy đơn', 'Khách hủy', 'Đơn hủy', 'Đã hủy đơn', 'Hủy bỏ', 'Bị hủy'],
        'returned': ['Trả hàng', 'Đã trả hàng', 'Hoàn trả', 'Khách trả hàng', 'Trả lại', 'Đổi trả', 'Hoàn hàng', 'Đã hoàn hàng'],
        'completed': ['Hoàn thành', 'Đã hoàn thành', 'Thành công', 'Đã giao', 'Giao thành công', 'Xong', 'Hoàn tất', 'Đã xong'],
        'delivering': ['Đang giao', 'Đang giao hàng', 'Đang vận chuyển', 'Chờ giao', 'Đang ship'],
        'cash': ['Tiền mặt', 'TM', 'Tiền mặt (TM)', 'Thanh toán tiền mặt'],
        'transfer': ['Chuyển khoản', 'Chuyển khoản NH', 'Ngân hàng', 'Chuyển khoản ngân hàng'],
        'cod': ['COD', 'Thu hộ (COD)', 'Thu hộ', 'Ship COD', 'Giao hàng thu tiền'],
        'debt': ['Ghi nợ', 'Công nợ', 'Nợ', 'Trả sau', 'Bán nợ'],
        'ewallet': ['Ví điện tử', 'Ví ĐT', 'E-wallet', 'Ví điện tử (QR)'],
    },
    'code': {
        'cancelled': ['CANCELLED', 'canceled', 'void', 'HUY'],
        'returned': ['RETURNED', 'return', 'TRA_HANG', 'returned_order'],
        'completed': ['COMPLETED', 'done', 'success', 'HOAN_THANH', 'finished'],
        'delivering': ['SHIPPING', 'delivering', 'in_transit', 'DANG_GIAO'],
        'cash': ['CASH', 'TM', 'tien_mat'],
        'transfer': ['BANK', 'bank_transfer', 'chuyen_khoan', 'TRANSFER'],
        'cod': ['COD', 'ship_cod', 'cod_ship'],
        'debt': ['CREDIT', 'ghi_no', 'DEBT', 'cong_no'],
        'ewallet': ['EWALLET', 'e_wallet', 'vi_dien_tu', 'wallet'],
    },
}
ENGLISH_LABELS = {'cancelled', 'cancel', 'returned', 'completed', 'shipping', 'cash', 'transfer', 'cod', 'debt', 'ewallet'}
LABEL_LIMIT = 30       # a label column has at most this many distinct values
P_COLUMN, P_LABEL, P_SHUFFLE = .85, .85, .7     # share of headers, label families, sheets changed

# ---------------------------------------------------------------- file, sheet and table names
PHRASES = {          # norm of a name phrase -> names of the same thing (accented; rendered in the file's style)
    'danh sach': ['Danh sách', 'DS', 'Bảng kê'],
    'hoa don': ['Hóa đơn', 'Đơn hàng', 'HĐ'],
    'don hang': ['Đơn hàng', 'Hóa đơn', 'Đơn bán'],
    'chi tiet': ['Chi tiết', 'CT'],
    'san pham': ['Sản phẩm', 'Hàng hóa', 'Mặt hàng'],
    'hang hoa': ['Hàng hóa', 'Sản phẩm', 'Mặt hàng'],
    'khach hang': ['Khách hàng', 'KH', 'Khách'],
    'nhap hang': ['Nhập hàng', 'Phiếu nhập', 'Nhập kho'],
    'don nhap hang': ['Đơn nhập hàng', 'Phiếu nhập hàng'],
    'ton kho': ['Tồn kho', 'Xuất nhập tồn', 'Kho hàng'],
    'bao cao': ['Báo cáo', 'BC'],
    'ban hang': ['Bán hàng', 'Doanh số', 'Bán lẻ'],
    'so': ['Sổ', 'Nhật ký'],
    'so quy': ['Sổ quỹ', 'Thu chi', 'Sổ thu chi'],
    'so tay': ['Sổ tay', 'Ghi chép'],
    'thanh toan': ['Thanh toán', 'Thu tiền', 'Phiếu thu'],
    'phieu thu': ['Phiếu thu', 'Thu tiền'],
    'quy doi': ['Quy đổi', 'Đổi đơn vị'],
    'don vi quy doi': ['Đơn vị quy đổi', 'Quy đổi đơn vị'],
    'don vi tinh': ['Đơn vị tính', 'ĐVT'],
    'don vi': ['Đơn vị', 'ĐVT'],
    'bang gia': ['Bảng giá', 'Lịch sử giá', 'Giá bán'],
    'lich su gia': ['Lịch sử giá', 'Bảng giá'],
    'danh muc': ['Danh mục', 'Danh mục hàng'],
    'du lieu': ['Dữ liệu', 'Data'],
    'du lieu xuat': ['Dữ liệu xuất', 'Export'],
    'giao hang': ['Giao hàng', 'Vận chuyển'],
    'phieu giao hang': ['Phiếu giao hàng', 'Phiếu giao'],
    'bang ke': ['Bảng kê', 'Danh sách'],
    'cong no': ['Công nợ', 'Nợ'],
    'theo han': ['Theo hạn', 'Theo kỳ hạn'],
    'han no': ['Hạn nợ', 'Hạn thanh toán'],
    'lo hang': ['Lô hàng', 'Lô'],
    'lo': ['Lô', 'Theo lô'],
    'thuoc': ['Thuốc', 'Danh mục thuốc'],
    'chi phi': ['Chi phí', 'Khoản chi'],
    'phong ban': ['Phòng bàn', 'Bàn'],
    'ban theo lo': ['Bán theo lô', 'Xuất theo lô'],
    'chi nhanh': ['Chi nhánh', 'Cửa hàng'],
    'nhan vien': ['Nhân viên', 'NV'],
    'nha cung cap': ['Nhà cung cấp', 'NCC'],
    'sp': ['SP', 'Sản phẩm'],
    'phieu nhap': ['Phiếu nhập', 'Nhập hàng'],
    'tra hang': ['Trả hàng', 'Hoàn hàng'],
    'the kho': ['Thẻ kho', 'Sổ kho'],
    'thong tin thuoc': ['Thông tin thuốc', 'Danh mục thuốc'],
    'giao': ['Giao', 'Giao hàng'],
}
_MAX_PHRASE = max(len(k.split()) for k in PHRASES)
FILE_STYLES = ('camel', 'snake', 'misa', 'spaced')
PERIOD_SHEET = re.compile(r'^(?:T|Thang |Tháng |Th)?(\d{1,2})[ ._\-](\d{4})$')
SHEET_FORMS = ('T{m:02d}_{y}', '{m:02d}.{y}', 'Thang {m:02d} {y}', 'Tháng {m:02d}-{y}', 'T{m:02d}-{y}')
GENERIC_SHEET = re.compile(r'(?i)^(sheet|data|trang tính)\s*\d*$')


def name_words(name: str):
    """Original words of a file/sheet/table name: CamelCase, snake_case, spaces and dashes split."""
    s = re.sub(r'(?<=[a-zà-ỹđ])(?=[A-ZĐ])', ' ', name)
    return [w for w in re.split(r'[\s_\-.]+', s) if w]


def rename_phrases(name: str, rng: random.Random):
    """(words of a synonym of `name`, all words known) phrase by phrase, longest phrase first."""
    words = name_words(name)
    keys = [norm(w) for w in words]
    out, known, i = [], True, 0
    while i < len(words):
        for n in range(min(_MAX_PHRASE, len(words) - i), 0, -1):
            k = ' '.join(keys[i:i + n])
            if k in PHRASES:
                out += rng.choice(PHRASES[k]).split()
                i += n
                break
        else:
            out.append(words[i])
            known = known and bool(re.search(r'[^\x00-\x7f]', words[i]))
            i += 1
    return out, known


def render_name(words, style: str) -> str:
    if style == 'camel':
        return ''.join(w[:1].upper() + w[1:] for w in (strip_accents(w) for w in words))
    if style == 'snake':
        return '_'.join(strip_accents(w).lower() for w in words)
    if style == 'misa':
        ws = [strip_accents(w) for w in words]
        return '_'.join([ws[0][:1].upper() + ws[0][1:]] + [w if w.isupper() else w.lower() for w in ws[1:]])
    text = ' '.join(words)
    return text[:1].upper() + text[1:] if text else text


# ---------------------------------------------------------------- plan
@dataclass
class Plan:
    shop: str
    seed: str
    files: dict = field(default_factory=dict)       # old file name -> new
    sheets: dict = field(default_factory=dict)      # "file\tsheet" -> new sheet / SQLite table name
    columns: dict = field(default_factory=dict)     # old header label -> new
    labels: dict = field(default_factory=dict)      # old cell value -> new
    shuffle: dict = field(default_factory=dict)     # "file\tsheet" -> new column order (list of old positions)
    readme: str = 'full'
    tables: dict = field(default_factory=dict)      # old table name -> new (filled after the copy is read back)
    reverted: list = field(default_factory=list)    # renames put back because the reader saw them differently


def _sheet_key(f, s):
    return f'{f}\t{s or ""}'


def _grid_header(rows, is_sql):
    """(header row, labels or None when the header cannot be renamed safely)."""
    cleaned = [[_clean(v) for v in r] for r in rows[:300]]
    width = max((len(r) for r in cleaned), default=0)
    cleaned = [list(r) + [None] * (width - len(r)) for r in cleaned]
    if is_sql:
        return 0, None
    h, group = find_header(cleaned, False)
    if sub_header(cleaned, h) is not None:
        return h, None
    return h, group


def _label_of(v):
    return re.sub(r'\s+', ' ', nfc(str(v))).strip() if v is not None and v != '' else None


def file_headers(files):
    """{label: count} of header labels, {sheet key: header row}, sheet keys with a group header row (no shuffle)."""
    labels, rows_at, grouped = {}, {}, set()
    for sf in files.values():
        for s in sf.sheets:
            key = _sheet_key(sf.name, s.name)
            if sf.kind == 'sqlite':
                for c in s.columns:
                    labels[c] = labels.get(c, 0) + 1
                continue
            if not s.rows:
                continue
            h, group = _grid_header(s.rows, False)
            rows_at[key] = h
            if group is not None:
                grouped.add(key)
            for v in s.rows[h]:
                lab = _label_of(v)
                if lab:
                    labels[lab] = labels.get(lab, 0) + 1
    return labels, rows_at, grouped


def label_values(business):
    """Status/payment labels of the shop: values of short text columns that hold a known label."""
    found = set()
    for name, df in business.tables.items():
        if name == 'calendar':
            continue
        for c in df.columns:
            if c.startswith('__') or df[c].dtype != object:
                continue
            vals = [v for v in df[c].dropna().unique()[:LABEL_LIMIT + 1] if isinstance(v, str)]
            if not vals or len(vals) > LABEL_LIMIT:
                continue
            if any(norm(v) in LABEL_CATEGORY for v in vals):
                found |= {v for v in vals}
    return found


def label_concept(v):
    """(kind, concept) the agent's catalog.label_groups would give a label (None: 'not matched')."""
    from datamate.catalog import LABEL_WORDS
    padded = ' ' + norm(v) + ' '
    for kind, concepts in LABEL_WORDS.items():
        for c, words in concepts.items():
            if any(' ' + w + ' ' in padded for w in words.split('|')):
                return kind, c
    return None


def plan_shop(business, files, rng: random.Random, p_column=None, p_label=None, p_shuffle=None) -> Plan:
    p_column = P_COLUMN if p_column is None else p_column
    p_label = P_LABEL if p_label is None else p_label
    p_shuffle = P_SHUFFLE if p_shuffle is None else p_shuffle
    plan = Plan(business.id, '')
    headers, _, grouped = file_headers(files)
    taken = {header_key(h) for h in headers}                        # never reuse a header of this shop
    # columns
    for h in sorted(headers):
        gi = header_group(h)
        if gi is None or rng.random() > p_column:
            continue
        group = HEADERS[gi]
        style = name_style(h)
        members = [x for x in group if not x.startswith('~')]
        if style in ('camel', 'snake'):                 # identifiers: no punctuation to drop ("No." -> "No")
            members = [x for x in members if not re.search(r'[.()/]', x)]
        elif style == 'plain':                          # a header with marks/spaces: not an identifier-style name
            members = [x for x in members if name_style(x) in ('plain', 'ascii')]
        cands = [render_style(x, style) for x in members]
        cands = [c for c in dict.fromkeys(cands) if header_key(c) not in taken and len(c.strip()) >= 2]
        if not cands:
            continue
        new = rng.choice(cands)
        plan.columns[h] = new
        taken.add(header_key(new))
    # labels: families of one norm (case/accent spellings) keep their spelling pattern
    values = label_values(business)
    used = {norm(v) for v in values}
    fams = {}
    for v in sorted(values):
        if norm(v) in LABEL_CATEGORY:
            fams.setdefault(norm(v), []).append(v)
    english = all(norm(v) in ENGLISH_LABELS for ms in fams.values() for v in ms)
    style = 'code' if english and rng.random() < .7 else 'vi'          # one style for the whole shop
    for key, members in sorted(fams.items()):
        if rng.random() > p_label:
            continue
        cat = LABEL_CATEGORY[key]
        concept = label_concept(members[0])          # the agent's label_groups must group the new label alike
        cands = [c for c in LABEL_POOLS[style][cat] if norm(c) not in used and norm(c) not in taken
                 and label_concept(c) == concept]
        if not cands:
            continue
        base = rng.choice(cands)
        news = _family(members, base)
        if news is None:
            continue
        used.add(norm(base))
        plan.labels.update(news)
    # files, sheets, tables
    used_names = {norm(Path(f).stem) for f in files} | {norm(s.name) for sf in files.values() for s in sf.sheets if s.name}
    style = rng.choice(FILE_STYLES)
    stems = {}
    for f in sorted(files):
        p = Path(f)
        m = re.match(r'^(.*?)([_\- ](?:\d{1,2}|20\d{2}))?$', p.stem)
        base, suffix = m.group(1), m.group(2) or ''
        if base not in stems:
            stems[base] = _new_name(base, style, rng, used_names)
        new_base = stems[base]
        if new_base:
            plan.files[f] = new_base + suffix + p.suffix
    for f, sf in files.items():
        forms = rng.choice(SHEET_FORMS)
        for s in sf.sheets:
            if s.name is None or GENERIC_SHEET.match(s.name):
                continue
            m = PERIOD_SHEET.match(s.name)
            if m:
                new = forms.format(m=int(m.group(1)), y=int(m.group(2)))
            else:
                new = _new_name(s.name, 'snake' if sf.kind == 'sqlite' else rng.choice(('camel', 'spaced', 'misa')), rng, used_names)
            if new and new != s.name:
                plan.sheets[_sheet_key(f, s.name)] = new
    # column order
    for f, sf in files.items():
        for s in sf.sheets:
            key = _sheet_key(f, s.name)
            width = len(s.columns) if sf.kind == 'sqlite' else max((len(r) for r in s.rows), default=0)
            if key in grouped or width < 2 or rng.random() > p_shuffle:
                continue
            perm = list(range(width))
            rng.shuffle(perm)
            plan.shuffle[key] = perm
    # partitions of one table keep one order
    by_base = {}
    for key, perm in sorted(plan.shuffle.items()):
        f = key.split('\t')[0]
        base = re.sub(r'([_\- ](?:\d{1,2}|20\d{2}))?\.\w+$', '', f)
        by_base.setdefault(base, perm)
        if len(perm) == len(by_base[base]):
            plan.shuffle[key] = by_base[base]
    plan.readme = rng.choices([l for l, _ in LEVELS], [w for _, w in LEVELS])[0]
    _drop_ambiguous(plan, files)
    return plan


def _family(members, base):
    """New spellings for one label family (members differ only by case/accents): same case pattern."""
    if len(members) == 1:
        return {members[0]: base}
    out = {}
    variants = [base, base.lower(), base.upper(), base[:1].upper() + base[1:].lower(), strip_accents(base)]
    for m in members:
        if m.islower():
            new = base.lower()
        elif m.isupper():
            new = base.upper()
        else:
            new = base
        if new in out.values():
            new = next((v for v in variants if v not in out.values()), None)
            if new is None:
                return None
        out[m] = new
    return out if len(set(out.values())) == len(out) else None


def _new_name(name, style, rng, used):
    for _ in range(6):
        words, known = rename_phrases(name, rng)
        st = style if (style != 'spaced' or known) else 'camel'
        new = render_name(words, st)
        if new and norm(new) not in used and new != name:
            used.add(norm(new))
            return new
    return None


def _drop_ambiguous(plan: Plan, files):
    """A string that is two kinds of name (a column and a table, a sheet and a label...) is not renamed."""
    sheets = {k.split('\t')[1] for k in plan.sheets}
    stems = {Path(f).stem for f in plan.files}
    kinds = [set(plan.columns), set(plan.labels), sheets, stems]
    for i, a in enumerate(kinds):
        for b in kinds[i + 1:]:
            for x in a & b:
                plan.columns.pop(x, None)
                plan.labels.pop(x, None)
                for k in [k for k in plan.sheets if k.split('\t')[1] == x]:
                    plan.sheets.pop(k)
                for f in [f for f in plan.files if Path(f).stem == x]:
                    plan.files.pop(f)


# ---------------------------------------------------------------- apply
def apply_plan(files: dict, plan: Plan) -> dict:
    out = {}
    for f, sf in files.items():
        new = ShopFile(plan.files.get(f, f), sf.kind, csv=dict(sf.csv))
        for s in sf.sheets:
            key = _sheet_key(f, s.name)
            name = plan.sheets.get(key, s.name)
            perm = plan.shuffle.get(key)
            if sf.kind == 'sqlite':
                cols = [plan.columns.get(c, c) for c in s.columns]
                types, rows = list(s.types), [list(r) for r in s.rows]
                rows = [[_relabel(v, plan.labels) for v in r] for r in rows]
                if perm and len(perm) == len(cols):
                    cols, types = [cols[j] for j in perm], [types[j] for j in perm]
                    rows = [[r[j] for j in perm] for r in rows]
                new.sheets.append(type(s)(name, rows, cols, types))
                continue
            rows = [list(r) for r in s.rows]
            if rows:
                h, _ = _grid_header(rows, False)
                width = max(len(r) for r in rows)
                rows = [r + [''] * (width - len(r)) if len(r) < width else r for r in rows]
                rows[h] = [_rename_header(v, plan.columns) for v in rows[h]]
                for i in range(h + 1, len(rows)):
                    rows[i] = [_relabel(v, plan.labels) for v in rows[i]]
                if perm and len(perm) == width:
                    rows = rows[:h] + [[r[j] for j in perm] for r in rows[h:]]
            new.sheets.append(type(s)(name, rows))
        out[new.name] = new
    return out


def _rename_header(v, columns):
    lab = _label_of(v)
    return columns.get(lab, v) if lab is not None else v


def _relabel(v, labels):
    if not isinstance(v, str) or not labels:
        return v
    key = nfc(v).strip()
    if key in labels:
        lead = v[:len(v) - len(v.lstrip())]
        trail = v[len(v.rstrip()):]
        return lead + labels[key] + trail
    return v


# ---------------------------------------------------------------- checks
def table_sources(business):
    return {p['table']: p['sources'] for p in business.profiles if p['table'] != 'calendar'}


def map_source(src: str, plan: Plan) -> str:
    """A source as the reader names it ('file.xlsx:Sheet', 'file.xlsx (3 sheets)') after the renames."""
    m = re.match(r'^(.*?)( \(\d+ sheets\))?$', src)
    body, tail = m.group(1), m.group(2) or ''
    f, _, s = body.partition(':')
    nf = plan.files.get(f, f)
    if s:
        s = plan.sheets.get(_sheet_key(f, s), s)
        return f'{nf}:{s}{tail}'
    return nf + tail


def compare(orig, new, plan: Plan):
    """(old -> new table names, problems). Problems name the old column (or table) that reads differently."""
    a_src, b_src = table_sources(orig), table_sources(new)
    by_sources = {tuple(sorted(v)): k for k, v in b_src.items()}
    tables, problems = {}, []
    for t, srcs in a_src.items():
        key = tuple(sorted(map_source(s, plan) for s in srcs))
        if key not in by_sources:
            problems.append(('table', t, f'sources {key} not found'))
            continue
        tables[t] = by_sources[key]
    if len(set(tables.values())) != len(tables) or len(b_src) != len(a_src):
        problems.append(('table', '*', f'{len(a_src)} tables -> {len(b_src)}'))
    inv = lambda c: next((o for o, n in plan.columns.items() if n == c), c)
    for t, nt in tables.items():
        A, B = orig.tables[t], new.tables[nt]
        if len(A) != len(B):
            problems.append(('table', t, f'{len(A)} rows -> {len(B)}'))
            continue
        cols = {}
        for c in B.columns:
            old = _old_column(c, plan)
            cols[old] = c
        if set(cols) != set(A.columns):
            missing = set(A.columns) - set(cols)
            extra = set(cols) - set(A.columns)
            for c in sorted(missing | extra, key=str):
                base = c
                for suf in ('__raw', '__unit', '__group_total'):
                    base = base[:-len(suf)] if base.endswith(suf) else base
                problems.append(('column', inv(base), f'{t}: column set differs ({c})'))
            continue
        for c in A.columns:
            x, y = A[c], B[cols[c]]
            if c == SOURCE_COL:
                x = x.map(lambda s: map_source(s, plan) if isinstance(s, str) else s)
            elif plan.labels and x.dtype == object:
                x = x.map(lambda v: _relabel(v, plan.labels))
            if str(x.dtype) != str(y.dtype) or not x.reset_index(drop=True).equals(y.reset_index(drop=True)):
                problems.append(('column', c, f'{t}: values differ ({x.dtype} -> {y.dtype})'))
        pa = next(p for p in orig.profiles if p['table'] == t)
        ga = _groups(pa, plan, mapped=True)
        gb = _groups(next(p for p in new.profiles if p['table'] == nt), plan)
        if ga != gb:
            problems.append(('labels', t, f'label_groups differ: {ga} -> {gb}'))
        pb = next(p for p in new.profiles if p['table'] == nt)
        if pa['dropped_rows'] != pb['dropped_rows']:
            problems.append(('table', t, f"dropped rows {pa['dropped_rows']} -> {pb['dropped_rows']}"))
    return tables, problems


def _groups(profile, plan, mapped=False):
    """catalog.label_groups of one table as {(old column, kind): {concept: sorted labels}} (old labels mapped)."""
    from datamate.catalog import label_groups, schema
    out = {}
    for g in label_groups([schema(profile)]):
        col = g['column'] if mapped else _old_column(g['column'], plan)
        out[(col, g['kind'])] = {k: sorted(_relabel(v, plan.labels) if mapped else v for v in vs) for k, vs in g['labels'].items()}
    return out


def _old_column(c, plan):
    for suf in ('', '__raw', '__unit', '__group_total'):
        base = c[:-len(suf)] if suf and c.endswith(suf) else (c if not suf else None)
        if base is None:
            continue
        for o, n in plan.columns.items():
            if n == base:
                return o + suf
    return c


def revert(plan: Plan, problems, files):
    """Put back what a problem points at: the column's rename, else every shuffle and the files' renames."""
    changed = False
    for kind, what, why in problems:
        if kind == 'labels' and plan.labels:
            plan.reverted.append(f'labels: {why}'[:300])
            plan.labels.clear()
            changed = True
            continue
        if kind == 'column' and what in plan.columns:
            plan.reverted.append(f'column {what} -> {plan.columns.pop(what)}: {why}')
            changed = True
        elif kind == 'column' and plan.shuffle:
            plan.reverted.append(f'shuffle: {why}')
            plan.shuffle.clear()
            changed = True
        elif kind == 'column' and plan.labels:
            plan.reverted.append(f'labels: {why}')
            plan.labels.clear()
            changed = True
    if not changed and problems:
        for attr in ('shuffle', 'sheets', 'files', 'labels'):
            if getattr(plan, attr):
                plan.reverted.append(f'{attr}: {problems[0][2]}')
                getattr(plan, attr).clear()
                return True
    return changed


# ---------------------------------------------------------------- names for text
def name_map(plan: Plan, orig, files) -> NameMap:
    """Old -> new strings for code, reasoning and README: columns (and their companion columns), tables, files
    (with and without extension), sheets."""
    names = dict(plan.columns)
    for f, nf in plan.files.items():
        names[f] = nf
        names[Path(f).stem] = Path(nf).stem
        m = re.match(r'^(.*?)[_\- ](?:\d{1,2}|20\d{2})$', Path(f).stem)
        mn = re.match(r'^(.*?)[_\- ](?:\d{1,2}|20\d{2})$', Path(nf).stem)
        if m and mn:
            names[m.group(1)] = mn.group(1)
    for k, new in plan.sheets.items():
        names[k.split('\t')[1]] = new
    names.update({t: n for t, n in plan.tables.items() if t != n})      # a stem that is also the table name: the table
    for t, n in plan.tables.items():                                    # a table that kept its name keeps it in text
        if t == n:
            names.pop(t, None)
    names = {k: v for k, v in names.items() if k and k != v}
    labels = {k: v for k, v in plan.labels.items() if k not in names}
    keep = set(plan.tables) | {c for t, df in orig.tables.items() if t != 'calendar' for c in df.columns} | label_values(orig)
    return NameMap(names, labels, keep)


# ---------------------------------------------------------------- README
STANDARD_DOCS = {norm(x) for x in (*DOC.values(), *DOC_MASTER.values(), *FILLER_DOC.values(), 'tên', 'ghi chú')}
SECTION = re.compile(r'^## Cột trong `([^`]+)`(?:, sheet `([^`]+)`)?\s*$')
BULLET = re.compile(r'^- \*\*(.+?)\*\*: (.*)$')
TITLE = re.compile(r'^(\s*- \*\*[^*]+\*\*:)(.*)$')


def rewrite_readme(text: str, plan: Plan, nm: NameMap, rng: random.Random, sales_files=()) -> str:
    """README.md with the new names; `partial` drops the plain column docs of non-sales files, `brief` of every
    file (docs that say more than the column's meaning, such as label codes or exceptions, always stay)."""
    lines = text.split('\n')
    out, i = [], 0
    label_words = None
    if nm.labels:
        codes = [o for o in nm.labels if re.fullmatch(r'[A-Za-z_]+', o) or o != o.lower()]   # 'cash', 'Tiền mặt', not 'trả hàng'
        body = '|'.join(re.escape(o) for o in sorted(codes, key=len, reverse=True))
        label_words = re.compile(rf'(?<![\w])({body})(?![\w])') if codes else None
    while i < len(lines):
        m = SECTION.match(lines[i])
        if not m:
            t = TITLE.match(lines[i])
            if t:                      # a note title is a concept; one that is exactly an old column name follows it
                title = re.match(r'^(\s*- \*\*)([^*]+)(\*\*:)$', t.group(1))
                head = title.group(1) + plan.columns.get(title.group(2), title.group(2)) + title.group(3) if title else t.group(1)
                out.append(head + nm.map_prose(t.group(2)))
            else:
                out.append(nm.map_prose(lines[i]))
            i += 1
            continue
        f, sheet = m.group(1), m.group(2)
        j = i + 1
        bullets, tail = [], []
        while j < len(lines) and not lines[j].startswith('## '):
            b = BULLET.match(lines[j])
            if b:
                bullets.append((b.group(1), b.group(2)))
            elif lines[j].strip():
                tail.append(lines[j])
            j += 1
        keep_plain = plan.readme == 'full' or (plan.readme == 'partial' and f in sales_files)
        kept = []
        for col, doc in bullets:
            if not keep_plain and norm(doc) in STANDARD_DOCS:
                continue
            new_doc = nm.map_prose(doc)
            if label_words is not None:
                new_doc = label_words.sub(lambda x: nm.labels[x.group(1)], new_doc)
            kept.append(f'- **{plan.columns.get(col, col)}**: {new_doc}')
        if rng.random() < .5:
            rng.shuffle(kept)
        if kept or tail:
            nf = plan.files.get(f, f)
            head = f'## Cột trong `{nf}`' + (f", sheet `{plan.sheets.get(_sheet_key(f, sheet), sheet)}`" if sheet else '')
            out += [head] + kept + [nm.map_prose(x) for x in tail] + ['']
        i = j
    text = '\n'.join(out)
    return re.sub(r'\n{3,}', '\n\n', text).rstrip('\n') + '\n'


# ---------------------------------------------------------------- one shop
def reskin_shop(src: Path, dst: Path, calendar: Path, seed: str, cache: Path | None = None, tries=5):
    """Write the reskinned copy of one shop; returns its plan (as a dict) with the checks."""
    rng = random.Random(seed)
    files = read_shop(src)
    orig = load_business(src, calendar, cache)
    plan = plan_shop(orig, files, rng)
    plan.seed = seed
    problems = []
    for attempt in range(tries):
        if dst.exists():
            shutil.rmtree(dst)
        write_shop(apply_plan(files, plan), dst)
        new = load_business(dst, calendar, None)
        tables, problems = compare(orig, new, plan)
        if new.unreadable:
            problems.append(('table', '*', f'unreadable: {new.unreadable}'))
        if not problems:
            break
        if not revert(plan, problems, files):
            break
    plan.tables = tables if not problems else {}
    sales = _sales_files(orig, plan)
    nm = name_map(plan, orig, files)
    readme = (src / 'README.md').read_text(encoding='utf-8') if (src / 'README.md').exists() else ''
    new_readme = rewrite_readme(readme, plan, nm, random.Random(seed + ':readme'), sales)
    (dst / 'README.md').write_text(new_readme, encoding='utf-8')
    untitled = '\n'.join(t.group(2) if (t := TITLE.match(x)) else x for x in new_readme.split('\n'))
    out = asdict(plan)
    out.update(ok=not problems, problems=[list(p) for p in problems], attempts=attempt + 1,
               readme_stale=nm.stale(prose=untitled), names=nm.names, label_map=nm.labels, keep=nm.keep,
               catalog_columns_before=sum(len(df.columns) for t, df in orig.tables.items() if t != 'calendar'),
               columns_renamed=len(plan.columns), labels_renamed=len(plan.labels))
    return out


def _sales_files(business, plan):
    """Files of the largest table (the sales lines): their column docs stay at the `partial` level."""
    best = max((p for p in business.profiles if p['table'] != 'calendar'), key=lambda p: p['rows'], default=None)
    if not best:
        return set()
    return {re.sub(r'( \(\d+ sheets\)|:.*)$', '', s) for s in best['sources']}


# ---------------------------------------------------------------- split
def _jsonl(path):
    return [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]


def _write_jsonl(path, rows):
    with open(path, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def _quoted_old(text, nm: NameMap):
    """A question that quotes or spells out an old name/label (the question would not match the copy)."""
    return [s for s in nm.stale(prose=text)]


def build_copy(k: int, out: Path, seed: int, shops, workers: int, cache: Path | None, train: Path = TRAIN):
    split = out / f'reskin_{k}'
    if split.exists():
        shutil.rmtree(split)
    (split / 'data').mkdir(parents=True)
    shutil.copy(train / 'calendar.csv', split / 'calendar.csv')
    shutil.copy(train / 'rulebook.md', split / 'rulebook.md')
    jobs = [(train / 'data' / b, split / 'data' / b, train / 'calendar.csv', f'{seed}:{k}:{b}', cache) for b in shops]
    if workers > 1:
        with ProcessPoolExecutor(workers) as pool:
            plans = dict(zip(shops, pool.map(_reskin_job, jobs)))
    else:
        plans = dict(zip(shops, map(_reskin_job, jobs)))
    questions = [q for q in _jsonl(train / 'questions.jsonl') if q['business_id'] in plans]
    gold = {a['id']: a for a in _jsonl(train / 'answers.jsonl')}
    intents = _train_intents() if train == TRAIN else {}
    qs, ans, meta, dropped = [], [], [], {}
    for q in questions:
        p = plans[q['business_id']]
        if not p['ok']:
            dropped['shop_not_ok'] = dropped.get('shop_not_ok', 0) + 1
            continue
        nm = NameMap(p['names'], p['label_map'], p.get('keep', ()))
        g = nm.map_answer(gold[q['id']])
        if g is None:
            dropped['answer_is_renamed_name'] = dropped.get('answer_is_renamed_name', 0) + 1
            continue
        if _quoted_old(q['question'], nm):
            dropped['question_quotes_old_name'] = dropped.get('question_quotes_old_name', 0) + 1
            continue
        qs.append(q)
        ans.append(g)
        meta.append({'id': q['id'], 'orig_id': q['id'], 'business_id': q['business_id'], 'intent': intents.get(q['id']),
                     'variant': f'reskin_{k}', 'label_mapped': g != gold[q['id']]})
    _write_jsonl(split / 'questions.jsonl', qs)
    _write_jsonl(split / 'answers.jsonl', ans)
    _write_jsonl(split / 'meta.jsonl', meta)
    val = [{'split': _rel(split), 'id': q['id'], 'business_id': q['business_id'], 'group': q['id']}
           for q in qs if q['business_id'] in VAL_SHOPS]
    _write_jsonl(split / 'val_questions.jsonl', val)
    (split / 'val_ids.txt').write_text(''.join(v['id'] + '\n' for v in val), encoding='utf-8')
    summary = {'copy': k, 'seed': seed, 'shops': len(plans), 'shops_ok': sum(p['ok'] for p in plans.values()),
               'questions': len(qs), 'dropped_questions': dropped, 'val_questions': len(val),
               'label_mapped_answers': sum(m['label_mapped'] for m in meta),
               'readme_levels': _count(p['readme'] for p in plans.values()),
               'columns_renamed': sum(p['columns_renamed'] for p in plans.values()),
               'labels_renamed': sum(p['labels_renamed'] for p in plans.values()),
               'files_renamed': sum(len(p['files']) for p in plans.values()),
               'sheets_renamed': sum(len(p['sheets']) for p in plans.values()),
               'tables_renamed': sum(sum(1 for a, b in p['tables'].items() if a != b) for p in plans.values()),
               'shuffled': sum(len(p['shuffle']) for p in plans.values()),
               'reverted': {b: p['reverted'] for b, p in plans.items() if p['reverted']},
               'readme_stale': {b: p['readme_stale'] for b, p in plans.items() if p['readme_stale']}}
    (split / 'reskin.json').write_text(json.dumps({'summary': summary, 'shops': plans}, ensure_ascii=False, indent=1),
                                       encoding='utf-8')
    return summary


def refresh_maps(split: Path, calendar: Path, cache: Path | None):
    """Recompute the text maps (names, labels, kept names) of an existing copy from its stored plan, without
    rewriting its files (after a fix of name_map); README is rewritten from the train README with the same seed."""
    path = split / 'reskin.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    for b, p in data['shops'].items():
        plan = Plan(**{k: p[k] for k in Plan.__dataclass_fields__})
        orig = load_business(TRAIN / 'data' / b, calendar, cache)
        nm = name_map(plan, orig, None)
        readme = (TRAIN / 'data' / b / 'README.md').read_text(encoding='utf-8')
        new_readme = rewrite_readme(readme, plan, nm, random.Random(plan.seed + ':readme'), _sales_files(orig, plan))
        (split / 'data' / b / 'README.md').write_text(new_readme, encoding='utf-8')
        untitled = '\n'.join(t.group(2) if (t := TITLE.match(x)) else x for x in new_readme.split('\n'))
        p.update(names=nm.names, label_map=nm.labels, keep=nm.keep, readme_stale=nm.stale(prose=untitled))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    return {b: p['readme_stale'] for b, p in data['shops'].items() if p['readme_stale']}


def _reskin_job(job):
    src, dst, cal, seed, cache = job
    return reskin_shop(src, dst, cal, seed, cache)


def _count(xs):
    out = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


def _rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def _train_intents():
    try:
        from gen.package import train_intent
        return {q['id']: train_intent(q['id']) for q in _jsonl(TRAIN / 'questions.jsonl')}
    except Exception:                                      # noqa: BLE001 - intents are for stats only
        return {}


def plan_digest(plan: dict) -> str:
    return hashlib.sha1(json.dumps({k: plan[k] for k in ('names', 'label_map')}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', default=str(ROOT / 'data_gen'), help='parent folder: writes <out>/reskin_<k>/')
    ap.add_argument('--copies', type=int, default=2)
    ap.add_argument('--first', type=int, default=1, help='number of the first copy')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--shops', default='', help='comma separated (default: every train shop)')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--cache', default=str(ROOT / 'outputs' / 'cache'))
    ap.add_argument('--refresh-maps', action='store_true', help='recompute the text maps and README of existing copies')
    a = ap.parse_args(argv)
    if a.refresh_maps:
        for k in range(a.first, a.first + a.copies):
            print(f'reskin_{k}: README with old names: {refresh_maps(Path(a.out) / f"reskin_{k}", TRAIN / "calendar.csv", Path(a.cache))}')
        return
    shops = [s for s in a.shops.split(',') if s] or sorted(p.name for p in (TRAIN / 'data').iterdir() if p.is_dir())
    for k in range(a.first, a.first + a.copies):
        s = build_copy(k, Path(a.out), a.seed, shops, a.workers, Path(a.cache) if a.cache else None)
        print(json.dumps({x: y for x, y in s.items() if x not in ('reverted', 'readme_stale')}, ensure_ascii=False))
        if s['reverted']:
            print('  reverted:', json.dumps(s['reverted'], ensure_ascii=False)[:2000])
        if s['readme_stale']:
            print('  README with old names:', json.dumps(s['readme_stale'], ensure_ascii=False)[:2000])


if __name__ == '__main__':
    main()
