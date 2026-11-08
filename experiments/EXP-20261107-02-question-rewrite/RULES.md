# RULES

1. 100 câu public giống hệt EXP-20261107-01 (`random.Random(20261103).sample`).
2. Chấm bằng cách chấm gần hệ thống (`status` của final_score.py, coi mã và tên cùng đối tượng là đúng); bỏ trống chỉ khi `type` rỗng hoặc `abstain`.
3. Ví dụ trong prompt chuẩn hoá không lấy câu public. Danh sách từ ở luật 4 rút từ thống kê cả 4000 câu, nên public hơi lạc quan ở `o đờ`, `xi ô đi`.
4. Câu viết lại phải qua luật kiểm bằng code: số, kỳ hỏi, tên đã nối, đơn vị, cụm quyết định unanswerable. Sai thì agent dùng câu gốc.
5. Bốn lần chạy A–D chỉ khác prompt, chuẩn hoá và model. Không chạy full public trước khi anh review.
