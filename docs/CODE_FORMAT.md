# Khuôn code Python cho student nhỏ (đề xuất, 14/11)

Nhánh `exp/lean-rl`. Trạng thái: **đề xuất, chưa code, chưa đo**. Tối ưu cho **student** (Gemma 12B sau SFT, không
thinking), không cho teacher. Teacher DeepSeek chỉ lỗi 2.3 % chương trình trả lời (lượt explore/look không tính).
Đã qua một vòng phản biện độc lập (mục 9).

## 1. Lỗi code đến từ đâu (số đo)

| Nguồn | Số | Ý nghĩa |
|---|---|---|
| Student `train_v3` trên public 1000 (gap §3–4; **student có thinking**, khác student không thinking dự định) | 20 % chương trình lỗi; `AssertionError` 151, `KeyError` 53, `AttributeError` 17. 41/49 tên cột gây `KeyError` là tên thuộc lòng từ shop train; `df.dedup` gọi như method; `_x`/`_y` sau `merge` | Nhóm lớn nhất là assert fail (model hiểu sai dữ liệu, bị chặn lại). Tên cột sai là nhóm thứ hai, gần như toàn bộ do học thuộc |
| Teacher train_v1, 3001 chương trình trả lời | 69 lỗi (2.3 %): `AssertionError` 26, `KeyError` 9, `MemoryError` 8. Tỉ lệ lỗi theo thành phần có trong chương trình: `.agg(` 8.7 % (n=92), `lambda` 11.3 % (n=53), `merge` 4.4 % (n=542), `map` 2.8 % (n=562) | Cỡ mẫu nhỏ và có thiên lệch (các thành phần này hay xuất hiện ở câu khó): chỉ dùng làm **ưu tiên**, không cấm |
| v5 public 100 (đọc log theo phép) | 8/16 chương trình lỗi là `kit.between` dùng như mask; 2/3 câu không đúng do assert ngưỡng thống kê và dựng lại cột tổng | Helper trả kiểu khác cách model hay dùng thì thành bẫy; assert sai tự chặn đáp án đúng |
| Teacher train_v1 + v5 | dòng comment: trung vị 0 %, trung bình 1.6–3.8 %; 8 % tên biến dài 1–2 ký tự (`o`, `dh`, `sp`) | Code teacher rất cô đọng. Một phần do prompt cũ chặn comment ("keep comments short") |

## 2. Tài liệu nói gì (và nói đến đâu)

- **Python/pandas hơn SQL** cho hỏi đáp trên bảng (SemEval-2025 Task 8 DataBench, [tổng quan](https://aclanthology.org/2025.semeval-1.324/)).
- **Gắn schema là nguồn lỗi lớn nhất** của LLM khi viết truy vấn ([DIN-SQL](https://arxiv.org/abs/2304.11015)).
  [RESDSQL](https://arxiv.org/abs/2302.05965) tách gắn schema khỏi phần sinh truy vấn. Đó là kiến trúc model, không phải
  cách trình bày code, nên ở đây nó chỉ là **phép so sánh**, không phải bằng chứng trực tiếp.
- **Kế hoạch có cấu trúc giống chương trình** tăng Pass@1 ([SCoT](https://arxiv.org/abs/2305.06599)).
- **Hàm trừu tượng dùng lại giúp model nhỏ** ([ReGAL](https://arxiv.org/abs/2401.16467)): chọn đúng một tên hàm dễ hơn
  tự dựng logic.
- **Tên biến mô tả** giúp model *hiểu* code: xoá tên làm GPT-4o tóm tắt code kém hẳn
  ([When Names Disappear](https://arxiv.org/abs/2510.03178)). Đó là đo khả năng tóm tắt, không phải sinh code.
- **Comment giúp model nhỏ:** [MANGO](https://aclanthology.org/2024.findings-acl.420.pdf) (model 3B/7B),
  [Code Needs Comments](https://arxiv.org/abs/2402.13013) (mật độ comment trong dữ liệu train).
- **Trace + phản hồi thực thi giúp sửa lỗi** ([Self-Debugging](https://arxiv.org/abs/2304.05128)).
- **Ràng buộc định dạng chặt có thể làm giảm suy luận** ([Let Me Speak Freely?](https://arxiv.org/abs/2408.02442),
  kết quả còn tranh cãi): khuôn phải nhẹ.

## 3. Đề xuất: chương trình ba khối "BIND → COMPUTE → CHECK"

Đây là bản mở rộng của quy tắc có sẵn trong prompt v5 ("decisions as named constants first"): thêm tên cột vào nhóm
hằng, gắn chúng bằng `kit.name`, đặt tên biến mô tả, mỗi khối một comment.

```python
# 1. BIND: tables, columns, labels and dates of THIS shop (kit.name checks each column here)
ORDERS = tables['ban_hang_hoa_don']
PAYMENTS = tables['ban_hang_phieu_thu']
ORDER_ID = kit.name(ORDERS, 'Order ID')
ORDER_DATE = kit.name(ORDERS, 'Ngày bán')
STATUS = kit.name(ORDERS, 'Trạng thái')
PAY_METHOD = kit.name(ORDERS, 'Phương thức TT')
ORDER_TOTAL = kit.name(ORDERS, 'Tong tien')              # README: what the customer pays for the whole order
PAYMENT_ORDER_ID = kit.name(PAYMENTS, 'Mã bill')
PAYMENT_DATE = kit.name(PAYMENTS, 'Thời gian thu')
PAYMENT_AMOUNT = kit.name(PAYMENTS, 'Số tiền thu')
CANCELLED_LABELS = ['Không giao được']
ALL_LABELS = CANCELLED_LABELS + ['Đổi trả', 'Đang vận chuyển', 'Đã giao']
NOT_DEBT_METHODS = ['Thu hộ (COD)']                      # COD orders are never customer debt
AS_OF_DAY = pd.Timestamp('2026-02-01')
END_OF_DAY = AS_OF_DAY + pd.Timedelta(days=1)            # "up to the end of day X" = before X + 1 day
MIN_AGE_DAYS = 7                                          # "hơn 7 ngày" = strictly more than 7
assert ORDERS[ORDER_ID].is_unique, 'order ids not unique'
assert ORDERS[STATUS].isin(ALL_LABELS).all(), 'unmapped status label'
assert PAYMENTS[PAYMENT_ORDER_ID].isin(ORDERS[ORDER_ID]).all(), 'payments whose order id is not in the orders'

# 2. COMPUTE: debt per order = order total - payments up to the end of the day
kept_mask = (ORDERS[ORDER_DATE] < END_OF_DAY) & ~ORDERS[STATUS].isin(CANCELLED_LABELS) & ~ORDERS[PAY_METHOD].isin(NOT_DEBT_METHODS)
kept_orders = ORDERS[kept_mask]
paid_by_order = PAYMENTS[PAYMENTS[PAYMENT_DATE] < END_OF_DAY].groupby(PAYMENT_ORDER_ID)[PAYMENT_AMOUNT].sum()
debt_by_order = kept_orders[ORDER_TOTAL] - kept_orders[ORDER_ID].map(paid_by_order).fillna(0)   # no payment yet = 0 paid
age_days = (AS_OF_DAY - kept_orders[ORDER_DATE].dt.normalize()).dt.days
owing_debts = debt_by_order[(debt_by_order > 0) & (age_days > MIN_AGE_DAYS)]

# 3. CHECK + RESULT
assert len(owing_debts) > 0, 'no owing orders'
result = {'type': 'number', 'answer': round_decimal(owing_debts.sum(), 0)}
```
(Câu train biz_124: `sandbox.execute` ra 2744100 = gold.)

### 3.1 Khối 1 BIND: gắn schema và kiểm đầu vào
- **Mỗi cột được gắn bằng `kit.name(TABLE, 'tên')`.** Hàm này đã có trong `kit` nhưng chưa được giới thiệu trong prompt.
  Nó trả về đúng nhãn cột (chấp nhận khác dấu hoặc hoa thường, như `TolerantFrame`). Tên không có thì báo `KeyError`
  **ngay ở khối 1**, kèm các cột gần nhất. Lỗi gắn schema nhờ đó luôn nằm ở một chỗ, trước khi tính gì.
- Hằng viết HOA theo **vai trò** (`ORDER_DATE`, `CANCELLED_LABELS`): bảng, cột, nhãn, mốc kỳ, ngưỡng của câu hỏi.
- Assert về **đầu vào** đặt ngay đây: khoá duy nhất, mọi nhãn đã ánh xạ, khoá của bảng phụ có trong bảng chính (trước
  mọi `map(...).fillna(...)`: một khoá lệch kiểu sẽ âm thầm thành "chưa trả").
- Lưu ý: khối này **không chống học thuộc**. Tên học thuộc chỉ chuyển từ COMPUTE lên BIND, nơi `kit.name` bắt nó sớm
  và nêu cột đúng. Học thuộc chỉ giảm nhờ dữ liệu reskin (PLAN_LEAN_RL §2.4).

### 3.2 Khối 2 COMPUTE: logic dùng hằng, tên biến mô tả
- Dùng hằng của khối 1 cho cột của shop. Cột mới tự tạo (`assign(line_total=...)`) và tên cột của bảng đáp án (theo chữ
  của câu hỏi) vẫn được viết trực tiếp.
- Tên biến mô tả, snake_case (`kept_orders`, `paid_by_order`), không dùng tên 1–2 ký tự. Mỗi dòng một bước, gán vào một
  biến (trace hiển thị từng biến).
- **Ưu tiên, không cấm:**
  - `groupby(KEY)[COL].sum()` thay cho `agg({...})`;
  - `map` từ một Series cho tra cứu nhiều-một trên một khoá; `merge` cho khoá nhiều cột hoặc join nhiều-nhiều, kèm assert
    số dòng;
  - mask dựng trên cùng một bảng;
  - tránh `lambda`/`apply` và chuỗi quá 2 method trên một dòng.
- Comment một dòng ở đầu khối nói phép tính chính. Comment cuối dòng chỉ cho quyết định không hiển nhiên.

### 3.3 Khối 3 CHECK + RESULT
Chỉ assert điều phải đúng tuyệt đối (còn dòng sau lọc, không dòng nào chưa khớp); không assert tỉ lệ khớp. Dòng cuối
là `result = {"type": ..., "answer": ...}`.

### 3.4 PLAN theo ba khối
PLAN trong phần chữ gồm ba mục `BIND:` / `COMPUTE:` / `CHECK:`, gạch đầu dòng tự do bên trong mỗi mục. Kế hoạch có cùng
cấu trúc với chương trình (SCoT).

### 3.5 Lượt sửa chỉ ra khối hỏng
Ở lượt sửa, `CAUSE:` nêu **khối** hỏng: `CAUSE: BIND — <cột/nhãn/kỳ nào sai>` hoặc `CAUSE: COMPUTE — <bước nào>`. Rồi
viết lại chương trình, chỉ sửa khối đó. Ba khối biến việc sửa lỗi thành việc khoanh vùng. Điều này nhắm thẳng vào điểm
yếu số 1 của student (sửa được 52 % so với teacher 74–100 %). Nó cũng cho bước DAgger một dạng lượt sửa cố định để học.

## 4. Thay đổi host (nhỏ)
1. **Trace không bị hằng chiếm chỗ.**
   - Hiện tại: trung vị 16 biến, p90 22 biến được ghi trong trace, giới hạn 60 dòng, giữ các dòng cuối.
   - Khối BIND thêm 10–16 hằng: p90 lên khoảng 35, và vài chương trình vượt 60, làm mất các dòng đầu (hình dạng bảng).
   - Sửa: trace và phần "biến trên dòng lỗi" bỏ qua hằng VIẾT HOA có giá trị là chuỗi hoặc danh sách chuỗi. Hằng bảng
     (`ORDERS`) vẫn hiện.
2. **`kit.between` dùng như mask báo lỗi rõ ngay** thay vì `MemoryError`/`TypeError`: kết quả của `between` là một
   `TolerantFrame` từ chối phép `&`, `|`, `~` kèm thông báo cách viết mask. Không thêm helper `kit.within`: thêm một hàm
   ngày tên gần giống là thêm một bẫy.
3. **`kit.lookup(keys, table, key, value, missing=...)`** cho tra cứu nhiều-một có kiểm:
   - khoá của bảng tra trùng thì báo lỗi (dòng trùng y hệt không tính);
   - khoá không tìm thấy thì báo lỗi kèm ví dụ, trừ khi truyền `missing=` (ví dụ `missing=0` cho "chưa trả");
   - chuẩn hoá kiểu khoá (số/chuỗi, `12.0` ↔ `12`); `key` nhận một cột hoặc danh sách cột (khoá nhiều cột như mặt hàng
     + đơn vị);
   - trả về Series cùng index với `keys`.

   Chỉ thêm nếu đo cho thấy lỗi tra cứu (`merge`, `dict(zip)`, `map` lệch khoá) còn đáng kể sau mục 3.
4. Prompt:
   - mục 2: khung ba khối, PLAN theo khối, CAUSE theo khối;
   - mục 6: `kit.name`, các ưu tiên ở 3.2;
   - bỏ "keep comments short" trong thông báo dừng của host (giữ ngưỡng chặn comment tràn 40 dòng).

## 5. Kiểm tuân thủ (chỉ để lọc và đo, không chặn lúc chạy)
- Bộ kiểm AST trên chương trình trả lời (bỏ lượt look):
  - chuỗi **trùng tên một cột trong catalog** của shop xuất hiện ngoài khối 1;
  - tên biến 1–2 ký tự;
  - thiếu comment đầu khối;
  - số cột gắn không qua `kit.name`.
- `lambda`, `merge`, `agg` chỉ đếm, không lọc.
- Lúc chạy không từ chối chương trình vì sai khuôn.

## 6. Đo trước khi nhận
- **Đủ cỡ mẫu.** Với mức lỗi cơ sở 2.3 %, sáu câu không đo được gì. Cần **200 câu trở lên trên train/syn_v2/rulevar**,
  so cặp trên cùng câu, khuôn hiện tại vs ba khối. Mỗi bên chạy DeepSeek **bật** và **tắt thinking**; chế độ tắt yếu
  hơn nên dùng làm đại diện cho model nhỏ. Lượt này cần người dùng cho phép.
  - Báo: độ đúng, chương trình lỗi theo loại, tỉ lệ sửa thành công, tuân thủ (mục 5), độ dài.
  - Cổng: độ đúng không kém; ở chế độ tắt thinking, số chương trình lỗi hoặc số câu sửa hỏng giảm.
- **Student** (phép đo thật): sau SFT, có và không reskin, so cặp trên tập val giữ riêng.

## 7. Rủi ro
- Teacher không theo khuôn đều: lọc bằng mục 5; nếu tuân thủ thấp thì thêm một ví dụ ngắn vào prompt.
- Code dài hơn (ví dụ 32 dòng so với khoảng 22 của bản gọn). Chi phí token nhỏ so với prompt khoảng 13k token, nhưng
  tăng số chỗ student có thể viết sai. Đổi lại, lỗi rơi đúng khối và có thông báo.
- Lợi ích của tên mô tả và comment được tài liệu ủng hộ về hướng, nhưng mức lợi cho SFT trên tác vụ hẹp này chưa biết.

## 8. Thứ tự làm
1. Mục 4.1 (trace) và 4.2 (`between` từ chối mask): sửa host thuần, an toàn, có ích ngay cả với khuôn hiện tại.
2. Prompt ba khối + `kit.name` + CAUSE theo khối, cùng bộ kiểm mục 5.
3. Đo mục 6 (cần cho phép).
4. `kit.lookup` chỉ khi số đo cho thấy cần.

## 9. Đã sửa sau phản biện (14/11)
- BIND gắn cột bằng `kit.name` (gán chuỗi trần không bắt được lỗi); ví dụ thêm assert khoá trước `map().fillna()`.
- Bỏ các lệnh cấm (`lambda`, `merge`): số lỗi quá ít và có thiên lệch, nên chỉ là ưu tiên và không dùng để lọc.
- Bỏ `kit.within`, thay bằng `between` từ chối phép mask. `kit.lookup` có `missing=`, khoá nhiều cột, chuẩn hoá kiểu,
  và chỉ thêm khi đo cho thấy cần.
- Trace bỏ qua hằng chuỗi viết HOA.
- Sửa số và cách nói:
  - tên biến ngắn 8 %;
  - 2.3 % là không tính lượt explore;
  - nhóm lỗi lớn nhất là assert, không phải tên cột;
  - RESDSQL chỉ là phép so sánh;
  - "When Names Disappear" đo khả năng tóm tắt code;
  - Let Me Speak Freely còn tranh cãi.
- Thêm: CAUSE theo khối cho lượt sửa; cỡ mẫu đo ≥ 200; BIND không chống học thuộc (cần reskin); student dự định không
  thinking, khác `think_full`.
