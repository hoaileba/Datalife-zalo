# STEPS — EXP-20261103-01

## 2026-11-03 — bước 1/3: chuẩn bị
Đã làm:    thử 4 biến thể tool calling với gemma (auto/required, schema có/không additionalProperties, vi/en); thêm ModelConfig.tool_choice; 81 test pass; snapshot code; config 2 nhánh
Kết quả:   auto cắt tham số 3/3; required đúng 3/3 (en), 2/3 (vi); turn với system prompt thật 5,4 s, 13,3k token vào
Bước tiếp: bước 2 — chạy 2 nhánh song song
