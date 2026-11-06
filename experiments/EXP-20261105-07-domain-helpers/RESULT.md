# RESULT

Test so với gold. Public so với bản Claude, không phải gold thật, chưa có điểm hệ thống cho bản này.

| Số đo | Test | Public, chấm chặt | Public, mã và tên cùng đối tượng là đúng |
|---|---|---|---|
| score | +282 | +789 | +815 |
| PA | 0.627 | 0.789 | 0.815 |
| right | 364 | 894 | 907 |
| wrong | 82 | 105 | 92 |
| blank | 4 | 1 | 1 |
| accuracy | 0.816 | 0.895 | 0.908 |
| coverage | 0.991 | 0.999 | 0.999 |

| Số đo khác | Kết quả |
|---|---|
| oracle_train_right | 1866/2550, không đổi |
| oracle_public_right | 567/1000, trước 566 |
| domain_formula_match | 131/133 tham chiếu public; giao hàng 10/10, lô 4/5, hết hàng 1/1 theo gold train |
| cross_shop_match | cùng helper điện thoại đúng ở cả `dev_011` và `dev_014` |
| wall_minutes | khoảng 51 phút public, thêm chạy lại câu thiếu |

## So với trước

| | PA | Đúng | Sai | Trống |
|---|---|---|---|---|
| Public, bản nộp 0.524 (local 0.528) | 0.528 | 758 | 230 | 12 |
| Public, bản này | 0.815 | 907 | 92 | 1 |
| Test 24 shop, EXP-02 | 0.891 | 354 | 19 | 3 |
| Test 24 shop, bản này | 0.915 | 360 | 16 | 0 |
| Test 6 shop thiếu `lines` | -0.838 | 4 | 66 | 4 |

Public: 167 câu thành đúng, 18 câu từ đúng thành sai hoặc trống.

## Kết luận

Giả thuyết đúng, PA public trong khoảng dự kiến 0.70 đến 0.85. Test không giảm. Public đã bị dùng để phát triển nên lạc quan; 24 shop test không có shop điện thoại, sửa xe, mẹ và bé nên không kiểm được 3 ngành đó. Milestone trong `docs/02`: không kiểm trong thí nghiệm này.

## Việc còn treo

1. 6 shop train không dựng được `lines`: 74 câu test, -62 điểm.
2. 16 câu đáng lẽ `unanswerable` vẫn trả lời.
3. `dev_012` PA 0.64, `dev_003` 0.705, `dev_006` 0.73 thấp nhất.
4. Nộp để lấy điểm thật.
