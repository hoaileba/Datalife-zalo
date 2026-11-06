# RULES — EXP-20261103-01

## Biến thay đổi so với parent (EXP-20261101-02)

1. Model `qwen/qwen3-14b` → `google/gemma-3-12b-it`. Gemma 3 không có reasoning (`reasoning` không gửi).
2. `model.tool_choice: required` (field mới, mặc định `auto`). Lý do đo trước khi mở: với `auto`, DeepInfra cắt tham số tool của gemma 3/3 lần (`run_python` nhận `{"code": "p"}`); với `required` đúng 3/3 (en), 2/3 (vi). DeepInfra là endpoint duy nhất có `tools` cho model này.

Prompt, 10 câu, tham chiếu Claude, max_turns, stuck_after, context_char_limit giữ nguyên.

## Code khác parent nhưng agent không dùng / ảnh hưởng nhỏ

- `datamate.norm.parse_money`: 1–2 chữ số sau dấu phân cách là phần thập phân (`"12345.0"` → 12345, trước là 123450). Model có thể gọi hàm này trong code.
- `datamate.tabio.read_head`, `read_table(row_numbers=...)`: thêm, mặc định không đổi hành vi.
- `modules/normalize.py`, `pipelines/normalize.py`: tầng chuẩn hoá, **chưa nối** vào agent.

## Luật rulebook code hoá

Không có. Rulebook chép nguyên văn vào system prompt.

## Quyết định tạm

- Giá token DeepInfra endpoint có tools: input $0,05/M, output $0,15/M (OpenRouter `/endpoints`, 2026-11-03).
