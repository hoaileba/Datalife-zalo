# 05 — Rút gọn system prompt

Trạng thái: đề xuất, chờ Hoài duyệt. Đi cùng `docs/04` (tool `submit` đổi phần mô tả tool trong prompt).

## 0. Vấn đề — đã đo

Nguồn: `artifacts/prompt-probe/test.log`, probe q_88aeb2f7b1a7 (dev_009), qwen3-14b.

| | Số |
| --- | --- |
| System prompt | 34.801 ký tự, 452 dòng, **11.059 token** |
| Tỉ lệ trong context 40.960 token | 27% |
| Gửi lại mỗi turn | 15 turn × 11.059 = 165.885 / 276.249 token cả probe = **60% chi phí** |

Cơ cấu:

| Khối | Ký tự | % | Ai viết |
| --- | --- | --- | --- |
| Brief (§0–§7) | 11.812 | 34% | tôi |
| Rulebook | 18.777 | 54% | ban tổ chức |
| Toolkit (chữ ký hàm) | 4.205 | 12% | sinh tự động |

## 1. Thành phần

| Thành phần | Mang thông tin gì | Tồn tại để làm gì | Ai đang dùng | Đánh giá |
| --- | --- | --- | --- | --- |
| Brief §0 không gian làm việc | 2 gốc `data/` `work/`, import toolkit, bảng tool | model biết đường dẫn | model, mọi turn | **giữ, viết lại** theo 4 tool của docs/04 |
| Brief §1 luật chấm | +1/−1/0, `unanswerable` | quyết khi nào trả lời | model | **giữ, ngắn** — rulebook §9 đã nói |
| Brief §2 bước A đọc | đọc README, câu hỏi, `peek` | tránh tính khi chưa hiểu dữ liệu | model | **giữ** 3 dòng |
| Brief §2 bước B census, invariant, capability map | quy trình kiểm kê của Claude | Claude dùng ở EXP-20261029-01 | probe: qwen **không làm bước nào** trong 15 turn | **bỏ** — chuyển thành bước tiền xử lý của harness (đề xuất A) |
| Brief §2 bước C 9–13 | khung script, `Clock`, `visible_rows` | đúng cách viết `answer()` | model | **giữ**, sửa theo `submit` |
| Brief §2 bước D tự kiểm | 5 câu đường thứ hai, sanity tháng | bắt lỗi ingest | probe: không làm | **bỏ** |
| Brief §3 bảng sai im lặng (27 dòng) | luật doanh thu, nợ, xếp hạng, format | nhắc luật dễ sai | model | **bỏ phần lặp rulebook**, giữ ~8 dòng rulebook không nói rõ |
| Brief §3 teencode | `dthu`, `hqua`, `bnhiu`... | đọc câu hỏi | model | **giữ** |
| Brief §4 bốn lớp dòng rác | dòng tổng, trùng, header lặp, khách lẻ | dữ liệu bẩn đã đo | model | **giữ tạm, ngắn**; về lâu dài thuộc tiền xử lý |
| Brief §5 tính từ không định nghĩa | 4/4 train là `unanswerable` | chặn map bừa | model | **giữ** 3 dòng |
| Brief §6 phong cách code | không `#`, frozen, tuple | phong cách của Hoài | **không ai cần**: không ảnh hưởng đáp án | **bỏ** |
| Brief §7 nộp 3 thứ + notes | script, đáp án, notes | Verifier đòi notes | Verifier `verify.py:55` | **bỏ notes**; `submit` thay script + đáp án. Phải gỡ check notes ở Verifier |
| Rulebook §1–§5, §7–§10 | luật tính đáp án | nguồn sự thật | model | **giữ nguyên văn** — không tự diễn đạt lại luật của đề |
| Rulebook §6 theo ngành | 6 ngành, 4.528 ký tự | luật riêng ngành | model chỉ cần **1 ngành** | **giữ nguyên** lần này. Cắt theo ngành cần map shop → ngành, dữ liệu không có field đó |
| Toolkit chữ ký hàm | ~60 chữ ký | model biết hàm có sẵn | model | **thu** về các hàm khung script và bước đọc dùng |

## 2. Quyết định

### 2.1 Cấu trúc 6 phần (Hoài chốt)

| Phần | Chứa gì | Nguồn | Tĩnh / động |
| --- | --- | --- | --- |
| 1. Định danh | agent làm gì, nộp gì | viết tay | tĩnh |
| 2. Folders | gốc `data/` `work/`, quyền, chứa file gì | viết tay, khớp `PathSpace` | tĩnh |
| 3. Tools | mỗi tool: chức năng, khi nào gọi, tham số, input/output format; toolkit `datamate` | viết tay, khớp `tools.py`; `{{toolkit_reference}}` sinh từ code | tĩnh |
| 4. Rules | 4.1 rulebook nguyên văn; 4.2 chấm điểm + `unanswerable`; 4.3 luật rút ra từ dữ liệu | `{{rulebook}}`, `{{abstain_policy}}`, viết tay | tĩnh theo bộ dữ liệu |
| 5. Process | 6 bước: hiểu câu hỏi → hiểu dữ liệu → làm sạch → tính thử → kiểm hợp lý → nộp | viết tay | tĩnh |
| 6. Context | `{{context}}` | harness điền lúc chạy | **động, theo shop / câu** |

File: `prompts/system.short.vi.md`, `prompts/system.short.en.md` — cùng cấu trúc, cùng nội dung.

### 2.2 `{{context}}` chứa gì

| Mục | Ví dụ | Vì sao đưa vào thay vì để model tự đọc |
| --- | --- | --- |
| Shop id | `dev_009` | model cần cho đường dẫn |
| Câu hỏi: `id`, `question`, `as_of_date` | `q_88aeb2f7b1a7 · Hqua có dthu tổng bnhiu? · 2026-06-20` | probe: turn 1–2 chỉ để đọc file câu hỏi |
| Danh sách file shop kèm kích thước | `danh_sach_hoa_don.csv  412.318 bytes` | bỏ một lượt `list_dir` |
| README của shop, nguyên văn | mốc ngày dữ liệu, ý nghĩa cột | probe: model đọc README ở turn 2–3 |

Về sau (đề xuất A, chưa làm): thêm profile dữ liệu do harness tính sẵn — header thật, khoảng ngày,
dòng rác đã đếm.

### 2.3 Còn lại

1. Rulebook giữ nguyên văn, cả trong bản tiếng Anh.
2. Toolkit 4.205 → **~1.200 ký tự** (chưa làm: `toolkit_reference()` vẫn in đủ).
3. Bỏ yêu cầu notes khỏi prompt và khỏi Verifier.
4. Bản tiếng Anh cần `ABSTAIN_*` tiếng Anh trong `prompts.py`.

Dự kiến: 34.801 → **~23.000 ký tự, ~7.300 token**. Phần còn lại phần lớn là rulebook.

## 3. Bằng chứng và giả thuyết

- **Đã đo**: chi phí giảm theo tỉ lệ token prompt (số học, ở mục 0).
- **Giả thuyết**: prompt ngắn giúp qwen3-14b bám chỉ dẫn hơn. Căn cứ: Liu et al., *Lost in the
  Middle: How Language Models Use Long Contexts* (TACL 2024) — độ chính xác giảm khi thông tin cần
  dùng nằm giữa context dài. Chưa đo trên bài này.
- **Cách đo**: `run_one` trên cùng 2 câu probe + 10 câu trong mẫu 20, so prompt cũ / mới, cùng
  temperature 0. Đo: số turn tới `submit` được nhận, số câu khớp Claude, token.

## 4. Không đổi trong lần này

- Nội dung rulebook.
- Logic toolkit, `visible_rows`, Verifier (trừ gỡ check notes).
