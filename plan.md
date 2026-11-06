# Plan DataMate — zalo 2026

Thứ tự doc này: **target → context → lược đồ → phân tích từng bước → phương án để chọn**.

§5 là nơi anh chọn. Mọi phương án ở đó **chưa chốt**. Cột *nghiêng về* là ý tôi kèm lý do, không phải quyết định.

Nhãn bằng chứng dùng xuyên suốt:
- **[đo]** — có command sinh ra số, chạy trên dữ liệu thật ngày 2026-10-29.
- **[benchmark]** — số từ paper hoặc leaderboard ngoài, không đo trên bài này.
- **[giả thuyết]** — suy từ nguyên lý, chưa có số.

---

# §1 Target

## 1.1 Mục tiêu

Tối đa **điểm** trên 1.000 câu `public_test`, không phải tối đa accuracy.

Luật chấm: đúng **+1**, sai **−1**, bỏ trống **0**. **[đo, rulebook §9]**

Hệ quả toán học, đây là thứ chi phối mọi quyết định còn lại:

| | |
| --- | --- |
| EV một câu trả lời có xác suất đúng `p` | `p·(+1) + (1−p)·(−1) = 2p − 1` |
| Trả lời có lợi khi | `p > 0.5` |
| Trả lời khi `p = 0.4` | **−0.2 điểm/câu**, tệ hơn bỏ trống |
| Hệ thống accuracy 60% trả lời hết 1000 câu | `600 − 400 = 200` điểm |
| Hệ thống accuracy 80% nhưng chỉ trả 500 câu | `400 − 100 = 300` điểm |

Dòng cuối là điểm quan trọng nhất của bài: **một hệ thống kém hơn về accuracy mà biết im lặng thì ăn điểm cao hơn.** Vì vậy abstain là thành phần kiến trúc, không phải tính năng thêm sau.

## 1.2 Ba số luôn báo cùng nhau

Báo một số là báo cáo vô dụng, vì accuracy tăng mà điểm giảm là chuyện xảy ra thật ở hàm mất mát này.

| Số | Định nghĩa |
| --- | --- |
| **score** | `(số câu đúng) − (số câu sai)` |
| **accuracy** | đúng / số câu **đã trả lời** (không tính abstain) |
| **coverage** | số câu đã trả lời / tổng câu |

## 1.3 Ràng buộc

| Ràng buộc | Nguồn | Hệ quả |
| --- | --- | --- |
| Model **< 15B** | luật thi | không trông vào reasoning dài nhiều bước; chia nhỏ, mỗi lần gọi quyết một thứ |
| Khớp tuyệt đối: tiền từng đồng, percent 2 chữ số thập phân | rulebook §9 **[đo]** | mọi phép tính phải deterministic; model không được là nơi cộng số |
| 8 type đáp án, mỗi type một format duy nhất, sai format là sai | rulebook §9 **[đo]** | formatter là module riêng, không để model tự format |
| 5.324.954 dòng dữ liệu | **[đo]** | không có đường nhồi dữ liệu vào context |
| 60+ luật nghiệp vụ trong rulebook | **[đo]** | không nhồi rulebook vào prompt mỗi câu |
| API model opensource đã serving | anh nêu | endpoint thuộc config connector, không nằm trong code pipeline |

## 1.4 Chưa biết, cần xác nhận

Không tự đọc ra được từ dữ liệu:

1. Luật thi cho dùng **mấy** model? Có cho gọi API ngoài?
2. Giới hạn thời gian chạy cho 1.000 câu?
3. Có giới hạn số lần gọi model mỗi câu?

Ba câu này đổi §5.6 và §5.7. Trước khi có câu trả lời, plan giả định: nhiều model cùng họ được phép, không giới hạn thời gian ngặt.

---

# §2 Context đã thu thập

Toàn bộ §2 là **[đo]** trừ chỗ ghi nhãn khác.

## 2.1 Quy mô

| Mục | Số |
| --- | --- |
| Shop train | 30 (`biz_101`–`biz_130`) |
| Shop public test | 14 (`dev_001`–`dev_014`) |
| Tổng dòng | 5.324.954 |
| Shop lớn nhất / nhỏ nhất | `biz_124` 305.975 dòng, 13 file / `dev_012` 6.082 dòng, 2 file |
| Câu hỏi | train 3.000 có đáp án, public test 1.000 không đáp án |
| Định dạng | `csv` 30 file, `xlsx` 176 file, `sqlite` 2 file × 17 table |
| Tên cột phân biệt (đã normalize) | **449**; chỉ 27 cột xuất hiện ở ≥10 shop; 151 cột chỉ ở 1 shop |
| Câu hỏi đã chia theo shop | `train/data/<biz>/questions.jsonl`, `public_test/data/<dev>/questions.jsonl` |
| Split đánh giá | `train/split/` — 2.550 train / 450 test, stratified theo `(type, business_id)`, seed 42 |

## 2.2 Phân bố đáp án (train 3.000)

| type | n | % | format bắt buộc |
| --- | --- | --- | --- |
| `number` | 1884 | 62.8% | JSON number, **100% là số nguyên**, min −62.275.893 max 8.843.326.100 |
| `percent` | 578 | 19.3% | số phần trăm (12.4 không phải 0.124), 136 câu âm, 8 câu >100 |
| `list` | 193 | 6.4% | mảng có thứ tự; độ dài 3/2/5/11; phần tử `str` 106, `int` 87 |
| `date` | 145 | 4.8% | `YYYY-MM-DD` 129, `YYYY-MM` 16 |
| `string` | 88 | 2.9% | tên nguyên văn từ dữ liệu |
| `unanswerable` | 70 | 2.3% | `{"type":"unanswerable","reason":"…"}` |
| `boolean` | 23 | 0.8% | `true`/`false` |
| `table` | 19 | 0.6% | **100% là 2 cột**; 3 hoặc 5 dòng |

`number` + `percent` = **82.1%** điểm. `boolean` + `table` = 1.4%, và trong 450 câu test split mỗi loại chỉ còn **3 câu** — không đọc accuracy per-type cho hai loại này.

Trường `alias`: **167/3000** câu có, toàn bộ ở `list`/`string`/`table`. Scorer không chấm alias thì tự báo sai.

## 2.3 Phân bố chủ đề — train vs public test lệch rõ

| Chủ đề | train | public test | |
| --- | --- | --- | --- |
| doanh thu | 26.1% | 22.6% | |
| tỉ lệ / tỉ trọng | 18.6% | 18.2% | |
| kho, tồn, nhập, hạn dùng | 16.9% | 18.2% | |
| đếm số lượng | 12.2% | **17.8%** | **+5.6đ** |
| xếp hạng | 11.6% | 13.1% | |
| khách | 7.2% | **12.3%** | **+5.1đ** |
| nhân viên / thợ | 0.8% | **2.4%** | **×3** |
| bảo hành | **0%** | **1.0%** | **mới hoàn toàn** |
| lãi, giá vốn, chi phí | 0.4% | 1.2% | ×3 |
| Tết, âm lịch | 0.1% | 0.7% | ×7 |

Không được tune theo phân bố train.

## 2.4 Độ phức tạp câu hỏi

| Mục | train | public test |
| --- | --- | --- |
| Câu chỉ **1 phép tính đơn** (không dấu hiệu compose) | 61.5% | 58.2% |
| Cần so 2 kỳ | 9.3% | 12.1% |
| Cần ≥2 bảng canonical | 61.0% | 43.8% |
| Cần ≥3 bảng canonical | 21.8% | 15.1% |
| Có điều kiện ngưỡng ("từ 8 đơn trở lên") | 1.1% | **4.8%** |
| Có subquery lồng ("trong số khách đã mua…") | 0.3% | 0.5% |

## 2.5 Độ đa dạng intent — số quyết định phạm vi tool library

| Mục | train | public test |
| --- | --- | --- |
| Signature phân biệt | **316** / 3000 câu | 257 / 1000 câu |
| Số signature để phủ 50% câu | **16** | 17 |
| Phủ 80% | **73** | 89 |
| Phủ 95% | **182** | 207 |
| **Signature public test KHÔNG có trong train** | — | **119/257 signature = 18.2% câu** |

Signature = `(tập bảng cần, loại metric, dimension)` suy bằng regex. Heuristic thô nên con số là ước lượng, không chính xác tuyệt đối.

Hai hệ quả: 16 tool phủ được nửa số câu (rẻ, nên làm). Nhưng một library đóng xây từ train sẽ hụt ~18% câu thi.

## 2.6 Chất lượng câu hỏi đầu vào

| Dạng | n | % |
| --- | --- | --- |
| Câu **không có một dấu tiếng Việt nào** | 774 | 25.8% |
| Câu có từ bị bỏ dấu | 676 | 22.5% |
| Teencode / viết tắt (`bao nhiu`, `dthu`, `ko`, `dc`, `bnhiu`) | 469 | 15.6% |
| Độ dài | min 4 từ, p50 13, p95 22, max 41 |

Ví dụ nguyên văn: `"e so don hang quy 4/2025 la bao nhiu vay"`, `"trong so khach da mua hang thang 7/2026, bnhiu % mua tu 8 don tro len"`, `"soos kg nếp cái hoa vàng bán đc trong tháng 9/2025 là bao nhiêu"`.

## 2.7 Schema: cùng khái niệm, khác tên

44 shop gom thành **22 nhóm theo bộ tên file**, nhưng **tên cột không đi theo nhóm**. Bằng chứng, 4 shop cùng bộ 5 file csv, file `thanh_toan.csv`:

| shop | cột |
| --- | --- |
| `biz_111` | `Thời gian thu`, `Phương thức`, `Tiền`, `Mã phiếu thu`, `Số HĐ` |
| `biz_127` | `Số CT`, `Ngày thu`, `Mã GD`, `Giá trị`, `HTTT` |
| `biz_129` | `Mã GD`, `PTTT`, `Tiền`, `Mã giao dịch`, `Thời điểm` |
| `dev_010` | `Loại TT`, `Ngay thu`, `So tien`, `Mã đơn`, `Mã TT` |

Cùng 5 field semantic, 4 bộ tên, thứ tự shuffle, có BOM.

**README là nguồn mapping chính thức.** 44/44 shop đều có `## File` + `## Quy ước`, hầu hết có `## Cột trong <file>` mô tả nghĩa từng cột. Tập **nhãn quy ước là tập đóng, parse được** — 26 nhãn:

`Quy đổi đơn vị`, `Công nợ`, `Còn nợ`, `Tồn kho`, `Nhập hàng`, `Giá bán`, `Giá vốn`, `Lô, hạn dùng`, `Thuốc`, `Trả hàng`, `Hạn thanh toán`, `Giao hàng`, `Dòng hàng`, `Mã tham chiếu`, `Sổ chi phí`, `Phí phục vụ`, `Bàn`, `Topping`, `Đơn`, `Đơn khách trả lại`, `Tiền khách trả`, `Ghi tắt, loại hàng`, `Thu máy cũ`, `Sổ nợ`, `Sổ góp`, `Sổ bảo hành`.

Và **mọi README có dòng `Dữ liệu có đến hết DD/MM/YYYY`** — mốc bắt buộc cho luật unanswerable.

## 2.8 Generalization: 8/14 shop test không có anh em train

| Nhóm theo bộ tên file | Shop |
| --- | --- |
| Có cả train và test (6 nhóm) | `biz_112/115/118/130`+`dev_001`; `biz_107/113/126`+`dev_011`; `biz_111/127/129`+`dev_010`; `biz_105/117`+`dev_004`; `biz_110`+`dev_009`; `biz_123`+`dev_006` |
| **Test không có anh em train (8 shop)** | `dev_002`, `dev_003`, `dev_005`, `dev_007`, `dev_008`, `dev_012`, `dev_013`, `dev_014` |

Cộng thêm: rulebook public test có **3 ngành train không có** — Mẹ và bé (`dev_013`), Sửa xe (`dev_012`), Cửa hàng điện thoại (`dev_011`, `dev_014`) — mỗi ngành một bảng luật riêng.

## 2.9 Dữ liệu bẩn có chủ đích — 51 case

### Nhóm A: parse giá trị

| # | Case | Phạm vi |
| --- | --- | --- |
| 1 | Số dùng `,` ngăn nghìn | **24 shop, 117.703 ô** |
| 2 | Tiền kèm hậu tố `đ` | **18 shop, 61.837 ô** |
| 3 | Tiền ghi `k` (`'35k'`, `'270k'`) | 10 shop, 15.317 ô |
| 4 | Tiền ghi `tr` / `triệu` | 10 shop, 2.240 ô |
| 5 | Số kèm chữ (`'1 phần'`) | 18 shop, 29.876 ô |
| 6 | Dấu `.` ngăn nghìn (`'28.970.000đ'`) | trong case 2 |
| 7 | Ngày `DD/MM/YYYY` | 40 shop, 95.204 ô |
| 8 | **Serial Excel lẫn trong cột ngày text** (`'46054'` cạnh `'01/02/2026'`) | ≤30 shop, ≤16.918 ô — chặn trên, chưa khử false positive từ tiền 45.000–46.999 |
| 9 | Ngày tiếng Việt `'1 thg 7 2025'` | 10 shop, 7.661 ô. `biz_101`: **100%** ô dạng này, không một ô `DD/MM/YYYY` |
| 10 | Số âm biểu thị trả hàng | `biz_105`, `biz_117` |
| 11 | Số lưu dạng string (`so_luong='-1'`) | phổ biến |
| 51 | **BOM ở cột đầu file csv** (`'﻿Giá bán'`) | mọi file csv |

### Nhóm B: cấu trúc file

| # | Case | Phạm vi |
| --- | --- | --- |
| 12 | Header không ở dòng đầu | **147 sheet**. `dev_002` có 3 dòng tiêu đề trước header |
| 13 | Ô trống kế thừa theo nhóm dòng | **114 sheet**. `biz_103`: 228/397 dòng ô đầu rỗng. Rulebook §8: ô trống = giống dòng đầu nhóm, **không** phải thiếu dữ liệu |
| 14 | Chia sheet theo tháng/năm | `biz_102` 19 sheet, `biz_103` 17, `dev_014` 16. Rulebook §8: ngày không ghi năm → năm của sheet |
| 15 | Chia **file** theo tháng | `dev_002` 18 file, `dev_005` 23 file |
| 16 | Dữ liệu trong sqlite | `biz_123`, `dev_006`, 17 table. Đây là shop **dễ nhất** — schema đã chuẩn |
| 17 | Dòng trùng hoàn toàn | rulebook §8: cùng đơn giống mọi ô = lỗi xuất file, tính 1 lần; khác đơn = tính cả hai |
| 18 | **Hai cơ chế tồn kho khác nhau** | snapshot: `biz_106/108/117/119/120/124/128`, `dev_003/007/008`. Thẻ kho running balance: `biz_123`, `dev_006`. "Tồn tại ngày X" phải tính hai đường khác hẳn |
| 47 | Header gộp 2 dòng (merged group header) | `dev_013`, `biz_105` |

### Nhóm C: semantics nghiệp vụ

| # | Case | Phạm vi |
| --- | --- | --- |
| 19 | **Trả hàng ghi 3 cách** | (a) cột trạng thái: đa số; (b) số lượng âm: `biz_105`, `biz_117`; (c) text trong ghi chú: `dev_008`, `dev_011`, `dev_014`. Rulebook: đơn có trả hàng **kể cả một phần** thì bỏ **cả đơn** |
| 20 | Không có cột trạng thái | `dev_008`, `dev_011`, `dev_014` — trạng thái ở `Ghi chú`; ghi chú không nhắc = hoàn thành |
| 21 | 4 trạng thái, nhiều cách viết | `biz_101`: `Xong`/`Đã hủy`/`Đổi trả`/`Đang giao` |
| 22 | **Topping ghi chung ô với món** | `dev_002`: nối `" + "`, số phần đứng trước tên, tiền trong ngoặc đã cộng vào tổng dòng. Rulebook: topping là **mặt hàng riêng** |
| 23 | `" + "` trong ô (hoạt chất nhiều chất) | 11 shop, 1.834 ô. Thuốc phối hợp là **một loại riêng** |
| 24 | Tiền trong ngoặc trong ô text | 10 shop, 1.880 ô |
| 25 | `Phí phục vụ` là dòng hàng nhưng **không phải mặt hàng** | `biz_125/126/127/128/129/130`, `dev_007/008`. Không xếp hạng, không đếm, **vẫn tính doanh thu** |
| 26 | Tên hàng ghi tắt | `dev_011`, `dev_014` — sheet `Ghi tắt` |
| 27 | Entity chưa chuẩn hoá | `dev_012`: thợ `'A.Đức'`/`'Đức'`/`'a Đức'` là một người; xe xác định theo biển số |
| 28 | Sổ tay nhiều dòng con cho một bản ghi | `dev_014` `SoNo.xlsx`, sheet `Trả góp` |
| 29 | Liên kết chéo sổ bằng số thứ tự | `dev_014`: `Ghi chú='STT 26'` |
| 30 | **Ô nghiệp vụ là free text** | `dev_012` cột `Làm gì`: `'bdtq + vs nồi'`. Rulebook có luật riêng: `nhớt` trơn = nhớt máy, `sửa điện` không gồm thay bóng đèn. **Chỗ bắt buộc dùng model** |
| 31 | Quy đổi đơn vị nhiều cấp | `biz_119`: `1 vỉ = 12 viên`, `1 hộp = 180 viên`, nhưng `Clorpheniramin: 1 hộp = 10 vỉ` |
| 32 | Bảng quy đổi nằm ở 3 chỗ | README (18 shop), file riêng (14 shop), table sqlite (2 shop) |
| 43 | Dòng không phải hàng xen giữa | `dev_013`: `"Voucher"` (TT âm), `"Dùng n điểm"` (mỗi điểm 100đ, TT âm), `"Phí ship"` |
| 46 | Nối bảng qua **tên** thay vì mã | `dev_013`, `dev_003` |
| 48 | Chương trình khuyến mãi là bảng riêng | `dev_013` sheet `KhuyenMai` |
| 49 | Nhiều nguồn khác loại trong một shop | `biz_124` 3 nguồn, `dev_003` 4 nguồn |
| 50 | **Cùng mặt hàng, hai cách viết khác nhau ở khoảng trắng** | `biz_101`: `'Coca Cola 330ml'` 1.531 dòng và `'Coca  Cola 330ml'` 144 dòng. 4/70 mặt hàng bị vậy. **Đã xác nhận làm sai đáp án**: 2.298.000 thay vì 2.726.000, lệch 428.000 |

### Nhóm D: shop thiếu hẳn một loại dữ liệu

| # | Case | Shop |
| --- | --- | --- |
| 44 | **Không có chi tiết mặt hàng**, chỉ có đơn | `biz_110`, `dev_009`. Phân bố type xác nhận: `biz_110` chỉ có `number` (35) + `date` (5), không `list`/`string` |
| 45 | Không ghi mã đơn, không ghi tên khách | `biz_107`, `biz_113`, `biz_126` |

### Nhóm E: luật thời gian và chấm điểm

| # | Case | Nguồn |
| --- | --- | --- |
| 33 | "Tháng này" = ngày 1 → hết `as_of_date`; so tháng trước phải lấy **cùng số ngày** | rulebook §2 |
| 34 | "Tuần" bắt đầu thứ Hai; "tuần này" đến hết hôm nay; "tuần trước" là cả T2–CN | rulebook §2 |
| 35 | "Tháng M" không ghi năm = năm nay nếu không sau hôm nay, ngược lại năm trước | rulebook §2 |
| 36 | Tết = 23 tháng Chạp (âm Y−1) → mùng 10 tháng Giêng (âm Y), tra `calendar.csv` | rulebook §2 |
| 37 | Ca sáng 06:00–13:59, ca chiều 14:00–21:59, theo **giờ tạo đơn** | rulebook §2 |
| 38 | Bản ghi ngày **sau** `as_of_date` coi như chưa xảy ra — **trừ** trạng thái huỷ/trả hàng | rulebook mở đầu |
| 39 | **Hết dữ liệu ≠ bằng 0**: kỳ **hoàn toàn** ngoài khoảng dữ liệu → `unanswerable`; một phần ngoài → tính trên phần có | rulebook §7 |
| 40 | Tie-break: bằng nhau ở tiêu chí thì xếp theo **mã** tăng dần, không có mã thì theo tên | rulebook §9 |
| 41 | Làm tròn: tiền về đồng (nửa đồng lên); percent và trung bình khác 2 chữ số thập phân | rulebook §9 |
| 42 | Chấm `−1` cho sai, `0` cho bỏ trống | rulebook §9 |

## 2.10 Phân tích 70 câu `unanswerable`

Phân bố: 70 câu trên **12 shop** (trong 30). Cao nhất `biz_112` 12/118 (10.2%), `biz_103` 12/119 (10.1%). **18 shop không có câu nào.**

| Nguyên nhân | Ví dụ nguyên văn | Nhận ra bằng gì |
| --- | --- | --- |
| 1. Kỳ hỏi **hoàn toàn** ngoài khoảng ngày của shop | `biz_121`: "trong thang 2/2025, ti le don huy la bao nhieu %" | **deterministic** — so kỳ với `date_range` |
| 2. Shop không ghi loại thông tin đó | `biz_103`: "tổng tiền nhập hàng tháng này" (không có file nhập); `biz_112`: "trong kho còn bao nhiêu hộp Bánh croissant"; `biz_118`: "mấy khách nhà ở đường Hai Bà Trưng" | **deterministic** — `capability map` |
| 3. Khái niệm không tồn tại trong bất kỳ dữ liệu nào | `biz_106`: "Ai là người lành nghề nhất?"; `biz_105`: "khách hay khen nhân viên nào nhất" | cần model |
| 4. Nhìn như trả lời được nhưng không | `biz_130`: "% khách mua từ 8 đơn trở lên" | **chưa rõ**, nghi do shop không định danh được khách |

Hai nguyên nhân đầu — phần lớn — **không cần model**. Chúng là hệ quả trực tiếp của hai artifact mà tầng ingest phải sinh ra: `date_range` và `capability map`. Mỗi câu đoán sai hướng này mất **2 điểm** (−1 thay vì +1).

## 2.11 Bằng chứng ngoài — benchmark

Tất cả là **[benchmark]**, đo trên BIRD/dbt/BFCL, **không** đo trên bài này.

| Số | Giá trị |
| --- | --- |
| Schema linking là nguyên nhân lỗi text-to-SQL | **>60%** lỗi. Phân tích 4.602 query sai: **81.2%** failure là schema-level (chọn sai cột, hiểu sai semantics), không phải sai cú pháp |
| GPT-4 trên BIRD không evidence → có evidence | 34.88% → **54.89%** (+20 điểm) |
| Semantic layer vs schema thô (dbt 2026) | 64.5% → 72.7% trên schema chưa normalize; 90.0% → 98.2% (Claude) trên tập câu của họ |
| Model 14B tốt nhất trên BIRD | Arctic-Text2SQL-R1-14B **70.04%** EX; XiYanSQL-QwenCoder-14B 65.32%; BASE-SQL+Qwen2.5-Coder-14B 63.82% |
| Human trên BIRD | 92.96% |
| BFCL v3 (multi-turn tool calling) | top model 76.7%, trung bình 23 model **58.5**, std 17.5 |

Hai cách đọc ngược chiều, cả hai đều phải nói:
- Bài này **dễ hơn** BIRD: schema cố định per shop, không phải schema lạ mỗi câu. Nên 70% EX là chặn dưới bi quan.
- Bài này **khó hơn** BIRD: câu hỏi teencode (25.8% không dấu), và rulebook phức tạp hơn "evidence" một dòng của BIRD.

## 2.12 Một trace đã chạy thật

6 câu của `biz_101`, từ `ban_hang.csv` thô đến đáp án, **6/6 khớp tuyệt đối**. Script `scratchpad/trace.py`, 120 dòng, chỉ `csv` + `re` + `datetime`.

| Câu | Ra | Đáp án |
| --- | --- | --- |
| `tong dthu thang 6 nam 2025 la bn` | 202856500 | ✓ |
| `Nếp cái hoa vàng tháng 7/2025 bao nhiêu kg` | 45 | ✓ |
| `Mặt hàng bán chạy nhất tháng 6/2026` | Mì Hảo Hảo tôm chua cay | ✓ |
| `thang 5/2026 ngay nao ban dc nhieu tien nhat` | 2026-05-09 | ✓ |
| `Doanh thu Coca Cola 330ml tháng 5/2026` | 2726000 | ✓ |
| `thang 8/2025 ban duoc tong cong bao nhieu tien` | 204564500 | ✓ |

Số phụ từ trace: 56.501 dòng → **22.428 đơn**; 21.386 hoàn thành / 699 huỷ / 333 trả hàng / 10 đang giao; loại 1.032 đơn còn 21.396 đơn và 53.924 dòng; `date_range` thật `2025-06-01` → `2026-08-24` khớp mốc README.

Câu Coca Cola **sai ở lần chạy đầu** vì thiếu normalize whitespace (case 50). Đây là bằng chứng cho đặc tính nguy hiểm nhất của bài: **số vẫn ra, không exception, chỉ là sai.**

---

# §3 Lược đồ high level

## 3.1 Hai tầng, phân biệt theo số lần chạy

```
                      ┌─────────────────────────────────────────┐
                      │  TẦNG OFFLINE — chạy 44 lần (1/shop)    │
                      └─────────────────────────────────────────┘

 train/data/<biz>/          O1          O2            O3            O4
 public_test/data/<dev>/   ┌────┐   ┌────────┐   ┌──────────┐   ┌────────┐
   ├── *.csv      ────────▶│read│──▶│structure│─▶│normalize │   │ README │
   ├── *.xlsx     ────────▶│ er │   │ fixer   │  │  value   │   │ parser │
   ├── pos.sqlite ────────▶└────┘   └────────┘   └──────────┘   └────────┘
   └── README.md  ─────────────────────────────────────┬───────────┘
                                                       │ nhãn quy ước,
                                                       │ mốc ngày, quy đổi
                                                       ▼
                                                  ┌─────────┐
                                                  │   O5    │  ◀── MODEL
                                                  │ schema  │      (44 lần)
                                                  │ mapper  │
                                                  └─────────┘
                                                       │ mapping.json
                                                       ▼
                                   ┌───────────────────────────────┐
                                   │  O6  canonicalizer            │
                                   │  core 9 bảng + extension      │
                                   └───────────────────────────────┘
                                                       │ parquet
                                   ┌───────────────────┴───────────┐
                                   ▼                               ▼
                         ┌──────────────────┐          ┌─────────────────────┐
                         │ O7  rule views   │          │ O8  artifact        │
                         │ nhúng 60+ luật   │          │ • date_range        │
                         │ rulebook vào SQL │          │ • capability map    │
                         └──────────────────┘          └─────────────────────┘
                                   │                               │
                                   └──────────┬────────────────────┘
                                              ▼
                                   ┌─────────────────────┐
                                   │  DuckDB per shop    │
                                   └─────────────────────┘
                                              │
         ┌────────────────────────────────────┴──────────────────────────────┐
         │          TẦNG RUNTIME — chạy 4.000 lần (1/câu hỏi)                │
         └───────────────────────────────────────────────────────────────────┘

  question            R1              R2                R3             R4
  as_of_date       ┌──────┐      ┌─────────┐      ┌──────────┐   ┌───────────┐
  business_id ────▶│ norm │─────▶│ router  │─────▶│  time    │──▶│capability │
                   │ hoá  │      │QuerySpec│      │ resolver │   │  check    │
                   └──────┘      └─────────┘      └──────────┘   └───────────┘
                                   ◀── MODEL                           │
                                                          ┌────────────┴──────┐
                                                          │ kỳ ngoài dữ liệu? │
                                                          │ shop thiếu bảng?  │
                                                          └────────┬──────────┘
                                                        có │       │ không
                                                           ▼       ▼
                                              ┌─────────────┐  ┌──────────────┐
                                              │unanswerable │  │ R5  execute  │
                                              └─────────────┘  └──────┬───────┘
                                                                       │
                                                      ┌────────────────┴────────┐
                                                      ▼                         ▼
                                            ┌──────────────────┐     ┌──────────────────┐
                                            │ tool library     │     │ SQL fallback     │
                                            │ (code, đúng luật)│     │ ◀── MODEL        │
                                            └──────────────────┘     └──────────────────┘
                                                      └────────────┬────────────┘
                                                                   ▼
                                                        ┌─────────────────┐
                                                        │ R6  formatter   │
                                                        │ 8 type, làm tròn│
                                                        └─────────────────┘
                                                                   ▼
                                                        ┌─────────────────┐
                                                        │ R7 abstain gate │
                                                        │ p > 0.5 ?       │
                                                        └─────────────────┘
                                                                   ▼
                                                        submission.jsonl

         ┌───────────────────────────────────────────────────────────────────┐
         │          TẦNG ĐO — bọc ngoài cả hai tầng trên                    │
         └───────────────────────────────────────────────────────────────────┘
            M1 scorer (score/accuracy/coverage)
            M2 invariant checker (chạy sau O6, 6 bất biến)
            M3 experiment log (AGENT.md: manifest/rules/steps/logs/result)
```

## 3.2 Ba nguyên tắc đọc được từ lược đồ

| Nguyên tắc | Vì sao |
| --- | --- |
| **Mọi việc nặng ở offline** | offline nhân 44, runtime nhân 4.000. Đẩy một việc sang runtime là trả giá 90 lần |
| **Model xuất hiện đúng 3 chỗ** | O5 (44 lần), R2 (4.000 lần), SQL fallback (chỉ khi không có tool). Model **không** cộng số, so ngày, làm tròn, sinh đáp án cuối |
| **Luật nằm trong view, không trong prompt** | 81.2% lỗi text-to-SQL là schema-level **[benchmark]**. Nhúng luật vào view thì model không có chỗ bỏ sót |

## 3.3 Luồng dữ liệu mẫu — một câu thật đã chạy

Câu `"tong dthu thang 6 nam 2025 la bn"`, `as_of=2026-08-24`, `biz_101`, đáp án `202856500`.

| Bước | Input → Output |
| --- | --- |
| R1 | `"tong dthu thang 6 nam 2025 la bn"` → `"tổng doanh thu tháng 6 năm 2025 là bao nhiêu"` |
| R2 | → `{intent: "revenue_sum", period: {kind: "month", year: 2025, month: 6}, filters: {}, expect_type: "number"}` |
| R3 | → `(2025-06-01, 2025-06-30)` |
| R4 | cần `order_lines` → có ✓ ; kỳ ⊂ `date_range` ✓ → không unanswerable |
| R5 | `SELECT sum(line_amount) FROM v_revenue_lines WHERE order_date BETWEEN ? AND ?` → `202856500` |
| R6 | `number` → `202856500` (không dấu phân cách, không đơn vị) |
| R7 | parse được + capability đủ + kỳ trong khoảng → trả lời |

Cùng câu đó hỏi `biz_101` nhưng là `"hàng nào hết hạn trong 120 ngày tới"`: R4 thấy `capability map` không có `lots` → `{"type":"unanswerable"}`. Không cần model, không đoán.

---

# §4 Phân tích từng bước

Mỗi bước: làm gì, vì sao khó, case nào chạm, output kiểm chứng được.

## O1 — Reader

| | |
| --- | --- |
| Việc | đọc 4 định dạng, giữ `src_file` / `src_sheet` / `src_row` cho mọi dòng |
| Khó | `xlsx` 176 file; `openpyxl` chưa cài trong python global (đã dựng venv trong scratchpad) |
| Case | 16, 51 |
| Output | 44 shop ra số dòng > 0, so khớp với `inventory.json` (5.324.954 dòng) |
| Tại sao giữ `src_row` | 51 case bẩn đều sai âm thầm. Không có đường truy về ô gốc thì chỉ thấy số lệch, không biết tại sao |

## O2 — Structure fixer

| | |
| --- | --- |
| Việc | tìm header thật; nối sheet/file theo tháng-năm; kế thừa ô trống theo nhóm dòng; lấy năm từ tên sheet |
| Khó | **147 sheet** header không ở dòng đầu; **114 sheet** có ô trống kế thừa; `dev_013` và `biz_105` header gộp 2 tầng |
| Case | 12, 13, 14, 15, 47 |
| Output | số đơn đếm được khớp đếm tay trên 1 sheet mẫu mỗi shop |
| Rủi ro lớn nhất | case 13 ảnh hưởng trực tiếp phép **đếm đơn** và **đếm khách** — hai thứ chiếm 12.2–17.8% câu |

## O3 — Value normalizer

| | |
| --- | --- |
| Việc | số, tiền, ngày, số lượng, tên entity |
| Khó | 117.703 ô `,` ngăn nghìn; 61.837 ô `đ`; 15.317 ô `k`; 29.876 ô số kèm chữ; 16.918 ô nghi serial Excel; 7.661 ô ngày tiếng Việt |
| Case | 1–11, 50, 51 |
| Output | tỉ lệ ô parse fail theo từng pattern, theo shop; 0 ô fail im lặng |
| Đã chứng minh | `biz_101` 6/6 câu đúng sau khi có đủ nhánh `thg`, `,`, BOM, whitespace |
| Bẫy | case 50 — whitespace trong **tên hàng**, không phải trong số. Dễ bỏ qua nhất, đã xác nhận lệch 428.000 |

## O4 — README parser

| | |
| --- | --- |
| Việc | parse 26 nhãn quy ước (tập đóng), mốc `Dữ liệu có đến hết`, bảng quy đổi inline |
| Khó | README dài: `biz_120` 1.952 từ, `biz_119` 1.840. Bảng quy đổi ở 3 chỗ khác nhau (case 32) |
| Case | 32, 43, 46 |
| Output | 44 file `conventions.json`; mọi file có mốc ngày; 26 nhãn parse hết, nhãn lạ thì báo |
| Giá trị | README chính là "evidence" mà benchmark đo được là **+20 điểm** **[benchmark]** |

## O5 — Schema mapper ◀ MODEL

| | |
| --- | --- |
| Việc | `README + header + sample` → `mapping.json`: cột thô → canonical field |
| Khó | 449 tên cột, 151 cột chỉ xuất hiện ở 1 shop; cùng bộ file mà tên cột khác hẳn (§2.7) |
| Case | §2.7 toàn bộ |
| Output | 44 file `mapping.json`, người đọc được và sửa tay được; mỗi field bắt buộc có cột nguồn hoặc ghi rõ `null` |
| Chạy 44 lần, không 4.000 lần | map mỗi câu = 4.000 lần schema linking, và **không có chỗ nào kiểm chứng**. Map 1 lần/shop thì invariant bắt được |

## O6 — Canonicalizer

| | |
| --- | --- |
| Việc | ghi core + extension ra parquet |
| Core 9 bảng | `orders`, `order_lines`, `payments`, `products`, `unit_conversions`, `purchases`, `purchase_lines`, `stock`, `expenses` |
| Extension | `service_tickets` (`dev_012`), `installments`/`trade_ins` (`dev_014`), `warranties`, `shift_reports` (`dev_003`), `deliveries` (4 shop VLXD), `price_history`, `lots` (7 shop nhà thuốc) |
| Vì sao cần extension | `dev_012` không có khái niệm đơn + dòng hàng; `dev_014` có sổ góp kỳ hạn. Nhồi vào core thì shop đó để `NULL` quá nửa field |
| Triệu chứng làm sai | một shop phải `NULL` quá nửa field core → đẩy sang extension |
| Case | 18, 28, 29, 30, 44, 45, 49 |

## O7 — Rule views

| | |
| --- | --- |
| Việc | nhúng 60+ luật rulebook vào SQL view |
| 9 view | `v_valid_orders` (bỏ huỷ + bỏ **cả đơn** có dòng trả hàng), `v_revenue_lines`, `v_order_revenue`, `v_rankable_lines` (loại `Phí phục vụ`), `v_qty_base`, `v_debt_orders` (đơn trả hàng **vẫn tính** nếu còn nợ, loại COD/sàn), `v_debt_balance(as_of)`, `v_stock(as_of)` (2 nhánh snapshot/ledger), `v_customers` |
| Vì sao | model sinh `SELECT sum(revenue) FROM v_order_revenue WHERE ...` thì không còn chỗ bỏ sót luật |
| Case | 19, 20, 21, 25, 31, 38, 39 |
| Luật chỉ định nghĩa **một chỗ** | nếu tool library tự lọc lại thì hai nơi sẽ nói hai luật khác nhau |

## O8 — Artifact: `date_range` + `capability map`

| | |
| --- | --- |
| Việc | per shop: min/max ngày thật + mốc README; core/extension table nào tồn tại, field nào không rỗng |
| Vì sao quan trọng hơn vẻ ngoài | đây là đầu vào của unanswerable detector. 2/4 nguyên nhân unanswerable (§2.10) giải được **không cần model** |
| Case | 39, 44, 45 |
| Mất gì nếu bỏ | trả `0` thay vì `unanswerable` → mất **2 điểm/câu** |

## R1 — Question normalizer

| | |
| --- | --- |
| Việc | teencode, không dấu, viết tắt (`dthu`, `bnhiu`, `hqua`, `ddown`, `soos`) |
| Khó | 774 câu (25.8%) không một dấu tiếng Việt |
| Case | §2.6 |
| Output | đo riêng: router accuracy có/không có bước này |

## R2 — Intent router ◀ MODEL

| | |
| --- | --- |
| Việc | câu đã normalize → `QuerySpec` (Pydantic, enum đóng) |
| Khó | 316 signature phân biệt; **18.2% câu public test có signature không có trong train** |
| Output | `{intent, period, filters, group_by, top_k, expect_type}`; parse fail → abstain |
| Đây là chỗ model chạy 4.000 lần | mọi thứ khác nên gỡ khỏi bước này |

## R3 — Time resolver

| | |
| --- | --- |
| Việc | toàn bộ rulebook §2 thành code: `(cách nói, as_of_date)` → `(from, to)` + kỳ so sánh |
| Khó | "tháng này so tháng trước **cùng số ngày**"; tuần bắt đầu T2; tháng/quý không ghi năm; Tết âm lịch qua `calendar.csv` |
| Case | 33–37 |
| Output | unit test phủ **mọi dòng** rulebook §2, mỗi luật ≥2 ca biên |
| Phủ bao nhiêu câu | 69% câu train có kỳ thời gian rõ |

## R4 — Capability check / unanswerable

| | |
| --- | --- |
| Việc | kỳ ⊂ `date_range`? shop có bảng/field cần? |
| Case | 39, 44, 45 |
| Output | so với 70 câu `unanswerable` train: bắt được bao nhiêu, báo nhầm bao nhiêu |
| Lưu ý | `unanswerable` đúng được **+1**. Nhầm câu trả lời được thành `unanswerable` thì **−1**. Khác hẳn abstain (luôn 0) |

## R5 — Execute

| | |
| --- | --- |
| Việc | gọi tool library, hoặc SQL fallback |
| Số liệu quyết định phạm vi | 16 tool phủ 50% câu; 73 tool phủ 80%; 182 tool phủ 95% |
| Case | mọi case nghiệp vụ |
| Output | accuracy riêng từng nhánh. Nhánh fallback phải > 50% mới được bật, dưới đó nó đang trừ điểm |

## R6 — Formatter

| | |
| --- | --- |
| Việc | 8 type, mỗi type một format duy nhất; làm tròn; tie-break |
| Khó | tiền làm tròn về đồng (nửa đồng lên); percent 2 chữ số; `list` đúng cả tập **và** thứ tự; `table` 2 cột, cột đầu là tên |
| Case | 40, 41 |
| Output | sai format = sai. Đo riêng: bao nhiêu câu số đúng mà format sai |

## R7 — Abstain gate

| | |
| --- | --- |
| Việc | gom tín hiệu → quyết trả lời hay bỏ trống |
| Tín hiệu | router parse được không; self-consistency có đồng thuận; kỳ có trong `date_range`; invariant của shop có pass; bucket độ phức tạp |
| Case | 42 |
| Output | so 3 chính sách (trả hết / ngưỡng / ngưỡng + unanswerable) trên 450 câu test split, lấy **điểm** cao nhất |
| Ngưỡng chọn ở đâu | **trên `train/split/train_*.jsonl`**, không trên test split |

## M1 — Scorer

| | |
| --- | --- |
| Việc | chấm đúng rulebook §9: format trước, giá trị sau; chuỗi bỏ qua hoa/thường/khoảng trắng/dấu câu; **chấm cả `alias`** |
| Output | chấm `test_answers.jsonl` làm submission phải ra **450/450** |
| Vì sao làm trước mọi thứ | không có nó thì mọi phase sau không biết đang tiến hay lùi |
| Bẫy | 167/3000 câu có `alias`. Không chấm alias = tự báo sai |

## M2 — Invariant checker

6 bất biến, chạy sau O6 trên cả 44 shop:

| Invariant | Bắt case nào |
| --- | --- |
| `sum(order_lines.line_amount)` theo đơn khớp `orders.order_total` (sau giảm giá đơn, cộng phí giao) trên ≥99% đơn | 1–6, 50 |
| Mọi `order_date` ⊂ `[min_date, mốc README]` | 8, 9 |
| `sum(payments.amount)` theo đơn ≤ `order_total` | 24, 28 |
| Mọi `unit` trong `order_lines` có dòng `unit_conversions` hoặc là `base_unit` | 31, 32 |
| Mỗi đơn đúng 1 trạng thái trong {hoàn thành, huỷ, trả hàng, đang giao} | 19, 20, 21 |
| `count(distinct order_id)` khớp đếm tay 1 sheet mẫu/shop | 13 |

---

# §5 Phương án khả thi cho mỗi bước

Cách đọc: mỗi bảng là **một quyết định**. Cột *nghiêng về* là ý tôi kèm lý do — **không phải quyết định**. Anh chọn ở §6.

## D1 — Engine truy vấn dữ liệu canonical  (bước O6, O7, R5)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **DuckDB** đọc parquet | analytic query nhanh; không cần server; view SQL nhúng luật tự nhiên; đọc parquet/csv trực tiếp | thêm 1 dependency | ◀ **A** — view là chỗ nhúng 60+ luật, và SQL fallback cần một engine SQL thật |
| B | **SQLite** per shop | có trong stdlib; `biz_123`/`dev_006` vốn đã là sqlite | chậm hơn với aggregate trên 300k dòng; thiếu hàm analytic | |
| C | **pandas/polars** thuần, không SQL | không cần nghĩ về SQL | mất khả năng nhúng luật vào view; SQL fallback không còn đường chạy | |

## D2 — Nơi lưu canonical  (bước O6)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **parquet trên đĩa**, 1 bộ/shop | ingest 1 lần dùng mãi; debug được bằng cách mở file | tốn đĩa (~5.3M dòng) | ◀ **A** — 4.000 câu hỏi trên 44 shop, re-ingest mỗi lần là không trả nổi |
| B | sqlite file/shop | 1 file/shop, gọn | ghi chậm hơn parquet | |
| C | in-memory, ingest lại mỗi lần chạy | không tốn đĩa | ingest 44 shop mỗi lần đo = vòng lặp thực nghiệm chậm gấp nhiều lần | |

## D3 — Schema mapper  (bước O5)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **Model đọc `README + header + sample`** → `mapping.json`, chạy 44 lần | README là mô tả chính thức, 44/44 shop có; invariant kiểm được ngay sau đó | model có thể map sai field ít gặp | ◀ **A** |
| B | Từ điển rule-based (449 tên cột → canonical), model chỉ xử cột lạ | deterministic cho cột phổ biến | 151 cột chỉ xuất hiện ở 1 shop; shop test có cột chưa từng thấy → từ điển vô dụng với 8 shop lạ | |
| C | A + **sửa tay** cho shop fail invariant | chắc nhất cho train | không áp được cho test thật (shop khác); và che mất chỉ số generalization | chỉ nên dùng kèm log "bao nhiêu % shop cần can thiệp tay" |
| D | Không mapper — mỗi câu đưa `header + README` vào context | không có bước offline | 4.000 lần schema linking; 81.2% lỗi text-to-SQL là schema-level **[benchmark]**; không có chỗ kiểm chứng | |

## D4 — Hình dạng canonical schema  (bước O6)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **Core 9 bảng + extension theo ngành** | mỗi module tính toán chỉ phụ thuộc field nó đọc; shop lạ không làm phình core | phải quyết ranh giới core/extension | ◀ **A** — `dev_012` không có đơn+dòng hàng, `dev_014` có sổ góp kỳ hạn |
| B | Core rộng ôm hết mọi ngành | một schema duy nhất | shop phải `NULL` quá nửa field; field rỗng biến thành bug im lặng | |
| C | Không canonicalize, chỉ tạo **view đặt tên lại** trên bảng thô | ít code hơn | không xử được case 13/14/22/28 (ô trống kế thừa, nối sheet, topping, sổ tay) — những case này cần **biến đổi**, không chỉ đổi tên | |

## D5 — Cách thực thi phép tính  (bước R5)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **Tool library only** | deterministic, test được, đúng luật | 73 tool mới phủ 80%; **18.2% câu test có signature lạ** → hụt | |
| B | **SQL only** trên rule view | phủ mọi câu | model 14B tốt nhất trên BIRD 70.04% EX **[benchmark]**; variance thành điểm âm trực tiếp | |
| C | **Tool (16 tool, phủ 50%) + SQL fallback cho đuôi** | lấy determinism ở chỗ dày, lấy độ phủ ở chỗ thưa | hai đường code, phải đảm bảo cùng dùng một định nghĩa luật (chỉ trong view) | ◀ **C** |
| D | Tool (73 tool, phủ 80%) + SQL fallback | phủ nhiều hơn bằng code | 73 tool là nhiều công sức cho phần đuôi mỏng | |

## D6 — Cách model hiểu câu hỏi  (bước R2)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **Single-shot structured output** → `QuerySpec` Pydantic, parse fail = abstain | 1 lần gọi/câu; abstain tự nhiên; rẻ | câu nhiều mệnh đề có thể không gói hết vào 1 spec | ◀ **A** — 61.5% câu là 1 phép tính đơn |
| B | **ReAct agent loop** (gọi tool, xem kết quả, gọi tiếp) | giải được câu cần compose | BFCL v3 top model 76.7%, trung bình 23 model **58.5** **[benchmark]**; mỗi turn thêm là một cơ hội sai, và sai bị −1 | |
| C | **2 tầng**: coarse intent (8–12 nhóm) → slot filling riêng cho nhóm đó | mỗi lần gọi quyết ít thứ, phù hợp model <15B | 2 lần gọi/câu = 8.000 lần gọi | ◀ cân nhắc nếu A cho intent accuracy < 85% |

## D7 — Số model và model nào  (xuyên suốt)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **1 model** cho cả mapping, router, SQL | đơn giản; chắc chắn hợp luật thi | 1 model phải vừa giỏi tiếng Việt vừa giỏi SQL | |
| B | **2 model**: Qwen3-14B cho tiếng Việt (O5, R2, free text) + Qwen2.5-Coder-14B cho SQL | mỗi việc một model mạnh đúng chỗ | **chưa biết luật thi có cho phép** (§1.4) | ◀ **B** nếu luật thi cho phép, ngược lại A với Qwen3-14B |
| C | Fine-tune LoRA cho router trên 2.550 câu train split | anh có sẵn kỹ năng và hạ tầng; router là bài classification hẹp | tốn 1 vòng train; rủi ro overfit vào 30 shop train | ◀ cân nhắc sau khi A/B có baseline |

Ứng viên model, tất cả < 15B:

| Model | Tham số | Ghi chú |
| --- | --- | --- |
| Qwen3-14B | 14B | tiếng Việt tốt nhất nhóm này **[giả thuyết]**, chưa đo trên bài này |
| Qwen2.5-Coder-14B | 14B | BASE-SQL + model này đạt 63.82% EX trên BIRD **[benchmark]** |
| Arctic-Text2SQL-R1-14B | 14B | **70.04%** EX trên BIRD, cao nhất nhóm <30B **[benchmark]**; nhưng chuyên SQL, không rõ tiếng Việt |
| XiYanSQL-QwenCoder-14B | 14B | 65.32% EX **[benchmark]** |
| Gemma-3-12B-it | 12B | multilingual tốt, ít dữ liệu về tiếng Việt kỹ thuật |
| Phi-4 | 14B | reasoning tốt, tiếng Việt yếu |

## D8 — Few-shot cho router  (bước R2)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **Static few-shot**, 10–20 ví dụ chọn tay từ `train_questions.jsonl` | đơn giản, prompt cố định, cache được | không phủ 316 signature | ◀ **A** cho baseline |
| B | **Retrieval few-shot**: embed câu hỏi, lấy k câu gần nhất trong 2.550 câu train split | phủ tốt hơn; anh có sẵn embedder tiếng Việt | thêm 1 lần gọi embedding/câu; prompt không cache được | ◀ **B** nếu A dưới mục tiêu |
| C | Không few-shot, chỉ schema + enum | rẻ nhất | model 14B khó bám đúng enum | |

## D9 — Phân loại độ phức tạp câu hỏi  (trước R7)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **Không phân loại**, một ngưỡng abstain duy nhất | đơn giản | bỏ mất thông tin: câu 4 bảng + so 2 kỳ có `p` khác hẳn câu 1 bảng | |
| B | **Phân loại bằng đặc trưng đếm được** từ `QuerySpec`: số bảng, có so kỳ, có top-k, có ngưỡng, có subquery | rẻ, deterministic; cho phép ngưỡng abstain **per bucket** | phải đo `p` từng bucket trên train split | ◀ **B** — EV `2p−1` nên biết `p` theo bucket là thông tin đổi được thành điểm |
| C | Phân loại bằng model | linh hoạt | thêm 1 lần gọi/câu, và phân loại sai thì route sai | |

## D10 — Abstain policy  (bước R7)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **Trả lời tất**, không abstain | coverage 100% | mỗi câu `p<0.5` là âm điểm | |
| B | **Ngưỡng cố định** trên tín hiệu nhị phân (parse fail, capability thiếu) | đơn giản, bắt được phần rõ ràng | không phân biệt mức độ không chắc | ◀ **B** cho vòng 1 |
| C | **Self-consistency**: sinh k mẫu, chỉ trả khi ≥m mẫu cùng kết quả | ước lượng `p` thật; khớp trực tiếp với EV | k lần gọi model/câu | ◀ **C** cho nhánh SQL fallback |
| D | B + C + ngưỡng per bucket (D9-B) | tối ưu điểm nhất | phức tạp nhất, cần đo nhiều | ◀ đích cuối |

## D11 — unanswerable detector  (bước R4)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **Deterministic only**: `date_range` + `capability map` | miễn phí nếu O8 có; bắt được nguyên nhân 1 và 2 (phần lớn trong 70 câu) | bỏ nguyên nhân 3 ("ai lành nghề nhất") | ◀ **A** cho vòng 1 |
| B | A + model cho nguyên nhân 3 | phủ hơn | nhầm câu trả lời được thành unanswerable thì **−1** | |
| C | Không detect, luôn trả số | không code gì | trả `0` thay vì `unanswerable` mất **2 điểm/câu** | |

## D12 — Time resolver  (bước R3)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **Code toàn bộ** rulebook §2, model chỉ trả về `period` dạng structured | deterministic; test phủ được mọi luật | phải code hết các ca biên | ◀ **A** — "tháng này so tháng trước cùng số ngày" là loại luật model sẽ làm sai im lặng |
| B | Model trả về trực tiếp `(from, to)` | ít code | model tự tính ngày = model làm số học; sai im lặng | |
| C | Hybrid: model trả `period` structured, code resolve, và **kiểm chéo** với model | có lớp kiểm | 2 lần gọi | |

## D13 — Xử lý free text nghiệp vụ  (`dev_012` cột `Làm gì`)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **Model phân loại 1 lần cho mỗi giá trị phân biệt**, cache thành từ điển | chạy ít lần; từ điển đọc và sửa được | cần biết tập giá trị phân biệt trước | ◀ **A** |
| B | Regex + từ điển viết tay | deterministic | `'bdtq + vs nồi'`, `'bộ nhông xích + thay nước má'` — rulebook còn có luật `nhớt` trơn ≠ nhớt láp, `sửa điện` không gồm thay bóng đèn | |
| C | Bỏ qua, abstain mọi câu cần `Làm gì` | không code | `dev_012` có 6.082 dòng và một phần câu hỏi public test | |

## D14 — Thứ tự xây  (xuyên suốt)

| | Phương án | Ưu | Nhược | Nghiêng về |
| --- | --- | --- | --- | --- |
| A | **Vertical slice**: 1 shop (`biz_101`) chạy xuyên suốt O1→R7 trước, rồi mở rộng 44 shop | có số thật sớm nhất; đã chứng minh 6/6 câu bằng `trace.py` | kiến trúc có thể phải sửa khi gặp shop khác họ | ◀ **A** |
| B | **Horizontal**: làm xong O1–O8 cho cả 44 shop, rồi mới làm runtime | ingest chắc trước | không có điểm nào đo được cho tới rất muộn | |
| C | 3 shop khác họ (`biz_101` csv phẳng, `biz_119` nhiều xlsx, `biz_123` sqlite) chạy xuyên suốt | phát hiện sớm chỗ kiến trúc vỡ, vẫn có số sớm | chậm hơn A một chút | ◀ **C** nếu muốn chắc hơn A |

## D15 — Thứ tự ưu tiên nếu thiếu thời gian

Xếp theo điểm/công sức, từ phân bố đã đo:

| # | Việc | Phủ bao nhiêu điểm |
| --- | --- | --- |
| 1 | M1 scorer | 0% trực tiếp, nhưng không có nó thì mọi số sau là mù |
| 2 | O1–O3 reader + structure + normalizer | 100% — mọi câu đi qua đây |
| 3 | R3 time resolver | 69% câu có kỳ thời gian rõ |
| 4 | Tool: doanh thu + đếm + tỉ lệ theo kỳ | `number`+`percent` = **82.1%** điểm |
| 5 | O8 + R4 unanswerable deterministic | 2.3% câu, mỗi câu **+1** thay vì −1 |
| 6 | R7 abstain gate | chuyển câu sai từ −1 về 0 |
| 7 | Tool: xếp hạng + tie-break | `list`+`string`+`date` = 14.1% |
| 8 | SQL fallback | đuôi dài, 18.2% signature lạ |
| 9 | `table`, `boolean` | 1.4%, và test split chỉ 3 câu mỗi loại |

---

# §6 Ô chọn — anh điền

Điền cột **Chọn** rồi tôi làm theo. Để trống = tôi chờ, không tự quyết.

| # | Quyết định | Phương án | Nghiêng về | **Chọn** |
| --- | --- | --- | --- | --- |
| D1 | Engine truy vấn | A DuckDB / B SQLite / C pandas | A | |
| D2 | Nơi lưu canonical | A parquet / B sqlite / C in-memory | A | |
| D3 | Schema mapper | A model+README / B từ điển / C A+sửa tay / D không mapper | A | |
| D4 | Hình dạng schema | A core+extension / B core rộng / C chỉ view đổi tên | A | |
| D5 | Cách thực thi | A tool only / B SQL only / C 16 tool+SQL / D 73 tool+SQL | C | |
| D6 | Model hiểu câu hỏi | A single-shot / B ReAct loop / C 2 tầng | A | |
| D7 | Số model | A một / B hai / C fine-tune LoRA | B (chờ luật thi) | |
| D8 | Few-shot | A static / B retrieval / C không | A | |
| D9 | Phân loại độ phức tạp | A không / B đặc trưng đếm được / C model | B | |
| D10 | Abstain policy | A trả hết / B ngưỡng / C self-consistency / D kết hợp | B rồi D | |
| D11 | unanswerable | A deterministic / B A+model / C không | A | |
| D12 | Time resolver | A code hết / B model / C hybrid | A | |
| D13 | Free text `Làm gì` | A model 1 lần/giá trị / B regex / C abstain | A | |
| D14 | Thứ tự xây | A 1 shop slice / B horizontal / C 3 shop slice | A hoặc C | |

Ba câu cần anh xác nhận, không đọc ra được từ dữ liệu:

| # | Câu hỏi | Ảnh hưởng |
| --- | --- | --- |
| Q1 | Luật thi cho dùng **mấy** model? Có cho API ngoài? | D7 |
| Q2 | Giới hạn thời gian chạy 1.000 câu? | D6, D10 (self-consistency nhân k lần gọi) |
| Q3 | Giới hạn số lần gọi model mỗi câu? | D6-C, D8-B, D10-C |

---

# §7 Việc đo còn thiếu

Chưa làm, cần làm trước khi code tầng tương ứng:

| # | Việc đo | Cho bước nào |
| --- | --- | --- |
| 1 | Serial Excel (case 8): đo lại **chỉ trên cột đã map là cột ngày**, khử false positive từ tiền 45.000–46.999 | O3 |
| 2 | Khoảng ngày thật từng shop so với mốc README — mâu thuẫn ảnh hưởng luật unanswerable | O8 |
| 3 | Tỉ lệ đơn huỷ / trả hàng từng shop, để biết case 19 ảnh hưởng bao nhiêu % doanh thu | O7 |
| 4 | 70 câu `unanswerable` train: xác định nguyên nhân thật từng câu, đặc biệt nhóm 4 (§2.10) | R4 |
| 5 | Gán nhãn intent tay cho 100 câu, làm ground truth đo router accuracy | R2 |
| 6 | `p` thực nghiệm theo từng bucket độ phức tạp | D9, R7 |
