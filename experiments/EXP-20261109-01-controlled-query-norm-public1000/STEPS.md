# Nhật ký EXP-20261109-01-controlled-query-norm-public1000

## 2026-11-09T15:37:15.228104+00:00 — bước 1/7
Đã làm: đọc AGENT.md, FAILURES.md, nguồn rewrite/pipeline; khai mục đích và metrics trước inference.
Kết quả: manifest open. docs/02-plan-kien-truc.md không có trong checkout; cấu hình VLLM_* chưa có trong env. Không dùng backend khác.
Bước tiếp: triển khai controlled edits, kiểm bằng synthetic fixtures, chụp source và chuẩn bị runner.

## 2026-11-09T15:53:54.490898+00:00 — bước 4/7
Đã làm: chạy smoke synthetic và một câu public không chấm gold
Kết quả: cache/agent có output; không chọn prompt bằng điểm smoke
Bước tiếp: full 1000 câu mới từ đầu, không ghép đáp án smoke

## 2026-11-09T15:54:19.113075+00:00 — bước 2/7
Đã làm: thêm question_normalize, CLI opt-in/cache riêng; kiểm synthetic và freeze source/input.
Kết quả: log01 có một assertion message thất bại dù ID bị chặn; log02/log04 có15 pass. Snapshot210 file, không symlink. Model inventory qua network được cấp quyền trả gemma-12b; URL/key chỉ ở env process.
Bước tiếp: smoke không chấm gold, sau đó full1000 mới từ snapshot.

## 2026-11-09T16:02:02.757928+00:00 — bước 5/7
Đã làm: bắt đầu full normalization trên 1000 câu
Kết quả: snapshot cố định; không tái dùng output smoke
Bước tiếp: agent 1000 câu sau normalization

## 2026-11-09T16:03:14.242356+00:00 — bước 5/7
Đã làm: lấy quyền mạng cho full run, bắt đầu lượt 1000 câu mới từ snapshot sau smoke.
Kết quả: process full đã thực thi, logs/08-full.log; server inventory đúng model gemma-12b. Khối bước2 phía trên ghi muộn sau smoke để bổ sung kết quả setup đã hoàn tất trước inference, không phải thứ tự thực thi; không biên tập nhật ký cũ.
Bước tiếp: theo dõi normalization rồi agent, không đổi prompt/source snapshot.

## 2026-11-09T16:16:56.528150+00:00 — bước 5/7
Đã làm: hoàn tất normalization 1000 câu
Kết quả: thời gian 893.763s; output out/analysis_normalize.jsonl
Bước tiếp: agent full 1000 từ snapshot
