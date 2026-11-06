# ADR 010: Tầng khái niệm và helper theo ngành

Trạng thái: Hoài đồng ý hướng ngày 2026-11-05, chờ duyệt chi tiết

## Bối cảnh

EXP-20261105-05 cho thấy 139 câu public không đúng có công thức rulebook khớp tham chiếu. EXP-20261105-06 cho thấy viết theo tên cột thì hỏng ở shop khác (`biz_118`), map theo mô tả README thì 10/10 khớp gold.

## Quyết định

1. **Helper ngành chỉ biết khái niệm.** `datamate_agent/concepts.py` dịch mô tả README sang khái niệm, dự phòng bằng tên cột đã biết, ghi `concepts.json` cạnh `mapping.json`.
2. **Helper tách theo ngành.** `datamate/domains/` gồm giao hàng, nhà thuốc, điện thoại, sửa xe, mẹ và bé, mỗi ngành một mixin của `Shop`.
3. **Bật theo khái niệm có mặt, không theo tên shop.** Thiếu khái niệm thì helper báo `shop has no`, prompt và ví dụ của ngành đó không xuất hiện.
4. **Ví dụ thêm tay nằm riêng** ở `prompts/library_curated.jsonl`, có trường `requires`, không bị ghi đè khi sinh lại thư viện.

## Pattern và đánh đổi

Semantic Layer tách nghĩa khỏi cách ghi của từng shop. Capability Detection bật tính năng theo dữ liệu có thật. Đánh đổi: bảng khái niệm giữ tay, thêm một lớp gián tiếp, và mixin khiến `Shop` có nhiều phương thức dù mỗi shop chỉ dùng một phần.

## Phương án đã loại

- Viết parser theo từng định dạng: hỏng ở định dạng mới.
- Để hết trong `shop.py`: file đã hơn 700 dòng, các ngành gần như độc lập.

## Đo sau khi áp dụng

EXP-20261105-07: public PA local 0.815 so với 0.528 cùng cách chấm, test 24 shop PA 0.915 so với 0.891. Chưa có điểm hệ thống. 3 ngành chỉ có ở public chưa kiểm được độc lập.
