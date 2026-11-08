# RESULT

google/gemma-4-12B-it trên server vLLM, cùng pipeline (v10 + gemma xếp lại ví dụ + thư viện train_*), 100 câu public, lenient scorer.

| Bản | PA | Đúng | Sai | Trống |
|---|---|---|---|---|
| gemma-3-12b-it, OpenRouter (EXP-04 v10) | +0,930 | 96 | 3 | 1 |
| gemma-4-12B-it, vLLM | +0,920 | 94 | 2 | 4 |

- Khác nhau 8 câu. gemma-4 được 3 (phí ship, "5/25", đơn thu máy cũ), mất 5: 3 câu lỗi API, 2 câu sai ("bnhiu dia", "Số đh hqua").
- 3 câu lỗi API đều là câu trả lời không dừng: `reply exceeded 180s after 17118–23677 chars`. Client không đặt `max_tokens`.
- Phân tích câu hỏi: 100/100 câu qua luật kiểm (gemma-3 có câu bị loại).
- Thời gian: phân tích 996s, agent 10223s cho 100 câu, 5 luồng. Server có hàng đợi: chờ token đầu 45–70s ở mọi cỡ prompt, nên không dùng ước lượng giới hạn 6 giờ.
