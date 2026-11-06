# STEPS

1. Lệnh sửa 6 shop bị Hoài từ chối nhưng đã ghi vào `src/datamate/shop.py` và `column_roles.py` lúc 14:40:40. Hoàn lại từ snapshot EXP-09 lúc 14:53, `diff` sạch, `artifacts/norm` không đổi.
2. Chia 5 tập 600 câu bằng `code/make_folds.py`. Dùng lại 679 câu từ EXP-07, 08, 09, cùng code. 6 câu lỗi mạng chạy lại.
3. Chạy lần lượt `code/run_all.sh`, 5 luồng, `nice -n 10`, từ 14:54.
4. Hoài yêu cầu tạm dừng để phân tích. Dừng chạy lúc đang ở tập 2.
5. Đọc 35 câu sai của `train_*` trên 24 shop, phân nhóm. Không đọc lỗi `test_*`.
6. Thử trong scratchpad, không sửa `src/`, bản vá ở `out/trial_fix.diff`: sổ không mã đơn oracle 101/101; hoá đơn tách hai bảng oracle 6/300 lên 141/300.
7. Đo luật kỳ ngoài dữ liệu trên `train_*`: 10 đúng, 0 báo nhầm. Tính tay `price_effect` khi quy đổi đủ các đơn vị lớn: 3/3 khớp gold.
