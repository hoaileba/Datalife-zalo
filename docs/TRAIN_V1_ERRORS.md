# Teacher run train_v1: phân tích lỗi (wrong / abstain)

Run: `outputs/teacher/train_v1` (DeepSeek flash, thinking bật, `gen/teacher.py`, max_calls 3, system prompt sha `6e33e47a…`).
Run đã xong: **3000** bản ghi, 2978 correct, 15 wrong, 7 abstain (đều `call_cap`), 0 host_error (`errors.jsonl` rỗng).
Bài này phủ **cả 22 ca**. Mỗi ca: đọc trace (output, program, observation), kiểm thông tin cần có trong prompt
(catalog trong `llm_calls[i].messages`, system prompt `system_prompt.md`), và tự tính lại đáp án bằng pandas trên bảng
`datamate.data.load_business` (đúng bảng agent thấy). Không gọi model, không đọc `data/public_test`. Số dòng code
tham chiếu `src/` tại HEAD 3152e22 (`answer.py`, `solve.py`, `helpers.py` không có sửa đổi chưa commit).

## Tổng hợp

| Lớp | Số ca | Ca |
|---|---|---|
| HOST CODE | **4** | 3 abstain vì luật "kết quả toàn 0" (gold = 0), 1 abstain vì cờ "%" bắt nhầm tên hàng |
| AGENT (teacher) | **18** | 15 wrong + 3 abstain |
| GOLD/QUESTION | **0** | cả 22 gold đều tính lại ra đúng; 3 câu không dấu hơi mơ hồ nhưng mẫu câu có dấu trong train xác nhận gold |

## Bảng các ca

| # | id | shop | câu hỏi (rút gọn) | gold | answer | lỗi | lớp |
|---|---|---|---|---|---|---|---|
| 1 | q_607f89f0a1de | biz_117 | 7 ngày gần nhất mấy mặt hàng ế | 0 | abstain | 0 bị cờ ALL_ZERO; xác nhận bị từ chối; chương trình thứ 2 ra 0 ở lượt cuối không được nộp | HOST (zero) |
| 2 | q_8aa3aaf65ac7 | biz_116 | 12/08–10/09/2025 mấy mặt hàng ế | 0 | abstain | 0 bị cờ; lượt cuối model xác nhận theo đúng gợi ý `next`, host từ chối | HOST (zero) |
| 3 | q_28beeec0f60a | biz_130 | Má heo nướng: 7 ngày từ 04/06 so 7 ngày trước, % | 0.0 | abstain | như ca 1 (15 đĩa vs 15 đĩa) | HOST (zero) |
| 4 | q_fe005c16981b | biz_119 | Ngày 01/05/2026 bán Povidine **10%** chai 90ml giá bao nhiêu | 20000 | abstain | Lượt cuối ra 20000, bị cờ "question asks for a percentage" vì dấu % trong tên hàng | HOST (cờ %) |
| 5 | q_bf8cd59968b5 | biz_109 | Số khách mua ≥3 đơn tháng 3/2026 | 174 | 175 | `astype(str)` trước khi bỏ ô trống: `None` → `'None'` thành một "khách" | AGENT (khách lẻ) |
| 6 | q_ac6250fbda50 | biz_109 | Số khách mua ≥4 đơn tháng 10/2025 | 112 | 113 | như ca 5 | AGENT (khách lẻ) |
| 7 | q_5055becf7714 | biz_106 | 3 khách chi tiêu nhiều nhất tháng 3/2026 | [Vương Phương Loan, …] | abstain | Lượt 1: `astype(str)` → khoá `'None'` → KeyError; lượt 2: `assign(Mã KH=...)` SyntaxError | AGENT (khách lẻ + cú pháp) |
| 8 | q_75d48f1bfc6d | biz_103 | Tháng 7/2025 khách ≥3 đơn chiếm % | 58.77 | 58.96 | So `dm.name_key` (giữ dấu) với literal `'khach le'` → không loại Khách lẻ | AGENT (khách lẻ) |
| 9 | q_bf329c45fda4 | biz_103 | Khách mua tháng 2/2026, tỉ lệ ≥6 đơn | 33.79 | 34.09 | như ca 8 (75/220 thay vì 74/219) | AGENT (khách lẻ) |
| 10 | q_e3ffb2e7d71b | biz_116 | 3 khách mua nhiều tiền nhất tháng 6/2025 | [Bùi Đức Hiếu, Đoàn Sơn Linh, Đỗ Tâm Ngân] | [Khách lẻ, Bùi Đức Hiếu, Đoàn Sơn Linh] | như ca 8; explore đã thấy Khách lẻ đứng đầu | AGENT (khách lẻ) |
| 11 | q_1f99d93acad3 | biz_106 | Nợ theo tuổi nợ 0–7, 8–15, >15 ngày | list | table (số đúng) | sai kiểu: table thay vì list | AGENT (kiểu) |
| 12 | q_2d2d91435d5d | biz_123 | Nợ chia theo tuổi nợ 0–7, 8–15, >15 | list [616900, 427900, 650] | table (số đúng) | như ca 11 | AGENT (kiểu) |
| 13 | q_1a79715010d5 | biz_111 | "so ly size m … tinh moi loai do uong" | 2435 | table 21 dòng | Đọc "moi" = "mỗi" (từng loại) thay vì "mọi" (cộng tất cả) | AGENT (kiểu, câu không dấu) |
| 14 | q_233670084b6f | biz_126 | "hang nao ban chay nhat nhi" | "Bia Tiger Bạc lon" | list 2 món | Đọc "nhi" = "nhì" (top 2) thay vì trợ từ "nhỉ" | AGENT (kiểu, câu không dấu) |
| 15 | q_f073ab4b809f | biz_122 | Doanh thu tuần trước | 56984400 | 56918200 | Cắt còn 4 cột rồi `dm.dedup` → xoá 467 dòng hàng hợp lệ | AGENT (dedup) |
| 16 | q_7ebd4d633970 | biz_122 | Doanh thu MTD so cùng kỳ tháng trước % | 4.8 | 4.86 | như ca 15; explore đã tính đúng 264400000 / 252287000 | AGENT (dedup) |
| 17 | q_0cb7c9b93048 | biz_101 | Số đơn hôm qua | 37 | 1 | `order_day[...].nunique()` đếm số NGÀY khác nhau thay vì số đơn | AGENT (đếm) |
| 18 | q_0ed6031586cc | biz_123 | Tiền vốn lô còn tồn HSD 28/06–26/09/2026 | 7899400 | 7723534 | `merge(suffixes=('', '_ci'))` lấy nhầm `lo_hang.DonGiaNhap` (đã/đv cơ bản) rồi chia hệ số lần nữa | AGENT (merge) |
| 19 | q_284698f995b8 | biz_119 | Giá nhập bình quân một hộp Yumangel tháng 6/2025 | 86414 | 4321 | Chia cho số gói (đv cơ bản) → giá/gói | AGENT (đơn vị) |
| 20 | q_6b90b5fe0a20 | biz_111 | DT Zalo OA và DT tại quầy tháng 2/2026 lần lượt | [9788500, 156637000] | [232780100, …] | Kỳ chỉ áp cho vế sau | AGENT (kỳ) |
| 21 | q_845f5b9b9c82 | biz_103 | Hàng bán chạy nhất tuần rồi | Snack Oishi tôm cay 40g | abstain | Explore ra đúng; 2 lượt sau chết vì assert tự viết sai (đơn vị lớn gộp mọi mặt hàng) | AGENT (assert sai) |
| 22 | q_ba9c6a5b7863 | biz_122 | Tiffy Dey đổi giá 09/06/2026, 14 ngày sau vs trước, % theo viên | -44.19 | abstain | Lượt 1: `assert len(cv) == 3` (chỉ có 2 dòng quy đổi); lượt 2: `fmap.get('vỉ')` nhưng khoá đã `dm.norm` thành `'vi'` | AGENT (assert sai) |

## Kiểm chứng (pandas trên bảng load_business)

| # | Tự tính | Ghi chú |
|---|---|---|
| 1 | 0 (60 mặt hàng bán trước kỳ, cả 60 có bán trong 02–08/11/2025) | bỏ đơn hủy/trả + dòng SL âm, `dm.name_key(Tên SP)` |
| 2 | 0 (55/55 mặt hàng) | cả theo ngày đơn (min Ngày) lẫn ngày dòng |
| 3 | 15 đĩa (04–10/06) vs 15 đĩa (28/05–03/06) → 0.00 % | |
| 4 | 3 dòng ngày 01/05/2026, đều 20000/chai (1 dòng đơn hủy, vẫn tính theo luật [Giá bán X ngày D]) | |
| 5, 6 | bỏ `Mã KH` trống: 174 và 112 | trống = `None`; dòng trống là "lẻ / kl / khách lẻ / Khách lẻ" |
| 7 | KH0185 1829500, KH0074 1732000, KH0002 1584000 | tên trong danh mục có kèm SĐT ("Vương Phương Loan - 0973 189 069"); gold ghi tên không SĐT. Gold các câu bảng công nợ cùng shop có alias tên kèm SĐT, nên không phải lỗi chấm |
| 8, 9 | bỏ Khách lẻ: 124/211 = 58.77; 74/219 = 33.79 | |
| 10 | Bùi Đức Hiếu 32833300, Đoàn Sơn Linh 19530000, Đỗ Tâm Ngân 14792500 | Khách lẻ 526599600 |
| 11, 12 | ba số trùng gold từng đồng | `eval.correct` yêu cầu trùng type, đúng `docs/zac/evaluation.md` |
| 13 | 2435 ly size M (01–19/08/2026) | train có 8 câu cùng mẫu, câu có dấu viết "tính **mọi** loại đồ uống", gold đều là number |
| 14 | Tiger Bạc lon 289 > Tiger lon 275 | các câu có dấu cùng mẫu viết "nhất **nhỉ**" |
| 15, 16 | `dm.dedup` cả bảng (không có dòng trùng): 56984400; 264400000 vs 252287000 → 4.80 | |
| 17 | 37 đơn có ngày đơn 23/09/2025 | |
| 18 | `left * lo_hang.DonGiaNhap` = `left * chi_tiet_nhap.DonGiaNhap / factor` = 7899400 | khớp oracle `gen/oracle.py:666` |
| 19 | 4 dòng nhập đều đơn vị hộp: 2506000 / 29 = 86413.79 → 86414 | |
| 20 | tháng 2/2026: zalo_oa 9788500, store 156637000 | |
| 21 | explore của agent: Snack Oishi 139 > Aquafina 112 | |
| 22 | 221 viên (09–22/06) vs 396 viên (26/05–08/06) → -44.19 | 1 vỉ = 4, 1 hộp = 100 viên |

## HOST CODE: nhóm theo nguyên nhân

### H1. Luật "kết quả toàn 0" chặn các đáp án 0 hợp lệ: 3 câu (#1, #2, #3)

Trong train có 4 gold bằng 0 (number/percent): 3 câu abstain vì luật này, 1 câu đúng nhờ `confirmed`.
Có ba chỗ ghép lại gây lỗi:

1. `src/datamate/solve.py:90-92`: observation của kết quả bị cờ luôn ghi `next: "...if it is truly right, submit it as it is:
   reply "Answer type: <its type>"..."`, kể cả khi cờ là ALL_ZERO.
2. `src/datamate/solve.py:133-136`: đúng lời xác nhận đó lại bị từ chối ("cannot be confirmed yet ... two programs giving 0").
   Cả 3 ca mất một lượt vì làm theo gợi ý ở (1). System prompt (`assets/prompt.md`, dòng "submit the flagged result of
   your last program as it is") không nói luật hai chương trình.
3. `src/datamate/solve.py:146-151`: khi chương trình thứ hai (khác code) cũng ra 0, `confirmable` thành True nhưng kết quả
   không được nộp. Ở lượt cuối (#1, #3) vòng lặp hết, kết quả là `call_cap`.

Đề xuất:
- (a) `solve.py:146-151`: nếu issue duy nhất là ALL_ZERO và `len(zero_programs) >= 2` (hai chương trình khác nhau cùng ra
  0) thì finalize và nộp luôn (reason ví dụ `zero_confirmed`). Sửa được #1, #3.
- (b) `solve.py:90-92`: với ALL_ZERO, `next` phải nói đúng luật: "a 0 is submitted only when a second, differently built
  program also gives 0: write it now (it is submitted when it agrees)". Nêu luật này trong `assets/prompt.md` (phần Answer
  type / HOW IT RUNS). Với (a), sửa được #2: model sẽ viết chương trình thứ hai ở lượt 2 thay vì xác nhận.
- Tổng: **3 câu** (cả 3 gold = 0 đang abstain).

### H2. Cờ "%" bắt nhầm dấu % trong tên hàng: 1 câu (#4), cộng 13 lượt thừa

`src/datamate/answer.py:156`: `if ('%' in question or PERCENT_WORDS.search(norm(question))) and answer_type != 'percent'`.
Tên thuốc chứa % (Povidine 10%, Otrivin 0,1%, Natri clorid 0,9%, Acyclovir 5%, Efticol 0,9%). Trong cả run, cờ này bật 14 lần:
13 câu đúng nhưng phải tốn một lượt để xác nhận, 1 câu (#4) bị cờ ở lượt cuối nên abstain. Không lần nào cờ bắt đúng.

Đề xuất: trước khi kiểm, bỏ khỏi câu hỏi các đoạn khớp giá trị trong dữ liệu (đã có `catalog.lookup`, match "mentioned in
question"), hoặc chỉ coi `%` là hỏi phần trăm khi nó không nằm sau một số trong cụm tên hàng. Đơn giản và đủ chung:
`re.sub(r'\d+(?:[.,]\d+)?\s*%(?=\s*\w)', '', question)` rồi mới kiểm `'%'`. Cách này giữ được "bao nhiêu %", "là mấy %?" và
"%" ở cuối câu. Sửa được **1 câu** và tiết kiệm 13 lượt (13 mẫu SFT có một lượt xác nhận thừa).

### Ghi chú chung cho H1, H2

Một kết quả bị cờ "mềm" ở lượt cuối (`terminal_only`) luôn mất. Kể cả khi model đã kiểm và kết luận đúng, không còn lượt để
xác nhận. Nếu muốn, có thể thêm luật: ở lượt cuối, cờ ALL_ZERO đã có hai chương trình đồng ý, hoặc cờ % (sau khi sửa H2), thì
nộp. Với teacher, tăng `max_calls` lên 4 cũng giảm loại lỗi này.

### Hardening tuỳ chọn (không có ca nào do chúng, nhưng chặn được lỗi agent lặp lại)

| Đề xuất | Chỗ | Ca có thể cứu |
|---|---|---|
| `dm.dedup` báo lỗi khi frame là một tập con cột của một bảng trong `tables` (cùng index, thiếu cột): "dm.dedup the whole table before selecting columns" | `src/datamate/helpers.py:198` | #15, #16 (2) |
| `answer.issues`: string/list chứa tên giữ chỗ khách lẻ (`norm` ∈ {khach le, le, kl, none, nan}) bị cờ | `src/datamate/answer.py:138` | #10 (1) |
| `answer.issues`: table 2 cột mà mọi ô cột đầu là nhãn có trong câu hỏi → "các nhóm do câu hỏi đặt: trả list theo thứ tự câu hỏi" | `src/datamate/answer.py:138` | #11, #12 (2) |
| Helper `dm.walkin(names)` (mask khách lẻ theo `dm.norm`, mọi cách viết trong dữ liệu) và nêu trong cookbook §3 | `src/datamate/helpers.py`, `assets/prompt.md` | #8, #9, #10 (3) |

## AGENT: mẫu lỗi lặp lại và luật chung có thể sửa

| Mẫu | Số câu | Ca | Luật chung (prompt/cookbook) |
|---|---|---|---|
| A. Khách lẻ / mã khách trống vẫn được tính là khách | **6** | #5–#10 | §3 [Xác định khách], thêm code mẫu: `df = df[df['<mã KH>'].notna()]` TRƯỚC mọi `astype(str)` (`astype(str)` biến ô trống thành `'None'`); khách lẻ theo tên: `walk = dm.norm(df['<tên>']).isin([...])`, không so khoá `dm.name_key` (giữ dấu) với literal; `assert walk.any()` khi dữ liệu có khách lẻ. Mọi bộ lọc theo nhãn phải assert là đã bỏ được ít nhất một dòng |
| B. Sai kiểu trả lời | **4** | #11–#14 | §9: "Các nhóm/khoảng do câu hỏi tự nêu → list theo thứ tự câu hỏi; table chỉ khi đối tượng lấy từ dữ liệu." Thêm: "Câu không dấu: đọc theo cách đặt dấu phổ biến: 'tinh moi loai' = tính mọi loại (cộng tất cả, một số); 'nhi' cuối câu = trợ từ 'nhỉ', không phải 'nhì'; câu '… nào … nhất' không nêu k → một đối tượng (string)." |
| C. `dm.dedup` sau khi cắt cột | **2** | #15, #16 | §8: "dm.dedup trên bảng đầy đủ, trước khi chọn cột." (hoặc hardening ở helpers.py:198) |
| D. Assert tự viết sai làm hết lượt | **2** | #21, #22 | §8 "After an error": "assert trên giá trị chương trình tính ra, không trên số đếm đoán trước (số dòng quy đổi); khoá sau `dm.norm` là không dấu ('vi', 'hop'); đơn vị lớn xét theo TỪNG mặt hàng." |
| E. Đếm sai thứ (nunique trên Series ngày) | 1 | #17 | §3: "Số đơn = số MÃ đơn khác nhau: `df.loc[mask, '<mã đơn>'].nunique()`, không `nunique()` trên cột ngày." |
| F. Trùng tên cột sau merge | 1 | #18 | §6 code rules: "Trước merge chỉ lấy cột cần; cột cùng tên ở hai bảng: rename, không dùng `suffixes=('', …)`." |
| G. Đơn vị của giá bình quân | 1 | #19 | §5 [Giá nhập bình quân]: "giá theo đơn vị câu hỏi nêu (mặc định đơn vị nhập); không chia cho số lượng cơ bản khi câu hỏi hỏi theo đơn vị lớn." |
| H. Kỳ dùng chung cho nhiều số đo | 1 | #20 | §2: "Một kỳ viết một lần cho 'A và B … lần lượt' áp cho mọi số đo." |

Ba mẫu A, B, C chiếm 12/18 lỗi agent và đều sửa được bằng luật chung (A thêm code mẫu, B thêm luật kiểu và đọc câu không
dấu, C một dòng). Không có lỗi nào cần luật riêng cho một câu.

Thông tin cần có đều nằm trong prompt: luật khách lẻ (§3), `name_key` "accents kept" (§7 helpers), luật dedup (§8), list/table
(§2 Answer type, §9), giá bình quân "in the purchase unit" (§5), recipe lô (§6), README đơn vị (biz_119, biz_122), cột `Mã KH`
trống (catalog). Ở #10, #16 và #21, chính explore của agent đã cho số đúng hoặc chỉ ra bẫy.

## GOLD/QUESTION

Không có gold đáng nghi: cả 22 gold đều tái tạo đúng bằng pandas. Có 3 câu mơ hồ ở mặt chữ, nhưng ngữ cảnh giải quyết được:
- #20 "Zalo OA và tại quầy tháng 2/2026 lần lượt": kỳ đặt cuối câu, cách đọc của gold (áp cho cả hai) tự nhiên hơn.
- #13 "tinh moi loai do uong" và #14 "ban chay nhat nhi": viết không dấu. Các câu có dấu cùng mẫu trong train ("tính **mọi**
  loại", "nhất **nhỉ**") xác nhận cách đọc của gold.
