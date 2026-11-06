# ADR 002 — Một agent một shop, không canonical schema chung

Ngày: 2026-10-29 · Trạng thái: đề xuất, chờ Hoài duyệt · Liên quan: `plan.md` §5 D3, D4, O6

## Bối cảnh

`plan.md` §2.7 đã đo: **449 tên cột phân biệt, chỉ 27 cột xuất hiện ở ≥10 shop, 151 cột chỉ ở 1 shop**.
§2.8: **8/14 shop public test không có anh em train**. §2.1: 14 shop, từ 2 đến 25 file, từ 6.082 đến
~300k dòng, 3 định dạng (`csv`, `xlsx`, `sqlite`).

D4 (hình dạng canonical schema) chưa chốt.

## Quyết định

**Không canonicalize.** Mỗi agent đọc README của chính shop mình, ingest trực tiếp, trả lời câu hỏi
của shop đó. 14 agent chạy song song, không chia sẻ schema.

Chia sẻ **đúng một thứ**: toolkit các luật **không phụ thuộc schema** —
`code/datamate/{norm,periods,fmt,io,calendar_vn}.py`.

## Đánh đổi kinh điển

Đây là chỗ **shared-nothing vs shared-schema**. Ranh giới tách đúng theo nguyên lý: luật rulebook §2
(thời gian) và §9 (format) **không phụ thuộc shop nào**, nên thuộc toolkit chung; mapping cột thì
phụ thuộc hoàn toàn vào shop, nên thuộc agent.

Triệu chứng nhận biết chỗ tách sai: nếu một hàm trong toolkit nhận tham số `shop_id` để phân biệt
hành vi, thì hàm đó đặt sai tầng.

Giá phải trả: **cùng một luật nghiệp vụ được code 14 lần**. Ví dụ luật §1 "đơn có trả hàng, kể cả
một phần, bỏ cả đơn" sẽ được 14 agent viết 14 kiểu. Một agent làm sai luật đó thì 13 agent kia không
cứu được, và không có invariant chung nào bắt được.

Theo luật tổ chức module của Hoài: *"trùng lặp về mặt chữ không phải lý do để rút ra hàm chung"* —
14 khối code đọc 14 schema khác nhau đang tiến hoá theo 14 hướng, rút sớm sẽ đẻ ra helper nhận 5
tham số để phân biệt.

## Vì sao vẫn chọn

Canonical hoá 14 schema **trước khi** trả lời câu nào là đường dài hơn: nó là bước O5+O6 đầy đủ, và
`plan.md` §2.11 **[benchmark]** nói 81.2% lỗi text-to-SQL là schema-level — tức là bước map này
chính là chỗ dễ sai nhất. Làm nó cho 14 shop mà không có invariant checker (M2 chưa có) là sai im
lặng ở quy mô lớn.

Agent đọc trực tiếp thì sai vẫn sai, nhưng sai **cục bộ trong một shop**, không lan.

## Hệ quả cho production

ADR này **không** áp dụng cho pipeline production. Ở đó 4.000 câu trên 44 shop thì re-ingest mỗi câu
là không trả nổi (`plan.md` D2), nên canonical + parquet là bắt buộc. ADR này chỉ đúng cho một lần
sinh submission.
