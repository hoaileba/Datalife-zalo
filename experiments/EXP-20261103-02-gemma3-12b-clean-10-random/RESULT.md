# RESULT — EXP-20261103-02-gemma3-12b-clean-10-random

**Bỏ dở, không có số đo.** Hoài yêu cầu bỏ harness này giữa chừng; tôi dừng 2 nhánh bằng `pkill` khi mới có 3 shop kết thúc (đều `stuck`). `out/comparison.*` nếu có chỉ là của phần chạy dở, không dùng.

## Đo được trước khi dừng

- Đối chứng dương (`logs/01-control.log`): 7/7 câu khớp Claude bằng công thức trên bảng sạch, sau khi sửa 6 lỗi tầng chuẩn hoá. Đã sửa dựa trên chính các câu này nên chỉ chứng minh môi trường có thể ra đáp án đúng.
- `submit` bị từ chối 16 lần, được nhận 0 lần: `IndentationError` 9, `ValueError` 3, `NameError` 3, `SyntaxError` 1. **Lỗi ngày tháng, tên cột, tên sheet: 0**.
- dev_003 nhánh vi tính đúng -0.9 ở turn 2 rồi hỏng khi gói vào khuôn hàm `answer`.

## Kết luận

Giả thuyết trong manifest không kiểm được. Bảng sạch hết nhóm lỗi dữ liệu; chỗ tắc chuyển sang khuôn hàm `answer(question, clock)`. Dẫn tới luồng `simple.py` ở EXP-20261103-03.
