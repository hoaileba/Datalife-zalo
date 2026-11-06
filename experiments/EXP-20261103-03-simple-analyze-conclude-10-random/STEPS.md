# STEPS — EXP-20261103-03

## 2026-11-03T13:20 — bước 1/3: chuẩn bị
Đã làm:    snapshot code (94 test), inputs giống parent, copy mapping + PROFILE
Kết quả:   hai lần chạy thử trước đó (artifacts/simple-runs): 2/10 luồng 2 tool; 2/10 luồng 3 pha với 1 lỗi API 429
Bước tiếp: bước 2 — chạy tuần tự 10 câu

## 2026-11-03 — bước 2/3: chạy
Đã làm:    chạy tuần tự 10 câu, lệnh ở logs/02-run.cmd
Kết quả:   đúng 2, sai 6, lỗi API 2, điểm −4; 30,3 phút, $0,019, 76 lần 429
Bước tiếp: bước 3 — viết RESULT, cập nhật INDEX, FAILURES

## 2026-11-03 — bước 3/3: đóng
Đã làm:    RESULT.md, manifest closed, INDEX, FAILURES
Kết quả:   xong
Bước tiếp: chờ lệnh
