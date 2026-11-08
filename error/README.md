# error/ — Điểm hiện tại, lỗi sai và hướng nâng điểm

Dành cho: bất kỳ ai cần biết hệ thống đang sai ở đâu và nên sửa gì tiếp. Cách hệ thống chạy xem `docs/07-kien-truc-hien-tai.md`.
Cập nhật: 2026-11-06.

Điểm cuộc thi là PA = (số câu đúng − số câu sai) / tổng số câu. Đúng +1, sai −1, bỏ trống 0.

Ba tập dữ liệu:

| Tập | Số câu | Có đáp án đúng không | Dùng để |
|---|---|---|---|
| `train_*` | 2550 | có | phát triển: đọc lỗi, rút luật, dựng thư viện ví dụ |
| `test_*` | 450 | có | **chỉ đo điểm**, không đọc từng câu sai (để điểm còn khách quan) |
| public | 1000 | không; so với bản Claude được hệ thống chấm 0,994 | đo điểm, nộp lên hệ thống |

Train có 30 shop. Trong đó **6 shop hỏng** ở bước chuẩn hoá (`biz_106`, `107`, `109`, `113`, `124`, `126`), 24 shop còn lại chạy được.

---

## 1. Tổng quan điểm

| Tập | Đã chạy agent | PA | Đúng / sai / trống | Bản code |
|---|---|---|---|---|
| Public | 1000 / 1000 | **0,849** (hệ thống chấm bản trước: 0,811) | 924 / 75 / 1 | mới nhất (ghép nhiều lần chạy) |
| `train_*` | **896 / 2550** | 0,619 | 724 / 169 / 3 | **cũ**: EXP-08, 09, 10, trước các bản sửa ngày 06/11 |
| `test_*` | 448 / 450 | 0,647 | 368 / 78 / 2 | EXP-07, có 83 câu chạy lại bằng bản ngày 06/11 |

Tách theo shop:

| Tập | 24 shop chạy được | 6 shop hỏng |
|---|---|---|
| `train_*` | **0,907** (717 / 35 / 0, n=752) | **−0,882** (7 / 134 / 3, n=144) |
| `test_*` | **0,936** (364 / 12 / 0, n=376) | **−0,861** (4 / 66 / 2, n=72) |

Đọc bảng này thế nào:

1. Ở 24 shop chạy được, agent đạt khoảng 0,91–0,94, ngang public.
2. 6 shop hỏng kéo cả tập xuống. Gần như mọi câu ở đó đều sai.
3. Điểm `train_*` lạc quan một chút. Câu có sẵn trong thư viện ví dụ đạt 0,975 (n=324), câu không có trong thư viện đạt 0,855 (n=428). Con số 0,855 gần với điểm thật trên câu mới hơn.

---

## 2. Số câu đã chạy agent và còn lại

| Tập | Tổng | Đã chạy | **Chưa chạy** | Câu chưa chạy thuộc 6 shop hỏng |
|---|---|---|---|---|
| `train_*` | 2550 | 896 | **1654** | 257 |
| `test_*` | 450 | 448 | **2** (`biz_106`, lỗi mạng) | 2 |
| **Tổng train** | 3000 | 1344 | **1656** | 259 |

Câu `train_*` chưa chạy, theo shop:

| Shop | Chưa chạy | Shop | Chưa chạy | Shop | Chưa chạy |
|---|---|---|---|---|---|
| biz_101 | 22 | biz_111 | 70 | biz_121 | 63 |
| biz_102 | 67 | biz_112 | 60 | biz_122 | 64 |
| biz_103 | 65 | biz_113 ⚠ | 22 | biz_123 | 69 |
| biz_104 | 64 | biz_114 | 19 | biz_124 ⚠ | 60 |
| biz_105 | 65 | biz_115 | 68 | biz_125 | 20 |
| biz_106 ⚠ | 64 | biz_116 | 67 | biz_126 ⚠ | 19 |
| biz_107 ⚠ | 28 | biz_117 | 66 | biz_127 | 65 |
| biz_108 | 66 | biz_118 | 65 | biz_128 | 66 |
| biz_109 ⚠ | 64 | biz_119 | 70 | biz_129 | 65 |
| biz_110 | 19 | biz_120 | 62 | biz_130 | 70 |

⚠ là shop hỏng. Danh sách từng câu: `train_not_run.jsonl`.

Ước tính thời gian chạy hết 1656 câu: khoảng 2 giờ với 5 luồng. Lần chạy lại ngày 06/11 đo được khoảng 4 giây mỗi câu: 138 câu trong 9 phút.

---

## 3. Lỗi trên public — 76 câu

```
 76 câu lỗi
 ├── 35  Chọn sai hàm, tham số hoặc kỳ ............ LLM chép ví dụ sai, bỏ qua gợi ý
 ├── 18  Sai dạng đáp án .......................... hỏi "tháng nào" mà trả số tiền
 ├── 17  Đáng lẽ "không trả lời được" ............. shop không có dữ liệu đó mà vẫn trả lời
 ├──  5  Code lỗi rồi trả "không trả lời được" .... bị −1, đáng lẽ bỏ trống để được 0
 └──  1  Đáp án tham chiếu đáng ngờ
```

| Nhóm | Ví dụ thật | Nguyên nhân |
|---|---|---|
| Chọn sai hàm (35) | "7 ngày gần nhất bán được bao nhiêu **ly**" → gọi `revenue(...)` ra 51.476.000; đúng là 1.285. "máy mới chiếm mấy %" → `revenue(group='máy mới')` thay vì `new_machine_share(...)` | LLM chép ví dụ đầu tiên. Trên public, 74% câu sai là chép đúng hàm của ví dụ đầu |
| Sai dạng (18) | "Th2, th3, th4/2026 tháng nào bán nhiều nhất" → `[465534000, 326590300, 313077600]`; đúng là `"2026-02"` | Không có bước so dạng đáp án với dạng câu hỏi |
| Đáng lẽ không trả lời được (17) | "món nào ngon nhất", "khách ở đường Mai Chí Thọ", "khách nữ" khi cột giới tính rỗng | Quyết định này hoàn toàn do LLM, code không kiểm cột |
| Code lỗi rồi bỏ cuộc (5) | gọi `expiring_items(clock.between(...))` sai cú pháp, sau mấy lượt nộp `unanswerable` | Bỏ cuộc mà trả "không trả lời được" thì bị −1 |

Danh sách từng câu: `public_errors.jsonl`, mã nhóm trong `labels_public.json`.

---

## 4. Lỗi trên `train_*` — 172 câu (đã đọc)

### 4.1 Ở 6 shop hỏng: 137 câu, chiếm 80% số lỗi train

| Kiểu | Số câu |
|---|---|
| Trả "không trả lời được" trong khi câu có đáp án | **116** |
| Số lệch | 17 |
| Khác | 4 |

**Nguyên nhân:** bước chuẩn hoá không dựng được bảng bán hàng `lines`, nên mọi hàm đều báo "shop has no …" và LLM nộp `unanswerable`. Có hai kiểu shop:

| Kiểu | Shop | Vì sao hỏng | Đã thử sửa trong nháp |
|---|---|---|---|
| Sổ bán hàng không ghi mã đơn | `biz_107`, `113`, `126` | luật xếp loại bảng bắt buộc có mã đơn mới coi là bảng bán hàng | `oracle.py` đúng 101/101 |
| Hoá đơn tách hai bảng, README không mô tả cột | `biz_106`, `109`, `124` | 53/58, 52/57 và 72/94 tên cột chưa có luật; không nối bảng hoá đơn với bảng chi tiết | `oracle.py` 6/300 → 141/300, còn xếp nhầm vài bảng |

### 4.2 Ở 24 shop chạy được: 35 câu

Đã đọc từng câu (EXP-20261105-10):

| Kiểu | Số câu | Ví dụ | Đã sửa ngày 06/11? |
|---|---|---|---|
| Thanh toán: alias `tm`, `tiền tươi`; "trả bằng" bị hiểu thành trả hàng; cộng gộp thay vì liệt kê | 6 | "đơn trả bằng tm" | một phần (thêm alias, gợi ý thanh toán theo thứ tự); chưa đo lại bằng agent |
| Kỳ nằm ngoài dữ liệu mà trả 0 | 5 | "Doanh thu 2/2025" ở shop chỉ có dữ liệu từ 2026 | chưa |
| Shop không có cột mà vẫn trả lời | 5 | "huỷ vì giao trễ" | chưa |
| Code ép `percent` vì tên hàng có dấu `%` | 3 | "Otrivin 0,1% …" | chưa |
| Quy đổi thiếu đơn vị lớn | 3 | Aquafina, Lavie, Efferalgan | **rồi**, `oracle.py` xác nhận 3/3 |
| Trả danh sách 1 phần tử thay vì số | 2 | `[217607800]` | chưa |
| Tên mất dấu | 2 | "Ho Linh Khoa" thay vì "Hồ Linh Khoa" | **rồi**, `oracle.py` xác nhận 2/2 |
| `cancel_rate` lệch mẫu số | 2 | 1,20 so với 1,21 | chưa rõ nguyên nhân |
| Lẻ | 7 | | |

Số câu sai này đo bằng **bản code cũ**. Sau các bản sửa ngày 06/11, `oracle.py` trên train tăng từ 2187 lên 2202 câu đúng, không câu nào từ đúng thành sai.

---

## 5. Lỗi trên `test_*` — 80 câu (chỉ thống kê)

`test_*` chỉ dùng để đo, nên chỉ đếm theo kiểu lỗi do script tự xếp, không đọc từng câu. Nếu đọc rồi sửa theo từng câu, điểm `test_*` không còn khách quan.

| Kiểu lỗi (tự động) | 24 shop | 6 shop hỏng |
|---|---|---|
| Trả "không trả lời được" nhầm | 3 | **59** |
| Đáng lẽ "không trả lời được" | 3 | 0 |
| Sai dạng đáp án | 3 | 0 |
| Số lệch hoặc sai giá trị | 3 | 7 |
| Bỏ trống | 0 | 2 |
| **Tổng** | **12** | **68** |

Kiểu lỗi trên `test_*` giống `train_*`. Phần lớn nằm ở 6 shop hỏng, và cùng kiểu "trả `unanswerable` vì không có bảng bán hàng".

---

## 6. Hướng nâng điểm

### 6.1 Mỗi việc nâng điểm ở tập nào

| # | Việc | Public (76 lỗi) | `train_*` (172 lỗi) | `test_*` (80 lỗi) | Loại thay đổi |
|---|---|---|---|---|---|
| 1 | **Shop hỏng thì bỏ trống, không trả "không trả lời được".** Khi lỗi là "không có bảng bán hàng" (lỗi cấu trúc, không phải thiếu một cột) thì bỏ trống | 0 | 116 câu từ −1 thành 0, mất 4 câu đang đúng nhờ trả `unanswerable`: **+112** | 59 câu, mất 1: **+58** | nhỏ, ở cổng kiểm đáp án |
| 2 | **Sửa bước chuẩn hoá cho 6 shop hỏng:** xếp loại bảng cho sổ không mã đơn; luật tên cột rút từ train; nối hoá đơn với chi tiết; kiểm tra bảng sau chuẩn hoá | 0 | tối đa +274 trên 137 câu | tối đa +136 trên 68 câu | lớn, ở bước A |
| 3 | **Kiểm dạng đáp án theo câu hỏi** ("tháng nào" → `YYYY-MM`, "ai" → tên, "N mặt hàng" → N phần tử, "bao nhiêu ly" → đếm) | khoảng 25 câu | khoảng 8 | khoảng 3 | vừa, ở cổng kiểm đáp án |
| 4 | **Cổng "không trả lời được":** từ chỉ điều dữ liệu không ghi; kiểm shop có cột và cột không rỗng; kỳ hỏi nằm ngoài dữ liệu | 17 | khoảng 20 | khoảng 3 | vừa |
| 5 | **Code lỗi thì bỏ trống** | 5 | ít | ít | nhỏ |
| 6 | **Chọn ví dụ theo dạng câu hỏi**, hàm báo lỗi khi nhận tham số lạ | khoảng 25 | khoảng 10 | ít | vừa, đổi prompt mọi câu |

Số câu ở các việc 3–6 là ước lượng (giả thuyết) từ cách xếp nhóm ở mục 3–5, chưa đo.

### 6.2 Thứ tự khuyến nghị

1. **Việc 1 trước.** Rẻ nhất mà tăng nhiều nhất trên train và test. Đây là lưới an toàn: nếu private có shop lạ bị chuẩn hoá hỏng, mất 0 điểm thay vì −1 cho mỗi câu. Ước lượng `test_*` từ 0,647 lên khoảng 0,775 ((290 + 58) / 450).
2. **Việc 3, 4, 5:** nâng public lên khoảng 0,90.
3. **Việc 2:** nâng train và test lên khoảng 0,89–0,93 nếu sửa được 6 shop. Đây là việc lớn, cần quyết thiết kế tầng bảng trước.
4. **Việc 6** sau cùng, vì đổi prompt của gần như mọi câu, phải chạy lại đủ cả tập để đo.

### 6.3 Cách đo sau mỗi việc

1. `oracle.py` trên train và public: không câu nào từ đúng thành sai.
2. Chạy agent đủ 1000 câu public và 450 câu `test_*` trong một lần, không ghép.
3. Chạy nốt 1654 câu `train_*` chưa chạy, để có điểm train bằng bản code mới nhất.
4. Chỉ nộp khi public tăng **và** `test_*` không giảm.

---

## 7. Đã sửa ngày 06/11

| Sửa | Ảnh hưởng đo được |
|---|---|
| Quy đổi nhiều đơn vị lớn (1 hộp = 25 vỉ × 4 viên) | public +3 câu; `oracle.py` train +14 câu |
| Nhận kỳ: tháng không ghi năm, Q1/2026, từ tháng 9 đến hết tháng 11, cùng kỳ tháng trước, trước Tết | public +6 câu |
| Lọc việc sửa xe theo rulebook | public +2 câu |
| Loại máy cũ/mới, alias thanh toán, nhận tên phải khớp dấu | public vài câu |
| Tên trong đáp án giữ đúng dấu và cách ghi của danh mục | `oracle.py` train +3 câu |

Public ở máy từ 0,815 lên 0,849. `test_*` từ +282 lên +290.

---

## 8. Tái tạo số

```bash
python3 error/train_status.py      # mục 1, 2, 4, 5 → train_test_status.jsonl, in bảng
python3 error/build.py             # mục 3 → public_errors.jsonl
PYTHONWARNINGS=ignore python3 error/replay.py experiments/EXP-20261106-01-deterministic-fixes/out/submission.jsonl error/replay_public.jsonl
```

| File | Là gì |
|---|---|
| `train_test_status.jsonl` | Mỗi câu `train_*` và `test_*`: đã chạy chưa, chạy ở lần nào, đúng hay sai, kiểu lỗi |
| `train_not_run.jsonl` | 1656 câu train chưa chạy agent |
| `public_errors.jsonl` | Từng câu public đang sai, kèm nhóm |
| `labels_public.json` | Mã nhóm lỗi public, gán tay |
| `replay_public.jsonl` | Câu public có đáp án đổi khi chạy lại code FINAL cũ trên code mới |
| `answers_public_current.jsonl` | Đáp án public hiện tại (ghép) |
