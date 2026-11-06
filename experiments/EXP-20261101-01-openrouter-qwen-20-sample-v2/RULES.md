# RULES — EXP-20261101-01-openrouter-qwen-20-sample-v2

## Thứ được đổi so với parent

**Một thứ: phiên bản harness** (`code/src`, snapshot 2026-11-01). Model, seed, mẫu 20 câu, executor, `max_turns`,
ngân sách, `allow_abstain: false` giữ nguyên. Harness v2 gồm nhiều sửa cùng lúc (ADR 006 + sửa Verifier sau
EXP-20261031-01), nên kết quả gán cho "harness v2" chứ không tách được từng sửa.

| Sửa | Ở đâu |
| --- | --- |
| Verifier dời file đáp án trước khi chạy lại; `write_file` cấm ghi `out/answers/` | `modules/verify.py`, `modules/tools.py` |
| Khung script harness ghi sẵn (id thật, `main()` ghi đáp án) | `prompts/script_template.py.txt` |
| Script dùng đường dẫn `data/`, `work/` như tool | `modules/executor.py` |
| Pool `parallel_shops: 3` thay batch; phát hiện kẹt `stuck_after: 3` | `pipelines/run.py`, `modules/agent.py` |
| `fmt.answer_line` nhận số numpy | `datamate/fmt.py` |
| Log từng turn theo câu hỏi | `modules/runlog.py` |

`model.reasoning` không đặt (thinking theo mặc định provider, như parent).

## Cố ý chưa làm

- Không có gold public: chỉ đo đồng ý với Claude (bản 0,994 public), không đo điểm/accuracy.
