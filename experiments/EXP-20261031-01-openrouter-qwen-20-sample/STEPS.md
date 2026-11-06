# STEPS — EXP-20261031-01-openrouter-qwen-20-sample

## 2026-10-31 — bước 1/5: bốc mẫu
Đã làm:    viết code/sample.py (seed 20261031), lệnh ở logs/01-sample.cmd
Kết quả:   lần bốc đầu sai: từ khoá "ton" khớp nhầm "tong" (tổng) → câu "T7/2025 tong dthu" vào nhóm nhiều bảng.
           Sửa từ khoá ("ton kho", " ton ", "lai gop"...) rồi bốc lại TRƯỚC khi chạy bất kỳ model nào.
           229 ứng viên nhiều bảng, mẫu 20 câu / 10 shop
Bước tiếp: bước 2 — config + điều kiện chạy (executor, base URL)

## 2026-10-31 — bước 2/5: điều kiện chạy
Đã làm:    kiểm .env (chỉ đọc tên biến) và Docker
Kết quả:   .env có OPENROUTER_KEY, không có base URL. Docker daemon không trả lời (timeout 15s).
           Hai điểm này chạm luật an toàn của Hoài → hỏi trước khi chạy
Bước tiếp: chờ Hoài chọn executor và cách cấp base URL

## 2026-10-31 — bước 3/5: chuẩn bị chạy
Đã làm:    Hoài chọn Docker và bảo tôi tự thêm OPENROUTER_BASE_URL vào .env (lệnh trực tiếp). Build image datamate-sandbox:0.1 (logs/02-docker-build.*).
           Kiểm DockerExecutor bằng script thử: /data chỉ lộ calendar.csv, data, rulebook.md; không thấy experiments/; ghi /data bị chặn; mạng bị chặn; ghi /work được
Kết quả:   executor docker hoạt động. Chạy với DATAMATE_ENV=prod để shop lỗi không dừng cả lượt (lỗi vẫn ghi status=error)
Bước tiếp: bước 4 — chạy, lệnh ở logs/03-run.cmd

## 2026-10-31 — bước 4/5: DỪNG theo lệnh Hoài (13:41 +07, sau ~4,5 phút)
Đã làm:    dừng tiến trình pipeline và monitor; kill 1 container datamate-* còn chạy
Kết quả:   batch 1 dở dang, chưa shop nào verified, chưa có state.json.
           47 lời gọi API (dev_001 16, dev_003 9, dev_004 22): 782.000 input + 43.064 output token ≈ $0,10.
           0 api_error, 0 retry. 48 tool call, 7 tool call lỗi.
           dev_004 gọi finish 2 lần, đều bị Verifier từ chối: lần 1 chưa có script + notes;
           lần 2 percent ghi dạng chuỗi và thiếu 3/3 id
Bước tiếp: chờ lệnh Hoài. Chạy lại cùng lệnh logs/03-run.cmd thì 3 shop này làm lại từ đầu

## 2026-10-31 — ghi chú: harness đổi phần log sau khi dừng
Đã làm:    theo yêu cầu Hoài, src/ thêm log mỗi lần chạy (logs/runs/<thời điểm>/) và log từng câu hỏi
           (input → process → output); bỏ <shop>-transcript.jsonl. Hành vi agent không đổi (65/65 test)
Kết quả:   code/src trong thư mục này là bản CŨ (trước thay đổi log)
Bước tiếp: trước khi chạy lại, snapshot lại src/ vào code/src và ghi rõ ở đây

## 2026-10-31 — bước 4/5 (lần 2): chạy lại 20 câu theo lệnh Hoài
Đã làm:    snapshot lại src/ vào code/src (bản có log từng lần chạy, trace.md, summary.md; hành vi agent không đổi).
           Chuyển kết quả dở của lần 1 sang run-aborted-20261031-1336/ (không xoá), để agent mới không thấy
           script/đáp án dở của dev_004 trong work/
Kết quả:   run/ trống, chạy lại cùng lệnh logs/03-run.cmd; log lần chạy ở run/logs/runs/<thời điểm>/
Bước tiếp: chờ chạy xong, rồi bước 5 — so với Claude

## 2026-10-31 — bước 5/5: so sánh và đóng
Đã làm:    chạy xong 10 shop (logs/04-run.log), so với Claude (code/compare.py → out/comparison.{json,md})
Kết quả:   đồng ý 0/20; 5,93M input + 0,40M output token ≈ $0,81. Phát hiện Verifier nhận đáp án viết tay
           (4/6 shop "verified" là giả) — đã sửa ở src/, chi tiết RESULT.md
Bước tiếp: đóng thực nghiệm. Chạy lại phải là thực nghiệm mới
