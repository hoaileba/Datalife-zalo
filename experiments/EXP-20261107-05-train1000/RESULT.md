# RESULT (tạm dừng theo yêu cầu ở 653/1000 câu)

Cấu hình: prompt v10 + gemma xếp lại ví dụ + thư viện train_*, ví dụ chỉ từ shop khác (ADR 017). Chạy tiếp được: agent bỏ qua câu đã có log nếu chạy lại với danh sách câu còn thiếu.

| Đo | Giá trị |
|---|---|
| lenient | +0,960 (638 đúng, 11 sai, 4 trống) |
| strict | +0,957 |
| oracle đúng | 580/653 |
| câu qua gemma xếp lại | 19/653 (2,9%; public 17,5%) |

15 câu không đúng: oracle cũng sai 6 (5 câu tồn kho nhà thuốc biz_121/122, hộp chẵn và vỉ lẻ), gold không trả lời được 5 (2 sai, 3 bỏ trống), đúng hàm sai tham số 2, sai dạng 1, bỏ trống 1. Chi tiết: out/errors_train1000.jsonl.
