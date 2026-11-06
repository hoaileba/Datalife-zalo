# RESULT

Public so với bản Claude (chưa có điểm hệ thống cho bản này). Test so với gold.
Số public, test là số **ghép**: chỉ chạy lại câu có prompt user đổi hoặc thuộc shop có `lines` đổi (public 148, test 83); câu khác dùng lại đáp án EXP-20261105-07.

| Số đo | Trước | Sau |
|---|---|---|
| oracle_train_right | 2187/3000 | 2201/3000 |
| oracle_public_right | 567/1000 | 570/1000 |
| oracle_regressions | | 0 train, 0 public |
| probe_cases_right (helper gọi đúng tham số) | | 24/24 nhóm F, E khớp tham chiếu |
| pa_public | 0.815 (907 / 92 / 1) | 0.845 (922 / 77 / 1) |
| score_test | +282 (364 / 82 / 4) | +290 (368 / 78 / 4) |
| accuracy public / test | 0.908 / 0.816 | 0.923 / 0.825 |
| coverage public / test | 0.999 / 0.991 | 0.999 / 0.991 |

Public chạy lại: 16 câu thành đúng, 1 câu từ đúng thành sai. Test chạy lại: 4 thành đúng, 0 thành sai.

## Câu từ đúng thành sai

`q_bfbe25641230` (dev_003, "khach tra bot no mua chiu"): bản cũ đúng nhờ bắt nhầm nhóm `'trà'` từ "trả", làm câu đã che tên khác đi và TF-IDF chọn ví dụ `debt_repaid`. Bỏ lỗi bắt nhầm thì top-1 thành ví dụ `[debt_added, debt_repaid]`, model chép theo. Thuộc nhóm lỗi D (chép ví dụ top-1), không hoàn lại bản sửa.

## Sự cố trong lúc chạy

Lần chạy đầu: 89/148 câu public và 83/83 câu test lỗi `APIConnectionError`; chạy lại riêng các câu đó, 0 lỗi (logs/05-*). Script chấm lần đầu đọc nhầm thư mục EXP-07 vì `exec` gán đè biến `E`; đã đổi tên biến, số trên là sau khi sửa.

## Kết luận

Giả thuyết đúng hướng, vượt mức dự kiến: PA public local 0.845 (dự kiến khoảng 0.84), test không giảm (+8). Oracle không có câu nào từ đúng thành sai. Sửa quy đổi nhiều đơn vị lớn cũng sửa 14 câu train ở biz_102, 103, 121, 122.

## Việc còn treo

1. Chạy đủ 1000 câu public một lần để có số không ghép và đo độ dao động của model.
2. Nộp `out/submission.jsonl` để lấy điểm hệ thống (anh quyết).
3. Bước 2–4 (chặn `unanswerable`, hợp đồng đáp án, chọn ví dụ theo hợp đồng) chạm thiết kế, chờ duyệt.
