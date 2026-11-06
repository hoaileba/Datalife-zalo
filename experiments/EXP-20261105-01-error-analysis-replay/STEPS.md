# STEPS

1. Ghép đáp án, tham chiếu, log; chạy oracle trên 1000 câu public: 552 đúng. Trong 346 câu model sai, oracle đúng 81.
2. So hàm đầu tiên với ví dụ top-1: 96 câu gọi `revenue` trái ví dụ, 82 sai.
3. Đọc bảng chuẩn hoá: phát hiện regex `SUBTOTAL` xoá khách họ Tống, `customer_group` dev_003 sai cột. Tính lại khớp 4421000 và 39571500.
4. Tính lại 25 câu mẫu bằng helper: 14 khớp. `purchase_minus_sold` chưa quy đơn vị nhập; alias thanh toán, nhân viên lỗi; dev_008 đọc `note` ra 15 khách nợ, khớp.
5. Phát lại 192 câu, hai nhánh, chạy `code/replay.py`, không sửa `src/`. Không có lỗi API.
6. Chấm bằng `code/score_replay.py`, kết quả ở `out/replay_score.txt`.
