# STEPS — EXP-20261103-02

## 2026-11-03 — bước 1/4: chuẩn bị
Đã làm:    snapshot code (86 test pass), config 2 nhánh, inputs giống parent
Kết quả:   chờ normalize-v3 xong
Bước tiếp: bước 2 — đối chứng dương trên bảng sạch, rồi chạy

## 2026-11-03 — bước 2/4: đối chứng dương
Đã làm:    tính 7/10 câu bằng công thức trên bảng sạch (code/control.py, logs/01-control.log). Lần đầu 4/7; sửa 6 lỗi tầng chuẩn hoá (status từ Ghi chú, Không giao được → huỷ, Đã giao → hoàn thành, status chỉ cho bảng sales, cột chữ không nhận toàn số, mở rộng tên tắt) rồi chuẩn hoá lại (normalize-v4)
Kết quả:   7/7 khớp Claude. Đã sửa dựa trên chính các câu này: 10 câu không còn mù, điểm lần này lạc quan
           Còn lỗi ngoài mẫu: dev_008 note ← Bàn; dev_006, dev_010 bảng dòng hàng không có status_norm; dev_013 chưa giao → huỷ
Bước tiếp: bước 3 — chạy 2 nhánh gemma
