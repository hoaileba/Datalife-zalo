# STEPS

1. Viết `datamate_agent/concepts.py`, sinh `concepts.json` cho 44 shop. Sửa nhầm `Hàng` và `Hãng` bằng so tên nguyên dấu.
2. Viết `datamate/domains/`: giao hàng, nhà thuốc, điện thoại, sửa xe, mẹ và bé. `Shop` có thêm helper theo khái niệm, không có tên shop trong code.
3. `code/verify_domains.py`: 131/133 khớp tham chiếu public; `b38db1` cùng người (KH0108) nên lệch thật còn 1 câu `7de8d5`.
4. `code/verify_train_gold.py`: giao hàng 10/10, lô 4/5, hết hàng 1/1 theo gold; 5 câu `biz_124` lỗi vì shop không dựng được `lines`.
5. Oracle: train 1866 giữ nguyên, public 566 lên 567, mất 0.
6. Prompt v9, `library_curated.jsonl` 109 câu 73 loại, lọc ví dụ theo ngành. Smoke `q_e4fc0d18d409` ra 11.
7. Đo test và public từ 13:22, xem `logs/run.cmd`.
8. Đo xong lúc 14:13. `httpx.ReadTimeout` lúc 13:27 làm tiến trình chính ngừng ghi `answers.jsonl` ở cả hai lần chạy, worker vẫn chạy và ghi log. Sửa: thêm `httpx.TransportError` vào retry, `httpx.HTTPError` vào nhánh bắt lỗi của `answer`.
9. `code/rebuild.py` dựng đáp án từ log. Chạy lại 2 câu public và 11 câu test không có `FINAL`, đều do lỗi mạng hoặc hết hạn trả lời. Sau đó còn 2 câu test vẫn trống.
10. `out/submission.jsonl`: 1000 dòng, 1 dòng sai format đổi thành `abstain`.
