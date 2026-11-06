# STEPS — EXP-20261101-01-openrouter-qwen-20-sample-v2

## 2026-11-01 — bước 1/3: mở
Đã làm:    copy mẫu 20 câu, groups, đáp án Claude, compare.py từ parent; snapshot src/ (73 test pass); config như parent, đổi batch_size → parallel_shops, thêm stuck_after
Kết quả:   Docker 28.0.4 sẵn sàng
Bước tiếp: bước 2 — chạy logs/03-run.cmd

## 2026-11-01 — bước 2/3: chạy (13:04 → 13:41, 37,1 phút)
Đã làm:    chạy logs/03-run.cmd, log logs/04-run.log
Kết quả:   10/10 shop stuck, 0 verified; 5,52M input + 0,35M output token ≈ $0,75; 0 lỗi API
Bước tiếp: bước 3 — so với Claude

## 2026-11-01 — bước 3/3: so sánh và đóng
Đã làm:    code/compare.py → out/comparison.{json,md}; đếm write_file vào script mỗi shop
Kết quả:   đồng ý 0/20; model không ghi script ở cả 10 shop; merge lấy cả file đáp án của shop chưa verify (đã sửa ở src/)
Bước tiếp: đóng. Đề xuất thực nghiệm kế: temperature 0.6 / top_p 0.95
