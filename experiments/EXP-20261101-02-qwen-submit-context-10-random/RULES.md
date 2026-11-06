# RULES — EXP-20261101-02

## Luật rulebook được code hoá

Không có luật nào code hoá trong harness. Rulebook chép nguyên văn vào system prompt (`code/src/datamate_agent/prompts/system.{vi,en}.md`, mục Rules); model tự viết code tính.

## Thay đổi so với parent (EXP-20261101-01)

1. Tool: `list_dir`, `read_file`, `run_python(code)`, `submit(code)`. Bỏ `write_file`, `check_answers`, `finish`, `run_python(path)`. `submit` ghép code model + `main()` cố định (`prompts/script_main.py.txt`), harness tự chạy script rồi kiểm (`Verifier.run_script`). Bỏ yêu cầu notes.
2. System prompt 6 phần (docs/05): định danh + cách chấm, folders, tools, rules, process + 8 ví dụ từ `train/split/train_*`, context.
3. `{{context}}`: shop id, câu hỏi (id, question, as_of_date), danh sách file shop (ẩn `questions.jsonl`), README nguyên văn. Không còn khung script.
4. `context_char_limit` 60.000 → 100.000 (system prompt đã ~37–42k ký tự, đếm cả trong giới hạn).

Đây là **nhiều thay đổi một lúc** so với parent (gói docs/04 + docs/05), không phải một biến. Biến duy nhất giữa hai nhánh là ngôn ngữ prompt: `vi` / `en`.

## Cố ý chưa làm

- Log đơn giản (`run_one`, một `run.log`) của docs/04: chưa, vẫn dùng runlog cũ.
- Tiền xử lý dữ liệu / profile (đề xuất A).
- Rút gọn toolkit_reference.

## Quyết định tạm chưa thành ADR

- Đáp án Claude ở `EXP-20261029-01/out/submission.jsonl` coi là đúng 100% (Hoài chốt). Bản candidate trùng ở cả 10 câu.
- Ẩn `questions.jsonl` của shop khỏi danh sách file trong context (vẫn đọc được qua tool).
- Giá token lấy như parent: input $0,12/M, output $0,24/M (`code/score.py`).
