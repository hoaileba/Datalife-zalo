# RESULT — EXP-20261101-02-qwen-submit-context-10-random

Lệnh: `logs/02-run-{vi,en}.cmd`, chấm `logs/03-score.cmd`. Bảng từng câu: `out/comparison.md`.

## Số đo, so với đáp án Claude (coi là đúng 100%)

| Metric | vi | en |
| --- | --- | --- |
| score_vs_claude | −5 | −7 |
| right / wrong / blank | 0 / 5 / 5 | 0 / 7 / 3 |
| accepted_shops | 3/7 | 5/7 |
| submit_calls / rejections | 23 / 20 | 24 / 19 |
| latency mỗi turn (trung bình) | 42,6 s | 55,0 s |
| output token mỗi turn | 1.104 | 1.482 |
| input / output tokens | 3.201.209 / 152.300 | 1.379.262 / 111.151 |
| cost_usd | 0,42 | 0,19 |
| api_errors | 4 | 1 |
| tool_error_rate | 0,0441 | 0,0294 |

## Kết luận

- Giả thuyết "ít nhất 5/7 shop ACCEPTED ở mỗi nhánh": **đúng ở en (5/7), không kiểm được ở vi**. "Điểm dương ở ít nhất một nhánh": **sai**. "Hai nhánh lệch không quá 2 câu đúng": đúng (cùng 0).
- `submit` gỡ được nút chặn của v2 (0/10 shop → 5/7), nhưng 0/10 câu khớp Claude: `verified` chỉ là đúng format.
- **Kết quả nhánh vi không dùng để so được**: dev_005, 011, 012, 014 lỗi `APIConnectionError` lúc 05:01 UTC ngày 02/11 (máy mất mạng), 0 turn. dev_003 của nhánh en lỗi `APITimeoutError` cùng lúc.
- Tôi tính khoảng 28/37 lần `submit` bị từ chối (đo giữa chừng, lúc có 37) là lỗi dữ liệu thô: ngày tháng 13, tên sheet/cột 12, tiền là chuỗi 3. Đây là căn cứ của tầng chuẩn hoá `docs/06`.
- 97–99% output mỗi turn là reasoning (đo trên các turn đầu).

## Bài học

Lúc lần chuẩn hoá chạy song song: chuẩn hoá bị 429 ở 3 shop, nhánh vi có 5 lần retry 429. Việc hai bên tranh quota là giả thuyết, chưa kiểm. Thực nghiệm dài chạy qua đêm trên laptop thì mất mạng: phải có cách chạy tiếp shop `error`.
