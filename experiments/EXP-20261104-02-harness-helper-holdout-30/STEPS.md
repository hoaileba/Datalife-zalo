# STEPS

1. Chạy gemma 12B, prompt v5, 30 câu holdout, parallel 2 (`logs/run.cmd`).
2. Sau 78 phút có 10 đáp án. Hai câu `q_4217e6c4305e`, `q_2e131da8a651` không có log mới từ 16:56.
3. Đọc log 6 câu sai, chạy tay helper one-liner trên 5 câu.
4. Dừng run lúc khoảng 17:10. Lệch manifest: manifest khai 30 câu, thực tế chấm 10 câu.
5. Đo API sau khi dừng: 6/6 request có `tools` bị 429 upstream; 10/10 request không `tools`, 12.533 token prompt, thành công trong 2,6–4,9s.
