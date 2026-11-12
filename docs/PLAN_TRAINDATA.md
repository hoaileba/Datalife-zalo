# Plan: tạo dữ liệu huấn luyện cho luồng code agent v4

Trạng thái: nghiên cứu, chưa có code. Mọi số liệu đo trên `data/train` (không đọc public).
Worktree: `datamate_v4_traindata`, nhánh `exp/traindata` (từ main 12e2025).

## 0. Ràng buộc quyết định thiết kế
- Hạn nộp Docker (gồm code train + data): **16/11**. Hôm nay 11/11, còn khoảng 5 ngày. Sau hạn thì đóng băng.
- Inference: tổng ≤ 15B tham số, chạy offline, 2×5090, 6 giờ cho khoảng 500 câu. Được fine-tune tự do. Được dùng data tự tổng hợp, kể cả khi teacher là API. **Không** được train trên public/private.
- Đầu ra cần học là đúng định dạng của v4: system = `prompt.md` + cookbook của bộ; user = catalog + question + as_of + data_lookup; assistant = JSON `{action, plan, rules, answer_type, code_lines}` (retry thì có `diagnosis` đứng đầu). Thinking tắt, nên lập luận phải nằm trong `plan`/`rules`.
- Mỗi lượt gọi model trên tập > 6 câu cần người dùng cho phép, kèm ước lượng chi phí.

## 1. Kết quả "revert" cách BTC sinh dữ liệu train

### 1.1 Shop (dữ liệu)
Pipeline gần như chắc chắn là: **spec shop → mô phỏng thế giới theo ngày → sổ cái chuẩn → renderer theo họ định dạng → bơm nhiễu → viết README**.

- **5 ngành**, mỗi ngành có một catalog cố định (tên và mã `SPxxxx` dùng chung cho các shop cùng ngành). Mỗi shop lấy một tập con và lệch giá.
  - tạp hoá: 60 SP, 77 dòng quy đổi lốc/thùng
  - cà phê: 50 SP, size (M)/(L)
  - VLXD: 55–60 SP, xe 4m3, tấn, thiên; có giao hàng và hạn nợ 30/60 ngày
  - nhà thuốc: 70–80 SP, lô, hạn dùng, kê đơn, hoạt chất
  - nhà hàng: 55–61 SP, Phí phục vụ = 5% tiền hàng, bàn/khu vực
- **Sổ cái chuẩn** ≈ schema `biz_123/pos.sqlite` (17 bảng: chi_nhanh, nhan_vien, khach_hang, nha_cung_cap, san_pham, don_vi_sp, phieu_nhap, chi_tiet_nhap, don_hang, chi_tiet_don, thanh_toan, tra_hang, the_kho, lich_su_gia, lo_hang, chi_tiet_don_lo, thong_tin_thuoc). Thêm chi phí (biz_124) và đợt giao (VLXD).
- **Tham số mô phỏng đo được:**
  - Thời gian: bắt đầu ngày 1 của một tháng, từ 01/2025 đến 06/2025, dài 14–20 tháng.
  - Đơn: 12k–86k đơn. Số đơn mỗi ngày = gốc × hệ số Tết theo ngành (tạp hoá ×2.1–2.7, cà phê/nhà hàng/VLXD ×0.4–0.6, thuốc ×1.1–1.3) × hệ số cuối tuần riêng từng shop (0.62–1.55) × ngày lương 1–5 (+5–12%) × xu hướng (±35%).
  - Dòng: 1–6 dòng mỗi đơn, phân phối gần hình học. Giờ mở cửa 6–22h, hai đỉnh.
  - Trạng thái: huỷ 1–4%, trả 0.3–1.5%. "Đang giao" chỉ có ở 2–3 ngày cuối.
  - Thanh toán: TM 48%, CK 34%, ví 10%, COD 5%, nợ 1–3%.
  - Phí và khuyến mãi: ship = 15.000 khi và chỉ khi kênh phone/zalo. KM01 = −10.000. VAT = 0.
  - Nợ: trả một phần lúc mua, sau đó 1–3 kỳ đều nhau; kỳ cuối gánh phần làm tròn.
  - Giá: tăng 1–3 lần, mỗi lần +4–9%. Nhập hàng mỗi 1–2 ngày; PN00001 là nhập đầu kỳ. Lô xuất theo FEFO.
- **9 họ định dạng (renderer):**
  - A: CSV dòng phẳng
  - A′: CSV một dòng mỗi hoá đơn
  - B: sổ tay một sheet, không mã đơn, không khách
  - C: sổ ghi tay, mỗi tháng một sheet, header 2 tầng, có BangGia/TonKho/SoNhapHang
  - D: kiểu Sapo DonHang_ChiTiet, không mã SP, kèm DanhSachQuyDoi, có fill-down trống
  - E: KiotViet DanhSach*
  - F: MISA So_chi_tiet_ban_hang
  - G: CSV chuẩn hoá, enum tiếng Anh
  - H: SQLite thô
  - I: trộn nhiều nguồn

  Trong cùng một họ, mỗi shop **đổi tên cột** (lấy từ kho từ đồng nghĩa) và **xáo thứ tự cột**. Có thêm cột rác.
- **Nhiễu đo được (theo từng shop):**
  - Dòng trùng 1–3%.
  - Biến thể tên SP/khách (hoa thường, bỏ dấu, 2 khoảng trắng, đổi họ Doãn↔Đoàn) trên khoảng 13% dòng. 40% tên khách kèm số điện thoại.
  - Số trộn "1,234"/số trần khoảng 50%. "45,000.0000", "55.000đ"/"25k", "1tr440", "16,56tr". Số lượng dạng "3 chai" ở 35–50% dòng.
  - Ngày: dd/mm, Excel serial khoảng 50%, "1 thg 6 2025", ISO, không năm.
  - Cấu trúc: dòng tiêu đề, dòng lọc, dòng tổng; chia file `_1/_2` ở mốc 100k dòng; sheet theo tháng.
  - Nhãn: mỗi trạng thái có kho từ đồng nghĩa, nửa số shop trộn 2 từ. Khách lẻ viết 1 dạng hoặc 4 dạng.
- **README**: một khuôn ("# Dữ liệu biz_X / ## File / ## Cột trong … / ## Quy ước") với 3 mức chi tiết: đầy đủ, sơ sài, gần trống. Luôn có câu "Dữ liệu có đến hết dd/mm/yyyy".

### 1.2 Câu hỏi
- **Quy mô:** 7 shop đơn giản × 40 câu và 23 shop đầy đủ × khoảng 118 câu. Mỗi shop có một **as_of chính** = cuối dữ liệu (70–95% số câu, hỏi các tháng/quý cụ thể) và 10–40 as_of ngẫu nhiên cho câu thời gian tương đối (hôm nay, tuần rồi, N ngày gần nhất, tháng này, từ đầu năm).
- **Khoảng 40 ý định có tham số.** Tỉ lệ thô trên 3000 câu: doanh thu kỳ/SP/nhóm 23%, tỉ trọng % 9%, số đơn 6%, giá trị TB đơn 5%, khách (top, ≥N đơn, nhóm) 5%, tỉ lệ huỷ 5%, ngày bán cao nhất 4%, số đơn huỷ 3.5%, hàng ế 3%, hoạt chất/kê đơn 3%, hiệu ứng tăng giá 3%, số lượng theo đơn vị 3%, top hàng 3%, size 3%, nhập hàng 3%, ca 2.5%, công nợ (tổng, bảng, nợ thêm/trả, tuổi nợ) 4%, giá bán ngày D 2%, tồn kho 2%, giá nhập bình quân 1%. Phần còn lại: hạn dùng, xu hướng tăng liên tục, tháng cao nhất, giỏ hàng ≥N đơn, số ngày đạt X, giao hàng, thanh toán, nhân viên, lãi gộp, lãi ròng.
- **Kiểu đáp án:** number 63%, percent 19%, list 6%, date 5%, string 3%, unanswerable 2.3%, boolean 0.8%, table 0.6%.
- **Tham số câu hỏi:** tháng trong khoảng dữ liệu; SP/nhóm/khách/nhân viên lấy từ shop; ngưỡng làm tròn gần phân vị (ví dụ "≥ 42 đơn", "49.000.000 đồng"); k ∈ {3, 5}; câu có hoà ở biên k bị loại (theo đề).
- **Không trả lời được** sinh theo **khả năng của shop**: hỏi thông tin shop không có (tồn kho, nhập, nợ, giới tính, địa chỉ, lý do huỷ/trả, kênh), câu chủ quan (nhân viên lễ phép), kỳ nằm ngoài dữ liệu, khách khi shop không ghi khách.
- **Lớp biến đổi cách viết** (chồng lên nhau, áp trên khuôn câu chuẩn):
  1. Nhiều khuôn diễn đạt cho mỗi ý định.
  2. Tiền tố: Cho mình hỏi / Xem giúp / Cho tôi biết / check giùm / coi giùm…
  3. Hậu tố: nhỉ, ạ, vậy, z, ta, đó, ha…
  4. Viết thường đầu câu 51%, bỏ dấu cả câu 26%.
  5. Viết tắt: dthu 16%, bn/bnhiu/nhiu, đc, hnay, hqua, trc, vs, th.
  6. Lỗi gõ telex 5% (hangf, naof, dduwowcj, soos).
  7. Chêm tiếng Anh: revenue, bill, order, total, best seller.

**Hệ quả:** dữ liệu train là sinh tự động có kiểm soát. Đáp án chuẩn chắc chắn được tính trên **sổ cái sạch** rồi mới render ra file nhiễu. Mình làm được y như vậy: đáp án đúng có sẵn mà không cần solver đọc file nhiễu.

## 2. Thiết kế bộ sinh (`gen/`, ngoài `src/datamate`, không import ngược)

```
spec (ngành, kích thước, khả năng) ─► sim (sổ cái chuẩn, pandas) ─► oracle (đáp án theo rulebook) ─┐
                                      └► render (họ A–I + họ mới) ─► noise ─► README ─► shop/  ◄────┘
questions: intent × tham số (từ sổ cái) × khuôn câu × lớp biến đổi ─► questions.jsonl + answers.jsonl (+ alias)
```

1. **spec**: 5 ngành của train và **ngành mới** cho private (ví dụ mỹ phẩm, mẹ & bé, sửa xe, thú cưng, văn phòng phẩm, tiệm bánh, nông sản). Catalog ngành mới nhờ LLM viết một lần, người duyệt. Cờ khả năng: có mã khách, nhập hàng, lô, nợ, giao, chi phí, bảng giá, nhân viên, ca.
2. **sim**: mô phỏng theo ngày với các tham số ở §1.1. Ghi ra sổ cái chuẩn (schema kiểu pos.sqlite).
3. **oracle**: mỗi ý định là một hàm thuần trên sổ cái sạch, cài đúng rulebook train §1–§10. Ví dụ: bỏ cả đơn có trả hàng, tuần bắt đầu thứ Hai, tháng này so cùng số ngày, Tết 23 Chạp đến mùng 10, tuổi nợ, FEFO, giá vốn trên dòng. Tham số hoá theo **biến thể luật** (xem §3 S4).
4. **render + noise**: tái tạo 9 họ (tên cột lấy từ kho đồng nghĩa đo trên train) và **thêm họ mới** (Excel nhiều sheet tự do, Google Sheet xuất CSV, file pivot). Mục đích là để model không học thuộc 9 layout. Mọi núm nhiễu có tỉ lệ ngẫu nhiên quanh mức đo được.
5. **questions**: khuôn câu viết tay cho khoảng 40 ý định (lấy cảm hứng từ cấu trúc train, không chép nguyên văn), cộng diễn đạt lại bằng LLM, cộng bộ biến đổi lỗi theo đúng tỉ lệ §1.2. Alias = mọi cách viết tên trong file cộng mã. Loại câu có hoà ở biên k.

**Hai bước hiệu chỉnh bắt buộc, có thể kiểm bằng gold train:**
- **Oracle vs gold:** nạp `biz_123/pos.sqlite` (gần như sổ cái thô) và họ G (111/127/129) vào sổ cái chuẩn, chạy oracle trên các câu train của chúng, so với `answers.jsonl`. Mục tiêu ≥ 98% khớp trước khi tin oracle cho data tổng hợp. Đây là cách duy nhất chứng minh mình hiểu đúng luật.
- **Shop tổng hợp vs train:** reader/catalog v4 đọc không lỗi. Phân phối thống kê (nhiễu, ý định, kiểu đáp án) khớp. DeepSeek trên luồng v4 đạt độ chính xác tương đương train (train20 = 20/20). Nếu thấp hơn nhiều thì generator đang sinh trường hợp lạ hoặc oracle sai.

## 3. Nguồn mẫu huấn luyện (SFT, theo định dạng v4)

| Nguồn | Cách làm | Nhãn | Ghi chú |
|---|---|---|---|
| **S1 chưng cất train** | 3000 câu train qua v4 với DeepSeek v4.1 flash (teacher), nhiều mẫu (temp 0 và 0.7) | giữ khi đáp án = gold | Rẻ nhất, làm ngay. Ước tính khoảng 3.2k lượt, khoảng 2.5 giờ, ~4 USD (theo p1000: 1065 lượt/1000 câu, 49 phút, 1.12 USD). |
| **S2 augment train, không cần simulator** | (a) diễn đạt lại / bơm lỗi cách viết lên câu train: cùng gold, cùng chương trình. (b) câu mới trên shop train: ý định cũ với tham số mới (tháng, SP, ngưỡng, as_of khác) | (a) gold sẵn có. (b) 2 lần teacher độc lập cùng ra một đáp án (đo được: đồng ý → 86–91% đúng) | (a) gần như miễn phí. (b) thêm khoảng 5–10k câu. |
| **S3 shop tổng hợp** | generator §2, khoảng 100–300 shop × 100 câu, kể cả ngành và họ định dạng mới | oracle | Mấu chốt để tổng quát cho private (ngành mới). |
| **S4 biến thể rulebook** | đổi một số dòng rulebook (ví dụ: tuần bắt đầu Chủ nhật, doanh thu gồm VAT/phí giao, đơn trả một phần vẫn tính, ca sáng 6–12h, Tết đến mùng 5…) → `rules.compare` sinh `rulebook_changes` và cookbook bỏ recipe tương ứng, đúng như luồng v4 | oracle chạy với luật đã đổi | Dạy model **đọc rulebook_changes và ưu tiên nó hơn cookbook**. Đề nói rulebook có thể khác giữa các bộ. Biến thể tự nghĩ ra từ train, không dựa vào nội dung public. |
| **S5 sửa lỗi (retry)** | lượt đầu sai hoặc lỗi của teacher/Gemma → lượt sau có `diagnosis` và chương trình đúng | gold/oracle | Dạy dùng đúng phần retry của v4. |
| **S6 không trả lời được / bỏ trống** | câu thiếu dữ liệu đúng nghĩa và câu "giả thiếu" (dữ liệu có mà model hay nói thiếu) | oracle | p1000: model nói "unanswerable" thì 12 đúng / 55 sai. Cần cân bằng hai chiều. |

**Lọc mẫu:**
- Chương trình chạy sạch trong sandbox v4 và cho đúng gold.
- Mỗi câu chọn chương trình ngắn nhất trong các mẫu đúng.
- Cân bằng theo ý định (giới hạn trên cho doanh thu tháng).
- Loại mẫu mà `plan`/`rules` mâu thuẫn với code (nhãn trạng thái thiếu).
- Ghi `system_prompt.md` + input đúng như runner tạo ra (`prompt.messages`), để mẫu huấn luyện khớp đúng từng byte với lúc chạy thật.

**Chia tập eval** (không dùng public):
- Giữ riêng theo **shop** (không theo câu).
- Thêm một split **giữ riêng cả ngành** (ví dụ nhà hàng) và **giữ riêng cả họ định dạng**, để mô phỏng private có ngành mới.
- Thêm một split rulebook biến thể.

## 4. Huấn luyện (phác thảo)
- **Base:** Gemma 12B hiện dùng (cần xác nhận checkpoint gốc: gateway báo `gemma12b-it-checkpoint1200`, có thể đã là bản fine-tune của nhóm).
- **Cách train:** LoRA/QLoRA, chỉ tính loss trên JSON của assistant. Ngữ cảnh 12–16k token (system khoảng 6–8k, catalog 3–8k).
- **Phần cứng:** máy này có 1×3090 24 GB (đang dùng 12 GB): QLoRA 12B ở 16k rất chật. Cần 2×5090 hoặc GPU thuê.
- **Khối lượng:** khoảng 5–20k mẫu, 1–2 epoch.
- **Đo:** PA trên các split eval của §3, cộng health của v4 (lỗi cú pháp, KeyError, bị cắt). So với Gemma gốc trong cùng khung giờ (server có thể đổi model âm thầm).

## 5. Lộ trình đề xuất (theo hạn 16/11)
| Ngày | Việc | Ra gì |
|---|---|---|
| 11–12/11 | `gen/questions` (khuôn + biến đổi lỗi) và S2a. Chạy S1 (cần cho phép khoảng 3.2k lượt DeepSeek). Script xuất mẫu SFT từ log v4. | ~3k mẫu đúng gold + vài nghìn bản diễn đạt lại |
| 12–13/11 | Oracle + nạp `pos.sqlite`/họ G, hiệu chỉnh với gold train. S2b có self-consistency. | Oracle ≥ 98% trên biz_123/111/127/129 |
| 13–14/11 | sim + render (bắt đầu với 3 họ: H, E, A) + noise. 1 ngành mới. S3/S4 lô nhỏ, kiểm bằng DeepSeek. | 30–50 shop tổng hợp |
| 14–15/11 | QLoRA trên S1+S2(+S3/S4 nếu kịp). Eval held-out shop/ngành. | Checkpoint + số đo |
| 15–16/11 | Đóng gói vào Docker (training code + data), chọn checkpoint. | Bản nộp |

Đường lui: nếu generator không kịp thì nộp bản chỉ có S1+S2 (chưng cất train). Phần generator vẫn đưa vào repo làm "training code" nếu đủ ổn.

## 6. Rủi ro / cần người dùng quyết
1. Có fine-tune thật trước 16/11 không, và train trên GPU nào? 1×3090 rất chật cho 12B ở 16k.
2. Base model: Gemma gốc hay checkpoint1200 trên gateway?
3. Cho phép chạy teacher trên 3000 câu train (S1) và các lô S2b/S3: ~3–10k lượt DeepSeek, ~5–15 USD.
4. Ưu tiên giữa S3 (generator đầy đủ, tổng quát cho ngành mới, tốn công) và S2 (nhanh, chỉ trong phân phối train).
5. Rủi ro học thuộc: train chỉ có 30 shop và 5 ngành. Không có S3/S4 thì model fine-tune có thể giỏi train nhưng kém với ngành, layout, rulebook mới.

## 7. Trạng thái code (11/11, nhánh `exp/traindata`, chưa commit, chưa gọi API)

| Thành phần | File | Kiểm bằng gì |
|---|---|---|
| Sổ cái chuẩn + bộ nạp shop train (H sqlite, G csv, E KiotViet) | `gen/ledger.py` | – |
| Oracle: 65 ý định, rulebook train tham số hoá (`Rules`) | `gen/oracle.py`, `gen/periods.py` | `scripts/calibrate_oracle.py`: **591/591** câu train của biz_123/111/127/129/106 khớp gold |
| Câu train → spec | `gen/parse.py`, `gen/textnorm.py` | cùng script trên |
| Danh mục 5 ngành train + 7 ngành mới | `gen/catalogs.py`, `gen/assets/` | – |
| Mô phỏng theo ngày | `gen/sim.py` | `tests_gen/test_oracle_sim.py` (bất biến: thành tiền, tổng đơn, ship, phí 5%, tồn ≥ 0, đã trả ≤ phải trả) |
| Xuất file: 8 họ train (H G E F D A B C) + 2 họ mới (S, P), nhiễu, README 3 mức | `gen/render.py`, `gen/noise.py`, `gen/readme.py`, `gen/pools.py`, `gen/xlsx.py` | `scripts/check_render.py`: 240/240 lượt đọc lại qua `load_business`, doanh thu khớp từng tháng |
| Câu hỏi: 287 khuôn, lớp lỗi cách viết theo số đo train | `gen/surface.py` | `scripts/check_surface.py`: round-trip 100% trên 3000 spec (realize ↔ parse), thống kê nhiễu khớp train |
| Chọn ý định/tham số/as_of, loại hoà ở biên k | `gen/questions.py` | kiểu đáp án tập thử 1200 câu: number 61%, percent 20%, list 5%, date 6%, unanswerable 3.8% (train 63/19/6/5/2.3) |
| Biến thể rulebook (11) | `gen/variants.py` | mỗi biến thể được `rules.compare` của v4 nhận là `rulebook_changes`; `--variant` giữ phần lớn câu bị luật đổi đáp án |
| Dựng split | `gen/build.py` | 12 shop × 100 câu trong 2 phút 18 giây; catalog v4 dựng được, 0 file không đọc được |
| S2a: viết lại câu train | `gen/augment_train.py` | 3465 câu (2748 bản bơm lỗi + 1176 bản diễn đạt lại đã kiểm bằng oracle) |
| Xuất SFT, gói giao tay (xem `docs/PLAN_SFT.md`) | `gen/sft.py`, `gen/package.py`, `gen/validate.py`, `gen/tokens.py` | `tests_gen/test_package.py`; gói từ smoke + try6: 15/15 prompt dựng lại khớp, 12/12 chương trình chạy lại ra gold |
| Trộn, giới hạn theo ý định, giữ riêng shop/ngành/họ | `gen/package.py` (thay `gen/mix.py`), `scripts/train_intents.py` | `tests_gen/test_package.py` |
| Shop train đổi tên (reskin), mẫu SFT không cần teacher | `gen/reskin.py`, `gen/shopio.py`, `gen/remap.py`, `gen/reskin_replay.py` | `tests_gen/test_reskin.py`; mọi bảng đọc lại bằng `load_business` khớp bảng gốc sau ánh xạ tên (xem `docs/PLAN_SFT.md` §3) |
| Biến thể rulebook trên 5 shop đã hiệu chỉnh | `gen/rule_variants.py`, `gen/variants.py` (thêm diễn đạt lại) | `data_gen/rulevar_summary.json` (rulebook_changes, system prompt, dry-run teacher) |
| LoRA SFT | `train/sft_lora.py` | chỉ `--dry-run` đã chạy (tokenizer Gemma 4 thật); **chưa train** (máy này không có torch). Tự tokenize, loss chỉ trên completion |

### Lệnh không gọi API (chạy thoải mái)
```
PY=/mnt/ssd4t/dungnd4/zac_2026/envs/pd22/bin/python; export PYTHONIOENCODING=utf-8 PYTHONPATH=src:.
$PY scripts/calibrate_oracle.py                      # oracle vs gold
$PY -m gen.build --out data_gen/syn_v1 --shops 100 --questions 100 --seed 1     # ~20 phút
$PY -m gen.build --out data_gen/var_<v> --shops 4 --questions 50 --variant <v> --seed 2
$PY -m gen.augment_train --out data_gen/train_aug --copies 2
$PY -m pytest -q tests_gen
```

### Bước cần cho phép (gọi teacher DeepSeek qua runner v4, `config.deepseek.yaml`)
Ước lượng theo p1000 DeepSeek: khoảng 1.07 lượt/câu, khoảng 49 phút cho 1000 câu với 8 luồng, khoảng 1.1 USD cho 1000 câu.

| Lượt | Câu | Lượt gọi | Thời gian | Chi phí |
|---|---|---|---|---|
| S1 train | 3000 | ~3.2k | ~2.5 giờ | ~3.5 USD |
| S2a train_aug | 3465 | ~3.7k | ~3 giờ | ~4 USD |
| S3 syn_v1 (100 shop) | 10000 | ~10.7k | ~8 giờ | ~11 USD |
| S4 biến thể (11 × 4 shop × 50) | 2200 | ~2.4k | ~2 giờ | ~2.5 USD |

Sau đó `gen.package --teacher <các run>` (chỉ giữ câu đúng gold) → `gen.validate` → `train/sft_lora.py` (xem `docs/PLAN_SFT.md`). Chia eval: giữ riêng shop, và giữ riêng một ngành mới cùng họ P/S.

### Việc còn thiếu
- Họ I (trộn nhiều nguồn) và A′ (một dòng mỗi hoá đơn) chưa có renderer. Nhà hàng chưa có số bàn, số khách.
- Một số ý định chỉ có ít câu gold để kiểm (net_profit, deliveries_count, stock_big_small, out_of_stock_count): oracle viết theo rulebook nhưng chưa được gold xác nhận.
- Họ định dạng đang chọn đều nhau, chưa theo tỉ lệ train. Câu theo tháng hơi nhiều hơn train.
- 100% round-trip chỉ cho thấy khuôn câu và parser khớp nhau, không phải độ phủ cách hỏi ngoài khuôn.
