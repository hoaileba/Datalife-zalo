# RULES

1. Không sửa `src/` và `prompts/`. Hai nhánh chỉ patch lúc chạy trong `code/replay.py`.
2. Nhánh `remind`: sau kết quả READ nhắc lại câu hỏi và ví dụ top-1.
3. Nhánh `neutral`: như `remind`, thêm thay ví dụ `revenue(...)` trong phần luồng làm việc của system prompt bằng `<hàm>(<kỳ>)`.
4. Mẫu chọn theo kết quả cũ nên không dùng số này làm ước lượng điểm toàn tập.
