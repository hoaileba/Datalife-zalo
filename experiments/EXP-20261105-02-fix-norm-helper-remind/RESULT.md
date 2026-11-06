# RESULT

Test so với gold. Public so với bản Claude, không phải gold thật.

| Số đo | Test | Public |
|---|---|---|
| score | +271 | +502 |
| right | 356 | 746 |
| wrong | 85 | 244 |
| blank | 9 | 10 |
| accuracy | 0.807 | 0.754 |
| coverage | 0.980 | 0.990 |
| score_untouched | | +359 trên 721 câu |
| oracle_train_right | 1866/2550 (trước 1836) | |
| oracle_public_right | | 566/1000 (trước 552) |
| wall_minutes | 44 | 57 |

File nộp sau khi kiểm format: +504, đúng 746, sai 242, trống 12, accuracy 0.755, coverage 0.988.

## So với trước

| | Điểm | Đúng | Sai | Trống | Accuracy | Coverage |
|---|---|---|---|---|---|---|
| Public, EXP-05 | +292 | 638 | 346 | 16 | 0.648 | 0.984 |
| Public, bản này | +502 | 746 | 244 | 10 | 0.754 | 0.990 |
| 100 câu test, EXP-03 | +44 | 72 | 28 | 0 | 0.720 | 1.000 |
| 100 câu test, bản này | +64 | 81 | 17 | 2 | 0.827 | 0.980 |

Public: 132 câu thành đúng, 24 câu từ đúng thành sai hoặc trống.

## Kết luận

Giả thuyết đúng, điểm public vượt khoảng dự kiến +380 đến +430. Milestone trong `docs/02`: không kiểm trong thí nghiệm này.

## Việc còn treo

1. 6 shop `lines` rỗng trên train: biz_106, 107, 109, 113, 124, 126. Trên test: 74 câu, -64 điểm.
2. `dev_014` -22 và `dev_012` -1 không đổi: trả góp, bảo hành, thu máy cũ, dịch vụ sửa xe chưa có helper.
3. Luật READ lượt đầu bị lọt ở 3 log: nộp FINAL lượt đầu, bị từ chối, lượt sau nộp FINAL mà không READ.
