# RULES

1. Chỉ đổi: luật kiểm câu viết lại (ADR 011), cổng không trả lời được theo dữ liệu (ADR 012), hợp đồng dạng đáp án (ADR 013), loại câu đang hỏi khỏi thư viện ví dụ.
2. Thử 100 câu public trước; có lỗi code thì sửa trước khi chạy 1000.
3. 1000 câu train_* chọn bằng `random.Random(20261107).sample` trong 1397 câu chưa chạy; câu đang hỏi bị loại khỏi thư viện ví dụ.
4. Chấm public bằng cách chấm gần hệ thống; train chấm theo gold cùng cách.
