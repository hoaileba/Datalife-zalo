# 03 — Chạy shop agent qua OpenRouter

Trạng thái: thiết kế + code đã viết, **chưa chạy với API thật** (chưa có key, chưa đo). Liên quan:
ADR 001, 002, 003, 004, 005.

## 0. Bài toán

Lần sinh `submission.jsonl` đầu tiên (EXP-20261029-01, điểm public **0.99**) chạy bằng subagent
Claude trong Claude Code. Cách đó không chạy lại được ngoài phiên Claude Code: không có script, chỉ
có brief, các script shop mà agent đã viết, và lịch sử hội thoại.

Mục tiêu: đóng gói **đúng quy trình đó** thành code chạy được bằng một API OpenAI-compatible
(OpenRouter), để:

1. chạy lại trên public test hoặc train split bằng một lệnh;
2. đổi model mà không đổi code;
3. mỗi con số truy lại được tới model, prompt, tool call và script đã sinh ra nó (AGENT.md luật 12).

## 1. Thành phần của cách làm hiện tại — liệt kê, chưa phán xét

| Thành phần | Mang thông tin gì | Tồn tại để làm gì | Ai đang dùng | Đánh giá |
| --- | --- | --- | --- | --- |
| `AGENT_BRIEF.md` | quy trình A→D, luật chấm, 4 lớp dòng rác, bẫy đã đo | dạy agent đi đúng thứ tự, tránh sai im lặng | 14 shop agent | **giữ** — là system prompt |
| `rulebook.md` | luật nghiệp vụ, format đáp án | nguồn sự thật duy nhất | agent đọc qua tool | giữ, nhúng vào system prompt |
| toolkit `datamate/` | luật §2 thời gian, §9 format, parse tiền/ngày, đọc bảng | phần deterministic dùng chung, có 49 test | script shop import | **giữ** — chuyển ra `src/datamate/` |
| `code/shops/<shop>.py` | ingest + trả lời của một shop | sinh file đáp án, chạy lại được | `run.sh`, bước kiểm tái lập | giữ dạng: agent mới cũng phải nộp script |
| `logs/<shop>-notes.md` | khoảng ngày, capability map, census, quyết định đọc luật | review sau khi chạy, dò câu rủi ro | Hoài, orchestrator | giữ |
| Bước kiểm tái lập (chạy lại script, diff) | script có sinh đúng file đã nộp không | bắt agent sửa tay file đáp án | orchestrator (tay) | **giữ, tự động hoá** |
| Batch 3 agent, dừng ở ~80% | giới hạn tải | tránh 429 làm chết cả lượt | orchestrator (tay) | giữ, đổi thành ngân sách token đo được |
| `merge.py` | gộp 14 file, điền id thiếu | ra file nộp đủ 1000 dòng | orchestrator | giữ |
| `score.py` | so với gold | đo điểm / accuracy / coverage | chưa ai chạy trên train | giữ, nối vào pipeline |
| Hội thoại orchestrator ↔ agent | dấu hiệu riêng từng shop, sửa hướng | cứu agent đi lệch | orchestrator (tay) | **bỏ** — không tái lập được; thay bằng vòng verify tự động |
| Dấu hiệu riêng từng shop trong prompt | suy từ shop họ hàng ở train | gợi ý cột, bẫy | 14 agent | **bỏ** — §3c brief: đã sai 3 lần |

## 2. Giữ gì, theo ownership

| Loại | Thành phần | Vì sao |
| --- | --- | --- |
| Domain thật | toolkit `datamate`, rulebook, scorer | luật bài toán, không phụ thuộc engine nào |
| Internal contract | file đáp án / script / notes của mỗi shop, format dòng JSONL | ranh giới giữa agent và pipeline |
| Config thuộc connector | base URL, API key | OpenRouter là owner; không nằm trong code (`plan.md` dòng 53) |
| Config thuộc run | model, số shop song song, ngân sách, chính sách abstain | đổi mỗi lần chạy, không đổi code |
| Di sản | hội thoại tay, dấu hiệu riêng shop | gắn với một phiên Claude Code cụ thể |

## 3. Kiến trúc

```
pipelines/run.py ─┬─ đọc RunConfig (yaml) + env connector
                  ├─ pool `parallel_shops` luồng, shop xong thì shop kế vào ngay
                  │     └─ modules/agent.py  ShopAgent ── vòng tool calling ──┐
                  │           ├─ connectors/openrouter.py  (gọi model)        │
                  │           ├─ modules/tools.py  list_dir / read_file /      │
                  │           │     write_file / run_python / check_answers /  │
                  │           │     finish                                    │
                  │           ├─ modules/executor.py  (local | docker)         │
                  │           └─ modules/verify.py  chạy lại script + diff ◀──┘ khi agent gọi finish
                  ├─ modules/budget.py  dừng nhận shop mới khi dùng ≥ stop_ratio ngân sách
                  ├─ modules/merge.py  gộp đáp án → submission.jsonl
                  └─ modules/score.py  nếu có gold: điểm, accuracy, coverage
```

Model không bao giờ ghi đáp án trực tiếp. Nó viết **script**, script gọi `fmt.answer_line()`, và
pipeline chỉ nhận đáp án khi **chạy lại script ra đúng file đó** (verify). Đây là chỗ thay cho bước
"chạy lại ra file y hệt" tôi làm tay ở EXP-20261029-01.

### Không gian đường dẫn mà model thấy

Model chỉ thấy hai gốc ảo, giống nhau ở cả executor local lẫn docker:

| Gốc ảo | Trỏ tới | Quyền |
| --- | --- | --- |
| `data/` | `dataset_root` (vd `public_test/`), **chỉ lộ** `rulebook.md`, `calendar.csv`, `data/` | chỉ đọc |
| `work/` | `output_dir` của lần chạy | đọc + ghi |

`train/` chứa `answers.jsonl` và `split/*_answers.jsonl` ngay ở gốc. Nếu agent đọc được thì số
calibration vô giá trị, nên tool ẩn mọi thứ ngoài ba mục trên, và executor `docker` chỉ mount đúng
ba mục đó. Executor `local` **không** chặn được script tự mở file gold (ADR 005).

Câu hỏi của shop được harness ghi ra `work/inputs/<shop>-questions.jsonl` từ `questions_file` của
config. Agent chỉ trả lời file đó, nên tập câu hỏi do config quyết, không do agent tự tìm.

Script đọc gốc thật qua biến môi trường `DATAMATE_DATA`, `DATAMATE_WORK`, `DATAMATE_CALENDAR`, không
hard-code đường dẫn.

### Đầu ra một lần chạy (`output_dir`)

Cùng bố cục với thực nghiệm trong AGENT.md, nên trỏ `output_dir` vào một `experiments/EXP-*` là dùng
được ngay:

```
<output_dir>/
├── code/shops/<shop>.py          script agent viết
├── out/answers/<shop>.jsonl      đáp án, chỉ nhận khi verify pass
├── out/submission.jsonl          merge
├── out/score.json                nếu có gold
├── logs/<shop>-notes.md          notes agent viết
├── logs/run.log                  log chính gộp MỌI lần chạy: tiến độ, shop xong, verify, lỗi — `tail -f` để theo dõi
├── logs/tools.log                log chi tiết tool gộp mọi lần chạy: mỗi lời gọi API, tool (tham số + kết quả), exec
├── logs/runs/<YYYYMMDD-HHMMSS>/  MỘT THƯ MỤC CHO MỖI LẦN CHẠY, không ghi đè lần trước
│   ├── summary.md                ĐỌC ĐẦU TIÊN khi debug: shop nào hỏng, ở bước nào, vì sao
│   ├── console.log               đúng những dòng in ra màn hình (không có chi tiết tool)
│   ├── tools.log                 chi tiết tool của lần chạy này: tham số đầy đủ, kết quả (2.000 ký tự đầu)
│   ├── events.jsonl              event API / tool / exec / verify / question
│   ├── shops/<shop>/
│   │   ├── system_prompt.md      system prompt đúng như đã gửi
│   │   ├── task_prompt.md
│   │   ├── tools.json            6 tool spec
│   │   ├── requests.jsonl        toàn bộ messages gửi model ở MỖI bước (sau khi lược)
│   │   ├── steps.jsonl           mỗi bước: input mới → process (reasoning, content, tool call) → output tool ĐẦY ĐỦ
│   │   └── trace.md              bảng mỗi action một dòng (bước → action → kết quả → token), rồi chi tiết từng bước
│   └── questions/<qid>.md        log đọc được cho từng câu (xem dưới)
└── state.json                    trạng thái từng shop + token đã dùng, để chạy tiếp
```

### Debug bắt đầu từ `summary.md`

Ghi lại sau mỗi shop (lần chạy bị dừng giữa chừng vẫn có), gồm một bảng mỗi shop: trạng thái, số
bước, token, số tool lỗi, số lần `finish` bị từ chối, số bước model không gọi tool, số bước output bị
cắt vì hết `max_output_tokens`, số lần API lỗi/retry. Dưới bảng là từng chỗ bất thường **kèm số
bước**, để mở thẳng bước đó trong `steps.jsonl` hoặc file câu hỏi. Shop crash thì có traceback đầy đủ.

### Log của một câu hỏi (`logs/runs/<lần chạy>/questions/<qid>.md`)

Được **ghi thêm ngay sau mỗi turn** (theo dõi được bằng `tail -f`), và ghi lại toàn bộ khi shop kết
thúc với kết quả cuối lên đầu. Agent phụ trách cả shop, nên các turn dùng chung cho mọi câu của shop;
turn nào nhắc tới id câu này có ★.

Mỗi turn là một khối rút gọn:

| Phần | Nội dung |
| --- | --- |
| tiêu đề | `## Turn N ★ · <tool> · <giờ> · token vào / ra` |
| **INPUT** | phần mới model nhận ở turn này: kết quả tool của turn trước đúng như model nhận (6 dòng đầu), hoặc task prompt / lời nhắc |
| **THINK** | reasoning của model (8 dòng đầu) và nội dung trả lời |
| **ACTION** | tool được gọi: code `run_python` / nội dung `write_file` (40 dòng đầu), tham số các tool khác |
| **RESULT** | output của tool (15 dòng đầu), ghi rõ khi model chỉ nhận bản cắt |

Bản không cắt của từng turn nằm ở `shops/<shop>/trace.md` và `steps.jsonl`. Khi shop kết thúc, file
câu hỏi có thêm: output cuối, kết luận Verifier, báo cáo agent, bảng tổng quan, script cuối.

## 4. Chạy

```bash
pip install -e ".[dev]"
docker build -t datamate-sandbox:0.1 -f docker/sandbox.Dockerfile .   # chỉ cần khi executor.kind = docker
export OPENROUTER_API_KEY=...        # key của anh
export OPENROUTER_BASE_URL=...       # base URL OpenAI-compatible của OpenRouter, lấy từ tài liệu OpenRouter
export DATAMATE_ENV=dev              # dev: lỗi là dừng. prod: shop lỗi ghi status, pipeline chạy tiếp
cp configs/run.example.yaml configs/run.yaml   # sửa model, output_dir, executor
python -m datamate_agent.pipelines.run --config configs/run.yaml
```

Màn hình có thanh tqdm đếm **số câu đã xử lý / tổng số câu**. Thanh nhảy theo shop, vì một agent trả lời cả shop một lần; phần đuôi ghi shop vừa xong, trạng thái, số câu được Verifier nhận và token đã dùng. Cùng thông tin đó được ghi thành event `progress` trong `logs/run.log`.

Chạy lại **cùng lệnh** là chạy tiếp: shop đã verify thì bỏ qua, shop dở thì làm lại từ đầu
(mỗi lần chạy có thư mục log riêng trong `logs/runs/`, lần trước không bị ghi đè).

Khi đã dùng ≥ `stop_ratio` × `max_total_tokens`, pipeline không mở shop mới, ghi event
`run_paused` kèm danh sách shop còn lại, vẫn merge ra `submission.jsonl` (shop chưa xong là
`abstain`). Muốn chạy nốt: tăng `max_total_tokens` hoặc giữ nguyên rồi chạy lại khi đã đổi kỳ thanh
toán, cùng lệnh.

Test: `pytest -q` — 73 test, gồm 50 test luật toolkit và 23 test harness chạy bằng test double
`tests/fakes.py::ScriptedChatClient`, không gọi API.

Chỉ chạy vài shop: `--shops dev_009 dev_011`. Chỉ merge + chấm, không gọi model: `--merge-only`.

### Đo trước khi tin (bước 4)

Public test không có gold, nên mọi lần chạy trên public chỉ ra **coverage**. Muốn có điểm và
accuracy thì chạy trên train split:

```yaml
dataset_root: ../train
questions_file: split/train_questions.jsonl
truth_file: split/train_answers.jsonl
shops: [biz_112]
```

Mẫu sẵn: `configs/calibration-train.example.yaml` (`biz_112`, 100 câu train). Không trỏ vào
`split/test_*.jsonl` khi chọn model hay sửa prompt (AGENT.md luật 8).

Lần chạy calibration sinh `out/score.json` với điểm, accuracy, coverage và `wrong_ids`.

## 5. Config

| Field | Nghĩa |
| --- | --- |
| `model.name` | id model trên OpenRouter. **Phải hỗ trợ tool calling** |
| `model.temperature`, `model.seed`, `model.max_output_tokens` | ghi vào event log để tái lập |
| `executor.kind` | `docker` hoặc `local`, **bắt buộc chọn**, không có mặc định — xem ADR 005 |
| `executor.timeout_s` | giới hạn mỗi lần chạy Python |
| `parallel_shops` | số shop chạy song song; shop xong thì shop kế vào ngay, shop nhiều câu chạy trước (ADR 006) |
| `stuck_after` | gọi y hệt lời gọi trước, hoặc `finish` bị từ chối cùng lý do, đủ số lần này thì dừng shop với status `stuck` |
| `model.reasoning` | `false` tắt thinking qua OpenRouter; bỏ trống thì theo mặc định provider. Chưa đo ảnh hưởng chất lượng |
| `max_turns` | số lượt gọi model tối đa cho một shop |
| `budget.max_total_tokens`, `budget.stop_ratio` | dừng mở shop mới khi đã dùng ≥ `stop_ratio` × ngân sách |
| `allow_abstain` | `false`: verify từ chối file có `abstain`, agent phải chọn đáp án khả năng đúng cao nhất |
| `context_char_limit`, `tool_output_char_limit` | cắt transcript / output tool cho model context ngắn |

## 6. Rủi ro đã biết, chưa đo

1. **Model < 15B làm agent nhiều bước.** Kết quả 0.99 là của Claude Opus. `plan.md` dòng 285:
   BFCL v3 multi-turn tool calling, trung bình 23 model **58.5**, top 76.7 **[benchmark]**. Một shop
   cần 30–80 lượt tool. **Giả thuyết**: model 14B sẽ rớt mạnh ở bước ingest (4 lớp dòng rác). Chưa
   đo — phải chạy train split trước.
2. **Context.** Brief + rulebook ≈ 40k ký tự. Model context 32k token vẫn đủ, nhưng transcript dài
   sẽ bị cắt output tool cũ (`context_char_limit`). Cắt có thể làm model quên kết quả census.
3. **Chạy code model sinh ra trên máy.** Xem ADR 005.
4. **Ngân sách đo bằng token, không bằng tiền.** OpenRouter tính tiền theo model; token chỉ là proxy.
5. **Prompt cache.** System prompt ~37k ký tự lặp lại mỗi lượt. Provider có prompt caching thì rẻ
   hơn nhiều; provider không có thì một shop 60 lượt tốn ~60 × 10k token chỉ cho system prompt.

## 7. Đã kiểm gì, chưa kiểm gì

| Đã kiểm | Cách |
| --- | --- |
| Vòng lặp agent, verify, chính sách abstain, ngân sách, chạy tiếp | 14 test với test double |
| Chặn đường dẫn, ẩn file gold | test `PathSpace` |
| Merge mới ra đúng file cũ | merge 14 file đáp án EXP-20261029-01 → giống từng byte `submission.jsonl` cũ |
| Thiếu biến môi trường | raise `missing environment variable` trước khi gọi mạng |

| **Chưa kiểm** | Vì sao |
| --- | --- |
| Gọi OpenRouter thật | chưa có key; không ghi endpoint vào file |
| `DockerExecutor` | daemon docker trên máy không trả lời (2026-10-30) |
| Model nào làm được | chưa chạy calibration |
