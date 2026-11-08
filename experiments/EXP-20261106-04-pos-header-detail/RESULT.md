# RESULT

Shop xuất từ máy POS tách đầu đơn và chi tiết (biz_106/109/124) giờ dựng được `lines`: chỉ sửa map cột, `join_order_fields` có sẵn nối đầu đơn vào dòng hàng.

## Đã đổi (`column_roles.py`)
- `HEADER_ROLES` thêm tên cột của file POS xuất ra, phần lớn có mô tả trùng ở README của shop khác (`Mã hóa đơn` = order_id ở 15 shop).
- `header_role`: so tên cột có xét dấu, `Hạng` không còn khớp `Hàng`, `Hãng` (dev_013) cũng vậy; `hoá`/`hóa` coi là một.
- `context_role`: tên cột mơ hồ đọc theo vai trò khác cùng bảng (`STT`, `Ngày`/`Thời gian`, `ĐVT`/`Đơn vị tính`, `Đơn giá`, `Giảm giá`/`CK`, `Tổng tiền`, `Quy đổi`, `Trạng thái`, `Thời gian tạo`, `Số lượng`). `STT` và `Số lượng` xét trước.

## Số
| Đo | Trước (EXP-03) | Sau |
|---|---|---|
| File norm đổi ngoài 3 shop | | 0 CSV; 3 `mapping.json` public đổi thứ tự role hoặc bỏ dòng rejected |
| oracle train | 2324 | 2566 (+248, mất 6) |
| oracle public | 570 | 570 |
| oracle 3 shop | 0/355 | 250/355 |
| agent 3 shop | PA khoảng -0,8 | +0,780 (308 đúng, 31 sai, 16 trống); test_* 55 câu +0,782 |
| error/train_status test_* | 0,732 | 0,920 |
| error/train_status train_* đã chạy | 0,709 | 0,876 |

6 câu oracle mất đều có gold `unanswerable`: trước đây shop hỏng nên báo lỗi trùng với không trả lời được. Giờ trả số cho kỳ ngoài dữ liệu (tháng 1/2025 ở biz_106) và cột không có (khách nữ, nhóm khách).

## Lỗi còn lại của agent trên 3 shop (31 sai)
- Lệch số nhỏ ở đơn, ca, nợ, tồn (khoảng 9 câu): chưa điều tra, nghi cách tính theo đầu đơn POS.
- Quy đổi đơn vị khi so giá, nhập trừ bán (4 câu, biz_106/124).
- Trả lời câu không trả lời được (5): cổng kỳ ngoài dữ liệu, cột không có.
- Sai dạng: list thay số, tên cột bảng, thứ tự (6).
- Lô hàng biz_124 chưa map (1), lãi gộp biz_109 (1).
