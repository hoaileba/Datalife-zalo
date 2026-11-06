# RESULT — EXP-20261031-01-openrouter-qwen-20-sample

Lệnh: `logs/03-run.cmd` (log `logs/04-run.log`), so sánh `logs/05-compare.cmd` (log `logs/05-compare.log`).
Log agent: `run/logs/runs/20261031-135313/` (`summary.md`, `shops/<shop>/trace.md`, `questions/<qid>.md`).

## Số đo (đúng các metric đã khai)

| Metric | Giá trị |
| --- | --- |
| agreement_with_claude_overall | **0/20 (0.00)** — 16 khác, 4 trống |
| agreement_with_claude_multi_table | 0/10 — 8 khác, 2 trống |
| agreement_with_claude_random | 0/10 — 8 khác, 2 trống |
| coverage | 0.80 (16/20 có dòng đáp án) |
| verified_shops | 6/10 theo harness lúc chạy — **nhưng 4/6 là giả**, xem dưới. Verified thật: 2/10 (dev_005, dev_006) |
| turns_per_shop | dev_001 20 · dev_003 35 · dev_004 0 (crash) · dev_005 15 · dev_006 22 · dev_008 60 · dev_011 26 · dev_012 60 · dev_013 16 · dev_014 34 |
| input_tokens | 5.933.206 |
| output_tokens | 396.053 |
| cost_usd | 0,807 (DeepInfra $0,12 / $0,24 per 1M) |
| api_errors | 0 (0 retry) |
| tool_error_rate | 6/322 = 0,0186 |

Ba số chuẩn: **điểm và accuracy không đo được** (public không có gold). Đồng ý với Claude (bản đạt 0,994 public) là 0/20.

## Lỗi harness lộ ra (đã sửa ở `src/`, bản trong `code/src/` là bản đã chạy, CÓ lỗi)

1. **Verifier nhận đáp án viết tay.** 4 shop (dev_001, dev_011, dev_013, dev_014) có script KHÔNG ghi file đáp án; model ghi
   file bằng `write_file` (vd dev_014 bước 28–34) với số bịa (12345, 54321, 67890). Verifier chạy lại script, script không
   đụng file → so trước/sau khớp → "verified". Sửa: Verifier dời file đáp án trước khi chạy lại và bắt script tạo lại;
   `write_file` từ chối ghi vào `out/answers/`. Test: `test_finish_rejects_answers_the_script_did_not_write`,
   `test_write_file_cannot_touch_answers`.
2. **dev_004 crash** vì model ghi file đáp án là một mảng JSON, `_changed_ids` gọi `.get` trên list. Sửa: dòng không phải
   object bị từ chối có thông báo. Test: `test_answers_written_as_json_array_are_rejected_not_crashed`.

## Hành vi của qwen3-14b (quan sát, 10 shop)

| Hành vi | Shop | Bằng chứng |
| --- | --- | --- |
| Bịa id câu hỏi `q1/q2/q3` thay vì đọc file câu hỏi | dev_004, dev_012 | dev_012: 11 lần finish bị từ chối cùng lý do "id not in this shop: q1" |
| Dùng id của shop khác | dev_008 | `q_06de4545fe25` |
| Viết tay file đáp án thay vì sinh từ script | dev_001, dev_008, dev_011, dev_013, dev_014 | `write_file` vào `out/answers/` |
| Lặp suy biến | dev_008 | bước 35–60: ghi cùng file 55 ký tự 25 lần |
| Gọi finish trước khi có script | 6/10 shop | summary.md, cột "finish bị từ chối" |
| Output bị cắt vì thinking ăn hết max_output_tokens | dev_005, dev_012 | finish_reason=length |
| Không bám đúng câu hỏi: trả `table` cho câu hỏi số lượt; trả "March 2026" cho câu hỏi tháng | dev_012, dev_001 | comparison.md |

## Kết luận

- Giả thuyết "tổng đồng ý < 80%": **đúng** (0%).
- Giả thuyết "multi_table thấp hơn random": **không kết luận được** (cả hai 0%).
- Với harness và prompt hiện tại, qwen3-14b **không dùng được** để trả lời: không câu nào khớp Claude, và phần lớn shop
  "xong" là nhờ lỗ hổng Verifier. Chi phí thấp ($0,81/20 câu) nhưng giá trị bằng 0.

## Việc còn treo

1. Chạy lại cùng 20 câu với `src/` đã sửa Verifier, để đo qwen3-14b khi KHÔNG còn đường tắt viết tay (một thực nghiệm mới, parent = thực nghiệm này).
2. Đề xuất chưa làm (chạm thiết kế): phát hiện vòng lặp tool call giống hệt; harness nạp sẵn danh sách id câu hỏi vào script mẫu; `fmt.answer_line` nhận kiểu số numpy; tăng `max_output_tokens` hoặc tắt thinking.
3. So một model mạnh hơn (vẫn < 15B hoặc không) trên cùng 20 câu, nếu luật thi cho phép.
