# RULES — EXP-20261103-04

## Thay đổi so với parent

Đo trên đáp án thật của ban tổ chức thay vì tham chiếu Claude; train/split/test_* chỉ để đo, không sửa theo.
Môi trường: gộp cách viết tên hàng; is_revenue, year, month; bảng dòng hàng lấy status_norm, order_date từ bảng đơn; suy năm cho ngày `d/m` từ tên file; đổi cột order_total ≈ số lượng × đơn giá thành line_amount; bảng gộp tên `sales.csv`; calendar.csv và kỳ Tết trong sandbox và prompt.
Agent: conclude phải khai table, period_start, period_end, measure_column, aggregation; harness kiểm bảng và cột tồn tại, định dạng ngày, code cuối có dùng measure_column.

## Luật rulebook được code hoá

Tầng chuẩn hoá: §8 ô trống, dòng trùng trong đơn, sổ không có cột trạng thái, 4 trạng thái. Rulebook train chép nguyên văn vào prompt.

## Cố ý chưa làm

Công thức sẵn trong toolkit; đổi model; giữ riêng shop để đo shop chưa thấy (split này chia theo câu, nhưng tầng chuẩn hoá chưa từng sửa theo test_*).

## Quyết định tạm chưa thành ADR

Luật map rút từ public và train_*: Đã giao, Không giao được, Chưa giao, TT đơn, Bớt. Đối chứng dương ở logs/01-control.log chỉ dùng train_*.
Giá token như parent. Chạy tuần tự do 429.
