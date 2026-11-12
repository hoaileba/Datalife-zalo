# Lượt teacher cuối và trộn dữ liệu SFT (12/11)

Mục tiêu: một lượt teacher (DeepSeek flash, `gen.teacher`, `config.deepseek_direct.yaml`) và một lượt LoRA SFT
Gemma-4-12B-it (thinking tắt), nhắm private test (10–20 shop, ~500 câu, **chắc chắn có ngành mới**; rulebook "có thể
khác" giữa các bộ: docs/zac/data.md). Không có lượt thứ hai. Không gọi model nào khi phân tích.

Script: `scripts/sft_mix.py` (`plan` dựng kế hoạch teacher từ split hiện tại; `select` chọn mẫu train từ một gói đầy
đủ). Kế hoạch đã dựng: `outputs/sft_plan/gen_plan.json`, lệnh: `outputs/sft_plan/run_teacher.sh` (chưa chạy).

## 1. Hiện có (đếm lại 12/11 11:25)

| Nguồn | Câu | Đúng | Mẫu train (sau giữ riêng shop val) | Ghi chú |
|---|---|---|---|---|
| `train_v1` (30 shop train, rulebook chuẩn) | 3000 | 2978 (99.3 %) | ~3300 | explore 20.8 % câu, sửa lỗi 3.5 %, 3 lượt 1.2 %, unanswerable 70, đáp án 0: 1 |
| `reskin_1`, `reskin_2` (cùng lời giải, shop đổi tên) | 2936 + 2932 | 100 % (đúng theo cách dựng, log có `outcome=correct`) | ~3250 mỗi bản | cùng hành vi như train_v1 (explore 20.4 %, sửa lỗi 3.2 %) |
| `try100_dir2_*` (rulevar) | 103 | 93 (90 %; trừ `this_month_full_prev` 4/9: 89/94) | — | **không dùng**: gold đổi sau sửa bộ sinh 12/11, lượt cuối hỏi lại cùng id |
| `try100_dir3_*` (syn_v2) | 100 | 97 (97 %) | — | như trên |

Gói thử (`gen.package` trên train_v1 + 2 reskin + try100, `--per-group 3`, không gọi model): train 9960 mẫu, val 916;
pool chuẩn có 9757 mẫu nhưng chỉ **2702 nhóm câu** khác nhau (mỗi câu ×3 bản).

## 2. Pool chưa chạy teacher và giá trị

| Pool | Câu | Shop | Intent | Đa dạng | Quyết định |
|---|---|---|---|---|---|
| `syn_v2/t1..t7` | 3778 | 63 (16 ngành, 6 ngành mới) | 69 (12 intent không có ở train/rulevar: khách/bàn, dịch vụ, xe, lãi ròng...) | câu có "anh em" gần giống trong cùng shop: 10–16 % (train: 32 %); t1 rulebook chuẩn + mục ngành, t2–t7 luật đổi (moved 960 câu) | **chạy hết, ưu tiên 1** (private chắc chắn có ngành mới) |
| `rulevar_*` (12) | 1868 | 5 shop train (data reskin) | 61 | luật đổi trên shop thật; nhưng lặp khuôn cao: `cancel_rate_no_returns` 75 % là cancel_rate, `shifts_split` 42 % shift_revenue; 24–46 % câu có "anh em" gần giống trong cùng shop (3 biến thể đo) | **chạy hết, ưu tiên 2**; cap khi chọn (phân tầng theo biến thể × intent, căn bậc hai) |
| `syn_v2/val` | 519 | 8 (hotpot, spa_salon; họ P) | 39 | luật/định nghĩa không có ở split train nào, rulebook viết lại toàn bộ | **chạy, ưu tiên 3, chỉ để đo** (độ đúng của teacher = trần, bắt lỗi bộ sinh); không train |
| `train_aug` | 3465 | 30 shop train | như train | cùng shop, cùng `as_of`, **cùng gold** với câu train (bản bơm lỗi chính tả + bản đổi khuôn đã kiểm bằng oracle; 3465 sau bỏ trùng); Jaccard 3-gram với câu gốc trung vị 0.78 | **bỏ**: chương trình teacher gần như y hệt; train_v1 + 2 reskin đã cho 3 record mỗi câu; ở ngân sách ≤ 8k mẫu thì cap nhóm sẽ bỏ nó |
| `private_mock*` | | | | | không dùng (nguồn không rõ) |

Biến thể nhỏ (`tet_short` 4 câu, `avg_purchase_simple` 44, `this_month_full_prev` 36): vẫn chạy (rẻ, < 0.15 USD
tổng); `this_month_full_prev` từng lỗi bộ sinh (4/9 đúng) đã được sửa; cổng `sft_mix.py gate` tự bỏ split
< 70 % đúng khỏi gói và intent < 70 % khỏi tập train.

## 3. Lượt teacher đề xuất

Hai script do `scripts/sft_mix.py plan` sinh (chưa chạy):

- `outputs/sft_plan/run_teacher.sh` (giai đoạn 1, **cần người dùng cho phép**): 6165 câu, **~10.4 USD** (try100 đo
  0.0016–0.0017 USD/câu), **~2.7 giờ** với 16 luồng (train_v1: 3000 câu/60 phút; rulevar/syn lâu hơn ~1.3×).
  `set -euo pipefail`; trước mỗi split chạy `sft_mix.py check`: split phải giống **dấu vân tay** lúc lập kế hoạch
  (sha256 của questions/answers/meta/rulebook/calendar + tên, cỡ, mtime mọi file sau `data/` đã giải symlink: bắt cả
  trường hợp gold đổi mà id giữ nguyên như sửa 12/11) và tổng tiền đã tiêu của mọi run trong kế hoạch phải < trần
  chung `total_max_usd` = 14.6 USD (`--max-usd` của `gen.teacher` chỉ tính trong một lần gọi, resume là đếm lại; trần chung chỉ kiểm giữa các split nên trần thật ≈ 14.6 + `--max-usd` của một split ≈ 16.6 USD).
- `outputs/sft_plan/package_and_select.sh` (giai đoạn 2, không gọi model): `sft_mix.py gate` (mọi run đủ câu, record `llm_error`/`host_error` coi là chưa xong, abstain ≤ 3 %, split
  không đổi; độ đúng teacher theo split và theo (split, intent): split < 70 % thì dừng (trừ khi `--allow-drop`), intent < 70 % với ≥ 8
  câu trong split hoặc gộp mọi split của pool bị `select` bỏ; thoát 1 thì dừng) → `gen.teacher_stats` → một gói đầy đủ → `gen.validate --rebuild --replay`
  → `select` cho 3k/5k/8k.

Thứ tự ưu tiên (bị ngắt thì phần đầu đã có ích nhất):

1. `syn_v2/t1..t7` 3778 câu (~6.4 USD, ~1.6 h): shop chưa thấy, ngành mới (chắc chắn có ở private)
2. `rulevar_*` 1868 câu (~3.2 USD, ~0.8 h): luật đổi trên dữ liệu thật
3. `syn_v2/val` 519 câu (~0.8 USD, ~0.2 h): chỉ để đo (trần teacher, bắt lỗi bộ sinh); không train

Sản lượng dự kiến: syn ~95 % đúng × ~1.25 mẫu/câu ≈ 4.5k mẫu, trừ 130 câu họ P của t5 sang val → **~4.3k mẫu
train**; rulevar ~93 % × ~1.2 ≈ **~2.0k mẫu**.

Trước khi chạy:
- **Số dư DeepSeek: 1.12 USD** (lần ghi cuối: `try100_dir3_val/summary.json`, 08:41 12/11). Cần nạp **≥ 15 USD**
  (ước lượng 10.4 + dư 40 %); giá thật có thể khác giá giả định 0.07/0.007/0.28.
- Agent kia đã dựng lại `rulevar_*` (10:41–11:10) và `syn_v2` (11:12–11:18; t1–t7 đổi số câu, ví dụ t3 585 → 457).
  **Đóng băng** `src/`, `gen/`, `data_gen/` (commit), rồi chạy lại `scripts/sft_mix.py plan` ngay trước giai đoạn 1
  (dấu vân tay lấy lúc đó).
- Bị ngắt / hết tiền / API lỗi: chạy lại đúng `run_teacher.sh` (thêm `--resume` khi thư mục đã có log; `gen.teacher`
  bỏ qua record đã xong, chạy lại `llm_error`/`host_error`).

## 4. Gói và chọn mẫu (`select`)

Quy tắc (tất định theo `--seed`, chạy lại được trên gói mới):
- **Pool** theo split: `std` (data/train + reskin), `rule` (rulevar), `syn` (syn_v2 t1–t7). Không bao giờ chọn
  syn_v2/val, train_aug, run `try*/demo*/smoke`, split test (dừng nếu gặp). Với `--gate`: bỏ run/intent trượt cổng.
- **Đơn vị chọn = một record** (lượt explore + lượt cuối đi cùng nhau); ngân sách đếm theo mẫu.
- **std**: mỗi câu một bản shop trước (gốc/reskin_1/reskin_2 xoay theo hash: học đọc catalog chứ không thuộc tên);
  hành vi hiếm vào trước (sửa lỗi, 3 lượt, đáp án 0, unanswerable, không chạy chương trình; tối đa 15 % quota std);
  chỉ sửa lỗi/3 lượt/đáp án 0 được thêm bản shop thứ hai (unanswerable thì không: chỉ chấm theo loại, nhân đôi sẽ
  đẩy model hay nói unanswerable); phần còn lại phân tầng theo intent với trọng số `n^0.7` (revenue 21 % → ~18 %);
  dư thì thêm bản thứ hai.
- **rule**: `paraphrase` ≤ 12 % pool, câu luật không đổi đáp án 18 % (đối chứng: đọc `rulebook_changes`, thấy không
  áp dụng), còn lại câu bị đổi; phân tầng (biến thể × intent) `n^0.5`. 55 % câu rulevar là câu train y nguyên chữ và
  `as_of` (trên dữ liệu reskin); những câu **không** đổi đáp án là bản gần trùng của std → tối đa 3 record mỗi câu
  train tính chung std + rule (câu bị luật đổi đáp án không tính vào trần: đáp án và chương trình khác, nên một câu có thể có 4 record).
- **syn**: phân tầng (split × intent) `n^0.5`; không ưu tiên câu `moved`.
- Hành vi sửa lỗi đi trước trong mọi pool. Pool thiếu mẫu thì quota dư chuyển sang syn → rule (chỉ câu đổi) → std.
- Kiểm rò rỉ (dừng nếu vi phạm): không nhóm câu nào của val (`val_meta`/`val_questions`), không shop giữ riêng (mọi
  bản reskin của chúng), không ngành/họ giữ riêng.

### Bảng trộn (số mẫu = lượt model; dự kiến theo sản lượng §3)

| Ngân sách | std (shop train, luật chuẩn) | rule (luật đổi, shop thật) | syn (shop tổng hợp, ngành mới) |
|---|---|---|---|
| **3k** | 55 % ≈ 1650: ~48 % số câu train, 1 bản | 15 % ≈ 450 | 30 % ≈ 900 (~21 % syn có) |
| **5k** | 48 % ≈ 2400: ~69 % số câu | 17 % ≈ 850 | 35 % ≈ 1750 (~40 %) |
| **8k** | 40 % ≈ 3200: ~93 % số câu, bản 2 chỉ cho hành vi sửa lỗi | 18 % ≈ 1440 (~70 %) | 42 % ≈ 3360 (~78 %) |

(Độ phủ câu std đo bằng `select` trên gói thử: 1293 / 1855 / 2522 trong 2702 nhóm ở quota 1650 / 2400 / 3200 mẫu.)
syn tăng theo ngân sách vì std chỉ có ~2700 câu khác nhau: thêm ngân sách cho std chỉ mua thêm bản reskin.

Theo trục: dưới rulebook đổi (theo chữ) ≈ rule + 85 % syn = 40 % / 47 % / 54 %; đáp án thật sự phụ thuộc luật đổi
(câu bị đổi/`moved`) ≈ 18 % / 21 % / 23 %; shop chưa thấy (syn) 30–42 %. Ngân sách là số lượt mẫu: GPU cho 8k lượt
thì dùng 8k mẫu khác nhau × 1 epoch hơn 4k × 2 epoch (còn mẫu mới về shop/luật).

Lý do chia: private ~500 câu, phần lớn intent kiểu train (đề nói rulebook "có thể" khác; ngành mới thì chắc chắn) →
std vẫn lớn nhất ở 3k/5k để không tụt trên phân phối train/public; syn là nguồn duy nhất có shop chưa thấy, ngành mới
và ít lặp khuôn (câu có "anh em" gần giống cùng shop: 10–16 % so với 32 % ở train); rule nhỏ hơn vì chỉ 5 shop và lặp
khuôn cao. Tài liệu: đa dạng nhiệm vụ/quỹ đạo thắng số lượng cho khái quát ngoài phân phối ở tool-use
([DIVE](https://arxiv.org/pdf/2603.11076), [TDScaling](https://arxiv.org/pdf/2602.03219v2)); với LoRA cho code agent
số lượng vẫn quan trọng và lọc chỉ-giữ-đúng không hơn ngẫu nhiên ở quy mô nhỏ
([2607.17205](https://www.alphaxiv.org/abs/2607.17205)); lọc từ chối bỏ quỹ đạo lặp/sai định dạng
([ROME](https://arxiv.org/pdf/2512.24873)); trọng số `n^α` là cách trộn kiểu temperature sampling quen dùng khi gộp
nguồn lệch cỡ; khử trùng lặp gần khi gộp dữ liệu sinh. (Chưa đọc đầy đủ các bài; chỉ dùng làm định hướng.)

## 5. Tập đo giữ riêng (không bao giờ train)

| Tập | Câu | Đo gì |
|---|---|---|
| `data/train` shop biz_108, biz_110, biz_130 (`val_questions.jsonl` của gói, split `data/train`) | 277 | rulebook chuẩn, shop thật chưa thấy (gần public nhất) |
| `data_gen/syn_v2/val` (không nằm trong gói: chạy thẳng split) | 519 | ngành mới (hotpot, spa_salon), họ P, rulebook viết lại toàn bộ, luật chưa thấy |
| `syn_v2/t5` họ P (2 shop, trong `val_questions.jsonl`) | 130 | định dạng file chưa thấy trên ngành đã thấy |
| (tuỳ chọn) bản reskin_1 của 3 shop val | 277 | so với dòng đầu: học thuộc tên hay đọc catalog |

Lưu ý: 32/273 câu chữ của shop val (12 %) trùng nguyên văn câu ở shop train ("Doanh thu hôm nay là bao nhiêu?"...):
tính chất của dữ liệu đề, điểm val hơi lạc quan. Quyết định nộp LoRA hay Gemma gốc: so **cặp** trên cùng câu
(McNemar), nộp LoRA khi hơn gốc ≥ 3 điểm % trên tập 1+3 gộp và không thua trên tập 2 (với ~400 câu, sai số chuẩn
của hiệu ~3 điểm). Chạy Gemma cần người dùng cho phép (CLAUDE.md).

## 6. Rủi ro chính
- Số dư API (1.12 USD lần ghi cuối) và thời gian (2.7 h ước lượng; try100 syn t4 có lúc 83 s/câu). Thứ tự ưu tiên giữ phần
  giá trị nhất; trần chung 14.6 USD.
- Bộ sinh còn lỗi ở intent hiếm: cổng 70 % theo split/intent; teacher "đúng" theo một gold sai vẫn lọt.
- Học thuộc 30 shop train: giảm bằng xoay bản reskin, giữ riêng 3 shop để đo.
- Dữ liệu tổng hợp "dễ" hơn/khác kiểu test: syn ≤ 42 %; ở 3k/5k std vẫn lớn nhất.
- Prompt dựng lại theo code lúc đóng gói: đổi `src/` sau lượt teacher thì `prompt_drift`; `validate --replay` bắt
  chương trình không còn ra gold.
- `rulevar` dùng 5 shop đã có trong std: luật đổi trên shop đã thấy; khái quát sang shop mới dựa vào syn.
- Họ P và 3 shop thật bị giữ riêng → mất một ít độ phủ định dạng trong lượt train duy nhất; đổi lại có số đo để
  quyết định nộp hay không.
