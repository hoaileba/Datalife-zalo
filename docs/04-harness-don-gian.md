# 04 — Thiết kế lại harness cho đơn giản

Trạng thái: đề xuất, chờ Hoài duyệt. Thay cho phần log và điều phối của `docs/03`.

## 0. Vấn đề

Hoài cần: **chạy một câu hỏi bằng một lệnh, nhìn thấy luồng chạy và output ngay**. Hiện tại:

- 2.549 dòng code, trong đó log chiếm 537 dòng (`runlog.py`) + 107 (`events.py`).
- Probe một câu sinh **19 file** trong 3 tầng thư mục; muốn biết model làm gì phải mở 3–4 file
  (`summary.md`, `trace.md`, `questions/<qid>.md`, `tools.log`).
- Mỗi lần Hoài hỏi một kiểu xem mới, tôi thêm một file log mới thay vì sửa cái cũ.

## 1. Thành phần hiện có

| Thành phần | Mang thông tin gì | Tồn tại để làm gì | Ai đang dùng | Đánh giá |
| --- | --- | --- | --- | --- |
| `connectors/openrouter.py` | request/response model, retry | gọi API | agent | giữ, bỏ event |
| `modules/agent.py` | vòng lặp, lược context, chặn lặp | chạy một shop | pipeline | giữ, gọn lại |
| `modules/tools.py` | 6 tool | việc agent được làm | agent | **đổi**: gộp `write_file`+`check_answers`+`finish` thành `submit` |
| `modules/verify.py` | chạy lại script, so file | chặn đáp án giả | tool `finish` | giữ, gọi từ `submit` |
| `modules/executor.py` | docker / local | chạy code model | tool, verify | giữ |
| `modules/paths.py` | gốc ảo `data/` `work/` | chặn đường dẫn | tool | giữ |
| `modules/prompts.py` + `prompts/` | system, task, khung script | dạy model | agent | giữ, rút gọn sau (việc riêng) |
| `pipelines/run.py` | pool, ngân sách, state, tqdm, summary | chạy nhiều shop | lệnh batch | **tách**: lệnh 1 câu không đi qua đây |
| `pipelines/probe.py` | bọc `run.py` cho 1 câu | xem 1 câu | Hoài | **bỏ**, thay bằng `run_one` |
| `modules/runlog.py` | 6 kiểu render log | xem lại | Hoài | **bỏ gần hết** |
| `utils/events.py` | events.jsonl, console, run.log, tools.log | log máy + log người | mọi module | **thay** bằng một logger chữ |
| `modules/budget.py` | đếm token | dừng ở 80% | pipeline batch | giữ cho batch |
| `modules/merge.py`, `score.py` | gộp, chấm | ra submission | pipeline batch | giữ |
| `models/` | config, record | validate | mọi nơi | giữ, bớt field log |
| `state.json`, `requests.jsonl`, `steps.jsonl`, `summary.md`, `trace.md`, `questions/*.md`, `tools.log`, `console.log` | các góc nhìn của cùng một dữ liệu | debug | Hoài | **còn 2 file** |

## 2. Quyết định

Tiêu chí: thứ Hoài thực sự đọc khi debug là **một luồng thời gian**: turn 1 gửi gì, model nghĩ gì, gọi gì,
nhận gì, turn 2… Mọi góc nhìn khác suy ra được từ luồng đó.

1. **Một lệnh cho một câu**, không đi qua pipeline batch:
   ```bash
   python -m datamate_agent.run_one --config configs/run.yaml --question q_88aeb2f7b1a7
   ```
2. **Một file log chữ**, cũng là thứ in ra màn hình (tee): `runs/<qid>-<giờ>/run.log`.
3. **Một file máy**: `runs/<qid>-<giờ>/transcript.jsonl` — đúng các message gửi/nhận, để phát lại hoặc grep.
4. Tool gộp còn 4: `list_dir`, `read_file`, `run_python`, `submit(code)`. `submit` nhận code của hàm
   `answer()`, harness tự ghi vào script rồi verify. Model không còn phải biết "sửa file rồi chạy lại".
5. Lệnh batch (nhiều shop) giữ pool + ngân sách + merge, nhưng log cũng chỉ là một `run.log` chữ gộp các
   shop + `transcript.jsonl` mỗi shop.

## 3. Hình dạng `run.log`

```
=== q_88aeb2f7b1a7 · dev_009 · "Hqua có dthu tổng bnhiu?" · as_of 2026-06-20 · qwen/qwen3-14b t=0.0
=== system prompt 11.059 token (prompts/system.md), task prompt 199 token

--- turn 1 · 11.809 → 1.018 token · 8,2 s
THINK  Tôi cần đọc câu hỏi trước... (đủ, không cắt)
CALL   read_file(path="work/inputs/dev_009-questions.jsonl")
RESULT [lines 1-1 of 1]
       {"id": "q_88aeb2f7b1a7", ...}

--- turn 2 · ...
CALL   run_python
       | import pandas as pd
       | ...
RESULT [exit 1, 0,6s]
       | KeyError: 'Ngày'

--- turn 9
CALL   submit
       | def answer(question, clock): ...
RESULT ACCEPTED · q_88aeb2f7b1a7 = 17912000

=== KẾT QUẢ: verified · 9 turn · 129.455 token · $0,017 · đáp án 17912000 · Claude 17912000 · KHỚP
```

Không cắt gì trong `run.log`: một câu chỉ vài chục turn, đọc thẳng được. Cần lọc thì `grep '^CALL'`.

## 4. Kích thước dự kiến

| | Hiện tại | Sau |
| --- | --- | --- |
| File sinh ra cho 1 câu | 19 | 2 (+ script và notes của agent) |
| Code log | 644 dòng | ~80 dòng |
| Tool | 6 | 4 |
| Lệnh xem 1 câu | `probe` qua `run.py` | `run_one`, độc lập |

## 5. Không đổi trong lần này

- Nội dung prompt (việc riêng, sau khi xem được output bằng `run_one`).
- Toolkit `datamate`, Verifier, executor docker, chặn đường dẫn, `Clock.visible_rows`.
