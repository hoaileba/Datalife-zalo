# RULES — EXP-20261031-01-openrouter-qwen-20-sample

## Luật được code hoá trong lần chạy này

| Luật | Ở đâu |
| --- | --- |
| Toàn bộ quy trình shop agent (bước A–D, 4 lớp dòng rác, tính từ không định nghĩa) | `code/src/datamate_agent/prompts/system.md` |
| Rulebook public, nhúng nguyên văn vào system prompt | `public_test/rulebook.md` |
| Thời gian §2, format §9 | `code/src/datamate/` |
| Không cho `abstain` (lệnh Hoài 2026-10-30) | `allow_abstain: false` trong `code/run.yaml`, Verifier từ chối |
| Đáp án chỉ nhận khi script chạy lại ra đúng file | `code/src/datamate_agent/modules/verify.py` |

## Cố ý chưa làm

- Không có gold cho public test: **không đo được điểm và accuracy**. Chỉ đo tỉ lệ đồng ý với đáp án Claude (EXP-20261029-01, điểm public 0.99 ⇒ ước lượng ~3 câu sai trên 1000). Đồng ý ≠ đúng.
- Mỗi shop chỉ nhận các câu được bốc, không phải toàn bộ câu của shop.

## Quyết định tạm chưa thành ADR

- Định nghĩa "nhiều bảng": shop ≥ 4 bảng **và** câu chạm khái niệm phải join (từ khoá trong `code/sample.py`). Đây là proxy, không phải phân tích script.
- Agent làm việc trong `run/`; đáp án Claude để ở `out/claude_reference.jsonl`, ngoài `work/` của agent.
