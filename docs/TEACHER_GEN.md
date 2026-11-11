# Sinh dữ liệu teacher (DeepSeek) và review prompt

Ba công cụ, đều chạy từ gốc repo:

| Lệnh | Gọi model? | Làm gì |
|---|---|---|
| `python -m gen.teacher` | có | Chạy agent v4 (`solve`) trên một split, nhiều luồng; mỗi câu một file JSON chi tiết |
| `python -m gen.teacher_stats` | không | Gom các record thành bảng CSV + `stats.json` để thống kê, lọc, tiền xử lý |
| `python scripts/prompt_md.py` | không | Ghép prompt (và output nếu có log) của một câu ra một file `.md` để review |

Môi trường chung:
```
PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python
export PYTHONIOENCODING=utf-8 PYTHONPATH=src:.
```

## 1. Cấu hình model

| Config | Đường gọi | Biến môi trường |
|---|---|---|
| `config.deepseek_direct.yaml` (mặc định của `gen.teacher`) | API DeepSeek trực tiếp, model `deepseek-flash` (V4.1 Flash), thinking bật | `DEEKSEEK_API_KEY` (tên đúng như trong `.env`), `DEEPSEEK_BASE_URL` (tự đặt `https://api.deepseek.com` nếu thiếu) |
| `config.deepseek.yaml` | OpenRouter, DeepSeek v4.1 flash (DeepInfra) | `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL` (tự đặt `https://openrouter.ai/api/v1`) |
| `config.yaml` | Gemma 12B qua vLLM (bản nộp) | `VLLM_BASE_URL`, `VLLM_API_KEY` |

`.env` được nạp tự động (chịu được xuống dòng CRLF). Trước khi mở luồng, `gen.teacher` gọi thử một lần
`max_tokens=1`: sai URL, key hay tên model thì dừng ngay, không treo.

Kiểm tra số dư: `curl -s https://api.deepseek.com/user/balance -H "Authorization: Bearer $DEEKSEEK_API_KEY"`.
`gen.teacher` tự ghi số dư trước và sau lượt chạy vào `run.json`.

## 2. Chạy `gen.teacher`

```
# Xem trước: số câu, ước lượng số lượt gọi và thời gian, không gọi model
$PY -m gen.teacher --split data_gen/train_aug --out outputs/teacher/aug_v1 --limit 200 --dry-run

# Chạy thật (quá 6 câu phải có --yes: chỉ dùng khi người dùng đã đồng ý)
$PY -m gen.teacher --split data_gen/train_aug --out outputs/teacher/aug_v1 --limit 200 --workers 8 --yes

# Bị ngắt giữa chừng: chạy lại cùng lệnh với --resume, các câu đã có file được bỏ qua
$PY -m gen.teacher --split data_gen/train_aug --out outputs/teacher/aug_v1 --limit 200 --workers 8 --yes --resume
```

Tham số:

| Nhóm | Tham số | Ý nghĩa |
|---|---|---|
| Đầu vào | `--split` | thư mục có `questions.jsonl`, `rulebook.md`, `calendar.csv`, `data/` (có `answers.jsonl` thì chấm đúng/sai) |
| | `--config` | mặc định `config.deepseek_direct.yaml` |
| Chọn câu | `--limit N` / `--all` | N câu đầu sau khi xáo bằng `--seed` (mặc định 0), hoặc tất cả |
| | `--ids ...`, `--ids-file f` | đúng các id này |
| | `--business ...` | chỉ các shop này |
| | `--shard k/n` | chia việc cho nhiều tiến trình/máy/key: tiến trình này lấy câu thứ k, k+n, ... |
| Lấy mẫu | `--samples N` | chạy mỗi câu N lần (mẫu k dùng seed `config.seed + k`); file `<id>__s<k>.json` |
| | `--temperature t` | ghi đè temperature (dùng t > 0 khi `--samples` > 1) |
| Tốc độ | `--workers` | số câu chạy song song (mặc định `run.workers`) |
| | `--concurrency` | số request model cùng lúc (mặc định `llm.max_concurrency`) |
| | `--max-calls` | ghi đè `agent.max_calls` |
| Chi phí | `--price miss,hit,out` | giá USD trên 1M token: input chưa cache, input cache hit, output (gồm thinking); dùng để tính `cost_usd` |
| | `--max-usd X` | đạt X USD (ước theo `--price`) thì không mở câu mới; chạy tiếp bằng `--resume` |
| An toàn | `--allow-test` | mặc định từ chối `public_test`/`private_test` (không lấy dữ liệu huấn luyện từ tập test) |
| | `--yes` | bắt buộc khi số lượt chạy vượt `run.dev_limit` (6) |
| | `--dry-run` | chỉ in ước lượng |
| Lưu | `--inline-system` | chép đủ system prompt vào mọi lượt gọi (mặc định: tham chiếu `system_prompt.md` + sha256) |

Ctrl-C lần đầu: chạy nốt các câu đang dở rồi dừng, mọi file đã ghi giữ nguyên. Ctrl-C lần hai: thoát ngay.
Trong lúc chạy, stderr in tiến độ sau mỗi câu: đúng/sai/bỏ trống, số lượt gọi, token, chi phí, ETA.

Ước lượng (DeepSeek flash, 11/11): khoảng 1.1 lượt gọi mỗi câu, 20–45 giây mỗi câu, 8 luồng xử lý khoảng
10–15 câu/phút. Một câu tốn khoảng 15k token input (phần lớn cache hit) và 2–6k token output.

## 3. Thư mục kết quả

```
outputs/teacher/<run>/
  run.json           danh sách các lượt chạy (mỗi lần --resume thêm một phần tử): tham số, config đầy đủ, git commit
                     và file đang sửa, phiên bản python/openai/pandas, host, sha256 config và system prompt,
                     rulebook (thống kê + dòng đổi), số dư trước/sau, summary
  config.yaml        config đã dùng (sau khi ghi đè bằng tham số)
  system_prompt.md   system prompt đầy đủ của split
  logs/<id>.json     một record mỗi câu (mỗi mẫu), ghi nguyên tử ngay khi câu xong
  index.jsonl        mỗi record một dòng gọn: outcome, reason, số lượt gọi, token, chi phí
  errors.jsonl       lỗi phía host (traceback)
  summary.json       tổng kết lượt chạy cuối
```

Một record (`schema: teacher_record/v1`):

| Trường | Nội dung |
|---|---|
| `id`, `sample`, `business_id`, `question`, `as_of`, `question_row` | câu hỏi (nguyên dòng trong `questions.jsonl`) |
| `gold` | đáp án gold (null nếu split không có) |
| `input` | model, temperature, seed, max_calls, max_tokens, extra_body, sha256 config/system prompt/catalog, độ dài catalog, thống kê rulebook |
| `llm_calls[]` | mỗi lượt gọi: `messages` gửi đi nguyên văn, `output`, `reasoning` (thinking), `finish`, `usage` gốc của API, `tokens` (prompt, cache_hit, cache_miss, completion, reasoning), `cost_usd`, `seconds`, `meta` (id response, model trả về, system_fingerprint, thời điểm gửi, thời gian chờ hàng đợi, thời điểm ra token thinking/nội dung đầu, số chunk, tham số request, số lần thử và lỗi đã retry), `error` nếu gọi hỏng |
| `trace[]` | trace của `solve`: `model`, `execution` (code, ok, result tối đa 20k ký tự, stdout, trace biến, lỗi, issues, thời gian chạy), `observation` gửi lại model |
| `type`, `answer` | đáp án nộp; `raw_answer` khi sai định dạng |
| `correct`, `outcome` | `correct` / `wrong` / `abstain` / `no_gold` |
| `reason`, `calls` | lý do kết thúc của `solve` (`auto_finalized`, `confirmed`, `model_decision`, `call_cap`, `repeated_error`, `deadline`, `llm_error`, `host_error`, ...) |
| `totals` | tổng của câu: lượt gọi, lỗi gọi, giây model, token từng loại, ký tự output/thinking, finish từng lượt, số chương trình (lỗi, explore), giây sandbox, chi phí |
| `started_at`, `finished_at`, `seconds`, `thread`, `run_id` | thời gian, luồng, lượt chạy |

Record là tập cha của log runner (`id`, `business_id`, `type`, `answer`, `reason`, `calls`, `trace`), nên các công cụ
cũ đọc được: `python -m gen.sft --run outputs/teacher/<run> --split <split> --out sft.jsonl` (chỉ lấy câu đúng gold).

Dữ liệu SFT: trong lúc chạy, `<run>/sft/` được làm mới ở luồng nền mỗi `--export-every` (200) record và khi kết thúc
(gói của riêng run này, prompt như đã gửi). Gói giao tay (nhiều run, prompt dựng lại bằng code hiện tại, token Gemma,
train/val theo shop): `python -m gen.package --teacher outputs/teacher/<run> [...] --out outputs/sft/<tên>`, kiểm bằng
`python -m gen.validate <gói> [--rebuild --replay]`. Xem `docs/PLAN_SFT.md`.

`--resume` bỏ qua record đã có, trừ record kết thúc vì `llm_error`/`host_error` (API sập, hết tiền, lỗi host): chúng
chạy lại (`--retry` đổi danh sách lý do, `--retry ""` để tắt). `--dry-run` in thêm ước lượng token và USD
(`--price`, mặc định giả định 0.07,0.007,0.28).

## 4. Thống kê: `gen.teacher_stats`

```
$PY -m gen.teacher_stats outputs/teacher/aug_v1 [outputs/teacher/aug_v2 ...] [--price 0.07,0.007,0.28] [--out DIR]
```

Ghi vào thư mục run đầu tiên (hoặc `--out`):

| File | Một dòng là | Cột chính |
|---|---|---|
| `questions.csv` | một record | run, id, sample, business_id, gold_type, type, outcome, reason, calls, seconds, model, seed, toàn bộ `totals`, cost_usd |
| `calls.csv` | một lượt gọi model | finish, error, seconds, queue_s, first_reasoning_s, first_content_s, attempts, retried_errors, response_model, system_fingerprint, số message, ký tự input/output/thinking, token từng loại, cost_usd |
| `executions.csv` | một lần chạy chương trình | turn, answer_type, ok, explore, error_type, seconds, code_lines, issues |
| `stats.json` | tổng hợp | outcome, PA, reason, phân bố số lượt gọi, kết quả theo loại đáp án và theo shop, p50/p90/p99 thời gian, tổng token, tỷ lệ cache hit, finish, loại lỗi chạy code, tổng chi phí |

`--price` tính lại chi phí từ `usage` (dùng khi lúc chạy chưa truyền giá). Đọc thêm bằng pandas:
`pd.read_csv('outputs/teacher/aug_v1/calls.csv')`.

## 5. Review prompt: `scripts/prompt_md.py`

Ghép prompt bằng đúng code của lượt chạy thật (`load_rulebook` → `build_catalog` → `prompt.messages`) ra một file
Markdown, không gọi model.

```
# Theo câu hỏi: prompt + output của log mới nhất có câu đó (outputs/teacher/*, outputs/runs/*)
$PY scripts/prompt_md.py --split data/train --id <qid> --out outputs/prompt_review/<qid>.md
$PY scripts/prompt_md.py --split data/train --business biz_123 --index 5 --out review.md   # câu thứ 6 của shop
$PY scripts/prompt_md.py --split data/train --id <qid> --run outputs/runs/<run> --out review.md   # log của run này
$PY scripts/prompt_md.py --split data/train --id <qid> --prompt-only --out review.md      # chỉ prompt lượt đầu
$PY scripts/prompt_md.py --split data/train --id <qid> --rulebook <file> --prompt-only --out review.md   # rulebook khác

# Theo record của gen.teacher
$PY scripts/prompt_md.py --record outputs/teacher/<run>/logs/<qid>.json --out review.md [--no-reasoning]
```

Bố cục file:
- Đầu file: id, shop, as_of, câu hỏi, đáp án, gold, outcome, token, đường dẫn log.
- Mục 1: system prompt đầy đủ (ghi một lần; các lượt gọi trỏ về đây).
- Mỗi lượt gọi: **Input** (các message theo thứ tự), **Thinking**, **Output**, **Chạy code** (code, result,
  stdout, trace, lỗi, issues), **Observation gửi lại model**.

Với log runner (không lưu messages), input từng lượt được dựng lại bằng `prompt.messages` với lịch sử là các action
đã parse và observation trước đó, đúng như runner đã gửi; message assistant trong lịch sử vì thế là bản đã chuẩn hoá,
có thể khác chữ so với Output thô của lượt trước. Script từ chối split public/private.

## 6. Quy tắc

- Mỗi lượt chạy có gọi model quá 6 câu cần người dùng đồng ý, kèm ước lượng (`--dry-run`).
- Không sinh dữ liệu huấn luyện từ `public_test`/`private_test`.
- So sánh hai lượt chạy chỉ khi cùng model, cùng config, chạy trong cùng khoảng thời gian (model phía server có thể đổi).
