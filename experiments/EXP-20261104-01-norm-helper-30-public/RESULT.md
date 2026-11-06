# RESULT

Run không hoàn tất. Trên 16 dòng có trong `answers.jsonl`: điểm -7, đúng 1, sai 8, trống 7, sau 61 phút.

Nguyên nhân đọc từ log:

| Nguyên nhân | Câu | Loại |
| --- | --- | --- |
| Gate `chưa đọc file` khớp nhầm chuỗi, chặn đường dẫn đúng | q_859861209455, q_99e67ed05dd8 | harness |
| final_code chỉ ghi literal, không print, lặp đến khi hỏng API; không có trần lượt thật | q_d857fdab9c0a (đã ra -5.94 ở Turn 1) | harness |
| `Shop` crash vì dev_014 không map cột `Ngày` | q_d08785ea5577, q_86a32a09633a | chuẩn hoá |
| Sổ sửa xe bị xếp thành `staff`, `lines` là None | q_4e280a1755de | chuẩn hoá |
| 429 và 5xx, `choices=None` giết cả run | q_a0046e6fede0, q_3f0d7d1b1eb1, q_cfa36137a14a, 10 câu chưa chạy | harness |
| Model tự viết pandas, so `month` với chuỗi, ra 0 | q_aacb2ba3f300, q_55cfcde4c03f, q_ca9e9c233325 | model, thiếu helper |

Các số trên không phải độ chính xác của agent vì run bị hỏng bởi lỗi harness.
