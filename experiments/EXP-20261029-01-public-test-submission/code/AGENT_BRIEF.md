# Brief cho shop agent — EXP-20261029-01-public-test-submission

Anh/chị là **một agent phụ trách đúng một shop**. Nhiệm vụ: trả lời mọi câu hỏi của shop đó và ghi
ra file đáp án đúng format. Không chạm shop khác.

## 0. Đường dẫn

| Thứ | Đường dẫn |
| --- | --- |
| Gốc repo | `/Users/lebahoai/Workspace/zalo/2026` |
| Gốc thực nghiệm `$E` | `$REPO/experiments/EXP-20261029-01-public-test-submission` |
| Rulebook | `$REPO/public_test/rulebook.md` — **đọc hết, không đọc lướt** |
| Lịch âm | `$REPO/public_test/calendar.csv` |
| Dữ liệu shop | `$REPO/public_test/data/<shop>/` |
| README shop | `$REPO/public_test/data/<shop>/README.md` — **nguồn mapping chính thức** |
| Câu hỏi | `$REPO/public_test/data/<shop>/questions.jsonl` |
| Toolkit | `$E/code/datamate/` |
| Script của anh/chị | `$E/code/shops/<shop>.py` |
| Đáp án phải ghi ra | `$E/out/answers/<shop>.jsonl` |
| Ghi chú phải ghi ra | `$E/logs/<shop>-notes.md` |

Dùng toolkit:

```python
import sys
sys.path.insert(0, "/Users/lebahoai/Workspace/zalo/2026/experiments/EXP-20261029-01-public-test-submission/code")
from datamate import Clock, fmt, read_table, peek, column_report, parse_money, parse_number, parse_date, parse_datetime, squeeze, name_key
from datamate.tabio import census, drop_subtotal_rows, fill_group, sheet_names, read_all_sheets, sqlite_tables, read_sqlite
```

## 1. Luật chấm điểm — cái này chi phối mọi quyết định

Đúng **+1**, sai **−1**, bỏ trống **0**.

EV của một câu có xác suất đúng `p` là `2p − 1`. **Trả lời chỉ có lợi khi `p > 0.5`.**
Trả lời bừa một câu không chắc là **−1**, tệ hơn bỏ trống. Không có điểm thưởng cho coverage.

Ba đáp án khác nhau hẳn nhau, đừng trộn:

| | Nghĩa | Điểm |
| --- | --- | --- |
| `{"id": ..., "type": "abstain"}` | tôi không chắc | luôn 0 |
| `{"id": ..., "type": "unanswerable", "answer": null, "reason": "..."}` | **dữ liệu phát hành không đủ để trả lời** | +1 nếu đúng, **−1 nếu sai** |
| đáp án thật | | +1 / −1 |

`unanswerable` **không phải van an toàn** — nó là một đáp án có điểm. Chỉ nộp nó khi khớp đúng một
trong hai nguyên nhân deterministic của rulebook §7:

1. kỳ hỏi nằm **hoàn toàn** ngoài khoảng ngày có dữ liệu của shop;
2. shop **không ghi** loại thông tin câu hỏi cần (không có file, không có cột, README không nói cách suy ra).

Rulebook §7: *"Không có dữ liệu khác với bằng 0"*, và *"Kỳ chỉ có một phần nằm trong khoảng ngày có
dữ liệu thì tính trên phần có dữ liệu"* — kỳ chồng một phần thì **tính**, không `unanswerable`.

Không chắc thuộc hai nguyên nhân đó → **`abstain`**, không phải `unanswerable`.

Khi nào `abstain`:
- không xác định được cột nào mang thông tin câu hỏi cần, sau khi đã đọc hết README;
- hai cách đọc luật ra hai số khác nhau mà rulebook không phân xử được;
- kết quả không qua được sanity check của chính mình.

## 2. Quy trình bắt buộc — theo đúng thứ tự này

### Bước A — đọc, chưa tính gì

1. Đọc hết `rulebook.md`. Đặc biệt §1 (doanh thu), §2 (thời gian), §3 (xếp hạng), §9 (format), và
   bảng §6 của **đúng ngành shop mình** nếu có.
2. Đọc hết `README.md` của shop. Ghi lại: mốc `Dữ liệu có đến hết DD/MM/YYYY`, bảng quy đổi đơn vị,
   mọi nhãn `## Quy ước`.
3. `peek()` **mọi file, mọi sheet**. Xác nhận bằng mắt header nằm ở dòng nào. Không tin
   `detect_header_row()` mà không nhìn.

### Bước B — ingest và kiểm kê, vẫn chưa trả lời câu nào

4. Với mỗi bảng: chạy `census(frame, key_columns=[...])`. **Mọi dòng không có cột khoá phải được
   giải thích**, không được lặng lẽ bỏ hay lặng lẽ giữ.
   Bẫy đã xác nhận ở `dev_001`: 554 dòng `Cộng ngày 01/01/2025` chen giữa sheet, chỉ có cột
   `Thành tiền`. Cộng thẳng ra **11.593.401.600** thay vì **5.796.700.800** — lệch đúng 2x, không
   exception nào. Loại dòng đó bằng `drop_subtotal_rows`.
5. Đo **khoảng ngày thật** của dữ liệu (min/max ngày đặt đơn). So với mốc README. Lệch thì ghi rõ
   vào notes và **lấy khoảng rộng hơn** làm căn cứ `unanswerable`.
6. Lập **capability map**: shop này có / không có loại thông tin nào. Dùng để quyết `unanswerable`
   nguyên nhân 2. Ví dụ `dev_009` chỉ có `danh_sach_hoa_don.csv` → không có chi tiết mặt hàng → mọi
   câu hỏi về mặt hàng là `unanswerable` nguyên nhân 2.
7. Kiểm **invariant** trước khi tin dữ liệu đã ingest đúng:
   - `Thành tiền` của mỗi dòng ≈ `Số lượng × Đơn giá` (sai nhiều dòng → đang hiểu sai cột nào đó);
   - tổng theo đơn khớp cột tổng đơn nếu có;
   - mọi đơn có đúng một trạng thái trong bốn trạng thái của rulebook §8;
   - phân bố trạng thái: ghi ra số đơn hoàn thành / huỷ / trả hàng / đang giao.
   Invariant fail thì **tìm nguyên nhân trước khi trả lời câu nào**, đừng vá bằng tham số.

### Bước C — trả lời

8. Nhóm câu hỏi theo dạng tính toán, viết hàm cho từng dạng. Mỗi hàm một luật rulebook, tên hàm nói
   đúng luật đó.
9. **Mọi câu đi qua `fmt.answer_line()`** — nó validate format §9 và raise nếu sai. Đừng tự ghi dict.
10. Dùng `Clock(as_of_date)` cho **mọi** cách nói thời gian. **Không tự tính ngày bằng tay** —
    `this_month` / `last_month_same_days` / `last_week` / `last_n_days` / `month(m)` / `quarter(q)` /
    `tet(y)` / `before_tet(y)` đã code đúng rulebook §2 và có test.
11. Luật mở đầu rulebook: **bản ghi có ngày sau `as_of_date` coi như chưa xảy ra** → lọc
    `date <= as_of` ở mọi phép tính. **Ngoại lệ**: trạng thái huỷ / trả hàng của đơn lấy theo trạng
    thái ghi trên đơn, kể cả khi phiếu trả ghi ngày sau hôm nay.

### Bước D — tự kiểm trước khi ghi file

12. Với **ít nhất 5 câu** trong số câu đã trả lời, tính lại bằng **đường thứ hai** (ví dụ: doanh thu
    tháng cộng từ dòng hàng, so với cộng từ tổng đơn). Lệch thì không trả lời câu đó.
13. Sanity check theo kỳ: in doanh thu / số đơn từng tháng. Một tháng lệch >50% so với tháng kề mà
    không giải thích được từ dữ liệu → nghi ingest sai, không nghi shop.
14. Đếm: số câu đã trả lời, số `abstain`, số `unanswerable`. Số dòng trong file đáp án **phải bằng**
    số dòng `questions.jsonl` của shop. Thiếu id nào là bỏ điểm câu đó.

## 3. Những chỗ sai im lặng đã biết — đọc trước khi viết code

| Chỗ | Luật đúng |
| --- | --- |
| Đơn **trả hàng dù chỉ một phần** | bỏ **cả đơn** khỏi doanh thu, không bỏ riêng dòng đó |
| Đơn **đang giao** | **vẫn tính** vào doanh thu |
| Trạng thái ở đâu | có cột trạng thái thì theo cột; không có cột thì đọc cột `Ghi chú`; ghi chú không nhắc trạng thái = **hoàn thành** |
| Ô trống ở dòng sau của cùng nhóm dòng | **giống dòng đầu nhóm** (rulebook §8), không phải thiếu dữ liệu, không phải khách lẻ. Dùng `fill_group` |
| Doanh thu một đơn | tổng **thành tiền các dòng hàng** (đã trừ giảm giá **dòng**). **Không** trừ giảm giá cả đơn, **không** cộng VAT, **không** gồm phí giao |
| Nợ một đơn | khác hẳn doanh thu: dùng **tổng đơn** khách phải trả — **đã trừ** giảm giá cả đơn, **gồm** phí giao |
| `Phí phục vụ` | là dòng hàng nhưng **không phải mặt hàng**: không xếp hạng, không đếm. **Vẫn tính** vào doanh thu, kể cả mẫu số tỉ trọng nhóm hàng |
| Bán chạy | theo **số lượng quy về đơn vị cơ bản**, không theo số dòng, không theo tiền |
| Hai cách viết cùng tên hàng khác nhau ở khoảng trắng | `'Coca Cola'` vs `'Coca  Cola'` là **một mặt hàng**. Dùng `squeeze` / `name_key`. Đã xác nhận làm lệch 428.000 ở một shop train |
| Khách vãng lai / khách lẻ | **không phải một khách**: không đếm, không xếp hạng, không thuộc nhóm khách nào. Nhưng **vẫn tính** vào doanh thu cả shop và vào tổng nợ |
| Số âm | ở một số shop số lượng âm nghĩa là trả hàng, không phải số lượng thật |
| Serial Excel lẫn trong cột ngày | `'46054'` cạnh `'01/02/2026'`. `parse_datetime` xử được cả hai |
| Tỉ lệ đơn huỷ | mẫu số là **mọi đơn đặt trong kỳ, mọi trạng thái** |
| Tỉ trọng nhóm khách | mẫu số là doanh thu **cả shop** cùng kỳ, **tính cả** đơn vãng lai |
| "Đến hết ngày X" | số **còn lại** tại thời điểm hết ngày X, tính mọi phát sinh **từ đầu dữ liệu**, không phải trong kỳ tháng |
| Tie-break | bằng nhau ở tiêu chí thì xếp theo **mã** tăng dần, không có mã thì theo **tên**. Câu hỏi một đối tượng thì lấy phần tử đầu theo thứ tự đó |
| `percent` | là **số phần trăm**: 12,4% ghi `12.4`, không ghi `0.124`. Làm tròn 2 chữ số |
| Tiền | số nguyên VND, làm tròn về đồng, nửa đồng lên. Dùng `fmt.money()` |
| Trung bình một khoản tiền | vẫn là tiền → làm tròn **về đồng**, không giữ 2 chữ số |
| `list` | đúng cả **tập và thứ tự**. Top k giảm dần theo tiêu chí câu hỏi |
| `table` | cột **đầu** là tên đối tượng, các cột sau là số đo **theo đúng thứ tự câu hỏi nêu** |
| `string` | tên **nguyên văn trong dữ liệu**, đủ dấu tiếng Việt. Không kèm tên cột, không kèm nhãn nhóm |
| Câu hỏi nhiều số | `type: list`, ghi theo **đúng thứ tự câu hỏi nêu** |
| Chênh lệch / hơn kém / tăng giảm (số) | **kỳ hỏi − kỳ so**, ít hơn ra **số âm** |
| Phần trăm thay đổi | so với **kỳ trước**, giảm ra **số âm** |

Câu hỏi viết teencode, không dấu (25.8% câu không có một dấu tiếng Việt nào): `dthu` = doanh thu,
`bn`/`bnhiu`/`bao nhiu` = bao nhiêu, `ko` = không, `dc` = được, `don` = đơn, `kh` = khách hàng.
Đọc kỹ, đừng đoán nhanh.

## 3b. Toolkit: 3 bug đã sửa và 2 helper mới — đọc trước khi dùng

Vòng 1 có 15 agent chạy và chết giữa đường vì rate limit. Chúng đã tìm ra 3 bug trong toolkit.
**Đã sửa, có test.** Đừng tự viết lại parser, và đừng tin phiên bản cũ:

| Bug | Trước | Giờ |
| --- | --- | --- |
| `parse_money` dạng tiền viết tay `<n>tr<nnn>` | `'19tr990'` → `19` | `'19tr990'` → `19990000`, `'20tr239'` → `20239000`, `'28,585tr'` → `28585000`, `'19tr5'` → `19500000` |
| `is_blank` coi chuỗi `'nan'` là rỗng | `is_blank('Nan')` → `True`, mà **`Nan` là hãng sữa thật** | chỉ chuỗi rỗng / toàn khoảng trắng / `None` / float NaN là rỗng. `'nan'`, `'-'` là giá trị thật |
| Tên hàng ghi **không dấu** không khớp danh mục | `name_key('Tra chanh (M)') != name_key('Trà chanh (M)')` | thêm `fold_key()` — bỏ dấu tiếng Việt, `đ`→`d`. Hai chuỗi trên khớp nhau |

**Luật dùng `fold_key`**: dùng nó để **KHỚP và GỘP**, nhưng đáp án `string` phải lấy **tên nguyên văn
có dấu đúng từ danh mục** (rulebook §9). Khớp bằng `fold_key`, xuất bằng tên gốc.

Hai helper mới trong `datamate.tabio`:

| Helper | Dùng khi |
| --- | --- |
| `drop_repeated_header_rows(frame)` | dòng header bị lặp lại giữa file (một shop có 226 dòng như vậy) |
| `drop_subtotal_rows(frame, key_columns=[...])` | dòng `Cộng ngày`, `Tổng cộng`, `Ghi chú:` chen giữa sheet |

Luôn chạy `census(frame, key_columns=[...])` trước. Nó in ra dòng nào không có cột khoá và chúng là gì.

## 3d. Hai lớp dòng rác BẮT BUỘC kiểm — đã xác nhận ở 4/6 shop đã làm

Đây không phải ca biên. Hai lớp này xuất hiện ở đa số shop và **không gây exception nào** — số vẫn
ra, chỉ là sai. Chạy hai lệnh kiểm này **trước khi tính câu nào**:

### Lớp 1 — dòng tổng cộng chen giữa sheet

| Shop | Đã đo |
| --- | --- |
| `dev_001` | 554 dòng `Cộng ngày DD/MM/YYYY` → cộng thô ra **gấp đúng 2x** doanh thu |
| `dev_008` | 587 dòng `Tổng ngày DD/MM` → cũng gấp đôi |
| `dev_004` | 18 dòng `Tổng cộng` + 27 dòng `Ghi chú:` cuối mỗi sheet |

```python
print(census(frame, key_columns=["<cột mã đơn>"]))
frame = drop_subtotal_rows(frame, key_columns=["<cột mã đơn>"])
```

### Lớp 2 — dòng trùng khít mọi ô

| Shop | Đã đo |
| --- | --- |
| `dev_006` | 1.350 dòng trùng → 1.335/37.833 đơn lệch tổng tiền; sau `distinct` còn **0/37.833** |
| `dev_008` | 1.347 cặp trùng, **tất cả** cùng mã đơn + cùng số dòng |
| `dev_007` | 2.762 dòng trùng |

Rulebook §8 phân biệt **hai** ca, và nhầm chúng là sai theo hai hướng ngược nhau:

- hai dòng của **cùng một đơn** giống nhau ở **mọi** ô → lỗi xuất file, tính **một lần**;
- hai dòng giống nhau của **hai đơn khác nhau** → hai lần bán, tính **cả hai**.

Nên dedupe phải **trong phạm vi một đơn**, không dedupe toàn bảng. Đo và ghi vào notes: bao nhiêu
dòng trùng, bao nhiêu thuộc ca 1, bao nhiêu thuộc ca 2.

### Lớp 3 — dòng header lặp lại giữa file

`dev_010`: 226 dòng. `drop_repeated_header_rows(frame)`.

### Lớp 4 — khách vãng lai viết nhiều kiểu

`dev_001`: ngoài `'lẻ'`, `'khách lẻ'`, `'Khách lẻ'` còn có **`'kl'` — 9.082 dòng**. Bỏ sót nó thì
`'kl'` thành **một khách** và đứng đầu mọi câu xếp hạng khách. Không có exception nào.

Liệt kê **mọi giá trị phân biệt** của cột khách, sort theo số dòng giảm dần, và đọc top 20 bằng mắt.
Giá trị nào chiếm hàng nghìn dòng mà trông không giống tên người thì nghi là khách vãng lai.

## 3e. Mã hay tên — rulebook đã phân xử, đừng tự cân

Một agent vòng trước lo rằng nộp mã khách (`KH0093`) thay vì tên là rủi ro. **Không phải.** Hai dòng
rulebook nói ngược lại:

- §9 dòng 168: *"Nhận mọi cách viết tên có trong file của shop, **hoặc mã**"*;
- §8 dòng 141: *"File có mã thì **theo mã**"*.

Tức là có mã thì **nộp mã là cách đúng nhất**, không phải cách rủi ro. Đối tượng chỉ có mã trong dữ
liệu (nhân viên ở nhiều shop) thì càng không có lựa chọn khác.

## 3c. Dấu hiệu tôi cấp cho bạn là GIẢ THUYẾT, không phải sự thật

Dấu hiệu trong prompt của bạn suy từ shop **họ hàng** ở tập train, không phải đo trên shop bạn.
Vòng 1 đã có một dấu hiệu **sai hẳn**: brief nói `dev_008` không có cột trạng thái, agent mở ra thì
shop đó **có** cột `TT đơn`.

Luật: **dữ liệu thắng dấu hiệu.** Mỗi dấu hiệu phải tự xác nhận bằng một lệnh chạy ra số. Dấu hiệu
sai thì ghi vào notes là sai, rồi làm theo dữ liệu.

## 4. Phong cách code — bắt buộc

- `from __future__ import annotations` ở mọi file.
- **Không viết comment `#`.** Cần comment nghĩa là tên hàm hoặc cấu trúc đang sai.
- Type annotation đầy đủ, mọi hàm có return type.
- Docstring một dòng ở class, nói **cái này là gì**, không kể hàm làm gì.
- Trả `tuple` không trả `list` ra ngoài.
- Message lỗi chữ thường, không dấu chấm cuối.
- Không mutable default argument.
- Fail fast: `raise ValueError`, không nuốt lỗi rồi trả rỗng.
- Không hard-code đường dẫn tuyệt đối rải rác; đặt một hằng CAPS ở đầu file.

## 5. Phải nộp lại 3 thứ

1. `$E/out/answers/<shop>.jsonl` — một dòng một câu hỏi, đủ mọi id, mọi dòng qua `fmt.answer_line`.
2. `$E/code/shops/<shop>.py` — script chạy lại được, sinh ra đúng file trên.
3. `$E/logs/<shop>-notes.md` — gồm:
   - khoảng ngày thật đo được, so với mốc README;
   - capability map: có / không có loại thông tin nào;
   - phân bố trạng thái đơn (số đơn mỗi trạng thái);
   - kết quả census từng bảng, và mọi dòng lạ đã giải thích thế nào;
   - kết quả invariant check;
   - 5 câu đã tính lại bằng đường thứ hai, kèm hai số;
   - bảng: id câu → đã trả lời / abstain / unanswerable, kèm **lý do một dòng** cho mọi câu không
     trả lời;
   - mọi quyết định đọc luật mà mình đã phải tự chọn.

## 6. Báo cáo cuối

Trả về (final message) đúng bốn phần:

1. **Số**: tổng câu / đã trả lời / abstain / unanswerable, và coverage.
2. **Phân bố type** đã nộp.
3. **Ba chỗ đáng ngờ nhất** trong bài mình, mỗi chỗ một dòng, nói rõ vì sao đáng ngờ.
4. **Câu đã tự kiểm bằng đường thứ hai**, kèm hai số và chúng có khớp không.

Đừng tô hồng. Báo cáo nói "làm xong hết" mà không có số là báo cáo vô dụng.
