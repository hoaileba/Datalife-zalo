# RESULT — EXP-20261103-04-simple-train-test-20

Lệnh: `logs/02-run.cmd`, stdout `logs/02-run.log`. Log từng câu: `run/20261103-144706/<id>.log`. Đối chứng: `logs/01-control.log`.

## Số đo, trên đáp án thật của ban tổ chức

| Metric | Giá trị |
| --- | --- |
| score | **−3 / 20** |
| right / wrong / blank / api_failed | 5 / 8 / 7 / 0 |
| accuracy (trên số câu đã trả lời) | 5/13 = 0,38 |
| coverage | 13/20 = 0,65 |
| code_failures | 68 lần exit khác 0 |
| cặp code liên tiếp y hệt | **55/77** |
| input / output tokens | 1.389.689 / 26.512 |
| cost_usd | 0,073 |
| api_retries | 79 lần 429; 0 câu lỗi |
| wall_minutes | 36,3 (tuần tự) |

Đối chứng dương trên `train_*`: doanh thu tháng khớp đáp án thật **60/60**, 29 shop.

## Nguyên nhân gốc đã phát lại được

7/7 câu trống là do model gửi lại nguyên đoạn code sau khi lỗi. Phát lại đúng hội thoại `q_9ad226a1d120`, gửi hai kiểu kết quả (n=2 mỗi kiểu):

| Model nhận | Kết quả |
| --- | --- |
| Traceback đầy đủ, 861 ký tự | Lặp `clean/sales.csv` 2/2 |
| Chỉ dòng lỗi cuối | Sửa đúng tên bảng 2/2 |

Giả thuyết ban đầu "provider làm mất kết quả tool" đã bị bác: model đọc được mã bí mật trong tool result.

Yếu tố của tôi cộng thêm: mô tả tool ghi ví dụ `sales.csv` nhưng bảng một nguồn lại mang tên khác (`sales_donhang_chitiet_sheet1.csv`).

## Câu sai đã soi code

- `q_930302e5889f`: lọc `status == 'huỷ'` trên cột gốc, không dùng `status_norm`; chia theo dòng → 0%.
- `q_0f54ed0c815f`: code tự in "File không tồn tại", cổng `conclude` coi là đã phân tích, trả `unanswerable`.
- `q_22184c4bfb6b`: hỏi kẹo Alpenliebe, code lọc `Bánh Oreo 133g`, và lấy `line_amount` thay vì giá.
- `q_311687ae2c21`: lấy ngày **lớn nhất** trong kỳ thay vì ngày có doanh thu cao nhất.
- `q_ae3ab239e10c`: dùng `order_total − order_discount`, không lọc `is_revenue`.
- `q_b1a26804c63b`: không lọc `is_revenue`.
- `q_83878331afed`, `q_e5e5eb7b1d8e`: ra 0,0, chưa soi hết.

## Kết luận

- Giả thuyết "đúng ít nhất 6/20": **sai**, 5/20. "Mọi câu ra đáp án": **sai**, 7 trống.
- Môi trường đủ cho doanh thu tháng (60/60); chỗ yếu là vòng sửa lỗi và logic của model.
- 2 câu trống có đáp án `unanswerable`, tức mất điểm đúng chỉ vì lặp lỗi.
- **Log `test_*` đã được dùng để tìm lỗi**: lần đo sau của harness đã sửa không còn mù trên 20 câu này.
