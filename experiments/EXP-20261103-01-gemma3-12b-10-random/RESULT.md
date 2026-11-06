# RESULT — EXP-20261103-01-gemma3-12b-10-random

Lệnh: `logs/02-run-{vi,en}.cmd`, chấm `logs/03-score.cmd`. Bảng từng câu: `out/comparison.md`. Parent: EXP-20261101-02 (qwen3-14b, cùng harness và prompt, dữ liệu thô).

## Số đo, so với đáp án Claude (coi là đúng 100%)

| Metric | gemma vi | gemma en | qwen en (parent) |
| --- | --- | --- | --- |
| score_vs_claude | −8 | −3 | −7 |
| right / wrong / blank | 0 / 8 / 2 | 0 / 3 / 7 | 0 / 7 / 3 |
| accepted_shops | 5/7 | 2/7 | 5/7 |
| submit_calls / rejections | 21 / 16 | 28 / 26 | 24 / 19 |
| latency mỗi turn (trung bình) | 9,5 s | 13,7 s | 55,0 s |
| output token mỗi turn | 187 | 291 | 1.482 |
| input / output tokens | 1.742.669 / 18.560 | 1.529.249 / 26.152 | 1.379.262 / 111.151 |
| cost_usd | 0,09 | 0,08 | 0,19 |
| api_errors | 0 | 0 | 1 |
| tool_error_rate | 0,2661 | 0,1149 | 0,0294 |
| wall (giờ đầu → cuối) | ~9 phút | ~11 phút | — (lẫn lỗi mạng) |

## Kết luận

- Giả thuyết "nhanh hơn ít nhất 5 lần mỗi turn": **sai sít sao**, đo được 4,0–4,5 lần. "Khớp Claude ≤ 2/10": **đúng**, 0/10 cả hai nhánh.
- Điểm −3 của nhánh en **không có nghĩa tốt hơn**: 7 câu blank vì 5/7 shop `stuck`.
- Lỗi của gemma nghiêng về viết code: `NameError` 11, `IndentationError` 7, `SyntaxError` 1 — qwen gần như không có `IndentationError`. tool_error_rate cao hơn qwen 4–9 lần.
- Nhanh và rẻ hơn, nhưng cùng 0/10. Dữ liệu thô vẫn là chỗ tắc chung của cả hai model; chưa kết luận được model nào tốt hơn.

## Cố ý chưa làm

Tầng chuẩn hoá (chưa nối vào agent ở snapshot này). Thực nghiệm tiếp theo đo đúng biến đó.
