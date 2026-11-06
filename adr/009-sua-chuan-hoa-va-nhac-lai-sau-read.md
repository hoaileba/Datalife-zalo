# ADR 009: Sửa chuẩn hoá, helper và nhắc lại câu hỏi sau READ

Trạng thái: chờ duyệt

## Bối cảnh

Phân tích 362 câu không đúng của EXP-20261104-05 cho thấy ba nguồn lỗi có bằng chứng: model bỏ ví dụ sau lượt READ, chuẩn hoá xoá nhầm dữ liệu, helper thiếu quy đổi và alias. Chi tiết ở EXP-20261105-01.

## Quyết định

1. **Nhắc lại câu hỏi và ví dụ top-1 ngay sau kết quả READ.** Đo trên 96 câu từng bỏ ví dụ: -69 lên +25; đối chứng 96 câu: +47 xuống +46. Không đổi dòng `revenue` trong phần luồng làm việc của prompt vì nhánh đó không tốt hơn rõ rệt.
2. **Nhận dòng tổng theo nhãn, không theo tiền tố.** `tong`, `cong` chỉ là dòng tổng khi đứng một mình hoặc theo sau là `cong`, `ngay`, `thang`, `quy`, `nam`, hoặc số. Lý do: khảo sát 44 shop thấy mọi nhãn thật có dạng này, còn lại là họ Tống và `công tắc`.
3. **Bỏ `Đối tượng KH` khỏi vai trò nhóm khách, thêm `Kiểu khách`.** Cột cũ toàn `Cá nhân`.
4. **Đọc hệ số quy đổi từ bảng `unit_factor` của catalog**, thêm `purchase_quantity`.
5. **Alias bộ lọc thanh toán, kênh, và tên nhân viên sang mã** nằm trong helper, không bắt model biết giá trị thô.
6. **Tách topping ghi chung ô thành dòng riêng trong `Shop`**, theo định dạng `món + N tên (tiền đ)` mà README mô tả. Bảng `tables[...]` giữ nguyên dữ liệu gốc.
7. **Shop không có bảng thu tiền thì đọc còn nợ từ ghi chú đơn.** Ghi chú là tình trạng đến ngày cuối dữ liệu, nên số cho ngày sớm hơn không đáng tin.

## Pattern và đánh đổi

Quyết định 1 là **context re-injection**: nhắc lại thông tin quan trọng ngay gần chỗ model ra quyết định, vì model nhỏ dễ bị kết quả đọc dài lấn át. Đánh đổi là prompt dài thêm vài dòng mỗi câu. Quyết định 5 là **anti-corruption layer** ở mức nhỏ: helper dịch từ ngôn ngữ câu hỏi sang giá trị trong dữ liệu, nên model không phụ thuộc cách từng shop ghi. Đánh đổi là bảng alias phải giữ thủ công.

## Hệ quả

- `artifacts/norm` và `prompts/library.jsonl` đã sinh lại. Oracle train 1836 lên 1866, public 552 lên 566, không câu nào từ đúng thành sai.
- Công nợ `dev_014` (sổ nợ cộng sổ góp), trả góp, bảo hành, thu máy cũ vẫn chưa có helper.

## Đo sau khi áp dụng

EXP-20261105-02: test +271 (accuracy 0.807, coverage 0.980), public +502 (accuracy 0.754, coverage 0.990), so với +292 trước đó.
