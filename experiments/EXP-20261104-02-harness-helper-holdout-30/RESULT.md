# RESULT

Bỏ dở theo quyết định của agent, chấm được 10/30 câu. Số dưới đây không đại diện cho 30 câu đã khai.

| Số đo | Giá trị |
|---|---|
| score_vs_claude | -3/10 |
| right / wrong / blank | 3 / 6 / 1 |
| accuracy / coverage | 0.33 / 0.90 |
| wall_minutes | khoảng 78 cho 10 câu |

Giả thuyết trong manifest (score dương, coverage trên 0.8, phần lớn câu gọi helper): sai về score và helper, đúng về coverage trên mẫu 10 câu.

Phân loại 6 câu sai:

| Câu | Model làm gì | Helper one-liner | Lỗi thuộc về |
|---|---|---|---|
| q_4263ec258265 | đoán file sales.csv, bỏ cuộc | 553626, khớp | model + thông báo lỗi thiếu danh sách file |
| q_7f61dbb4d934 | lọc theo dòng thay vì đơn | 1210, khớp | model + `orders` thiếu year/month |
| q_e9eeeaa6cb03 | quên lọc tháng | 171, khớp (sau khi có `customer_count`) | model + thiếu helper |
| q_b342fe1e1211 | so `month == '4'`, rỗng, bỏ cuộc | 'Đạt', reference 'Hà Loan Đạt' | model + thiếu gộp tên thợ |
| q_54bbf080f0cd | gọi helper đúng | hoà 301/301, tie-break sai | helper: rulebook §9 xếp theo mã |
| q_dd2362109dd4 | đoán cột 'Ngày áp dụng' | chưa có helper | thiếu helper hiệu ứng tăng giá |

Kết luận đã đo: tool_choice ép vào endpoint có tools là nguyên nhân chính của độ chậm. Không có tools thì 10/10 request thành công.
