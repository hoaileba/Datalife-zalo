# STEPS

1. Bỏ native tool calling, viết giao thức văn bản, prompt v6, thư viện 902 ví dụ, 48 mẫu từ `train/split/train_*`.
2. Chạy 100 câu public mới và 100 câu `test_*`, parallel 8 (`logs/run.cmd`).
3. Gom 36 case public không đúng vào `out/public_wrong/`, đọc log, chạy lại code đúng.
