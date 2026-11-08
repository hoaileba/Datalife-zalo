# RULES

1. Chỉ đổi `--model`. Prompt v9, norm, helper, seed giữ nguyên như lần chạy gemma hiện tại.
2. 100 câu public chọn bằng `random.Random(20261103).sample`, file `out/public100.jsonl`.
3. Thử 1 câu trước; chạy 100 câu sau khi câu thử ra đáp án hợp lệ.
4. So với gemma trên đúng 100 câu đó (`error/answers_public_current.jsonl`). Không chạy full public trước khi anh review.
