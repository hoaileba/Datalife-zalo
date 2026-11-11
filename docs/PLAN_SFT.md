# Plan: gói dữ liệu SFT cho model agent (Gemma 4 12B, LoRA)

Mục tiêu: **một thư mục giao cho người khác train ngay** (dữ liệu + README + script train + kiểm tra). Ba bước, cùng
một định dạng gói:

1. **Bước 1 (xong code, chờ cho phép chạy teacher):** 3000 câu train gốc → teacher DeepSeek (`gen.teacher`) → gói SFT
   (`gen.package`).
2. **Bước 2 (kế hoạch):** augmentation trên shop train: câu hỏi, README, tên bảng/cột/file, rulebook, dữ liệu.
3. **Bước 3 (kế hoạch):** shop tổng hợp, ngành mới (`gen.build`).

Liên quan: `docs/PLAN_TRAINDATA.md` (thiết kế bộ sinh, §7 trạng thái), `docs/TEACHER_GEN.md` (chạy teacher).

## 1. Định dạng (dùng chung cho cả 3 bước)

Một mẫu = một lượt model của agent v4:

```
{"id": "<run>/<question id>/s<sample>/t<turn>",
 "prompt": [system, user, (assistant, user)*],            # đúng chuỗi message agent gửi ở lượt đó
 "completion": [{"role": "assistant", "content": "Answer type: ...\n<lập luận>\n```python\n...\n```"}],
 "meta": {...}}                                           # trong gói: tách ra <side>_meta.jsonl cùng thứ tự dòng
```

- `prompt` dựng bằng code agent hiện tại (`prompt.messages` trên catalog, data lookup và lịch sử đã ghi), nên khớp
  từng byte với lúc suy luận. Completion là `prompt.render_action` của action đã parse (dạng chuẩn hoá agent cũng dùng
  khi đưa lượt cũ vào lịch sử). Không có thinking của teacher.
- Loss chỉ trên completion. Các lượt assistant cũ trong prompt (có thể là lượt hỏng) không có loss.
- Mẫu giữ lại: lượt cuối của câu trả lời đúng gold, cộng lượt `explore` chạy sạch trước đó; lượt phải kết thúc bình
  thường (`finish = stop`).

Gói (`python -m gen.package --teacher <run...> --out <dir>`):

| File | Nội dung |
|---|---|
| `train.jsonl`, `val.jsonl` | `{"id", "prompt", "completion"}` |
| `train_meta.jsonl`, `val_meta.jsonl` | `key` = `id`; `id` câu, `group`, `shop`, `split`, `run_path`, `record`, `turn`, `final`, `answer_type`, `gold_type`, `intent`/`industry`/`family`, `weak`, `recovered`, `prompt_drift`, `prompt_tokens`/`completion_tokens`/`total_tokens`, `tokens_exact`, câu hỏi, `as_of` |
| `val_questions.jsonl` | mọi câu của shop/nhóm giữ riêng (kể cả câu teacher làm sai): để đo agent sau train |
| `stats.json` | nguồn (run, split, teacher), tuỳ chọn, số bị bỏ ở từng bộ lọc, phân bố, độ dài, sha256 file, kết quả kiểm tra |
| `README.md` | (tiếng Việt) dữ liệu là gì, cách train, siêu tham số, bộ nhớ GPU, gộp + serve vLLM, đánh giá |
| `sft_lora.py` | bản sao `train/sft_lora.py` |

Khoá nhóm (chống rò rỉ train/val): `group` = `orig_id` do bộ sinh ghi (meta.jsonl hoặc questions.jsonl), không có thì
`q_aug<k>_<x>` → `q_<x>`, còn lại là chính id. Khoá shop: thư mục dữ liệu thật (symlink đã giải); `--val-shops` nhận id
trần (`biz_108` khớp mọi split có thư mục `.../biz_108`, kể cả bản sao đã augment) hoặc đường dẫn.

## 2. Bước 1: trạng thái và cách chạy

### Code (chưa commit)

| File | Làm gì |
|---|---|
| `gen/sft.py` | định dạng mẫu duy nhất; `teacher_turns` (lượt nào giữ, vì sao bỏ), `teacher_samples`, `weak_flags`, `group_of`, `history_of`; `export_teacher` = gói của một run (prompt đã ghi) |
| `gen/package.py` | gói giao tay: gộp nhiều run, chọn record tốt nhất mỗi câu, dựng lại prompt, đếm token Gemma, lọc, chia train/val, README, kiểm tra |
| `gen/validate.py` | kiểm tra gói (định dạng, nguồn gốc, completion parse được, prompt đúng câu hỏi, độ dài, rò rỉ nhóm/shop, hash); `--rebuild` so prompt với code hiện tại; `--replay` chạy lại chương trình cuối, so gold |
| `gen/tokens.py` | đếm token đúng như học sinh thấy (chat template Gemma 4, thinking tắt); không có `tokenizers`/`jinja2` thì ước lượng (luôn dư) |
| `gen/assets/sft_package_readme.md` | mẫu README của gói |
| `train/sft_lora.py` | train LoRA: tự tokenize (không dùng đường prompt-completion của TRL), loss chỉ trên target, `logits_to_keep`, `--dry-run`, `--max-steps`, `--merge` |
| `gen/teacher.py` | `--resume` chạy lại record lỗi API/host (`--retry`); xuất `<run>/sft/` ở luồng nền mỗi 200 record; `--dry-run` in ước lượng token và USD |
| `gen/mix.py` | thay bằng lời nhắn trỏ sang `gen.package` (định dạng cũ không còn ai ghi) |
| `scripts/train_intents.py` | đường dẫn theo repo (để `gen.package` import được) |
| `tests_gen/test_package.py` | chạy `gen.teacher` thật với model giả theo kịch bản trên split tí hon (không API): explore, sửa lỗi, trả lời không đọc được, xác nhận, sai, unanswerable, lỗi API + `--resume`, câu augment, shop giữ riêng, quá dài, thiếu system prompt, prompt lệch, gói bị sửa tay |

### Quyết định và lý do

| Điểm | Quyết định | Lý do |
|---|---|---|
| Định dạng | prompt-completion, meta tách file | `gen.mix` cũ đọc `messages`/`meta` không ai ghi (KeyError); `sft_lora` cũ dùng `messages` + `assistant_only_loss` → loss cả trên lượt hỏng trong lịch sử, và template Gemma không có `{% generation %}` |
| Tokenize | tự làm trong `sft_lora.py` | Gemma 4 với thinking tắt mở lượt model bằng `<|channel>thought\n<channel|>`; render prompt+completion thì không có đoạn này, nên prompt của TRL không phải tiền tố (đã kiểm bằng template thật: lệch ở 15/15 mẫu). Target = nội dung + `<turn|>` (id 106, vLLM dừng ở đây) |
| Prompt | `--prompts current` (mặc định) | học sinh phải thấy đúng prompt lúc suy luận. Khi code agent đổi sau lượt teacher, prompt được dựng lại và gắn cờ `prompt_drift` (`--drop-drift` để bỏ). Trên smoke + try6: 15/15 giống hệt bản đã gửi |
| `max_len` | 24576, bỏ mẫu dài hơn (không cắt) | lượt 0 của cả 3000 câu train: p50 13.6k, p90 16.8k, p99 18.4k, max 18.9k token Gemma (system prompt 9.3k); lượt 2–3 cộng lịch sử khoảng 1–5k; completion 300–800 |
| Val | giữ riêng cả shop `biz_108` (KiotViet, họ E), `biz_110` (CSV hoá đơn một file), `biz_130` (MISA, họ F): 277 câu (9%) | test là shop khác hẳn train; đo trên shop chưa thấy mới có ý nghĩa. Không lấy 5 shop đã hiệu chỉnh oracle (bước 2 cần chúng). `val_questions.jsonl` có cả câu teacher làm sai → điểm PA không lệch. Bản cuối có thể train lại trên train + val (hoặc `--val-shops none`) |
| Nhãn yếu | giữ, gắn cờ `weak` | `unanswerable` chỉ chấm theo loại (70 câu, 2.3%), `boolean` là tung đồng xu (23 câu, 0.8%), `zero` (kết quả 0 có thể do lọc trượt), `no_program`. Ít, và bỏ đi sẽ dạy model không bao giờ nói unanswerable (mà câu đó +1 điểm). Bỏ được bằng `--drop-weak` |
| Nhiều record một câu | `--per-question 1`: giữ record ít lượt gọi nhất, ít lượt hỏng nhất | `--samples > 1` ở temperature 0 cho bản gần trùng; gộp nhiều run cũng vậy |
| Trùng | bỏ mẫu cùng prompt + cùng completion (bỏ khoảng trắng) | |
| Explore | giữ (tắt bằng `--no-explore`) | chỉ giữ explore chạy sạch của câu cuối cùng đúng; lượt cuối vẫn thấy kết quả explore trong lịch sử |
| Cân bằng intent | không cap mặc định; `--cap-intent N` có sẵn | phân bố train gần phân bố test; `stats.json` in phân bố intent (36 nhóm từ `scripts/train_intents.py`; revenue 687/3000) |

### Lệnh

```
PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python; export PYTHONIOENCODING=utf-8 PYTHONPATH=src:.

# 0. Một lần: đếm token chính xác (không bắt buộc; thiếu thì ước lượng dư)
$PY -m pip install tokenizers jinja2          # nhỏ, không kéo numpy; CHƯA cài vào pd22 (cần người dùng đồng ý)
$PY -m gen.tokens --fetch                     # đã tải sẵn: outputs/tokenizers/gemma-4-12B-it (32 MB, không có trọng số)

# 1. Ước lượng (không gọi model)
$PY -m gen.teacher --split data/train --out outputs/teacher/train_v1 --all --dry-run

# 2. CẦN NGƯỜI DÙNG CHO PHÉP: teacher trên 3000 câu train
$PY -m gen.teacher --split data/train --out outputs/teacher/train_v1 --all --workers 8 \
    --price 0.07,0.007,0.28 --max-usd 6 --yes
#    bị ngắt / hết tiền / API lỗi: cùng lệnh + --resume (record llm_error/host_error chạy lại)
$PY -m gen.teacher_stats outputs/teacher/train_v1 --price 0.07,0.007,0.28

# 3. Gói giao tay (không gọi model; đo trên 300 record giả: 45 giây, 2.4 GB RAM → khoảng 5 phút cho 3000)
$PY -m gen.package --teacher outputs/teacher/train_v1 --out outputs/sft/train_v1
$PY -m gen.validate outputs/sft/train_v1 --rebuild --replay       # kiểm sâu (sandbox chạy lại ~3000 chương trình)

# 4. Phía người train (máy có GPU): xem README.md trong gói
python sft_lora.py --data . --model google/gemma-4-12B-it --dry-run
```

Gói mẫu dựng từ hai lượt nhỏ đã có: `outputs/sft/demo_smoke_try6` (13 train / 2 val).

### Ước lượng lượt teacher 3000 câu (`--dry-run`, 11/11)

| | Giá trị | Nguồn |
|---|---|---|
| Lượt gọi | ~3300 (1.1/câu) | p1000 + smoke/try6 |
| Thời gian | ~2.9 giờ với 8 request song song (~25 giây/lượt); `--concurrency 16 --workers 16` khoảng 1.5 giờ nếu API chịu | smoke: 6 câu 46 giây |
| Token | prompt ~53M (~95% cache hit), output ~7.2M (gồm thinking) | smoke + try6: 17.7k prompt, 2.4k output mỗi câu |
| Chi phí | ~2.5 USD theo giá giả định 0.07/0.007/0.28 USD mỗi 1M; p1000 thực tế 1.1 USD/1000 câu → ~3.3 USD. Đặt `--max-usd 6` | số dư 9.04 USD (11/11) |
| Mẫu SFT dự kiến | giả sử teacher đúng 85–90% (chưa đo trên đủ 3000 câu) → ~2600 câu đúng → ~2900 mẫu (explore ~10%); train ~2650, val ~250 | |

### Kiểm tra sau lượt chạy thật
1. `stats.json` của gói: `dropped_records` (wrong/abstain), `dropped_samples.too_long` (kỳ vọng ≈ 0), `prompt.drift`
   (kỳ vọng 0 nếu không sửa `src/` giữa chừng), phân bố `gold_type` và `intent` so với train.
2. `gen.validate --rebuild --replay` sạch.
3. Đọc tay 20 mẫu (`scripts/prompt_md.py --record ...`), ưu tiên `recovered`, `weak`, explore.
4. Người train chạy `--dry-run` rồi `--max-steps 5` trước khi chạy thật.

### Chưa kiểm được (máy này không có torch)
- `train/sft_lora.py` chưa từng train: chỉ phần tokenize/`--dry-run` đã chạy (transformers 5.22, tokenizer Gemma 4 thật:
  ranh giới prompt/target đúng, số token khớp `gen.tokens` từng mẫu). Chưa kiểm: lớp model Gemma 4 nạp bằng
  `AutoModelForCausalLM` hay `AutoModelForImageTextToText`, tên lớp LoRA (lọc bỏ tháp vision/audio), `token_type_ids`,
  `logits_to_keep` qua PEFT, `merge_and_unload` + vLLM phục vụ bản gộp đa phương thức.
- Bộ nhớ GPU và thời gian train trong README chỉ là ước lượng.
- Checkpoint gốc: `config.yaml` ghi `google/gemma-4-12B-it`; PLAN_TRAINDATA §4 nhắc gateway từng báo
  `gemma12b-it-checkpoint1200`. Phải train từ đúng checkpoint sẽ nộp, và chat template của nó phải giống bản đã dùng để
  đếm token.

### Rủi ro bước 1
- Chỉ 30 shop: model có thể học thuộc catalog của shop train. Val theo shop đo được điều này; bước 2–3 giảm nó.
- Thiên lệch chọn mẫu: chỉ giữ câu teacher làm đúng → dữ liệu thiếu câu khó. `val_questions.jsonl` đo đúng phần này.
- Teacher đúng do may với nhãn yếu (gắn cờ) và với câu kết quả 0.
- Code agent đổi sau lượt teacher: prompt dựng lại (cờ `prompt_drift`), nhưng completion có thể dùng helper đã đổi:
  `gen.validate --replay` bắt được trường hợp chương trình không còn ra gold.
- `data_gen/private_mock*` không rõ nguồn gốc: không dùng làm dữ liệu train khi chưa xác nhận.

## 3. Bước 2: augmentation trên shop train (kế hoạch)

Nguyên tắc: mỗi augmentation là **một split mới** dưới `data_gen/<tên>/` (`questions.jsonl`, `answers.jsonl`,
`rulebook.md`, `calendar.csv`, `data/`, `meta.jsonl` với `orig_id`, `intent`, `variant`), chạy `gen.teacher` trên split đó
rồi gộp mọi run vào một gói: `gen.package --teacher outputs/teacher/train_v1 outputs/teacher/aug_v1 ...`. Không cần code
mới ở phía gói. Hai luật bắt buộc để không rò rỉ: bản augment **giữ nguyên `business_id`** của shop gốc (shop giữ riêng
khớp theo id) và **ghi `orig_id`** (hoặc đặt id `q_aug<k>_<x>`).

| Hạng mục | Đã có | Còn thiếu | Nhãn |
|---|---|---|---|
| S2a viết lại câu hỏi | `gen/augment_train.py` → `data_gen/train_aug` (3465 câu: bơm lỗi cách viết + diễn đạt lại kiểm bằng oracle trên 5 shop đã hiệu chỉnh), `gen/surface.py` | ghi `orig_id`/`intent` vào `meta.jsonl` (hiện chỉ dựa vào tên id) | gold của câu gốc |
| Câu mới trên shop train (S2b) | oracle khớp 591/591 câu của biz_123/111/127/129/106 | bộ chọn tham số mới (tháng, sản phẩm, ngưỡng, as_of) cho 5 shop đó, dùng `gen/questions.py` trên ledger nạp từ shop train | oracle |
| README augment | `gen/readme.py` (3 mức chi tiết) | `gen/augment_shop.py`: viết lại README (bỏ bớt, đổi thứ tự, đổi cách gọi cột) | gold không đổi (dữ liệu giữ nguyên) |
| Tên file/bảng/sheet/cột | kho đồng nghĩa `gen/pools.py` | cùng `augment_shop.py`: đổi tên file/sheet/cột theo kho đồng nghĩa, cập nhật README cho khớp; kiểm `load_business` đọc được, catalog đổi đúng chỗ | gold không đổi, trừ câu có đáp án là tên cột (không có trong train) |
| Rulebook | `gen/variants.py` (11 biến thể, oracle tham số hoá) | chạy biến thể trên 5 shop đã hiệu chỉnh (hiện chỉ trên shop tổng hợp qua `gen.build --variant`); diễn đạt lại rulebook không đổi nghĩa (kiểm bằng `rules.compare`: không sinh `rulebook_changes` giả) | oracle với luật đổi |
| Dữ liệu (dòng) | ledger loader của 5 shop | thêm nhiễu cấp dòng (`gen/noise.py`) lên shop train đã hiệu chỉnh; chỉ những thay đổi không đổi đáp án, hoặc tính lại gold bằng oracle | oracle |

Thứ tự đề xuất (rẻ và an toàn trước):
1. Ghi `meta.jsonl` cho `train_aug`; chạy teacher trên `train_aug` (3465 câu, ~3.8k lượt, ~3 giờ, ~3 USD; cần cho phép).
   Gói = train_v1 + aug_v1. Thêm `--per-group N` vào `gen.package` (giới hạn số mẫu mỗi nhóm câu, để một câu train
   không nặng gấp 3 lần) và so `eval_loss`/PA với gói chỉ có train_v1.
2. `augment_shop.py` (README + tên): kiểm bằng `load_business` và bằng `gen.validate --replay` trên chương trình teacher
   cũ được ánh xạ tên cột (không cần gọi model để biết augment có phá đáp án không), rồi mới chạy teacher.
3. Biến thể rulebook trên 5 shop đã hiệu chỉnh (dạy đọc `rulebook_changes`).
4. Câu mới (S2b) và nhiễu dòng, sau khi 1–3 cho thấy có ích.

Rủi ro: lệch khỏi phân phối test (augment quá tay); học thuộc 30 shop càng nặng khi mỗi shop có nhiều bản sao; oracle
chỉ đã kiểm trên 5 shop; diễn đạt lại có thể đổi nghĩa câu (S2a đã lọc bằng oracle, bơm lỗi thì không).

## 4. Bước 3: shop tổng hợp và ngành mới (kế hoạch)

Đã có (`docs/PLAN_TRAINDATA.md` §7): `gen/sim.py` (mô phỏng theo ngày), `gen/render.py` (8 họ train + 2 họ mới S, P,
nhiễu, README 3 mức), `gen/catalogs.py` (5 ngành train + 7 ngành mới), `gen/questions.py` (287 khuôn), `gen/oracle.py`
(65 ý định), `gen/build.py` (12 shop × 100 câu trong 2 phút 18 giây). `gen.build` đã ghi `meta.jsonl` với `intent`,
`family`, `industry`, `variant`, id shop `syn_<n>`, nên khớp sẵn với gói: `gen.package --val-industries <ngành>
--val-families <họ>`.

Còn thiếu: họ I (trộn nhiều nguồn) và A′ (một dòng mỗi hoá đơn); nhà hàng chưa có bàn/số khách; một số ý định chưa
được gold xác nhận (net_profit, deliveries_count, stock_big_small, out_of_stock_count); phân bố họ chưa theo train.
Phía gói: `--first-id` khác nhau cho mỗi lần `gen.build` (hiện mặc định 901 → `syn_901` lặp giữa các split; khoá shop
theo thư mục vẫn tách đúng, nhưng `--val-shops syn_901` sẽ khớp mọi split).

Nhãn: teacher đúng theo đáp án oracle. Bất đồng teacher–oracle là tín hiệu chất lượng: oracle hoặc bộ sinh sai, hoặc
teacher sai. Mẫu bất đồng bị bỏ, nên phải xem tỉ lệ đồng ý theo intent trước khi tăng quy mô.

Thứ tự:
1. Lô thử: `gen.build --shops 4 --questions 50` mỗi ngành mới, teacher (~200 câu, cần cho phép), `gen.teacher_stats`:
   tỉ lệ đúng theo intent/họ/ngành. Intent nào < 70% thì đọc tay 10 record (`scripts/prompt_md.py`), sửa oracle/bộ sinh.
2. `syn_v1`: 100 shop × 100 câu (~10.7k lượt, ~8 giờ, ~11 USD), giữ riêng một ngành mới + một họ định dạng làm val.
3. Biến thể rulebook trên shop tổng hợp (`gen.build --variant`, 11 × 4 shop × 50 câu, ~2.5 USD).
4. Gói cuối: train_v1 + aug + syn + var, `--cap-intent` để doanh thu tháng không áp đảo; val = shop train giữ riêng +
   ngành giữ riêng + họ giữ riêng; so PA từng phần.

Rủi ro: shop tổng hợp "dễ" hơn hoặc khác kiểu với test (model học bộ sinh); oracle sai ở ý định chưa kiểm; chi phí
teacher tăng nhanh; tỉ lệ dữ liệu tổng hợp quá cao làm giảm điểm trên phân phối train/test.

## 5. Bàn giao: danh sách kiểm
- `gen.validate <gói> --rebuild --replay` sạch; `stats.json` không có `prompt.drift`, `tokens.exact = true`.
- README của gói ghi đúng số mẫu, max_len, shop val; `sft_lora.py --dry-run` chạy được trên máy người train.
- Không có mẫu từ `public_test`/`private_test` (gói từ chối khi dựng, validator kiểm lại nguồn từng mẫu).
- Ghi lại commit của code agent: gói chỉ đúng với prompt của commit đó (`stats.json` → `git`).
