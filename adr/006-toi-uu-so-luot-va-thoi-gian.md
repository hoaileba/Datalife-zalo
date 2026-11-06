# ADR 006 — Giảm lượt và thời gian chạy: pool thay batch, khung script, đường dẫn chung, phát hiện kẹt

Ngày: 2026-11-01 · Trạng thái: đã làm theo lệnh Hoài ("tối ưu lại số lượt"), chờ duyệt · Liên quan: ADR 004, EXP-20261031-01

## Bối cảnh (đo trên EXP-20261031-01, 10 shop, qwen3-14b)

- 88,4 phút. Batch 3 shop chờ shop chậm nhất: batch 1 = 27 phút (dev_003), batch 3 = 33 phút (dev_012), trong khi 7/10 shop xong < 13 phút.
- 209/302 lượt là lượt phí: python lỗi 96, gọi y hệt bước trước 41, finish bị từ chối 33, viết tay đáp án 30.
- Python lỗi hay gặp: `KeyError 'Ngày'` 15, `NameError os` 14 (prompt bắt đọc `os.environ`), `FileNotFoundError 'data/data/...'` 11 (model dùng đường dẫn tool trong script), numpy `int64` bị `fmt` từ chối 4.

## Quyết định

| # | Thay đổi | Ở đâu |
| --- | --- | --- |
| 1 | **Pool** `parallel_shops` thay `batch_size`: shop xong thì shop kế vào ngay; xếp shop nhiều câu trước (LPT); kiểm ngân sách trước mỗi shop | `pipelines/run.py` |
| 2 | **Khung script** harness ghi sẵn: đọc đúng file câu hỏi, hằng `QUESTIONS` liệt kê id thật, `main()` ghi đáp án; model chỉ viết `answer()` | `prompts/script_template.py.txt`, `prompts.script_skeleton` |
| 3 | **Một hệ đường dẫn**: script chạy trong thư mục có sẵn `data/` và `work/` như tool (docker `/sandbox`, local thư mục tạm có symlink) | `modules/executor.py`, `prompts/system.md` |
| 4 | **Phát hiện kẹt**: gọi y hệt lời gọi ngay trước thì không chạy, trả lỗi; lặp `stuck_after` lần, hoặc `finish` bị từ chối cùng lý do `stuck_after` lần → status `stuck` | `modules/agent.py` |
| 5 | `fmt.answer_line` đổi số numpy và tuple sang kiểu JSON | `datamate/fmt.py` |
| 6 | Tuỳ chọn `model.reasoning: false` (tắt thinking qua OpenRouter `reasoning.enabled`). Mặc định không gửi | `connectors/openrouter.py` |

## Đánh đổi kinh điển

- (1) là **work-stealing / list scheduling** thay cho **bulk-synchronous batch**: batch có rào chắn nên mỗi batch tốn bằng shop chậm nhất. LPT (Longest Processing Time first) là heuristic kinh điển giảm makespan; ở đây số câu chỉ là proxy cho độ dài.
- (2) là **template method**: phần bất biến (đọc câu hỏi, ghi file đáp án) thuộc harness, phần biến thiên (tính) thuộc model. Giá: model nhỏ có thể sửa `main()`; Verifier vẫn chặn vì bắt script tự tạo lại file đáp án.
- (4) là **circuit breaker** cho agent: dừng sớm một tiến trình đã chứng tỏ không tiến triển, đổi lấy rủi ro dừng nhầm một shop sắp xong. Ngưỡng 3 là chọn tay, chưa tune.
- (6) đổi chất lượng lấy tốc độ; **chưa đo**, nên không bật mặc định.

## Số đo (replay log EXP-20261031-01, không gọi model)

| Cách chạy | Phút |
| --- | --- |
| batch 3 (đã chạy) | 88,4 — replay ra đúng 88,4 thực đo |
| pool 3 | 60,6 |
| pool 3 + phát hiện kẹt | 37,3 (dev_008 dừng ở bước 20 thay vì 60, dev_012 ở bước 29) |
| pool 5 + phát hiện kẹt | 27,4 (chặn dưới = dev_003 27,4) |

(2), (3), (5) đổi **hành vi model**, replay không đo được: là giả thuyết, cần chạy lại.
