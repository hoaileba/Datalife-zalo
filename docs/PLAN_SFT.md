# Plan: gói dữ liệu SFT cho model agent (Gemma 4 12B, LoRA)

Mục tiêu: **một thư mục giao cho người khác train ngay** (dữ liệu + README + script train + kiểm tra). Ba bước, cùng
một định dạng gói:

1. **Bước 1 (xong code, chờ cho phép chạy teacher):** 3000 câu train gốc → teacher DeepSeek (`gen.teacher`) → gói SFT
   (`gen.package`).
2. **Bước 2:** reskin shop train (đã có mẫu, không gọi API) và biến thể rulebook (split sẵn, chờ teacher), §3.
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

## 3. Bước 2: augmentation trên shop train

Vấn đề: chỉ 30 shop (mỗi shop ~100 câu, cùng tên bảng/cột/nhãn) và một rulebook duy nhất → học sinh có thể học thuộc
shop thay vì đọc catalog, và không bao giờ phải đọc rulebook. Hai hướng đã làm (chưa gọi API nào):

### 3.1 Reskin shop train (không cần teacher)

| File | Làm gì |
|---|---|
| `gen/shopio.py` | đọc/ghi file của shop dạng lưới ô (CSV giữ dialect/BOM, XLSX qua calamine + `gen/xlsx.py`, SQLite giữ kiểu cột). Ghi lại nguyên trạng: 30/30 shop đọc ra bảng giống hệt |
| `gen/reskin.py` | mỗi bản sao: đổi tên file/sheet/bảng SQLite (cụm từ đồng nghĩa, kiểu tên KiotViet/MISA/snake/có dấu), tên cột (bộ đồng nghĩa cùng nghĩa, giữ kiểu tên gốc: CamelCase, snake, không dấu), nhãn trạng thái/thanh toán (cùng loại, cùng nhóm `label_groups` mà agent tự tính, một kiểu cho cả shop), xáo thứ tự cột, viết lại README theo mức `full`/`partial`/`brief` (bỏ mô tả cột "trơn", giữ mô tả có thông tin riêng và mọi quy ước). Kiểm: `load_business` đọc 0 file lỗi, mọi bảng bằng bảng gốc sau ánh xạ tên/nhãn (cùng dòng, giá trị, dtype, dòng bị bỏ, `label_groups`); sai thì hoàn tác phần gây sai và ghi lại |
| `gen/remap.py` | ánh xạ cũ → mới trong code teacher (chỉ chuỗi literal, f-string, comment, `df.cột`), lập luận (tên trong nháy/backtick/đậm; tên "đặc biệt" như snake/CamelCase/viết hoa/nhiều chữ không đứng đầu câu), README, gold (nhãn trong đáp án). Tên không đổi của shop được bảo vệ (`keep`: "trả hàng" trong nhãn "Đã trả hàng" không bị thay). `stale()`: còn tên/nhãn cũ → bỏ mẫu |
| `gen/reskin_replay.py` | mỗi record đúng của teacher → chạy lại **chính vòng `solve`** trên bản sao, model là kịch bản các câu trả lời teacher đã ánh xạ: prompt là đúng prompt agent gửi trên bản sao, quan sát (explore, lỗi, kiểm tra) là kết quả thật trên dữ liệu bản sao. Giữ khi cùng số lượt, cùng trạng thái từng lượt, cùng loại đáp án và đúng gold. Ra một thư mục run teacher (`teacher_record/v1`) mà `gen.package` nhận như mọi run. Thinking của teacher không chép |
| `gen/package.py` | thêm `--per-group N` (tối đa N record mỗi nhóm câu và mỗi rulebook; run liệt kê trước thắng) |
| `tests_gen/test_reskin.py` | ánh xạ code/văn bản, `keep`, khoá cột có dấu, round-trip, reskin 3 shop thật (CSV/SQLite/XLSX theo tháng), end-to-end teacher giả → reskin → replay → gói → `validate --rebuild --replay`, `--per-group`, shop giữ riêng |

Quyết định:
- **Explore và lượt sửa lỗi giữ lại**, vì không ánh xạ quan sát bằng tay: `solve` chạy lại từng lượt trên bản sao nên lịch sử là output thật. Lượt nào lệch (bản sao báo lỗi ở chỗ bản gốc chạy được, hay ngược lại) thì bỏ cả record.
- **Không đổi**: câu hỏi, tên hàng/khách (đáp án và data_lookup dựa vào), nhãn mơ hồ (`đã lấy`, `ok`, `Đang xử lý`, `Đang giao dịch`, `đang gửi`, `Không giao được`: lập luận teacher bàn về chúng), số liệu. Cột/tên có hai nghĩa trong train (vd "Trạng thái" của đơn và của khách) chỉ đổi sang tên chung.
- Bản sao giữ `business_id` và id câu (nhóm = id gốc, `meta.jsonl` có `orig_id`), nên shop giữ riêng (biz_108/110/130) và mọi bản sao của nó đều sang val; `val_questions.jsonl`/`val_ids.txt` trong mỗi bản sao để đo học thuộc (PA trên shop val gốc so với bản reskin).
- Một bản sao = một split đầy đủ (`data_gen/reskin_<k>/`, 2 bản, ~185 MB mỗi bản).

Số liệu (2 bản, seed 0): 30/30 shop đạt kiểm tra ở cả 2 bản, 0 hoàn tác; mỗi bản đổi ~770 cột, ~141 nhãn, 127 file, ~180 sheet, 135 bảng, ~205 sheet xáo cột; README full/partial/brief = 15/11/4 và 16/11/3; 0 câu bỏ (không đáp án nào là tên cột/nhãn bị đổi). Replay từ train_v1 (+ smoke, try6; 2984 câu có record đúng, 2978 trong split): giữ **2936/2978** (bản 1) và **2932/2978** (bản 2); bỏ: lệch (cần thêm lượt) 20/26, lệch trạng thái lượt 12/12, còn tên cũ 10/8, sai gold 0/0. ~9 phút/bản, đỉnh ~4.1 GB RSS (4 luồng, một shop một lúc).

### 3.2 Biến thể rulebook trên 5 shop đã hiệu chỉnh (cần teacher)

`gen/rule_variants.py` → `data_gen/rulevar_<biến thể>/` (rulebook = biến thể, data = link sang bản reskin của shop để 5 shop
không giống nhau ở mọi biến thể), `meta.jsonl` (`orig_id`, `intent`, `variant`, `changed`, `source` train|generated, `reskin`),
tổng hợp ở `data_gen/rulevar_summary.json`. Câu: câu train của shop (oracle luật mặc định phải bằng gold train) + câu sinh
(`gen.questions`, viết bằng `gen.surface`, phải parse lại ra cùng đáp án). Gold = oracle với luật biến thể. Chọn ~75% câu
bị luật đổi đáp án, ~25% không đổi. Với `returns_count`/`delivering_out` bỏ các intent mà oracle dùng chung tập đơn hợp lệ
nhưng dòng luật riêng của chúng không đổi (bán chạy, ế, hiệu ứng tăng giá, lãi gộp, tồn...): gold sẽ mâu thuẫn rulebook.
Bộ nhớ: ~2.2 GB đỉnh mỗi biến thể (đo bằng `/usr/bin/time -v`); chạy mỗi biến thể một process (summary gộp).

| Split | Câu | Đổi | Không đổi |
|---|---|---|---|
| week_sunday | 123 | 92 | 31 |
| returns_count | 220 | 165 | 55 |
| delivering_out | 184 | 138 | 46 |
| revenue_shipping | 156 | 117 | 39 |
| revenue_voucher | 220 | 165 | 55 |
| cancel_rate_no_returns | 220 | 165 | 55 |
| this_month_full_prev | 39 | 29 | 10 |
| tet_short | 4 | 3 | 1 |
| shifts_split | 220 | 165 | 55 |
| avg_purchase_simple | 44 | 33 | 11 |
| pct_one_decimal | 220 | 165 | 55 |
| paraphrase (diễn đạt lại, đáp án chuẩn) | 220 | 0 | 220 |
| **Tổng** | **1870** | **1237** | **633** |

Kiểm pipeline (mọi split): `load_rulebook` liệt kê đúng dòng đổi (1–2 dòng; paraphrase 6), mọi đoạn mới của biến thể có
trong `rulebook_changes`, không split nào thành "rewrite", system prompt khác train (bỏ công thức của dòng đổi),
catalog của shop có `rulebook_changes`, 0 file không đọc được.

Diễn đạt lại rulebook (`gen/variants.py`): `paraphrase_format` (bảng → gạch đầu dòng, bỏ đậm, huỷ/hủy, nháy cong) cho
**0** `rulebook_changes` (test). `paraphrase_words` (6 dòng đổi chữ, cùng nghĩa) cho **6** thay đổi "giả": `datamate.rules`
so theo chữ, nên một rulebook viết lại câu chữ sẽ mất công thức của các dòng đó và hiện chúng trong `rulebook_changes`.
Không sửa được ở `src/` lúc này; split `rulevar_paraphrase` dạy đúng tình huống này (dòng "đổi" nhưng đáp án như chuẩn).

Ước lượng teacher (`gen.teacher --dry-run`, 16 workers): 1870 câu, ~2056 lượt gọi, ~54 phút, ~1.6 USD (giá giả định
0.07/0.007/0.28). Đề xuất chạy tất cả (1.9k câu; bỏ `tet_short` nếu muốn, chỉ 4 câu).

### 3.3 Lệnh

```
PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python; export PYTHONIOENCODING=utf-8 PYTHONPATH=src:.
# (đã chạy) bản sao + kiểm tra, ~4 phút, ~0.8 GB
$PY -m gen.reskin --out data_gen --copies 2 --workers 3
# (đã chạy) mẫu trên bản sao, không gọi API, ~9 phút/bản, ~4.1 GB đỉnh; --resume khi có record teacher mới
for k in 1 2; do $PY -m gen.reskin_replay --teacher outputs/teacher/train_v1 outputs/teacher/smoke outputs/teacher/try6 \
    --split data_gen/reskin_$k --out outputs/teacher/reskin_$k --workers 4; done
# gói: gốc + 2 bản (mỗi câu tối đa 3 record; --per-group 2 để nhẹ hơn)
$PY -m gen.package --teacher outputs/teacher/train_v1 outputs/teacher/reskin_1 outputs/teacher/reskin_2 --out outputs/sft/train_v1_reskin
$PY -m gen.validate outputs/sft/train_v1_reskin --rebuild --replay
# đo học thuộc sau train: agent trên shop val gốc và bản reskin
#   data/train + ids của biz_108/110/130 (val_questions.jsonl của gói) và data_gen/reskin_<k> + val_ids.txt
# (đã chạy) biến thể rulebook, mỗi biến thể một process
for v in week_sunday returns_count ... paraphrase; do $PY -m gen.rule_variants --out data_gen --variants $v \
    --reskin data_gen/reskin_1,data_gen/reskin_2; done
# CẦN NGƯỜI DÙNG CHO PHÉP: teacher trên các split biến thể (~1.6 USD, ~1 giờ ở 16 workers)
for s in data_gen/rulevar_*/; do n=$(basename $s); $PY -m gen.teacher --split $s --out outputs/teacher/$n --all \
    --workers 16 --concurrency 16 --price 0.07,0.007,0.28 --max-usd 1 --yes; done
$PY -m gen.package --teacher outputs/teacher/train_v1 outputs/teacher/reskin_1 outputs/teacher/reskin_2 outputs/teacher/rulevar_* --out ...
```

Rủi ro / chưa kiểm:
- Bản reskin chỉ đổi tên, không đổi bố cục hay dữ liệu: học sinh vẫn có thể nhớ số liệu, giá trị cột, tên hàng của 30 shop.
- README mức `brief`/`partial` bỏ mô tả cột trơn, nhưng lập luận teacher có thể vẫn nhắc nghĩa cột lấy từ README gốc.
- Đồng nghĩa cột/nhãn chọn tay: có thể còn cặp lệch sắc thái; kiểm bằng máy chỉ đảm bảo gold không đổi.
- Gold biến thể đúng theo oracle; oracle chỉ được xác nhận với luật mặc định (591/591), chưa với luật biến thể.
- `paraphrase_words`: `rules.compare` coi diễn đạt lại là thay đổi (nêu trên).
- ~1.3% mẫu reskin (36 + 38) có nhãn viết thường không nháy trong một danh sách nhãn ("trả hàng (trả hàng, Đã trả hàng)", "cancel") vẫn là nhãn cũ: lập luận nhắc một nhãn không còn trên bản sao (stale check không bắt; code và đáp án đúng).
- Chưa đo trên học sinh: lợi ích của reskin/biến thể chỉ biết sau khi train và đo val gốc vs val reskin.

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

### 4.1 syn_v2 (12/11, Hướng 3: ngành mới, rulebook riêng; chưa gọi API)

Private test có ngành không có trong train/public và **rulebook riêng** của bộ (docs/zac/data.md). Một split dùng chung
một rulebook, nên `syn_v2` là 8 split con, mỗi split một rulebook do `gen/rulebook_gen.py` ghép:

| Thành phần | Nội dung |
|---|---|
| Ngành mới (`gen/assets/new_industries.yaml`) | +6: `fruit_shop` (bán theo ký, số lượng lẻ 1,35 kg), `fashion` (size trong tên `... size M`), `milk_tea` (size (M)/(L) + topping), `spa_salon` (dịch vụ, 5 kỹ thuật viên), `hotpot` (bàn, khu vực, số khách, khăn lạnh), `phone_shop`; ngành cũ thêm: `motorbike_repair` có biển số xe, `mother_baby`/`cosmetics`/`agri_supply` có lô + hạn dùng; nhà hàng tổng hợp có bàn/số khách. Shop ngành mới giữ 60–95 % danh mục |
| Sổ cái / xuất file | bảng `visits` (bàn, khu vực, số khách, biển số) → cột trong danh sách hoá đơn, không có thì lặp ở mọi dòng hàng (README ghi rõ); SQLite có bảng `luot_phuc_vu`. Rulebook tính phí giao / voucher đơn vào doanh thu → file luôn có cột phí giao / giảm giá đơn (`add_money_columns`), không dùng họ B. Mỗi đơn mỗi mặt hàng một dòng (hai dòng giống hệt là lỗi xuất file theo §8) |
| Rulebook của split | rulebook train + mục §6 cho ngành có mặt (bàn/khách, dịch vụ/tiền công, xe quay lại, size chữ, trà sữa, hàng cân ký, vụ Đông Xuân/Hè Thu, mùa tựu trường, hàng có hạn dùng, topping/khăn lạnh) với định nghĩa thay thế; luật mặc định đổi gán theo split (`gen/build_v2.py` FORCE: mọi biến thể của `gen/variants.py` + 3 mới — bán chạy theo doanh thu, N ngày gần nhất không gồm hôm nay, Tết từ 25 Chạp); bỏ mục ngành train vắng mặt; diễn đạt lại cùng nghĩa; `val` viết lại toàn bộ (agent nhận cả văn bản + cả cookbook). Mọi nghĩa đổi là một trường `Rules`, gold theo đúng chữ; `meta.jsonl` có `moved` (luật đổi làm đổi đáp án) |
| Ý định mới (`gen/oracle.py`) | `guests_total`, `revenue_per_guest`, `area_revenue`, `top_table`, `service_revenue` (+ phần hàng hoá), `service_share`, `vehicle_count`, `repeat_vehicles`; `qty_size` cho size chữ; hạn dùng cho ngành có lô; kỳ `season`. Chỉ hỏi khi rulebook của split có mục tương ứng (`questions.allowed`) |
| Câu hỏi (`mix='train'`) | loại kỳ theo tỉ lệ đo trên train; họ định dạng phân tầng theo tỉ lệ train; không hỏi số đơn khi file không có mã đơn; gần như không có đáp án 0; không lặp câu kỳ tuyệt đối ở as_of khác; bỏ câu có hoà trong top k; "so với tháng trước" để rulebook quyết; câu hiệu ứng tăng giá chỉ nêu giá mới khi file thấy được ngày tăng; câu không trả lời được riêng từng ngành |

Split (`data_gen/syn_v2`, 71 shop, 4615 câu, ~8 phút dựng với 3 tiến trình, đỉnh 2 GB): t1 (rulebook train + mục ngành),
t2–t5, t7 (luật đổi), t6 (diễn đạt lại nhiều + luật đổi), mỗi split 9 shop × 65 câu; `val` (8 shop `hotpot` +
`spa_salon`, luật đổi và định nghĩa mục riêng không có ở split train nào, rulebook viết lại toàn bộ, chủ yếu họ P). Họ P
chỉ có ở `val` và 2 shop của t5 (họ giữ riêng trên ngành đã thấy). Chi tiết: `manifest.json`.

Kiểm (không gọi model, `scripts/check_syn.py`, bản dựng cuối): 0/71 shop có file không đọc được; gold so với lời giải
pandas độc lập trên bảng của reader (không dùng code oracle): **2280/2280** khớp (18 ý định, đủ 10 họ); kiểu đáp án
number 61 % / percent 22 % / date 6 % / list 5 % / string 3 % / unanswerable 3 % (train 63/19/5/6/3/2); kỳ "tháng" 55–62 %
(train 64 %); nhiễu câu hỏi khớp train; 13 đáp án 0; 1072 câu có đáp án đổi theo chữ của rulebook split (`moved`); token
lượt đầu (tokenizer Gemma thật, 710 câu) p50 13.6k, p99 20.8k, max 20.9k < 24576 (val dài nhất: nhận cả rulebook +
cookbook). Reviewer độc lập: vòng 1 NOT PROUD (voucher/phí giao không có trong file, câu số đơn trên file không mã đơn,
"so với tháng trước", tăng giá không thấy ngày, tồn đơn vị lớn, hoà trong list), vòng 2 ALMOST (bản dựng cũ, cột tiền
lộ luật, lệch tỉ lệ percent), đã sửa hết; vòng 3 **PROUD** (230/230 gold tự tính lại khớp, t5/t7/val dựng lại giống từng byte, `moved` khớp). Lưu ý: tín hiệu luật đổi của val chỉ 65/520 câu; danh mục ngành mới nhỏ (15–31 mặt hàng).

Lệnh:
```
$PY -m gen.build_v2 --out data_gen/syn_v2 --jobs 3                       # không gọi API, ~8 phút
$PY scripts/check_syn.py data_gen/syn_v2/{t1,t2,t3,t4,t5,t6,t7,val} --what load,cross,dist,tokens --sample 1000
# CẦN NGƯỜI DÙNG CHO PHÉP (DeepSeek, 16 luồng): mỗi split ~585 câu ≈ 650 lượt, ~17 phút, ~0.5 USD (giá giả định)
for s in t1 t2 t3 t4 t5 t6 t7 val; do
  $PY -m gen.teacher --split data_gen/syn_v2/$s --out outputs/teacher/syn_v2_$s --config config.deepseek.yaml \
      --all --workers 16 --concurrency 16 --price 0.07,0.007,0.28 --max-usd 1.5 --yes; done
$PY -m gen.package --teacher outputs/teacher/train_v1 outputs/teacher/syn_v2_* --out outputs/sft/v2 \
    --val-industries hotpot,spa_salon --val-families P
```

## 5. Bàn giao: danh sách kiểm
- `gen.validate <gói> --rebuild --replay` sạch; `stats.json` không có `prompt.drift`, `tokens.exact = true`.
- README của gói ghi đúng số mẫu, max_len, shop val; `sft_lora.py --dry-run` chạy được trên máy người train.
- Không có mẫu từ `public_test`/`private_test` (gói từ chối khi dựng, validator kiểm lại nguồn từng mẫu).
- Ghi lại commit của code agent: gói chỉ đúng với prompt của commit đó (`stats.json` → `git`).
