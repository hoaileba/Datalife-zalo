# RESULT

| Tập | Score | Đúng / sai / trống | Accuracy | Coverage | Lượt TB | Thời gian |
|---|---|---|---|---|---|---|
| Public 100 (tham chiếu Claude) | +29 | 64 / 35 / 1 | 0.65 | 0.99 | 3.78 | khoảng 13,5 phút |
| Train test 100 (gold) | +44 | 72 / 28 / 0 | 0.72 | 1.00 | chưa tính lại khi xong | khoảng 6,5 phút |

Giả thuyết trong manifest: score dương đúng trên cả hai tập, thời gian dưới 1 phút mỗi câu đúng. "Đa số câu FINAL trong 3 lượt" chưa kiểm; trung bình 3.78 lượt, lượt đầu thường mất vì bỏ READ (98/100 và 100/100 log).

Phân tích câu sai: `out/public_wrong/ANALYSIS.md`. 13 câu train test thuộc 6 shop chưa dựng được `lines`.

100 câu public này đã bị đọc log nên hết là holdout.
