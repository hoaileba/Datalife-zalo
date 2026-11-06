# RULES

1. Khai manifest trước khi chạy. Không sửa `src/` trong lúc chạy.
2. `inputs/test_*` chỉ để đo, không dùng phát triển. Thư viện few-shot chỉ lấy từ `train/split/train_*`.
3. 100 câu public chưa từng xuất hiện ở input của EXP nào. Đọc log của chúng rồi thì chúng hết là holdout.
4. Đáp án tham chiếu không được đưa cho agent.
5. Train có 6 shop chưa dựng được `lines`; không loại khỏi mẫu, ghi rõ số câu thuộc các shop đó.
