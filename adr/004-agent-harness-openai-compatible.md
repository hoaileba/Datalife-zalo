# ADR 004 — Harness agent riêng trên API OpenAI-compatible, không dùng framework agent

Ngày: 2026-10-30 · Trạng thái: đề xuất, chờ Hoài duyệt · Liên quan: ADR 001, 002, 003, `docs/03`

## Bối cảnh

ADR 001 chọn agent làm engine, nhưng engine đó là Claude Code: vòng lặp agent, tool `Bash`/`Read`/
`Write`, và orchestrator là tôi. Hoài cần chạy lại bằng OpenRouter, tức là phải tự có vòng lặp agent.

## Quyết định

Viết harness nhỏ trong `src/datamate_agent/`:

1. Vòng lặp **ReAct bằng native tool calling** của Chat Completions API (`tools=[...]`), qua SDK
   `openai` trỏ `base_url` vào OpenRouter.
2. Sáu tool cố định: `list_dir`, `read_file`, `write_file`, `run_python`, `check_answers`, `finish`.
3. `finish` không kết thúc ngay: harness **chạy lại script** của agent và diff với file đáp án. Lệch,
   thiếu id, sai format, hoặc có `abstain` khi `allow_abstain: false` → trả lỗi về cho agent, vòng
   lặp chạy tiếp.
4. Batch + ngân sách token thay cho "batch 3 agent, dừng ở ~80%" mà tôi làm tay.

## Đánh đổi kinh điển

Đây là **build vs buy** ở tầng orchestration. Framework agent (LangGraph, smolagents, OpenAI Agents
SDK) cho sẵn vòng lặp, nhưng thêm một lớp abstraction giữa event log và lời gọi API — đúng chỗ AGENT.md
bắt log model, prompt hash, token, latency. Vòng lặp tool calling chỉ khoảng 150 dòng; tự viết thì
mọi lời gọi đi qua đúng một hàm có log.

Chọn **native tool calling** thay vì để model in JSON trong text: OpenRouter chuẩn hoá `tools` sang
từng provider, và lỗi parse JSON tự do là một nguồn sai nữa. Giá: **model không hỗ trợ tool calling
thì không chạy được**, phải chọn model có hỗ trợ.

## Vì sao verify là cổng bắt buộc

Ở EXP-20261029-01, bước "chạy lại script ra file y hệt" là bước duy nhất phân biệt "agent tính ra"
với "agent sửa tay file đáp án". Với model nhỏ hơn, nguy cơ sửa tay cao hơn. Đặt verify trong
harness biến nó thành **invariant** thay vì thói quen của orchestrator.

## Thay vào đó đã không chọn gì

- **Một lời gọi model mỗi câu hỏi** (pipeline compiler của `plan.md`): đúng hướng production, nhưng
  không phải cách đã ra 0.99. Yêu cầu lần này là đóng gói cách đã chạy.
- **Giữ hội thoại orchestrator ↔ agent**: không tái lập được, và đã sai 3 lần (brief §3c).

## Hệ quả

- `allow_abstain` là config của run. Lần chạy này Hoài chốt `false` (2026-10-30: "không được để
  abstain"), đi ngược ADR 003. ADR 003 vẫn đúng khi bật lại `true`.
- Không tái lập bit-exact (ADR 001 hệ quả 1) vẫn đúng: cùng config chạy hai lần có thể ra script
  khác. Cái tái lập được là **từng file đáp án từ script của chính nó**.
