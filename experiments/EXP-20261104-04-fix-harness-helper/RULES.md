# RULES

1. Khai manifest trước khi chạy. Không sửa `src/` trong lúc chạy.
2. Chỉ `public_new` và `test_same` được dùng để kết luận. `regression` đã bị đọc log nên chỉ để kiểm hồi quy.
3. Thư viện few-shot chỉ lấy từ `train/split/train_*`.
4. Đáp án tham chiếu không đưa cho agent.

Lệch quy tắc 1: lúc 22:53 sửa `openrouter_client` (stream, giới hạn 180s mỗi câu trả lời) vì `q_bdbe8ca608ce` treo hơn 40 phút. Public đã có 99/100 đáp án bằng code cũ; test và regression chạy bằng code mới. Không đổi logic chấm hay helper.
