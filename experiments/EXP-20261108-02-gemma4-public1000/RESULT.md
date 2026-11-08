# RESULT

gemma-4-12B-it qua vLLM, cùng pipeline với file nộp gemma-3 (v10 + gemma xếp lại ví dụ + thư viện train_*), 1000 câu public, lenient scorer. 100 câu lấy từ EXP-20261108-01, 900 câu chạy mới.

| Bản | PA lenient | PA strict | Đúng | Sai | Trống |
|---|---|---|---|---|---|
| gemma-3 file nộp (EXP-04) | +0,878 | +0,850 | 936 | 58 | 6 |
| gemma-4 file nộp `out/submission.jsonl` | +0,943 | +0,915 | 965 | 22 | 13 |

- So với gemma-3 v10: được 47 câu, mất 18 câu.
- 13 câu trống đều là lỗi API do câu trả lời không dừng (`reply exceeded 180s`). Ở 13 câu này gemma-3 đúng 7, sai 4, trống 2. Bỏ 13 câu đó ra: gemma-4 có 965 đúng / 22 sai, gemma-3 có 929 đúng / 56 sai.
- Thời gian 900 câu: phân tích câu hỏi 588s, agent 2838s, 5 luồng. Lúc chạy 100 câu đầu server có hàng đợi (chờ token đầu 45–70s); lúc chạy 900 câu thì 1,6s.
