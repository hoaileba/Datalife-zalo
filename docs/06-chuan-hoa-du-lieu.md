# 06 — Tầng chuẩn hoá dữ liệu trước agent

Trạng thái: Hoài ra lệnh code (2026-11-01). Các quyết định dưới đây tôi tự chọn, cần Hoài duyệt lại.

## 0. Vấn đề — đã đo

- 14 shop public: ~32 tên cột khác nhau cho "ngày", 9 cho "trạng thái", ~12 cho "tiền" (regex trên header, xấp xỉ).
- EXP-20261101-02: qwen chép tên cột ví dụ trong prompt (`Ngày tháng`, `Trạng thái đơn`) → `KeyError` → `submit` bị trả lại; mỗi vòng sửa ~2 phút, lặp lại ở mọi câu.
- Bảng: 163 (public) / 339 (train); 72 chữ ký header khác nhau ở public; 98 bảng public có dòng tiêu đề trên header.

Muốn: LLM viết code trên **bảng đã sạch, tên cột chuẩn**; phần đoán cột và lọc dòng rác làm **một lần mỗi bảng**, có kiểm, chạy tự động trên shop chưa thấy (private test).

## 1. Thành phần

| Thành phần | Mang thông tin gì | Tồn tại để làm gì | Ai dùng | Đánh giá |
| --- | --- | --- | --- | --- |
| `ROLES` (mô hình chuẩn) | tên cột chuẩn + kiểu (`id/text/date/money/number`) + cấp (`order/line/record`) | một bộ tên cho mọi shop | mapper, transform, prompt agent | mới, domain thật |
| Khám phá bảng | file/sheet/bảng sqlite, dòng header, 5 dòng mẫu | đơn vị để map | mapper | mới |
| Chữ ký header | tuple tên cột | header giống nhau dùng chung một mapping (12 sheet tháng → 1 lần gọi) | mapper | mới |
| Mapper (LLM, tool `set_mapping`) | `kind` bảng + cột nguồn → vai trò chuẩn | phần ngữ nghĩa không làm bằng luật được | transform | mới; gọi 1 lần / chữ ký |
| Kiểm mapping (deterministic) | tỉ lệ parse được theo kiểu, trùng vai trò | chặn map sai trước khi nó thành sai có hệ thống | transform, profile | mới |
| Map trạng thái (LLM, tool `set_status_map`) | giá trị trạng thái thật → 4 trạng thái rulebook §8 | `status_norm` dùng chung | transform | mới |
| Transform | bỏ header lặp, tách dòng rác (kèm lý do), điền dòng tiếp nối, bỏ dòng trùng trong đơn, parse kiểu | bảng sạch | agent | mới; dùng lại `datamate.tabio`, `datamate.norm` |
| `mapping.json` | mapping đã duyệt qua kiểm | chạy lại không gọi LLM, sửa tay được | normalize lần sau | mới |
| `PROFILE.md` | mapping, dòng đã loại theo lý do, khoảng ngày, giá trị trạng thái, khách lẻ | context cho agent, bằng chứng cho người | agent, Hoài | mới |

## 2. Quyết định

1. **Vị trí**: pipeline riêng `python -m datamate_agent.pipelines.normalize --config ...`, chạy trước agent. Ra
   `<output_dir>/clean/<shop>/` — agent thấy là `work/clean/<shop>/`. Dữ liệu gốc không đổi.
2. **Đơn vị map**: chữ ký header trong một shop. Các bảng cùng chữ ký gộp thành **một** bảng sạch.
3. **Mô hình chuẩn**: danh sách `ROLES` trong `modules/normalize.py`. Cột không map được **giữ nguyên tên gốc**, không xoá.
4. **Dòng rác không bị xoá im lặng**: ghi sang `<bảng>.dropped.csv` kèm `drop_reason`
   (`repeated_header`, `subtotal`, `empty`, `duplicate_in_order`).
5. **Kiểm mapping**: cột `date` parse được ≥ 90% ô có giá trị, `money`/`number` ≥ 90%, mỗi vai trò dùng một lần.
   Trượt thì bỏ vai trò đó, ghi lý do vào PROFILE. Không hỏi lại LLM ở bản đầu.
6. **Khách lẻ**: `is_walk_in` = tên khách trống hoặc thuộc `{khach le, le, kl}` (fold_key) — tập từ EXP-20261029-01.
7. **Định dạng**: CSV UTF-8 (image sandbox không có pyarrow). Ngày ISO, tiền số nguyên.
8. **Model map**: cấu hình riêng (`normalize.model`), mặc định qwen3-14b, `reasoning: false`. Giả thuyết: map cột là
   phân loại, không cần reasoning dài. Chưa đo.

## 3. Chưa làm ở bản này

- Suy trạng thái từ `Ghi chú` khi shop không có cột trạng thái.
- Quy đổi đơn vị (bảng quy đổi), join danh mục.
- Nối `PROFILE.md` vào `{{context}}` của agent — làm sau khi đo được độ đúng của mapping.

## 4. Đo

1. Chạy trên 14 shop public: số chữ ký, số vai trò qua kiểm / trượt, dòng loại theo lý do.
2. So mapping với cột mà script Claude (EXP-20261029-01) đã dùng ở vài shop: ngày đơn, trạng thái, tiền doanh thu.
3. Sau khi nối vào agent: chạy lại 10 câu của EXP-20261101-02, so điểm và số lần `submit` bị trả lại.
