# 07 — Hệ thống trả lời câu hỏi DataMate chạy như thế nào

Dành cho: người mới, chưa biết gì về dự án.
Tài liệu mô tả code **đang chạy** ngày 2026-11-06 (model `google/gemma-3-12b-it`, prompt `v9`).

---

## 1. Bài toán

| | |
|---|---|
| **Đầu vào** | Một câu hỏi tiếng Việt của chủ cửa hàng, ngày hôm nay, và dữ liệu bán hàng của cửa hàng đó (file Excel/CSV, mỗi cửa hàng ghi một kiểu khác nhau) |
| **Đầu ra** | Một đáp án đúng định dạng, ví dụ `{"id": "q_01d1099489a0", "type": "percent", "answer": -2.94}` |
| **Chấm điểm** | Đúng +1, sai −1, bỏ trống 0 |
| **Ràng buộc** | Chỉ được dùng model dưới 15B tham số |

Ví dụ dùng xuyên suốt tài liệu này:

> Cửa hàng `dev_005` (nhà thuốc). Hôm nay là 18/03/2025.
> Câu hỏi: *"Từ đầu tháng này tới hết hnay, dthu cao hay thấp hơn cùng kỳ tháng trước mấy %?"*
> Đáp án đúng: `-2.94` (doanh thu 1–18/3 thấp hơn 1–18/2 là 2,94%).

---

## 2. Sơ đồ tổng

```
╔══════════════════ LÀM TRƯỚC, MỘT LẦN (không dùng LLM) ══════════════════╗
║                                                                          ║
║  Dữ liệu thô của mỗi cửa hàng          Câu hỏi train + đáp án đúng       ║
║  (Excel, CSV, tên cột lung tung)       (3000 câu)                         ║
║            │                                    │                         ║
║            ▼  BƯỚC A: chuẩn hoá                  ▼  BƯỚC B: dựng thư viện  ║
║                                                                          ║
║  Bảng sạch, tên cột chuẩn              Thư viện ~1000 cặp                 ║
║  (artifacts/norm/<cửa hàng>/)          "câu hỏi → 1 dòng code đúng"       ║
╚══════════════════════════════════════════════════════════════════════════╝
                 │                                    │
                 ▼                                    ▼
╔══════════════════════════ MỖI CÂU HỎI ══════════════════════════════════╗
║                                                                          ║
║  Câu hỏi + ngày hôm nay + mã cửa hàng                                     ║
║       │                                                                  ║
║       ▼  C1. Soạn đề bài cho LLM ............................... [CODE] ║
║       │      luật cuộc thi + danh sách bảng + gợi ý + 4 ví dụ giống nhất  ║
║       ▼  C2. Chọn một bảng để xem ................................ [LLM] ║
║       ▼  C3. Đưa 10 dòng đầu bảng, nhắc lại câu hỏi ............. [CODE] ║
║       ▼  C4. Viết 1 dòng code gọi hàm tính sẵn ................... [LLM] ║
║       ▼  C5. Chạy dòng code đó, kiểm kết quả ................... [CODE] ║
║       │      ├─ lỗi  → gửi dòng lỗi cho LLM, quay lại C4 (tối đa 10 lượt) ║
║       │      └─ được → sang C6                                            ║
║       ▼  C6. Ghi đáp án vào answers.jsonl ....................... [CODE] ║
╚══════════════════════════════════════════════════════════════════════════╝
                 │
                 ▼  BƯỚC D: gom 1000 đáp án, kiểm định dạng ........ [CODE]
            submission.jsonl (file nộp)
```

**Ý chính:** LLM chỉ làm hai việc là chọn bảng để xem (C2) và viết **một dòng code gọi hàm có sẵn** (C4). Mọi phép tính đều do code Python viết sẵn làm. Code này deterministic: cùng đầu vào luôn ra cùng kết quả.

---

## 3. Bước A — Chuẩn hoá dữ liệu cửa hàng

**Vấn đề.** Mỗi cửa hàng đặt tên cột một kiểu. Cùng là "tiền của một dòng hàng", có nơi ghi `Tổng tiền`, nơi ghi `Thanh tien`, nơi ghi `TriGia`. Ngày có nơi ghi `18/03/2025`, nơi ghi `2025-03-18`. Tiền có nơi ghi `45.000đ`.

**Cách làm.** Đổi mọi cột về **một bộ tên chuẩn**, gọi là *role*. Có 42 role, ví dụ `order_id` (mã đơn), `order_date` (ngày bán), `item_name` (tên hàng), `quantity` (số lượng), `line_amount` (tiền của dòng).

| Việc | Ví dụ với `dev_005` |
|---|---|
| 1. Đọc mọi file, tìm dòng tiêu đề | `BanHang_Thang01_2025.xlsx`, sheet `DonHang_ChiTiet`, tiêu đề ở dòng 4 |
| 2. Gán role cho từng cột: dựa vào mô tả cột trong `README.md` của cửa hàng, không có thì dựa vào tên cột đã gặp | `Mã đơn hàng` → `order_id`, `Ngày đặt hàng` → `order_date`, `Tên sản phẩm` → `item_name`, `Số lượng sản phẩm` → `quantity`, `Tổng tiền` → `line_amount` |
| 3. Kiểm role: cột tiền mà dưới 90% ô đọc được thành số thì bỏ role đó | |
| 4. Xếp loại bảng: bán hàng, nhập hàng, danh mục hàng, khách… | bảng có `order_id` + ngày + tiền → bảng bán hàng (`sales`) |
| 5. Làm sạch: ngày về `YYYY-MM-DD`, tiền về số, bỏ dòng "Tổng cộng", bỏ dòng trùng | `45.000đ` → `45000` |
| 6. Ghép: gộp các cách viết của cùng một tên hàng, quy đổi đơn vị lớn ra đơn vị nhỏ nhất | `1 hộp Tiffy Dey` = 25 vỉ × 4 viên = 100 viên |

**Đầu ra:** thư mục `artifacts/norm/dev_005/` gồm `sales.csv`, `catalog_*.csv`… cùng `mapping.json`, file ghi lại cột nào được đổi thành role nào.

**Vì sao không để LLM tự làm việc này:** đã thử. Gemma tự làm sạch dữ liệu thì đúng 0/10 câu (xem `FAILURES.md`).

**Code:** `src/datamate_agent/prepare.py` (chạy), `normalize.py` (làm sạch), `column_roles.py` (gán role).

---

## 4. Hàm tính sẵn — thứ LLM được gọi

Trên bảng sạch có sẵn khoảng 75 hàm Python, gọi là *helper*. LLM không phải viết code xử lý bảng (pandas), chỉ cần gọi đúng hàm với đúng tham số.

| Nhóm | Ví dụ |
|---|---|
| Kỳ thời gian (`clock`) | `clock.month(5, 2026)`, `clock.this_month()` (đầu tháng tới hôm nay), `clock.last_month_same_days()` (cùng số ngày ở tháng trước), `clock.tet(2026)` |
| Tiền, đơn | `revenue(kỳ)`, `order_count(kỳ)`, `average_order(kỳ)`, `gross_profit(kỳ)` |
| Hàng | `quantity(kỳ, item="Panadol Extra")`, `ranking(by="item", period=kỳ)` (xếp hạng) |
| So sánh | `pct_change(a, b)` (phần trăm thay đổi từ b sang a) |
| Theo ngành | nhà thuốc: `expiring_items(...)`; sửa xe: `repair_count(kỳ, job="sửa điện")`; điện thoại: `machines_sold(kỳ)` |

Mỗi hàm đã làm sẵn luật của ban tổ chức: không tính đơn huỷ, không tính đơn trả hàng, quy đổi đơn vị… Nhờ vậy LLM không cần nhớ các luật này.

**Code:** `src/datamate/shop.py` (lớp `Shop`, hàm chung), `src/datamate/domains/` (hàm theo ngành), `src/datamate/periods.py` (`clock`).

---

## 5. Bước B — Thư viện ví dụ

**Làm gì.** Tạo sẵn các cặp "câu hỏi → một dòng code đúng" để đưa cho LLM bắt chước.

**Cách làm.** Một bộ giải viết tay bằng luật (`oracle.py`, không dùng LLM) đọc từng câu hỏi train, đoán code theo mẫu câu, chạy code đó rồi so với đáp án đúng. Câu nào ra đúng thì lưu cặp lại.

Ví dụ một cặp trong thư viện:

```
Câu hỏi: từ đầu tháng này đến hết bữa nay, dthu hown hay kém cungf kỳ th trước mấy %
Code:    FINAL percent: pct_change(revenue(clock.this_month()), revenue(clock.last_month_same_days()))
```

**Đầu ra:** `prompts/library.jsonl` có 967 cặp sinh tự động, `prompts/library_curated.jsonl` có 109 cặp viết tay.

---

## 6. Bước C — Trả lời một câu hỏi

### C1. Soạn đề bài cho LLM [CODE]

LLM nhận hai phần:

**Phần chung (system prompt):** luật của ban tổ chức (nguyên văn), cách làm việc (lượt đầu phải đọc một bảng, nộp bài bằng `FINAL`), danh sách bảng sạch của cửa hàng kèm cột, README của cửa hàng, và danh sách hàm theo ngành nếu cửa hàng thuộc ngành đó.

**Phần riêng của câu hỏi (user prompt).** Đây là prompt thật của câu ví dụ:

```
Hôm nay là 2025-03-18.
Câu hỏi: Từ đầu tháng này tới hết hnay, dthu cao hay thấp hơn cùng kỳ tháng trước mấy %?

Nhận ra trong câu: kỳ clock.this_month(); kỳ đem ra so clock.last_month_same_days()
Nhóm hàng của shop: ['dùng ngoài', 'dị ứng', 'giảm đau hạ sốt', ...]

Câu tương tự đã làm đúng ở shop khác:
- từ đầu tháng này đến hết bữa nay, dthu hown hay kém cungf kỳ th trước mấy %
  FINAL percent: pct_change(revenue(clock.this_month()), revenue(clock.last_month_same_days()))
- Doanh thu từ đầu năm tới hết hnay là bao nhiêu?
  FINAL number: revenue(clock.year_to_date())
- (thêm 2 ví dụ)
```

Code tạo phần riêng này theo ba bước:

| Bước | Làm gì | Ví dụ |
|---|---|---|
| Nhận ra trong câu | Tìm kỳ thời gian, tên hàng, tên khách, nhóm hàng, cách thanh toán bằng luật viết sẵn, rồi ghi ra đúng như trong dữ liệu | "đầu tháng này tới hết hnay … cùng kỳ tháng trước" → `clock.this_month()` và `clock.last_month_same_days()` |
| Che tên riêng | Thay tên hàng, tên khách… bằng nhãn, để hai câu khác tên hàng vẫn được coi là giống nhau | "bán bao nhiêu hộp Panadol" → "bán bao nhiêu hộp `<item>`" |
| Chọn 4 ví dụ | So câu đã che với thư viện bằng TF-IDF (đếm từ chung, từ càng hiếm càng nặng điểm). Lấy 4 câu giống nhất, mỗi câu một dạng code khác nhau | ví dụ đầu tiên ở trên |

**Code:** `agent.py` (`build_system`, `user_hints`), `fewshot.py` (chọn ví dụ, nhận tên), `intents.py` (nhận kỳ).

### C2. LLM chọn một bảng để xem [LLM]

Lượt đầu, LLM bắt buộc trả lời đúng một dòng dạng `READ norm/<bảng>.csv`. Ví dụ: `READ norm/sales.csv`.

### C3. Đưa bảng cho LLM [CODE]

Code gửi lại 10 dòng đầu của bảng, nhắc lại câu hỏi và nhắc lại ví dụ giống nhất.

### C4. LLM viết code [LLM]

LLM có hai lựa chọn:

- **Chạy thử** một khối code để xem kết quả, rồi viết tiếp ở lượt sau.
- **Nộp bài**: một dòng `FINAL <kiểu đáp án>` kèm code.

Câu ví dụ được nộp luôn ở lượt này, chép đúng ví dụ đầu tiên:

```
FINAL percent
pct_change(revenue(clock.this_month()), revenue(clock.last_month_same_days()))
```

Kiểu đáp án là một trong: `number`, `percent`, `date`, `boolean`, `string`, `list`, `table`, `unanswerable` (dữ liệu không đủ để trả lời).

### C5. Chạy và kiểm [CODE]

Code chạy dòng của LLM trong một tiến trình Python riêng. Tiến trình này đã nạp sẵn bảng sạch và mọi hàm ở mục 4, có giới hạn 120 giây. Ví dụ ra `-2.94`.

Trước khi nhận đáp án, code kiểm:

| Kiểm gì | Nếu sai thì |
|---|---|
| Lượt đầu có phải `READ` không | báo lỗi, bắt làm lại |
| Code có chạy được và in ra giá trị không | gửi dòng lỗi cuối cho LLM sửa |
| Giá trị có đúng kiểu đã khai không (số, ngày `YYYY-MM-DD`…) | báo lỗi |
| Có phải số tự nghĩ ra, không gọi hàm nào không | từ chối |
| Code có y hệt lần trước không | từ chối, bắt đổi |
| Khai `number` nhưng câu hỏi có `%` | tự đổi thành `percent` |
| Nộp `unanswerable` khi chưa thử hàm nào | từ chối một lần, bắt thử hàm trước |
| Hết 10 lượt | cho thêm 3 lượt chỉ để nộp; vẫn không nộp được thì bỏ trống (0 điểm, không bị −1) |

### C6. Ghi đáp án [CODE]

Code ghi một dòng vào `answers.jsonl`: `{"id": "q_01d1099489a0", "type": "percent", "answer": -2.94}`.

**Code của C2–C6:** `agent.py` (`solve`, `_execute`, `_final`).

---

## 7. Bước D — Đóng gói file nộp [CODE]

Gom đáp án của 1000 câu rồi kiểm định dạng từng câu theo luật của ban tổ chức. Câu nào sai định dạng hoặc không có đáp án thì ghi thành bỏ trống (`abstain`, 0 điểm) thay vì để bị −1.

**Code:** `experiments/<thí nghiệm>/code/make_submission.py`.

---

## 8. Ai làm gì

| Việc | Code | LLM |
|---|:---:|:---:|
| Đọc và làm sạch dữ liệu thô | ✔ | |
| Nhận ra kỳ, tên hàng, tên khách trong câu | ✔ | |
| Chọn ví dụ giống nhất | ✔ | |
| Chọn bảng để xem | | ✔ |
| Chọn hàm, tham số, kiểu đáp án | | ✔ |
| Quyết định "không trả lời được" | chặn khi chưa thử hàm | ✔ |
| Tính toán | ✔ | |
| Kiểm và sửa định dạng đáp án | ✔ | |

---

## 9. Thuật ngữ

| Từ | Nghĩa |
|---|---|
| **role** | Tên chuẩn của một loại cột, ví dụ `line_amount` = tiền của một dòng hàng |
| **bảng sạch** (`norm/`) | Bảng sau bước A: tên cột là role, ngày và tiền đã đúng định dạng |
| **`lines`** | Bảng chính mọi hàm dùng: mỗi dòng là một mặt hàng trong một đơn bán, đã ghép tên khách, nhóm hàng, quy đổi đơn vị |
| **helper** | Hàm Python tính sẵn, ví dụ `revenue`, `quantity` |
| **`clock`** | Bộ hàm tạo kỳ thời gian theo ngày hôm nay của câu hỏi |
| **as_of** | Ngày hôm nay của câu hỏi; dữ liệu sau ngày này bị ẩn |
| **few-shot** | Đưa vài ví dụ đã đúng vào prompt để LLM bắt chước |
| **TF-IDF** | Cách đo hai câu giống nhau: đếm từ chung, từ càng hiếm càng nặng điểm |
| **oracle** | Bộ giải viết tay bằng luật, không dùng LLM; dùng để dựng thư viện ví dụ và để kiểm tra sửa code có làm sai câu nào không |
| **PA** | Điểm cuộc thi: (số câu đúng − số câu sai) / tổng số câu |

---

## 10. Hiện trạng

| Tập | PA | Ghi chú |
|---|---|---|
| Public, hệ thống chấm | 0,811 | bản nộp ngày 2026-11-05 |
| Public, chấm ở máy so với bản Claude | 0,845 | sau khi sửa ngày 2026-11-06, chưa nộp |
| `train/split/test_*` (450 câu, có đáp án đúng) | 0,644 | 6 cửa hàng không dựng được bảng `lines` kéo điểm xuống |

Điểm yếu lớn nhất, xếp theo số câu sai:

1. **LLM chép ví dụ giống nhất kể cả khi ví dụ đó sai dạng.** 74% câu sai trên public là chép đúng hàm của ví dụ đầu tiên. Ví dụ: câu hỏi "bao nhiêu **ly**" nhưng ví dụ đầu là "bao nhiêu **tiền**", LLM chép `revenue(...)`.
2. **Không kiểm dạng đáp án theo câu hỏi.** Hỏi "tháng nào" mà trả về số tiền vẫn được nhận.
3. **"Không trả lời được" hoàn toàn do LLM tự quyết.** 17 câu public đáng lẽ phải trả `unanswerable` thì LLM vẫn trả lời.
4. **Bước A xếp loại bảng bằng luật cứng.** 6/30 cửa hàng train bị xếp sai, nên mọi câu của các cửa hàng này đều sai.
