# RESULT — EXP-20261103-03-simple-analyze-conclude-10-random

Lệnh: `logs/02-run.cmd`, stdout `logs/02-run.log`. Log từng câu: `run/20261103-131605/<id>.log`; lời gọi API: `run/20261103-131605/api.jsonl`.

## Số đo, so với đáp án Claude (coi là đúng 100%)

| Metric | Giá trị |
| --- | --- |
| score_vs_claude | **−4 / 10** |
| right / wrong / blank / api_failed | 2 / 6 / 0 / 2 |
| turns_per_question | 3 (5 câu), 1 (2 câu dính lỗi API), 4, 5, 7 |
| code_failures | 4 lần exit khác 0, 3 trong đó ở câu Tết |
| input / output tokens | 342.101 / 12.609 |
| cost_usd | 0,019 |
| api_retries | 76 lần 429; 2 câu hết 10 lần thử lại |
| wall_minutes | 30,3 (chạy tuần tự) |
| latency mỗi lượt gọi | 18,2 s |

## Từng câu

| Câu | Model | Đúng | Kết quả | Nguyên nhân, trích từ nhận định trong log |
| --- | --- | --- | --- | --- |
| dev_004 tăng giảm 2/26 | −36,85 | −36,85 | ĐÚNG | |
| dev_014 doanh thu đầu năm | 4.959.714.000 | 4.959.714.000 | ĐÚNG | |
| dev_003 so cùng kỳ | −38,63 | −0,9 | SAI | Code cuối không lọc `status_norm`; lần chạy thử trước so với cả tháng trước |
| dev_011 bán chạy | Kính cường lực 9D | Cáp Type-C 1m | SAI | Chưa soi code |
| dev_003 Tết | 261.753.000 | 84.059.600 | SAI | Đoán Tết 2026 là 2026-01-01 đến 2026-01-31 (không có lịch âm trong sandbox) |
| dev_005 Nurofen | 46 | 120 | SAI | "Đếm số dòng" thay vì cộng số lượng |
| dev_014 trung bình đơn | 2.936.478,01 | 4.325.306 | SAI | Chưa soi code |
| dev_001 tháng nào | `'2'` | `2026-03` | SAI | Giá trị và kiểu đều sai |
| dev_004 tỉ lệ huỷ | — | 1,52 | LỖI API | 429 |
| dev_012 lượt bảo hành | — | 39 | LỖI API | 429 |

## Kết luận

- Giả thuyết "mọi câu ra đáp án": **sai** vì 2 câu lỗi 429; ngoài lỗi API thì 8/8 câu ra đáp án, không câu nào hết turn. "Khớp ít nhất 2/10": **đúng**, nhưng chỉ là mốc.
- 10 câu không còn mù: đã dùng ở đối chứng dương và 2 lần chạy thử. Đối chứng 7/7 cho thấy phần lớn câu sai là do logic của model, không do bảng sạch.
- **Không tái lập được**: temperature 0, cùng model, kết quả vẫn đổi giữa các lần. dev_012 ra 39 (đúng) ở lần chạy thử đầu, 1303 ở lần sau; dev_003 ra 7,11 rồi −38,16 rồi −38,63. Một lần chạy 10 câu không đủ để so hai cấu hình.
- Provider gemma có tools chỉ có một (DeepInfra) và đang giới hạn tốc độ nặng: 76 lần 429 kể cả khi chạy tuần tự. Với 1.000 câu thì đây là chặn thực tế.
