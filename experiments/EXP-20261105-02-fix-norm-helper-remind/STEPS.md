# STEPS

1. Sửa `SUBTOTAL`, vai trò nhóm khách, `_conversions`, thêm `purchase_quantity`, alias bộ lọc, `_split_addons`, `_note_left`. Kiểm `code/verify_cases.py`: 31/31 khớp tham chiếu.
2. Chuẩn hoá lại ra thư mục tạm, so số dòng: chỉ tăng. Oracle train 1836 lên 1866, mất 0. Oracle public 552 lên 566, mất 0. Thay `artifacts/norm`.
3. Dựng lại `prompts/library.jsonl`: 952 lên 967 ví dụ, 53 lên 54 intent.
4. Thêm nhắc lại sau READ vào `agent.py`, tạo prompt v8. Smoke một câu `test_*` q_00a6e23cbacf, thấy dòng trả về `unanswerable`, không đọc tiếp log.
5. Đo test và public từ 10:10, xem `logs/run.cmd`.
6. Đo xong: test 10:08 đến 10:52, public 10:08 đến 11:05. Không có lỗi API. Chấm bằng `code/final_score.py`, kết quả ở `out/final_score.txt`.
7. Tách 6 shop `lines` rỗng trên test: 74 câu, 2 đúng, 66 sai, 6 trống; 24 shop còn lại: 376 câu, 354 đúng, 19 sai, 3 trống.
8. Tạo `out/submission.jsonl` bằng `code/make_submission.py`, chỉ kiểm format, không dùng tham chiếu: 10 câu trống và 2 câu sai format thành `abstain`, 9 câu `unanswerable` thiếu lý do được ghi lý do chung.
