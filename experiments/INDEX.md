# Nhật ký thực nghiệm

Append-only. Cập nhật ngay khi mở và khi đóng một thực nghiệm. Luật ở `AGENT.md`.

| ID | Phase | Mục đích | Điểm | Accuracy | Coverage | Status | Parent |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `EXP-20261029-01-public-test-submission` | P0 | Sinh submission.jsonl cho 1000 câu public test bằng 14 shop agent + toolkit deterministic | — | — | — | `open` | — |
| `EXP-20261031-01-openrouter-qwen-20-sample` | P0 | qwen3-14b qua OpenRouter trên 20 câu public (10 nhiều bảng + 10 ngẫu nhiên), so với Claude | — (đồng ý Claude 0/20) | — | 0.80 | `closed` | `EXP-20261029-01-public-test-submission` |
| `EXP-20261101-01-openrouter-qwen-20-sample-v2` | P0 | Chạy lại 20 câu của EXP-20261031-01 với harness v2, so với Claude | — (đồng ý Claude 0/20) | — | 0.00 (0/10 shop verified) | `closed` | `EXP-20261031-01-openrouter-qwen-20-sample` |
| `EXP-20261101-02-qwen-submit-context-10-random` | P0 | qwen3-14b + tool submit + context + prompt docs/05, 10 câu random, so với Claude; nhánh vi/en | −5 (vi, hỏng do mất mạng) / −7 (en) | 0/10 | 0.50 / 0.70 | `closed` | `EXP-20261101-01-openrouter-qwen-20-sample-v2` |
| `EXP-20261103-01-gemma3-12b-10-random` | P0 | Đổi model sang gemma-3-12b trên cùng harness, 10 câu random, so với Claude; nhánh vi/en | −8 (vi) / −3 (en) | 0/10 | 0.80 / 0.30 | `closed` | `EXP-20261101-02-qwen-submit-context-10-random` |
| `EXP-20261103-02-gemma3-12b-clean-10-random` | P0 | gemma + bảng sạch trên harness cũ; bỏ dở theo yêu cầu, đối chứng dương 7/7 | — | — | — | `failed` | `EXP-20261103-01-gemma3-12b-10-random` |
| `EXP-20261103-03-simple-analyze-conclude-10-random` | P0 | Luồng simple.py: phân tích → nhận định → sinh code, gemma + bảng sạch, 10 câu random, so với Claude | −4 | 2/8 (2 lỗi API) | 0.80 | `closed` | `EXP-20261103-02-gemma3-12b-clean-10-random` |
| `EXP-20261103-04-simple-train-test-20` | P0 | simple.py + bảng sạch trên 20 câu `test_*`, đáp án thật | −3 | 0.38 | 0.65 | `closed` | `EXP-20261103-03-simple-analyze-conclude-10-random` |
| `EXP-20261103-05-simple-short-error-train-20` | P0 | Chỉ gửi dòng lỗi cuối cho model; 20 câu mới từ `train_*`, đáp án thật | −7 | 0.29 | 0.85 | `closed` | `EXP-20261103-04-simple-train-test-20` |
| `EXP-20261104-01-norm-helper-30-public` | P0 | Chuẩn hoá tất định + helper + prompt v4, gemma 12B, 30 câu public | -7 trên 16 dòng | 0.11 | 0.56 | `closed` (run chết giữa chừng) | `EXP-20261103-05-simple-short-error-train-20` |
| `EXP-20261104-02-harness-helper-holdout-30` | P0 | Prompt v5 trên holdout public; dừng sau 10/30 câu vì tools bị 429 upstream | -3/10 | 0.33 | 0.90 | `failed` (bỏ dở) | `EXP-20261104-01-norm-helper-30-public` |
| `EXP-20261104-03-text-protocol-fewshot` | P0 | Giao thức văn bản, few-shot động, prompt v6; 100 câu public và 100 câu test | public +29, test +44 | 0.65 / 0.72 | 0.99 / 1.00 | `closed` | `EXP-20261104-02-harness-helper-holdout-30` |
| `EXP-20261104-04-fix-harness-helper` | P0 | Sửa harness, helper, từ điển, prompt v7; bỏ dở để chạy đủ 1000 câu public | score 20/99  | 0.60 | 0.97 | `failed` (bỏ dở theo yêu cầu) | `EXP-20261104-03-text-protocol-fewshot` |
| `EXP-20261104-05-public-1000-v7` | P0 | Gemma 12B, prompt v7, đủ 1000 câu public, so với bản Claude | +292 | 0.648 | 0.984 | `closed` | `EXP-20261104-04-fix-harness-helper` |
| `EXP-20261105-01-error-analysis-replay` | P0 | Phân loại 362 câu không đúng; phát lại 192 câu với nhắc lại sau READ | nhóm bỏ ví dụ -69 → +25, đối chứng +47 → +46 | 0.632 / 0.740 | 0.99 / 1.00 | `closed` | `EXP-20261104-05-public-1000-v7` |
| `EXP-20261105-02-fix-norm-helper-remind` | P0 | Sửa chuẩn hoá, helper, nhắc lại sau READ, prompt v8; 450 câu test và 1000 câu public | test +271, public +502 | 0.807 / 0.754 | 0.98 / 0.99 | `closed` | `EXP-20261105-01-error-analysis-replay` |
| `EXP-20261105-03-submission-unanswerable-format` | P0 | Tạo lại file nộp, dòng unanswerable theo format rulebook | +504 local, chưa nộp lại | 0.755 | 0.988 | `closed` | `EXP-20261105-02-fix-norm-helper-remind` |
| `EXP-20261105-04-why-pa-0524` | P0 | Phân tích nguyên nhân PA public 0.524 | thiếu helper +0.235, model chọn sai +0.200, unanswerable +0.037 (trần) | | | `closed` | `EXP-20261105-03-submission-unanswerable-format` |
| `EXP-20261105-05-root-cause-prototypes` | P0 | Viết thử công thức cho 139 câu không đúng, đếm thư viện ví dụ | 138/143 khớp, chưa đo model | | | `closed` | `EXP-20261105-04-why-pa-0524` |
| `EXP-20261105-06-concept-mapping-holdout` | P0 | Thử map cột theo mô tả README trên shop train | 10/10 đợt giao khớp gold, chưa gọi model | | | `closed` | `EXP-20261105-05-root-cause-prototypes` |
| `EXP-20261105-07-domain-helpers` | P0 | Tầng khái niệm, helper theo ngành, ví dụ thêm tay, prompt v9 | public PA 0.815 local, test +282 | 0.908 / 0.816 | 0.999 / 0.991 | `closed` | `EXP-20261105-06-concept-mapping-holdout` |
| `EXP-20261105-08-train-sample-200` | P0 | 200 câu train, prompt v9 | bỏ dở 197/200 | | | `failed` | `EXP-20261105-07-domain-helpers` |
| `EXP-20261105-09-train-3000-coverage` | P0 | 3000 câu train | bỏ dở 38/2350, máy lag | | | `failed` | `EXP-20261105-08-train-sample-200` |
| `EXP-20261105-10-train-5-folds` | P0 | Eval train theo 5 tập, dừng ở 1358/3000 để phân tích | PA 0.616; 24 shop 0.910; 6 shop -0.822 | 0.813 | 0.986 | `closed` | `EXP-20261105-09-train-3000-coverage` |
| `EXP-20261106-01-deterministic-fixes` | P0 | Sửa lỗi tất định F, E của public | public PA 0.845 local (ghép), test +290 | 0.923 / 0.825 | 0.999 / 0.991 | `closed` | `EXP-20261105-07-domain-helpers` |
| `EXP-20261106-02-display-diacritics` | P0 | Giữ đúng dấu và cách ghi tên trong đáp án | | | | `open` | `EXP-20261106-01-deterministic-fixes` |
