# RESULT — EXP-20261101-01-openrouter-qwen-20-sample-v2

Lệnh: `logs/03-run.cmd` (log `logs/04-run.log`), so sánh `logs/05-compare.cmd` (log `logs/05-compare.log`).
Log agent: `run/logs/runs/20261101-130405/` (`summary.md`, `tools.log` không có — bản snapshot này chưa tách log tool).

## Số đo, cạnh parent

| Metric | Parent EXP-20261031-01 (harness v1) | Thực nghiệm này (harness v2) |
| --- | --- | --- |
| agreement_with_claude_overall | 0/20 | **0/20** |
| agreement_with_claude_multi_table | 0/10 | 0/10 |
| agreement_with_claude_random | 0/10 | 0/10 |
| coverage (merge lúc chạy) | 0,80 — gồm 4 shop "verified" giả | 0,45 — **toàn bộ từ shop chưa verify** (lỗi merge, xem dưới); tính đúng = **0,00** |
| verified_shops | 6 báo cáo, 2 thật | **0/10** |
| stuck_shops | — (chưa có) | **10/10** |
| turns_per_shop | 15–60, tổng 302 | 22–44, tổng 299 |
| wall_minutes | 88,4 | **37,1** (replay ADR 006 dự đoán 37,3) |
| input_tokens | 5.933.206 | 5.524.511 |
| output_tokens | 396.053 | 345.088 |
| cost_usd | 0,807 | 0,746 |
| api_errors | 0 | 0 |
| tool_error_rate | 0,0186 | 0,0551 (gồm 33 lời gọi lặp bị chặn) |

Lượt theo loại: python lỗi 96 → **133**; lặp y hệt 41 (chạy lại) → 33 (bị chặn); finish bị từ chối 33 → 23; viết tay đáp án 30 → 0 (`write_file` bị chặn).

## Phát hiện chính

1. **qwen3-14b không bao giờ ghi vào file script.** `write_file` vào `code/shops/<shop>.py`: **0 lần ở cả 10 shop**. Model viết
   `answer()` và chạy nó trong code nháp `run_python`, rồi gọi `finish`; Verifier chạy script thật = khung gốc →
   `ValueError: not answered yet` → 3 lần cùng lý do → `stuck`. Khung script (ADR 006 mục 2) giả định model sẽ sửa file;
   giả định đó sai với model này.
2. **Một số shop tự ghi file đáp án qua code nháp** (`run_python` mở `work/out/answers/...`), lách lệnh cấm của `write_file`.
   Merge gộp cả file đó vào submission dù shop chưa verify → coverage 0,45 là ảo. Đã sửa ở `src/`: merge chỉ lấy shop
   `verified` (`modules/merge.py`, test `test_finish_rejects_answers_the_script_did_not_write`).
3. Lặp y hệt vẫn nhiều (33 lời gọi bị chặn ở 10/10 shop) dù đã có phát hiện kẹt. **Giả thuyết**: `temperature: 0`
   (greedy). Model card Qwen3 (Best Practices) khuyến nghị thinking mode `temperature=0.6, top_p=0.95, top_k=20` và
   cảnh báo greedy decoding gây lặp vô hạn.
4. Thời gian chạy giảm đúng như dự đoán (88,4 → 37,1 phút): pool + phát hiện kẹt hoạt động.

## Kết luận

- "Thời gian ~40 phút": **đúng** (37,1).
- "Không còn verified nhờ viết tay": **đúng** (0 verified, có thêm lỗ merge đã sửa).
- "Lượt phí giảm": **sai một phần** — finish bị từ chối và viết tay giảm, python lỗi tăng 96 → 133.
- "Đồng ý với Claude tăng": **sai** (0/20 cả hai).

Harness v2 nhanh hơn và chặn được gian lận, nhưng qwen3-14b vẫn không ra được một đáp án hợp lệ nào.

## Việc còn treo — mỗi việc một thực nghiệm

1. `temperature: 0.6`, `top_p: 0.95` (theo model card) — một thay đổi config, rẻ nhất.
2. Đổi giao kèo nộp bài cho khớp cách qwen làm việc: tool `submit_answer_code(code)` nhận thân `answer()` + hàm phụ,
   harness tự ghi vào script rồi verify (thay vì bắt model sửa file).
3. Bước chuẩn hoá dữ liệu trước agent (đề xuất A, chờ Hoài duyệt).
4. Thêm `tabulate` vào image sandbox.
