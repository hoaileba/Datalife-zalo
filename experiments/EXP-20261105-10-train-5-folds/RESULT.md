# RESULT

Dừng giữa chừng theo yêu cầu: 1358/3000 câu có đáp án, tập 1 đủ, tập 2 dở. So với gold.

| Phần | n | Score | PA | Đúng | Sai | Trống | Accuracy | Coverage |
|---|---|---|---|---|---|---|---|---|
| Tất cả có đáp án | 1358 | +837 | 0.616 | 1088 | 251 | 19 | 0.813 | 0.986 |
| 24 shop | 1128 | +1026 | 0.910 | 1077 | 51 | 0 | 0.955 | 1.000 |
| 6 shop thiếu lines | 230 | -189 | -0.822 | 11 | 200 | 19 | 0.052 | 0.917 |
| 24 shop, không có trong thư viện | 792 | +698 | 0.881 | 745 | 47 | 0 | 0.941 | 1.000 |

Kết luận: giả thuyết đúng trên phần đã đo. Các tập chưa đủ nên chưa so được độ chênh giữa các tập.

Việc còn treo: chờ Hoài quyết định hướng sửa. `src/` và `artifacts/norm` chưa đổi.
