# RESULT — EXP-20261103-05-simple-short-error-train-20

Lệnh: `logs/02-run.cmd`, stdout `logs/02-run.log`. Log và hội thoại từng câu: `run/20261103-152729/<id>.log`, `<id>.conversation.json`.

## Số đo, trên đáp án thật, cạnh parent (khác bộ câu)

| Metric | Parent EXP-04 (traceback đầy đủ) | Thực nghiệm này (dòng lỗi cuối) |
| --- | --- | --- |
| score | −3/20 | **−7/20** |
| right / wrong / blank | 5 / 8 / 7 | 5 / 12 / 3 |
| accuracy | 0,38 | 0,29 |
| coverage | 0,65 | 0,85 |
| cặp code liên tiếp y hệt | 55/77 (71%) | **33/63 (52%)**, gồm cả lặp do cổng measure_column chặn 7 lần |
| code_failures | 68 | **36** |
| lượt gọi model | 131 | 110 |
| cost_usd | 0,073 | 0,056 |
| api_retries | 79 | 80, 0 câu lỗi |
| wall_minutes | 36,3 | 32,9 |

## Kết luận

- Giả thuyết: tỉ lệ lặp giảm (71% → 52%), câu trống giảm (7 → 3): **đúng**. Điểm không so trực tiếp được vì khác 20 câu.
- Điểm tệ hơn −3 không đủ để nói dòng lỗi ngắn gây hại: các câu trống trước đây (0 điểm) giờ ra đáp án, mà đáp án sai bị −1. Với gemma, trả lời thêm hiện lỗ: accuracy 0,29 < 0,5, EV mỗi câu trả lời âm.
- Vẫn lặp: `NameError: nrows` 14 lần, `nunique_items` 5 lần. Cổng measure_column chặn code không chạy: 7 lần trên 3 câu, 1 câu hết turn; đã sửa ở `src/`, snapshot này chưa có.
- Câu đúng: doanh thu theo kỳ, doanh thu một mặt hàng, số lượng, tăng giảm %. Câu sai gặp ở: ca chiều, tuần trước, nợ, tồn kho, đếm theo điều kiện. Chưa đọc hết code từng câu sai.
