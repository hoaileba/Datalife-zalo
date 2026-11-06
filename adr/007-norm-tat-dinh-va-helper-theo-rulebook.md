# ADR 007 — Chuẩn hoá tất định và helper theo rulebook cho model 12B

Trạng thái: đề xuất, chờ Hoài duyệt. Thay cho hướng "agent tự viết code chuẩn hoá" của prompt v3.

## Bối cảnh

Cuộc thi bắt buộc model dưới 15B. Số đã đo:

- gemma-3-12b tự chuẩn hoá trên file gốc: 0/2 (`logs/agent/v3-20261104-093713/`).
- gemma tự viết pandas trên bảng sạch cũ: accuracy 0,29 đến 0,38 (EXP-20261103-04, -05).
- Mapping cột do qwen làm sai im lặng: `dev_007` lấy cột tiền cấp đơn làm `line_amount`, doanh thu lệch hơn 4 lần; `dev_013` mất `order_date`. Đối chứng 7/7 trước đó không bắt được vì mẫu nhỏ.
- 1.210 cột của 44 shop chỉ dùng 174 mô tả README.

## Quyết định

Tách làm ba tầng, model chỉ giữ tầng cuối:

1. **Chuẩn hoá tất định** (`column_roles.py`, `normalize.py`, `prepare.py`): tra mô tả README rồi tên cột ra vai trò chuẩn, không gọi LLM, chạy một lần cho mỗi shop.
2. **Tầng số đo** (`datamate/shop.py`): `revenue`, `order_count`, `quantity`, `ranking`... đã áp luật rulebook.
3. **Model** (prompt v4): hiểu câu hỏi, chọn hàm, kỳ, bộ lọc. Câu ngoài các hàm thì viết pandas trên bảng nạp sẵn.

## Pattern và đánh đổi

Đây là **semantic layer** (lớp số đo): LLM sinh lời gọi hàm nghiệp vụ thay vì sinh truy vấn trên bảng thô. Nó hoạt động bằng cách đưa luật vào code đã kiểm, nên model nhỏ chỉ cần chọn đúng. Đánh đổi kinh điển: chính xác cao ở phần đã phủ, đổi lại phải tự viết và bảo trì từng số đo, phần chưa phủ vẫn yếu.

## Các phương án đã loại

- Agent tự viết chuẩn hoá: 0/2, tốn hết lượt.
- LLM map cột: sai im lặng, kể cả có README (gemma gán `order_id ← No.` trên `dev_007`).
- Viết sẵn script từng shop như bản Claude: không chạy được trên shop mới.

## Giá phải trả

- `HEADER_ROLES` viết từ tên cột shop đã thấy, nên shop mới có README không theo template sẽ map thiếu. Chưa đo trên train.
- Chưa có helper cho nợ, kho, lô, lãi; chưa quy đổi đơn vị khi shop không có cột đã quy đổi.
- Từ chối `read_csv` trên `norm/` là cổng chặn code, cần theo dõi có chặn nhầm không.
