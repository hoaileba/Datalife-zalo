# RESULT

So với bản Claude, không phải gold thật. Mẫu chọn theo kết quả cũ, không phải ước lượng điểm toàn tập.

| Nhóm, nhánh | n | Score | Đúng | Sai | Trống | Accuracy | Coverage | Bỏ ví dụ |
|---|---|---|---|---|---|---|---|---|
| Bỏ ví dụ, gốc EXP-05 | 96 | -69 | 13 | 82 | 1 | 0.137 | 0.990 | 96 |
| Bỏ ví dụ, remind | 96 | +25 | 60 | 35 | 1 | 0.632 | 0.990 | 23 |
| Bỏ ví dụ, neutral | 96 | +18 | 56 | 38 | 2 | 0.596 | 0.979 | 22 |
| Đối chứng, gốc EXP-05 | 96 | +47 | 70 | 23 | 3 | 0.753 | 0.969 | 0 |
| Đối chứng, remind | 96 | +46 | 71 | 25 | 0 | 0.740 | 1.000 | 1 |
| Đối chứng, neutral | 96 | +50 | 72 | 22 | 2 | 0.766 | 0.979 | 0 |

Kết luận: giả thuyết nhắc lại sau READ đúng trên mẫu này. Đổi ví dụ `revenue` trong system prompt không có thêm tác dụng rõ ràng.

Phân loại 362 câu ở `out/buckets.json`, gán bằng luật regex, chỉ kiểm tay một phần. Câu lệnh tính lại ở `code/an7.py`, `code/an9.py`.

Việc còn treo: áp nhánh remind và các sửa chuẩn hoá vào `src/` sau khi Hoài duyệt, đo lại trên `test_*` và đủ 1000 câu public.
