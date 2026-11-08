# RESULT

| Số đo | Trước (EXP-20261106-02) | Sau |
|---|---|---|
| tables_kind_changed | | 3 bảng, đúng 3 sổ không mã đơn (`catalog` → `sales`); chuẩn hoá lại 44 shop, chỉ 3 shop có file khác |
| oracle_train_right | 2204/3000 | 2324/3000 (+120; biz_107, 113, 126 mỗi shop 40/40) |
| oracle_public_right | 570/1000 | 570/1000 |
| oracle_regressions | | 0 train, 0 public |
| agent_three_shops_pa (120 câu, gold) | 1 đúng / 50 sai trên 51 câu đã chạy trước | +0.983 (119 / 1 / 0); test_* 19/19 |

Câu sai còn lại `q_54c30a98b2f5`: LLM thêm `unit='đĩa'` thừa, shop không có cột đơn vị cơ bản, hàm báo `shop has no column for unit`, LLM trả `unanswerable` (đáp án 66). Lỗi cũ nhóm "chọn sai tham số", không do bản sửa này.

Ảnh hưởng tới shop khác: `_require_orders` chỉ chạy khi `lines` không có `order_id`; kiểm cả 44 shop, chỉ biz_107, 113, 126. Dòng bị loại: biz_107 526 dòng `Tổng ngày dd/mm`, đúng.

Kết luận: giả thuyết đúng.
