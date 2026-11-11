# DataMate SFT package

Dữ liệu fine-tune (LoRA) cho model agent của DataMate (Zalo AI Challenge 2026: hỏi đáp tiếng Việt trên dữ liệu
bảng của cửa hàng). Model học sinh: **Gemma 4 12B-it** (`google/gemma-4-12B-it`), chạy bằng vLLM, thinking tắt.

- Tạo lúc: {{created_at}}, commit `{{commit}}`
- Nguồn: lượt chạy teacher {{runs}} (DeepSeek, agent v4, chỉ giữ câu có đáp án cuối đúng gold)
- **train: {{train}} mẫu, val: {{val}} mẫu**; val là toàn bộ câu của các shop: {{val_shops}}
- Đếm token: {{counter}}; mẫu dài nhất {{max_total}} token (prompt + completion), giới hạn khi đóng gói {{max_len}}

## 1. Dữ liệu là gì

Agent trả lời một câu hỏi trong tối đa 3 lượt. Mỗi lượt model nhận prompt (system prompt dài khoảng 9k token: hướng
dẫn + cookbook luật; user message: catalog bảng dữ liệu của shop, câu hỏi, `as_of`, giá trị tra được), rồi viết:

```
Answer type: <number|percent|string|date|boolean|list|table|explore|unanswerable|abstain>
<lập luận ngắn: hỏi gì, luật nào áp dụng, lọc thế nào>
```python
<chương trình pandas, gán kết quả vào biến result>
```
```

Host chạy chương trình trong sandbox; kết quả đạt yêu cầu thì nộp luôn, nếu không thì lỗi hoặc kết quả được gửi lại
thành lượt sau. Một mẫu = một lượt của teacher:

- **lượt cuối** của câu teacher trả lời đúng (lượt sinh ra đáp án nộp; có thể là lượt sửa lỗi, khi đó prompt chứa các
  lượt hỏng trước đó và lỗi của chúng: model học cách sửa);
- **lượt `explore`** chạy sạch trước lượt cuối (xem dữ liệu rồi mới viết chương trình trả lời).

Prompt là đúng chuỗi message agent gửi lúc chạy thật (dựng lại bằng code agent hiện tại). Completion là câu trả lời
của teacher ở dạng chuẩn hoá mà agent đọc được. Thinking của teacher không nằm trong mẫu.

## 2. Định dạng

| File | Một dòng là |
|---|---|
| `train.jsonl`, `val.jsonl` | `{"id": ..., "prompt": [{"role": "system"|"user"|"assistant", "content": ...}, ...], "completion": [{"role": "assistant", "content": ...}]}` |
| `train_meta.jsonl`, `val_meta.jsonl` | cùng dòng đó (`key` = `id`): câu hỏi, shop, nhóm câu, lượt, loại đáp án, intent, cờ `weak`, số token |
| `val_questions.jsonl` | mọi câu của shop/nhóm giữ riêng (cả câu teacher làm sai): dùng để đo độ chính xác thật |
| `stats.json` | nguồn, bộ lọc và số mẫu mỗi bộ lọc bỏ, phân bố, độ dài, sha256 các file |
| `sft_lora.py` | script train (LoRA, loss chỉ trên completion) |

`prompt` luôn bắt đầu bằng `system`, `user`, rồi các cặp (`assistant`, `user`) của lượt trước, kết thúc bằng `user`.
Đây là định dạng prompt-completion của TRL, nhưng **đừng để TRL tự tokenize** (xem mục 3).

Cờ trong meta: `weak` = đáp án có thể đúng do may (`unanswerable`: chỉ chấm theo loại; `boolean`; `zero`: kết quả 0;
`no_program`), `recovered` = có lượt hỏng trước lượt này, `prompt_drift` = prompt teacher thấy khác prompt hiện tại.

## 3. Train

```
pip install "torch>=2.6" "transformers>=5.10" peft accelerate   # + bitsandbytes nếu dùng --qlora
python sft_lora.py --data . --model google/gemma-4-12B-it --dry-run          # kiểm tra: độ dài, ranh giới prompt/target
python sft_lora.py --data . --model google/gemma-4-12B-it --out ckpt/smoke --max-steps 5   # chạy thử 5 bước
python sft_lora.py --data . --model google/gemma-4-12B-it --out ckpt/lora_v1 --max-len {{train_len}}
accelerate launch --num_processes 2 sft_lora.py --data . --model google/gemma-4-12B-it --out ckpt/lora_v1   # nhiều GPU
```

Script tự tokenize: prompt render bằng chat template của chính model với `add_generation_prompt=True`,
`enable_thinking=False` (Gemma 4 mở lượt model bằng một kênh thought rỗng `<|channel>thought\n<channel|>`, giống hệt
vLLM lúc suy luận), target = nội dung completion + `<turn|>`. Loss chỉ trên target (không trên prompt, không trên các
lượt assistant cũ trong prompt). Mẫu dài hơn `--max-len` bị bỏ, không cắt. Đường prompt-completion hội thoại của TRL
render prompt+completion không có kênh thought rỗng nên prompt không còn là tiền tố: target bị lệch.

Siêu tham số khuyên dùng (chưa tune; điểm khởi đầu):

| Tham số | Giá trị |
|---|---|
| LoRA | r 16, alpha 32, dropout 0.05, mọi lớp linear của language model (attention + MLP), tháp vision/audio đóng băng |
| Tối ưu | lr 1e-4, cosine, warmup 3%, 2 epoch, batch 1 × accumulation 16 (effective 16) |
| Độ dài | `--max-len {{train_len}}` (mẫu dài nhất {{max_total}}, p99 {{p99_total}}) |
| Attention | `sdpa` (flash-attention 2 không hỗ trợ head_dim 512 của các lớp global) |

Bộ nhớ GPU (ước lượng, **chưa đo**): base bf16 khoảng 24 GB; activation với gradient checkpointing ở 24k token khoảng
10–15 GB; logits chỉ tính cho phần target (`logits_to_keep`). LoRA bf16 cần một GPU 80 GB (A100/H100); `--qlora`
(4-bit) khoảng 25–35 GB, chạy được trên 48 GB, có thể vừa 32 GB nếu giảm `--max-len`. Thời gian (ước lượng): mỗi
epoch khoảng 45M token cho 3000 mẫu × 15k token, cỡ 3 giờ trên một H100.

Theo dõi `eval_loss` trên val (shop chưa thấy). Bản cuối có thể train lại trên train + val (`cat train.jsonl val.jsonl`)
sau khi đã chọn được siêu tham số.

## 4. Gộp và chạy bằng vLLM

```
python sft_lora.py --model google/gemma-4-12B-it --merge ckpt/lora_v1 --out ckpt/merged_v1
vllm serve ckpt/merged_v1 --served-model-name gemma-12b --dtype bfloat16 --max-model-len 32768 --seed 0
```

Agent gọi model tên `gemma-12b` (`config.yaml`: `llm.model`, `VLLM_BASE_URL`), `temperature 0`, thinking tắt, tối đa 2
request song song. Có thể phục vụ adapter không gộp: `vllm serve google/gemma-4-12B-it --enable-lora --lora-modules
gemma-12b=ckpt/lora_v1 --max-lora-rank 16`. Luật cuộc thi: tổng tham số ≤ 15B (12B + LoRA gộp vẫn là 12B).

## 5. Đánh giá

Đo bằng agent thật trên các câu của shop giữ riêng (repo DataMate v4, model đã serve như trên):

```
PY=python; export PYTHONIOENCODING=utf-8 PYTHONPATH=src:.
IDS=$($PY -c "import json; print(' '.join(json.loads(l)['id'] for l in open('<package>/val_questions.jsonl') if json.loads(l)['split'] == 'data/train'))")
$PY -m datamate.runner --split data/train --ids $IDS --allow-large --out outputs/runs/sft_val --config config.yaml
```

So với model gốc chạy cùng lệnh, cùng thời điểm. `val_questions.jsonl` gồm cả câu teacher làm sai, nên điểm này không
bị lệch về phía câu dễ. Kiểm tra package (trong repo): `python -m gen.validate <package> [--rebuild --replay]`.
